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
import platform_id as P  # noqa: E402


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

    def test_vectors_match_a_live_erl(self):
        if subprocess.run(["which", "erl"], capture_output=True).returncode != 0:
            self.skipTest("erl is not installed")
        for program, path in ((C.erl_program, C.TYPED_VECTORS),):
            out = C.run_erl(program())
            live = dict(line.split(" ") for line in out.splitlines() if not line.startswith("#"))
            _, vec = C.read_vectors(path)
            self.assertEqual(live, vec, path)

    def test_every_expected_reason_is_a_language_atom(self):
        for lf in C.LEAVES.values():
            for c in lf["cases"]:
                if c[0] == "dec" and c[3] != "ok":
                    self.assertIn(c[3], W.REASONS)

    def test_trial_sizes_stay_small(self):
        # silica-defects SD-29: one compiler process runs out of memory on a lot of wide-typed code
        for name in C.LEAVES:
            for dname, idxs in C.leaf_dirs(name):
                self.assertLessEqual(len(idxs), C.CHUNK)

    def check_leaf(self, dname, idxs, cases, vec, name, expect_of, enc_hex):
        path = os.path.join(ROOT, "trials", dname, P.golden_name("main.scout"))
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


NODE = "node b@127.0.0.1\nredial off\npeer a@127.0.0.1 127.0.0.1 7001 dial\n"


def parse_type(text):
    p = W.Parser(W.tokenize(text, "t.wire:1"), "t.wire:1", "m")
    ty = p.parse_type("<value>")
    assert p.peek() is None, p.peek()
    return ty


