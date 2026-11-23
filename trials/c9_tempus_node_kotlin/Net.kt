// C9: a mixed network of Silica nodes and nodes of the Kotlin extension (example_tempus_clients/kotlin) on 127.0.0.1.
// TEST CODE of this trial; it is not part of the extension. It starts nodes of the extension as an application would
// (TempusNode.start), with the TEST ONLY identities of tools/bees_tempus_certs.py, checks every step and prints one
// line per step. Nothing printed depends on the time of day.
//
// The Kotlin nodes KE, KS, KH and KC are test nodes: each is given a clock the scenario sets, timers the scenario
// runs and literal draws, through NodeEnvironment, the extension's ordinary construction interface. No frame reaches
// any of that. KP is not a test node: it is started with NodeEnvironment.system(), reads the machine's clock and
// runs its own timers. The lines of each Kotlin node (the extension's own lines, and one line for everything its
// application is told) are written to NAME.sout.
//
// What this program cannot do is asked of the trial tool (walk.py beside this file), one line `@request` on the
// standard output answered by one line on the standard input: starting and stopping a Silica node process, waiting
// for a line of its output, sending a Silica test node the test-only tick frame, and playing a peer that misbehaves.
package bees.tempus.trial

import bees.tempus.*
import bees.tempus.test.Certs
import bees.tempus.test.Lines
import bees.tempus.test.ManualTimers
import bees.tempus.test.TestClock
import bees.tempus.test.constant
import bees.tempus.test.testEnvironment
import java.nio.file.Files
import java.nio.file.Path
import kotlin.system.exitProcess

private val input = System.`in`.bufferedReader()

private fun die(what: String): Nothing {
    println("FAIL: $what")
    System.out.flush()
    exitProcess(1)
}

private fun must(cond: Boolean, what: String) {
    if (!cond) die(what)
}

private fun tool(request: String): String {
    println("@$request")
    System.out.flush()
    val answer = input.readLine() ?: die("the trial tool went away")
    if (!answer.startsWith("ok")) die("the trial tool, asked `$request`: $answer")
    return answer.removePrefix("ok").trim()
}

// a Silica node's connection actor is reaped half a second after its close: steps stand apart
private fun quiet(ms: Long = 700) = Thread.sleep(ms)

private fun id8(d: Descriptor) = hex(d.id.copyOf(4))

/** One node of the Kotlin extension, hosted by this program, with what the scenario drives it by. */
private class Hosted(val name: String, val lines: Lines, val clock: TestClock?, val timers: ManualTimers?) {
    lateinit var node: TempusNode
    private var mark = 0

    /** the application of the node: one line for everything it is told */
    val application = NodeListener { _, e ->
        when (e) {
            is NodeEvent.ViewChanged -> lines.add("view ${e.store}:" + if (e.entries.isEmpty()) " (empty)" else e.entries.joinToString("") { " ${id8(it.d)}@${it.age}" })
            is NodeEvent.OwnTokenInvalid -> lines.add("application: told that the node's own token is not valid any more: ${e.why}")
            is NodeEvent.KeyRotated -> lines.add("application: told that a peer answered key_rotated, its current kid is ${String(e.kid)}")
            is NodeEvent.ClockUnreadable -> lines.add("application: told (86) ${e.what}")
            is NodeEvent.Stopped -> lines.add("application: told (87) ${e.why}")
            is NodeEvent.ListenFailed -> lines.add("application: told that the node cannot listen: ${e.why}")
        }
    }

    fun await(pattern: String, waitMs: Long = 20000): String =
        lines.await(Regex(pattern), waitMs) ?: die("node $name did not write /$pattern/ in time; its lines so far:\n" + lines.snapshot().joinToString("\n"))

    /** runs the node's armed timer of that name, as its time had come */
    fun fire(timer: String) {
        armed(timer)
        timers!!.fire(timer)
    }

