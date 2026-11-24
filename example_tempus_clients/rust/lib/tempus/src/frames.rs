//! The tempus/1 frame bodies (design section 5), with every bound of design section 8, and the token (design
//! section 4). The test-only tick and clock frames of src/tempus_test are not here: they are no part of an extension,
//! and this reader refuses both as it refuses any frame of no kind.
use crate::etf::{be32, etf_decode, etf_decode_within, etf_encode, Term, FRAME_MAX};
use crate::{Fault, Refused};
use std::collections::BTreeMap;

pub const PEER_TYPES: [&str; 3] = ["tempus_edge", "tempus_bridge", "tempus_sentinel"];
/// The kinds this extension reads as tempus/1 frames.
pub const KINDS: [&str; 9] = ["advert", "pop_challenge", "pop_response", "key_rotated", "shuffle", "shuffle_reply", "sample",
                              "sample_reply", "done"];
pub const AGE_MAX: i64 = 65535;
/// The literal ceiling of entries in one frame.
pub const ENTRIES_MAX: usize = 64;

/// The record that describes one peer.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Descriptor {
    pub id: Vec<u8>,
    pub public_key: Vec<u8>,
    pub addr: Vec<u8>,
    pub token: Vec<u8>,
}

impl Descriptor {
    pub fn term(&self) -> Term {
        Term::map(vec![("id", Term::binary(&self.id)), ("pub", Term::binary(&self.public_key)), ("addr", Term::binary(&self.addr)),
                       ("token", Term::binary(&self.token))])
    }
}

/// One entry of a shuffle or sample frame.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Entry {
    pub age: i64,
    pub d: Descriptor,
}

impl Entry {
    fn term(&self) -> Term {
        Term::map(vec![("age", Term::Int(self.age)), ("d", self.d.term())])
    }
}

/// A body as this extension read it.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Frame {
    Advert(Descriptor),
    PopChallenge { nonce: Vec<u8> },
    PopResponse { sig: Vec<u8> },
    KeyRotated { kid: Vec<u8> },
    Shuffle { store: String, entries: Vec<Entry> },
    ShuffleReply { store: String, entries: Vec<Entry> },
    Sample { store: String, n: i64 },
    SampleReply { store: String, entries: Vec<Entry> },
    Done,
    /// A map whose `t` is no tempus/1 kind (TRUST's call, cast and result), with its other fields as decoded, unchecked.
    Other { kind: String, fields: BTreeMap<String, Term> },
}

impl Frame {
    pub fn kind(&self) -> &str {
        match self {
            Frame::Advert(_) => "advert",
            Frame::PopChallenge { .. } => "pop_challenge",
            Frame::PopResponse { .. } => "pop_response",
            Frame::KeyRotated { .. } => "key_rotated",
            Frame::Shuffle { .. } => "shuffle",
            Frame::ShuffleReply { .. } => "shuffle_reply",
            Frame::Sample { .. } => "sample",
            Frame::SampleReply { .. } => "sample_reply",
            Frame::Done => "done",
            Frame::Other { kind, .. } => kind,
        }
    }

    pub fn store(&self) -> Option<&str> {
        match self {
            Frame::Shuffle { store, .. } | Frame::ShuffleReply { store, .. } | Frame::SampleReply { store, .. }
            | Frame::Sample { store, .. } => Some(store),
            _ => None,
        }
    }

    pub fn entries(&self) -> Option<&[Entry]> {
        match self {
            Frame::Shuffle { entries, .. } | Frame::ShuffleReply { entries, .. } | Frame::SampleReply { entries, .. } => Some(entries),
            _ => None,
        }
    }
}

// ---------------------------------------------------------------- checks shared by the readers
fn check_keys<'a>(t: &'a Term, keys: &[&str], what: &str) -> Result<&'a BTreeMap<String, Term>, Refused> {
    let m = match t {
        Term::Map(m) => m,
        _ => return Err(Refused(format!("{} is not a map", what))),
    };
    if m.keys().any(|k| !keys.contains(&k.as_str())) {
        return Err(Refused::new("unknown_field"));
    }
    if keys.iter().any(|k| !m.contains_key(*k)) {
        return Err(Refused::new("missing_field"));
    }
    Ok(m)
}

