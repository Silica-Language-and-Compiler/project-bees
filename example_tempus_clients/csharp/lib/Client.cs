// EXAMPLE ONLY, not for production. See README.md in the directory above.
//
// The client half: an ordinary TEMPUS peer over TCP and mutual TLS 1.3, in both positions. Client.Dial connects, is
// admitted, sends ONE request and reads its reply. Listener accepts, is admitted, reads one request and answers it.
// What happened on a connection is an Outcome, a plain value; nothing a peer does throws.
//
// Each connection offers and accepts exactly: TLS 1.3; the key exchange group X25519MLKEM768; the cipher suites
// TLS_AES_256_GCM_SHA384 and TLS_CHACHA20_POLY1305_SHA256; the signature algorithm ed25519; the application protocol
// tempus/1; a certificate from both sides. No authority is consulted: after the handshake the peer's certificate must
// have an Ed25519 key and be self-signed, and admission then binds the certificate's key to the peer's advert, token
// and proof of possession.
using System;
using System.Collections.Generic;
using System.Linq;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;

namespace Bees.Tempus
{
    /// <summary>
    /// What happened on one connection.
    ///
    /// What    "reply"        dialing: the reply arrived and passed every check (Body, Bytes)
    ///         "served"       listening: the peer was admitted and its request read; Sent says what went back: "reply" or "close"
    ///         "key_rotated"  the peer answered this side's advert with key_rotated; Kid is the kid it named
    ///         "refused"      THIS side refused the peer or a frame of it; Reason says why ("key_rotated": this side sent that frame)
    ///         "closed"       the connection closed before the exchange was complete. This is all a refusal by the peer
    ///                        shows. It is also the ordinary end of a cast, which has no reply.
    ///         "timeout"      nothing came within the time allowed for the whole connection
    ///         "tls_failed"   no tempus/1 TLS connection: the handshake failed, or a TLS alert came before any frame
    ///         "unreachable"  dialing: no TCP connection
    /// Stage   where it ended: "tls", "advert", "challenge", "response", "request", "reply", "done"
    /// Advert  the peer's descriptor, once its advert was read (also when the peer was then refused)
    /// Typ     the type in the peer's token, once the advert verified
    /// </summary>
    public sealed class Outcome
    {
        public string What = "", Stage = "", Reason = "", Typ = "", Sent = "";
        public Body Body;
        public byte[] Bytes = Array.Empty<byte>();
        public Descriptor Advert;
        public byte[] Kid;

        public Outcome(string what, string stage, string reason = "") { What = what; Stage = stage; Reason = reason; }

        /// <summary>One line with nothing of the wall clock in it.</summary>
        public string Line()
        {
            var parts = new List<string> { What };
            if (What != "reply" && What != "served") parts.Add("at=" + Stage);
            switch (Body)
            {
                case Body.Entries b: parts.Add(b.Name + " entries=[" + string.Join(",", b.List.Select(e => e.Age + ":" + e.D.Id8())) + "] store=" + b.Store); break;
                case Body.Sample b: parts.Add("sample n=" + b.N + " store=" + b.Store); break;
                case Body.Result b: parts.Add("result req_id=" + Hex.Of(b.ReqId) + " value=" + Show(b.Value)); break;
                case null: break;
                default: parts.Add(Body.Kind); break;
            }
            if (Sent.Length > 0) parts.Add("sent=" + Sent);
            if (Kid != null) parts.Add("kid=" + Hex.Of(Kid));
            if (Advert != null) parts.Add("peer=" + Advert.Id8());
            if (Typ.Length > 0) parts.Add("typ=" + Typ);
            if (Reason.Length > 0) parts.Add("reason=\"" + Reason + "\"");
            return string.Join(" ", parts);
        }

        public override string ToString() => Line();

        public static string Show(Term t)
        {
            switch (t)
            {
                case TAtom a: return a.Name;
                case TInt i: return i.Value.ToString();
                case TBin b: return Hex.Of(b.Bytes);
                case TList l: return "[" + string.Join(",", l.Items.Select(Show)) + "]";
                case TMap m: return "{" + string.Join(",", m.Fields.OrderBy(f => f.Key, StringComparer.Ordinal).Select(f => f.Key + "=" + Show(f.Value))) + "}";
                default: return "?";
            }
        }
    }

    /// <summary>One request of a client.</summary>
    public abstract class Request
    {
        public abstract byte[] Body();

