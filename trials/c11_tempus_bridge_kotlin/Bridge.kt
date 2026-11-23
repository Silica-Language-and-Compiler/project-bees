// C11: the client half of the Kotlin extension (example_tempus_clients/kotlin) against real bridge nodes on 127.0.0.1:
// two bridges, B1 and B2 (each a TRUST node and a TEMPUS node in one Silica program), and the TRUST node T behind
// them. TEST CODE of this trial; it is not part of the extension. It uses the client as an application would (dial,
// Listener) with the TEST ONLY identities of tools/bees_tempus_certs.py, checks every step and prints one line per
// step. Nothing printed depends on the time of day. COVERAGE.md beside this file says which row of the design's
// section 16.2 each step reaches.
//
// What a client cannot do is asked of the trial tool (walk.py beside this file), one line `@request` on the standard
// output answered by one line on the standard input: starting and stopping a node process, waiting for a line of its
// output, and sending a bridge (a test program) the test-only tick and clock frames, with the Python test support.
package bees.tempus.trial

import bees.tempus.*
import bees.tempus.test.Certs
import bees.tempus.test.constant
import java.nio.file.Files
import java.nio.file.Path
import java.util.concurrent.ConcurrentLinkedQueue
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

// a node's connection actor is reaped half a second after its close: steps stand apart, so a node's lines come in one order
private fun quiet(ms: Long = 700) = Thread.sleep(ms)

// the text of a failed handshake is the TLS library's own; a close before the request and a failed handshake are one fact
private fun line(o: Outcome): String = if (o.what == "tls_failed") "tls_failed at=${o.stage}" else o.line()

private fun entries(o: Outcome): String = (o.body as? Body.Entries ?: die("no entries in: ${o.line()}")).entries.joinToString(" ") { "${hex(it.d.id.copyOf(4))}@${it.age}" }.ifEmpty { "(empty)" }

fun main(argv: Array<String>) {
    try {
        walk(argv)
    } catch (e: Exception) {
        die("the walk ended with ${e.javaClass.simpleName}: ${e.message}")
    }
}

