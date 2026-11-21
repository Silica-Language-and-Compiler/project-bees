// EXAMPLE ONLY, not for production. See README.md beside the lib directory.
//
// The tempus/1 messages a client writes and reads, with every bound of the design's section 8, and the token's
// structure (section 4). The two test-only frames (tick and clock) and their answer (done) are not here: they are no
// part of a client.
package bees.tempus

import java.security.MessageDigest

val PEER_TYPES = listOf("tempus_edge", "tempus_bridge", "tempus_sentinel")
const val AGE_MAX = 65535
const val ENTRIES_MAX = 64          // the ceiling of entries in one frame; a network's shuffle length is at or below it
const val REQ_ID_MAX = 16

/** The record that describes one peer. */
class Descriptor(val id: ByteArray, val pub: ByteArray, val addr: ByteArray, val token: ByteArray) {
    fun term(): TMap = TMap(mapOf("id" to TBin(id), "pub" to TBin(pub), "addr" to TBin(addr), "token" to TBin(token)))
    override fun equals(other: Any?) = other is Descriptor && id.contentEquals(other.id) && pub.contentEquals(other.pub) &&
        addr.contentEquals(other.addr) && token.contentEquals(other.token)
    override fun hashCode() = id.contentHashCode()
    /** the first 8 bytes of the identifier, as hex: enough to tell peers apart in a line of output */
    fun id8(): String = hex(id.copyOf(minOf(8, id.size)))
    fun addrText(): String = String(addr, Charsets.UTF_8)
}

/** One entry of a shuffle or sample frame: a descriptor and its age. */
data class Entry(val age: Int, val d: Descriptor)

/** The identifier of a public key: its SHA-512. */
fun peerId(pub: ByteArray): ByteArray = MessageDigest.getInstance("SHA-512").digest(pub)

fun sha512(data: ByteArray): ByteArray = MessageDigest.getInstance("SHA-512").digest(data)

// ---------------------------------------------------------------- what a client writes
private fun store(name: String): TAtom {
    require(name in PEER_TYPES) { "a store is one of $PEER_TYPES" }
    return TAtom(name)
}

/** The body with its 4-byte length, most significant byte first, as it travels. */
fun frame(body: ByteArray): ByteArray {
    require(body.size <= FRAME_MAX) { "a body above the frame ceiling" }
    val n = body.size
    return byteArrayOf((n ushr 24).toByte(), (n ushr 16).toByte(), (n ushr 8).toByte(), n.toByte()) + body
}

fun advert(d: Descriptor): ByteArray = etfEncode(TMap(mapOf("t" to TAtom("advert"), "ver" to TInt(1), "d" to d.term())))

fun challenge(nonce: ByteArray): ByteArray = etfEncode(TMap(mapOf("t" to TAtom("pop_challenge"), "nonce" to TBin(nonce))))

fun response(sig: ByteArray): ByteArray = etfEncode(TMap(mapOf("t" to TAtom("pop_response"), "sig" to TBin(sig))))

fun keyRotated(kid: ByteArray): ByteArray = etfEncode(TMap(mapOf("t" to TAtom("key_rotated"), "kid" to TBin(kid))))

private fun entriesFrame(kind: String, storeName: String, entries: List<Entry>): ByteArray =
    etfEncode(TMap(mapOf("t" to TAtom(kind), "store" to store(storeName),
        "entries" to TList(entries.map { TMap(mapOf("age" to TInt(it.age.toLong()), "d" to it.d.term())) }))))

fun shuffle(storeName: String, entries: List<Entry>): ByteArray = entriesFrame("shuffle", storeName, entries)

fun shuffleReply(storeName: String, entries: List<Entry>): ByteArray = entriesFrame("shuffle_reply", storeName, entries)

fun sampleReply(storeName: String, entries: List<Entry>): ByteArray = entriesFrame("sample_reply", storeName, entries)