        /// <summary>Asks for up to n entries of the named store.</summary>
        public sealed class Sample : Request
        {
            public string Store; public int N;
            public Sample(string store, int n) { Store = store; N = n; }
            public override byte[] Body() => Frames.Sample(Store, N);
        }
        /// <summary>Offers entries of the named store and asks for some in return.</summary>
        public sealed class Shuffle : Request
        {
            public string Store; public IReadOnlyList<Entry> Entries;
            public Shuffle(string store, IReadOnlyList<Entry> entries) { Store = store; Entries = entries; }
            public override byte[] Body() => Frames.Shuffle(Store, Entries);
        }
        /// <summary>Asks a bridge to run a function and return its value.</summary>
        public sealed class Call : Request
        {
            public byte[] ReqId; public string Module, Function; public IReadOnlyList<Term> Args;
            public Call(byte[] reqId, string module, string function, IReadOnlyList<Term> args) { ReqId = reqId; Module = module; Function = function; Args = args; }
            public override byte[] Body() => Frames.RequestFrame("call", ReqId, Module, Function, Args);
        }
        /// <summary>Asks a bridge to run a function; there is no reply.</summary>
        public sealed class Cast : Request
        {
            public byte[] ReqId; public string Module, Function; public IReadOnlyList<Term> Args;
            public Cast(byte[] reqId, string module, string function, IReadOnlyList<Term> args) { ReqId = reqId; Module = module; Function = function; Args = args; }
            public override byte[] Body() => Frames.RequestFrame("cast", ReqId, Module, Function, Args);
        }
    }

    /// <summary>
    /// Settings every connection of a client needs. None has a default: the time bound for a whole connection and the
    /// shuffle length are properties of the network the client joins.
    /// </summary>
    public sealed class Settings
    {
        public long TimeoutMs { get; }
        public int ShuffleLength { get; }
        public Settings(long timeoutMs, int shuffleLength)
        {
            if (timeoutMs <= 0) throw new ArgumentException("the time bound of a connection is positive");
            if (shuffleLength < 1 || shuffleLength > Frames.EntriesMax) throw new ArgumentException("the shuffle length is 1 to 64");
            TimeoutMs = timeoutMs; ShuffleLength = shuffleLength;
        }
    }

    /// <summary>What a Listener's handler is given: the verified request of an admitted peer.</summary>
    public sealed class Incoming
    {
        public Body Body; public Descriptor Peer; public string Typ; public int Index;
    }

    public static class Client
    {
        // One connection's state for the Outcome.
        sealed class Link
        {
            public Conn Conn; public Descriptor Advert; public string Typ = "";

            public Outcome End(string what, string stage, string reason = "", Body body = null, byte[] bytes = null, byte[] kid = null, string sent = "")
            {
                Conn.Close();
                return new Outcome(what, stage, reason) { Body = body, Bytes = bytes ?? Array.Empty<byte>(), Advert = Advert, Typ = Typ, Kid = kid, Sent = sent };
            }

            public Outcome End(Stop stop, string stage)
            {
                switch (stop)
                {
                    case Stop.Oversize: return End("refused", stage, "a frame above the ceiling");
                    case Stop.Timeout: return End("timeout", stage);
                    case Stop.TlsFailed: return End("tls_failed", stage, Conn.Why);
                    default: return End("closed", stage);
                }
            }
        }

        // The next frame, which must be one of the kinds wanted: the body, or the Outcome that ended the connection.
        static Body Next(Link link, string stage, int shuffleLength, out Outcome ended, params string[] want)
        {
            ended = null;
            var bytes = link.Conn.Read(out Stop stop);
            if (bytes == null) { ended = link.End(stop, stage); return null; }
            Body body;
            try { body = Frames.ReadBody(bytes, shuffleLength); }
            catch (Refused e) { ended = link.End("refused", stage, e.Why, bytes: bytes); return null; }
            if (!want.Contains(body.Kind)) { ended = link.End("refused", stage, body.Kind + " where " + string.Join(" or ", want) + " was due", bytes: bytes); return null; }
            return body;
        }

        /// After the handshake: what was negotiated, and the peer's certificate. Refused(reason) otherwise.
        static Certificate TlsChecks(Conn conn)
        {
            if (conn.TlsVersion != Tls.Version) throw new Refused("the TLS version is not 1.3");
            if (!Tls.Suites.Split(':').Contains(conn.SuiteName)) throw new Refused("the cipher suite is not one of tempus/1");
            if (!string.Equals(conn.GroupName, Tls.Group, StringComparison.OrdinalIgnoreCase)) throw new Refused("the key exchange group is not X25519MLKEM768");
            if (conn.SelectedAlpn != Tls.Alpn) throw new Refused("the ALPN protocol is not tempus/1");
            var cert = conn.PeerCertificate();
            if (cert == null) throw new Refused("the peer presented no certificate");
            cert.TempusKey();
            return cert;
        }

