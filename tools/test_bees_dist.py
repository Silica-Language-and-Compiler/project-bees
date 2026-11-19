#!/usr/bin/env python3
"""Tests for the distribution half of tools/bees_config.py (tools/bees_dist_gen.py, milestone M3) and for the byte layouts
of the distribution protocol that the trial `trials/m3_dist_frames` printed (its recorded output is read; Silica is not
compiled here). The layouts are checked against the installed OTP 28 when it is there: the mandatory flag set against
kernel's dist.hrl, the control message and the payload against `term_to_binary`, the handshake messages against an
independent Python writer of dist_util's `<<$N, Flags:64, Creation:32, NameLen:16>>`.
Run: python3 tools/test_bees_dist.py   (standard library only)"""
import glob
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
import platform_id as P  # noqa: E402
GOLDEN = os.path.join(ROOT, "trials", "m3_dist_frames", P.golden_name("main.scout"))
FLAGS = 0x4_0307_0F94


def run(args):
    return subprocess.run([sys.executable, CONFIG] + args, capture_output=True, text=True)


def have_erl():
    return subprocess.run(["which", "erl"], capture_output=True).returncode == 0


def erl(expr):
    r = subprocess.run(["erl", "-noshell", "-eval", expr + ", halt()."], capture_output=True, text=True, timeout=60)
    return r.stdout.strip()


def golden():
    out = {}
    with open(GOLDEN) as fh:
        for line in fh:
            line = line.rstrip("\n")
            for label in ("n_init", "s_ok", "n_acc", "payload", "reg_send"):
                if line.startswith(label + " ") and not re.match(label + r" (parse|peer|as|accepted|validates|decoded|local|from)", line):
                    out[label] = line.split(" ", 1)[1]
    return out


NODE = "node b@127.0.0.1\nredial off\npeer a@127.0.0.1 127.0.0.1 7001 dial\n"
MSG = "{ op: atom, n: int64 }"


