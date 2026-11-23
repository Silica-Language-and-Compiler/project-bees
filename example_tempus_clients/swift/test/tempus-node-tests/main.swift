// The unit tests of the node part of the Swift TEMPUS extension. A plain program (no XCTest is needed):
//   tempus-node-tests BEES_ROOT     the clock, configuration and admission tests; they read recorded outputs of BEES trials
//   tempus-node-tests model         answers the cases test/model_check.py writes to its standard input, one line each
// Keys and tokens are TEST ONLY, from fixed seeds (TempusClientTesting).
import Foundation
import TempusClient
import TempusNode
import TempusClientTesting
// TempusClient has a store of its own with the same name (lib/TempusClient/Gossip.swift); the node's is meant here
import struct TempusNode.Store

nonisolated(unsafe) var passed = 0
nonisolated(unsafe) var failed = 0

func check(_ ok: Bool, _ what: String) {
    if ok { passed += 1 } else {
        failed += 1
        print("FAILED: " + what)
    }
}

func same(_ got: String, _ want: String, _ what: String) { check(got == want, "\(what)\n   got:  \(got)\n   want: \(want)") }

// ---------------------------------------------------------------- the model cases (test/model_check.py)
typealias E = ViewEntry<String>

func entries(_ any: Any?) -> [E] {
    ((any as? [[Any]]) ?? []).map { E(id: Array(($0[0] as! String).utf8), d: $0[1] as! String, age: $0[2] as! Int) }
}

func show(_ v: [E]) -> String {
    v.isEmpty ? "(empty)" : v.map { "\(String(decoding: $0.id, as: UTF8.self)):\($0.age)/\($0.d)" }.joined(separator: " ")
}

func model() {
    var store: Store<String>?
    while let line = readLine() {
        guard let c = try? JSONSerialization.jsonObject(with: Data(line.utf8)) as? [String: Any], let op = c["op"] as? String else {
            print("bad case")
            continue
        }
        let view = entries(c["view"]), draws = c["draws"] as? [Int], n = c["n"] as? Int ?? 0
        let me = Array((c["self"] as? String ?? "").utf8), cap = c["cap"] as? Int ?? 0
        switch op {
        case "age_all": print(show(View.ageAll(view)))
        case "select":
            if let s = View.select(view, count: n, draws: draws ?? []) {
                print("partner \(show([s.partner])) | sent \(show(s.sent)) | rest \(show(s.rest))")
            } else {
                print("none")
            }
        case "reply_select":
            let r = View.replySelect(view, count: n, asker: Array((c["asker"] as! String).utf8), draws: draws ?? [])
            print("sent \(show(r.sent)) | rest \(show(r.rest))")
        case "merge": print(show(View.merge(view, entries(c["received"]), selfId: me, cap: cap)))
        case "prefer_sent": print(show(View.preferSent(entries(c["received"]), entries(c["sent"]))))
        case "backfill": print(show(View.backfill(view, entries(c["sent"]), cap: cap)))
        case "insert": print(show(View.insert(view, entries(c["received"])[0], selfId: me, cap: cap)))
        case "sample": print(show(View.sample(view, n, draws: draws ?? [])))
        case "valid": print(View.valid(view, selfId: me, cap: cap) ? "yes" : "no")
        case "store.new":
            store = Store(selfId: me, selfD: "@" + (c["self"] as! String), own: c["own"] as! Bool, cap: cap, count: n)
            print("new")
        case "store.tick":
            switch store!.tick(draws: draws) {
            case .skipped: print("skipped | \(show(store!.view))")
            case .aged: print("aged | \(show(store!.view))")
            case .empty: print("empty | \(show(store!.view))")
            case .shuffle(let p, let out): print("shuffle \(show([p])) | out \(show(out)) | \(show(store!.view))")
            }
        case "store.failed":
            store!.failed()
            print(show(store!.view))
        case "store.reply":
            store!.reply(entries(c["received"]))
            print(show(store!.view))
        case "store.request":
            let out = store!.request(asker: Array((c["asker"] as! String).utf8), received: entries(c["received"]), draws: draws)
            print("\(out.map(show) ?? "refused") | \(show(store!.view))")
        case "store.sample":
            print("\(store!.sample(n, draws: draws).map(show) ?? "refused") | \(show(store!.view))")
        case "store.insert":
            store!.insert(entries(c["received"])[0])
            print(show(store!.view))
        case "store.drop":
            store!.drop(Array((c["id"] as! String).utf8))
            print(show(store!.view))
        default: print("unknown op")
        }
    }
}

