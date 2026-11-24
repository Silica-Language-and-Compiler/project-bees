// A usable example, to be used carefully. See README.md beside the lib directory.
//
// The active part: an ordinary TEMPUS peer over TCP and mutual TLS 1.3, in both positions. dial() connects, is
// admitted, sends ONE request and reads its reply. Listener accepts, is admitted, reads one request and answers it.
// What happened on a connection is an Outcome, a plain value; nothing a peer does throws.
//
// TLS is the JDK's own (JSSE). Each connection offers and accepts exactly: TLS 1.3; the key exchange group
// X25519MLKEM768; the cipher suites TLS_AES_256_GCM_SHA384 and TLS_CHACHA20_POLY1305_SHA256; the signature scheme
// ed25519; the application protocol tempus/1; a certificate from both sides. No authority is consulted: the trust
// manager below requires an Ed25519 certificate that is self-signed, and admission then binds the certificate's key to
// the peer's advert, token and proof of possession.
package bees.tempus

import java.io.IOException
import java.io.InputStream
import java.net.InetSocketAddress
import java.net.ServerSocket
import java.net.Socket
import java.net.SocketTimeoutException
import java.security.Principal
import java.security.PrivateKey
import java.security.SecureRandom
import java.security.cert.CertificateException
import java.security.cert.X509Certificate
import javax.net.ssl.KeyManager
import javax.net.ssl.SSLContext
import javax.net.ssl.SSLEngine
import javax.net.ssl.SSLException
import javax.net.ssl.SSLSocket
import javax.net.ssl.TrustManager
import javax.net.ssl.X509ExtendedKeyManager
import javax.net.ssl.X509ExtendedTrustManager

const val ALPN = "tempus/1"
const val TLS_VERSION = "TLSv1.3"
const val TLS_GROUP = "X25519MLKEM768"
val TLS_SUITES = arrayOf("TLS_AES_256_GCM_SHA384", "TLS_CHACHA20_POLY1305_SHA256")
const val TLS_SIGNATURE = "ed25519"

// How long a closing side keeps reading after it has ended its own sending, so that its last frame is not destroyed by
// a connection reset. The value is the Python example's.
const val LINGER_MS = 500L

/**
 * What happened on one connection.
 *
 * what    "reply"        dialing: the reply arrived and passed every check (body, bytes)
 *         "served"       listening: the peer was admitted and its request read; `sent` says what went back: "reply" or
 *                        "close"
 *         "key_rotated"  the peer answered this side's advert with key_rotated; `kid` is the kid it named
 *         "refused"      THIS side refused the peer or a frame of it; `reason` says why ("key_rotated": this side sent
 *                        that frame)
 *         "closed"       the connection closed before the exchange was complete. This is all a refusal by the peer
 *                        shows. It is also the ordinary end of a cast, which has no reply.
 *         "timeout"      nothing came within the time allowed for the whole connection
 *         "tls_failed"   no tempus/1 TLS connection: the handshake failed, or a TLS alert came before any frame
 *         "unreachable"  dialing: no TCP connection
 * stage   where it ended: "tls", "advert", "challenge", "response", "request", "reply", "done"
 * advert  the peer's descriptor, once its advert was read (also when the peer was then refused)
 * typ     the type in the peer's token, once the advert verified
 */
class Outcome(val what: String, val stage: String, val reason: String = "", val body: Body? = null, val bytes: ByteArray = ByteArray(0),
              val advert: Descriptor? = null, val typ: String = "", val kid: ByteArray? = null, val sent: String = "") {
    /** One line with nothing of the wall clock in it. */
    fun line(): String {
        val parts = ArrayList<String>()
        parts.add(what)
        if (what != "reply" && what != "served") parts.add("at=$stage")
        when (val b = body) {
            is Body.Entries -> parts.add("${b.kind} entries=[${b.entries.joinToString(",") { "${it.age}:${it.d.id8()}" }}] store=${b.store}")
            is Body.Sample -> parts.add("sample n=${b.n} store=${b.store}")
            is Body.Result -> parts.add("result req_id=${hex(b.reqId)} value=${show(b.value)}")
            null -> {}
            else -> parts.add(b.kind())
        }
        if (sent.isNotEmpty()) parts.add("sent=$sent")
        if (kid != null) parts.add("kid=${hex(kid)}")
        if (advert != null) parts.add("peer=${advert.id8()}")
        if (typ.isNotEmpty()) parts.add("typ=$typ")
        if (reason.isNotEmpty()) parts.add("reason=\"$reason\"")
        return parts.joinToString(" ")
    }

    override fun toString() = line()
}