fn bin(m: &BTreeMap<String, Term>, key: &str, lo: usize, hi: usize, text: &str) -> Result<Vec<u8>, Refused> {
    match m.get(key) {
        Some(Term::Binary(v)) if v.len() >= lo && v.len() <= hi => Ok(v.clone()),
        _ => Err(Refused::new(text)),
    }
}

fn read_descriptor(t: &Term) -> Result<Descriptor, Refused> {
    let m = check_keys(t, &["id", "pub", "addr", "token"], "descriptor")?;
    Ok(Descriptor {
        id: bin(m, "id", 64, 64, "id is not 64 bytes")?,
        public_key: bin(m, "pub", 32, 32, "pub is not 32 bytes")?,
        addr: bin(m, "addr", 3, 261, "addr is not 3 to 261 bytes")?,
        token: bin(m, "token", 65, 1024, "token is not 65 to 1024 bytes")?,
    })
}

/// The field bounds of a descriptor held as a value (one built by the caller, or one read from a frame).
pub fn check_descriptor(d: &Descriptor) -> Result<(), Refused> {
    read_descriptor(&d.term()).map(|_| ())
}

// ---------------------------------------------------------------- the token
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TokenFields {
    pub kid: Vec<u8>,
    pub sub: Vec<u8>,
    pub typ: String,
    pub nbf: i64,
    pub exp: i64,
}

/// A token as read: its fields, the payload bytes the producer signed, and the signature.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Token {
    pub fields: TokenFields,
    pub payload: Vec<u8>,
    pub sig: Vec<u8>,
}

/// The bytes a producer signs: the ETF map of the five fields, times in whole seconds. An extension never signs a
/// token; this is here because a verifier and a test both need the one byte form.
pub fn token_payload(kid: &[u8], sub: &[u8], typ: &str, nbf: i64, exp: i64) -> Result<Vec<u8>, Fault> {
    etf_encode(&Term::map(vec![("kid", Term::binary(kid)), ("sub", Term::binary(sub)), ("typ", Term::atom(typ)),
                               ("nbf", Term::Int(nbf)), ("exp", Term::Int(exp))]))
}

/// The structure and bounds of a token. The signature is NOT verified here.
pub fn read_token(token: &[u8]) -> Result<Token, Refused> {
    if token.len() < 65 || token.len() > 1024 {
        return Err(Refused::new("token is not 65 to 1024 bytes"));
    }
    let (sig, payload) = token.split_at(64);
    let t = etf_decode_within(payload, 2, FRAME_MAX)?;
    match &t {
        Term::Map(five) if five.len() == 5 => {}
        _ => return Err(Refused::new("the token is not a map of five keys")),
    }
    let m = check_keys(&t, &["kid", "sub", "typ", "nbf", "exp"], "token")?;
    let kid = bin(m, "kid", 1, 64, "kid is not 1 to 64 bytes")?;
    let sub = bin(m, "sub", 32, 32, "sub is not 32 bytes")?;
    let typ = match m.get("typ") {
        Some(Term::Atom(typ)) if PEER_TYPES.contains(&typ.as_str()) => typ.clone(),
        _ => return Err(Refused::new("typ is not a peer type")),
    };
    let (nbf, exp) = match (m.get("nbf"), m.get("exp")) {
        (Some(Term::Int(nbf)), Some(Term::Int(exp))) if *nbf >= 0 && *exp >= 0 => (*nbf, *exp),
        _ => return Err(Refused::new("nbf or exp is not a time")),
    };
    if exp <= nbf {
        return Err(Refused::new("exp is not after nbf"));
    }
    Ok(Token { fields: TokenFields { kid, sub, typ, nbf, exp }, payload: payload.to_vec(), sig: sig.to_vec() })
}

// ---------------------------------------------------------------- writing frame bodies
fn typ(store: &str) -> Result<Term, Fault> {
    if !PEER_TYPES.contains(&store) {
        return Err(Fault(format!("store is one of {:?}", PEER_TYPES)));
    }
    Ok(Term::atom(store))
}

pub fn advert(d: &Descriptor) -> Result<Vec<u8>, Fault> {
    etf_encode(&Term::map(vec![("t", Term::atom("advert")), ("ver", Term::Int(1)), ("d", d.term())]))
}

pub fn challenge(nonce: &[u8]) -> Result<Vec<u8>, Fault> {
    etf_encode(&Term::map(vec![("t", Term::atom("pop_challenge")), ("nonce", Term::binary(nonce))]))
}