        // Admission, the same at both ends (design sections 4 and 5): this side's advert at once; the peer's advert,
        // checked; this side's challenge; the peer's challenge, answered; the peer's response, verified. null when both
        // directions passed, else the Outcome.
        static Outcome Admit(Link link, Identity me, Verifier verifier, Certificate certificate, int shuffleLength)
        {
            var conn = link.Conn;
            var nonce = Crypto.RandomBytes(32);
            if (nonce == null) return link.End("closed", "advert", "internal error: no random bytes");
            conn.Send(Frames.Frame(Frames.Advert(me.Descriptor())));
            var first = Next(link, "advert", shuffleLength, out Outcome ended, "advert");
            if (first == null) return ended;
            var theirs = ((Body.Advert)first).D;
            link.Advert = theirs;
            try { link.Typ = verifier.CheckPeer(theirs, certificate).Typ; }
            catch (Refused e)
            {
                // the one exception to silence: a token under another kid is answered with one key_rotated frame, then the close
                if (e.Why == "key_rotated") conn.Send(Frames.Frame(Frames.KeyRotated(verifier.Kid)));
                return link.End("refused", "advert", e.Why);
            }
            conn.Send(Frames.Frame(Frames.Challenge(nonce)));
            var second = Next(link, "challenge", shuffleLength, out ended, "pop_challenge", "key_rotated");
            if (second == null) return ended;
            if (second is Body.KeyRotated kr) return link.End("key_rotated", "challenge", kid: kr.Kid);
            conn.Send(Frames.Frame(Frames.Response(me.Prove(((Body.Challenge)second).Nonce))));
            var third = Next(link, "response", shuffleLength, out ended, "pop_response");
            if (third == null) return ended;
            try { verifier.CheckProof(theirs.Pub, nonce, theirs.Token, ((Body.Response)third).Sig); }
            catch (Refused e) { return link.End("refused", "response", e.Why); }
            return null;
        }

        static void CheckEntries(Body b, string kind, string store, int most, Verifier verifier)
        {
            if (!(b is Body.Entries e) || e.Name != kind) throw new Refused(b.Kind + " where " + kind + " was due");
            if (e.Store != store) throw new Refused("the reply names another store");
            if (e.List.Count > most) throw new Refused("more entries than were asked for");
            for (int i = 0; i < e.List.Count; i++)
            {
                // one entry that does not verify refuses the whole frame: nothing of it may be used
                try { verifier.CheckEntry(e.List[i].D, store); }
                catch (Refused why) { throw new Refused("entry " + i + " does not verify: " + why.Why); }
            }
        }

        static void CheckReply(Request request, Body b, Verifier verifier)
        {
            switch (request)
            {
                case Request.Sample s: CheckEntries(b, "sample_reply", s.Store, s.N, verifier); break;
                case Request.Shuffle s: CheckEntries(b, "shuffle_reply", s.Store, Frames.EntriesMax, verifier); break;
                case Request.Call c:
                    if (!(b is Body.Result r)) throw new Refused(b.Kind + " where result was due");
                    if (!r.ReqId.AsSpan().SequenceEqual(c.ReqId)) throw new Refused("the result names another req_id");
                    break;
                default: throw new Refused(b.Kind + " where no reply was due");
            }
        }

        /// <summary>A connected socket, or null with what ("unreachable" or "timeout").</summary>
        internal static Socket Connect(IPEndPoint ep, long deadline, out string what)
        {
            what = "unreachable";
            if (ep == null) return null;
            var socket = new Socket(ep.AddressFamily, SocketType.Stream, ProtocolType.Tcp);
            try
            {
                var task = socket.ConnectAsync(ep);
                long left = deadline - Tls.NowMs();
                bool done;
                try { done = left > 0 && task.Wait(TimeSpan.FromMilliseconds(left)); }
                catch (AggregateException) { socket.Close(); return null; }
                if (!done) { what = "timeout"; socket.Close(); return null; }
                return socket;
            }
            catch (Exception) { try { socket.Close(); } catch (Exception) { } return null; }
        }