fun show(t: Term): String = when (t) {
    is TAtom -> t.name
    is TInt -> t.value.toString()
    is TBin -> hex(t.bytes)
    is TList -> "[" + t.items.joinToString(",") { show(it) } + "]"
    is TMap -> "{" + t.fields.keys.sorted().joinToString(",") { "$it=${show(t.fields.getValue(it))}" } + "}"
}

/** One request of a client. */
sealed class Request {
    /** asks for up to n entries of the named store */
    class Sample(val store: String, val n: Int) : Request()
    /** offers entries of the named store and asks for some in return */
    class Shuffle(val store: String, val entries: List<Entry>) : Request()
    /** asks a bridge to run a function and return its value */
    class Call(val reqId: ByteArray, val module: String, val function: String, val args: List<Term>) : Request()
    /** asks a bridge to run a function; there is no reply */
    class Cast(val reqId: ByteArray, val module: String, val function: String, val args: List<Term>) : Request()

    fun body(): ByteArray = when (this) {
        is Sample -> sample(store, n)
        is Shuffle -> shuffle(store, entries)
        is Call -> requestFrame("call", reqId, module, function, args)
        is Cast -> requestFrame("cast", reqId, module, function, args)
    }
}

// ---------------------------------------------------------------- TLS
private class OwnKey(val identity: Identity) : X509ExtendedKeyManager() {
    override fun getClientAliases(keyType: String?, issuers: Array<out Principal>?) = arrayOf("tempus")
    override fun chooseClientAlias(keyType: Array<out String>?, issuers: Array<out Principal>?, socket: Socket?) = "tempus"
    override fun chooseEngineClientAlias(keyType: Array<out String>?, issuers: Array<out Principal>?, engine: SSLEngine?) = "tempus"
    override fun getServerAliases(keyType: String?, issuers: Array<out Principal>?) = arrayOf("tempus")
    override fun chooseServerAlias(keyType: String?, issuers: Array<out Principal>?, socket: Socket?) = "tempus"
    override fun chooseEngineServerAlias(keyType: String?, issuers: Array<out Principal>?, engine: SSLEngine?) = "tempus"
    override fun getCertificateChain(alias: String?): Array<X509Certificate> = arrayOf(identity.certificate)
    override fun getPrivateKey(alias: String?): PrivateKey = identity.key
}

/**
 * Accepts no authority. A peer's certificate must have an Ed25519 key and be self-signed (certificateKey); the JDK
 * itself has by then verified, in the handshake, that the peer holds that certificate's private key. `refused` keeps
 * the reason of a refusal for the Outcome.
 */
internal class SelfSignedEd25519 : X509ExtendedTrustManager() {
    @Volatile var refused: String? = null

    private fun check(chain: Array<out X509Certificate>?) {
        try {
            if (chain == null || chain.isEmpty()) throw Refused("the peer presented no certificate")
            certificateKey(chain[0])
        } catch (e: Refused) {
            refused = e.why
            throw CertificateException(e.why)
        }
    }

    override fun checkClientTrusted(chain: Array<out X509Certificate>?, authType: String?) = check(chain)
    override fun checkServerTrusted(chain: Array<out X509Certificate>?, authType: String?) = check(chain)
    override fun checkClientTrusted(chain: Array<out X509Certificate>?, authType: String?, socket: Socket?) = check(chain)
    override fun checkServerTrusted(chain: Array<out X509Certificate>?, authType: String?, socket: Socket?) = check(chain)
    override fun checkClientTrusted(chain: Array<out X509Certificate>?, authType: String?, engine: SSLEngine?) = check(chain)
    override fun checkServerTrusted(chain: Array<out X509Certificate>?, authType: String?, engine: SSLEngine?) = check(chain)
    override fun getAcceptedIssuers(): Array<X509Certificate> = arrayOf()
}

internal fun context(identity: Identity, trust: SelfSignedEd25519): SSLContext {
    val ctx = SSLContext.getInstance(TLS_VERSION)
    ctx.init(arrayOf<KeyManager>(OwnKey(identity)), arrayOf<TrustManager>(trust), SecureRandom())
    return ctx
}

