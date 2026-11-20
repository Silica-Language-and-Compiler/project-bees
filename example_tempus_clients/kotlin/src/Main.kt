// EXAMPLE ONLY, not for production. See README.md beside the src directory.
//
// The command line of the example client.
package bees.tempus

import java.nio.file.Files
import java.nio.file.Path
import kotlin.system.exitProcess

private const val USAGE = """bees-tempus-client: an EXAMPLE TEMPUS client. Not for production.

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
      --shuffle-length N     the shuffle length of the network
      --whitelist-cert FILE  optional, may be repeated: the certificate (PEM) of a bridge or sentinel this client accepts
      --now SECONDS          optional: the time for token checks, in seconds since 1970 UTC, in place of the system clock
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

private class Setup(o: Options) {
    val me = Identity.load(Path.of(o.one("--cert")), Path.of(o.one("--key")),
        unhex(String(Files.readAllBytes(Path.of(o.one("--token"))), Charsets.US_ASCII).trim()), o.one("--addr"))
    val now: () -> Long = o.maybe("--now")?.toLong()?.let { fixed -> { fixed } } ?: { System.currentTimeMillis() / 1000 }
    val verifier = Verifier(unhex(o.one("--producer-pub")), o.one("--kid").toByteArray(Charsets.UTF_8), now, o.one("--skew").toLong(),
        o.many("--whitelist-cert").map { fingerprint(readCertificate(Files.readAllBytes(Path.of(it)))) }.toSet())
    val settings = Settings(o.one("--timeout-ms").toLong(), o.one("--shuffle-length").toInt())
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
                println(dial(o.rest[0], s.me, s.verifier, request, s.settings).line())
            }
            "listen" -> {
                val o = Options(argv.drop(1))
                if (o.rest.size != 1) fail("listen HOST:PORT OPTIONS --count N")
                val s = Setup(o)
                val count = o.one("--count").toInt()
                val at = o.rest[0].lastIndexOf(':')
                if (at <= 0) fail("an address is host:port")
                val mine = readToken(s.me.token).typ
                Listener(s.me, s.verifier, s.settings, o.rest[0].substring(0, at), o.rest[0].substring(at + 1).toInt()) { rq ->
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