private fun walk(argv: Array<String>) {
    val root = Path.of(argv[0])
    val base = argv[1].toInt()
    val certs = Certs(root)
    val producerPub = unhex(constant(String(Files.readAllBytes(root.resolve("trials/c6_tempus_kotlin/lib/tempus_ids.silica"))), "producer_pub_hex"))
    val b1 = "127.0.0.1:${base + 1}"; val b2 = "127.0.0.1:${base + 2}"; val lp = "127.0.0.1:${base + 3}"; val dead = "127.0.0.1:${base + 5}"
    val bridges = setOf(fingerprint(certs.cert("bridge")), fingerprint(certs.cert("x1")))      // the TEMPUS certificates of B1 and B2
    val clock = longArrayOf(1500)
    fun verifier(whitelist: Set<String> = bridges) = Verifier(producerPub, "k1".toByteArray(), { clock[0] }, 10, whitelist)
    val settings = Settings(9000, 3)
    val p = certs.identity("other", "tempus_edge", 1000, 3000, lp)          // the client's edge
    val n = certs.identity("node", "tempus_edge", 1000, 3000, lp)           // a second edge
    val h = certs.identity("x3", "tempus_edge", 1000, 3000, lp)             // the edge that misbehaves
    val r = certs.identity("sentinel", "tempus_edge", 1000, 3000, lp)       // the edge of the rate bound
    val q = certs.identity("x2", "tempus_edge", 1000, 3000, lp)             // the edge that asks when the bridge is full
    var step = 0
    fun say(what: String, out: String) { step += 1; println("$step $what: $out") }
    fun ask(who: Identity, addr: String, request: Request, v: Verifier = verifier(), wait: Long = 700): Outcome = dial(addr, who, v, request, settings).also { quiet(wait) }
    fun call(who: Identity, addr: String, rid: String, f: String, vararg args: Long, module: String = "demo") =
        ask(who, addr, Request.Call(rid.toByteArray(), module, f, args.map { TInt(it) }))
    fun result(what: String, out: Outcome, value: Long) {
        val b = out.body as? Body.Result
        must(out.what == "reply" && b != null && b.value == TInt(value), "$what: wanted the result $value, got: ${out.line()}")
        say(what, "result ${show(b!!.value)}")
    }
    fun closed(what: String, out: Outcome) {
        must(out.what == "closed" && out.stage == "reply", "$what: wanted a close with no reply, got: ${out.line()}")
        say(what, "closed, no reply")
    }

    tool("start t"); tool("start b1"); tool("start b2")

    println("== A. calls and a cast through a bridge (rows 24, 25, 31, 32)")
    result("a call of demo:add/2 on bridge B1", call(p, b1, "k1", "add", 2, 3), 5)
    result("the same call on bridge B2", call(p, b2, "k2", "add", 2, 3), 5)
    result("demo:onward/2 on B1, which the bridge's application sends on to the TRUST node T", call(p, b1, "k3", "onward", 20, 22), 42)
    tool("wait t demo:add/2")
    result("the same through B2", call(p, b2, "k4", "onward", 20, 22), 42)
    closed("a cast of demo:note/1 on B1 (a cast has no reply)", ask(p, b1, Request.Cast("k5".toByteArray(), "demo", "note", listOf(TInt(7)))))
    tool("wait b1 ^\\[bridge\\] note got 7$")
    say("the bridge ran the cast", "its line `[bridge] note got 7` is in B1's output")

    println("== B. what a bridge refuses of an edge; the edge sees a close and nothing else (rows 24, 34)")
    closed("a function that fails (demo:crash/1): no error body", call(p, b1, "k6", "crash", 1))
    result("the bridge still serves", call(p, b1, "k7", "add", 2, 3), 5)
    closed("a function that answers after the bridge's call timeout (demo:slow/1)", call(p, b1, "k8", "slow", 1))
    closed("a function of a forbidden module (erlang:apply/0)", call(p, b1, "k9", "apply", module = "erlang"))
    closed("a function the bridge does not let an edge call (demo:secret/0)", call(p, b1, "k10", "secret"))
    for (i in 1..6) must(call(h, b1, "h$i", "secret").what == "closed", "a refused request of the second edge was answered")
    say("six refused requests of another edge, H", "each closed, no reply")
    closed("then a good request of H: refused for its score", call(h, b1, "h7", "add", 2, 3))
    tool("wait b1 bridge_refused peer=\\S+ score 6 is above the limit 5")
    result("another edge is served meanwhile", call(n, b1, "n1", "add", 2, 3), 5)

    println("== C. the bridge's bounds (rows 20, 35)")
    val held = ConcurrentLinkedQueue<Outcome>()
    val threads = ArrayList<Thread>()
    // B1 numbers its accepted connections; sections A and B made 16, so the held calls are connections 17, 18, 20 and 21
    // (19 is the third request of the first edge). The number tells one edge's second held call from its first.
    fun hold(i: Int, who: Identity) {
        threads.add(Thread { held.add(dial(b1, who, verifier(), Request.Call("c$i".toByteArray(), "demo", "hold", listOf(TInt(i + 1L))), settings)) }.also { it.start() })
        tool("wait b1 bridge_admitted peer=${hex(who.peerId.copyOf(8))} call demo:hold/1 a${17 + i + (if (i > 1) 1 else 0)}$")
        quiet(300)
    }
    hold(0, p); hold(1, p)
    val third = dial(b1, p, verifier(), Request.Call("c9".toByteArray(), "demo", "add", listOf(TInt(2), TInt(3))), settings)
    must(third.what == "closed" && third.stage == "reply", "a third request of an edge with two calls in flight: ${third.line()}")
    tool("wait b1 bridge_inflight peer=\\S+ the peer's requests in flight are at their bound")
    say("two calls of this edge are held open by the bridge's application; a third request of the same edge", "closed, no reply")
    quiet(300)
    hold(2, n); hold(3, n)
    val fifth = dial(b1, q, verifier(), Request.Sample("tempus_bridge", 2), settings)
    must(fifth.what in listOf("closed", "tls_failed") && fifth.stage in listOf("tls", "advert"), "the connection beyond inflight_max was served: ${fifth.line()}")
    tool("wait b1 inflight_refused")
    say("two calls of a second edge are held open too: four connections, and a fifth, beyond inflight_max 4", "closed at once, before any frame")
    threads.forEach { it.join() }
    must(held.all { it.what == "closed" }, "the held calls: ${held.map { it.line() }}")
    say("the four held calls end at the bridge's call timeout", "each closed, no reply")
    quiet()
    result("demo:release/0 afterwards, called by the second edge", call(n, b1, "c8", "release"), 2)
    for (i in 0 until 20) {
        val out = dial(b1, r, verifier(), Request.Call("r$i".toByteArray(), "demo", "add", listOf(TInt(i.toLong()), TInt(1))), settings)
        must(out.what == "reply" && (out.body as? Body.Result)?.value == TInt(i + 1L), "request ${i + 1} of the rate: ${out.line()}")
    }
    quiet()
    say("twenty calls of one edge, R, within the hour", "each answered")
    closed("the twenty-first: the rate bound", call(r, b1, "r20", "add", 2, 3))
    tool("wait b1 bridge_rate peer=\\S+ more than 20 requests in 3600000 ms")
    result("another edge is served", call(n, b1, "n2", "add", 2, 3), 5)

    println("== D. the whitelist rule for a bridge's certificate (rows 11, 12)")
    val out1 = ask(p, b1, Request.Call("w1".toByteArray(), "demo", "add", listOf(TInt(2), TInt(3))), verifier(emptySet()))
    must(out1.what == "refused" && out1.stage == "advert" && out1.reason.contains("not in the tempus whitelist"), "a bridge this client does not list was accepted: ${out1.line()}")
    say("a client whose whitelist does not hold B1's certificate refuses B1", line(out1).replace(Regex(" peer=\\S+"), ""))
    val out2 = ask(p, b1, Request.Call("w2".toByteArray(), "demo", "add", listOf(TInt(2), TInt(3))), verifier(setOf(fingerprint(certs.cert("x1")))))
    must(out2.what == "refused" && out2.stage == "advert", "B1 was accepted under B2's certificate alone: ${out2.line()}")
    say("the same when it lists only B2's certificate", line(out2).replace(Regex(" peer=\\S+"), ""))
    val bogus = certs.identity("other", "tempus_bridge", 1000, 3000, lp)
    val out3 = ask(bogus, b1, Request.Sample("tempus_bridge", 2))
    must(out3.what == "closed", "B1 admitted a bridge token under a certificate it does not list: ${out3.line()}")
    tool("wait b1 whitelist_reject")
    say("this client with a bridge token, under a certificate B1 does not list", "closed, no reply")
    val x4 = certs.identity("x4", "tempus_bridge", 1000, 3000, lp)
    val out4 = ask(x4, b1, Request.Sample("tempus_bridge", 2))
    must(out4.what == "reply", "B1 did not admit a bridge token under a certificate of its whitelist: ${out4.line()}")
    say("with a bridge token under a certificate B1 lists (x4): a sample of B1's bridge store", entries(out4))

    println("== E. the node's steps a client reaches with the test frames, and finding a bridge (rows 4, 5, 7, 10, 16, 18, 21, 29, 30)")
    val d1 = certs.identity("x2", "tempus_edge", 1000, 1600, dead)          // an entry whose token ends at 1600, where nobody listens
    val replies = ConcurrentLinkedQueue<Pair<Long, List<Entry>>>()          // what the listener answers next: after a wait, these entries
    val got = ConcurrentLinkedQueue<String>()
    Listener(p, verifier(), settings, "127.0.0.1", base + 3) { rq ->
        val b = rq.body as? Body.Entries ?: return@Listener null
        got.add(b.entries.joinToString(" ") { "${hex(it.d.id.copyOf(4))}@${it.age}" }.ifEmpty { "(empty)" })
        val (wait, answer) = replies.poll() ?: (0L to emptyList())
        Thread.sleep(wait)
        answer
    }.use { listener ->
        fun served(k: Int): String {
            must(listener.outcomes(k, 9000).size == k, "the listener was not dialed $k times")
            return got.elementAt(k - 1)
        }
        must(ask(p, b2, Request.Shuffle("tempus_edge", listOf(p.entry(5), d1.entry(2)))).what == "reply", "the shuffle into B2 was not answered")
        say("this client shuffles two entries into B2's edge store: its own at age 5 and one for x2 at age 2; the store", entries(ask(p, b2, Request.Sample("tempus_edge", 3))))
        replies.add(0L to listOf(d1.entry(1)))
        tool("tick b2 tempus_edge")
        say("a tick: B2 dials its oldest entry, this client, with the other entry one tick older, and none of its own (the store is not of its type)", served(1))
        must(got.elementAt(0) == "${hex(d1.peerId.copyOf(4))}@3", "the shuffle frame of the tick: ${got.elementAt(0)}")
        say("this client answered with x2 at age 1: the younger entry is kept, and the partner that answered is back at age 0; the store", entries(ask(p, b2, Request.Sample("tempus_edge", 3))))
        tool("tick b2 tempus_edge")
        tool("wait b2 ^tick tempus_edge: shuffle failed$")
        say("a tick: the oldest entry is x2, where nobody listens: it is forgotten; the store", entries(ask(p, b2, Request.Sample("tempus_edge", 3))))
        replies.add(2500L to emptyList())
        tool("ticks2 b2 tempus_edge")
        tool("wait b2 ^tick tempus_edge: aged only \\(a shuffle is in flight\\)$")
        must(listener.outcomes(3, 3000).size == 2, "a tick during a shuffle in flight dialed again")
        say("a tick while this client holds the tick's shuffle open: a second tick only ages", "B2 dialed once; its line `aged only` is in its output")
        must(ask(p, b2, Request.Shuffle("tempus_edge", listOf(d1.entry(2)))).what == "reply", "the second shuffle into B2 was not answered")
        say("x2 (token valid to 1600) is shuffled in again; the store", entries(ask(p, b2, Request.Sample("tempus_edge", 3))))
        tool("clock b2 1700000")
        clock[0] = 1700
        tool("tick b2 tempus_edge")
        tool("wait b2 ^expired in tempus_edge: ${hex(d1.peerId.copyOf(4))}$")
        say("B2's clock is set to 1700 and its store ticks: the entry whose token expired has left; the store", entries(ask(p, b2, Request.Sample("tempus_edge", 3))))
    }
    val b1Entry = certs.identity("bridge", "tempus_bridge", 1000, 3000, b1).entry(5)
    must(ask(x4, b2, Request.Shuffle("tempus_bridge", listOf(b1Entry))).what == "reply", "the shuffle into B2's bridge store was not answered")
    val found = ask(n, b2, Request.Sample("tempus_bridge", 2))
    say("a bridge peer shuffles B1's entry into B2's bridge store; an edge samples that store (every entry of the reply verified)", entries(found))
    val there = (found.body as Body.Entries).entries.single().d
    must(String(there.addr) == b1, "the entry's address is not B1's: ${String(there.addr)}")
    result("the edge dials the address of the entry it was given and calls demo:add/2 there", call(n, String(there.addr), "e1", "add", 40, 2), 42)

    println("== F. what a client sees when the TRUST side refuses or cannot be reached, and a bridge that is lost (design 17.7, rows 3, 33)")
    for (i in 1..3) must(call(n, b1, "t$i", "bad").what == "closed", "demo:bad/0 was answered")
    tool("wait t quarantined")
    say("three calls of demo:bad/0 on B1, which sends on a call T does not permit: T quarantines B1", "each closed, no reply")
    closed("then demo:onward/2 on B1: T refuses the quarantined bridge", call(n, b1, "t4", "onward", 20, 22))
    result("B1 itself still answers what needs no TRUST node", call(n, b1, "t5", "add", 2, 3), 5)
    result("and B2 still reaches T", call(p, b2, "t6", "onward", 20, 22), 42)
    tool("stop t")
    closed("T is stopped: demo:onward/2 on B2", call(p, b2, "t7", "onward", 20, 22))
    result("B2 itself still answers", call(p, b2, "t8", "add", 2, 3), 5)
    tool("stop b1")
    val gone = dial(b1, p, verifier(), Request.Call("t9".toByteArray(), "demo", "add", listOf(TInt(2), TInt(3))), settings)
    must(gone.what == "unreachable", "a stopped bridge answered: ${gone.line()}")
    say("B1 is stopped: a call to it", gone.line())
    tool("tick b2 tempus_bridge")
    say("a tick of B2's bridge store, whose only entry is B1: the shuffle fails and B1 is forgotten; the store", entries(ask(p, b2, Request.Sample("tempus_bridge", 2))))
    result("a call through the other bridge, B2", call(p, b2, "t10", "add", 2, 3), 5)
    tool("stop b2")
    println("[c11_tempus_bridge_kotlin] every step passed ($step steps)")
}
