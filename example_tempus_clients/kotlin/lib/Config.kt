// A usable example, to be used carefully. See README.md beside the lib directory.
//
// A node's configuration, as a value the application builds: the keys of the `tempus` section of bees.config
// (development-plan/tempus-design.md section 11), with the bounds and refusals of tools/bees_tempus_conf.py and the
// start refusals of the Silica node (bees_tempus_node@boot_why). Nothing has a default: every constructor parameter
// must be written, and a value outside its bounds is refused, never clamped.
package bees.tempus

import java.security.cert.X509Certificate

/** One store: its capacity, its shuffle length and how often it ticks. */
class StoreConfig(val capacity: Int, val shuffleLength: Int, val tickMs: Long)

/** One sentinel a node joins through. certName names an entry of the node's tempus whitelist. */
class SentinelAddress(val host: String, val port: Int, val certName: String) {
    val address: String get() = "$host:$port"
}

/** The start of a node was refused. why is the reason, the text after "tempus: boot refused: ". */
class ConfigRefused(val why: String) : Exception("tempus: boot refused: $why")

/**
 * The `tempus` section. The names are the section's keys in camel case.
 *
 * role              "edge" or "sentinel": the node's own type, and the type its token must carry. "bridge" is refused:
 *                   a bridge is also a TRUST node, and this extension runs TEMPUS only
 * listenAddress     the address the node listens on, an IPv4 literal or a host name; port its port
 * sentinels         the sentinels the node joins through, 1 to 16; empty only for a first sentinel
 * edge, bridge, sentinel   the three stores
 * producerKid, producerKey   the one current producer key: its kid (1 to 64 bytes) and the 32 raw bytes of the key
 * whitelist         the tempus whitelist: by name, the certificate of each bridge and sentinel this node accepts
 * shuffleTimeoutMs  ONE bound for a whole connection, from the dial or the accept to the close
 * inflightMax       accepted connections at once
 * clockSkewMs       the clock difference allowed when a token's time is judged
 * clockBack         "follow", "hold" or "stop": what a reading of the system clock earlier than the node's time does
 * clockBackLimitS   required under "stop" (the greatest step back in seconds still followed), null under the others
 * clockFail         "continue" or "pause": what a reading that fails after a good one does
 * clockReadMs       how often the system clock is read
 * joinRetryInitialMs, joinRetryMaxMs   the delays between attempts to join when no sentinel answers
 */
