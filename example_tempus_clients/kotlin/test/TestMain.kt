// Tests of the Kotlin example TEMPUS client, run by a plain main function (no test library is needed):
//
//   make -C example_tempus_clients/kotlin test
//
// Group 1, the frames golden: trials/t2_tempus_frames prints, for every frame and token it writes or mutates, a line
// `NAME hex HEX` and a line `NAME read: ...` saying what the Silica reader made of it. These tests build the same
// frames and tokens from the same inputs and require the same bytes, and read every HEX and require the same verdict.
// Group 2, the codec on its own. Group 3, the TEST ONLY identities and tokens of tools/bees_tempus_ids.py, byte for
// byte (Ed25519 signatures are deterministic). Group 4, the admission cases of trials/t4_tempus_admission. Group 5,
// the client against itself over mutual TLS 1.3 on 127.0.0.1, a port the system assigns. No Silica program runs.
// Every line printed is the same on every run.
package bees.tempus.test

import bees.tempus.*
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

private fun refusedWith(why: String?, block: () -> Unit) {
    try {
        block()
    } catch (e: Refused) {
        if (why != null && !e.why.contains(why)) throw AssertionError("refused with \"${e.why}\", wanted \"$why\"")
        return
    }
    throw AssertionError("not refused" + (why?.let { ", wanted \"$it\"" } ?: ""))
}

// ---------------------------------------------------------------- group 1: the fixed values of trials/t2_tempus_frames
private const val ADDR = "127.0.0.1:22801"
private val SIG = ByteArray(64) { 'S'.code.toByte() }
private val PUB = ByteArray(32) { 'p'.code.toByte() }
private val TOKEN = SIG + tokenPayload("k1", PUB, "tempus_edge", 1000, 2000)
private const val SHUFFLE_LENGTH = 3
// what the Silica library does not read and this client does not either: the frames of the test unit
private val TEST_FRAMES = setOf("tick", "clock", "clock of no time", "clock with a later reading", "clock before -1", "clock whose wait is 0")

private fun rep(ch: Char, n: Int) = ByteArray(n) { ch.code.toByte() }
private fun desc(id: ByteArray, pub: ByteArray = PUB, addr: String = ADDR, token: ByteArray = TOKEN) = Descriptor(id, pub, addr.toByteArray(), token)
private fun peer(ch: Char, age: Int) = Entry(age, desc(rep(ch, 64)))

private fun built(): Map<String, ByteArray> {
    val three = listOf(peer('A', 0), peer('B', 7), peer('C', 65535))
    val four = listOf(peer('D', 1)) + three
    fun one(d: Descriptor) = listOf(Entry(0, d))
    return linkedMapOf(
        "advert" to advert(desc(rep('A', 64))),
        "pop_challenge" to challenge(rep('N', 32)),
        "pop_response" to response(rep('G', 64)),
        "key_rotated" to keyRotated("k2".toByteArray()),
        "shuffle" to shuffle("tempus_edge", three),
        "shuffle_reply" to shuffleReply("tempus_bridge", emptyList()),
        "sample" to sample("tempus_sentinel", 2),
        "sample_reply" to sampleReply("tempus_sentinel", listOf(peer('B', 7))),
        "token" to TOKEN,
        "token of a bridge" to SIG + tokenPayload("producer-key-2026", rep('q', 32), "tempus_bridge", 0, 1763424300),
        "token whose exp is not after nbf" to SIG + tokenPayload("k1", PUB, "tempus_edge", 2000, 2000),
        "token with a 31-byte sub" to SIG + tokenPayload("k1", rep('p', 31), "tempus_edge", 1000, 2000),
        "token with an empty kid" to SIG + tokenPayload("", PUB, "tempus_edge", 1000, 2000),
        "token with a 65-byte kid" to SIG + tokenPayload("k".repeat(65), PUB, "tempus_edge", 1000, 2000),
        "shuffle of four entries, shuffle length three" to shuffle("tempus_edge", four),
        "entry of age 65536" to shuffle("tempus_edge", listOf(peer('A', 65536))),
        "entry with a 63-byte id" to shuffle("tempus_edge", one(desc(rep('A', 63)))),
        "entry with a 31-byte pub" to shuffle("tempus_edge", one(desc(rep('A', 64), pub = rep('p', 31)))),
        "entry with a 2-byte addr" to shuffle("tempus_edge", one(desc(rep('A', 64), addr = "a:"))),
        "entry with a 262-byte addr" to shuffle("tempus_edge", one(desc(rep('A', 64), addr = "a".repeat(262)))),
        "entry with a 64-byte token" to shuffle("tempus_edge", one(desc(rep('A', 64), token = SIG))),
        "advert with a 65-byte id" to advert(desc(rep('A', 65))),
        "sample of 0" to sample("tempus_edge", 0),
        "sample of 4, shuffle length three" to sample("tempus_edge", 4),
        "nonce of 31 bytes" to challenge(rep('N', 31)),
        "sig of 65 bytes" to response(rep('G', 65)),
        "kid of no bytes" to keyRotated(ByteArray(0)),
    )
}

