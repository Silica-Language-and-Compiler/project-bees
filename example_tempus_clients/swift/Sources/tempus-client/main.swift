// The command line of the Swift example TEMPUS client. An example only: not for production (README.md).
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

let argv = Array(CommandLine.arguments.dropFirst())
let flags: Set<String> = ["--system-clock", "--no-entry-check"]
switch argv.first {
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
    fail("usage: tempus-client read-hex | test-token | dial | listen (see the README)")
}
