// Gossip discovery: what makes a client a member of a TEMPUS network instead of a program that sends one request.
// An example only: not for production.
//
//   - the view rules (development-plan/tempus-design.md section 3): ageing, the choice of a partner and of the entries
//     sent, the partner's choice, the merge, the eviction, putting sent entries back;
//   - Store: one of a peer's three stores (edge, bridge, sentinel) and its steps: tick, reply, failed, request, sample,
//     insert, drop;
//   - Peer: a listener, the three stores, one tick timer per store, and the join through the configured sentinels
//     (section 6). It answers the shuffles and samples of admitted peers from its stores, and when its own token says
//     tempus_sentinel it puts every peer that asks it for a sample into its store of that peer's type.
//
// The rules are the node's (src/tempus/bees_tempus_view.silica, bees_tempus_store.silica, bees_tempus_node.part),
// stated again here in Swift. Nothing has a default: capacity, shuffle length and tick of each store, the time bound of
// a connection, the sentinels and the join's retry delays are all values the application passes.
//
// An entry enters a store only after its descriptor verified for that store (Verifier.checkEntry): dial() and Listener
// do that for every entry of a reply and of a shuffle before this file sees it.
import Foundation

public let capacityMax = 256

/// An entry inside a store: the peer's id (the key), its descriptor, its age in ticks.
public struct Held: Equatable {
    public var id: Bytes
    public var d: Descriptor
    public var age: Int64

    public init(id: Bytes, d: Descriptor, age: Int64) {
        self.id = id
        self.d = d
        self.age = age
    }

    public init(_ e: Entry) { self.init(id: e.d.id, d: e.d, age: e.age) }

    public var entry: Entry { Entry(age: age, d: d) }
}

/// `count` draws from the system's secure source, seven bytes each (design 3.5).
public func secureDraws(_ count: Int) -> [UInt64] {
    guard let raw = try? randomBytes(7 * count) else { return [] }
    return (0..<count).map { i in (0..<7).reduce(UInt64(0)) { ($0 << 8) | UInt64(raw[7 * i + $1]) } }
}

private struct Draws {
    var values: [UInt64]
    mutating func take() -> UInt64 { values.isEmpty ? 0 : values.removeFirst() }
}

// ---------------------------------------------------------------- the view rules (design section 3)
/// every age one higher; an age stops at 65535
public func ageAll(_ view: [Held]) -> [Held] {
    view.map { Held(id: $0.id, d: $0.d, age: min($0.age + 1, ageMax)) }
}

/// k entries drawn without replacement, in the order drawn, and what is left
private func pick(_ view: [Held], _ k: Int, _ draws: inout Draws) -> (taken: [Held], left: [Held]) {
    var left = view
    var taken: [Held] = []
    var n = k
    while n > 0 && !left.isEmpty {
        taken.append(left.remove(at: Int(draws.take() % UInt64(left.count))))
        n -= 1
    }
    return (taken, left)
}

/// One tick's choice at the initiator, on a view that is not empty. The partner is the oldest entry (the first draw
/// settles a tie); `sent` are count - 1 others drawn without replacement; `rest` is the view without the partner and
/// without the sent entries.
public func select(_ view: [Held], count: Int, draws values: [UInt64]) -> (partner: Held, sent: [Held], rest: [Held]) {
    var draws = Draws(values: values)
    let top = view.map(\.age).max() ?? 0
    let oldest = view.filter { $0.age == top }
    let partner = oldest[Int(draws.take() % UInt64(oldest.count))]
    let (sent, rest) = pick(view.filter { $0.id != partner.id }, count - 1, &draws)
    return (partner, sent, rest)
}

/// The partner's choice: up to count entries drawn without replacement, never the asker's own.
public func replySelect(_ view: [Held], count: Int, asker: Bytes, draws values: [UInt64]) -> (sent: [Held], rest: [Held]) {
    var draws = Draws(values: values)
    let (sent, _) = pick(view.filter { $0.id != asker }, count, &draws)
    let gone = Set(sent.map(\.id))
    return (sent, view.filter { !gone.contains($0.id) })
}

