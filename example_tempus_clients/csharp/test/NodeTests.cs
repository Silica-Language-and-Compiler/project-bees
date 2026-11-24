// Tests of the node half of the C# extension, run by a plain Main:
//
//   make -C example_tempus_clients/csharp test
//
// Group 1, the view and the store against the two independent Python models and the goldens of trials/t0_tempus_view
// and trials/t1_tempus_store: test/model_cases.py records every call of a model function behind every line of those
// goldens, and the same kinds of call on generated views and stores; each call is made again here and must give the
// same answer. Group 2, the clock: every line of the golden of trials/t0_tempus_clock is computed again. Group 3, the
// configuration: the refusals of tools/test_bees_tempus_conf.py that a value can show, and the start refusals of
// trials/c4_tempus_boot with their texts. Group 4, the node's own judgement of an entry on the cases of
// trials/t4_tempus_admission. No Silica program runs and nothing listens. Every line printed is the same on every run.
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.RegularExpressions;
using Bees.Tempus;
using Bees.Tempus.Testing;

namespace Bees.Tempus.Tests
{
    static class NodeTests
    {
        // ---------------------------------------------------------------- group 1: the models
        static Held<string> Ent(string s) { if (s == "-") return null; var p = s.Split('~'); return new Held<string>(p[0], p[1], int.Parse(p[2])); }
        static List<Held<string>> Vw(string s) => s == "-" ? new List<Held<string>>() : s.Split(',').Select(Ent).ToList();
        static List<long> Draws(string s) => s == "N" ? null : s == "-" ? new List<long>() : s.Split(',').Select(long.Parse).ToList();
        static string Show(Held<string> e) => e == null ? "-" : e.Id + "~" + e.Value + "~" + e.Age;
        static string Show(IReadOnlyList<Held<string>> v) => v.Count == 0 ? "-" : string.Join(",", v.Select(Show));
        static string ShowDraws(IReadOnlyList<long> d) => d == null ? "N" : d.Count == 0 ? "-" : string.Join(",", d);

        static (string, string) ViewCase(string[] f)
        {
            switch (f[1])
            {
                case "ageAll": return (Show(View.AgeAll(Vw(f[2]))), f[3]);
                case "select": { var r = View.Select(Vw(f[2]), int.Parse(f[3]), Draws(f[4])); return ((r.Partner != null ? 1 : 0) + "|" + Show(r.Partner) + "|" + Show(r.Sent) + "|" + Show(r.Left), string.Join("|", f.Skip(5))); }
                case "outgoing": return (Show(View.Outgoing(f[2], f[3], Vw(f[4]))), f[5]);
                case "replySelect": { var r = View.ReplySelect(Vw(f[2]), int.Parse(f[3]), f[4], Draws(f[5])); return (Show(r.Sent) + "|" + Show(r.Kept), f[6] + "|" + f[7]); }
                case "merge": return (Show(View.Merge(Vw(f[2]), Vw(f[3]), f[4], int.Parse(f[5]))), f[6]);
                case "preferSent": return (Show(View.PreferSent(Vw(f[2]), Vw(f[3]))), f[4]);
                case "backfill": return (Show(View.Backfill(Vw(f[2]), Vw(f[3]), int.Parse(f[4]))), f[5]);
                case "insert": return (Show(View.Insert(Vw(f[2]), Ent(f[3]), f[4], int.Parse(f[5]))), f[6]);
                case "sample": return (Show(View.Sample(Vw(f[2]), int.Parse(f[3]), Draws(f[4]))), f[5]);
                case "valid": return (View.Valid(Vw(f[2]), f[3], int.Parse(f[4])) ? "1" : "0", f[5]);
                default: throw new Exception("no such view function: " + f[1]);
            }
        }

        static string State(Store<string> s) => string.Join("|", s.SelfId, s.SelfD, s.Own ? "1" : "0", s.Cap, s.Count, Show(s.Entries), Show(s.Sent), Show(s.Partner),
            ShowDraws(s.TickDraws), ShowDraws(s.ReplyDraws));

