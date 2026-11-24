// A usable example, to be used carefully. See README.md in the directory above.
//
// A TEMPUS node: an edge or a sentinel (never a bridge, which is also a TRUST node). It does what the Silica node of
// src/tempus does (development-plan/tempus-design.md sections 3 to 6 and 8 to 11): it reads the clock, listens, joins
// through its sentinels, ticks its three stores on their timers, starts shuffles and answers shuffles and samples,
// admits peers with every check of section 4, and tells its application what the Silica node tells its own. The
// lines it writes are the Silica node's lines, word for word, so an operator can compare the two.
//
// Who owns what. All of the node's state (the three stores, the clock state, the node's token and producer key, the
// counts of connections, the join) belongs to ONE thread, the node thread, which takes one action after another from
// a queue that only it reads. Everything else puts an action on that queue: the timers, the acceptor, each
// connection, and the application's calls. A connection runs on a thread of its own (NodeConn.cs) with a copy of the
// values it needs, taken on the node thread when the connection begins; it never touches a store. The application's
// listener is called on the node thread, in order.
//
// The clock, the timers, the draws and the nonces come from a NodeEnvironment. NodeEnvironment.System() is the
// machine's clock, real timers and the system's secure random source: an application passes nothing else. A test
// passes its own. No frame a peer can send sets the clock or causes a tick.
using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Linq;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using System.Threading.Tasks;

namespace Bees.Tempus
{
    /// <summary>What a node tells its application.</summary>
    public abstract class NodeEvent
    {
        /// <summary>The node's own token is not valid any more and ticking has stopped, until the application passes a new one.</summary>
        public sealed class OwnTokenInvalid : NodeEvent { public string Why; }
        /// <summary>
        /// A peer answered this node's advert with key_rotated; Kid is the kid it named. The application fetches a new
        /// token. Dialed says whether this node had dialed the peer (true) or the peer had dialed this node (false).
        /// </summary>
        public sealed class KeyRotated : NodeEvent { public byte[] Kid; public bool Dialed; }
        /// <summary>The system clock could not be read; What says what that means for the node. Told once per failure.</summary>
        public sealed class ClockUnreadable : NodeEvent { public string What; }
        /// <summary>The node has stopped for good after its clock went back by more than clock_back_limit_s. Only a new node ends this.</summary>
        public sealed class Stopped : NodeEvent { public string Why; }
        /// <summary>The node could not listen on its address.</summary>
        public sealed class ListenFailed : NodeEvent { public string Why; }
        /// <summary>The view of one store after a step that may have changed it, in the view's order.</summary>
        public sealed class ViewChanged : NodeEvent { public string Store; public IReadOnlyList<Entry> Entries; }
    }

    /// <summary>Runs an action once, later. name says what the timer is for: "clock", "tick tempus_edge", "join tempus_edge".</summary>
    public interface INodeTimers
    {
        void After(long ms, string name, Action action);
    }

    /// <summary>The draws of one choice of one store: count numbers, each 0 or more; null when the random source gave none.</summary>
    public interface IDrawSource
    {
        IReadOnlyList<long> Draws(string store, int count);
    }

    /// <summary>Real timers.</summary>
    public sealed class SystemTimers : INodeTimers, IDisposable
    {
        readonly HashSet<Timer> pending = new HashSet<Timer>();
        bool closed;

        public void After(long ms, string name, Action action)
        {
            lock (pending)
            {
                if (closed) return;
                Timer t = null;
                t = new Timer(_ =>
                {
                    lock (pending) { if (closed) return; pending.Remove(t); }
                    t.Dispose();
                    action();
                }, null, Timeout.Infinite, Timeout.Infinite);
                pending.Add(t);
                t.Change(ms, Timeout.Infinite);
            }
        }

        public void Dispose()
        {
            lock (pending)
            {
                closed = true;
                foreach (var t in pending) t.Dispose();
                pending.Clear();
            }
        }
    }

