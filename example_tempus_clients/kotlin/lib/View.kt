// A usable example, to be used carefully. See README.md beside the lib directory.
//
// The view of one store and the steps of one store: the rules of development-plan/tempus-design.md section 3 (the
// Cyclon view, with the rulings OQ-5, OQ-12, NQ-15 and NQ-16), equal in behaviour to the Silica units
// src/tempus/bees_tempus_view.silica and bees_tempus_store.silica. Pure: nothing here reads a clock, makes a random
// number or touches a connection. Every function that chooses takes its draws as a list of numbers and uses one
// draw per choice, as an index modulo the number of candidates; a missing or negative draw counts as 0.
package bees.tempus

/** One entry of a view: the peer's identifier as text, what the holder keeps for it, and its age in ticks. */
class Held<D>(val id: String, val d: D, val age: Int) {
    override fun equals(other: Any?) = other is Held<*> && id == other.id && d == other.d && age == other.age
    override fun hashCode() = id.hashCode() * 31 + age
    override fun toString() = "$id:$age"
}

/** The pure view functions. A view is a list of entries with no identifier twice and none for the node itself. */
object View {
    private class Draws(values: List<Long>) {
        private val left = ArrayDeque(values)
        fun take(): Long {
            val v = if (left.isEmpty()) 0L else left.removeFirst()
            return if (v >= 0) v else 0L
        }
    }

    /** Every age one higher; an age stops at 65535. */
    fun <D> ageAll(view: List<Held<D>>): List<Held<D>> = view.map { Held(it.id, it.d, minOf(it.age + 1, AGE_MAX)) }

    /** k entries drawn without replacement, in the order drawn, and what is left. */
    private fun <D> pick(view: List<Held<D>>, k: Int, draws: Draws): Pair<List<Held<D>>, List<Held<D>>> {
        val left = ArrayList(view)
        val taken = ArrayList<Held<D>>()
        var n = k
        while (n > 0 && left.isNotEmpty()) {
            taken.add(left.removeAt((draws.take() % left.size).toInt()))
            n -= 1
        }
        return taken to left
    }

    class Selected<D>(val partner: Held<D>?, val sent: List<Held<D>>, val rest: List<Held<D>>)

    /**
     * One tick's choice at the initiator (the caller has aged the view): the partner is the oldest entry (the first
     * draw settles a tie); length - 1 others are drawn to be sent; rest is the view without them all. The partner is
     * null on an empty view.
     */
    fun <D> select(view: List<Held<D>>, length: Int, draws: List<Long>): Selected<D> {
        if (view.isEmpty()) return Selected(null, emptyList(), emptyList())
        val ds = Draws(draws)
        val top = view.maxOf { it.age }
        val oldest = view.filter { it.age == top }
        val partner = oldest[(ds.take() % oldest.size).toInt()]
        val (sent, rest) = pick(view.filter { it.id != partner.id }, length - 1, ds)
        return Selected(partner, sent, rest)
    }

    /** The buffer for the partner: the node's own entry at age 0, then the entries chosen. */
    fun <D> outgoing(selfId: String, selfD: D, sent: List<Held<D>>): List<Held<D>> = listOf(Held(selfId, selfD, 0)) + sent

    /** The partner's choice: up to length entries, never the asker's own; and the view without them. */
    fun <D> replySelect(view: List<Held<D>>, length: Int, asker: String, draws: List<Long>): Pair<List<Held<D>>, List<Held<D>>> {
        val (sent, _) = pick(view.filter { it.id != asker }, length, Draws(draws))
        val gone = sent.map { it.id }.toSet()
        return sent to view.filter { it.id !in gone }
    }

    /**
     * The view after a shuffle: entries for the node itself are dropped; a peer in both is kept once, the younger
     * entry (at equal age the one the node had); the winning received entries come first, in the order of their first
     * arrival; then the oldest are evicted down to the capacity (at equal age the latest in the view's order).
     */
    fun <D> merge(rest: List<Held<D>>, received: List<Held<D>>, selfId: String, cap: Int): List<Held<D>> {
        val order = ArrayList<String>()
        val best = HashMap<String, Held<D>>()
        for (e in received) {
            if (e.id == selfId) continue
            val had = best[e.id]
            if (had == null) { order.add(e.id); best[e.id] = e } else if (e.age < had.age) best[e.id] = e
        }
        val have = rest.associate { it.id to it.age }
        val win = order.map { best.getValue(it) }.filter { have[it.id].let { a -> a == null || it.age < a } }
        val won = win.map { it.id }.toSet()
        val view = ArrayList(win + rest.filter { it.id !in won })
        while (view.size > cap) {
            val top = view.maxOf { it.age }
            view.removeAt(view.indexOfLast { it.age == top })
        }
        return view
    }

