// C13: a mixed network of Silica nodes and nodes of the C# extension (example_tempus_clients/csharp) on 127.0.0.1.
// TEST CODE of this trial; it is not part of the extension. It starts nodes of the extension as an application would
// (TempusNode.Start), with the TEST ONLY identities of tools/bees_tempus_certs.py, checks every step and prints one
// line per step. Nothing printed depends on the time of day.
//
// The C# nodes CE, CS, CH, CC and CS2 are test nodes: each is given a clock the scenario sets, timers the scenario
// runs and literal draws, through NodeEnvironment, the extension's ordinary construction interface. No frame reaches
// any of that. CP is not a test node: it is started with NodeEnvironment.System(), reads the machine's clock and runs
// its own timers. The lines of each C# node (the extension's own lines, and one line for everything its application
// is told) are written to NAME.sout.
//
// What this program cannot do is asked of the trial tool (walk.py beside this file), one line `@request` on the
// standard output answered by one line on the standard input: starting and stopping a Silica node process, waiting
// for a line of its output, sending a Silica test node the test-only tick frame, and playing a peer that misbehaves.
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using Bees.Tempus;
using Bees.Tempus.Testing;

static class Net
{
    sealed class Died : Exception { }

    static void Die(string what)
    {
        Console.WriteLine("FAIL: " + what);
        throw new Died();
    }

    static void Must(bool cond, string what) { if (!cond) Die(what); }

    static string Tool(string request)
    {
        Console.WriteLine("@" + request);
        string answer = Console.ReadLine();
        if (answer == null) Die("the trial tool went away");
        if (!answer.StartsWith("ok")) Die("the trial tool, asked `" + request + "`: " + answer);
        return answer.Substring(2).Trim();
    }

    // a Silica node's connection actor is reaped half a second after its close: steps stand apart
    static void Quiet(int ms = 700) => Thread.Sleep(ms);

    static string Id8(Descriptor d) => Hex.Of(d.Id, 4);
    static byte[] B(string s) => Encoding.UTF8.GetBytes(s);

    // the side whose peer closed learns of it at whichever step it had reached (as tools/bees_tempus_reports.py writes it)
    static string Normal(string line) => Regex.Replace(line, @"^(\[tempus audit\] closed_by_peer) peer=\S+ stage [a-z_]+", "$1 peer=(any) stage (any)");

    // what a misbehaving peer saw, without what differs between two nodes (their identifiers and what their stores hold)
    static string Brief(string saw) => Regex.Replace(saw, @" (entries|peer|typ|store)=\S+", "");

    static string Shown(Outcome o)
    {
        if (!(o.Body is Body.Entries b)) { Die("no entries in: " + o.Line()); return null; }
        return b.List.Count == 0 ? "(empty)" : string.Join(" ", b.List.Select(e => Id8(e.D) + "@" + e.Age));
    }

    static string After(string text, string prefix) => text.StartsWith(prefix) ? text.Substring(prefix.Length) : text;

    /// One node of the C# extension, hosted by this program, with what the scenario drives it by.
    sealed class Hosted
    {
        public readonly string Name; public readonly Lines Lines; public readonly TestClock Clock; public readonly ManualTimers Timers;
        public TempusNode Node;
        int mark;

        public Hosted(string name, Lines lines, TestClock clock, ManualTimers timers) { Name = name; Lines = lines; Clock = clock; Timers = timers; }

        /// the application of the node: one line for everything it is told
        public void Application(TempusNode n, NodeEvent e)
        {
            switch (e)
            {
                case NodeEvent.ViewChanged x: Lines.Add("view " + x.Store + ":" + (x.Entries.Count == 0 ? " (empty)" : string.Concat(x.Entries.Select(i => " " + Id8(i.D) + "@" + i.Age)))); break;
                case NodeEvent.OwnTokenInvalid x: Lines.Add("application: told that the node's own token is not valid any more: " + x.Why); break;
                case NodeEvent.KeyRotated x: Lines.Add("application: told that a peer " + (x.Dialed ? "this node dialed" : "that dialed this node") + " answered key_rotated, its current kid is " + Encoding.UTF8.GetString(x.Kid)); break;
                case NodeEvent.ClockUnreadable x: Lines.Add("application: told (86) " + x.What); break;
                case NodeEvent.Stopped x: Lines.Add("application: told (87) " + x.Why); break;
                case NodeEvent.ListenFailed x: Lines.Add("application: told that the node cannot listen: " + x.Why); break;
            }
        }

