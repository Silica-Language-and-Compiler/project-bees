//! Identities, the verifier (design section 4) and outcomes: what a client needs to be admitted by a peer and to
//! admit it.
use crate::crypto::{certificate_key, ed25519_verify, hex, sha512, SigningKey};
use crate::etf::Term;
use crate::frames::{self, check_descriptor, read_token, Descriptor, Entry, Frame, TokenFields, PEER_TYPES};
use crate::{Fault, Refused};
use std::collections::BTreeMap;
use std::sync::Arc;

/// One peer: its Ed25519 key, the certificate self-signed over that key (DER), its token exactly as the producer gave
/// it, and the listen address text "host:port" it advertises. The key is shared, never copied out.
#[derive(Clone)]
pub struct Identity {
    pub key: Arc<SigningKey>,
    pub token: Vec<u8>,
    pub addr: Option<String>,
    pub cert_der: Vec<u8>,
}

impl Identity {
    pub fn new(key: Arc<SigningKey>, token: Vec<u8>, addr: Option<String>, cert_der: Vec<u8>) -> Identity {
        Identity { key, token, addr, cert_der }
    }

    pub fn public_key(&self) -> &[u8] {
        self.key.public()
    }

    pub fn peer_id(&self) -> Vec<u8> {
        sha512(self.key.public())
    }

    /// This peer's descriptor, with `other` as its address when given.
    pub fn descriptor(&self, other: Option<&str>) -> Result<Descriptor, Fault> {
        let a = other.or(self.addr.as_deref())
            .ok_or_else(|| Fault::new("this identity has no listen address (design OQ-15: every node has one)"))?;
        Ok(Descriptor { id: self.peer_id(), public_key: self.public_key().to_vec(), addr: a.as_bytes().to_vec(), token: self.token.clone() })
    }

    pub fn advert(&self, other: Option<&str>) -> Result<Vec<u8>, Fault> {
        frames::advert(&self.descriptor(other)?)
    }

    pub fn entry(&self, age: i64) -> Result<Entry, Fault> {
        Ok(Entry { age, d: self.descriptor(None)? })
    }

    /// The proof of possession: this key's signature over the peer's nonce followed by this peer's own token.
    pub fn prove(&self, nonce: &[u8]) -> Result<Vec<u8>, Fault> {
        let mut message = nonce.to_vec();
        message.extend_from_slice(&self.token);
        self.key.sign(&message)
    }
}

/// What this peer needs to check another: the current producer key (32 raw bytes) and its kid, the clock in whole
/// seconds since 1970 (a function, so that the caller decides where the time comes from), the skew in seconds, the
/// token types it admits, and the `tempus` whitelist.
#[derive(Clone)]
pub struct Verifier {
    pub producer_key: Vec<u8>,
    pub kid: Vec<u8>,
    pub clock: Arc<dyn Fn() -> i64 + Send + Sync>,
    pub skew: i64,
    pub types: Vec<String>,
    /// The SHA-512 of the DER of every bridge and sentinel certificate this client accepts (design sections 4 and 9:
    /// a peer whose token says tempus_bridge or tempus_sentinel must present one of them, and a peer that presents one
    /// of them must have such a token). None: the rule is not applied.
    pub whitelist: Option<Vec<Vec<u8>>>,
}

impl Verifier {
    pub fn new(producer_key: Vec<u8>, kid: Vec<u8>, clock: Arc<dyn Fn() -> i64 + Send + Sync>, skew: i64, whitelist: Option<Vec<Vec<u8>>>) -> Verifier {
        Verifier { producer_key, kid, clock, skew, types: PEER_TYPES.iter().map(|s| s.to_string()).collect(), whitelist }
    }