/// The view after a shuffle. Entries for selfId are dropped; a peer that appears twice is kept once, the younger entry
/// (at equal age the one this peer already had); the result is the winning received entries in arrival order, then
/// the kept ones; then the oldest are evicted down to the capacity (at equal age the latest in order first).
public func merge(_ rest: [Held], received: [Held], selfId: Bytes, capacity: Int) -> [Held] {
    var order: [Bytes] = []
    var best: [Bytes: Held] = [:]
    for e in received where e.id != selfId {
        if let had = best[e.id] {
            if e.age < had.age { best[e.id] = e }
        } else {
            order.append(e.id)
            best[e.id] = e
        }
    }
    let have = Dictionary(rest.map { ($0.id, $0.age) }, uniquingKeysWith: { a, _ in a })
    let win = order.compactMap { best[$0] }.filter { e in have[e.id].map { e.age < $0 } ?? true }
    let won = Set(win.map(\.id))
    var view = win + rest.filter { !won.contains($0.id) }
    while view.count > capacity {
        let top = view.map(\.age).max() ?? 0
        if let last = view.lastIndex(where: { $0.age == top }) { view.remove(at: last) }
    }
    return view
}

/// Ruling NQ-16: a received entry whose peer was just sent, and sent strictly younger, becomes the sent one.
public func preferSent(_ received: [Held], sent: [Held]) -> [Held] {
    var mine: [Bytes: Held] = [:]
    for e in sent where mine[e.id] == nil { mine[e.id] = e }
    return received.map { e in
        if let s = mine[e.id], s.age < e.age { return s }
        return e
    }
}

/// sent entries go back at the end of the view, in order, while there is room; one already there is skipped
public func backfill(_ view: [Held], sent: [Held], capacity: Int) -> [Held] {
    var out = view
    for e in sent where out.count < capacity && !out.contains(where: { $0.id == e.id }) { out.append(e) }
    return out
}

/// one entry enters the view by the merge rules
public func insertEntry(_ view: [Held], _ e: Held, selfId: Bytes, capacity: Int) -> [Held] {
    merge(view, received: [e], selfId: selfId, capacity: capacity)
}

public func takeSample(_ view: [Held], n: Int, draws values: [UInt64]) -> [Held] {
    var draws = Draws(values: values)
    return pick(view, n, &draws).taken
}

// ---------------------------------------------------------------- one store
public enum TickAct {
    /// a shuffle is in flight: the view was aged and nothing else
    case aged
    /// nothing to do
    case empty
    /// the partner and the entries to send it besides the peer's own; they have left the view until reply() or failed()
    case shuffle(partner: Held, others: [Held])
}

/// One store's steps (design sections 3 and 10). It knows nothing of tokens, connections or time: its holder gives it
/// verified entries and draws, and carries out what it answers. `own` says whether the peer's own entry belongs in
/// this store: true only for the store of the peer's own type (ruling OQ-5).
public struct Store {
    public let selfId: Bytes
    public let own: Bool
    public let capacity: Int
    public let count: Int
    public var view: [Held] = []
    public var sent: [Held] = []
    public var partner: Held?            // set while a shuffle this store started is in flight

    public init(selfId: Bytes, own: Bool, capacity: Int, count: Int) {
        self.selfId = selfId
        self.own = own
        self.capacity = capacity
        self.count = count
    }

    public mutating func tick(draws: [UInt64]) -> TickAct {
        let aged = ageAll(view)
        if partner != nil {
            view = aged
            return .aged
        }
        if aged.isEmpty { return .empty }
        let s = select(aged, count: own ? count : count + 1, draws: draws)
        view = s.rest
        sent = s.sent
        partner = s.partner
        return .shuffle(partner: s.partner, others: s.sent)
    }

    /// the partner was unreachable, closed, timed out or violated: it stays out; the other sent entries go back
    public mutating func failed() {
        guard partner != nil else { return }
        view = backfill(view, sent: sent, capacity: capacity)
        sent = []
        partner = nil
    }

