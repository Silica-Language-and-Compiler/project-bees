// EXAMPLE ONLY, not for production. See README.md in the directory above.
//
// The part of the Erlang external term format (ETF) that tempus/1 uses: maps with atom keys, atoms, binaries,
// integers and lists. Written from example_tempus_clients/writing-a-tempus-client.md section 4 and the ruled design
// (development-plan/tempus-design.md sections 5 and 8).
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;

namespace Bees.Tempus
{
    /// <summary>A body, a token or a peer this extension does not accept. Why says why.</summary>
    public sealed class Refused : Exception
    {
        public string Why { get; }
        public Refused(string why) : base(why) { Why = why; }
    }

    /// <summary>One term of the subset.</summary>
    public abstract class Term { }

    public sealed class TAtom : Term
    {
        public string Name { get; }
        public TAtom(string name) { Name = name; }
        public override bool Equals(object o) => o is TAtom a && a.Name == Name;
        public override int GetHashCode() => Name.GetHashCode();
    }

    public sealed class TInt : Term
    {
        public long Value { get; }
        public TInt(long value) { Value = value; }
        public override bool Equals(object o) => o is TInt a && a.Value == Value;
        public override int GetHashCode() => Value.GetHashCode();
    }

    public sealed class TBin : Term
    {
        public byte[] Bytes { get; }
        public TBin(byte[] bytes) { Bytes = bytes; }
        public override bool Equals(object o) => o is TBin a && a.Bytes.AsSpan().SequenceEqual(Bytes);
        public override int GetHashCode() => Bytes.Length;
    }

    public sealed class TList : Term
    {
        public IReadOnlyList<Term> Items { get; }
        public TList(IEnumerable<Term> items) { Items = items.ToList(); }
        public override bool Equals(object o) => o is TList a && a.Items.SequenceEqual(Items);
        public override int GetHashCode() => Items.Count;
    }

    /// <summary>A map whose keys are atoms; a key is the atom's name. The order of the pairs is the order given or read.</summary>
    public sealed class TMap : Term
    {
        public IReadOnlyList<KeyValuePair<string, Term>> Fields { get; }
        public TMap(IEnumerable<KeyValuePair<string, Term>> fields) { Fields = fields.ToList(); }
        public TMap(params (string, Term)[] fields) { Fields = fields.Select(f => new KeyValuePair<string, Term>(f.Item1, f.Item2)).ToList(); }
        public Term Get(string key)
        {
            foreach (var f in Fields) if (f.Key == key) return f.Value;
            return null;
        }
        public bool Has(string key) => Get(key) != null;
        public override bool Equals(object o) => o is TMap a && a.Fields.Count == Fields.Count && Fields.All(f => f.Value.Equals(a.Get(f.Key)));
        public override int GetHashCode() => Fields.Count;
    }

    public static class Hex
    {
        public static string Of(byte[] b) => Convert.ToHexString(b).ToLowerInvariant();
        public static string Of(byte[] b, int count) => Convert.ToHexString(b, 0, Math.Min(count, b.Length)).ToLowerInvariant();

        public static byte[] Parse(string s)
        {
            if (s.Length % 2 != 0 || !s.All(Uri.IsHexDigit)) throw new ArgumentException("not hex digits in pairs");
            return Convert.FromHexString(s);
        }
    }

    public static class Etf
    {
        /// <summary>The greatest length of a frame's body.</summary>
        public const int FrameMax = 131072;

        static readonly UTF8Encoding StrictUtf8 = new UTF8Encoding(false, true);

        static int CompareBytes(byte[] a, byte[] b)
        {
            int n = Math.Min(a.Length, b.Length);
            for (int i = 0; i < n; i++) { int d = a[i] - b[i]; if (d != 0) return d; }
            return a.Length - b.Length;
        }

        static void U32(MemoryStream o, long n)
        {
            o.WriteByte((byte)(n >> 24)); o.WriteByte((byte)(n >> 16)); o.WriteByte((byte)(n >> 8)); o.WriteByte((byte)n);
        }

