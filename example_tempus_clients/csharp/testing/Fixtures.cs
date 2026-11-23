// TEST ONLY. Keys from fixed seeds that are written in this repository, and tokens signed with them: keys that belong
// to nobody. Nothing in this file is part of the extension: an extension never makes or signs a token.
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;

namespace Bees.Tempus.Testing
{
    public static class Fixtures
    {
        /// <summary>TEST ONLY: the 32 bytes first, first+1, ...</summary>
        public static byte[] Seed(int first) => Enumerable.Range(0, 32).Select(i => (byte)(first + i)).ToArray();

        /// <summary>TEST ONLY: the Ed25519 private key whose seed is the 32 bytes first, first+1, ...</summary>
        public static SigningKey Key(int first) => SigningKey.FromSeed(Seed(first));

        /// <summary>The bytes a producer signs: the ETF map of the five fields.</summary>
        public static byte[] TokenPayload(string kid, byte[] sub, string typ, long nbf, long exp) =>
            Etf.Encode(new TMap(("kid", new TBin(Encoding.UTF8.GetBytes(kid))), ("sub", new TBin(sub)), ("typ", new TAtom(typ)), ("nbf", new TInt(nbf)), ("exp", new TInt(exp))));

        /// <summary>TEST ONLY: a token signed with a fixture key.</summary>
        public static byte[] MakeToken(SigningKey producer, string kid, byte[] sub, string typ, long nbf, long exp)
        {
            var payload = TokenPayload(kid, sub, typ, nbf, exp);
            return Crypto.Concat(producer.Sign(payload), payload);
        }

        /// <summary>The values of one `fn NAME(i: int64) -> string { case i of { 0 -> "..."; ... } }` table of a generated fixture unit.</summary>
        public static List<string> Table(string text, string fn)
        {
            int start = text.IndexOf("fn " + fn + "(", StringComparison.Ordinal);
            if (start < 0) throw new ArgumentException("no table " + fn);
            string body = text.Substring(start, text.IndexOf("\n}", start, StringComparison.Ordinal) - start);
            return Regex.Matches(body, "^\\s+\\d+ -> \"?([^\";]*)\"?;", RegexOptions.Multiline).Select(m => m.Groups[1].Value).ToList();
        }

        public static string Constant(string text, string fn)
        {
            var m = Regex.Match(text, "fn " + fn + "\\(\\) -> \\w+ \\{ \"?([^\"}]*?)\"? \\}");
            if (!m.Success) throw new ArgumentException("no constant " + fn);
            return m.Groups[1].Value;
        }
    }

    /// <summary>The TEST ONLY certificates and keys of tools/bees_tempus_certs.py, and the seed each was made from.</summary>
    public sealed class Certs
    {
        public static readonly (string Name, int Seed)[] Seeds =
            { ("node", 32), ("other", 64), ("sentinel", 128), ("bridge", 160), ("x1", 176), ("x2", 192), ("x3", 208), ("x4", 224) };
        readonly string dir;

        public Certs(string root) { dir = Path.Combine(root, "trials", "t5_tempus_tls", "certs"); }

        public string CertPath(string name) => Path.Combine(dir, name + ".pem");
        public string KeyPath(string name) => Path.Combine(dir, name + "-key.pem");
        public Certificate Cert(string name) => Certificate.FromPem(File.ReadAllText(CertPath(name)));
        public static int SeedOf(string name) => Seeds.First(s => s.Name == name).Seed;

        /// <summary>The identity `name` with a token of the test producer (seed 0, kid k1 unless said otherwise).</summary>
        public Identity Identity(string name, string typ, long nbf, long exp, string addr, string kid = "k1", SigningKey producer = null, byte[] sub = null)
        {
            var plain = Bees.Tempus.Identity.Load(CertPath(name), KeyPath(name), new byte[65], addr);
            return plain.WithToken(Fixtures.MakeToken(producer ?? Fixtures.Key(0), kid, sub ?? plain.Pub, typ, nbf, exp));
        }
    }
}