    /// The token's fields when the descriptor verifies; Refused(reason) otherwise. The checks are made in the node's
    /// order: the field bounds; the channel binding, when `cert_der` is given (the certificate the peer presented in
    /// the TLS handshake: its key must be the descriptor's `pub`); the token's structure; the kid, with the reason
    /// "key_rotated" for a token under another one, whatever else is wrong with it (a signature under a key this
    /// verifier does not hold cannot be judged); the time window; `sub`; the whitelist rule in both directions, when a
    /// certificate and a whitelist are given; the id hash; the producer's signature. An entry of a reply has no
    /// connection, so it is checked without a certificate.
    pub fn check_descriptor(&self, d: &Descriptor, cert_der: Option<&[u8]>) -> Result<TokenFields, Refused> {
        check_descriptor(d)?;
        if let Some(der) = cert_der {
            if certificate_key(der)? != d.public_key {
                return Err(Refused::new("the certificate's key is not the advert's pub"));
            }
        }
        let token = read_token(&d.token)?;
        let fields = token.fields;
        let now = (self.clock)();
        if fields.kid != self.kid {
            return Err(Refused::new("key_rotated"));
        }
        if now < fields.nbf - self.skew {
            return Err(Refused::new("the token is not valid yet"));
        }
        if now >= fields.exp + self.skew {
            return Err(Refused::new("the token has expired"));
        }
        if fields.sub != d.public_key {
            return Err(Refused::new("sub is not the peer's key"));
        }
        if !self.types.contains(&fields.typ) {
            return Err(Refused::new("typ is not allowed"));
        }
        if let (Some(der), Some(list)) = (cert_der, &self.whitelist) {
            let listed = list.contains(&sha512(der));
            if fields.typ != "tempus_edge" && !listed {
                return Err(Refused(format!("the certificate of a {} is not in the whitelist", fields.typ)));
            }
            if fields.typ == "tempus_edge" && listed {
                return Err(Refused::new("a certificate of the whitelist with a token whose typ is tempus_edge"));
            }
        }
        if sha512(&d.public_key) != d.id {
            return Err(Refused::new("id is not the SHA-512 of pub"));
        }
        if !ed25519_verify(&self.producer_key, &token.payload, &token.sig) {
            return Err(Refused::new("the signature does not verify"));
        }
        Ok(fields)
    }

    /// An entry of a shuffle or sample frame for `store`: the descriptor verifies and its token's type is the store's.
    pub fn check_entry(&self, e: &Entry, store: &str) -> Result<(), Refused> {
        let fields = self.check_descriptor(&e.d, None)?;
        if fields.typ != store {
            return Err(Refused::new("the entry's typ is not the store's"));
        }
        Ok(())
    }

    pub fn check_proof(&self, public_key: &[u8], nonce: &[u8], token: &[u8], sig: &[u8]) -> Result<(), Refused> {
        let mut message = nonce.to_vec();
        message.extend_from_slice(token);
        if !ed25519_verify(public_key, &message, sig) {
            return Err(Refused::new("the proof of possession does not verify"));
        }
        Ok(())
    }
}

// ---------------------------------------------------------------- outcomes
fn show_term(t: &Term) -> String {
    match t {
        Term::Atom(s) => s.clone(),
        Term::Int(n) => n.to_string(),
        Term::Binary(b) => hex(b),
        Term::List(l) => format!("[{}]", l.iter().map(show_term).collect::<Vec<_>>().join(",")),
        Term::Map(m) => {
            if let Some(Term::Binary(id)) = m.get("id") {
                return hex(&id[..id.len().min(8)]);
            }
            format!("{{{}}}", m.iter().map(|(k, v)| format!("{}={}", k, show_term(v))).collect::<Vec<_>>().join(","))
        }
    }
}

fn show_descriptor(d: &Descriptor) -> String {
    hex(&d.id[..d.id.len().min(8)])
}

fn show_entries(entries: &[Entry]) -> String {
    format!("[{}]", entries.iter().map(|e| format!("{}:{}", e.age, show_descriptor(&e.d))).collect::<Vec<_>>().join(","))
}

