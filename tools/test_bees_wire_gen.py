#!/usr/bin/env python3
"""Tests for the wire half of tools/bees_config.py (tools/bees_wire_gen.py).
Run: python3 tools/test_bees_wire_gen.py   (Python 3, standard library only; Silica is not involved except that the
round-trip trial's recorded output is read and its frame bytes are compared with Python's struct.pack)."""
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


class Digest(unittest.TestCase):
    def test_fnv_vectors(self):
        self.assertEqual(W.fnv1a64(b""), 0xCBF29CE484222325)
        self.assertEqual(W.fnv1a64(b"a"), 0xAF63DC4C8601EC8C)
        self.assertEqual(W.fnv1a64(b"foobar"), 0x85944171F73967E8)

    def test_signed_reading(self):
        self.assertEqual(W.signed64(0), 0)
        self.assertEqual(W.signed64((1 << 63) - 1), (1 << 63) - 1)
        self.assertEqual(W.signed64(1 << 63), -(1 << 63))
        self.assertEqual(W.signed64((1 << 64) - 1), -1)

    def test_schema_text_and_digest(self):
        with tempfile.TemporaryDirectory() as d:
            m = write(d, "x.wire", "message a int64\nmessage b { x: atom, y: List[string] }\n")
            msgs = W.collect([m])
            self.assertEqual(W.schema_text(msgs),
                             "bees-wire 1\nlimits frame=4096 depth=16 list=256 atom=255 string=1024\n"
                             "message 0 a int64\nmessage 1 b {x:atom,y:List[string]}\n")
            self.assertEqual(W.digest(msgs), W.fnv1a64(W.schema_text(msgs).encode()))
            # whitespace and the optional list space do not change the digest; order and names and types do
            m2 = write(d, "y.wire", "message a   int64\nmessage b {x:atom, y: List[string, mem(normal)]}\n")
            self.assertEqual(W.digest(W.collect([m2])), W.digest(msgs))
            for text in ("message b { x: atom, y: List[string] }\nmessage a int64\n",
                         "message a int64\nmessage b { x: atom, y: List[uint8] }\n",
                         "message a int64\nmessage c { x: atom, y: List[string] }\n"):
                m3 = write(d, "z.wire", text)
                self.assertNotEqual(W.digest(W.collect([m3])), W.digest(msgs))

    def test_kind_ids_in_manifest_order_across_files(self):
        with tempfile.TemporaryDirectory() as d:
            a = write(d, "a.wire", "message one int64\nmessage two string\n")
            b = write(d, "b.wire", "message three atom\n")
            out = os.path.join(d, "out")
            self.assertEqual(run(["wire", "-o", out, a, b]).returncode, 0)
            src = read(os.path.join(out, "bees_wire_msgs.silica"))
            for name, idx in (("one", 0), ("two", 1), ("three", 2)):
                self.assertIn(f"fn kind_id_{name}() -> int64 {{ {idx} }}", src)
            self.assertIn("fn kind_count() -> int64 { 3 }", src)
            digest = W.signed64(W.digest(W.collect([a, b])))
            self.assertIn(f"fn schema_digest() -> int64 {{ {digest} }}", src)


class Generated(unittest.TestCase):
    def generate(self, d, text):
        m = write(d, "x.wire", text)
        out = os.path.join(d, "out")
        self.assertEqual(run(["wire", "-o", out, m]).returncode, 0)
        return out

    def test_deterministic(self):
        text = "message a { n: int64, l: List[string] }\nmessage b (atom, float64)\n"
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            o1, o2 = self.generate(d1, text), self.generate(d2, text)
            for f in ("bees_wire_tables.silica", "bees_wire_msgs.silica"):
                self.assertEqual(read(os.path.join(o1, f)), read(os.path.join(o2, f)))

    def test_no_atom_literals_and_tiers(self):
        text = "message a { n: int64, l: List[string], at: atom }\n" + "".join(f"message m{i} int64\n" for i in range(600))
        with tempfile.TemporaryDirectory() as d:
            out = self.generate(d, text)
            units = [os.path.join(out, f) for f in ("bees_wire_tables.silica", "bees_wire_msgs.silica")]
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
            src = read(units[1])
            self.assertIn("fn validate_slot_2(", src)   # 601 kinds are split over three helpers

    def test_limits_match_the_core(self):
        core = read(os.path.join(ROOT, "src", "inter_nodal", "bees_wire.silica"))
        for name, value in (("max_frame", W.MAX_FRAME), ("max_depth", W.MAX_DEPTH), ("max_list", W.MAX_LIST),
                            ("max_atom", W.MAX_ATOM), ("max_string", W.MAX_STRING), ("version", W.WIRE_VERSION)):
            self.assertIn(f"fn {name}() -> int64 {{ {value} }}", core)
        self.assertIn("buf(L, normal, uint8, %d)" % W.MAX_FRAME, core)

    def test_reason_atoms_are_declared(self):
        atoms = [ln.strip() for ln in read(os.path.join(ROOT, "src", "inter_nodal", "bees_wire.atoms")).split("\n")
                 if ln.strip() and not ln.startswith("#")]
        self.assertEqual(sorted(atoms), sorted(W.WIRE_ATOMS))


