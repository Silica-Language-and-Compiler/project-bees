// EXAMPLE ONLY, not for production. See README.md beside the lib directory.
//
// A TEMPUS node: an edge or a sentinel (never a bridge, which is also a TRUST node). It does what the Silica node of
// src/tempus does (development-plan/tempus-design.md sections 3 to 6 and 8 to 11): it reads the clock, listens, joins
// through its sentinels, ticks its three stores on their timers, starts shuffles and answers shuffles and samples,
// admits peers with every check of section 4, and tells its application what the Silica node tells its own. The
// lines it writes are the Silica node's lines, word for word, so an operator can compare the two.
//
// Who owns what. All of the node's state (the three stores, the clock state, the node's token and producer key, the
// counts of connections, the join) belongs to ONE thread, the node thread. Everything else posts a message to it:
// the timers, the clock reader, the acceptor, each connection, and the application's calls. A connection runs on a
// thread of its own (a virtual thread) with a copy of the values it needs, taken on the node thread when the
// connection begins; it never touches a store. The application's listener is called on the node thread, in order.
//
// The clock, the timers and the draws come from a NodeEnvironment. NodeEnvironment.system() is the machine's clock,
// real timers and the platform's secure random source: an application passes nothing. A test passes its own.
package bees.tempus

import java.io.IOException
import java.net.InetSocketAddress
import java.net.ServerSocket
import java.net.Socket
import java.net.SocketTimeoutException
import java.security.SecureRandom
import java.security.cert.X509Certificate
import java.util.concurrent.CompletableFuture
import java.util.concurrent.Executors
import java.util.concurrent.RejectedExecutionException
import java.util.concurrent.ScheduledThreadPoolExecutor
import java.util.concurrent.TimeUnit
import javax.net.ssl.SSLException
import javax.net.ssl.SSLSocket

/** What a node tells its application. */
sealed class NodeEvent {
    /** The node's own token is not valid any more and ticking has stopped, until the application passes a new one. */
    class OwnTokenInvalid(val why: String) : NodeEvent()
    /** A peer answered this node's advert with key_rotated; kid is the kid it named. The application fetches a new token. */
    class KeyRotated(val kid: ByteArray) : NodeEvent()
    /** The system clock could not be read; what says what that means for the node. Told once per failure. */
    class ClockUnreadable(val what: String) : NodeEvent()
    /** The node has stopped for good after its clock went back by more than clock_back_limit_s. Only a new node ends this. */
    class Stopped(val why: String) : NodeEvent()
    /** The node could not listen on its address. */
    class ListenFailed(val why: String) : NodeEvent()
    /** The view of one store after a step that may have changed it, in the view's order. */
    class ViewChanged(val store: String, val entries: List<Entry>) : NodeEvent()
}

fun interface NodeListener {
    /** Called on the node's own thread, in order. It must return soon; it may call the node's methods. */
    fun onEvent(node: TempusNode, event: NodeEvent)
}

/** Runs an action once, later. name says what the timer is for: "clock", "tick tempus_edge", "join tempus_edge". */
fun interface NodeTimers {
    fun after(ms: Long, name: String, action: () -> Unit)
}

/** The draws of one choice of one store: count numbers, each 0 or more; null when the random source gave none. */
fun interface DrawSource {
    fun draws(store: String, count: Int): List<Long>?
}

/** Real timers: one thread that only starts the actions. */
class SystemTimers : NodeTimers, AutoCloseable {
    private val pool = ScheduledThreadPoolExecutor(1) { r -> Thread(r, "tempus-timers").also { it.isDaemon = true } }
    override fun after(ms: Long, name: String, action: () -> Unit) {
        try { pool.schedule(action, ms, TimeUnit.MILLISECONDS) } catch (e: RejectedExecutionException) { }
    }
    override fun close() { pool.shutdownNow() }
}

/** Draws from the platform's secure random source, seven bytes each (design 3.5). */
class SecureDraws(private val random: SecureRandom) : DrawSource {
    override fun draws(store: String, count: Int): List<Long>? {
        val raw = ByteArray(7 * count)
        random.nextBytes(raw)
        return List(count) { i -> (0 until 7).fold(0L) { acc, k -> (acc shl 8) or (raw[7 * i + k].toLong() and 0xff) } }
    }
}

/**
 * Where a node takes the time, its timers, its draws, its nonces, and where its lines go. system() is what an
 * application uses. The other constructor is for a test, which supplies its own clock, timers and draws.
 */
