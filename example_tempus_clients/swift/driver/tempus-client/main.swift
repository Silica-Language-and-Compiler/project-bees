// The driver application of the Swift TEMPUS extension: a command line over its two libraries (lib/TempusClient and
// lib/TempusNode). A usable example, to be used with care (README.md). It reads its values from the command line and
// from the files the command line names, hands them to the libraries, and prints what they report, one line each.
//
//   tempus-client gossip OPTIONS
//       Be a member of a TEMPUS network: a node of lib/TempusNode, whose role is the type its token carries. It
//       listens, joins through the sentinels, shuffles the three stores on their timers and answers the peers that
//       dial. Prints the node's own lines (with its audit lines) and, for every peer it comes to know, `learned STORE
//       ID16 HOST:PORT`. Runs until it is interrupted or ended, or for --run-ms; then prints, per store, `known STORE:
//       ID16 ...` (every peer it ever learned of, sorted). What a node requires and these options do not carry (the
//       bound on accepted connections and the clock choices) is stated in GossipChoices below.
//       OPTIONS, all required unless marked:
//         --cert FILE --key FILE         this peer's certificate (PEM, self-signed over its Ed25519 key) and its private
//                                        key (PEM, PKCS#8, not encrypted)
//         --token FILE                   its token from the producer, as hex digits in a file
//         --addr HOST:PORT               the address it advertises and listens on (HOST an IPv4 literal)
//         --producer-pub HEX --kid KID   the producer's current public key and its identifier
//         --skew SECONDS                 the clock difference this peer allows
//         --timeout-ms MS                the time bound of a whole connection
//         --store-edge CAP:LEN:TICK_MS --store-bridge CAP:LEN:TICK_MS --store-sentinel CAP:LEN:TICK_MS
//                                        capacity, shuffle length and tick of each store
//         --join-retry-ms FIRST:MAX      the join's first and greatest retry delay
//         --sentinel HOST:PORT           may be repeated (1 to 16); none for a first sentinel
//         --whitelist-cert PEM_FILE      optional, may be repeated: a bridge or sentinel this peer accepts
//         --now SECONDS                  optional: one fixed reading in place of the machine's clock (the node
//                                        accepts that on a loopback address only)
//         --run-ms MS                    optional: stop after that long
//
// The commands below were written for the trial trials/c5_tempus_swift. They take the key as a seed and can make TEST
// ONLY tokens and entries (testing/TempusClientTesting):
//
//   tempus-client read-hex HEX SHUFFLE_LENGTH
//   tempus-client test-token --seed HEX --kid KID TYP NBF EXP
//   tempus-client dial HOST:PORT IDENTITY CHECKS [--nonce HEX] REQUEST
//       REQUEST: sample STORE N | shuffle STORE | call MODULE FUNCTION [INTEGER...] | cast MODULE FUNCTION [INTEGER...]
//                | raw HEX
//       (`shuffle STORE` sends this client's own entry at age 0; `call` and `cast` use the request id "1".)
//   tempus-client listen HOST:PORT IDENTITY CHECKS [--test-entry STORE=AGE:FIRST:TYP:NBF:EXP:HOST:PORT ...]
//       Answers a sample or a shuffle for STORE with the entries given for it, and anything else with a close.
//       Prints "listening HOST:PORT", then one line per connection, in accept order. Ends when its standard input ends.
//   IDENTITY: --seed HEX --addr HOST:PORT (--token HEX | --test-token TYP:NBF:EXP) [--cert PEM_FILE]
//   CHECKS:   --producer-pub HEX --kid KID (--now SECONDS | --system-clock) --skew SECONDS --timeout SECONDS
//             --shuffle-length N [--whitelist-cert PEM_FILE ...] [--no-entry-check]
// --test-token and --test-entry sign with the TEST producer seed 00..1f under --kid: TEST ONLY.
// Every dial prints its outcome as one line and exits 0; a fault of the command line exits 2.
import Foundation
import TempusClient
import TempusClientTesting
import TempusNode

func fail(_ text: String) -> Never {
    FileHandle.standardError.write(Data(("tempus-client: " + text + "\n").utf8))
    exit(2)
}

func say(_ line: String) {
    print(line)
    fflush(stdout)
}

struct Options {
    var values: [String: [String]] = [:]
    var rest: [String] = []

    init(_ argv: [String], flags: Set<String>) {
        var i = 0
        while i < argv.count {
            let a = argv[i]
            if a.hasPrefix("--") {
                if flags.contains(a) {
                    values[a, default: []].append("")
                } else {
                    guard i + 1 < argv.count else { fail("\(a) needs a value") }
                    values[a, default: []].append(argv[i + 1])
                    i += 1
                }
            } else {
                rest.append(a)
            }
            i += 1
        }
    }

