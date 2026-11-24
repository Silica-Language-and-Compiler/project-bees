// The tempus/1 frame bodies a client writes and reads (design section 5), with every bound of design section 8, and
// the token (design section 4). The test-only tick and clock frames of src/tempus_test are not here: they are no part
// of a client, and this reader refuses both as it refuses any frame of no kind.
// A usable example, to be used with care (README.md says what care means).

public let peerTypes = ["tempus_edge", "tempus_bridge", "tempus_sentinel"]
/// The kinds this client reads as tempus/1 frames.
public let kinds = ["advert", "pop_challenge", "pop_response", "key_rotated", "shuffle", "shuffle_reply", "sample",
                    "sample_reply", "done"]
public let ageMax: Int64 = 65535
/// The literal ceiling of entries in one frame.
public let entriesMax = 64

/// The record that describes one peer.
public struct Descriptor: Equatable, Sendable {
    public var id: Bytes
    public var pub: Bytes
    public var addr: Bytes
    public var token: Bytes

    public init(id: Bytes, pub: Bytes, addr: Bytes, token: Bytes) {
        self.id = id
        self.pub = pub
        self.addr = addr
        self.token = token
    }

    public init(id: Bytes, pub: Bytes, addr: String, token: Bytes) {
        self.init(id: id, pub: pub, addr: Array(addr.utf8), token: token)
    }

    public var term: Term {
        .map(["id": .binary(id), "pub": .binary(pub), "addr": .binary(addr), "token": .binary(token)])
    }
}

/// One entry of a shuffle or sample frame.
public struct Entry: Equatable, Sendable {
    public var age: Int64
    public var d: Descriptor

    public init(age: Int64, d: Descriptor) {
        self.age = age
        self.d = d
    }

    var term: Term { .map(["age": .int(age), "d": d.term]) }
}

/// A body as this client read it.
public enum Frame: Equatable, Sendable {
    case advert(Descriptor)
    case popChallenge(nonce: Bytes)
    case popResponse(sig: Bytes)
    case keyRotated(kid: Bytes)
    case shuffle(store: String, entries: [Entry])
    case shuffleReply(store: String, entries: [Entry])
    case sample(store: String, n: Int64)
    case sampleReply(store: String, entries: [Entry])
    case done
    /// A map whose `t` is no tempus/1 kind (TRUST's call, cast and result), with its other fields as decoded, unchecked.
    case other(kind: String, fields: [String: Term])

    public var kind: String {
        switch self {
        case .advert: return "advert"
        case .popChallenge: return "pop_challenge"
        case .popResponse: return "pop_response"
        case .keyRotated: return "key_rotated"
        case .shuffle: return "shuffle"
        case .shuffleReply: return "shuffle_reply"
        case .sample: return "sample"
        case .sampleReply: return "sample_reply"
        case .done: return "done"
        case .other(let kind, _): return kind
        }
    }

    public var store: String? {
        switch self {
        case .shuffle(let s, _), .shuffleReply(let s, _), .sampleReply(let s, _), .sample(let s, _): return s
        default: return nil
        }
    }

    public var entries: [Entry]? {
        switch self {
        case .shuffle(_, let e), .shuffleReply(_, let e), .sampleReply(_, let e): return e
        default: return nil
        }
    }
}

// ---------------------------------------------------------------- checks shared by the readers
private func checkKeys(_ t: Term, _ keys: [String], _ what: String) throws -> [String: Term] {
    guard case .map(let m) = t else { throw Refused("\(what) is not a map") }
    let have = Set(m.keys), want = Set(keys)
    if !have.subtracting(want).isEmpty { throw Refused("unknown_field") }
    if !want.subtracting(have).isEmpty { throw Refused("missing_field") }
    return m
}

private func bin(_ m: [String: Term], _ key: String, _ lo: Int, _ hi: Int, _ text: String) throws -> Bytes {
    guard case .binary(let v)? = m[key], v.count >= lo, v.count <= hi else { throw Refused(text) }
    return v
}

func readDescriptor(_ t: Term) throws -> Descriptor {
    let m = try checkKeys(t, ["id", "pub", "addr", "token"], "descriptor")
    return Descriptor(id: try bin(m, "id", 64, 64, "id is not 64 bytes"),
                      pub: try bin(m, "pub", 32, 32, "pub is not 32 bytes"),
                      addr: try bin(m, "addr", 3, 261, "addr is not 3 to 261 bytes"),
                      token: try bin(m, "token", 65, 1024, "token is not 65 to 1024 bytes"))
}