    /// the partner's answer, every entry already verified. More than the shuffle length counts as failed.
    public mutating func reply(_ received: [Held]) {
        guard let p = partner else { return }
        if received.count > count {
            failed()
            return
        }
        var merged = merge(view, received: preferSent(received, sent: sent), selfId: selfId, capacity: capacity)
        // ruling NQ-15: in a store that is not of this peer's type the partner cannot hold this peer, so nothing else
        // would bring the link back: the partner that answered re-enters at age 0
        if !own { merged = insertEntry(merged, Held(id: p.id, d: p.d, age: 0), selfId: selfId, capacity: capacity) }
        view = backfill(merged, sent: sent, capacity: capacity)
        sent = []
        partner = nil
    }

    /// A partner's shuffle, every entry already verified: the entries to answer with, or nil when refused (more than
    /// the shuffle length). It does not matter whether a shuffle of this store's own is in flight.
    public mutating func request(asker: Bytes, received: [Held], draws: [UInt64]) -> [Held]? {
        if received.count > count { return nil }
        let (out, kept) = replySelect(view, count: count, asker: asker, draws: draws)
        view = backfill(merge(kept, received: preferSent(received, sent: out), selfId: selfId, capacity: capacity), sent: out,
                        capacity: capacity)
        return out
    }

    /// up to n entries (at most the shuffle length) drawn at random; the view is not changed
    public func sample(n: Int, draws: [UInt64]) -> [Held] { takeSample(view, n: min(n, count), draws: draws) }

    public mutating func insert(_ e: Held) { view = insertEntry(view, e, selfId: selfId, capacity: capacity) }

    public mutating func drop(_ id: Bytes) { view.removeAll { $0.id == id } }
}

// ---------------------------------------------------------------- settings (no defaults: design section 11)
/// capacity 1 to 256; shuffleLength 1 to 64 and at most the capacity; tickMs 100 to 3600000
public struct StoreSettings {
    public let capacity: Int
    public let shuffleLength: Int
    public let tickMs: Int

    public init(capacity: Int, shuffleLength: Int, tickMs: Int) throws {
        guard (1...capacityMax).contains(capacity) else { throw Unencodable("a capacity is 1 to \(capacityMax)") }
        guard (1...entriesMax).contains(shuffleLength), shuffleLength <= capacity else {
            throw Unencodable("a shuffle length is 1 to \(entriesMax) and at most the capacity")
        }
        guard (100...3_600_000).contains(tickMs) else { throw Unencodable("tick_ms is 100 to 3600000") }
        self.capacity = capacity
        self.shuffleLength = shuffleLength
        self.tickMs = tickMs
    }
}

/// stores: one StoreSettings for each of tempus_edge, tempus_bridge and tempus_sentinel; the time bound of a whole
/// connection in ms (100 to 60000); the sentinels as "host:port" texts (none for a first sentinel; at most 16); the
/// join's first and greatest retry delay in ms (100 to 3600000 each).
public struct PeerSettings {
    public let stores: [String: StoreSettings]
    public let shuffleTimeoutMs: Int
    public let sentinels: [String]
    public let joinRetryInitialMs: Int
    public let joinRetryMaxMs: Int

    public init(stores: [String: StoreSettings], shuffleTimeoutMs: Int, sentinels: [String], joinRetryInitialMs: Int,
                joinRetryMaxMs: Int) throws {
        guard Set(stores.keys) == Set(peerTypes) else { throw Unencodable("the three stores are \(peerTypes)") }
        guard (100...60000).contains(shuffleTimeoutMs) else { throw Unencodable("shuffle_timeout_ms is 100 to 60000") }
        guard sentinels.count <= 16 else { throw Unencodable("at most 16 sentinels") }
        guard (100...3_600_000).contains(joinRetryInitialMs), (100...3_600_000).contains(joinRetryMaxMs) else {
            throw Unencodable("a join retry delay is 100 to 3600000 ms")
        }
        self.stores = stores
        self.shuffleTimeoutMs = shuffleTimeoutMs
        self.sentinels = sentinels
        self.joinRetryInitialMs = joinRetryInitialMs
        self.joinRetryMaxMs = joinRetryMaxMs
    }
}

