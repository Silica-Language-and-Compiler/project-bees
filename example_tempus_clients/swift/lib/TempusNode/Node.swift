// A TEMPUS node (development-plan/tempus-design.md sections 3 to 6 and 8 to 11): it listens, joins through its
// sentinels, serves admitted peers and ticks its three stores. What it does, and the lines it writes, follow the BEES
// node of src/tempus/bees_tempus_node.part.
//
// Who owns what. Everything that changes (the three stores, the clock state, the token, the producer key, the counts,
// the join) is owned by one serial dispatch queue, `queue`: every event (a clock reading, a timer, the outcome of a
// connection, a request of an admitted peer, a call of the application) is one block on it, and nothing else reads or
// writes that state. A connection runs on a thread of its own with a copy of the values it needs, taken when it was
// dialed or accepted (NodeConnection.swift); it reaches the node only through blocks on the queue.
import Darwin
import Foundation
import TempusClient

/// What the application is told. Each event is given on the node's queue, in order with the node's lines: the
/// function that receives it must return quickly and must not wait for the node.
public enum NodeEvent: Sendable {
    /// The first reading of the clock succeeded and the node listens.
    case listening(address: String)
    /// The view of one store after a step that may have changed it.
    case view(store: PeerType, entries: [ViewEntry<Descriptor>])
    /// The join through the sentinels is complete.
    case joined
    /// The node's own token is not valid any more and ticking has stopped, until replaceToken.
    case ownTokenNotValid(reason: String)
    /// A peer answered this node's advert with key_rotated, naming the kid it takes as current. `dialed` says whether
    /// this node dialed that peer. The application must get a new token.
    case keyRotated(kid: Bytes, dialed: Bool)
    /// The clock could not be read; the text says what that means for the node. Told once per failure.
    case clockNotRead(String)
    /// The clock went back by more than clock_back_limit_s under clock_back stop: the node has stopped for good.
    case stopped(String)
    /// An accepted peer was refused. `peerId` is the SHA-512 of the key of its TLS certificate, never the id an advert
    /// claims; `tokenVerified` says whether the producer's signature on its token had verified. A node that is not a
    /// bridge keeps no score: this is for the application's own records.
    case peerRefused(event: String, peerId: Bytes, tokenVerified: Bool)
    /// The node could not listen on its address.
    case listenFailed(String)
}

public final class TempusNode: @unchecked Sendable {
    public let config: TempusConfig
    /// The node's peer id, the SHA-512 of its public key.
    public let peerId: Bytes
    public let publicKey: Bytes

    let queue = DispatchQueue(label: "tempus.node")
    let sources: NodeSources
    let key: SigningKey
    let certDER: Bytes
    let address: String
    let serverContext: TLSContext
    let clientContext: TLSContext
    let whitelist: [Bytes]                  // the SHA-512 of each whitelisted certificate's DER, in the order given
    let skew: Int64
    private let linesSink: @Sendable (String) -> Void
    private let eventsSink: @Sendable (NodeEvent) -> Void
    private let lineLock = NSLock()
    private let flagLock = NSLock()
    private var ended = false               // under flagLock

    // ---- owned by `queue`
    private var token: Bytes
    private var kid: Bytes
    private var producerKey: Bytes
    private var stores: [PeerType: Store<Descriptor>] = [:]
    private var now: Int64 = 0
    private var ck = ClockState.none
    private var live = 0, accepted = 0, dialedCount = 0
    private var ownTokenTold = false
    private var joinState = 0               // 0 not begun, 1...3 the store being asked for, 4 done, 10 + store: waits for the clock
    private var joinDelay: Int
    private var joinPending: Set<PeerType> = []
    private enum Dial { case shuffle(PeerType), join(PeerType, Int) }
    private var dials: [Int: Dial] = [:]
    private var listenFd: Int32 = -1