        /// <summary>
        /// Connect to the TEMPUS peer at "host:port", be admitted, send ONE request and read its reply. The reply must
        /// be the one the request calls for: a sample_reply or shuffle_reply for the same store, whose every entry
        /// verifies for that store, or a result with the request's req_id. A cast has no reply: its ordinary end is
        /// "closed" at stage "reply". ArgumentException for a request this client cannot make; nothing is sent then.
        /// </summary>
        public static Outcome Dial(string addr, Identity me, Verifier verifier, Request request, Settings settings)
        {
            // built before anything is sent: a request this client cannot make is the caller's fault
            if (request is Request.Sample rs && (rs.N < 1 || rs.N > settings.ShuffleLength)) throw new ArgumentException("n is 1 to the shuffle length");
            if (request is Request.Shuffle rsh && rsh.Entries.Count > settings.ShuffleLength) throw new ArgumentException("more entries than the shuffle length");
            var requestBody = request.Body();
            var context = new TlsContext(false, me, "ed25519", false);
            long deadline = Tls.NowMs() + settings.TimeoutMs;
            var socket = Connect(Tls.EndPoint(addr), deadline, out string what);
            if (socket == null) return new Outcome(what, "tls");
            var link = new Link { Conn = new Conn(socket, context, true, deadline) };
            var conn = link.Conn;
            var stop = conn.Handshake();
            if (stop != Stop.None)
            {
                string why = conn.Why;
                conn.Close();
                if (stop == Stop.Timeout) return new Outcome("timeout", "tls");
                return new Outcome("tls_failed", "tls", stop == Stop.TlsFailed ? why : "closed during the handshake");
            }
            Certificate certificate;
            try { certificate = TlsChecks(conn); }
            catch (Refused e) { return link.End("refused", "tls", e.Why); }
            // In TLS 1.3 a dialer's handshake ends before the listener has judged the dialer's certificate: a listener's
            // TLS refusal shows as an alert on the first read, reported as tls_failed at "advert".
            var ended = Admit(link, me, verifier, certificate, settings.ShuffleLength);
            if (ended != null) return ended;
            // a call or a cast goes to a bridge only: a peer admitted with a bridge token, which the whitelist rule ties
            // to a certificate of this client's tempus whitelist
            if ((request is Request.Call || request is Request.Cast) && link.Typ != "tempus_bridge") return link.End("refused", "request", "the peer is not a bridge");
            conn.Send(Frames.Frame(requestBody));
            var bytes = conn.Read(out stop);
            if (bytes == null) return link.End(stop, "reply");
            Body body;
            try
            {
                body = Frames.ReadBody(bytes, settings.ShuffleLength);
                CheckReply(request, body, verifier);
            }
            catch (Refused e) { return link.End("refused", "reply", e.Why, bytes: bytes); }
            return link.End("reply", "done", body: body, bytes: bytes);
        }

        // One accepted connection of a Listener.
        internal static Outcome Serve(Socket socket, TlsContext context, Identity identity, Verifier verifier, Settings settings,
                                      Func<Incoming, IReadOnlyList<Entry>> handler, int index)
        {
            long deadline = Tls.NowMs() + settings.TimeoutMs;
            var link = new Link { Conn = new Conn(socket, context, false, deadline) };
            var conn = link.Conn;
            var stop = conn.Handshake();
            if (stop != Stop.None)
            {
                string why = conn.Why;
                conn.Close();
                if (stop == Stop.Timeout) return new Outcome("timeout", "tls");
                if (stop == Stop.TlsFailed && why.Contains("peer did not return a certificate")) return new Outcome("refused", "tls", "the peer presented no certificate");
                return new Outcome("tls_failed", "tls", stop == Stop.TlsFailed ? why : "closed during the handshake");
            }
            Certificate certificate;
            try { certificate = TlsChecks(conn); }
            catch (Refused e) { return link.End("refused", "tls", e.Why); }
            var ended = Admit(link, identity, verifier, certificate, settings.ShuffleLength);
            if (ended != null) return ended;
            var bytes = conn.Read(out stop);
            if (bytes == null) return link.End(stop, "request");
            Body body;
            try
            {
                body = Frames.ReadBody(bytes, settings.ShuffleLength);
                if (body is Body.Entries b)
                {
                    if (b.Name != "shuffle") throw new Refused(b.Name + " where a request was due");
                    for (int i = 0; i < b.List.Count; i++)
                    {
                        try { verifier.CheckEntry(b.List[i].D, b.Store); }
                        catch (Refused why) { throw new Refused("entry " + i + " does not verify: " + why.Why); }
                    }
                }
                else if (!(body is Body.Sample)) throw new Refused(body.Kind + " where a request was due");
            }
            catch (Refused e) { return link.End("refused", "request", e.Why, bytes: bytes); }
            var answer = handler(new Incoming { Body = body, Peer = link.Advert, Typ = link.Typ, Index = index });
            if (answer == null) return link.End("served", "done", body: body, bytes: bytes, sent: "close");
            byte[] reply;
            if (body is Body.Sample s)
            {
                if (answer.Count > s.N) throw new ArgumentException("the handler answered a sample with more entries than were asked for");
                reply = Frames.SampleReply(s.Store, answer);
            }
            else
            {
                if (answer.Count > settings.ShuffleLength) throw new ArgumentException("the handler answered with more entries than the shuffle length");
                reply = Frames.ShuffleReply(((Body.Entries)body).Store, answer);
            }
            conn.Send(Frames.Frame(reply));
            return link.End("served", "done", body: body, bytes: bytes, sent: "reply");
        }
    }