/** name -> (bytes, the Silica reader's text) from one output of the frames trial */
private fun parse(path: Path): Map<String, Pair<ByteArray, String>> {
    val hexes = LinkedHashMap<String, ByteArray>()
    val reads = HashMap<String, String>()
    for (line in Files.readAllLines(path)) {
        if (line.contains(" hex ")) hexes[line.substringBefore(" hex ")] = unhex(line.substringAfter(" hex "))
        else if (line.endsWith(" hex")) hexes[line.removeSuffix(" hex")] = ByteArray(0)
        else if (line.contains(" read: ")) reads[line.substringBefore(" read: ")] = line.substringAfter(" read: ")
    }
    return hexes.mapValues { (name, bytes) -> bytes to reads.getValue(name) }
}

private fun accepts(name: String, data: ByteArray): String? = try {
    if (name.startsWith("token")) readToken(data) else readBody(data, SHUFFLE_LENGTH)
    null
} catch (e: Refused) {
    e.why
}

private fun framesGolden(root: Path) {
    val leaf = root.resolve("trials/t2_tempus_frames")
    val goldens = Files.list(leaf).use { s -> s.filter { it.fileName.toString().matches(Regex("""frames\..*\.scout""")) }.sorted().toList() }
    check("frames golden: there is a recorded output to compare with") { if (goldens.isEmpty()) throw AssertionError("no frames.*.scout in $leaf") }
    for (path in goldens) {
        val name = path.fileName.toString()
        val seen = parse(path)
        check("frames golden $name: the same bytes from the same inputs (${built().size} frames and tokens)") {
            for ((n, data) in built()) eq(hex(data), hex((seen[n] ?: throw AssertionError("no line for $n")).first), n)
        }
        check("frames golden $name: the same verdict on every frame the library reads") {
            var n = 0
            for ((frameName, pair) in seen) {
                val (data, text) = pair
                if (frameName in TEST_FRAMES || frameName == "done") continue
                val silicaOk = !text.contains("refused")
                val why = accepts(frameName, data)
                if ((why == null) != silicaOk) throw AssertionError("$frameName: Silica says \"$text\", Kotlin says \"${why ?: "accepted"}\"")
                n += 1
            }
            if (n < 37) throw AssertionError("only $n frames compared")
        }
        check("frames golden $name: the test unit's frames (tick, clock) and their answer (done) are frames of no kind to this client") {
            for (frameName in TEST_FRAMES + "done") eq(accepts(frameName, seen.getValue(frameName).first), "unknown kind", frameName)
        }
        check("frames golden $name: the same fields read") {
            val b = readBody(seen.getValue("shuffle").first, SHUFFLE_LENGTH) as Body.Entries
            eq(b.kind to b.store, "shuffle" to "tempus_edge")
            eq(b.entries.map { it.age to String(it.d.id.copyOf(4)) }, listOf(0 to "AAAA", 7 to "BBBB", 65535 to "CCCC"))
            val t = readToken(seen.getValue("token").first)
            eq(listOf(String(t.kid), t.typ, t.nbf, t.exp, t.payload.size), listOf("k1", "tempus_edge", 1000L, 2000L, 98))
            val s = readBody(seen.getValue("sample").first, SHUFFLE_LENGTH) as Body.Sample
            eq(s.store to s.n, "tempus_sentinel" to 2)
            val a = readBody(seen.getValue("advert").first, SHUFFLE_LENGTH) as Body.Advert
            eq(a.d.addrText(), ADDR)
        }
    }
}

