// EXAMPLE ONLY, not for production. See README.md beside the lib directory.
//
// Gossip discovery: what makes a client a member of a TEMPUS network instead of a program that sends one request.
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
// stated again here in Kotlin. Nothing has a default: capacity, shuffle length and tick of each store, the time bound
// of a connection, the sentinels and the join's retry delays are all values the application passes.
//
// An entry enters a store only after its descriptor verified for that store (Verifier.checkEntry): dial() and Listener
// do that for every entry of a reply and of a shuffle before this file sees it.
package bees.tempus

import java.security.SecureRandom

const val CAPACITY_MAX = 256

/** An entry inside a store: the peer's id as hex (the key), its descriptor, its age in ticks. */
class Held(val id: String, val d: Descriptor, val age: Int) {
    constructor(e: Entry) : this(hex(e.d.id), e.d, e.age)
    fun entry() = Entry(age, d)
    fun aged(to: Int) = Held(id, d, to)
    override fun equals(other: Any?) = other is Held && id == other.id && age == other.age && d == other.d
    override fun hashCode() = id.hashCode()
    override fun toString() = "${id.take(8)}@$age"
}

/** `count` draws from the system's secure source, seven bytes each (design 3.5). */
fun secureDraws(random: SecureRandom, count: Int): List<Long> {
    val raw = ByteArray(7 * count)
    random.nextBytes(raw)
    return (0 until count).map { i -> (0 until 7).fold(0L) { acc, k -> (acc shl 8) or (raw[7 * i + k].toLong() and 0xff) } }
}

private class Draws(values: List<Long>) {
    private val left = ArrayDeque(values)
    fun take(): Long {
        val v = if (left.isEmpty()) 0L else left.removeFirst()
        return if (v >= 0) v else 0L
    }
}

// ---------------------------------------------------------------- the view rules (design section 3)
/** every age one higher; an age stops at 65535 */
fun ageAll(view: List<Held>): List<Held> = view.map { it.aged(minOf(it.age + 1, AGE_MAX)) }

/** k entries drawn without replacement, in the order drawn, and what is left */
private fun pick(view: List<Held>, k: Int, draws: Draws): Pair<List<Held>, List<Held>> {
    val left = ArrayList(view)
    val taken = ArrayList<Held>()
    var n = k
    while (n > 0 && left.isNotEmpty()) {
        taken.add(left.removeAt((draws.take() % left.size).toInt()))
        n -= 1
    }
    return taken to left
}

class Selected(val partner: Held, val sent: List<Held>, val rest: List<Held>)

/**
 * One tick's choice at the initiator, on a view that is not empty. The partner is the oldest entry (the first draw
 * settles a tie); `sent` are count - 1 others drawn without replacement; `rest` is the view without the partner and
 * without the sent entries.
 */
fun select(view: List<Held>, count: Int, drawValues: List<Long>): Selected {
    val draws = Draws(drawValues)
    val top = view.maxOf { it.age }
    val oldest = view.filter { it.age == top }
    val partner = oldest[(draws.take() % oldest.size).toInt()]
    val (sent, rest) = pick(view.filter { it.id != partner.id }, count - 1, draws)
    return Selected(partner, sent, rest)
}

/** The partner's choice: (sent, rest). Up to count entries drawn without replacement, never the asker's own. */
fun replySelect(view: List<Held>, count: Int, asker: String, drawValues: List<Long>): Pair<List<Held>, List<Held>> {
    val (sent, _) = pick(view.filter { it.id != asker }, count, Draws(drawValues))
    val gone = sent.map { it.id }.toSet()
    return sent to view.filter { it.id !in gone }
}

/**
 * The view after a shuffle. Entries for selfId are dropped; a peer that appears twice is kept once, the younger entry
 * (at equal age the one this peer already had); the result is the winning received entries in arrival order, then the
 * kept ones; then the oldest are evicted down to the capacity (at equal age the latest in order first).
 */
