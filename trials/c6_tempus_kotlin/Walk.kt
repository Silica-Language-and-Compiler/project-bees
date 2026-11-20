// C6: the walk of the Kotlin example TEMPUS client (example_tempus_clients/kotlin) against real nodes on 127.0.0.1.
// TEST CODE of this trial; it is not part of the example client. It uses the client as an application would (dial,
// Listener) with the TEST ONLY identities of tools/bees_tempus_certs.py, checks every step, and prints one line per
// step. Nothing printed depends on the time of day.
//
// What a client cannot do is asked of the trial tool (walk.py beside this file), one line `@request` on the standard
// output answered by one line on the standard input: starting and stopping a node process, waiting for a line of a
// node's output, sending a test node the test-only tick frame (with the Python example client: the Kotlin client has
// no such frame), and playing a peer that misbehaves (the Python example client, which can do that on purpose).
package bees.tempus.trial

import bees.tempus.*
import bees.tempus.test.Certs
import bees.tempus.test.constant
import bees.tempus.test.fixtureKey
import bees.tempus.test.makeToken
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

// a node's connection actor is reaped half a second after its close: steps stand apart, so a node's lines come in one order
private fun quiet(ms: Long = 700) = Thread.sleep(ms)

// the text of a failed handshake is the TLS library's own and differs between its versions
private fun line(o: Outcome): String = if (o.what == "tls_failed") "tls_failed at=${o.stage}" else o.line()

private fun step(label: String, out: Outcome, wait: Long = 700): Outcome {
    println("$label: ${line(out)}")
    quiet(wait)
    return out
}

