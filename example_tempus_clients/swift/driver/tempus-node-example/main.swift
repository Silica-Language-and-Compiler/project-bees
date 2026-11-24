// An application that is a TEMPUS node, using the Swift TEMPUS extension: the smallest complete one. It links
// TempusNode and nothing of the tests. It reads the machine's clock, runs its own timers and draws from the system's
// secure random source; nothing here can set its time.
//
//   tempus-node-example KEY=VALUE ...      every key is required unless marked optional; nothing has a default
//     role=edge|sentinel  listen_address=A.B.C.D  port=N  address=A.B.C.D:PORT (what other nodes dial)
//     seed_file=PATH (the 32 bytes of the Ed25519 private seed)  cert_file=PATH (PEM)  token_file=PATH (the token's bytes)
//     producer_kid=TEXT  producer_key=HEX  sentinels=A.B.C.D:PORT,... (optional for a first sentinel)
//     whitelist=PEM_FILE,... (optional)  edge=CAPACITY/SHUFFLE_LENGTH/TICK_MS  bridge=...  sentinel=...
//     shuffle_timeout_ms=N  inflight_max=N  clock_skew_ms=N  clock_back=follow|hold|stop  clock_back_limit_s=N (with stop)
//     clock_fail=continue|pause  clock_read_ms=N  join_retry_initial_ms=N  join_retry_max_ms=N
// It prints the node's lines and what the application is told, and ends when its standard input says `exit` or ends.
import Foundation
import TempusClient
import TempusNode

func fail(_ text: String) -> Never {
    FileHandle.standardError.write(Data(("tempus-node-example: " + text + "\n").utf8))
    exit(2)
}

var given: [String: String] = [:]
for a in CommandLine.arguments.dropFirst() {
    guard let eq = a.firstIndex(of: "=") else { fail("not KEY=VALUE: \(a)") }
    given[String(a[..<eq])] = String(a[a.index(after: eq)...])
}

@MainActor func need(_ key: String) -> String {
    guard let v = given[key] else { fail("\(key) is required (no default)") }
    return v
}

@MainActor func number(_ key: String) -> Int {
    guard let n = Int(need(key)) else { fail("\(key) is not a number") }
    return n
}

@MainActor func file(_ path: String) -> Data {
    guard let d = FileManager.default.contents(atPath: path) else { fail("cannot read \(path)") }
    return d
}

@MainActor func certificate(_ path: String) -> Bytes {
    guard let der = certificateDER(pem: String(decoding: file(path), as: UTF8.self)) else { fail("\(path) holds no certificate") }
    return der
}

@MainActor func store(_ key: String) -> StoreConfig {
    let p = need(key).split(separator: "/").compactMap { Int($0) }
    guard p.count == 3 else { fail("\(key) is not CAPACITY/SHUFFLE_LENGTH/TICK_MS") }
    return StoreConfig(capacity: p[0], shuffleLength: p[1], tickMs: p[2])
}

guard let role = PeerType(rawValue: "tempus_" + need("role")) else { fail("role is not edge, bridge or sentinel") }
guard let back = ClockBack(rawValue: need("clock_back")) else { fail("clock_back is not follow, hold or stop") }
guard let clockFail = ClockFail(rawValue: need("clock_fail")) else { fail("clock_fail is not continue or pause") }
guard let producerKey = unhex(need("producer_key")) else { fail("producer_key is not hex") }
let sentinels: [Sentinel] = (given["sentinels"] ?? "").split(separator: ",").map { text in
    guard let colon = text.lastIndex(of: ":"), let port = Int(text[text.index(after: colon)...]) else { fail("a sentinel is A.B.C.D:PORT") }
    return Sentinel(host: String(text[..<colon]), port: port)
}

let config = TempusConfig(
    role: role, listenAddress: need("listen_address"), port: number("port"), sentinels: sentinels,
    edge: store("edge"), bridge: store("bridge"), sentinel: store("sentinel"),
    producerKid: Array(need("producer_kid").utf8), producerKey: producerKey,
    whitelist: (given["whitelist"] ?? "").split(separator: ",").map { certificate(String($0)) },
    shuffleTimeoutMs: number("shuffle_timeout_ms"), inflightMax: number("inflight_max"), clockSkewMs: number("clock_skew_ms"),
    clockBack: back, clockBackLimitS: given["clock_back_limit_s"].map { _ in number("clock_back_limit_s") },
    clockFail: clockFail, clockReadMs: number("clock_read_ms"),
    joinRetryInitialMs: number("join_retry_initial_ms"), joinRetryMaxMs: number("join_retry_max_ms"))
let identity = NodeIdentity(seed: Bytes(file(need("seed_file"))), certificateDER: certificate(need("cert_file")),
                            token: Bytes(file(need("token_file"))), address: need("address"))

setvbuf(stdout, nil, _IOLBF, 0)
let node: TempusNode
do {
    node = try TempusNode(config: config, identity: identity, lines: { print($0) }, events: { event in
        // what the application is told; an application acts on these (a new token, a new node), this one prints them
        switch event {
        case .ownTokenNotValid(let reason): print("application: told that the node's own token is not valid any more: \(reason)")
        case .keyRotated(let kid, _): print("application: told that a peer answered key_rotated, its current kid is \(String(decoding: kid, as: UTF8.self))")
        case .clockNotRead(let text): print("application: told that \(text)")
        case .stopped(let text): print("application: told that \(text)")
        case .listenFailed(let text): print("application: told that the node does not listen: \(text)")
        case .listening, .view, .joined, .peerRefused: break
        }
    })
} catch {
    exit(1)          // the node has written the line that says why
}
node.start()
while let line = readLine(), line != "exit" {}
node.stop()