// ---------------------------------------------------------------- group 2: the codec on its own
private fun codec() {
    check("codec: every frame decodes and encodes to the same bytes") {
        for ((name, data) in built()) if (!name.startsWith("token")) eq(hex(etfEncode(etfDecode(data))), hex(data), name)
    }
    check("codec: map keys are written in the byte order of their names") {
        val body = String(sample("tempus_edge", 1), Charsets.ISO_8859_1)
        val n = body.indexOf("w\u0001n"); val s = body.indexOf("w\u0005store"); val t = body.indexOf("w\u0001t")
        if (!(n in 0 until s && s < t)) throw AssertionError("order n=$n store=$s t=$t")
        // whatever order the caller gives the keys in
        eq(hex(etfEncode(TMap(linkedMapOf("t" to TAtom("x"), "b" to TInt(1), "ab" to TInt(2), "a" to TInt(3))))),
            hex(etfEncode(TMap(linkedMapOf("a" to TInt(3), "ab" to TInt(2), "b" to TInt(1), "t" to TAtom("x"))))))
    }
    check("codec: integers 0 to 255 as tag 97, larger ones that fit 32 bits as tag 98, an empty list as tag 106 alone") {
        eq(hex(etfEncode(TInt(255))), "8361ff"); eq(hex(etfEncode(TInt(256))), "836200000100"); eq(hex(etfEncode(TInt(-1))), "8362ffffffff")
        eq(hex(etfEncode(TInt(4000000000))), "836e0400" + "00286bee"); eq(hex(etfEncode(TList(emptyList()))), "836a")
        eq(etfDecode(etfEncode(TInt(4000000000))), TInt(4000000000))
    }
    check("codec: a frame is its body after a 4-byte length, most significant byte first") {
        eq(hex(frame(sample("tempus_edge", 1)).copyOf(4)), "0000002a")
        eq(sample("tempus_edge", 1).size, 42)
    }
    check("codec: the reader's refusals") {
        refusedWith("truncated") { readBody(ByteArray(0), 3) }
        refusedWith("bad_version") { readBody(unhex("82"), 3) }
        refusedWith("trailing_bytes") { readBody(sample("tempus_edge", 1) + 0, 3) }
        refusedWith("bad_tag") { readBody(unhex("836800"), 3) }
        refusedWith("bad_tag") { readBody(unhex("83740000000161016101"), 3) }
        refusedWith("duplicate_field") { readBody(unhex("8374000000027701747706" + hex("sample".toByteArray()) + "7701747706" + hex("sample".toByteArray())), 3) }
        refusedWith("unknown_field") { readBody(etfEncode(TMap(mapOf("t" to TAtom("sample"), "store" to TAtom("tempus_edge"), "n" to TInt(1), "x" to TInt(1)))), 3) }
        refusedWith("missing_field") { readBody(etfEncode(TMap(mapOf("t" to TAtom("sample"), "store" to TAtom("tempus_edge")))), 3) }
        refusedWith("too_deep") { etfDecode(unhex("83" + "6c00000001".repeat(8) + "6a".repeat(9))) }
        refusedWith("not UTF-8") { readBody(unhex("83740000000177017477 02 c328".replace(" ", "")), 3) }
        refusedWith("too_large") { etfDecode(ByteArray(FRAME_MAX + 1)) }
    }
    check("codec: TRUST's call and cast frames are the bytes the Python example writes, and its result is read") {
        eq(hex(requestFrame("call", "p2".toByteArray(), "demo", "add", listOf(TInt(2), TInt(3)))),
            "83740000000877016161027704617267736c00000002610261036a770166770361646477016d770464656d6f77046f707473740000000077067265715f69646d000000027032770174770463616c6c77037665726101")
        eq(hex(requestFrame("cast", "p7".toByteArray(), "demo", "note", listOf(TInt(7)))),
            "83740000000877016161017704617267736c0000000161076a77016677046e6f746577016d770464656d6f77046f707473740000000077067265715f69646d00000002703777017477046361737477037665726101")
        val r = readBody(unhex("83740000000477067265715f69646d0000000270327701747706726573756c74770576616c7565610577037665726101"), 3) as Body.Result
        eq(String(r.reqId) to r.value, "p2" to TInt(5))
    }
    check("codec: the identifier of a key is its SHA-512") {
        eq(peerId(PUB).size, 64)
        eq(hex(peerId(PUB)), hex(java.security.MessageDigest.getInstance("SHA-512").digest(PUB)))
    }
}