private fun view(o: Outcome): List<String> = (o.body as? Body.Entries ?: die("no entries in: ${o.line()}")).entries.map { "${it.d.id8()}@${it.age}" }

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
    val kAddr = "127.0.0.1:$base"                 // node K, a test node
    val qAddr = "127.0.0.1:${base + 1}"           // node Q, not a test node
    val sAddr = "127.0.0.1:${base + 2}"           // this client's sentinel listener
    val eAddr = "127.0.0.1:${base + 3}"           // this client's edge listener
    val pAddr = "127.0.0.1:${base + 4}"           // the trial tool's Python peer
    val dead = "127.0.0.1:${base + 5}"            // nobody listens here
    val settings = Settings(5000, 3)        // node K: shuffle_timeout_ms 2000, shuffle length 3 (edge store)
    val wide = Settings(5000, 64)           // a client configured for another network's shuffle length
    fun verifier(now: Long = 1500, kid: String = "k1", whitelist: Set<String> = emptySet()) = Verifier(producerPub, kid.toByteArray(), { now }, 10, whitelist)
    val producer = fixtureKey(0)
    val sentinel = certs.identity("sentinel", "tempus_sentinel", 1000, 3000, sAddr)
    val edge = certs.identity("other", "tempus_edge", 1000, 3000, eAddr)
    val nodeId = hex(peerId(certificateKey(certs.cert("node")))).take(16)
    fun x(name: String, age: Int, typ: String = "tempus_edge", exp: Long = 2000) = certs.identity(name, typ, 1000, exp, dead).entry(age)
    fun id(name: String) = hex(peerId(certificateKey(certs.cert(name)))).take(16)
    fun token(signer: java.security.PrivateKey = producer, kid: String = "k1", sub: ByteArray = edge.pub, typ: String = "tempus_edge", nbf: Long = 1000, exp: Long = 2000) =
        makeToken(signer, kid, sub, typ, nbf, exp)
    val sample3 = Request.Sample("tempus_edge", 3)

    // ---------------------------------------------------------------- A
    println("== A. node K joins through this client, which listens as a sentinel")
    val ls = Listener(sentinel, verifier(), settings, "127.0.0.1", base + 2) { rq ->
        when (val b = rq.body) {
            is Body.Sample -> when (b.store) { "tempus_edge" -> listOf(x("x1", 1)); "tempus_bridge" -> emptyList(); else -> listOf(sentinel.entry(0)) }
            is Body.Entries -> listOf(x("bridge", 1, typ = b.store))
            else -> null
        }
    }
    tool("start k")
    val joined = ls.outcomes(3, 10000)
    joined.forEachIndexed { i, o -> println("A1 the join, request ${i + 1}, served: ${o.line()}") }
    must(joined.size == 3 && joined.map { (it.body as? Body.Sample)?.store } == listOf("tempus_edge", "tempus_bridge", "tempus_sentinel"),
        "A1: the join did not ask this sentinel for the three stores, one sample each")
    must(joined.all { it.what == "served" && it.sent == "reply" && it.typ == "tempus_edge" && it.advert?.id8() == nodeId }, "A1: the joiner was not admitted as the node it is")
    quiet()
    var out = step("A2 sample of K's sentinel store", dial(kAddr, sentinel, verifier(), Request.Sample("tempus_sentinel", 2), settings))
    must(out.what == "reply" && view(out) == listOf("${id("sentinel")}@0"), "A2: K did not keep the sentinel it joined through at age 0")
    tool("tick k tempus_sentinel")
    val shuffled = ls.outcomes(4, 8000).getOrNull(3) ?: die("A3: K did not shuffle its sentinel store with this sentinel")
    println("A3 a tick of K's sentinel store, served: ${shuffled.line()}")
    must(shuffled.what == "served" && (shuffled.body as? Body.Entries)?.let { it.kind == "shuffle" && it.store == "tempus_sentinel" && it.entries.isEmpty() } == true,
        "A3: the shuffle of the sentinel store by an edge holds an entry")
    quiet()
    out = step("A4 sample of K's sentinel store", dial(kAddr, sentinel, verifier(), Request.Sample("tempus_sentinel", 2), settings))
    must(out.what == "reply" && view(out).sorted() == listOf("${id("bridge")}@1", "${id("sentinel")}@0").sorted(), "A4: the sentinel store after its shuffle")
    out = step("A5 sample of K's bridge store", dial(kAddr, sentinel, verifier(), Request.Sample("tempus_bridge", 2), settings))
    must(out.what == "reply" && view(out).isEmpty(), "A5: the bridge store is not empty")
    ls.close()

    // ---------------------------------------------------------------- B
    println("== B. this client as an edge: sample, shuffle, and being dialed by K")
    out = step("B1 sample", dial(kAddr, edge, verifier(), sample3, settings))
    must(out.what == "reply" && view(out) == listOf("${id("x1")}@1") && out.typ == "tempus_edge" && out.advert?.id8() == nodeId, "B1: K's edge store after the join")
    out = step("B2 shuffle, own entry first at age 0", dial(kAddr, edge, verifier(), Request.Shuffle("tempus_edge", listOf(edge.entry(0), x("x2", 2))), settings))
    must(out.what == "reply" && (out.body as Body.Entries).kind == "shuffle_reply", "B2: no shuffle_reply")
    out = step("B3 sample", dial(kAddr, edge, verifier(), sample3, settings))
    must(out.what == "reply" && "${id("other")}@0" in view(out), "B3: this client is not in K's edge store at age 0")
    val le = Listener(edge, verifier(), settings, "127.0.0.1", base + 3) { rq ->
        when (rq.body) {
            is Body.Sample -> listOf(x("x1", 1))
            is Body.Entries -> listOf(x("x3", 4), x("x4", 1))
            else -> null
        }
    }
    var served = 0
    var ticks = 0
    while (served == 0 && ticks < 5) {
        ticks += 1
        tool("tick k tempus_edge")
        val got = le.outcomes(1, 1500)
        if (got.isEmpty()) {
            println("B4 tick $ticks of K's edge store: K did not dial this client")
        } else {
            println("B4 tick $ticks of K's edge store, served: ${got[0].line()}")
            val b = got[0].body as? Body.Entries ?: die("B4: no shuffle")
            must(got[0].what == "served" && b.kind == "shuffle" && b.store == "tempus_edge" && b.entries.first().let { it.d.id8() == nodeId && it.age == 0 },
                "B4: the shuffle does not begin with the node's own entry at age 0")
            served = 1
        }
        quiet()
    }
    must(served == 1, "B4: K never shuffled with this client")
    out = step("B5 sample", dial(kAddr, edge, verifier(), sample3, settings))
    must(out.what == "reply" && view(out).containsAll(listOf("${id("x3")}@4", "${id("x4")}@1")), "B5: what this client answered is not in K's edge store")

    // ---------------------------------------------------------------- C
    println("== C. what K refuses, and what this client refuses of K")
    fun closed(label: String, who: Identity, request: Request = sample3, with: Settings = settings) {
        val o = step(label, dial(kAddr, who, verifier(), request, with))
        must(o.what == "closed", "$label: the node did not close with no reply")
    }
    closed("C1 a token another key signed", edge.withToken(token(signer = fixtureKey(96))))
    closed("C2 an expired token", edge.withToken(token(exp = 1400)))
    closed("C3 a token not valid yet", edge.withToken(token(nbf = 1800)))
    closed("C4 a token issued for another key", edge.withToken(token(sub = certificateKey(certs.cert("x1")))))
    closed("C5 a bridge token with a certificate K does not list", edge.withToken(token(typ = "tempus_bridge")))
    out = step("C6 a token under an old kid", dial(kAddr, edge.withToken(token(signer = fixtureKey(96), kid = "k0")), verifier(), sample3, settings))
    must(out.what == "key_rotated" && out.kid?.let { String(it) } == "k1", "C6: no key_rotated naming k1")
    closed("C7 a sample of 9 where K's shuffle length is 3", edge, Request.Sample("tempus_edge", 9), wide)
    closed("C8 an edge's entry offered to the sentinel store", edge, Request.Shuffle("tempus_sentinel", listOf(x("x1", 0))))
    closed("C9 four entries where K's shuffle length is 3", edge, Request.Shuffle("tempus_edge", listOf(edge.entry(0), x("x1", 1), x("x2", 1), x("x3", 1))), wide)
    out = step("C10 a call, to a peer that is not a bridge", dial(kAddr, edge, verifier(), Request.Call("c10".toByteArray(), "demo", "add", listOf(TInt(2), TInt(3))), settings))
    must(out.what == "refused" && out.stage == "request", "C10: the call was sent to a peer that is not a bridge")
    out = step("C11 this client's clock at 2600: K's token has expired", dial(kAddr, edge, verifier(now = 2600), sample3, settings))
    must(out.what == "refused" && out.stage == "advert" && out.reason == "the token has expired", "C11")
    out = step("C12 this client's clock at 500: K's token is not valid yet", dial(kAddr, edge, verifier(now = 500), sample3, settings))
    must(out.what == "refused" && out.stage == "advert" && out.reason == "the token is not valid yet", "C12")
    out = step("C13 K's certificate in this client's whitelist, K's token an edge's", dial(kAddr, edge, verifier(whitelist = setOf(fingerprint(certs.cert("node")))), sample3, settings))
    must(out.what == "refused" && out.reason == "a certificate of the tempus whitelist with a tempus_edge token", "C13")
    out = step("C14 nobody listens", dial(dead, edge, verifier(), sample3, settings))
    must(out.what == "unreachable", "C14")
    out = step("C15 this client holds another producer key as current (k9): it answers K's advert with key_rotated", dial(kAddr, edge, verifier(kid = "k9"), sample3, settings))
    must(out.what == "refused" && out.reason == "key_rotated", "C15")
    // K was dialed, so K's application is not told (it is told when a peer K dialed answers so). K serves on.
    out = step("C16 sample", dial(kAddr, edge, verifier(), sample3, settings))
    must(out.what == "reply", "C16: K does not serve after C15")
    tool("stop k")

    // ---------------------------------------------------------------- D
    println("== D. this client dials a peer that misbehaves (the Python example client, listening)")
    val bridgeList = setOf(fingerprint(certs.cert("x4")))
    fun against(label: String, mode: String, request: Request = sample3, v: Verifier = verifier(), with: Settings = settings, who: Identity = edge): Outcome {
        tool("peer $mode")
        val o = dial(pAddr, who, v, request, with)
        println("$label: ${line(o)}")
        println("$label, the peer: ${tool("peerdone")}")
        return o
    }
    val call = Request.Call("d1".toByteArray(), "demo", "add", listOf(TInt(2), TInt(3)))
    out = against("D1 a call to a peer with a bridge token and a whitelisted certificate", "bridge-result", call, verifier(whitelist = bridgeList))
    must(out.what == "reply" && (out.body as? Body.Result)?.value == TInt(5), "D1: no result of 5")
    out = against("D2 a result that names another req_id", "bridge-other-req-id", call, verifier(whitelist = bridgeList))
    must(out.what == "refused" && out.reason == "the result names another req_id", "D2")
    out = against("D3 a cast", "bridge-cast", Request.Cast("d3".toByteArray(), "demo", "note", listOf(TInt(7))), verifier(whitelist = bridgeList))
    must(out.what == "closed" && out.stage == "reply", "D3")
    out = against("D4 a bridge token, the certificate not in this client's whitelist", "bridge-result", call)
    must(out.what == "refused" && out.stage == "advert" && out.reason == "a tempus_bridge whose certificate is not in the tempus whitelist", "D4")
    out = against("D5 another peer's advert (the channel binding)", "binding")
    must(out.what == "refused" && out.stage == "advert" && out.reason == "the certificate's key is not the advert's pub", "D5")
    out = against("D6 a proof of possession over another nonce", "wrong-proof")
    must(out.what == "refused" && out.stage == "response" && out.reason == "the proof of possession does not verify", "D6")
    out = against("D7 the peer answers this client's advert with key_rotated, naming k9", "names-k9")
    must(out.what == "key_rotated" && out.kid?.let { String(it) } == "k9", "D7")
    out = against("D8 the peer's token is under an old kid: this client answers key_rotated", "old-kid")
    must(out.what == "refused" && out.reason == "key_rotated", "D8")
    out = against("D9 a reply with an entry another key signed, beside a good one", "forged-entry")
    must(out.what == "refused" && out.stage == "reply" && out.reason == "entry 1 does not verify: the signature does not verify", "D9")
    out = against("D10 a reply that names another store", "other-store")
    must(out.what == "refused" && out.reason == "the reply names another store", "D10")
    out = against("D11 a shuffle_reply where a sample_reply was due", "shuffle-reply")
    must(out.what == "refused" && out.reason == "shuffle_reply where sample_reply was due", "D11")
    out = against("D12 more entries than were asked for", "three-entries", Request.Sample("tempus_edge", 1))
    must(out.what == "refused" && out.reason == "more entries than were asked for", "D12")
    out = against("D13 a reply above the frame ceiling", "oversize")
    must(out.what == "refused" && out.reason == "a frame above the ceiling", "D13")
    out = against("D14 the peer closes with no reply", "closes")
    must(out.what == "closed" && out.stage == "reply", "D14")
    out = against("D15 the peer stays silent: this client's one time bound ends the connection", "silent", with = Settings(1500, 3))
    must(out.what == "timeout" && out.stage == "reply", "D15")
    out = against("D16 a sample where the peer's challenge was due", "wrong-frame")
    must(out.what == "refused" && out.stage == "challenge" && out.reason == "sample where pop_challenge or key_rotated was due", "D16")
    out = against("D17 the answer of the test unit's frames (done) as a reply", "done")
    must(out.what == "refused" && out.reason == "unknown kind", "D17")
    out = against("D18 a certificate another key issued", "issued")
    must(out.what == "refused" && out.stage == "tls" && out.reason == "the certificate is not self-signed", "D18")
    out = against("D19 a P-256 certificate", "p256")
    must(out.what in listOf("refused", "tls_failed") && out.stage == "tls", "D19")
    out = against("D20 a peer that speaks TLS 1.2 only", "tls12")
    must(out.what == "tls_failed" && out.stage == "tls", "D20")
    out = against("D21 a peer with another ALPN protocol", "alpn")
    must(out.what in listOf("refused", "tls_failed") && out.stage == "tls", "D21")

    // ---------------------------------------------------------------- E
    println("== E. this client listens and is dialed by a peer that misbehaves (the Python example client, dialing)")
    var index = le.outcomes(1, 0).size
    fun dialed(label: String, mode: String): Outcome {
        val peer = tool("pydial $mode")
        val o = le.outcomes(index + 1, 8000).getOrNull(index) ?: die("$label: the connection did not end")
        index += 1
        println("$label: ${line(o)}")
        println("$label, the peer: $peer")
        return o
    }
    out = dialed("E1 a sample, from a peer whose certificate this client has never seen", "good")
    must(out.what == "served" && out.sent == "reply", "E1")
    out = dialed("E2 a shuffle", "shuffle")
    must(out.what == "served" && out.sent == "reply", "E2")
    out = dialed("E3 another peer's advert (the channel binding)", "binding")
    must(out.what == "refused" && out.stage == "advert" && out.reason == "the certificate's key is not the advert's pub", "E3")
    out = dialed("E4 a proof of possession by another key", "proof-other-key")
    must(out.what == "refused" && out.stage == "response" && out.reason == "the proof of possession does not verify", "E4")
    out = dialed("E5 no proof of possession: the request where it was due", "no-proof")
    must(out.what == "refused" && out.stage == "response" && out.reason == "sample where pop_response was due", "E5")
    out = dialed("E6 an advert above the frame ceiling", "oversize-advert")
    must(out.what == "refused" && out.stage == "advert" && out.reason == "a frame above the ceiling", "E6")
    out = dialed("E7 an expired token", "expired")
    must(out.what == "refused" && out.reason == "the token has expired", "E7")
    out = dialed("E8 a token under an old kid: this client answers key_rotated", "old-kid")
    must(out.what == "refused" && out.reason == "key_rotated", "E8")
    out = dialed("E9 a sentinel token, the certificate not in this client's whitelist", "sentinel-token")
    must(out.what == "refused" && out.reason == "a tempus_sentinel whose certificate is not in the tempus whitelist", "E9")
    out = dialed("E10 the test unit's tick frame as the request", "tick")
    must(out.what == "refused" && out.stage == "request" && out.reason == "unknown kind", "E10")
    out = dialed("E11 a shuffle with an entry another key signed", "forged-shuffle")
    must(out.what == "refused" && out.stage == "request" && out.reason == "entry 1 does not verify: the signature does not verify", "E11")
    out = dialed("E12 a sample of 9 where this client's shuffle length is 3", "sample-9")
    must(out.what == "refused" && out.reason == "n is not 1 to the shuffle length", "E12")
    out = dialed("E13 the peer closes after its advert", "closes")
    must(out.what == "closed" && out.stage == "challenge", "E13")
    out = dialed("E14 a P-256 certificate", "p256")
    must(out.what in listOf("refused", "tls_failed") && out.stage == "tls", "E14")
    le.close()

    // ---------------------------------------------------------------- Q
    println("== Q. node Q, which is not a test node, and this client, both by the machine's clock")
    tool("start q")
    val clock = Verifier(producerPub, "k1".toByteArray(), { System.currentTimeMillis() / 1000 }, 10, emptySet())
    val real = edge.withToken(token(exp = 4000000000))
    fun q(label: String, who: Identity, request: Request) = step(label, dial(qAddr, who, clock, request, settings))
    out = q("Q1 sample", real, sample3)
    must(out.what == "reply" && view(out).isEmpty() && out.advert?.id8() == nodeId, "Q1")
    out = q("Q2 shuffle, own entry at age 0", real, Request.Shuffle("tempus_edge", listOf(real.entry(0))))
    must(out.what == "reply", "Q2")
    out = q("Q3 sample", real, sample3)
    must(out.what == "reply" && view(out) == listOf("${id("other")}@0"), "Q3: this client is not in Q's edge store")
    out = q("Q4 a token that ended at 3000 seconds after 1970", edge, sample3)
    must(out.what == "closed", "Q4")
    out = q("Q5 a token that begins at 3900000000 seconds after 1970", edge.withToken(token(nbf = 3900000000, exp = 4000000000)), sample3)
    must(out.what == "closed", "Q5")
    println("Q6 the command line, dial: ${tool("cli-dial")}")
    quiet()
    println("Q7 the command line, listen: ${tool("cli-listen")}")
    tool("stop q")
    println("[c6] the Kotlin client's walk passed")
    System.out.flush()
    exitProcess(0)
}
