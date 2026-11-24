// A usable example, to be used carefully. See README.md in the directory above.
//
// The OpenSSL installed on the machine (4.1.0 or later), called as a C library through P/Invoke. Declarations only:
// there is no C code in this extension. .NET's own TLS (SslStream) and cryptography cannot be used on macOS, where
// they are Apple's: no Ed25519 key can be loaded, and no handshake with a TEMPUS node completes (README.md, "Why not
// SslStream"). Several OpenSSL settings are C macros over SSL_CTX_ctrl; this file calls what they expand to.
//
// Where the two libraries are looked for, in this order: the directory in OpenSsl.LibraryDirectory when the
// application set it before the first use; the directory in the environment variable BEES_OPENSSL_LIB; then
// /opt/homebrew/opt/openssl@4/lib and /usr/local/opt/openssl@4/lib (Homebrew on a Mac); then the system's own search
// for libssl.so.4 and libcrypto.so.4, or libssl.4.dylib and libcrypto.4.dylib.
using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;

namespace Bees.Tempus
{
    /// <summary>OpenSSL could not be loaded or is too old.</summary>
    public sealed class OpenSslUnavailable : Exception
    {
        public OpenSslUnavailable(string why) : base(why) { }
    }

    public static unsafe class OpenSsl
    {
        const string Ssl = "bees-tempus-libssl";
        const string Crypto = "bees-tempus-libcrypto";

        /// <summary>The directory that holds libssl and libcrypto, when the application names it. Set it before anything else is used.</summary>
        public static string LibraryDirectory;

        static readonly Dictionary<string, IntPtr> Loaded = new Dictionary<string, IntPtr>();

        static OpenSsl()
        {
            NativeLibrary.SetDllImportResolver(typeof(OpenSsl).Assembly, Resolve);
        }

        static IntPtr Resolve(string name, Assembly assembly, DllImportSearchPath? path)
        {
            if (name != Ssl && name != Crypto) return IntPtr.Zero;
            lock (Loaded)
            {
                if (Loaded.TryGetValue(name, out var have)) return have;
                string stem = name == Ssl ? "libssl" : "libcrypto";
                bool mac = RuntimeInformation.IsOSPlatform(OSPlatform.OSX);
                string file = mac ? stem + ".4.dylib" : stem + ".so.4";
                var tried = new List<string>();
                var dirs = new List<string>();
                if (!string.IsNullOrEmpty(LibraryDirectory)) dirs.Add(LibraryDirectory);
                string env = Environment.GetEnvironmentVariable("BEES_OPENSSL_LIB");
                if (!string.IsNullOrEmpty(env)) dirs.Add(env);
                if (mac) { dirs.Add("/opt/homebrew/opt/openssl@4/lib"); dirs.Add("/usr/local/opt/openssl@4/lib"); }
                foreach (var d in dirs)
                {
                    string full = Path.Combine(d, file);
                    tried.Add(full);
                    if (NativeLibrary.TryLoad(full, out var h)) { Loaded[name] = h; return h; }
                }
                tried.Add(file);
                if (NativeLibrary.TryLoad(file, out var sys)) { Loaded[name] = sys; return sys; }
                throw new OpenSslUnavailable("OpenSSL 4.1.0 or later is needed and " + stem + " was not found (tried " + string.Join(", ", tried) +
                    "); set the environment variable BEES_OPENSSL_LIB to the directory that holds it");
            }
        }

        /// <summary>The version text of the OpenSSL in use, for example "OpenSSL 4.1.0 ...".</summary>
        public static string Version() => Marshal.PtrToStringUTF8(OpenSSL_version(0));

        /// <summary>OpenSslUnavailable unless the OpenSSL found is 4.1.0 or later.</summary>
        public static void Require()
        {
            ulong v = OpenSSL_version_num();          // 0xMNN00PP0: major, minor, patch
            if (v < 0x40100000UL) throw new OpenSslUnavailable("OpenSSL 4.1.0 or later is needed; found " + Version());
        }