// ---------------------------------------------------------------- group 3: the TEST ONLY identities and tokens
private fun identities(root: Path) {
    val certs = Certs(root)
    val text = String(Files.readAllBytes(root.resolve("trials/c2_tempus_clients/lib/tempus_ids.silica")))
    val names = table(text, "name")
    val producer = fixtureKey(0)
    val old = fixtureKey(96)
    val producerPub = unhex(constant(text, "producer_pub_hex"))
    check("identities: the eight TEST ONLY certificates are Ed25519 and self-signed, and their keys, identifiers and fingerprints are those of tools/bees_tempus_ids.py") {
        eq(names, certs.seeds.keys.toList())
        names.forEachIndexed { i, name ->
            val cert = certs.cert(name)
            eq(hex(certificateKey(cert)), table(text, "pub_hex")[i], "$name pub")
            eq(hex(peerId(certificateKey(cert))), table(text, "id_hex")[i], "$name id")
            eq(fingerprint(cert), table(text, "fp_hex")[i], "$name fingerprint")
        }
    }
    check("identities: each key file is the key of its seed and of its certificate") {
        val message = "the same message".toByteArray()
        for ((name, first) in certs.seeds) {
            val me = Identity.load(certs.certPath(name), certs.keyPath(name), ByteArray(65), "127.0.0.1:1")
            eq(hex(ed25519Sign(me.key, message)), hex(ed25519Sign(fixtureKey(first), message)), name)
            if (!ed25519Verify(me.pub, message, ed25519Sign(me.key, message))) throw AssertionError(name)
        }
        if (!ed25519Verify(producerPub, message, ed25519Sign(producer, message))) throw AssertionError("the producer's key")
    }
    check("identities: the 112 tokens of tools/bees_tempus_ids.py, made here from the same seeds, are the same bytes") {
        // token 9 is issued for another key, the one of seed 96. The JDK cannot derive a public key from a seed, so that
        // key is read from the recorded token and shown to be the key of seed 96 by a signature.
        val oldPub = readToken(unhex(table(text, "tok9")[0])).sub
        if (!ed25519Verify(oldPub, "seed 96".toByteArray(), ed25519Sign(old, "seed 96".toByteArray()))) throw AssertionError("token 9's sub is not the key of seed 96")
        var n = 0
        names.forEachIndexed { i, name ->
            val pub = certificateKey(certs.cert(name))
            val mine = mapOf(
                1 to makeToken(producer, "k1", pub, "tempus_edge", 1000, 2000), 2 to makeToken(producer, "k1", pub, "tempus_bridge", 1000, 2000),
                3 to makeToken(producer, "k1", pub, "tempus_sentinel", 1000, 2000), 4 to makeToken(old, "k0", pub, "tempus_edge", 1000, 2000),
                5 to makeToken(producer, "k1", pub, "tempus_edge", 1000, 1400), 6 to makeToken(producer, "k1", pub, "tempus_edge", 1000, 3000),
                7 to makeToken(producer, "k1", pub, "tempus_edge", 1800, 2000), 8 to makeToken(old, "k1", pub, "tempus_edge", 1000, 2000),
                9 to makeToken(producer, "k1", oldPub, "tempus_edge", 1000, 2000), 10 to makeToken(producer, "k1", pub, "tempus_edge", 1000, 1600),
                11 to makeToken(producer, "k1", pub, "tempus_sentinel", 1000, 3000), 12 to makeToken(producer, "k1", pub, "tempus_edge", 1000, 2500),
                13 to makeToken(producer, "k1", pub, "tempus_bridge", 1000, 3000), 14 to makeToken(producer, "k1", pub, "tempus_edge", 1000, 4000000000))
            for ((v, token) in mine) { eq(hex(token), table(text, "tok$v")[i], "$name token $v"); n += 1 }
        }
        eq(n, 112)
    }
    check("identities: a real token is verified, and refused outside its time, under another kid, under another key and when changed") {
        val sub = certificateKey(certs.cert("node"))
        val token = makeToken(producer, "k1", sub, "tempus_edge", 1000, 2000)
        eq(token.size, 64 + 98)
        val d = Descriptor(peerId(sub), sub, ADDR.toByteArray(), token)
        fun v(now: Long, skew: Long, kid: String = "k1", key: ByteArray = producerPub) = Verifier(key, kid.toByteArray(), { now }, skew, emptySet())
        eq(hex(v(1500, 0).checkEntry(d, "tempus_edge").sub), hex(sub))
        for ((now, skew, ok) in listOf(Triple(999L, 0L, false), Triple(999L, 1L, true), Triple(2000L, 0L, false), Triple(2000L, 1L, true), Triple(2001L, 1L, false))) {
            if (ok) v(now, skew).checkEntry(d, "tempus_edge") else refusedWith(null) { v(now, skew).checkEntry(d, "tempus_edge") }
        }
        refusedWith("key_rotated") { v(1500, 0, kid = "k2").checkEntry(d, "tempus_edge") }
        refusedWith("the signature does not verify") { v(1500, 0, key = sub).checkEntry(d, "tempus_edge") }
        val flipped = token.copyOf(); flipped[70] = (flipped[70].toInt() xor 1).toByte()
        refusedWith(null) { v(1500, 0).checkEntry(Descriptor(d.id, d.pub, d.addr, flipped), "tempus_edge") }
        refusedWith("typ is not the store's type") { v(1500, 0).checkEntry(d, "tempus_bridge") }
    }
    check("identities: the channel binding and the whitelist rule") {
        val now = { 1500L }
        val node = certs.identity("node", "tempus_edge", 1000, 2000, ADDR)
        val sentinel = certs.identity("sentinel", "tempus_sentinel", 1000, 2000, ADDR)
        val fp = fingerprint(certs.cert("sentinel"))
        val none = Verifier(producerPub, "k1".toByteArray(), now, 10, emptySet())
        val listed = Verifier(producerPub, "k1".toByteArray(), now, 10, setOf(fp))
        eq(none.checkPeer(node.descriptor(), certs.cert("node")).typ, "tempus_edge")
        // every field of the node's advert verifies; only the certificate is another peer's
        refusedWith("the certificate's key is not the advert's pub") { none.checkPeer(node.descriptor(), certs.cert("other")) }
        eq(listed.checkPeer(sentinel.descriptor(), certs.cert("sentinel")).typ, "tempus_sentinel")
        refusedWith("not in the tempus whitelist") { none.checkPeer(sentinel.descriptor(), certs.cert("sentinel")) }
        val edgeToken = certs.identity("sentinel", "tempus_edge", 1000, 2000, ADDR)
        refusedWith("a certificate of the tempus whitelist with a tempus_edge token") { listed.checkPeer(edgeToken.descriptor(), certs.cert("sentinel")) }
        eq(none.checkPeer(edgeToken.descriptor(), certs.cert("sentinel")).typ, "tempus_edge")
        refusedWith("the certificate's key is not Ed25519") { certificateKey(readCertificate(Files.readAllBytes(root.resolve("trials/t5_tempus_tls/certs/p256.pem")))) }
    }
}