// ---------------------------------------------------------------- the clock, against trials/t0_tempus_clock
func choices(_ text: Substring) -> ClockChoices? {
    // "follow" | "hold" | "stop limit N", then optionally ", clock_fail X"
    let parts = text.components(separatedBy: ", clock_fail ")
    let words = parts[0].split(separator: " ")
    guard let back = ClockBack(rawValue: String(words[0])) else { return nil }
    let fail = parts.count > 1 ? ClockFail(rawValue: parts[1]) : .pause
    guard let fail else { return nil }
    return ClockChoices(back: back, limit: words.count == 3 ? Int64(words[2])! : 0, fail: fail)
}

func stateText(_ ck: ClockState) -> String {
    switch ck {
    case .none: return "no reading yet"
    case .noneTold: return "no reading yet, application told"
    case .good: return "good"
    case .paused: return "paused, waits for the clock"
    case .continuing: return "goes on with its last reading"
    case .holding: return "holds its time"
    case .stopped: return "stopped"
    }
}

func sayText(_ s: ClockSay) -> String {
    switch s {
    case .nothing: return "nothing"
    case .first: return "first reading: one line, listen"
    case .noTimeAtStart: return "no time at start: one line, application told"
    case .noTimePause: return "no time, pause: one line, application told"
    case .noTimeContinue: return "no time, continue: one line, application told"
    case .followed: return "step back followed: one line"
    case .holdBegins: return "step back, hold begins: one line"
    case .holdEnds: return "the held time is reached: one line"
    case .stop: return "step back above the limit: one line, application told, stop"
    }
}

func clockTests(_ root: String) {
    let path = root + "/trials/t0_tempus_clock/clock.macos_applesilicon.scout"
    guard let text = try? String(contentsOfFile: path, encoding: .utf8) else {
        check(false, "cannot read " + path)
        return
    }
    var z: ClockChoices?, ck = ClockState.none, now: Int64 = 0, lines = 0
    for line in text.split(separator: "\n") {
        if line.hasPrefix("part ") || line.hasPrefix("exit=") { continue }
        if line.hasPrefix("clock_back ") {
            z = choices(line.dropFirst(11))
            ck = .none
            now = 0
            check(z != nil, "the choices of: \(line)")
        } else if line.hasPrefix("  reading "), let z {
            let reading = line.dropFirst(10).components(separatedBy: " -> ")[0]
            let t = clockTurn(ck, last: now, reading: Int64(reading), z)
            now = t.now
            ck = t.ck
            let accepts = ck == .none || ck == .noneTold ? "does not listen yet"
                : ck == .paused ? "closes accepted connections (role 4, clock_refused)"
                : ck == .stopped ? "closes accepted connections (role 5, clock_stopped)" : "accepts"
            same("  reading \(reading) -> time \(now); \(stateText(ck)); \(ck.ticks ? "ticks" : "no ticks"); \(accepts); does: "
                 + (t.again ? "read again: one line; then " : "") + sayText(t.say), String(line), "clock_turn")
            check((ck.closesWith == nil) == (accepts == "accepts" || accepts == "does not listen yet"), "closesWith of \(ck)")
            lines += 1
        } else if let colon = line.range(of: ": time "), let z1 = choices(line[..<colon.lowerBound]) {
            let nums = line[colon.upperBound...].components(separatedBy: " -> ")[0].components(separatedBy: ", reading ")
            let b = clockBack(last: Int64(nums[0])!, reading: Int64(nums[1])!, z1)
            let what = ["not earlier", "earlier, followed", "earlier, held", "earlier, the node stops"][b.act]
            same("\(line[..<colon.lowerBound]): time \(nums[0]), reading \(nums[1]) -> time \(b.now), \(what)", String(line), "clock_back")
            lines += 1
        } else {
            check(false, "a line of the clock trial this test does not read: \(line)")
        }
    }
    check(lines == 71, "the clock trial's recorded output has 71 case lines; read \(lines)")
}

