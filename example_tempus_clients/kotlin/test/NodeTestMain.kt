// Tests of the node part of the Kotlin extension, run by a plain main function:
//
//   make -C example_tempus_clients/kotlin test
//
// Group 1, the view and the store against the two independent Python models and the goldens of trials/t0_tempus_view
// and trials/t1_tempus_store: test/model_cases.py records every call of a model function behind every line of those
// goldens, and the same kinds of call on generated views and stores; each call is made again here and must give the
// same answer. Group 2, the clock: every line of the golden of trials/t0_tempus_clock is computed again. Group 3, the
// configuration: the refusals of tools/test_bees_tempus_conf.py that a value can show, and the start refusals of
// trials/c4_tempus_boot with their texts. Group 4, the node's own judgement of an entry on the cases of
// trials/t4_tempus_admission. Group 5, three nodes of this extension in one process, over mutual TLS 1.3 on 127.0.0.1:
// a sentinel and two edges that are given the sentinel's address only, with test clocks, timers the test runs and
// literal draws; each edge must come to hold the other. No Silica program runs. Every line printed is the same on
// every run.
package bees.tempus.test

import bees.tempus.*
import java.net.ServerSocket
import java.nio.file.Files
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

// ---------------------------------------------------------------- group 1: the models
private fun ent(s: String): Held<String>? = if (s == "-") null else s.split('~').let { Held(it[0], it[1], it[2].toInt()) }
private fun view(s: String): List<Held<String>> = if (s == "-") emptyList() else s.split(',').map { ent(it)!! }
private fun draws(s: String): List<Long>? = when (s) { "N" -> null; "-" -> emptyList(); else -> s.split(',').map { it.toLong() } }
private fun show(e: Held<String>?): String = if (e == null) "-" else "${e.id}~${e.d}~${e.age}"
private fun show(v: List<Held<String>>): String = if (v.isEmpty()) "-" else v.joinToString(",") { show(it) }
private fun showDraws(d: List<Long>?): String = if (d == null) "N" else if (d.isEmpty()) "-" else d.joinToString(",")

private fun viewCase(f: List<String>): Pair<String, String> = when (f[1]) {
    "ageAll" -> show(View.ageAll(view(f[2]))) to f[3]
    "select" -> View.select(view(f[2]), f[3].toInt(), draws(f[4])!!).let { "${if (it.partner != null) 1 else 0}|${show(it.partner)}|${show(it.sent)}|${show(it.rest)}" } to f.drop(5).joinToString("|")
    "outgoing" -> show(View.outgoing(f[2], f[3], view(f[4]))) to f[5]
    "replySelect" -> View.replySelect(view(f[2]), f[3].toInt(), f[4], draws(f[5])!!).let { "${show(it.first)}|${show(it.second)}" } to "${f[6]}|${f[7]}"
    "merge" -> show(View.merge(view(f[2]), view(f[3]), f[4], f[5].toInt())) to f[6]
    "preferSent" -> show(View.preferSent(view(f[2]), view(f[3]))) to f[4]
    "backfill" -> show(View.backfill(view(f[2]), view(f[3]), f[4].toInt())) to f[5]
    "insert" -> show(View.insert(view(f[2]), ent(f[3])!!, f[4], f[5].toInt())) to f[6]
    "sample" -> show(View.sample(view(f[2]), f[3].toInt(), draws(f[4])!!)) to f[5]
    "valid" -> (if (View.valid(view(f[2]), f[3], f[4].toInt())) "1" else "0") to f[5]
    else -> throw AssertionError("no such view function: ${f[1]}")
}

private fun state(s: Store<String>): String =
    listOf(s.selfId, s.selfD, if (s.own) "1" else "0", s.cap.toString(), s.count.toString(), show(s.view), show(s.sent), show(s.partner), showDraws(s.tickDraws),
        showDraws(s.replyDraws)).joinToString("|")