/// The field bounds of a descriptor held as a value (one built by the caller, or one read from a frame).
public func checkDescriptor(_ d: Descriptor) throws {
    _ = try readDescriptor(d.term)
}

// ---------------------------------------------------------------- the token
public struct TokenFields: Equatable, Sendable {
    public let kid: Bytes
    public let sub: Bytes
    public let typ: String
    public let nbf: Int64
    public let exp: Int64
}

/// The bytes a producer signs: the ETF map of the five fields, times in whole seconds.
public func tokenPayload(kid: Bytes, sub: Bytes, typ: String, nbf: Int64, exp: Int64) throws -> Bytes {
    try etfEncode(.map(["kid": .binary(kid), "sub": .binary(sub), "typ": .atom(typ), "nbf": .int(nbf), "exp": .int(exp)]))
}

/// The structure and bounds of a token. The signature is NOT verified here.
public func readToken(_ token: Bytes) throws -> (fields: TokenFields, payload: Bytes, sig: Bytes) {
    guard token.count >= 65, token.count <= 1024 else { throw Refused("token is not 65 to 1024 bytes") }
    let sig = Bytes(token[..<64]), payload = Bytes(token[64...])
    let t = try etfDecode(payload, depthMax: 2)
    guard case .map(let five) = t, five.count == 5 else { throw Refused("the token is not a map of five keys") }
    let m = try checkKeys(t, ["kid", "sub", "typ", "nbf", "exp"], "token")
    let kid = try bin(m, "kid", 1, 64, "kid is not 1 to 64 bytes")
    let sub = try bin(m, "sub", 32, 32, "sub is not 32 bytes")
    guard case .atom(let typ)? = m["typ"], peerTypes.contains(typ) else { throw Refused("typ is not a peer type") }
    guard case .int(let nbf)? = m["nbf"], case .int(let exp)? = m["exp"], nbf >= 0, exp >= 0 else {
        throw Refused("nbf or exp is not a time")
    }
    guard exp > nbf else { throw Refused("exp is not after nbf") }
    return (TokenFields(kid: kid, sub: sub, typ: typ, nbf: nbf, exp: exp), payload, sig)
}

// ---------------------------------------------------------------- writing frame bodies
private func typ(_ store: String) throws -> Term {
    guard peerTypes.contains(store) else { throw Unencodable("store is one of \(peerTypes)") }
    return .atom(store)
}

public func advert(_ d: Descriptor) throws -> Bytes {
    try etfEncode(.map(["t": .atom("advert"), "ver": .int(1), "d": d.term]))
}

public func challenge(nonce: Bytes) throws -> Bytes {
    try etfEncode(.map(["t": .atom("pop_challenge"), "nonce": .binary(nonce)]))
}

public func response(sig: Bytes) throws -> Bytes {
    try etfEncode(.map(["t": .atom("pop_response"), "sig": .binary(sig)]))
}

public func keyRotated(kid: Bytes) throws -> Bytes {
    try etfEncode(.map(["t": .atom("key_rotated"), "kid": .binary(kid)]))
}

private func entriesBody(_ kind: String, _ store: String, _ entries: [Entry]) throws -> Bytes {
    try etfEncode(.map(["t": .atom(kind), "store": try typ(store), "entries": .list(entries.map { $0.term })]))
}

public func shuffle(store: String, entries: [Entry]) throws -> Bytes { try entriesBody("shuffle", store, entries) }

public func shuffleReply(store: String, entries: [Entry]) throws -> Bytes {
    try entriesBody("shuffle_reply", store, entries)
}

public func sampleReply(store: String, entries: [Entry]) throws -> Bytes {
    try entriesBody("sample_reply", store, entries)
}

public func sample(store: String, n: Int64) throws -> Bytes {
    try etfEncode(.map(["t": .atom("sample"), "store": try typ(store), "n": .int(n)]))
}

public func done() throws -> Bytes { try etfEncode(.map(["t": .atom("done")])) }

