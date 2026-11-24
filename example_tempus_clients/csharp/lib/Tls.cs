// A usable example, to be used carefully. See README.md in the directory above.
//
// The transport: TCP with mutual TLS 1.3 on top, through OpenSSL (OpenSsl.cs). TLS, exactly:
//   - TLS 1.3 only; the key exchange group X25519MLKEM768 only; the cipher suites TLS_AES_256_GCM_SHA384 and
//     TLS_CHACHA20_POLY1305_SHA256; ALPN tempus/1; a certificate from both sides.
//   - No chain is verified, because a TEMPUS certificate is self-signed: OpenSSL is told to accept whatever chain the
//     peer presents. The handshake itself still proves that the peer holds the private key of the certificate it
//     presented. What the certificate must be is judged after the handshake, by the code that uses the connection.
//   - Certificate validity dates are not checked: the producer's token carries the validity period.
// The TCP connection is a System.Net.Sockets.Socket. OpenSSL never touches it: the TLS engine reads and writes two
// memory buffers (memory BIOs), and this file moves bytes between them and the Socket. That keeps every wait under
// the ONE deadline of the connection.
using System;
using System.Diagnostics;
using System.Net;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Text;

namespace Bees.Tempus
{
    public static class Tls
    {
        public const string Alpn = "tempus/1";
        public const string Version = "TLSv1.3";
        public const string Group = "X25519MLKEM768";
        public const string Suites = "TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256";
        /// <summary>
        /// How long a closing side keeps reading after it has ended its own sending, so that its last frame is not
        /// destroyed by a connection reset. The value is the Python extension's.
        /// </summary>
        public const int LingerMs = 500;

        /// <summary>A clock that only goes forward, in milliseconds.</summary>
        public static long NowMs() => Stopwatch.GetTimestamp() * 1000 / Stopwatch.Frequency;

        /// <summary>The address of "host:port" for a connection; null when the text is not one or the name does not resolve to IPv4.</summary>
        internal static IPEndPoint EndPoint(string text)
        {
            int at = text.LastIndexOf(':');
            if (at <= 0 || !int.TryParse(text.AsSpan(at + 1), out int port) || port < 0 || port > 65535) return null;
            string host = text.Substring(0, at);
            if (IPAddress.TryParse(host, out var ip)) return new IPEndPoint(ip, port);
            try
            {
                foreach (var a in Dns.GetHostAddresses(host)) if (a.AddressFamily == AddressFamily.InterNetwork) return new IPEndPoint(a, port);
            }
            catch (Exception) { }
            return null;
        }
    }

    /// <summary>An OpenSSL context with the tempus/1 profile and one identity's certificate and key.</summary>
    internal sealed unsafe class TlsContext
    {
        internal readonly IntPtr Ctx;
        readonly SigningKey key;        // kept so that the key outlives the context

