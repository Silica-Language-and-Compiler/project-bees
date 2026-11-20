// TEST ONLY. Keys from fixed seeds that are written in this repository, and tokens signed with them: keys that belong
// to nobody. Nothing in this file is part of the example client: a client never makes or signs a token.
package bees.tempus.test

import bees.tempus.Identity
import bees.tempus.TAtom
import bees.tempus.TBin
import bees.tempus.TInt
import bees.tempus.TMap
import bees.tempus.ed25519Sign
import bees.tempus.etfEncode
import bees.tempus.readCertificate
import java.nio.file.Files
import java.nio.file.Path
import java.security.KeyFactory
import java.security.PrivateKey
import java.security.cert.X509Certificate
import java.security.spec.EdECPrivateKeySpec
import java.security.spec.NamedParameterSpec

/** TEST ONLY: the Ed25519 private key whose seed is the 32 bytes first, first+1, ... */
fun fixtureKey(first: Int): PrivateKey =
    KeyFactory.getInstance("Ed25519").generatePrivate(EdECPrivateKeySpec(NamedParameterSpec.ED25519, ByteArray(32) { (first + it).toByte() }))

/** The bytes a producer signs: the ETF map of the five fields. */
fun tokenPayload(kid: String, sub: ByteArray, typ: String, nbf: Long, exp: Long): ByteArray =
    etfEncode(TMap(mapOf("kid" to TBin(kid.toByteArray()), "sub" to TBin(sub), "typ" to TAtom(typ), "nbf" to TInt(nbf), "exp" to TInt(exp))))

/** TEST ONLY: a token signed with a fixture key. */
fun makeToken(producer: PrivateKey, kid: String, sub: ByteArray, typ: String, nbf: Long, exp: Long): ByteArray {
    val payload = tokenPayload(kid, sub, typ, nbf, exp)
    return ed25519Sign(producer, payload) + payload
}

/** The TEST ONLY certificates and keys of tools/bees_tempus_certs.py, and the seed each was made from. */
class Certs(val root: Path) {
    val seeds = linkedMapOf("node" to 32, "other" to 64, "sentinel" to 128, "bridge" to 160, "x1" to 176, "x2" to 192, "x3" to 208, "x4" to 224)
    private val dir = root.resolve("trials/t5_tempus_tls/certs")

    fun certPath(name: String): Path = dir.resolve("$name.pem")
    fun keyPath(name: String): Path = dir.resolve("$name-key.pem")
    fun cert(name: String): X509Certificate = readCertificate(Files.readAllBytes(certPath(name)))

    /** The identity `name` with a token of the test producer (seed 0, kid k1 unless said otherwise). */
    fun identity(name: String, typ: String, nbf: Long, exp: Long, addr: String, kid: String = "k1", producer: PrivateKey = fixtureKey(0),
                 sub: ByteArray? = null): Identity {
        val plain = Identity.load(certPath(name), keyPath(name), ByteArray(65), addr)
        return plain.withToken(makeToken(producer, kid, sub ?: plain.pub, typ, nbf, exp))
    }
}

/** The values of one `fn NAME(i: int64) -> string { case i of { 0 -> "..."; ... } }` table of a generated fixture unit. */
fun table(text: String, fn: String): List<String> {
    val start = text.indexOf("fn $fn(")
    require(start >= 0) { "no table $fn" }
    val body = text.substring(start, text.indexOf("\n}", start))
    return Regex("""^\s+\d+ -> "?([^";]*)"?;""", RegexOption.MULTILINE).findAll(body).map { it.groupValues[1] }.toList()
}

fun constant(text: String, fn: String): String =
    Regex("""fn $fn\(\) -> \w+ \{ "?([^"}]*?)"? \}""").find(text)?.groupValues?.get(1) ?: error("no constant $fn")
