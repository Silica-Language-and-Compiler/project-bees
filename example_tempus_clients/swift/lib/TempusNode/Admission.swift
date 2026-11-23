// Admission as the node judges it (design section 4), with the order and the reason texts of
// src/tempus/bees_tempus_admit.silica and of the connection actor (src/tempus/dangerous_bees_tempus_conn.silica), so
// that a node of this extension and a Silica node write the same audit line for the same refusal.
import TempusClient

public enum Admission {
    public static let rotated = "key_rotated"

    /// The checks that need no key operation, in the node's order: the descriptor's lengths, the token's structure,
    /// the kid (a token under another kid is "key_rotated" whatever else is wrong with it), the window
    /// nbf - skew <= now < exp + skew, sub, and, when `want` is given, the token's type. "" when all pass.
    public static func pre(_ d: Descriptor, kid: Bytes, now: Int64, skew: Int64, want: PeerType?)
        -> (why: String, fields: TokenFields?, payload: Bytes, sig: Bytes) {
        guard d.id.count == 64, d.pub.count == 32, d.addr.count >= 3, d.addr.count <= 261,
              d.token.count >= 65, d.token.count <= 1024 else {
            return ("a field of the descriptor has a wrong length", nil, [], [])
        }
        let t: (fields: TokenFields, payload: Bytes, sig: Bytes)
        do {
            t = try readToken(d.token)
        } catch {
            return ("\(error)", nil, [], [])
        }
        let f = t.fields
        if f.kid != kid { return (rotated, f, [], []) }
        if now < f.nbf - skew { return ("the token is not valid yet", f, [], []) }
        if now >= f.exp + skew { return ("the token has expired", f, [], []) }
        if f.sub != d.pub { return ("sub is not the peer's key", f, [], []) }
        if let want, f.typ != want.rawValue { return ("typ is not the store's type", f, [], []) }
        return ("", f, t.payload, t.sig)
    }

    /// The two key operations that follow pre(): the id is the SHA-512 of pub, and the producer's signature over the
    /// token's payload as received. "" when both pass.
    public static func keys(_ d: Descriptor, payload: Bytes, sig: Bytes, producerKey: Bytes) -> String {
        if sha512(d.pub) != d.id { return "id is not the SHA-512 of pub" }
        if !ed25519Verify(pub: producerKey, message: payload, sig: sig) { return "the signature does not verify" }
        return ""
    }

    /// A descriptor admitted to a store without contact (an entry of a shuffle or sample frame; ruling OQ-4).
    public static func entry(_ d: Descriptor, kid: Bytes, producerKey: Bytes, now: Int64, skew: Int64, want: PeerType?) -> String {
        let p = pre(d, kid: kid, now: now, skew: skew, want: want)
        return p.why.isEmpty ? keys(d, payload: p.payload, sig: p.sig, producerKey: producerKey) : p.why
    }

    /// The whitelist rule (rulings OQ-3, NQ-4), both sides: `listed` says whether the peer's certificate is in the
    /// tempus whitelist. "" when it holds.
    public static func whitelist(typ: String, listed: Bool) -> String {
        if typ == PeerType.edge.rawValue {
            return listed ? "a certificate of the tempus whitelist with a token whose typ is not tempus_bridge or tempus_sentinel" : ""
        }
        return listed ? "" : "a tempus_bridge or tempus_sentinel token under a certificate that is not in the tempus whitelist"
    }

    /// True when `sig` is the peer's signature over nonce || token.
    public static func proof(pub: Bytes, nonce: Bytes, token: Bytes, sig: Bytes) -> Bool {
        ed25519Verify(pub: pub, message: nonce + token, sig: sig)
    }
}

// ---------------------------------------------------------------- what a body is, as the node's connection reads it
let requestKinds = ["advert", "pop_challenge", "pop_response", "key_rotated", "shuffle", "shuffle_reply", "sample",
                    "sample_reply", "done", "call", "cast", "result"]
/// Every atom a production BEES node holds for tempus/1 and TRUST's frames (src/tempus/bees_tempus.atoms and the
/// frame atoms of src/trust/bees_trust.atoms). A body with any other atom is refused as `unknown_atom`, which is
/// what a Silica node says of the test-only tick and clock frames.
let knownAtoms: Set<String> = Set(requestKinds + ["tempus_edge", "tempus_bridge", "tempus_sentinel", "d", "id", "pub", "addr",
    "nonce", "sig", "kid", "store", "entries", "age", "n", "sub", "typ", "nbf", "exp", "t", "ver", "req_id", "m", "f", "a",
    "args", "opts", "value", "token", "deadline_ms", "hello", "token_present", "token_issue", "goaway", "erlang", "ok", "error"])

private func unknownAtom(_ t: Term) -> Bool {
    switch t {
    case .atom(let a): return !knownAtoms.contains(a)
    case .list(let l): return l.contains(where: unknownAtom)
    case .map(let m): return m.contains { !knownAtoms.contains($0.key) || unknownAtom($0.value) }
    default: return false
    }
}

/// The kind of a body (the atom of its `t`), or nil with the reason when its structure is refused or its `t` is no
/// kind: the reason is the decoder's word, or "unknown kind" for a well-formed map.
func bodyKind(_ body: Bytes) -> (kind: String?, why: String) {
    if body.count >= 1 && body[0] != 131 { return (nil, "bad_version") }
    if body.count < 6 { return (nil, "truncated") }
    if body[1] != 116 { return (nil, "bad_tag") }
    if body[2] != 0 || body[3] != 0 || body[4] != 0 || body[5] > 16 { return (nil, "too_long") }
    let t: Term
    do {
        t = try etfDecode(body, depthMax: 6)
    } catch {
        return (nil, "\(error)")
    }
    if unknownAtom(t) { return (nil, "unknown_atom") }
    guard case .map(let m) = t, case .atom(let k)? = m["t"], requestKinds.contains(k) else { return (nil, "unknown kind") }
    return (k, "")
}

/// A typed frame, or the node's word for what is wrong with it.
func readFrame(_ body: Bytes, count: Int) -> (frame: Frame?, why: String) {
    do {
        return (try readBody(body, shuffleLength: count), "")
    } catch {
        return (nil, "\(error)")
    }
}