        /// <summary>
        /// peerSignatures names the signature algorithms accepted from the peer. The client half accepts Ed25519 only.
        /// A node also lets a P-256 certificate through the handshake, as a BEES node does, so that it can refuse it
        /// afterwards with the audit event a BEES node writes for it (tempus_cert_key). strictAlpn makes a listener
        /// end the handshake with a fatal alert when the dialer does not offer tempus/1, as a BEES node does.
        /// </summary>
        internal TlsContext(bool server, Identity identity, string peerSignatures, bool strictAlpn)
        {
            OpenSsl.Require();
            key = identity.Key;
            IntPtr c = OpenSsl.SSL_CTX_new(server ? OpenSsl.TLS_server_method() : OpenSsl.TLS_client_method());
            if (c == IntPtr.Zero) throw new InvalidOperationException("no TLS context");
            IntPtr cert = identity.Certificate.ToX509();
            try
            {
                if (cert == IntPtr.Zero ||
                    OpenSsl.SSL_CTX_ctrl(c, OpenSsl.SSL_CTRL_SET_MIN_PROTO_VERSION, OpenSsl.TLS1_3_VERSION, IntPtr.Zero) != 1 ||
                    OpenSsl.SSL_CTX_ctrl(c, OpenSsl.SSL_CTRL_SET_MAX_PROTO_VERSION, OpenSsl.TLS1_3_VERSION, IntPtr.Zero) != 1 ||
                    OpenSsl.SSL_CTX_set_ciphersuites(c, Tls.Suites) != 1 ||
                    OpenSsl.SSL_CTX_ctrl(c, OpenSsl.SSL_CTRL_SET_GROUPS_LIST, 0, Tls.Group) != 1 ||
                    OpenSsl.SSL_CTX_ctrl(c, OpenSsl.SSL_CTRL_SET_SIGALGS_LIST, 0, peerSignatures) != 1 ||
                    OpenSsl.SSL_CTX_ctrl(c, OpenSsl.SSL_CTRL_SET_CLIENT_SIGALGS_LIST, 0, peerSignatures) != 1 ||
                    OpenSsl.SSL_CTX_use_certificate(c, cert) != 1 ||
                    OpenSsl.SSL_CTX_use_PrivateKey(c, key.Pkey) != 1 ||
                    OpenSsl.SSL_CTX_check_private_key(c) != 1)
                {
                    string why = OpenSsl.Reason();
                    OpenSsl.SSL_CTX_free(c);
                    throw new InvalidOperationException("the TLS context could not be set up: " + why);
                }
            }
            finally
            {
                if (cert != IntPtr.Zero) OpenSsl.X509_free(cert);
            }
            // no session is kept or resumed: every connection is a full handshake with both certificates
            OpenSsl.SSL_CTX_set_num_tickets(c, 0);
            OpenSsl.SSL_CTX_ctrl(c, OpenSsl.SSL_CTRL_SET_SESS_CACHE_MODE, 0, IntPtr.Zero);
            // the peer's certificate is required; its chain is not judged (see the text at the top of this file)
            OpenSsl.SSL_CTX_set_verify(c, OpenSsl.SSL_VERIFY_PEER | OpenSsl.SSL_VERIFY_FAIL_IF_NO_PEER_CERT, IntPtr.Zero);
            OpenSsl.SSL_CTX_set_cert_verify_callback(c, &OpenSsl.AcceptAnyChain, IntPtr.Zero);
            if (server)
            {
                OpenSsl.SSL_CTX_set_alpn_select_cb(c, &OpenSsl.AlpnSelect, strictAlpn ? (IntPtr)1 : IntPtr.Zero);
            }
            else
            {
                var name = Encoding.ASCII.GetBytes(Tls.Alpn);
                var protos = new byte[name.Length + 1];
                protos[0] = (byte)name.Length;
                Buffer.BlockCopy(name, 0, protos, 1, name.Length);
                if (OpenSsl.SSL_CTX_set_alpn_protos(c, protos, (uint)protos.Length) != 0)
                {
                    OpenSsl.SSL_CTX_free(c);
                    throw new InvalidOperationException("the ALPN protocol could not be set");
                }
            }
            Ctx = c;
        }

        ~TlsContext() { if (Ctx != IntPtr.Zero) OpenSsl.SSL_CTX_free(Ctx); }
    }

    /// <summary>How a read or a handshake ended when it gave no frame.</summary>
    internal enum Stop { None, Oversize, Closed, Timeout, TlsFailed }

    /// <summary>
    /// A TLS connection with ONE deadline for all of it. It is used by one thread at a time. Reads and writes answer
    /// with values, never with exceptions: nothing a peer does throws.
    /// </summary>
    internal sealed unsafe class Conn
    {
        readonly Socket socket;
        readonly TlsContext context;
        readonly IntPtr ssl, rbio, wbio;
        readonly long deadline;
        readonly byte[] buf = new byte[16384];
        int framesRead;
        bool open = true;
        /// <summary>The reason of the last Stop.TlsFailed, in OpenSSL's words.</summary>
        internal string Why = "";

