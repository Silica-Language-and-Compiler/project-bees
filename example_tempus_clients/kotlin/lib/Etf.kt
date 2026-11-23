// EXAMPLE ONLY, not for production. See README.md beside the lib directory.
//
// The part of the Erlang external term format (ETF) that tempus/1 uses: maps with atom keys, atoms, binaries,
// integers and lists. Written from example_tempus_clients/writing-a-tempus-client.md section 4 and the ruled design
// (development-plan/tempus-design.md sections 5 and 8), not from the Python or the Silica code.
package bees.tempus

import java.io.ByteArrayOutputStream
import java.nio.charset.CharacterCodingException
import java.nio.charset.CodingErrorAction
import java.nio.ByteBuffer

/** A body, a token or a peer this client does not accept. The message says why. */
class Refused(val why: String) : Exception(why)

/** One term of the subset. */
sealed class Term

data class TAtom(val name: String) : Term()

data class TInt(val value: Long) : Term()

class TBin(val bytes: ByteArray) : Term() {
    override fun equals(other: Any?) = other is TBin && bytes.contentEquals(other.bytes)
    override fun hashCode() = bytes.contentHashCode()
    override fun toString() = "TBin(${hex(bytes)})"
}

data class TList(val items: List<Term>) : Term()

/** A map whose keys are atoms; the key is the atom's name. */
data class TMap(val fields: Map<String, Term>) : Term()

const val FRAME_MAX = 131072

fun hex(b: ByteArray): String = b.joinToString("") { "%02x".format(it.toInt() and 0xff) }

fun unhex(s: String): ByteArray {
    require(s.length % 2 == 0 && s.all { it in '0'..'9' || it in 'a'..'f' || it in 'A'..'F' }) { "not hex digits in pairs" }
    return ByteArray(s.length / 2) { s.substring(2 * it, 2 * it + 2).toInt(16).toByte() }
}

private fun compareBytes(a: ByteArray, b: ByteArray): Int {
    val n = minOf(a.size, b.size)
    for (i in 0 until n) {
        val d = (a[i].toInt() and 0xff) - (b[i].toInt() and 0xff)
        if (d != 0) return d
    }
    return a.size - b.size
}

private fun u32(out: ByteArrayOutputStream, n: Int) {
    out.write(n ushr 24); out.write(n ushr 16); out.write(n ushr 8); out.write(n)
}

private fun enc(term: Term, out: ByteArrayOutputStream) {
    when (term) {
        is TAtom -> {
            val name = term.name.toByteArray(Charsets.UTF_8)
            require(name.size <= 255) { "atom too long for tempus/1" }
            out.write(0x77); out.write(name.size); out.write(name)
        }
        is TInt -> {
            val v = term.value
            if (v in 0..255) {
                out.write(0x61); out.write(v.toInt())
            } else if (v >= Int.MIN_VALUE && v <= Int.MAX_VALUE) {
                out.write(0x62); u32(out, v.toInt())
            } else {
                require(v != Long.MIN_VALUE) { "integer beyond this writer" }
                var mag = if (v < 0) -v else v
                val digits = ByteArrayOutputStream()
                while (mag != 0L) { digits.write((mag and 0xff).toInt()); mag = mag ushr 8 }
                out.write(0x6e); out.write(digits.size()); out.write(if (v < 0) 1 else 0); out.write(digits.toByteArray())
            }
        }
        is TBin -> { out.write(0x6d); u32(out, term.bytes.size); out.write(term.bytes) }
        is TList -> {
            if (term.items.isNotEmpty()) {
                out.write(0x6c); u32(out, term.items.size)
                for (x in term.items) enc(x, out)
            }
            out.write(0x6a)
        }
        is TMap -> {
            out.write(0x74); u32(out, term.fields.size)
            // keys in the byte order of their names: every message has exactly one byte form
            val keys = term.fields.keys.map { it to it.toByteArray(Charsets.UTF_8) }.sortedWith { a, b -> compareBytes(a.second, b.second) }
            for ((key, _) in keys) { enc(TAtom(key), out); enc(term.fields.getValue(key), out) }
        }
    }
}

/** The bytes of a term, beginning with the version byte 131. */
fun etfEncode(term: Term): ByteArray {
    val out = ByteArrayOutputStream()
    out.write(0x83)
    enc(term, out)
    return out.toByteArray()
}

private class Reader(val data: ByteArray, val depthMax: Int) {
    var pos = 0

    fun take(n: Int): ByteArray {
        if (n < 0 || n > data.size - pos) throw Refused("truncated")
        val chunk = data.copyOfRange(pos, pos + n)
        pos += n
        return chunk
    }

    fun byte(): Int = take(1)[0].toInt() and 0xff

    fun u32(): Long {
        val b = take(4)
        return ((b[0].toLong() and 0xff) shl 24) or ((b[1].toLong() and 0xff) shl 16) or ((b[2].toLong() and 0xff) shl 8) or (b[3].toLong() and 0xff)
    }

    fun count(): Int {
        val n = u32()
        if (n > data.size) throw Refused("truncated")
        return n.toInt()
    }

    fun atom(bytes: ByteArray): TAtom {
        val dec = Charsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT).onUnmappableCharacter(CodingErrorAction.REPORT)
        try {
            return TAtom(dec.decode(ByteBuffer.wrap(bytes)).toString())
        } catch (e: CharacterCodingException) {
            throw Refused("an atom name is not UTF-8")
        }
    }

    fun term(depth: Int): Term {
        if (depth > depthMax) throw Refused("too_deep")
        when (val tag = byte()) {
            0x77 -> return atom(take(byte()))
            0x76 -> { val b = take(2); return atom(take(((b[0].toInt() and 0xff) shl 8) or (b[1].toInt() and 0xff))) }
            0x61 -> return TInt(byte().toLong())
            0x62 -> return TInt(u32().toInt().toLong())
            0x6e -> {
                val n = byte()
                val sign = byte()
                if (n > 8) throw Refused("unsupported")
                val d = take(n)
                if (n == 8 && d[7] < 0) throw Refused("unsupported")
                var v = 0L
                for (i in n - 1 downTo 0) v = (v shl 8) or (d[i].toLong() and 0xff)
                return TInt(if (sign != 0) -v else v)
            }
            0x6d -> return TBin(take(count()))
            0x6a -> return TList(emptyList())
            0x6c -> {
                val n = count()
                val items = ArrayList<Term>()
                repeat(n) { items.add(term(depth + 1)) }
                if (byte() != 0x6a) throw Refused("bad_tag")
                return TList(items)
            }
            0x74 -> {
                val n = count()
                val m = LinkedHashMap<String, Term>()
                repeat(n) {
                    val key = term(depth + 1) as? TAtom ?: throw Refused("bad_tag")
                    if (m.containsKey(key.name)) throw Refused("duplicate_field")
                    m[key.name] = term(depth + 1)
                }
                return TMap(m)
            }
            else -> throw Refused(if (tag == 0x68 || tag == 0x69 || tag == 0x6b || tag == 0x46) "bad_tag" else "unsupported")
        }
    }
}

/** The one term of `data`, which must begin with 131 and hold nothing after the term. */
fun etfDecode(data: ByteArray, depthMax: Int = 6, sizeMax: Int = FRAME_MAX): Term {
    if (data.size > sizeMax) throw Refused("too_large")
    if (data.isEmpty()) throw Refused("truncated")
    if ((data[0].toInt() and 0xff) != 0x83) throw Refused("bad_version")
    val r = Reader(data, depthMax)
    r.pos = 1
    val term = r.term(1)
    if (r.pos != data.size) throw Refused("trailing_bytes")
    return term
}
