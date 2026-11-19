#!/usr/bin/env python3
"""Tests of tools/bees_term_etf.py (the independent ETF writer and reader) and, through it, of what
trials/c1_codec_term records for the Silica units bees_term_wire and bees_etf_scan.

  - the writer against stock Erlang's term_to_binary/1, and Erlang's binary_to_term/1 reading the writer's bytes
    (skipped when no erl is installed);
  - the fixture hex embedded in trials/c1_codec_term/main.silica against tools/bees_term_fixtures.erl run again
    (skipped without erl);
  - every fixture, canonical-form and refusal line of the trial's golden predicted from the hex in main.silica by the
    Python reader and writer (no erl needed), and the lines of the large and limit cases predicted from frames built here.
"""
import os
import re
import shutil
import struct
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bees_term_etf as E  # noqa: E402
from bees_term_etf import Atom, BitString, Improper, Map, Opaque  # noqa: E402

ROOT = os.path.dirname(HERE)
TRIAL = os.path.join(ROOT, "trials", "c1_codec_term")
MAIN = os.path.join(TRIAL, "main.silica")
GOLDEN = os.path.join(TRIAL, "main.macos_applesilicon.scout")
FIXTURES_ERL = os.path.join(HERE, "bees_term_fixtures.erl")


def find(name):
    found = shutil.which(name)
    if found:
        return found
    fallback = os.path.join("/usr/local/erlang/bin", name)
    return fallback if os.path.exists(fallback) else None


ERL = find("erl")
ESCRIPT = find("escript")

# (an Erlang expression, the same term in the Python model)
TERMS = [
    ("0", 0), ("255", 255), ("256", 256), ("-1", -1), ("2147483647", 2147483647), ("-2147483648", -2147483648),
    ("2147483648", 2147483648), ("-2147483649", -2147483649), ("9223372036854775807", (1 << 63) - 1),
    ("-9223372036854775808", -(1 << 63)), ("9223372036854775808", 1 << 63), ("1 bsl 64", 1 << 64),
    ("(1 bsl 2047) + 12345", (1 << 2047) + 12345), ("-((1 bsl 2047) + 12345)", -((1 << 2047) + 12345)),
    ("(1 bsl 2040) - 1", (1 << 2040) - 1), ("1 bsl 2040", 1 << 2040),
    ("1.5", 1.5), ("-0.0", -0.0), ("0.0", 0.0), ("1.0e300", 1.0e300),
    ("ok", Atom("ok")), ("''", Atom("")), ("true", True), ("list_to_atom([104,233,8594])", Atom("hé→")),
    ("list_to_atom(lists:duplicate(255, $x))", Atom("x" * 255)),
    ("list_to_atom(lists:duplicate(255, 233))", Atom("é" * 255)),
    ("<<>>", b""), ("<<\"abc\">>", b"abc"), ("<<5:3>>", BitString(b"\xa0", 3)), ("<<1,2,3:4>>", BitString(b"\x01\x02\x30", 4)),
    ("{}", ()), ("{a,1,<<\"x\">>}", (Atom("a"), 1, b"x")), ("list_to_tuple(lists:seq(1,300))", tuple(range(1, 301))),
    ("[]", []), ("\"abc\"", [97, 98, 99]), ("[1,a,<<\"b\">>,{c},2.5,[],\"s\"]", [1, Atom("a"), b"b", (Atom("c"),), 2.5, [], [115]]),
    ("[1|2]", Improper([1], 2)), ("[a,b|c]", Improper([Atom("a"), Atom("b")], Atom("c"))),
    ("[256,1000,65536,-1]", [256, 1000, 65536, -1]), ("[104,256]", [104, 256]),
    ("lists:duplicate(65535, 7)", [7] * 65535), ("lists:duplicate(65536, 7)", [7] * 65536),
    ("#{}", Map([])), ("#{a => 1}", Map([(Atom("a"), 1)])), ("#{1 => a, 2 => b, 3 => c}", Map([(1, Atom("a")), (2, Atom("b")), (3, Atom("c"))])),
    ("#{a => 1, b => 2}", Map([(Atom("a"), 1), (Atom("b"), 2)])),
    ("#{1 => a, 1.0 => b}", Map([(1, Atom("a")), (1.0, Atom("b"))])),
    ("#{k => #{1 => [#{}]}, <<\"b\">> => {#{}}}", Map([(Atom("k"), Map([(1, [Map([])])])), (b"b", (Map([]),))])),
    ("sets:from_list([3,1,2])", Map([(1, []), (2, []), (3, [])])),
    ("fun lists:map/2", Opaque("fun", bytes.fromhex("7177056c6973747377036d61706102"))),
]


