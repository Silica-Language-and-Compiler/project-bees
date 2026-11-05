#!/usr/bin/env python3
"""Tests for the wire half of tools/bees_config.py (tools/bees_wire_gen.py) and for the ETF codec's oracle checks.
Run: python3 tools/test_bees_wire_gen.py   (Python 3, standard library only; Silica is not compiled here: the trials'
recorded outputs are read and their frame bytes are compared with the vectors the installed `erl` produced,
tools/etf_oracle/*.vectors, written by tools/etf_cases.py; the vectors themselves are re-checked against a live `erl`
when one is installed).
Run from any directory."""
import os
import re
import struct
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CONFIG = os.path.join(HERE, "bees_config.py")
sys.path.insert(0, HERE)
import bees_wire_gen as W  # noqa: E402
import etf_cases as C  # noqa: E402


def run(args):
    return subprocess.run([sys.executable, CONFIG] + args, capture_output=True, text=True)


def read(path):
    with open(path) as fh:
        return fh.read()


def write(d, name, text):
    p = os.path.join(d, name)
    with open(p, "w") as fh:
        fh.write(text)
    return p


class BuildErrors(unittest.TestCase):
    """A message type the wire cannot carry is a build error that names the message, the field and the type."""

    def build(self, text, cmd="wire"):
        with tempfile.TemporaryDirectory() as d:
            m = write(d, "x.wire", text)
            r = run([cmd, "-o", os.path.join(d, "out"), m])
            written = os.path.exists(os.path.join(d, "out", "bees_wire_msgs.silica"))
            return r, written

    def test_actor_ref_field(self):
        for cmd in ("wire", "generate"):
            r, written = self.build("message ping { n: int64, to: actor_ref }\n", cmd)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("message ping", r.stderr)
            self.assertIn("field 'to'", r.stderr)
            self.assertIn("'actor_ref'", r.stderr)
            self.assertIn("not supported", r.stderr)
            self.assertFalse(written, "nothing is generated for a rejected schema")

    def test_each_unsupported_kind(self):
        cases = [
            ("{ a: ref(L, normal, int64) }", "a", "ref"),
            ("{ a: ref?(L, normal, int64) }", "a", "ref?"),
            ("{ a: region(L, normal) }", "a", "region"),
            ("{ a: buf(L, normal, uint8, 8) }", "a", "buf"),
            ("{ a: fn(x: int64) -> int64 }", "a", "fn"),
            ("{ a: int64 | atom }", "a", "int64 | ..."),
            ("(int64, :tag)", "1", ":"),
            ("{ a: float16 }", "a", "float16"),
            ("{ a: Map }", "a", "Map"),
            ("{ a: widget }", "a", "widget"),
            ("{ a: { b: actor_ref } }", "a.b", "actor_ref"),
            ("List[actor_ref]", "<value>[]", "actor_ref"),
            ("(int64, supervisor_ref)", "1", "supervisor_ref"),
            ("{ a: List[(int64, actor_ref)] }", "a[].1", "actor_ref"),
            ("actor_ref", "<value>", "actor_ref"),
        ]
        for ty, path, name in cases:
            r, _ = self.build(f"message m {ty}\n")
            self.assertNotEqual(r.returncode, 0, ty)
            self.assertIn("message m", r.stderr, ty)
            self.assertIn(f"field '{path}'", r.stderr, ty)
            self.assertIn(f"'{name}", r.stderr, ty)

    def test_syntax_and_names(self):
        for text, msg in [
            ("message m { update: int64 }\n", "Silica keyword"),
            ("message m { a: int64, a: int64 }\n", "listed twice"),
            ("message m ()\n", "not supported"),
            ("message m (int64)\n", "two or more"),
            ("message m List[int64, mem(atomic)]\n", "List[T]"),
            ("message m int64\nmessage m string\n", "already declared"),
            ("message normal int64\n", "not a usable message name"),
            ("msg m int64\n", "cannot read"),
            ("message m int64 extra\n", "unexpected"),
            ("message m { a int64 }\n", "expected ':'"),
        ]:
            r, _ = self.build(text)
            self.assertNotEqual(r.returncode, 0, text)
            self.assertIn(msg, r.stderr, text)

    def test_supported_forms_build(self):
        text = ("# comment\n"
                "message a { op: atom, n: int64, reply_to: atom }\n"
                "message b List[ (int8, uint16, string, boolean) ]\n"
                "message c List[float32, mem(normal)]  # trailing comment\n"
                "message d { x: float64, y: char, z: List[List[uint64]] }\n")
        r, written = self.build(text)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(written)

    def test_too_deep_is_a_warning_not_an_error(self):
        ty = "uint8"
        for _ in range(17):
            ty = "{ d: " + ty + " }"
        r, written = self.build(f"message deep {ty}\n")
        self.assertEqual(r.returncode, 0)
        self.assertIn("too_deep", r.stderr)


