// C16: the client half of the C# extension (example_tempus_clients/csharp) against real bridge nodes on 127.0.0.1:
// two bridges, B1 and B2 (each a TRUST node and a TEMPUS node in one Silica program), and the TRUST node T behind
// them. TEST CODE of this trial; it is not part of the extension. It uses the extension as an application would
// (Client.Dial) with the TEST ONLY identities of tools/bees_tempus_certs.py, checks every step and prints one line per
// step. Nothing printed depends on the time of day. COVERAGE.md beside this file says which row of the design's
// section 16.2 each step reaches.
//
// What a client cannot do is asked of the trial tool (walk.py beside this file), one line `@request` on the
// standard output answered by one line on the standard input: starting and stopping a node process, waiting for a
// line of its output, and sending a bridge (a test program) the test-only tick frame, with the Python test support.
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using Bees.Tempus;
using Bees.Tempus.Testing;

static class Bridge
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

    static byte[] B(string s) => Encoding.UTF8.GetBytes(s);

    static string Entries(Outcome o)
    {
        if (!(o.Body is Body.Entries b)) { Die("no entries in: " + o.Line()); return null; }
        return b.List.Count == 0 ? "(empty)" : string.Join(" ", b.List.Select(e => Hex.Of(e.D.Id, 4) + "@" + e.Age));
    }

    static string NoPeer(Outcome o) => Regex.Replace(o.Line(), @" peer=\S+", "");

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
        var producerPub = Fixtures.Key(0).Pub;
        string b1 = "127.0.0.1:" + (port + 1), b2 = "127.0.0.1:" + (port + 2), lp = "127.0.0.1:" + (port + 3);
        // the TEMPUS certificates of B1 ("bridge") and B2 ("x1"): this client's tempus whitelist
        var bridges = new[] { certs.Cert("bridge").Fingerprint, certs.Cert("x1").Fingerprint };
        Verifier V(string[] whitelist = null) => new Verifier(producerPub, B("k1"), () => 1500, 10, whitelist ?? bridges);
        var settings = new Settings(9000, 3);
        var p = certs.Identity("other", "tempus_edge", 1000, 3000, lp);          // the client's edge
        var n = certs.Identity("node", "tempus_edge", 1000, 3000, lp);           // a second edge
        var r = certs.Identity("sentinel", "tempus_edge", 1000, 3000, lp);       // the edge of the rate bound
        var x4 = certs.Identity("x4", "tempus_bridge", 1000, 3000, lp);          // a bridge identity whose certificate the bridges list
        int step = 0;
        void Say(string what, string o) { step += 1; Console.WriteLine(step + " " + what + ": " + o); }
        Outcome Ask(Identity who, string addr, Request request, Verifier v = null, int wait = 700)
        {
            var o = Client.Dial(addr, who, v ?? V(), request, settings);
            Quiet(wait);
            return o;
        }
        Request.Call CallOf(string rid, string f, long[] args, string module = "demo") => new Request.Call(B(rid), module, f, args.Select(a => (Term)new TInt(a)).ToList());
        Outcome Call(Identity who, string addr, string rid, string f, params long[] args) => Ask(who, addr, CallOf(rid, f, args));
        void Result(string what, Outcome o, long value)
        {
            Must(o.What == "reply" && o.Body is Body.Result b && new TInt(value).Equals(b.Value), what + ": wanted the result " + value + ", got: " + o.Line());
            Say(what, "result " + Outcome.Show(((Body.Result)o.Body).Value) + ", req_id " + Encoding.UTF8.GetString(((Body.Result)o.Body).ReqId));
        }
        void Closed(string what, Outcome o)
        {
            Must(o.What == "closed" && o.Stage == "reply", what + ": wanted a close with no reply, got: " + o.Line());
            Say(what, "closed, no reply");
        }

        Tool("start t"); Tool("start b1"); Tool("start b2");

        Console.WriteLine("== A. calls and a cast through a bridge (rows 24, 25, 31, 32)");
        Result("a call of demo:add/2 on bridge B1", Call(p, b1, "k1", "add", 2, 3), 5);
        Result("the same call on bridge B2", Call(p, b2, "k2", "add", 2, 3), 5);
        Result("demo:onward/2 on B1, which the bridge's application sends on to the TRUST node T", Call(p, b1, "k3", "onward", 20, 22), 42);
        Tool(@"wait t demo:add/2");
        Result("the same through B2", Call(p, b2, "k4", "onward", 20, 22), 42);
        Closed("a cast of demo:note/1 on B1 (a cast has no reply)", Ask(p, b1, new Request.Cast(B("k5"), "demo", "note", new Term[] { new TInt(7) })));
        Tool(@"wait b1 ^\[bridge\] note got 7$");
        Say("the bridge ran the cast", "its line `[bridge] note got 7` is in B1's output");

        Console.WriteLine("== B. what a bridge refuses of an edge; the edge sees a close and nothing else (rows 24, 34, 35)");
        Closed("a function that fails (demo:crash/1): no error body", Call(p, b1, "k6", "crash", 1));
        Result("the bridge still serves", Call(p, b1, "k7", "add", 2, 3), 5);
        Closed("a function that answers after the bridge's call timeout (demo:slow/1)", Call(p, b1, "k8", "slow", 1));
        Result("the bridge still serves", Call(p, b1, "k9", "add", 2, 3), 5);
        // the bound on one peer's requests in flight is 2: two calls are held, a third is refused
        var held = new Outcome[2];
        var threads = new List<Thread>();
        for (int i = 0; i < 2; i++)
        {
            int k = i;
            var t = new Thread(() => held[k] = Client.Dial(b1, p, V(), CallOf("h" + k, "hold", new long[] { k + 1 }), settings));
            t.Start();
            threads.Add(t);
            Tool(@"wait b1 bridge_admitted peer=\S+ call demo:hold/1");
            Quiet(300);
        }
        Closed("two calls of this edge are held by the bridge's application; a third request of the same edge", Call(p, b1, "k10", "add", 2, 3));
        Tool(@"wait b1 bridge_inflight peer=\S+ the peer's requests in flight are at their bound");
        Result("another edge is served meanwhile", Call(n, b1, "n1", "add", 2, 3), 5);
        foreach (var t in threads) t.Join();
        Must(held.All(h => h != null && h.What == "closed" && h.Stage == "reply"), "the held calls: " + string.Join("; ", held.Select(h => h?.Line())));
        Say("the two held calls end at the bridge's call timeout", "each closed, no reply");
        Quiet(1200);
        Result("demo:release/0 afterwards", Call(p, b1, "k11", "release"), 2);
        Closed("a function of a forbidden module (erlang:apply/0)", Ask(p, b1, CallOf("k12", "apply", new long[0], "erlang")));
        Closed("a function the bridge does not let an edge call (demo:secret/0)", Call(p, b1, "k13", "secret"));
        Closed("the forbidden module again", Ask(p, b1, CallOf("k14", "apply", new long[0], "erlang")));
        Closed("the function that is not permitted again", Call(p, b1, "k15", "secret"));
        Closed("then a good request of the same edge: refused for its score", Call(p, b1, "k16", "add", 2, 3));
        Tool(@"wait b1 bridge_refused peer=\S+ score 6 is above the limit 5");
        Result("another edge is still served", Call(n, b1, "n2", "add", 2, 3), 5);
        for (int i = 0; i < 20; i++)
        {
            var o = Client.Dial(b1, r, V(), CallOf("r" + i, "add", new long[] { i, 1 }), settings);
            Must(o.What == "reply" && o.Body is Body.Result b && new TInt(i + 1).Equals(b.Value), "request " + (i + 1) + " of the rate: " + o.Line());
        }
        Quiet();
        Say("twenty calls of one edge, R, within the hour", "each answered");
        Closed("the twenty-first: the rate bound", Call(r, b1, "r20", "add", 2, 3));
        Tool(@"wait b1 bridge_rate peer=\S+ more than 20 requests in 3600000 ms");
        Result("another edge is served", Call(n, b1, "n3", "add", 2, 3), 5);

        Console.WriteLine("== C. the whitelist rule for a bridge's certificate, both ways (rows 11, 12, 26)");
        var call = CallOf("w1", "add", new long[] { 2, 3 });
        var o1 = Ask(p, b1, call, V(new string[0]));
        Must(o1.What == "refused" && o1.Stage == "advert" && o1.Reason == "a tempus_bridge whose certificate is not in the tempus whitelist", "a bridge this client does not list was accepted: " + o1.Line());
        Say("a client whose whitelist is empty refuses B1 before any request", NoPeer(o1));
        var o2 = Ask(p, b1, call, V(new[] { certs.Cert("x1").Fingerprint }));
        Must(o2.What == "refused" && o2.Stage == "advert", "B1 was accepted under B2's certificate alone: " + o2.Line());
        Say("the same when it lists only B2's certificate", NoPeer(o2));
        var o3 = Ask(p, b1, new Request.Sample("tempus_bridge", 2), V(new[] { certs.Cert("bridge").Fingerprint, certs.Cert("other").Fingerprint }));
        Must(o3.What == "reply", "a sample of B1 by a client that lists B1: " + o3.Line());
        Say("a client that lists B1's certificate is answered: a sample of B1's bridge store", Entries(o3));
        var bogus = certs.Identity("other", "tempus_bridge", 1000, 3000, lp);
        var o4 = Ask(bogus, b1, new Request.Sample("tempus_bridge", 2));
        Must(o4.What == "closed", "B1 admitted a bridge token under a certificate it does not list: " + o4.Line());
        Tool("wait b1 whitelist_reject");
        Say("this client with a bridge token, under a certificate B1 does not list", "closed, no reply");
        var listedEdge = certs.Identity("x4", "tempus_edge", 1000, 3000, lp);
        var o5 = Ask(listedEdge, b1, new Request.Sample("tempus_bridge", 2));
        Must(o5.What == "closed", "B1 admitted an edge token under a certificate of its whitelist: " + o5.Line());
        Tool("wait b1 whitelist_reject");
        Say("with an edge token, under a certificate B1 lists (x4)", "closed, no reply");
        var o6 = Ask(x4, b1, CallOf("w2", "add", new long[] { 2, 3 }));
        Must(o6.What == "closed" && o6.Stage == "reply", "B1 served a call of a peer with a bridge token: " + o6.Line());
        Say("with a bridge token under that certificate, admitted: a call, which the bridge permits to edges only", "closed, no reply");

        Console.WriteLine("== D. an application finds a bridge in a store and calls it (rows 29, 30)");
        var b2Entry = certs.Identity("x1", "tempus_bridge", 1000, 3000, b2).Entry(1);
        var b1Entry = certs.Identity("bridge", "tempus_bridge", 1000, 3000, b1).Entry(1);
        Must(Ask(x4, b1, new Request.Shuffle("tempus_bridge", new[] { b2Entry })).What == "reply", "the shuffle into B1's bridge store was not answered");
        Must(Ask(x4, b2, new Request.Shuffle("tempus_bridge", new[] { b1Entry })).What == "reply", "the shuffle into B2's bridge store was not answered");
        var found = Ask(n, b1, new Request.Sample("tempus_bridge", 2));
        Must(found.What == "reply" && found.Body is Body.Entries fe && fe.List.Count == 1 && fe.List[0].D.AddrText() == b2, "the sample of B1's bridge store: " + found.Line());
        Say("a bridge peer shuffles B2's entry into B1's bridge store; an edge samples that store (every entry of the reply verified)", Entries(found));
        string picked = ((Body.Entries)found.Body).List[0].D.AddrText();
        Result("the edge dials the address of the entry it was given and calls demo:add/2 there", Call(n, picked, "d1", "add", 40, 2), 42);
        Say("B2's bridge store holds B1", Entries(Ask(n, b2, new Request.Sample("tempus_bridge", 2))));

        Console.WriteLine("== E. what a client sees when the TRUST side refuses or cannot be reached (design 17.7, row 33)");
        for (int i = 1; i <= 3; i++) Must(Call(n, b1, "t" + i, "bad").What == "closed", "demo:bad/0 was answered");
        Tool("wait t quarantined");
        Say("three calls of demo:bad/0 on B1, which sends on a call T does not permit: T quarantines B1", "each closed, no reply");
        Closed("then demo:onward/2 on B1: T refuses the quarantined bridge", Call(n, b1, "t4", "onward", 20, 22));
        Result("B1 itself still answers what needs no TRUST node", Call(n, b1, "t5", "add", 2, 3), 5);
        Result("and B2 still reaches T", Call(n, b2, "t6", "onward", 20, 22), 42);
        Tool("stop t");
        Closed("T is stopped: demo:onward/2 on B2", Call(n, b2, "t7", "onward", 20, 22));
        Result("B2 itself still answers", Call(n, b2, "t8", "add", 2, 3), 5);
        Tool("stop b1");
        var gone = Client.Dial(b1, n, V(), CallOf("t9", "add", new long[] { 2, 3 }), settings);
        Must(gone.What == "unreachable", "a stopped bridge answered: " + gone.Line());
        Say("B1 is stopped: a call to it", gone.Line());
        Tool("tick b2 tempus_bridge");
        Tool("wait b2 ^tick tempus_bridge: shuffle failed$");
        Say("a tick of B2's bridge store, whose only entry is B1: the shuffle fails and B1 is forgotten; the store", Entries(Ask(n, b2, new Request.Sample("tempus_bridge", 2))));
        Tool("stop b2");
        Console.WriteLine("[c16_tempus_bridge_csharp] every step passed (" + step + " steps)");
    }
}
