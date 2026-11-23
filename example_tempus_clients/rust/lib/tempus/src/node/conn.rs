//! One tempus/1 connection of a node (design sections 4, 5, 8 and 10), dialed or accepted: the same until the request.
//! The order, the checks, the audit events and their texts are those of src/tempus/dangerous_bees_tempus_conn.silica
//! and of the TLS link under it (src/tempus/dangerous_bees_tempus_tls.silica). Any violation closes with no reply (the
//! one exception is key_rotated) and writes one audit line. A connection runs on a thread of its own, with the values
//! of ConnValues, and blocks only on its own connection, which has ONE time bound from the dial or the accept to the
//! close (ruling NQ-14). It reaches the node only by sending messages to the node's thread.
use super::admit::{self, body_kind, read_frame};
use super::config::PeerType;
use super::{Answer, Msg, NodeEvent, Shared};
use crate::crypto::{hex, sha512};
use crate::frames::{self, frame, read_token, Descriptor, Frame, ENTRIES_MAX};
use crate::tls::{Conn, ReadResult, ALPN};
use std::net::{SocketAddr, TcpStream};
use std::sync::mpsc::{channel, Sender};
use std::sync::Arc;
use std::time::Instant;

/// What a connection works with: copied from the node when the connection was dialed or accepted.
pub(crate) struct ConnValues {
    pub(crate) cid: usize,
    pub(crate) dialed: bool,
    pub(crate) advert: Vec<u8>,
    pub(crate) token: Vec<u8>,
    pub(crate) kid: Vec<u8>,
    pub(crate) producer_key: Vec<u8>,
    pub(crate) now: i64,
    pub(crate) skew: i64,
    /// The most entries a frame may hold: the store's shuffle length when dialed, the greatest of the three when accepted.
    pub(crate) count: usize,
    /// When shuffle_timeout_ms has passed, on the machine's monotonic clock.
    pub(crate) deadline: Instant,
}

pub(crate) enum DialOutcome {
    /// The reply (None for a reply frame that is not of tempus/1's own kinds), the admitted peer and its token's type.
    Reply(Option<Frame>, Descriptor, String),
    /// The audit event that ended it, or connect_failed.
    Failed(String),
    KeyRotated(Vec<u8>),
}

pub(crate) struct NodeConn {
    shared: Arc<Shared>,
    tx: Sender<Msg>,
    v: ConnValues,
    conn: Option<Conn>,
    peer: Option<Descriptor>,
    cert_key: Vec<u8>,
    listed: Option<usize>,
    token_verified: bool,
    /// True while the node counts this accepted connection as served.
    counted: bool,
}

impl NodeConn {
    pub(crate) fn new(shared: Arc<Shared>, tx: Sender<Msg>, v: ConnValues) -> NodeConn {
        NodeConn { shared, tx, v, conn: None, peer: None, cert_key: Vec::new(), listed: None, token_verified: false, counted: false }
    }

    fn tag(&self) -> String {
        format!("{}{}", if self.v.dialed { "d" } else { "a" }, self.v.cid)
    }

