#!/usr/bin/env python3
"""Unit tests of the configuration packer (tools/bees_pack.py, bees_pack_store.py, bees_pack_gen.py): the on-medium layout
against vectors written by hand from Silica's design, the ETF forms, the record table against the reader's effective values,
and that the generated units in src/config are what the generator writes. The Silica side is tried by trials/d1_store_layout,
d2_store_config and d3_store_node."""
import os
import stat
import struct
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bees_conf            # noqa: E402
import bees_pack as P       # noqa: E402
import bees_pack_gen as G   # noqa: E402
import bees_pack_store as S # noqa: E402
from bees_pack_store import Atom as A   # noqa: E402

ROOT = os.path.dirname(HERE)


class Layout(unittest.TestCase):
    def test_crc32c_check_value(self):
        self.assertEqual(S.crc32c(b"123456789"), 0xE3069283)      # the CRC-32C check value

    def test_numbers(self):
        self.assertEqual((S.BLOCK, S.HEADER, S.ENVELOPE, S.MTU, S.SEGMENT), (4096, 16, 16, 4064, 4060))

    def test_first_record_bytes(self):
        img = S.Image(8192)
        img.append(b"r0")
        data = img.bytes()
        self.assertEqual(data[:12], struct.pack(">QI", 0, 1))
        self.assertEqual(data[12:16], struct.pack(">I", S.crc32c(data[:12])))
        self.assertEqual(data[16:28], struct.pack(">IQ", 2, 0))
        self.assertEqual(data[28:32], struct.pack(">I", S.crc32c(data[16:28] + b"r0")))
        self.assertEqual(data[32:34], b"r0")
        self.assertEqual(data[34:], bytes(8192 - 34))

    def test_a_record_never_spans_blocks(self):
        img = S.Image(16384)
        img.append(b"a" * 30)
        img.append(b"b" * S.MTU)             # does not fit behind the first: opens block 1
        img.append(b"c" * 10)                # block 1 is full: opens block 2
        data = img.bytes()
        self.assertEqual(struct.unpack(">Q", data[4096:4104])[0], 1)
        self.assertEqual(struct.unpack(">Q", data[8192:8200])[0], 2)
        self.assertEqual([len(p) for _, p in S.records(data)], [30, S.MTU, 10])

    def test_full_and_bad_sizes(self):
        img = S.Image(4096)
        img.append(b"x" * S.MTU)
        with self.assertRaises(S.StoreError):
            img.append(b"y")
        for bad in (0, 100, 4097):
            with self.assertRaises(S.StoreError):
                S.Image(bad)
        with self.assertRaises(S.StoreError):
            S.Image(4096).append(b"")
        with self.assertRaises(S.StoreError):
            S.Image(8192).append(b"z" * (S.MTU + 1))

    def test_segments_and_reassembly(self):
        frame = S.stored_frame(7, bytes(range(256)) * 40)      # 10243 bytes: three records
        segs = S.segments(frame)
        self.assertEqual([len(s) for s in segs], [4064, 4064, len(frame) - 2 * 4060 + 4])
        self.assertEqual([struct.unpack(">HH", s[:4]) for s in segs], [(0, 0), (0, 1), (0, 0x8002)])
        img = S.Image(16384)
        for s in segs:
            img.append(s)
        self.assertEqual(S.frames(img.bytes()), [(1, 7, frame[3:])])
        self.assertEqual(struct.unpack(">HH", S.segments(b"abc")[0][:4]), (0, 0x8000))

    def test_scan_stops_like_the_carrier(self):
        img = S.Image(8192)
        for i in range(3):
            img.append(b"r%d" % i)
        data = bytearray(img.bytes())
        data[16 + 18 + 16 + 1] ^= 1                              # a payload byte of record 1
        self.assertEqual([s for s, _ in S.records(bytes(data))], [0])
        self.assertEqual(S.records(bytes(8192)), [])

    def test_a_record_after_a_sync_is_found_at_the_write_unit(self):
        data = bytearray(4096)
        data[:16] = S.block_header(0)
        r0 = S.envelope(0, b"r0")
        data[16:16 + len(r0)] = r0
        r1 = S.envelope(1, b"r1")
        data[512:512 + len(r1)] = r1
        self.assertEqual([s for s, _ in S.records(bytes(data))], [0, 1])