class NodeKinds(unittest.TestCase):
    """C1 (development-plan/spikes/C1-codec-term-coverage.md 2.1, 2.2, 2.7): atom literal types, tagged tuples, sums and
    optional references, carried on the node path only."""

    def refused(self, ty):
        with self.assertRaises(W.WireError) as cm:
            parse_type(ty)
        return str(cm.exception)

    def test_the_new_kinds_parse(self):
        ty = parse_type("(:a, int64) | (:b, string) | :none")
        self.assertEqual(ty, ("sum", [("tuple", [("atomlit", "a"), ("prim", "int64")]),
                                      ("tuple", [("atomlit", "b"), ("prim", "string")]), ("atomlit", "none")]))
        self.assertEqual(W.canon(ty), "(:a,int64)|(:b,string)|:none")
        self.assertEqual(W.silica(ty), "(:a, int64) | (:b, string) | :none")
        self.assertEqual(W.silica_value(ty), W.silica(ty))
        self.assertEqual((W.depth_of(ty), W.max_depth(ty)), (1, 2))
        self.assertEqual(W.min_size(ty), 6)                       # the atom none: 119, 4, "none"
        self.assertEqual(W.type_atoms(ty), ["a", "b", "none"])
        self.assertFalse(W.has_slot(ty))
        self.assertTrue(W.has_node_kinds(ty))

    def test_a_sum_may_be_anywhere_a_type_may(self):
        ty = parse_type("{ id: int64, st: :on | :off, items: List[(:i, int64) | (:s, string) | :gap] }")
        self.assertEqual(W.silica(ty), "{ id: int64, st: :on | :off, items: List[(:i, int64) | (:s, string) | :gap, mem(normal)] }")
        self.assertEqual(W.canon(ty), "{id:int64,st::on|:off,items:List[(:i,int64)|(:s,string)|:gap]}")
        self.assertEqual((W.depth_of(ty), W.max_depth(ty)), (3, 4))
        self.assertEqual(W.type_atoms(ty), ["on", "off", "i", "s", "gap"])
        ty = parse_type("(:wrap, { k: :a | :b, v: (:some, int64) | :none })")
        self.assertEqual(W.silica(ty), "(:wrap, { k: :a | :b, v: (:some, int64) | :none })")
        self.assertTrue(W.is_tagged(ty))
        # a record variant (at most one), a tag and an atom of one name, a sum as a tuple's first component
        for text in ("(:pt, int64, int64) | { x: int64, y: string } | :nil", "(:ping, string) | :ping",
                     "{ x: int64 } | :nil", "(:a | :b, int64)", ":red | :green | :blue"):
            self.assertEqual(W.silica(parse_type(text)), text)

    def test_an_optional_reference_makes_the_message_carry_its_region(self):
        ty = parse_type("(atom, int64, ref?(L, normal, rec))")
        self.assertEqual(ty, ("tuple", [("prim", "atom"), ("prim", "int64"), ("slot",)]))
        self.assertTrue(W.has_slot(ty))
        self.assertEqual(W.canon(ty), "(atom,int64,ref?(L,normal,rec))")
        self.assertEqual(W.silica_value(ty), "(atom, int64, ref?(L, normal, rec))")
        self.assertEqual(W.silica(ty), "{ r: region(L, normal), v: (atom, int64, ref?(L, normal, rec)) }")
        self.assertEqual(W.depth_of(ty), 1)
        self.assertEqual(W.max_depth(ty), 65)                      # the type's nesting plus 64 (2.7, Q6)
        self.assertEqual(W.min_size(ty), 2 + 2 + 2 + 6)
        ty = parse_type("(:chain, { id: int64, head: (int64, string, ref?(L, normal, rec)) })")
        self.assertEqual(W.silica(ty), "{ r: region(L, normal), v: (:chain, { id: int64, head: (int64, string, ref?(L, normal, rec)) }) }")
        self.assertEqual((W.depth_of(ty), W.max_depth(ty)), (3, 67))
        self.assertEqual(W.type_atoms(ty), ["chain"])
        # a tagged recursive tuple, alone and as a sum variant
        ty = parse_type("(:cons, int64, ref?(L, normal, rec)) | :nil")
        self.assertEqual(W.silica(ty), "{ r: region(L, normal), v: (:cons, int64, ref?(L, normal, rec)) | :nil }")
        self.assertEqual(W.max_depth(ty), 65)

    def test_the_old_kinds_are_as_they_were(self):
        ty = parse_type("{ a: (int64, string), l: List[List[uint8]] }")
        self.assertEqual(ty, ("record", [("a", ("tuple", [("prim", "int64"), ("prim", "string")])),
                                         ("l", ("list", ("list", ("prim", "uint8"))))]))
        self.assertEqual(W.silica(ty), "{ a: (int64, string), l: List[List[uint8, mem(normal)], mem(normal)] }")
        self.assertEqual(W.silica_value(ty), W.silica(ty))
        self.assertEqual(W.canon(ty), "{a:(int64,string),l:List[List[uint8]]}")
        self.assertEqual((W.depth_of(ty), W.max_depth(ty)), (3, 4))
        self.assertFalse(W.has_node_kinds(ty))
        self.assertEqual(W.type_atoms(ty), [])

    def test_refusals(self):
        cases = [
            # two variants with one tag
            ("(:pt, int64, int64) | (:pt, int64) | :none", "<value>", "'(:pt,int64,int64) | ...'",
             "the variants (:pt,int64,int64) and (:pt,int64) have one tag and cannot be told apart on the wire (E2404)"),
            ("(:a, int64) | (:a, string)", "<value>", "'(:a,int64) | ...'", "cannot be told apart on the wire (E2404)"),
            # a primitive, list or untagged tuple variant
            ("int64 | string", "<value>", "'int64 | ...'", "tag it: (:i, int64)"),
            ("{ a: (:n, int64) | string }", "a", "'(:n,int64) | ...'", "the variant 'string' is not an atom literal, a tagged tuple or a record"),
            ("(:n, int64) | List[int64]", "<value>", "'(:n,int64) | ...'", "tag it: (:i, List[int64, mem(normal)])"),
            ("(:n, int64) | (int64, string)", "<value>", "'(:n,int64) | ...'", "tag it: (:i, int64, string)"),
            (":a | :a", "<value>", "':a | ...'", "the variant :a is listed twice"),
            ("{ x: int64 } | { y: int64 }", "<value>", "'{x:int64} | ...'", "a sum has at most one record variant"),
            # the two orders and shapes the pinned compiler's derived codec does not compile
            (":ping | (:pong, int64)", "<value>", "':ping | ...'",
             "a sum that starts with an atom literal cannot have a tagged tuple variant (the compiler's derived decoder does not "
             "compile it, E2005); write a tagged tuple first: (:pong, int64) | :ping"),
            ("(:ping) | (:pong, int64)", "<value>", "'(:ping)'", "a tagged tuple has one or more components after its tag"),
            ("(:ping)", "<value>", "'(:ping)'", "write the atom literal :ping"),
            # an atom literal type anywhere else
            (":a", "<value>", "':a'", "an atom literal type is only a tuple's first component or a sum variant"),
            ("(int64, :tag)", "1", "':tag'", "an atom literal type is only a tuple's first component or a sum variant"),
            ("{ a: :x }", "a", "':x'", "an atom literal type is only"),
            ("List[:x]", "<value>[]", "':x'", "an atom literal type is only"),
            ("(:a, int64) | :9", "<value>", "':9'", "an atom literal type is :name, an identifier"),
            # an optional reference anywhere but a tuple's component
            ("{ a: ref?(L, normal, rec) }", "a", "'ref?(L, normal, rec)'", "an optional reference is only a component of a tuple"),
            ("List[ref?(L, normal, rec)]", "<value>[]", "'ref?(L, normal, rec)'", "only a component of a tuple"),
            ("ref?(L, normal, rec)", "<value>", "'ref?(L, normal, rec)'", "only a component of a tuple"),
            ("(int64, ref?(L, normal, rec) | :a)", "1", "'ref?(L, normal, rec)'", "only a component of a tuple"),
            ("(int64, ref?(L, normal, int64))", "1", "'ref?'", "the one form carried is ref?(L, normal, rec)"),
            ("(int64, ref?(L, atomic, rec))", "1", "'ref?'", "optional references cannot cross the wire"),
        ]
        for ty, path, shown, why in cases:
            text = self.refused(ty)
            self.assertIn(f"t.wire:1: message m: field '{path}' has type {shown}, which is not supported on the wire: ", text, ty)
            self.assertIn(why, text, ty)

    def test_message_names_include_the_atoms_written_in_types(self):
        with tempfile.TemporaryDirectory() as d:
            m = write(d, "x.wire", NODE + "remote val @ a@127.0.0.1 cast (:i, int64) | (:s, string) | :none\n"
                                         "local shape cast { st: :on | :off, v: (:i, int64) | :val }\n")
            # the names in the manifest's order, then the type atoms, sorted, each once (val is a name already)
            self.assertEqual(W.message_names([m]), ["val", "shape", "i", "none", "off", "on", "s"])
            out = os.path.join(d, "out")
            r = run(["generate", "-o", out, m])
            self.assertEqual(r.returncode, 0, r.stderr)
            atoms = read(os.path.join(out, "bees_atoms.silica"))
            for a in ("val", "shape", "i", "s", "on", "off", "none"):
                self.assertIn(f"fn a_{a}() -> atom {{ :{a} }}", atoms)

    def test_the_hand_codec_refuses_the_new_kinds(self):
        """A manifest with no node line is the m1 trials' hand codec (bees_wire_msgs); it does not learn the new kinds."""
        for ty, shown in (("(:a, int64) | :none", "(:a,int64)|:none"), ("(:tag, int64)", "(:tag,int64)"),
                          ("(atom, int64, ref?(L, normal, rec))", "(atom,int64,ref?(L,normal,rec))"),
                          ("{ a: List[:x | :y] }", "{a:List[:x|:y]}")):
            for cmd in ("wire", "generate"):
                with tempfile.TemporaryDirectory() as d:
                    m = write(d, "x.wire", f"message m {ty}\n")
                    out = os.path.join(d, "out")
                    r = run([cmd, "-o", out, m])
                    self.assertNotEqual(r.returncode, 0, ty)
                    self.assertIn(f"x.wire:1: message m: type '{shown}' (an atom literal type, a sum or an optional reference) is "
                                  "carried only on the node path (bees_msgs, the language's derived codec)", r.stderr, ty)
                    self.assertNotIn("Traceback", r.stderr)
                    self.assertFalse(os.path.exists(os.path.join(out, "bees_wire_msgs.silica")))
                    self.assertFalse(os.path.exists(os.path.join(out, "bees_atoms.silica")), "nothing is generated")
            with tempfile.TemporaryDirectory() as d:
                m = write(d, "x.wire", f"message m {ty}\n")
                with self.assertRaises(W.WireError):
                    W.generate_wire(os.path.join(d, "out"), [m])
                self.assertTrue(W.on_node_path([write(d, "y.wire", NODE)]))
                self.assertFalse(W.on_node_path([m]))

    def test_existing_manifests_generate_what_they_did(self):
        """The n1_limits manifest (records of an int64 and of a string, a frame cap of 65536): bees_msgs is, byte for byte,
        the text the generator wrote before the new kinds existed, and no .atoms file is written."""
        leaf = os.path.join(ROOT, "trials", "n1_limits")
        with tempfile.TemporaryDirectory() as d:
            r = run(["generate", "-o", d, "--config", os.path.join(leaf, "bees.config"), os.path.join(leaf, "limits.wire")])
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(sorted(os.listdir(d)), ["bees_atoms.index", "bees_atoms.silica", "bees_msgs.silica", "bees_peers.silica"])
            body = read(os.path.join(d, "bees_msgs.silica")).split("module bees_msgs;\n", 1)[1]
            self.assertEqual(body, N1_LIMITS_MSGS)
            peers = read(os.path.join(d, "bees_peers.silica"))
            self.assertIn("fn dlv_num(msg: string, st: int64) -> (:no_reply, int64) {\n    sequence proc[concurrency]\n"
                          "        r: (:ok, { n: int64 }) | (:rejected, atom) <- bees_msgs@dec_num(msg);\n", peers)
            self.assertIn("fn proxy_str(msg: { s: string }, st: { tx: actor_ref, id: int64 })", peers)
            self.assertNotIn("alloc_region", peers)