class Names(unittest.TestCase):
    def test_message_names_are_dispatch_targets(self):
        with tempfile.TemporaryDirectory() as d:
            a = write(d, "a.wire", "message one int64\nmessage two string\n")
            b = write(d, "b.wire", "message three atom\n")
            out = os.path.join(d, "out")
            self.assertEqual(run(["wire", "-o", out, a, b]).returncode, 0)
            src = read(os.path.join(out, "bees_wire_msgs.silica"))
            for name, idx in (("one", 0), ("two", 1), ("three", 2)):
                self.assertIn(f"fn msg_index_{name}() -> int64 {{ {idx} }}", src)
                self.assertIn(f"case name == bees_atoms@a_{name}() of", src)
            self.assertIn("fn msg_count() -> int64 { 3 }", src)
            self.assertEqual(W.message_names([a, b]), ["one", "two", "three"])

    def test_generate_adds_the_message_names_to_the_atoms(self):
        with tempfile.TemporaryDirectory() as d:
            a = write(d, "a.wire", "message ping int64\n")
            at = write(d, "a.atoms", "extra\n")
            out = os.path.join(d, "out")
            self.assertEqual(run(["generate", "-o", out, a, at]).returncode, 0)
            src = read(os.path.join(out, "bees_atoms.silica"))
            self.assertIn("fn a_ping() -> atom { :ping }", src)
            self.assertIn("fn a_extra() -> atom { :extra }", src)


class Generated(unittest.TestCase):
    def generate(self, d, text):
        m = write(d, "x.wire", text)
        out = os.path.join(d, "out")
        self.assertEqual(run(["wire", "-o", out, m]).returncode, 0)
        return out

    UNITS = ("bees_wire_tables.silica", "bees_wire_ints.silica", "bees_wire_msgs.silica")

    def test_deterministic(self):
        text = "message a { n: int64, l: List[string] }\nmessage b (atom, float64)\n"
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            o1, o2 = self.generate(d1, text), self.generate(d2, text)
            for f in self.UNITS:
                self.assertEqual(read(os.path.join(o1, f)), read(os.path.join(o2, f)))

    def test_no_atom_literals_and_tiers(self):
        text = "message a { n: int64, l: List[string], at: atom }\n" + "".join(f"message m{i} int64\n" for i in range(600))
        with tempfile.TemporaryDirectory() as d:
            out = self.generate(d, text)
            units = [os.path.join(out, f) for f in self.UNITS]
            r = run(["check"] + units)
            self.assertEqual(r.returncode, 0, r.stdout)
            for u in units:
                arms = 0
                for line in read(u).split("\n"):
                    s = line.strip()
                    if s.startswith("case ") and s.endswith(" of {"):
                        arms = 0
                    elif re.match(r"^(-?\d+|\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*') -> ", s):
                        arms += 1
                        self.assertLessEqual(arms, W.TIER, u)
            src = read(units[2])
            self.assertIn("fn validate_slot_2(", src)   # 601 messages are split over three helpers
            self.assertIn("fn index_of_9(", src)         # the name lookup is chunked too (64 per helper)

    def test_records_are_written_in_name_order(self):
        with tempfile.TemporaryDirectory() as d:
            out = self.generate(d, "message r { zeta: int64, alpha: int64, mid: int64 }\n")
            src = read(os.path.join(out, "bees_wire_msgs.silica"))
            enc = [ln for ln in src.split("\n") if ln.startswith("    bees_wire_ints@enc_int64(")][0]
            self.assertLess(enc.index('"alpha"'), enc.index('"mid"'))
            self.assertLess(enc.index('"mid"'), enc.index('"zeta"'))

    def test_limits_match_the_core(self):
        core = read(os.path.join(ROOT, "src", "inter_nodal", "bees_wire.silica"))
        for name, value in (("max_frame", W.MAX_FRAME), ("max_depth", W.MAX_DEPTH), ("max_list", W.MAX_LIST),
                            ("max_atom", W.MAX_ATOM), ("max_string", W.MAX_STRING)):
            self.assertIn(f"fn {name}() -> int64 {{ {value} }}", core)
        self.assertIn("buf(L, normal, uint8, %d)" % W.MAX_FRAME, core)

    def test_reason_atoms_are_declared_and_numbered_alike(self):
        atoms = [ln.strip() for ln in read(os.path.join(ROOT, "src", "inter_nodal", "bees_wire.atoms")).split("\n")
                 if ln.strip() and not ln.startswith("#")]
        self.assertEqual(atoms, W.REASONS)
        core = read(os.path.join(ROOT, "src", "inter_nodal", "bees_wire.silica"))
        for i, r in enumerate(W.REASONS, 1):
            self.assertIn(f"fn reason_{r}() -> int64 {{ {i} }}", core)
            self.assertIn(f"        {i} -> bees_atoms@a_{r}();", core)

    def test_term_unit_is_current(self):
        sys.path.insert(0, HERE)
        import gen_bees_etf
        self.assertEqual(read(os.path.join(ROOT, "src", "inter_nodal", "bees_etf_term.silica")),
                         gen_bees_etf.expand(gen_bees_etf.SRC))