class TempusConfig(
    val role: String,
    val listenAddress: String,
    val port: Int,
    val sentinels: List<SentinelAddress>,
    val edge: StoreConfig,
    val bridge: StoreConfig,
    val sentinel: StoreConfig,
    val producerKid: ByteArray,
    val producerKey: ByteArray,
    val whitelist: Map<String, X509Certificate>,
    val shuffleTimeoutMs: Long,
    val inflightMax: Int,
    val clockSkewMs: Long,
    val clockBack: String,
    val clockBackLimitS: Long?,
    val clockFail: String,
    val clockReadMs: Long,
    val joinRetryInitialMs: Long,
    val joinRetryMaxMs: Long,
) {
    fun store(typ: String): StoreConfig = when (typ) { "tempus_edge" -> edge; "tempus_bridge" -> bridge; else -> sentinel }

    /** The node's own type as a peer type. */
    val typ: String get() = "tempus_$role"

    /** The clock difference in whole seconds, as the node judges tokens: clockSkewMs / 1000, rounded down. */
    val skewSeconds: Long get() = clockSkewMs / 1000

    /**
     * Why this configuration is refused, or null. The checks, their order and their texts are those of
     * tools/bees_tempus_conf.py (a text there begins with the file's name and line, which a value does not have).
     */
    fun refusal(): String? {
        fun int(key: String, v: Long, lo: Long, hi: Long): String? = when {
            v < lo -> "tempus.$key: $v is below $lo (bounds $lo to $hi; never clamped)"
            v > hi -> "tempus.$key: $v is above $hi (bounds $lo to $hi; never clamped)"
            else -> null
        }
        fun atom(key: String, v: String, choices: List<String>): String? =
            if (v in choices) null else "tempus.$key: expected one of ${choices.joinToString(", ")}"
        fun store(name: String, s: StoreConfig): String? =
            int("$name.capacity", s.capacity.toLong(), 1, 256) ?: int("$name.shuffle_length", s.shuffleLength.toLong(), 1, 64)
                ?: int("$name.tick_ms", s.tickMs, 100, 3600000)
                ?: if (s.shuffleLength > s.capacity) "tempus.$name.shuffle_length: ${s.shuffleLength} is above the capacity ${s.capacity}" else null
        atom("role", role, listOf("edge", "bridge", "sentinel"))?.let { return it }
        if (role == "bridge") return "tempus.role: bridge needs mode tempus-trust (a bridge runs TRUST and TEMPUS); this extension runs TEMPUS only and cannot be a bridge"
        if (addrKind(listenAddress) == "bad") return "tempus.listen_address: \"$listenAddress\" is not an IPv4 or IPv6 literal or a host name"
        if (addrKind(listenAddress) == "ipv6") return "tempus.listen_address: $listenAddress is not built yet: this extension listens on IPv4 addresses and host names"
        (int("port", port.toLong(), 1, 65535) ?: int("shuffle_timeout_ms", shuffleTimeoutMs, 100, 60000) ?: int("inflight_max", inflightMax.toLong(), 1, 64)
            ?: int("clock_skew_ms", clockSkewMs, 0, 300000) ?: int("join_retry_initial_ms", joinRetryInitialMs, 100, 3600000)
            ?: int("join_retry_max_ms", joinRetryMaxMs, 100, 3600000) ?: int("clock_read_ms", clockReadMs, 100, 60000))?.let { return it }
        if (joinRetryMaxMs < joinRetryInitialMs) return "tempus.join_retry_max_ms: below join_retry_initial_ms"
        (atom("clock_back", clockBack, listOf("follow", "hold", "stop")) ?: atom("clock_fail", clockFail, listOf("continue", "pause")))?.let { return it }
        if (clockBack == "stop") {
            val limit = clockBackLimitS ?: return "tempus.clock_back_limit_s: required when clock_back is stop (no default)"
            int("clock_back_limit_s", limit, 0, 86400)?.let { return it }
        } else if (clockBackLimitS != null) {
            return "tempus.clock_back_limit_s: clock_back is $clockBack, so no step back stops the node: remove clock_back_limit_s (it is for clock_back stop only)"
        }
        (store("edge", edge) ?: store("bridge", bridge) ?: store("sentinel", sentinel))?.let { return it }
        if (producerKid.size !in 1..64) return "tempus.producer_key: the kid is not 1 to 64 bytes"
        if (producerKey.size != 32) return "tempus.producer_key: the public key is not 32 bytes as 64 hex digits"
        if (sentinels.isEmpty()) {
            if (role != "sentinel") return "tempus.sentinels: required unless the node is the first sentinel (role sentinel)"
        } else {
            if (sentinels.size > 16) return "tempus.sentinels: expected a list of 1 to 16 {Host, Port, CertName}"
            for (s in sentinels) {
                if (addrKind(s.host) !in listOf("ipv4", "name")) return "tempus.sentinels: \"${s.host}\" is not an IPv4 literal or a host name"
                int("sentinels", s.port.toLong(), 1, 65535)?.let { return it }
                // not a refusal of tools/bees_tempus_conf.py, which does not read the whitelist: section 11 says CertName
                // names an entry of the tempus whitelist, and a sentinel that is not in it could never be admitted
                if (s.certName !in whitelist) return "tempus.sentinels: \"${s.certName}\" names no entry of the tempus whitelist"
            }
        }
        return null
    }
}

private val IPV4 = Regex("""(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}""")
private val NAME = Regex("""[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*""")

/** "ipv4", "ipv6", "name" or "bad", as tools/bees_conf.py tells addresses apart. */
internal fun addrKind(a: String): String = when {
    IPV4.matches(a) -> "ipv4"
    a.contains(':') && a.all { it.isLetterOrDigit() && it.code < 128 && (it.isDigit() || it.lowercaseChar() in 'a'..'f') || it == ':' || it == '.' } -> "ipv6"
    a.length <= 253 && NAME.matches(a) && !a.all { it.isDigit() || it == '.' } -> "name"
    else -> "bad"
}