N1_LIMITS_MSGS = """use wire_etf;
use bees_atoms;

export validate_named/2;
export enc_num/1;
export dec_num/1;
export enc_str/1;
export dec_str/1;

fn enc_num(msg: { n: int64 }) -> string {
    sequence proc[mem(normal), transport]
        s: string <- encode((:etf), msg)
    produces pure s end
}

fn dec_num(frame: string) -> (:ok, { n: int64 }) | (:rejected, atom) {
    sequence proc[mem(normal), transport]
        r: (:ok, { n: int64 }) | (:rejected, atom) <- decode((:etf), frame)
    produces pure r end
}

fn check_num(frame: string) -> atom {
    sequence
        r: (:ok, { n: int64 }) | (:rejected, atom) <- dec_num(frame);
        why: atom <- case r of { (:ok, _v: { n: int64 }) -> :ok; (:rejected, w: atom) -> w }
    produces pure why end
}

fn enc_str(msg: { s: string }) -> string {
    sequence proc[mem(normal), transport]
        s: string <- encode((:etf), msg)
    produces pure s end
}

fn dec_str(frame: string) -> (:ok, { s: string }) | (:rejected, atom) {
    sequence proc[mem(normal), transport]
        r: (:ok, { s: string }) | (:rejected, atom) <- decode((:etf), frame, { max_bytes: 65536, max_depth: 2, max_length: 65536 })
    produces pure r end
}

fn check_str(frame: string) -> atom {
    sequence
        r: (:ok, { s: string }) | (:rejected, atom) <- dec_str(frame);
        why: atom <- case r of { (:ok, _v: { s: string }) -> :ok; (:rejected, w: atom) -> w }
    produces pure why end
}

fn validate_named(frame: string, name: atom) -> atom { case name == bees_atoms@a_num() of { true -> check_num(frame); false -> case name == bees_atoms@a_str() of { true -> check_str(frame); false -> bees_atoms@a_unknown_atom() } } }
"""