        static (string, string) StoreCase(string[] f)
        {
            var s = new Store<string>(f[1], f[2], f[3] == "1", int.Parse(f[4]), int.Parse(f[5]));
            s.Entries = Vw(f[6]); s.Sent = Vw(f[7]); s.Partner = Ent(f[8]); s.TickDraws = Draws(f[9]); s.ReplyDraws = Draws(f[10]);
            string arg = f[12], o;
            switch (f[11])
            {
                case "insert": s.Insert(Ent(arg)); o = ""; break;
                case "drop": s.Drop(arg); o = ""; break;
                case "tick":
                {
                    var t = s.Tick();
                    o = t.Kind == TickKind.Skipped ? "skipped" : t.Kind == TickKind.Aged ? "aged" : t.Kind == TickKind.Empty ? "empty" : "shuffle;" + Show(t.Partner) + ";" + Show(t.Buffer);
                    break;
                }
                case "failed": s.Failed(); o = ""; break;
                case "reply": if (s.InFlight) s.Reply(Vw(arg)); o = ""; break;
                case "request": { var a = arg.Split(';'); var r = s.Request(a[0], Vw(a[1])); o = r == null ? "N" : Show(r); break; }
                case "sample": { var r = s.Sample(int.Parse(arg)); o = r == null ? "N" : Show(r); break; }
                default: throw new Exception("no such step: " + f[11]);
            }
            return (o + "|" + State(s), string.Join("|", f.Skip(13)));
        }

        static void Models(string cases)
        {
            var lines = File.ReadAllLines(cases);
            int fromGoldens = int.Parse(lines[1].Substring(lines[1].LastIndexOf(' ') + 1));
            var body = lines.Skip(2).ToList();
            void Run(string what, List<string> part, char kind) => T.Check(what + ": " + part.Count(l => l[0] == kind) + " calls give the model's answers", () =>
            {
                foreach (var line in part)
                {
                    if (line[0] != kind) continue;
                    var f = line.Split('|');
                    var (mine, want) = kind == 'V' ? ViewCase(f) : StoreCase(f);
                    if (mine != want) throw new Exception(line + "\n      got " + mine);
                }
            });
            T.Check("models: the model's lines are the goldens of trials/t0_tempus_view and trials/t1_tempus_store (" + lines[0].Substring(lines[0].LastIndexOf(' ') + 1) + " files)", () =>
                T.Eq(lines[0].StartsWith("# goldens "), true));
            Run("view, the calls behind the goldens", body.Take(fromGoldens).ToList(), 'V');
            Run("store, the steps behind the goldens", body.Take(fromGoldens).ToList(), 'S');
            Run("view, generated cases", body.Skip(fromGoldens).ToList(), 'V');
            Run("store, generated cases", body.Skip(fromGoldens).ToList(), 'S');
        }