        // ---------------------------------------------------------------- constants (the values of OpenSSL's headers)
        public const int EVP_PKEY_ED25519 = 1087;
        public const int SSL_CTRL_SET_SESS_CACHE_MODE = 44;
        public const int SSL_CTRL_SET_GROUPS_LIST = 92;
        public const int SSL_CTRL_SET_SIGALGS_LIST = 98;
        public const int SSL_CTRL_SET_CLIENT_SIGALGS_LIST = 102;
        public const int SSL_CTRL_SET_MIN_PROTO_VERSION = 123;
        public const int SSL_CTRL_SET_MAX_PROTO_VERSION = 124;
        public const int TLS1_3_VERSION = 0x0304;
        public const int SSL_VERIFY_PEER = 1;
        public const int SSL_VERIFY_FAIL_IF_NO_PEER_CERT = 2;
        public const int SSL_ERROR_SSL = 1;
        public const int SSL_ERROR_WANT_READ = 2;
        public const int SSL_ERROR_WANT_WRITE = 3;
        public const int SSL_ERROR_SYSCALL = 5;
        public const int SSL_ERROR_ZERO_RETURN = 6;
        public const int SSL_TLSEXT_ERR_OK = 0;
        public const int SSL_TLSEXT_ERR_ALERT_FATAL = 2;
        public const int SSL_TLSEXT_ERR_NOACK = 3;
        public const int BIO_CTRL_PENDING = 10;
        public const int MBSTRING_UTF8 = 0x1000;

        // ---------------------------------------------------------------- libcrypto
        [DllImport(Crypto)] public static extern ulong OpenSSL_version_num();
        [DllImport(Crypto)] public static extern IntPtr OpenSSL_version(int type);
        [DllImport(Crypto)] public static extern void ERR_clear_error();
        [DllImport(Crypto)] public static extern ulong ERR_peek_last_error();
        [DllImport(Crypto)] public static extern IntPtr ERR_reason_error_string(ulong e);
        [DllImport(Crypto)] public static extern int RAND_bytes(byte[] buf, int num);
        [DllImport(Crypto)] public static extern IntPtr EVP_sha512();
        [DllImport(Crypto)] public static extern int EVP_Digest(byte[] data, nuint count, byte[] md, out uint size, IntPtr type, IntPtr impl);
        [DllImport(Crypto)] public static extern IntPtr EVP_PKEY_new_raw_private_key(int type, IntPtr e, byte[] key, nuint len);
        [DllImport(Crypto)] public static extern IntPtr EVP_PKEY_new_raw_public_key(int type, IntPtr e, byte[] key, nuint len);
        [DllImport(Crypto)] public static extern int EVP_PKEY_get_raw_public_key(IntPtr pkey, byte[] pub, ref nuint len);
        [DllImport(Crypto)] public static extern int EVP_PKEY_get_base_id(IntPtr pkey);
        [DllImport(Crypto)] public static extern void EVP_PKEY_free(IntPtr pkey);
        [DllImport(Crypto)] public static extern IntPtr d2i_AutoPrivateKey(IntPtr a, ref IntPtr pp, nint length);
        [DllImport(Crypto)] public static extern IntPtr EVP_MD_CTX_new();
        [DllImport(Crypto)] public static extern void EVP_MD_CTX_free(IntPtr ctx);
        [DllImport(Crypto)] public static extern int EVP_DigestSignInit(IntPtr ctx, IntPtr pctx, IntPtr type, IntPtr e, IntPtr pkey);
        [DllImport(Crypto)] public static extern int EVP_DigestSign(IntPtr ctx, byte[] sig, ref nuint siglen, byte[] tbs, nuint tbslen);
        [DllImport(Crypto)] public static extern int EVP_DigestVerifyInit(IntPtr ctx, IntPtr pctx, IntPtr type, IntPtr e, IntPtr pkey);
        [DllImport(Crypto)] public static extern int EVP_DigestVerify(IntPtr ctx, byte[] sig, nuint siglen, byte[] tbs, nuint tbslen);
        [DllImport(Crypto)] public static extern IntPtr d2i_X509(IntPtr a, ref IntPtr pp, nint length);
        [DllImport(Crypto)] public static extern int i2d_X509(IntPtr x, IntPtr pp);
        [DllImport(Crypto)] public static extern int i2d_X509(IntPtr x, ref IntPtr pp);
        [DllImport(Crypto)] public static extern IntPtr X509_new();
        [DllImport(Crypto)] public static extern void X509_free(IntPtr x);
        [DllImport(Crypto)] public static extern IntPtr X509_get0_pubkey(IntPtr x);
        [DllImport(Crypto)] public static extern IntPtr X509_get_issuer_name(IntPtr x);
        [DllImport(Crypto)] public static extern IntPtr X509_get_subject_name(IntPtr x);
        [DllImport(Crypto)] public static extern int X509_NAME_cmp(IntPtr a, IntPtr b);
        [DllImport(Crypto)] public static extern int X509_verify(IntPtr x, IntPtr pkey);
        [DllImport(Crypto)] public static extern int X509_set_version(IntPtr x, nint version);
        [DllImport(Crypto)] public static extern IntPtr X509_get_serialNumber(IntPtr x);
        [DllImport(Crypto)] public static extern int ASN1_INTEGER_set(IntPtr a, nint v);
        [DllImport(Crypto)] public static extern IntPtr X509_NAME_new();
        [DllImport(Crypto)] public static extern void X509_NAME_free(IntPtr n);
        [DllImport(Crypto)] public static extern int X509_NAME_add_entry_by_txt(IntPtr name, [MarshalAs(UnmanagedType.LPUTF8Str)] string field, int type, byte[] bytes, int len, int loc, int set);
        [DllImport(Crypto)] public static extern int X509_set_subject_name(IntPtr x, IntPtr name);
        [DllImport(Crypto)] public static extern int X509_set_issuer_name(IntPtr x, IntPtr name);
        [DllImport(Crypto)] public static extern IntPtr X509_getm_notBefore(IntPtr x);
        [DllImport(Crypto)] public static extern IntPtr X509_getm_notAfter(IntPtr x);
        [DllImport(Crypto)] public static extern int ASN1_TIME_set_string(IntPtr s, [MarshalAs(UnmanagedType.LPUTF8Str)] string str);
        [DllImport(Crypto)] public static extern int X509_set_pubkey(IntPtr x, IntPtr pkey);
        [DllImport(Crypto)] public static extern int X509_sign(IntPtr x, IntPtr pkey, IntPtr md);
        [DllImport(Crypto)] public static extern IntPtr BIO_s_mem();
        [DllImport(Crypto)] public static extern IntPtr BIO_new(IntPtr type);
        [DllImport(Crypto)] public static extern int BIO_read(IntPtr b, byte* data, int dlen);
        [DllImport(Crypto)] public static extern int BIO_write(IntPtr b, byte* data, int dlen);
        [DllImport(Crypto)] public static extern nint BIO_ctrl(IntPtr b, int cmd, nint larg, IntPtr parg);