internal fun restrict(socket: SSLSocket) {
    val p = socket.sslParameters
    p.protocols = arrayOf(TLS_VERSION)
    p.cipherSuites = TLS_SUITES
    p.namedGroups = arrayOf(TLS_GROUP)
    p.signatureSchemes = arrayOf(TLS_SIGNATURE)
    p.applicationProtocols = arrayOf(ALPN)
    p.needClientAuth = true
    socket.sslParameters = p
}

/** After the handshake: what was negotiated, and the peer's certificate. Refused(reason) otherwise. */
internal fun tlsChecks(socket: SSLSocket): X509Certificate {
    val session = socket.session
    if (session.protocol != TLS_VERSION) throw Refused("the TLS version is not 1.3")
    if (session.cipherSuite !in TLS_SUITES) throw Refused("the cipher suite is not one of tempus/1")
    if (socket.applicationProtocol != ALPN) throw Refused("the ALPN protocol is not tempus/1")
    val chain = try { session.peerCertificates } catch (e: SSLException) { throw Refused("the peer presented no certificate") }
    val cert = chain.firstOrNull() as? X509Certificate ?: throw Refused("the peer presented no certificate")
    certificateKey(cert)
    return cert
}

internal fun sslReason(e: Exception): String = (e.message ?: e.javaClass.simpleName).lineSequence().first()

// ---------------------------------------------------------------- one connection
internal sealed class Read {
    class Frame(val body: ByteArray) : Read()
    object Oversize : Read()
    class Ended(val what: String, val why: String) : Read()        // closed, timeout, tls_failed
}

/** A TLS connection with ONE deadline for all of it. */
internal class Conn(val socket: SSLSocket, val deadline: Long) {
    var framesRead = 0
    var open = true
    var advert: Descriptor? = null
    var typ = ""

    private fun arm(until: Long = deadline) {
        val left = (minOf(until, deadline) - System.nanoTime()) / 1_000_000
        if (left <= 0) throw SocketTimeoutException()
        socket.soTimeout = left.toInt().coerceAtLeast(1)
    }

    fun send(data: ByteArray) {
        try {
            arm()
            val out = socket.outputStream
            out.write(data)
            out.flush()
        } catch (e: IOException) {
            // not reported here: the next read says what happened
        }
    }

    private fun exact(input: InputStream, n: Int): ByteArray {
        val data = ByteArray(n)
        var have = 0
        while (have < n) {
            arm()
            val got = input.read(data, have, n - have)
            if (got < 0) throw java.io.EOFException()
            have += got
        }
        return data
    }

    fun read(): Read {
        try {
            val input = socket.inputStream
            val h = exact(input, 4)
            val size = ((h[0].toLong() and 0xff) shl 24) or ((h[1].toLong() and 0xff) shl 16) or ((h[2].toLong() and 0xff) shl 8) or (h[3].toLong() and 0xff)
            if (size > FRAME_MAX) return Read.Oversize      // refused from the length alone, before any of the body is read
            val body = exact(input, size.toInt())
            framesRead += 1
            return Read.Frame(body)
        } catch (e: SocketTimeoutException) {
            return Read.Ended("timeout", "")
        } catch (e: SSLException) {
            return if (framesRead == 0) Read.Ended("tls_failed", sslReason(e)) else Read.Ended("closed", "")
        } catch (e: IOException) {
            return Read.Ended("closed", "")
        }
    }

    /**
     * Close so that what was last written arrives: end this side's sending (TLS close_notify and the TCP end of
     * writing), read to the peer's end for at most LINGER_MS, then close. Closing with unread bytes can reset the
     * connection, and a reset can destroy a frame the peer has not read yet.
     */
    fun close() {
        if (!open) return
        open = false
        try {
            socket.shutdownOutput()
            val until = System.nanoTime() + LINGER_MS * 1_000_000
            val input = socket.inputStream
            val sink = ByteArray(4096)
            while (true) {
                arm(until)
                if (input.read(sink) < 0) break
            }
        } catch (e: IOException) {
        }
        try {
            socket.close()
        } catch (e: IOException) {
        }
    }

    fun end(what: String, stage: String, reason: String = "", body: Body? = null, bytes: ByteArray = ByteArray(0), kid: ByteArray? = null,
            sent: String = ""): Outcome {
        close()
        return Outcome(what, stage, reason, body, bytes, advert, typ, kid, sent)
    }
}