/// the first 8 hex digits of a peer id, as a node prints it in its own lines
public func peer8(_ id: Bytes) -> String { hex(Array(id.prefix(4))) }

// ---------------------------------------------------------------- the peer
/// A member of a TEMPUS network: it listens, joins through its sentinels, ticks its three stores and answers the
/// shuffles and samples of admitted peers.
///
/// identity   this peer's Identity; its address is the one other peers dial, and the one it listens on
/// verifier   its Verifier: producer key, kid, clock, skew and the tempus whitelist
/// settings   a PeerSettings
/// onLine     called with each line the peer has to say (what a node prints: the join, each tick)
/// onLearned  called as onLearned(store, descriptor) when a peer that was not in a store enters it
/// draws      a function count -> that many draws; nil takes them from the system's secure source
///
/// start() begins, stop() ends. view(store) is a copy of a store's entries. newToken(bytes) replaces the peer's own
/// token (the application refreshes it; this library never speaks to the producer).
public final class Peer {
    public private(set) var identity: Identity
    public let verifier: Verifier
    public let settings: PeerSettings
    public let typ: String
    public var onLine: (String) -> Void = { _ in }
    public var onLearned: (String, Descriptor) -> Void = { _, _ in }

    private let host: String
    private let port: Int
    private let address: String
    private let draws: (Int) -> [UInt64]
    private let lock = NSRecursiveLock()
    private let wake = NSCondition()
    private var stopping = false
    private var running = 0
    private var stores: [String: Store] = [:]
    private var listener: Listener?
    private var joined = false
    private var asking: Set<String> = []        // stores for which a sample to a sentinel is on its way
    private var tokenStopped = false

    public init(identity: Identity, verifier: Verifier, settings: PeerSettings, draws: ((Int) -> [UInt64])? = nil) throws {
        guard let addr = identity.addr, let colon = addr.lastIndex(of: ":"), let port = Int(addr[addr.index(after: colon)...]) else {
            throw Unencodable("a peer's identity has a listen address host:port")
        }
        self.identity = identity
        self.verifier = verifier
        self.settings = settings
        self.typ = try readToken(identity.token).fields.typ
        self.host = String(addr[..<colon])
        self.port = port
        self.address = addr
        self.draws = draws ?? secureDraws
        for (t, s) in settings.stores {
            stores[t] = Store(selfId: identity.peerId, own: t == typ, capacity: s.capacity, count: s.shuffleLength)
        }
    }

    // ---- the application's side
    @discardableResult
    public func start() throws -> Peer {
        let longest = settings.stores.values.map(\.shuffleLength).max() ?? 1
        let l = try Listener(identity: identity, verifier: verifier, host: host, port: port,
                             timeout: Double(settings.shuffleTimeoutMs) / 1000.0, shuffleLength: longest) { [unowned self] rq in
            self.serve(rq)
        }
        l.keep = false
        l.current = { [unowned self] in self.current() }
        l.start()
        listener = l
        onLine("\(typ) peer \(peer8(identity.peerId)) listening on \(address)")
        for t in peerTypes {
            if let s = settings.stores[t] { onLine("store \(t): capacity \(s.capacity), shuffle length \(s.shuffleLength)") }
        }
        run { self.join() }
        for t in peerTypes { run { self.ticker(t) } }
        return self
    }

    public func stop() {
        wake.lock()
        stopping = true
        wake.broadcast()
        while running > 0 { wake.wait() }
        wake.unlock()
        listener?.stop()
    }

    public func view(_ store: String) -> [Held] {
        lock.lock()
        defer { lock.unlock() }
        return stores[store]?.view ?? []
    }

    public func newToken(_ token: Bytes) throws {
        lock.lock()
        identity = try Identity(seed: identity.key.seed, token: token, addr: identity.addr, certDER: identity.certDER)
        tokenStopped = false
        lock.unlock()
        onLine("own token replaced")
    }

    // ---- helpers
    private func current() -> Identity {
        lock.lock()
        defer { lock.unlock() }
        return identity
    }

    private func run(_ body: @escaping () -> Void) {
        wake.lock()
        running += 1
        wake.unlock()
        Thread.detachNewThread { [self] in
            body()
            wake.lock()
            running -= 1
            wake.broadcast()
            wake.unlock()
        }
    }