class GoldenFramesAgainstStruct(unittest.TestCase):
    """The round-trip trial prints the first bytes of every primitive's frame. Python's struct.pack, which shares no
    code with the codec, must give the same bytes. The trial's golden is read, not re-run."""

    LEAF = os.path.join(ROOT, "trials", "m1_wire_types")
    # the round trips are split over six leaves (one compiler process cannot type-check them all, SD-29); they share types.wire
    LEAVES = ["m1_wire_types", "m1_wire_types_signed_a", "m1_wire_types_signed_b", "m1_wire_types_float64",
              "m1_wire_types_float32", "m1_wire_types_text"]

    def golden_text(self):
        paths = [os.path.join(ROOT, "trials", leaf, "main.scout") for leaf in self.LEAVES]
        return "\n".join(read(g) for g in paths) if all(os.path.exists(g) for g in paths) else None

    def test_primitive_frames(self):
        golden = self.golden_text()
        wire = os.path.join(self.LEAF, "types.wire")
        if golden is None or not os.path.exists(wire):
            self.skipTest("trial golden not recorded yet")
        kinds = {name: i for i, (name, _) in enumerate(W.collect([wire]))}
        fmt = {"uint8": ">B", "uint16": ">H", "uint32": ">I", "uint64": ">Q", "int8": ">b", "int16": ">h",
               "int32": ">i", "int64": ">q", "float64": ">d", "float32": ">f"}
        checked = 0
        for line in golden.split("\n"):
            m = re.match(r"^(\S+) (\S+) n=(\d+) bytes=((?: \d+)*) sum=\d+ :ok rt$", line.strip())
            if not m:
                continue
            ty, val, n, bytes_ = m.group(1), m.group(2), int(m.group(3)), [int(x) for x in m.group(4).split()]
            if ty in fmt:
                v = -0.0 if val == "NEG0" else (float(val) if ty.startswith("float") else int(val))
                body = struct.pack(fmt[ty], v)
            elif ty == "boolean":
                body = bytes([1 if val == "true" else 0])
            else:
                continue
            frame = struct.pack(">IBBH", 2 + 2 + len(body), 1, 1, kinds["t_" + ty]) + body
            self.assertEqual(n, len(frame), line)
            self.assertEqual(bytes(bytes_), frame[:24], line)
            checked += 1
        self.assertGreater(checked, 70)

    def test_hello_frame_and_digest(self):
        text = self.golden_text()
        wire = os.path.join(self.LEAF, "types.wire")
        if text is None or not os.path.exists(wire):
            self.skipTest("trial golden not recorded yet")
        digest = W.signed64(W.digest(W.collect([wire])))
        m = re.search(r"^hello alpha n=(\d+) bytes=((?: \d+)*) sum=\d+ digest=(-?\d+) same_digest=true same_node=true code=:ok$",
                      text, re.M)
        self.assertIsNotNone(m)
        self.assertEqual(int(m.group(3)), digest)
        frame = struct.pack(">IBBB", 1 + 1 + 1 + 5 + 8, 1, 0, 5) + b"alpha" + struct.pack(">q", digest)
        self.assertEqual(int(m.group(1)), len(frame))
        self.assertEqual(bytes(int(x) for x in m.group(2).split()), frame[:24])


class DocumentVectors(unittest.TestCase):
    """The worked example of contract/wire-v1.md: the bytes below are the ones the document lists, and the vectors
    trial (trials/m1_wire_vectors) must produce exactly them."""

    HEX = {
        "a": "00 00 00 05 01 01 00 00 ff",
        "b": "00 00 00 0c 01 01 00 01 ff fe 00 00 00 02 68 69",
        "c": "00 00 00 0a 01 01 00 02 00 00 00 02 01 00",
        "hello": "00 00 00 0d 01 00 02 6e 31 bd fe 92 0b 6e 5e 1c 92",
    }
    DIGEST = 0xBDFE920B6E5E1C92

    def test_digest_of_the_example_schema(self):
        leaf = os.path.join(ROOT, "trials", "m1_wire_vectors")
        msgs = W.collect([os.path.join(leaf, "vectors.wire")])
        self.assertEqual(W.digest(msgs), self.DIGEST)
        self.assertEqual(W.schema_text(msgs),
                         "bees-wire 1\nlimits frame=4096 depth=16 list=256 atom=255 string=1024\n"
                         "message 0 a uint8\nmessage 1 b {n:int16,s:string}\nmessage 2 c List[boolean]\n")

    def test_trial_golden_matches_the_document(self):
        golden = os.path.join(ROOT, "trials", "m1_wire_vectors", "main.scout")
        if not os.path.exists(golden):
            self.skipTest("trial golden not recorded yet")
        text = read(golden)
        self.assertIn(str(W.signed64(self.DIGEST)), text.split("\n")[0])
        for name, hexes in self.HEX.items():
            want = " ".join(str(int(x, 16)) for x in hexes.split())
            self.assertIn(f"{name}: {want} \n", text + "\n", name)


if __name__ == "__main__":
    unittest.main()
