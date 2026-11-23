//! The order of a connection (design sections 4 and 5): the two adverts, the two challenges, the two responses, one
//! request, one reply; and `dial`.
use crate::admission::{Identity, Outcome, Verifier};
use crate::crypto::random_bytes;
use crate::etf::FRAME_MAX;
use crate::frames::{self, frame, read_any, read_body, Descriptor, Frame, ENTRIES_MAX};
use crate::tls::{Conn, ReadResult, TlsContext, ALPN};
use crate::Refused;
use std::net::{TcpStream, ToSocketAddrs};
use std::time::{Duration, Instant};

pub(crate) fn split_address(text: &str) -> Option<(String, u16)> {
    let i = text.rfind(':')?;
    let (host, port) = (&text[..i], &text[i + 1..]);
    if host.is_empty() {
        return None;
    }
    Some((host.to_string(), port.parse::<u16>().ok()?))
}

#[derive(Default)]
pub(crate) struct State {
    pub(crate) advert: Option<Descriptor>,
    pub(crate) typ: String,
}

pub(crate) fn end(conn: &mut Conn, what: &str, stage: &str, state: &State, reason: &str) -> Outcome {
    conn.close();
    let mut out = Outcome::new(what, stage, reason);
    out.advert = state.advert.clone();
    out.typ = state.typ.clone();
    out
}

pub(crate) fn end_read(conn: &mut Conn, result: ReadResult, stage: &str, state: &State) -> Outcome {
    match result {
        ReadResult::Oversize => end(conn, "refused", stage, state, "a frame above the ceiling"),
        ReadResult::Closed(why) => end(conn, "closed", stage, state, &why),
        ReadResult::Timeout => end(conn, "timeout", stage, state, ""),
        ReadResult::TlsFailed(why) => end(conn, "tls_failed", stage, state, &why),
        ReadResult::Frame(_) => end(conn, "closed", stage, state, ""),
    }
}

/// The next frame, which must be one of the kinds `want`; otherwise the Outcome that ended the connection (this side
/// then closes without a reply, design section 5).
fn read_frame(conn: &mut Conn, stage: &str, state: &State, want: &[&str], shuffle_length: usize) -> Result<Frame, Outcome> {
    let body = match conn.read() {
        ReadResult::Frame(body) => body,
        other => return Err(end_read(conn, other, stage, state)),
    };
    match read_body(&body, shuffle_length) {
        Ok(f) => {
            if !want.contains(&f.kind()) {
                let reason = format!("{} where {} was due", f.kind(), want.join(" or "));
                return Err(end(conn, "refused", stage, state, &reason));
            }
            Ok(f)
        }
        Err(why) => Err(end(conn, "refused", stage, state, &why.0)),
    }
}

/// After the handshake: the version, the group, the ALPN protocol and the peer's certificate (DER), with what tempus/1
/// requires of it.
pub(crate) fn tls_checks(conn: &Conn) -> Result<Vec<u8>, Refused> {
    if conn.version() != "TLSv1.3" {
        return Err(Refused::new("the TLS version is not 1.3"));
    }
    if conn.selected_alpn().as_deref() != Some(ALPN) {
        return Err(Refused::new("the ALPN protocol is not tempus/1"));
    }
    if conn.group().to_uppercase() != "X25519MLKEM768" {
        return Err(Refused::new("the key exchange group is not X25519MLKEM768"));
    }
    let der = conn.peer_certificate().and_then(|c| c.der()).ok_or_else(|| Refused::new("the peer presented no certificate"))?;
    crate::crypto::certificate_key(&der)?;
    Ok(der)
}

