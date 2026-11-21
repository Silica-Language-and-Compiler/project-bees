// Tests of the gossip part of the Kotlin example TEMPUS client (lib/Gossip.kt), run by a plain main function:
//
//   make -C example_tempus_clients/kotlin test
//
// Group 1, the view rules and the store's steps on cases worked by hand (the answer is in each check). Group 2, three
// peers of this library in one process, over mutual TLS 1.3 on 127.0.0.1: a sentinel and two edges that are given the
// sentinel's address only; each edge must come to hold the other. The keys and tokens are TEST ONLY fixtures.
// Every line printed is the same on every run.
package bees.tempus.test

import bees.tempus.*
import java.net.ServerSocket
import java.nio.file.Path
import kotlin.system.exitProcess

private var passed = 0
private var failed = 0

private fun check(name: String, block: () -> Unit) {
    try {
        block()
        passed += 1
        println("ok    $name")
    } catch (e: Throwable) {
        failed += 1
        println("FAIL  $name: ${e.javaClass.simpleName}: ${e.message}")
    }
}

private fun eq(a: Any?, b: Any?, what: String = "") {
    if (a != b) throw AssertionError("$what: got $a, wanted $b")
}

private val D = Descriptor(ByteArray(64), ByteArray(32), "127.0.0.1:1".toByteArray(), ByteArray(65))
private fun h(id: String, age: Int) = Held(id, D, age)
private fun text(v: List<Held>) = v.joinToString(" ") { "${it.id}@${it.age}" }

private fun rules() {
    check("rules: every age rises by one and stops at 65535") {
        eq(text(ageAll(listOf(h("a", 0), h("b", 65534), h("c", 65535)))), "a@1 b@65535 c@65535")
    }
    check("rules: the partner is the oldest; the first draw settles a tie; the others are drawn without replacement") {
        val s = select(listOf(h("a", 3), h("b", 7), h("c", 7), h("d", 1)), 3, listOf(1, 0, 1))
        eq(s.partner.id, "c")                                   // the oldest are b and c; draw 1 takes the second
        eq(text(s.sent), "a@3 d@1")                             // of a b d: draw 0 takes a, then of b d: draw 1 takes d
        eq(text(s.rest), "b@7")
    }
    check("rules: the partner's choice never holds the asker") {
        val (sent, rest) = replySelect(listOf(h("a", 1), h("x", 2), h("b", 3)), 2, "x", listOf(0, 0))
        eq(text(sent), "a@1 b@3")
        eq(text(rest), "x@2")
    }
    check("rules: the merge prefers the younger, keeps its own at equal age, drops itself and evicts the oldest") {
        val got = merge(listOf(h("a", 5), h("b", 2), h("c", 9)), listOf(h("me", 0), h("a", 1), h("b", 2), h("d", 9), h("a", 0)), "me", 3)
        // received, once each: a@0 (the younger of two), b@2, d@9. a wins (0 < 5); b does not (equal age); d is new.
        // a@0 d@9 b@2 c@9 is one too many: the oldest are d and c, and the latest in order, c, goes.
        eq(text(got), "a@0 d@9 b@2")
    }
    check("rules: a received entry that was just sent younger becomes the sent one") {
        eq(text(preferSent(listOf(h("a", 4), h("b", 1)), listOf(h("a", 2), h("b", 1)))), "a@2 b@1")
    }
    check("rules: sent entries go back while there is room") {
        eq(text(backfill(listOf(h("a", 1)), listOf(h("a", 0), h("b", 2), h("c", 3)), 2)), "a@1 b@2")
    }
    check("store: a tick in the peer's own store sends shuffle length - 1 others; a failed shuffle drops the partner only") {
        val st = Store("me", true, 4, 2)
        for (e in listOf(h("a", 0), h("b", 4), h("c", 1))) st.insert(e)
        val act = st.tick(listOf(0, 0, 0)) as TickAct.Shuffle
        eq(act.partner.id, "b")
        eq(act.others.size, 1)
        eq(st.view.size, 1)
        eq(st.tick(listOf(0)) is TickAct.Aged, true)
        st.failed()
        eq(st.view.map { it.id }.sorted(), listOf("a", "c"))
    }
    check("store: in a store of another type the partner that answered re-enters at age 0") {
        val st = Store("me", false, 4, 2)
        for (e in listOf(h("a", 0), h("b", 4))) st.insert(e)
        val act = st.tick(listOf(0, 0, 0, 0)) as TickAct.Shuffle
        eq(act.partner.id, "b")
        eq(act.others.size, 1)                                   // shuffle length others, but only a is left
        st.reply(listOf(h("d", 3)))
        eq(text(st.view), "b@0 d@3 a@1")
    }
    check("store: a request or a reply of more than the shuffle length is refused") {
        val st = Store("me", true, 4, 1)
        st.insert(h("a", 0))
        eq(st.request("x", listOf(h("b", 0), h("c", 0)), listOf(0)), null)
        st.tick(listOf(0))
        st.reply(listOf(h("b", 0), h("c", 0)))
        eq(text(st.view), "")                                    // counted as failed: the partner stays out
    }
}