class Etf(unittest.TestCase):
    def test_forms(self):
        self.assertEqual(S.etf(5), bytes([131, 97, 5]))
        self.assertEqual(S.etf(256), bytes([131, 98, 0, 0, 1, 0]))
        self.assertEqual(S.etf(-1), bytes([131, 98, 255, 255, 255, 255]))
        self.assertEqual(S.etf(4294967295), bytes([131, 110, 4, 0, 255, 255, 255, 255]))
        self.assertEqual(S.etf(-(1 << 40)), bytes([131, 110, 6, 1, 0, 0, 0, 0, 0, 1]))
        self.assertEqual(S.etf(True), bytes([131, 119, 4]) + b"true")
        self.assertEqual(S.etf("hi"), bytes([131, 109, 0, 0, 0, 2]) + b"hi")
        self.assertEqual(S.etf([]), bytes([131, 106]))
        self.assertEqual(S.etf([1]), bytes([131, 108, 0, 0, 0, 1, 97, 1, 106]))
        # a record: a map with atom keys, in the order of the field names
        self.assertEqual(S.etf({A("n"): 42, A("name"): "alpha"}), S.etf({A("name"): "alpha", A("n"): 42}))
        self.assertEqual(S.etf({A("name"): "alpha", A("n"): 42}).hex(), "83740000000277016e612a77046e616d656d00000005616c706861")
        with self.assertRaises(S.StoreError):
            S.etf(1 << 70)

    def test_show_decoder_reads_what_the_packer_writes(self):
        v = {A("a"): -70000, A("b"): [{A("x"): b"y"}], A("c"): False, A("d"): 1 << 40}
        got, end = P._decode(S.etf(v), 1)
        self.assertEqual(got, {"a": -70000, "b": [{"x": b"y"}], "c": False, "d": 1 << 40})
        self.assertEqual(end, len(S.etf(v)))


BEAM = """[ {mode, beam}, {node, [{name, "a@localhost"}]},
  {beam, [{transport, tcp}, {auth, cookie}, {cookie_file, "cookie"}, {listen_address, "127.0.0.1"}, {listen_port, 23410}, {epmd, none}]} ].
"""
WIRE = "node a@localhost\npeer b@localhost 127.0.0.1 23410 listen\n"
SECRET = "unit-test-cookie-value"