class NodeEnvironment(val clock: WallClock, val timers: NodeTimers, val draws: DrawSource, val random: SecureRandom, val log: (String) -> Unit) {
    companion object {
        /** The machine's clock, real timers, the platform's secure random source; lines go to the standard output. */
        fun system(log: (String) -> Unit = { println(it) }): NodeEnvironment {
            val random = SecureRandom()
            return NodeEnvironment(SystemWallClock, SystemTimers(), SecureDraws(random), random, log)
        }
    }
}

/** The values one connection needs, copied on the node thread when the connection begins. */
internal class ConnValues(val me: Identity, val kid: ByteArray, val producerKey: ByteArray, val now: Long, val skew: Long,
                          val whitelist: List<String>, val count: Int, val timeoutMs: Long)

/** An admitted peer's request, handed to the node thread, which completes `answer` with the reply body, or null to close. */
internal class PeerRequest(val cid: Int, val kind: String, val bytes: ByteArray, val body: Body?, val why: String, val peer: Descriptor, val typ: String,
                           val answer: CompletableFuture<ByteArray?>)

internal sealed class Dialed {
    class Reply(val body: Body, val peer: Descriptor, val typ: String) : Dialed()
    class Failed(val event: String) : Dialed()
    class Rotated(val kid: ByteArray) : Dialed()
}

private class Ended(val event: String, val kid: ByteArray? = null) : Exception()

/** The first eight hex digits of an identifier: how the node's own lines name a peer (an audit line shows sixteen). */
private fun peer8(id: ByteArray): String = hex(id.copyOf(4))

/** Why a descriptor's token is refused before any key operation, in the Silica node's order and words; null when it passes. */
internal fun preWhy(d: Descriptor, kid: ByteArray, now: Long, skew: Long, want: String?): Pair<String?, Token?> {
    val t = try { readToken(d.token) } catch (e: Refused) { return e.why to null }
    if (!t.kid.contentEquals(kid)) return "key_rotated" to t
    if (now < t.nbf - skew) return "the token is not valid yet" to t
    if (now >= t.exp + skew) return "the token has expired" to t
    if (!t.sub.contentEquals(d.pub)) return "sub is not the peer's key" to t
    if (want != null && t.typ != want) return "typ is not the store's type" to t
    return null to t
}

/** Why a gossiped entry of the named store does not verify without contact; null when it does. */
internal fun entryWhy(d: Descriptor, store: String, v: ConnValues): String? {
    val (why, t) = preWhy(d, v.kid, v.now, v.skew, store)
    if (why != null) return why
    if (!peerId(d.pub).contentEquals(d.id)) return "id is not the SHA-512 of pub"
    if (!ed25519Verify(v.producerKey, t!!.payload, t.sig)) return "the signature does not verify"
    return null
}

// The atoms a program that is a Silica TEMPUS node holds for the wire: every atom of src/tempus/bees_tempus.atoms and
// every atom of src/trust/bees_trust.atoms (frame keys and kinds, `erlang`, the language's rejection atoms and the
// results of a TRUST call), in the order of those two files. The Silica reader refuses a map that names any other atom
// as unknown_atom, which is what a production node says of the test unit's tick and clock frames; this set lets this
// node say the same, and lets it read a call such as erlang:ok/0 as a call, which it then refuses as a request.
private val WIRE_ATOMS = setOf(
    "advert", "pop_challenge", "pop_response", "key_rotated", "shuffle", "shuffle_reply", "sample", "sample_reply", "done", "tempus_edge",
    "tempus_bridge", "tempus_sentinel", "d", "id", "pub", "addr", "nonce", "sig", "kid", "store", "entries", "age", "n", "sub", "typ", "nbf", "exp",
    "t", "ver", "req_id", "m", "f", "a", "args", "opts", "value", "token", "deadline_ms", "hello", "token_present", "token_issue", "call", "cast",
    "result", "goaway", "erlang", "bad_version", "truncated", "trailing_bytes", "bad_tag", "too_large", "too_deep", "too_long", "out_of_range",
    "unknown_atom", "bad_variant", "missing_field", "duplicate_field", "unknown_field", "unsupported", "ok", "error", "dns_error", "connect_failed",
    "closed", "timeout", "protocol_error", "server_not_pinned")

/**
 * The name of a frame's kind (the atom under `t`), or null when the body is not one well-formed map that names a kind.
 * The second value is why such a body is no request, in the Silica reader's words.
 */
internal fun kindOf(bytes: ByteArray): Pair<String?, String> {
    val m = try { etfDecode(bytes) as? TMap ?: return null to "bad_tag" } catch (e: Refused) { return null to e.why }
    val t = (m.fields["t"] as? TAtom)?.name
    fun strange(x: Term): Boolean = when (x) {
        is TAtom -> x.name !in WIRE_ATOMS
        is TList -> x.items.any { strange(it) }
        is TMap -> x.fields.any { it.key !in WIRE_ATOMS || strange(it.value) }
        else -> false
    }
    if (strange(m)) return null to "unknown_atom"
    return t to "unknown kind"
}

