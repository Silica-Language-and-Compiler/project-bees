// EXAMPLE ONLY, not for production. See README.md in the directory above.
//
// The tempus/1 messages a peer writes and reads, with every bound of the design's section 8, and the token's
// structure (section 4). The two test-only frames (tick and clock) and their answer (done) are not here: they are no
// part of the extension.
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;

namespace Bees.Tempus
{
    /// <summary>The record that describes one peer.</summary>
    public sealed class Descriptor
    {
        public byte[] Id { get; }
        public byte[] Pub { get; }
        public byte[] Addr { get; }
        public byte[] Token { get; }
        public Descriptor(byte[] id, byte[] pub, byte[] addr, byte[] token) { Id = id; Pub = pub; Addr = addr; Token = token; }
        public TMap Term() => new TMap(("id", new TBin(Id)), ("pub", new TBin(Pub)), ("addr", new TBin(Addr)), ("token", new TBin(Token)));
        public override bool Equals(object o) => o is Descriptor d && d.Id.AsSpan().SequenceEqual(Id) && d.Pub.AsSpan().SequenceEqual(Pub) &&
            d.Addr.AsSpan().SequenceEqual(Addr) && d.Token.AsSpan().SequenceEqual(Token);
        public override int GetHashCode() => Id.Length > 3 ? BitConverter.ToInt32(Id, 0) : 0;
        /// <summary>The first 8 bytes of the identifier, as hex: enough to tell peers apart in a line of output.</summary>
        public string Id8() => Hex.Of(Id, 8);
        public string AddrText() => Encoding.UTF8.GetString(Addr);
    }

    /// <summary>One entry of a shuffle or sample frame: a descriptor and its age.</summary>
    public sealed class Entry
    {
        public int Age { get; }
        public Descriptor D { get; }
        public Entry(int age, Descriptor d) { Age = age; D = d; }
        public override bool Equals(object o) => o is Entry e && e.Age == Age && e.D.Equals(D);
        public override int GetHashCode() => D.GetHashCode() * 31 + Age;
    }

    /// <summary>A body as this extension read it.</summary>
    public abstract class Body
    {
        public abstract string Kind { get; }

        public sealed class Advert : Body { public Descriptor D; public override string Kind => "advert"; }
        public sealed class Challenge : Body { public byte[] Nonce; public override string Kind => "pop_challenge"; }
        public sealed class Response : Body { public byte[] Sig; public override string Kind => "pop_response"; }
        public sealed class KeyRotated : Body { public byte[] Kid; public override string Kind => "key_rotated"; }
        /// <summary>Name is "shuffle", "shuffle_reply" or "sample_reply".</summary>
        public sealed class Entries : Body
        {
            public string Name; public string Store; public IReadOnlyList<Entry> List;
            public override string Kind => Name;
        }
        public sealed class Sample : Body { public string Store; public int N; public override string Kind => "sample"; }
        /// <summary>TRUST's answer to a call.</summary>
        public sealed class Result : Body { public byte[] ReqId; public Term Value; public override string Kind => "result"; }
    }

    /// <summary>The five fields of a token, the payload bytes the producer signed, and the signature.</summary>
    public sealed class Token
    {
        public byte[] Kid, Sub, Payload, Sig;
        public string Typ;
        public long Nbf, Exp;
    }

    public static class Frames
    {
        public static readonly IReadOnlyList<string> PeerTypes = new[] { "tempus_edge", "tempus_bridge", "tempus_sentinel" };
        public const int AgeMax = 65535;
        /// <summary>The ceiling of entries in one frame; a network's shuffle length is at or below it.</summary>
        public const int EntriesMax = 64;
        public const int ReqIdMax = 16;

        // ---------------------------------------------------------------- what a peer writes
        static TAtom Store(string name)
        {
            if (!PeerTypes.Contains(name)) throw new ArgumentException("a store is one of tempus_edge, tempus_bridge, tempus_sentinel");
            return new TAtom(name);
        }

        /// <summary>The body with its 4-byte length, most significant byte first, as it travels.</summary>
        public static byte[] Frame(byte[] body)
        {
            if (body.Length > Etf.FrameMax) throw new ArgumentException("a body above the frame ceiling");
            var o = new byte[4 + body.Length];
            int n = body.Length;
            o[0] = (byte)(n >> 24); o[1] = (byte)(n >> 16); o[2] = (byte)(n >> 8); o[3] = (byte)n;
            Buffer.BlockCopy(body, 0, o, 4, n);
            return o;
        }

