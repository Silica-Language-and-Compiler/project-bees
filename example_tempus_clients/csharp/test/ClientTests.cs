// Tests of the client half of the C# extension, run by a plain Main (no test library is needed):
//
//   make -C example_tempus_clients/csharp test
//
// Group 1, the frames golden: trials/t2_tempus_frames prints, for every frame and token it writes or mutates, a line
// `NAME hex HEX` and a line `NAME read: ...` saying what the Silica reader made of it. These tests build the same
// frames and tokens from the same inputs and require the same bytes, and read every HEX and require the same verdict.
// Group 2, the codec on its own. Group 3, the TEST ONLY identities and tokens of tools/bees_tempus_ids.py, byte for
// byte (Ed25519 signatures are deterministic). Group 4, the admission cases of trials/t4_tempus_admission. Group 5,
// the client against itself over mutual TLS 1.3 on 127.0.0.1, a port the system assigns. No Silica program runs.
// Every line printed is the same on every run.
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Text.RegularExpressions;
using Bees.Tempus;
using Bees.Tempus.Testing;

namespace Bees.Tempus.Tests
{
    static class T
    {
        public static int Passed, Failed;

        public static void Check(string name, Action block)
        {
            try { block(); Passed += 1; Console.WriteLine("ok    " + name); }
            catch (Exception e) { Failed += 1; Console.WriteLine("FAIL  " + name + ": " + e.GetType().Name + ": " + e.Message); }
        }

        public static string S(object o)
        {
            switch (o)
            {
                case null: return "null";
                case byte[] b: return Hex.Of(b);
                case string s: return s;
                case System.Collections.IEnumerable e: return "[" + string.Join(", ", e.Cast<object>().Select(S)) + "]";
                default: return o.ToString();
            }
        }

        public static void Eq(object a, object b, string what = "")
        {
            if (S(a) != S(b)) throw new Exception(what + ": got " + S(a) + ", wanted " + S(b));
        }

        public static void RefusedWith(string why, Action block)
        {
            try { block(); }
            catch (Refused e)
            {
                if (why != null && !e.Why.Contains(why)) throw new Exception("refused with \"" + e.Why + "\", wanted \"" + why + "\"");
                return;
            }
            throw new Exception("not refused" + (why != null ? ", wanted \"" + why + "\"" : ""));
        }

        public static byte[] B(string s) => Encoding.UTF8.GetBytes(s);
        public static byte[] Rep(char ch, int n) => Enumerable.Repeat((byte)ch, n).ToArray();
        public static List<string> Goldens(string leaf, string pattern) =>
            Directory.GetFiles(leaf).Where(p => Regex.IsMatch(Path.GetFileName(p), pattern)).OrderBy(p => p, StringComparer.Ordinal).ToList();
    }

    static class ClientTests
    {
        // ---------------------------------------------------------------- group 1: the fixed values of trials/t2_tempus_frames
        const string Addr = "127.0.0.1:22801";
        static readonly byte[] Sig = T.Rep('S', 64);
        static readonly byte[] Pub = T.Rep('p', 32);
        static readonly byte[] Tok = Crypto.Concat(Sig, Fixtures.TokenPayload("k1", Pub, "tempus_edge", 1000, 2000));
        const int ShuffleLength = 3;
        // what the Silica library does not read and this extension does not either: the frames of the test unit
        static readonly HashSet<string> TestFrames = new HashSet<string> { "tick", "clock", "clock of no time", "clock with a later reading", "clock before -1", "clock whose wait is 0" };

        static Descriptor Desc(byte[] id, byte[] pub = null, string addr = Addr, byte[] token = null) => new Descriptor(id, pub ?? Pub, T.B(addr), token ?? Tok);
        static Entry Peer(char ch, int age) => new Entry(age, Desc(T.Rep(ch, 64)));

        static List<(string, byte[])> Built()
        {
            var three = new[] { Peer('A', 0), Peer('B', 7), Peer('C', 65535) };
            var four = new[] { Peer('D', 1) }.Concat(three).ToArray();
            Entry[] One(Descriptor d) => new[] { new Entry(0, d) };
            byte[] Token(string kid, byte[] sub, string typ, long nbf, long exp) => Crypto.Concat(Sig, Fixtures.TokenPayload(kid, sub, typ, nbf, exp));
            return new List<(string, byte[])>
            {
                ("advert", Frames.Advert(Desc(T.Rep('A', 64)))),
                ("pop_challenge", Frames.Challenge(T.Rep('N', 32))),
                ("pop_response", Frames.Response(T.Rep('G', 64))),
                ("key_rotated", Frames.KeyRotated(T.B("k2"))),
                ("shuffle", Frames.Shuffle("tempus_edge", three)),
                ("shuffle_reply", Frames.ShuffleReply("tempus_bridge", new Entry[0])),
                ("sample", Frames.Sample("tempus_sentinel", 2)),
                ("sample_reply", Frames.SampleReply("tempus_sentinel", new[] { Peer('B', 7) })),
                ("token", Tok),
                ("token of a bridge", Token("producer-key-2026", T.Rep('q', 32), "tempus_bridge", 0, 1763424300)),
                ("token whose exp is not after nbf", Token("k1", Pub, "tempus_edge", 2000, 2000)),
                ("token with a 31-byte sub", Token("k1", T.Rep('p', 31), "tempus_edge", 1000, 2000)),
                ("token with an empty kid", Token("", Pub, "tempus_edge", 1000, 2000)),
                ("token with a 65-byte kid", Token(new string('k', 65), Pub, "tempus_edge", 1000, 2000)),
                ("shuffle of four entries, shuffle length three", Frames.Shuffle("tempus_edge", four)),
                ("entry of age 65536", Frames.Shuffle("tempus_edge", new[] { Peer('A', 65536) })),
                ("entry with a 63-byte id", Frames.Shuffle("tempus_edge", One(Desc(T.Rep('A', 63))))),
                ("entry with a 31-byte pub", Frames.Shuffle("tempus_edge", One(Desc(T.Rep('A', 64), pub: T.Rep('p', 31))))),
                ("entry with a 2-byte addr", Frames.Shuffle("tempus_edge", One(Desc(T.Rep('A', 64), addr: "a:")))),
                ("entry with a 262-byte addr", Frames.Shuffle("tempus_edge", One(Desc(T.Rep('A', 64), addr: new string('a', 262))))),
                ("entry with a 64-byte token", Frames.Shuffle("tempus_edge", One(Desc(T.Rep('A', 64), token: Sig)))),
                ("advert with a 65-byte id", Frames.Advert(Desc(T.Rep('A', 65)))),
                ("sample of 0", Frames.Sample("tempus_edge", 0)),
                ("sample of 4, shuffle length three", Frames.Sample("tempus_edge", 4)),
                ("nonce of 31 bytes", Frames.Challenge(T.Rep('N', 31))),
                ("sig of 65 bytes", Frames.Response(T.Rep('G', 65))),
                ("kid of no bytes", Frames.KeyRotated(new byte[0])),
            };
        }