    /// <summary>Draws from the system's secure random source, seven bytes each (design 3.5).</summary>
    public sealed class SecureDraws : IDrawSource
    {
        public IReadOnlyList<long> Draws(string store, int count)
        {
            var raw = Crypto.RandomBytes(7 * count);
            if (raw == null) return null;
            var o = new long[count];
            for (int i = 0; i < count; i++)
            {
                long v = 0;
                for (int k = 0; k < 7; k++) v = (v << 8) | raw[7 * i + k];
                o[i] = v;
            }
            return o;
        }
    }

    /// <summary>
    /// Where a node takes the time, its timers, its draws and its nonces, and where its lines go. System() is what an
    /// application uses. The constructor is for a test, which supplies its own clock, timers and draws.
    /// </summary>
    public sealed class NodeEnvironment
    {
        /// <summary>Whole seconds since 1970 UTC, or null when the clock could not be read.</summary>
        public Func<long?> Clock { get; }
        public INodeTimers Timers { get; }
        public IDrawSource Draws { get; }
        /// <summary>32 fresh random bytes for one challenge, or null when the random source gave none.</summary>
        public Func<byte[]> Nonce { get; }
        public Action<string> Log { get; }

        public NodeEnvironment(Func<long?> clock, INodeTimers timers, IDrawSource draws, Func<byte[]> nonce, Action<string> log)
        {
            Clock = clock; Timers = timers; Draws = draws; Nonce = nonce; Log = log;
        }

        /// <summary>The machine's clock, real timers, the system's secure random source. log null: lines go to the standard output.</summary>
        public static NodeEnvironment System(Action<string> log = null) =>
            new NodeEnvironment(Bees.Tempus.Clock.SystemSeconds, new SystemTimers(), new SecureDraws(), () => Crypto.RandomBytes(32), log ?? Console.WriteLine);
    }

    /// <summary>The values one connection needs, copied on the node thread when the connection begins.</summary>
    internal sealed class ConnValues
    {
        public Identity Me; public byte[] Kid, ProducerKey; public long Now, Skew; public IReadOnlyList<string> Whitelist; public int Count; public long Deadline;
    }

    /// <summary>An admitted peer's request, handed to the node thread, which sets the answer: the reply body, or null to close.</summary>
    internal sealed class PeerRequest
    {
        public int Cid; public string Kind; public Body Body; public string Why = ""; public Descriptor Peer; public string Typ;
        public readonly TaskCompletionSource<byte[]> Answer = new TaskCompletionSource<byte[]>(TaskCreationOptions.RunContinuationsAsynchronously);
    }

    /// <summary>How a connection the node dialed ended.</summary>
    internal sealed class Dialed
    {
        public Body Reply; public bool Replied; public Descriptor Peer; public string Typ; public string Failed; public byte[] RotatedKid;
    }

    public sealed class TempusNode : IDisposable
    {
        /// <summary>
        /// Starts a node. ConfigRefused when the configuration or the identity is refused: the line "tempus: boot
        /// refused: WHY" is written and nothing is started. The node reads its clock at once and listens when the
        /// first reading has come. listener is called on the node's own thread, in order; it must return soon and may
        /// call the node's methods. environment null: NodeEnvironment.System().
        /// </summary>
        public static TempusNode Start(TempusConfig config, Identity identity, Action<TempusNode, NodeEvent> listener, NodeEnvironment environment = null)
        {
            var env = environment ?? NodeEnvironment.System();
            string why = config.StartRefusal(identity);
            if (why != null)
            {
                env.Log("tempus: boot refused: " + why);
                (env.Timers as IDisposable)?.Dispose();
                throw new ConfigRefused(why);
            }
            var node = new TempusNode(config, identity, listener, env);
            node.Post(node.ReadClock);
            return node;
        }

        static readonly IReadOnlyList<string> Types = Frames.PeerTypes;
        readonly TempusConfig config;
        readonly Action<TempusNode, NodeEvent> listener;
        readonly NodeEnvironment env;
        readonly BlockingCollection<Action> queue = new BlockingCollection<Action>();
        readonly Thread thread;
        readonly List<string> whitelist;
        readonly List<string> sentinels;
        readonly string myId;
        readonly object logLock = new object();
        internal readonly TlsContext ServerContext, ClientContext;

