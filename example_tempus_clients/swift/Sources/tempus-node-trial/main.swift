// TEST ONLY: a node of the Swift TEMPUS extension as the trial trials/c8_tempus_node_swift runs it. Its identity and
// token come from fixed seeds (TempusTestSupport), and its clock, timers and draws are set by hand: the trial tool
// writes commands to its standard input. None of this is in the extension: the node is made with the initializer
// that takes its sources, and is refused on an address that is not loopback.
//
//   tempus-node-trial KEY=VALUE ...
//     role=edge|sentinel  port=N  seed=FIRST_BYTE  token=TYP:NBF:EXP  cert=PEM_FILE (optional: else one is made)
//     sentinels=127.0.0.1:PORT,...  whitelist=PEM_FILE,...  stores=CAP/LEN,CAP/LEN,CAP/LEN (edge, bridge, sentinel)
//     inflight_max=N  shuffle_timeout_ms=N  clock_back=...  clock_back_limit_s=N  clock_fail=...  draws=3,0,7
//     join_retry=INITIAL/MAX  now=SECONDS (optional: the first reading; without it the clock cannot be read at start)
//   Commands, one per line:
//     clock SECONDS | clock fail      the next reading of the node's clock, taken at once
//     tick STORE                      the tick timer of that store runs now
//     retry                           the join's retry timer runs now
//     token TYP:NBF:EXP               the application passes a new token
//     exit
// It prints the node's lines, one line `view STORE: ID@AGE ...` for each view the node tells its application, and one
// line `application: ...` for everything else it is told.
import Foundation
import TempusClient
import TempusNode
import TempusTestSupport

func fail(_ text: String) -> Never {
    FileHandle.standardError.write(Data(("tempus-node-trial: " + text + "\n").utf8))
    exit(2)
}

var given: [String: String] = [:]
for a in CommandLine.arguments.dropFirst() {
    guard let eq = a.firstIndex(of: "=") else { fail("not KEY=VALUE: \(a)") }
    given[String(a[..<eq])] = String(a[a.index(after: eq)...])
}

@MainActor func need(_ key: String) -> String {
    guard let v = given[key] else { fail("\(key) is required") }
    return v
}

@MainActor func number(_ key: String) -> Int {
    guard let n = Int(need(key)) else { fail("\(key) is not a number") }
    return n
}

@MainActor func certificate(_ path: String) -> Bytes {
    guard let pem = try? String(contentsOfFile: path, encoding: .utf8), let der = certificateDER(pem: pem) else { fail("no certificate in \(path)") }
    return der
}

@MainActor func testToken(_ text: String, sub: Bytes) -> Bytes {
    let p = text.split(separator: ":").map(String.init)
    guard p.count == 3, let nbf = Int64(p[1]), let exp = Int64(p[2]), let producer = try? SigningKey(seed: fixtureSeed(0)),
          let t = try? makeTestToken(producer: producer, kid: "k1", sub: sub, typ: p[0], nbf: nbf, exp: exp) else { fail("a token is TYP:NBF:EXP") }
    return t
}

