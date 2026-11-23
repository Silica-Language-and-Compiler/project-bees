// EXAMPLE ONLY, not for production. See README.md in the directory above.
//
// A node's configuration, as a value the application builds: the keys of the `tempus` section of bees.config
// (development-plan/tempus-design.md section 11), with the bounds and refusals of tools/bees_tempus_conf.py and the
// start refusals of the Silica node (bees_tempus_node@boot_why). Nothing has a default: every constructor parameter
// must be written, and a value outside its bounds is refused, never clamped.
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;

namespace Bees.Tempus
{
    /// <summary>One store: its capacity, its shuffle length and how often it ticks.</summary>
    public sealed class StoreConfig
    {
        public int Capacity { get; }
        public int ShuffleLength { get; }
        public long TickMs { get; }
        public StoreConfig(int capacity, int shuffleLength, long tickMs) { Capacity = capacity; ShuffleLength = shuffleLength; TickMs = tickMs; }
    }

    /// <summary>One sentinel a node joins through. CertName names an entry of the node's tempus whitelist.</summary>
    public sealed class SentinelAddress
    {
        public string Host { get; }
        public int Port { get; }
        public string CertName { get; }
        public SentinelAddress(string host, int port, string certName) { Host = host; Port = port; CertName = certName; }
        public string Address => Host + ":" + Port;
    }

    /// <summary>The start of a node was refused. Why is the reason, the text after "tempus: boot refused: ".</summary>
    public sealed class ConfigRefused : Exception
    {
        public string Why { get; }
        public ConfigRefused(string why) : base("tempus: boot refused: " + why) { Why = why; }
    }

    /// <summary>
    /// The `tempus` section. The names are the section's keys in the casing of C#.
    ///
    /// role              "edge" or "sentinel": the node's own type, and the type its token must carry. "bridge" is
    ///                   refused: a bridge is also a TRUST node, and this extension runs TEMPUS only
    /// listenAddress     the address the node listens on, an IPv4 literal or a host name; port its port
    /// sentinels         the sentinels the node joins through, 1 to 16; empty only for a first sentinel
    /// edge, bridge, sentinel   the three stores
    /// producerKid, producerKey   the one current producer key: its kid (1 to 64 bytes) and the 32 raw bytes of the key
    /// whitelist         the tempus whitelist: by name, the certificate of each bridge and sentinel this node accepts,
    ///                   in the order that the audit lines count entries in
    /// shuffleTimeoutMs  ONE bound for a whole connection, from the dial or the accept to the close
    /// inflightMax       accepted connections at once
    /// clockSkewMs       the clock difference allowed when a token's time is judged
    /// clockBack         "follow", "hold" or "stop": what a reading of the system clock earlier than the node's time does
    /// clockBackLimitS   required under "stop" (the greatest step back in seconds still followed), null under the others
    /// clockFail         "continue" or "pause": what a reading that fails after a good one does
    /// clockReadMs       how often the system clock is read
    /// joinRetryInitialMs, joinRetryMaxMs   the delays between attempts to join when no sentinel answers
    /// </summary>
    public sealed class TempusConfig
    {
        public string Role { get; }
        public string ListenAddress { get; }
        public int Port { get; }
        public IReadOnlyList<SentinelAddress> Sentinels { get; }
        public StoreConfig Edge { get; }
        public StoreConfig Bridge { get; }
        public StoreConfig Sentinel { get; }
        public byte[] ProducerKid { get; }
        public byte[] ProducerKey { get; }
        public IReadOnlyList<KeyValuePair<string, Certificate>> Whitelist { get; }
        public long ShuffleTimeoutMs { get; }
        public int InflightMax { get; }
        public long ClockSkewMs { get; }
        public string ClockBack { get; }
        public long? ClockBackLimitS { get; }
        public string ClockFail { get; }
        public long ClockReadMs { get; }
        public long JoinRetryInitialMs { get; }
        public long JoinRetryMaxMs { get; }

