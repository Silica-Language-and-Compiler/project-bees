#!/usr/bin/env python3
"""Tests of the Python TEMPUS client: its codec (C1) against the Silica frame unit (T2), and its active part (C2).

trials/t2_tempus_frames prints, for every frame and token it writes or mutates, a line `NAME hex HEX` and a line
`NAME read: ...` saying what the Silica reader made of it. This test:
  - builds the same frames and tokens with example_tempus_clients/python/bees_tempus_client.py from the same inputs and requires the same bytes;
  - reads every HEX of the golden with the Python reader and requires the same verdict (accepted or refused);
  - checks the Python codec on its own (round trips, the canonical key order, real Ed25519 tokens, identities).
It reads every recorded golden (frames.<platform>.scout) and the last run's output when there is one.

The active part (class Active) is the Python client against itself over mutual TLS 1.3 on 127.0.0.1, a port the system
assigns: admission both ways and every request kind, each refusal cause, key_rotated, the channel binding, every named
misbehaviour and the TLS refusals. No Silica program runs; keys and certificates are TEST ONLY, from fixed seeds.

    python3 example_tempus_clients/python/test_bees_tempus_client.py
"""
import glob
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))  # bees_tempus_certs, the trial fixtures
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
        "clock of no time": c.clock(-1),
        "clock with a later reading": c.clock(-1, 3000, 1763424000000),
        "clock before -1": c.clock(-2),
        "clock whose wait is 0": c.clock(5, 0, 6),
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


# ---------------------------------------------------------------- C2: the active part, Python client against Python client
# Everything below runs on 127.0.0.1 with a port the system assigns. Keys are TEST ONLY, from fixed seeds: 00.. the
# producer, 60.. the producer's old key, 20.. the dialer, 40.. the listener, 80.. a third peer. The clock is the number
# NOW, never the machine's.
NOW, SKEW = 1500, 10
ADVERTISED = "127.0.0.1:22899"          # the dialer's advertised listen address; nothing dials it in these tests
PRODUCER_PUB = c._raw_public(c.fixture_key(0))
OLD = c.fixture_key(96)
BINDING = "the certificate's key is not the advert's pub"
PROOF = "the proof of possession does not verify"


def who(first, typ="tempus_edge", nbf=1000, exp=2000, addr=None, **more):
    return c.fixture_identity(first, typ, nbf, exp, addr, **more)


DIALER = who(32, addr=ADVERTISED)
LISTENER = who(64, typ="tempus_sentinel")
THIRD = who(128, addr=ADVERTISED)


def verifier(**more):
    return c.Verifier(PRODUCER_PUB, "k1", NOW, SKEW, **more)


def done(request):
    return c.done()


def exchange(request=None, handler=done, dialer=DIALER, listener=LISTENER, trusted=None, dial_verifier=None,
             listen_verifier=None, dial=None, listen=None):
    """One connection: (the dialer's Outcome, the listener's Outcome)."""
    trusted = [dialer.cert_pem] if trusted is None else trusted
    with c.Listener(listener, listen_verifier or verifier(), handler, trusted, timeout=5.0, **(listen or {})) as lis:
        out = c.dial(lis.address, dialer, dial_verifier or verifier(), c.tick("tempus_edge") if request is None else request,
                     **(dial or {}))
        (served,) = lis.outcomes(1)
    return out, served