/** The next frame, which must be one of the kinds wanted: the body, or the Outcome that ended the connection. */
private fun next(conn: Conn, stage: String, shuffleLength: Int, vararg want: String): Pair<Body?, Outcome?> {
    when (val r = conn.read()) {
        is Read.Oversize -> return null to conn.end("refused", stage, "a frame above the ceiling")
        is Read.Ended -> return null to conn.end(r.what, stage, r.why)
        is Read.Frame -> {
            val body = try {
                readBody(r.body, shuffleLength)
            } catch (e: Refused) {
                return null to conn.end("refused", stage, e.why, bytes = r.body)
            }
            if (body.kind() !in want) return null to conn.end("refused", stage, "${body.kind()} where ${want.joinToString(" or ")} was due", bytes = r.body)
            return body to null
        }
    }
}

/**
 * Admission, the same at both ends (design sections 4 and 5): this side's advert at once; the peer's advert, checked;
 * this side's challenge; the peer's challenge, answered; the peer's response, verified. null when both directions
 * passed, else the Outcome.
 */
private fun admit(conn: Conn, me: Identity, verifier: Verifier, certificate: X509Certificate, shuffleLength: Int, random: SecureRandom): Outcome? {
    val nonce = ByteArray(32)
    random.nextBytes(nonce)
    conn.send(frame(advert(me.descriptor())))
    val (first, out1) = next(conn, "advert", shuffleLength, "advert")
    if (out1 != null) return out1
    val theirs = (first as Body.Advert).d
    conn.advert = theirs
    try {
        conn.typ = verifier.checkPeer(theirs, certificate).typ
    } catch (e: Refused) {
        // the one exception to silence: a token under another kid is answered with one key_rotated frame, then the close
        if (e.why == "key_rotated") conn.send(frame(keyRotated(verifier.kid)))
        return conn.end("refused", "advert", e.why)
    }
    conn.send(frame(challenge(nonce)))
    val (second, out2) = next(conn, "challenge", shuffleLength, "pop_challenge", "key_rotated")
    if (out2 != null) return out2
    if (second is Body.KeyRotated) return conn.end("key_rotated", "challenge", kid = second.kid)
    conn.send(frame(response(me.prove((second as Body.Challenge).nonce))))
    val (third, out3) = next(conn, "response", shuffleLength, "pop_response")
    if (out3 != null) return out3
    try {
        verifier.checkProof(theirs.pub, nonce, theirs.token, (third as Body.Response).sig)
    } catch (e: Refused) {
        return conn.end("refused", "response", e.why)
    }
    return null
}

internal fun hostPort(text: String): InetSocketAddress {
    val at = text.lastIndexOf(':')
    require(at > 0) { "an address is host:port" }
    return InetSocketAddress(text.substring(0, at), text.substring(at + 1).toInt())
}

/**
 * Settings every connection of a client needs. None has a default: the time bound for a whole connection and the
 * shuffle length are properties of the network the client joins.
 */
class Settings(val timeoutMs: Long, val shuffleLength: Int) {
    init {
        require(timeoutMs > 0) { "the time bound of a connection is positive" }
        require(shuffleLength in 1..ENTRIES_MAX) { "the shuffle length is 1 to $ENTRIES_MAX" }
    }
}

/**
 * Connect to the TEMPUS peer at "host:port", be admitted, send ONE request and read its reply. The reply must be the
 * one the request calls for: a sample_reply or shuffle_reply for the same store, whose every entry verifies for that
 * store, or a result with the request's req_id. A cast has no reply: its ordinary end is "closed" at stage "reply".
 */
