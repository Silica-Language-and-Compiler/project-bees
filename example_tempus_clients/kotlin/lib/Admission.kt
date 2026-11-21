// EXAMPLE ONLY, not for production. See README.md beside the lib directory.
//
// What a client holds (its identity) and what it checks of another peer (the verifier): the token, the channel
// binding, the tempus whitelist and the proof of possession. Design section 4; the order of the checks is the node's
// (writing-a-tempus-client.md section 6).
package bees.tempus

import java.io.ByteArrayInputStream
import java.nio.file.Files
import java.nio.file.Path
import java.security.KeyFactory
import java.security.PrivateKey
import java.security.PublicKey
import java.security.Signature
import java.security.cert.CertificateFactory
import java.security.cert.X509Certificate
import java.security.spec.PKCS8EncodedKeySpec
import java.security.spec.X509EncodedKeySpec
import java.util.Base64

// The DER of an Ed25519 SubjectPublicKeyInfo is these 12 bytes followed by the 32 bytes of the key (RFC 8410).
private val ED25519_SPKI = unhex("302a300506032b6570032100")

/** The Ed25519 public key object of 32 raw bytes. */
fun publicKeyOf(raw: ByteArray): PublicKey {
    require(raw.size == 32) { "an Ed25519 public key is 32 bytes" }
    return KeyFactory.getInstance("Ed25519").generatePublic(X509EncodedKeySpec(ED25519_SPKI + raw))
}

/** The 32 raw bytes of an Ed25519 public key; Refused when the key is of another kind. */
fun rawPublicKey(key: PublicKey): ByteArray {
    val der = key.encoded ?: throw Refused("the certificate's key is not Ed25519")
    if (der.size != 44 || !der.copyOf(12).contentEquals(ED25519_SPKI)) throw Refused("the certificate's key is not Ed25519")
    return der.copyOfRange(12, 44)
}

fun ed25519Verify(pub: ByteArray, message: ByteArray, sig: ByteArray): Boolean = try {
    val v = Signature.getInstance("Ed25519")
    v.initVerify(publicKeyOf(pub))
    v.update(message)
    v.verify(sig)
} catch (e: Exception) {
    false
}

fun ed25519Sign(key: PrivateKey, message: ByteArray): ByteArray {
    val s = Signature.getInstance("Ed25519")
    s.initSign(key)
    s.update(message)
    return s.sign()
}

/**
 * The raw Ed25519 key of a certificate, after checking what tempus/1 requires of a certificate: an Ed25519 key, the
 * issuer equal to the subject, and the signature verifying under the certificate's own key. No authority is consulted
 * and the validity dates are not checked: the token carries the validity period. Refused(reason) otherwise.
 */
fun certificateKey(cert: X509Certificate): ByteArray {
    val raw = rawPublicKey(cert.publicKey)
    try {
        if (cert.issuerX500Principal != cert.subjectX500Principal) throw Refused("the certificate is not self-signed")
        cert.verify(cert.publicKey)
    } catch (e: Exception) {
        throw Refused("the certificate is not self-signed")
    }
    return raw
}

/** The SHA-512 of a certificate's DER, as lower-case hex: how a tempus whitelist names a certificate. */
fun fingerprint(cert: X509Certificate): String = hex(sha512(cert.encoded))

fun readCertificate(pem: ByteArray): X509Certificate =
    CertificateFactory.getInstance("X.509").generateCertificate(ByteArrayInputStream(pem)) as X509Certificate

fun readPrivateKey(pem: ByteArray): PrivateKey {
    val text = String(pem, Charsets.US_ASCII)
    require(text.contains("-----BEGIN PRIVATE KEY-----")) { "the key file is not an unencrypted PKCS#8 PEM file" }
    val der = Base64.getMimeDecoder().decode(text.replace(Regex("-----[A-Z ]+-----"), ""))
    return KeyFactory.getInstance("Ed25519").generatePrivate(PKCS8EncodedKeySpec(der))
}

/**
 * One peer: its Ed25519 private key, its certificate self-signed over that key, its token exactly as the producer
 * gave it, and the listen address it advertises, as the text host:port. The private key never leaves this object
 * except into the JDK's TLS and signature code, and nothing here prints it.
 */
class Identity(val certificate: X509Certificate, val key: PrivateKey, val token: ByteArray, val addr: String) {
    val pub: ByteArray = certificateKey(certificate)
    val peerId: ByteArray = peerId(pub)