pub fn response(sig: &[u8]) -> Result<Vec<u8>, Fault> {
    etf_encode(&Term::map(vec![("t", Term::atom("pop_response")), ("sig", Term::binary(sig))]))
}

pub fn key_rotated(kid: &[u8]) -> Result<Vec<u8>, Fault> {
    etf_encode(&Term::map(vec![("t", Term::atom("key_rotated")), ("kid", Term::binary(kid))]))
}

fn entries_body(kind: &str, store: &str, entries: &[Entry]) -> Result<Vec<u8>, Fault> {
    etf_encode(&Term::map(vec![("t", Term::atom(kind)), ("store", typ(store)?),
                               ("entries", Term::List(entries.iter().map(|e| e.term()).collect()))]))
}

pub fn shuffle(store: &str, entries: &[Entry]) -> Result<Vec<u8>, Fault> {
    entries_body("shuffle", store, entries)
}

pub fn shuffle_reply(store: &str, entries: &[Entry]) -> Result<Vec<u8>, Fault> {
    entries_body("shuffle_reply", store, entries)
}

pub fn sample_reply(store: &str, entries: &[Entry]) -> Result<Vec<u8>, Fault> {
    entries_body("sample_reply", store, entries)
}

pub fn sample(store: &str, n: i64) -> Result<Vec<u8>, Fault> {
    etf_encode(&Term::map(vec![("t", Term::atom("sample")), ("store", typ(store)?), ("n", Term::Int(n))]))
}

pub fn done() -> Result<Vec<u8>, Fault> {
    etf_encode(&Term::map(vec![("t", Term::atom("done"))]))
}

/// TRUST's request frame as a bridge reads it (design 17.4): `kind` is "call" or "cast"; `args` is a list of integers
/// (this extension's ETF subset has no tuples and no floats). A `call` is answered with a `result` frame carrying the
/// same `req_id`; a `cast` is never answered.
pub fn call_frame(kind: &str, req_id: &[u8], module: &str, function: &str, args: &[i64]) -> Result<Vec<u8>, Fault> {
    if kind != "call" && kind != "cast" {
        return Err(Fault::new("a request to a bridge is a call or a cast"));
    }
    if req_id.is_empty() || req_id.len() > 16 {
        return Err(Fault::new("req_id is 1 to 16 bytes"));
    }
    etf_encode(&Term::map(vec![("t", Term::atom(kind)), ("ver", Term::Int(1)), ("req_id", Term::binary(req_id)),
                               ("m", Term::atom(module)), ("f", Term::atom(function)), ("a", Term::Int(args.len() as i64)),
                               ("args", Term::List(args.iter().map(|n| Term::Int(*n)).collect())), ("opts", Term::Map(BTreeMap::new()))]))
}

/// The body with its 4-byte length, most significant byte first, as it travels.
pub fn frame(body: &[u8]) -> Result<Vec<u8>, Fault> {
    if body.len() > FRAME_MAX {
        return Err(Fault::new("body above the frame ceiling"));
    }
    let mut out = be32(body.len()).to_vec();
    out.extend_from_slice(body);
    Ok(out)
}

// ---------------------------------------------------------------- reading frame bodies
fn store_of(m: &BTreeMap<String, Term>) -> Result<String, Refused> {
    match m.get("store") {
        Some(Term::Atom(store)) if PEER_TYPES.contains(&store.as_str()) => Ok(store.clone()),
        _ => Err(Refused::new("store is not a peer type")),
    }
}