    private var isStopping: Bool {
        wake.lock()
        defer { wake.unlock() }
        return stopping
    }

    /// waits; true when the peer is stopping
    private func pause(ms: Double) -> Bool {
        let until = Date().addingTimeInterval(ms / 1000.0)
        wake.lock()
        defer { wake.unlock() }
        while !stopping {
            if !wake.wait(until: until) { break }
        }
        return stopping
    }

    private func count(_ store: String) -> Int { settings.stores[store]?.shuffleLength ?? 1 }

    /// verified entries enter a store by the merge rules; a peer new to the store is told to the application
    private func put(_ store: String, _ entries: [Held]) {
        lock.lock()
        defer { lock.unlock() }
        for e in entries {
            let before = Set((stores[store]?.view ?? []).map(\.id))
            stores[store]?.insert(e)
            told(store, before)
        }
    }

    private func told(_ store: String, _ before: Set<Bytes>) {
        for e in stores[store]?.view ?? [] where !before.contains(e.id) { onLearned(store, e.d) }
    }

    private func dialFor(_ addr: String, _ request: Bytes, _ store: String) -> Outcome {
        dial(addr, identity: current(), verifier: verifier, request: request, timeout: Double(settings.shuffleTimeoutMs) / 1000.0,
             shuffleLength: count(store))
    }

    private func why(_ out: Outcome) -> String { out.reason.isEmpty ? out.what : out.reason }

    // ---- the join (design section 6): one sample per store to a sentinel
    /// One sample of `store` from the first sentinel that answers. True when one did: its entries are in the store,
    /// and the sentinel itself is in this peer's sentinel store at age 0 (ruling NQ-12).
    private func ask(_ store: String) -> Bool {
        for addr in settings.sentinels {
            if isStopping { return false }
            onLine("join: asking the sentinel at \(addr) for \(store)")
            guard let body = try? sample(store: store, n: Int64(count(store))) else { return false }
            let out = dialFor(addr, body, store)
            guard out.what == "reply", case .sampleReply(let s, let entries)? = out.frame, s == store else {
                onLine("join: the sentinel did not answer for \(store), \(why(out))")
                continue
            }
            onLine("join: the sentinel answered for \(store)")
            put(store, entries.map(Held.init))
            if out.typ == "tempus_sentinel", let sentinel = out.advert {
                put("tempus_sentinel", [Held(id: sentinel.id, d: sentinel, age: 0)])
            }
            return true
        }
        return false
    }

    private func join() {
        if settings.sentinels.isEmpty {
            onLine("join: no sentinel is configured")
            setJoined()
            return
        }
        for store in peerTypes {
            var delay = settings.joinRetryInitialMs
            while !ask(store) {
                if isStopping { return }
                onLine("join: no sentinel answered for \(store); waiting to try again")
                if pause(ms: Double(delay)) { return }
                delay = min(delay * 2, settings.joinRetryMaxMs)
            }
        }
        onLine("join: done")
        setJoined()
    }

    private func setJoined() {
        lock.lock()
        joined = true
        lock.unlock()
    }

    private func askAgain(_ store: String) {
        if !ask(store) && !isStopping { onLine("join: no sentinel answered for \(store)") }
        lock.lock()
        asking.remove(store)
        lock.unlock()
    }

    // ---- ticks (design 3.2 and section 10)
    private func ticker(_ store: String) {
        let every = Double(settings.stores[store]?.tickMs ?? 1000)
        var due = monotonic() * 1000.0 + every
        while !pause(ms: max(0, due - monotonic() * 1000.0)) {
            due += every
            tick(store)
        }
    }

    private func ownTokenWhy() -> String {
        do {
            try verifier.checkEntry(try identity.entry(age: 0), store: typ)
            return ""
        } catch {
            return "\(error)"
        }
    }

