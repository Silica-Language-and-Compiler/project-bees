// EXAMPLE ONLY, not for production. See README.md in the directory above.
//
// Ed25519, SHA-512, random bytes and certificates, through OpenSSL (OpenSsl.cs). An Ed25519 signature made here is
// the same bytes on every call (RFC 8032), so tokens and proofs can be compared byte for byte with the other
// extensions. .NET 11 on macOS has no Ed25519 of its own.
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;

namespace Bees.Tempus
{
    public static class Crypto
    {
        public static byte[] Sha512(byte[] data)
        {
            var o = new byte[64];
            if (OpenSsl.EVP_Digest(data, (nuint)data.Length, o, out uint n, OpenSsl.EVP_sha512(), IntPtr.Zero) != 1 || n != 64)
                throw new InvalidOperationException("SHA-512 failed");
            return o;
        }

        /// <summary>The identifier of a public key: its SHA-512.</summary>
        public static byte[] PeerId(byte[] pub) => Sha512(pub);

        /// <summary>Bytes from the system's secure random source, through OpenSSL; null when it gave none.</summary>
        public static byte[] RandomBytes(int n)
        {
            var o = new byte[n];
            return OpenSsl.RAND_bytes(o, n) == 1 ? o : null;
        }

        /// <summary>True when sig is the Ed25519 signature of message under the 32 raw bytes of a public key.</summary>
        public static bool Ed25519Verify(byte[] pub, byte[] message, byte[] sig)
        {
            if (pub == null || sig == null || pub.Length != 32 || sig.Length != 64) return false;
            IntPtr k = OpenSsl.EVP_PKEY_new_raw_public_key(OpenSsl.EVP_PKEY_ED25519, IntPtr.Zero, pub, 32);
            if (k == IntPtr.Zero) { OpenSsl.ERR_clear_error(); return false; }
            IntPtr ctx = OpenSsl.EVP_MD_CTX_new();
            try
            {
                if (ctx == IntPtr.Zero || OpenSsl.EVP_DigestVerifyInit(ctx, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero, k) != 1) return false;
                return OpenSsl.EVP_DigestVerify(ctx, sig, (nuint)sig.Length, message, (nuint)message.Length) == 1;
            }
            finally
            {
                if (ctx != IntPtr.Zero) OpenSsl.EVP_MD_CTX_free(ctx);
                OpenSsl.EVP_PKEY_free(k);
                OpenSsl.ERR_clear_error();
            }
        }

        public static byte[] Concat(byte[] a, byte[] b)
        {
            var o = new byte[a.Length + b.Length];
            Buffer.BlockCopy(a, 0, o, 0, a.Length);
            Buffer.BlockCopy(b, 0, o, a.Length, b.Length);
            return o;
        }

        /// <summary>The DER bytes between the BEGIN and END lines of the first PEM block with that label; null when there is none.</summary>
        public static byte[] PemBlock(string pem, string label)
        {
            string begin = "-----BEGIN " + label + "-----", end = "-----END " + label + "-----";
            int a = pem.IndexOf(begin, StringComparison.Ordinal);
            if (a < 0) return null;
            int b = pem.IndexOf(end, a, StringComparison.Ordinal);
            if (b < 0) return null;
            try { return Convert.FromBase64String(new string(pem.Substring(a + begin.Length, b - a - begin.Length).Where(c => !char.IsWhiteSpace(c)).ToArray())); }
            catch (FormatException) { return null; }
        }
    }

    /// <summary>
    /// An Ed25519 private key. It is held by OpenSSL; this object never gives its bytes out, and nothing in the
    /// extension prints or sends them.
    /// </summary>
    public sealed class SigningKey
    {
        internal readonly IntPtr Pkey;
        /// <summary>The 32 raw bytes of the public key.</summary>
        public byte[] Pub { get; }

        SigningKey(IntPtr pkey)
        {
            Pkey = pkey;
            var raw = new byte[32];
            nuint n = 32;
            if (OpenSsl.EVP_PKEY_get_base_id(pkey) != OpenSsl.EVP_PKEY_ED25519 || OpenSsl.EVP_PKEY_get_raw_public_key(pkey, raw, ref n) != 1 || n != 32)
            {
                OpenSsl.EVP_PKEY_free(pkey);
                OpenSsl.ERR_clear_error();
                GC.SuppressFinalize(this);
                throw new ArgumentException("the key is not an Ed25519 private key");
            }
            Pub = raw;
        }