fun dial(addr: String, me: Identity, verifier: Verifier, request: Request, settings: Settings, random: SecureRandom = SecureRandom()): Outcome {
    val requestBody = when (request) {       // built before anything is sent: a request this client cannot make is the caller's fault
        is Request.Sample -> { require(request.n in 1..settings.shuffleLength) { "n is 1 to the shuffle length" }; request.body() }
        is Request.Shuffle -> { require(request.entries.size <= settings.shuffleLength) { "more entries than the shuffle length" }; request.body() }
        else -> request.body()
    }
    val deadline = System.nanoTime() + settings.timeoutMs * 1_000_000
    val trust = SelfSignedEd25519()
    val socket = context(me, trust).socketFactory.createSocket() as SSLSocket
    try {
        socket.connect(hostPort(addr), settings.timeoutMs.toInt())
    } catch (e: SocketTimeoutException) {
        socket.close()
        return Outcome("timeout", "tls")
    } catch (e: IOException) {
        socket.close()
        return Outcome("unreachable", "tls")
    }
    val certificate: X509Certificate
    try {
        socket.useClientMode = true
        restrict(socket)
        socket.soTimeout = ((deadline - System.nanoTime()) / 1_000_000).toInt().coerceAtLeast(1)
        socket.startHandshake()
    } catch (e: SocketTimeoutException) {
        socket.close()
        return Outcome("timeout", "tls")
    } catch (e: IOException) {
        socket.close()
        val why = trust.refused
        return if (why != null) Outcome("refused", "tls", why) else Outcome("tls_failed", "tls", if (e is SSLException) sslReason(e) else "closed during the handshake")
    }
    val conn = Conn(socket, deadline)
    try {
        certificate = tlsChecks(socket)
    } catch (e: Refused) {
        return conn.end("refused", "tls", e.why)
    }
    // In TLS 1.3 a dialer's handshake ends before the listener has judged the dialer's certificate: a listener's TLS
    // refusal shows as an alert on the first read, reported as tls_failed at "advert".
    admit(conn, me, verifier, certificate, settings.shuffleLength, random)?.let { return it }
    // a call or a cast goes to a bridge only: a peer admitted with a bridge token, which the whitelist rule ties to a
    // certificate of this client's tempus whitelist
    if ((request is Request.Call || request is Request.Cast) && conn.typ != "tempus_bridge") return conn.end("refused", "request", "the peer is not a bridge")
    conn.send(frame(requestBody))
    val read = conn.read()
    if (read is Read.Oversize) return conn.end("refused", "reply", "a frame above the ceiling")
    if (read is Read.Ended) return conn.end(read.what, "reply", read.why)
    val bytes = (read as Read.Frame).body
    val body = try {
        val b = readBody(bytes, settings.shuffleLength)
        checkReply(request, b, verifier)
        b
    } catch (e: Refused) {
        return conn.end("refused", "reply", e.why, bytes = bytes)
    }
    return conn.end("reply", "done", body = body, bytes = bytes)
}

private fun checkReply(request: Request, b: Body, verifier: Verifier) {
    fun entries(kind: String, store: String, most: Int) {
        if (b !is Body.Entries || b.kind != kind) throw Refused("${b.kind()} where $kind was due")
        if (b.store != store) throw Refused("the reply names another store")
        if (b.entries.size > most) throw Refused("more entries than were asked for")
        b.entries.forEachIndexed { i, e ->
            try {
                verifier.checkEntry(e.d, store)
            } catch (why: Refused) {
                // one entry that does not verify refuses the whole frame: nothing of it may be used
                throw Refused("entry $i does not verify: ${why.why}")
            }
        }
    }
    when (request) {
        is Request.Sample -> entries("sample_reply", request.store, request.n)
        is Request.Shuffle -> entries("shuffle_reply", request.store, ENTRIES_MAX)
        is Request.Call -> {
            if (b !is Body.Result) throw Refused("${b.kind()} where result was due")
            if (!b.reqId.contentEquals(request.reqId)) throw Refused("the result names another req_id")
        }
        is Request.Cast -> throw Refused("${b.kind()} where no reply was due")
    }
}

/** What a Listener's handler is given: the verified request of an admitted peer. */
class Incoming(val body: Body, val peer: Descriptor, val typ: String, val index: Int)

/**
 * The listening position: a thread accepts connections on host:port, and each connection, in its own thread, is
 * admitted and has ONE request read. A shuffle (every entry verified for its store first) and a sample are given to
 * the handler, which returns the entries of the reply, or null to close with no reply. Any other request is closed
 * with no reply. Every connection ends as one Outcome, kept in accept order.
 */
