// EXAMPLE ONLY, not for production. See README.md beside the lib directory.
//
// The driver application of the example client: a thin program over the library in ../lib. It reads its values from
// the command line and from the files the command line names, hands them to the library, and prints what the library
// reports, one line each.
package bees.tempus

import java.nio.file.Files
import java.nio.file.Path
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import kotlin.system.exitProcess

private const val USAGE = """bees-tempus-client: an EXAMPLE TEMPUS client. Not for production.

  gossip OPTIONS                      be a member of a TEMPUS network: listen, join through the sentinels, shuffle the
                                      three stores on their timers, answer the peers that dial. Prints the peer's own
                                      lines and, for every peer it comes to know, `learned STORE ID16 HOST:PORT`.
                                      Runs until it is interrupted or ended, or for --run-ms; then prints, per store,
                                      `known STORE: ID16 ...` (every peer it ever learned of, sorted).
  dial HOST:PORT OPTIONS REQUEST      connect, be admitted, send one request, print the outcome as one line
      REQUEST: sample STORE N
               shuffle STORE                        offers this client's own entry at age 0
               call REQ_ID MODULE FUNCTION [INT]...  to a bridge; the arguments are integers
               cast REQ_ID MODULE FUNCTION [INT]...  to a bridge; there is no reply
  listen HOST:PORT OPTIONS --count N  accept N connections; answer a sample or a shuffle of this client's own type
                                      with its own entry at age 0, and of another type with no entries; print each
                                      outcome as one line
  read-hex HEX SHUFFLE_LENGTH         read one frame body given as hex digits and print what it is

  OPTIONS, all required unless marked:
      --cert FILE            this client's certificate, PEM, self-signed over its Ed25519 key
      --key FILE             its private key, PEM (PKCS#8, not encrypted)
      --token FILE           its token from the producer, as hex digits in a file
      --addr HOST:PORT       the listen address this client advertises
      --producer-pub HEX     the producer's current public key, 64 hex digits
      --kid TEXT             the identifier of that key
      --skew SECONDS         the clock difference this client allows
      --timeout-ms MS        the time bound of a whole connection
      --shuffle-length N     dial and listen: the shuffle length of the network
      --whitelist-cert FILE  optional, may be repeated: the certificate (PEM) of a bridge or sentinel this client accepts
      --now SECONDS          optional: the time for token checks, in seconds since 1970 UTC, in place of the system clock
    gossip only (in place of --shuffle-length; --addr is also where the peer listens):
      --store-edge CAP:LEN:TICK_MS      capacity, shuffle length and tick of the edge store
      --store-bridge CAP:LEN:TICK_MS    the same of the bridge store
      --store-sentinel CAP:LEN:TICK_MS  the same of the sentinel store
      --join-retry-ms FIRST:MAX         the join's first and greatest retry delay
      --sentinel HOST:PORT   may be repeated; none for a first sentinel
      --run-ms MS            optional: stop after that long
  STORE is tempus_edge, tempus_bridge or tempus_sentinel.
"""

private class Options(args: List<String>) {
    val values = HashMap<String, MutableList<String>>()
    val rest = ArrayList<String>()

    init {
        var i = 0
        while (i < args.size) {
            val a = args[i]
            if (a.startsWith("--")) {
                if (i + 1 >= args.size) fail("the option $a needs a value")
                values.getOrPut(a) { ArrayList() }.add(args[i + 1])
                i += 2
            } else {
                rest.add(a)
                i += 1
            }
        }
    }

    fun one(name: String): String {
        val v = values[name] ?: fail("the option $name is required")
        if (v.size != 1) fail("the option $name is given once")
        return v[0]
    }

    fun maybe(name: String): String? = values[name]?.let { if (it.size != 1) fail("the option $name is given once") else it[0] }

    fun many(name: String): List<String> = values[name] ?: emptyList()
}

private fun fail(text: String): Nothing {
    System.err.println("bees-tempus-client: $text")
    exitProcess(2)
}

private class Setup(o: Options, gossip: Boolean = false) {
    val me = Identity.load(Path.of(o.one("--cert")), Path.of(o.one("--key")),
        unhex(String(Files.readAllBytes(Path.of(o.one("--token"))), Charsets.US_ASCII).trim()), o.one("--addr"))
    val now: () -> Long = o.maybe("--now")?.toLong()?.let { fixed -> { fixed } } ?: { System.currentTimeMillis() / 1000 }
    val verifier = Verifier(unhex(o.one("--producer-pub")), o.one("--kid").toByteArray(Charsets.UTF_8), now, o.one("--skew").toLong(),
        o.many("--whitelist-cert").map { fingerprint(readCertificate(Files.readAllBytes(Path.of(it)))) }.toSet())
    val timeoutMs = o.one("--timeout-ms").toLong()
    val settings = if (gossip) null else Settings(timeoutMs, o.one("--shuffle-length").toInt())
}