private fun storeCase(f: List<String>): Pair<String, String> {
    val s = Store(f[1], f[2], f[3] == "1", f[4].toInt(), f[5].toInt())
    s.view = view(f[6]); s.sent = view(f[7]); s.partner = ent(f[8]); s.tickDraws = draws(f[9]); s.replyDraws = draws(f[10])
    val arg = f[12]
    val out = when (f[11]) {
        "insert" -> { s.insert(ent(arg)!!); "" }
        "drop" -> { s.drop(arg); "" }
        "tick" -> when (val t = s.tick()) {
            is Tick.Skipped -> "skipped"
            is Tick.Aged -> "aged"
            is Tick.Empty -> "empty"
            is Tick.Shuffle -> "shuffle;${show(t.partner)};${show(t.buffer)}"
        }
        "failed" -> { s.failed(); "" }
        "reply" -> { if (s.inFlight) s.reply(view(arg)); "" }
        "request" -> arg.split(';').let { a -> s.request(a[0], view(a[1]))?.let { show(it) } ?: "N" }
        "sample" -> s.sample(arg.toInt())?.let { show(it) } ?: "N"
        else -> throw AssertionError("no such step: ${f[11]}")
    }
    return "$out|${state(s)}" to f.drop(13).joinToString("|")
}

private fun models(cases: Path) {
    val lines = Files.readAllLines(cases)
    val fromGoldens = lines[1].substringAfterLast(' ').toInt()
    val body = lines.drop(2)
    fun run(what: String, part: List<String>, kind: Char) = check("$what: ${part.count { it[0] == kind }} calls give the model's answers") {
        for (line in part) {
            if (line[0] != kind) continue
            val f = line.split('|')
            val (mine, want) = if (kind == 'V') viewCase(f) else storeCase(f)
            if (mine != want) throw AssertionError("$line\n      got $mine")
        }
    }
    check("models: the model's lines are the goldens of trials/t0_tempus_view and trials/t1_tempus_store (${lines[0].substringAfterLast(' ')} files)") {
        eq(lines[0].startsWith("# goldens "), true)
    }
    run("view, the calls behind the goldens", body.take(fromGoldens), 'V')
    run("store, the steps behind the goldens", body.take(fromGoldens), 'S')
    run("view, generated cases", body.drop(fromGoldens), 'V')
    run("store, generated cases", body.drop(fromGoldens), 'S')
}

// ---------------------------------------------------------------- group 2: the clock
private fun clockGolden(root: Path) {
    val leaf = root.resolve("trials/t0_tempus_clock")
    val goldens = Files.list(leaf).use { s -> s.filter { it.fileName.toString().matches(Regex("""clock\..*\.scout""")) }.sorted().toList() }
    check("clock: there is a recorded output to compare with") { eq(goldens.isNotEmpty(), true) }
    val one = Regex("""^(follow|hold|stop limit (\d+)): time (\d+), reading (\d+) -> .*$""")
    val head = Regex("""^clock_back (follow|hold|stop)(?: limit (\d+))?, clock_fail (continue|pause)$""")
    val reading = Regex("""^  reading (no time|\d+) -> .*$""")
    val states = mapOf(0 to "no reading yet", 3 to "no reading yet, application told", 1 to "good", 2 to "paused, waits for the clock",
        6 to "goes on with its last reading", 5 to "holds its time", 4 to "stopped")
    val says = mapOf(0 to "nothing", 1 to "first reading: one line, listen", 2 to "no time at start: one line, application told",
        3 to "no time, pause: one line, application told", 4 to "no time, continue: one line, application told", 6 to "step back followed: one line",
        7 to "step back, hold begins: one line", 8 to "the held time is reached: one line", 9 to "step back above the limit: one line, application told, stop")
    for (path in goldens) check("clock ${path.fileName}: every line of the golden is computed again") {
        var back = ""; var limit = 0L; var fail = ""; var ck = 0; var now = 0L; var lines = 0
        for (line in Files.readAllLines(path)) {
            val m1 = one.find(line); val m2 = head.find(line); val m3 = reading.find(line)
            val mine = when {
                m1 != null -> {
                    val b = clockBack(m1.groupValues[3].toLong(), m1.groupValues[4].toLong(), m1.groupValues[1].substringBefore(' '), m1.groupValues[2].ifEmpty { "0" }.toLong())
                    "${m1.groupValues[1]}: time ${m1.groupValues[3]}, reading ${m1.groupValues[4]} -> time ${b.now}, " +
                        listOf("not earlier", "earlier, followed", "earlier, held", "earlier, the node stops")[b.act]
                }
                m2 != null -> { back = m2.groupValues[1]; limit = m2.groupValues[2].ifEmpty { "0" }.toLong(); fail = m2.groupValues[3]; ck = 0; now = 0; line }
                m3 != null -> {
                    val t = clockTurn(ck, now, m3.groupValues[1].toLongOrNull(), back, limit, fail)
                    ck = t.ck; now = t.now
                    val accepts = when {
                        ck == 0 || ck == 3 -> "does not listen yet"
                        ClockState.closes(ck) == "clock_refused" -> "closes accepted connections (role 4, clock_refused)"
                        ClockState.closes(ck) == "clock_stopped" -> "closes accepted connections (role 5, clock_stopped)"
                        else -> "accepts"
                    }
                    "  reading ${m3.groupValues[1]} -> time $now; ${states[ck]}; ${if (ClockState.ticks(ck)) "ticks" else "no ticks"}; $accepts; does: " +
                        (if (t.again) "read again: one line; then " else "") + says[t.say]
                }
                else -> line
            }
            eq(mine, line)
            if (m1 != null || m3 != null) lines += 1
        }
        if (lines < 70) throw AssertionError("only $lines lines were computed")
    }
}