/** An address a node dials from a gossiped entry: a dotted quad, a colon, a port of 1 to 65535. A name is not resolved. */
internal fun dialable(addr: String): Boolean {
    val at = addr.indexOf(':')
    if (at < 7) return false
    val port = addr.substring(at + 1)
    if (port.isEmpty() || port.length > 5 || !port.all { it in '0'..'9' } || port.toInt() !in 1..65535) return false
    val parts = addr.substring(0, at).split('.')
    return parts.size == 4 && parts.all { it.length in 1..3 && it.all { c -> c in '0'..'9' } }
}

/**
 * Why the Silica node refuses to start from its arguments alone (bees_tempus_node@boot_why), the same checks in the
 * same order with the same texts; null when it may start. The numbers are the Silica node's: typ 1 edge, 2 bridge,
 * 3 sentinel; back 1 follow, 2 hold, 3 stop; fail 1 continue, 2 pause. stores holds capacity, shuffle length and
 * tick_ms of the edge, bridge and sentinel store. The node's token is judged as far as its structure, its type and
 * its key. (The Silica node's refusal of an externally driven node on an address that is not loopback has no place
 * here: this extension has no externally driven node.)
 */
fun bootWhy(typ: Int, idBytes: Int, pub: ByteArray, seedBytes: Int, token: ByteArray, kidBytes: Int, producerKeyBytes: Int, inflightMax: Long,
            shuffleTimeoutMs: Long, joinInitialMs: Long, joinMaxMs: Long, skew: Long, whitelistHexChars: Int, stores: List<StoreConfig>,
            back: Int, backLimit: Long, fail: Int, clockReadMs: Long): String? {
    if (typ !in 1..3) return "the node's type is not edge, bridge or sentinel"
    if (idBytes != 64 || pub.size != 32 || seedBytes != 32) return "the identity is not a 64-byte peer id, a 32-byte key and a 32-byte seed"
    val t = try { readToken(token) } catch (e: Refused) { return "the node's token does not read: ${e.why}" }
    if (PEER_TYPES.indexOf(t.typ) + 1 != typ) return "the node's token is for another peer type than the node's"
    if (!t.sub.contentEquals(pub)) return "the node's token names another key"
    if (kidBytes !in 1..64 || producerKeyBytes != 32) return "the producer key is not a kid of 1 to 64 bytes and a 32-byte key"
    if (inflightMax !in 1..64) return "inflight_max is not 1 to 64"
    if (shuffleTimeoutMs < 1) return "shuffle_timeout_ms is below 1"
    if (joinInitialMs < 1 || joinMaxMs < joinInitialMs) return "the join's initial delay is below 1 or above its maximum"
    if (skew < 0) return "clock_skew is below 0"
    if (whitelistHexChars % 128 != 0) return "the tempus whitelist is not 128 hex characters per certificate"
    for ((i, s) in stores.withIndex()) {
        val name = PEER_TYPES[listOf(0, 1, 2)[i]]
        if (s.capacity !in 1..256) return "$name: capacity is not 1 to 256"
        if (s.shuffleLength !in 1..64 || s.shuffleLength > s.capacity) return "$name: shuffle_length is not 1 to 64 and at most the capacity"
        if (s.tickMs < 1) return "$name: tick_ms is below 1"
    }
    if (back !in 1..3) return "clock_back is not follow (1), hold (2) or stop (3)"
    if (back == 3 && backLimit < 0) return "clock_back_limit_s is below 0"
    if (fail !in 1..2) return "clock_fail is not continue (1) or pause (2)"
    if (clockReadMs < 1) return "clock_read_ms is below 1"
    return null
}

/** Why a node with this configuration and identity may not start, or null: the configuration's refusal, then the node's. */
fun startRefusal(config: TempusConfig, identity: Identity): String? {
    config.refusal()?.let { return it }
    return bootWhy(listOf("edge", "bridge", "sentinel").indexOf(config.role) + 1, identity.peerId.size, identity.pub, 32, identity.token,
        config.producerKid.size, config.producerKey.size, config.inflightMax.toLong(), config.shuffleTimeoutMs, config.joinRetryInitialMs,
        config.joinRetryMaxMs, config.skewSeconds, config.whitelist.size * 128, listOf(config.edge, config.bridge, config.sentinel),
        listOf("follow", "hold", "stop").indexOf(config.clockBack) + 1, config.clockBackLimitS ?: 0, listOf("continue", "pause").indexOf(config.clockFail) + 1,
        config.clockReadMs)
}