    /// A node that reads the machine's clock, runs its own timers and draws from the system's secure random source.
    /// `lines` is given every line the node writes (its own and the audit lines), one call per line, from any thread,
    /// one at a time. `events` is given what the application is told. Throws ConfigRefused, after writing the line
    /// `tempus: boot refused: WHY`, when the configuration or the identity refuses the start. Nothing runs before start().
    public convenience init(config: TempusConfig, identity: NodeIdentity, lines: @escaping @Sendable (String) -> Void,
                            events: @escaping @Sendable (NodeEvent) -> Void) throws {
        try self.init(config: config, identity: identity, sources: nil, lines: lines, events: events)
    }

    /// A node whose clock, timers and random numbers are the caller's: for tests. It is refused on a listen address
    /// that is not loopback.
    public convenience init(config: TempusConfig, identity: NodeIdentity, sources: NodeSources,
                            lines: @escaping @Sendable (String) -> Void, events: @escaping @Sendable (NodeEvent) -> Void) throws {
        try self.init(config: config, identity: identity, sources: Optional(sources), lines: lines, events: events)
    }

    private init(config: TempusConfig, identity: NodeIdentity, sources given: NodeSources?,
                 lines: @escaping @Sendable (String) -> Void, events: @escaping @Sendable (NodeEvent) -> Void) throws {
        func refuse(_ why: String) -> ConfigRefused {
            lines("tempus: boot refused: " + why)
            return ConfigRefused(reason: why)
        }
        if given != nil && !config.listensOnLoopback {
            throw refuse("a node with a clock, timers or random numbers of its caller's on a listen address that is not loopback")
        }
        if let why = config.refusal() { throw refuse(why) }
        guard identity.seed.count == 32, let key = try? SigningKey(seed: identity.seed) else {
            throw refuse("the identity is not a 32-byte seed")
        }
        if let why = identityRefusal(role: config.role, pub: key.pub, token: identity.token) { throw refuse(why) }
        guard let certKey = try? certificateKey(der: identity.certificateDER), certKey == key.pub else {
            throw refuse("the identity certificate is not a certificate self-signed over the identity key")
        }
        guard dialable(Array(identity.address.utf8)) else {
            throw refuse("the node's address is not a dotted quad, a colon and a port")
        }
        for der in config.whitelist where (try? certificateKey(der: der)) == nil {
            throw refuse("a certificate of the tempus whitelist is not a certificate self-signed over an Ed25519 key")
        }
        self.config = config
        self.sources = given ?? .system
        self.key = key
        publicKey = key.pub
        peerId = sha512(key.pub)
        certDER = identity.certificateDER
        address = identity.address
        token = identity.token
        kid = config.producerKid
        producerKey = config.producerKey
        whitelist = config.whitelist.map { sha512($0) }
        skew = Int64(config.clockSkewMs / 1000)
        joinDelay = config.joinRetryInitialMs
        linesSink = lines
        eventsSink = events
        let me = Identity(key: key, token: identity.token, addr: identity.address, certDER: identity.certificateDER)
        do {
            let both = "ed25519:ecdsa_secp256r1_sha256"
            serverContext = try TLSContext(server: true, identity: me, peerSignatures: both, strictALPN: true)
            clientContext = try TLSContext(server: false, identity: me, peerSignatures: both)
        } catch {
            throw refuse("this node's TEMPUS certificate or key could not be loaded")
        }
        let d = Descriptor(id: peerId, pub: publicKey, addr: identity.address, token: identity.token)
        for t in PeerType.allCases {
            let s = config.store(t)
            stores[t] = Store(selfId: peerId, selfD: d, own: t == config.role, cap: s.capacity, count: s.shuffleLength)
        }
    }

    // ---------------------------------------------------------------- what the application calls
    /// Begins: the clock is read, and at the first reading the node listens and joins. Call it once.
    public func start() {
        queue.async { [self] in
            for t in PeerType.allCases { arm(t) }
            readClock()
        }
    }

    /// Ends the node: it stops listening, its timers do nothing more, and connections in hand end by themselves
    /// within shuffle_timeout_ms. A node that has ended is not started again: make a new one.
    public func stop() {
        flagLock.lock()
        ended = true
        flagLock.unlock()
        queue.sync {
            if listenFd >= 0 { close(listenFd) }
            listenFd = -1
        }
    }