fun merge(rest: List<Held>, received: List<Held>, selfId: String, capacity: Int): List<Held> {
    val order = ArrayList<String>()
    val best = HashMap<String, Held>()
    for (e in received) {
        if (e.id == selfId) continue
        val had = best[e.id]
        if (had == null) {
            order.add(e.id)
            best[e.id] = e
        } else if (e.age < had.age) {
            best[e.id] = e
        }
    }
    val have = rest.associate { it.id to it.age }
    val win = order.map { best.getValue(it) }.filter { val a = have[it.id]; a == null || it.age < a }
    val won = win.map { it.id }.toSet()
    val view = ArrayList(win + rest.filter { it.id !in won })
    while (view.size > capacity) {
        val top = view.maxOf { it.age }
        view.removeAt(view.indexOfLast { it.age == top })
    }
    return view
}

/** Ruling NQ-16: a received entry whose peer was just sent, and sent strictly younger, becomes the sent one. */
fun preferSent(received: List<Held>, sent: List<Held>): List<Held> {
    val mine = HashMap<String, Held>()
    for (e in sent) mine.putIfAbsent(e.id, e)
    return received.map { e -> val s = mine[e.id]; if (s != null && s.age < e.age) s else e }
}

/** sent entries go back at the end of the view, in order, while there is room; one already there is skipped */
fun backfill(view: List<Held>, sent: List<Held>, capacity: Int): List<Held> {
    val out = ArrayList(view)
    for (e in sent) if (out.size < capacity && out.none { it.id == e.id }) out.add(e)
    return out
}

/** one entry enters the view by the merge rules */
fun insertEntry(view: List<Held>, e: Held, selfId: String, capacity: Int): List<Held> = merge(view, listOf(e), selfId, capacity)

fun takeSample(view: List<Held>, n: Int, drawValues: List<Long>): List<Held> = pick(view, n, Draws(drawValues)).first

// ---------------------------------------------------------------- one store
sealed class TickAct {
    /** a shuffle is in flight: the view was aged and nothing else */
    object Aged : TickAct()
    /** nothing to do */
    object Empty : TickAct()
    /** the partner and the entries to send it besides the peer's own; they have left the view until reply() or failed() */
    class Shuffle(val partner: Held, val others: List<Held>) : TickAct()
}

/**
 * One store's steps (design sections 3 and 10). It knows nothing of tokens, connections or time: its holder gives it
 * verified entries and draws, and carries out what it answers. `own` says whether the peer's own entry belongs in this
 * store: true only for the store of the peer's own type (ruling OQ-5).
 */
class Store(val selfId: String, val own: Boolean, val capacity: Int, val count: Int) {
    var view: List<Held> = emptyList()
    var sent: List<Held> = emptyList()
    var partner: Held? = null            // set while a shuffle this store started is in flight

    fun tick(draws: List<Long>): TickAct {
        val aged = ageAll(view)
        if (partner != null) {
            view = aged
            return TickAct.Aged
        }
        if (aged.isEmpty()) return TickAct.Empty
        val s = select(aged, if (own) count else count + 1, draws)
        view = s.rest
        sent = s.sent
        partner = s.partner
        return TickAct.Shuffle(s.partner, s.sent)
    }

    /** the partner was unreachable, closed, timed out or violated: it stays out; the other sent entries go back */
    fun failed() {
        if (partner == null) return
        view = backfill(view, sent, capacity)
        sent = emptyList()
        partner = null
    }

    /** the partner's answer, every entry already verified. More than the shuffle length counts as failed. */
    fun reply(received: List<Held>) {
        val p = partner ?: return
        if (received.size > count) {
            failed()
            return
        }
        var merged = merge(view, preferSent(received, sent), selfId, capacity)
        // ruling NQ-15: in a store that is not of this peer's type the partner cannot hold this peer, so nothing else
        // would bring the link back: the partner that answered re-enters at age 0
        if (!own) merged = insertEntry(merged, p.aged(0), selfId, capacity)
        view = backfill(merged, sent, capacity)
        sent = emptyList()
        partner = null
    }

    /**
     * A partner's shuffle, every entry already verified: the entries to answer with, or null when refused (more than
     * the shuffle length). It does not matter whether a shuffle of this store's own is in flight.
     */
    fun request(asker: String, received: List<Held>, draws: List<Long>): List<Held>? {
        if (received.size > count) return null
        val (out, kept) = replySelect(view, count, asker, draws)
        view = backfill(merge(kept, preferSent(received, out), selfId, capacity), out, capacity)
        return out
    }