        static void Enc(Term term, MemoryStream o)
        {
            switch (term)
            {
                case TAtom a:
                {
                    var name = Encoding.UTF8.GetBytes(a.Name);
                    if (name.Length > 255) throw new ArgumentException("atom too long for tempus/1");
                    o.WriteByte(0x77); o.WriteByte((byte)name.Length); o.Write(name, 0, name.Length);
                    break;
                }
                case TInt i:
                {
                    long v = i.Value;
                    if (v >= 0 && v <= 255) { o.WriteByte(0x61); o.WriteByte((byte)v); }
                    else if (v >= int.MinValue && v <= int.MaxValue) { o.WriteByte(0x62); U32(o, v); }
                    else
                    {
                        if (v == long.MinValue) throw new ArgumentException("integer beyond this writer");
                        ulong mag = (ulong)(v < 0 ? -v : v);
                        var digits = new List<byte>();
                        while (mag != 0) { digits.Add((byte)(mag & 0xff)); mag >>= 8; }
                        o.WriteByte(0x6e); o.WriteByte((byte)digits.Count); o.WriteByte((byte)(v < 0 ? 1 : 0)); o.Write(digits.ToArray(), 0, digits.Count);
                    }
                    break;
                }
                case TBin b:
                    o.WriteByte(0x6d); U32(o, b.Bytes.Length); o.Write(b.Bytes, 0, b.Bytes.Length);
                    break;
                case TList l:
                    if (l.Items.Count > 0)
                    {
                        o.WriteByte(0x6c); U32(o, l.Items.Count);
                        foreach (var x in l.Items) Enc(x, o);
                    }
                    o.WriteByte(0x6a);
                    break;
                case TMap m:
                {
                    o.WriteByte(0x74); U32(o, m.Fields.Count);
                    // keys in the byte order of their names: every message has exactly one byte form
                    var keys = m.Fields.Select(f => (f.Key, Encoding.UTF8.GetBytes(f.Key), f.Value)).ToList();
                    keys.Sort((x, y) => CompareBytes(x.Item2, y.Item2));
                    foreach (var k in keys) { Enc(new TAtom(k.Key), o); Enc(k.Value, o); }
                    break;
                }
                default: throw new ArgumentException("a term outside the subset");
            }
        }

        /// <summary>The bytes of a term, beginning with the version byte 131.</summary>
        public static byte[] Encode(Term term)
        {
            var o = new MemoryStream();
            o.WriteByte(0x83);
            Enc(term, o);
            return o.ToArray();
        }

        sealed class Reader
        {
            readonly byte[] data; readonly int depthMax;
            public int Pos;
            public Reader(byte[] data, int depthMax) { this.data = data; this.depthMax = depthMax; }

            byte[] Take(int n)
            {
                if (n < 0 || n > data.Length - Pos) throw new Refused("truncated");
                var chunk = new byte[n];
                Buffer.BlockCopy(data, Pos, chunk, 0, n);
                Pos += n;
                return chunk;
            }

            int Byte() => Take(1)[0];

            long U32() { var b = Take(4); return ((long)b[0] << 24) | ((long)b[1] << 16) | ((long)b[2] << 8) | b[3]; }

            int Count() { long n = U32(); if (n > data.Length) throw new Refused("truncated"); return (int)n; }

            static TAtom Atom(byte[] bytes)
            {
                try { return new TAtom(StrictUtf8.GetString(bytes)); }
                catch (ArgumentException) { throw new Refused("an atom name is not UTF-8"); }
            }

            public Term Next(int depth)
            {
                if (depth > depthMax) throw new Refused("too_deep");
                int tag = Byte();
                switch (tag)
                {
                    case 0x77: return Atom(Take(Byte()));
                    case 0x76: { var b = Take(2); return Atom(Take((b[0] << 8) | b[1])); }
                    case 0x61: return new TInt(Byte());
                    case 0x62: return new TInt((int)U32());
                    case 0x6e:
                    {
                        int n = Byte(); int sign = Byte();
                        if (n > 8) throw new Refused("unsupported");
                        var d = Take(n);
                        if (n == 8 && d[7] >= 0x80) throw new Refused("unsupported");
                        long v = 0;
                        for (int i = n - 1; i >= 0; i--) v = (v << 8) | d[i];
                        return new TInt(sign != 0 ? -v : v);
                    }
                    case 0x6d: return new TBin(Take(Count()));
                    case 0x6a: return new TList(Array.Empty<Term>());
                    case 0x6c:
                    {
                        int n = Count();
                        var items = new List<Term>();
                        for (int i = 0; i < n; i++) items.Add(Next(depth + 1));
                        if (Byte() != 0x6a) throw new Refused("bad_tag");
                        return new TList(items);
                    }
                    case 0x74:
                    {
                        int n = Count();
                        var m = new List<KeyValuePair<string, Term>>();
                        var seen = new HashSet<string>();
                        for (int i = 0; i < n; i++)
                        {
                            if (!(Next(depth + 1) is TAtom key)) throw new Refused("bad_tag");
                            if (!seen.Add(key.Name)) throw new Refused("duplicate_field");
                            m.Add(new KeyValuePair<string, Term>(key.Name, Next(depth + 1)));
                        }
                        return new TMap(m);
                    }
                    default:
                        throw new Refused(tag == 0x68 || tag == 0x69 || tag == 0x6b || tag == 0x46 ? "bad_tag" : "unsupported");
                }
            }
        }

        /// <summary>The one term of data, which must begin with 131 and hold nothing after the term.</summary>
        public static Term Decode(byte[] data, int depthMax = 6, int sizeMax = FrameMax)
        {
            if (data.Length > sizeMax) throw new Refused("too_large");
            if (data.Length == 0) throw new Refused("truncated");
            if (data[0] != 0x83) throw new Refused("bad_version");
            var r = new Reader(data, depthMax) { Pos = 1 };
            var term = r.Next(1);
            if (r.Pos != data.Length) throw new Refused("trailing_bytes");
            return term;
        }
    }
}
