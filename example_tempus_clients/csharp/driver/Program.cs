// A usable example, to be used carefully. See README.md in the directory above.
//
// The driver application of the C# extension: a thin program over the library in ../lib. It reads its values from
// the command line and from the files the command line names, hands them to the library, and prints what the library
// reports, one line each. It holds no test code: it makes no key and no token.
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using Bees.Tempus;

namespace Bees.Tempus.Driver
{
    static class Program
    {
        const string Usage = @"bees-tempus: the driver of the C# extension for TEMPUS. A usable example: use it carefully.

  gossip OPTIONS                      be a node of a TEMPUS network (an edge or a sentinel, as the token says): listen,
                                      join through the sentinels, shuffle the three stores on their timers, answer
                                      the peers that dial. Prints the node's own lines, its audit lines, and, for every
                                      peer it comes to know, `learned STORE ID16 HOST:PORT`.
                                      Runs until it is interrupted or ended, or for --run-ms; then prints, per store,
                                      `known STORE: ID16 ...` (every peer it ever learned of, sorted).
  dial HOST:PORT OPTIONS REQUEST      connect, be admitted, send one request, print the outcome as one line
      REQUEST: sample STORE N
               shuffle STORE                        offers this client's own entry at age 0
               call REQ_ID MODULE FUNCTION [INT]...  to a bridge; the arguments are integers
               cast REQ_ID MODULE FUNCTION [INT]...  to a bridge; there is no reply
  listen HOST:PORT OPTIONS --count N  accept N connections; answer a sample or a shuffle of this client's own type
                                      with its own entry at age 0, and of another type with no entries; print each
                                      outcome as one line
  read-hex HEX SHUFFLE_LENGTH         read one frame body given as hex digits and print what it is
  node KEY=VALUE ...                  be a TEMPUS node (an edge or a sentinel) until the standard input says exit or ends