private fun freePort(): Int = ServerSocket(0).use { it.localPort }

private fun network(root: Path) {
    val certs = Certs(root)
    val far = 4000000000L
    val names = listOf("sentinel", "node", "other")
    val ports = names.map { freePort() }
    val ids = names.mapIndexed { k, n -> certs.identity(n, if (k == 0) "tempus_sentinel" else "tempus_edge", 1000, far, "127.0.0.1:${ports[k]}") }
    // the test producer's public key, from the generated fixture unit (tools/bees_tempus_ids.py)
    val producerPub = unhex(constant(java.nio.file.Files.readString(root.resolve("trials/c2_tempus_clients/lib/tempus_ids.silica")), "producer_pub_hex"))
    val whitelist = setOf(fingerprint(certs.cert("sentinel")))
    val stores = PEER_TYPES.associateWith { StoreSettings(4, 3, 150) }
    val learned = names.map { HashMap<String, HashSet<String>>() }
    val peers = ArrayList<Peer>()
    check("network: two edges that know only the sentinel's address come to hold each other") {
        try {
            for (k in names.indices) {
                val verifier = Verifier(producerPub, "k1".toByteArray(), { System.currentTimeMillis() / 1000 }, 10, whitelist)
                val settings = PeerSettings(stores, 3000, if (k == 0) emptyList() else listOf("127.0.0.1:${ports[0]}"), 200, 800)
                peers.add(Peer(ids[k], verifier, settings, "127.0.0.1", ports[k], onLearned = { store, d ->
                    synchronized(learned) { learned[k].getOrPut(store) { HashSet() }.add(hex(d.id)) }
                }).start())
            }
            fun complete(): Boolean = synchronized(learned) {
                val id = ids.map { hex(it.peerId) }
                (learned[1]["tempus_edge"]?.contains(id[2]) ?: false) && (learned[2]["tempus_edge"]?.contains(id[1]) ?: false) &&
                    (1..2).all { learned[it]["tempus_sentinel"]?.contains(id[0]) ?: false } &&
                    (learned[0]["tempus_edge"]?.containsAll(listOf(id[1], id[2])) ?: false)
            }
            val until = System.nanoTime() + 20_000_000_000L
            while (!complete() && System.nanoTime() < until) Thread.sleep(50)
            eq(complete(), true, "what was learned in 20 s")
            for (p in peers) for (t in PEER_TYPES) {
                val v = p.view(t)
                eq(v.size <= 4 && v.map { it.id }.toSet().size == v.size && v.none { it.id == hex(p.identity.peerId) }, true, "the view of $t")
            }
        } finally {
            for (p in peers) p.stop()
        }
    }
}

fun main(argv: Array<String>) {
    val root = Path.of(if (argv.isNotEmpty()) argv[0] else ".").toAbsolutePath().normalize()
    rules()
    network(root)
    println("[kotlin client gossip tests] $passed passed, $failed failed")
    exitProcess(if (failed == 0) 0 else 1)
}