/// A body as a Frame, every bound of design section 8 checked. `shuffle_length` is the value of the network this
/// peer joined; a peer cannot ask a node for it.
pub fn read_body(body: &[u8], shuffle_length: usize) -> Result<Frame, Refused> {
    let t = etf_decode(body)?;
    let top = match &t {
        Term::Map(top) => top,
        _ => return Err(Refused::new("bad_tag")),
    };
    let kind = match top.get("t") {
        Some(Term::Atom(kind)) if KINDS.contains(&kind.as_str()) => kind.as_str(),
        _ => return Err(Refused::new("unknown kind")),
    };
    match kind {
        "advert" => {
            let m = check_keys(&t, &["t", "ver", "d"], kind)?;
            if m.get("ver") != Some(&Term::Int(1)) {
                return Err(Refused::new("ver is not 1"));
            }
            Ok(Frame::Advert(read_descriptor(&m["d"])?))
        }
        "pop_challenge" => {
            let m = check_keys(&t, &["t", "nonce"], kind)?;
            Ok(Frame::PopChallenge { nonce: bin(m, "nonce", 32, 32, "nonce is not 32 bytes")? })
        }
        "pop_response" => {
            let m = check_keys(&t, &["t", "sig"], kind)?;
            Ok(Frame::PopResponse { sig: bin(m, "sig", 64, 64, "sig is not 64 bytes")? })
        }
        "key_rotated" => {
            let m = check_keys(&t, &["t", "kid"], kind)?;
            Ok(Frame::KeyRotated { kid: bin(m, "kid", 1, 64, "kid is not 1 to 64 bytes")? })
        }
        "shuffle" | "shuffle_reply" | "sample_reply" => {
            let m = check_keys(&t, &["t", "store", "entries"], kind)?;
            let store = store_of(m)?;
            let items = match m.get("entries") {
                Some(Term::List(items)) => items,
                _ => return Err(Refused::new("entries is not a list")),
            };
            if items.len() > ENTRIES_MAX || items.len() > shuffle_length {
                return Err(Refused::new("more entries than the shuffle length"));
            }
            let mut entries = Vec::with_capacity(items.len());
            for item in items {
                let e = check_keys(item, &["age", "d"], "entry")?;
                let age = match e.get("age") {
                    Some(Term::Int(age)) if *age >= 0 && *age <= AGE_MAX => *age,
                    _ => return Err(Refused::new("age is not 0 to 65535")),
                };
                entries.push(Entry { age, d: read_descriptor(&e["d"])? });
            }
            Ok(match kind {
                "shuffle" => Frame::Shuffle { store, entries },
                "shuffle_reply" => Frame::ShuffleReply { store, entries },
                _ => Frame::SampleReply { store, entries },
            })
        }
        "sample" => {
            let m = check_keys(&t, &["t", "store", "n"], kind)?;
            let store = store_of(m)?;
            match m.get("n") {
                Some(Term::Int(n)) if *n >= 1 && *n <= shuffle_length as i64 => Ok(Frame::Sample { store, n: *n }),
                _ => Err(Refused::new("n is not 1 to the shuffle length")),
            }
        }
        _ => {
            check_keys(&t, &["t"], kind)?;
            Ok(Frame::Done)
        }
    }
}

/// Any body: a tempus/1 frame by read_body; a map whose `t` is an atom that is no tempus/1 kind (TRUST's result, call,
/// cast) with its fields as decoded, unchecked; otherwise Refused with read_body's reason. A TRUST frame that carries
/// a tuple or a float cannot be decoded by this extension's subset and is refused; its bytes are still in the Outcome.
pub fn read_any(body: &[u8], shuffle_length: usize) -> Result<Frame, Refused> {
    match read_body(body, shuffle_length) {
        Ok(f) => Ok(f),
        Err(first) => {
            if let Ok(Term::Map(mut m)) = etf_decode(body) {
                if let Some(Term::Atom(kind)) = m.get("t").cloned() {
                    if !KINDS.contains(&kind.as_str()) {
                        m.remove("t");
                        return Ok(Frame::Other { kind, fields: m });
                    }
                }
            }
            Err(first)
        }
    }
}

/// What a `result` frame must be to be the reply of the call with this `req_id` (writing-a-tempus-client.md section 8):
/// the kind `result`, `ver` 1, the same `req_id`, and a `value`. The value when it is.
pub fn result_value<'a>(f: &'a Frame, req_id: &[u8]) -> Result<&'a Term, Refused> {
    match f {
        Frame::Other { kind, fields } if kind == "result" => {
            if fields.keys().any(|k| !["ver", "req_id", "value"].contains(&k.as_str())) {
                return Err(Refused::new("unknown_field"));
            }
            if fields.get("ver") != Some(&Term::Int(1)) {
                return Err(Refused::new("ver is not 1"));
            }
            if fields.get("req_id") != Some(&Term::Binary(req_id.to_vec())) {
                return Err(Refused::new("the result is not for this call's req_id"));
            }
            fields.get("value").ok_or_else(|| Refused::new("missing_field"))
        }
        other => Err(Refused(format!("{} where result was due", other.kind()))),
    }
}