    func one(_ name: String) -> String? { values[name]?.last }

    func need(_ name: String) -> String {
        guard let v = one(name) else { fail("\(name) is required") }
        return v
    }

    func needHex(_ name: String, _ count: Int? = nil) -> Bytes {
        guard let b = unhex(need(name)), count == nil || b.count == count else { fail("\(name) is not the hex it should be") }
        return b
    }

    func needInt(_ name: String) -> Int64 {
        guard let n = Int64(need(name)) else { fail("\(name) is not a whole number") }
        return n
    }
}

func pemDER(_ path: String) -> Bytes {
    guard let text = try? String(contentsOfFile: path, encoding: .utf8), let der = certificateDER(pem: text) else {
        fail("no certificate could be read from \(path)")
    }
    return der
}

func testToken(_ spec: String, kid: String, sub: Bytes) -> Bytes {
    let p = spec.split(separator: ":").map(String.init)
    guard p.count == 3, let nbf = Int64(p[1]), let exp = Int64(p[2]),
          let producer = try? SigningKey(seed: fixtureSeed(0)),
          let token = try? makeTestToken(producer: producer, kid: kid, sub: sub, typ: p[0], nbf: nbf, exp: exp) else {
        fail("a test token is TYP:NBF:EXP")
    }
    return token
}

func identity(_ o: Options) -> Identity {
    let seed = o.needHex("--seed", 32)
    guard let key = try? SigningKey(seed: seed) else { fail("--seed is not an Ed25519 seed") }
    guard (o.one("--token") == nil) != (o.one("--test-token") == nil) else { fail("give exactly one of --token and --test-token") }
    let token = o.one("--token") != nil ? o.needHex("--token") : testToken(o.need("--test-token"), kid: o.need("--kid"), sub: key.pub)
    do {
        return try Identity(seed: seed, token: token, addr: o.need("--addr"), certDER: o.one("--cert").map(pemDER))
    } catch {
        fail("\(error)")
    }
}

func verifier(_ o: Options) -> Verifier {
    guard (o.one("--now") == nil) != (o.one("--system-clock") == nil) else { fail("give exactly one of --now and --system-clock") }
    let clock: () -> Int64
    if o.one("--now") != nil {
        let now = o.needInt("--now")
        clock = { now }
    } else {
        clock = { Int64(Date().timeIntervalSince1970) }
    }
    let listed = o.values["--whitelist-cert"].map { Set($0.map { sha512(pemDER($0)) }) }
    return Verifier(producerPub: o.needHex("--producer-pub", 32), kid: Array(o.need("--kid").utf8), clock: clock,
                    skew: o.needInt("--skew"), whitelist: listed)
}

func timeout(_ o: Options) -> Double {
    guard let t = Double(o.need("--timeout")), t > 0 else { fail("--timeout is a number of seconds") }
    return t
}

func request(_ r: [String], me: Identity) -> Bytes {
    do {
        if r.count == 3, r[0] == "sample", let n = Int64(r[2]) { return try sample(store: r[1], n: n) }
        if r.count == 2, r[0] == "shuffle" { return try shuffle(store: r[1], entries: [try me.entry(age: 0)]) }
        if r.count >= 3, r[0] == "call" || r[0] == "cast" {
            let args = r[3...].map { Int64($0) }
            guard !args.contains(nil) else { fail("the arguments of a call or cast are whole numbers") }
            return try callFrame(kind: r[0], reqId: Array("1".utf8), module: r[1], function: r[2], args: args.map { $0! })
        }
        if r.count == 2, r[0] == "raw", let body = unhex(r[1]) { return body }
    } catch {
        fail("\(error)")
    }
    fail("the request is: sample STORE N | shuffle STORE | call M F [INTEGER...] | cast M F [INTEGER...] | raw HEX")
}

func testEntries(_ o: Options) -> [String: [Entry]] {
    var held: [String: [Entry]] = [:]
    for spec in o.values["--test-entry"] ?? [] {
        let halves = spec.split(separator: "=", maxSplits: 1).map(String.init)
        let p = halves.count == 2 ? halves[1].split(separator: ":", maxSplits: 5).map(String.init) : []
        guard p.count == 6, let age = Int64(p[0]), let first = UInt8(p[1]), let nbf = Int64(p[3]), let exp = Int64(p[4]),
              let who = try? fixtureIdentity(first, typ: p[2], nbf: nbf, exp: exp, addr: p[5], kid: o.need("--kid")),
              let entry = try? who.entry(age: age) else {
            fail("a test entry is STORE=AGE:FIRST:TYP:NBF:EXP:HOST:PORT")
        }
        held[halves[0], default: []].append(entry)
    }
    return held
}