        public TempusConfig(string role, string listenAddress, int port, IReadOnlyList<SentinelAddress> sentinels, StoreConfig edge, StoreConfig bridge,
                            StoreConfig sentinel, byte[] producerKid, byte[] producerKey, IReadOnlyList<KeyValuePair<string, Certificate>> whitelist,
                            long shuffleTimeoutMs, int inflightMax, long clockSkewMs, string clockBack, long? clockBackLimitS, string clockFail,
                            long clockReadMs, long joinRetryInitialMs, long joinRetryMaxMs)
        {
            Role = role; ListenAddress = listenAddress; Port = port; Sentinels = sentinels; Edge = edge; Bridge = bridge; Sentinel = sentinel;
            ProducerKid = producerKid; ProducerKey = producerKey; Whitelist = whitelist; ShuffleTimeoutMs = shuffleTimeoutMs; InflightMax = inflightMax;
            ClockSkewMs = clockSkewMs; ClockBack = clockBack; ClockBackLimitS = clockBackLimitS; ClockFail = clockFail; ClockReadMs = clockReadMs;
            JoinRetryInitialMs = joinRetryInitialMs; JoinRetryMaxMs = joinRetryMaxMs;
        }

        public StoreConfig Store(string typ) => typ == "tempus_edge" ? Edge : typ == "tempus_bridge" ? Bridge : Sentinel;

        /// <summary>The node's own type as a peer type.</summary>
        public string Typ => "tempus_" + Role;

        /// <summary>The clock difference in whole seconds, as the node judges tokens: clockSkewMs / 1000, rounded down.</summary>
        public long SkewSeconds => ClockSkewMs / 1000;

        static string Int(string key, long v, long lo, long hi) =>
            v < lo ? "tempus." + key + ": " + v + " is below " + lo + " (bounds " + lo + " to " + hi + "; never clamped)" :
            v > hi ? "tempus." + key + ": " + v + " is above " + hi + " (bounds " + lo + " to " + hi + "; never clamped)" : null;

        static string Atom(string key, string v, params string[] choices) =>
            choices.Contains(v) ? null : "tempus." + key + ": expected one of " + string.Join(", ", choices);

        static string StoreWhy(string name, StoreConfig s)
        {
            if (s == null) return "tempus." + name + ": required (no default)";
            return Int(name + ".capacity", s.Capacity, 1, 256) ?? Int(name + ".shuffle_length", s.ShuffleLength, 1, 64) ?? Int(name + ".tick_ms", s.TickMs, 100, 3600000)
                ?? (s.ShuffleLength > s.Capacity ? "tempus." + name + ".shuffle_length: " + s.ShuffleLength + " is above the capacity " + s.Capacity : null);
        }