        // name -> (bytes, the Silica reader's text) from one output of the frames trial
        static List<(string Name, byte[] Data, string Text)> Parse(string path)
        {
            var hexes = new List<(string, byte[])>();
            var reads = new Dictionary<string, string>();
            foreach (var line in File.ReadAllLines(path))
            {
                int at;
                if ((at = line.IndexOf(" hex ", StringComparison.Ordinal)) >= 0) hexes.Add((line.Substring(0, at), Hex.Parse(line.Substring(at + 5))));
                else if (line.EndsWith(" hex")) hexes.Add((line.Substring(0, line.Length - 4), new byte[0]));
                else if ((at = line.IndexOf(" read: ", StringComparison.Ordinal)) >= 0) reads[line.Substring(0, at)] = line.Substring(at + 7);
            }
            return hexes.Select(h => (h.Item1, h.Item2, reads[h.Item1])).ToList();
        }

        static string Accepts(string name, byte[] data)
        {
            try
            {
                if (name.StartsWith("token")) Frames.ReadToken(data); else Frames.ReadBody(data, ShuffleLength);
                return null;
            }
            catch (Refused e) { return e.Why; }
        }

        static void FramesGolden(string root)
        {
            string leaf = Path.Combine(root, "trials", "t2_tempus_frames");
            var goldens = T.Goldens(leaf, @"^frames\..*\.scout$");
            T.Check("frames golden: there is a recorded output to compare with", () => { if (goldens.Count == 0) throw new Exception("no frames.*.scout in " + leaf); });
            foreach (var path in goldens)
            {
                string name = Path.GetFileName(path);
                var seen = Parse(path);
                byte[] Of(string n) => seen.First(s => s.Name == n).Data;
                T.Check("frames golden " + name + ": the same bytes from the same inputs (" + Built().Count + " frames and tokens)", () =>
                {
                    foreach (var (n, data) in Built())
                    {
                        if (!seen.Any(s => s.Name == n)) throw new Exception("no line for " + n);
                        T.Eq(Hex.Of(data), Hex.Of(Of(n)), n);
                    }
                });
                T.Check("frames golden " + name + ": the same verdict on every frame the library reads", () =>
                {
                    int n = 0;
                    foreach (var s in seen)
                    {
                        if (TestFrames.Contains(s.Name) || s.Name == "done") continue;
                        bool silicaOk = !s.Text.Contains("refused");
                        string why = Accepts(s.Name, s.Data);
                        if ((why == null) != silicaOk) throw new Exception(s.Name + ": Silica says \"" + s.Text + "\", C# says \"" + (why ?? "accepted") + "\"");
                        n += 1;
                    }
                    if (n < 37) throw new Exception("only " + n + " frames compared");
                });
                T.Check("frames golden " + name + ": the test unit's frames (tick, clock) and their answer (done) are frames of no kind to this extension", () =>
                {
                    foreach (var f in TestFrames.Concat(new[] { "done" })) T.Eq(Accepts(f, Of(f)), "unknown kind", f);
                });
                T.Check("frames golden " + name + ": the same fields read", () =>
                {
                    var b = (Body.Entries)Frames.ReadBody(Of("shuffle"), ShuffleLength);
                    T.Eq(b.Name + " " + b.Store, "shuffle tempus_edge");
                    T.Eq(b.List.Select(e => e.Age + " " + Encoding.ASCII.GetString(e.D.Id, 0, 4)), new[] { "0 AAAA", "7 BBBB", "65535 CCCC" });
                    var t = Frames.ReadToken(Of("token"));
                    T.Eq(new object[] { Encoding.ASCII.GetString(t.Kid), t.Typ, t.Nbf, t.Exp, t.Payload.Length }, new object[] { "k1", "tempus_edge", 1000L, 2000L, 98 });
                    var s = (Body.Sample)Frames.ReadBody(Of("sample"), ShuffleLength);
                    T.Eq(s.Store + " " + s.N, "tempus_sentinel 2");
                    var a = (Body.Advert)Frames.ReadBody(Of("advert"), ShuffleLength);
                    T.Eq(a.D.AddrText(), Addr);
                });
            }
        }