    /** up to n entries (at most the shuffle length) drawn at random; the view is not changed */
    fun sample(n: Int, draws: List<Long>): List<Held> = takeSample(view, minOf(n, count), draws)

    fun insert(e: Held) {
        view = insertEntry(view, e, selfId, capacity)
    }

    fun drop(id: String) {
        view = view.filter { it.id != id }
    }
}

// ---------------------------------------------------------------- settings (no defaults: design section 11)
/** capacity 1 to 256; shuffleLength 1 to 64 and at most the capacity; tickMs 100 to 3600000 */
class StoreSettings(val capacity: Int, val shuffleLength: Int, val tickMs: Long) {
    init {
        require(capacity in 1..CAPACITY_MAX) { "a capacity is 1 to $CAPACITY_MAX" }
        require(shuffleLength in 1..ENTRIES_MAX && shuffleLength <= capacity) { "a shuffle length is 1 to $ENTRIES_MAX and at most the capacity" }
        require(tickMs in 100..3600000) { "tick_ms is 100 to 3600000" }
    }
}

/**
 * stores: one StoreSettings for each of tempus_edge, tempus_bridge and tempus_sentinel; the time bound of a whole
 * connection in ms (100 to 60000); the sentinels as "host:port" texts (none for a first sentinel; at most 16); the
 * join's first and greatest retry delay in ms (100 to 3600000 each).
 */
class PeerSettings(val stores: Map<String, StoreSettings>, val shuffleTimeoutMs: Long, val sentinels: List<String>,
                   val joinRetryInitialMs: Long, val joinRetryMaxMs: Long) {
    init {
        require(stores.keys == PEER_TYPES.toSet()) { "the three stores are $PEER_TYPES" }
        require(shuffleTimeoutMs in 100..60000) { "shuffle_timeout_ms is 100 to 60000" }
        require(sentinels.size <= 16) { "at most 16 sentinels" }
        require(joinRetryInitialMs in 100..3600000 && joinRetryMaxMs in 100..3600000) { "a join retry delay is 100 to 3600000 ms" }
    }
}

/** the first 8 hex digits of a peer id, as a node prints it in its own lines */
fun peer8(idHex: String): String = idHex.take(8)

// ---------------------------------------------------------------- the peer
/**
 * A member of a TEMPUS network: it listens, joins through its sentinels, ticks its three stores and answers the
 * shuffles and samples of admitted peers.
 *
 * identity   this peer's Identity; its address is the one other peers dial
 * verifier   its Verifier: producer key, kid, clock, skew and the tempus whitelist
 * settings   a PeerSettings
 * host, port where it listens
 * onLine     called with each line the peer has to say (what a node prints: the join, each tick)
 * onLearned  called as onLearned(store, descriptor) when a peer that was not in a store enters it
 * draws      a function count -> that many non-negative integers; the default is the system's secure source
 *
 * start() begins, stop() ends. view(store) is a copy of a store's entries. newToken(bytes) replaces the peer's own
 * token (the application refreshes it; this library never speaks to the producer).
 */