// ---------------------------------------------------------------- configuration and boot refusals
func goodConfig() -> TempusConfig {
    let s = StoreConfig(capacity: 4, shuffleLength: 2, tickMs: 1000)
    return TempusConfig(role: .edge, listenAddress: "127.0.0.1", port: 24300, sentinels: [Sentinel(host: "127.0.0.1", port: 24310)],
                        edge: StoreConfig(capacity: 4, shuffleLength: 3, tickMs: 1000), bridge: s, sentinel: s,
                        producerKid: Array("k1".utf8), producerKey: Bytes(repeating: 0, count: 32), whitelist: [],
                        shuffleTimeoutMs: 2000, inflightMax: 4, clockSkewMs: 10000, clockBack: .follow, clockBackLimitS: nil,
                        clockFail: .pause, clockReadMs: 1000, joinRetryInitialMs: 200, joinRetryMaxMs: 800)
}

func refused(_ what: String, _ part: String, _ change: (inout TempusConfig) -> Void) {
    var c = goodConfig()
    change(&c)
    let why = c.refusal() ?? "(accepted)"
    check(why.contains(part), "\(what): wanted a refusal with \"\(part)\", got: \(why)")
}

func configTests() {
    check(goodConfig().refusal() == nil, "the good configuration: \(goodConfig().refusal() ?? "")")
    // the cases of tools/test_bees_tempus_conf.py that concern values (the file's syntax and the mode are not this extension's)
    refused("role bridge", "bridge needs mode tempus-trust") { $0.role = .bridge }
    refused("capacity 257", "tempus.edge.capacity: 257 is above 256 (bounds 1 to 256; never clamped)") { $0.edge.capacity = 257 }
    refused("shuffle length 5 of capacity 4", "tempus.edge.shuffle_length: 5 is above the capacity 4") { $0.edge.shuffleLength = 5 }
    refused("a key of 31 bytes", "32 bytes") { $0.producerKey = Bytes(repeating: 0, count: 31) }
    refused("join maximum below the initial", "tempus.join_retry_max_ms: below join_retry_initial_ms") { $0.joinRetryMaxMs = 150 }
    refused("no sentinels, an edge", "tempus.sentinels: required unless the node is the first sentinel") { $0.sentinels = [] }
    var first = goodConfig()
    first.role = .sentinel
    first.sentinels = []
    check(first.refusal() == nil, "a first sentinel needs no sentinels: \(first.refusal() ?? "")")
    refused("stop with no limit", "tempus.clock_back_limit_s: required when clock_back is stop") { $0.clockBack = .stop }
    for back in [ClockBack.follow, .hold] {
        refused("a limit under \(back)", "remove clock_back_limit_s") { $0.clockBack = back; $0.clockBackLimitS = 30 }
        for fail in ClockFail.allCases {
            var c = goodConfig()
            c.clockBack = back
            c.clockFail = fail
            check(c.refusal() == nil, "\(back) with \(fail)")
        }
    }
    for limit in [0, 86400] {
        var c = goodConfig()
        c.clockBack = .stop
        c.clockBackLimitS = limit
        check(c.refusal() == nil, "stop with the limit \(limit)")
    }
    refused("a limit of -1", "tempus.clock_back_limit_s: -1 is below 0") { $0.clockBack = .stop; $0.clockBackLimitS = -1 }
    refused("a limit of 86401", "tempus.clock_back_limit_s: 86401 is above 86400") { $0.clockBack = .stop; $0.clockBackLimitS = 86401 }
    for ms in [100, 60000] {
        var c = goodConfig()
        c.clockReadMs = ms
        check(c.refusal() == nil, "clock_read_ms \(ms)")
    }
    refused("clock_read_ms 99", "tempus.clock_read_ms: 99 is below 100") { $0.clockReadMs = 99 }
    refused("clock_read_ms 60001", "tempus.clock_read_ms: 60001 is above 60000") { $0.clockReadMs = 60001 }
    // the other bounds of design section 11
    refused("port 0", "tempus.port: 0 is below 1") { $0.port = 0 }
    refused("shuffle_timeout_ms 99", "tempus.shuffle_timeout_ms: 99 is below 100") { $0.shuffleTimeoutMs = 99 }
    refused("shuffle_timeout_ms 60001", "tempus.shuffle_timeout_ms: 60001 is above 60000") { $0.shuffleTimeoutMs = 60001 }
    refused("inflight_max 0", "tempus.inflight_max: 0 is below 1") { $0.inflightMax = 0 }
    refused("inflight_max 65", "tempus.inflight_max: 65 is above 64") { $0.inflightMax = 65 }
    refused("clock_skew_ms 300001", "tempus.clock_skew_ms: 300001 is above 300000") { $0.clockSkewMs = 300001 }
    refused("clock_skew_ms -1", "tempus.clock_skew_ms: -1 is below 0") { $0.clockSkewMs = -1 }
    refused("join_retry_initial_ms 99", "tempus.join_retry_initial_ms: 99 is below 100") { $0.joinRetryInitialMs = 99 }
    refused("tick_ms 99", "tempus.bridge.tick_ms: 99 is below 100") { $0.bridge.tickMs = 99 }
    refused("tick_ms 3600001", "tempus.sentinel.tick_ms: 3600001 is above 3600000") { $0.sentinel.tickMs = 3600001 }
    refused("shuffle_length 65", "tempus.edge.shuffle_length: 65 is above 64") { $0.edge.capacity = 256; $0.edge.shuffleLength = 65 }
    refused("capacity 0", "tempus.sentinel.capacity: 0 is below 1") { $0.sentinel.capacity = 0 }
    refused("an empty kid", "tempus.producer_key: the kid is not 1 to 64 bytes") { $0.producerKid = [] }
    refused("17 sentinels", "1 to 16") { $0.sentinels = Array(repeating: Sentinel(host: "127.0.0.1", port: 1), count: 17) }
    refused("a sentinel by name", "is not an IPv4 literal") { $0.sentinels = [Sentinel(host: "s.example", port: 1)] }
    refused("an IPv6 listen address", "tempus.listen_address") { $0.listenAddress = "::1" }

    // the boot refusals a node writes (trials/c4_tempus_boot shows the Silica node's): the line and the error
    func boot(_ what: String, _ want: String, sources: NodeSources? = nil, token: (typ: String, nbf: Int64, exp: Int64) = ("tempus_edge", 1000, 2000),
              sub: UInt8 = 32, _ change: (inout TempusConfig) -> Void = { _ in }) {
        var c = goodConfig()
        change(&c)
        let lines = Lines()
        do {
            let who = try fixtureIdentity(sub, typ: token.typ, nbf: token.nbf, exp: token.exp, addr: "127.0.0.1:24300")
            let me = try fixtureIdentity(32, typ: "tempus_edge", nbf: 1000, exp: 2000, addr: "127.0.0.1:24300")
            let idn = NodeIdentity(seed: fixtureSeed(32), certificateDER: me.certDER, token: who.token, address: "127.0.0.1:24300")
            if let sources {
                _ = try TempusNode(config: c, identity: idn, sources: sources, lines: { lines.add($0) }, events: { _ in })
            } else {
                _ = try TempusNode(config: c, identity: idn, lines: { lines.add($0) }, events: { _ in })
            }
            check(want.isEmpty, "\(what): the node was made, wanted the refusal: \(want)")
        } catch let e as ConfigRefused {
            same(e.reason, want, what)
            same(lines.all.joined(separator: "|"), "tempus: boot refused: " + want, what + ", the line")
        } catch {
            check(false, "\(what): \(error)")
        }
    }
    boot("a good start", "")
    boot("capacity", "tempus.edge.capacity: 0 is below 1 (bounds 1 to 256; never clamped)") { $0.edge.capacity = 0 }
    boot("producer", "tempus.producer_key: the public key is not 32 bytes") { $0.producerKey = [1, 2, 3] }
    boot("token of another type", "the node's token is for another peer type than the node's", token: ("tempus_sentinel", 1000, 2000))
    boot("token of another key", "the node's token names another key", sub: 64)
    let manual = NodeSources(clock: ManualClock(1500), timers: ManualTimers(), random: ListRandom([0]))
    boot("a test node on loopback", "", sources: manual)
    boot("a test node off loopback", "a node with a clock, timers or random numbers of its caller's on a listen address that is not loopback",
         sources: manual) { $0.listenAddress = "0.0.0.0" }
}