// ---------------------------------------------------------------- group 4: the admission cases of trials/t4_tempus_admission
private fun admissionCases(root: Path) {
    val leaf = root.resolve("trials/t4_tempus_admission")
    val text = String(Files.readAllBytes(leaf.resolve("lib/tempus_fixtures.silica")))
    val goldens = Files.list(leaf).use { s -> s.filter { it.fileName.toString().matches(Regex("""dangerous_admit\..*\.scout""")) }.sorted().toList() }
    val stores = mapOf("1" to "tempus_edge", "2" to "tempus_bridge", "3" to "tempus_sentinel")
    val verifier = Verifier(unhex(constant(text, "producer_pub_hex")), constant(text, "kid").toByteArray(), { constant(text, "now").toLong() },
        constant(text, "skew").toLong(), emptySet())
    val names = table(text, "name"); val kinds = table(text, "kind"); val ids = table(text, "id_hex"); val pubs = table(text, "pub_hex")
    val tokens = table(text, "token_hex"); val nonces = table(text, "nonce_hex"); val sigs = table(text, "sig_hex"); val wants = table(text, "want")
    for (path in goldens) {
        val said = Files.readAllLines(path).filter { it.contains(": ") }.associate { it.substringBefore(": ") to it.substringAfter(": ") }
        check("admission cases ${path.fileName}: the ${names.size} cases get the verdict, and the reason, the Silica node gave") {
            eq(names.size, constant(text, "count").toInt())
            names.forEachIndexed { i, name ->
                val mine = when (kinds[i]) {
                    "1" -> try {
                        // the descriptor is read as a frame's would be (its bounds), then verified without contact
                        val d = readDescriptor(Descriptor(unhex(ids[i]), unhex(pubs[i]), constant(text, "addr").toByteArray(), unhex(tokens[i])).term())
                        verifier.checkEntry(d, stores.getValue(wants[i])); "admitted"
                    } catch (e: Refused) { "refused: ${e.why}" }
                    "2" -> try {
                        verifier.checkProof(unhex(pubs[i]), unhex(nonces[i]), unhex(tokens[i]), unhex(sigs[i])); "admitted"
                    } catch (e: Refused) { "refused: the signature does not verify" }
                    else -> {
                        val seed = unhex(pubs[i])
                        val key = java.security.KeyFactory.getInstance("Ed25519").generatePrivate(
                            java.security.spec.EdECPrivateKeySpec(java.security.spec.NamedParameterSpec.ED25519, seed))
                        if (hex(ed25519Sign(key, unhex(nonces[i]) + unhex(tokens[i]))) == sigs[i]) "the same 64 bytes as the fixture's signature" else "other bytes"
                    }
                }
                eq(mine, said[name], name)
            }
        }
    }
}

