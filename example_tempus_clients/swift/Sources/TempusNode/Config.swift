// The configuration of a node: the keys of the `tempus` section of bees.config (design section 11) as one value the
// application builds, with the bounds and the refusal texts of tools/bees_tempus_conf.py and the boot refusals of
// bees_tempus_node@boot_why. Nothing has a default and nothing is clamped: a value outside its bounds refuses the start.
// A key the Silica node requires is a property without a default here, so leaving it out does not compile.
import TempusClient

public enum PeerType: String, Sendable, CaseIterable {
    case edge = "tempus_edge"
    case bridge = "tempus_bridge"
    case sentinel = "tempus_sentinel"

    /// The name of the role in the configuration: edge, bridge, sentinel.
    public var role: String { String(rawValue.dropFirst(7)) }
}

/// capacity, shuffle_length and tick_ms of one store.
public struct StoreConfig: Sendable {
    public var capacity: Int
    public var shuffleLength: Int
    public var tickMs: Int

    public init(capacity: Int, shuffleLength: Int, tickMs: Int) {
        self.capacity = capacity
        self.shuffleLength = shuffleLength
        self.tickMs = tickMs
    }
}

/// A sentinel the node joins through: an IPv4 literal and a port. Its TEMPUS certificate must be in `whitelist`.
public struct Sentinel: Sendable {
    public var host: String
    public var port: Int

    public init(host: String, port: Int) {
        self.host = host
        self.port = port
    }
}

/// A configuration, or an identity, that the node refuses to start with. `reason` is the text an operator reads.
public struct ConfigRefused: Error, Equatable, CustomStringConvertible {
    public let reason: String
    public var description: String { reason }
}

public struct TempusConfig: Sendable {
    /// The node's own type, and the `typ` its token must carry. `bridge` is refused: see refusal().
    public var role: PeerType
    /// An IPv4 literal, or "localhost". "0.0.0.0" listens on every IPv4 interface.
    public var listenAddress: String
    public var port: Int
    /// Required unless the node is the first sentinel (role sentinel): 1 to 16.
    public var sentinels: [Sentinel]
    public var edge: StoreConfig
    public var bridge: StoreConfig
    public var sentinel: StoreConfig
    /// The one current producer key: its kid (1 to 64 bytes) and the 32-byte Ed25519 public key.
    public var producerKid: Bytes
    public var producerKey: Bytes
    /// The `tempus` whitelist: the TEMPUS certificates (DER) of the bridges and sentinels this node accepts.
    public var whitelist: [Bytes]
    public var shuffleTimeoutMs: Int
    public var inflightMax: Int
    public var clockSkewMs: Int
    public var clockBack: ClockBack
    /// Required when clockBack is stop; refused under follow and hold.
    public var clockBackLimitS: Int?
    public var clockFail: ClockFail
    public var clockReadMs: Int
    public var joinRetryInitialMs: Int
    public var joinRetryMaxMs: Int

    public init(role: PeerType, listenAddress: String, port: Int, sentinels: [Sentinel], edge: StoreConfig,
                bridge: StoreConfig, sentinel: StoreConfig, producerKid: Bytes, producerKey: Bytes, whitelist: [Bytes],
                shuffleTimeoutMs: Int, inflightMax: Int, clockSkewMs: Int, clockBack: ClockBack, clockBackLimitS: Int?,
                clockFail: ClockFail, clockReadMs: Int, joinRetryInitialMs: Int, joinRetryMaxMs: Int) {
        self.role = role
        self.listenAddress = listenAddress
        self.port = port
        self.sentinels = sentinels
        self.edge = edge
        self.bridge = bridge
        self.sentinel = sentinel
        self.producerKid = producerKid
        self.producerKey = producerKey
        self.whitelist = whitelist
        self.shuffleTimeoutMs = shuffleTimeoutMs
        self.inflightMax = inflightMax
        self.clockSkewMs = clockSkewMs
        self.clockBack = clockBack
        self.clockBackLimitS = clockBackLimitS
        self.clockFail = clockFail
        self.clockReadMs = clockReadMs
        self.joinRetryInitialMs = joinRetryInitialMs
        self.joinRetryMaxMs = joinRetryMaxMs
    }

    public func store(_ t: PeerType) -> StoreConfig { t == .edge ? edge : t == .bridge ? bridge : sentinel }

    /// True when the listen address is a loopback address.
    public var listensOnLoopback: Bool { listenAddress == "localhost" || (isIPv4(listenAddress) && listenAddress.hasPrefix("127.")) }