class TempusNode private constructor(private val config: TempusConfig, identity: Identity, private val listener: NodeListener,
                                     private val env: NodeEnvironment) : AutoCloseable {
    companion object {
        /**
         * Starts a node. ConfigRefused when the configuration or the identity is refused: the line "tempus: boot
         * refused: WHY" is written and nothing is started. The node reads its clock at once and listens when the
         * first reading has come.
         */
        fun start(config: TempusConfig, identity: Identity, listener: NodeListener, environment: NodeEnvironment = NodeEnvironment.system()): TempusNode {
            startRefusal(config, identity)?.let { why ->
                environment.log("tempus: boot refused: $why")
                (environment.timers as? AutoCloseable)?.close()
                throw ConfigRefused(why)
            }
            val node = TempusNode(config, identity, listener, environment)
            node.post { node.readClock() }
            return node
        }
    }

    private val exec = Executors.newSingleThreadExecutor { r -> Thread(r, "tempus-node").also { it.isDaemon = true } }
    private val types = PEER_TYPES
    private val whitelist: List<String> = config.whitelist.values.map { fingerprint(it) }
    private val sentinels: List<String> = config.sentinels.map { it.address }
    private val myId = hex(identity.peerId)

    // ---- the node's state: read and written on the node thread only
    private var me: Identity = identity
    private var kid: ByteArray = config.producerKid
    private var producerKey: ByteArray = config.producerKey
    private val stores: Map<String, NodeStore<Descriptor>> = types.associateWith { t ->
        NodeStore(myId, identity.descriptor(), t == config.typ, config.store(t).capacity, config.store(t).shuffleLength)
    }
    private var now = 0L
    private var ck = ClockState.NO_READING
    private var live = 0                    // accepted connections in hand
    private var accepted = 0                // the number of the last accepted connection
    private var dialed = 0                  // the number of the last dialed connection
    private var tokenStop = false           // ticking has stopped for the node's own token
    private var joinStore = 0               // 0 not begun; 1 to 3 the store the join is at; 4 done; 10 + store: it waits for the clock
    private var joinDelay = config.joinRetryInitialMs
    private val joinInFlight = HashSet<String>()
    private var server: ServerSocket? = null
    @Volatile private var closed = false

    private fun say(line: String) = env.log(line)

    private fun post(action: () -> Unit) {
        try {
            exec.execute {
                if (closed) return@execute
                try { action() } catch (e: Exception) { say("internal error: ${e.javaClass.simpleName}: ${e.message}") }
            }
        } catch (e: RejectedExecutionException) { }
    }

    private fun tell(event: NodeEvent) {
        try { listener.onEvent(this, event) } catch (e: Exception) { say("internal error: the application's listener failed: ${e.javaClass.simpleName}: ${e.message}") }
    }

    // ---------------------------------------------------------------- what the application may call
    /** A new token from the producer. The node's own entry carries it from the next shuffle on, and ticking starts again. */
    fun setToken(token: ByteArray) = post {
        me = me.withToken(token)
        tokenStop = false
        say("own token replaced")
        for (s in stores.values) s.selfD = me.descriptor()
    }

    /** A new producer key (ruling NQ-5): its kid and the 32 raw bytes of the key. */
    fun setProducerKey(newKid: ByteArray, key: ByteArray) {
        require(newKid.size in 1..64 && key.size == 32) { "a producer key is a kid of 1 to 64 bytes and a 32-byte key" }
        post {
            kid = newKid; producerKey = key
            say("producer key replaced, kid ${String(newKid, Charsets.UTF_8)}")
        }
    }

    /**
     * Up to n entries of one of the node's stores, drawn at random (at most the store's shuffle length): how an
     * application finds a bridge to call. The view is not changed. Completes with an empty list when there is none.
     */
    fun sample(store: String, n: Int): CompletableFuture<List<Entry>> {
        require(store in types) { "a store is one of $types" }
        val out = CompletableFuture<List<Entry>>()
        post {
            val s = stores.getValue(store)
            refill(store)
            out.complete(s.sample(n)?.map { Entry(it.age, it.d) } ?: emptyList())
            refill(store)
        }
        return out
    }

    /** Stops the node: it listens no more, its timers do nothing more, and connections in hand end by their bound. */
    override fun close() {
        closed = true
        try { server?.close() } catch (e: IOException) { }
        (env.timers as? AutoCloseable)?.close()
        exec.shutdown()
    }

    // ---------------------------------------------------------------- the stores
    private fun refill(typ: String) {
        val s = stores.getValue(typ)
        if (s.tickDraws == null) s.tickDraws = env.draws.draws(typ, s.count + 1)
        if (s.replyDraws == null) s.replyDraws = env.draws.draws(typ, s.count + 1)
    }

    private fun held(e: Entry) = NodeHeld(hex(e.d.id), e.d, e.age)

    private fun show(typ: String) = tell(NodeEvent.ViewChanged(typ, stores.getValue(typ).view.map { Entry(it.age, it.d) }))

    private fun values(count: Int) = ConnValues(me, kid, producerKey, now, config.skewSeconds, whitelist, count, config.shuffleTimeoutMs)

    private fun maxCount() = types.maxOf { config.store(it).shuffleLength }

    // ---------------------------------------------------------------- the clock
    private fun readClock() {
        val n = try { env.clock.seconds() } catch (e: Exception) { null }
        env.timers.after(config.clockReadMs, "clock") { post { readClock() } }
        reading(n)
    }

    private fun reading(n: Long?) {
        val limit = config.clockBackLimitS ?: 0
        val t = clockTurn(ck, now, n, config.clockBack, limit, config.clockFail)
        if (t.again) say("clock: the system clock is read again")
        val back = "the system clock went back by ${now - (n ?: 0)} s"
        val stop = "$back, more than clock_back_limit_s $limit: the node has stopped; it admits no connection and does not tick until its application starts it again"
        fun unreadable(what: String) { say("clock: $what"); tell(NodeEvent.ClockUnreadable(what)) }
        var listen = false
        when (t.say) {
            ClockSay.FIRST -> { say("clock: the system clock is read"); listen = true }
            ClockSay.NONE_AT_START -> unreadable("the system clock could not be read: the node has not started")
            ClockSay.FAILED_PAUSE -> unreadable("the system clock could not be read: the node admits no connection and does not tick until it is read again")
            ClockSay.FAILED_CONTINUE -> unreadable("the system clock could not be read: the node goes on with its last reading")
            ClockSay.BACK_FOLLOWED -> say("clock: $back; the node follows it")
            ClockSay.BACK_HELD -> say("clock: $back; the node holds its time until the system clock has reached it")
            ClockSay.HOLD_ENDED -> say("clock: the system clock has reached the held time; the node follows it again")
            ClockSay.BACK_STOP -> { say("clock: $stop"); tell(NodeEvent.Stopped(stop)) }
        }
        now = t.now; ck = t.ck
        if (listen) listen()
        // the join request that waited for the clock is made at once when the clock is read again (ruling 1.d)
        if (t.again && joinStore > 10) { joinStore -= 10; join(types[joinStore - 1], 0, true) }
    }

    // ---------------------------------------------------------------- listening
    private fun listen() {
        val s = ServerSocket()
        try {
            s.reuseAddress = true
            s.bind(InetSocketAddress(config.listenAddress, config.port), 64)
        } catch (e: IOException) {
            say("the listening link has gone down")
            tell(NodeEvent.ListenFailed(e.message ?: "the address could not be bound"))
            return
        }
        server = s
        Thread.ofVirtual().name("tempus-accept").start {
            while (!closed) {
                val raw = try { s.accept() } catch (e: IOException) { break }
                val at = System.nanoTime()
                post { onAccepted(raw, at) }
            }
            if (!closed) post { say("the listening link has gone down"); tell(NodeEvent.ListenFailed("the listener closed")) }
        }
        say("${config.typ} node ${peer8(me.peerId)} listening on ${me.addr}")
        for (t in types) say("store $t: capacity ${config.store(t).capacity}, shuffle length ${config.store(t).shuffleLength}")
        for (t in types) refill(t)
        for (t in types) armTick(t)
        if (sentinels.isEmpty()) {
            say("join: no sentinel is configured"); joinStore = 4
        } else {
            joinStore = 1; join(types[0], 0, true)
        }
    }

    private fun onAccepted(raw: Socket, at: Long) {
        accepted += 1
        val cid = accepted
        val closes = ClockState.closes(ck)
        val role = closes ?: if (live >= config.inflightMax) "inflight_refused" else null
        if (role == null) live += 1
        val v = values(maxCount())
        Thread.ofVirtual().name("tempus-a$cid").start {
            try {
                NodeConn(this, v, "a$cid").accepted(raw, at, role, cid)
            } catch (e: Exception) {
                say("internal error: connection a$cid: ${e.javaClass.simpleName}: ${e.message}")
                try { raw.close() } catch (x: IOException) { }
            } finally {
                if (role == null) post { live -= 1 }
            }
        }
    }

    // ---------------------------------------------------------------- the join (section 6)
    /** index: which sentinel; start: part of the join at start (it goes on to the next store and retries). */
    private fun join(typ: String, index: Int, start: Boolean) {
        if (ck == ClockState.PAUSED) {
            say("join: the request for $typ waits until the system clock is read again")
            joinStore = 10 + types.indexOf(typ) + 1
            return
        }
        if (ck == ClockState.STOPPED) return
        dialed += 1
        val cid = dialed
        val addr = sentinels[index]
        val count = config.store(typ).shuffleLength
        say("join: asking the sentinel at $addr for $typ d$cid")
        joinInFlight.add(typ)
        dial(addr, bees.tempus.sample(typ, count), cid, values(count)) { out -> joined(typ, index, start, cid, out) }
    }

    private fun joined(typ: String, index: Int, start: Boolean, cid: Int, out: Dialed) {
        joinInFlight.remove(typ)
        val body = (out as? Dialed.Reply)?.body
        if (out is Dialed.Reply && body is Body.Entries && body.kind == "sample_reply") {
            say("join: the sentinel answered for $typ d$cid")
            val s = stores.getValue(typ)
            if (body.store == typ && body.entries.size <= s.count) for (e in body.entries) s.insert(held(e))
            show(typ)
            if (out.typ == "tempus_sentinel") {
                // ruling NQ-12: a joiner keeps the sentinel it joined through, at age 0, after the sample's entries
                stores.getValue("tempus_sentinel").insert(NodeHeld(hex(out.peer.id), out.peer, 0))
                show("tempus_sentinel")
            }
            if (!start) return
            val at = types.indexOf(typ)
            joinDelay = config.joinRetryInitialMs
            if (at < 2) { joinStore = at + 2; join(types[at + 1], 0, true) } else { say("join: done"); joinStore = 4 }
            return
        }
        val what = when (out) {
            is Dialed.Failed -> out.event
            is Dialed.Rotated -> "key_rotated"
            is Dialed.Reply -> "the reply is not a sample_reply"
        }
        say("join: the sentinel did not answer for $typ, $what d$cid")
        if (index + 1 < sentinels.size) { join(typ, index + 1, start); return }
        if (!start) { say("join: no sentinel answered for $typ"); return }
        say("join: no sentinel answered for $typ; waiting to try again")
        val store = types.indexOf(typ) + 1
        env.timers.after(joinDelay, "join $typ") { post { if (ck != ClockState.STOPPED) join(typ, 0, true) } }
        joinStore = store
        joinDelay = minOf(joinDelay * 2, config.joinRetryMaxMs)
    }

    // ---------------------------------------------------------------- ticks
    private fun armTick(typ: String): Unit = env.timers.after(config.store(typ).tickMs, "tick $typ") { post { armTick(typ); tick(typ) } }

    private fun tick(typ: String) {
        // no tick before the first reading, none while the node waits for its clock, none after it stopped
        if (!ClockState.ticks(ck)) return
        val (why, _) = preWhy(me.descriptor(), kid, now, config.skewSeconds, null)
        if (why != null) {
            if (!tokenStop) { say("own token: $why; ticking has stopped"); tell(NodeEvent.OwnTokenInvalid(why)) }
            tokenStop = true
            return
        }
        val s = stores.getValue(typ)
        // entries whose token has expired leave the view first (ruling OQ-4; the window is admission's)
        val gone = s.view.filter { e -> (try { readToken(e.d.token).exp } catch (x: Refused) { 0L }).let { now >= it + config.skewSeconds } }
        for (e in gone) s.drop(e.id)
        if (gone.isNotEmpty()) say("expired in $typ:" + gone.joinToString("") { " " + peer8(it.d.id) })
        refill(typ)
        val t = s.tick()
        refill(typ)
        show(typ)
        when (t) {
            is Tick.Skipped -> say("tick $typ: skipped (no draws)")
            is Tick.Aged -> say("tick $typ: aged only (a shuffle is in flight)")
            is Tick.Empty -> {
                say("tick $typ: the view is empty")
                // an empty view: the node asks a sentinel again
                if (joinStore == 4 && typ !in joinInFlight && sentinels.isNotEmpty()) join(typ, 0, false)
            }
            is Tick.Shuffle -> {
                val d = t.partner.d
                val head = "tick $typ: shuffle with ${peer8(d.id)}"
                if (!dialable(d.addrText())) {
                    say("$head: its address is not one this build dials")
                    endShuffle(typ, null)
                    return
                }
                dialed += 1
                val cid = dialed
                say("$head at ${d.addrText()} d$cid")
                dial(d.addrText(), shuffle(typ, t.buffer.map { Entry(it.age, it.d) }), cid, values(s.count)) { out ->
                    val body = (out as? Dialed.Reply)?.body
                    if (out is Dialed.Reply) {
                        endShuffle(typ, (body as? Body.Entries)?.takeIf { it.kind == "shuffle_reply" && it.store == typ })
                    } else {
                        say("tick $typ: the partner did not answer, ${(out as? Dialed.Failed)?.event ?: "key_rotated"} d$cid")
                        endShuffle(typ, null)
                    }
                }
            }
        }
    }

    /** The shuffle this store started has ended: with the partner's entries, or failed (reply null). */
    private fun endShuffle(typ: String, reply: Body.Entries?) {
        val s = stores.getValue(typ)
        if (!s.inFlight) return
        val merged = reply != null && s.reply(reply.entries.map { held(it) })
        if (reply == null) s.failed()
        show(typ)
        say("tick $typ: " + if (merged) "shuffle merged" else "shuffle failed")
    }

    // ---------------------------------------------------------------- dialing
    private fun dial(addr: String, request: ByteArray, cid: Int, v: ConnValues, then: (Dialed) -> Unit) {
        Thread.ofVirtual().name("tempus-d$cid").start {
            val out = try {
                NodeConn(this, v, "d$cid").dial(addr, request)
            } catch (e: Exception) {
                say("internal error: connection d$cid: ${e.javaClass.simpleName}: ${e.message}")
                Dialed.Failed("internal_error")
            }
            post {
                if (out is Dialed.Rotated) tell(NodeEvent.KeyRotated(out.kid))
                then(out)
            }
        }
    }

    // ---------------------------------------------------------------- an admitted peer's request
    internal fun request(r: PeerRequest) = post { r.answer.complete(answer(r)) }

    /** The peer of an accepted connection answered this node's advert with key_rotated. */
    internal fun rotated(kid: ByteArray) = post { tell(NodeEvent.KeyRotated(kid)) }

    private fun refuse(r: PeerRequest, event: String, what: String): ByteArray? {
        say("[tempus audit] $event peer=${r.peer.id8()} $what a${r.cid}")
        return null
    }

    private fun answer(r: PeerRequest): ByteArray? {
        when (r.kind) {
            "shuffle" -> {
                val b = r.body as Body.Entries
                val s = stores.getValue(b.store)
                refill(b.store)
                val out = s.request(hex(r.peer.id), b.entries.map { held(it) })
                refill(b.store)
                if (out == null) {
                    say("[tempus audit] shuffle_refused peer=- the store refused the frame a${r.cid}")
                    return null
                }
                show(b.store)
                return shuffleReply(b.store, out.map { Entry(it.age, it.d) })
            }
            "sample" -> {
                val b = r.body as? Body.Sample ?: return refuse(r, "protocol_error", r.why)
                val s = stores.getValue(b.store)
                if (b.n > s.count) return refuse(r, "protocol_error", "n is not 1 to the shuffle length")
                refill(b.store)
                val out = s.sample(b.n)
                refill(b.store)
                // a sentinel inserts the peer that asks into its store of the peer's type, after the sample was taken
                // (ruling NQ-13), so a joiner is never answered with itself
                if (config.role == "sentinel") {
                    stores.getValue(r.typ).insert(NodeHeld(hex(r.peer.id), r.peer, 0))
                    show(r.typ)
                }
                return out?.let { sampleReply(b.store, it.map { e -> Entry(e.age, e.d) }) }
            }
            else -> return refuse(r, "request_refused", "call and cast are served by a bridge only")
        }
    }

    internal fun line(text: String) = say(text)
    internal val random: SecureRandom get() = env.random
}