        // ---- the node's state: read and written on the node thread only
        Identity me;
        byte[] kid, producerKey;
        readonly Dictionary<string, Store<Descriptor>> stores = new Dictionary<string, Store<Descriptor>>();
        long now;
        int ck = ClockState.NoReading;
        int live;                       // accepted connections in hand
        int accepted;                   // the number of the last accepted connection
        int dialed;                     // the number of the last dialed connection
        bool tokenStop;                 // ticking has stopped for the node's own token
        int joinStore;                  // 0 not begun; 1 to 3 the store the join is at; 4 done; 10 + store: it waits for the clock
        long joinDelay;
        readonly HashSet<string> joinInFlight = new HashSet<string>();
        Socket server;
        volatile bool closed;

        TempusNode(TempusConfig config, Identity identity, Action<TempusNode, NodeEvent> listener, NodeEnvironment env)
        {
            this.config = config; this.listener = listener; this.env = env;
            me = identity; kid = config.ProducerKid; producerKey = config.ProducerKey;
            whitelist = (config.Whitelist ?? Array.Empty<KeyValuePair<string, Certificate>>()).Select(w => w.Value.Fingerprint).ToList();
            sentinels = (config.Sentinels ?? Array.Empty<SentinelAddress>()).Select(s => s.Address).ToList();
            myId = Hex.Of(identity.PeerId);
            joinDelay = config.JoinRetryInitialMs;
            foreach (var t in Types) stores[t] = new Store<Descriptor>(myId, identity.Descriptor(), t == config.Typ, config.Store(t).Capacity, config.Store(t).ShuffleLength);
            // A node lets a P-256 certificate through the handshake, as a BEES node does, and refuses it afterwards (tempus_cert_key).
            ServerContext = new TlsContext(true, identity, "ed25519:ecdsa_secp256r1_sha256", true);
            ClientContext = new TlsContext(false, identity, "ed25519:ecdsa_secp256r1_sha256", false);
            thread = new Thread(Run) { IsBackground = true, Name = "tempus-node" };
            thread.Start();
        }

        void Run()
        {
            foreach (var action in queue.GetConsumingEnumerable())
            {
                if (closed) continue;
                try { action(); } catch (Exception e) { Say("internal error: " + e.GetType().Name + ": " + e.Message); }
            }
        }

        internal void Post(Action action)
        {
            try { queue.Add(action); } catch (InvalidOperationException) { }
        }

        internal void Say(string line) { lock (logLock) env.Log(line); }

        void Tell(NodeEvent e)
        {
            if (listener == null) return;
            try { listener(this, e); } catch (Exception x) { Say("internal error: the application's listener failed: " + x.GetType().Name + ": " + x.Message); }
        }

        internal bool IsClosed => closed;

        internal byte[] Nonce() { try { return env.Nonce(); } catch (Exception) { return null; } }

        // ---------------------------------------------------------------- what the application may call
        /// <summary>
        /// A new token from the producer. The node's own entry carries it from the next shuffle on, and ticking starts
        /// again. As in the Silica node, the token is not judged here: one that is not valid shows at the next tick.
        /// </summary>
        public void SetToken(byte[] token)
        {
            if (token == null || token.Length < 65 || token.Length > 1024) throw new ArgumentException("a token is 65 to 1024 bytes");
            var copy = (byte[])token.Clone();
            Post(() =>
            {
                me = me.WithToken(copy);
                tokenStop = false;
                Say("own token replaced");
                foreach (var s in stores.Values) s.SelfD = me.Descriptor();
            });
        }

        /// <summary>A new producer key (ruling NQ-5): its kid and the 32 raw bytes of the key.</summary>
        public void SetProducerKey(byte[] newKid, byte[] key)
        {
            if (newKid == null || key == null || newKid.Length < 1 || newKid.Length > 64 || key.Length != 32)
                throw new ArgumentException("a producer key is a kid of 1 to 64 bytes and a 32-byte key");
            var k = (byte[])newKid.Clone(); var p = (byte[])key.Clone();
            Post(() =>
            {
                kid = k; producerKey = p;
                Say("producer key replaced, kid " + Encoding.UTF8.GetString(k));
            });
        }