    // the node arms a timer again when it has taken what the timer brought: the scenario waits for that
    private fun armed(timer: String) {
        val until = System.nanoTime() + 5_000_000_000
        while (!timers!!.armed(timer)) {
            if (System.nanoTime() > until) die("node $name has no timer `$timer` armed")
            Thread.sleep(20)
        }
    }

    /** the clock reader's timer fires with this reading (null: the clock could not be read) */
    fun reading(seconds: Long?) {
        armed("clock")
        clock!!.reading = seconds
        timers!!.fire("clock")
    }

    /** the audit lines since this was last asked, as the trial tool gives a Silica node's */
    fun audit(): String {
        quiet()
        val all = lines.snapshot().filter { it.startsWith("[tempus audit] ") }
        val new = all.drop(mark)
        mark = all.size
        return new.filter { !it.contains(" tls_established ") }.joinToString(" / ") { normal(it.replace(Regex(" [ad]\\d+$"), "")) }
    }

    fun write(leaf: Path) {
        Files.write(leaf.resolve("$name.sout"), (lines.snapshot().map { normal(it) } + "exit=0").joinToString("") { it + "\n" }.toByteArray())
    }
}

// the side whose peer closed learns of it at whichever step it had reached (as tools/bees_tempus_reports.py writes it)
private fun normal(line: String) = line.replace(Regex("^(\\[tempus audit\\] closed_by_peer) peer=\\S+ stage [a-z_]+"), "$1 peer=(any) stage (any)")

// what a misbehaving peer saw, without what differs between two nodes (their identifiers and what their stores hold)
private fun brief(saw: String) = saw.replace(Regex(" (entries|peer|typ|store)=\\S+"), "")

private fun shown(o: Outcome): String = (o.body as? Body.Entries ?: die("no entries in: ${o.line()}")).entries.joinToString(" ") { "${id8(it.d)}@${it.age}" }.ifEmpty { "(empty)" }

fun main(argv: Array<String>) {
    try {
        net(argv)
    } catch (e: Exception) {
        die("the program ended with ${e.javaClass.simpleName}: ${e.message}")
    }
}