# ------------------------------------------------------------------------------ the oracle

def parse_golden(path):
    """The lines of a trial's golden: {id: ('enc', hex, reason, verdict) | ('dec', reason, verdict) | ('rej', reason)}."""
    got = {}
    for line in read(path).split("\n"):
        m = re.match(r"^(\S+) n=(\d+) hex=([0-9a-f]*) (:\S+) (rt|DIFFERENT)$", line)
        if m:
            got[m.group(1)] = ("enc", m.group(3), m.group(4), m.group(5), int(m.group(2)))
            continue
        m = re.match(r"^(\S+) dec (:\S+) (rt|DIFFERENT|-)$", line)
        if m:
            got[m.group(1)] = ("dec", m.group(2), m.group(3))
            continue
        m = re.match(r"^(\S+) encode rejected (\S+)", line)
        if m:
            got[m.group(1)] = ("rej", m.group(2))
    return got


class Oracle(unittest.TestCase):
    """The vectors come from the installed erl (term_to_binary/1); the trials' recorded output must equal them byte for
    byte, every alternative encoding must decode to the same value, and every hostile frame must be refused with the
    language's reason."""

    def test_vectors_were_written_by_erl(self):
        header, vec = C.read_vectors(C.TYPED_VECTORS)
        self.assertTrue(header.startswith("# OTP "), header)
        self.assertGreater(len(vec), 200)
        header, vec = C.read_vectors(C.TERMS_VECTORS)
        self.assertTrue(header.startswith("# OTP "), header)
        self.assertGreater(len(vec), 80)

    def test_vectors_match_a_live_erl(self):
        if subprocess.run(["which", "erl"], capture_output=True).returncode != 0:
            self.skipTest("erl is not installed")
        for program, path in ((C.erl_program, C.TYPED_VECTORS), (C.erl_term_program, C.TERMS_VECTORS)):
            out = C.run_erl(program())
            live = dict(line.split(" ") for line in out.splitlines() if not line.startswith("#"))
            _, vec = C.read_vectors(path)
            self.assertEqual(live, vec, path)

    def test_every_expected_reason_is_a_language_atom(self):
        for lf in C.LEAVES.values():
            for c in lf["cases"]:
                if c[0] == "dec" and c[3] != "ok":
                    self.assertIn(c[3], W.REASONS)
        for lf in C.TERM_LEAVES.values():
            for c in lf["cases"]:
                if c[0] == "dec" and c[2] != "ok":
                    self.assertIn(c[2], W.REASONS)

    def test_trial_sizes_stay_small(self):
        # silica-defects SD-29: one compiler process runs out of memory on a lot of wide-typed code
        for name in C.LEAVES:
            for dname, idxs in C.leaf_dirs(name):
                self.assertLessEqual(len(idxs), C.CHUNK)
        for name in C.TERM_LEAVES:
            for dname, idxs in C.term_leaf_dirs(name):
                self.assertLessEqual(len(idxs), C.TERM_CHUNK)

    def check_leaf(self, dname, idxs, cases, vec, name, expect_of, enc_hex):
        path = os.path.join(ROOT, "trials", dname, "main.scout")
        if not os.path.exists(path):
            self.skipTest(f"{dname}: golden not recorded yet")
        got = parse_golden(path)
        for k in idxs:
            ident = f"{name}.{k}"
            r = got.get(ident)
            self.assertIsNotNone(r, f"{dname}: no line for {ident}")
            c = cases[k]
            if c[0] == "enc":
                self.assertEqual(r[0], "enc", (ident, r))
                self.assertEqual(r[1], vec[ident], f"{ident}: the frame differs from erl's")
                self.assertEqual(r[4], len(vec[ident]) // 2, ident)
                self.assertEqual((r[2], r[3]), (":ok", "rt"), ident)
            else:
                expect = expect_of(c)
                self.assertEqual(r[0], "dec", (ident, r))
                if expect == "ok":
                    self.assertEqual((r[1], r[2]), (":ok", "rt"), ident)
                else:
                    self.assertEqual(r[1], ":" + expect, ident)

    def test_typed_trials_match_erl(self):
        _, vec = C.read_vectors(C.TYPED_VECTORS)
        for name, lf in C.LEAVES.items():
            for dname, idxs in C.leaf_dirs(name):
                self.check_leaf(dname, idxs, lf["cases"], vec, name, lambda c: c[3], None)

    def test_term_trials_match_erl(self):
        _, vec = C.read_vectors(C.TERMS_VECTORS)
        for name, lf in C.TERM_LEAVES.items():
            for dname, idxs in C.term_leaf_dirs(name):
                self.check_leaf(dname, idxs, lf["cases"], vec, name, lambda c: c[2], None)


class IndependentEncoder(unittest.TestCase):
    """A second, independent writer of ETF (Python's struct) agrees with erl on the scalar types, so the vectors do not
    rest on erl alone for the layouts that matter (integers, floats, atoms, binaries, tuples)."""

    @staticmethod
    def enc_int(v):
        if 0 <= v <= 255:
            return bytes([97, v])
        if -2 ** 31 <= v < 2 ** 31:
            return bytes([98]) + struct.pack(">i", v)
        mag, digits = abs(v), []
        while mag:
            digits.append(mag & 255)
            mag >>= 8
        return bytes([110, len(digits), 1 if v < 0 else 0] + digits)

    def test_integers_floats_text_agree_with_erl(self):
        _, vec = C.read_vectors(C.TYPED_VECTORS)
        checked = 0
        for name, lf in C.LEAVES.items():
            tys = {m: C.parse_type(t) for m, t in lf["msgs"]}
            for k, c in enumerate(lf["cases"]):
                if c[0] != "enc":
                    continue
                ty, v = tys[c[1]], c[2]
                if ty[0] != "prim":
                    continue
                n = ty[1]
                if n in W.INT_TYPES:
                    body = self.enc_int(v)
                elif n == "float64" or n == "float32":
                    body = bytes([70]) + struct.pack(">d", v)
                elif n == "char":
                    body = self.enc_int(ord(v))
                elif n == "boolean":
                    body = bytes([119, 4 if v else 5]) + (b"true" if v else b"false")
                elif n == "atom":
                    body = bytes([119, len(v)]) + v.encode()
                else:
                    t = v.text() if isinstance(v, C.Rep) else v
                    body = bytes([109]) + struct.pack(">I", len(t)) + t.encode()
                self.assertEqual((bytes([131]) + body).hex(), vec[f"{name}.{k}"], (name, k, v))
                checked += 1
        self.assertGreater(checked, 90)


if __name__ == "__main__":
    unittest.main()