    fn side(&self) -> &'static str {
        if self.v.dialed { "client" } else { "server" }
    }

    fn audit(&self, event: &str, what: &str) {
        let p = self.peer.as_ref().map(|d| hex(&d.id[..8])).unwrap_or_else(|| "-".to_string());
        self.shared.say(&format!("[tempus audit] {} peer={} {} {}", event, p, what, self.tag()));
    }

    /// The count of accepted connections in hand falls when the connection ends, before its close is complete.
    fn finish(&mut self) {
        if self.counted {
            self.counted = false;
            let _ = self.tx.send(Msg::ConnEnded);
        }
        if let Some(mut c) = self.conn.take() {
            c.close();
        }
    }

    /// A refusal that is the peer's doing: one audit line, the close, and for an accepted peer whose certificate key
    /// is known the node is told (ruling NQ-19).
    fn refuse(&mut self, event: &str, what: &str) -> DialOutcome {
        self.audit(event, what);
        self.finish();
        if !self.v.dialed && self.cert_key.len() == 32 {
            let _ = self.tx.send(Msg::Report(NodeEvent::PeerRefused { event: event.to_string(), peer_id: sha512(&self.cert_key),
                                                                     token_verified: self.token_verified }));
        }
        DialOutcome::Failed(event.to_string())
    }

    /// The next frame's body, or how the connection ended while it was waited for.
    fn next(&mut self, stage: &str) -> Result<Vec<u8>, DialOutcome> {
        let got = match self.conn.as_mut() {
            Some(c) => c.read(),
            None => ReadResult::Closed(String::new()),
        };
        match got {
            ReadResult::Frame(body) => Ok(body),
            ReadResult::Oversize => Err(self.refuse("protocol_error", "frame refused before decoding: too_large")),
            ReadResult::Timeout => Err(self.refuse("timeout", &format!("stage {}", stage))),
            ReadResult::Closed(_) | ReadResult::TlsFailed(_) => {
                self.audit("closed_by_peer", &format!("stage {}", stage));
                self.finish();
                Err(DialOutcome::Failed("closed_by_peer".into()))
            }
        }
    }

    fn send(&mut self, body: &[u8]) {
        if let (Some(c), Ok(b)) = (self.conn.as_mut(), frame(body)) {
            c.send(&b);
        }
    }

    fn internal(&mut self, what: &str) -> DialOutcome {
        self.audit("internal_error", what);
        self.finish();
        DialOutcome::Failed("internal_error".into())
    }

    // ---------------------------------------------------------------- TLS
    /// The handshake and what tempus/1 requires of it. False when the connection was refused (the line is written).
    fn handshake(&mut self, stream: TcpStream) -> bool {
        let context = if self.v.dialed { &self.shared.client_context } else { &self.shared.server_context };
        let mut c = match Conn::new(context, stream, !self.v.dialed, self.v.deadline) {
            Ok(c) => c,
            Err(_) => {
                self.finish();
                return false;
            }
        };
        let stop = c.handshake();
        let facts = (c.selected_alpn(), c.peer_certificate(), c.group(), c.version(), c.cipher());
        self.conn = Some(c);
        let side = self.side();
        let failed = |me: &mut NodeConn, event: &str, what: &str| -> bool {
            me.audit(event, &format!("{}, as {}", what, side));
            me.finish();
            false
        };
        const NO_ALPN: &str = "the peer did not agree on ALPN tempus/1";
        const NO_CERT: &str = "the peer presented no certificate";
        if let Some(stop) = stop {
            return match stop {
                ReadResult::Timeout => failed(self, "timeout", "stage tls_handshake"),
                ReadResult::TlsFailed(why) => {
                    // the listener's own refusal of the dialer's protocols (TlsContext, strict_alpn)
                    if why.contains("no application protocol") || why.contains("callback failed") {
                        failed(self, "alpn_mismatch", NO_ALPN)
                    } else if why.contains("peer did not return a certificate") {
                        failed(self, "tls_verify_failed", NO_CERT)
                    } else {
                        failed(self, "tls_handshake_failed", "the TLS 1.3 handshake failed (alert, version, group, suite or signature outside the tempus/1 profile)")
                    }
                }
                _ => failed(self, "closed_by_peer", "stage tls_handshake"),
            };
        }
        let (alpn, cert, group, version, cipher) = facts;
        if alpn.as_deref() != Some(ALPN) {
            return failed(self, "alpn_mismatch", NO_ALPN);
        }
        let cert = match cert {
            Some(c) => c,
            None => return failed(self, "tls_verify_failed", NO_CERT),
        };
        if group.to_uppercase() != "X25519MLKEM768" {
            return failed(self, "tls_group_refused", "the connection did not negotiate X25519MLKEM768, the only key exchange of the tempus/1 profile");
        }
        let (key, der) = match (cert.ed25519_key(), cert.der()) {
            (Some(k), Some(d)) => (k, d),
            _ => return failed(self, "tempus_cert_key", "the peer certificate's key is not Ed25519"),
        };
        self.cert_key = key;
        let print = sha512(&der);
        self.listed = self.shared.whitelist.iter().position(|w| *w == print);
        let suite = cipher.unwrap_or_else(|| "other-suite".to_string());
        self.audit("tls_established", &format!("{} X25519MLKEM768 {} alpn tempus/1, mutual, as {}", version, suite, side));
        true
    }

    // ---------------------------------------------------------------- admission, the same at both ends
    /// Ok when the peer is admitted; else how the connection ended.
    fn admit(&mut self) -> Result<(), DialOutcome> {
        let mine = self.v.advert.clone();
        self.send(&mine);
        let first = self.next("advert")?;
        if body_kind(&first).ok().as_deref() != Some("advert") {
            return Err(self.refuse("protocol_error", "the first frame is not an advert"));
        }
        let d = match read_frame(&first, self.v.count) {
            Ok(Frame::Advert(d)) => d,
            Ok(_) => return Err(self.refuse("protocol_error", "the first frame is not an advert")),
            Err(why) => return Err(self.refuse("protocol_error", &why)),
        };
        self.peer = Some(d.clone());
        // the channel binding: without it a node in the middle with its own certificate could relay an advert and its proof
        if d.public_key != self.cert_key {
            return Err(self.refuse("binding_refused", "the advert's pub is not the key of the peer's TLS certificate"));
        }
        let p = admit::pre(&d, &self.v.kid, self.v.now, self.v.skew, None);
        if p.why == admit::ROTATED {
            // the one exception to silence (ruling OQ-10). What the peer still sends is read and dropped until it closes
            // or the bound passes: closing with its bytes unread would reset the connection and could destroy the frame
            if let Ok(body) = frames::key_rotated(&self.v.kid) {
                self.send(&body);
            }
            self.audit("key_rotated", "the peer's token is under another kid; it was told the current one");
            while let Some(ReadResult::Frame(_)) = self.conn.as_mut().map(|c| c.read()) {}
            self.finish();
            return Err(DialOutcome::Failed("key_rotated_sent".into()));
        }
        if !p.why.is_empty() {
            return Err(self.refuse("admission_refused", &p.why));
        }
        let typ = p.fields.as_ref().map(|f| f.typ.clone()).unwrap_or_default();
        let wl = admit::whitelist(&typ, self.listed.is_some());
        if !wl.is_empty() {
            return Err(self.refuse("whitelist_reject", wl));
        }
        let keys = admit::keys(&d, &p.payload, &p.sig, &self.v.producer_key);
        if !keys.is_empty() {
            return Err(self.refuse("admission_refused", keys));
        }
        self.token_verified = true;
        let nonce = match self.shared.sources.random.nonce() {
            Some(n) if n.len() == 32 => n,
            _ => return Err(self.internal("random bytes refused")),
        };
        match frames::challenge(&nonce) {
            Ok(ch) => self.send(&ch),
            Err(_) => return Err(self.internal("random bytes refused")),
        }
        let second = self.next("challenge")?;
        match body_kind(&second).ok().as_deref() {
            Some("key_rotated") => {
                let named = match read_frame(&second, self.v.count) {
                    Ok(Frame::KeyRotated { kid }) => kid,
                    Ok(_) => return Err(self.refuse("protocol_error", "a challenge was expected")),
                    Err(why) => return Err(self.refuse("protocol_error", &why)),
                };
                self.audit("key_rotated", "the peer says this node's token is under another kid than its current one");
                self.finish();
                if !self.v.dialed {
                    let _ = self.tx.send(Msg::Report(NodeEvent::KeyRotated { kid: named.clone(), dialed: false }));
                }
                return Err(DialOutcome::KeyRotated(named));
            }
            Some("pop_challenge") => {
                let theirs = match read_frame(&second, self.v.count) {
                    Ok(Frame::PopChallenge { nonce }) => nonce,
                    Ok(_) => return Err(self.refuse("protocol_error", "a challenge was expected")),
                    Err(why) => return Err(self.refuse("protocol_error", &why)),
                };
                let mut message = theirs;
                message.extend_from_slice(&self.v.token);
                match self.shared.key.sign(&message).and_then(|sig| frames::response(&sig)) {
                    Ok(body) => self.send(&body),
                    Err(_) => return Err(self.internal("the signature could not be made")),
                }
            }
            _ => return Err(self.refuse("protocol_error", "a challenge was expected")),
        }
        let third = self.next("response")?;
        if body_kind(&third).ok().as_deref() != Some("pop_response") {
            return Err(self.refuse("pop_failed", "a response was expected"));
        }
        let sig = match read_frame(&third, self.v.count) {
            Ok(Frame::PopResponse { sig }) => sig,
            Ok(_) => return Err(self.refuse("pop_failed", "a response was expected")),
            Err(why) => return Err(self.refuse("pop_failed", &why)),
        };
        if !admit::proof(&d.public_key, &nonce, &d.token, &sig) {
            return Err(self.refuse("pop_failed", "the proof of possession does not verify"));
        }
        let how = match self.listed {
            Some(k) => format!(", tempus whitelist entry {}", k),
            None => ", token and proof of possession".to_string(),
        };
        self.audit("admitted", &format!("{}{}", typ, how));
        Ok(())
    }

    /// Every entry of a received frame is verified without contact before the node sees the frame (ruling OQ-4): one
    /// that does not verify refuses the whole frame.
    fn entries(&mut self, body: &[u8]) -> Result<Frame, DialOutcome> {
        let f = match read_frame(body, self.v.count) {
            Ok(f) => f,
            Err(why) => return Err(self.refuse("protocol_error", &why)),
        };
        let store = f.store().and_then(PeerType::from_name);
        let list: Vec<Descriptor> = f.entries().map(|l| l.iter().map(|e| e.d.clone()).collect()).unwrap_or_default();
        for (k, d) in list.iter().enumerate() {
            let why = admit::entry(d, &self.v.kid, &self.v.producer_key, self.v.now, self.v.skew, store);
            if !why.is_empty() {
                return Err(self.refuse("entry_refused", &format!("entry {}: {}", k, why)));
            }
        }
        Ok(f)
    }

    // ---------------------------------------------------------------- an accepted connection
    /// `close_with`: the audit event with which the connection is closed at once after its handshake (the node is at
    /// inflight_max, waits for its clock, or has stopped). Otherwise the node counts the connection as served.
    pub(crate) fn accepted(mut self, stream: TcpStream, close_with: Option<&'static str>) {
        self.counted = close_with.is_none();
        if !self.handshake(stream) {
            return;
        }
        if let Some(event) = close_with {
            let what = match event {
                "inflight_refused" => "more accepted connections than inflight_max: closed at once",
                "clock_refused" => "the system clock cannot be read: closed at once",
                _ => "the node stopped after its system clock went back: closed at once",
            };
            self.audit(event, what);
            self.finish();
            return;
        }
        if self.admit().is_err() {
            return;
        }
        let body = match self.next("request") {
            Ok(b) => b,
            Err(_) => return,
        };
        let d = match self.peer.clone() {
            Some(d) => d,
            None => return self.finish(),
        };
        let typ = read_token(&d.token).map(|t| t.fields.typ).unwrap_or_default();
        let kind = body_kind(&body);
        let request = match kind.as_deref() {
            Ok("shuffle") => match self.entries(&body) {
                Ok(f) => Some(f),
                Err(_) => return,
            },
            Ok("sample") => match read_frame(&body, ENTRIES_MAX) {
                Ok(f) => Some(f),
                Err(why) => {
                    self.refuse("protocol_error", &why);
                    return;
                }
            },
            Ok("call") | Ok("cast") => None,
            other => {
                // a frame of no request kind: the test-only tick and clock frames are refused here like any other
                let why = match other {
                    Err(why) => why.clone(),
                    Ok(_) => "unknown kind".to_string(),
                };
                self.refuse("protocol_error", &format!("not a request: {}", why));
                return;
            }
        };
        let (reply_tx, reply_rx) = channel();
        let asked = self.tx.send(Msg::Request { frame: request, peer: d, typ, cid: self.v.cid, reply: reply_tx });
        if asked.is_ok() {
            if let Ok(Answer::Reply(reply)) = reply_rx.recv() {
                self.send(&reply);
            }
        }
        self.finish();
    }

    // ---------------------------------------------------------------- a dialed connection
    pub(crate) fn dial(mut self, addr: &str, request: &[u8]) -> DialOutcome {
        let failed = || DialOutcome::Failed("connect_failed".into());
        let target: SocketAddr = match addr.parse() {
            Ok(a) => a,
            Err(_) => return failed(),
        };
        let left = self.v.deadline.saturating_duration_since(Instant::now());
        if left.is_zero() {
            return failed();
        }
        let stream = match TcpStream::connect_timeout(&target, left) {
            Ok(s) => s,
            Err(_) => return failed(),
        };
        if !self.handshake(stream) {
            return failed();
        }
        if let Err(ended) = self.admit() {
            return ended;
        }
        let d = match self.peer.clone() {
            Some(d) => d,
            None => return DialOutcome::Failed("closed".into()),
        };
        let typ = read_token(&d.token).map(|t| t.fields.typ).unwrap_or_default();
        self.send(request);
        let body = match self.next("reply") {
            Ok(b) => b,
            Err(how) => return how,
        };
        match body_kind(&body).ok().as_deref() {
            Some("shuffle_reply") | Some("sample_reply") => match self.entries(&body) {
                Ok(f) => {
                    self.finish();
                    DialOutcome::Reply(Some(f), d, typ)
                }
                Err(refused) => refused,
            },
            Some("done") | Some("result") => {
                self.finish();
                DialOutcome::Reply(None, d, typ)
            }
            _ => self.refuse("protocol_error", "the reply is not a reply frame"),
        }
    }
}