    init {
        require(token.size in 65..1024) { "a token is 65 to 1024 bytes" }
        require(addr.toByteArray(Charsets.UTF_8).size in 3..261) { "a listen address is 3 to 261 bytes" }
        val probe = "bees tempus example: the key file belongs to the certificate".toByteArray()
        require(ed25519Verify(pub, probe, ed25519Sign(key, probe))) { "the private key is not the certificate's key" }
    }

    fun descriptor(): Descriptor = Descriptor(peerId, pub, addr.toByteArray(Charsets.UTF_8), token)

    fun entry(age: Int = 0): Entry = Entry(age, descriptor())

    /** The proof of possession: this key's signature over the peer's nonce followed by this peer's own token. */
    fun prove(nonce: ByteArray): ByteArray = ed25519Sign(key, nonce + token)

    fun withToken(other: ByteArray) = Identity(certificate, key, other, addr)

    fun withAddr(other: String) = Identity(certificate, key, token, other)

    companion object {
        fun load(certPem: Path, keyPem: Path, token: ByteArray, addr: String): Identity =
            Identity(readCertificate(Files.readAllBytes(certPem)), readPrivateKey(Files.readAllBytes(keyPem)), token, addr)
    }
}

/**
 * What this client needs to check another peer: the producer's current public key (32 raw bytes) and its kid, a clock
 * in whole seconds since 1970 UTC, the clock difference it allows in seconds, and its tempus whitelist: the
 * fingerprints (fingerprint()) of the certificates of the bridges and sentinels it accepts. The whitelist may be empty;
 * the client then accepts no bridge and no sentinel on a connection.
 */
class Verifier(val producerPub: ByteArray, val kid: ByteArray, val now: () -> Long, val skew: Long, val whitelist: Set<String>) {
    init {
        require(producerPub.size == 32) { "the producer's public key is 32 bytes" }
        require(kid.size in 1..64) { "a kid is 1 to 64 bytes" }
        require(skew >= 0) { "the skew is not negative" }
    }

    /**
     * The checks of a descriptor that need no connection, in the node's order: the token's structure, its kid
     * (Refused("key_rotated")), the time, sub, the id hash, the producer's signature. Returns the token.
     */
    private fun check(d: Descriptor, between: (Token) -> Unit): Token {
        val t = readToken(d.token)
        val at = now()
        if (!t.kid.contentEquals(kid)) throw Refused("key_rotated")
        if (at < t.nbf - skew) throw Refused("the token is not valid yet")
        if (at >= t.exp + skew) throw Refused("the token has expired")
        if (!t.sub.contentEquals(d.pub)) throw Refused("sub is not the peer's key")
        between(t)
        if (!peerId(d.pub).contentEquals(d.id)) throw Refused("id is not the SHA-512 of pub")
        if (!ed25519Verify(producerPub, t.payload, t.sig)) throw Refused("the signature does not verify")
        return t
    }

    /**
     * The peer of a connection: its advert's descriptor and the certificate it presented in the TLS handshake.
     * First the channel binding: the advert's pub must be the certificate's key. Then the checks above, with the
     * whitelist rule between sub and the id hash: a token that says bridge or sentinel needs a certificate of the
     * whitelist, and a certificate of the whitelist needs such a token.
     */
    fun checkPeer(d: Descriptor, certificate: X509Certificate): Token {
        if (!certificateKey(certificate).contentEquals(d.pub)) throw Refused("the certificate's key is not the advert's pub")
        return check(d) { t ->
            val listed = fingerprint(certificate) in whitelist
            val special = t.typ == "tempus_bridge" || t.typ == "tempus_sentinel"
            if (special && !listed) throw Refused("a ${t.typ} whose certificate is not in the tempus whitelist")
            if (listed && !special) throw Refused("a certificate of the tempus whitelist with a ${t.typ} token")
        }
    }

    /** An entry received in a shuffle or sample frame of the named store: verified without contact. */
    fun checkEntry(d: Descriptor, store: String): Token =
        check(d) { t -> if (t.typ != store) throw Refused("typ is not the store's type") }

    /** The proof of possession: sig must be the signature, under pub, over the nonce this side sent and the peer's token. */
    fun checkProof(pub: ByteArray, nonce: ByteArray, token: ByteArray, sig: ByteArray) {
        if (!ed25519Verify(pub, nonce + token, sig)) throw Refused("the proof of possession does not verify")
    }
}