/** One connection of a node, on its own thread. It holds copies only; what it learns goes to the node thread. */
internal class NodeConn(private val node: TempusNode, private val v: ConnValues, private val tag: String) {
    private var peer: Descriptor? = null

    private fun audit(event: String, what: String) = node.line("[tempus audit] $event peer=${peer?.id8() ?: "-"} $what $tag")

    private fun refuse(event: String, what: String): Nothing {
        audit(event, what)
        throw Ended(event)
    }

    /** TLS on a connected socket: the peer's certificate, or Ended after the audit line. */
    private fun handshake(socket: SSLSocket, trust: SelfSignedEd25519, client: Boolean, deadline: Long): X509Certificate {
        val side = if (client) "client" else "server"
        fun text(why: String): Pair<String, String> = when {
            why.contains("no certificate") -> "tls_verify_failed" to "the peer presented no certificate"
            why.contains("not Ed25519") -> "tempus_cert_key" to "the peer certificate's key is not Ed25519"
            why.contains("not self-signed") -> "tls_verify_failed" to "the peer certificate did not pass the engine's check"
            why.contains("ALPN") -> "alpn_mismatch" to "the peer did not agree on ALPN tempus/1"
            else -> "tls_handshake_failed" to "the TLS 1.3 handshake failed (alert, version, group, suite or signature outside the tempus/1 profile)"
        }
        try {
            socket.useClientMode = client
            restrict(socket)
            socket.soTimeout = ((deadline - System.nanoTime()) / 1_000_000).toInt().coerceAtLeast(1)
            socket.startHandshake()
            val cert = tlsChecks(socket)
            audit("tls_established", "$TLS_VERSION $TLS_GROUP ${socket.session.cipherSuite} alpn $ALPN, mutual, as $side")
            return cert
        } catch (e: Exception) {
            try { socket.close() } catch (x: IOException) { }
            val (event, what) = when {
                e is SocketTimeoutException -> "timeout" to "stage tls_handshake"
                e is Refused -> text(e.why)
                trust.refused != null -> text(trust.refused!!)
                e is SSLException && (e.message ?: "").contains("application", ignoreCase = true) -> text("ALPN")
                e is SSLException && (e.message ?: "").contains("certificate chain", ignoreCase = true) -> text("no certificate")
                e is SSLException -> text("")
                else -> "closed_by_peer" to "stage tls_handshake"
            }
            refuse(event, "$what, as $side")
        }
    }