class Manifest(unittest.TestCase):
    def gen(self, text):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.wire")
            with open(p, "w") as fh:
                fh.write(text)
            r = run(["generate", "-o", os.path.join(d, "out"), p])
            peers = os.path.join(d, "out", "bees_peers.silica")
            body = open(peers).read() if os.path.exists(peers) else None
            return r, body

    def test_a_good_manifest_builds(self):
        r, body = self.gen(NODE + f"remote counter @ a@127.0.0.1 cast {MSG}\nlocal inbox cast {MSG}\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("fn node_name() -> string { \"b@127.0.0.1\" }", body)
        # the language's carrier address: "host:port:timeout_ms" connects, "listen:port" listens on 127.0.0.1 (transport design 6.2)
        self.assertIn("fn link_address() -> string { \"127.0.0.1:7001:10000\" }", body)
        self.assertIn("bees_msgs@dec_inbox", body)
        self.assertIn("bees_dist@frame4", body)
        self.assertIn("proxy_counter", body)
        self.assertIn("dlv_inbox", body)
        self.assertIn("spawn_registered", body)
        self.assertIn("kill_abnormal", body)

    def test_names_become_atoms_and_nothing_writes_an_atom_literal(self):
        r, body = self.gen(NODE + f"remote counter @ a@127.0.0.1 cast {MSG}\nlocal inbox cast {MSG}\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("bees_atoms@a_counter()", body)
        self.assertIn("bees_atoms@a_inbox()", body)
        self.assertEqual(re.findall(r"[^a-z_@]:[a-z_]+", re.sub(r'"[^"]*"', "", body)).count(":counter"), 0)

    def test_a_name_cannot_be_remote_and_local(self):
        r, body = self.gen(NODE + f"remote x @ a@127.0.0.1 cast {MSG}\nlocal x cast {MSG}\n")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("already declared", r.stderr)
        self.assertIsNone(body)

    def test_remote_names_a_peer_that_is_listed(self):
        r, _ = self.gen(NODE + f"remote x @ z@127.0.0.1 cast {MSG}\n")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("not a peer line", r.stderr)

    def test_only_the_local_host(self):
        # N1: a manifest-only node is auth none, a loopback-only test setting: non-loopback hosts are refused, loopback ones
        # (127.0.0.0/8, localhost: resolved at boot by the resolver edge) pass the reader
        for host in ("localhost", "127.0.0.2"):
            r, _ = self.gen(f"node b@127.0.0.1\nredial off\npeer a@127.0.0.1 {host} 7001 dial\nremote x @ a@127.0.0.1 cast {MSG}\n")
            self.assertEqual(r.returncode, 0, host + r.stderr)
        for host in ("0.0.0.0", "10.0.0.1"):
            r, _ = self.gen(f"node b@127.0.0.1\nredial off\npeer a@127.0.0.1 {host} 7001 dial\n")
            self.assertNotEqual(r.returncode, 0, host)
            self.assertIn("is not a loopback address: a node built from the manifest alone is auth none", r.stderr)   # N1: the test-setting rule

    def test_other_errors(self):
        cases = [
            ("peer a@h 127.0.0.1 7001 dial\n", "no node line"),
            ("node b@h\n", "no peer line"),
            (NODE + "node c@h\n", "second node line"),
            (NODE + "peer a@127.0.0.1 127.0.0.1 7002 dial\n", "listed twice"),
            ("node b@h\npeer b@h 127.0.0.1 7001 dial\n", "this node itself"),
            ("node b@h\npeer a@h 127.0.0.1 70000 dial\n", "not 1..65535"),
            ("node b@h\npeer a@h 127.0.0.1 7001 maybe\n", "expected: peer"),
            (NODE + "timing 0 1 1\n", "timing values"),
            (NODE + "creation 99999999999\n", "creation"),
            (NODE + f"local Bad cast {MSG}\n", "not a usable registered name"),
        ]
        for text, want in cases:
            r, body = self.gen(text)
            self.assertNotEqual(r.returncode, 0, text)
            self.assertIn(want, r.stderr, text)

    def test_remote_and_local_lines_declare_the_message_types(self):
        # the type of a remote or local line is checked like a `message` line: an unsupported field is a build error
        r, _ = self.gen(NODE + "local inbox cast { n: int64, to: actor_ref }\n")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("actor_ref", r.stderr)

    def test_deterministic(self):
        text = NODE + f"remote counter @ a@127.0.0.1 cast {MSG}\nlocal inbox cast {MSG}\n"
        self.assertEqual(self.gen(text)[1], self.gen(text)[1])


class Flags(unittest.TestCase):
    def test_mandatory_set_is_the_union_in_dist_hrl(self):
        hrl = glob.glob("/usr/local/erlang/lib/erlang/lib/kernel-*/include/dist.hrl")
        if not hrl:
            self.skipTest("the installed OTP source is not there")
        text = open(hrl[0]).read()
        defs = {}
        for m in re.finditer(r"-define\((DFLAG_[A-Z0-9_]+),\s*\(?16#([0-9a-fA-F]+)(?: bsl (\d+))?\)?\)", text):
            defs[m.group(1)] = int(m.group(2), 16) << int(m.group(3) or 0)
        m25 = re.search(r"MANDATORY_DFLAGS_25,\s*\((.*?)\)\)", text, re.S).group(1)
        m26 = re.search(r"MANDATORY_DFLAGS_26, \((.*?)\)\)", text, re.S).group(1)
        union = 0
        for name in re.findall(r"\?(DFLAG_[A-Z0-9_]+)", m25 + " " + m26):
            union |= defs[name]
        self.assertEqual(union, FLAGS)


class Frames(unittest.TestCase):
    """The bytes the Silica trial printed equal the layouts of the protocol."""

    @classmethod
    def setUpClass(cls):
        cls.g = golden()

    def test_all_frames_were_recorded(self):
        self.assertEqual(sorted(self.g), ["n_acc", "n_init", "payload", "reg_send", "s_ok"])

    def test_n_init(self):
        name = b"b@127.0.0.1"
        body = b"N" + struct.pack(">QIH", FLAGS, 1, len(name)) + name
        self.assertEqual((struct.pack(">H", len(body)) + body).hex(), self.g["n_init"])

    def test_n_acc(self):
        name = b"a@127.0.0.1"
        body = b"N" + struct.pack(">QIIH", FLAGS, 0, 7, len(name)) + name
        self.assertEqual((struct.pack(">H", len(body)) + body).hex(), self.g["n_acc"])

    def test_s_ok(self):
        self.assertEqual(self.g["s_ok"], (struct.pack(">H", 3) + b"sok").hex())

    def test_n_messages_as_dist_util_writes_them(self):
        if not have_erl():
            self.skipTest("erl is not installed")
        # dist_util:send_name builds [<<$N, Flags:64, Creation:32, NameLen:16>>, Name] and send_challenge
        # [<<$N, Flags:64, Challenge:32, Creation:32, NameLen:16>>, Name]; the 2-byte length framing is {packet, 2}
        out = erl('Name = <<"b@127.0.0.1">>, NameA = <<"a@127.0.0.1">>, Flags = 16#4_0307_0F94, '
                  'A = iolist_to_binary([<<$N, Flags:64, 1:32, (byte_size(Name)):16>>, Name]), '
                  'B = iolist_to_binary([<<$N, Flags:64, 0:32, 7:32, (byte_size(NameA)):16>>, NameA]), '
                  'io:format("~s ~s", [binary:encode_hex(<<(byte_size(A)):16, A/binary>>), '
                  'binary:encode_hex(<<(byte_size(B)):16, B/binary>>)])')
        a, b = out.lower().split()
        self.assertEqual(self.g["n_init"], a)
        self.assertEqual(self.g["n_acc"], b)

    def test_reg_send_against_erl(self):
        if not have_erl():
            self.skipTest("erl is not installed")
        out = erl('Pid = binary_to_term(<<131,88,119,11,"b@127.0.0.1",3:32,0:32,1:32>>), '
                  'true = (term_to_binary(Pid) =:= <<131,88,119,11,"b@127.0.0.1",3:32,0:32,1:32>>), '
                  'Ctl = term_to_binary({6, Pid, \'\', counter}), '
                  'Pay = term_to_binary(#{op => inc, n => 5}, [deterministic]), '
                  'Body = <<112, Ctl/binary, Pay/binary>>, '
                  'io:format("~s ~s", [binary:encode_hex(<<(byte_size(Body)):32, Body/binary>>), binary:encode_hex(Pay)])')
        frame, pay = out.lower().split()
        self.assertEqual(self.g["reg_send"], frame)
        self.assertEqual(self.g["payload"], pay)

    def test_reg_send_structure(self):
        b = bytes.fromhex(self.g["reg_send"])
        (n,) = struct.unpack(">I", b[:4])
        self.assertEqual(n, len(b) - 4)
        body = b[4:]
        self.assertEqual(body[0], 112)
        self.assertEqual(body[1:6], bytes([131, 104, 4, 97, 6]))
        self.assertEqual(body[6], 88)  # NEW_PID_EXT
        self.assertEqual(body[7:9], bytes([119, 11]))
        self.assertEqual(body[9:20], b"b@127.0.0.1")
        self.assertEqual(struct.unpack(">III", body[20:32]), (3, 0, 1))  # id, serial, creation
        self.assertEqual(body[32:34], bytes([119, 0]))  # the empty cookie atom
        self.assertEqual(body[34:36], bytes([119, 7]))
        self.assertEqual(body[36:43], b"counter")
        self.assertEqual(body[43], 131)  # the payload term


class Parsed(unittest.TestCase):
    """The recorded parse results of the same trial."""

    def lines(self):
        return open(GOLDEN).read()

    def test_parse_results(self):
        t = self.lines()
        for want in ("n_init parse code 0", "n_init parse name b@127.0.0.1", "s_ok accepted 1", "n_acc parse code 0",
                     "n_acc parse name a@127.0.0.1", "reg_send parse code 0", "reg_send parse name counter",
                     "reg_send from another node, code 15", "payload validates 0", "payload decoded n 5",
                     "payload decoded op inc", "n_init peer_index -1",
                     "reg_send local_index of counter (a remote name) -1"):
            self.assertIn(want, t)
        # a name message read as the other direction's message is refused, not misread
        self.assertIn("n_acc as an init message, code 2", t)
        self.assertIn("n_init as an acc message, code 2", t)


class TypedKinds(unittest.TestCase):
    """C1 (development-plan/spikes/C1-codec-term-coverage.md 2.1, 2.2, 2.7): sums and optional references through bees_msgs and
    bees_peers. Silica is not compiled here; trials/c1_codec_sum and trials/c1_codec_optref run what these shapes generate."""
    SUM = "(:i, int64) | (:s, string) | :none"
    ENUM = ":red | :green"
    CHAIN = "(atom, int64, ref?(L, normal, rec))"

    def gen(self, d, text):
        p = os.path.join(d, "x.wire")
        with open(p, "w") as fh:
            fh.write(text)
        out = os.path.join(d, "out")
        r = run(["generate", "-o", out, p])
        self.assertEqual(r.returncode, 0, r.stderr)
        return out

    def read(self, out, name):
        with open(os.path.join(out, name)) as fh:
            return fh.read()

    def test_a_sum_is_one_derived_encode_and_decode(self):
        with tempfile.TemporaryDirectory() as d:
            out = self.gen(d, NODE + f"remote val @ a@127.0.0.1 cast {self.SUM}\nlocal colour cast {self.ENUM}\n")
            msgs = self.read(out, "bees_msgs.silica")
            self.assertIn("export enc_val/1;\nexport dec_val/1;", msgs)
            self.assertIn(f"fn enc_val(msg: {self.SUM}) -> string {{\n    sequence proc[mem(normal), transport]\n"
                          "        s: string <- encode((:etf), msg)\n    produces pure s end\n}", msgs)
            # a variant holds a string: limits, max_depth the type's nesting plus one
            self.assertIn(f"        r: (:ok, {self.SUM}) | (:rejected, atom) <- decode((:etf), frame, "
                          "{ max_bytes: 4294967295, max_depth: 2, max_length: 4294967295 })", msgs)
            # a sum of atom literals has a fixed size: no limits argument, as for any fixed-size type
            self.assertIn(f"        r: (:ok, {self.ENUM}) | (:rejected, atom) <- decode((:etf), frame)\n", msgs)
            self.assertIn("fn check_val(frame: string) -> atom {", msgs)
            self.assertIn("check_colour(frame)", msgs)
            peers = self.read(out, "bees_peers.silica")
            self.assertIn(f"fn proxy_val(msg: {self.SUM}, st: ", peers)
            self.assertIn(f"(:ok, v: {self.ENUM}) -> cast_registered(bees_atoms@a_colour(), v impl ActorMessage {{}})", peers)
            self.assertNotIn("alloc_region", msgs + peers)

    def test_a_recursive_message_carries_its_region(self):
        rt = f"(:ok, {self.CHAIN}) | (:rejected, atom)"
        rec = f"{{ r: region(L, normal), v: {self.CHAIN} }}"
        with tempfile.TemporaryDirectory() as d:
            out = self.gen(d, NODE + f"remote out @ a@127.0.0.1 cast {self.CHAIN}\nlocal chain cast {self.CHAIN}\n")
            msgs = self.read(out, "bees_msgs.silica")
            self.assertIn("export enc_chain/1;\nexport dec_chain/2;", msgs)
            self.assertIn(f"fn enc_chain(msg: {rec}) -> string {{\n    sequence proc[mem(normal), transport]\n"
                          f"        v: {self.CHAIN} <- msg.v;\n        s: string <- encode((:etf), v)\n    produces pure s end\n}}", msgs)
            # the caller's region is decode's fourth argument; max_depth is the type's nesting plus 64
            self.assertIn(f"fn dec_chain(frame: string, r: region(L, normal)) -> {rt} {{\n    sequence proc[mem(normal), transport]\n"
                          f"        x: {rt} <- decode((:etf), frame, {{ max_bytes: 4294967295, max_depth: 65, max_length: 4294967295 }}, r)\n"
                          "    produces pure x end\n}", msgs)
            # validation decodes into a scratch region of its own
            self.assertIn("fn check_chain(frame: string) -> atom {\n    sequence proc[mem(normal)]\n"
                          "        L: lifetime <- fresh_lifetime();\n        r: region(L, normal) <- alloc_region(normal);\n"
                          f"        x: {rt} <- dec_chain(frame, r);\n", msgs)
            self.assertIn("case name == bees_atoms@a_chain() of { true -> check_chain(frame);", msgs)
            peers = self.read(out, "bees_peers.silica")
            # the deliverer: a fresh region, the decode into it, and the region cast with the value
            self.assertIn("fn dlv_chain(msg: string, st: int64) -> (:no_reply, int64) {\n    sequence proc[concurrency, mem(normal)]\n"
                          "        L: lifetime <- fresh_lifetime();\n        r: region(L, normal) <- alloc_region(normal);\n"
                          f"        x: {rt} <- bees_msgs@dec_chain(msg, r);\n"
                          f"        _: boolean <- case x of {{ (:ok, v: {self.CHAIN}) -> cast_registered(bees_atoms@a_chain(), "
                          "{ r: r, v: v } impl ActorMessage {}); (:rejected, _w: atom) -> true };\n"
                          "        _: atom <- stop_self(:normal)\n", peers)
            self.assertIn("fn start_dlv_chain() -> actor_ref {", peers)
            # the proxy's message is the record; it hands it to enc_<name>
            self.assertIn(f"fn proxy_out(msg: {rec}, st: ", peers)
            self.assertIn("payload: string <- bees_msgs@enc_out(msg);", peers)

    def test_type_atoms_get_their_manifests_and_check_passes(self):
        with tempfile.TemporaryDirectory() as d:
            out = self.gen(d, NODE + f"remote val @ a@127.0.0.1 cast {self.SUM}\nlocal colour cast {self.ENUM}\n")
            for unit in ("bees_msgs", "bees_peers", "beam_peers"):
                lines = [x for x in self.read(out, unit + ".atoms").split("\n") if x and not x.startswith("#")]
                self.assertEqual(lines, ["green", "i", "none", "red", "s"], unit)
            units = [os.path.join(out, f) for f in ("bees_msgs.silica", "bees_peers.silica")]
            r = run(["check"] + units)
            self.assertEqual(r.returncode, 0, r.stdout)
            # the manifests are what allows the literals: without them check reports the tags
            os.remove(os.path.join(out, "bees_msgs.atoms"))
            r = run(["check"] + units)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("BEAM atom literal :red outside bees_atoms (D30)", r.stdout)
            self.assertNotIn("bees_peers.silica", r.stdout)
            # a second build reads the generated manifests as its own input (trial.mk's lib/*.atoms): the same atoms, the same files
            first = {f: self.read(out, f) for f in sorted(os.listdir(self.gen(d, self.read(d, "x.wire"))))}
            p = os.path.join(d, "x.wire")
            r = run(["generate", "-o", out, p] + [os.path.join(out, u + ".atoms") for u in ("bees_msgs", "bees_peers", "beam_peers")])
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(first, {f: self.read(out, f) for f in sorted(os.listdir(out))})
            # a manifest without type atoms writes none, and removes the ones this tool wrote earlier (not a file of the program's)
            with open(os.path.join(out, "beam_peers.atoms"), "w") as fh:
                fh.write("mine\n")
            out = self.gen(d, NODE + f"remote counter @ a@127.0.0.1 cast {MSG}\nlocal inbox cast {MSG}\n")
            self.assertEqual(sorted(f for f in os.listdir(out) if f.endswith(".atoms")), ["beam_peers.atoms"])
            self.assertEqual(self.read(out, "beam_peers.atoms"), "mine\n")

    def test_deterministic(self):
        text = NODE + f"remote val @ a@127.0.0.1 cast {self.SUM}\nlocal chain cast {self.CHAIN}\n"
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            o1, o2 = self.gen(d1, text), self.gen(d2, text)
            self.assertEqual(sorted(os.listdir(o1)), sorted(os.listdir(o2)))
            for f in os.listdir(o1):
                self.assertEqual(self.read(o1, f), self.read(o2, f), f)


class SplitKinds(unittest.TestCase):
    """C1 (development-plan/spikes/C1-codec-term-coverage.md 2.3 to 2.6, 3.5): Map, Set, buf, term and the SD-37 split through
    bees_msgs and bees_peers. Silica is not compiled here; trials/c1_codec_map, c1_codec_set, c1_codec_buf, c1_codec_termmsg and
    c1_codec_wide run what these shapes generate."""
    IM = "List[(int64, string), mem(normal)]"
    BLOB = "{ b: buf(L, normal, uint8, 8), n: int64 }"
    TOKS = "List[(int64, int64, float64, string), mem(normal)]"

    def gen(self, d, text):
        p = os.path.join(d, "x.wire")
        with open(p, "w") as fh:
            fh.write(text)
        out = os.path.join(d, "out")
        r = run(["generate", "-o", out, p])
        self.assertEqual(r.returncode, 0, r.stderr)
        return out

    def read(self, out, name):
        with open(os.path.join(out, name)) as fh:
            return fh.read()

    def test_a_map_is_converted_node_by_node(self):
        rt = f"(:ok, {self.IM}) | (:rejected, atom)"
        with tempfile.TemporaryDirectory() as d:
            out = self.gen(d, NODE + "local im cast Map[int64, string]\n")
            msgs = self.read(out, "bees_msgs.silica")
            self.assertIn("module bees_msgs;\nuse wire_etf;\nuse bees_atoms;\nuse bees_etf_scan;\nuse bees_codec_kinds;\n", msgs)
            self.assertIn("export enc_im/1;\nexport dec_im/1;", msgs)
            self.assertIn("// node 0: Map[int64,string]\n", msgs)
            self.assertIn("// node 1: int64 (plain: the derived codec)\n", msgs)
            self.assertIn("// node 2: string (plain: the derived codec)\n", msgs)
            self.assertIn(f"fn enc_im(msg: {self.IM}) -> string {{ ke_0(msg) }}", msgs)
            self.assertIn(f"fn dec_im(frame: string) -> {rt} {{\n"
                          "    case bees_codec_kinds@frame_check(frame, 4294967295) < 0 of {\n"
                          "        true -> (:rejected, bees_etf_scan@code_reason(bees_codec_kinds@frame_check(frame, 4294967295)));\n"
                          "        false -> kd_0(frame)\n    }\n}", msgs)
            # the header is checked before anything is decoded; pairs in the list's order; no key twice in either direction
            self.assertIn("        c: int64 <- bees_codec_kinds@map_open(frame);", msgs)
            self.assertIn("                ok: boolean <- bees_codec_kinds@pair_ok(n, keys, kf, vf);", msgs)
            self.assertIn("        dup: boolean <- bees_codec_kinds@seen(keys, kc);", msgs)
            self.assertIn("case dup of { true -> (:rejected, bees_etf_scan@code_reason(0 - 13));", msgs)
            # each plain part is ONE derived encode and ONE derived decode, with the limits a whole message carries
            self.assertEqual(msgs.count("encode((:etf), v)"), 2)
            self.assertEqual(msgs.count("<- decode((:etf), frame"), 2)
            self.assertIn("        x: (:ok, int64) | (:rejected, atom) <- decode((:etf), frame)\n", msgs)
            self.assertIn("        x: (:ok, string) | (:rejected, atom) <- decode((:etf), frame, "
                          "{ max_bytes: 4294967295, max_depth: 1, max_length: 4294967295 })", msgs)
            self.assertIn("check_im(frame)", msgs)
            peers = self.read(out, "bees_peers.silica")
            self.assertIn(f"(:ok, v: {self.IM}) -> cast_registered(bees_atoms@a_im(), v impl ActorMessage {{}})", peers)
            self.assertNotIn("alloc_region", msgs + peers)

    def test_a_set_writes_nil_values(self):
        with tempfile.TemporaryDirectory() as d:
            msgs = self.read(self.gen(d, NODE + "remote ints @ a@127.0.0.1 cast Set[int64]\n"), "bees_msgs.silica")
            self.assertIn("fn enc_ints(msg: List[int64, mem(normal)]) -> string { ke_0(msg) }", msgs)
            self.assertIn("        l: List[string, mem(normal)] <- bees_codec_kinds@push_member(acc, kf)", msgs)
            self.assertIn("bees_codec_kinds@nil_end(frame, pos)", msgs)
            self.assertNotIn("pair_end", msgs)

    def test_a_buf_message_carries_its_region(self):
        rt = f"(:ok, {self.BLOB}) | (:rejected, atom)"
        with tempfile.TemporaryDirectory() as d:
            out = self.gen(d, NODE + "local blob cast buf(L, normal, uint8, 8)\n")
            msgs = self.read(out, "bees_msgs.silica")
            self.assertIn("export enc_blob/1;\nexport dec_blob/2;", msgs)
            self.assertIn(f"fn enc_blob(msg: {{ r: region(L, normal), v: {self.BLOB} }}) -> string {{ ke_0(msg.v, msg.r) }}", msgs)
            self.assertIn(f"fn dec_blob(frame: string, r: region(L, normal)) -> {rt} {{", msgs)
            self.assertIn('    case v.n < 0 or v.n > 8 of { true -> ""; false -> ke_0_b(v.b, r, v.n) }', msgs)
            self.assertIn("decode((:etf), frame, { max_bytes: 4294967295, max_depth: 1, max_length: 8 })", msgs)
            self.assertIn("        b: buf(L, normal, uint8, 8) <- alloc_buf(r, 8);", msgs)
            self.assertIn("                y: uint8 <- bees_codec_kinds@int_byte(c);\n                _: atom <- write_buf(b, i, y)", msgs)
            self.assertIn(f"        x: {rt} <- dec_blob(frame, r);", msgs)      # check_blob: a scratch region of its own
            peers = self.read(out, "bees_peers.silica")
            self.assertIn(f"        x: {rt} <- bees_msgs@dec_blob(msg, r);", peers)
            self.assertIn("cast_registered(bees_atoms@a_blob(), { r: r, v: v } impl ActorMessage {})", peers)

    def test_a_term_message_is_bees_term_wire(self):
        rt = f"(:ok, {self.TOKS}) | (:rejected, atom)"
        with tempfile.TemporaryDirectory() as d:
            out = self.gen(d, NODE + "local any cast term\nremote out @ a@127.0.0.1 cast term\nremote ping @ a@127.0.0.1 cast (int64, string)\n")
            msgs = self.read(out, "bees_msgs.silica")
            self.assertIn("use wire_etf;\nuse bees_atoms;\nuse bees_term_wire;\n", msgs)
            self.assertNotIn("bees_codec_kinds", msgs)
            self.assertIn(f"fn enc_out(msg: {self.TOKS}) -> string {{ bees_term_wire@encode(msg) }}", msgs)
            self.assertIn(f"fn dec_any(frame: string) -> {rt} {{ bees_term_wire@decode(frame) }}", msgs)
            self.assertIn("fn enc_ping(msg: (int64, string)) -> string {\n    sequence proc[mem(normal), transport]\n"
                          "        s: string <- encode((:etf), msg)", msgs)
            self.assertIn("check_any(frame)", msgs)
            peers = self.read(out, "bees_peers.silica")
            self.assertIn(f"fn proxy_out(msg: {self.TOKS}, st: ", peers)
            self.assertIn(f"(:ok, v: {self.TOKS}) -> cast_registered(bees_atoms@a_any(), v impl ActorMessage {{}})", peers)

    def test_a_plain_manifest_gains_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            msgs = self.read(self.gen(d, NODE + f"local m cast {MSG}\n"), "bees_msgs.silica")
            self.assertIn("module bees_msgs;\nuse wire_etf;\nuse bees_atoms;\n\nexport", msgs)
            for word in ("bees_etf_scan", "bees_codec_kinds", "bees_term_wire", "ke_", "kd_", "// node"):
                self.assertNotIn(word, msgs)

    def test_the_sd37_split_is_one_constant(self):
        import bees_dist_gen as D
        import bees_wire_gen as W
        wide = "{ a: int64, b: int64, c: int64, d: int64, e: int64 }"
        ty = ("record", [(f, ("prim", "int64")) for f in "abcde"])

        def text():
            with tempfile.TemporaryDirectory() as d:
                D.generate_msgs(d, [("w", ty)])
                return self.read(d, "bees_msgs.silica")
        keep = W.SD37_SPLIT
        try:
            on = text()
            self.assertIn(f"fn enc_w(msg: {wide}) -> string {{ ke_0(msg) }}", on)
            self.assertIn('        ns: List[string, mem(normal)] <- ["a", "b", "c", "d", "e"];\n'
                          "        ps: List[int64, mem(normal)] <- bees_codec_kinds@record_parts(frame, ns);", on)
            self.assertEqual(on.count("<- decode((:etf), frame"), 1)          # the one node of the five int64 fields
            self.assertIn("fn kd_0_4(frame: string, ps: List[int64, mem(normal)], a0: int64, a1: int64, a2: int64, a3: int64) -> ", on)
            self.assertIn("(:ok, { a: a0, b: a1, c: a2, d: a3, e: a })", on)
            del W.SD37_SPLIT
            off = text()
            self.assertIn(f"fn enc_w(msg: {wide}) -> string {{\n    sequence proc[mem(normal), transport]\n"
                          "        s: string <- encode((:etf), msg)", off)
            self.assertIn(f"        r: (:ok, {wide}) | (:rejected, atom) <- decode((:etf), frame)\n", off)
            for word in ("bees_codec_kinds", "ke_", "kd_"):
                self.assertNotIn(word, off)
        finally:
            W.SD37_SPLIT = keep


if __name__ == "__main__":
    unittest.main()