        ~SigningKey() { OpenSsl.EVP_PKEY_free(Pkey); }

        /// <summary>The key of a 32-byte seed (RFC 8032).</summary>
        public static SigningKey FromSeed(byte[] seed)
        {
            if (seed == null || seed.Length != 32) throw new ArgumentException("an Ed25519 seed is 32 bytes");
            IntPtr k = OpenSsl.EVP_PKEY_new_raw_private_key(OpenSsl.EVP_PKEY_ED25519, IntPtr.Zero, seed, 32);
            if (k == IntPtr.Zero) { OpenSsl.ERR_clear_error(); throw new ArgumentException("the Ed25519 key could not be made"); }
            return new SigningKey(k);
        }

        /// <summary>The key of an unencrypted PKCS#8 PEM text ("-----BEGIN PRIVATE KEY-----").</summary>
        public static unsafe SigningKey FromPem(string pem)
        {
            var der = Crypto.PemBlock(pem, "PRIVATE KEY");
            if (der == null) throw new ArgumentException("the key file is not an unencrypted PKCS#8 PEM file");
            IntPtr k;
            fixed (byte* p = der)
            {
                IntPtr pp = (IntPtr)p;
                k = OpenSsl.d2i_AutoPrivateKey(IntPtr.Zero, ref pp, der.Length);
            }
            Array.Clear(der, 0, der.Length);
            if (k == IntPtr.Zero) { OpenSsl.ERR_clear_error(); throw new ArgumentException("the key file does not hold a private key"); }
            return new SigningKey(k);
        }

        /// <summary>The Ed25519 signature of a message: 64 bytes, the same bytes on every call.</summary>
        public byte[] Sign(byte[] message)
        {
            IntPtr ctx = OpenSsl.EVP_MD_CTX_new();
            try
            {
                var sig = new byte[64];
                nuint n = 64;
                if (ctx == IntPtr.Zero || OpenSsl.EVP_DigestSignInit(ctx, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero, Pkey) != 1 ||
                    OpenSsl.EVP_DigestSign(ctx, sig, ref n, message, (nuint)message.Length) != 1 || n != 64)
                {
                    OpenSsl.ERR_clear_error();
                    throw new InvalidOperationException("the signature could not be made");
                }
                return sig;
            }
            finally
            {
                if (ctx != IntPtr.Zero) OpenSsl.EVP_MD_CTX_free(ctx);
                GC.KeepAlive(this);
            }
        }
    }

    /// <summary>
    /// One X.509 certificate, as its DER bytes, with what tempus/1 asks of it worked out once: whether its key is an
    /// Ed25519 key (and the 32 raw bytes of it), and whether it is self-signed (issuer equal to subject and its
    /// signature verifying under its own key). No authority is consulted and the validity dates are not read: the
    /// token carries the validity period.
    /// </summary>
    public sealed class Certificate
    {
        public byte[] Der { get; }
        /// <summary>The 32 raw bytes of the certificate's Ed25519 key; null when the key is of another kind.</summary>
        public byte[] Ed25519Key { get; }
        public bool SelfSigned { get; }
        /// <summary>The SHA-512 of the DER, as lower-case hex: how a tempus whitelist names a certificate.</summary>
        public string Fingerprint { get; }

        public unsafe Certificate(byte[] der)
        {
            IntPtr x;
            fixed (byte* p = der)
            {
                IntPtr pp = (IntPtr)p;
                x = OpenSsl.d2i_X509(IntPtr.Zero, ref pp, der.Length);
                if (x != IntPtr.Zero && pp != (IntPtr)(p + der.Length)) { OpenSsl.X509_free(x); x = IntPtr.Zero; }    // bytes after the certificate
            }
            if (x == IntPtr.Zero) { OpenSsl.ERR_clear_error(); throw new Refused("the certificate cannot be read"); }
            try
            {
                Der = (byte[])der.Clone();
                Fingerprint = Hex.Of(Crypto.Sha512(Der));
                IntPtr key = OpenSsl.X509_get0_pubkey(x);
                if (key != IntPtr.Zero && OpenSsl.EVP_PKEY_get_base_id(key) == OpenSsl.EVP_PKEY_ED25519)
                {
                    var raw = new byte[32];
                    nuint n = 32;
                    if (OpenSsl.EVP_PKEY_get_raw_public_key(key, raw, ref n) == 1 && n == 32) Ed25519Key = raw;
                }
                SelfSigned = key != IntPtr.Zero && OpenSsl.X509_NAME_cmp(OpenSsl.X509_get_issuer_name(x), OpenSsl.X509_get_subject_name(x)) == 0 &&
                    OpenSsl.X509_verify(x, key) == 1;
            }
            finally
            {
                OpenSsl.X509_free(x);
                OpenSsl.ERR_clear_error();
            }
        }