fun sample(storeName: String, n: Int): ByteArray =
    etfEncode(TMap(mapOf("t" to TAtom("sample"), "store" to store(storeName), "n" to TInt(n.toLong()))))

/**
 * TRUST's request frame, which an edge sends to a bridge: kind is "call" or "cast". The arguments are terms of this
 * codec's subset. `a` is the number of arguments.
 */
fun requestFrame(kind: String, reqId: ByteArray, module: String, function: String, args: List<Term>): ByteArray {
    require(kind == "call" || kind == "cast") { "the kind is call or cast" }
    require(reqId.size in 1..REQ_ID_MAX) { "req_id is 1 to $REQ_ID_MAX bytes" }
    return etfEncode(TMap(mapOf("t" to TAtom(kind), "ver" to TInt(1), "req_id" to TBin(reqId), "m" to TAtom(module),
        "f" to TAtom(function), "a" to TInt(args.size.toLong()), "args" to TList(args), "opts" to TMap(emptyMap()))))
}

// ---------------------------------------------------------------- what a client reads
/** A body as this client read it. */
sealed class Body {
    class Advert(val d: Descriptor) : Body()
    class Challenge(val nonce: ByteArray) : Body()
    class Response(val sig: ByteArray) : Body()
    class KeyRotated(val kid: ByteArray) : Body()
    /** kind is "shuffle", "shuffle_reply" or "sample_reply" */
    class Entries(val kind: String, val store: String, val entries: List<Entry>) : Body()
    class Sample(val store: String, val n: Int) : Body()
    /** TRUST's answer to a call */
    class Result(val reqId: ByteArray, val value: Term) : Body()

    fun kind(): String = when (this) {
        is Advert -> "advert"
        is Challenge -> "pop_challenge"
        is Response -> "pop_response"
        is KeyRotated -> "key_rotated"
        is Entries -> kind
        is Sample -> "sample"
        is Result -> "result"
    }
}

private fun checkKeys(m: Term, keys: List<String>, what: String): Map<String, Term> {
    val f = (m as? TMap ?: throw Refused("$what is not a map")).fields
    if (f.keys.any { it !in keys }) throw Refused("unknown_field")
    if (keys.any { it !in f.keys }) throw Refused("missing_field")
    return f
}

private fun bin(f: Map<String, Term>, key: String, lo: Int, hi: Int, text: String): ByteArray {
    val v = f.getValue(key) as? TBin ?: throw Refused(text)
    if (v.bytes.size < lo || v.bytes.size > hi) throw Refused(text)
    return v.bytes
}

fun readDescriptor(t: Term): Descriptor {
    val f = checkKeys(t, listOf("id", "pub", "addr", "token"), "descriptor")
    return Descriptor(bin(f, "id", 64, 64, "id is not 64 bytes"), bin(f, "pub", 32, 32, "pub is not 32 bytes"),
        bin(f, "addr", 3, 261, "addr is not 3 to 261 bytes"), bin(f, "token", 65, 1024, "token is not 65 to 1024 bytes"))
}

private fun storeOf(f: Map<String, Term>): String {
    val s = f.getValue("store") as? TAtom ?: throw Refused("store is not a peer type")
    if (s.name !in PEER_TYPES) throw Refused("store is not a peer type")
    return s.name
}

/**
 * A body as a message, every bound checked; Refused(reason) otherwise. shuffleLength is the shuffle length of the
 * network this client is in: the most entries one frame may hold, and the most a sample may ask for.
 */
