// Identities, the verifier (design section 4) and outcomes.
// An example only: not for production.

/// One peer: its Ed25519 key, pub, peer id = SHA-512(pub), the certificate self-signed over that key (DER), its token
/// exactly as the producer gave it, and the listen address text "host:port" it advertises.
public final class Identity {
    public let key: SigningKey
    public let token: Bytes
    public let addr: String?
    public let certDER: Bytes

    public var pub: Bytes { key.pub }
    public var peerId: Bytes { sha512(key.pub) }

    /// `certDER` nil: a certificate is made, self-signed over the key, with this common name and serial number.
    public init(seed: Bytes, token: Bytes, addr: String? = nil, certDER: Bytes? = nil,
                commonName: String = "bees tempus example client", serial: Int = 1) throws {
        key = try SigningKey(seed: seed)
        self.token = token
        self.addr = addr
        self.certDER = try certDER ?? selfSignedCertificate(key: key, commonName: commonName, serial: serial)
    }

    public func descriptor(addr other: String? = nil) throws -> Descriptor {
        guard let a = other ?? addr else {
            throw Unencodable("this identity has no listen address (design OQ-15: every node has one)")
        }
        return Descriptor(id: peerId, pub: pub, addr: a, token: token)
    }

    public func advert(addr other: String? = nil) throws -> Bytes { try TempusClient.advert(try descriptor(addr: other)) }

    public func entry(age: Int64 = 0, addr other: String? = nil) throws -> Entry {
        Entry(age: age, d: try descriptor(addr: other))
    }

    /// The proof of possession: this key's signature over the peer's nonce followed by this peer's own token.
    public func prove(nonce: Bytes) throws -> Bytes { try key.sign(nonce + token) }
}

/// What this peer needs to check another: the current producer key (32 raw bytes) and its kid, the clock in whole
/// seconds since 1970 (a function, so that the caller decides where the time comes from), the skew in seconds, the
/// token types it admits, and the `tempus` whitelist.
public struct Verifier {
    public var producerPub: Bytes
    public var kid: Bytes
    public var clock: () -> Int64
    public var skew: Int64
    public var types: [String]
    /// The SHA-512 of the DER of every bridge and sentinel certificate this client accepts (design sections 4 and 9:
    /// an edge checks that a peer whose token says tempus_bridge or tempus_sentinel presents one of them). nil: the
    /// rule is not applied, which is what the Python example does.
    public var whitelist: Set<Bytes>?

    public init(producerPub: Bytes, kid: Bytes, clock: @escaping () -> Int64, skew: Int64, types: [String] = peerTypes,
                whitelist: Set<Bytes>? = nil) {
        self.producerPub = producerPub
        self.kid = kid
        self.clock = clock
        self.skew = skew
        self.types = types
        self.whitelist = whitelist
    }

    /// The token's fields when the descriptor verifies; Refused(reason) otherwise, reason "key_rotated" for a token
    /// under another kid (checked first: a signature under a key this verifier does not hold cannot be judged).
    /// `certDER`, when given, is the certificate the peer presented in the TLS handshake: its key must be the
    /// descriptor's `pub` (the channel binding), and the whitelist rule is applied to it. An entry of a reply has no
    /// connection, so it is checked without a certificate.
    @discardableResult
    public func checkDescriptor(_ d: Descriptor, certDER: Bytes? = nil) throws -> TokenFields {
        try TempusClient.checkDescriptor(d)
        let (fields, payload, sig) = try readToken(d.token)
        let now = clock()
        if fields.kid != kid { throw Refused("key_rotated") }
        if now < fields.nbf - skew { throw Refused("the token is not valid yet") }
        if now >= fields.exp + skew { throw Refused("the token has expired") }
        if fields.sub != d.pub { throw Refused("sub is not the peer's key") }
        if !types.contains(fields.typ) { throw Refused("typ is not allowed") }
        if sha512(d.pub) != d.id { throw Refused("id is not the SHA-512 of pub") }
        if !ed25519Verify(pub: producerPub, message: payload, sig: sig) { throw Refused("the signature does not verify") }
        if let certDER {
            if try certificateKey(der: certDER) != d.pub { throw Refused("the certificate's key is not the advert's pub") }
            if let whitelist, fields.typ != "tempus_edge", !whitelist.contains(sha512(certDER)) {
                throw Refused("the certificate of a \(fields.typ) is not in the whitelist")
            }
        }
        return fields
    }