        // ---------------------------------------------------------------- group 2: the codec on its own
        static void Codec()
        {
            T.Check("codec: every frame decodes and encodes to the same bytes", () =>
            {
                foreach (var (name, data) in Built()) if (!name.StartsWith("token")) T.Eq(Hex.Of(Etf.Encode(Etf.Decode(data))), Hex.Of(data), name);
            });
            T.Check("codec: map keys are written in the byte order of their names", () =>
            {
                string body = Encoding.Latin1.GetString(Frames.Sample("tempus_edge", 1));
                int n = body.IndexOf("w\u0001n", StringComparison.Ordinal), s = body.IndexOf("w\u0005store", StringComparison.Ordinal), t = body.IndexOf("w\u0001t", StringComparison.Ordinal);
                if (!(n >= 0 && n < s && s < t)) throw new Exception("order n=" + n + " store=" + s + " t=" + t);
                // whatever order the caller gives the keys in
                T.Eq(Hex.Of(Etf.Encode(new TMap(("t", new TAtom("x")), ("b", new TInt(1)), ("ab", new TInt(2)), ("a", new TInt(3))))),
                    Hex.Of(Etf.Encode(new TMap(("a", new TInt(3)), ("ab", new TInt(2)), ("b", new TInt(1)), ("t", new TAtom("x"))))));
            });
            T.Check("codec: integers 0 to 255 as tag 97, larger ones that fit 32 bits as tag 98, an empty list as tag 106 alone", () =>
            {
                T.Eq(Hex.Of(Etf.Encode(new TInt(255))), "8361ff"); T.Eq(Hex.Of(Etf.Encode(new TInt(256))), "836200000100"); T.Eq(Hex.Of(Etf.Encode(new TInt(-1))), "8362ffffffff");
                T.Eq(Hex.Of(Etf.Encode(new TInt(4000000000))), "836e0400" + "00286bee"); T.Eq(Hex.Of(Etf.Encode(new TList(new Term[0]))), "836a");
                T.Eq(((TInt)Etf.Decode(Etf.Encode(new TInt(4000000000)))).Value, 4000000000L);
            });
            T.Check("codec: a frame is its body after a 4-byte length, most significant byte first", () =>
            {
                T.Eq(Hex.Of(Frames.Frame(Frames.Sample("tempus_edge", 1)), 4), "0000002a");
                T.Eq(Frames.Sample("tempus_edge", 1).Length, 42);
            });
            T.Check("codec: the reader's refusals", () =>
            {
                string sample = Hex.Of(T.B("sample"));
                T.RefusedWith("truncated", () => Frames.ReadBody(new byte[0], 3));
                T.RefusedWith("bad_version", () => Frames.ReadBody(Hex.Parse("82"), 3));
                T.RefusedWith("trailing_bytes", () => Frames.ReadBody(Crypto.Concat(Frames.Sample("tempus_edge", 1), new byte[1]), 3));
                T.RefusedWith("bad_tag", () => Frames.ReadBody(Hex.Parse("836800"), 3));
                T.RefusedWith("bad_tag", () => Frames.ReadBody(Hex.Parse("83740000000161016101"), 3));
                T.RefusedWith("duplicate_field", () => Frames.ReadBody(Hex.Parse("8374000000027701747706" + sample + "7701747706" + sample), 3));
                T.RefusedWith("unknown_field", () => Frames.ReadBody(Etf.Encode(new TMap(("t", new TAtom("sample")), ("store", new TAtom("tempus_edge")), ("n", new TInt(1)), ("x", new TInt(1)))), 3));
                T.RefusedWith("missing_field", () => Frames.ReadBody(Etf.Encode(new TMap(("t", new TAtom("sample")), ("store", new TAtom("tempus_edge")))), 3));
                T.RefusedWith("too_deep", () => Etf.Decode(Hex.Parse("83" + string.Concat(Enumerable.Repeat("6c00000001", 8)) + string.Concat(Enumerable.Repeat("6a", 9)))));
                T.RefusedWith("not UTF-8", () => Frames.ReadBody(Hex.Parse("8374000000017701747702c328"), 3));
                T.RefusedWith("too_large", () => Etf.Decode(new byte[Etf.FrameMax + 1]));
            });
            T.Check("codec: TRUST's call and cast frames are the bytes the Python example writes, and its result is read", () =>
            {
                T.Eq(Hex.Of(Frames.RequestFrame("call", T.B("p2"), "demo", "add", new Term[] { new TInt(2), new TInt(3) })),
                    "83740000000877016161027704617267736c00000002610261036a770166770361646477016d770464656d6f77046f707473740000000077067265715f69646d000000027032770174770463616c6c77037665726101");
                T.Eq(Hex.Of(Frames.RequestFrame("cast", T.B("p7"), "demo", "note", new Term[] { new TInt(7) })),
                    "83740000000877016161017704617267736c0000000161076a77016677046e6f746577016d770464656d6f77046f707473740000000077067265715f69646d00000002703777017477046361737477037665726101");
                var r = (Body.Result)Frames.ReadBody(Hex.Parse("83740000000477067265715f69646d0000000270327701747706726573756c74770576616c7565610577037665726101"), 3);
                T.Eq(Encoding.ASCII.GetString(r.ReqId) + " " + ((TInt)r.Value).Value, "p2 5");
            });
            T.Check("codec: the identifier of a key is its SHA-512, and OpenSSL's SHA-512 is .NET's", () =>
            {
                T.Eq(Crypto.PeerId(Pub).Length, 64);
                T.Eq(Hex.Of(Crypto.PeerId(Pub)), Hex.Of(System.Security.Cryptography.SHA512.HashData(Pub)));
            });
        }