class Listener(val identity: Identity, val verifier: Verifier, val settings: Settings, host: String, port: Int,
               val handler: (Incoming) -> List<Entry>?) : AutoCloseable {
    // A plain java.net.ServerSocket; TLS is layered on each accepted connection, with a trust manager of its own.
    private val server: ServerSocket = ServerSocket()
    private val done = HashMap<Int, Outcome>()
    private val lock = Object()
    private val threads = ArrayList<Thread>()
    @Volatile private var stopping = false
    private val random = SecureRandom()
    val address: String
    private val acceptor: Thread

    init {
        server.reuseAddress = true
        server.bind(InetSocketAddress(host, port), 64)
        server.soTimeout = 50
        address = "$host:${server.localPort}"
        acceptor = Thread { accept() }
        acceptor.isDaemon = true
        acceptor.start()
    }

    private fun accept() {
        var index = 0
        while (!stopping) {
            val raw = try {
                server.accept()
            } catch (e: SocketTimeoutException) {
                continue
            } catch (e: IOException) {
                break
            }
            val i = index++
            val t = Thread {
                val out = try {
                    serve(raw, i)
                } catch (e: Exception) {        // a fault of this program or of the handler, never the peer's doing: say so
                    try { raw.close() } catch (x: IOException) {}
                    Outcome("closed", "tls", "internal error: ${e.javaClass.simpleName}: ${e.message}")
                }
                synchronized(lock) { done[i] = out; lock.notifyAll() }
            }
            t.isDaemon = true
            synchronized(threads) { threads.add(t) }
            t.start()
        }
    }

    private fun serve(raw: Socket, index: Int): Outcome {
        val deadline = System.nanoTime() + settings.timeoutMs * 1_000_000
        val trust = SelfSignedEd25519()
        val socket = context(identity, trust).socketFactory.createSocket(raw, null, true) as SSLSocket
        try {
            socket.useClientMode = false
            restrict(socket)
            socket.soTimeout = settings.timeoutMs.toInt()
            socket.startHandshake()
        } catch (e: SocketTimeoutException) {
            socket.close()
            return Outcome("timeout", "tls")
        } catch (e: IOException) {
            socket.close()
            val why = trust.refused
            return if (why != null) Outcome("refused", "tls", why) else Outcome("tls_failed", "tls", if (e is SSLException) sslReason(e) else "closed during the handshake")
        }
        val conn = Conn(socket, deadline)
        val certificate = try {
            tlsChecks(socket)
        } catch (e: Refused) {
            return conn.end("refused", "tls", e.why)
        }
        admit(conn, identity, verifier, certificate, settings.shuffleLength, random)?.let { return it }
        val read = conn.read()
        if (read is Read.Oversize) return conn.end("refused", "request", "a frame above the ceiling")
        if (read is Read.Ended) return conn.end(read.what, "request", read.why)
        val bytes = (read as Read.Frame).body
        val body = try {
            val b = readBody(bytes, settings.shuffleLength)
            when (b) {
                is Body.Sample -> {}
                is Body.Entries -> {
                    if (b.kind != "shuffle") throw Refused("${b.kind} where a request was due")
                    b.entries.forEachIndexed { i, e ->
                        try {
                            verifier.checkEntry(e.d, b.store)
                        } catch (why: Refused) {
                            throw Refused("entry $i does not verify: ${why.why}")
                        }
                    }
                }
                else -> throw Refused("${b.kind()} where a request was due")
            }
            b
        } catch (e: Refused) {
            return conn.end("refused", "request", e.why, bytes = bytes)
        }
        val answer = handler(Incoming(body, conn.advert!!, conn.typ, index))
            ?: return conn.end("served", "done", body = body, bytes = bytes, sent = "close")
        val reply = when (body) {
            is Body.Sample -> { require(answer.size <= body.n) { "the handler answered a sample with more entries than were asked for" }; sampleReply(body.store, answer) }
            is Body.Entries -> { require(answer.size <= settings.shuffleLength) { "the handler answered with more entries than the shuffle length" }; shuffleReply(body.store, answer) }
            else -> throw IllegalStateException()
        }
        conn.send(frame(reply))
        return conn.end("served", "done", body = body, bytes = bytes, sent = "reply")
    }

    /**
     * The Outcomes of the first `count` connections in accept order, waiting up to waitMs for them (fewer when they
     * did not all end in time).
     */
    fun outcomes(count: Int, waitMs: Long): List<Outcome> {
        val until = System.nanoTime() + waitMs * 1_000_000
        synchronized(lock) {
            while (!(0 until count).all { it in done }) {
                val left = (until - System.nanoTime()) / 1_000_000
                if (left <= 0) break
                lock.wait(left)
            }
            return done.keys.sorted().filter { it < count }.map { done.getValue(it) }
        }
    }

    /** Stops accepting and waits for the connections in hand to end (each is bounded by the settings' time bound). */
    override fun close() {
        stopping = true
        acceptor.join()
        val all = synchronized(threads) { ArrayList(threads) }
        for (t in all) t.join()
        server.close()
    }
}
