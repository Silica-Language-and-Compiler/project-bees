// Ed25519, SHA-512 and certificates, through the OpenSSL installed on the machine.
// CryptoKit is not used: its Ed25519 signatures are randomized, so the same key and message give different bytes on
// every call, and the tokens and proofs of the trials could not be compared byte for byte.
// An example only: not for production.
import COpenSSL

public struct CryptoFailure: Error, CustomStringConvertible {
    public let description: String
    init(_ text: String) { description = text }
}

/// The SHA-512 of some bytes.
public func sha512(_ data: Bytes) -> Bytes {
    var out = Bytes(repeating: 0, count: 64)
    var n: UInt32 = 0
    let ok = EVP_Digest(data, data.count, &out, &n, EVP_sha512(), nil)
    precondition(ok == 1 && n == 64, "SHA-512 failed")
    return out
}

/// The identity of a public key: its SHA-512 (design section 4).
public func peerId(pub: Bytes) -> Bytes { sha512(pub) }

/// Bytes from the system's secure random source (through OpenSSL).
public func randomBytes(_ n: Int) throws -> Bytes {
    var out = Bytes(repeating: 0, count: n)
    guard RAND_bytes(&out, Int32(n)) == 1 else { throw CryptoFailure("no random bytes") }
    return out
}

/// An Ed25519 private key, from its 32-byte seed.
public final class SigningKey {
    package let pkey: OpaquePointer
    public let pub: Bytes

    public init(seed: Bytes) throws {
        guard seed.count == 32 else { throw CryptoFailure("an Ed25519 seed is 32 bytes") }
        guard let k = EVP_PKEY_new_raw_private_key(EVP_PKEY_ED25519, nil, seed, 32) else {
            throw CryptoFailure("the Ed25519 key could not be made")
        }
        pkey = k
        var raw = Bytes(repeating: 0, count: 32)
        var n = 32
        guard EVP_PKEY_get_raw_public_key(k, &raw, &n) == 1, n == 32 else {
            EVP_PKEY_free(k)
            throw CryptoFailure("the Ed25519 public key could not be read")
        }
        pub = raw
    }

    deinit { EVP_PKEY_free(pkey) }

    /// The Ed25519 signature of a message: 64 bytes, the same bytes on every call (RFC 8032).
    public func sign(_ message: Bytes) throws -> Bytes {
        guard let ctx = EVP_MD_CTX_new() else { throw CryptoFailure("no digest context") }
        defer { EVP_MD_CTX_free(ctx) }
        var sig = Bytes(repeating: 0, count: 64)
        var n = 64
        guard EVP_DigestSignInit(ctx, nil, nil, nil, pkey) == 1,
              EVP_DigestSign(ctx, &sig, &n, message, message.count) == 1, n == 64 else {
            throw CryptoFailure("the signature could not be made")
        }
        return sig
    }
}

/// True when `sig` is the Ed25519 signature of `message` under the raw 32-byte public key `pub`.
public func ed25519Verify(pub: Bytes, message: Bytes, sig: Bytes) -> Bool {
    guard pub.count == 32, sig.count == 64,
          let k = EVP_PKEY_new_raw_public_key(EVP_PKEY_ED25519, nil, pub, 32) else { return false }
    defer { EVP_PKEY_free(k) }
    guard let ctx = EVP_MD_CTX_new() else { return false }
    defer { EVP_MD_CTX_free(ctx) }
    guard EVP_DigestVerifyInit(ctx, nil, nil, nil, k) == 1 else { return false }
    let ok = EVP_DigestVerify(ctx, sig, sig.count, message, message.count) == 1
    ERR_clear_error()
    return ok
}

// ---------------------------------------------------------------- certificates
package func derOf(_ x: OpaquePointer) -> Bytes? {
    let n = i2d_X509(x, nil)
    guard n > 0 else { return nil }
    var out = Bytes(repeating: 0, count: Int(n))
    let written = out.withUnsafeMutableBufferPointer { buf -> Int32 in
        var p = buf.baseAddress
        return i2d_X509(x, &p)
    }
    return written == n ? out : nil
}

package func x509(der: Bytes) -> OpaquePointer? {
    der.withUnsafeBufferPointer { buf -> OpaquePointer? in
        var p = buf.baseAddress
        let x = d2i_X509(nil, &p, der.count)
        if let x, p != buf.baseAddress.map({ $0 + der.count }) {      // bytes after the certificate
            X509_free(x)
            return nil
        }
        return x
    }
}