    private func expired(_ store: String) {
        let now = verifier.clock()
        let gone = (stores[store]?.view ?? []).filter { e in
            guard let exp = try? readToken(e.d.token).fields.exp else { return true }
            return now >= exp + verifier.skew
        }
        for e in gone { stores[store]?.drop(e.id) }
        if !gone.isEmpty { onLine("expired in \(store): \(gone.map { peer8($0.id) }.joined(separator: " "))") }
    }

    private func tick(_ store: String) {
        var act: TickAct?
        var again = false
        var buffer: [Held] = []
        var said: String?
        lock.lock()
        let why = ownTokenWhy()
        if !why.isEmpty {
            // a peer whose own token is not valid cannot be admitted anywhere: it stops ticking and says so once
            if !tokenStopped {
                tokenStopped = true
                said = "own token: \(why); ticking has stopped"
            }
        } else {
            expired(store)
            let n = (stores[store]?.count ?? 1) + 1
            act = stores[store]?.tick(draws: draws(n))
            switch act {
            case .empty?:
                again = joined && !asking.contains(store) && !settings.sentinels.isEmpty
                if again { asking.insert(store) }
            case .shuffle(_, let others)?:
                let me = (try? identity.descriptor()).map { Held(id: identity.peerId, d: $0, age: 0) }
                buffer = ((stores[store]?.own ?? false) ? [me].compactMap { $0 } : []) + others
            default:
                break
            }
        }
        lock.unlock()
        if let said { onLine(said) }
        switch act {
        case .aged?:
            onLine("tick \(store): aged only (a shuffle is in flight)")
        case .empty?:
            onLine("tick \(store): the view is empty")
            if again { run { self.askAgain(store) } }
        case .shuffle(let partner, _)?:
            run { self.shuffleWith(store, partner, buffer) }
        case nil:
            break
        }
    }

    private func shuffleWith(_ store: String, _ partner: Held, _ buffer: [Held]) {
        let addr = String(decoding: partner.d.addr, as: UTF8.self)
        onLine("tick \(store): shuffle with \(peer8(partner.id)) at \(addr)")
        var received: [Held]?
        var why = ""
        if let body = try? shuffle(store: store, entries: buffer.map(\.entry)) {
            let out = dialFor(addr, body, store)
            if out.what == "reply", case .shuffleReply(let s, let entries)? = out.frame, s == store {
                received = entries.map(Held.init)
            } else {
                why = self.why(out)
            }
        } else {
            why = "the shuffle could not be written"
        }
        lock.lock()
        let before = Set(((stores[store]?.view ?? []) + (stores[store]?.sent ?? [])).map(\.id)).union([partner.id])
        if let received {
            stores[store]?.reply(received)
            told(store, before)
        } else {
            stores[store]?.failed()
        }
        lock.unlock()
        if received == nil {
            onLine("tick \(store): the partner did not answer, \(why)")
            onLine("tick \(store): shuffle failed")
        } else {
            onLine("tick \(store): shuffle merged")
        }
    }

    // ---- an admitted peer's request (the Listener has verified every entry of a shuffle for its store)
    private func serve(_ rq: Request) -> Answer {
        lock.lock()
        defer { lock.unlock() }
        switch rq.frame {
        case .shuffle(let store, let entries):
            guard let st = stores[store] else { return .close }
            let before = Set((st.view + st.sent).map(\.id)).union(st.partner.map { [$0.id] } ?? [])
            guard let out = stores[store]?.request(asker: rq.advert.id, received: entries.map(Held.init), draws: draws(st.count + 1)),
                  let reply = try? shuffleReply(store: store, entries: out.map(\.entry)) else { return .close }
            told(store, before)
            return .reply(reply)
        case .sample(let store, let n):
            guard let st = stores[store], n <= Int64(st.count) else { return .close }
            let out = st.sample(n: Int(n), draws: draws(st.count + 1))
            // the join (design section 6, ruling NQ-13): a sentinel puts every peer that asks it for a sample into its
            // store of that peer's type, after the sample was taken
            if typ == "tempus_sentinel" { put(rq.typ, [Held(id: rq.advert.id, d: rq.advert, age: 0)]) }
            guard let reply = try? sampleReply(store: store, entries: out.map(\.entry)) else { return .close }
            return .reply(reply)
        default:
            return .close
        }
    }
}