        /// <summary>
        /// Up to n entries of one of the node's stores, drawn at random (at most the store's shuffle length): how an
        /// application finds a bridge to call. The view is not changed. An empty list when there is none.
        /// </summary>
        public Task<IReadOnlyList<Entry>> Sample(string store, int n)
        {
            if (!Types.Contains(store)) throw new ArgumentException("a store is one of tempus_edge, tempus_bridge, tempus_sentinel");
            var o = new TaskCompletionSource<IReadOnlyList<Entry>>(TaskCreationOptions.RunContinuationsAsynchronously);
            Post(() =>
            {
                var s = stores[store];
                Refill(store);
                var got = s.Sample(n);
                Refill(store);
                o.SetResult(got == null ? new List<Entry>() : got.Select(e => new Entry(e.Age, e.Value)).ToList());
            });
            return o.Task;
        }

        /// <summary>The whole view of one store, in the view's order.</summary>
        public Task<IReadOnlyList<Entry>> ViewOf(string store)
        {
            if (!Types.Contains(store)) throw new ArgumentException("a store is one of tempus_edge, tempus_bridge, tempus_sentinel");
            var o = new TaskCompletionSource<IReadOnlyList<Entry>>(TaskCreationOptions.RunContinuationsAsynchronously);
            Post(() => o.SetResult(stores[store].Entries.Select(e => new Entry(e.Age, e.Value)).ToList()));
            return o.Task;
        }

        /// <summary>Stops the node: it listens no more, its timers do nothing more, and connections in hand end by their bound.</summary>
        public void Dispose()
        {
            if (closed) return;
            closed = true;
            try { server?.Close(); } catch (Exception) { }
            (env.Timers as IDisposable)?.Dispose();
            queue.CompleteAdding();
        }

        // ---------------------------------------------------------------- the stores
        void Refill(string typ)
        {
            var s = stores[typ];
            if (s.TickDraws == null) s.TickDraws = env.Draws.Draws(typ, s.Count + 1);
            if (s.ReplyDraws == null) s.ReplyDraws = env.Draws.Draws(typ, s.Count + 1);
        }

        static Held<Descriptor> HeldOf(Entry e) => new Held<Descriptor>(Hex.Of(e.D.Id), e.D, e.Age);

        void Show(string typ) => Tell(new NodeEvent.ViewChanged { Store = typ, Entries = stores[typ].Entries.Select(e => new Entry(e.Age, e.Value)).ToList() });

        ConnValues Values(int count, long startMs) => new ConnValues
        {
            Me = me, Kid = kid, ProducerKey = producerKey, Now = now, Skew = config.SkewSeconds, Whitelist = whitelist, Count = count,
            Deadline = startMs + config.ShuffleTimeoutMs
        };

        int MaxCount() => Types.Max(t => config.Store(t).ShuffleLength);

        static string Peer8(byte[] id) => Hex.Of(id, 4);

        // ---------------------------------------------------------------- the clock
        void ReadClock()
        {
            long? n;
            try { n = env.Clock(); } catch (Exception) { n = null; }
            env.Timers.After(config.ClockReadMs, "clock", () => Post(ReadClock));
            Reading(n);
        }

        void Reading(long? n)
        {
            long limit = config.ClockBackLimitS ?? 0;
            var t = Bees.Tempus.Clock.Turn(ck, now, n, config.ClockBack, limit, config.ClockFail);
            if (t.Again) Say("clock: the system clock is read again");
            string back = "the system clock went back by " + (now - (n ?? 0)) + " s";
            string stop = back + ", more than clock_back_limit_s " + limit + ": the node has stopped; it admits no connection and does not tick until its application starts it again";
            void Unreadable(string what) { Say("clock: " + what); Tell(new NodeEvent.ClockUnreadable { What = what }); }
            bool listen = false;
            switch (t.Say)
            {
                case ClockSay.First: Say("clock: the system clock is read"); listen = true; break;
                case ClockSay.NoneAtStart: Unreadable("the system clock could not be read: the node has not started"); break;
                case ClockSay.FailedPause: Unreadable("the system clock could not be read: the node admits no connection and does not tick until it is read again"); break;
                case ClockSay.FailedContinue: Unreadable("the system clock could not be read: the node goes on with its last reading"); break;
                case ClockSay.BackFollowed: Say("clock: " + back + "; the node follows it"); break;
                case ClockSay.BackHeld: Say("clock: " + back + "; the node holds its time until the system clock has reached it"); break;
                case ClockSay.HoldEnded: Say("clock: the system clock has reached the held time; the node follows it again"); break;
                case ClockSay.BackStop: Say("clock: " + stop); Tell(new NodeEvent.Stopped { Why = stop }); break;
            }
            now = t.Now; ck = t.Ck;
            if (listen) Listen();
            // the join request that waited for the clock is made at once when the clock is read again (ruling 1.d)
            if (t.Again && joinStore > 10) { joinStore -= 10; Join(Types[joinStore - 1], 0, true); }
        }

