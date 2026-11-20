// Unit tests of the Swift example TEMPUS client, as a plain program: Apple's Command Line Tools without Xcode have
// neither XCTest nor a Testing module that the package manager finds.
//
//     tempus-client-tests BEES_ROOT
//
// Part A, against the Silica frame unit: trials/t2_tempus_frames prints, for every frame and token it writes or
// mutates, a line `NAME hex HEX` and a line `NAME read: ...`. This program builds the same frames and tokens from the
// same inputs and requires the same bytes, and reads every HEX of every recorded golden and requires the library's
// verdict. The test-only tick and clock frames are no part of a client: this client builds none, and must refuse each
// as a frame of no kind, which is what the golden says the library does.
// Part B, on its own: round trips, key order, integers, Ed25519 against RFC 8032 and against the vectors the Python
// example made (native/tempus/selftest/vectors.h), the certificates of tools/bees_tempus_certs.py byte for byte, and
// TRUST's call, cast and result frames against bytes the Python example wrote.
// Part C, the active part: this client against itself over mutual TLS 1.3 on 127.0.0.1, ports the system assigns.
// Keys, certificates and tokens are TEST ONLY, from fixed seeds. The clock is the number 1500, never the machine's.
import Foundation
import TempusClient

var passed = 0
var failed = 0

func check(_ what: String, _ ok: Bool, _ detail: @autoclosure () -> String = "") {
    if ok {
        passed += 1
    } else {
        failed += 1
        print("FAIL: \(what)" + (detail().isEmpty ? "" : ": " + detail()))
    }
}

func equal<T: Equatable>(_ what: String, _ got: T, _ want: T) {
    check(what, got == want, "got \(got), wanted \(want)")
}

func refusal(_ body: () throws -> Void) -> String? {
    do {
        try body()
        return nil
    } catch let why as Refused {
        return why.reason
    } catch {
        return "another error: \(error)"
    }
}

func bytes(_ s: String) -> Bytes { Array(s.utf8) }
func rep(_ ch: String, _ n: Int) -> Bytes { Bytes(repeating: bytes(ch)[0], count: n) }

guard CommandLine.arguments.count == 2 else {
    print("usage: tempus-client-tests BEES_ROOT")
    exit(2)
}
let root = CommandLine.arguments[1]

// ---------------------------------------------------------------- A: against the Silica frame unit
let shuffleLength = 3
let addr = "127.0.0.1:22801"          // a value in the frames only: nothing listens there
let sig = rep("S", 64)
let pub = rep("p", 32)
func tok(_ kid: String, _ sub: Bytes, _ typ: String, _ nbf: Int64, _ exp: Int64) -> Bytes {
    sig + (try! tokenPayload(kid: bytes(kid), sub: sub, typ: typ, nbf: nbf, exp: exp))
}
let token = tok("k1", pub, "tempus_edge", 1000, 2000)
func desc(_ id: Bytes, _ p: Bytes = pub, _ a: String = addr, _ t: Bytes = token) -> Descriptor {
    Descriptor(id: id, pub: p, addr: a, token: t)
}
func peer(_ ch: String, _ age: Int64) -> Entry { Entry(age: age, d: desc(rep(ch, 64))) }