        public string Await(string pattern, long waitMs = 20000)
        {
            string got = Lines.Await(pattern, waitMs);
            if (got == null) Die("node " + Name + " did not write /" + pattern + "/ in time; its lines so far:\n" + string.Join("\n", Lines.Snapshot()));
            return got;
        }

        // the node arms a timer again when it has taken what the timer brought: the scenario waits for that
        void Armed(string timer)
        {
            long until = Tls.NowMs() + 5000;
            while (!Timers.Armed(timer))
            {
                if (Tls.NowMs() > until) Die("node " + Name + " has no timer `" + timer + "` armed");
                Thread.Sleep(20);
            }
        }

        /// runs the node's armed timer of that name, as if its time had come
        public void Fire(string timer) { Armed(timer); Timers.Fire(timer); }

        /// the clock reader's timer fires with this reading (null: the clock could not be read)
        public void Reading(long? seconds) { Armed("clock"); Clock.Reading = seconds; Timers.Fire("clock"); }

        /// the audit lines since this was last asked, as the trial tool gives a Silica node's
        public string Audit()
        {
            Quiet();
            var all = Lines.Snapshot().Where(l => l.StartsWith("[tempus audit] ")).ToList();
            var fresh = all.Skip(mark).ToList();
            mark = all.Count;
            return string.Join(" / ", fresh.Where(l => !l.Contains(" tls_established ")).Select(l => Normal(Regex.Replace(l, @" [ad]\d+$", ""))));
        }

        public int Count(Func<string, bool> which) => Lines.Snapshot().Count(which);

        public void Write(string leaf) =>
            File.WriteAllText(Path.Combine(leaf, Name + ".sout"), string.Concat(Lines.Snapshot().Select(Normal).Concat(new[] { "exit=0" }).Select(l => l + "\n")));
    }

    static int Main(string[] argv)
    {
        Console.SetOut(new StreamWriter(Console.OpenStandardOutput()) { AutoFlush = true });
        try { Run(argv); return 0; }
        catch (Died) { return 1; }
        catch (Exception e) { Console.WriteLine("FAIL: the program ended with " + e.GetType().Name + ": " + e.Message); return 1; }
    }