class Active(unittest.TestCase):
    def test_certificates_are_the_ones_of_the_certificate_tool(self):
        import bees_tempus_certs as certs
        files = certs.files()
        for serial, name in enumerate(sorted(certs.SEEDS), start=1):
            key = c.fixture_key(certs.SEEDS[name])
            self.assertEqual(c.certificate_pem(key, "bees tempus test " + name, serial), files[name + ".pem"], name)
            self.assertEqual(c._key_pem(key), files[name + "-key.pem"], name)

    def test_identity(self):
        self.assertEqual(DIALER.pub, c._raw_public(c.fixture_key(32)))
        self.assertEqual(DIALER.peer_id, c.peer_id(DIALER.pub))
        self.assertEqual(DIALER.cert_pem, who(32).cert_pem, "the certificate is the same on every run")
        from cryptography import x509
        from cryptography.hazmat.primitives import serialization
        der = x509.load_pem_x509_certificate(DIALER.cert_pem).public_bytes(serialization.Encoding.DER)
        self.assertEqual(c.certificate_key(der), DIALER.pub)
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            cert, key = DIALER.write_pem(tmp)
            for path, data in ((cert, DIALER.cert_pem), (key, DIALER.key_pem)):
                with open(path, "rb") as f:
                    self.assertEqual(f.read(), data)
        self.assertEqual(verifier().check_descriptor(DIALER.descriptor())["typ"], "tempus_edge")

    def test_admission_both_ways_and_every_request(self):
        entries = [THIRD.entry(4), DIALER.entry(0)]
        call = c.etf_encode({c.Atom("t"): c.Atom("call"), c.Atom("req_id"): 7, c.Atom("f"): c.Atom("ping")})
        result = c.etf_encode({c.Atom("t"): c.Atom("result"), c.Atom("req_id"): 7, c.Atom("value"): 42})
        cast = c.etf_encode({c.Atom("t"): c.Atom("cast"), c.Atom("f"): c.Atom("ping")})
        cases = [
            (c.shuffle("tempus_edge", entries), c.shuffle_reply("tempus_edge", [LISTENER.entry(0, "127.0.0.1:9")]),
             "shuffle", "shuffle_reply"),
            (c.sample("tempus_bridge", 2), c.sample_reply("tempus_bridge", []), "sample", "sample_reply"),
            (c.tick("tempus_sentinel"), c.done(), "tick", "done"),
            (c.clock(1763424000000), c.done(), "clock", "done"),
            (call, result, "call", "result"),
        ]
        for request, reply, asked, answered in cases:
            seen = []

            def handler(r, reply=reply):
                seen.append(r)
                return reply
            out, served = exchange(request, handler)
            self.assertEqual((out.what, out.stage, out.kind), ("reply", "done", answered), out.line())
            self.assertEqual(out.body, reply)
            self.assertEqual((served.what, served.kind, served.sent), ("served", asked, "reply"), served.line())
            self.assertEqual(served.body, request)
            # each side read and verified the other's advert
            self.assertEqual(out.advert[c.Atom("id")], LISTENER.peer_id)
            self.assertEqual(out.typ, "tempus_sentinel")
            self.assertEqual(served.advert, DIALER.descriptor())
            self.assertEqual(served.typ, "tempus_edge")
            self.assertEqual((seen[0].kind, seen[0].index, seen[0].advert), (asked, 0, DIALER.descriptor()))
            # a listener with no address of its own advertises the one it bound
            self.assertTrue(out.advert[c.Atom("addr")].startswith(b"127.0.0.1:"))
        self.assertEqual(seen[0].fields, {"req_id": 7, "f": "ping"})
        self.assertEqual(out.fields, {"req_id": 7, "value": 42})
        out, served = exchange(c.shuffle("tempus_edge", entries), lambda r: c.shuffle_reply("tempus_edge", r.fields["entries"]))
        self.assertEqual(out.fields, {"store": "tempus_edge", "entries": entries})
        # a cast has no reply: the listener closes
        out, served = exchange(cast, lambda r: None)
        self.assertEqual((out.what, out.stage), ("closed", "reply"), out.line())
        self.assertEqual((served.what, served.kind, served.sent), ("served", "cast", "nothing"), served.line())

    def test_lines_are_deterministic(self):
        lines = set()
        for _ in range(2):
            out, served = exchange(c.sample("tempus_edge", 2), lambda r: c.sample_reply("tempus_edge", [THIRD.entry(3)]))
            lines.add((out.line(), served.line()))
        self.assertEqual(lines, {(
            "reply sample_reply entries=[3:%s] store=tempus_edge peer=%s typ=tempus_sentinel"
            % (THIRD.peer_id[:8].hex(), LISTENER.peer_id[:8].hex()),
            "served sample n=2 store=tempus_edge sent=reply peer=%s typ=tempus_edge" % DIALER.peer_id[:8].hex())})

    def test_a_listener_serves_several_connections_in_order(self):
        with c.Listener(LISTENER, verifier(), done, [DIALER.cert_pem],
                        nonce=lambda i: bytes([i]) * 32) as lis:
            for n in (1, 2, 3):
                self.assertEqual(c.dial(lis.address, DIALER, verifier(), c.sample("tempus_edge", n), nonce=b"N" * 32).what, "reply")
            self.assertEqual([o.fields["n"] for o in lis.outcomes(3)], [1, 2, 3])

    def test_each_refusal_cause_is_detected_by_the_listening_verifier(self):
        me = DIALER
        other_id = c.advert(c.descriptor(THIRD.peer_id, me.pub, ADVERTISED, me.token))
        cases = [
            ("wrong signature", who(32, addr=ADVERTISED, producer=c.fixture_key(64)), None, None, "advert",
             "the signature does not verify"),
            ("expired", who(32, exp=1400, addr=ADVERTISED), None, None, "advert", "the token has expired"),
            ("expired at exactly exp plus skew", who(32, exp=1490, addr=ADVERTISED), None, None, "advert", "the token has expired"),
            ("not yet valid", who(32, nbf=1600, addr=ADVERTISED), None, None, "advert", "the token is not valid yet"),
            ("sub is another key", who(32, addr=ADVERTISED, sub=THIRD.pub), None, None, "advert", "sub is not the peer's key"),
            ("typ not allowed", me, None, ("tempus_bridge", "tempus_sentinel"), "advert", "typ is not allowed"),
            ("id is not the key's hash", me, c.wrong_advert(other_id), None, "advert", "id is not the SHA-512 of pub"),
            ("token cut short", me, c.wrong_advert(c.advert(c.descriptor(me.peer_id, me.pub, ADVERTISED, me.token[:-1]))), None,
             "advert", "truncated"),
            ("proof over another nonce", me, c.wrong_proof_other_nonce(), None, "response", PROOF),
            ("proof by another key", me, c.wrong_proof_other_key(THIRD.key), None, "response", PROOF),
            ("proof of zero bytes", me, c.wrong_proof_bytes(), None, "response", PROOF),
            ("proof of 63 bytes", me, c.wrong_proof_bytes(bytes(63)), None, "response", "sig is not 64 bytes"),
            ("no proof", me, c.no_proof(), None, "response", "tick where pop_response was due"),
        ]
        for name, dialer, mis, types, stage, reason in cases:
            asked = []
            out, served = exchange(dialer=dialer, trusted=[me.cert_pem], dial={"misbehaviour": mis},
                                   handler=lambda r: asked.append(r) or c.done(),
                                   listen_verifier=verifier(types=types) if types else None)
            self.assertEqual((served.what, served.stage, served.reason), ("refused", stage, reason), name + ": " + served.line())
            self.assertEqual(out.what, "closed", name + ": " + out.line())     # closed, no reply: all the wire shows
            self.assertEqual(asked, [], name)
        # inside the skew a token is still (or already) good
        for dialer in (who(32, exp=1495, addr=ADVERTISED), who(32, nbf=1505, addr=ADVERTISED)):
            out, served = exchange(dialer=dialer, trusted=[me.cert_pem])
            self.assertEqual((out.what, served.what), ("reply", "served"))

    def test_the_dialing_verifier_refuses_a_bad_listener(self):
        for listener, mis, stage, reason in (
                (who(64, exp=1400), None, "advert", "the token has expired"),
                (who(64, producer=c.fixture_key(128)), None, "advert", "the signature does not verify"),
                (LISTENER, c.wrong_proof_other_nonce(), "response", PROOF)):
            out, served = exchange(listener=listener, listen={"misbehaviour": mis})
            self.assertEqual((out.what, out.stage, out.reason), ("refused", stage, reason), out.line())
            self.assertEqual(served.what, "closed", served.line())
        self.assertEqual(out.advert[c.Atom("id")], LISTENER.peer_id, "the refused peer's advert is still reported")

    def test_key_rotated(self):
        old = who(32, addr=ADVERTISED, producer=OLD, kid="k0")
        out, served = exchange(dialer=old)
        self.assertEqual((out.what, out.stage, out.kid), ("key_rotated", "challenge", b"k1"), out.line())
        self.assertEqual((served.what, served.reason), ("refused", "key_rotated"), served.line())
        self.assertEqual(out.line(), "key_rotated at=challenge kid=6b31 peer=%s typ=tempus_sentinel" % LISTENER.peer_id[:8].hex())
        # another kid comes before every other fault of the token (here it is expired too)
        out, served = exchange(dialer=who(32, addr=ADVERTISED, producer=OLD, kid="k0", exp=1400))
        self.assertEqual((out.what, out.kid), ("key_rotated", b"k1"))
        # the other way round: the listener's token is the old one and the dialer says so
        out, served = exchange(listener=who(64, producer=OLD, kid="k0"))
        self.assertEqual((out.what, out.reason), ("refused", "key_rotated"), out.line())
        self.assertEqual((served.what, served.kid), ("key_rotated", b"k1"), served.line())

    def test_channel_binding(self):
        # THIRD holds a good certificate and a good token of its own, and presents the DIALER's advert: every field of
        # that advert verifies, so only the binding to the TLS certificate refuses it.
        self.assertEqual(verifier().check_descriptor(DIALER.descriptor())["sub"], DIALER.pub)
        with self.assertRaisesRegex(c.Refused, BINDING):
            verifier().check_descriptor(DIALER.descriptor(), THIRD.pub)
        asked = []
        out, served = exchange(dialer=THIRD, dial={"misbehaviour": c.wrong_advert(DIALER.advert())},
                               handler=lambda r: asked.append(r) or c.done())
        self.assertEqual((served.what, served.stage, served.reason), ("refused", "advert", BINDING), served.line())
        self.assertEqual(served.advert, DIALER.descriptor())
        self.assertEqual((out.what, asked), ("closed", []), out.line())
        # and a listener presenting somebody else's advert is refused by the dialer
        out, served = exchange(listen={"misbehaviour": c.wrong_advert(THIRD.advert())})
        self.assertEqual((out.what, out.stage, out.reason), ("refused", "advert", BINDING), out.line())

    def test_misbehaviour_of_the_dialer(self):
        junk = c.raw_frame(b"hello")
        for name, mis, what, stage, reason in (
                ("closes after the advert", c.close_after_advert(), "closed", "challenge", ""),
                ("closes instead of the proof", c.close_at("response"), "closed", "response", ""),
                ("closes instead of the request", c.close_at("request"), "closed", "request", ""),
                ("a wrong frame for the challenge", c.wrong_frame_at("challenge", c.done()), "refused", "challenge",
                 "done where pop_challenge or key_rotated was due"),
                ("a second advert for the request", c.wrong_frame_at("request", DIALER.advert()), "served", "done", ""),
                ("an unknown key in the request", c.wrong_frame_at("request", c.etf_encode(
                    {c.Atom("t"): c.Atom("tick"), c.Atom("store"): c.Atom("tempus_edge"), c.Atom("x"): 1})), "refused",
                 "request", "unknown_field"),
                ("an oversize advert", c.oversize_frame_at("advert"), "refused", "advert", "a frame above the ceiling"),
                ("an oversize request", c.oversize_frame_at("request"), "refused", "request", "a frame above the ceiling"),
                ("raw bytes for the advert", c.raw_bytes_at("advert", junk), "refused", "advert", "bad_version"),
                ("half a frame, then nothing more", c.raw_bytes_at("request", b"\x00\x00\x00\x10abc") , "timeout", "request", ""),
                ("no advert at all", c.Misbehaviour(skip=("advert",)), "refused", "advert",
                 "pop_challenge where advert was due")):
            with c.Listener(LISTENER, verifier(), done, [DIALER.cert_pem], timeout=0.4) as lis:
                out = c.dial(lis.address, DIALER, verifier(), c.tick("tempus_edge"), misbehaviour=mis, timeout=3.0)
                (served,) = lis.outcomes(1)
            self.assertEqual((served.what, served.stage, served.reason), (what, stage, reason), name + ": " + served.line())
            if what != "served":
                self.assertNotEqual(out.what, "reply", name + ": " + out.line())
        # the close on purpose is said so at the side that made it
        out, served = exchange(dial={"misbehaviour": c.close_after_advert()})
        self.assertEqual((out.what, out.stage, out.reason), ("closed", "challenge", c.ON_PURPOSE), out.line())

    def test_silence(self):
        # a silent dialer: the listener gives up at its timeout and closes, which is what the dialer then sees
        with c.Listener(LISTENER, verifier(), done, [DIALER.cert_pem], timeout=0.3) as lis:
            out = c.dial(lis.address, DIALER, verifier(), c.tick("tempus_edge"), misbehaviour=c.silent_at("response", 5), timeout=8.0)
            (served,) = lis.outcomes(1)
        self.assertEqual((served.what, served.stage), ("timeout", "response"), served.line())
        self.assertEqual((out.what, out.stage, out.reason), ("closed", "response", "silent on purpose"), out.line())
        # a silent listener (during admission, and instead of the reply): the dialer times out
        for listen, handler, stage in (({"misbehaviour": c.silent_at("challenge", 5)}, done, "challenge"),
                                       ({}, lambda r: c.stay_silent(5), "reply")):
            with c.Listener(LISTENER, verifier(), handler, [DIALER.cert_pem], **listen) as lis:
                out = c.dial(lis.address, DIALER, verifier(), c.tick("tempus_edge"), timeout=0.3)
                (served,) = lis.outcomes(1)
            self.assertEqual((out.what, out.stage), ("timeout", stage), out.line())
        self.assertEqual((served.what, served.sent), ("served", "silent"), served.line())

    def test_misbehaviour_of_the_listener(self):
        bad_entry = c.descriptor(THIRD.peer_id, THIRD.pub, ADVERTISED, bytes([THIRD.token[0] ^ 1]) + THIRD.token[1:])
        for name, handler, what, stage, reason in (
                ("closes instead of replying", lambda r: c.CLOSE, "closed", "reply", ""),
                ("raw bytes for the reply", lambda r: c.send_raw(c.raw_frame(b"hello")), "refused", "reply", "bad_version"),
                ("an oversize reply", lambda r: c.send_raw(b"\x00\x02\x00\x01"), "refused", "reply", "a frame above the ceiling"),
                ("more entries than the shuffle length", lambda r: c.shuffle_reply("tempus_edge", [THIRD.entry(i) for i in range(4)]),
                 "refused", "reply", "more entries than the shuffle length"),
                ("an age above 65535", lambda r: c.shuffle_reply("tempus_edge", [THIRD.entry(65536)]), "refused", "reply",
                 "age is not 0 to 65535")):
            out, served = exchange(handler=handler, dial={"shuffle_length": 3})
            self.assertEqual((out.what, out.stage, out.reason), (what, stage, reason), name + ": " + out.line())
        # row 17: one bad entry among good ones travels as the caller built it (judging entries is the reader's own act)
        reply = c.shuffle_reply("tempus_edge", [DIALER.entry(1), (2, bad_entry)])
        out, served = exchange(c.shuffle("tempus_edge", []), lambda r: reply)
        self.assertEqual(out.what, "reply")
        verifier().check_descriptor(out.fields["entries"][0][1])
        with self.assertRaisesRegex(c.Refused, "does not verify"):
            verifier().check_descriptor(out.fields["entries"][1][1])
        # the listener closes after its advert
        out, served = exchange(listen={"misbehaviour": c.close_after_advert()})
        self.assertEqual((out.what, out.stage), ("closed", "challenge"), out.line())

    def test_tls_refusals(self):
        p256 = c.p256_certificate()
        # (the dialer's switches, the certificates the listener trusts) -> what each side sees
        for name, dial, trusted, d_what, d_stage, l_what, l_reason in (
                ("TLS 1.2 only", c.tls12_only(), None, "tls_failed", "tls", "tls_failed", "UNSUPPORTED_PROTOCOL"),
                ("another ALPN", c.other_alpn("h2"), None, "closed", "advert", "refused", "the ALPN protocol is not tempus/1"),
                ("no ALPN", c.other_alpn(None), None, "closed", "advert", "refused", "the ALPN protocol is not tempus/1"),
                ("no client certificate", c.no_certificate(), None, "tls_failed", "advert", "tls_failed",
                 "PEER_DID_NOT_RETURN_A_CERTIFICATE"),
                ("a P-256 certificate", c.p256_cert(), None, "tls_failed", "advert", "tls_failed", "CERTIFICATE_VERIFY_FAILED"),
                ("a P-256 certificate the listener was given", c.p256_cert(), [p256[0]], "closed", "advert", "refused",
                 "the certificate's key is not Ed25519"),
                # the limit of Python's ssl: a good self-signed Ed25519 certificate the listener was not given
                ("an unknown Ed25519 certificate", {}, [THIRD.cert_pem], "tls_failed", "advert", "tls_failed",
                 "CERTIFICATE_VERIFY_FAILED")):
            asked = []
            out, served = exchange(dial=dial, trusted=trusted, handler=lambda r: asked.append(r) or c.done())
            self.assertEqual((out.what, out.stage), (d_what, d_stage), name + ": " + out.line())
            self.assertEqual((served.what, served.stage, served.reason), (l_what, "tls", l_reason), name + ": " + served.line())
            self.assertEqual(asked, [], name)

    def test_an_rsa_certificate_is_refused(self):
        rsa = c.rsa_certificate()
        self.assertEqual(rsa, c.rsa_certificate())          # fixed primes: the same files on every run
        out, served = exchange(dial=c.rsa_cert(), trusted=[rsa[0]])
        self.assertEqual((served.what, served.stage, served.reason), ("refused", "tls", "the certificate's key is not Ed25519"), served.line())
        self.assertEqual((out.what, out.stage), ("closed", "advert"), out.line())

    def test_the_dialer_checks_the_listener_certificate(self):
        issued = c.certificate_pem(LISTENER.key, "bees tempus test issued", 9, issuer_key=c.fixture_key(160), issuer_name="bees tempus test issuer")
        other_name = c.certificate_pem(LISTENER.key, "bees tempus test issued", 9, issuer_name="somebody else")
        for name, cert, reason in (("P-256", c.p256_certificate(), "the certificate's key is not Ed25519"),
                                   ("issued by another key", (issued, LISTENER.key_pem), "the certificate is not self-signed"),
                                   ("issuer name is not the subject", (other_name, LISTENER.key_pem), "the certificate is not self-signed")):
            out, served = exchange(listen={"tls_cert": cert})
            self.assertEqual((out.what, out.stage, out.reason), ("refused", "tls", reason), name + ": " + out.line())
        # and a listener that speaks another ALPN or TLS 1.2
        out, served = exchange(listen={"alpn": "h2"})
        self.assertEqual((out.what, out.stage, out.reason), ("refused", "tls", "the ALPN protocol is not tempus/1"), out.line())
        out, served = exchange(listen={"tls_version": "1.2"})
        self.assertEqual((out.what, out.stage), ("tls_failed", "tls"), out.line())

    def test_unreachable(self):
        import socket
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()                                   # nothing listens there now
        out = c.dial("127.0.0.1:%d" % port, DIALER, verifier(), c.tick("tempus_edge"), timeout=2.0)
        self.assertEqual(out.line(), "unreachable at=tls")

    def test_command_line(self):
        import contextlib
        import io
        with c.Listener(LISTENER, verifier(), lambda r: c.sample_reply("tempus_edge", [THIRD.entry(3)]), [DIALER.cert_pem]) as lis:
            common = ["bees_tempus_client.py", "dial", lis.address, "--seed", DIALER.seed.hex(), "--addr", ADVERTISED,
                      "--producer-pub", PRODUCER_PUB.hex(), "--kid", "k1", "--now", str(NOW), "--skew", str(SKEW)]
            lines = []
            for more in (["--token", DIALER.token.hex(), "sample", "tempus_edge", "2"],
                         ["--test-token", "tempus_edge:1000:2000", "--nonce", "4e" * 32, "sample", "tempus_edge", "2"],
                         ["--test-token", "tempus_edge:1000:1400", "tick", "tempus_edge"]):
                text = io.StringIO()
                with contextlib.redirect_stdout(text):
                    self.assertEqual(c.main(common + more), 0)
                lines.append(text.getvalue())
            lis.outcomes(3)
        peer = "peer=%s typ=tempus_sentinel" % LISTENER.peer_id[:8].hex()
        reply = "reply sample_reply entries=[3:%s] store=tempus_edge %s\n" % (THIRD.peer_id[:8].hex(), peer)
        self.assertEqual(lines, [reply, reply, "closed at=challenge %s\n" % peer])


if __name__ == "__main__":
    unittest.main()