        // ---------------------------------------------------------------- listening
        void Listen()
        {
            Socket s = null;
            try
            {
                var ep = Tls.EndPoint(config.ListenAddress + ":" + config.Port) ?? throw new SocketException((int)SocketError.HostNotFound);
                s = new Socket(ep.AddressFamily, SocketType.Stream, ProtocolType.Tcp);
                s.SetSocketOption(SocketOptionLevel.Socket, SocketOptionName.ReuseAddress, true);
                s.Bind(ep);
                s.Listen(64);
            }
            catch (Exception e)
            {
                try { s?.Close(); } catch (Exception) { }
                Say("the listening link has gone down");
                Tell(new NodeEvent.ListenFailed { Why = e.Message });
                return;
            }
            server = s;
            new Thread(() =>
            {
                while (!closed)
                {
                    Socket raw;
                    try { raw = s.Accept(); } catch (Exception) { break; }
                    long at = Tls.NowMs();
                    Post(() => OnAccepted(raw, at));
                }
                if (!closed) Post(() => { Say("the listening link has gone down"); Tell(new NodeEvent.ListenFailed { Why = "the listener closed" }); });
            }) { IsBackground = true, Name = "tempus-accept" }.Start();
            Say(config.Typ + " node " + Peer8(me.PeerId) + " listening on " + me.Addr);
            foreach (var t in Types) Say("store " + t + ": capacity " + config.Store(t).Capacity + ", shuffle length " + config.Store(t).ShuffleLength);
            foreach (var t in Types) Refill(t);
            foreach (var t in Types) ArmTick(t);
            if (sentinels.Count == 0) { Say("join: no sentinel is configured"); joinStore = 4; }
            else { joinStore = 1; Join(Types[0], 0, true); }
        }

        // The decision is made here, at the accept: the clock's state first, then the inflight limit. A connection that
        // is closed for either reason still has its TLS handshake completed, and does not count as served.
        void OnAccepted(Socket raw, long at)
        {
            accepted += 1;
            int cid = accepted;
            string role = ClockState.Closes(ck) ?? (live >= config.InflightMax ? "inflight_refused" : null);
            if (role == null) live += 1;
            var v = Values(MaxCount(), at);
            Action release = role == null ? () => Post(() => live -= 1) : (Action)(() => { });
            new Thread(() =>
            {
                try { new NodeConn(this, v, "a" + cid).Accepted(raw, role, cid, release); }
                catch (Exception e)
                {
                    Say("internal error: connection a" + cid + ": " + e.GetType().Name + ": " + e.Message);
                    release();
                    try { raw.Close(); } catch (Exception) { }
                }
            }) { IsBackground = true, Name = "tempus-a" + cid }.Start();
        }

        // ---------------------------------------------------------------- the join (section 6)
        // index: which sentinel; start: part of the join at start (it goes on to the next store and retries).
        void Join(string typ, int index, bool start)
        {
            if (ck == ClockState.Paused)
            {
                Say("join: the request for " + typ + " waits until the system clock is read again");
                joinStore = 10 + Types.ToList().IndexOf(typ) + 1;
                return;
            }
            if (ck == ClockState.Stopped) return;
            dialed += 1;
            int cid = dialed;
            string addr = sentinels[index];
            int count = config.Store(typ).ShuffleLength;
            Say("join: asking the sentinel at " + addr + " for " + typ + " d" + cid);
            joinInFlight.Add(typ);
            Dial(addr, Frames.Sample(typ, count), cid, Values(count, Tls.NowMs()), o => Joined(typ, index, start, cid, o));
        }