private fun storeSettings(text: String): StoreSettings {
    val p = text.split(":")
    if (p.size != 3) fail("a store is CAP:LEN:TICK_MS")
    return StoreSettings(p[0].toInt(), p[1].toInt(), p[2].toLong())
}

private val out = Object()

private fun say(line: String) {
    synchronized(out) {
        println(line)
        System.out.flush()
    }
}

private fun gossip(o: Options) {
    if (o.rest.isNotEmpty()) fail("gossip OPTIONS")
    val s = Setup(o, gossip = true)
    val retry = o.one("--join-retry-ms").split(":")
    if (retry.size != 2) fail("--join-retry-ms is FIRST:MAX")
    val settings = PeerSettings(mapOf("tempus_edge" to storeSettings(o.one("--store-edge")), "tempus_bridge" to storeSettings(o.one("--store-bridge")),
        "tempus_sentinel" to storeSettings(o.one("--store-sentinel"))), s.timeoutMs, o.many("--sentinel"), retry[0].toLong(), retry[1].toLong())
    val known = PEER_TYPES.associateWith { java.util.TreeSet<String>() }
    val addr = o.one("--addr")
    val at = addr.lastIndexOf(':')
    if (at <= 0) fail("an address is host:port")
    val peer = Peer(s.me, s.verifier, settings, addr.substring(0, at), addr.substring(at + 1).toInt(), ::say, { store, d ->
        val isNew = synchronized(known) { known.getValue(store).add(d.id8()) }
        if (isNew) say("learned $store ${d.id8()} ${d.addrText()}")
    })
    val ended = CountDownLatch(1)
    val finished = CountDownLatch(1)
    Runtime.getRuntime().addShutdownHook(Thread {
        ended.countDown()
        finished.await(10, TimeUnit.SECONDS)
    })
    peer.start()
    val runMs = o.maybe("--run-ms")?.toLong()
    if (runMs == null) ended.await() else ended.await(runMs, TimeUnit.MILLISECONDS)
    peer.stop()
    synchronized(known) {
        for (t in PEER_TYPES) say("known $t: " + known.getValue(t).joinToString(" ").ifEmpty { "(none)" })
    }
    finished.countDown()
}

private fun ints(words: List<String>): List<Term> = words.map { TInt(it.toLong()) }

fun main(argv: Array<String>) {
    if (argv.isEmpty()) { print(USAGE); exitProcess(2) }
    try {
        when (argv[0]) {
            "read-hex" -> {
                if (argv.size != 3) fail("read-hex HEX SHUFFLE_LENGTH")
                try {
                    val b = readBody(unhex(argv[1]), argv[2].toInt())
                    println(Outcome("reply", "done", body = b).line().removePrefix("reply "))
                } catch (e: Refused) {
                    println("refused: ${e.why}")
                }
            }
            "gossip" -> gossip(Options(argv.drop(1)))
            "dial" -> {
                val o = Options(argv.drop(1))
                if (o.rest.size < 2) fail("dial HOST:PORT OPTIONS REQUEST")
                val s = Setup(o)
                val r = o.rest.drop(1)
                val request = when {
                    r[0] == "sample" && r.size == 3 -> Request.Sample(r[1], r[2].toInt())
                    r[0] == "shuffle" && r.size == 2 -> Request.Shuffle(r[1], listOf(s.me.entry(0)))
                    r[0] == "call" && r.size >= 4 -> Request.Call(r[1].toByteArray(Charsets.UTF_8), r[2], r[3], ints(r.drop(4)))
                    r[0] == "cast" && r.size >= 4 -> Request.Cast(r[1].toByteArray(Charsets.UTF_8), r[2], r[3], ints(r.drop(4)))
                    else -> fail("the request is: sample STORE N | shuffle STORE | call REQ_ID MODULE FUNCTION [INT]... | cast ...")
                }
                println(dial(o.rest[0], s.me, s.verifier, request, s.settings!!).line())
            }
            "listen" -> {
                val o = Options(argv.drop(1))
                if (o.rest.size != 1) fail("listen HOST:PORT OPTIONS --count N")
                val s = Setup(o)
                val count = o.one("--count").toInt()
                val at = o.rest[0].lastIndexOf(':')
                if (at <= 0) fail("an address is host:port")
                val mine = readToken(s.me.token).typ
                Listener(s.me, s.verifier, s.settings!!, o.rest[0].substring(0, at), o.rest[0].substring(at + 1).toInt()) { rq ->
                    val store = when (val b = rq.body) { is Body.Sample -> b.store; is Body.Entries -> b.store; else -> "" }
                    if (store == mine) listOf(s.me.entry(0)) else emptyList()
                }.use { lis ->
                    System.err.println("listening on ${lis.address}")
                    var seen = 0
                    while (seen < count) {
                        val outs = lis.outcomes(seen + 1, 1000)
                        while (seen < outs.size) { println(outs[seen].line()); seen += 1 }
                    }
                }
            }
            else -> { print(USAGE); exitProcess(2) }
        }
    } catch (e: IllegalArgumentException) {
        fail(e.message ?: "a wrong argument")
    }
}