    /// An entry of a shuffle or sample frame for `store`: the descriptor verifies and its token's type is the store's.
    public func checkEntry(_ e: Entry, store: String) throws {
        let fields = try checkDescriptor(e.d)
        if fields.typ != store { throw Refused("the entry's typ is not the store's") }
    }

    public func checkProof(pub: Bytes, nonce: Bytes, token: Bytes, sig: Bytes) throws {
        if !ed25519Verify(pub: pub, message: nonce + token, sig: sig) {
            throw Refused("the proof of possession does not verify")
        }
    }
}

// ---------------------------------------------------------------- outcomes
func show(_ t: Term) -> String {
    switch t {
    case .atom(let s): return s
    case .int(let n): return String(n)
    case .binary(let b): return hex(b)
    case .list(let l): return "[" + l.map(show).joined(separator: ",") + "]"
    case .map(let m):
        if case .binary(let id)? = m["id"] { return hex(Bytes(id.prefix(8))) }
        return "{" + m.keys.sorted(by: keyOrder).map { "\($0)=\(show(m[$0]!))" }.joined(separator: ",") + "}"
    }
}

func show(_ d: Descriptor) -> String { hex(Bytes(d.id.prefix(8))) }

func show(_ entries: [Entry]) -> String {
    "[" + entries.map { "\($0.age):\(show($0.d))" }.joined(separator: ",") + "]"
}

/// The fields of a frame as `name=value` texts, in name order.
func shownFields(_ f: Frame) -> [String] {
    var m: [String: String] = [:]
    switch f {
    case .advert(let d): m["d"] = show(d)
    case .popChallenge(let nonce): m["nonce"] = hex(nonce)
    case .popResponse(let sig): m["sig"] = hex(sig)
    case .keyRotated(let kid): m["kid"] = hex(kid)
    case .shuffle(let store, let entries), .shuffleReply(let store, let entries), .sampleReply(let store, let entries):
        m["store"] = store
        m["entries"] = show(entries)
    case .sample(let store, let n):
        m["store"] = store
        m["n"] = String(n)
    case .done: break
    case .other(_, let fields):
        for (k, v) in fields { m[k] = show(v) }
    }
    return m.keys.sorted(by: keyOrder).map { "\($0)=\(m[$0]!)" }
}

/// What happened on one connection, as plain values. Expected behaviour of a peer is never an error thrown.
///
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
public struct Outcome {
    public var what: String
    public var stage: String
    public var reason = ""
    public var frame: Frame?
    public var body: Bytes = []
    public var advert: Descriptor?
    public var typ = ""
    public var kid: Bytes?
    public var sent = ""

    public init(_ what: String, _ stage: String, reason: String = "") {
        self.what = what
        self.stage = stage
        self.reason = reason
    }

    /// One deterministic line, in the form of the Python example's: nothing of the wall clock.
    public var line: String {
        var parts = [what]
        if what != "reply" && what != "served" { parts.append("at=" + stage) }
        if let frame {
            parts.append(frame.kind)
            parts += shownFields(frame)
        }
        if !sent.isEmpty { parts.append("sent=" + sent) }
        if let kid { parts.append("kid=" + hex(kid)) }
        if let advert { parts.append("peer=" + show(advert)) }
        if !typ.isEmpty { parts.append("typ=" + typ) }
        if !reason.isEmpty { parts.append("reason=\"\(reason)\"") }
        return parts.joined(separator: " ")
    }
}