        void Joined(string typ, int index, bool start, int cid, Dialed o)
        {
            joinInFlight.Remove(typ);
            if (o.Replied && o.Reply is Body.Entries body && body.Name == "sample_reply")
            {
                Say("join: the sentinel answered for " + typ + " d" + cid);
                var s = stores[typ];
                if (body.Store == typ && body.List.Count <= s.Count) foreach (var e in body.List) s.Insert(HeldOf(e));
                Show(typ);
                if (o.Typ == "tempus_sentinel")
                {
                    // ruling NQ-12: a joiner keeps the sentinel it joined through, at age 0, after the sample's entries
                    stores["tempus_sentinel"].Insert(new Held<Descriptor>(Hex.Of(o.Peer.Id), o.Peer, 0));
                    Show("tempus_sentinel");
                }
                if (!start) return;
                int at = Types.ToList().IndexOf(typ);
                joinDelay = config.JoinRetryInitialMs;
                if (at < 2) { joinStore = at + 2; Join(Types[at + 1], 0, true); } else { Say("join: done"); joinStore = 4; }
                return;
            }
            string what = o.Failed ?? (o.RotatedKid != null ? "key_rotated" : "the reply is not a sample_reply");
            Say("join: the sentinel did not answer for " + typ + ", " + what + " d" + cid);
            if (index + 1 < sentinels.Count) { Join(typ, index + 1, start); return; }
            if (!start) { Say("join: no sentinel answered for " + typ); return; }
            Say("join: no sentinel answered for " + typ + "; waiting to try again");
            env.Timers.After(joinDelay, "join " + typ, () => Post(() => { if (ck != ClockState.Stopped) Join(typ, 0, true); }));
            joinStore = Types.ToList().IndexOf(typ) + 1;
            joinDelay = Math.Min(joinDelay * 2, config.JoinRetryMaxMs);
        }

        // ---------------------------------------------------------------- ticks
        void ArmTick(string typ) => env.Timers.After(config.Store(typ).TickMs, "tick " + typ, () => Post(() => { ArmTick(typ); Tick(typ); }));

        void Tick(string typ)
        {
            // no tick before the first reading, none while the node waits for its clock, none after it stopped
            if (!ClockState.Ticks(ck)) return;
            string why = NodeChecks.PreWhy(me.Descriptor(), kid, now, config.SkewSeconds, null, out _);
            if (why != null)
            {
                if (!tokenStop) { Say("own token: " + why + "; ticking has stopped"); Tell(new NodeEvent.OwnTokenInvalid { Why = why }); }
                tokenStop = true;
                return;
            }
            var s = stores[typ];
            // entries whose token has expired leave the view first (ruling OQ-4; the window is admission's)
            var gone = s.Entries.Where(e =>
            {
                long exp;
                try { exp = Frames.ReadToken(e.Value.Token).Exp; } catch (Refused) { exp = 0; }
                return now >= exp + config.SkewSeconds;
            }).ToList();
            foreach (var e in gone) s.Drop(e.Id);
            if (gone.Count > 0) Say("expired in " + typ + ":" + string.Concat(gone.Select(e => " " + Peer8(e.Value.Id))));
            Refill(typ);
            var t = s.Tick();
            Refill(typ);
            Show(typ);
            switch (t.Kind)
            {
                case TickKind.Skipped: Say("tick " + typ + ": skipped (no draws)"); break;
                case TickKind.Aged: Say("tick " + typ + ": aged only (a shuffle is in flight)"); break;
                case TickKind.Empty:
                    Say("tick " + typ + ": the view is empty");
                    // an empty view: the node asks a sentinel again
                    if (joinStore == 4 && !joinInFlight.Contains(typ) && sentinels.Count > 0) Join(typ, 0, false);
                    break;
                case TickKind.Shuffle:
                {
                    var d = t.Partner.Value;
                    string head = "tick " + typ + ": shuffle with " + Peer8(d.Id);
                    string addr = d.AddrText();
                    if (!Addresses.Dialable(addr))
                    {
                        Say(head + ": its address is not one this build dials");
                        EndShuffle(typ, null);
                        return;
                    }
                    dialed += 1;
                    int cid = dialed;
                    Say(head + " at " + addr + " d" + cid);
                    Dial(addr, Frames.Shuffle(typ, t.Buffer.Select(e => new Entry(e.Age, e.Value))), cid, Values(s.Count, Tls.NowMs()), o =>
                    {
                        if (o.Replied)
                        {
                            EndShuffle(typ, o.Reply is Body.Entries b && b.Name == "shuffle_reply" && b.Store == typ ? b : null);
                        }
                        else
                        {
                            Say("tick " + typ + ": the partner did not answer, " + (o.Failed ?? "key_rotated") + " d" + cid);
                            EndShuffle(typ, null);
                        }
                    });
                    break;
                }
            }
        }