        /// <summary>deadline is a value of Tls.NowMs(). The socket is connected; this object closes it.</summary>
        internal Conn(Socket socket, TlsContext context, bool client, long deadline)
        {
            this.socket = socket; this.context = context; this.deadline = deadline;
            socket.NoDelay = true;
            ssl = OpenSsl.SSL_new(context.Ctx);
            rbio = OpenSsl.BIO_new(OpenSsl.BIO_s_mem());
            wbio = OpenSsl.BIO_new(OpenSsl.BIO_s_mem());
            if (ssl == IntPtr.Zero || rbio == IntPtr.Zero || wbio == IntPtr.Zero) throw new InvalidOperationException("no TLS object");
            OpenSsl.SSL_set_bio(ssl, rbio, wbio);         // the TLS object owns both from here on
            if (client) OpenSsl.SSL_set_connect_state(ssl); else OpenSsl.SSL_set_accept_state(ssl);
        }

        // What the TLS engine wants sent goes to the peer. A failure is not reported here: the next read says what happened.
        void Flush()
        {
            while (OpenSsl.BIO_ctrl(wbio, OpenSsl.BIO_CTRL_PENDING, 0, IntPtr.Zero) > 0)
            {
                int n;
                fixed (byte* p = buf) n = OpenSsl.BIO_read(wbio, p, buf.Length);
                if (n <= 0) return;
                int sent = 0;
                try
                {
                    while (sent < n)
                    {
                        long left = deadline - Tls.NowMs();
                        if (left <= 0) return;
                        if (!socket.Poll(TimeSpan.FromMilliseconds(left), SelectMode.SelectWrite)) return;
                        sent += socket.Send(buf, sent, n - sent, SocketFlags.None);
                    }
                }
                catch (SocketException) { return; }
                catch (ObjectDisposedException) { return; }
            }
        }

        // Bytes of the peer for the TLS engine, waited for until `until`.
        Stop Feed(long until)
        {
            try
            {
                long left = until - Tls.NowMs();
                if (left <= 0 || !socket.Poll(TimeSpan.FromMilliseconds(left), SelectMode.SelectRead)) return Stop.Timeout;
                int n = socket.Receive(buf, 0, buf.Length, SocketFlags.None);
                if (n <= 0) return Stop.Closed;
                fixed (byte* p = buf) OpenSsl.BIO_write(rbio, p, n);
                return Stop.None;
            }
            catch (SocketException) { return Stop.Closed; }
            catch (ObjectDisposedException) { return Stop.Closed; }
        }

        delegate int Op();

        // Runs one TLS operation to its end: its result when positive, else why it stopped.
        int Run(Op op, out Stop stop)
        {
            while (true)
            {
                OpenSsl.ERR_clear_error();
                int r = op();
                int err = r > 0 ? 0 : OpenSsl.SSL_get_error(ssl, r);
                string why = err == OpenSsl.SSL_ERROR_SSL ? OpenSsl.Reason() : "";
                Flush();                                // also after a failure: an alert this side raised must reach the peer
                if (r > 0) { stop = Stop.None; return r; }
                switch (err)
                {
                    case OpenSsl.SSL_ERROR_WANT_READ:
                        stop = Feed(deadline);
                        if (stop != Stop.None) return r;
                        break;
                    case OpenSsl.SSL_ERROR_WANT_WRITE:
                        break;
                    case OpenSsl.SSL_ERROR_ZERO_RETURN:
                    case OpenSsl.SSL_ERROR_SYSCALL:
                        OpenSsl.ERR_clear_error();
                        stop = Stop.Closed;
                        return r;
                    default:
                        // an end of the stream without close_notify is a close, as a TCP reset is
                        if (why == "unexpected eof while reading") { stop = Stop.Closed; return r; }
                        Why = why;
                        stop = framesRead == 0 ? Stop.TlsFailed : Stop.Closed;
                        return r;
                }
            }
        }

        /// <summary>The handshake. Stop.None when it succeeded.</summary>
        internal Stop Handshake()
        {
            Run(() => OpenSsl.SSL_do_handshake(ssl), out Stop stop);
            return stop;
        }