        // ---------------------------------------------------------------- libssl
        [DllImport(Ssl)] public static extern IntPtr TLS_server_method();
        [DllImport(Ssl)] public static extern IntPtr TLS_client_method();
        [DllImport(Ssl)] public static extern IntPtr SSL_CTX_new(IntPtr method);
        [DllImport(Ssl)] public static extern void SSL_CTX_free(IntPtr ctx);
        [DllImport(Ssl)] public static extern nint SSL_CTX_ctrl(IntPtr ctx, int cmd, nint larg, IntPtr parg);
        [DllImport(Ssl)] public static extern nint SSL_CTX_ctrl(IntPtr ctx, int cmd, nint larg, [MarshalAs(UnmanagedType.LPUTF8Str)] string parg);
        [DllImport(Ssl)] public static extern int SSL_CTX_set_ciphersuites(IntPtr ctx, [MarshalAs(UnmanagedType.LPUTF8Str)] string str);
        [DllImport(Ssl)] public static extern int SSL_CTX_use_certificate(IntPtr ctx, IntPtr x);
        [DllImport(Ssl)] public static extern int SSL_CTX_use_PrivateKey(IntPtr ctx, IntPtr pkey);
        [DllImport(Ssl)] public static extern int SSL_CTX_check_private_key(IntPtr ctx);
        [DllImport(Ssl)] public static extern void SSL_CTX_set_verify(IntPtr ctx, int mode, IntPtr callback);
        [DllImport(Ssl)] public static extern void SSL_CTX_set_cert_verify_callback(IntPtr ctx, delegate* unmanaged[Cdecl]<IntPtr, IntPtr, int> cb, IntPtr arg);
        [DllImport(Ssl)] public static extern int SSL_CTX_set_num_tickets(IntPtr ctx, nuint n);
        [DllImport(Ssl)] public static extern void SSL_CTX_set_alpn_select_cb(IntPtr ctx, delegate* unmanaged[Cdecl]<IntPtr, byte**, byte*, byte*, uint, IntPtr, int> cb, IntPtr arg);
        [DllImport(Ssl)] public static extern int SSL_CTX_set_alpn_protos(IntPtr ctx, byte[] protos, uint len);
        [DllImport(Ssl)] public static extern IntPtr SSL_new(IntPtr ctx);
        [DllImport(Ssl)] public static extern void SSL_free(IntPtr ssl);
        [DllImport(Ssl)] public static extern void SSL_set_bio(IntPtr ssl, IntPtr rbio, IntPtr wbio);
        [DllImport(Ssl)] public static extern void SSL_set_connect_state(IntPtr ssl);
        [DllImport(Ssl)] public static extern void SSL_set_accept_state(IntPtr ssl);
        [DllImport(Ssl)] public static extern int SSL_do_handshake(IntPtr ssl);
        [DllImport(Ssl)] public static extern int SSL_read(IntPtr ssl, byte* buf, int num);
        [DllImport(Ssl)] public static extern int SSL_write(IntPtr ssl, byte* buf, int num);
        [DllImport(Ssl)] public static extern int SSL_get_error(IntPtr ssl, int ret);
        [DllImport(Ssl)] public static extern int SSL_shutdown(IntPtr ssl);
        [DllImport(Ssl)] public static extern void SSL_get0_alpn_selected(IntPtr ssl, out IntPtr data, out uint len);
        [DllImport(Ssl)] public static extern IntPtr SSL_get_version(IntPtr ssl);
        [DllImport(Ssl)] public static extern IntPtr SSL_get1_peer_certificate(IntPtr ssl);
        [DllImport(Ssl)] public static extern IntPtr SSL_get0_group_name(IntPtr ssl);
        [DllImport(Ssl)] public static extern IntPtr SSL_get_current_cipher(IntPtr ssl);
        [DllImport(Ssl)] public static extern IntPtr SSL_CIPHER_get_name(IntPtr cipher);