        // ---------------------------------------------------------------- group 3: the TEST ONLY identities and tokens
        static void Identities(string root)
        {
            var certs = new Certs(root);
            string text = File.ReadAllText(Path.Combine(root, "trials", "c2_tempus_clients", "lib", "tempus_ids.silica"));
            var names = Fixtures.Table(text, "name");
            var producer = Fixtures.Key(0);
            var old = Fixtures.Key(96);
            var producerPub = Hex.Parse(Fixtures.Constant(text, "producer_pub_hex"));
            T.Check("identities: the eight TEST ONLY certificates are Ed25519 and self-signed, and their keys, identifiers and fingerprints are those of tools/bees_tempus_ids.py", () =>
            {
                T.Eq(names, Certs.Seeds.Select(s => s.Name));
                for (int i = 0; i < names.Count; i++)
                {
                    var cert = certs.Cert(names[i]);
                    T.Eq(Hex.Of(cert.TempusKey()), Fixtures.Table(text, "pub_hex")[i], names[i] + " pub");
                    T.Eq(Hex.Of(Crypto.PeerId(cert.TempusKey())), Fixtures.Table(text, "id_hex")[i], names[i] + " id");
                    T.Eq(cert.Fingerprint, Fixtures.Table(text, "fp_hex")[i], names[i] + " fingerprint");
                }
            });
            T.Check("identities: each key file is the key of its seed and of its certificate, and the producer's key is the key of seed 0", () =>
            {
                var message = T.B("the same message");
                foreach (var (name, first) in Certs.Seeds)
                {
                    var me = Identity.Load(certs.CertPath(name), certs.KeyPath(name), new byte[65], "127.0.0.1:1");
                    T.Eq(Hex.Of(me.Key.Sign(message)), Hex.Of(Fixtures.Key(first).Sign(message)), name);
                    T.Eq(Hex.Of(Fixtures.Key(first).Pub), Hex.Of(me.Pub), name);
                    if (!Crypto.Ed25519Verify(me.Pub, message, me.Key.Sign(message))) throw new Exception(name);
                }
                T.Eq(Hex.Of(producer.Pub), Hex.Of(producerPub), "the producer's key");
            });
            T.Check("identities: a certificate made here from a seed, with the dates and serial of tools/bees_tempus_certs.py, is the recorded certificate byte for byte", () =>
            {
                int n = 0;
                foreach (var (name, first) in Certs.Seeds)
                {
                    var want = certs.Cert(name);
                    for (int serial = 1; serial <= 16; serial++)
                    {
                        var made = Certificate.SelfSign(Fixtures.Key(first), "bees tempus test " + name, serial, "260101000000Z", "460101000000Z");
                        if (made.Fingerprint == want.Fingerprint) { n += 1; break; }
                    }
                }
                T.Eq(n, 8);
            });
            T.Check("identities: the 112 tokens of tools/bees_tempus_ids.py, made here from the same seeds, are the same bytes", () =>
            {
                var oldPub = old.Pub;
                T.Eq(Hex.Of(Frames.ReadToken(Hex.Parse(Fixtures.Table(text, "tok9")[0])).Sub), Hex.Of(oldPub), "token 9's sub is the key of seed 96");
                int n = 0;
                for (int i = 0; i < names.Count; i++)
                {
                    var pub = certs.Cert(names[i]).TempusKey();
                    var mine = new Dictionary<int, byte[]>
                    {
                        [1] = Fixtures.MakeToken(producer, "k1", pub, "tempus_edge", 1000, 2000), [2] = Fixtures.MakeToken(producer, "k1", pub, "tempus_bridge", 1000, 2000),
                        [3] = Fixtures.MakeToken(producer, "k1", pub, "tempus_sentinel", 1000, 2000), [4] = Fixtures.MakeToken(old, "k0", pub, "tempus_edge", 1000, 2000),
                        [5] = Fixtures.MakeToken(producer, "k1", pub, "tempus_edge", 1000, 1400), [6] = Fixtures.MakeToken(producer, "k1", pub, "tempus_edge", 1000, 3000),
                        [7] = Fixtures.MakeToken(producer, "k1", pub, "tempus_edge", 1800, 2000), [8] = Fixtures.MakeToken(old, "k1", pub, "tempus_edge", 1000, 2000),
                        [9] = Fixtures.MakeToken(producer, "k1", oldPub, "tempus_edge", 1000, 2000), [10] = Fixtures.MakeToken(producer, "k1", pub, "tempus_edge", 1000, 1600),
                        [11] = Fixtures.MakeToken(producer, "k1", pub, "tempus_sentinel", 1000, 3000), [12] = Fixtures.MakeToken(producer, "k1", pub, "tempus_edge", 1000, 2500),
                        [13] = Fixtures.MakeToken(producer, "k1", pub, "tempus_bridge", 1000, 3000), [14] = Fixtures.MakeToken(producer, "k1", pub, "tempus_edge", 1000, 4000000000),
                    };
                    foreach (var kv in mine) { T.Eq(Hex.Of(kv.Value), Fixtures.Table(text, "tok" + kv.Key)[i], names[i] + " token " + kv.Key); n += 1; }
                }
                T.Eq(n, 112);
            });
            T.Check("identities: a real token is verified, and refused outside its time, under another kid, under another key and when changed", () =>
            {
                var sub = certs.Cert("node").TempusKey();
                var token = Fixtures.MakeToken(producer, "k1", sub, "tempus_edge", 1000, 2000);
                T.Eq(token.Length, 64 + 98);
                var d = new Descriptor(Crypto.PeerId(sub), sub, T.B(Addr), token);
                Verifier V(long now, long skew, string kid = "k1", byte[] key = null) => new Verifier(key ?? producerPub, T.B(kid), () => now, skew, null);
                T.Eq(Hex.Of(V(1500, 0).CheckEntry(d, "tempus_edge").Sub), Hex.Of(sub));
                foreach (var (now, skew, ok) in new[] { (999L, 0L, false), (999L, 1L, true), (2000L, 0L, false), (2000L, 1L, true), (2001L, 1L, false) })
                {
                    if (ok) V(now, skew).CheckEntry(d, "tempus_edge"); else T.RefusedWith(null, () => V(now, skew).CheckEntry(d, "tempus_edge"));
                }
                T.RefusedWith("key_rotated", () => V(1500, 0, kid: "k2").CheckEntry(d, "tempus_edge"));
                T.RefusedWith("the signature does not verify", () => V(1500, 0, key: sub).CheckEntry(d, "tempus_edge"));
                var flipped = (byte[])token.Clone(); flipped[70] ^= 1;
                T.RefusedWith(null, () => V(1500, 0).CheckEntry(new Descriptor(d.Id, d.Pub, d.Addr, flipped), "tempus_edge"));
                T.RefusedWith("typ is not the store's type", () => V(1500, 0).CheckEntry(d, "tempus_bridge"));
            });
            T.Check("identities: the channel binding and the whitelist rule", () =>
            {
                Func<long> now = () => 1500L;
                var node = certs.Identity("node", "tempus_edge", 1000, 2000, Addr);
                var sentinel = certs.Identity("sentinel", "tempus_sentinel", 1000, 2000, Addr);
                string fp = certs.Cert("sentinel").Fingerprint;
                var none = new Verifier(producerPub, T.B("k1"), now, 10, null);
                var listed = new Verifier(producerPub, T.B("k1"), now, 10, new[] { fp });
                T.Eq(none.CheckPeer(node.Descriptor(), certs.Cert("node")).Typ, "tempus_edge");
                // every field of the node's advert verifies; only the certificate is another peer's
                T.RefusedWith("the certificate's key is not the advert's pub", () => none.CheckPeer(node.Descriptor(), certs.Cert("other")));
                T.Eq(listed.CheckPeer(sentinel.Descriptor(), certs.Cert("sentinel")).Typ, "tempus_sentinel");
                T.RefusedWith("not in the tempus whitelist", () => none.CheckPeer(sentinel.Descriptor(), certs.Cert("sentinel")));
                var edgeToken = certs.Identity("sentinel", "tempus_edge", 1000, 2000, Addr);
                T.RefusedWith("a certificate of the tempus whitelist with a tempus_edge token", () => listed.CheckPeer(edgeToken.Descriptor(), certs.Cert("sentinel")));
                T.Eq(none.CheckPeer(edgeToken.Descriptor(), certs.Cert("sentinel")).Typ, "tempus_edge");
                T.RefusedWith("the certificate's key is not Ed25519", () => Certificate.FromPem(File.ReadAllText(Path.Combine(root, "trials/t5_tempus_tls/certs/p256.pem"))).TempusKey());
            });
        }