class Pack(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name
        for name, text, mode in (("bees.config", BEAM, 0o644), ("node.wire", WIRE, 0o644), ("cookie", SECRET + "\n", 0o600)):
            p = os.path.join(self.d, name)
            with open(p, "w") as f:
                f.write(text)
            os.chmod(p, mode)

    def tearDown(self):
        self.tmp.cleanup()

    def pack(self, capacity=16384):
        out = os.path.join(self.d, "node.sildat")
        return out, P.pack(os.path.join(self.d, "bees.config"), [os.path.join(self.d, "node.wire")], capacity, out)

    def test_pack_and_show(self):
        out, (conf, recs) = self.pack()
        self.assertEqual(stat.S_IMODE(os.stat(out).st_mode), 0o600)
        self.assertEqual(os.path.getsize(out), 16384)
        self.assertEqual(recs[0], (1, {"kind": "bees.config", "version": 1, "mode": "beam", "frames": len(recs)}))
        lines = P.show(out)
        self.assertIn('node.name = "a@localhost"', lines)
        self.assertIn('net.listener = "listen:23410"', lines)
        self.assertIn(f"auth.cookie = (secret, {len(SECRET)} bytes)", lines)
        self.assertFalse(any(SECRET in line for line in lines))
        with open(out, "rb") as f:
            self.assertIn(SECRET.encode(), f.read())             # the secret travels in the store, and only there

    def test_every_record_has_at_most_four_fields(self):
        def walk(fields):
            self.assertLessEqual(len(fields), 4)                 # SD-37 on the pinned compiler
            self.assertEqual([f[0] for f in fields], sorted(f[0] for f in fields))
            for f in fields:
                if f[1] in ("rec", "list"):
                    walk(f[4])
        for mode in P.GROUPS:
            schemas = [g[1] for g in P.GROUPS[mode]]
            self.assertEqual(len(schemas), len(set(schemas)))
            for g in P.GROUPS[mode]:
                walk(g[3])

    def test_refusals_are_the_readers_line(self):
        with open(os.path.join(self.d, "bees.config"), "w") as f:
            f.write(BEAM.replace("23410}", "99999}"))
        with self.assertRaises(bees_conf.ConfError) as e:
            self.pack()
        self.assertTrue(e.exception.text.startswith("bees.config:2: beam.listen_port:"))

    def test_loose_cookie_is_refused(self):
        os.chmod(os.path.join(self.d, "cookie"), 0o644)
        with self.assertRaises(bees_conf.ConfError):
            self.pack()

    def test_capacity(self):
        with self.assertRaises(S.StoreError):
            self.pack(capacity=5000)
        self.assertEqual(P.main(["bees_pack.py", "pack", "--config", os.path.join(self.d, "bees.config"), "-o", os.path.join(self.d, "x.sildat")]), 2)

    def test_table_check_refuses_what_the_silica_reader_refuses(self):
        _, (conf, recs) = self.pack()
        bad = dict(recs[2][1], listen_port=70000)
        with self.assertRaises(P.PackError):
            P._check("beam.net", P.by_schema("beam")[10][3], bad)


class Generated(unittest.TestCase):
    def test_src_config_is_what_the_generator_writes(self):
        for name, text in G.files().items():
            with open(os.path.join(ROOT, "src", "config", name), encoding="utf-8") as f:
                self.assertEqual(f.read(), text, f"src/config/{name}: run tools/bees_pack_gen.py write")

    def test_every_decode_carries_the_one_literal_ceiling(self):
        import re
        for name, text in G.files().items():
            for m in re.finditer(r"decode\(\(:etf\), e, \{([^}]*)\}\)", text):
                self.assertIn("max_bytes: 4294967295", m.group(1))       # D47
                self.assertIn("max_length: 4294967295", m.group(1))
            if name.startswith("bees_cfg_") and name.endswith(".silica"):
                self.assertGreater(text.count("decode((:etf)"), 4)

    def test_no_secret_is_printed_by_show(self):
        for mode in ("beam", "trust"):
            text = G.Unit(mode).plain()
            secrets = [f[0] for g in P.GROUPS[mode] for f in g[3] if f[1] == "secret"]
            self.assertTrue(secrets)
            for s in secrets:
                self.assertNotRegex(text, rf'say_(s|len|n)\("[a-z.\[\]]*\.{s} = "')

    def test_example_root_is_current(self):
        d = os.path.join(ROOT, "examples", "store_node")
        with open(os.path.join(d, "dangerous_store_node.silica.in"), encoding="utf-8") as f:
            want = f.read().replace("@MODE@", "beam").replace("@CFG@", G.Unit("beam").cfg()).replace("@ERR@", G.ERR)
        with open(os.path.join(d, "dangerous_store_node.silica"), encoding="utf-8") as f:
            self.assertEqual(f.read(), want)


class StoreAtoms(unittest.TestCase):
    """Owner ruling 2026-11-18: the store carrier's own vocabulary is on the language list of the D30 atoms check."""
    # transport_serialization_design.md 6.8.1, 6.8.2, 6.8.3, 6.8.9
    VOCABULARY = {"store", "memory", "backing", "sd_blocks", "flash_region", "ring", "stop", "trim", "storage", "sync", "read",
                  "read_stop", "log", "synced", "rx_end", "read_failed", "full", "empty", "trimmed", "beyond_tail", "busy",
                  "corrupt", "medium", "in_use", "mismatch"}

    def test_the_vocabulary_is_on_the_language_list(self):
        import bees_config
        self.assertLessEqual(self.VOCABULARY, bees_config.FIXED_ATOMS)

    def test_every_atom_of_the_store_units_passes_the_check(self):
        import bees_config
        units = [os.path.join(ROOT, "src", "config", n) for n in G.files() if n.endswith(".silica")]
        units.append(os.path.join(ROOT, "examples", "store_node", "dangerous_store_node.silica"))
        for u in units:
            with open(u, encoding="utf-8") as f:
                text = "\n".join(line.split("//")[0] for line in f)
            for m in bees_config.ATOM_RE.finditer(text):
                self.assertIn(m.group(1), bees_config.FIXED_ATOMS, f"{os.path.basename(u)}: :{m.group(1)}")

    def test_the_carriers_own_atoms_in_silica_are_covered(self):
        # what Silica's backing carrier sends its owner or takes from it; its private self-messages are not vocabulary
        src = os.path.join(ROOT, "..", "silica", "compiler", "stdlib", "dangerous_store_backing_carrier.silica")
        if not os.path.exists(src):
            self.skipTest("no Silica checkout beside the project")
        import bees_config
        import re
        with open(src, encoding="utf-8") as f:
            found = set(re.findall(r"(?<![A-Za-z0-9_]):([a-z_]+)", "\n".join(line.split("//")[0] for line in f)))
        private = {"drain", "recover", "step", "record", "end", "loopback"}
        self.assertEqual(found - bees_config.FIXED_ATOMS - private, set())


if __name__ == "__main__":
    unittest.main()