    private fun next(conn: Conn, stage: String): ByteArray = when (val r = conn.read()) {
        is Read.Frame -> r.body
        is Read.Oversize -> refuse("protocol_error", "frame refused before decoding: too_large")
        is Read.Ended -> if (r.what == "timeout") refuse("timeout", "stage $stage") else refuse("closed_by_peer", "stage $stage")
    }

    private fun <T> read(event: String, block: () -> T): T = try { block() } catch (e: Refused) { refuse(event, e.why) }

    /** Admission, the same at both ends (design sections 4 and 5). Returns the type in the peer's token. */
    private fun admit(conn: Conn, certificate: X509Certificate): String {
        conn.send(frame(advert(v.me.descriptor())))
        val first = next(conn, "advert")
        if (kindOf(first).first != "advert") refuse("protocol_error", "the first frame is not an advert")
        val d = read("protocol_error") { (readBody(first, ENTRIES_MAX) as Body.Advert).d }
        peer = d
        // the channel binding: the advert's pub must be the key of the certificate the handshake proved the peer holds
        if (!certificateKey(certificate).contentEquals(d.pub)) refuse("binding_refused", "the advert's pub is not the key of the peer's TLS certificate")
        val (why, token) = preWhy(d, v.kid, v.now, v.skew, null)
        if (why == "key_rotated") {
            // the one exception to silence: one key_rotated frame, then what the peer still sends is read and dropped
            // until it closes or the connection's bound passes, so that a reset cannot destroy the frame
            conn.send(frame(keyRotated(v.kid)))
            audit("key_rotated", "the peer's token is under another kid; it was told the current one")
            while (conn.read() is Read.Frame) { }
            throw Ended("key_rotated_sent")
        }
        if (why != null) refuse("admission_refused", why)
        val typ = token!!.typ
        val listed = v.whitelist.indexOf(fingerprint(certificate))
        if (typ == "tempus_edge" && listed >= 0) refuse("whitelist_reject", "a certificate of the tempus whitelist with a token whose typ is not tempus_bridge or tempus_sentinel")
        if (typ != "tempus_edge" && listed < 0) refuse("whitelist_reject", "a tempus_bridge or tempus_sentinel token under a certificate that is not in the tempus whitelist")
        if (!peerId(d.pub).contentEquals(d.id)) refuse("admission_refused", "id is not the SHA-512 of pub")
        if (!ed25519Verify(v.producerKey, token.payload, token.sig)) refuse("admission_refused", "the signature does not verify")
        val nonce = ByteArray(32)
        node.random.nextBytes(nonce)
        conn.send(frame(challenge(nonce)))
        val second = next(conn, "challenge")
        when (kindOf(second).first) {
            "key_rotated" -> {
                val named = read("protocol_error") { (readBody(second, ENTRIES_MAX) as Body.KeyRotated).kid }
                audit("key_rotated", "the peer says this node's token is under another kid than its current one")
                throw Ended("key_rotated", named)
            }
            "pop_challenge" -> {}
            else -> refuse("protocol_error", "a challenge was expected")
        }
        val theirs = read("protocol_error") { (readBody(second, ENTRIES_MAX) as Body.Challenge).nonce }
        conn.send(frame(response(v.me.prove(theirs))))
        val third = next(conn, "response")
        if (kindOf(third).first != "pop_response") refuse("pop_failed", "a response was expected")
        val sig = read("pop_failed") { (readBody(third, ENTRIES_MAX) as Body.Response).sig }
        if (!ed25519Verify(d.pub, nonce + d.token, sig)) refuse("pop_failed", "the proof of possession does not verify")
        audit("admitted", typ + if (listed >= 0) ", tempus whitelist entry $listed" else ", token and proof of possession")
        return typ
    }

