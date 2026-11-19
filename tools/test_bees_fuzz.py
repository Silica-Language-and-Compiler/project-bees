#!/usr/bin/env python3
"""Unit tests of the fuzzer's pure parts (tools/bees_fuzz_etf.py, tools/bees_fuzz_gen.py): the generator is deterministic, the ETF
writer and the lenient reader agree with each other and, where erl is installed, with term_to_binary/binary_to_term, and the
oracle models give the verdicts the wire rules ask for. No node is run here (the smoke case is trials/f1_fuzz_wire).
Run: python3 tools/test_bees_fuzz.py   (standard library only)"""
import json
import os
import struct
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bees_fuzz_etf as E  # noqa: E402
import bees_fuzz_gen as G  # noqa: E402

LIVE = [s for s, on in G.SURFACES.items() if on]


def have_erl():
    return subprocess.run(["which", "erl"], capture_output=True).returncode == 0


class Deterministic(unittest.TestCase):
    def test_rng_is_fixed(self):
        # pinned values (splitmix64 over a SHA-256 seed): a change here changes every generated case and every golden id
        r = E.Rng("bees-fuzz", 1, "beam_accept", 0)
        self.assertEqual([r.u64() for _ in range(3)], [11048859690965668515, 12294302096072838315, 415585492181903283])
        self.assertEqual(E.Rng("a").bytes(4), E.Rng("a").bytes(4))
        self.assertNotEqual(E.Rng("a").u64(), E.Rng("b").u64())

    def test_same_case_twice_and_json(self):
        for s in LIVE:
            for i in (0, 1, 7, 500, 99999):
                a, b = G.case(3, s, i), G.case(3, s, i)
                self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))
                self.assertEqual(json.loads(json.dumps(a)), a)
                self.assertEqual(G.case_id(a), G.case_id(b))

    def test_seed_and_index_matter(self):
        for s in LIVE:
            ids = {G.case_id(G.case(seed, s, i)) for seed in (1, 2) for i in range(40)}
            self.assertGreater(len(ids), 70)

    def test_no_clock_or_random_module(self):
        for name in ("bees_fuzz_gen.py", "bees_fuzz_etf.py"):
            with open(os.path.join(HERE, name)) as fh:
                text = fh.read()
            for word in ("import time", "import random", "import os", "import datetime", "import secrets"):
                self.assertNotIn(word, text, name)

    def test_tempus_is_a_documented_hook(self):
        self.assertFalse(G.SURFACES["tempus"])
        with self.assertRaises(ValueError):
            G.case(1, "tempus", 0)

    def test_every_kind_family_appears(self):
        want = {"beam_accept": {"frames", "pre", "name", "auth", "slow"}, "beam_dial": {"epmd", "acceptor", "frames"},
                "trust_plain": {"request", "request_token", "first", "length", "identity", "token", "order", "slow"},
                "trust_tls": {"tls_raw", "request"}, "epmd_register": {"alive2"}, "resolve": {"answer"}}
        for s, fams in want.items():
            seen = {G.case(1, s, i)["kind"].split("/")[0] for i in range(600)}
            self.assertTrue(fams <= seen, (s, fams - seen))