        public static byte[] Advert(Descriptor d) => Etf.Encode(new TMap(("t", new TAtom("advert")), ("ver", new TInt(1)), ("d", d.Term())));

        public static byte[] Challenge(byte[] nonce) => Etf.Encode(new TMap(("t", new TAtom("pop_challenge")), ("nonce", new TBin(nonce))));

        public static byte[] Response(byte[] sig) => Etf.Encode(new TMap(("t", new TAtom("pop_response")), ("sig", new TBin(sig))));

        public static byte[] KeyRotated(byte[] kid) => Etf.Encode(new TMap(("t", new TAtom("key_rotated")), ("kid", new TBin(kid))));

        static byte[] EntriesFrame(string kind, string store, IEnumerable<Entry> entries) =>
            Etf.Encode(new TMap(("t", new TAtom(kind)), ("store", Store(store)),
                ("entries", new TList(entries.Select(e => (Term)new TMap(("age", new TInt(e.Age)), ("d", e.D.Term())))))));

        public static byte[] Shuffle(string store, IEnumerable<Entry> entries) => EntriesFrame("shuffle", store, entries);

        public static byte[] ShuffleReply(string store, IEnumerable<Entry> entries) => EntriesFrame("shuffle_reply", store, entries);

        public static byte[] SampleReply(string store, IEnumerable<Entry> entries) => EntriesFrame("sample_reply", store, entries);

        public static byte[] Sample(string store, int n) => Etf.Encode(new TMap(("t", new TAtom("sample")), ("store", Store(store)), ("n", new TInt(n))));

        /// <summary>
        /// TRUST's request frame, which an edge sends to a bridge: kind is "call" or "cast". The arguments are terms of
        /// this codec's subset. `a` is the number of arguments.
        /// </summary>
        public static byte[] RequestFrame(string kind, byte[] reqId, string module, string function, IReadOnlyList<Term> args)
        {
            if (kind != "call" && kind != "cast") throw new ArgumentException("the kind is call or cast");
            if (reqId.Length < 1 || reqId.Length > ReqIdMax) throw new ArgumentException("req_id is 1 to 16 bytes");
            return Etf.Encode(new TMap(("t", new TAtom(kind)), ("ver", new TInt(1)), ("req_id", new TBin(reqId)), ("m", new TAtom(module)),
                ("f", new TAtom(function)), ("a", new TInt(args.Count)), ("args", new TList(args)), ("opts", new TMap())));
        }

        // ---------------------------------------------------------------- what a peer reads
        static TMap CheckKeys(Term m, string[] keys, string what)
        {
            if (!(m is TMap f)) throw new Refused(what + " is not a map");
            if (f.Fields.Any(x => !keys.Contains(x.Key))) throw new Refused("unknown_field");
            if (keys.Any(k => !f.Has(k))) throw new Refused("missing_field");
            return f;
        }

        static byte[] Bin(TMap f, string key, int lo, int hi, string text)
        {
            if (!(f.Get(key) is TBin v) || v.Bytes.Length < lo || v.Bytes.Length > hi) throw new Refused(text);
            return v.Bytes;
        }

        public static Descriptor ReadDescriptor(Term t)
        {
            var f = CheckKeys(t, new[] { "id", "pub", "addr", "token" }, "descriptor");
            return new Descriptor(Bin(f, "id", 64, 64, "id is not 64 bytes"), Bin(f, "pub", 32, 32, "pub is not 32 bytes"),
                Bin(f, "addr", 3, 261, "addr is not 3 to 261 bytes"), Bin(f, "token", 65, 1024, "token is not 65 to 1024 bytes"));
        }

        static string StoreOf(TMap f)
        {
            if (!(f.Get("store") is TAtom s) || !PeerTypes.Contains(s.Name)) throw new Refused("store is not a peer type");
            return s.Name;
        }