    /// nil when a node may start with this configuration; else why not, as `tempus.KEY: text`, in the order and with
    /// the texts of tools/bees_tempus_conf.py.
    public func refusal() -> String? {
        func int(_ key: String, _ v: Int, _ lo: Int, _ hi: Int) -> String? {
            if v < lo { return "tempus.\(key): \(v) is below \(lo) (bounds \(lo) to \(hi); never clamped)" }
            if v > hi { return "tempus.\(key): \(v) is above \(hi) (bounds \(lo) to \(hi); never clamped)" }
            return nil
        }
        if role == .bridge {
            return "tempus.role: bridge needs mode tempus-trust (a bridge runs TRUST and TEMPUS); this extension has no TRUST side and cannot be a bridge"
        }
        if listenAddress != "localhost" && !isIPv4(listenAddress) {
            return "tempus.listen_address: \"\(listenAddress)\" is not an IPv4 literal or localhost (this extension listens on IPv4 only)"
        }
        for (key, v, lo, hi) in [("port", port, 1, 65535), ("shuffle_timeout_ms", shuffleTimeoutMs, 100, 60000),
                                 ("inflight_max", inflightMax, 1, 64), ("clock_skew_ms", clockSkewMs, 0, 300000),
                                 ("join_retry_initial_ms", joinRetryInitialMs, 100, 3600000),
                                 ("join_retry_max_ms", joinRetryMaxMs, 100, 3600000), ("clock_read_ms", clockReadMs, 100, 60000)] {
            if let why = int(key, v, lo, hi) { return why }
        }
        if joinRetryMaxMs < joinRetryInitialMs { return "tempus.join_retry_max_ms: below join_retry_initial_ms" }
        if clockBack == .stop {
            guard let limit = clockBackLimitS else {
                return "tempus.clock_back_limit_s: required when clock_back is stop (no default)"
            }
            if let why = int("clock_back_limit_s", limit, 0, 86400) { return why }
        } else if clockBackLimitS != nil {
            return "tempus.clock_back_limit_s: clock_back is \(clockBack.rawValue), so no step back stops the node: remove clock_back_limit_s (it is for clock_back stop only)"
        }
        for t in PeerType.allCases {
            let s = store(t), path = t.role
            if let why = int("\(path).capacity", s.capacity, 1, 256) ?? int("\(path).shuffle_length", s.shuffleLength, 1, 64)
                ?? int("\(path).tick_ms", s.tickMs, 100, 3600000) { return why }
            if s.shuffleLength > s.capacity {
                return "tempus.\(path).shuffle_length: \(s.shuffleLength) is above the capacity \(s.capacity)"
            }
        }
        if producerKid.count < 1 || producerKid.count > 64 { return "tempus.producer_key: the kid is not 1 to 64 bytes" }
        if producerKey.count != 32 { return "tempus.producer_key: the public key is not 32 bytes" }
        if sentinels.isEmpty {
            if role != .sentinel { return "tempus.sentinels: required unless the node is the first sentinel (role sentinel)" }
        } else if sentinels.count > 16 {
            return "tempus.sentinels: expected a list of 1 to 16 {Host, Port}"
        }
        for s in sentinels {
            if !isIPv4(s.host) { return "tempus.sentinels: \"\(s.host)\" is not an IPv4 literal (this extension resolves no host name)" }
            if let why = int("sentinels", s.port, 1, 65535) { return why }
        }
        return nil
    }
}

/// The node's TEMPUS identity, passed by the application as bytes: the 32-byte Ed25519 private seed, the certificate
/// self-signed over that key (DER), the producer's token, and the address other nodes dial ("a.b.c.d:port").
/// The node makes its key from the seed when it is created and keeps no copy of the seed.
public struct NodeIdentity: Sendable {
    public var seed: Bytes
    public var certificateDER: Bytes
    public var token: Bytes
    public var address: String

    public init(seed: Bytes, certificateDER: Bytes, token: Bytes, address: String) {
        self.seed = seed
        self.certificateDER = certificateDER
        self.token = token
        self.address = address
    }
}

func isIPv4(_ s: String) -> Bool {
    let parts = s.split(separator: ".", omittingEmptySubsequences: false)
    return parts.count == 4 && parts.allSatisfy { p in
        !p.isEmpty && p.count <= 3 && p.utf8.allSatisfy { $0 >= 48 && $0 <= 57 } && Int(p)! <= 255
    }
}

/// An address this node dials: a dotted quad, a colon, a port of 1 to 65535 in decimal. A name is not resolved.
func dialable(_ addr: Bytes) -> Bool {
    guard let text = String(validating: addr, as: UTF8.self), let c = text.firstIndex(of: ":") else { return false }
    let host = text[..<c], port = text[text.index(after: c)...]
    let quads = host.split(separator: ".", omittingEmptySubsequences: false)
    guard quads.count == 4, quads.allSatisfy({ !$0.isEmpty && $0.count <= 3 && $0.utf8.allSatisfy { $0 >= 48 && $0 <= 57 } }),
          !port.isEmpty, port.count <= 5, port.utf8.allSatisfy({ $0 >= 48 && $0 <= 57 }), let p = Int(port) else { return false }
    return p >= 1 && p <= 65535
}

/// What refuses a node's start from its identity (bees_tempus_node@boot_why, with its texts): nil when it may start.
func identityRefusal(role: PeerType, pub: Bytes, token: Bytes) -> String? {
    let fields: TokenFields
    do {
        fields = try readToken(token).fields
    } catch {
        return "the node's token does not read: \(error)"
    }
    if fields.typ != role.rawValue { return "the node's token is for another peer type than the node's" }
    if fields.sub != pub { return "the node's token names another key" }
    return nil
}