  OPTIONS of gossip, dial and listen, all required unless marked:
      --cert FILE            this client's certificate, PEM, self-signed over its Ed25519 key
      --key FILE             its private key, PEM (PKCS#8, not encrypted)
      --token FILE           its token from the producer, as hex digits in a file
      --addr HOST:PORT       the listen address this client advertises
      --producer-pub HEX     the producer's current public key, 64 hex digits
      --kid TEXT             the identifier of that key
      --skew SECONDS         the clock difference this client allows
      --timeout-ms MS        the time bound of a whole connection
      --shuffle-length N     dial and listen: the shuffle length of the network
      --whitelist-cert FILE  optional, may be repeated: the certificate (PEM) of a bridge or sentinel this client accepts
      --now SECONDS          optional: the time for token checks, in seconds since 1970 UTC, in place of the system clock
    gossip only (in place of --shuffle-length; --addr is also where the node listens; a --sentinel needs its
    certificate among the --whitelist-cert files; --now, when given, is the node's clock, on a loopback --addr only):
      --store-edge CAP:LEN:TICK_MS      capacity, shuffle length and tick of the edge store
      --store-bridge CAP:LEN:TICK_MS    the same of the bridge store
      --store-sentinel CAP:LEN:TICK_MS  the same of the sentinel store
      --join-retry-ms FIRST:MAX         the join's first and greatest retry delay
      --sentinel HOST:PORT   may be repeated; none for a first sentinel
      --run-ms MS            optional: stop after that long
  STORE is tempus_edge, tempus_bridge or tempus_sentinel.

  KEYS of node, every one required unless marked optional; nothing has a default:
      role=edge|sentinel  listen_address=A.B.C.D  port=N  address=A.B.C.D:PORT (what other nodes dial)
      cert_file=PATH (PEM)  key_file=PATH (PEM, PKCS#8, not encrypted)  token_file=PATH (the token as hex digits)
      producer_kid=TEXT  producer_key=HEX
      sentinels=HOST:PORT:CERTNAME,... (optional for a first sentinel)
      whitelist=CERTNAME:PEM_FILE,... (optional)
      edge=CAPACITY/SHUFFLE_LENGTH/TICK_MS  bridge=...  sentinel=...
      shuffle_timeout_ms=N  inflight_max=N  clock_skew_ms=N  clock_back=follow|hold|stop  clock_back_limit_s=N (with stop)
      clock_fail=continue|pause  clock_read_ms=N  join_retry_initial_ms=N  join_retry_max_ms=N
";

        sealed class Problem : Exception { public Problem(string m) : base(m) { } }

        sealed class Options
        {
            public readonly Dictionary<string, List<string>> Values = new Dictionary<string, List<string>>();
            public readonly List<string> Rest = new List<string>();

            public Options(IEnumerable<string> args)
            {
                var a = args.ToList();
                for (int i = 0; i < a.Count; i++)
                {
                    if (a[i].StartsWith("--"))
                    {
                        if (i + 1 >= a.Count) throw new Problem(a[i] + " needs a value");
                        if (!Values.TryGetValue(a[i], out var l)) Values[a[i]] = l = new List<string>();
                        l.Add(a[++i]);
                    }
                    else Rest.Add(a[i]);
                }
            }

            public string Need(string name) => Values.TryGetValue(name, out var l) ? l[l.Count - 1] : throw new Problem(name + " is required (no default)");
            public string Maybe(string name) => Values.TryGetValue(name, out var l) ? l[l.Count - 1] : null;
            public List<string> All(string name) => Values.TryGetValue(name, out var l) ? l : new List<string>();
            public long Number(string name) => long.TryParse(Need(name), out long n) ? n : throw new Problem(name + " is not a number");
        }

        static string ReadText(string path)
        {
            try { return File.ReadAllText(path); } catch (Exception) { throw new Problem("cannot read " + path); }
        }

        static byte[] TokenFile(string path)
        {
            try { return Hex.Parse(ReadText(path).Trim()); } catch (ArgumentException) { throw new Problem(path + " does not hold a token as hex digits"); }
        }

        static byte[] HexOf(string text, string what)
        {
            try { return Hex.Parse(text); } catch (ArgumentException) { throw new Problem(what + " is not hex digits"); }
        }

        static int Run(string[] argv)
        {
            if (argv.Length == 0) { Console.Write(Usage); return 2; }
            switch (argv[0])
            {
                case "read-hex":
                {
                    if (argv.Length != 3) throw new Problem("read-hex HEX SHUFFLE_LENGTH");
                    try
                    {
                        var body = Frames.ReadBody(HexOf(argv[1], "the frame"), int.Parse(argv[2]));
                        Console.WriteLine(new Outcome("reply", "done") { Body = body }.Line());
                    }
                    catch (Refused e) { Console.WriteLine("refused reason=\"" + e.Why + "\""); }
                    return 0;
                }
                case "dial":
                case "listen":
                {
                    var o = new Options(argv.Skip(1));
                    if (o.Rest.Count == 0) throw new Problem(argv[0] + " HOST:PORT ...");
                    Identity me;
                    try { me = Identity.Load(o.Need("--cert"), o.Need("--key"), TokenFile(o.Need("--token")), o.Need("--addr")); }
                    catch (Exception e) when (e is ArgumentException || e is Refused || e is IOException) { throw new Problem("the identity cannot be used: " + e.Message); }
                    string nowText = o.Maybe("--now");
                    long fixedNow = nowText == null ? 0 : long.Parse(nowText);
                    Func<long> now = nowText == null ? Verifier.SystemSeconds : () => fixedNow;
                    var whitelist = o.All("--whitelist-cert").Select(f => Certificate.FromPem(ReadText(f)).Fingerprint).ToList();
                    var verifier = new Verifier(HexOf(o.Need("--producer-pub"), "--producer-pub"), Encoding.UTF8.GetBytes(o.Need("--kid")), now, o.Number("--skew"), whitelist);
                    var settings = new Settings(o.Number("--timeout-ms"), (int)o.Number("--shuffle-length"));
                    if (argv[0] == "dial")
                    {
                        var r = o.Rest.Skip(1).ToList();
                        Request request;
                        if (r.Count == 3 && r[0] == "sample") request = new Request.Sample(r[1], int.Parse(r[2]));
                        else if (r.Count == 2 && r[0] == "shuffle") request = new Request.Shuffle(r[1], new[] { me.Entry(0) });
                        else if (r.Count >= 4 && (r[0] == "call" || r[0] == "cast"))
                        {
                            var args = r.Skip(4).Select(x => (Term)new TInt(long.Parse(x))).ToList();
                            var id = Encoding.UTF8.GetBytes(r[1]);
                            request = r[0] == "call" ? new Request.Call(id, r[2], r[3], args) : (Request)new Request.Cast(id, r[2], r[3], args);
                        }
                        else throw new Problem("the request is sample STORE N, shuffle STORE, call REQ_ID MODULE FUNCTION [INT]... or cast ...");
                        Console.WriteLine(Client.Dial(o.Rest[0], me, verifier, request, settings).Line());
                        return 0;
                    }
                    int at = o.Rest[0].LastIndexOf(':');
                    if (at <= 0) throw new Problem("listen HOST:PORT");
                    int count = (int)o.Number("--count");
                    string mine = Frames.ReadToken(me.Token).Typ;
                    using (var listener = new Listener(me, verifier, settings, o.Rest[0].Substring(0, at), int.Parse(o.Rest[0].Substring(at + 1)),
                        rq => (rq.Body is Body.Sample s ? s.Store : ((Body.Entries)rq.Body).Store) == mine ? new[] { me.Entry(0) } : Array.Empty<Entry>()))
                    {
                        Console.Error.WriteLine("listening on " + listener.Address);
                        for (int i = 0; i < count; i++)
                        {
                            IReadOnlyList<Outcome> outs;
                            do { outs = listener.Outcomes(i + 1, 1000); } while (outs.Count <= i);
                            Console.WriteLine(outs[i].Line());
                        }
                    }
                    return 0;
                }
                case "gossip":
                    return Gossip(new Options(argv.Skip(1)));
                case "node":
                    return Node(argv.Skip(1));
                default:
                    Console.Write(Usage);
                    return 2;
            }
        }

        // What a node's configuration requires and the command line of `gossip` does not carry. The library has no
        // defaults, so the driver states them here. They are the driver's choices for the gossip example, not
        // recommendations: an application decides each of them for its own network (README.md, "The configuration").
        const int GossipInflightMax = 16;                 // accepted connections at once
        const string GossipClockBack = "follow";          // a clock that goes back is followed
        static readonly long? GossipClockBackLimitS = null; // used under "stop" only
        const string GossipClockFail = "continue";        // a failed reading leaves the last good time in use
        const long GossipClockReadMs = 1000;              // how often the clock is read

        static StoreConfig GossipStore(Options o, string name)
        {
            var p = o.Need(name).Split(':');
            if (p.Length != 3 || !p.All(x => long.TryParse(x, out _))) throw new Problem(name + " is CAP:LEN:TICK_MS");
            return new StoreConfig(int.Parse(p[0]), int.Parse(p[1]), long.Parse(p[2]));
        }

        static (string Host, int Port) HostPort(string text, string name)
        {
            int at = text.LastIndexOf(':');
            if (at <= 0 || !int.TryParse(text.Substring(at + 1), out int port)) throw new Problem(name + " is HOST:PORT");
            return (text.Substring(0, at), port);
        }

        // `gossip`: a member of a TEMPUS network, as the Python, Swift and Kotlin drivers' `gossip` commands are, for the
        // gossip example in ../gossip. A thin command over TempusNode: no second implementation of anything.
        static int Gossip(Options o)
        {
            if (o.Rest.Count != 0) throw new Problem("gossip OPTIONS");
            Identity me;
            try { me = Identity.Load(o.Need("--cert"), o.Need("--key"), TokenFile(o.Need("--token")), o.Need("--addr")); }
            catch (Exception e) when (e is ArgumentException || e is Refused || e is IOException) { throw new Problem("the identity cannot be used: " + e.Message); }
            // the node's role is the type its token carries
            string role;
            try { role = Frames.ReadToken(me.Token).Typ.Substring("tempus_".Length); }
            catch (Refused) { throw new Problem("--token does not hold a token"); }
            var retry = o.Need("--join-retry-ms").Split(':');
            if (retry.Length != 2 || !retry.All(x => long.TryParse(x, out _))) throw new Problem("--join-retry-ms is FIRST:MAX");
            var (host, port) = HostPort(me.Addr, "--addr");
            // The whitelist's entries are named by their place on the command line. The command line does not say which
            // certificate is which sentinel's, and the node does not need it: it requires only that a sentinel's name is
            // an entry of the whitelist, and admits a sentinel when its certificate is any entry. So every sentinel is
            // given the first name; with no --whitelist-cert the node refuses to start, since it could admit no sentinel.
            var whitelist = o.All("--whitelist-cert").Select((f, k) => new KeyValuePair<string, Certificate>("cert" + (k + 1), Certificate.FromPem(ReadText(f)))).ToList();
            var sentinels = o.All("--sentinel").Select(s => { var (h, p) = HostPort(s, "--sentinel"); return new SentinelAddress(h, p, whitelist.Count > 0 ? whitelist[0].Key : ""); }).ToList();
            var config = new TempusConfig(role, host, port, sentinels, GossipStore(o, "--store-edge"), GossipStore(o, "--store-bridge"), GossipStore(o, "--store-sentinel"),
                Encoding.UTF8.GetBytes(o.Need("--kid")), HexOf(o.Need("--producer-pub"), "--producer-pub"), whitelist, o.Number("--timeout-ms"),
                GossipInflightMax, o.Number("--skew") * 1000, GossipClockBack, GossipClockBackLimitS, GossipClockFail, GossipClockReadMs,
                long.Parse(retry[0]), long.Parse(retry[1]));
            // every line, the node's and this command's, is printed under one lock
            var printing = new object();
            void Say(string line) { lock (printing) Console.WriteLine(line); }
            // the node's clock: the machine's, or the fixed time of --now
            string nowText = o.Maybe("--now");
            long fixedNow = nowText == null ? 0 : long.Parse(nowText);
            // The library's node takes the clock of any environment it is given. The Silica node, and the Swift and Rust
            // nodes, accept a clock of their caller's on a loopback listen address only; this command keeps that rule.
            if (nowText != null && host != "localhost" && !(Addresses.Kind(host) == "ipv4" && host.StartsWith("127.")))
                throw new Problem("--now is taken on a loopback listen address only");
            var environment = nowText == null ? NodeEnvironment.System(Say)
                : new NodeEnvironment(() => fixedNow, new SystemTimers(), new SecureDraws(), () => Crypto.RandomBytes(32), Say);
            // every peer this node ever held in a store, from the views the node reports; the listener runs on the node's thread
            var known = Frames.PeerTypes.ToDictionary(t => t, t => new SortedSet<string>(StringComparer.Ordinal));
            TempusNode node;
            try
            {
                node = TempusNode.Start(config, me, (n, e) =>
                {
                    switch (e)
                    {
                        case NodeEvent.ViewChanged v:
                            foreach (var x in v.Entries)
                            {
                                string id16 = Hex.Of(x.D.Id.Take(8).ToArray());
                                bool isNew;
                                lock (known) isNew = known[v.Store].Add(id16);
                                if (isNew) Say("learned " + v.Store + " " + id16 + " " + Encoding.UTF8.GetString(x.D.Addr));
                            }
                            break;
                        case NodeEvent.OwnTokenInvalid x: Say("told: the node's own token is not valid any more: " + x.Why); break;
                        case NodeEvent.KeyRotated x: Say("told: a peer answered key_rotated, its current kid is " + Encoding.UTF8.GetString(x.Kid)); break;
                        case NodeEvent.ClockUnreadable x: Say("told: " + x.What); break;
                        case NodeEvent.Stopped x: Say("told: " + x.Why); break;
                        case NodeEvent.ListenFailed x: Say("told: the node does not listen: " + x.Why); break;
                    }
                }, environment);
            }
            catch (ConfigRefused) { return 1; }       // the node has written the line that says why
            // SIGINT and SIGTERM end the run, so that the `known` lines are printed
            using var ended = new System.Threading.ManualResetEventSlim(false);
            void End(System.Runtime.InteropServices.PosixSignalContext c) { c.Cancel = true; ended.Set(); }
            using var onInt = System.Runtime.InteropServices.PosixSignalRegistration.Create(System.Runtime.InteropServices.PosixSignal.SIGINT, End);
            using var onTerm = System.Runtime.InteropServices.PosixSignalRegistration.Create(System.Runtime.InteropServices.PosixSignal.SIGTERM, End);
            string runMs = o.Maybe("--run-ms");
            if (runMs == null) ended.Wait(); else ended.Wait(TimeSpan.FromMilliseconds(long.Parse(runMs)));
            node.Dispose();
            lock (known)
                foreach (var t in Frames.PeerTypes) Say("known " + t + ": " + (known[t].Count == 0 ? "(none)" : string.Join(" ", known[t])));
            return 0;
        }

        // An application that is a TEMPUS node: the smallest complete one. It reads the machine's clock, runs its own
        // timers and draws from the system's secure random source; nothing here can set its time.
        static int Node(IEnumerable<string> args)
        {
            var given = new Dictionary<string, string>();
            foreach (var a in args)
            {
                int eq = a.IndexOf('=');
                if (eq <= 0) throw new Problem("not KEY=VALUE: " + a);
                given[a.Substring(0, eq)] = a.Substring(eq + 1);
            }
            string Need(string key) => given.TryGetValue(key, out var v) ? v : throw new Problem(key + " is required (no default)");
            long Number(string key) => long.TryParse(Need(key), out long n) ? n : throw new Problem(key + " is not a number");
            StoreConfig Store(string key)
            {
                var p = Need(key).Split('/');
                if (p.Length != 3 || !p.All(x => long.TryParse(x, out _))) throw new Problem(key + " is not CAPACITY/SHUFFLE_LENGTH/TICK_MS");
                return new StoreConfig(int.Parse(p[0]), int.Parse(p[1]), long.Parse(p[2]));
            }
            var whitelist = new List<KeyValuePair<string, Certificate>>();
            foreach (var w in (given.GetValueOrDefault("whitelist") ?? "").Split(',', StringSplitOptions.RemoveEmptyEntries))
            {
                int c = w.IndexOf(':');
                if (c <= 0) throw new Problem("a whitelist entry is CERTNAME:PEM_FILE");
                whitelist.Add(new KeyValuePair<string, Certificate>(w.Substring(0, c), Certificate.FromPem(ReadText(w.Substring(c + 1)))));
            }
            var sentinels = new List<SentinelAddress>();
            foreach (var s in (given.GetValueOrDefault("sentinels") ?? "").Split(',', StringSplitOptions.RemoveEmptyEntries))
            {
                var p = s.Split(':');
                if (p.Length != 3 || !int.TryParse(p[1], out int port)) throw new Problem("a sentinel is HOST:PORT:CERTNAME");
                sentinels.Add(new SentinelAddress(p[0], port, p[2]));
            }
            var config = new TempusConfig(Need("role"), Need("listen_address"), (int)Number("port"), sentinels, Store("edge"), Store("bridge"), Store("sentinel"),
                Encoding.UTF8.GetBytes(Need("producer_kid")), HexOf(Need("producer_key"), "producer_key"), whitelist, Number("shuffle_timeout_ms"),
                (int)Number("inflight_max"), Number("clock_skew_ms"), Need("clock_back"), given.ContainsKey("clock_back_limit_s") ? Number("clock_back_limit_s") : (long?)null,
                Need("clock_fail"), Number("clock_read_ms"), Number("join_retry_initial_ms"), Number("join_retry_max_ms"));
            Identity identity;
            try { identity = Identity.Load(Need("cert_file"), Need("key_file"), TokenFile(Need("token_file")), Need("address")); }
            catch (Exception e) when (e is ArgumentException || e is Refused || e is IOException) { throw new Problem("the identity cannot be used: " + e.Message); }
            TempusNode node;
            try
            {
                node = TempusNode.Start(config, identity, (n, e) =>
                {
                    // what the application is told; an application acts on these (a new token, a new node), this one prints them
                    switch (e)
                    {
                        case NodeEvent.OwnTokenInvalid x: Console.WriteLine("application: told that the node's own token is not valid any more: " + x.Why); break;
                        case NodeEvent.KeyRotated x: Console.WriteLine("application: told that a peer answered key_rotated, its current kid is " + Encoding.UTF8.GetString(x.Kid)); break;
                        case NodeEvent.ClockUnreadable x: Console.WriteLine("application: told that " + x.What); break;
                        case NodeEvent.Stopped x: Console.WriteLine("application: told that " + x.Why); break;
                        case NodeEvent.ListenFailed x: Console.WriteLine("application: told that the node does not listen: " + x.Why); break;
                    }
                });
            }
            catch (ConfigRefused) { return 1; }       // the node has written the line that says why
            string line;
            while ((line = Console.ReadLine()) != null && line != "exit") { }
            node.Dispose();
            return 0;
        }

        static int Main(string[] argv)
        {
            Console.SetOut(new StreamWriter(Console.OpenStandardOutput()) { AutoFlush = true });
            try { return Run(argv); }
            catch (Problem e) { Console.Error.WriteLine("bees-tempus: " + e.Message); return 2; }
            catch (OpenSslUnavailable e) { Console.Error.WriteLine("bees-tempus: " + e.Message); return 3; }
            catch (FormatException) { Console.Error.WriteLine("bees-tempus: a number was expected"); return 2; }
        }
    }
}