    /// A new token from the producer (design section 6): the node's own entry carries it from the next shuffle on,
    /// and a node that had stopped ticking for its expired token ticks again.
    public func replaceToken(_ newToken: Bytes) {
        queue.async { [self] in
            token = newToken
            ownTokenTold = false
            say("own token replaced")
            for t in PeerType.allCases { stores[t]!.me.d = ownDescriptor }
        }
    }

    /// A new current producer key (ruling NQ-5).
    public func replaceProducerKey(kid newKid: Bytes, publicKey newKey: Bytes) {
        queue.async { [self] in
            kid = newKid
            producerKey = newKey
            say("producer key replaced, kid " + String(decoding: newKid, as: UTF8.self))
        }
    }

    /// Up to `count` peers of one store, drawn at random (how an application finds a bridge, design 17.3). The answer
    /// is given on the node's queue; it is empty when the store is empty or no random numbers can be had.
    public func peers(of store: PeerType, count: Int, _ answer: @escaping @Sendable ([Descriptor]) -> Void) {
        queue.async { [self] in
            let s = stores[store]!
            answer((s.sample(count, draws: sources.random.draws(s.count + 1)) ?? []).map(\.d))
        }
    }

    // ---------------------------------------------------------------- lines and events
    func say(_ line: String) {
        lineLock.lock()
        linesSink(line)
        lineLock.unlock()
    }

    private func tell(_ e: NodeEvent) { eventsSink(e) }

    private var hasEnded: Bool {
        flagLock.lock()
        defer { flagLock.unlock() }
        return ended
    }

    private var ownDescriptor: Descriptor { Descriptor(id: peerId, pub: publicKey, addr: address, token: token) }
    private func count(_ t: PeerType) -> Int { config.store(t).shuffleLength }
    private var maxCount: Int { PeerType.allCases.map(count).max()! }
    private func id8(_ id: Bytes) -> String { hex(Array(id.prefix(4))) }
    private func showView(_ t: PeerType) { tell(.view(store: t, entries: stores[t]!.view)) }

    private func after(_ ms: Int, _ purpose: TimerPurpose, _ action: @escaping @Sendable () -> Void) {
        sources.timers.after(milliseconds: ms, for: purpose) { [self] in
            if !hasEnded { queue.async(execute: action) }
        }
    }

    /// The values a connection works with: a copy, taken now.
    private func snapshot(cid: Int, dialed: Bool, count: Int) -> ConnValues {
        ConnValues(cid: cid, dialed: dialed, advert: (try? advert(ownDescriptor)) ?? [], token: token, kid: kid,
                   producerKey: producerKey, now: now, skew: skew, count: count,
                   deadline: monotonic() + Double(config.shuffleTimeoutMs) / 1000)
    }

    // ---------------------------------------------------------------- the clock (design section 10)
    private func readClock() {
        reading(sources.clock.seconds())
        after(config.clockReadMs, .clockRead) { [self] in readClock() }
    }

    private func reading(_ n: Int64?) {
        let limit = Int64(config.clockBackLimitS ?? 0)
        let t = clockTurn(ck, last: now, reading: n, ClockChoices(back: config.clockBack, limit: limit, fail: config.clockFail))
        let back = "the system clock went back by \(now - (n ?? 0)) s"
        if t.again { say("clock: the system clock is read again") }
        switch t.say {
        case .nothing: break
        case .first: say("clock: the system clock is read")
        case .noTimeAtStart:
            say("clock: the system clock could not be read: the node has not started")
            tell(.clockNotRead("the system clock could not be read: the node has not started"))
        case .noTimePause:
            let text = "the system clock could not be read: the node admits no connection and does not tick until it is read again"
            say("clock: " + text)
            tell(.clockNotRead(text))
        case .noTimeContinue:
            say("clock: the system clock could not be read: the node goes on with its last reading")
            tell(.clockNotRead("the system clock could not be read: the node goes on with its last reading"))
        case .followed: say("clock: \(back); the node follows it")
        case .holdBegins: say("clock: \(back); the node holds its time until the system clock has reached it")
        case .holdEnds: say("clock: the system clock has reached the held time; the node follows it again")
        case .stop:
            let text = "\(back), more than clock_back_limit_s \(limit): the node has stopped; it admits no connection and does not tick until its application starts it again"
            say("clock: " + text)
            tell(.stopped(text))
        }
        now = t.now
        ck = t.ck
        if t.say == .first { listen() }
        // the join request that waited for the clock is made at once when the clock is read again (ruling 1.d)
        if t.again && joinState > 10 {
            let st = PeerType.allCases[joinState - 11]
            joinState -= 10
            join(st, 1)
        }
    }