final class Lines: @unchecked Sendable {
    private let lock = NSLock()
    private var lines: [String] = []
    func add(_ s: String) {
        lock.lock()
        lines.append(s)
        lock.unlock()
    }
    var all: [String] {
        lock.lock()
        defer { lock.unlock() }
        return lines
    }
}

// ---------------------------------------------------------------- admission, against trials/t4_tempus_admission
func admissionTests(_ root: String) {
    let path = root + "/trials/t4_tempus_admission/dangerous_admit.macos_applesilicon.scout"
    var want: [String: String] = [:]
    for line in ((try? String(contentsOfFile: path, encoding: .utf8)) ?? "").split(separator: "\n") {
        if let r = line.range(of: ": ") { want[String(line[..<r.lowerBound])] = String(line[r.upperBound...]) }
    }
    check(want.count == 20, "the admission trial's recorded output has 20 cases; read \(want.count)")
    var seen = 0
    do {
        let producer = try SigningKey(seed: fixtureSeed(0)), other = try SigningKey(seed: fixtureSeed(96))
        let node = try SigningKey(seed: fixtureSeed(32))
        let kid = Array("k1".utf8)
        func desc(_ token: Bytes, id: Bytes? = nil) -> Descriptor {
            Descriptor(id: id ?? sha512(node.pub), pub: node.pub, addr: "127.0.0.1:1", token: token)
        }
        func tok(_ typ: String = "tempus_edge", _ nbf: Int64 = 1000, _ exp: Int64 = 2000, kid k: String = "k1", by: SigningKey? = nil,
                 sub: Bytes? = nil) throws -> Bytes {
            try makeTestToken(producer: by ?? producer, kid: k, sub: sub ?? node.pub, typ: typ, nbf: nbf, exp: exp)
        }
        // the node's verdict in the words of the trial: "admitted" or "refused: WHY"
        func verdict(_ d: Descriptor, now: Int64 = 1500, want w: PeerType? = .edge) -> String {
            let why = Admission.entry(d, kid: kid, producerKey: producer.pub, now: now, skew: 10, want: w)
            return why.isEmpty ? "admitted" : "refused: " + why
        }
        func said(_ label: String, _ got: String) {
            seen += 1
            same(got, want[label] ?? "(no such case in the trial)", "admission, " + label)
        }
        said("a good edge token", verdict(desc(try tok())))
        said("expired", verdict(desc(try tok("tempus_edge", 1000, 1400))))
        said("not valid yet", verdict(desc(try tok("tempus_edge", 1800, 2000))))
        said("expired, inside the skew", verdict(desc(try tok("tempus_edge", 1000, 1495))))
        said("not valid yet, inside the skew", verdict(desc(try tok("tempus_edge", 1505, 2000))))
        said("expired at exactly exp plus skew", verdict(desc(try tok("tempus_edge", 1000, 1490))))
        said("under another kid", verdict(desc(try tok(kid: "k0", by: other))))
        said("under another kid and expired too", verdict(desc(try tok("tempus_edge", 1000, 1400, kid: "k0", by: other))))
        said("signed by a key that is not the producer's", verdict(desc(try tok(by: other))))
        said("sub is another key", verdict(desc(try tok(sub: other.pub))))
        said("a bridge token where an edge is wanted", verdict(desc(try tok("tempus_bridge"))))
        said("a bridge token where a bridge is wanted", verdict(desc(try tok("tempus_bridge")), want: .bridge))
        said("id is not the hash of pub", verdict(desc(try tok(), id: sha512(other.pub))))
        var changed = try tok()
        // nbf 1000 becomes 1001 after the signature was made: the atom nbf, the tag 98 and four bytes
        let nbfAt = (0..<(changed.count - 3)).first { Array(changed[$0..<($0 + 3)]) == Array("nbf".utf8) }!
        changed[nbfAt + 7] ^= 1
        said("payload changed after signing", verdict(desc(changed)))
        said("token cut short", verdict(desc(Array(try tok().dropLast(3)))))
        let good = try tok(), nonce = Bytes(repeating: 7, count: 32)
        let proof = try node.sign(nonce + good)
        func pop(_ ok: Bool) -> String { ok ? "admitted" : "refused: the signature does not verify" }
        said("proof of possession", pop(Admission.proof(pub: node.pub, nonce: nonce, token: good, sig: proof)))
        said("proof for another nonce", pop(Admission.proof(pub: node.pub, nonce: Bytes(repeating: 8, count: 32), token: good, sig: proof)))
        said("proof by another key", pop(Admission.proof(pub: node.pub, nonce: nonce, token: good, sig: try other.sign(nonce + good))))
        said("proof over another token", pop(Admission.proof(pub: node.pub, nonce: nonce, token: try tok("tempus_edge", 1000, 2500), sig: proof)))
        check(seen == 19, "19 of the trial's 20 cases are judged here (the 20th compares a signature with a fixture of the trial)")
        // the whitelist rule, both sides (rulings OQ-3, NQ-4), with the connection actor's texts
        same(Admission.whitelist(typ: "tempus_edge", listed: false), "", "an edge that is not listed")
        same(Admission.whitelist(typ: "tempus_sentinel", listed: true), "", "a listed sentinel")
        same(Admission.whitelist(typ: "tempus_bridge", listed: false),
             "a tempus_bridge or tempus_sentinel token under a certificate that is not in the tempus whitelist", "a bridge that is not listed")
        same(Admission.whitelist(typ: "tempus_edge", listed: true),
             "a certificate of the tempus whitelist with a token whose typ is not tempus_bridge or tempus_sentinel", "a listed edge")
    } catch {
        check(false, "admission tests: \(error)")
    }
}

