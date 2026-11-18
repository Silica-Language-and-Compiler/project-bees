#!/usr/bin/env python3
"""Tests of the Python TEMPUS client's codec (C1) against the Silica frame unit (T2).

trials/t2_tempus_frames prints, for every frame and token it writes or mutates, a line `NAME hex HEX` and a line
`NAME read: ...` saying what the Silica reader made of it. This test:
  - builds the same frames and tokens with tools/bees_tempus_client.py from the same inputs and requires the same bytes;
  - reads every HEX of the golden with the Python reader and requires the same verdict (accepted or refused);
  - checks the Python codec on its own (round trips, the canonical key order, real Ed25519 tokens, identities).
It reads every recorded golden (frames.<platform>.scout) and the last run's output when there is one.

    python3 tools/test_bees_tempus_client.py
"""
import glob
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import bees_tempus_client as c  # noqa: E402

LEAF = os.path.join(ROOT, "trials", "t2_tempus_frames")
SHUFFLE_LENGTH = 3

# the fixed values of the trial (trials/t2_tempus_frames/frames.silica)
ADDR = "127.0.0.1:22801"
SIG = b"S" * 64
PUB = b"p" * 32
TOKEN = SIG + c.token_payload("k1", PUB, "tempus_edge", 1000, 2000)


def ident(ch):
    return ch.encode() * 64


def peer(ch, age):
    return (age, c.descriptor(ident(ch), PUB, ADDR, TOKEN))


def built():
    """name -> bytes, for every frame and token of the trial this side builds from the same inputs."""
    three = [peer("A", 0), peer("B", 7), peer("C", 65535)]
    four = [peer("D", 1)] + three
    one = lambda d, age=0: [(age, d)]  # noqa: E731
    return {
        "advert": c.advert(c.descriptor(ident("A"), PUB, ADDR, TOKEN)),
        "pop_challenge": c.challenge(b"N" * 32),
        "pop_response": c.response(b"G" * 64),
        "key_rotated": c.key_rotated("k2"),
        "shuffle": c.shuffle("tempus_edge", three),
        "shuffle_reply": c.shuffle_reply("tempus_bridge", []),
        "sample": c.sample("tempus_sentinel", 2),
        "sample_reply": c.sample_reply("tempus_sentinel", [peer("B", 7)]),
        "tick": c.tick("tempus_edge"),
        "clock": c.clock(1763424000000),
        "done": c.done(),
        "token": TOKEN,
        "token of a bridge": SIG + c.token_payload("producer-key-2026", b"q" * 32, "tempus_bridge", 0, 1763424300),
        "token whose exp is not after nbf": SIG + c.token_payload("k1", PUB, "tempus_edge", 2000, 2000),
        "token with a 31-byte sub": SIG + c.token_payload("k1", b"p" * 31, "tempus_edge", 1000, 2000),
        "token with an empty kid": SIG + c.token_payload("", PUB, "tempus_edge", 1000, 2000),
        "token with a 65-byte kid": SIG + c.token_payload("k" * 65, PUB, "tempus_edge", 1000, 2000),
        "shuffle of four entries, shuffle length three": c.shuffle("tempus_edge", four),
        "entry of age 65536": c.shuffle("tempus_edge", [peer("A", 65536)]),
        "entry with a 63-byte id": c.shuffle("tempus_edge", one(c.descriptor(b"A" * 63, PUB, ADDR, TOKEN))),
        "entry with a 31-byte pub": c.shuffle("tempus_edge", one(c.descriptor(ident("A"), b"p" * 31, ADDR, TOKEN))),
        "entry with a 2-byte addr": c.shuffle("tempus_edge", one(c.descriptor(ident("A"), PUB, "a:", TOKEN))),
        "entry with a 262-byte addr": c.shuffle("tempus_edge", one(c.descriptor(ident("A"), PUB, "a" * 262, TOKEN))),
        "entry with a 64-byte token": c.shuffle("tempus_edge", one(c.descriptor(ident("A"), PUB, ADDR, SIG))),
        "advert with a 65-byte id": c.advert(c.descriptor(b"A" * 65, PUB, ADDR, TOKEN)),
        "sample of 0": c.sample("tempus_edge", 0),
        "sample of 4, shuffle length three": c.sample("tempus_edge", 4),
        "clock before 0": c.clock(-1),
        "nonce of 31 bytes": c.challenge(b"N" * 31),
        "sig of 65 bytes": c.response(b"G" * 65),
        "kid of no bytes": c.key_rotated(""),
    }


def parse(path):
    """name -> (hex bytes, the Silica reader's text) from the trial's output."""
    hexes, reads = {}, {}
    with open(path) as f:
        for line in f:
            line = line.rstrip("\n")
            if " hex " in line:
                name, _, h = line.partition(" hex ")
                hexes[name] = bytes.fromhex(h)
            elif " read: " in line:
                name, _, text = line.partition(" read: ")
                reads[name] = text
    return {name: (hexes[name], reads[name]) for name in hexes}


def outputs():
    out = sorted(glob.glob(os.path.join(LEAF, "frames.*.scout")))
    sout = os.path.join(LEAF, "frames.sout")
    return out + ([sout] if os.path.exists(sout) else [])


def python_accepts(name, data):
    try:
        if name.startswith("token"):
            c.read_token(data)
        else:
            c.read_body(data, SHUFFLE_LENGTH)
        return True, ""
    except c.Refused as why:
        return False, str(why)