        // ---------------------------------------------------------------- the two callbacks OpenSSL calls back into
        /// <summary>
        /// Accepts whatever chain the peer presented: a TEMPUS certificate is self-signed and no authority exists. The
        /// handshake itself still proves that the peer holds the certificate's private key (the TLS 1.3
        /// CertificateVerify, which OpenSSL always checks). What the certificate must be is judged after the handshake.
        /// </summary>
        [UnmanagedCallersOnly(CallConvs = new[] { typeof(CallConvCdecl) })]
        public static int AcceptAnyChain(IntPtr storeCtx, IntPtr arg) => 1;

        static readonly byte[] Tempus1 = { (byte)'t', (byte)'e', (byte)'m', (byte)'p', (byte)'u', (byte)'s', (byte)'/', (byte)'1' };

        /// <summary>
        /// A listener's choice of the application protocol: tempus/1 when the dialer offers it. Otherwise: with arg 0
        /// no protocol is selected, and the check after the handshake refuses; with arg 1 the handshake ends with the
        /// fatal alert no_application_protocol, as a BEES node's does.
        /// </summary>
        [UnmanagedCallersOnly(CallConvs = new[] { typeof(CallConvCdecl) })]
        public static int AlpnSelect(IntPtr ssl, byte** outp, byte* outlen, byte* inp, uint inlen, IntPtr arg)
        {
            int refuse = arg == IntPtr.Zero ? SSL_TLSEXT_ERR_NOACK : SSL_TLSEXT_ERR_ALERT_FATAL;
            if (outp == null || outlen == null || inp == null) return refuse;
            uint i = 0;
            while (i < inlen)
            {
                uint n = inp[i];
                if (i + 1 + n > inlen) break;
                if (n == Tempus1.Length)
                {
                    bool same = true;
                    for (int k = 0; k < n; k++) if (inp[i + 1 + k] != Tempus1[k]) { same = false; break; }
                    if (same) { *outp = inp + i + 1; *outlen = (byte)n; return SSL_TLSEXT_ERR_OK; }
                }
                i += 1 + n;
            }
            return refuse;
        }

        /// <summary>The reason text of the last OpenSSL error, and the error queue emptied.</summary>
        public static string Reason()
        {
            ulong e = ERR_peek_last_error();
            IntPtr s = e == 0 ? IntPtr.Zero : ERR_reason_error_string(e);
            ERR_clear_error();
            return s == IntPtr.Zero ? "" : Marshal.PtrToStringUTF8(s);
        }
    }
}