// ---------------------------------------------------------------- the atoms a node holds
func atomTests(_ root: String) {
    var union = Set<String>()
    for path in ["/src/tempus/bees_tempus.atoms", "/src/trust/bees_trust.atoms"] {
        guard let text = try? String(contentsOfFile: root + path, encoding: .utf8) else {
            check(false, "the atoms file \(path) cannot be read")
            return
        }
        for line in text.split(separator: "\n") {
            let name = line.trimmingCharacters(in: .whitespaces)
            if !name.isEmpty && !name.hasPrefix("#") { union.insert(name) }
        }
    }
    same("missing: \(union.subtracting(knownAtoms).sorted()) extra: \(knownAtoms.subtracting(union).sorted())", "missing: [] extra: []",
         "knownAtoms is the union of src/tempus/bees_tempus.atoms and src/trust/bees_trust.atoms")
    // the node's word for a frame, as a Silica node says it (the three frames were sent to a Silica node on 2026-11-23)
    func word(_ t: Term) -> String { (try? etfEncode(t)).map { bodyKind($0).why } ?? "not encoded" }
    same(word(.map(["t": .atom("truncated")])), "unknown kind", "a frame whose t is an atom of the rejection list")
    same(word(.map(["t": .atom("server_not_pinned")])), "unknown kind", "a frame whose t is an atom of TRUST's results")
    same(word(.map(["t": .atom("tick")])), "unknown_atom", "a frame whose t is an atom no production node holds")
    same(word(.map(["t": .atom("sample"), "store": .atom("no_such_atom"), "n": .int(1)])), "unknown_atom", "a value that is an atom no node holds")
}

let args = CommandLine.arguments
if args.count == 2 && args[1] == "model" {
    model()
} else if args.count == 2 {
    clockTests(args[1])
    configTests()
    admissionTests(args[1])
    atomTests(args[1])
    print("tempus-node-tests: \(passed) passed, \(failed) failed")
    exit(failed == 0 ? 0 : 1)
} else {
    print("usage: tempus-node-tests BEES_ROOT | tempus-node-tests model")
    exit(2)
}