        // ---------------------------------------------------------------- group 2: the clock
        static void ClockGolden(string root)
        {
            var goldens = T.Goldens(Path.Combine(root, "trials", "t0_tempus_clock"), @"^clock\..*\.scout$");
            T.Check("clock: there is a recorded output to compare with", () => T.Eq(goldens.Count > 0, true));
            var one = new Regex(@"^(follow|hold|stop limit (\d+)): time (\d+), reading (\d+) -> .*$");
            var head = new Regex(@"^clock_back (follow|hold|stop)(?: limit (\d+))?, clock_fail (continue|pause)$");
            var reading = new Regex(@"^  reading (no time|\d+) -> .*$");
            var states = new Dictionary<int, string> { [0] = "no reading yet", [3] = "no reading yet, application told", [1] = "good", [2] = "paused, waits for the clock",
                [6] = "goes on with its last reading", [5] = "holds its time", [4] = "stopped" };
            var says = new Dictionary<int, string> { [0] = "nothing", [1] = "first reading: one line, listen", [2] = "no time at start: one line, application told",
                [3] = "no time, pause: one line, application told", [4] = "no time, continue: one line, application told", [6] = "step back followed: one line",
                [7] = "step back, hold begins: one line", [8] = "the held time is reached: one line", [9] = "step back above the limit: one line, application told, stop" };
            long Num(string s) => s.Length == 0 ? 0 : long.Parse(s);
            foreach (var path in goldens) T.Check("clock " + Path.GetFileName(path) + ": every line of the golden is computed again", () =>
            {
                string back = "", fail = ""; long limit = 0, now = 0; int ck = 0, lines = 0;
                foreach (var line in File.ReadAllLines(path))
                {
                    Match m1 = one.Match(line), m2 = head.Match(line), m3 = reading.Match(line);
                    string mine;
                    if (m1.Success)
                    {
                        var b = Clock.Back(long.Parse(m1.Groups[3].Value), long.Parse(m1.Groups[4].Value), m1.Groups[1].Value.Split(' ')[0], Num(m1.Groups[2].Value));
                        mine = m1.Groups[1].Value + ": time " + m1.Groups[3].Value + ", reading " + m1.Groups[4].Value + " -> time " + b.Now + ", " +
                            new[] { "not earlier", "earlier, followed", "earlier, held", "earlier, the node stops" }[b.Act];
                    }
                    else if (m2.Success) { back = m2.Groups[1].Value; limit = Num(m2.Groups[2].Value); fail = m2.Groups[3].Value; ck = 0; now = 0; mine = line; }
                    else if (m3.Success)
                    {
                        var t = Clock.Turn(ck, now, long.TryParse(m3.Groups[1].Value, out long n) ? n : (long?)null, back, limit, fail);
                        ck = t.Ck; now = t.Now;
                        string accepts = ck == 0 || ck == 3 ? "does not listen yet" :
                            ClockState.Closes(ck) == "clock_refused" ? "closes accepted connections (role 4, clock_refused)" :
                            ClockState.Closes(ck) == "clock_stopped" ? "closes accepted connections (role 5, clock_stopped)" : "accepts";
                        mine = "  reading " + m3.Groups[1].Value + " -> time " + now + "; " + states[ck] + "; " + (ClockState.Ticks(ck) ? "ticks" : "no ticks") + "; " + accepts + "; does: " +
                            (t.Again ? "read again: one line; then " : "") + says[t.Say];
                    }
                    else mine = line;
                    T.Eq(mine, line);
                    if (m1.Success || m3.Success) lines += 1;
                }
                if (lines < 70) throw new Exception("only " + lines + " lines were computed");
            });
        }