/// TRUST's request frame as a bridge reads it (design 17.4): `kind` is "call" or "cast"; `args` is a list of integers
/// (this client's ETF subset has no tuples and no floats). A `call` is answered with a `result` frame carrying the same
/// `reqId`; a `cast` is never answered.
public func callFrame(kind: String = "call", reqId: Bytes, module: String, function: String, args: [Int64]) throws -> Bytes {
    guard kind == "call" || kind == "cast" else { throw Unencodable("a request to a bridge is a call or a cast") }
    guard reqId.count >= 1, reqId.count <= 16 else { throw Unencodable("req_id is 1 to 16 bytes") }
    return try etfEncode(.map(["t": .atom(kind), "ver": .int(1), "req_id": .binary(reqId), "m": .atom(module),
                               "f": .atom(function), "a": .int(Int64(args.count)), "args": .list(args.map { .int($0) }),
                               "opts": .map([:])]))
}

/// The body with its 4-byte length, most significant byte first, as it travels.
public func frame(_ body: Bytes) throws -> Bytes {
    guard body.count <= frameMax else { throw Unencodable("body above the frame ceiling") }
    return be32(body.count) + body
}

// ---------------------------------------------------------------- reading frame bodies
private func storeOf(_ m: [String: Term]) throws -> String {
    guard case .atom(let store)? = m["store"], peerTypes.contains(store) else { throw Refused("store is not a peer type") }
    return store
}

/// A body as a Frame, every bound of design section 8 checked. `shuffleLength` is the value of the network this
/// client joined; a client cannot ask a node for it.
public func readBody(_ body: Bytes, shuffleLength: Int) throws -> Frame {
    let t = try etfDecode(body)
    guard case .map(let top) = t else { throw Refused("bad_tag") }
    guard case .atom(let kind)? = top["t"], kinds.contains(kind) else { throw Refused("unknown kind") }
    switch kind {
    case "advert":
        let m = try checkKeys(t, ["t", "ver", "d"], kind)
        guard m["ver"] == .int(1) else { throw Refused("ver is not 1") }
        return .advert(try readDescriptor(m["d"]!))
    case "pop_challenge":
        let m = try checkKeys(t, ["t", "nonce"], kind)
        return .popChallenge(nonce: try bin(m, "nonce", 32, 32, "nonce is not 32 bytes"))
    case "pop_response":
        let m = try checkKeys(t, ["t", "sig"], kind)
        return .popResponse(sig: try bin(m, "sig", 64, 64, "sig is not 64 bytes"))
    case "key_rotated":
        let m = try checkKeys(t, ["t", "kid"], kind)
        return .keyRotated(kid: try bin(m, "kid", 1, 64, "kid is not 1 to 64 bytes"))
    case "shuffle", "shuffle_reply", "sample_reply":
        let m = try checkKeys(t, ["t", "store", "entries"], kind)
        let store = try storeOf(m)
        guard case .list(let items)? = m["entries"] else { throw Refused("entries is not a list") }
        guard items.count <= entriesMax, items.count <= shuffleLength else {
            throw Refused("more entries than the shuffle length")
        }
        var entries: [Entry] = []
        for item in items {
            let e = try checkKeys(item, ["age", "d"], "entry")
            guard case .int(let age)? = e["age"], age >= 0, age <= ageMax else { throw Refused("age is not 0 to 65535") }
            entries.append(Entry(age: age, d: try readDescriptor(e["d"]!)))
        }
        switch kind {
        case "shuffle": return .shuffle(store: store, entries: entries)
        case "shuffle_reply": return .shuffleReply(store: store, entries: entries)
        default: return .sampleReply(store: store, entries: entries)
        }
    case "sample":
        let m = try checkKeys(t, ["t", "store", "n"], kind)
        let store = try storeOf(m)
        guard case .int(let n)? = m["n"], n >= 1, n <= Int64(shuffleLength) else {
            throw Refused("n is not 1 to the shuffle length")
        }
        return .sample(store: store, n: n)
    default:
        _ = try checkKeys(t, ["t"], kind)
        return .done
    }
}

/// Any body: a tempus/1 frame by readBody; a map whose `t` is an atom that is no tempus/1 kind (TRUST's result, call,
/// cast) with its fields as decoded, unchecked; otherwise Refused with readBody's reason. A TRUST frame that carries a
/// tuple or a float cannot be decoded by this client's subset and is refused; its bytes are still in the Outcome.
public func readAny(_ body: Bytes, shuffleLength: Int = entriesMax) throws -> Frame {
    do {
        return try readBody(body, shuffleLength: shuffleLength)
    } catch let first as Refused {
        guard let t = try? etfDecode(body), case .map(var m) = t, case .atom(let kind)? = m["t"],
              !kinds.contains(kind) else { throw first }
        m["t"] = nil
        return .other(kind: kind, fields: m)
    }
}