    /** Ruling NQ-16: a received entry whose peer was just sent, the sent one strictly younger, becomes the sent one. */
    fun <D> preferSent(received: List<Held<D>>, sent: List<Held<D>>): List<Held<D>> {
        val ages = HashMap<String, Held<D>>()
        for (e in sent) ages.putIfAbsent(e.id, e)
        return received.map { e -> ages[e.id]?.takeIf { it.age < e.age } ?: e }
    }

    /** Entries of sent go back at the end of the view, in order, while there is room; one already there is skipped. */
    fun <D> backfill(view: List<Held<D>>, sent: List<Held<D>>, cap: Int): List<Held<D>> {
        val out = ArrayList(view)
        for (e in sent) if (out.size < cap && out.none { it.id == e.id }) out.add(e)
        return out
    }

    /** One entry enters the view by the merge rules. */
    fun <D> insert(view: List<Held<D>>, e: Held<D>, selfId: String, cap: Int): List<Held<D>> = merge(view, listOf(e), selfId, cap)

    /** Up to n entries drawn without replacement; the view is not changed. */
    fun <D> sample(view: List<Held<D>>, n: Int, draws: List<Long>): List<Held<D>> = pick(view, n, Draws(draws)).first

    /** At most cap entries, no identifier twice, none empty, none for the node itself, every age 0 to 65535. */
    fun <D> valid(view: List<Held<D>>, selfId: String, cap: Int): Boolean =
        view.size <= cap && view.map { it.id }.toSet().size == view.size &&
            view.all { it.id.isNotEmpty() && it.id != selfId && it.age in 0..AGE_MAX }
}

/** What one tick of a store did. */
sealed class Tick<out D> {
    /** no tick draws: the tick was skipped whole */
    object Skipped : Tick<Nothing>()
    /** a shuffle of this store is in flight: the view was aged and nothing else */
    object Aged : Tick<Nothing>()
    /** the view is empty: nothing to do in this store */
    object Empty : Tick<Nothing>()
    /** a shuffle begins: dial the partner and send it the buffer */
    class Shuffle<D>(val partner: Held<D>, val buffer: List<Held<D>>) : Tick<D>()
}

/**
 * One store's state and steps. own says whether the node's own entry belongs in this store (true only for the store
 * of the node's own type, ruling OQ-5). The two sets of draws are each used once and then gone until the holder gives
 * new ones: nothing is ever chosen without a draw.
 */
class Store<D>(val selfId: String, selfD: D, val own: Boolean, val cap: Int, val count: Int) {
    var selfD: D = selfD
    var view: List<Held<D>> = emptyList()
    var sent: List<Held<D>> = emptyList()
    /** set while a shuffle this store started is in flight */
    var partner: Held<D>? = null
    var tickDraws: List<Long>? = null
    var replyDraws: List<Long>? = null

    val inFlight: Boolean get() = partner != null

    fun insert(e: Held<D>) { view = View.insert(view, e, selfId, cap) }

    fun drop(id: String) { view = view.filter { it.id != id } }

    fun tick(): Tick<D> {
        val draws = tickDraws ?: return Tick.Skipped
        val aged = View.ageAll(view)
        if (partner != null) { view = aged; return Tick.Aged }
        if (aged.isEmpty()) return Tick.Empty
        val sel = View.select(aged, if (own) count else count + 1, draws)
        tickDraws = null
        view = sel.rest; sent = sel.sent; partner = sel.partner
        return Tick.Shuffle(sel.partner!!, if (own) View.outgoing(selfId, selfD, sel.sent) else sel.sent)
    }

    /** The partner was unreachable, closed, timed out or violated: it stays out, the other sent entries go back. */
    fun failed() {
        if (partner == null) return
        view = View.backfill(view, sent, cap)
        sent = emptyList(); partner = null
    }

    /** The partner's answer. False when it held more entries than the shuffle length, which counts as failed. */
    fun reply(received: List<Held<D>>): Boolean {
        val p = partner ?: return true
        if (received.size > count) { failed(); return false }
        var merged = View.merge(view, View.preferSent(received, sent), selfId, cap)
        // ruling NQ-15: in a store that is not of the node's own type the partner that answered re-enters at age 0
        if (!own) merged = View.insert(merged, Held(p.id, p.d, 0), selfId, cap)
        view = View.backfill(merged, sent, cap)
        sent = emptyList(); partner = null
        return true
    }

    /** A partner's shuffle: the entries answered, or null when refused (too many entries, or no reply draws). */
    fun request(asker: String, received: List<Held<D>>): List<Held<D>>? {
        val draws = replyDraws
        if (received.size > count || draws == null) return null
        val (out, kept) = View.replySelect(view, count, asker, draws)
        replyDraws = null
        view = View.backfill(View.merge(kept, View.preferSent(received, out), selfId, cap), out, cap)
        return out
    }

    /** Up to n entries (at most the shuffle length); the view is not changed. Null when refused. */
    fun sample(n: Int): List<Held<D>>? {
        val draws = replyDraws
        if (n < 1 || draws == null) return null
        val out = View.sample(view, minOf(n, count), draws)
        replyDraws = null
        return out
    }
}