// ---------------------------------------------------------------- gossip
func readText(_ path: String) -> String {
    guard let text = try? String(contentsOfFile: path, encoding: .utf8) else { fail("\(path) cannot be read") }
    return text
}

func storeConfig(_ o: Options, _ name: String) -> StoreConfig {
    let p = o.need(name).split(separator: ":").map { Int($0) }
    guard p.count == 3, let capacity = p[0], let length = p[1], let tick = p[2] else { fail("\(name) is CAP:LEN:TICK_MS") }
    return StoreConfig(capacity: capacity, shuffleLength: length, tickMs: tick)
}

/// The values a node requires and the `gossip` command line does not carry. The node library has no default for any
/// of them; these are this driver's choices for the gossip example, stated here and nowhere else. An application of
/// its own states its own (README.md, "The configuration").
enum GossipChoices {
    static let inflightMax = 16                      // accepted connections at once
    static let clockBack = ClockBack.follow          // a clock that steps back is followed
    static let clockBackLimitS: Int? = nil           // only `stop` takes a limit
    static let clockFail = ClockFail.continue        // a reading that fails after a good one: go on with the last reading
    static let clockReadMs = 1000                    // how often the clock is read
}

/// The clock of `--now SECONDS`: one fixed reading. The node accepts a clock of its caller's on a loopback listen
/// address only.
struct FixedClock: NodeClockSource {
    let now: Int64
    func seconds() -> Int64? { now }
}

/// What the instance has learned, per store, and the one lock under which every line is printed.
final class Learned: @unchecked Sendable {
    private let lock = NSLock()
    private var known: [String: Set<String>] = [:]

    func line(_ text: String) {
        lock.lock()
        say(text)
        lock.unlock()
    }

    /// Prints `learned STORE ID16 HOST:PORT` for each entry of a view that this instance sees for the first time.
    func view(_ store: String, _ entries: [ViewEntry<Descriptor>]) {
        lock.lock()
        for e in entries {
            let id16 = hex(Array(e.id.prefix(8)))
            if known[store, default: []].insert(id16).inserted {
                say("learned \(store) \(id16) \(String(decoding: e.d.addr, as: UTF8.self))")
            }
        }
        lock.unlock()
    }

    func all(_ store: String) -> [String] {
        lock.lock()
        defer { lock.unlock() }
        return (known[store] ?? []).sorted()
    }
}

var interrupted: sig_atomic_t = 0

func gossip(_ o: Options) {
    guard o.rest.isEmpty else { fail("gossip OPTIONS") }
    guard let seed = ed25519Seed(pkcs8PEM: readText(o.need("--key"))) else { fail("--key is not an unencrypted PKCS#8 Ed25519 key in PEM") }
    guard let token = unhex(readText(o.need("--token")).trimmingCharacters(in: .whitespacesAndNewlines)) else { fail("--token does not hold hex digits") }
    // the node's role is the type its token carries
    guard let typ = try? readToken(token).fields.typ, let role = PeerType(rawValue: typ) else { fail("--token does not hold a token") }
    let retry = o.need("--join-retry-ms").split(separator: ":").map { Int($0) }
    guard retry.count == 2, let first = retry[0], let most = retry[1] else { fail("--join-retry-ms is FIRST:MAX") }
    func hostPort(_ text: String, _ name: String) -> (String, Int) {
        guard let colon = text.lastIndex(of: ":"), let port = Int(text[text.index(after: colon)...]) else { fail("\(name) is HOST:PORT") }
        return (String(text[..<colon]), port)
    }
    let (host, port) = hostPort(o.need("--addr"), "--addr")
    // a member of a network always applies the whitelist rule: with no --whitelist-cert it accepts no bridge and no
    // sentinel on a connection
    let config = TempusConfig(
        role: role, listenAddress: host, port: port,
        sentinels: (o.values["--sentinel"] ?? []).map { let (h, p) = hostPort($0, "--sentinel"); return Sentinel(host: h, port: p) },
        edge: storeConfig(o, "--store-edge"), bridge: storeConfig(o, "--store-bridge"), sentinel: storeConfig(o, "--store-sentinel"),
        producerKid: Array(o.need("--kid").utf8), producerKey: o.needHex("--producer-pub", 32),
        whitelist: (o.values["--whitelist-cert"] ?? []).map(pemDER),
        shuffleTimeoutMs: Int(o.needInt("--timeout-ms")), inflightMax: GossipChoices.inflightMax,
        clockSkewMs: Int(o.needInt("--skew")) * 1000,
        clockBack: GossipChoices.clockBack, clockBackLimitS: GossipChoices.clockBackLimitS,
        clockFail: GossipChoices.clockFail, clockReadMs: GossipChoices.clockReadMs,
        joinRetryInitialMs: first, joinRetryMaxMs: most)
    let identity = NodeIdentity(seed: seed, certificateDER: pemDER(o.need("--cert")), token: token, address: o.need("--addr"))
    let learned = Learned()
    let lines: @Sendable (String) -> Void = { learned.line($0) }
    let events: @Sendable (NodeEvent) -> Void = { event in
        switch event {
        case .view(let store, let entries): learned.view(store.rawValue, entries)
        case .ownTokenNotValid(let reason): learned.line("told: the node's own token is not valid any more: \(reason)")
        case .keyRotated(let kid, _): learned.line("told: a peer answered key_rotated, its current kid is \(String(decoding: kid, as: UTF8.self))")
        case .clockNotRead(let text), .stopped(let text): learned.line("told: \(text)")
        case .listenFailed(let text): learned.line("told: the node does not listen: \(text)")
        case .listening, .joined, .peerRefused: break
        }
    }
    let node: TempusNode
    do {
        if o.one("--now") != nil {
            let sources = NodeSources(clock: FixedClock(now: o.needInt("--now")), timers: SystemTimers(), random: SecureRandom())
            node = try TempusNode(config: config, identity: identity, sources: sources, lines: lines, events: events)
        } else {
            node = try TempusNode(config: config, identity: identity, lines: lines, events: events)
        }
    } catch {
        exit(1)          // the node has written the line that says why
    }
    signal(SIGINT) { _ in interrupted = 1 }
    signal(SIGTERM) { _ in interrupted = 1 }
    node.start()
    let until = o.one("--run-ms").map { _ in Date().addingTimeInterval(Double(o.needInt("--run-ms")) / 1000.0) }
    while interrupted == 0 && (until.map { Date() < $0 } ?? true) { usleep(50_000) }
    node.stop()
    for t in peerTypes {
        let all = learned.all(t)
        learned.line("known \(t): " + (all.isEmpty ? "(none)" : all.joined(separator: " ")))
    }
}