    // ---------------------------------------------------------------- listening
    private func listen() {
        var hints = addrinfo()
        hints.ai_family = AF_INET
        hints.ai_socktype = SOCK_STREAM
        hints.ai_flags = AI_PASSIVE
        var list: UnsafeMutablePointer<addrinfo>?
        let fd = socket(AF_INET, SOCK_STREAM, 0)
        var one: Int32 = 1
        setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &one, socklen_t(MemoryLayout<Int32>.size))
        guard fd >= 0, getaddrinfo(config.listenAddress, String(config.port), &hints, &list) == 0, let first = list,
              bind(fd, first.pointee.ai_addr, first.pointee.ai_addrlen) == 0, Darwin.listen(fd, 64) == 0 else {
            let e = errno
            if list != nil { freeaddrinfo(list) }
            if fd >= 0 { close(fd) }
            say("the listening link has gone down")
            tell(.listenFailed("cannot listen on \(config.listenAddress):\(config.port) (errno \(e))"))
            return
        }
        freeaddrinfo(list)
        listenFd = fd
        say("\(config.role.rawValue) node \(id8(peerId)) listening on \(address)")
        for t in PeerType.allCases {
            say("store \(t.rawValue): capacity \(config.store(t).capacity), shuffle length \(count(t))")
        }
        tell(.listening(address: address))
        Thread.detachNewThread { [self] in
            while !hasEnded {
                var p = pollfd(fd: fd, events: Int16(POLLIN), revents: 0)
                guard poll(&p, 1, 50) > 0 else { continue }
                let peer = Darwin.accept(fd, nil, nil)
                guard peer >= 0 else { continue }
                queue.async { self.acceptedConnection(peer) }
            }
        }
        if config.sentinels.isEmpty {
            say("join: no sentinel is configured")
            joinState = 4
        } else {
            joinState = 1
            joinDelay = config.joinRetryInitialMs
            join(.edge, 1)
        }
    }

    private func acceptedConnection(_ fd: Int32) {
        accepted += 1
        // an accepted connection is closed at once, after its handshake, while the clock cannot be read (clock_fail
        // pause), after the node stopped (clock_back stop), and beyond inflight_max
        let closeWith = ck.closesWith ?? (live >= config.inflightMax ? "inflight_refused" : nil)
        if closeWith == nil { live += 1 }
        let v = snapshot(cid: accepted, dialed: false, count: maxCount)
        Thread.detachNewThread { [self] in
            // the count of accepted connections in hand falls when the connection ends, before its close is complete
            NodeConnection(node: self, v: v).accepted(fd, closeWith: closeWith) {
                if closeWith == nil { self.queue.async { self.live -= 1 } }
            }
        }
    }

    // ---------------------------------------------------------------- the join (design section 6)
    private func join(_ st: PeerType, _ x: Int) {
        if ck == .paused {
            say("join: the request for \(st.rawValue) waits until the system clock is read again")
            joinState = 11 + PeerType.allCases.firstIndex(of: st)!
            return
        }
        if ck == .stopped { return }
        dialedCount += 1
        let cid = dialedCount, s = config.sentinels[x / 2]
        let addr = "\(s.host):\(s.port)"
        say("join: asking the sentinel at \(addr) for \(st.rawValue) d\(cid)")
        dials[cid] = .join(st, x)
        joinPending.insert(st)
        dial(cid, addr, (try? sample(store: st.rawValue, n: Int64(count(st)))) ?? [], count(st))
    }

    private func joinGoesOn(_ st: PeerType, _ x: Int) {
        guard x % 2 == 1 else { return }
        joinDelay = config.joinRetryInitialMs
        if let i = PeerType.allCases.firstIndex(of: st), i < 2 {
            joinState = i + 2
            join(PeerType.allCases[i + 1], 1)
        } else {
            say("join: done")
            joinState = 4
            tell(.joined)
        }
    }

    private func joinFailed(_ st: PeerType, _ x: Int) {
        if x / 2 + 1 < config.sentinels.count {
            join(st, x + 2)
        } else if x % 2 == 1 {
            say("join: no sentinel answered for \(st.rawValue); waiting to try again")
            after(joinDelay, .joinRetry) { [self] in
                if ck != .stopped { join(st, 1) }
            }
            joinState = 1 + PeerType.allCases.firstIndex(of: st)!
            joinDelay = min(joinDelay * 2, config.joinRetryMaxMs)
        } else {
            say("join: no sentinel answered for \(st.rawValue)")
        }
    }

    // ---------------------------------------------------------------- ticks (design 3.2)
    private func arm(_ st: PeerType) {
        after(config.store(st).tickMs, .tick(st)) { [self] in
            arm(st)
            tick(st)
        }
    }

    private func tick(_ st: PeerType) {
        // no tick before the first reading, while the node waits for its clock, or after it stopped
        guard ck.ticks else { return }
        let own = Admission.pre(ownDescriptor, kid: kid, now: now, skew: skew, want: nil).why
        if !own.isEmpty {
            if !ownTokenTold {
                say("own token: \(own); ticking has stopped")
                tell(.ownTokenNotValid(reason: own))
            }
            ownTokenTold = true
            return
        }
        // entries whose token has expired leave the view first (ruling OQ-4)
        let gone = stores[st]!.view.filter { e in now >= ((try? readToken(e.d.token).fields.exp) ?? 0) + skew }
        for e in gone { stores[st]!.drop(e.id) }
        if !gone.isEmpty { say("expired in \(st.rawValue):" + gone.map { " " + id8($0.id) }.joined()) }
        let step = stores[st]!.tick(draws: sources.random.draws(count(st) + 1))
        showView(st)
        let head = "tick \(st.rawValue): "
        switch step {
        case .skipped: say(head + "skipped (no draws)")
        case .aged: say(head + "aged only (a shuffle is in flight)")
        case .empty:
            say(head + "the view is empty")
            // an empty view: the node asks a sentinel again (design section 10)
            if joinState == 4 && !joinPending.contains(st) && !config.sentinels.isEmpty { join(st, 0) }
        case .shuffle(let partner, let out):
            let with = head + "shuffle with \(id8(partner.id))"
            guard dialable(partner.d.addr), let body = try? shuffle(store: st.rawValue, entries: out.map { Entry(age: Int64($0.age), d: $0.d) }) else {
                say(with + ": its address is not one this build dials")
                shuffleFailed(st)
                return
            }
            dialedCount += 1
            let addr = String(decoding: partner.d.addr, as: UTF8.self)
            say(with + " at \(addr) d\(dialedCount)")
            dials[dialedCount] = .shuffle(st)
            dial(dialedCount, addr, body, count(st))
        }
    }

    private func shuffleFailed(_ st: PeerType) {
        stores[st]!.failed()
        showView(st)
        say("tick \(st.rawValue): shuffle failed")
    }

    // ---------------------------------------------------------------- dialed connections
    private func dial(_ cid: Int, _ addr: String, _ request: Bytes, _ count: Int) {
        let v = snapshot(cid: cid, dialed: true, count: count)
        Thread.detachNewThread { [self] in
            let out = NodeConnection(node: self, v: v).dial(addr, request: request)
            queue.async { self.dialed(cid, out) }
        }
    }

    private func dialed(_ cid: Int, _ out: DialOutcome) {
        guard let what = dials.removeValue(forKey: cid) else { return }
        var failure = ""
        var reply: (frame: Frame?, peer: Descriptor, typ: String)?
        switch out {
        case .reply(let frame, let peer, let typ): reply = (frame, peer, typ)
        case .failed(let event): failure = event
        case .keyRotated(let named):
            tell(.keyRotated(kid: named, dialed: true))
            failure = "key_rotated"
        }
        switch what {
        case .shuffle(let st):
            guard let reply else {
                say("tick \(st.rawValue): the partner did not answer, \(failure) d\(cid)")
                shuffleFailed(st)
                return
            }
            guard case .shuffleReply(let store, let entries)? = reply.frame, store == st.rawValue, entries.count <= count(st),
                  stores[st]!.reply(entries.map { ViewEntry(id: $0.d.id, d: $0.d, age: Int($0.age)) }) else {
                shuffleFailed(st)
                return
            }
            showView(st)
            say("tick \(st.rawValue): shuffle merged")
        case .join(let st, let x):
            joinPending.remove(st)
            guard let reply, case .sampleReply(let store, let entries)? = reply.frame else {
                let why = reply == nil ? failure : "a reply that is not a sample_reply"
                say("join: the sentinel did not answer for \(st.rawValue), \(why) d\(cid)")
                joinFailed(st, x)
                return
            }
            say("join: the sentinel answered for \(st.rawValue) d\(cid)")
            if store == st.rawValue {
                for e in entries { stores[st]!.insert(ViewEntry(id: e.d.id, d: e.d, age: Int(e.age))) }
            }
            showView(st)
            // the joiner keeps the sentinel it joined through (ruling NQ-12)
            if reply.typ == PeerType.sentinel.rawValue {
                stores[.sentinel]!.insert(ViewEntry(id: reply.peer.id, d: reply.peer, age: 0))
                showView(.sentinel)
            }
            joinGoesOn(st, x)
        }
    }

    // ---------------------------------------------------------------- what connections ask of the node
    enum Answer { case reply(Bytes), close }

    private func audit(_ event: String, _ peer: Descriptor, _ what: String, _ cid: Int) {
        say("[tempus audit] \(event) peer=\(hex(Array(peer.id.prefix(8)))) \(what) a\(cid)")
    }

    /// The one request of an admitted peer on an accepted connection. Called by the connection's thread.
    func request(_ frame: Frame?, kind: String, peer: Descriptor, typ: String, cid: Int) -> Answer {
        queue.sync {
            switch frame {
            case .shuffle(let store, let entries)?:
                let st = PeerType(rawValue: store)!
                let received = entries.map { ViewEntry(id: $0.d.id, d: $0.d, age: Int($0.age)) }
                guard entries.count <= count(st),
                      let out = stores[st]!.request(asker: peer.id, received: received, draws: sources.random.draws(count(st) + 1)),
                      let body = try? shuffleReply(store: store, entries: out.map { Entry(age: Int64($0.age), d: $0.d) }) else {
                    say("[tempus audit] shuffle_refused peer=- the store refused the frame a\(cid)")
                    return .close
                }
                showView(st)
                return .reply(body)
            case .sample(let store, let n)?:
                let st = PeerType(rawValue: store)!
                guard n <= Int64(count(st)) else {
                    audit("protocol_error", peer, "n is not 1 to the shuffle length", cid)
                    return .close
                }
                let out = stores[st]!.sample(Int(n), draws: sources.random.draws(count(st) + 1))
                // a sentinel inserts the peer that asks it into its store of the peer's type, after the sample was
                // taken (rulings OQ-6, NQ-13), so a joiner is never answered with itself
                if config.role == .sentinel, let pt = PeerType(rawValue: typ) {
                    stores[pt]!.insert(ViewEntry(id: peer.id, d: peer, age: 0))
                    showView(pt)
                }
                guard let out, let body = try? sampleReply(store: store, entries: out.map { Entry(age: Int64($0.age), d: $0.d) }) else {
                    return .close
                }
                return .reply(body)
            default:
                audit("request_refused", peer, "call and cast are served by a bridge only", cid)
                return .close
            }
        }
    }

    /// A refusal of an accepted peer (ruling NQ-19), and key_rotated said by a peer that dialed this node.
    func report(_ e: NodeEvent) {
        queue.async { self.tell(e) }
    }
}