// ---------------------------------------------------------------- group 3: the configuration
private fun configuration(root: Path) {
    val certs = Certs(root)
    val store = StoreConfig(4, 3, 1000)
    val small = StoreConfig(4, 2, 1000)
    val sentinelCert = certs.cert("sentinel")
    fun conf(role: String = "edge", addr: String = "127.0.0.1", port: Int = 24300, sentinels: List<SentinelAddress> = listOf(SentinelAddress("127.0.0.1", 24301, "s1")),
             edge: StoreConfig = store, key: ByteArray = ByteArray(32), kid: String = "k1", timeout: Long = 2000, inflight: Int = 2, skew: Long = 10000,
             back: String = "follow", limit: Long? = null, fail: String = "pause", read: Long = 1000, jinit: Long = 200, jmax: Long = 800) =
        TempusConfig(role, addr, port, sentinels, edge, small, small, kid.toByteArray(), key, mapOf("s1" to sentinelCert), timeout, inflight, skew, back, limit,
            fail, read, jinit, jmax)
    fun refused(c: TempusConfig, part: String) {
        val why = c.refusal() ?: throw AssertionError("not refused, wanted \"$part\"")
        if (!why.contains(part)) throw AssertionError("refused with \"$why\", wanted \"$part\"")
    }
    check("configuration: a good value is accepted, for an edge and for a first sentinel") {
        eq(conf().refusal(), null)
        eq(conf(role = "sentinel", sentinels = emptyList()).refusal(), null)
        eq(conf(back = "stop", limit = 0).refusal(), null); eq(conf(back = "stop", limit = 86400).refusal(), null)
        eq(conf(back = "hold", fail = "continue").refusal(), null)
        eq(conf(read = 100).refusal(), null); eq(conf(read = 60000).refusal(), null)
    }
    check("configuration: the bounds of tools/test_bees_tempus_conf.py, with its words") {
        refused(conf(edge = StoreConfig(257, 3, 1000)), "257 is above 256")
        refused(conf(edge = StoreConfig(4, 5, 1000)), "above the capacity 4")
        refused(conf(key = ByteArray(31)), "32 bytes")
        refused(conf(jmax = 150), "below join_retry_initial_ms")
        refused(conf(edge = StoreConfig(4, 3, 99)), "tempus.edge.tick_ms: 99 is below 100 (bounds 100 to 3600000; never clamped)")
        refused(conf(timeout = 60001), "tempus.shuffle_timeout_ms: 60001 is above 60000")
        refused(conf(inflight = 65), "tempus.inflight_max"); refused(conf(skew = 300001), "tempus.clock_skew_ms"); refused(conf(port = 0), "tempus.port")
    }
    check("configuration: sentinels are required unless the node is the first sentinel") {
        refused(conf(sentinels = emptyList()), "required unless the node is the first sentinel")
        refused(conf(sentinels = List(17) { SentinelAddress("127.0.0.1", 24301, "s1") }), "1 to 16")
        refused(conf(sentinels = listOf(SentinelAddress("127.0.0.1", 24301, "nobody"))), "names no entry of the tempus whitelist")
    }
    check("configuration: the clock's choices are closed sets, and the limit belongs to stop alone") {
        refused(conf(back = "ignore"), "expected one of follow, hold, stop"); refused(conf(back = "1"), "expected one of follow, hold, stop")
        refused(conf(fail = "stop"), "expected one of continue, pause"); refused(conf(fail = "true"), "expected one of continue, pause")
        refused(conf(back = "stop"), "tempus.clock_back_limit_s: required when clock_back is stop")
        refused(conf(back = "follow", limit = 30), "remove clock_back_limit_s"); refused(conf(back = "hold", limit = 30), "remove clock_back_limit_s")
        refused(conf(back = "stop", limit = -1), "clock_back_limit_s"); refused(conf(back = "stop", limit = 86401), "clock_back_limit_s")
        refused(conf(read = 99), "clock_read_ms"); refused(conf(read = 60001), "clock_read_ms")
    }
    check("configuration: the bridge role is refused, and a role outside the set") {
        refused(conf(role = "bridge"), "bridge needs mode tempus-trust")
        refused(conf(role = "client"), "expected one of edge, bridge, sentinel")
    }
    // the start refusals of the Silica node (trials/c4_tempus_boot): the same fault gives the same line
    val leaf = root.resolve("trials/c4_tempus_boot")
    val me = certs.identity("node", "tempus_edge", 1000, 2000, "127.0.0.1:24300")
    val three = listOf(store, small, small)
    fun boot(typ: Int = 1, token: ByteArray = me.token, key: Int = 32, stores: List<StoreConfig> = three, back: Int = 1) =
        bootWhy(typ, 64, me.pub, 32, token, 2, key, 2, 2000, 200, 800, 10, 128, stores, back, 0, 2, 1000)
    val faults = linkedMapOf(
        "capacity" to boot(stores = listOf(StoreConfig(257, 3, 1000), small, small)),
        "shuffle" to boot(stores = listOf(StoreConfig(4, 5, 1000), small, small)),
        "producer" to boot(key = 31),
        "clockback" to boot(back = 4),
        "token" to boot(token = certs.identity("node", "tempus_bridge", 1000, 2000, "127.0.0.1:24300").token))
    check("start refusals: a good set of values is not refused") { eq(boot(), null) }
    for ((name, mine) in faults) {
        val goldens = Files.list(leaf).use { s -> s.filter { it.fileName.toString().matches(Regex("""dangerous_$name\..*\.scout""")) }.sorted().toList() }
        check("start refusals: the fault of trials/c4_tempus_boot dangerous_$name is refused with the Silica node's line (${goldens.size} goldens)") {
            eq(goldens.isNotEmpty(), true)
            for (g in goldens) eq("tempus: boot refused: $mine", Files.readAllLines(g)[0])
        }
    }
    check("start refusals: a node's own token must read, be of the node's type and name the node's key") {
        eq(startRefusal(conf(), me), null)
        eq(startRefusal(conf(role = "sentinel", sentinels = emptyList()), me), "the node's token is for another peer type than the node's")
        eq(startRefusal(conf(), me.withToken(certs.identity("other", "tempus_edge", 1000, 2000, "127.0.0.1:1").token)), "the node's token names another key")
        eq(startRefusal(conf(), me.withToken(ByteArray(70))), "the node's token does not read: bad_version")
        try { TempusNode.start(conf(role = "bridge"), me, { _, _ -> }, testEnvironment(TestClock(1500), ManualTimers(), emptyList(), Lines())); throw AssertionError("started") }
        catch (e: ConfigRefused) { eq(e.why.contains("cannot be a bridge"), true) }
    }
}