class AgainstSilica(unittest.TestCase):
    def test_there_is_output_to_compare(self):
        self.assertTrue(glob.glob(os.path.join(LEAF, "frames.*.scout")), "no golden recorded in trials/t2_tempus_frames")

    def test_same_bytes_from_the_same_inputs(self):
        for path in outputs():
            seen = parse(path)
            for name, data in built().items():
                self.assertIn(name, seen, "%s: no line for %r" % (path, name))
                self.assertEqual(seen[name][0].hex(), data.hex(), "%s: %s" % (path, name))

    def test_same_verdict_on_every_frame(self):
        for path in outputs():
            seen = parse(path)
            self.assertGreaterEqual(len(seen), 44)
            for name, (data, text) in seen.items():
                silica_ok = "refused" not in text
                ok, why = python_accepts(name, data)
                self.assertEqual(ok, silica_ok, "%s: %s: Silica says %r, Python says %r" % (path, name, text, why or "accepted"))

    def test_same_fields_read(self):
        for path in outputs():
            seen = parse(path)
            kind, f = c.read_body(seen["shuffle"][0], SHUFFLE_LENGTH)
            self.assertEqual((kind, f["store"]), ("shuffle", "tempus_edge"))
            self.assertEqual([(age, d[c.Atom("id")][:4]) for age, d in f["entries"]], [(0, b"AAAA"), (7, b"BBBB"), (65535, b"CCCC")])
            self.assertIn("AAAA/64:0 BBBB/64:7 CCCC/64:65535", seen["shuffle"][1])
            fields, payload, sig = c.read_token(seen["token"][0])
            self.assertEqual((fields["kid"], fields["typ"], fields["nbf"], fields["exp"], len(payload)), (b"k1", "tempus_edge", 1000, 2000, 98))
            self.assertIn("kid k1 sub pppp/32 typ 1 nbf 1000 exp 2000 payload of 98 bytes", seen["token"][1])
            self.assertEqual(c.read_body(seen["clock"][0], 3), ("clock", {"ms": 1763424000000}))


class OnItsOwn(unittest.TestCase):
    def test_round_trips(self):
        for name, data in built().items():
            if name.startswith("token"):
                continue
            term = c.etf_decode(data)
            self.assertEqual(c.etf_encode(term), data, name)

    def test_keys_are_written_in_name_order(self):
        body = c.sample("tempus_edge", 1)
        self.assertLess(body.index(b"\x77\x01n"), body.index(b"\x77\x05store"))
        self.assertLess(body.index(b"\x77\x05store"), body.index(b"\x77\x01t"))

    def test_frame_prefix(self):
        self.assertEqual(c.frame(c.done())[:4], (15).to_bytes(4, "big"))

    def test_identity_is_sha512_of_the_key(self):
        import hashlib
        self.assertEqual(c.peer_id(PUB), hashlib.sha512(PUB).digest())
        self.assertEqual(len(c.peer_id(PUB)), 64)

    def test_a_real_token(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives import serialization
        raw = serialization.Encoding.Raw, serialization.PublicFormat.Raw
        producer = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))        # TEST ONLY keys, fixed
        node = Ed25519PrivateKey.from_private_bytes(bytes(range(32, 64)))
        sub = node.public_key().public_bytes(*raw)
        token = c.make_token(producer, "k1", sub, "tempus_edge", 1000, 2000)
        self.assertEqual(len(token), 64 + 98)
        self.assertEqual(token, c.make_token(producer, "k1", sub, "tempus_edge", 1000, 2000), "Ed25519 is deterministic")
        fields = c.verify_token(token, producer.public_key(), "k1", now=1500)
        self.assertEqual(fields["sub"], sub)
        for now, skew, ok in ((999, 0, False), (999, 1, True), (2000, 0, False), (2000, 1, True), (2001, 1, False)):
            if ok:
                c.verify_token(token, producer.public_key(), "k1", now=now, skew=skew)
            else:
                with self.assertRaises(c.Refused):
                    c.verify_token(token, producer.public_key(), "k1", now=now, skew=skew)
        with self.assertRaisesRegex(c.Refused, "key_rotated"):
            c.verify_token(token, producer.public_key(), "k2", now=1500)
        with self.assertRaisesRegex(c.Refused, "producer"):
            c.verify_token(token, node.public_key(), "k1", now=1500)
        flipped = token[:70] + bytes([token[70] ^ 1]) + token[71:]
        with self.assertRaises(c.Refused):
            c.verify_token(flipped, producer.public_key(), "k1", now=1500)
        # proof of possession: the node signs nonce || token
        nonce = b"N" * 32
        node.public_key().verify(node.sign(nonce + token), nonce + token)

    def test_refusals_of_the_reader(self):
        for bad, why in ((b"", "truncated"), (b"\x82", "bad_version"), (c.done() + b"\0", "trailing_bytes"),
                         (b"\x83\x68\x00", "bad_tag"), (b"\x83\x74\x00\x00\x00\x01\x61\x01\x61\x01", "bad_tag")):
            with self.assertRaisesRegex(c.Refused, why):
                c.read_body(bad, 3)
        twice = b"\x83\x74\x00\x00\x00\x02\x77\x01t\x77\x04done\x77\x01t\x77\x04done"
        with self.assertRaisesRegex(c.Refused, "duplicate_field"):
            c.read_body(twice, 3)


if __name__ == "__main__":
    unittest.main()