func built() throws -> [String: Bytes] {
    let three = [peer("A", 0), peer("B", 7), peer("C", 65535)]
    let four = [peer("D", 1)] + three
    func one(_ d: Descriptor) throws -> Bytes { try shuffle(store: "tempus_edge", entries: [Entry(age: 0, d: d)]) }
    return [
        "advert": try advert(desc(rep("A", 64))),
        "pop_challenge": try challenge(nonce: rep("N", 32)),
        "pop_response": try response(sig: rep("G", 64)),
        "key_rotated": try keyRotated(kid: bytes("k2")),
        "shuffle": try shuffle(store: "tempus_edge", entries: three),
        "shuffle_reply": try shuffleReply(store: "tempus_bridge", entries: []),
        "sample": try sample(store: "tempus_sentinel", n: 2),
        "sample_reply": try sampleReply(store: "tempus_sentinel", entries: [peer("B", 7)]),
        "done": try done(),
        "token": token,
        "token of a bridge": tok("producer-key-2026", rep("q", 32), "tempus_bridge", 0, 1763424300),
        "token whose exp is not after nbf": tok("k1", pub, "tempus_edge", 2000, 2000),
        "token with a 31-byte sub": tok("k1", rep("p", 31), "tempus_edge", 1000, 2000),
        "token with an empty kid": tok("", pub, "tempus_edge", 1000, 2000),
        "token with a 65-byte kid": tok(String(repeating: "k", count: 65), pub, "tempus_edge", 1000, 2000),
        "shuffle of four entries, shuffle length three": try shuffle(store: "tempus_edge", entries: four),
        "entry of age 65536": try shuffle(store: "tempus_edge", entries: [peer("A", 65536)]),
        "entry with a 63-byte id": try one(desc(rep("A", 63))),
        "entry with a 31-byte pub": try one(desc(rep("A", 64), rep("p", 31))),
        "entry with a 2-byte addr": try one(desc(rep("A", 64), pub, "a:")),
        "entry with a 262-byte addr": try one(desc(rep("A", 64), pub, String(repeating: "a", count: 262))),
        "entry with a 64-byte token": try one(desc(rep("A", 64), pub, addr, sig)),
        "advert with a 65-byte id": try advert(desc(rep("A", 65))),
        "sample of 0": try sample(store: "tempus_edge", n: 0),
        "sample of 4, shuffle length three": try sample(store: "tempus_edge", n: 4),
        "nonce of 31 bytes": try challenge(nonce: rep("N", 31)),
        "sig of 65 bytes": try response(sig: rep("G", 65)),
        "kid of no bytes": try keyRotated(kid: []),
    ]
}

/// name -> (the bytes, the Silica reader's text) from one output of the trial
func parse(_ path: String) -> [String: (Bytes, String)] {
    var hexes: [String: Bytes] = [:], reads: [String: String] = [:]
    let text = (try? String(contentsOfFile: path, encoding: .utf8)) ?? ""
    for line in text.split(separator: "\n").map(String.init) {
        if let r = line.range(of: " hex ") {
            hexes[String(line[..<r.lowerBound])] = unhex(String(line[r.upperBound...])) ?? []
        } else if line.hasSuffix(" hex") {
            hexes[String(line.dropLast(4))] = []
        } else if let r = line.range(of: " read: ") {
            reads[String(line[..<r.lowerBound])] = String(line[r.upperBound...])
        }
    }
    var out: [String: (Bytes, String)] = [:]
    for (name, data) in hexes { out[name] = (data, reads[name] ?? "") }
    return out
}

let leaf = root + "/trials/t2_tempus_frames"
let goldens = ((try? FileManager.default.contentsOfDirectory(atPath: leaf)) ?? [])
    .filter { $0.hasPrefix("frames.") && $0.hasSuffix(".scout") }.sorted().map { leaf + "/" + $0 }
check("there is a golden of trials/t2_tempus_frames to compare with", !goldens.isEmpty)
let testOnly = "the library refuses it (unknown kind)"
var testOnlySeen = 0
for path in goldens {
    let seen = parse(path)
    let name = (path as NSString).lastPathComponent
    check("\(name): at least 44 frames and tokens", seen.count >= 44, "\(seen.count)")
    // the same bytes from the same inputs
    for (what, data) in try built() {
        guard let theirs = seen[what] else {
            check("\(name): a line for \(what)", false)
            continue
        }
        check("\(name): same bytes: \(what)", theirs.0 == data, "Silica \(hex(theirs.0)), Swift \(hex(data))")
    }
    // the same verdict on every frame
    for (what, (data, text)) in seen {
        let why = refusal {
            if what.hasPrefix("token") { _ = try readToken(data) } else { _ = try readBody(data, shuffleLength: shuffleLength) }
        }
        if text.hasPrefix(testOnly) {
            testOnlySeen += 1
            equal("\(name): the test-only frame `\(what)` is a frame of no kind", why, "unknown kind")
        } else {
            let silicaAccepts = !text.contains("refused")
            check("\(name): same verdict: \(what)", (why == nil) == silicaAccepts,
                  "Silica says \"\(text)\", Swift says \(why ?? "accepted")")
        }
    }
    // the same fields read
    if let f = try? readBody(seen["shuffle"]?.0 ?? [], shuffleLength: shuffleLength), case .shuffle(let store, let entries) = f {
        equal("\(name): the shuffle's store", store, "tempus_edge")
        equal("\(name): the shuffle's entries", entries.map { "\(String(decoding: $0.d.id.prefix(4), as: UTF8.self))/\($0.d.id.count):\($0.age)" }.joined(separator: " "),
              "AAAA/64:0 BBBB/64:7 CCCC/64:65535")
        check("\(name): Silica read the same entries", (seen["shuffle"]?.1 ?? "").contains("AAAA/64:0 BBBB/64:7 CCCC/64:65535"))
    } else {
        check("\(name): the shuffle is read", false)
    }
    if let t = try? readToken(seen["token"]?.0 ?? []) {
        check("\(name): the token's fields", t.fields == (try! readToken(token)).fields && t.fields.kid == bytes("k1")
              && t.fields.typ == "tempus_edge" && t.fields.nbf == 1000 && t.fields.exp == 2000 && t.payload.count == 98)
        check("\(name): Silica read the same token", (seen["token"]?.1 ?? "").contains("kid k1 sub pppp/32 typ 1 nbf 1000 exp 2000 payload of 98 bytes"))
    } else {
        check("\(name): the token is read", false)
    }
}
check("the goldens hold the test-only frames this client must refuse", goldens.isEmpty || testOnlySeen >= 6 * goldens.count, "\(testOnlySeen)")