        // ---------------------------------------------------------------- group 4: the admission cases of trials/t4_tempus_admission
        static void AdmissionCases(string root)
        {
            string leaf = Path.Combine(root, "trials", "t4_tempus_admission");
            string text = File.ReadAllText(Path.Combine(leaf, "lib", "tempus_fixtures.silica"));
            var goldens = T.Goldens(leaf, @"^dangerous_admit\..*\.scout$");
            var stores = new Dictionary<string, string> { ["1"] = "tempus_edge", ["2"] = "tempus_bridge", ["3"] = "tempus_sentinel" };
            long nowValue = long.Parse(Fixtures.Constant(text, "now"));
            var verifier = new Verifier(Hex.Parse(Fixtures.Constant(text, "producer_pub_hex")), T.B(Fixtures.Constant(text, "kid")), () => nowValue,
                long.Parse(Fixtures.Constant(text, "skew")), null);
            var names = Fixtures.Table(text, "name"); var kinds = Fixtures.Table(text, "kind"); var ids = Fixtures.Table(text, "id_hex"); var pubs = Fixtures.Table(text, "pub_hex");
            var tokens = Fixtures.Table(text, "token_hex"); var nonces = Fixtures.Table(text, "nonce_hex"); var sigs = Fixtures.Table(text, "sig_hex"); var wants = Fixtures.Table(text, "want");
            T.Check("admission cases: there is a recorded output to compare with", () => { if (goldens.Count == 0) throw new Exception("no golden"); });
            foreach (var path in goldens)
            {
                var said = new Dictionary<string, string>();
                foreach (var line in File.ReadAllLines(path)) { int at = line.IndexOf(": ", StringComparison.Ordinal); if (at >= 0 && !said.ContainsKey(line.Substring(0, at))) said[line.Substring(0, at)] = line.Substring(at + 2); }
                T.Check("admission cases " + Path.GetFileName(path) + ": the " + names.Count + " cases get the verdict, and the reason, the Silica node gave", () =>
                {
                    T.Eq(names.Count, int.Parse(Fixtures.Constant(text, "count")));
                    for (int i = 0; i < names.Count; i++)
                    {
                        string mine;
                        if (kinds[i] == "1")
                        {
                            try
                            {
                                // the descriptor is read as a frame's would be (its bounds), then verified without contact
                                var d = Frames.ReadDescriptor(new Descriptor(Hex.Parse(ids[i]), Hex.Parse(pubs[i]), T.B(Fixtures.Constant(text, "addr")), Hex.Parse(tokens[i])).Term());
                                verifier.CheckEntry(d, stores[wants[i]]); mine = "admitted";
                            }
                            catch (Refused e) { mine = "refused: " + e.Why; }
                        }
                        else if (kinds[i] == "2")
                        {
                            try { verifier.CheckProof(Hex.Parse(pubs[i]), Hex.Parse(nonces[i]), Hex.Parse(tokens[i]), Hex.Parse(sigs[i])); mine = "admitted"; }
                            catch (Refused) { mine = "refused: the signature does not verify"; }
                        }
                        else
                        {
                            var key = SigningKey.FromSeed(Hex.Parse(pubs[i]));
                            mine = Hex.Of(key.Sign(Crypto.Concat(Hex.Parse(nonces[i]), Hex.Parse(tokens[i])))) == sigs[i] ? "the same 64 bytes as the fixture's signature" : "other bytes";
                        }
                        T.Eq(mine, said[names[i]], names[i]);
                    }
                });
            }
        }

