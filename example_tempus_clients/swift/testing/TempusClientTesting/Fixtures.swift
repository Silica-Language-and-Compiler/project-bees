// TEST ONLY: keys, tokens and identities from fixed seeds that are written in this repository. Anyone can reproduce
// them. They exist so that the unit tests and the trial can be repeated; a client never makes or signs a token (the
// producer does), and never takes its key from a fixed seed. This file is a module of its own, TempusClientTesting, so
// that the library (lib/TempusClient) holds nothing of it.
import TempusClient

/// TEST ONLY: the 32 bytes first, first+1, ... (a seed that belongs to nobody).
public func fixtureSeed(_ first: UInt8) -> Bytes { (0..<32).map { first &+ UInt8($0) } }

/// TEST ONLY: a token signed with a producer's private key. The producer's signature is over the payload bytes.
public func makeTestToken(producer: SigningKey, kid: String, sub: Bytes, typ: String, nbf: Int64, exp: Int64) throws -> Bytes {
    let payload = try tokenPayload(kid: Array(kid.utf8), sub: sub, typ: typ, nbf: nbf, exp: exp)
    return try producer.sign(payload) + payload
}

/// TEST ONLY: the identity of seed first..first+31 with a token signed by the test producer (seed 00..1f, the one of
/// tools/bees_tempus_fixtures.py) unless another `producer` is given.
public func fixtureIdentity(_ first: UInt8, typ: String, nbf: Int64, exp: Int64, addr: String? = nil, kid: String = "k1",
                            producer: SigningKey? = nil, certDER: Bytes? = nil) throws -> Identity {
    let key = try SigningKey(seed: fixtureSeed(first))
    let token = try makeTestToken(producer: try producer ?? SigningKey(seed: fixtureSeed(0)), kid: kid, sub: key.pub,
                                  typ: typ, nbf: nbf, exp: exp)
    return try Identity(seed: fixtureSeed(first), token: token, addr: addr, certDER: certDER)
}