// ---------------------------------------------------------------- group 4: the node's judgement of an entry
private fun admission(root: Path) {
    val leaf = root.resolve("trials/t4_tempus_admission")
    val text = String(Files.readAllBytes(leaf.resolve("lib/tempus_fixtures.silica")))
    val goldens = Files.list(leaf).use { s -> s.filter { it.fileName.toString().matches(Regex("""dangerous_admit\..*\.scout""")) }.sorted().toList() }
    val stores = mapOf("1" to "tempus_edge", "2" to "tempus_bridge", "3" to "tempus_sentinel")
    val me = Certs(root).identity("node", "tempus_edge", 1000, 2000, "127.0.0.1:1")
    val v = ConnValues(me, constant(text, "kid").toByteArray(), unhex(constant(text, "producer_pub_hex")), constant(text, "now").toLong(),
        constant(text, "skew").toLong(), emptyList(), 3, 1000)
    val names = table(text, "name"); val kinds = table(text, "kind"); val ids = table(text, "id_hex"); val pubs = table(text, "pub_hex")
    val tokens = table(text, "token_hex"); val wants = table(text, "want")
    for (path in goldens) {
        val said = Files.readAllLines(path).filter { it.contains(": ") }.associate { it.substringBefore(": ") to it.substringAfter(": ") }
        check("the node's entry check, ${path.fileName}: the verdict and the reason the Silica node gave, on every descriptor case") {
            var n = 0
            names.forEachIndexed { i, name ->
                if (kinds[i] != "1") return@forEachIndexed
                val mine = try {
                    val d = readDescriptor(Descriptor(unhex(ids[i]), unhex(pubs[i]), constant(text, "addr").toByteArray(), unhex(tokens[i])).term())
                    entryWhy(d, stores.getValue(wants[i]), v)?.let { "refused: $it" } ?: "admitted"
                } catch (e: Refused) { "refused: ${e.why}" }
                eq(mine, said[name], name)
                n += 1
            }
            if (n < 10) throw AssertionError("only $n cases")
        }
    }
}