        /// <summary>The first certificate of a PEM text.</summary>
        public static Certificate FromPem(string pem)
        {
            var der = Crypto.PemBlock(pem, "CERTIFICATE");
            if (der == null) throw new Refused("the certificate cannot be read");
            return new Certificate(der);
        }

        public string ToPem()
        {
            var b64 = Convert.ToBase64String(Der);
            var sb = new StringBuilder("-----BEGIN CERTIFICATE-----\n");
            for (int i = 0; i < b64.Length; i += 64) sb.Append(b64, i, Math.Min(64, b64.Length - i)).Append('\n');
            return sb.Append("-----END CERTIFICATE-----\n").ToString();
        }

        /// <summary>
        /// The raw key, after checking what tempus/1 requires of a certificate: an Ed25519 key, the issuer equal to
        /// the subject, and the signature verifying under the certificate's own key. Refused(reason) otherwise.
        /// </summary>
        public byte[] TempusKey()
        {
            if (Ed25519Key == null) throw new Refused("the certificate's key is not Ed25519");
            if (!SelfSigned) throw new Refused("the certificate is not self-signed");
            return Ed25519Key;
        }

        /// <summary>
        /// A certificate self-signed over key: version 3, no extensions, the subject and the issuer one common name.
        /// .NET cannot make one for an Ed25519 key on macOS, so the extension offers this to an application that has
        /// no other tool. notBefore and notAfter are UTCTime texts, "YYMMDDHHMMSSZ"; the dates are never checked by a
        /// TEMPUS peer.
        /// </summary>
        public static Certificate SelfSign(SigningKey key, string commonName, long serial, string notBefore, string notAfter)
        {
            IntPtr x = OpenSsl.X509_new(), name = OpenSsl.X509_NAME_new();
            try
            {
                var cn = Encoding.UTF8.GetBytes(commonName);
                if (x == IntPtr.Zero || name == IntPtr.Zero ||
                    OpenSsl.X509_set_version(x, 2) != 1 ||
                    OpenSsl.ASN1_INTEGER_set(OpenSsl.X509_get_serialNumber(x), (nint)serial) != 1 ||
                    OpenSsl.X509_NAME_add_entry_by_txt(name, "CN", OpenSsl.MBSTRING_UTF8, cn, cn.Length, -1, 0) != 1 ||
                    OpenSsl.X509_set_subject_name(x, name) != 1 || OpenSsl.X509_set_issuer_name(x, name) != 1 ||
                    OpenSsl.ASN1_TIME_set_string(OpenSsl.X509_getm_notBefore(x), notBefore) != 1 ||
                    OpenSsl.ASN1_TIME_set_string(OpenSsl.X509_getm_notAfter(x), notAfter) != 1 ||
                    OpenSsl.X509_set_pubkey(x, key.Pkey) != 1 ||
                    OpenSsl.X509_sign(x, key.Pkey, IntPtr.Zero) <= 0)
                {
                    OpenSsl.ERR_clear_error();
                    throw new InvalidOperationException("the certificate could not be made");
                }
                return new Certificate(DerOf(x));
            }
            finally
            {
                if (name != IntPtr.Zero) OpenSsl.X509_NAME_free(name);
                if (x != IntPtr.Zero) OpenSsl.X509_free(x);
                GC.KeepAlive(key);
            }
        }

        internal static unsafe byte[] DerOf(IntPtr x)
        {
            int n = OpenSsl.i2d_X509(x, IntPtr.Zero);
            if (n <= 0) return null;
            var o = new byte[n];
            fixed (byte* p = o)
            {
                IntPtr pp = (IntPtr)p;
                if (OpenSsl.i2d_X509(x, ref pp) != n) return null;
            }
            return o;
        }

        internal unsafe IntPtr ToX509()
        {
            fixed (byte* p = Der)
            {
                IntPtr pp = (IntPtr)p;
                return OpenSsl.d2i_X509(IntPtr.Zero, ref pp, Der.Length);
            }
        }
    }
}
