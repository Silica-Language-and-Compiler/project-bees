// C12: the walk of the client half of the C# extension (example_tempus_clients/csharp) against real nodes on
// 127.0.0.1. TEST CODE of this trial; it is not part of the extension. It uses the extension as an application would
// (Client.Dial, Listener) with the TEST ONLY identities of tools/bees_tempus_certs.py, checks every step, and prints
// one line per step. Nothing printed depends on the time of day.
//
// What a client cannot do is asked of the trial tool (walk.py beside this file), one line `@request` on the
// standard output answered by one line on the standard input: starting and stopping a node process, waiting for a
// line of a node's output, sending a test node the test-only tick frame (with the Python test support: the C#
// extension has no such frame), and playing a peer that misbehaves (the Python test support, which can do that on
// purpose).
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Threading;
using Bees.Tempus;
using Bees.Tempus.Testing;

static class Walk
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

    // a node's connection actor is reaped half a second after its close: steps stand apart, so a node's lines come in one order
    static void Quiet(int ms = 700) => Thread.Sleep(ms);

    // the text of a failed handshake is the TLS library's own and differs between its versions
    static string Line(Outcome o) => o.What == "tls_failed" ? "tls_failed at=" + o.Stage : o.Line();

    static Outcome Step(string label, Outcome o, int wait = 700)
    {
        Console.WriteLine(label + ": " + Line(o));
        Quiet(wait);
        return o;
    }

    static List<string> ViewOf(Outcome o)
    {
        if (!(o.Body is Body.Entries b)) { Die("no entries in: " + o.Line()); return null; }
        return b.List.Select(e => e.D.Id8() + "@" + e.Age).ToList();
    }

    static bool Same(IEnumerable<string> a, params string[] b) => a.SequenceEqual(b);
    static byte[] B(string s) => Encoding.UTF8.GetBytes(s);
    static string Text(byte[] b) => b == null ? null : Encoding.UTF8.GetString(b);

    static int Main(string[] argv)
    {
        Console.SetOut(new StreamWriter(Console.OpenStandardOutput()) { AutoFlush = true });
        try { Run(argv); return 0; }
        catch (Died) { return 1; }
        catch (Exception e) { Console.WriteLine("FAIL: the walk ended with " + e.GetType().Name + ": " + e.Message); return 1; }
    }

    static void Run(string[] argv)
    {
        string root = argv[0];
        int port = int.Parse(argv[1]);
        var certs = new Certs(root);
        var producerPub = Hex.Parse(Fixtures.Constant(File.ReadAllText(Path.Combine(root, "trials/c12_tempus_csharp/lib/tempus_ids.silica")), "producer_pub_hex"));
        string kAddr = "127.0.0.1:" + port;                 // node K, a test node
        string qAddr = "127.0.0.1:" + (port + 1);           // node Q, not a test node
        string sAddr = "127.0.0.1:" + (port + 2);           // this client's sentinel listener
        string eAddr = "127.0.0.1:" + (port + 3);           // this client's edge listener
        string pAddr = "127.0.0.1:" + (port + 4);           // the trial tool's Python peer
        string dead = "127.0.0.1:" + (port + 5);            // nobody listens here
        var settings = new Settings(5000, 3);        // node K: shuffle_timeout_ms 2000, shuffle length 3 (edge store)
        var wide = new Settings(5000, 64);           // a client configured for another network's shuffle length
        Verifier V(long now = 1500, string kid = "k1", string[] whitelist = null) => new Verifier(producerPub, B(kid), () => now, 10, whitelist);
        var producer = Fixtures.Key(0);
        var sentinel = certs.Identity("sentinel", "tempus_sentinel", 1000, 3000, sAddr);
        var edge = certs.Identity("other", "tempus_edge", 1000, 3000, eAddr);
        string Id(string name) => Hex.Of(Crypto.PeerId(certs.Cert(name).TempusKey()), 8);
        string nodeId = Id("node");
        Entry X(string name, int age, string typ = "tempus_edge", long exp = 2000) => certs.Identity(name, typ, 1000, exp, dead).Entry(age);
        byte[] Token(SigningKey signer = null, string kid = "k1", byte[] sub = null, string typ = "tempus_edge", long nbf = 1000, long exp = 2000) =>
            Fixtures.MakeToken(signer ?? producer, kid, sub ?? edge.Pub, typ, nbf, exp);
        var sample3 = new Request.Sample("tempus_edge", 3);
        Outcome o;

        // ---------------------------------------------------------------- A
        Console.WriteLine("== A. node K joins through this client, which listens as a sentinel");
        var ls = new Listener(sentinel, V(), settings, "127.0.0.1", port + 2, rq =>
        {
            if (rq.Body is Body.Sample s) return s.Store == "tempus_edge" ? new[] { X("x1", 1) } : s.Store == "tempus_bridge" ? new Entry[0] : new[] { sentinel.Entry(0) };
            return new[] { X("bridge", 1, typ: ((Body.Entries)rq.Body).Store) };
        });
        Tool("start k");
        var joined = ls.Outcomes(3, 10000);
        for (int i = 0; i < joined.Count; i++) Console.WriteLine("A1 the join, request " + (i + 1) + ", served: " + joined[i].Line());
        Must(joined.Count == 3 && Same(joined.Select(j => (j.Body as Body.Sample)?.Store), "tempus_edge", "tempus_bridge", "tempus_sentinel"),
            "A1: the join did not ask this sentinel for the three stores, one sample each");
        Must(joined.All(j => j.What == "served" && j.Sent == "reply" && j.Typ == "tempus_edge" && j.Advert?.Id8() == nodeId), "A1: the joiner was not admitted as the node it is");
        Quiet();
        o = Step("A2 sample of K's sentinel store", Client.Dial(kAddr, sentinel, V(), new Request.Sample("tempus_sentinel", 2), settings));
        Must(o.What == "reply" && Same(ViewOf(o), Id("sentinel") + "@0"), "A2: K did not keep the sentinel it joined through at age 0");
        Tool("tick k tempus_sentinel");
        var four = ls.Outcomes(4, 8000);
        if (four.Count < 4) Die("A3: K did not shuffle its sentinel store with this sentinel");
        var shuffled = four[3];
        Console.WriteLine("A3 a tick of K's sentinel store, served: " + shuffled.Line());
        Must(shuffled.What == "served" && shuffled.Body is Body.Entries sb && sb.Name == "shuffle" && sb.Store == "tempus_sentinel" && sb.List.Count == 0,
            "A3: the shuffle of the sentinel store by an edge holds an entry");
        Quiet();
        o = Step("A4 sample of K's sentinel store", Client.Dial(kAddr, sentinel, V(), new Request.Sample("tempus_sentinel", 2), settings));
        Must(o.What == "reply" && ViewOf(o).OrderBy(x => x, StringComparer.Ordinal).SequenceEqual(new[] { Id("bridge") + "@1", Id("sentinel") + "@0" }.OrderBy(x => x, StringComparer.Ordinal)),
            "A4: the sentinel store after its shuffle");
        o = Step("A5 sample of K's bridge store", Client.Dial(kAddr, sentinel, V(), new Request.Sample("tempus_bridge", 2), settings));
        Must(o.What == "reply" && ViewOf(o).Count == 0, "A5: the bridge store is not empty");
        ls.Dispose();

        // ---------------------------------------------------------------- B
        Console.WriteLine("== B. this client as an edge: sample, shuffle, and being dialed by K");
        o = Step("B1 sample", Client.Dial(kAddr, edge, V(), sample3, settings));
        Must(o.What == "reply" && Same(ViewOf(o), Id("x1") + "@1") && o.Typ == "tempus_edge" && o.Advert?.Id8() == nodeId, "B1: K's edge store after the join");
        o = Step("B2 shuffle, own entry first at age 0", Client.Dial(kAddr, edge, V(), new Request.Shuffle("tempus_edge", new[] { edge.Entry(0), X("x2", 2) }), settings));
        Must(o.What == "reply" && ((Body.Entries)o.Body).Name == "shuffle_reply", "B2: no shuffle_reply");
        o = Step("B3 sample", Client.Dial(kAddr, edge, V(), sample3, settings));
        Must(o.What == "reply" && ViewOf(o).Contains(Id("other") + "@0"), "B3: this client is not in K's edge store at age 0");
        var le = new Listener(edge, V(), settings, "127.0.0.1", port + 3, rq => rq.Body is Body.Sample ? new[] { X("x1", 1) } : new[] { X("x3", 4), X("x4", 1) });
        int served = 0, ticks = 0;
        while (served == 0 && ticks < 5)
        {
            ticks += 1;
            Tool("tick k tempus_edge");
            var got = le.Outcomes(1, 1500);
            if (got.Count == 0) Console.WriteLine("B4 tick " + ticks + " of K's edge store: K did not dial this client");
            else
            {
                Console.WriteLine("B4 tick " + ticks + " of K's edge store, served: " + got[0].Line());
                var b = got[0].Body as Body.Entries;
                if (b == null) Die("B4: no shuffle");
                Must(got[0].What == "served" && b.Name == "shuffle" && b.Store == "tempus_edge" && b.List.Count > 0 && b.List[0].D.Id8() == nodeId && b.List[0].Age == 0,
                    "B4: the shuffle does not begin with the node's own entry at age 0");
                served = 1;
            }
            Quiet();
        }
        Must(served == 1, "B4: K never shuffled with this client");
        o = Step("B5 sample", Client.Dial(kAddr, edge, V(), sample3, settings));
        Must(o.What == "reply" && ViewOf(o).Contains(Id("x3") + "@4") && ViewOf(o).Contains(Id("x4") + "@1"), "B5: what this client answered is not in K's edge store");

        // ---------------------------------------------------------------- C
        Console.WriteLine("== C. what K refuses, and what this client refuses of K");
        void Closed(string label, Identity who, Request request = null, Settings with = null)
        {
            var r = Step(label, Client.Dial(kAddr, who, V(), request ?? sample3, with ?? settings));
            Must(r.What == "closed", label + ": the node did not close with no reply");
        }
        Closed("C1 a token another key signed", edge.WithToken(Token(signer: Fixtures.Key(96))));
        Closed("C2 an expired token", edge.WithToken(Token(exp: 1400)));
        Closed("C3 a token not valid yet", edge.WithToken(Token(nbf: 1800)));
        Closed("C4 a token issued for another key", edge.WithToken(Token(sub: certs.Cert("x1").TempusKey())));
        Closed("C5 a bridge token with a certificate K does not list", edge.WithToken(Token(typ: "tempus_bridge")));
        o = Step("C6 a token under an old kid", Client.Dial(kAddr, edge.WithToken(Token(signer: Fixtures.Key(96), kid: "k0")), V(), sample3, settings));
        Must(o.What == "key_rotated" && Text(o.Kid) == "k1", "C6: no key_rotated naming k1");
        Closed("C7 a sample of 9 where K's shuffle length is 3", edge, new Request.Sample("tempus_edge", 9), wide);
        Closed("C8 an edge's entry offered to the sentinel store", edge, new Request.Shuffle("tempus_sentinel", new[] { X("x1", 0) }));
        Closed("C9 four entries where K's shuffle length is 3", edge, new Request.Shuffle("tempus_edge", new[] { edge.Entry(0), X("x1", 1), X("x2", 1), X("x3", 1) }), wide);
        o = Step("C10 a call, to a peer that is not a bridge", Client.Dial(kAddr, edge, V(), new Request.Call(B("c10"), "demo", "add", new Term[] { new TInt(2), new TInt(3) }), settings));
        Must(o.What == "refused" && o.Stage == "request", "C10: the call was sent to a peer that is not a bridge");
        o = Step("C11 this client's clock at 2600: K's token has expired", Client.Dial(kAddr, edge, V(now: 2600), sample3, settings));
        Must(o.What == "refused" && o.Stage == "advert" && o.Reason == "the token has expired", "C11");
        o = Step("C12 this client's clock at 500: K's token is not valid yet", Client.Dial(kAddr, edge, V(now: 500), sample3, settings));
        Must(o.What == "refused" && o.Stage == "advert" && o.Reason == "the token is not valid yet", "C12");
        o = Step("C13 K's certificate in this client's whitelist, K's token an edge's", Client.Dial(kAddr, edge, V(whitelist: new[] { certs.Cert("node").Fingerprint }), sample3, settings));
        Must(o.What == "refused" && o.Reason == "a certificate of the tempus whitelist with a tempus_edge token", "C13");
        o = Step("C14 nobody listens", Client.Dial(dead, edge, V(), sample3, settings));
        Must(o.What == "unreachable", "C14");
        o = Step("C15 this client holds another producer key as current (k9): it answers K's advert with key_rotated", Client.Dial(kAddr, edge, V(kid: "k9"), sample3, settings));
        Must(o.What == "refused" && o.Reason == "key_rotated", "C15");
        // K was dialed, so K's application is not told (it is told when a peer K dialed answers so). K serves on.
        o = Step("C16 sample", Client.Dial(kAddr, edge, V(), sample3, settings));
        Must(o.What == "reply", "C16: K does not serve after C15");
        Tool("stop k");

        // ---------------------------------------------------------------- D
        Console.WriteLine("== D. this client dials a peer that misbehaves (the Python test support, listening)");
        var bridgeList = new[] { certs.Cert("x4").Fingerprint };
        Outcome Against(string label, string mode, Request request = null, Verifier v = null, Settings with = null)
        {
            Tool("peer " + mode);
            var r = Client.Dial(pAddr, edge, v ?? V(), request ?? sample3, with ?? settings);
            Console.WriteLine(label + ": " + Line(r));
            Console.WriteLine(label + ", the peer: " + Tool("peerdone"));
            return r;
        }
        var call = new Request.Call(B("d1"), "demo", "add", new Term[] { new TInt(2), new TInt(3) });
        o = Against("D1 a call to a peer with a bridge token and a whitelisted certificate", "bridge-result", call, V(whitelist: bridgeList));
        Must(o.What == "reply" && o.Body is Body.Result res && new TInt(5).Equals(res.Value), "D1: no result of 5");
        o = Against("D2 a result that names another req_id", "bridge-other-req-id", call, V(whitelist: bridgeList));
        Must(o.What == "refused" && o.Reason == "the result names another req_id", "D2");
        o = Against("D3 a cast", "bridge-cast", new Request.Cast(B("d3"), "demo", "note", new Term[] { new TInt(7) }), V(whitelist: bridgeList));
        Must(o.What == "closed" && o.Stage == "reply", "D3");
        o = Against("D4 a bridge token, the certificate not in this client's whitelist", "bridge-result", call);
        Must(o.What == "refused" && o.Stage == "advert" && o.Reason == "a tempus_bridge whose certificate is not in the tempus whitelist", "D4");
        o = Against("D5 another peer's advert (the channel binding)", "binding");
        Must(o.What == "refused" && o.Stage == "advert" && o.Reason == "the certificate's key is not the advert's pub", "D5");
        o = Against("D6 a proof of possession over another nonce", "wrong-proof");
        Must(o.What == "refused" && o.Stage == "response" && o.Reason == "the proof of possession does not verify", "D6");
        o = Against("D7 the peer answers this client's advert with key_rotated, naming k9", "names-k9");
        Must(o.What == "key_rotated" && Text(o.Kid) == "k9", "D7");
        o = Against("D8 the peer's token is under an old kid: this client answers key_rotated", "old-kid");
        Must(o.What == "refused" && o.Reason == "key_rotated", "D8");
        o = Against("D9 a reply with an entry another key signed, beside a good one", "forged-entry");
        Must(o.What == "refused" && o.Stage == "reply" && o.Reason == "entry 1 does not verify: the signature does not verify", "D9");
        o = Against("D10 a reply that names another store", "other-store");
        Must(o.What == "refused" && o.Reason == "the reply names another store", "D10");
        o = Against("D11 a shuffle_reply where a sample_reply was due", "shuffle-reply");
        Must(o.What == "refused" && o.Reason == "shuffle_reply where sample_reply was due", "D11");
        o = Against("D12 more entries than were asked for", "three-entries", new Request.Sample("tempus_edge", 1));
        Must(o.What == "refused" && o.Reason == "more entries than were asked for", "D12");
        o = Against("D13 a reply above the frame ceiling", "oversize");
        Must(o.What == "refused" && o.Reason == "a frame above the ceiling", "D13");
        o = Against("D14 the peer closes with no reply", "closes");
        Must(o.What == "closed" && o.Stage == "reply", "D14");
        o = Against("D15 the peer stays silent: this client's one time bound ends the connection", "silent", with: new Settings(1500, 3));
        Must(o.What == "timeout" && o.Stage == "reply", "D15");
        o = Against("D16 a sample where the peer's challenge was due", "wrong-frame");
        Must(o.What == "refused" && o.Stage == "challenge" && o.Reason == "sample where pop_challenge or key_rotated was due", "D16");
        o = Against("D17 the answer of the test unit's frames (done) as a reply", "done");
        Must(o.What == "refused" && o.Reason == "unknown kind", "D17");
        o = Against("D18 a certificate another key issued", "issued");
        Must(o.What == "refused" && o.Stage == "tls" && o.Reason == "the certificate is not self-signed", "D18");
        o = Against("D19 a P-256 certificate", "p256");
        Must((o.What == "refused" || o.What == "tls_failed") && o.Stage == "tls", "D19");
        o = Against("D20 a peer that speaks TLS 1.2 only", "tls12");
        Must(o.What == "tls_failed" && o.Stage == "tls", "D20");
        o = Against("D21 a peer with another ALPN protocol", "alpn");
        Must((o.What == "refused" || o.What == "tls_failed") && o.Stage == "tls", "D21");

        // ---------------------------------------------------------------- E
        Console.WriteLine("== E. this client listens and is dialed by a peer that misbehaves (the Python test support, dialing)");
        int index = le.Outcomes(1, 0).Count;
        Outcome Dialed(string label, string mode)
        {
            string peer = Tool("pydial " + mode);
            var all = le.Outcomes(index + 1, 8000);
            if (all.Count <= index) Die(label + ": the connection did not end");
            var r = all[index];
            index += 1;
            Console.WriteLine(label + ": " + Line(r));
            Console.WriteLine(label + ", the peer: " + peer);
            return r;
        }
        o = Dialed("E1 a sample, from a peer whose certificate this client has never seen", "good");
        Must(o.What == "served" && o.Sent == "reply", "E1");
        o = Dialed("E2 a shuffle", "shuffle");
        Must(o.What == "served" && o.Sent == "reply", "E2");
        o = Dialed("E3 another peer's advert (the channel binding)", "binding");
        Must(o.What == "refused" && o.Stage == "advert" && o.Reason == "the certificate's key is not the advert's pub", "E3");
        o = Dialed("E4 a proof of possession by another key", "proof-other-key");
        Must(o.What == "refused" && o.Stage == "response" && o.Reason == "the proof of possession does not verify", "E4");
        o = Dialed("E5 no proof of possession: the request where it was due", "no-proof");
        Must(o.What == "refused" && o.Stage == "response" && o.Reason == "sample where pop_response was due", "E5");
        o = Dialed("E6 an advert above the frame ceiling", "oversize-advert");
        Must(o.What == "refused" && o.Stage == "advert" && o.Reason == "a frame above the ceiling", "E6");
        o = Dialed("E7 an expired token", "expired");
        Must(o.What == "refused" && o.Reason == "the token has expired", "E7");
        o = Dialed("E8 a token under an old kid: this client answers key_rotated", "old-kid");
        Must(o.What == "refused" && o.Reason == "key_rotated", "E8");
        o = Dialed("E9 a sentinel token, the certificate not in this client's whitelist", "sentinel-token");
        Must(o.What == "refused" && o.Reason == "a tempus_sentinel whose certificate is not in the tempus whitelist", "E9");
        o = Dialed("E10 the test unit's tick frame as the request", "tick");
        Must(o.What == "refused" && o.Stage == "request" && o.Reason == "unknown kind", "E10");
        o = Dialed("E11 a shuffle with an entry another key signed", "forged-shuffle");
        Must(o.What == "refused" && o.Stage == "request" && o.Reason == "entry 1 does not verify: the signature does not verify", "E11");
        o = Dialed("E12 a sample of 9 where this client's shuffle length is 3", "sample-9");
        Must(o.What == "refused" && o.Reason == "n is not 1 to the shuffle length", "E12");
        o = Dialed("E13 the peer closes after its advert", "closes");
        Must(o.What == "closed" && o.Stage == "challenge", "E13");
        o = Dialed("E14 a P-256 certificate", "p256");
        Must((o.What == "refused" || o.What == "tls_failed") && o.Stage == "tls", "E14");
        le.Dispose();

        // ---------------------------------------------------------------- Q
        Console.WriteLine("== Q. node Q, which is not a test node, and this client, both by the machine's clock");
        Tool("start q");
        var clock = new Verifier(producerPub, B("k1"), Verifier.SystemSeconds, 10, null);
        var real = edge.WithToken(Token(exp: 4000000000));
        Outcome Q(string label, Identity who, Request request) => Step(label, Client.Dial(qAddr, who, clock, request, settings));
        o = Q("Q1 sample", real, sample3);
        Must(o.What == "reply" && ViewOf(o).Count == 0 && o.Advert?.Id8() == nodeId, "Q1");
        o = Q("Q2 shuffle, own entry at age 0", real, new Request.Shuffle("tempus_edge", new[] { real.Entry(0) }));
        Must(o.What == "reply", "Q2");
        o = Q("Q3 sample", real, sample3);
        Must(o.What == "reply" && Same(ViewOf(o), Id("other") + "@0"), "Q3: this client is not in Q's edge store");
        o = Q("Q4 a token that ended at 3000 seconds after 1970", edge, sample3);
        Must(o.What == "closed", "Q4");
        o = Q("Q5 a token that begins at 3900000000 seconds after 1970", edge.WithToken(Token(nbf: 3900000000, exp: 4000000000)), sample3);
        Must(o.What == "closed", "Q5");
        o = Q("Q6 a cast, to a peer that is not a bridge", real, new Request.Cast(B("q6"), "demo", "note", new Term[] { new TInt(1) }));
        Must(o.What == "refused" && o.Stage == "request", "Q6");
        Console.WriteLine("Q7 the command line, dial: " + Tool("cli-dial"));
        Quiet();
        Console.WriteLine("Q8 the command line, listen: " + Tool("cli-listen"));
        Tool("stop q");
        Console.WriteLine("[c12] the C# client's walk passed");
    }
}