        // ---------------------------------------------------------------- group 5: the client against itself
        static void Loopback(string root)
        {
            var certs = new Certs(root);
            var producerPub = Hex.Parse(Fixtures.Constant(File.ReadAllText(Path.Combine(root, "trials", "c2_tempus_clients", "lib", "tempus_ids.silica")), "producer_pub_hex"));
            var settings = new Settings(4000, 3);
            const string advertised = "127.0.0.1:9";          // an address in the adverts only: nothing dials it in these tests
            Verifier V(string kid = "k1", string[] whitelist = null, long now = 1500) => new Verifier(producerPub, T.B(kid), () => now, 10, whitelist);
            var dialer = certs.Identity("node", "tempus_edge", 1000, 2000, advertised);
            var edge = certs.Identity("other", "tempus_edge", 1000, 2000, advertised);
            var third = certs.Identity("x1", "tempus_edge", 1000, 2000, advertised);
            var sentinel = certs.Identity("sentinel", "tempus_sentinel", 1000, 2000, advertised);
            string sentinelFp = certs.Cert("sentinel").Fingerprint;
            Func<Incoming, IReadOnlyList<Entry>> none = _ => new Entry[0];

            // one connection: the dialer's Outcome and the listener's
            (Outcome, Outcome) Exchange(Request request, Identity listener = null, Identity me = null, Verifier dialVerifier = null, Verifier listenVerifier = null,
                                        Settings dialSettings = null, Func<Incoming, IReadOnlyList<Entry>> handler = null)
            {
                using (var lis = new Listener(listener ?? edge, listenVerifier ?? V(), settings, "127.0.0.1", 0, handler ?? none))
                {
                    var o = Client.Dial(lis.Address, me ?? dialer, dialVerifier ?? V(), request, dialSettings ?? settings);
                    var served = lis.Outcomes(1, 6000);
                    if (served.Count != 1) throw new Exception("the listener saw no connection end");
                    return (o, served[0]);
                }
            }
            Request Smp(int n = 1, string store = "tempus_edge") => new Request.Sample(store, n);

            T.Check("loopback: admission both ways, a sample and its reply", () =>
            {
                var (o, served) = Exchange(Smp(2), handler: _ => new[] { third.Entry(3) });
                T.Eq(o.Line(), "reply sample_reply entries=[3:" + third.Descriptor().Id8() + "] store=tempus_edge peer=" + edge.Descriptor().Id8() + " typ=tempus_edge");
                T.Eq(served.Line(), "served sample n=2 store=tempus_edge sent=reply peer=" + dialer.Descriptor().Id8() + " typ=tempus_edge");
                if (!o.Advert.Equals(edge.Descriptor()) || !served.Advert.Equals(dialer.Descriptor())) throw new Exception("the adverts");
            });
            T.Check("loopback: a shuffle and its reply, entry for entry", () =>
            {
                var offered = new[] { dialer.Entry(0), third.Entry(4) };
                IReadOnlyList<Entry> got = null;
                var (o, served) = Exchange(new Request.Shuffle("tempus_edge", offered), handler: rq => { got = ((Body.Entries)rq.Body).List; return new[] { edge.Entry(0), third.Entry(5) }; });
                if (!got.SequenceEqual(offered)) throw new Exception("the entries offered");
                if (!((Body.Entries)o.Body).List.SequenceEqual(new[] { edge.Entry(0), third.Entry(5) })) throw new Exception("the entries answered");
                T.Eq(o.What + " " + served.Sent, "reply reply");
            });
            T.Check("loopback: a handler that answers nothing closes with no reply", () =>
            {
                var (o, served) = Exchange(Smp(), handler: _ => null);
                T.Eq(o.Line(), "closed at=reply peer=" + edge.Descriptor().Id8() + " typ=tempus_edge");
                T.Eq(served.Sent, "close");
            });
            T.Check("loopback: a call and a cast are not sent to a peer that is no bridge; a peer with a bridge token gets them, and this extension's listener answers neither", () =>
            {
                foreach (var rq in new Request[] { new Request.Call(T.B("r1"), "demo", "add", new Term[] { new TInt(2), new TInt(3) }), new Request.Cast(T.B("r2"), "demo", "note", new Term[] { new TInt(7) }) })
                {
                    var (o, served) = Exchange(rq);
                    T.Eq(o.What + "|" + o.Stage + "|" + o.Reason, "refused|request|the peer is not a bridge");
                    T.Eq(served.What + " " + served.Stage, "closed request");
                    var bridge = certs.Identity("bridge", "tempus_bridge", 1000, 2000, advertised);
                    var (o2, served2) = Exchange(rq, listener: bridge, dialVerifier: V(whitelist: new[] { certs.Cert("bridge").Fingerprint }));
                    T.Eq(o2.What + " " + o2.Stage, "closed reply");
                    T.Eq(served2.What + " " + served2.Reason, "refused unknown kind");
                }
            });
            T.Check("loopback: each cause of refusing a dialer's token, seen by the listener; the dialer sees only the close", () =>
            {
                var other = Fixtures.Key(64);
                var cases = new[]
                {
                    (certs.Identity("node", "tempus_edge", 1000, 2000, advertised, producer: other), "the signature does not verify"),
                    (certs.Identity("node", "tempus_edge", 1000, 1400, advertised), "the token has expired"),
                    (certs.Identity("node", "tempus_edge", 1000, 1490, advertised), "the token has expired"),
                    (certs.Identity("node", "tempus_edge", 1600, 2000, advertised), "the token is not valid yet"),
                    (certs.Identity("node", "tempus_edge", 1000, 2000, advertised, sub: third.Pub), "sub is not the peer's key"),
                    (certs.Identity("node", "tempus_sentinel", 1000, 2000, advertised), "a tempus_sentinel whose certificate is not in the tempus whitelist"),
                };
                foreach (var (who, reason) in cases)
                {
                    int asked = 0;
                    var (o, served) = Exchange(Smp(), me: who, handler: _ => { asked += 1; return new Entry[0]; });
                    T.Eq(served.What + "|" + served.Stage + "|" + served.Reason, "refused|advert|" + reason);
                    T.Eq(o.What + " " + asked, "closed 0", reason);
                }
                foreach (var who in new[] { certs.Identity("node", "tempus_edge", 1000, 1495, advertised), certs.Identity("node", "tempus_edge", 1505, 2000, advertised) })
                {
                    var (o, served) = Exchange(Smp(), me: who);
                    T.Eq(o.What + " " + served.What, "reply served", "inside the skew");
                }
            });
            T.Check("loopback: the dialer refuses a listener whose token has expired or was signed by another key", () =>
            {
                var (o, served) = Exchange(Smp(), listener: certs.Identity("other", "tempus_edge", 1000, 1400, advertised));
                T.Eq(o.What + "|" + o.Stage + "|" + o.Reason, "refused|advert|the token has expired"); T.Eq(served.What, "closed");
                var (o2, _) = Exchange(Smp(), listener: certs.Identity("other", "tempus_edge", 1000, 2000, advertised, producer: Fixtures.Key(128)));
                T.Eq(o2.What + "|" + o2.Stage + "|" + o2.Reason, "refused|advert|the signature does not verify");
                T.Eq(o2.Advert?.Id8(), edge.Descriptor().Id8(), "the refused peer's advert is still reported");
            });
            T.Check("loopback: key_rotated, in both directions, and before every other fault of the token", () =>
            {
                var old = Fixtures.Key(96);
                var (o, served) = Exchange(Smp(), me: certs.Identity("node", "tempus_edge", 1000, 2000, advertised, kid: "k0", producer: old));
                T.Eq(o.Line(), "key_rotated at=challenge kid=6b31 peer=" + edge.Descriptor().Id8() + " typ=tempus_edge");
                T.Eq(served.What + " " + served.Reason, "refused key_rotated");
                var (o2, _) = Exchange(Smp(), me: certs.Identity("node", "tempus_edge", 1000, 1400, advertised, kid: "k0", producer: old));
                T.Eq(o2.What + " " + (o2.Kid == null ? "" : Encoding.ASCII.GetString(o2.Kid)), "key_rotated k1");
                var (o3, served3) = Exchange(Smp(), listener: certs.Identity("other", "tempus_edge", 1000, 2000, advertised, kid: "k0", producer: old));
                T.Eq(o3.What + " " + o3.Reason, "refused key_rotated");
                T.Eq(served3.What + " " + (served3.Kid == null ? "" : Encoding.ASCII.GetString(served3.Kid)), "key_rotated k1");
            });
            T.Check("loopback: a sentinel is admitted only with its certificate in the whitelist", () =>
            {
                var (o, _) = Exchange(Smp(1, "tempus_sentinel"), listener: sentinel, dialVerifier: V(whitelist: new[] { sentinelFp }), handler: _ => new[] { sentinel.Entry(0) });
                T.Eq(o.What + " " + o.Typ, "reply tempus_sentinel");
                var (o2, _) = Exchange(Smp(1, "tempus_sentinel"), listener: sentinel);
                T.Eq(o2.What + "|" + o2.Stage + "|" + o2.Reason, "refused|advert|a tempus_sentinel whose certificate is not in the tempus whitelist");
            });
            T.Check("loopback: a reply is refused whole when one entry does not verify, is of another store's type, or the reply is not what was asked for", () =>
            {
                var forged = certs.Identity("x2", "tempus_edge", 1000, 2000, advertised, producer: Fixtures.Key(96));
                var (o, _) = Exchange(Smp(3), handler: _ => new[] { third.Entry(1), forged.Entry(0) });
                T.Eq(o.What + "|" + o.Stage + "|" + o.Reason, "refused|reply|entry 1 does not verify: the signature does not verify");
                var (o2, _) = Exchange(new Request.Shuffle("tempus_edge", new[] { dialer.Entry(0) }), handler: _ => new[] { sentinel.Entry(0) });
                T.Eq(o2.Reason, "entry 0 does not verify: typ is not the store's type");
                var expired = certs.Identity("x2", "tempus_edge", 1000, 1400, advertised);
                var (o3, _) = Exchange(Smp(3), handler: _ => new[] { expired.Entry(0) });
                T.Eq(o3.Reason, "entry 0 does not verify: the token has expired");
                // the listener's shuffle length is 3 and the dialer's is 2: the reply holds more entries than the dialer's network allows
                var (o4, _) = Exchange(Smp(2), dialSettings: new Settings(4000, 2), handler: _ => new[] { third.Entry(1), edge.Entry(0) });
                T.Eq(o4.What, "reply");
                var (o5, _) = Exchange(new Request.Shuffle("tempus_edge", new Entry[0]), dialSettings: new Settings(4000, 2), handler: _ => new[] { third.Entry(1), edge.Entry(0), dialer.Entry(2) });
                T.Eq(o5.What + " " + o5.Reason, "refused more entries than the shuffle length");
            });
            T.Check("loopback: a listener refuses a shuffle whose entry does not verify, and its handler is not asked", () =>
            {
                var forged = certs.Identity("x2", "tempus_edge", 1000, 2000, advertised, producer: Fixtures.Key(96));
                int asked = 0;
                var (o, served) = Exchange(new Request.Shuffle("tempus_edge", new[] { dialer.Entry(0), forged.Entry(1) }), handler: _ => { asked += 1; return new Entry[0]; });
                T.Eq(served.What + "|" + served.Stage + "|" + served.Reason, "refused|request|entry 1 does not verify: the signature does not verify");
                T.Eq(o.What + " " + asked, "closed 0");
            });
            T.Check("loopback: a listener serves several connections in order", () =>
            {
                using (var lis = new Listener(edge, V(), settings, "127.0.0.1", 0, none))
                {
                    for (int n = 1; n <= 3; n++) T.Eq(Client.Dial(lis.Address, dialer, V(), Smp(n), settings).What, "reply");
                    T.Eq(lis.Outcomes(3, 6000).Select(x => ((Body.Sample)x.Body).N), new[] { 1, 2, 3 });
                }
            });
            T.Check("loopback: nobody listens: unreachable; a peer that never answers: timeout at the one bound of the connection", () =>
            {
                int free;
                using (var s = new Socket(AddressFamily.InterNetwork, SocketType.Stream, ProtocolType.Tcp)) { s.Bind(new IPEndPoint(IPAddress.Loopback, 0)); free = ((IPEndPoint)s.LocalEndPoint).Port; }
                T.Eq(Client.Dial("127.0.0.1:" + free, dialer, V(), Smp(), settings).Line(), "unreachable at=tls");
                using (var silent = new Socket(AddressFamily.InterNetwork, SocketType.Stream, ProtocolType.Tcp))
                {
                    silent.Bind(new IPEndPoint(IPAddress.Loopback, 0)); silent.Listen(4);
                    long t0 = Tls.NowMs();
                    var o = Client.Dial("127.0.0.1:" + ((IPEndPoint)silent.LocalEndPoint).Port, dialer, V(), Smp(), new Settings(600, 3));
                    long ms = Tls.NowMs() - t0;
                    T.Eq(o.Line(), "timeout at=tls");
                    if (ms < 500 || ms > 3000) throw new Exception("the bound of 600 ms ended after " + ms + " ms");
                }
            });
            T.Check("loopback: a request this extension cannot make is refused before anything is sent", () =>
            {
                foreach (var bad in new Action[] { () => Client.Dial("127.0.0.1:9", dialer, V(), Smp(4), settings), () => Client.Dial("127.0.0.1:9", dialer, V(), Smp(1, "tempus_node"), settings),
                    () => Client.Dial("127.0.0.1:9", dialer, V(), new Request.Call(new byte[17], "m", "f", new Term[0]), settings) })
                {
                    try { bad(); throw new Exception("not refused"); } catch (ArgumentException) { }
                }
            });
        }