// ---------------------------------------------------------------- group 5: nodes of this extension together
private fun network(root: Path) {
    val certs = Certs(root)
    val names = listOf("sentinel", "node", "other")
    val ports = names.map { ServerSocket(0).use { s -> s.localPort } }
    val ids = names.mapIndexed { k, n -> certs.identity(n, if (k == 0) "tempus_sentinel" else "tempus_edge", 1000, 3000, "127.0.0.1:${ports[k]}") }
    val idHex = ids.map { hex(it.peerId) }
    val producerPub = unhex(constant(Files.readString(root.resolve("trials/c2_tempus_clients/lib/tempus_ids.silica")), "producer_pub_hex"))
    val lines = names.map { Lines() }
    val timers = names.map { ManualTimers() }
    // the last view each node reported of each store
    val views = names.map { HashMap<String, List<Entry>>() }
    val nodes = ArrayList<TempusNode>()
    fun holds(k: Int, store: String, other: Int) = synchronized(views) { views[k][store].orEmpty().any { hex(it.d.id) == idHex[other] } }
    check("network: two edges that know only the sentinel's address come to hold each other") {
        try {
            for (k in names.indices) {
                val config = TempusConfig(if (k == 0) "sentinel" else "edge", "127.0.0.1", ports[k],
                    if (k == 0) emptyList() else listOf(SentinelAddress("127.0.0.1", ports[0], "s")), StoreConfig(4, 3, 1000), StoreConfig(4, 2, 1000),
                    StoreConfig(4, 2, 1000), "k1".toByteArray(), producerPub, mapOf("s" to certs.cert("sentinel")), 3000, 4, 10000, "follow", null, "pause",
                    1000, 200, 800)
                nodes.add(TempusNode.start(config, ids[k], { _, e -> if (e is NodeEvent.ViewChanged) synchronized(views) { views[k][e.store] = e.entries } },
                    testEnvironment(TestClock(1500), timers[k], listOf(0L, 1L, 2L, 3L), lines[k])))
                // the node reads its clock at once, then listens and joins
                val ready = if (k == 0) "^join: no sentinel is configured$" else "^join: done$"
                lines[k].await(Regex(ready)) ?: throw AssertionError("${names[k]} did not write /$ready/: ${lines[k].snapshot()}")
            }
            // the second edge joined after the first and was given it by the sentinel; the first holds nobody yet
            eq(holds(2, "tempus_edge", 1), true, "the second edge holds the first after its join")
            eq(holds(1, "tempus_edge", 2), false, "the first edge holds the second after the joins")
            // the second edge's edge store ticks: it shuffles with the first, which so learns of it
            eq(timers[2].fire("tick tempus_edge"), true, "the second edge's tick was armed")
            eq(lines[2].await(Regex("^tick tempus_edge: shuffle (merged|failed)$")), "tick tempus_edge: shuffle merged")
            // the first edge took the second into its view before it answered
            eq(holds(1, "tempus_edge", 2), true, "the first edge holds the second")
            for (k in 1..2) eq(holds(k, "tempus_sentinel", 0), true, "${names[k]} holds the sentinel")
            eq(holds(0, "tempus_edge", 1) && holds(0, "tempus_edge", 2), true, "the sentinel holds both edges")
            for (k in names.indices) for ((store, v) in synchronized(views) { HashMap(views[k]) }) {
                val vid = v.map { hex(it.d.id) }
                eq(v.size <= 4 && vid.toSet().size == v.size && idHex[k] !in vid, true, "the view of $store at ${names[k]}")
            }
        } finally {
            for (n in nodes) n.close()
        }
    }
}

fun main(argv: Array<String>) {
    val root = Path.of(argv.getOrElse(0) { "." })
    models(Path.of(argv[1]))
    clockGolden(root)
    configuration(root)
    admission(root)
    network(root)
    println("$passed passed, $failed failed")
    exitProcess(if (failed == 0) 0 else 1)
}