// ---------------------------------------------------------------- B: on its own
for (what, data) in try built() where !what.hasPrefix("token") {
    equal("round trip: \(what)", try etfEncode(try etfDecode(data)), data)
}
do {
    let body = try sample(store: "tempus_edge", n: 1)
    func at(_ needle: Bytes) -> Int {
        (0...(body.count - needle.count)).first { Array(body[$0..<($0 + needle.count)]) == needle } ?? -1
    }
    let n = at([0x77, 1] + bytes("n")), s = at([0x77, 5] + bytes("store")), t = at([0x77, 1] + bytes("t"))
    check("keys are written in name order", n >= 0 && n < s && s < t, "\(n) \(s) \(t)")
    equal("the frame prefix", Array(try frame(try done()).prefix(4)), [0, 0, 0, 15])
    // integers, against bytes the Python example wrote
    for (n, want) in [(Int64(0), "836100"), (255, "8361ff"), (256, "836200000100"), (-1, "8362ffffffff"),
                      (2147483647, "83627fffffff"), (-2147483648, "836280000000"), (2147483648, "836e040000000080"),
                      (-2147483649, "836e040101000080"), (9007199254740992, "836e070000000000000020"),
                      (1763424000000, "836e060000d842949a01")] {
        equal("the integer \(n)", hex(try etfEncode(.int(n))), want)
        equal("the integer \(n) read back", try etfDecode(unhex(want)!), .int(n))
    }
    // TRUST's frames, against bytes the Python example wrote (call_frame("1", "bees_c3", "add", [2, 40]), a cast, a result)
    equal("a call", hex(try callFrame(reqId: bytes("1"), module: "bees_c3", function: "add", args: [2, 40])),
          "83740000000877016161027704617267736c00000002610261286a770166770361646477016d7707626565735f633377046f707473740000000077067265715f69646d0000000131770174770463616c6c77037665726101")
    equal("a cast", hex(try callFrame(kind: "cast", reqId: bytes("r9"), module: "m", function: "f", args: [])),
          "83740000000877016161007704617267736a77016677016677016d77016d77046f707473740000000077067265715f69646d00000002723977017477046361737477037665726101")
    let result = try readAny(unhex("83740000000477067265715f69646d00000001317701747706726573756c74770576616c7565612a77037665726101")!)
    equal("a result", result, .other(kind: "result", fields: ["req_id": .binary(bytes("1")), "value": .int(42), "ver": .int(1)]))
    equal("a result is no tempus/1 kind for the strict reader",
          refusal { _ = try readBody(unhex("83740000000477067265715f69646d00000001317701747706726573756c74770576616c7565612a77037665726101")!, shuffleLength: 3) }, "unknown kind")
    check("a request id above 16 bytes is not written", (try? callFrame(reqId: rep("r", 17), module: "m", function: "f", args: [])) == nil)
    // refusals of the reader
    for (bad, why) in [([], "truncated"), ([0x82], "bad_version"), (try done() + [0], "trailing_bytes"),
                       ([0x83, 0x68, 0x00], "bad_tag"), ([0x83, 0x74, 0, 0, 0, 1, 0x61, 1, 0x61, 1], "bad_tag")] as [(Bytes, String)] {
        equal("the reader refuses \(hex(bad))", refusal { _ = try readBody(bad, shuffleLength: 3) }, why)
    }
    let twice: Bytes = [0x83, 0x74, 0, 0, 0, 2] + [0x77, 1] + bytes("t") + [0x77, 4] + bytes("done") + [0x77, 1] + bytes("t") + [0x77, 4] + bytes("done")
    equal("a key twice", refusal { _ = try readBody(twice, shuffleLength: 3) }, "duplicate_field")
    equal("a map nested too deep", refusal { _ = try etfDecode([0x83] + Array(repeating: [0x6c, 0, 0, 0, 1], count: 8).flatMap { $0 } + Bytes(repeating: 0x6a, count: 9)) }, "too_deep")
    equal("a body above the ceiling", refusal { _ = try etfDecode(Bytes(repeating: 0x83, count: frameMax + 1)) }, "too_large")
    check("a body above the ceiling is not framed", (try? frame(Bytes(repeating: 0, count: frameMax + 1))) == nil)
}