guard let role = PeerType(rawValue: "tempus_" + need("role")) else { fail("role") }
guard let first = UInt8(need("seed")), let key = try? SigningKey(seed: fixtureSeed(first)) else { fail("seed") }
guard let back = ClockBack(rawValue: need("clock_back")), let clockFail = ClockFail(rawValue: need("clock_fail")) else { fail("the clock's choices") }
let sizes = need("stores").split(separator: ",").map { $0.split(separator: "/").compactMap { Int($0) } }
guard sizes.count == 3, sizes.allSatisfy({ $0.count == 2 }) else { fail("stores") }
let retry = need("join_retry").split(separator: "/").compactMap { Int($0) }
guard retry.count == 2 else { fail("join_retry") }
let port = number("port")
let sentinels: [Sentinel] = (given["sentinels"] ?? "").split(separator: ",").map { text in
    let p = text.split(separator: ":")
    return Sentinel(host: String(p[0]), port: Int(p[1]) ?? 0)
}
guard let producer = try? SigningKey(seed: fixtureSeed(0)) else { fail("the producer key") }
// the timers never run by themselves, so the tick and clock periods are only values that pass the bounds
let config = TempusConfig(
    role: role, listenAddress: "127.0.0.1", port: port, sentinels: sentinels,
    edge: StoreConfig(capacity: sizes[0][0], shuffleLength: sizes[0][1], tickMs: 1000),
    bridge: StoreConfig(capacity: sizes[1][0], shuffleLength: sizes[1][1], tickMs: 1000),
    sentinel: StoreConfig(capacity: sizes[2][0], shuffleLength: sizes[2][1], tickMs: 1000),
    producerKid: Array("k1".utf8), producerKey: producer.pub,
    whitelist: (given["whitelist"] ?? "").split(separator: ",").map { certificate(String($0)) },
    shuffleTimeoutMs: number("shuffle_timeout_ms"), inflightMax: number("inflight_max"), clockSkewMs: 10000,
    clockBack: back, clockBackLimitS: given["clock_back_limit_s"].map { _ in number("clock_back_limit_s") },
    clockFail: clockFail, clockReadMs: 1000, joinRetryInitialMs: retry[0], joinRetryMaxMs: retry[1])
let certDER: Bytes
if let path = given["cert"] {
    certDER = certificate(path)
} else {
    guard let made = try? selfSignedCertificate(key: key, commonName: "bees tempus trial node", serial: 1) else { fail("the certificate") }
    certDER = made
}
let identity = NodeIdentity(seed: fixtureSeed(first), certificateDER: certDER, token: testToken(need("token"), sub: key.pub),
                            address: "127.0.0.1:\(port)")

let clock = ManualClock(given["now"].flatMap { Int64($0) }), timers = ManualTimers()
let random = ListRandom(need("draws").split(separator: ",").compactMap { Int($0) })
setvbuf(stdout, nil, _IOLBF, 0)
print("TEST ONLY: this node's clock, timers and draws are set by the trial")
let node: TempusNode
do {
    node = try TempusNode(config: config, identity: identity, sources: NodeSources(clock: clock, timers: timers, random: random),
                          lines: { print($0) }, events: { event in
        switch event {
        case .view(let store, let entries):
            print("view \(store.rawValue):" + (entries.isEmpty ? " (empty)" : entries.map { " \(hex(Array($0.id.prefix(4))))@\($0.age)" }.joined()))
        case .ownTokenNotValid(let reason): print("application: told that the node's own token is not valid any more: \(reason)")
        case .keyRotated(let kid, let dialed):
            print("application: told that a peer \(dialed ? "this node dialed" : "that dialed this node") answered key_rotated, its current kid is \(String(decoding: kid, as: UTF8.self))")
        case .clockNotRead(let text): print("application: told that \(text)")
        case .stopped(let text): print("application: told that \(text)")
        case .listenFailed(let text): print("application: told that the node does not listen: \(text)")
        case .peerRefused(let e, let id, let verified):
            print("application: told that a peer was refused: \(e) \(hex(Array(id.prefix(8)))) \(verified ? "token verified" : "token not verified")")
        case .listening, .joined: break
        }
    })
} catch {
    print("boot: refused, nothing started")
    exit(1)
}
node.start()
while let line = readLine(), line != "exit" {
    let w = line.split(separator: " ").map(String.init)
    switch w.first {
    case "clock" where w.count == 2:
        clock.set(Int64(w[1]))            // `fail` is no number: the clock cannot be read
        if !timers.fire(.clockRead) { print("trial: no clock timer is armed") }
    case "tick" where w.count == 2:
        if let st = PeerType(rawValue: w[1]), timers.fire(.tick(st)) {} else { print("trial: no tick timer for \(w[1])") }
    case "retry":
        if !timers.fire(.joinRetry) { print("trial: no join retry timer is armed") }
    case "token" where w.count == 2:
        node.replaceToken(testToken(w[1], sub: key.pub))
    default:
        print("trial: unknown command: \(line)")
    }
}
node.stop()