class Peer(identity: Identity, val verifier: Verifier, val settings: PeerSettings, private val host: String, private val port: Int,
           private val onLine: (String) -> Unit = {}, private val onLearned: (String, Descriptor) -> Unit = { _, _ -> },
           draws: ((Int) -> List<Long>)? = null) {
    @Volatile var identity: Identity = identity
        private set
    val typ: String = readToken(identity.token).typ
    private val random = SecureRandom()
    private val draws: (Int) -> List<Long> = draws ?: { n -> secureDraws(random, n) }
    private val lock = Object()
    private val selfId = hex(identity.peerId)
    private val stores: Map<String, Store> = settings.stores.mapValues { (t, s) -> Store(selfId, t == typ, s.capacity, s.shuffleLength) }
    @Volatile private var stopping = false
    private val wake = Object()
    private val threads = ArrayList<Thread>()
    private var listener: Listener? = null
    @Volatile private var joined = false
    private val asking = HashSet<String>()          // stores for which a sample to a sentinel is on its way
    private var tokenStopped = false

    // ---- the application's side
    fun start(): Peer {
        val longest = settings.stores.values.maxOf { it.shuffleLength }
        listener = Listener(identity, verifier, Settings(settings.shuffleTimeoutMs, longest), host, port, keep = false,
            current = { this.identity }) { serve(it) }
        onLine("$typ peer ${peer8(selfId)} listening on ${identity.addr}")
        for (t in PEER_TYPES) {
            val s = settings.stores.getValue(t)
            onLine("store $t: capacity ${s.capacity}, shuffle length ${s.shuffleLength}")
        }
        run { join() }
        for (t in PEER_TYPES) run { ticker(t) }
        return this
    }

    fun stop() {
        stopping = true
        synchronized(wake) { wake.notifyAll() }
        while (true) {
            val t = synchronized(threads) { threads.firstOrNull { it.isAlive } } ?: break
            t.join()
        }
        listener?.close()
    }

    fun view(store: String): List<Held> = synchronized(lock) { ArrayList(stores.getValue(store).view) }

    fun newToken(token: ByteArray) {
        synchronized(lock) {
            identity = identity.withToken(token)
            tokenStopped = false
        }
        onLine("own token replaced")
    }

    // ---- helpers
    private fun run(body: () -> Unit) {
        val t = Thread(body)
        t.isDaemon = true
        synchronized(threads) {
            threads.removeAll { !it.isAlive }
            threads.add(t)
        }
        t.start()
    }

    /** waits; true when the peer is stopping */
    private fun pause(ms: Long): Boolean {
        val until = System.nanoTime() + ms * 1_000_000
        synchronized(wake) {
            while (!stopping) {
                val left = (until - System.nanoTime()) / 1_000_000
                if (left <= 0) break
                wake.wait(left)
            }
        }
        return stopping
    }

    private fun count(store: String) = settings.stores.getValue(store).shuffleLength

    /** verified entries enter a store by the merge rules; a peer new to the store is told to the application */
    private fun put(store: String, entries: List<Held>) {
        synchronized(lock) {
            val st = stores.getValue(store)
            for (e in entries) {
                val before = st.view.map { it.id }.toSet()
                st.insert(e)
                told(store, before)
            }
        }
    }

    private fun told(store: String, before: Set<String>) {
        for (e in stores.getValue(store).view) if (e.id !in before) onLearned(store, e.d)
    }

    private fun dialFor(addr: String, request: Request, store: String): Outcome =
        dial(addr, identity, verifier, request, Settings(settings.shuffleTimeoutMs, count(store)), random)

    private fun why(out: Outcome) = out.reason.ifEmpty { out.what }

    // ---- the join (design section 6): one sample per store to a sentinel
    /**
     * One sample of `store` from the first sentinel that answers. True when one did: its entries are in the store, and
     * the sentinel itself is in this peer's sentinel store at age 0 (ruling NQ-12).
     */
    private fun ask(store: String): Boolean {
        for (addr in settings.sentinels) {
            if (stopping) return false
            onLine("join: asking the sentinel at $addr for $store")
            val out = dialFor(addr, Request.Sample(store, count(store)), store)
            val body = out.body
            if (out.what != "reply" || body !is Body.Entries) {
                onLine("join: the sentinel did not answer for $store, ${why(out)}")
                continue
            }
            onLine("join: the sentinel answered for $store")
            put(store, body.entries.map { Held(it) })
            val sentinel = out.advert
            if (out.typ == "tempus_sentinel" && sentinel != null) put("tempus_sentinel", listOf(Held(hex(sentinel.id), sentinel, 0)))
            return true
        }
        return false
    }

    private fun join() {
        if (settings.sentinels.isEmpty()) {
            onLine("join: no sentinel is configured")
            joined = true
            return
        }
        for (store in PEER_TYPES) {
            var delay = settings.joinRetryInitialMs
            while (!ask(store)) {
                if (stopping) return
                onLine("join: no sentinel answered for $store; waiting to try again")
                if (pause(delay)) return
                delay = minOf(delay * 2, settings.joinRetryMaxMs)
            }
        }
        onLine("join: done")
        joined = true
    }

    private fun askAgain(store: String) {
        try {
            if (!ask(store) && !stopping) onLine("join: no sentinel answered for $store")
        } finally {
            synchronized(lock) { asking.remove(store) }
        }
    }

    // ---- ticks (design 3.2 and section 10)
    private fun ticker(store: String) {
        val every = settings.stores.getValue(store).tickMs
        var due = System.nanoTime() / 1_000_000 + every
        while (!pause(maxOf(0L, due - System.nanoTime() / 1_000_000))) {
            due += every
            tick(store)
        }
    }

    private fun ownTokenWhy(): String = try {
        verifier.checkEntry(identity.descriptor(), typ)
        ""
    } catch (e: Refused) {
        e.why
    }

    private fun expired(store: String) {
        val now = verifier.now()
        val st = stores.getValue(store)
        val gone = st.view.filter { now >= readToken(it.d.token).exp + verifier.skew }
        for (e in gone) st.drop(e.id)
        if (gone.isNotEmpty()) onLine("expired in $store: ${gone.joinToString(" ") { peer8(it.id) }}")
    }

    private fun tick(store: String) {
        var act: TickAct? = null
        var again = false
        var buffer: List<Held> = emptyList()
        var said: String? = null
        synchronized(lock) {
            val why = ownTokenWhy()
            if (why.isNotEmpty()) {
                // a peer whose own token is not valid cannot be admitted anywhere: it stops ticking and says so once
                if (!tokenStopped) {
                    tokenStopped = true
                    said = "own token: $why; ticking has stopped"
                }
                return@synchronized
            }
            expired(store)
            val st = stores.getValue(store)
            val a = st.tick(draws(st.count + 1))
            act = a
            if (a is TickAct.Empty) {
                again = joined && store !in asking && settings.sentinels.isNotEmpty()
                if (again) asking.add(store)
            } else if (a is TickAct.Shuffle) {
                buffer = (if (st.own) listOf(Held(selfId, identity.descriptor(), 0)) else emptyList()) + a.others
            }
        }
        said?.let { onLine(it) }
        when (val a = act) {
            null -> {}
            is TickAct.Aged -> onLine("tick $store: aged only (a shuffle is in flight)")
            is TickAct.Empty -> {
                onLine("tick $store: the view is empty")
                if (again) run { askAgain(store) }
            }
            is TickAct.Shuffle -> run { shuffle(store, a.partner, buffer) }
        }
    }

    private fun shuffle(store: String, partner: Held, buffer: List<Held>) {
        val addr = partner.d.addrText()
        onLine("tick $store: shuffle with ${peer8(partner.id)} at $addr")
        var received: List<Held>? = null
        var why = ""
        val at = addr.lastIndexOf(':')
        if (at <= 0 || addr.substring(at + 1).toIntOrNull() == null) {
            why = "its address is not one this peer dials"
        } else {
            val out = dialFor(addr, Request.Shuffle(store, buffer.map { it.entry() }), store)
            val body = out.body
            if (out.what == "reply" && body is Body.Entries) received = body.entries.map { Held(it) } else why = why(out)
        }
        synchronized(lock) {
            val st = stores.getValue(store)
            val before = (st.view + st.sent).map { it.id }.toSet() + partner.id
            val got = received
            if (got == null) {
                st.failed()
            } else {
                st.reply(got)
                told(store, before)
            }
        }
        if (received == null) {
            onLine("tick $store: the partner did not answer, $why")
            onLine("tick $store: shuffle failed")
        } else {
            onLine("tick $store: shuffle merged")
        }
    }

    // ---- an admitted peer's request (the Listener has verified every entry of a shuffle for its store)
    private fun serve(rq: Incoming): List<Entry>? {
        when (val b = rq.body) {
            is Body.Entries -> synchronized(lock) {
                val st = stores.getValue(b.store)
                val before = (st.view + st.sent).map { it.id }.toSet() + listOfNotNull(st.partner?.id)
                val out = st.request(hex(rq.peer.id), b.entries.map { Held(it) }, draws(st.count + 1)) ?: return null
                told(b.store, before)
                return out.map { it.entry() }
            }
            is Body.Sample -> synchronized(lock) {
                if (b.n > count(b.store)) return null
                val st = stores.getValue(b.store)
                val out = st.sample(b.n, draws(st.count + 1))
                // the join (design section 6, ruling NQ-13): a sentinel puts every peer that asks it for a sample into
                // its store of that peer's type, after the sample was taken
                if (typ == "tempus_sentinel") put(rq.typ, listOf(Held(hex(rq.peer.id), rq.peer, 0)))
                return out.map { it.entry() }
            }
            else -> return null
        }
    }
}