    /// <summary>
    /// The listening position: a thread accepts connections on host:port, and each connection, on a thread of its own,
    /// is admitted and has ONE request read. A shuffle (every entry verified for its store first) and a sample are
    /// given to the handler, which returns the entries of the reply, or null to close with no reply. Any other request
    /// is closed with no reply. Every connection ends as one Outcome, kept in accept order.
    /// </summary>
    public sealed class Listener : IDisposable
    {
        readonly Identity identity; readonly Verifier verifier; readonly Settings settings;
        readonly Func<Incoming, IReadOnlyList<Entry>> handler;
        readonly Socket server;
        readonly TlsContext context;
        readonly Dictionary<int, Outcome> done = new Dictionary<int, Outcome>();
        readonly List<Thread> threads = new List<Thread>();
        readonly Thread acceptor;
        volatile bool stopping;
        /// <summary>The address listened on, as host:port with the port the system gave when 0 was asked for.</summary>
        public string Address { get; }

        public Listener(Identity identity, Verifier verifier, Settings settings, string host, int port, Func<Incoming, IReadOnlyList<Entry>> handler)
        {
            this.identity = identity; this.verifier = verifier; this.settings = settings; this.handler = handler;
            context = new TlsContext(true, identity, "ed25519", false);
            var ep = Tls.EndPoint(host + ":" + port) ?? throw new ArgumentException("the listen address cannot be used");
            server = new Socket(ep.AddressFamily, SocketType.Stream, ProtocolType.Tcp);
            server.SetSocketOption(SocketOptionLevel.Socket, SocketOptionName.ReuseAddress, true);
            server.Bind(ep);
            server.Listen(64);
            Address = host + ":" + ((IPEndPoint)server.LocalEndPoint).Port;
            acceptor = new Thread(Accept) { IsBackground = true, Name = "tempus-listener" };
            acceptor.Start();
        }

        void Accept()
        {
            int index = 0;
            while (!stopping)
            {
                Socket raw;
                try
                {
                    if (!server.Poll(TimeSpan.FromMilliseconds(50), SelectMode.SelectRead)) continue;
                    raw = server.Accept();
                }
                catch (Exception) { break; }
                int i = index++;
                var t = new Thread(() =>
                {
                    Outcome o;
                    try { o = Client.Serve(raw, context, identity, verifier, settings, handler, i); }
                    catch (Exception e)       // a fault of this program or of the handler, never the peer's doing: say so
                    {
                        try { raw.Close(); } catch (Exception) { }
                        o = new Outcome("closed", "tls", "internal error: " + e.GetType().Name + ": " + e.Message);
                    }
                    lock (done) { done[i] = o; Monitor.PulseAll(done); }
                }) { IsBackground = true, Name = "tempus-listener-" + i };
                lock (threads) threads.Add(t);
                t.Start();
            }
        }

        /// <summary>
        /// The Outcomes of the first count connections in accept order, waiting up to waitMs for them (fewer when they
        /// did not all end in time).
        /// </summary>
        public IReadOnlyList<Outcome> Outcomes(int count, long waitMs)
        {
            long until = Tls.NowMs() + waitMs;
            lock (done)
            {
                while (!Enumerable.Range(0, count).All(done.ContainsKey))
                {
                    long left = until - Tls.NowMs();
                    if (left <= 0) break;
                    Monitor.Wait(done, (int)left);
                }
                return done.Keys.Where(k => k < count).OrderBy(k => k).Select(k => done[k]).ToList();
            }
        }

        /// <summary>Stops accepting and waits for the connections in hand to end (each is bounded by the settings' time bound).</summary>
        public void Dispose()
        {
            stopping = true;
            acceptor.Join();
            List<Thread> all;
            lock (threads) all = new List<Thread>(threads);
            foreach (var t in all) t.Join();
            try { server.Close(); } catch (Exception) { }
        }
    }
}