    static void Run(string[] argv)
    {
        string root = argv[0];
        int port = int.Parse(argv[1]);
        string leaf = argv[2];
        var certs = new Certs(root);
        var producerPub = Hex.Parse(Fixtures.Constant(File.ReadAllText(Path.Combine(leaf, "lib", "tempus_ids.silica")), "producer_pub_hex"));
        string Addr(int k) => "127.0.0.1:" + (port + k);
        string sAddr = Addr(0), aAddr = Addr(1), ceAddr = Addr(2), csAddr = Addr(3), cpAddr = Addr(4), qAddr = Addr(5), pAddr = Addr(6), dead = Addr(7);
        // the tempus whitelist of every node of this trial, in the order the Silica nodes number it (node.role)
        var whitelist = new[]
        {
            new KeyValuePair<string, Certificate>("s", certs.Cert("sentinel")), new KeyValuePair<string, Certificate>("cs", certs.Cert("bridge")),
            new KeyValuePair<string, Certificate>("cp", certs.Cert("x1")),
        };
        var prints = whitelist.Select(w => w.Value.Fingerprint).ToArray();
        var hosted = new List<Hosted>();
        var none = new SentinelAddress[0];

        TempusConfig Config(string role, int p, IReadOnlyList<SentinelAddress> sentinels, string back, long? limit, string fail, long edgeTick = 1000) =>
            new TempusConfig(role, "127.0.0.1", p, sentinels, new StoreConfig(4, 3, edgeTick), new StoreConfig(4, 2, 3600000), new StoreConfig(4, 2, 3600000),
                B("k1"), producerPub, whitelist, 2000, 2, 10000, back, limit, fail, 1000, 200, 800);

        // a test node: its clock begins at the trial's value, 1500; its draws are the Silica test nodes' literal list
        Hosted TestNode(string name, string role, int p, Identity me, IReadOnlyList<SentinelAddress> sentinels, string back = "follow", long? limit = null, string fail = "pause")
        {
            var h = new Hosted(name, new Lines(), new TestClock(1500), new ManualTimers());
            h.Node = TempusNode.Start(Config(role, p, sentinels, back, limit, fail), me, h.Application, TestEnvironment.Of(h.Clock, h.Timers, new long[] { 0, 1, 2, 3 }, h.Lines));
            hosted.Add(h);
            return h;
        }

        // the trial's own peer: the extension's client half, as an edge whose certificate no node lists
        var settings = new Settings(5000, 3);
        var verifier = new Verifier(producerPub, B("k1"), () => 1500, 10, prints);
        var x3 = certs.Identity("x3", "tempus_edge", 1000, 3000, pAddr);
        var x2 = certs.Identity("x2", "tempus_edge", 1000, 3000, dead);
        Outcome Ask(string to, Request request)
        {
            var o = Client.Dial(to, x3, verifier, request, settings);
            Must(o.What == "reply", "a request to " + to + " was not answered: " + o.Line());
            Quiet();
            return o;
        }
        string Sampled(string to, string store) => Shown(Ask(to, new Request.Sample(store, store == "tempus_edge" ? 3 : 2)));
        void Step(string label, string text) => Console.WriteLine(label + ": " + text);
        string IdOf(string name) => Hex.Of(Crypto.PeerId(certs.Cert(name).TempusKey()), 4);

        string sId = IdOf("sentinel"), aId = IdOf("node"), ceId = IdOf("other"), x2Id = IdOf("x2");
        var sentinelS = new[] { new SentinelAddress("127.0.0.1", port, "s") };
        var sentinelCs = new[] { new SentinelAddress("127.0.0.1", port + 3, "cs") };

        // ---------------------------------------------------------------- A
        Console.WriteLine("== A. the C# node CE joins through the Silica sentinel S");
        Tool("start s");
        var ce = TestNode("ce", "edge", port + 2, certs.Identity("other", "tempus_edge", 1000, 3000, ceAddr), sentinelS);
        ce.Await("^join: done$");
        Tool("wait s ^view tempus_edge: " + ceId + "@0$");
        Quiet();
        Step("A1 CE asked S for its three stores and S holds CE in its edge store", "yes");
        Step("A2 CE keeps the sentinel it joined through; its sentinel store", Sampled(ceAddr, "tempus_sentinel"));
        Must(ce.Count(l => l == "view tempus_sentinel: " + sId + "@0") == 4, "CE did not put S into its sentinel store after each answer");

        // ---------------------------------------------------------------- B
        Console.WriteLine("== B. the Silica node A joins through the C# sentinel CS");
        var cs = TestNode("cs", "sentinel", port + 3, certs.Identity("bridge", "tempus_sentinel", 1000, 3000, csAddr), none);
        cs.Await("^join: no sentinel is configured$");
        Tool("start a");
        cs.Await("^view tempus_edge: " + aId + "@0$");
        Quiet();
        Must(cs.Count(l => l.Contains(" admitted peer=" + aId)) == 3, "CS did not admit A three times");
        Step("B1 A asked CS for its three stores and CS holds A in its edge store", "yes");
        Step("B2 A keeps the sentinel it joined through; its sentinel store", Sampled(aAddr, "tempus_sentinel"));

        // ---------------------------------------------------------------- C
        Console.WriteLine("== C. shuffles started by each side and answered by the other");
        Ask(ceAddr, new Request.Shuffle("tempus_edge", new[] { x2.Entry(3) }));
        Step("C1 a peer shuffles an entry for x2 (age 3) into CE; CE's edge store", Sampled(ceAddr, "tempus_edge"));
        Ask(aAddr, new Request.Shuffle("tempus_edge", new[] { certs.Identity("other", "tempus_edge", 1000, 3000, ceAddr).Entry(5) }));
        Step("C2 a peer shuffles CE's entry (age 5) into A; A's edge store", Sampled(aAddr, "tempus_edge"));
        Tool("tick a tempus_edge");
        Tool("wait a ^tick tempus_edge: shuffle merged$");
        ce.Await("^view tempus_edge: " + aId + "@0 " + x2Id + "@3$");
        Step("C3 A ticks: it shuffles with CE, which answers with x2; A's edge store", Sampled(aAddr, "tempus_edge"));
        Step("C3 CE holds A, whose entry came in the shuffle; CE's edge store", Sampled(ceAddr, "tempus_edge"));
        ce.Fire("tick tempus_edge");
        ce.Await(@"^tick tempus_edge: the partner did not answer, connect_failed d\d+$");
        ce.Await("^tick tempus_edge: shuffle failed$");
        Step("C4 CE ticks: its oldest entry is x2, where nobody listens; the partner is dropped, the entry sent is put back; CE's edge store", Sampled(ceAddr, "tempus_edge"));
        ce.Fire("tick tempus_edge");
        ce.Await("^tick tempus_edge: shuffle merged$");
        Tool("wait a ^view tempus_edge: " + ceId + "@0");
        Quiet();
        Step("C5 CE ticks: it shuffles with A, which answers; A's edge store", Sampled(aAddr, "tempus_edge"));
        Step("C5 CE's edge store", Sampled(ceAddr, "tempus_edge"));
        Tool("tick s tempus_edge");
        Tool("wait s ^tick tempus_edge: shuffle merged$");
        Step("C6 S ticks its edge store, which is not of its own type: it shuffles with CE without an entry of its own and keeps CE", "merged");
        cs.Fire("tick tempus_edge");
        cs.Await("^tick tempus_edge: shuffle merged$");
        string csView = cs.Lines.Snapshot().Last(l => l.StartsWith("view tempus_edge:"));
        Must(csView.Contains(aId + "@0"), "CS did not put the partner that answered back at age 0");
        Step("C7 CS ticks its edge store: it shuffles with A and puts A back at age 0 (ruling NQ-15); CS's edge view", After(csView, "view tempus_edge: "));
        ce.Fire("tick tempus_sentinel");
        ce.Await("^tick tempus_sentinel: shuffle merged$");
        Step("C8 CE ticks its sentinel store: it shuffles with S, a sentinel of its whitelist", "merged");
        Tool("tick a tempus_sentinel");
        Tool("wait a ^tick tempus_sentinel: shuffle merged$");
        Step("C9 A ticks its sentinel store: it shuffles with CS, a sentinel of its whitelist", "merged");

        // ---------------------------------------------------------------- D
        Console.WriteLine("== D. what the Silica node A refuses, the C# node CE refuses, with the same audit lines");
        Tool("audit a"); ce.Audit();
        int k = 0;
        void Both(string mode, string what)
        {
            k += 1;
            string saw = Brief(Tool("pydial a " + mode));
            string silica = Tool("audit a");
            string saw2 = Brief(Tool("pydial ce " + mode));
            string mine = ce.Audit();
            Must(silica == mine, "D" + k + " " + what + ": the Silica node wrote `" + silica + "`, the C# node `" + mine + "`");
            Must(saw == saw2, "D" + k + " " + what + ": the peer saw `" + saw + "` of the Silica node and `" + saw2 + "` of the C# node");
            Must(silica.Length > 0, "D" + k + " " + what + ": neither node wrote an audit line");
            Step("D" + k + " " + what, "the peer sees: " + saw + "; both nodes: " + After(silica, "[tempus audit] "));
        }
        Both("good", "a good peer's sample");
        Both("expired", "an expired token");
        Both("not-yet", "a token not valid yet");
        Both("old-kid", "a token under an old kid");
        Both("old-kid-expired", "a token under an old kid that has also expired");
        Both("forged", "a token another key signed");
        Both("other-sub", "a token issued for another key");
        Both("not-a-token", "a token that is not a token");
        Both("sentinel-token", "a sentinel token under a certificate that is not in the whitelist");
        Both("bridge-token", "a bridge token under a certificate that is not in the whitelist");
        Both("listed-edge", "a certificate of the whitelist with an edge token");
        Both("binding", "an advert for another key than the certificate's");
        Both("id-not-hash", "an advert whose id is not the hash of its pub");
        Both("short-id", "an advert whose id is 63 bytes");
        Both("ver2", "an advert of version 2");
        Both("sample-as-advert", "a sample where the advert is due");
        Both("proof-other-key", "a proof made with another key");
        Both("proof-other-nonce", "a proof over another nonce");
        Both("proof-63", "a proof of 63 bytes");
        Both("no-proof", "no proof");
        Both("wrong-frame", "a sample where the challenge is due");
        Both("oversize-advert", "an advert above the frame ceiling");
        Both("oversize-request", "a request above the frame ceiling");
        Both("closes", "a peer that closes after its advert");
        Both("silent-challenge", "a peer that is silent where its challenge is due, past the connection's one bound");
        Both("sample-9", "a sample of 9 where the shuffle length is 3");
        Both("sample-3-bridge", "a sample of 3 from the bridge store, whose shuffle length is 2");
        Both("sample-0", "a sample of 0");
        Both("four-entries", "four entries where the greatest shuffle length is 3");
        Both("three-entries-bridge", "three entries of edges for the bridge store, whose shuffle length is 2");
        Both("three-bridges", "three entries of bridges for the bridge store, whose shuffle length is 2");
        Both("forged-shuffle", "a shuffle with an entry another key signed");
        Both("expired-entry", "a shuffle with an entry whose token has expired");
        Both("other-store", "an edge's entry offered to the sentinel store");
        Both("age-65536", "an entry of age 65536");
        Both("no-kind", "a frame whose t is no kind");
        Both("an-advert", "an advert where a request is due");
        Both("reply-as-request", "a reply where a request is due");
        Both("not-a-map", "a request that is not a map");
        Both("call", "a call, which only a bridge serves");
        Both("cast", "a cast, which only a bridge serves");
        Both("call-unknown", "a call that names a module and a function the node holds no atom for");
        Both("trailing", "a request with a byte after it");
        k += 1;
        string heldA = Tool("inflight a"), linesA = Tool("audit a");
        string heldC = Tool("inflight ce"), linesC = ce.Audit();
        Must(linesA == linesC && heldA == heldC, "D" + k + " inflight_max: the Silica node `" + heldA + "` `" + linesA + "`, the C# node `" + heldC + "` `" + linesC + "`");
        Must(linesC.Contains("inflight_refused peer=- more accepted connections than inflight_max: closed at once"), "D" + k + " no inflight_refused line: " + linesC);
        Step("D" + k + " two connections held open and a third (inflight_max is 2)", heldC + "; both nodes: " + After(linesC, "[tempus audit] "));
        Both("tls12", "a peer that offers TLS 1.2 only");
        Both("alpn", "a peer that offers another ALPN protocol");
        Both("p256", "a peer whose certificate has a P-256 key");
        Both("no-cert", "a peer that presents no certificate");
        Step("D the stores after all of it; A's edge store", Sampled(aAddr, "tempus_edge"));
        Step("D CE's edge store", Sampled(ceAddr, "tempus_edge"));
        ce.Node.Dispose(); cs.Node.Dispose();
        Quiet(1000);

        // ---------------------------------------------------------------- E
        Console.WriteLine("== E. the clock's choices, the node's own token and key_rotated, on C# nodes whose clock the trial sets");
        var ch = TestNode("ch", "edge", port + 2, certs.Identity("other", "tempus_edge", 1000, 2000, ceAddr), sentinelS, back: "hold", fail: "continue");
        ch.Await("^join: done$");
        Quiet();
        ch.Reading(1450);
        Step("E1 hold: the clock reads 1450 after 1500", After(ch.Await("^clock: the system clock went back by 50 s; the node holds its time"), "clock: "));
        ch.Audit();
        Must(Tool("pydial ch short") == "closed", "E2 a token that ended at 1480 was served by the held time 1500");
        Step("E2 it admits by the held time: a token that ended at 1480", After(ch.Audit(), "[tempus audit] "));
        Must(Tool("pydial ch good").StartsWith("reply"), "E2 a good peer was not served while the node holds its time");
        ch.Fire("tick tempus_sentinel");
        Step("E2 and it ticks", ch.Await("^tick tempus_sentinel: shuffle merged$"));
        ch.Reading(1460);
        ch.Reading(1500);
        Step("E3 a reading still behind (1460) says nothing; 1500 ends the hold", After(ch.Await("^clock: the system clock has reached the held time"), "clock: "));
        Must(ch.Count(l => l.StartsWith("clock: ")) == 3, "E3 the reading that was still behind wrote a line");
        ch.Reading(null);
        Step("E4 continue: the clock cannot be read", After(ch.Await("^clock: the system clock could not be read: the node goes on with its last reading$"), "clock: "));
        ch.Await(@"^application: told \(86\)");
        Must(Tool("pydial ch good").StartsWith("reply"), "E4 a good peer was not served while the node goes on with its last reading");
        ch.Reading(1510);
        ch.Reading(null);
        ch.Await(@"^application: told \(86\)");
        Step("E5 the next good reading says nothing; a second failure is told again", "yes");
        ch.Reading(2600);
        ch.Fire("tick tempus_sentinel");
        Step("E6 the clock reads 2600, past the node's own token (valid to 2000); the next tick", After(ch.Await("^own token: "), "own token: "));
        ch.Await("^application: told that the node's own token is not valid any more: the token has expired$");
        ch.Fire("tick tempus_sentinel");
        ch.Node.SetToken(certs.Identity("other", "tempus_edge", 1000, 4000, ceAddr).Token);
        ch.Await("^own token replaced$");
        ch.Fire("tick tempus_sentinel");
        Step("E7 its application passes a new token and it ticks again", ch.Await("^tick tempus_sentinel: shuffle merged$"));
        Must(ch.Count(l => l.StartsWith("own token: ")) == 1, "E7 the stop for the node's own token was said more than once");
        // key_rotated: CH dials a peer whose verifier names another kid
        var late = new Verifier(producerPub, B("k1"), () => 2600, 10, null);
        var x3late = certs.Identity("x3", "tempus_edge", 1000, 4000, pAddr);
        Must(Client.Dial(ceAddr, x3late, late, new Request.Shuffle("tempus_edge", new[] { x3late.Entry(9) }), settings).What == "reply", "E8 the shuffle into CH was not answered");
        Quiet();
        Tool("peer names-k9");
        ch.Fire("tick tempus_edge");
        ch.Await("^application: told that a peer this node dialed answered key_rotated, its current kid is k9$");
        Step("E8 a partner answers CH's advert with key_rotated; the tick", Regex.Replace(ch.Await(@"^tick tempus_edge: the partner did not answer, key_rotated d\d+$"), @" d\d+$", ""));
        ch.Await("^tick tempus_edge: shuffle failed$");
        Tool("peerdone");
        // key_rotated on a connection CH accepted: the dialing peer names another kid. The Silica node writes the audit
        // line and does not tell its application; this extension tells it, and says that the peer had dialed.
        ch.Audit();
        var k9 = new Verifier(producerPub, B("k9"), () => 2600, 10, null);
        var o9 = Client.Dial(ceAddr, x3late, k9, new Request.Sample("tempus_edge", 1), settings);
        Must(o9.What == "refused" && o9.Reason == "key_rotated", "E9 the dialing peer did not answer key_rotated: " + o9.Line());
        ch.Await("^application: told that a peer that dialed this node answered key_rotated, its current kid is k9$");
        Step("E9 a peer that dialed CH answers CH's advert with key_rotated; CH's audit line, and its application is told", After(ch.Audit(), "[tempus audit] "));
        ch.Node.Dispose();
        Quiet(1000);

        var cc = TestNode("cc", "edge", port + 2, certs.Identity("other", "tempus_edge", 1000, 3000, ceAddr), sentinelCs, back: "stop", limit: 60, fail: "pause");
        cc.Await("^join: no sentinel answered for tempus_edge; waiting to try again$");
        cc.Reading(null);
        Step("E10 pause: the clock cannot be read", After(cc.Await("^clock: the system clock could not be read: the node admits no connection"), "clock: "));
        cc.Await(@"^application: told \(86\)");
        cc.Audit();
        string shut = Tool("pydial cc good");
        Must(shut == "closed" || shut == "tls_failed", "E11 a connection to the waiting node was not closed: " + shut);
        Step("E11 an accepted connection is closed at once", After(cc.Audit(), "[tempus audit] "));
        cc.Fire("join tempus_edge");
        Step("E12 the join's retry falls due", After(cc.Await("^join: the request for tempus_edge waits until the system clock is read again$"), "join: "));
        cc.Fire("tick tempus_edge");
        var cs2 = TestNode("cs2", "sentinel", port + 3, certs.Identity("bridge", "tempus_sentinel", 1000, 3000, csAddr), none);
        cs2.Await("^join: no sentinel is configured$");
        cc.Reading(1500);
        cc.Await("^clock: the system clock is read again$");
        cc.Await("^join: done$");
        Must(cc.Count(l => l.StartsWith("tick ")) == 0, "E13 the waiting node ticked");
        Step("E13 the clock is read again: the waiting request is dialed at once and the join is done; a tick meanwhile did nothing", "yes");
        Quiet();
        cc.Reading(1470);
        Step("E14 stop with a limit of 60 s: a step back of 30 s", After(cc.Await("^clock: the system clock went back by 30 s; the node follows it$"), "clock: "));
        Must(Tool("pydial cc good").StartsWith("reply"), "E14 a good peer was not served after the step back that was followed");
        cc.Reading(1370);
        Step("E15 a step back of 100 s", After(cc.Await("^clock: the system clock went back by 100 s, more than clock_back_limit_s 60: the node has stopped"), "clock: "));
        cc.Await(@"^application: told \(87\)");
        cc.Audit();
        string shut2 = Tool("pydial cc good");
        Must(shut2 == "closed" || shut2 == "tls_failed", "E16 a connection to the stopped node was not closed: " + shut2);
        Step("E16 an accepted connection is closed at once", After(cc.Audit(), "[tempus audit] "));
        cc.Reading(2000);
        cc.Fire("tick tempus_edge");
        string shut3 = Tool("pydial cc good");
        Must(shut3 == "closed" || shut3 == "tls_failed", "E17 the stopped node served a connection after a later good reading: " + shut3);
        Step("E17 a later good reading changes nothing: no line, no tick, and a connection", After(cc.Audit(), "[tempus audit] "));
        Must(cc.Count(l => l.StartsWith("clock: ")) == 5 && cc.Count(l => l.StartsWith("tick ")) == 0, "E17 the stopped node wrote a clock line or ticked");
        cc.Node.Dispose(); cs2.Node.Dispose();
        Tool("stop a"); Tool("stop s");

        // ---------------------------------------------------------------- F
        Console.WriteLine("== F. a C# node that is not a test node: the machine's clock, its own timers, secure random draws");
        var cp = new Hosted("cp", new Lines(), null, null);
        const long far = 4000000000L;
        cp.Node = TempusNode.Start(Config("sentinel", port + 4, none, "follow", null, "pause", edgeTick: 20000),
            certs.Identity("x1", "tempus_sentinel", 1000, far, cpAddr), cp.Application, NodeEnvironment.System(cp.Lines.Add));
        hosted.Add(cp);
        cp.Await("^join: no sentinel is configured$");
        Tool("start q");
        string qId = IdOf("x2");
        cp.Await("^view tempus_edge: " + qId + "@0$");
        Quiet();
        Step("F1 the Silica node Q, not a test node either, joined through CP by the machine's clock on both sides", "yes");
        Tool("audit q"); cp.Audit();
        foreach (var (mode, what) in new[] { ("tick", "the test unit's tick frame"), ("clock", "the test unit's clock frame"), ("clock-later", "the clock frame with a later reading") })
        {
            string saw = Brief(Tool("pydial q " + mode)), silica = Tool("audit q");
            string saw2 = Brief(Tool("pydial cp " + mode)), mine = cp.Audit();
            // Both refuse it as a frame that is no request. The last word may differ: Q's program is built in this leaf,
            // whose atom table also serves the two test programs, so Q holds the atoms `tick` and `clock` and says
            // "unknown kind"; a Silica program built without the test unit (node P of trials/t6_tempus_clock) does not
            // hold them and says "unknown_atom", as the C# node does.
            var head = new Regex(@"^\[tempus audit\] admitted peer=\S+ tempus_edge, token and proof of possession / \[tempus audit\] protocol_error peer=\S+ not a request: ");
            Must(saw == saw2 && head.IsMatch(silica) && head.IsMatch(mine), "F2 " + what + ": the Silica node wrote `" + silica + "` (" + saw + "), the C# node `" + mine + "` (" + saw2 + ")");
            Step("F2 " + what, "the peer sees: " + saw + "; Q: " + silica.Substring(silica.LastIndexOf("] ") + 2) + "; CP: " + mine.Substring(mine.LastIndexOf("] ") + 2));
        }
        cp.Await("^tick tempus_edge: shuffle merged$", 45000);
        Step("F3 CP's own timer ticked its edge store: it shuffled with Q", "merged");
        var real = new Verifier(producerPub, B("k1"), Verifier.SystemSeconds, 10, prints);
        var x3far = certs.Identity("x3", "tempus_edge", 1000, far, pAddr);
        var o = Client.Dial(qAddr, x3far, real, new Request.Sample("tempus_sentinel", 2), settings);
        Must(o.What == "reply", "F4 Q did not answer: " + o.Line());
        Step("F4 Q keeps CP in its sentinel store", Shown(o));
        Quiet();
        Tool("stop q");
        cp.Node.Dispose();

        foreach (var h in hosted) h.Write(leaf);
        Console.WriteLine("[c13_tempus_node_csharp] every step passed");
    }
}