        // ---------------------------------------------------------------- group 3: the configuration
        static void Configuration(string root)
        {
            var certs = new Certs(root);
            var store = new StoreConfig(4, 3, 1000);
            var small = new StoreConfig(4, 2, 1000);
            var sentinelCert = certs.Cert("sentinel");
            var one = new[] { new SentinelAddress("127.0.0.1", 24301, "s1") };
            TempusConfig Conf(string role = "edge", string addr = "127.0.0.1", int port = 24300, IReadOnlyList<SentinelAddress> sentinels = null, StoreConfig edge = null, int keyBytes = 32,
                              string kid = "k1", long timeout = 2000, int inflight = 2, long skew = 10000, string back = "follow", long? limit = null, string fail = "pause",
                              long read = 1000, long jinit = 200, long jmax = 800) =>
                new TempusConfig(role, addr, port, sentinels ?? one, edge ?? store, small, small, T.B(kid), new byte[keyBytes],
                    new[] { new KeyValuePair<string, Certificate>("s1", sentinelCert) }, timeout, inflight, skew, back, limit, fail, read, jinit, jmax);
            var noSentinels = new SentinelAddress[0];
            void Refused(TempusConfig c, string part)
            {
                string why = c.Refusal() ?? throw new Exception("not refused, wanted \"" + part + "\"");
                if (!why.Contains(part)) throw new Exception("refused with \"" + why + "\", wanted \"" + part + "\"");
            }
            T.Check("configuration: a good value is accepted, for an edge and for a first sentinel", () =>
            {
                T.Eq(Conf().Refusal(), null);
                T.Eq(Conf(role: "sentinel", sentinels: noSentinels).Refusal(), null);
                T.Eq(Conf(back: "stop", limit: 0).Refusal(), null); T.Eq(Conf(back: "stop", limit: 86400).Refusal(), null);
                T.Eq(Conf(back: "hold", fail: "continue").Refusal(), null);
                T.Eq(Conf(read: 100).Refusal(), null); T.Eq(Conf(read: 60000).Refusal(), null);
            });
            T.Check("configuration: the bounds of tools/test_bees_tempus_conf.py, with its words", () =>
            {
                Refused(Conf(edge: new StoreConfig(257, 3, 1000)), "257 is above 256");
                Refused(Conf(edge: new StoreConfig(4, 5, 1000)), "above the capacity 4");
                Refused(Conf(keyBytes: 31), "32 bytes");
                Refused(Conf(jmax: 150), "below join_retry_initial_ms");
                Refused(Conf(edge: new StoreConfig(4, 3, 99)), "tempus.edge.tick_ms: 99 is below 100 (bounds 100 to 3600000; never clamped)");
                Refused(Conf(timeout: 60001), "tempus.shuffle_timeout_ms: 60001 is above 60000");
                Refused(Conf(inflight: 65), "tempus.inflight_max"); Refused(Conf(skew: 300001), "tempus.clock_skew_ms"); Refused(Conf(port: 0), "tempus.port");
            });
            T.Check("configuration: sentinels are required unless the node is the first sentinel", () =>
            {
                Refused(Conf(sentinels: noSentinels), "required unless the node is the first sentinel");
                Refused(Conf(sentinels: Enumerable.Repeat(one[0], 17).ToList()), "1 to 16");
                Refused(Conf(sentinels: new[] { new SentinelAddress("127.0.0.1", 24301, "nobody") }), "names no entry of the tempus whitelist");
            });
            T.Check("configuration: the clock's choices are closed sets, and the limit belongs to stop alone", () =>
            {
                Refused(Conf(back: "ignore"), "expected one of follow, hold, stop"); Refused(Conf(back: "1"), "expected one of follow, hold, stop");
                Refused(Conf(fail: "stop"), "expected one of continue, pause"); Refused(Conf(fail: "true"), "expected one of continue, pause");
                Refused(Conf(back: "stop"), "tempus.clock_back_limit_s: required when clock_back is stop");
                Refused(Conf(back: "follow", limit: 30), "remove clock_back_limit_s"); Refused(Conf(back: "hold", limit: 30), "remove clock_back_limit_s");
                Refused(Conf(back: "stop", limit: -1), "clock_back_limit_s"); Refused(Conf(back: "stop", limit: 86401), "clock_back_limit_s");
                Refused(Conf(read: 99), "clock_read_ms"); Refused(Conf(read: 60001), "clock_read_ms");
            });
            T.Check("configuration: the bridge role is refused, and a role outside the set", () =>
            {
                Refused(Conf(role: "bridge"), "bridge needs mode tempus-trust");
                Refused(Conf(role: "client"), "expected one of edge, bridge, sentinel");
            });
            // the start refusals of the Silica node (trials/c4_tempus_boot): the same fault gives the same line
            string leaf = Path.Combine(root, "trials", "c4_tempus_boot");
            var me = certs.Identity("node", "tempus_edge", 1000, 2000, "127.0.0.1:24300");
            var three = new[] { store, small, small };
            string BootWhy(int typ = 1, byte[] token = null, int key = 32, StoreConfig[] stores = null, int back = 1) =>
                Boot.Why(typ, 64, me.Pub, 32, token ?? me.Token, 2, key, 2, 2000, 200, 800, 10, 128, stores ?? three, back, 0, 2, 1000);
            var faults = new List<(string, string)>
            {
                ("capacity", BootWhy(stores: new[] { new StoreConfig(257, 3, 1000), small, small })),
                ("shuffle", BootWhy(stores: new[] { new StoreConfig(4, 5, 1000), small, small })),
                ("producer", BootWhy(key: 31)),
                ("clockback", BootWhy(back: 4)),
                ("token", BootWhy(token: certs.Identity("node", "tempus_bridge", 1000, 2000, "127.0.0.1:24300").Token)),
            };
            T.Check("start refusals: a good set of values is not refused", () => T.Eq(BootWhy(), null));
            foreach (var (name, mine) in faults)
            {
                var goldens = T.Goldens(leaf, @"^dangerous_" + name + @"\..*\.scout$");
                T.Check("start refusals: the fault of trials/c4_tempus_boot dangerous_" + name + " is refused with the Silica node's line (" + goldens.Count + " goldens)", () =>
                {
                    T.Eq(goldens.Count > 0, true);
                    foreach (var g in goldens) T.Eq("tempus: boot refused: " + mine, File.ReadAllLines(g)[0]);
                });
            }
            T.Check("start refusals: a node's own token must read, be of the node's type and name the node's key; a refused start writes the line and starts nothing", () =>
            {
                T.Eq(Conf().StartRefusal(me), null);
                T.Eq(Conf(role: "sentinel", sentinels: noSentinels).StartRefusal(me), "the node's token is for another peer type than the node's");
                T.Eq(Conf().StartRefusal(me.WithToken(certs.Identity("other", "tempus_edge", 1000, 2000, "127.0.0.1:1").Token)), "the node's token names another key");
                T.Eq(Conf().StartRefusal(me.WithToken(new byte[70])), "the node's token does not read: bad_version");
                var lines = new Lines();
                try { TempusNode.Start(Conf(role: "bridge"), me, null, TestEnvironment.Of(new TestClock(1500), new ManualTimers(), new long[0], lines)); throw new Exception("started"); }
                catch (ConfigRefused e) { T.Eq(e.Why.Contains("cannot be a bridge"), true); }
                T.Eq(lines.Snapshot().Count == 1 && lines.Snapshot()[0].StartsWith("tempus: boot refused: tempus.role: bridge needs mode tempus-trust"), true);
            });
        }

