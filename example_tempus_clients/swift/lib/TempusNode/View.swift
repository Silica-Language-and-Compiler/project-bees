// The Cyclon view of one store, as pure functions (development-plan/tempus-design.md section 3), and one store's steps
// over them (sections 3 and 10). The rules are those of src/tempus/bees_tempus_view.silica and
// src/tempus/bees_tempus_store.silica; test/model_check.py compares this file with the two independent Python models
// of the BEES tools (tools/bees_tempus_view_model.py, tools/bees_tempus_store_model.py) on generated cases.
// Nothing here makes a random number, reads a clock or knows a peer type: every function that chooses takes its draws
// as a list of non-negative integers and uses one draw per choice, as an index modulo the number of candidates. A
// missing or negative draw counts as 0.
import TempusClient

/// One entry of a view: the peer's identity, what describes it (opaque here), and its age in ticks.
public struct ViewEntry<P: Sendable>: Sendable {
    public var id: Bytes
    public var d: P
    public var age: Int

    public init(id: Bytes, d: P, age: Int) {
        self.id = id
        self.d = d
        self.age = age
    }
}

struct Draws {
    var values: ArraySlice<Int>

    init(_ values: [Int]) { self.values = values[...] }

    mutating func take() -> Int {
        guard let v = values.popFirst() else { return 0 }
        return v < 0 ? 0 : v
    }
}

/// The view rules. A view is an array of entries with no id twice and none for the node itself, at most `cap` long.
public enum View {
    public static let ageMax = 65535

    /// Every age one higher, stopping at ageMax.
    public static func ageAll<P>(_ v: [ViewEntry<P>]) -> [ViewEntry<P>] {
        v.map { ViewEntry(id: $0.id, d: $0.d, age: min($0.age + 1, ageMax)) }
    }

    /// k entries drawn without replacement, in the order drawn, and what is left, in order.
    static func pick<P>(_ v: [ViewEntry<P>], _ k: Int, _ draws: inout Draws) -> (taken: [ViewEntry<P>], rest: [ViewEntry<P>]) {
        var left = v, taken: [ViewEntry<P>] = []
        var k = k
        while k > 0 && !left.isEmpty {
            taken.append(left.remove(at: draws.take() % left.count))
            k -= 1
        }
        return (taken, left)
    }

    /// One tick's choice at the initiator (the caller has aged the view): the partner is the oldest entry (the first
    /// draw settles a tie), `sent` are count - 1 others drawn without replacement, `rest` is the view without them.
    /// nil on an empty view.
    public static func select<P>(_ v: [ViewEntry<P>], count: Int, draws: [Int])
        -> (partner: ViewEntry<P>, sent: [ViewEntry<P>], rest: [ViewEntry<P>])? {
        guard let top = v.map(\.age).max() else { return nil }
        var ds = Draws(draws)
        let oldest = v.indices.filter { v[$0].age == top }
        let p = oldest[ds.take() % oldest.count]
        var others = v
        let partner = others.remove(at: p)
        let got = pick(others, count - 1, &ds)
        return (partner, got.taken, got.rest)
    }

    /// The partner's choice: up to count entries drawn without replacement, never the asker's own entry; `rest` is the
    /// view without them (the asker's old entry, if any, stays in rest: the merge replaces it).
    public static func replySelect<P>(_ v: [ViewEntry<P>], count: Int, asker: Bytes, draws: [Int])
        -> (sent: [ViewEntry<P>], rest: [ViewEntry<P>]) {
        var ds = Draws(draws)
        let sent = pick(v.filter { $0.id != asker }, count, &ds).taken
        let gone = Set(sent.map(\.id))
        return (sent, v.filter { !gone.contains($0.id) })
    }

    /// The view after a shuffle. Entries for selfId are dropped; a peer received twice is kept once, the younger (the
    /// earlier at equal age), at the place of its first arrival; a received entry wins against the view's entry of the
    /// same peer only when strictly younger; the result is the winners in arrival order, then the kept entries; then
    /// the oldest are evicted down to cap (at equal age the latest in order first).
    public static func merge<P>(_ rest: [ViewEntry<P>], _ received: [ViewEntry<P>], selfId: Bytes, cap: Int) -> [ViewEntry<P>] {
        var once: [ViewEntry<P>] = []
        for e in received where e.id != selfId {
            if let i = once.firstIndex(where: { $0.id == e.id }) {
                if e.age < once[i].age { once[i] = e }
            } else {
                once.append(e)
            }
        }
        var have: [Bytes: Int] = [:]
        for e in rest { have[e.id] = e.age }
        let win = once.filter { e in have[e.id].map { e.age < $0 } ?? true }
        let won = Set(win.map(\.id))
        var view = win + rest.filter { !won.contains($0.id) }
        while view.count > cap {
            let top = view.map(\.age).max()!
            view.remove(at: view.lastIndex(where: { $0.age == top })!)
        }
        return view
    }

    /// Ruling NQ-16 (b): a received entry whose peer was just sent, and sent strictly younger, is replaced by the sent one.
    public static func preferSent<P>(_ received: [ViewEntry<P>], _ sent: [ViewEntry<P>]) -> [ViewEntry<P>] {
        received.map { e in
            if let s = sent.first(where: { $0.id == e.id }), s.age < e.age { return s }
            return e
        }
    }