        public static int Run(string root)
        {
            T.Check("the OpenSSL found is 4.1.0 or later, and can offer the TLS key exchange group X25519MLKEM768 with an Ed25519 certificate", () =>
            {
                OpenSsl.Require();
                var certs = new Certs(root);
                using (new Listener(certs.Identity("node", "tempus_edge", 1000, 2000, "127.0.0.1:9"), new Verifier(new byte[32], T.B("k1"), () => 0, 0, null), new Settings(1000, 3), "127.0.0.1", 0, _ => null)) { }
            });
            if (T.Failed > 0) { Console.WriteLine("[csharp client tests] " + T.Passed + " passed, " + T.Failed + " failed"); return 1; }
            FramesGolden(root);
            Codec();
            Identities(root);
            AdmissionCases(root);
            Loopback(root);
            Console.WriteLine("[csharp client tests] " + T.Passed + " passed, " + T.Failed + " failed");
            return T.Failed == 0 ? 0 : 1;
        }
    }

    static class Program
    {
        static int Main(string[] argv)
        {
            Console.SetOut(new StreamWriter(Console.OpenStandardOutput()) { AutoFlush = true });
            if (argv.Length == 1 && argv[0] == "openssl")
            {
                // says which OpenSSL was found, or why none can be used; the trials ask this before they run
                try { OpenSsl.Require(); Console.WriteLine(OpenSsl.Version()); return 0; }
                catch (OpenSslUnavailable e) { Console.WriteLine("FAIL: " + e.Message); return 1; }
            }
            if (argv.Length >= 2 && argv[0] == "client") return ClientTests.Run(Path.GetFullPath(argv[1]));
            if (argv.Length >= 3 && argv[0] == "node") return NodeTests.Run(Path.GetFullPath(argv[1]), argv[2]);
            Console.Error.WriteLine("bees-tempus-tests openssl | client BEES_ROOT | node BEES_ROOT MODEL_CASES_FILE");
            return 2;
        }
    }
}