        /// <summary>
        /// A body as a message, every bound checked; Refused(reason) otherwise. shuffleLength is the most entries one
        /// frame may hold, and the most a sample may ask for.
        /// </summary>
        public static Body ReadBody(byte[] body, int shuffleLength)
        {
            if (!(Etf.Decode(body) is TMap m)) throw new Refused("bad_tag");
            if (!(m.Get("t") is TAtom ta)) throw new Refused("unknown kind");
            string kind = ta.Name;
            switch (kind)
            {
                case "advert":
                {
                    var f = CheckKeys(m, new[] { "t", "ver", "d" }, kind);
                    if (!new TInt(1).Equals(f.Get("ver"))) throw new Refused("ver is not 1");
                    return new Body.Advert { D = ReadDescriptor(f.Get("d")) };
                }
                case "pop_challenge": return new Body.Challenge { Nonce = Bin(CheckKeys(m, new[] { "t", "nonce" }, kind), "nonce", 32, 32, "nonce is not 32 bytes") };
                case "pop_response": return new Body.Response { Sig = Bin(CheckKeys(m, new[] { "t", "sig" }, kind), "sig", 64, 64, "sig is not 64 bytes") };
                case "key_rotated": return new Body.KeyRotated { Kid = Bin(CheckKeys(m, new[] { "t", "kid" }, kind), "kid", 1, 64, "kid is not 1 to 64 bytes") };
                case "shuffle":
                case "shuffle_reply":
                case "sample_reply":
                {
                    var f = CheckKeys(m, new[] { "t", "store", "entries" }, kind);
                    string st = StoreOf(f);
                    if (!(f.Get("entries") is TList list)) throw new Refused("entries is not a list");
                    if (list.Items.Count > EntriesMax || list.Items.Count > shuffleLength) throw new Refused("more entries than the shuffle length");
                    var o = new List<Entry>();
                    foreach (var e in list.Items)
                    {
                        var ef = CheckKeys(e, new[] { "age", "d" }, "entry");
                        if (!(ef.Get("age") is TInt age) || age.Value < 0 || age.Value > AgeMax) throw new Refused("age is not 0 to 65535");
                        o.Add(new Entry((int)age.Value, ReadDescriptor(ef.Get("d"))));
                    }
                    return new Body.Entries { Name = kind, Store = st, List = o };
                }
                case "sample":
                {
                    var f = CheckKeys(m, new[] { "t", "store", "n" }, kind);
                    string st = StoreOf(f);
                    if (!(f.Get("n") is TInt n) || n.Value < 1 || n.Value > shuffleLength) throw new Refused("n is not 1 to the shuffle length");
                    return new Body.Sample { Store = st, N = (int)n.Value };
                }
                case "result":
                {
                    var f = CheckKeys(m, new[] { "t", "ver", "req_id", "value" }, kind);
                    if (!new TInt(1).Equals(f.Get("ver"))) throw new Refused("ver is not 1");
                    return new Body.Result { ReqId = Bin(f, "req_id", 1, ReqIdMax, "req_id is not 1 to 16 bytes"), Value = f.Get("value") };
                }
                default: throw new Refused("unknown kind");
            }
        }

        // ---------------------------------------------------------------- the token
        /// <summary>The structure and bounds of a token. The signature is NOT verified here (Verifier does that).</summary>
        public static Token ReadToken(byte[] token)
        {
            if (token.Length < 65 || token.Length > 1024) throw new Refused("token is not 65 to 1024 bytes");
            var sig = token.AsSpan(0, 64).ToArray();
            var payload = token.AsSpan(64).ToArray();
            if (!(Etf.Decode(payload, 2) is TMap m) || m.Fields.Count != 5) throw new Refused("the token is not a map of five keys");
            var f = CheckKeys(m, new[] { "kid", "sub", "typ", "nbf", "exp" }, "token");
            var kid = Bin(f, "kid", 1, 64, "kid is not 1 to 64 bytes");
            var sub = Bin(f, "sub", 32, 32, "sub is not 32 bytes");
            if (!(f.Get("typ") is TAtom typ) || !PeerTypes.Contains(typ.Name)) throw new Refused("typ is not a peer type");
            if (!(f.Get("nbf") is TInt nbf) || !(f.Get("exp") is TInt exp) || nbf.Value < 0 || exp.Value < 0) throw new Refused("nbf or exp is not a time");
            if (exp.Value <= nbf.Value) throw new Refused("exp is not after nbf");
            return new Token { Kid = kid, Sub = sub, Typ = typ.Name, Nbf = nbf.Value, Exp = exp.Value, Payload = payload, Sig = sig };
        }
    }
}