/// The certificate of a PEM text (the first one in it), as DER.
public func certificateDER(pem: String) -> Bytes? {
    let lines = pem.split(whereSeparator: { $0 == "\n" || $0 == "\r\n" || $0 == "\r" }).map(String.init)
    guard let a = lines.firstIndex(of: "-----BEGIN CERTIFICATE-----"),
          let b = lines[a...].firstIndex(of: "-----END CERTIFICATE-----") else { return nil }
    return base64Decode(lines[(a + 1)..<b].joined())
}

public func certificatePEM(der: Bytes) -> String {
    let b64 = Array(base64Encode(der))
    var out = "-----BEGIN CERTIFICATE-----\n"
    var i = 0
    while i < b64.count {
        out += String(b64[i..<min(i + 64, b64.count)]) + "\n"
        i += 64
    }
    return out + "-----END CERTIFICATE-----\n"
}

private let b64Alphabet = Array("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/".utf8)

func base64Encode(_ data: Bytes) -> String {
    var out = Bytes()
    var i = 0
    while i < data.count {
        let a = data[i], b = i + 1 < data.count ? data[i + 1] : 0, c = i + 2 < data.count ? data[i + 2] : 0
        out.append(b64Alphabet[Int(a >> 2)])
        out.append(b64Alphabet[Int((a & 3) << 4 | b >> 4)])
        out.append(i + 1 < data.count ? b64Alphabet[Int((b & 15) << 2 | c >> 6)] : 61)
        out.append(i + 2 < data.count ? b64Alphabet[Int(c & 63)] : 61)
        i += 3
    }
    return String(decoding: out, as: UTF8.self)
}

func base64Decode(_ text: String) -> Bytes? {
    var out = Bytes()
    var acc = 0, bits = 0
    for ch in text.utf8 where ch != 61 {
        guard let v = b64Alphabet.firstIndex(of: ch) else { return nil }
        acc = (acc << 6) | v
        bits += 6
        if bits >= 8 {
            bits -= 8
            out.append(UInt8((acc >> bits) & 0xFF))
        }
    }
    return out
}

/// A certificate self-signed over `key`, as DER: version 3, no extensions, the subject and issuer one common name.
/// With the dates and serial numbers of tools/bees_tempus_certs.py it is byte for byte the certificate that tool
/// writes, because an Ed25519 signature is the same on every run. `notBefore` and `notAfter` are UTCTime texts,
/// "YYMMDDHHMMSSZ".
public func selfSignedCertificate(key: SigningKey, commonName: String, serial: Int,
                                  notBefore: String = "260101000000Z", notAfter: String = "460101000000Z") throws -> Bytes {
    guard let x = X509_new() else { throw CryptoFailure("no certificate") }
    defer { X509_free(x) }
    guard let name = X509_NAME_new() else { throw CryptoFailure("no name") }
    defer { X509_NAME_free(name) }
    let cn = Array(commonName.utf8)
    guard X509_set_version(x, 2) == 1,
          ASN1_INTEGER_set(X509_get_serialNumber(x), serial) == 1,
          X509_NAME_add_entry_by_txt(name, "CN", MBSTRING_UTF8, cn, Int32(cn.count), -1, 0) == 1,
          X509_set_subject_name(x, name) == 1, X509_set_issuer_name(x, name) == 1,
          ASN1_TIME_set_string(X509_getm_notBefore(x), notBefore) == 1,
          ASN1_TIME_set_string(X509_getm_notAfter(x), notAfter) == 1,
          X509_set_pubkey(x, key.pkey) == 1,
          X509_sign(x, key.pkey, nil) > 0,
          let der = derOf(x) else {
        throw CryptoFailure("the certificate could not be made")
    }
    return der
}

/// The raw 32-byte Ed25519 key of a certificate (DER), after checking what tempus/1 requires of it: an Ed25519 key,
/// issuer equal to subject, and the signature verifying under its own key. The validity dates are not checked
/// (ruling NQ-10: the producer token carries the validity window).
public func certificateKey(der: Bytes) throws -> Bytes {
    guard let x = x509(der: der), let key = X509_get0_pubkey(x) else {
        ERR_clear_error()
        throw Refused("the certificate cannot be read")
    }
    defer { X509_free(x) }
    guard EVP_PKEY_get_base_id(key) == EVP_PKEY_ED25519 else { throw Refused("the certificate's key is not Ed25519") }
    guard X509_NAME_cmp(X509_get_issuer_name(x), X509_get_subject_name(x)) == 0, X509_verify(x, key) == 1 else {
        ERR_clear_error()
        throw Refused("the certificate is not self-signed")
    }
    var raw = Bytes(repeating: 0, count: 32)
    var n = 32
    guard EVP_PKEY_get_raw_public_key(key, &raw, &n) == 1, n == 32 else { throw Refused("the certificate cannot be read") }
    return raw
}