    /** A frame of entries: its bounds, then every entry verified without contact. One bad entry refuses the whole frame. */
    private fun entries(bytes: ByteArray): Body.Entries {
        val b = read("protocol_error") { readBody(bytes, v.count) as Body.Entries }
        b.entries.forEachIndexed { i, e -> entryWhy(e.d, b.store, v)?.let { refuse("entry_refused", "entry $i: $it") } }
        return b
    }

    fun dial(addr: String, request: ByteArray): Dialed {
        val deadline = System.nanoTime() + v.timeoutMs * 1_000_000
        val trust = SelfSignedEd25519()
        val socket = context(v.me, trust).socketFactory.createSocket() as SSLSocket
        try {
            socket.connect(hostPort(addr), v.timeoutMs.toInt())
        } catch (e: Exception) {
            try { socket.close() } catch (x: IOException) { }
            return Dialed.Failed("connect_failed")
        }
        var conn: Conn? = null
        try {
            val certificate = handshake(socket, trust, true, deadline)
            conn = Conn(socket, deadline)
            val typ = admit(conn, certificate)
            conn.send(frame(request))
            val reply = next(conn, "reply")
            return when (kindOf(reply).first) {
                "shuffle_reply", "sample_reply" -> Dialed.Reply(entries(reply), peer!!, typ)
                "done", "result" -> Dialed.Reply(Body.KeyRotated(ByteArray(1)), peer!!, typ)    // a reply of another kind: no entries
                else -> refuse("protocol_error", "the reply is not a reply frame")
            }
        } catch (e: Ended) {
            return if (e.kid != null) Dialed.Rotated(e.kid) else Dialed.Failed(e.event)
        } finally {
            conn?.close()
        }
    }

