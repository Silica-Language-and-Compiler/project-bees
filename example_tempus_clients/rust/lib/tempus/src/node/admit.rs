//! Admission as the node judges it (design section 4), with the order and the reason texts of
//! src/tempus/bees_tempus_admit.silica and of the connection actor (src/tempus/dangerous_bees_tempus_conn.silica), so
//! that a node of this extension and a Silica node write the same audit line for the same refusal.
use super::config::PeerType;
use crate::crypto::{ed25519_verify, sha512};
use crate::etf::{etf_decode, Term};
use crate::frames::{read_body, read_token, Descriptor, Frame, TokenFields};

pub const ROTATED: &str = "key_rotated";

/// What `pre` found: `why` is "" when every check passed.
pub struct Pre {
    pub why: String,
    pub fields: Option<TokenFields>,
    pub payload: Vec<u8>,
    pub sig: Vec<u8>,
}

/// The checks that need no key operation, in the node's order: the descriptor's lengths, the token's structure,
/// the kid (a token under another kid is "key_rotated" whatever else is wrong with it), the window
/// nbf - skew <= now < exp + skew, sub, and, when `want` is given, the token's type.
pub fn pre(d: &Descriptor, kid: &[u8], now: i64, skew: i64, want: Option<PeerType>) -> Pre {
    let no = |why: &str, fields: Option<TokenFields>| Pre { why: why.to_string(), fields, payload: Vec::new(), sig: Vec::new() };
    if d.id.len() != 64 || d.public_key.len() != 32 || d.addr.len() < 3 || d.addr.len() > 261 || d.token.len() < 65 || d.token.len() > 1024 {
        return no("a field of the descriptor has a wrong length", None);
    }
    let t = match read_token(&d.token) {
        Ok(t) => t,
        Err(why) => return no(&why.0, None),
    };
    let f = t.fields.clone();
    if f.kid != kid {
        return no(ROTATED, Some(f));
    }
    if now < f.nbf - skew {
        return no("the token is not valid yet", Some(f));
    }
    if now >= f.exp + skew {
        return no("the token has expired", Some(f));
    }
    if f.sub != d.public_key {
        return no("sub is not the peer's key", Some(f));
    }
    if let Some(w) = want {
        if f.typ != w.name() {
            return no("typ is not the store's type", Some(f));
        }
    }
    Pre { why: String::new(), fields: Some(f), payload: t.payload, sig: t.sig }
}

/// The two key operations that follow pre(): the id is the SHA-512 of pub, and the producer's signature over the
/// token's payload as received. "" when both pass.
pub fn keys(d: &Descriptor, payload: &[u8], sig: &[u8], producer_key: &[u8]) -> &'static str {
    if sha512(&d.public_key) != d.id {
        return "id is not the SHA-512 of pub";
    }
    if !ed25519_verify(producer_key, payload, sig) {
        return "the signature does not verify";
    }
    ""
}

/// A descriptor admitted to a store without contact (an entry of a shuffle or sample frame; ruling OQ-4). "" when it is.
pub fn entry(d: &Descriptor, kid: &[u8], producer_key: &[u8], now: i64, skew: i64, want: Option<PeerType>) -> String {
    let p = pre(d, kid, now, skew, want);
    if p.why.is_empty() { keys(d, &p.payload, &p.sig, producer_key).to_string() } else { p.why }
}

/// The whitelist rule (rulings OQ-3, NQ-4), both sides: `listed` says whether the peer's certificate is in the
/// tempus whitelist. "" when it holds.
pub fn whitelist(typ: &str, listed: bool) -> &'static str {
    if typ == PeerType::Edge.name() {
        return if listed { "a certificate of the tempus whitelist with a token whose typ is not tempus_bridge or tempus_sentinel" } else { "" };
    }
    if listed { "" } else { "a tempus_bridge or tempus_sentinel token under a certificate that is not in the tempus whitelist" }
}

/// True when `sig` is the peer's signature over nonce || token.
pub fn proof(public_key: &[u8], nonce: &[u8], token: &[u8], sig: &[u8]) -> bool {
    let mut message = nonce.to_vec();
    message.extend_from_slice(token);
    ed25519_verify(public_key, &message, sig)
}

// ---------------------------------------------------------------- what a body is, as the node's connection reads it
const REQUEST_KINDS: [&str; 12] = ["advert", "pop_challenge", "pop_response", "key_rotated", "shuffle", "shuffle_reply", "sample",
                                   "sample_reply", "done", "call", "cast", "result"];
/// Every atom a production BEES node holds: the lines of src/tempus/bees_tempus.atoms and of src/trust/bees_trust.atoms
/// (the frame keys and kinds, the peer types, the language's rejection atoms and the results of a TRUST call). A body
/// that names any other atom is refused as `unknown_atom` before its kind is looked at, which is what a Silica node
/// says of the test-only tick and clock frames, and of a call that names a module it holds no atom for. The tests
/// read the two files and require this list to be their union.
pub const WIRE_ATOMS: [&str; 68] = [
    "a", "addr", "advert", "age", "args", "bad_tag", "bad_variant", "bad_version", "call", "cast", "closed", "connect_failed", "d", "deadline_ms",
    "dns_error", "done", "duplicate_field", "entries", "erlang", "error", "exp", "f", "goaway", "hello", "id", "key_rotated", "kid", "m",
    "missing_field", "n", "nbf", "nonce", "ok", "opts", "out_of_range", "pop_challenge", "pop_response", "protocol_error", "pub", "req_id", "result",
    "sample", "sample_reply", "server_not_pinned", "shuffle", "shuffle_reply", "sig", "store", "sub", "t", "tempus_bridge", "tempus_edge",
    "tempus_sentinel", "timeout", "token", "token_issue", "token_present", "too_deep", "too_large", "too_long", "trailing_bytes", "truncated", "typ",
    "unknown_atom", "unknown_field", "unsupported", "value", "ver"];

fn known(a: &str) -> bool {
    WIRE_ATOMS.contains(&a)
}

fn unknown_atom(t: &Term) -> bool {
    match t {
        Term::Atom(a) => !known(a),
        Term::List(l) => l.iter().any(unknown_atom),
        Term::Map(m) => m.iter().any(|(k, v)| !known(k) || unknown_atom(v)),
        _ => false,
    }
}

/// The kind of a body (the atom of its `t`), or the reason its structure is refused or its `t` is no kind: the
/// reason is the decoder's word, or "unknown kind" for a well-formed map.
pub fn body_kind(body: &[u8]) -> Result<String, String> {
    if !body.is_empty() && body[0] != 131 {
        return Err("bad_version".into());
    }
    if body.len() < 6 {
        return Err("truncated".into());
    }
    if body[1] != 116 {
        return Err("bad_tag".into());
    }
    if body[2] != 0 || body[3] != 0 || body[4] != 0 || body[5] > 16 {
        return Err("too_long".into());
    }
    let t = etf_decode(body).map_err(|e| e.0)?;
    if unknown_atom(&t) {
        return Err("unknown_atom".into());
    }
    match &t {
        Term::Map(m) => match m.get("t") {
            Some(Term::Atom(k)) if REQUEST_KINDS.contains(&k.as_str()) => Ok(k.clone()),
            _ => Err("unknown kind".into()),
        },
        _ => Err("unknown kind".into()),
    }
}

/// A typed frame, or the node's word for what is wrong with it.
pub fn read_frame(body: &[u8], count: usize) -> Result<Frame, String> {
    read_body(body, count).map_err(|e| e.0)
}