        /// <summary>
        /// Why this configuration is refused, or null. The checks, their order and their texts are those of
        /// tools/bees_tempus_conf.py (a text there begins with the file's name and line, which a value does not have).
        /// </summary>
        public string Refusal()
        {
            string why = Atom("role", Role, "edge", "bridge", "sentinel");
            if (why != null) return why;
            if (Role == "bridge") return "tempus.role: bridge needs mode tempus-trust (a bridge runs TRUST and TEMPUS); this extension runs TEMPUS only and cannot be a bridge";
            string kind = Addresses.Kind(ListenAddress ?? "");
            if (kind == "bad") return "tempus.listen_address: \"" + ListenAddress + "\" is not an IPv4 or IPv6 literal or a host name";
            if (kind == "ipv6") return "tempus.listen_address: " + ListenAddress + " is not built yet: this extension listens on IPv4 addresses and host names";
            why = Int("port", Port, 1, 65535) ?? Int("shuffle_timeout_ms", ShuffleTimeoutMs, 100, 60000) ?? Int("inflight_max", InflightMax, 1, 64)
                ?? Int("clock_skew_ms", ClockSkewMs, 0, 300000) ?? Int("join_retry_initial_ms", JoinRetryInitialMs, 100, 3600000)
                ?? Int("join_retry_max_ms", JoinRetryMaxMs, 100, 3600000) ?? Int("clock_read_ms", ClockReadMs, 100, 60000);
            if (why != null) return why;
            if (JoinRetryMaxMs < JoinRetryInitialMs) return "tempus.join_retry_max_ms: below join_retry_initial_ms";
            why = Atom("clock_back", ClockBack, "follow", "hold", "stop") ?? Atom("clock_fail", ClockFail, "continue", "pause");
            if (why != null) return why;
            if (ClockBack == "stop")
            {
                if (ClockBackLimitS == null) return "tempus.clock_back_limit_s: required when clock_back is stop (no default)";
                why = Int("clock_back_limit_s", ClockBackLimitS.Value, 0, 86400);
                if (why != null) return why;
            }
            else if (ClockBackLimitS != null)
            {
                return "tempus.clock_back_limit_s: clock_back is " + ClockBack + ", so no step back stops the node: remove clock_back_limit_s (it is for clock_back stop only)";
            }
            why = StoreWhy("edge", Edge) ?? StoreWhy("bridge", Bridge) ?? StoreWhy("sentinel", Sentinel);
            if (why != null) return why;
            if (ProducerKid == null || ProducerKid.Length < 1 || ProducerKid.Length > 64) return "tempus.producer_key: the kid is not 1 to 64 bytes";
            if (ProducerKey == null || ProducerKey.Length != 32) return "tempus.producer_key: the public key is not 32 bytes as 64 hex digits";
            var sentinels = Sentinels ?? Array.Empty<SentinelAddress>();
            var whitelist = Whitelist ?? Array.Empty<KeyValuePair<string, Certificate>>();
            if (sentinels.Count == 0)
            {
                if (Role != "sentinel") return "tempus.sentinels: required unless the node is the first sentinel (role sentinel)";
            }
            else
            {
                if (sentinels.Count > 16) return "tempus.sentinels: expected a list of 1 to 16 {Host, Port, CertName}";
                foreach (var s in sentinels)
                {
                    string k = Addresses.Kind(s.Host ?? "");
                    if (k != "ipv4" && k != "name") return "tempus.sentinels: \"" + s.Host + "\" is not an IPv4 literal or a host name";
                    why = Int("sentinels", s.Port, 1, 65535);
                    if (why != null) return why;
                    // not a refusal of tools/bees_tempus_conf.py, which does not read the whitelist: section 11 says CertName
                    // names an entry of the tempus whitelist, and a sentinel that is not in it could never be admitted
                    if (!whitelist.Any(w => w.Key == s.CertName)) return "tempus.sentinels: \"" + s.CertName + "\" names no entry of the tempus whitelist";
                }
            }
            return null;
        }

        /// <summary>Why a node with this configuration and identity may not start, or null: the configuration's refusal, then the node's.</summary>
        public string StartRefusal(Identity identity)
        {
            string why = Refusal();
            if (why != null) return why;
            return Boot.Why(Array.IndexOf(new[] { "edge", "bridge", "sentinel" }, Role) + 1, identity.PeerId.Length, identity.Pub, 32, identity.Token,
                ProducerKid.Length, ProducerKey.Length, InflightMax, ShuffleTimeoutMs, JoinRetryInitialMs, JoinRetryMaxMs, SkewSeconds,
                (Whitelist?.Count ?? 0) * 128, new[] { Edge, Bridge, Sentinel }, Array.IndexOf(new[] { "follow", "hold", "stop" }, ClockBack) + 1,
                ClockBackLimitS ?? 0, Array.IndexOf(new[] { "continue", "pause" }, ClockFail) + 1, ClockReadMs);
        }
    }

    public static class Addresses
    {
        static readonly Regex Ipv4 = new Regex(@"^(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}$", RegexOptions.ECMAScript);
        static readonly Regex Name = new Regex(@"^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$", RegexOptions.ECMAScript);

        /// <summary>"ipv4", "ipv6", "name" or "bad", as tools/bees_conf.py tells addresses apart.</summary>
        public static string Kind(string a)
        {
            if (Ipv4.IsMatch(a)) return "ipv4";
            if (a.Contains(':') && a.All(c => Uri.IsHexDigit(c) || c == ':' || c == '.')) return "ipv6";
            if (a.Length <= 253 && Name.IsMatch(a) && !a.All(c => (c >= '0' && c <= '9') || c == '.')) return "name";
            return "bad";
        }