fun readBody(body: ByteArray, shuffleLength: Int): Body {
    val m = etfDecode(body) as? TMap ?: throw Refused("bad_tag")
    val kind = (m.fields["t"] as? TAtom)?.name ?: throw Refused("unknown kind")
    when (kind) {
        "advert" -> {
            val f = checkKeys(m, listOf("t", "ver", "d"), kind)
            if (f.getValue("ver") != TInt(1)) throw Refused("ver is not 1")
            return Body.Advert(readDescriptor(f.getValue("d")))
        }
        "pop_challenge" -> return Body.Challenge(bin(checkKeys(m, listOf("t", "nonce"), kind), "nonce", 32, 32, "nonce is not 32 bytes"))
        "pop_response" -> return Body.Response(bin(checkKeys(m, listOf("t", "sig"), kind), "sig", 64, 64, "sig is not 64 bytes"))
        "key_rotated" -> return Body.KeyRotated(bin(checkKeys(m, listOf("t", "kid"), kind), "kid", 1, 64, "kid is not 1 to 64 bytes"))
        "shuffle", "shuffle_reply", "sample_reply" -> {
            val f = checkKeys(m, listOf("t", "store", "entries"), kind)
            val st = storeOf(f)
            val list = (f.getValue("entries") as? TList ?: throw Refused("entries is not a list")).items
            if (list.size > ENTRIES_MAX || list.size > shuffleLength) throw Refused("more entries than the shuffle length")
            val out = ArrayList<Entry>()
            for (e in list) {
                val ef = checkKeys(e, listOf("age", "d"), "entry")
                val age = (ef.getValue("age") as? TInt)?.value ?: throw Refused("age is not 0 to 65535")
                if (age < 0 || age > AGE_MAX) throw Refused("age is not 0 to 65535")
                out.add(Entry(age.toInt(), readDescriptor(ef.getValue("d"))))
            }
            return Body.Entries(kind, st, out)
        }
        "sample" -> {
            val f = checkKeys(m, listOf("t", "store", "n"), kind)
            val st = storeOf(f)
            val n = (f.getValue("n") as? TInt)?.value ?: throw Refused("n is not 1 to the shuffle length")
            if (n < 1 || n > shuffleLength) throw Refused("n is not 1 to the shuffle length")
            return Body.Sample(st, n.toInt())
        }
        "result" -> {
            val f = checkKeys(m, listOf("t", "ver", "req_id", "value"), kind)
            if (f.getValue("ver") != TInt(1)) throw Refused("ver is not 1")
            return Body.Result(bin(f, "req_id", 1, REQ_ID_MAX, "req_id is not 1 to 16 bytes"), f.getValue("value"))
        }
        else -> throw Refused("unknown kind")
    }
}

// ---------------------------------------------------------------- the token
/** The five fields of a token, the payload bytes the producer signed, and the signature. */
class Token(val kid: ByteArray, val sub: ByteArray, val typ: String, val nbf: Long, val exp: Long, val payload: ByteArray, val sig: ByteArray)

/** The structure and bounds of a token. The signature is NOT verified here (Verifier does that). */
fun readToken(token: ByteArray): Token {
    if (token.size < 65 || token.size > 1024) throw Refused("token is not 65 to 1024 bytes")
    val sig = token.copyOfRange(0, 64)
    val payload = token.copyOfRange(64, token.size)
    val m = etfDecode(payload, depthMax = 2) as? TMap ?: throw Refused("the token is not a map of five keys")
    if (m.fields.size != 5) throw Refused("the token is not a map of five keys")
    val f = checkKeys(m, listOf("kid", "sub", "typ", "nbf", "exp"), "token")
    val kid = bin(f, "kid", 1, 64, "kid is not 1 to 64 bytes")
    val sub = bin(f, "sub", 32, 32, "sub is not 32 bytes")
    val typ = (f.getValue("typ") as? TAtom)?.name ?: throw Refused("typ is not a peer type")
    if (typ !in PEER_TYPES) throw Refused("typ is not a peer type")
    val nbf = (f.getValue("nbf") as? TInt)?.value ?: throw Refused("nbf or exp is not a time")
    val exp = (f.getValue("exp") as? TInt)?.value ?: throw Refused("nbf or exp is not a time")
    if (nbf < 0 || exp < 0) throw Refused("nbf or exp is not a time")
    if (exp <= nbf) throw Refused("exp is not after nbf")
    return Token(kid, sub, typ, nbf, exp, payload, sig)
}