/// Admission, the same at both ends (design sections 4 and 5). Ok when both directions passed, else the Outcome.
pub(crate) fn admit(conn: &mut Conn, me: &Identity, addr: Option<&str>, verifier: &Verifier, nonce: Option<Vec<u8>>, cert_der: &[u8],
                    state: &mut State, shuffle_length: usize) -> Result<(), Outcome> {
    let internal = |conn: &mut Conn, state: &State, what: String| end(conn, "closed", "advert", state, &format!("internal error: {}", what));
    let nonce = match nonce.map(Ok).unwrap_or_else(|| random_bytes(32)) {
        Ok(n) => n,
        Err(e) => return Err(internal(conn, state, e.0)),
    };
    let mine = match me.advert(addr).and_then(|b| frame(&b)) {
        Ok(b) => b,
        Err(e) => return Err(internal(conn, state, e.0)),
    };
    conn.send(&mine);
    let theirs = match read_frame(conn, "advert", state, &["advert"], shuffle_length)? {
        Frame::Advert(d) => d,
        _ => return Err(end(conn, "refused", "advert", state, "")),
    };
    state.advert = Some(theirs.clone());
    match verifier.check_descriptor(&theirs, Some(cert_der)) {
        Ok(fields) => state.typ = fields.typ,
        Err(why) => {
            if why.0 == "key_rotated" {
                // the one exception to silence (ruling OQ-10): one frame. What the peer still sends is then read and
                // dropped until it closes or this connection's bound passes: closing with its bytes unread could
                // reset the connection and destroy the frame before the peer has read it
                if let Ok(b) = frames::key_rotated(&verifier.kid).and_then(|b| frame(&b)) {
                    conn.send(&b);
                    while let ReadResult::Frame(_) = conn.read() {}
                }
            }
            return Err(end(conn, "refused", "advert", state, &why.0));
        }
    }
    match frames::challenge(&nonce).and_then(|b| frame(&b)) {
        Ok(b) => conn.send(&b),
        Err(e) => return Err(internal(conn, state, e.0)),
    };
    let their_nonce = match read_frame(conn, "challenge", state, &["pop_challenge", "key_rotated"], shuffle_length)? {
        Frame::KeyRotated { kid } => {
            let mut o = end(conn, "key_rotated", "challenge", state, "");
            o.kid = Some(kid);
            return Err(o);
        }
        Frame::PopChallenge { nonce } => nonce,
        _ => return Err(end(conn, "refused", "challenge", state, "")),
    };
    match me.prove(&their_nonce).and_then(|sig| frames::response(&sig)).and_then(|b| frame(&b)) {
        Ok(b) => conn.send(&b),
        Err(e) => return Err(internal(conn, state, e.0)),
    };
    let sig = match read_frame(conn, "response", state, &["pop_response"], shuffle_length)? {
        Frame::PopResponse { sig } => sig,
        _ => return Err(end(conn, "refused", "response", state, "")),
    };
    if let Err(why) = verifier.check_proof(&theirs.public_key, &nonce, &theirs.token, &sig) {
        return Err(end(conn, "refused", "response", state, &why.0));
    }
    Ok(())
}

/// Every entry of a shuffle or sample frame must verify before any of them is used; one that does not refuses the frame.
pub(crate) fn check_entries(f: &Frame, verifier: &Verifier) -> Result<(), Refused> {
    if let (Some(store), Some(entries)) = (f.store(), f.entries()) {
        for e in entries {
            verifier.check_entry(e, store).map_err(|why| Refused(format!("an entry does not verify: {}", why.0)))?;
        }
    }
    Ok(())
}

/// What a reply must be to be the reply of `request` (writing-a-tempus-client.md section 8): a sample is answered by a
/// sample_reply for the same store with at most the `n` asked for; a shuffle by a shuffle_reply for the same store; a
/// call by a result with the call's req_id. A request this function does not know (bytes another program wrote) is
/// not judged.
pub fn check_reply(request: &[u8], reply: &Frame) -> Result<(), Refused> {
    let rq = match read_any(request, ENTRIES_MAX) {
        Ok(f) => f,
        Err(_) => return Ok(()),
    };
    let due = |kind: &str| Refused(format!("{} where {} was due", reply.kind(), kind));
    match &rq {
        Frame::Sample { store, n } => match reply {
            Frame::SampleReply { store: s, entries } => {
                if s != store {
                    return Err(Refused::new("the reply is for another store than the request"));
                }
                if entries.len() as i64 > *n {
                    return Err(Refused::new("more entries than the sample asked for"));
                }
                Ok(())
            }
            _ => Err(due("sample_reply")),
        },
        Frame::Shuffle { store, .. } => match reply {
            Frame::ShuffleReply { store: s, .. } => {
                if s != store {
                    return Err(Refused::new("the reply is for another store than the request"));
                }
                Ok(())
            }
            _ => Err(due("shuffle_reply")),
        },
        Frame::Other { kind, fields } if kind == "call" => match fields.get("req_id") {
            Some(crate::etf::Term::Binary(id)) => frames::result_value(reply, id).map(|_| ()),
            _ => Ok(()),
        },
        _ => Ok(()),
    }
}