// ---------------------------------------------------------------- group 5: the client against itself
private fun loopback(root: Path) {
    val certs = Certs(root)
    val producerPub = unhex(constant(String(Files.readAllBytes(root.resolve("trials/c2_tempus_clients/lib/tempus_ids.silica"))), "producer_pub_hex"))
    val settings = Settings(4000, 3)
    val advertised = "127.0.0.1:9"          // an address in the adverts only: nothing dials it in these tests
    fun verifier(kid: String = "k1", whitelist: Set<String> = emptySet(), now: Long = 1500) = Verifier(producerPub, kid.toByteArray(), { now }, 10, whitelist)
    val dialer = certs.identity("node", "tempus_edge", 1000, 2000, advertised)
    val edge = certs.identity("other", "tempus_edge", 1000, 2000, advertised)
    val third = certs.identity("x1", "tempus_edge", 1000, 2000, advertised)
    val sentinel = certs.identity("sentinel", "tempus_sentinel", 1000, 2000, advertised)
    val sentinelFp = fingerprint(certs.cert("sentinel"))

    /** one connection: the dialer's Outcome and the listener's */
    fun exchange(request: Request, listener: Identity = edge, me: Identity = dialer, dialVerifier: Verifier = verifier(), listenVerifier: Verifier = verifier(),
                 dialSettings: Settings = settings, handler: (Incoming) -> List<Entry>? = { emptyList() }): Pair<Outcome, Outcome> =
        Listener(listener, listenVerifier, settings, "127.0.0.1", 0, handler).use { lis ->
            val out = dial(lis.address, me, dialVerifier, request, dialSettings)
            out to lis.outcomes(1, 6000).single()
        }

    check("loopback: admission both ways, a sample and its reply") {
        val (out, served) = exchange(Request.Sample("tempus_edge", 2)) { listOf(third.entry(3)) }
        eq(out.line(), "reply sample_reply entries=[3:${third.descriptor().id8()}] store=tempus_edge peer=${edge.descriptor().id8()} typ=tempus_edge")
        eq(served.line(), "served sample n=2 store=tempus_edge sent=reply peer=${dialer.descriptor().id8()} typ=tempus_edge")
        eq(out.advert, edge.descriptor()); eq(served.advert, dialer.descriptor())
    }
    check("loopback: a shuffle and its reply, entry for entry") {
        val offered = listOf(dialer.entry(0), third.entry(4))
        var got: List<Entry> = emptyList()
        val (out, served) = exchange(Request.Shuffle("tempus_edge", offered)) { rq -> got = (rq.body as Body.Entries).entries; listOf(edge.entry(0), third.entry(5)) }
        eq(got, offered)
        eq((out.body as Body.Entries).entries, listOf(edge.entry(0), third.entry(5)))
        eq(out.what to served.sent, "reply" to "reply")
    }
    check("loopback: a handler that answers nothing closes with no reply") {
        val (out, served) = exchange(Request.Sample("tempus_edge", 1)) { null }
        eq(out.line(), "closed at=reply peer=${edge.descriptor().id8()} typ=tempus_edge")
        eq(served.sent, "close")
    }
    check("loopback: a call and a cast are not sent to a peer that is no bridge; a peer with a bridge token gets them, and this client's listener answers neither") {
        for (rq in listOf(Request.Call("r1".toByteArray(), "demo", "add", listOf(TInt(2), TInt(3))), Request.Cast("r2".toByteArray(), "demo", "note", listOf(TInt(7))))) {
            val (out, served) = exchange(rq)
            eq(Triple(out.what, out.stage, out.reason), Triple("refused", "request", "the peer is not a bridge"))
            eq(served.what to served.stage, "closed" to "request")
            val bridge = certs.identity("bridge", "tempus_bridge", 1000, 2000, advertised)
            val (out2, served2) = exchange(rq, listener = bridge, dialVerifier = verifier(whitelist = setOf(fingerprint(certs.cert("bridge")))))
            eq(out2.what to out2.stage, "closed" to "reply")
            eq(served2.what to served2.reason, "refused" to "unknown kind")
        }
    }
    check("loopback: each cause of refusing a dialer's token, seen by the listener; the dialer sees only the close") {
        val other = fixtureKey(64)
        val cases = listOf(
            certs.identity("node", "tempus_edge", 1000, 2000, advertised, producer = other) to "the signature does not verify",
            certs.identity("node", "tempus_edge", 1000, 1400, advertised) to "the token has expired",
            certs.identity("node", "tempus_edge", 1000, 1490, advertised) to "the token has expired",
            certs.identity("node", "tempus_edge", 1600, 2000, advertised) to "the token is not valid yet",
            certs.identity("node", "tempus_edge", 1000, 2000, advertised, sub = third.pub) to "sub is not the peer's key",
            certs.identity("node", "tempus_sentinel", 1000, 2000, advertised) to "a tempus_sentinel whose certificate is not in the tempus whitelist")
        for ((who, reason) in cases) {
            var asked = 0
            val (out, served) = exchange(Request.Sample("tempus_edge", 1), me = who) { asked += 1; emptyList() }
            eq(Triple(served.what, served.stage, served.reason), Triple("refused", "advert", reason))
            eq(out.what to asked, "closed" to 0, reason)
        }
        for (who in listOf(certs.identity("node", "tempus_edge", 1000, 1495, advertised), certs.identity("node", "tempus_edge", 1505, 2000, advertised))) {
            val (out, served) = exchange(Request.Sample("tempus_edge", 1), me = who)
            eq(out.what to served.what, "reply" to "served", "inside the skew")
        }
    }
    check("loopback: the dialer refuses a listener whose token has expired or was signed by another key") {
        val (out, served) = exchange(Request.Sample("tempus_edge", 1), listener = certs.identity("other", "tempus_edge", 1000, 1400, advertised))
        eq(Triple(out.what, out.stage, out.reason), Triple("refused", "advert", "the token has expired")); eq(served.what, "closed")
        val (out2, _) = exchange(Request.Sample("tempus_edge", 1), listener = certs.identity("other", "tempus_edge", 1000, 2000, advertised, producer = fixtureKey(128)))
        eq(Triple(out2.what, out2.stage, out2.reason), Triple("refused", "advert", "the signature does not verify"))
        eq(out2.advert?.id8(), edge.descriptor().id8(), "the refused peer's advert is still reported")
    }
    check("loopback: key_rotated, in both directions, and before every other fault of the token") {
        val old = fixtureKey(96)
        val (out, served) = exchange(Request.Sample("tempus_edge", 1), me = certs.identity("node", "tempus_edge", 1000, 2000, advertised, kid = "k0", producer = old))
        eq(out.line(), "key_rotated at=challenge kid=6b31 peer=${edge.descriptor().id8()} typ=tempus_edge")
        eq(served.what to served.reason, "refused" to "key_rotated")
        val (out2, _) = exchange(Request.Sample("tempus_edge", 1), me = certs.identity("node", "tempus_edge", 1000, 1400, advertised, kid = "k0", producer = old))
        eq(out2.what to out2.kid?.let { String(it) }, "key_rotated" to "k1")
        val (out3, served3) = exchange(Request.Sample("tempus_edge", 1), listener = certs.identity("other", "tempus_edge", 1000, 2000, advertised, kid = "k0", producer = old))
        eq(out3.what to out3.reason, "refused" to "key_rotated")
        eq(served3.what to served3.kid?.let { String(it) }, "key_rotated" to "k1")
    }
    check("loopback: a sentinel is admitted only with its certificate in the whitelist") {
        val (out, _) = exchange(Request.Sample("tempus_sentinel", 1), listener = sentinel, dialVerifier = verifier(whitelist = setOf(sentinelFp))) { listOf(sentinel.entry(0)) }
        eq(out.what to out.typ, "reply" to "tempus_sentinel")
        val (out2, _) = exchange(Request.Sample("tempus_sentinel", 1), listener = sentinel)
        eq(Triple(out2.what, out2.stage, out2.reason), Triple("refused", "advert", "a tempus_sentinel whose certificate is not in the tempus whitelist"))
    }
    check("loopback: a reply is refused whole when one entry does not verify, is of another store's type, or the reply is not what was asked for") {
        val forged = certs.identity("x2", "tempus_edge", 1000, 2000, advertised, producer = fixtureKey(96))
        val (out, _) = exchange(Request.Sample("tempus_edge", 3)) { listOf(third.entry(1), forged.entry(0)) }
        eq(Triple(out.what, out.stage, out.reason), Triple("refused", "reply", "entry 1 does not verify: the signature does not verify"))
        val (out2, _) = exchange(Request.Shuffle("tempus_edge", listOf(dialer.entry(0)))) { listOf(sentinel.entry(0)) }
        eq(out2.reason, "entry 0 does not verify: typ is not the store's type")
        val expired = certs.identity("x2", "tempus_edge", 1000, 1400, advertised)
        val (out3, _) = exchange(Request.Sample("tempus_edge", 3)) { listOf(expired.entry(0)) }
        eq(out3.reason, "entry 0 does not verify: the token has expired")
        // the listener's shuffle length is 3 and the dialer's is 2: the reply holds more entries than the dialer's network allows
        val (out4, _) = exchange(Request.Sample("tempus_edge", 2), dialSettings = Settings(4000, 2)) { listOf(third.entry(1), edge.entry(0)) }
        eq(out4.what, "reply")
        val (out5, _) = exchange(Request.Shuffle("tempus_edge", emptyList()), dialSettings = Settings(4000, 2)) { listOf(third.entry(1), edge.entry(0), dialer.entry(2)) }
        eq(out5.what to out5.reason, "refused" to "more entries than the shuffle length")
    }
    check("loopback: a listener refuses a shuffle whose entry does not verify, and its handler is not asked") {
        val forged = certs.identity("x2", "tempus_edge", 1000, 2000, advertised, producer = fixtureKey(96))
        var asked = 0
        val (out, served) = exchange(Request.Shuffle("tempus_edge", listOf(dialer.entry(0), forged.entry(1)))) { asked += 1; emptyList() }
        eq(Triple(served.what, served.stage, served.reason), Triple("refused", "request", "entry 1 does not verify: the signature does not verify"))
        eq(out.what to asked, "closed" to 0)
    }
    check("loopback: a listener serves several connections in order") {
        Listener(edge, verifier(), settings, "127.0.0.1", 0) { emptyList() }.use { lis ->
            for (n in 1..3) eq(dial(lis.address, dialer, verifier(), Request.Sample("tempus_edge", n), settings).what, "reply")
            eq(lis.outcomes(3, 6000).map { (it.body as Body.Sample).n }, listOf(1, 2, 3))
        }
    }
    check("loopback: nobody listens: unreachable; a peer that never answers: timeout at the one bound of the connection") {
        val free = java.net.ServerSocket(0).use { it.localPort }
        eq(dial("127.0.0.1:$free", dialer, verifier(), Request.Sample("tempus_edge", 1), settings).line(), "unreachable at=tls")
        java.net.ServerSocket(0).use { silent ->
            val t0 = System.nanoTime()
            val out = dial("127.0.0.1:${silent.localPort}", dialer, verifier(), Request.Sample("tempus_edge", 1), Settings(600, 3))
            val ms = (System.nanoTime() - t0) / 1_000_000
            eq(out.line(), "timeout at=tls")
            if (ms < 500 || ms > 3000) throw AssertionError("the bound of 600 ms ended after $ms ms")
        }
    }
    check("loopback: a request this client cannot make is refused before anything is sent") {
        for (bad in listOf<() -> Unit>({ dial("127.0.0.1:9", dialer, verifier(), Request.Sample("tempus_edge", 4), settings) },
            { dial("127.0.0.1:9", dialer, verifier(), Request.Sample("tempus_node", 1), settings) },
            { dial("127.0.0.1:9", dialer, verifier(), Request.Call(ByteArray(17), "m", "f", emptyList()), settings) })) {
            try { bad(); throw AssertionError("not refused") } catch (e: IllegalArgumentException) { }
        }
    }
}

fun main(argv: Array<String>) {
    val root = Path.of(if (argv.isNotEmpty()) argv[0] else ".").toAbsolutePath().normalize()
    val jdk = Runtime.version().feature()
    val groups = javax.net.ssl.SSLContext.getInstance(TLS_VERSION).also { it.init(null, null, null) }.supportedSSLParameters.namedGroups?.toList() ?: emptyList()
    if (TLS_GROUP !in groups) {
        println("FAIL  this Java runtime (feature release $jdk) cannot offer the TLS key exchange group $TLS_GROUP, which a TEMPUS node requires")
        exitProcess(1)
    }
    framesGolden(root)
    codec()
    identities(root)
    admissionCases(root)
    loopback(root)
    println("[kotlin client tests] $passed passed, $failed failed")
    exitProcess(if (failed == 0) 0 else 1)
}
