// A usable example, to be used carefully. See README.md in the directory above.
//
// What a peer holds (its identity) and what the client half checks of another peer (the verifier): the token, the
// channel binding, the tempus whitelist and the proof of possession. Design section 4; the order of the checks is the
// node's (writing-a-tempus-client.md section 6).
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;

namespace Bees.Tempus
{
    /// <summary>
    /// One peer: its Ed25519 private key, its certificate self-signed over that key, its token exactly as the producer
    /// gave it, and the listen address it advertises, as the text host:port. The private key stays inside the
    /// SigningKey object, which hands it to OpenSSL only; nothing here prints it.
    /// </summary>
    public sealed class Identity
    {
        public Certificate Certificate { get; }
        public SigningKey Key { get; }
        public byte[] Token { get; }
        public string Addr { get; }
        public byte[] Pub { get; }
        public byte[] PeerId { get; }

        public Identity(Certificate certificate, SigningKey key, byte[] token, string addr)
        {
            Certificate = certificate; Key = key; Token = token; Addr = addr;
            try { Pub = certificate.TempusKey(); } catch (Refused e) { throw new ArgumentException(e.Why); }
            PeerId = Crypto.PeerId(Pub);
            if (token == null || token.Length < 65 || token.Length > 1024) throw new ArgumentException("a token is 65 to 1024 bytes");
            int n = Encoding.UTF8.GetByteCount(addr);
            if (n < 3 || n > 261) throw new ArgumentException("a listen address is 3 to 261 bytes");
            if (!key.Pub.AsSpan().SequenceEqual(Pub)) throw new ArgumentException("the private key is not the certificate's key");
        }

        public Descriptor Descriptor() => new Descriptor(PeerId, Pub, Encoding.UTF8.GetBytes(Addr), Token);

        public Entry Entry(int age = 0) => new Entry(age, Descriptor());

        /// <summary>The proof of possession: this key's signature over the peer's nonce followed by this peer's own token.</summary>
        public byte[] Prove(byte[] nonce) => Key.Sign(Crypto.Concat(nonce, Token));

        public Identity WithToken(byte[] other) => new Identity(Certificate, Key, other, Addr);

        public Identity WithAddr(string other) => new Identity(Certificate, Key, Token, other);

        /// <summary>From a PEM certificate file and an unencrypted PKCS#8 PEM key file.</summary>
        public static Identity Load(string certPemPath, string keyPemPath, byte[] token, string addr) =>
            new Identity(Certificate.FromPem(File.ReadAllText(certPemPath)), SigningKey.FromPem(File.ReadAllText(keyPemPath)), token, addr);
    }

    /// <summary>
    /// What the client half needs to check another peer: the producer's current public key (32 raw bytes) and its kid,
    /// a clock in whole seconds since 1970 UTC, the clock difference it allows in seconds, and its tempus whitelist:
    /// the fingerprints (Certificate.Fingerprint) of the certificates of the bridges and sentinels it accepts. The
    /// whitelist may be empty; the client then accepts no bridge and no sentinel on a connection.
    /// </summary>
    public sealed class Verifier
    {
        public byte[] ProducerPub { get; }
        public byte[] Kid { get; }
        public Func<long> Now { get; }
        public long Skew { get; }
        public IReadOnlySet<string> Whitelist { get; }

        public Verifier(byte[] producerPub, byte[] kid, Func<long> now, long skew, IEnumerable<string> whitelist)
        {
            if (producerPub == null || producerPub.Length != 32) throw new ArgumentException("the producer's public key is 32 bytes");
            if (kid == null || kid.Length < 1 || kid.Length > 64) throw new ArgumentException("a kid is 1 to 64 bytes");
            if (skew < 0) throw new ArgumentException("the skew is not negative");
            if (now == null) throw new ArgumentException("a clock is required");
            ProducerPub = producerPub; Kid = kid; Now = now; Skew = skew;
            Whitelist = new HashSet<string>(whitelist ?? Array.Empty<string>());
        }

        /// <summary>The machine's clock, in whole seconds since 1970 UTC.</summary>
        public static long SystemSeconds() => DateTimeOffset.UtcNow.ToUnixTimeSeconds();

        // The checks of a descriptor that need no connection, in the node's order: the token's structure, its kid
        // (Refused("key_rotated")), the time, sub, then `between`, the id hash, the producer's signature.
        Token Check(Descriptor d, Action<Token> between)
        {
            var t = Frames.ReadToken(d.Token);
            long at = Now();
            if (!t.Kid.AsSpan().SequenceEqual(Kid)) throw new Refused("key_rotated");
            if (at < t.Nbf - Skew) throw new Refused("the token is not valid yet");
            if (at >= t.Exp + Skew) throw new Refused("the token has expired");
            if (!t.Sub.AsSpan().SequenceEqual(d.Pub)) throw new Refused("sub is not the peer's key");
            between(t);
            if (!Crypto.PeerId(d.Pub).AsSpan().SequenceEqual(d.Id)) throw new Refused("id is not the SHA-512 of pub");
            if (!Crypto.Ed25519Verify(ProducerPub, t.Payload, t.Sig)) throw new Refused("the signature does not verify");
            return t;
        }

        /// <summary>
        /// The peer of a connection: its advert's descriptor and the certificate it presented in the TLS handshake.
        /// First the channel binding: the advert's pub must be the certificate's key. Then the checks above, with the
        /// whitelist rule between sub and the id hash: a token that says bridge or sentinel needs a certificate of the
        /// whitelist, and a certificate of the whitelist needs such a token.
        /// </summary>
        public Token CheckPeer(Descriptor d, Certificate certificate)
        {
            if (!certificate.TempusKey().AsSpan().SequenceEqual(d.Pub)) throw new Refused("the certificate's key is not the advert's pub");
            return Check(d, t =>
            {
                bool listed = Whitelist.Contains(certificate.Fingerprint);
                bool special = t.Typ == "tempus_bridge" || t.Typ == "tempus_sentinel";
                if (special && !listed) throw new Refused("a " + t.Typ + " whose certificate is not in the tempus whitelist");
                if (listed && !special) throw new Refused("a certificate of the tempus whitelist with a " + t.Typ + " token");
            });
        }

        /// <summary>An entry received in a shuffle or sample frame of the named store: verified without contact.</summary>
        public Token CheckEntry(Descriptor d, string store) =>
            Check(d, t => { if (t.Typ != store) throw new Refused("typ is not the store's type"); });

        /// <summary>The proof of possession: sig must be the signature, under pub, over the nonce this side sent and the peer's token.</summary>
        public void CheckProof(byte[] pub, byte[] nonce, byte[] token, byte[] sig)
        {
            if (!Crypto.Ed25519Verify(pub, Crypto.Concat(nonce, token), sig)) throw new Refused("the proof of possession does not verify");
        }
    }
}