class Etf(unittest.TestCase):
    def test_round_trip(self):
        t = E.emap([(E.atom("n"), E.integer(-5)), (E.atom("op"), E.atom("inc", 118)), (E.atom("x"), E.lst([E.integer(1 << 40), E.binary(b"hi"), E.tup([E.new_float(1.5)])]))])
        v = E.read_term(E.term(t))
        self.assertEqual(v, ("map", [(("atom", "n"), -5), (("atom", "op"), ("atom", "inc")), (("atom", "x"), ("list", [1 << 40, ("bin", b"hi"), ("tuple", [1.5])], None))]))

    def test_reader_refuses(self):
        for b in (b"", b"\x83", b"\x82\x6a", E.term(E.integer(1)) + b"\x00", b"\x83\x6d\xff\xff\xff\xff\x00", b"\x83\x6c\x00\x00\x00\x05\x6a", b"\x83\x74\x00\x00\x00\x01\x61\x01",
                  b"\x83\x77\x05ab", b"\x83\x50\x00\x00\x00\x01\x00", b"\x83" + E.nested(E.Rng("d"), E.DEPTH_CEILING + 5, E.integer(1))):
            with self.assertRaises(E.Bad):
                E.read_term(b)

    def test_integers(self):
        for n in (0, 255, 256, -1, (1 << 31) - 1, -(1 << 31), 1 << 31, (1 << 63) - 1, -(1 << 63), 1 << 64, -(1 << 200)):
            self.assertEqual(E.read_term(E.term(E.integer(n))), n)
            self.assertEqual(E.read_term(E.term(E.big(n, 111))), n)

    def test_depth_and_others(self):
        v = E.read_term(E.term(E.tup([E.lst([E.emap([(E.integer(1), E.pid("a@b", 1))])])])))
        self.assertEqual(E.depth_of(v), 3)
        self.assertTrue(E.has_other(v))
        self.assertIn("a@b", E.atoms_of(v))

    @unittest.skipUnless(have_erl(), "erl is not installed")
    def test_against_erl(self):
        """the writer's bytes are what binary_to_term reads, and term_to_binary's bytes are what the reader reads"""
        t = E.term(E.emap([(E.atom("n"), E.integer(1 << 40)), (E.atom("op"), E.atom("inc"))]))
        expr = "B = <<%s>>, #{n := N, op := Op} = binary_to_term(B), io:format(\"~p ~p~n\", [N, Op])" % ",".join(str(x) for x in t)
        out = subprocess.run(["erl", "-noshell", "-eval", expr + ", halt()."], capture_output=True, text=True, timeout=60).stdout.strip()
        self.assertEqual(out, "1099511627776 inc")
        expr = "io:format(\"~w~n\", [binary_to_list(term_to_binary({6, self(), '', inbox, [1.5, <<1,2>>, #{a => -70000}]}))])"
        out = subprocess.run(["erl", "-noshell", "-eval", expr + ", halt()."], capture_output=True, text=True, timeout=60).stdout.strip()
        v = E.read_term(bytes(json.loads(out)))
        self.assertEqual(v[0], "tuple")
        self.assertEqual(v[1][0], 6)
        self.assertEqual(v[1][1][0], E.UNSUPPORTED)
        self.assertEqual(v[1][4], ("list", [1.5, ("bin", b"\x01\x02"), ("map", [(("atom", "a"), -70000)])], None))


class BeamModel(unittest.TestCase):
    def test_good_frame_is_valid(self):
        m = G.beam_model(G.good_frame("inbox", "inc", 41), "inbox")
        self.assertEqual(m, {"frames": [("valid", "inc", 41)], "violation": False, "partial": False})

    def test_verdicts(self):
        ctl = G.reg_send("inbox")
        def one(pay, c=ctl):
            return G.beam_model(G.dist_frame(c, pay), "inbox")["frames"][0][0]
        self.assertEqual(one(b"\x82" + G.payload("inc", 1)[1:]), "invalid")                      # bad version
        self.assertEqual(one(G.payload("inc", 1)[:-1]), "invalid")                               # truncated
        self.assertEqual(one(G.payload("inc", 1) + b"\x00"), "invalid")                          # trailing byte
        self.assertEqual(one(E.term(E.emap([(E.atom("n"), E.integer(1))]))), "invalid")          # missing key
        self.assertEqual(one(E.term(E.emap([(E.atom("n"), E.integer(1)), (E.atom("op"), E.atom("inc")), (E.atom("x"), E.integer(1))]))), "invalid")
        self.assertEqual(one(E.term(E.emap([(E.atom("n"), E.big(1 << 63)), (E.atom("op"), E.atom("inc"))]))), "invalid")
        self.assertEqual(one(E.term(E.emap([(E.atom("n"), E.integer(1)), (E.atom("op"), E.atom(E.UNKNOWN_PREFIX + "1"))]))), "invalid")
        self.assertEqual(one(E.term(E.emap([(E.atom("op"), E.atom("inc")), (E.atom("n"), E.integer(1))]))), "maybe")    # another key order
        self.assertEqual(one(G.payload("inc", 1), E.term(E.tup([E.integer(19), G.my_pid(), E.atom("")]))), "invalid")     # MONITOR_P delivers nothing
        self.assertEqual(one(G.payload("inc", 1), E.term(E.tup([E.integer(2), E.atom(""), E.pid("bl@localhost", 0)]))), "maybe")

    def test_framing(self):
        good = G.good_frame("inbox", "inc", 1)
        self.assertTrue(G.beam_model(struct.pack(">I", 4097) + good, "inbox")["violation"])
        self.assertEqual(G.beam_model(struct.pack(">I", 4097) + good, "inbox")["frames"], [])
        self.assertTrue(G.beam_model(good[:-1], "inbox")["partial"])
        self.assertEqual(G.beam_model(bytes(8) + good, "inbox")["frames"], [("valid", "inc", 1)])   # ticks are no frames
        self.assertEqual(len(G.beam_model(good + good, "inbox")["frames"]), 2)

    def test_layouts(self):
        self.assertEqual(G.name_msg()[:9], b"N" + bytes([0, 0, 0, 4, 3, 7, 15, 157]))
        self.assertEqual(G.name_msg(challenge=5)[9:13], b"\x00\x00\x00\x05")
        self.assertEqual(len(G.digest(123)), 16)
        self.assertEqual(G.port2_resp(23501)[:4], bytes([119, 0]) + struct.pack(">H", 23501))