/// The fields of a frame as `name=value` texts, in name order.
fn shown_fields(f: &Frame) -> Vec<String> {
    let mut m: BTreeMap<String, String> = BTreeMap::new();
    match f {
        Frame::Advert(d) => {
            m.insert("d".into(), show_descriptor(d));
        }
        Frame::PopChallenge { nonce } => {
            m.insert("nonce".into(), hex(nonce));
        }
        Frame::PopResponse { sig } => {
            m.insert("sig".into(), hex(sig));
        }
        Frame::KeyRotated { kid } => {
            m.insert("kid".into(), hex(kid));
        }
        Frame::Shuffle { store, entries } | Frame::ShuffleReply { store, entries } | Frame::SampleReply { store, entries } => {
            m.insert("store".into(), store.clone());
            m.insert("entries".into(), show_entries(entries));
        }
        Frame::Sample { store, n } => {
            m.insert("store".into(), store.clone());
            m.insert("n".into(), n.to_string());
        }
        Frame::Done => {}
        Frame::Other { fields, .. } => {
            for (k, v) in fields {
                m.insert(k.clone(), show_term(v));
            }
        }
    }
    m.into_iter().map(|(k, v)| format!("{}={}", k, v)).collect()
}

/// What happened on one connection, as plain values. Expected behaviour of a peer is never an error.
///
/// ```text
///     what   "reply"        dialing: a reply frame arrived (frame, body)
///            "served"       listening: the peer was admitted and its request read (frame, body); `sent` says what
///                           went back: "reply" or "close"
///            "key_rotated"  the peer answered this side's advert with key_rotated; `kid` is the kid it named
///            "refused"      THIS side refused the peer or its frame; `reason` says why ("key_rotated": this side
///                           sent the frame)
///            "closed"       the connection closed before the exchange was complete
///            "timeout"      nothing came within the time allowed
///            "tls_failed"   no tempus/1 TLS connection: the handshake failed, or a TLS alert came before any frame
///            "unreachable"  dialing: no TCP connection
///     stage  where it ended: "tls", "advert", "challenge", "response", "request", "reply", "done"
///     advert the peer's descriptor, once its advert was read (also when it was then refused)
///     typ    the type in the peer's token, once the advert verified
/// ```
#[derive(Debug, Clone)]
pub struct Outcome {
    pub what: String,
    pub stage: String,
    pub reason: String,
    pub frame: Option<Frame>,
    pub body: Vec<u8>,
    pub advert: Option<Descriptor>,
    pub typ: String,
    pub kid: Option<Vec<u8>>,
    pub sent: String,
}

impl Outcome {
    pub fn new(what: &str, stage: &str, reason: &str) -> Outcome {
        Outcome { what: what.into(), stage: stage.into(), reason: reason.into(), frame: None, body: Vec::new(), advert: None,
                  typ: String::new(), kid: None, sent: String::new() }
    }

    /// One deterministic line: nothing of the wall clock. It has the form of the other extensions' lines.
    pub fn line(&self) -> String {
        let mut parts = vec![self.what.clone()];
        if self.what != "reply" && self.what != "served" {
            parts.push(format!("at={}", self.stage));
        }
        if let Some(f) = &self.frame {
            parts.push(f.kind().to_string());
            parts.extend(shown_fields(f));
        }
        if !self.sent.is_empty() {
            parts.push(format!("sent={}", self.sent));
        }
        if let Some(kid) = &self.kid {
            parts.push(format!("kid={}", hex(kid)));
        }
        if let Some(d) = &self.advert {
            parts.push(format!("peer={}", show_descriptor(d)));
        }
        if !self.typ.is_empty() {
            parts.push(format!("typ={}", self.typ));
        }
        if !self.reason.is_empty() {
            parts.push(format!("reason=\"{}\"", self.reason));
        }
        parts.join(" ")
    }
}

/// The frame of a body that was read, as one line in the form of an Outcome's (for a tool that shows a frame).
pub fn frame_line(f: &Frame) -> String {
    let mut parts = vec![f.kind().to_string()];
    parts.extend(shown_fields(f));
    parts.join(" ")
}