        /// <summary>Hands the bytes to the transport. A failure is not reported here: the next read says what happened.</summary>
        internal void Send(byte[] data)
        {
            int sent = 0;
            fixed (byte* p = data)
            {
                while (sent < data.Length)
                {
                    byte* at = p + sent;
                    int count = data.Length - sent;
                    int n = Run(() => OpenSsl.SSL_write(ssl, at, count), out Stop stop);
                    if (stop != Stop.None) return;
                    sent += n;
                }
            }
        }

        bool Exact(byte[] data, out Stop stop)
        {
            int got = 0;
            stop = Stop.None;
            fixed (byte* p = data)
            {
                while (got < data.Length)
                {
                    byte* at = p + got;
                    int count = data.Length - got;
                    int n = Run(() => OpenSsl.SSL_read(ssl, at, count), out stop);
                    if (stop != Stop.None) return false;
                    got += n;
                }
            }
            return true;
        }

        /// <summary>The next frame's body, or null with why. A frame above the ceiling is refused from its length, before its body is read.</summary>
        internal byte[] Read(out Stop stop)
        {
            var head = new byte[4];
            if (!Exact(head, out stop)) return null;
            long size = ((long)head[0] << 24) | ((long)head[1] << 16) | ((long)head[2] << 8) | head[3];
            if (size > Etf.FrameMax) { stop = Stop.Oversize; return null; }
            var body = new byte[size];
            if (!Exact(body, out stop)) return null;
            framesRead += 1;
            return body;
        }

        internal string SelectedAlpn
        {
            get
            {
                OpenSsl.SSL_get0_alpn_selected(ssl, out IntPtr p, out uint n);
                return p == IntPtr.Zero || n == 0 ? null : Marshal.PtrToStringUTF8(p, (int)n);
            }
        }

        internal string TlsVersion => Marshal.PtrToStringUTF8(OpenSsl.SSL_get_version(ssl));

        internal string GroupName
        {
            get { IntPtr p = OpenSsl.SSL_get0_group_name(ssl); return p == IntPtr.Zero ? "" : Marshal.PtrToStringUTF8(p); }
        }

        internal string SuiteName
        {
            get
            {
                IntPtr c = OpenSsl.SSL_get_current_cipher(ssl);
                IntPtr p = c == IntPtr.Zero ? IntPtr.Zero : OpenSsl.SSL_CIPHER_get_name(c);
                return p == IntPtr.Zero ? "other-suite" : Marshal.PtrToStringUTF8(p);
            }
        }

        /// <summary>The certificate the peer presented; null when it presented none.</summary>
        internal Certificate PeerCertificate()
        {
            IntPtr x = OpenSsl.SSL_get1_peer_certificate(ssl);
            if (x == IntPtr.Zero) return null;
            try
            {
                var der = Certificate.DerOf(x);
                return der == null ? null : new Certificate(der);
            }
            catch (Refused) { return null; }
            finally { OpenSsl.X509_free(x); }
        }

        /// <summary>
        /// Close so that what was last written arrives: TLS close_notify, the TCP end of writing, then read to the
        /// peer's end for at most Tls.LingerMs. Closing with unread bytes can reset the connection, and a reset can
        /// destroy a frame the peer has not read yet.
        /// </summary>
        internal void Close()
        {
            if (!open) return;
            open = false;
            OpenSsl.ERR_clear_error();
            OpenSsl.SSL_shutdown(ssl);                  // writes close_notify; does not wait for the peer's
            OpenSsl.ERR_clear_error();
            Flush();
            try
            {
                socket.Shutdown(SocketShutdown.Send);
                long until = Math.Min(Tls.NowMs() + Tls.LingerMs, Math.Max(deadline, Tls.NowMs() + 1));
                var sink = new byte[4096];
                while (true)
                {
                    long left = until - Tls.NowMs();
                    if (left <= 0 || !socket.Poll(TimeSpan.FromMilliseconds(left), SelectMode.SelectRead)) break;
                    if (socket.Receive(sink, 0, sink.Length, SocketFlags.None) <= 0) break;
                }
            }
            catch (SocketException) { }
            catch (ObjectDisposedException) { }
            OpenSsl.SSL_free(ssl);
            try { socket.Close(); } catch (Exception) { }
            GC.KeepAlive(context);
        }
    }
}