        // The shuffle this store started has ended: with the partner's entries, or failed (reply null).
        void EndShuffle(string typ, Body.Entries reply)
        {
            var s = stores[typ];
            if (!s.InFlight) return;
            bool merged = reply != null && s.Reply(reply.List.Select(HeldOf).ToList());
            if (reply == null) s.Failed();
            Show(typ);
            Say("tick " + typ + ": " + (merged ? "shuffle merged" : "shuffle failed"));
        }

        // ---------------------------------------------------------------- dialing
        void Dial(string addr, byte[] request, int cid, ConnValues v, Action<Dialed> then)
        {
            new Thread(() =>
            {
                Dialed o;
                try { o = new NodeConn(this, v, "d" + cid).Dial(addr, request); }
                catch (Exception e)
                {
                    Say("internal error: connection d" + cid + ": " + e.GetType().Name + ": " + e.Message);
                    o = new Dialed { Failed = "internal_error" };
                }
                Post(() =>
                {
                    if (o.RotatedKid != null) Tell(new NodeEvent.KeyRotated { Kid = o.RotatedKid, Dialed = true });
                    then(o);
                });
            }) { IsBackground = true, Name = "tempus-d" + cid }.Start();
        }

        // ---------------------------------------------------------------- an admitted peer's request
        internal void Request(PeerRequest r) => Post(() => r.Answer.SetResult(Answer(r)));

        /// The peer of an accepted connection answered this node's advert with key_rotated.
        internal void Rotated(byte[] named) => Post(() => Tell(new NodeEvent.KeyRotated { Kid = named, Dialed = false }));

        byte[] Refuse(PeerRequest r, string ev, string what)
        {
            Say("[tempus audit] " + ev + " peer=" + r.Peer.Id8() + " " + what + " a" + r.Cid);
            return null;
        }

        byte[] Answer(PeerRequest r)
        {
            switch (r.Kind)
            {
                case "shuffle":
                {
                    var b = (Body.Entries)r.Body;
                    var s = stores[b.Store];
                    Refill(b.Store);
                    var o = s.Request(Hex.Of(r.Peer.Id), b.List.Select(HeldOf).ToList());
                    Refill(b.Store);
                    if (o == null)
                    {
                        Say("[tempus audit] shuffle_refused peer=- the store refused the frame a" + r.Cid);
                        return null;
                    }
                    Show(b.Store);
                    return Frames.ShuffleReply(b.Store, o.Select(e => new Entry(e.Age, e.Value)));
                }
                case "sample":
                {
                    if (!(r.Body is Body.Sample b)) return Refuse(r, "protocol_error", r.Why);
                    var s = stores[b.Store];
                    if (b.N > s.Count) return Refuse(r, "protocol_error", "n is not 1 to the shuffle length");
                    Refill(b.Store);
                    var o = s.Sample(b.N);
                    Refill(b.Store);
                    // a sentinel inserts the peer that asks into its store of the peer's type, after the sample was taken
                    // (ruling NQ-13), so a joiner is never answered with itself
                    if (config.Role == "sentinel")
                    {
                        stores[r.Typ].Insert(new Held<Descriptor>(Hex.Of(r.Peer.Id), r.Peer, 0));
                        Show(r.Typ);
                    }
                    return o == null ? null : Frames.SampleReply(b.Store, o.Select(e => new Entry(e.Age, e.Value)));
                }
                default:
                    return Refuse(r, "request_refused", "call and cast are served by a bridge only");
            }
        }
    }
}