def erl_eval(expr):
    out = subprocess.run([ERL, "-noshell", "-eval", expr, "-s", "init", "stop"], capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        raise RuntimeError("erl failed: " + out.stderr[-400:])
    return out.stdout.split()


def has_map(v):
    if isinstance(v, Map):
        return True
    if isinstance(v, (tuple, list)):
        return any(has_map(x) for x in v)
    if isinstance(v, Improper):
        return any(has_map(x) for x in v.items) or has_map(v.tail)
    return False


class Model(unittest.TestCase):
    def test_round_trip(self):
        for _, value in TERMS:
            frame = E.encode(value)
            back = E.decode(frame)
            expect = Atom("true") if value is True else value
            self.assertEqual(back, expect)
            self.assertEqual(E.encode(back), frame)
            if expect != [7] * 65536:      # 65538 tokens: over bees_term_wire's limit
                self.assertEqual(E.frame_of_tokens(E.to_tokens(value)), frame)
        with self.assertRaises(E.EtfError):
            E.to_tokens([7] * 65536)

    def test_integer_forms(self):
        self.assertEqual(E.encode(255), bytes.fromhex("8361ff"))
        self.assertEqual(E.encode(256), bytes.fromhex("836200000100"))
        self.assertEqual(E.encode(-1), bytes.fromhex("8362ffffffff"))
        self.assertEqual(E.encode(1 << 31), bytes.fromhex("836e040000000080"))
        self.assertEqual(E.encode(1 << 64)[:4], bytes.fromhex("836e0900"))
        self.assertEqual(E.encode(1 << 2040)[:6], bytes.fromhex("836f00000100"))
        for n in (0, 1, -1, 255, 256, 1 << 31, -(1 << 31) - 1, (1 << 63) - 1, 1 << 63, -(1 << 63), -(1 << 63) - 1, 1 << 200, -(1 << 3000)):
            self.assertEqual(E.decode(E.encode(n)), n)
            kind = E.to_tokens(n)[0][0]
            self.assertEqual(kind, 1 if -(1 << 63) <= n < (1 << 63) else 2)

    def test_tokens(self):
        toks = E.to_tokens((Atom("a"), [1, 2], Improper([1], 2), Map([(1, b"x")]), [300]))
        self.assertEqual([t[0] for t in toks], [7, 4, 10, 8, 1, 1, 11, 1, 5, 8, 1, 9])
        self.assertEqual(E.term_end(toks, 0), len(toks))
        self.assertEqual(E.term_end(toks, 3), 6)
        self.assertEqual(E.term_end(toks, 99), -1)
        self.assertEqual(E.from_tokens(toks), (Atom("a"), [1, 2], Improper([1], 2), Map([(1, b"x")]), [300]))
        # a byte list has two token forms and one byte form
        as_list = [(8, 2, 0.0, b""), (1, 1, 0.0, b""), (1, 2, 0.0, b""), (9, 0, 0.0, b"")]
        self.assertEqual(E.frame_of_tokens(as_list), E.frame_of_tokens([(10, 0, 0.0, b"\x01\x02")]))
        self.assertEqual(E.tokens_text(toks, 3), "t5 a:61 s:0102 +9")

    def test_map_equality_ignores_order(self):
        self.assertEqual(Map([(1, 2), (3, 4)]), Map([(3, 4), (1, 2)]))
        self.assertNotEqual(Map([(1, 2)]), Map([(1.0, 2)]))

    def test_refusals(self):
        cases = [
            ("", "truncated"), ("6100", "bad_version"), ("83", "truncated"), ("8350", "unsupported"), ("83ff", "bad_tag"),
            ("836a00", "trailing_bytes"), ("836cffffffff61016a", "truncated"), ("8374ffffffff6a6a", "too_long"),
            ("83740000000261017701616101770162", "duplicate_field"),
            ("83740000000261016a62000000016a", "duplicate_field"), ("837702c328", "bad_utf8"),
            ("837400000002740000000261016a61026a6a740000000261026a61016a6a", "duplicate_field"),
            ("8374000000027400000001740000000261016a61026a6a6a7400000001740000000261026a61016a6a6a", "duplicate_field"),
            ("8363" + "30" * 31, "unsupported"), ("835200", "unsupported"), ("834d000000010080", "out_of_range"),
            ("834d000000010980", "out_of_range"), ("836e010205", "out_of_range"), ("836c000000006a", "bad_tag"),
            ("83" + "6801" * 65 + "6a", "too_deep"), ("8376" + "0100" + "78" * 256, "too_long"),
        ]
        for hx, reason in cases:
            with self.assertRaises(E.EtfError) as c:
                E.tokens_of_frame(bytes.fromhex(hx))
            self.assertEqual(c.exception.reason, reason, hx[:40])
        self.assertEqual(len(E.tokens_of_frame(bytes.fromhex("83" + "6801" * 64 + "6a"))), 65)
        # two keys that are maps with different pairs are different keys
        self.assertEqual(len(E.tokens_of_frame(bytes.fromhex("837400000002740000000261016a61026a6a740000000261016a61036a6a"))), 13)

    def test_token_limit(self):
        ok = b"\x83l" + struct.pack(">I", 65534) + b"j" * 65535
        self.assertEqual(len(E.tokens_of_frame(ok)), 65536)
        over = b"\x83l" + struct.pack(">I", 65535) + b"j" * 65536
        with self.assertRaises(E.EtfError) as c:
            E.tokens_of_frame(over)
        self.assertEqual(c.exception.reason, "too_long")

    def test_writer_refusals(self):
        bad = [
            [], [(7, 2, 0.0, b""), (1, 1, 0.0, b"")], [(1, 1, 0.0, b""), (1, 2, 0.0, b"")], [(99, 0, 0.0, b"")],
            [(6, 0, 0.0, b"a")], [(6, 9, 0.0, b"a")], [(4, 0, 0.0, b"x" * 256)], [(4, 0, 0.0, b"\xc3\x28")],
            [(11, 2, 0.0, b""), (1, 1, 0.0, b""), (9, 0, 0.0, b""), (1, 1, 0.0, b""), (9, 0, 0.0, b"")],
            [(11, 1025, 0.0, b"")], [(2, 0, 0.0, b"\x01\x00")], [(2, 2, 0.0, b"x")], [(12, 0, 0.0, b"abc")],
            [(8, 0, 0.0, b""), (9, 0, 0.0, b"")],
        ]
        for toks in bad:
            self.assertEqual(E.frame_of_tokens(toks), b"", toks)


@unittest.skipUnless(ERL, "no erl installed")
class AgainstErlang(unittest.TestCase):
    def test_writer_matches_term_to_binary(self):
        exprs = ", ".join(e for e, _ in TERMS)
        lines = erl_eval("lists:foreach(fun(T) -> io:format(\"~s~n\", [binary:encode_hex(term_to_binary(T), lowercase)]) end, [%s])." % exprs)
        self.assertEqual(len(lines), len(TERMS))
        for (expr, value), hx in zip(TERMS, lines):
            theirs = bytes.fromhex(hx)
            if has_map(value):
                # the order of a map's pairs is not stable in erl: compare the terms
                self.assertEqual(E.decode(theirs), E.decode(E.encode(value)), expr)
                self.assertEqual(len(theirs), len(E.encode(value)), expr)
            else:
                self.assertEqual(E.encode(value).hex(), hx, expr)

    def test_binary_to_term_reads_the_writer(self):
        pairs = ", ".join("{\"%s\", %s}" % (E.encode(v).hex(), e) for e, v in TERMS)
        lines = erl_eval("lists:foreach(fun({H, T}) -> io:format(\"~p~n\", [binary_to_term(binary:decode_hex(list_to_binary(H))) =:= T]) end, [%s])." % pairs)
        self.assertEqual(lines, ["true"] * len(TERMS))

    def test_erlang_refuses_a_duplicate_key(self):
        lines = erl_eval("io:format(\"~p~n\", [catch binary_to_term(binary:decode_hex(<<\"83740000000261017701616101770162\">>))]).")
        self.assertIn("badarg", " ".join(lines))

    def test_erlang_agrees_on_keys_that_are_maps(self):
        """the trial's refusal lines about map keys that hold maps: erl refuses (badarg) exactly the frames BEES refuses"""
        with open(MAIN) as f:
            cases = [(l, h) for l, h in re.findall(r'fx\("([^"]+)", "([0-9a-f]*)"\)', f.read()) if " maps " in l or "map values" in l or "map keys" in l]
        self.assertGreaterEqual(len(cases), 6)
        for label, hx in cases:
            lines = erl_eval("io:format(\"~s~n\", [case catch binary_to_term(binary:decode_hex(<<\"%s\">>)) of {'EXIT', _} -> refused; _ -> accepted end])." % hx)
            mine = "refused" if E.trial_line(label, bytes.fromhex(hx)).endswith("rejected :duplicate_field") else "accepted"
            self.assertEqual(lines, [mine], label)

    @unittest.skipUnless(ESCRIPT and os.path.exists(MAIN), "no escript or no trial")
    def test_embedded_fixtures_are_what_erl_writes(self):
        out = subprocess.run([ESCRIPT, FIXTURES_ERL], capture_output=True, text=True, timeout=120)
        self.assertEqual(out.returncode, 0, out.stderr)
        now = dict(line.split() for line in out.stdout.splitlines() if line.strip())
        with open(MAIN) as f:
            embedded = dict(re.findall(r'fx\("([a-z0-9_]+)", "([0-9a-f]*)"\)', f.read()))
        self.assertGreater(len(now), 40)
        for label, hx in now.items():
            self.assertIn(label, embedded)
            mine = bytes.fromhex(embedded[label])
            theirs = bytes.fromhex(hx)
            if has_map(E.decode(theirs)):
                self.assertEqual(E.decode(mine), E.decode(theirs), label)
            else:
                self.assertEqual(mine, theirs, label)


def nested(n):
    return b"\x83" + b"\x68\x01" * n + b"j"


def head4(tag, n):
    return bytes([tag]) + struct.pack(">I", n)


def large_lines(label, frame):
    toks = E.tokens_of_frame(frame)
    again = E.frame_of_tokens(toks)
    return ["%s: tokens %d" % (label, len(toks)), "%s: bytes in %d" % (label, len(frame)), "%s: bytes out %d" % (label, len(again)),
            "%s: bytes %s" % (label, "same" if again == frame else "differs"), "%s: scanner ends at %d" % (label, len(frame))]


def ask_line(label, frame, depth=E.MAX_NESTING, tokens=E.MAX_TOKENS):
    try:
        return "%s: accepted, tokens %d" % (label, len(E.tokens_of_frame(frame, depth, tokens)))
    except E.EtfError as e:
        return "%s: rejected :%s" % (label, e.reason)


def accepted(frame):
    try:
        E.tokens_of_frame(frame)
        return 1
    except E.EtfError:
        return 0


def sweep_lines(label, frame):
    reasons = []
    for k in range(len(frame)):
        try:
            E.tokens_of_frame(frame[:k])
            reasons.append("ok")
        except E.EtfError as e:
            reasons.append(e.reason)
    lines = ["%s: prefixes tried %d" % (label, len(frame)), "%s: prefixes accepted %d" % (label, reasons.count("ok")),
             "%s: prefixes rejected truncated %d" % (label, reasons.count("truncated")),
             "%s: prefixes the scanner refused %d" % (label, len(frame))]
    for add in (1, 128):
        n = sum(accepted(frame[:i] + bytes([(frame[i] + add) % 256]) + frame[i + 1:]) for i in range(len(frame)))
        lines.append("%s: bytes changed by %d, accepted %d" % (label, add, n))
    return lines


@unittest.skipUnless(os.path.exists(MAIN) and os.path.exists(GOLDEN), "no trial golden on this checkout")
class TrialGolden(unittest.TestCase):
    """the Silica units' recorded output, line by line, against the Python reader and writer"""

    @classmethod
    def setUpClass(cls):
        with open(MAIN) as f:
            cls.source = f.read()
        with open(GOLDEN) as f:
            cls.golden = f.read().splitlines()
        cls.fixtures = re.findall(r'fx\("([^"]+)", "([0-9a-f]*)"\)', cls.source)
        cls.by_label = dict(cls.fixtures)

    def test_program_ended_cleanly(self):
        self.assertEqual(self.golden[-1], "exit=0")
        self.assertFalse([l for l in self.golden if "SCAN" in l or "fault" in l])

    def test_fixture_and_refusal_lines(self):
        self.assertGreater(len(self.fixtures), 80)
        for label, hx in self.fixtures:
            self.assertIn(E.trial_line(label, bytes.fromhex(hx)), self.golden)

    def test_erl_fixtures_round_trip_to_the_same_bytes(self):
        part1 = self.golden[self.golden.index("-- 1 fixtures from erl") + 1:self.golden.index("-- 2 forms erl reads and does not write")]
        self.assertGreater(len(part1), 50)
        for line in part1:
            self.assertTrue(line.endswith(" | same"), line)

    def test_canonical_lines(self):
        cases = re.findall(r'canon\("([^"]+)", "([0-9a-f]*)"\)', self.source)
        self.assertGreater(len(cases), 15)
        for label, hx in cases:
            toks = E.tokens_of_frame(bytes.fromhex(hx))
            self.assertIn("%s: %s -> %s" % (label, E.tokens_text(toks), E.frame_of_tokens(toks).hex()), self.golden)

    def test_built_lines(self):
        built = [l for l in self.golden if l.startswith("built ")]
        self.assertGreater(len(built), 25)
        for line in built:
            self.assertTrue(line.endswith(": same"), line)

    def test_encoder_refusals(self):
        lines = [l for l in self.golden if l.startswith("encode refuses ")]
        self.assertGreater(len(lines), 20)
        for line in lines:
            self.assertTrue(line.endswith(": length 0"), line)
        self.assertIn("encode 65 deep: length 0", self.golden)
        self.assertIn("encode 64 deep: length 130", self.golden)
        self.assertIn("encode byte list of 65535 (STRING_EXT): length %d" % len(E.encode([120] * 65535)), self.golden)
        self.assertIn("encode byte list of 65536 (LIST_EXT): length %d" % len(E.encode([120] * 65536)), self.golden)

    def test_large_and_limit_lines(self):
        expect = []
        expect += large_lines("list of 30000 one-tuples", b"\x83" + head4(108, 30000) + b"".join(bytes([104, 1, 97, i % 256]) for i in range(30000)) + b"j")
        expect += large_lines("list of 60000 integers", b"\x83" + head4(108, 60000) + b"".join(head4(98, 1000 + i) for i in range(60000)) + b"j")
        expect += large_lines("60000 small integers spelled as a list (out: STRING_EXT)",
                              b"\x83" + head4(108, 60000) + b"".join(bytes([97, i % 256]) for i in range(60000)) + b"j")
        int_map = lambda n: b"\x83" + head4(116, n) + b"".join(head4(98, 1000 + i) + b"j" for i in range(n))  # noqa: E731
        expect += large_lines("map of 1024 pairs", int_map(1024))
        expect.append(ask_line("map of 1025 pairs", int_map(1025)))
        nils = lambda n: b"\x83" + head4(108, n) + b"j" * (n + 1)  # noqa: E731
        expect.append(ask_line("list of 65534 nils (65536 tokens)", nils(65534)))
        expect.append(ask_line("list of 65535 nils (65537 tokens)", nils(65535)))
        expect.append(ask_line("300 tuples of 255 nils (76802 tokens)", b"\x83" + head4(108, 300) + (bytes([104, 255]) + b"j" * 255) * 300 + b"j"))
        tuple_3 = bytes.fromhex(self.by_label["tuple_3"])
        expect.append(ask_line("tuple_3 within 4 tokens", tuple_3, 64, 4))
        expect.append(ask_line("tuple_3 within 3 tokens", tuple_3, 64, 3))
        expect.append(ask_line("2 deep within depth 2", nested(2), 2, 100))
        expect.append(ask_line("3 deep within depth 2", nested(3), 2, 100))
        expect.append(ask_line("64 deep within depth 1000 (lowered to 64)", nested(64), 1000, 1000000))
        expect.append(ask_line("65 deep within depth 1000 (lowered to 64)", nested(65), 1000, 1000000))
        expect.append(E.trial_line("atom of 256 letters", b"\x83v\x01\x00" + b"x" * 256))
        expect.append(E.trial_line("65 deep", nested(65)))
        expect.append(E.trial_line("64 deep", nested(64)))
        for line in expect:
            self.assertIn(line, self.golden)

    def test_prefix_and_change_sweeps(self):
        for label in ("mixed", "fixed_all"):
            for line in sweep_lines(label, bytes.fromhex(self.by_label[label])):
                self.assertIn(line, self.golden)

    def test_term_end_lines(self):
        toks = E.tokens_of_frame(bytes.fromhex(self.by_label["mixed"]))
        self.assertIn("mixed: tokens %d" % len(toks), self.golden)
        for i, note in ((0, ""), (1, " (an atom)"), (2, " (the map)"), (3, " (its first key)"), (4, " (its first value)"), (9999, "")):
            self.assertIn("mixed: term_end %d%s %d" % (i, note, E.term_end(toks, i)), self.golden)


if __name__ == "__main__":
    unittest.main()