    /** refusal: why the node closes this connection at once (its inflight limit, or its clock), or null to serve it. */
    fun accepted(raw: Socket, at: Long, refusal: String?, cid: Int) {
        val deadline = at + v.timeoutMs * 1_000_000
        val trust = SelfSignedEd25519()
        val socket = context(v.me, trust).socketFactory.createSocket(raw, null, true) as SSLSocket
        var conn: Conn? = null
        try {
            val certificate = handshake(socket, trust, false, deadline)
            conn = Conn(socket, deadline)
            when (refusal) {
                "inflight_refused" -> refuse(refusal, "more accepted connections than inflight_max: closed at once")
                "clock_refused" -> refuse(refusal, "the system clock cannot be read: closed at once")
                "clock_stopped" -> refuse(refusal, "the node stopped after its system clock went back: closed at once")
            }
            val typ = admit(conn, certificate)
            val bytes = next(conn, "request")
            val (kind, why) = kindOf(bytes)
            val rq = when (kind) {
                "shuffle" -> PeerRequest(cid, kind, bytes, entries(bytes), "", peer!!, typ, CompletableFuture())
                "sample" -> {
                    var body: Body? = null
                    var bad = ""
                    try { body = readBody(bytes, ENTRIES_MAX) } catch (e: Refused) { bad = e.why }
                    PeerRequest(cid, kind, bytes, body, bad, peer!!, typ, CompletableFuture())
                }
                "call", "cast" -> PeerRequest(cid, kind, bytes, null, "", peer!!, typ, CompletableFuture())
                // a frame of no kind of tempus/1, the test unit's tick and clock among them: refused like any frame
                // that is not a request. This extension holds no code that could do otherwise.
                else -> refuse("protocol_error", "not a request: $why")
            }
            node.request(rq)
            // while the node works on the request the bound is the node's: it always answers
            val reply = rq.answer.get()
            if (reply != null) conn.send(frame(reply))
        } catch (e: Ended) {
            if (e.kid != null) node.rotated(e.kid)
        } finally {
            conn?.close()
        }
    }
}