// Ed25519: RFC 8032 section 7.1, test 1 (the empty message)
do {
    let k = try SigningKey(seed: unhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")!)
    equal("RFC 8032 test 1: the public key", hex(k.pub), "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a")
    equal("RFC 8032 test 1: the signature", hex(try k.sign([])),
          "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b")
}

// the vectors the Python example made with the `cryptography` package (TEST ONLY seeds 00..1f and 20..3f)
func vector(_ name: String) -> Bytes {
    let text = (try? String(contentsOfFile: root + "/native/tempus/selftest/vectors.h", encoding: .utf8)) ?? ""
    guard let a = text.range(of: " \(name)["), let open = text.range(of: "{", range: a.upperBound..<text.endIndex),
          let close = text.range(of: "}", range: open.upperBound..<text.endIndex) else { return [] }
    return text[open.upperBound..<close.lowerBound].split(separator: ",").compactMap { UInt8($0.trimmingCharacters(in: .whitespaces)) }
}
do {
    let producer = try SigningKey(seed: fixtureSeed(0)), node = try SigningKey(seed: fixtureSeed(32))
    equal("the vectors are there", vector("token").count, 162)
    equal("the producer's public key", producer.pub, vector("producer_pub"))
    equal("the node's public key", node.pub, vector("node_pub"))
    equal("the identity is the SHA-512 of the key", peerId(pub: node.pub), vector("node_id"))
    let t = try makeTestToken(producer: producer, kid: "k1", sub: node.pub, typ: "tempus_edge", nbf: 1000, exp: 2000)
    equal("a token with the TEST ONLY keys is the Python example's, byte for byte", t, vector("token"))
    equal("Ed25519 is deterministic", t, try makeTestToken(producer: producer, kid: "k1", sub: node.pub, typ: "tempus_edge", nbf: 1000, exp: 2000))
    let me = try Identity(seed: fixtureSeed(32), token: t, addr: addr)
    equal("the proof of possession signs nonce || token", try me.prove(nonce: vector("nonce")), vector("pop_sig"))

    func v(_ now: Int64, _ skew: Int64 = 0, kid: String = "k1", producer p: SigningKey = producer) -> Verifier {
        Verifier(producerPub: p.pub, kid: bytes(kid), clock: { now }, skew: skew)
    }
    let d = try me.descriptor()
    equal("a good token verifies", refusal { try v(1500).checkDescriptor(d) }, nil)
    for (now, skew, ok) in [(999, 0, false), (999, 1, true), (2000, 0, false), (2000, 1, true), (2001, 1, false)] as [(Int64, Int64, Bool)] {
        check("the window at \(now) with skew \(skew)", (refusal { try v(now, skew).checkDescriptor(d) } == nil) == ok)
    }
    equal("before nbf", refusal { try v(989, 10).checkDescriptor(d) }, "the token is not valid yet")
    equal("at exp plus skew", refusal { try v(2010, 10).checkDescriptor(d) }, "the token has expired")
    equal("another kid", refusal { try v(1500, kid: "k2").checkDescriptor(d) }, "key_rotated")
    equal("another kid comes before every other fault", refusal { try v(5000, kid: "k2", producer: node).checkDescriptor(d) }, "key_rotated")
    equal("another producer key", refusal { try v(1500, producer: node).checkDescriptor(d) }, "the signature does not verify")
    var flipped = d
    flipped.token[70] ^= 1
    check("a changed payload", refusal { try v(1500).checkDescriptor(flipped) } != nil)
    var otherId = d
    otherId.id = peerId(pub: producer.pub)
    equal("an id that is not the key's hash", refusal { try v(1500).checkDescriptor(otherId) }, "id is not the SHA-512 of pub")
    let third = try fixtureIdentity(128, typ: "tempus_edge", nbf: 1000, exp: 2000, addr: addr)
    var otherSub = d
    otherSub.token = third.token
    equal("a token for another key", refusal { try v(1500).checkDescriptor(otherSub) }, "sub is not the peer's key")
    var onlyBridges = v(1500)
    onlyBridges.types = ["tempus_bridge", "tempus_sentinel"]
    equal("a type this verifier does not admit", refusal { try onlyBridges.checkDescriptor(d) }, "typ is not allowed")
    var cut = d
    cut.token.removeLast()
    equal("a token cut short", refusal { try v(1500).checkDescriptor(cut) }, "truncated")
    // the channel binding: every field of the descriptor verifies, and the certificate is another key's
    equal("the binding holds for the peer's own certificate", refusal { try v(1500).checkDescriptor(d, certDER: me.certDER) }, nil)
    equal("the binding refuses another key's certificate", refusal { try v(1500).checkDescriptor(d, certDER: third.certDER) },
          "the certificate's key is not the advert's pub")
    // the whitelist rule for a peer whose token says bridge or sentinel
    let sentinel = try fixtureIdentity(64, typ: "tempus_sentinel", nbf: 1000, exp: 2000, addr: addr)
    var listed = v(1500)
    listed.whitelist = [sha512(third.certDER)]
    equal("a sentinel whose certificate is not listed", refusal { try listed.checkDescriptor(try sentinel.descriptor(), certDER: sentinel.certDER) },
          "the certificate of a tempus_sentinel is not in the whitelist")
    listed.whitelist = [sha512(sentinel.certDER)]
    equal("a sentinel whose certificate is listed", refusal { try listed.checkDescriptor(try sentinel.descriptor(), certDER: sentinel.certDER) }, nil)
    listed.whitelist = []
    equal("an edge needs no entry in the whitelist", refusal { try listed.checkDescriptor(d, certDER: me.certDER) }, nil)
    // the proof of possession
    let nonce = rep("N", 32)
    equal("a proof verifies", refusal { try v(1500).checkProof(pub: me.pub, nonce: nonce, token: t, sig: try me.prove(nonce: nonce)) }, nil)
    equal("a proof over another nonce", refusal { try v(1500).checkProof(pub: me.pub, nonce: rep("M", 32), token: t, sig: try me.prove(nonce: nonce)) },
          "the proof of possession does not verify")
    equal("a proof by another key", refusal { try v(1500).checkProof(pub: me.pub, nonce: nonce, token: t, sig: try third.key.sign(nonce + t)) },
          "the proof of possession does not verify")
    // entries
    equal("an entry of its store", refusal { try v(1500).checkEntry(try me.entry(age: 3), store: "tempus_edge") }, nil)
    equal("an entry of another store", refusal { try v(1500).checkEntry(try me.entry(age: 3), store: "tempus_bridge") }, "the entry's typ is not the store's")
}

// certificates: the files of tools/bees_tempus_certs.py, byte for byte
do {
    let seeds: [(String, UInt8)] = [("bridge", 160), ("node", 32), ("other", 64), ("sentinel", 128), ("x1", 176), ("x2", 192), ("x3", 208), ("x4", 224)]
    let dir = root + "/trials/t5_tempus_tls/certs/"
    for (i, (name, first)) in seeds.enumerated() {
        guard let pem = try? String(contentsOfFile: dir + name + ".pem", encoding: .utf8), let der = certificateDER(pem: pem) else {
            check("the certificate file of \(name) is read", false)
            continue
        }
        let key = try SigningKey(seed: fixtureSeed(first))
        let made = try selfSignedCertificate(key: key, commonName: "bees tempus test " + name, serial: i + 1)
        check("the certificate of \(name) is the tool's, byte for byte", made == der)
        equal("the PEM of \(name)", certificatePEM(der: made), pem)
        equal("the key of the certificate of \(name)", try certificateKey(der: der), key.pub)
    }
    if let pem = try? String(contentsOfFile: dir + "p256.pem", encoding: .utf8), let der = certificateDER(pem: pem) {
        equal("a P-256 certificate", refusal { _ = try certificateKey(der: der) }, "the certificate's key is not Ed25519")
    } else {
        check("the P-256 certificate file is read", false)
    }
    equal("bytes that are no certificate", refusal { _ = try certificateKey(der: [1, 2, 3]) }, "the certificate cannot be read")
}

// ---------------------------------------------------------------- C: the active part, this client against itself
let now: Int64 = 1500, skew: Int64 = 10
let advertised = "127.0.0.1:22899"     // the dialer's advertised listen address; nothing dials it in these tests
let producerPub = try SigningKey(seed: fixtureSeed(0)).pub
let oldProducer = try SigningKey(seed: fixtureSeed(96))

func who(_ first: UInt8, _ typ: String = "tempus_edge", nbf: Int64 = 1000, exp: Int64 = 2000, addr: String? = advertised,
         kid: String = "k1", producer: SigningKey? = nil) -> Identity {
    try! fixtureIdentity(first, typ: typ, nbf: nbf, exp: exp, addr: addr, kid: kid, producer: producer)
}
func verifier(at time: Int64 = now, kid: String = "k1", types: [String] = peerTypes, whitelist: Set<Bytes>? = nil) -> Verifier {
    Verifier(producerPub: producerPub, kid: bytes(kid), clock: { time }, skew: skew, types: types, whitelist: whitelist)
}
let dialer = who(32)
let listenerId = who(64, "tempus_sentinel", addr: nil)
let third = who(128)

/// One connection: (the dialer's Outcome, the listener's Outcome).
func exchange(_ request: Bytes, dialer d: Identity = dialer, listener l: Identity = listenerId, dialVerifier: Verifier = verifier(),
              listenVerifier: Verifier = verifier(), shuffleLength n: Int = entriesMax, dialTimeout: Double = 5.0,
              handler: @escaping (Request) -> Answer) -> (Outcome, Outcome) {
    let lis = try! Listener(identity: l, verifier: listenVerifier, timeout: 5.0, shuffleLength: n, handler: handler).start()
    let out = dial(lis.address, identity: d, verifier: dialVerifier, request: request, timeout: dialTimeout, shuffleLength: n)
    let served = lis.outcomes(count: 1).first ?? Outcome("timeout", "tls", reason: "the listener reported nothing")
    lis.stop()
    return (out, served)
}

do {
    let l8 = hex(Array(listenerId.peerId.prefix(8))), d8 = hex(Array(dialer.peerId.prefix(8))), t8 = hex(Array(third.peerId.prefix(8)))
    // admission both ways and every request kind
    let entries = [try third.entry(age: 4), try dialer.entry(age: 0)]
    var (out, served) = exchange(try sample(store: "tempus_edge", n: 2)) { rq in
        standardAnswer(rq) { _ in [try! third.entry(age: 3), try! dialer.entry(age: 9), try! third.entry(age: 5)] }
    }
    equal("sample: the dialer's line", out.line, "reply sample_reply entries=[3:\(t8),9:\(d8)] store=tempus_edge peer=\(l8) typ=tempus_sentinel")
    equal("sample: the listener's line", served.line, "served sample n=2 store=tempus_edge sent=reply peer=\(d8) typ=tempus_edge")
    check("a listener with no address of its own advertises the one it bound", String(decoding: out.advert?.addr ?? [], as: UTF8.self).hasPrefix("127.0.0.1:"))
    equal("the listener read the dialer's advert", served.advert, try dialer.descriptor())

    (out, served) = exchange(try shuffle(store: "tempus_edge", entries: entries)) { rq in
        .reply(try! shuffleReply(store: "tempus_edge", entries: rq.frame.entries ?? []))
    }
    equal("shuffle: the reply", out.frame, .shuffleReply(store: "tempus_edge", entries: entries))
    equal("shuffle: the listener's line", served.line, "served shuffle entries=[4:\(t8),0:\(d8)] store=tempus_edge sent=reply peer=\(d8) typ=tempus_edge")

    let call = try callFrame(reqId: bytes("7"), module: "m", function: "ping", args: [1, 2])
    let result = try etfEncode(.map(["t": .atom("result"), "ver": .int(1), "req_id": .binary(bytes("7")), "value": .int(42)]))
    (out, served) = exchange(call) { _ in .reply(result) }
    equal("call: the dialer's line", out.line, "reply result req_id=37 value=42 ver=1 peer=\(l8) typ=tempus_sentinel")
    equal("call: the reply's bytes", out.body, result)
    equal("call: the request's bytes", served.body, call)
    equal("call: the listener's kind", served.frame?.kind, "call")
    // a cast has no reply: the listener closes
    (out, served) = exchange(try callFrame(kind: "cast", reqId: bytes("8"), module: "m", function: "ping", args: [])) { rq in standardAnswer(rq) { _ in [] } }
    equal("cast: the dialer's line", out.line, "closed at=reply peer=\(l8) typ=tempus_sentinel")
    equal("cast: the listener", [served.what, served.frame?.kind ?? "", served.sent], ["served", "cast", "close"])
    // a test-only frame is to a listening client a frame of no tempus/1 kind: closed with no reply
    let tick = try etfEncode(.map(["t": .atom("tick"), "store": .atom("tempus_edge")]))
    (out, served) = exchange(tick) { rq in standardAnswer(rq) { _ in [] } }
    equal("a tick: the dialer", [out.what, out.stage], ["closed", "reply"])
    equal("a tick: the listener", [served.what, served.frame?.kind ?? "", served.sent], ["served", "tick", "close"])

    // each refusal cause a token can carry, detected by the listening verifier; all the dialer sees is a close
    let smp = try sample(store: "tempus_edge", n: 1)
    let cases: [(String, Identity, [String], String)] = [
        ("a token another key signed", who(32, producer: try SigningKey(seed: fixtureSeed(64))), peerTypes, "the signature does not verify"),
        ("expired", who(32, exp: 1400), peerTypes, "the token has expired"),
        ("expired at exactly exp plus skew", who(32, exp: 1490), peerTypes, "the token has expired"),
        ("not yet valid", who(32, nbf: 1600), peerTypes, "the token is not valid yet"),
        ("typ not allowed", dialer, ["tempus_bridge", "tempus_sentinel"], "typ is not allowed"),
    ]
    for (name, d, types, reason) in cases {
        var asked = 0
        (out, served) = exchange(smp, dialer: d, listenVerifier: verifier(types: types)) { _ in
            asked += 1
            return .close
        }
        equal("\(name): the listener", [served.what, served.stage, served.reason], ["refused", "advert", reason])
        equal("\(name): the dialer", out.what, "closed")
        equal("\(name): no request was read", asked, 0)
    }
    for d in [who(32, exp: 1495), who(32, nbf: 1505)] {
        (out, served) = exchange(smp, dialer: d) { rq in standardAnswer(rq) { _ in [] } }
        equal("inside the skew a token is good", [out.what, served.what], ["reply", "served"])
    }
    // the dialing verifier refuses a bad listener, and still reports its advert
    for (l, reason) in [(who(64, "tempus_sentinel", exp: 1400, addr: nil), "the token has expired"),
                        (who(64, "tempus_sentinel", addr: nil, producer: try SigningKey(seed: fixtureSeed(128))), "the signature does not verify")] {
        (out, served) = exchange(smp, listener: l) { _ in .close }
        equal("a bad listener (\(reason)): the dialer", [out.what, out.stage, out.reason], ["refused", "advert", reason])
        equal("a bad listener (\(reason)): its advert is reported", out.advert?.id, l.peerId)
        equal("a bad listener (\(reason)): the listener", served.what, "closed")
    }
    // key_rotated, both ways
    (out, served) = exchange(smp, dialer: who(32, kid: "k0", producer: oldProducer)) { _ in .close }
    equal("key_rotated: the dialer's line", out.line, "key_rotated at=challenge kid=6b31 peer=\(l8) typ=tempus_sentinel")
    equal("key_rotated: the listener", [served.what, served.reason], ["refused", "key_rotated"])
    (out, served) = exchange(smp, dialer: who(32, exp: 1400, kid: "k0", producer: oldProducer)) { _ in .close }
    equal("another kid comes before an expired token", [out.what, hex(out.kid ?? [])], ["key_rotated", "6b31"])
    (out, served) = exchange(smp, listener: who(64, "tempus_sentinel", addr: nil, kid: "k0", producer: oldProducer)) { _ in .close }
    equal("key_rotated the other way: the dialer", [out.what, out.reason], ["refused", "key_rotated"])
    equal("key_rotated the other way: the listener", [served.what, hex(served.kid ?? [])], ["key_rotated", "6b31"])
    // the whitelist rule on a connection
    (out, served) = exchange(smp, dialVerifier: verifier(whitelist: [])) { _ in .close }
    equal("a sentinel that is not listed", [out.what, out.stage, out.reason], ["refused", "advert", "the certificate of a tempus_sentinel is not in the whitelist"])
    (out, served) = exchange(smp, dialVerifier: verifier(whitelist: [sha512(listenerId.certDER)])) { rq in standardAnswer(rq) { _ in [] } }
    equal("a sentinel that is listed", out.what, "reply")
    // replies the dialer refuses
    let forged = who(128, producer: oldProducer)
    let replies: [(String, Bytes, String)] = [
        ("more entries than the shuffle length", try shuffleReply(store: "tempus_edge", entries: try (0..<4).map { try third.entry(age: $0) }), "more entries than the shuffle length"),
        ("an age above 65535", try shuffleReply(store: "tempus_edge", entries: [try third.entry(age: 65536)]), "age is not 0 to 65535"),
        ("bytes that are no term", bytes("hello"), "bad_version"),
        ("an entry another key signed, beside a good one", try sampleReply(store: "tempus_edge", entries: [try dialer.entry(age: 1), try forged.entry(age: 2)]),
         "an entry does not verify: the signature does not verify"),
        ("an entry of another store's type", try sampleReply(store: "tempus_bridge", entries: [try third.entry(age: 1)]), "an entry does not verify: the entry's typ is not the store's"),
    ]
    for (name, reply, reason) in replies {
        (out, served) = exchange(smp, shuffleLength: 3) { _ in .reply(reply) }
        equal("a reply with \(name)", [out.what, out.stage, out.reason], ["refused", "reply", reason])
        equal("a reply with \(name): its bytes are kept", out.body, reply)
    }
    // a shuffle the listener refuses: an entry that does not verify refuses the whole frame, with no reply
    var asked = 0
    (out, served) = exchange(try shuffle(store: "tempus_edge", entries: [try dialer.entry(age: 0), try forged.entry(age: 2)])) { _ in
        asked += 1
        return .close
    }
    equal("a shuffle with a forged entry: the listener", [served.what, served.stage, served.reason], ["refused", "request", "an entry does not verify: the signature does not verify"])
    equal("a shuffle with a forged entry: the dialer", [out.what, out.stage, String(asked)], ["closed", "reply", "0"])
    // an oversize reply is refused from its length
    (out, served) = exchange(smp) { _ in .reply(Bytes(repeating: 0, count: frameMax + 1)) }
    equal("an oversize reply", [out.what, out.stage, out.reason], ["refused", "reply", "a frame above the ceiling"])
    // a listener that closes instead of replying; a listener that is silent past the dialer's bound
    (out, served) = exchange(smp) { _ in .close }
    equal("a close instead of a reply", [out.what, out.stage], ["closed", "reply"])
    (out, served) = exchange(smp, dialTimeout: 0.4) { _ in
        Thread.sleep(forTimeInterval: 1.0)
        return .close
    }
    equal("silence instead of a reply", [out.what, out.stage], ["timeout", "reply"])
    // a listener serves several connections, in order
    let lis = try Listener(identity: listenerId, verifier: verifier(), timeout: 5.0) { rq in standardAnswer(rq) { _ in [] } }.start()
    var lines: [String] = []
    lis.onOutcome = { _, o in lines.append(o.line) }
    for n in [1, 2, 3] as [Int64] {
        equal("connection \(n) is answered", dial(lis.address, identity: dialer, verifier: verifier(), request: try sample(store: "tempus_edge", n: n), timeout: 5.0, nonce: rep("N", 32)).what, "reply")
    }
    equal("three connections in accept order", lis.outcomes(count: 3).map { $0.frame }, [.sample(store: "tempus_edge", n: 1), .sample(store: "tempus_edge", n: 2), .sample(store: "tempus_edge", n: 3)])
    let port = lis.port
    lis.stop()
    equal("each outcome was told once, in order", lines.count, 3)
    // nothing listens there now
    equal("unreachable", dial("127.0.0.1:\(port)", identity: dialer, verifier: verifier(), request: smp, timeout: 2.0).line, "unreachable at=tls")
}

print("tempus-client-tests: \(passed) passed, \(failed) failed")
exit(failed == 0 ? 0 : 1)