        // ---------------------------------------------------------------- group 4: the node's judgement of an entry
        static void Admission(string root)
        {
            string leaf = Path.Combine(root, "trials", "t4_tempus_admission");
            string text = File.ReadAllText(Path.Combine(leaf, "lib", "tempus_fixtures.silica"));
            var goldens = T.Goldens(leaf, @"^dangerous_admit\..*\.scout$");
            var stores = new Dictionary<string, string> { ["1"] = "tempus_edge", ["2"] = "tempus_bridge", ["3"] = "tempus_sentinel" };
            byte[] kid = T.B(Fixtures.Constant(text, "kid")), producer = Hex.Parse(Fixtures.Constant(text, "producer_pub_hex"));
            long now = long.Parse(Fixtures.Constant(text, "now")), skew = long.Parse(Fixtures.Constant(text, "skew"));
            var names = Fixtures.Table(text, "name"); var kinds = Fixtures.Table(text, "kind"); var ids = Fixtures.Table(text, "id_hex"); var pubs = Fixtures.Table(text, "pub_hex");
            var tokens = Fixtures.Table(text, "token_hex"); var wants = Fixtures.Table(text, "want");
            foreach (var path in goldens)
            {
                var said = new Dictionary<string, string>();
                foreach (var line in File.ReadAllLines(path)) { int at = line.IndexOf(": ", StringComparison.Ordinal); if (at >= 0 && !said.ContainsKey(line.Substring(0, at))) said[line.Substring(0, at)] = line.Substring(at + 2); }
                T.Check("the node's entry check, " + Path.GetFileName(path) + ": the verdict and the reason the Silica node gave, on every descriptor case", () =>
                {
                    int n = 0;
                    for (int i = 0; i < names.Count; i++)
                    {
                        if (kinds[i] != "1") continue;
                        string mine;
                        try
                        {
                            var d = Frames.ReadDescriptor(new Descriptor(Hex.Parse(ids[i]), Hex.Parse(pubs[i]), T.B(Fixtures.Constant(text, "addr")), Hex.Parse(tokens[i])).Term());
                            string why = NodeChecks.EntryWhy(d, stores[wants[i]], kid, producer, now, skew);
                            mine = why == null ? "admitted" : "refused: " + why;
                        }
                        catch (Refused e) { mine = "refused: " + e.Why; }
                        T.Eq(mine, said[names[i]], names[i]);
                        n += 1;
                    }
                    if (n < 10) throw new Exception("only " + n + " cases");
                });
            }
            T.Check("the node's reader: a frame of the test unit names an atom a production node does not hold", () =>
            {
                T.Eq(NodeChecks.KindOf(Etf.Encode(new TMap(("t", new TAtom("tick")), ("store", new TAtom("tempus_edge")))), out string why), null);
                T.Eq(why, "unknown_atom");
                T.Eq(NodeChecks.KindOf(Etf.Encode(new TMap(("t", new TAtom("done")))), out why), "done");
                T.Eq(NodeChecks.KindOf(Frames.Sample("tempus_edge", 1), out why), "sample");
            });
        }

        public static int Run(string root, string cases)
        {
            Models(cases);
            ClockGolden(root);
            Configuration(root);
            Admission(root);
            Console.WriteLine("[csharp node tests] " + T.Passed + " passed, " + T.Failed + " failed");
            return T.Failed == 0 ? 0 : 1;
        }
    }
}