class SplitKinds(unittest.TestCase):
    """C1 (development-plan/spikes/C1-codec-term-coverage.md 2.1, 2.3 to 2.6, 3.5): Map, Set, buf and term in the grammar, what is
    plain, and the SD-37 switch. Silica is not compiled here; trials/c1_codec_map, c1_codec_set, c1_codec_buf, c1_codec_termmsg
    and c1_codec_wide run what these shapes generate."""

    def refused(self, ty):
        with self.assertRaises(W.WireError) as cm:
            parse_type(ty)
        return str(cm.exception)

    def collected(self, d, text, node=True):
        return W.collect([write(d, "x.wire", (NODE if node else "") + text)], warn=False)

    def collect_refused(self, text, node=True):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(W.WireError) as cm:
                self.collected(d, text, node)
        return str(cm.exception)

    def test_a_map(self):
        ty = parse_type("Map[int64, string]")
        self.assertEqual(ty, ("map", ("prim", "int64"), ("prim", "string")))
        self.assertEqual(W.canon(ty), "Map[int64,string]")
        self.assertEqual(W.silica(ty), "List[(int64, string), mem(normal)]")
        self.assertEqual(W.silica_value(ty), W.silica(ty))
        self.assertEqual((W.depth_of(ty), W.max_depth(ty)), (1, 2))
        self.assertEqual(W.min_size(ty), 5)                        # 116 and the four count bytes
        self.assertTrue(W.has_node_kinds(ty))
        self.assertTrue(W.has_special(ty))
        self.assertFalse(W.is_plain(ty))
        self.assertFalse(W.has_region(ty))
        # the value may be a list, a sum, a record, a map or a set; the key a tuple
        ty = parse_type("Map[(int64, int64), Map[string, Set[(:i, int64) | :none]]]")
        self.assertEqual(W.canon(ty), "Map[(int64,int64),Map[string,Set[(:i,int64)|:none]]]")
        self.assertEqual(W.silica(ty), "List[((int64, int64), List[(string, List[(:i, int64) | :none, mem(normal)]), mem(normal)]), mem(normal)]")
        self.assertEqual(W.depth_of(ty), 4)
        self.assertEqual(W.type_atoms(ty), ["i", "none"])

    def test_a_set(self):
        ty = parse_type("Set[(:pt, int64, int64)]")
        self.assertEqual(ty, ("set", ("tuple", [("atomlit", "pt"), ("prim", "int64"), ("prim", "int64")])))
        self.assertEqual(W.canon(ty), "Set[(:pt,int64,int64)]")
        self.assertEqual(W.silica(ty), "List[(:pt, int64, int64), mem(normal)]")
        self.assertEqual((W.depth_of(ty), W.max_depth(ty)), (2, 3))
        self.assertEqual(W.type_atoms(ty), ["pt"])
        self.assertFalse(W.is_plain(ty))

    def test_a_buf_makes_the_message_carry_its_region(self):
        ty = parse_type("buf(L, normal, uint8, 8)")
        self.assertEqual(ty, ("buf", 8))
        self.assertEqual(W.canon(ty), "buf(L,normal,uint8,8)")
        self.assertEqual(W.silica_value(ty), "{ b: buf(L, normal, uint8, 8), n: int64 }")
        self.assertEqual(W.silica(ty), "{ r: region(L, normal), v: { b: buf(L, normal, uint8, 8), n: int64 } }")
        self.assertTrue(W.has_buf(ty) and W.has_region(ty) and not W.has_slot(ty))
        self.assertEqual(W.depth_of(ty), 0)
        ty = parse_type("{ id: int64, data: buf(L, normal, uint8, 65536) }")
        self.assertEqual(W.silica(ty), "{ r: region(L, normal), v: { id: int64, data: { b: buf(L, normal, uint8, 65536), n: int64 } } }")
        self.assertFalse(W.is_plain(ty))

    def test_a_term_is_a_whole_message(self):
        with tempfile.TemporaryDirectory() as d:
            msgs = self.collected(d, "local any cast term\nremote out @ a@127.0.0.1 cast term\n")
        self.assertEqual(msgs, [("any", ("term",)), ("out", ("term",))])
        self.assertEqual(W.silica(("term",)), "List[(int64, int64, float64, string), mem(normal)]")
        self.assertEqual(W.canon(("term",)), "term")
        self.assertFalse(W.is_plain(("term",)))
        self.assertFalse(W.has_region(("term",)))
        self.assertEqual(W.split_uses(msgs), ["use bees_term_wire;"])
        for text in ("{ a: term }", "List[term]", "(int64, term)", "Map[int64, term]"):
            self.assertIn("a dynamic term is only a whole message type", self.refused(text), text)

    def test_grammar_refusals(self):
        why = "holds no Map, Set, buf or optional reference (it is compared for duplicates)"
        self.assertIn("field '<value>{key}' has type 'Map[int64,int64]', which is not supported on the wire: a map's key " + why,
                      self.refused("Map[Map[int64, int64], string]"))
        self.assertIn("field 'a{}' has type 'Set[int64]', which is not supported on the wire: a set's element " + why,
                      self.refused("{ a: Set[Set[int64]] }"))
        self.assertIn("a map's key " + why, self.refused("Map[buf(L, normal, uint8, 4), int64]"))
        self.assertIn("a map is written Map[K, V]", self.refused("{ a: Map }"))
        self.assertIn("a set is written Set[T]", self.refused("Set"))
        one = "the one buffer carried is buf(L, normal, uint8, N), N a literal 1..65536"
        for text in ("buf(L, normal, uint8, 0)", "buf(L, normal, uint8, 65537)", "buf(L, normal, int64, 8)", "buf(L, normal, uint8, 08)",
                     "buf(L, normal, uint8)", "buf"):
            self.assertIn("field '<value>' has type 'buf', which is not supported on the wire: " + one, self.refused(text), text)

    def test_what_the_node_by_node_codec_refuses(self):
        cases = [
            ("(:m, Map[int64, int64]) | :none", "field '<value>' has type '(:m,Map[int64,int64])|:none'",
             "a sum with a variant that holds a Map, a Set or a buf is not carried"),
            ("List[buf(L, normal, uint8, 8)]", "field '<value>[]' has type 'buf(L,normal,uint8,8)'",
             "a buf is carried below tuples and records only, not in a list"),
            ("Map[int64, buf(L, normal, uint8, 8)]", "field '<value>{}' has type 'buf(L,normal,uint8,8)'", "not in a map"),
            ("(int64, Map[int64, int64], ref?(L, normal, rec))", "field '<value>'",
             "a type with an optional reference holds no Map, Set or buf"),
            ("(int64, int64, int64, int64, int64, int64, int64, Set[int64])", "field '<value>'",
             "a tuple that holds a Map, a Set or a buf has at most 7 parts (6 with a buf)"),
            ("{ a: int64, b: int64, c: int64, d: int64, e: int64, f: int64, g: buf(L, normal, uint8, 8) }", "field '<value>'",
             "has at most 6 parts (6 with a buf)"),
            ("{ a: int64, b: int64, c: int64, d: int64, e: int64 } | :none", "field '<value>'",
             "a sum with a variant that holds a record of more than four fields is not carried on the pinned compiler (SD-37)"),
        ]
        for ty, where, why in cases:
            msg = self.collect_refused(f"local m cast {ty}\n")
            self.assertIn("message m: " + where, msg, ty)
            self.assertIn(why, msg, ty)
        # the hand codec of a manifest with no node line carries none of the new kinds
        for ty, path, name in (("{ a: Map[int64, int64] }", "a", "Map[int64,int64]"), ("Set[int64]", "<value>", "Set[int64]"),
                               ("(int64, buf(L, normal, uint8, 8))", "1", "buf(L,normal,uint8,8)"), ("term", "<value>", "term")):
            msg = self.collect_refused(f"message m {ty}\n", node=False)
            self.assertIn(f"message m: field '{path}' has type '{name}', which is not supported on the wire: a Map, a Set, a buf "
                          "and a dynamic term are carried only on the node path (bees_msgs)", msg, ty)

    def test_plain_types_stay_plain(self):
        for text in ("int64", "{ a: (int64, string), l: List[List[uint8]] }", "(:a, int64) | (:b, string) | :none",
                     "(atom, int64, ref?(L, normal, rec))", "{ a: int64, b: int64, c: int64, d: int64 }"):
            self.assertTrue(W.is_plain(parse_type(text)), text)
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(W.split_uses(self.collected(d, "local m cast { a: int64, l: List[string] }\n")), [])
            self.assertEqual(W.split_uses(self.collected(d, "local m cast Map[int64, int64]\n")),
                             ["use bees_etf_scan;", "use bees_codec_kinds;"])

    def test_the_sd37_switch(self):
        wide = parse_type("{ a: int64, b: int64, c: int64, d: int64, e: int64 }")
        inside = parse_type("List[(:w, { a: int64, b: int64, c: int64, d: int64, e: int64 })]")
        self.assertTrue(W.SD37_SPLIT)
        self.assertTrue(W.is_wide(wide))
        self.assertFalse(W.is_plain(wide))
        self.assertFalse(W.is_plain(inside))
        self.assertEqual(W.silica(wide), "{ a: int64, b: int64, c: int64, d: int64, e: int64 }")   # the type itself does not change
        keep = W.SD37_SPLIT
        try:
            W.SD37_SPLIT = False
            self.assertTrue(W.is_plain(wide) and W.is_plain(inside))
            del W.SD37_SPLIT                                        # removing the workaround is deleting the constant
            self.assertTrue(W.is_plain(wide) and W.is_plain(inside))
            self.assertFalse(W.is_plain(parse_type("Map[int64, int64]")))
        finally:
            W.SD37_SPLIT = keep


if __name__ == "__main__":
    unittest.main()