    /// Entries of `sent` go back at the end of the view, in order, while there is room; one already there is skipped.
    public static func backfill<P>(_ v: [ViewEntry<P>], _ sent: [ViewEntry<P>], cap: Int) -> [ViewEntry<P>] {
        var view = v
        for e in sent where view.count < cap && !view.contains(where: { $0.id == e.id }) { view.append(e) }
        return view
    }

    /// One entry enters the view by the merge rules.
    public static func insert<P>(_ v: [ViewEntry<P>], _ e: ViewEntry<P>, selfId: Bytes, cap: Int) -> [ViewEntry<P>] {
        merge(v, [e], selfId: selfId, cap: cap)
    }

    /// Up to n entries drawn without replacement; the view is not changed.
    public static func sample<P>(_ v: [ViewEntry<P>], _ n: Int, draws: [Int]) -> [ViewEntry<P>] {
        var ds = Draws(draws)
        return pick(v, n, &ds).taken
    }

    /// The invariants: at most cap entries, no id twice, no empty id, none for selfId, every age in 0...ageMax.
    public static func valid<P>(_ v: [ViewEntry<P>], selfId: Bytes, cap: Int) -> Bool {
        v.count <= cap && Set(v.map(\.id)).count == v.count
            && v.allSatisfy { !$0.id.isEmpty && $0.id != selfId && $0.age >= 0 && $0.age <= ageMax }
    }
}

/// What a tick did.
public enum TickStep<P: Sendable>: Sendable {
    /// No draws were given: the tick is skipped whole.
    case skipped
    /// A shuffle of this store is in flight: the view was aged and nothing else.
    case aged
    /// The view is empty.
    case empty
    /// The buffer `out` goes to `partner`; the partner and the sent entries have left the view.
    case shuffle(partner: ViewEntry<P>, out: [ViewEntry<P>])
}

/// One of a node's three stores. It knows nothing of types, connections, tokens or time: its owner feeds it events
/// and carries out what it answers. `own` says whether the node's own entry belongs in it (true only for the store of
/// the node's own type, ruling OQ-5).
public struct Store<P: Sendable>: Sendable {
    public private(set) var view: [ViewEntry<P>] = []
    public private(set) var sent: [ViewEntry<P>] = []
    public private(set) var partner: ViewEntry<P>?
    public var me: ViewEntry<P>
    public let own: Bool
    public let cap: Int
    public let count: Int

    public init(selfId: Bytes, selfD: P, own: Bool, cap: Int, count: Int) {
        me = ViewEntry(id: selfId, d: selfD, age: 0)
        self.own = own
        self.cap = cap
        self.count = count
    }

    /// True while a shuffle this store started is in flight.
    public var shuffling: Bool { partner != nil }

    public mutating func tick(draws: [Int]?) -> TickStep<P> {
        guard let draws else { return .skipped }
        let aged = View.ageAll(view)
        if partner != nil {
            view = aged
            return .aged
        }
        guard let sel = View.select(aged, count: own ? count : count + 1, draws: draws) else { return .empty }
        view = sel.rest
        sent = sel.sent
        partner = sel.partner
        return .shuffle(partner: sel.partner, out: own ? [me] + sel.sent : sel.sent)
    }

    /// The partner was unreachable, closed, timed out or violated: it stays out, the other sent entries are put back.
    public mutating func failed() {
        guard partner != nil else { return }
        view = View.backfill(view, sent, cap: cap)
        sent = []
        partner = nil
    }

    /// The partner's answer. False when it held more than `count` entries, which counts as a failed shuffle.
    @discardableResult
    public mutating func reply(_ received: [ViewEntry<P>]) -> Bool {
        guard let p = partner else { return true }
        if received.count > count {
            failed()
            return false
        }
        var m = View.merge(view, View.preferSent(received, sent), selfId: me.id, cap: cap)
        if !own {      // ruling NQ-15: the partner that answered re-enters at age 0
            m = View.insert(m, ViewEntry(id: p.id, d: p.d, age: 0), selfId: me.id, cap: cap)
        }
        view = View.backfill(m, sent, cap: cap)
        sent = []
        partner = nil
        return true
    }

    /// A partner's shuffle arrives. nil when refused (no draws, or more than `count` entries); else the answer.
    public mutating func request(asker: Bytes, received: [ViewEntry<P>], draws: [Int]?) -> [ViewEntry<P>]? {
        guard let draws, received.count <= count else { return nil }
        let r = View.replySelect(view, count: count, asker: asker, draws: draws)
        let m = View.merge(r.rest, View.preferSent(received, r.sent), selfId: me.id, cap: cap)
        view = View.backfill(m, r.sent, cap: cap)
        return r.sent
    }

    /// Up to n entries (at most `count`); the view is not changed. nil when refused.
    public func sample(_ n: Int, draws: [Int]?) -> [ViewEntry<P>]? {
        guard let draws, n >= 1 else { return nil }
        return View.sample(view, min(n, count), draws: draws)
    }

    public mutating func insert(_ e: ViewEntry<P>) { view = View.insert(view, e, selfId: me.id, cap: cap) }

    public mutating func drop(_ id: Bytes) { view.removeAll { $0.id == id } }
}