/// What `dial` takes beside the peer, the identity and the verifier.
pub struct DialOptions {
    /// One bound for the whole connection. No default: the caller says.
    pub timeout: Duration,
    /// The 32-byte challenge; None takes it from the system's secure random source, which is what a client does.
    pub nonce: Option<Vec<u8>>,
    /// The shuffle length of the network this client joined.
    pub shuffle_length: usize,
    /// false leaves the entries of a reply unjudged; the caller must then check each with Verifier::check_entry.
    pub verify_entries: bool,
}

/// Connect to the TEMPUS peer at "host:port", be admitted, send ONE request body and read one reply.
///
/// `request` is a body from frames::shuffle, frames::sample or frames::call_frame. `identity.addr` is the listen
/// address this peer advertises. The reply is checked against its request (check_reply) and every entry of it is
/// verified before the outcome says "reply". When `request` is a cast, no reply comes: the outcome is "closed" at
/// stage "reply".
pub fn dial(addr: &str, identity: &Identity, verifier: &Verifier, request: &[u8], options: DialOptions) -> Outcome {
    let deadline = Instant::now() + options.timeout;
    let mut state = State::default();
    let unusable = || Outcome::new("unreachable", "tls", "the address, the identity or the request cannot be used");
    let (host, port) = match split_address(addr) {
        Some(x) => x,
        None => return unusable(),
    };
    if identity.addr.as_deref().and_then(split_address).is_none() || request.len() > FRAME_MAX {
        return unusable();
    }
    let context = match TlsContext::new(false, &identity.key, &identity.cert_der, "ed25519", true, false) {
        Ok(c) => c,
        Err(_) => return unusable(),
    };
    let target = match (host.as_str(), port).to_socket_addrs().ok().and_then(|mut a| a.next()) {
        Some(a) => a,
        None => return Outcome::new("unreachable", "tls", ""),
    };
    let stream = match TcpStream::connect_timeout(&target, options.timeout) {
        Ok(s) => s,
        Err(e) if e.kind() == std::io::ErrorKind::TimedOut => return Outcome::new("timeout", "tls", ""),
        Err(_) => return Outcome::new("unreachable", "tls", ""),
    };
    let mut conn = match Conn::new(&context, stream, false, deadline) {
        Ok(c) => c,
        Err(e) => return Outcome::new("tls_failed", "tls", &e.0),
    };
    if let Some(failed) = conn.handshake() {
        conn.close();
        return match failed {
            ReadResult::Timeout => Outcome::new("timeout", "tls", ""),
            ReadResult::TlsFailed(why) => Outcome::new("tls_failed", "tls", &why),
            _ => Outcome::new("tls_failed", "tls", "closed during the handshake"),
        };
    }
    let cert_der = match tls_checks(&conn) {
        Ok(der) => der,
        Err(why) => return end(&mut conn, "refused", "tls", &state, &why.0),
    };
    // In TLS 1.3 a dialer's handshake ends before the listener has judged the dialer's certificate: a listener's TLS
    // refusal shows as an alert on the first read, reported as tls_failed at "advert".
    if let Err(out) = admit(&mut conn, identity, None, verifier, options.nonce, &cert_der, &mut state, options.shuffle_length) {
        return out;
    }
    match frame(request) {
        Ok(b) => conn.send(&b),
        Err(_) => return end(&mut conn, "closed", "request", &state, "internal error"),
    };
    let body = match conn.read() {
        ReadResult::Frame(body) => body,
        other => return end_read(&mut conn, other, "reply", &state),
    };
    let judged = read_any(&body, options.shuffle_length).and_then(|f| {
        check_reply(request, &f)?;
        if options.verify_entries {
            check_entries(&f, verifier)?;
        }
        Ok(f)
    });
    let mut out = match judged {
        Ok(f) => {
            let mut out = end(&mut conn, "reply", "done", &state, "");
            out.frame = Some(f);
            out
        }
        Err(why) => end(&mut conn, "refused", "reply", &state, &why.0),
    };
    out.body = body;
    out
}