        /// <summary>An address a node dials from a gossiped entry: a dotted quad, a colon, a port of 1 to 65535. A name is not resolved.</summary>
        public static bool Dialable(string addr)
        {
            int at = addr.IndexOf(':');
            if (at < 7) return false;
            string port = addr.Substring(at + 1);
            if (port.Length == 0 || port.Length > 5 || !port.All(c => c >= '0' && c <= '9')) return false;
            int p = int.Parse(port);
            if (p < 1 || p > 65535) return false;
            var parts = addr.Substring(0, at).Split('.');
            return parts.Length == 4 && parts.All(x => x.Length >= 1 && x.Length <= 3 && x.All(c => c >= '0' && c <= '9'));
        }
    }

    public static class Boot
    {
        /// <summary>
        /// Why the Silica node refuses to start from its arguments alone (bees_tempus_node@boot_why), the same checks
        /// in the same order with the same texts; null when it may start. The numbers are the Silica node's: typ 1
        /// edge, 2 bridge, 3 sentinel; back 1 follow, 2 hold, 3 stop; fail 1 continue, 2 pause. stores holds the edge,
        /// bridge and sentinel store. The node's token is judged as far as its structure, its type and its key. (The
        /// Silica node's refusal of an externally driven node on an address that is not loopback has no place here:
        /// this extension has no externally driven node.)
        /// </summary>
        public static string Why(int typ, int idBytes, byte[] pub, int seedBytes, byte[] token, int kidBytes, int producerKeyBytes, long inflightMax,
                                 long shuffleTimeoutMs, long joinInitialMs, long joinMaxMs, long skew, int whitelistHexChars, IReadOnlyList<StoreConfig> stores,
                                 int back, long backLimit, int fail, long clockReadMs)
        {
            if (typ < 1 || typ > 3) return "the node's type is not edge, bridge or sentinel";
            if (idBytes != 64 || pub.Length != 32 || seedBytes != 32) return "the identity is not a 64-byte peer id, a 32-byte key and a 32-byte seed";
            Token t;
            try { t = Frames.ReadToken(token); } catch (Refused e) { return "the node's token does not read: " + e.Why; }
            if (Frames.PeerTypes.ToList().IndexOf(t.Typ) + 1 != typ) return "the node's token is for another peer type than the node's";
            if (!t.Sub.AsSpan().SequenceEqual(pub)) return "the node's token names another key";
            if (kidBytes < 1 || kidBytes > 64 || producerKeyBytes != 32) return "the producer key is not a kid of 1 to 64 bytes and a 32-byte key";
            if (inflightMax < 1 || inflightMax > 64) return "inflight_max is not 1 to 64";
            if (shuffleTimeoutMs < 1) return "shuffle_timeout_ms is below 1";
            if (joinInitialMs < 1 || joinMaxMs < joinInitialMs) return "the join's initial delay is below 1 or above its maximum";
            if (skew < 0) return "clock_skew is below 0";
            if (whitelistHexChars % 128 != 0) return "the tempus whitelist is not 128 hex characters per certificate";
            for (int i = 0; i < stores.Count; i++)
            {
                var s = stores[i];
                string name = Frames.PeerTypes[i];
                if (s.Capacity < 1 || s.Capacity > 256) return name + ": capacity is not 1 to 256";
                if (s.ShuffleLength < 1 || s.ShuffleLength > 64 || s.ShuffleLength > s.Capacity) return name + ": shuffle_length is not 1 to 64 and at most the capacity";
                if (s.TickMs < 1) return name + ": tick_ms is below 1";
            }
            if (back < 1 || back > 3) return "clock_back is not follow (1), hold (2) or stop (3)";
            if (back == 3 && backLimit < 0) return "clock_back_limit_s is below 0";
            if (fail < 1 || fail > 2) return "clock_fail is not continue (1) or pause (2)";
            if (clockReadMs < 1) return "clock_read_ms is below 1";
            return null;
        }
    }
}