let argv = Array(CommandLine.arguments.dropFirst())
let flags: Set<String> = ["--system-clock", "--no-entry-check"]
switch argv.first {
case "gossip":
    gossip(Options(Array(argv.dropFirst()), flags: flags))
case "read-hex" where argv.count == 3:
    guard let body = unhex(argv[1]), let length = Int(argv[2]) else { fail("read-hex HEX SHUFFLE_LENGTH") }
    do {
        var out = Outcome("reply", "done")
        out.frame = try readBody(body, shuffleLength: length)
        say(out.line.dropFirst("reply ".count).description)
    } catch {
        say("refused: \(error)")
    }
case "test-token":
    let o = Options(Array(argv.dropFirst()), flags: flags)
    guard o.rest.count == 3, let key = try? SigningKey(seed: o.needHex("--seed", 32)) else { fail("test-token --seed HEX --kid KID TYP NBF EXP") }
    say(hex(testToken(o.rest.joined(separator: ":"), kid: o.need("--kid"), sub: key.pub)))
case "dial":
    let o = Options(Array(argv.dropFirst()), flags: flags)
    guard let peer = o.rest.first else { fail("dial HOST:PORT ...") }
    let me = identity(o)
    let out = dial(peer, identity: me, verifier: verifier(o), request: request(Array(o.rest.dropFirst()), me: me),
                   timeout: timeout(o), nonce: o.one("--nonce").map { _ in o.needHex("--nonce", 32) },
                   shuffleLength: Int(o.needInt("--shuffle-length")), verifyEntries: o.one("--no-entry-check") == nil)
    say(out.line)
case "listen":
    let o = Options(Array(argv.dropFirst()), flags: flags)
    guard o.rest.count == 1, let at = o.rest.first, let colon = at.lastIndex(of: ":"),
          let port = Int(at[at.index(after: colon)...]) else { fail("listen HOST:PORT ...") }
    let held = testEntries(o)
    do {
        let listener = try Listener(identity: identity(o), verifier: verifier(o), host: String(at[..<colon]), port: port,
                                    timeout: timeout(o), shuffleLength: Int(o.needInt("--shuffle-length")),
                                    verifyEntries: o.one("--no-entry-check") == nil) { rq in
            standardAnswer(rq) { held[$0] ?? [] }
        }
        listener.onOutcome = { _, out in say(out.line) }
        listener.start()
        say("listening " + listener.address)
        while readLine() != nil {}
        listener.stop()
    } catch {
        fail("\(error)")
    }
default:
    fail("usage: tempus-client gossip | read-hex | test-token | dial | listen (see the README)")
}