private fun net(argv: Array<String>) {
    val root = Path.of(argv[0])
    val base = argv[1].toInt()
    val leaf = Path.of(argv[2])
    val certs = Certs(root)
    val producerPub = unhex(constant(String(Files.readAllBytes(leaf.resolve("lib/tempus_ids.silica"))), "producer_pub_hex"))
    fun addr(k: Int) = "127.0.0.1:${base + k}"
    val sAddr = addr(0); val aAddr = addr(1); val keAddr = addr(2); val ksAddr = addr(3); val kpAddr = addr(4); val qAddr = addr(5); val pAddr = addr(6)
    val dead = addr(7)
    val whitelist = mapOf("s" to certs.cert("sentinel"), "ks" to certs.cert("bridge"), "kp" to certs.cert("x1"))
    val hosted = ArrayList<Hosted>()

    fun config(role: String, port: Int, sentinels: List<SentinelAddress>, back: String, limit: Long?, fail: String, edgeTick: Long = 1000) =
        TempusConfig(role = role, listenAddress = "127.0.0.1", port = port, sentinels = sentinels,
            edge = StoreConfig(4, 3, edgeTick), bridge = StoreConfig(4, 2, 3600000), sentinel = StoreConfig(4, 2, 3600000),
            producerKid = "k1".toByteArray(), producerKey = producerPub, whitelist = whitelist, shuffleTimeoutMs = 2000, inflightMax = 2,
            clockSkewMs = 10000, clockBack = back, clockBackLimitS = limit, clockFail = fail, clockReadMs = 1000, joinRetryInitialMs = 200,
            joinRetryMaxMs = 800)

    /** a test node: its clock begins at the trial's value, 1500; its draws are the Silica test nodes' literal list */
    fun testNode(name: String, role: String, port: Int, me: Identity, sentinels: List<SentinelAddress>, back: String = "follow", limit: Long? = null,
                 fail: String = "pause"): Hosted {
        val h = Hosted(name, Lines(), TestClock(1500), ManualTimers())
        h.node = TempusNode.start(config(role, port, sentinels, back, limit, fail), me, h.application, testEnvironment(h.clock!!, h.timers!!, listOf(0L, 1L, 2L, 3L), h.lines))
        hosted.add(h)
        return h
    }

    // the trial's own peer: the extension's client half, as an edge whose certificate no node lists
    val settings = Settings(5000, 3)
    val verifier = Verifier(producerPub, "k1".toByteArray(), { 1500 }, 10, whitelist.values.map { fingerprint(it) }.toSet())
    val x3 = certs.identity("x3", "tempus_edge", 1000, 3000, pAddr)
    val x2 = certs.identity("x2", "tempus_edge", 1000, 3000, dead)
    fun ask(to: String, request: Request, s: Settings = settings): Outcome {
        val out = dial(to, x3, verifier, request, s)
        must(out.what == "reply", "a request to $to was not answered: ${out.line()}")
        quiet()
        return out
    }
    fun sampled(to: String, store: String) = shown(ask(to, Request.Sample(store, if (store == "tempus_edge") 3 else 2)))
    fun step(label: String, text: String) = println("$label: $text")

    val sId = hex(peerId(certificateKey(certs.cert("sentinel")))).take(8)
    val aId = hex(peerId(certificateKey(certs.cert("node")))).take(8)
    val keId = hex(peerId(certificateKey(certs.cert("other")))).take(8)
    val ksId = hex(peerId(certificateKey(certs.cert("bridge")))).take(8)
    val x2Id = hex(x2.peerId).take(8)
    val sentinelS = listOf(SentinelAddress("127.0.0.1", base, "s"))
    val sentinelKs = listOf(SentinelAddress("127.0.0.1", base + 3, "ks"))

    // ---------------------------------------------------------------- A
    println("== A. the Kotlin node KE joins through the Silica sentinel S")
    tool("start s")
    val ke = testNode("ke", "edge", base + 2, certs.identity("other", "tempus_edge", 1000, 3000, keAddr), sentinelS)
    ke.await("^join: done$")
    tool("wait s ^view tempus_edge: $keId@0$")
    quiet()
    step("A1 KE asked S for its three stores and S holds KE in its edge store", "yes")
    step("A2 KE keeps the sentinel it joined through; its sentinel store", sampled(keAddr, "tempus_sentinel"))
    must(ke.lines.snapshot().count { it == "view tempus_sentinel: $sId@0" } == 4, "KE did not put S into its sentinel store after each answer")

    // ---------------------------------------------------------------- B
    println("== B. the Silica node A joins through the Kotlin sentinel KS")
    val ks = testNode("ks", "sentinel", base + 3, certs.identity("bridge", "tempus_sentinel", 1000, 3000, ksAddr), emptyList())
    ks.await("^join: no sentinel is configured$")
    tool("start a")
    ks.await("^view tempus_edge: $aId@0$")
    quiet()
    must(ks.lines.snapshot().count { it.contains(" admitted peer=$aId") } == 3, "KS did not admit A three times")
    step("B1 A asked KS for its three stores and KS holds A in its edge store", "yes")
    step("B2 A keeps the sentinel it joined through; its sentinel store", sampled(aAddr, "tempus_sentinel"))

    // ---------------------------------------------------------------- C
    println("== C. shuffles started by each side and answered by the other")
    step("C1 a peer shuffles an entry for x2 (age 3) into KE; KE's edge store", ask(keAddr, Request.Shuffle("tempus_edge", listOf(x2.entry(3)))).let { sampled(keAddr, "tempus_edge") })
    step("C2 a peer shuffles KE's entry (age 5) into A; A's edge store",
        ask(aAddr, Request.Shuffle("tempus_edge", listOf(certs.identity("other", "tempus_edge", 1000, 3000, keAddr).entry(5)))).let { sampled(aAddr, "tempus_edge") })
    tool("tick a tempus_edge")
    tool("wait a ^tick tempus_edge: shuffle merged$")
    ke.await("^view tempus_edge: $aId@0 $x2Id@3$")
    step("C3 A ticks: it shuffles with KE, which answers with x2; A's edge store", sampled(aAddr, "tempus_edge"))
    step("C3 KE holds A, whose entry came in the shuffle; KE's edge store", sampled(keAddr, "tempus_edge"))
    ke.fire("tick tempus_edge")
    ke.await("^tick tempus_edge: the partner did not answer, connect_failed d\\d+$")
    ke.await("^tick tempus_edge: shuffle failed$")
    step("C4 KE ticks: its oldest entry is x2, where nobody listens; the partner is dropped, the entry sent is put back; KE's edge store", sampled(keAddr, "tempus_edge"))
    ke.fire("tick tempus_edge")
    ke.await("^tick tempus_edge: shuffle merged$")
    tool("wait a ^view tempus_edge: $keId@0")
    quiet()
    step("C5 KE ticks: it shuffles with A, which answers; A's edge store", sampled(aAddr, "tempus_edge"))
    step("C5 KE's edge store", sampled(keAddr, "tempus_edge"))
    tool("tick s tempus_edge")
    tool("wait s ^tick tempus_edge: shuffle merged$")
    step("C6 S ticks its edge store, which is not of its own type: it shuffles with KE without an entry of its own and keeps KE", "merged")
    ks.fire("tick tempus_edge")
    ks.await("^tick tempus_edge: shuffle merged$")
    must(ks.lines.snapshot().last { it.startsWith("view tempus_edge:") }.contains("$aId@0"), "KS did not put the partner that answered back at age 0")
    step("C7 KS ticks its edge store: it shuffles with A and puts A back at age 0 (ruling NQ-15); KS's edge view", ks.lines.snapshot().last { it.startsWith("view tempus_edge:") }.removePrefix("view tempus_edge: "))
    ke.fire("tick tempus_sentinel")
    ke.await("^tick tempus_sentinel: shuffle merged$")
    step("C8 KE ticks its sentinel store: it shuffles with S, a sentinel of its whitelist", "merged")
    tool("tick a tempus_sentinel")
    tool("wait a ^tick tempus_sentinel: shuffle merged$")
    step("C9 A ticks its sentinel store: it shuffles with KS, a sentinel of its whitelist", "merged")

    // ---------------------------------------------------------------- D
    println("== D. what the Silica node A refuses, the Kotlin node KE refuses, with the same audit lines")
    tool("audit a"); ke.audit()
    var k = 0
    fun both(mode: String, what: String, same: Boolean = true) {
        k += 1
        val saw = brief(tool("pydial a $mode"))
        val silica = tool("audit a")
        val saw2 = brief(tool("pydial ke $mode"))
        val kotlin = ke.audit()
        if (same) {
            must(silica == kotlin, "D$k $what: the Silica node wrote `$silica`, the Kotlin node `$kotlin`")
            must(saw == saw2, "D$k $what: the peer saw `$saw` of the Silica node and `$saw2` of the Kotlin node")
            step("D$k $what", "the peer sees: $saw; both nodes: ${silica.removePrefix("[tempus audit] ")}")
        } else {
            step("D$k $what", "the peer sees: $saw of A, $saw2 of KE; A: ${silica.removePrefix("[tempus audit] ")}; KE: ${kotlin.removePrefix("[tempus audit] ")}")
        }
    }
    both("good", "a good peer's sample")
    both("expired", "an expired token")
    both("not-yet", "a token not valid yet")
    both("old-kid", "a token under an old kid")
    both("forged", "a token another key signed")
    both("other-sub", "a token issued for another key")
    both("sentinel-token", "a sentinel token under a certificate that is not in the whitelist")
    both("listed-edge", "a certificate of the whitelist with an edge token")
    both("binding", "an advert for another key than the certificate's")
    both("proof-other-key", "a proof made with another key")
    both("no-proof", "no proof")
    both("wrong-frame", "a sample where the challenge is due")
    both("oversize-advert", "an advert above the frame ceiling")
    both("oversize-request", "a request above the frame ceiling")
    both("closes", "a peer that closes after its advert")
    both("sample-9", "a sample of 9 where the shuffle length is 3")
    both("sample-3-bridge", "a sample of 3 from the bridge store, whose shuffle length is 2")
    both("four-entries", "four entries where the greatest shuffle length is 3")
    both("three-entries-bridge", "three entries for the bridge store, whose shuffle length is 2")
    both("forged-shuffle", "a shuffle with an entry another key signed")
    both("other-store", "an edge's entry offered to the sentinel store")
    both("age-65536", "an entry of age 65536")
    both("no-kind", "a frame whose t is no kind")
    both("an-advert", "an advert where a request is due")
    both("call", "a call, which only a bridge serves")
    both("trailing", "a request with a byte after it")
    k += 1
    val heldA = tool("inflight a"); val linesA = tool("audit a")
    val heldK = tool("inflight ke"); val linesK = ke.audit()
    must(linesA == linesK && heldA == heldK, "D$k inflight_max: the Silica node `$heldA` `$linesA`, the Kotlin node `$heldK` `$linesK`")
    must(linesK.contains("inflight_refused peer=- more accepted connections than inflight_max: closed at once"), "D$k no inflight_refused line: $linesK")
    step("D$k two connections held open and a third (inflight_max is 2)", "$heldK; both nodes: ${linesK.removePrefix("[tempus audit] ")}")
    both("tls12", "a peer that offers TLS 1.2 only")
    both("alpn", "a peer that offers another ALPN protocol")
    both("p256", "a peer whose certificate has a P-256 key", same = false)
    both("no-cert", "a peer that presents no certificate")
    step("D the stores after all of it; A's edge store", sampled(aAddr, "tempus_edge"))
    step("D KE's edge store", sampled(keAddr, "tempus_edge"))
    ke.node.close(); ks.node.close()
    quiet(1000)

    // ---------------------------------------------------------------- E
    println("== E. the clock's choices, the node's own token and key_rotated, on Kotlin nodes whose clock the trial sets")
    val kh = testNode("kh", "edge", base + 2, certs.identity("other", "tempus_edge", 1000, 2000, keAddr), sentinelS, back = "hold", fail = "continue")
    kh.await("^join: done$")
    quiet()
    kh.reading(1450)
    step("E1 hold: the clock reads 1450 after 1500", kh.await("^clock: the system clock went back by 50 s; the node holds its time").removePrefix("clock: "))
    kh.audit()
    must(tool("pydial kh short") == "closed", "E2 a token that ended at 1480 was served by the held time 1500")
    step("E2 it admits by the held time: a token that ended at 1480", kh.audit().removePrefix("[tempus audit] "))
    must(tool("pydial kh good").startsWith("reply"), "E2 a good peer was not served while the node holds its time")
    kh.fire("tick tempus_sentinel")
    step("E2 and it ticks", kh.await("^tick tempus_sentinel: shuffle merged$"))
    kh.reading(1460)
    kh.reading(1500)
    step("E3 a reading still behind (1460) says nothing; 1500 ends the hold", kh.await("^clock: the system clock has reached the held time").removePrefix("clock: "))
    must(kh.lines.snapshot().count { it.startsWith("clock: ") } == 3, "E3 the reading that was still behind wrote a line")
    kh.reading(null)
    step("E4 continue: the clock cannot be read", kh.await("^clock: the system clock could not be read: the node goes on with its last reading$").removePrefix("clock: "))
    kh.await("^application: told \\(86\\)")
    must(tool("pydial kh good").startsWith("reply"), "E4 a good peer was not served while the node goes on with its last reading")
    kh.reading(1510)
    kh.reading(null)
    kh.await("^application: told \\(86\\)")
    step("E5 the next good reading says nothing; a second failure is told again", "yes")
    kh.reading(2600)
    kh.fire("tick tempus_sentinel")
    step("E6 the clock reads 2600, past the node's own token (valid to 2000); the next tick", kh.await("^own token: ").removePrefix("own token: "))
    kh.await("^application: told that the node's own token is not valid any more: the token has expired$")
    kh.fire("tick tempus_sentinel")
    kh.node.setToken(certs.identity("other", "tempus_edge", 1000, 4000, keAddr).token)
    kh.await("^own token replaced$")
    kh.fire("tick tempus_sentinel")
    step("E7 its application passes a new token and it ticks again", kh.await("^tick tempus_sentinel: shuffle merged$"))
    must(kh.lines.snapshot().count { it.startsWith("own token: ") } == 1, "E7 the stop for the node's own token was said more than once")
    // key_rotated: KH dials a peer whose verifier names another kid
    val late = Verifier(producerPub, "k1".toByteArray(), { 2600 }, 10, emptySet())
    val x3late = certs.identity("x3", "tempus_edge", 1000, 4000, pAddr)
    must(dial(keAddr, x3late, late, Request.Shuffle("tempus_edge", listOf(x3late.entry(9))), settings).what == "reply", "E8 the shuffle into KH was not answered")
    quiet()
    tool("peer names-k9")
    kh.fire("tick tempus_edge")
    kh.await("^application: told that a peer answered key_rotated, its current kid is k9$")
    step("E8 a partner answers KH's advert with key_rotated; the tick", kh.await("^tick tempus_edge: the partner did not answer, key_rotated d\\d+$").replace(Regex(" d\\d+$"), ""))
    kh.await("^tick tempus_edge: shuffle failed$")
    tool("peerdone")
    kh.node.close()
    quiet(1000)

    val kc = testNode("kc", "edge", base + 2, certs.identity("other", "tempus_edge", 1000, 3000, keAddr), sentinelKs, back = "stop", limit = 60, fail = "pause")
    kc.await("^join: no sentinel answered for tempus_edge; waiting to try again$")
    kc.reading(null)
    step("E9 pause: the clock cannot be read", kc.await("^clock: the system clock could not be read: the node admits no connection").removePrefix("clock: "))
    kc.await("^application: told \\(86\\)")
    kc.audit()
    val shut = tool("pydial kc good")
    must(shut == "closed" || shut == "tls_failed", "E10 a connection to the waiting node was not closed: $shut")
    step("E10 an accepted connection is closed at once", kc.audit().removePrefix("[tempus audit] "))
    kc.fire("join tempus_edge")
    step("E11 the join's retry falls due", kc.await("^join: the request for tempus_edge waits until the system clock is read again$").removePrefix("join: "))
    kc.fire("tick tempus_edge")
    val ks2 = testNode("ks2", "sentinel", base + 3, certs.identity("bridge", "tempus_sentinel", 1000, 3000, ksAddr), emptyList())
    ks2.await("^join: no sentinel is configured$")
    kc.reading(1500)
    kc.await("^clock: the system clock is read again$")
    kc.await("^join: done$")
    must(kc.lines.snapshot().none { it.startsWith("tick ") }, "E12 the waiting node ticked")
    step("E12 the clock is read again: the waiting request is dialed at once and the join is done; a tick meanwhile did nothing", "yes")
    quiet()
    kc.reading(1470)
    step("E13 stop with a limit of 60 s: a step back of 30 s", kc.await("^clock: the system clock went back by 30 s; the node follows it$").removePrefix("clock: "))
    must(tool("pydial kc good").startsWith("reply"), "E13 a good peer was not served after the step back that was followed")
    kc.reading(1370)
    step("E14 a step back of 100 s", kc.await("^clock: the system clock went back by 100 s, more than clock_back_limit_s 60: the node has stopped").removePrefix("clock: "))
    kc.await("^application: told \\(87\\)")
    kc.audit()
    val shut2 = tool("pydial kc good")
    must(shut2 == "closed" || shut2 == "tls_failed", "E15 a connection to the stopped node was not closed: $shut2")
    step("E15 an accepted connection is closed at once", kc.audit().removePrefix("[tempus audit] "))
    kc.reading(2000)
    kc.fire("tick tempus_edge")
    val shut3 = tool("pydial kc good")
    must(shut3 == "closed" || shut3 == "tls_failed", "E16 the stopped node served a connection after a later good reading: $shut3")
    step("E16 a later good reading changes nothing: no line, no tick, and a connection", kc.audit().removePrefix("[tempus audit] "))
    must(kc.lines.snapshot().count { it.startsWith("clock: ") } == 5 && kc.lines.snapshot().none { it.startsWith("tick ") }, "E16 the stopped node wrote a clock line or ticked")
    kc.node.close(); ks2.node.close()
    tool("stop a"); tool("stop s")

    // ---------------------------------------------------------------- F
    println("== F. a Kotlin node that is not a test node: the machine's clock, its own timers, secure random draws")
    val kp = Hosted("kp", Lines(), null, null)
    val far = 4000000000L
    kp.node = TempusNode.start(config("sentinel", base + 4, emptyList(), "follow", null, "pause", edgeTick = 20000),
        certs.identity("x1", "tempus_sentinel", 1000, far, kpAddr), kp.application, NodeEnvironment.system { kp.lines.add(it) })
    hosted.add(kp)
    kp.await("^join: no sentinel is configured$")
    tool("start q")
    val qId = hex(peerId(certificateKey(certs.cert("x2")))).take(8)
    kp.await("^view tempus_edge: $qId@0$")
    quiet()
    step("F1 the Silica node Q, not a test node either, joined through KP by the machine's clock on both sides", "yes")
    tool("audit q"); kp.audit()
    for ((mode, what) in listOf("tick" to "the test unit's tick frame", "clock" to "the test unit's clock frame", "clock-later" to "the clock frame with a later reading")) {
        val saw = brief(tool("pydial q $mode")); val silica = tool("audit q")
        val saw2 = brief(tool("pydial kp $mode")); val kotlin = kp.audit()
        // Both refuse it as a frame that is no request. The last word differs: Q's program is built in this leaf, whose
        // atom table also serves the two test programs, so Q holds the atoms `tick` and `clock` and says "unknown kind";
        // a Silica program built without the test unit (node P of trials/t6_tempus_clock) does not hold them and says
        // "unknown_atom", as the Kotlin node does.
        val head = Regex("^\\[tempus audit\\] admitted peer=\\S+ tempus_edge, token and proof of possession / \\[tempus audit\\] protocol_error peer=\\S+ not a request: ")
        must(saw == saw2 && head.containsMatchIn(silica) && head.containsMatchIn(kotlin), "F2 $what: the Silica node wrote `$silica` ($saw), the Kotlin node `$kotlin` ($saw2)")
        step("F2 $what", "the peer sees: $saw; Q: ${silica.substringAfterLast("] ")}; KP: ${kotlin.substringAfterLast("] ")}")
    }
    kp.await("^tick tempus_edge: shuffle merged$", 45000)
    step("F3 KP's own timer ticked its edge store: it shuffled with Q", "merged")
    val real = Verifier(producerPub, "k1".toByteArray(), { System.currentTimeMillis() / 1000 }, 10, whitelist.values.map { fingerprint(it) }.toSet())
    val x3far = certs.identity("x3", "tempus_edge", 1000, far, pAddr)
    val out = dial(qAddr, x3far, real, Request.Sample("tempus_sentinel", 2), settings)
    must(out.what == "reply", "F4 Q did not answer: ${out.line()}")
    step("F4 Q keeps KP in its sentinel store", shown(out))
    quiet()
    tool("stop q")
    kp.node.close()

    for (h in hosted) h.write(leaf)
    println("[c9_tempus_node_kotlin] every step passed")
}