class TrustModel(unittest.TestCase):
    def stream(self, req, first=None):
        return G.f4(first or G.t_hello()) + G.f4(req)

    def test_good_request(self):
        m = G.trust_model(self.stream(G.t_request("cast", "demo", "note", [E.integer(7)])))
        self.assertEqual((m["may_execute"], m["verdict"], m["request"]["args"]), (True, "valid", [7]))

    def test_refusals(self):
        note = [E.integer(7)]
        bad = [G.t_request("call", "demo", "note", note, ver=2), G.t_request("call", "demo", "note", note, rid=b""), G.t_request("call", "demo", "note", note, rid=bytes(17)),
               G.t_request("call", "erlang", "apply", note), G.t_request("call", "demo", "secret", []), G.t_request("call", "demo", "note", note, arity=2),
               G.t_request("call", "demo", "note", [E.binary(b"x")]), G.t_request("call", "demo", "echo", [E.binary(bytes(1100))]), G.t_request("call", "demo", "note", note, opts=E.integer(1)),
               G.t_request("hello", "demo", "note", note), G.t_request("call", "demo", "note", note)[:-1], G.t_request("call", "demo", "note", note) + b"\x00",
               G.t_request("call", "demo", "note", note, extra=[(E.atom("x%d" % i), E.integer(i)) for i in range(9)]),
               G.t_request("call", "demo", "note", note, extra=[(E.atom("t"), E.integer(1))]),
               G.t_request("call", "demo", "note", note, opts=E.emap([(E.atom("ok"), G.my_pid())])),
               G.t_request("call", "demo", "note", [E.big(1 << 63)])]
        for b in bad:
            self.assertFalse(G.trust_model(self.stream(b))["may_execute"], b.hex())

    def test_unknown_top_level_key_is_not_certain(self):
        m = G.trust_model(self.stream(G.t_request("cast", "demo", "note", [E.integer(7)], extra=[(E.atom("x1"), E.integer(1))])))
        self.assertEqual((m["may_execute"], m["verdict"]), (True, "maybe"))

    def test_first_frame_and_framing(self):
        req = G.t_request("cast", "demo", "note", [E.integer(7)])
        self.assertFalse(G.trust_model(self.stream(req, G.t_hello(2)))["may_execute"])
        self.assertFalse(G.trust_model(self.stream(req, req))["may_execute"])                    # a request before the token step
        self.assertFalse(G.trust_model(self.stream(req, G.t_token_present(bytes(48))))["may_execute"])
        self.assertTrue(G.trust_model(self.stream(req, G.t_token_present(bytes(48))), live_token=True)["may_execute"])
        self.assertFalse(G.trust_model(G.f4(G.t_hello()) + struct.pack(">I", 4097) + req)["may_execute"])
        self.assertFalse(G.trust_model(G.f4(G.t_hello()) + G.f4(req)[:-1])["may_execute"])


class ResolveModel(unittest.TestCase):
    def test_filter_rules(self):
        self.assertEqual(G.resolve_model("ok 127.0.0.1,10.0.0.8,127.0.0.1 0", False), ("ok", ["127.0.0.1", "10.0.0.8"]))
        self.assertEqual(G.resolve_model("ok 127.0.0.1,10.0.0.8 0", True), ("err", "not_loopback"))
        self.assertEqual(G.resolve_model("ok 0.1.2.3,224.0.0.1,255.255.255.255,240.0.0.1 0", False), ("err", "no_usable_address"))
        self.assertEqual(G.resolve_model("ok 01.2.3.4 0", False), ("maybe",))
        self.assertEqual(G.resolve_model("err nxdomain", False), ("maybe",))
        for q in ("256.1.1.1", "1.2.3", "01.2.3.4", "0.0.0.0", "239.1.1.1", "255.255.255.255", "", "1.2.3.4 ", "::1"):
            self.assertTrue(G.never_usable(q), q)
        self.assertFalse(G.never_usable("223.255.255.255"))

    def test_answers_are_plain_text(self):
        """the answers are compiled in as string literals: nothing that needs an escape"""
        for i in range(3000):
            a = G.case(1, "resolve", i)["answer"]
            self.assertTrue(all(32 <= ord(ch) < 127 and ch not in '"\\' for ch in a), a)


if __name__ == "__main__":
    unittest.main()
