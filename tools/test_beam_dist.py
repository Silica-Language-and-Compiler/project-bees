#!/usr/bin/env python3
"""Tests for BEAM mode (milestone N2): the beam half of the bees.config reader (tools/bees_config_beam.py: one rejecting case
per validation rule it owns, and what it generates), and the byte layouts that trials/n2_frames and trials/n2_auth printed (their
recorded goldens are read; Silica is not compiled here), checked against the installed OTP 28 where it is there:
  - the flag set against kernel's dist.hrl (mandatory set | PUBLISHED | DIST_MONITOR);
  - N, s, r, a against an independent Python writer of dist_util.erl's <<$N, Flags:64, Challenge:32, Creation:32, NameLen:16>>,
    [$s | Status], [$r, ?int32(Challenge), Digest], [$a, Digest] with the 2-byte packet length;
  - ALIVE2_REQ and PORT_PLEASE2_REQ against erl_epmd.erl's packets, written independently here;
  - EXIT, UNLINK_ID_ACK, SEND and the is_auth reply against term_to_binary in erl;
  - the cookie digests against erlang:md5([Cookie | integer_to_list(Challenge)]) (dist_util:gen_digest/2).
Run: python3 tools/test_beam_dist.py   (standard library only)"""
import os
import re
import struct
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TOOL = os.path.join(HERE, "bees_config_beam.py")
sys.path.insert(0, HERE)
import platform_id as P  # noqa: E402
FRAMES = os.path.join(ROOT, "trials", "n2_frames", P.golden_name("main.scout"))
AUTH = os.path.join(ROOT, "trials", "n2_auth", P.golden_name("dangerous_n2_auth.scout"))
DIST_HRL = "/usr/local/erlang/lib/erlang/lib/kernel-10.0/include/dist.hrl"
FLAGS = 0x4_0307_0F9D


def have_erl():
    return subprocess.run(["which", "erl"], capture_output=True).returncode == 0


def erl(expr):
    r = subprocess.run(["erl", "-noshell", "-eval", expr + ", halt()."], capture_output=True, text=True, timeout=60)
    return r.stdout.strip()


def read(path):
    with open(path) as fh:
        return fh.read()


def golden(path):
    out = {}
    with open(path) as fh:
        for line in fh:
            line = line.rstrip("\n")
            k, _, v = line.rpartition(" ")
            out[k] = v
    return out


def frame2(b):
    return struct.pack(">H", len(b)) + b


MANIFEST = """node   bees@localhost
peer   stock@localhost 127.0.0.1 47500 listen
peer   other@localhost 127.0.0.1 47501 dial
remote outbox @ stock@localhost cast { op: atom, n: int64 }
local  inbox cast { op: atom, n: int64 }
"""
GOOD = """[ {mode, beam},
  {node, [{name, "bees@localhost"}]},
  {beam, [{transport, tcp}, {cookie_file, "cookie"}, {listen_address, "127.0.0.1"}, {listen_port, 47500},
          {epmd_port, 4399}, {net_ticktime_s, 8}, {redial, false}]} ].
"""


class Reader(unittest.TestCase):
    def run_tool(self, cfg, beam=None, cookie_mode=0o600, cookie=b"secret\n", manifest=MANIFEST, generate=True):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "node.wire"), "w") as fh:
            fh.write(manifest)
        if cookie is not None:
            p = os.path.join(d, "cookie")
            with open(p, "wb") as fh:
                fh.write(cookie)
            os.chmod(p, cookie_mode)
        with open(os.path.join(d, "bees.config"), "w") as fh:
            fh.write(cfg)
        args = [sys.executable, TOOL, "generate" if generate else "check", "--config", os.path.join(d, "bees.config")]
        if beam is not None:
            with open(os.path.join(d, "node.beam"), "w") as fh:
                fh.write(beam)
            args += ["--beam", os.path.join(d, "node.beam")]
        if generate:
            args += ["-o", os.path.join(d, "out")]
        r = subprocess.run(args + [os.path.join(d, "node.wire")], capture_output=True, text=True)
        return r, d

    def refuse(self, cfg, pattern, **kw):
        r, _ = self.run_tool(cfg, **kw)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertRegex(r.stderr.strip(), r"^bees\.config:\d+: " + pattern)

    def test_good_generates_both_units(self):
        r, d = self.run_tool(GOOD, beam="pid outbox deliver inbox\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        conf = read(os.path.join(d, "out", "beam_conf.silica"))
        self.assertIn('fn link_address() -> string { "listen:47500" }', conf)
        self.assertIn("fn io_ms() -> uint64 { 8000 }", conf)
        self.assertIn("fn tick_ms() -> uint64 { 2000 }", conf)
        self.assertIn('fn epmd_address() -> string { "127.0.0.1:4399:10000" }', conf)
        self.assertIn("fn register_epmd() -> boolean { true }", conf)
        self.assertNotIn("secret", conf)          # the cookie is never built in, only its path
        peers = read(os.path.join(d, "out", "beam_peers.silica"))
        self.assertIn("beam_dist@with_pid", peers)
        self.assertIn("        0 -> 0;", peers)       # pid 0 (the outbox proxy) delivers to local 0 (inbox)

    def test_syntax(self):
        self.refuse("[{mode, beam}", r"\(syntax\)")
        self.refuse("[{mode, beam}]. [].", r"\(syntax\): a second term")
        self.refuse("[{mode, 1.5}].", r"\(syntax\): floats")

    def test_unknown_and_duplicate_key(self):
        self.refuse(GOOD.replace("{transport, tcp}", "{transport, tcp}, {colour, red}"), r"beam\.colour: unknown key")
        self.refuse(GOOD.replace("{transport, tcp}", "{transport, tcp}, {transport, tcp}"), r"beam\.transport: duplicate key")
        self.refuse(GOOD.replace("{mode, beam},", "{mode, beam}, {mode, beam},"), r"mode: duplicate key")

    def test_types_and_bounds(self):
        self.refuse(GOOD.replace("{net_ticktime_s, 8}", "{net_ticktime_s, \"8\"}"), r"beam\.net_ticktime_s: expected an integer")
        self.refuse(GOOD.replace("{net_ticktime_s, 8}", "{net_ticktime_s, 3}"), r"beam\.net_ticktime_s: 3 is below 4")
        self.refuse(GOOD.replace("{net_ticktime_s, 8}", "{net_ticktime_s, 3601}"), r"beam\.net_ticktime_s: 3601 is above 3600")
        self.refuse(GOOD.replace("{epmd_port, 4399}", "{epmd_port, 0}"), r"beam\.epmd_port: 0 is below 1")
        self.refuse(GOOD.replace("{transport, tcp}", "{transport, udp}"), r"beam\.transport: expected one of tcp, tls")

    def test_mode(self):
        self.refuse(GOOD.replace("{mode, beam},", ""), r"mode: absent, so the mode is trust")
        self.refuse(GOOD.replace("{mode, beam}", "{mode, [beam, trust]}"), r"mode: the list form is reserved")
        self.refuse(GOOD.replace("{mode, beam}", "{mode, trust}"), r"mode: trust, but the manifest has remote/local lines")

    def test_required_and_files(self):
        self.refuse(GOOD.replace('{listen_address, "127.0.0.1"}, ', ""), r"beam\.listen_address: required, no built-in default")
        self.refuse(GOOD.replace('{cookie_file, "cookie"}, ', ""), r"beam\.cookie_file: required when auth is cookie")
        self.refuse(GOOD, r"beam\.cookie_file: cookie does not exist", cookie=None)
        self.refuse(GOOD, r"beam\.cookie_file: cookie is readable or writable by group or others", cookie_mode=0o644)
        self.refuse(GOOD, r"beam\.cookie_file: cookie must hold 1 to 255 bytes", cookie=b"\n")

    def test_not_built_yet(self):
        self.refuse(GOOD.replace("{transport, tcp}, ", ""), r"beam\.transport: required, no default")   # N2T: tls is built; ruled 2026-11-18: no default
        self.refuse(GOOD.replace('"127.0.0.1"', '"10.0.0.7"'), r"beam\.listen_address: 10\.0\.0\.7 is not built yet")
        self.refuse(GOOD.replace("{net_ticktime_s, 8}", "{net_ticktime_s, 8}, {frame_size_max, 4294967296}"), r"beam\.frame_size_max: 4294967296 is above 4294967295")
        self.refuse(GOOD.replace("{net_ticktime_s, 8}", "{net_ticktime_s, 8}, {spawn, any}"), r"beam\.spawn: any is not built yet")
        self.refuse(GOOD.replace('{name, "bees@localhost"}', '{name, "bees@localhost"}, {creation, epmd}'), r"node\.creation: epmd is not built yet")

    def test_cross_field_and_names(self):
        self.refuse(GOOD.replace("{listen_port, 47500}", "{listen_port, 0}, {epmd, none}"), r"beam\.listen_port: 0 needs epmd external")
        self.refuse(GOOD.replace('{name, "bees@localhost"}', '{name, "orders@localhost"}'), r"node\.name: \"orders@localhost\" differs from the manifest")
        self.refuse(GOOD.replace("{net_ticktime_s, 8}", '{net_ticktime_s, 8}, {peers, [{"nobody@localhost", [{port, epmd}]}]}'), r"beam\.peers: nobody@localhost is not a peer of the manifest")

    def test_beam_manifest(self):
        r, _ = self.run_tool(GOOD, beam="pid inbox deliver inbox\n")
        self.assertEqual(r.returncode, 1)
        self.assertIn("inbox is not a remote name", r.stderr)


@unittest.skipUnless(os.path.exists(FRAMES), "trials/n2_frames has no recorded golden")
class Frames(unittest.TestCase):
    g = golden(FRAMES) if os.path.exists(FRAMES) else {}

    def hx(self, k):
        return bytes.fromhex(self.g[k])

    @unittest.skipUnless(os.path.exists(DIST_HRL), "no OTP 28 dist.hrl")
    def test_flags_against_dist_hrl(self):
        text = read(DIST_HRL)
        val = {m.group(1): m.group(2) for m in re.finditer(r"-define\((DFLAG_\w+),\s*(\S+?)\)\.", text)}
        def v(name):
            s = val[name]
            m = re.fullmatch(r"\(16#([0-9a-fA-F]+)bsl32", s.replace(" ", ""))
            return int(m.group(1), 16) << 32 if m else int(s.replace("16#", ""), 16)
        mand = 0
        for f in ["EXTENDED_REFERENCES", "FUN_TAGS", "NEW_FUN_TAGS", "EXTENDED_PIDS_PORTS", "EXPORT_PTR_TAG", "BIT_BINARIES",
                  "NEW_FLOATS", "UTF8_ATOMS", "MAP_TAG", "BIG_CREATION", "HANDSHAKE_23", "UNLINK_ID"]:
            mand |= v("DFLAG_" + f)
        mand |= 4 << 32                            # DFLAG_V4_NC, written (16#04 bsl 32)
        self.assertEqual(FLAGS, mand | v("DFLAG_PUBLISHED") | v("DFLAG_DIST_MONITOR"))

    def test_handshake_messages(self):
        name = b"bees@localhost"
        self.assertEqual(self.hx("n_init"), frame2(b"N" + struct.pack(">QIH", FLAGS, 1, len(name)) + name))
        self.assertEqual(self.hx("n_acc"), frame2(b"N" + struct.pack(">QIIH", FLAGS, 3000000000, 7, len(name)) + name))
        self.assertEqual(self.hx("s_ok"), frame2(b"sok"))
        self.assertEqual(self.hx("s_not_allowed"), frame2(b"snot_allowed"))
        d = bytes(range(16))
        self.assertEqual(self.hx("r"), frame2(b"r" + struct.pack(">I", 3000000000) + d))
        self.assertEqual(self.hx("a"), frame2(b"a" + d))
        self.assertEqual(self.g["n_acc challenge"], "3000000000")
        self.assertEqual(self.g["r challenge"], "3000000000")

    def test_epmd_requests(self):
        # erl_epmd.erl do_register_node/3: [?int16(Len), $x, ?int16(Port), $M, 0, ?int16(High), ?int16(Low), ?int16(NLen), Name, ?int16(0)]
        name = b"bees"
        body = b"x" + struct.pack(">HBBHHH", 47500, ord("M"), 0, 6, 6, len(name)) + name + struct.pack(">H", 0)
        self.assertEqual(self.hx("alive2_req"), struct.pack(">H", len(body)) + body)
        # erl_epmd.erl get_port/3: [?int16(Len), $z, Name] with Len = 1 + length(Name)
        self.assertEqual(self.hx("port_please2_req"), struct.pack(">H", 6) + b"zstock")
        self.assertEqual(self.g["alive2_x_resp ok creation"], str(0x000a0b0c))
        self.assertEqual(self.g["port2_resp port"], "47500")

    @unittest.skipUnless(have_erl(), "erl not installed")
    def test_control_replies_against_term_to_binary(self):
        expr = ('B = fun(N, I, C) -> NB = atom_to_binary(N), binary_to_term(<<131,88,119,(byte_size(NB)),NB/binary,I:32,0:32,C:32>>) end, '
                'Ours = B(\'bees@localhost\', 5, 1), Theirs = B(\'gen@localhost\', 10, 1794336599), Ours0 = B(\'bees@localhost\', 0, 1), '
                'Tag = binary_to_term(<<131, (binary:decode_hex(<<"6c000000017705616c6961735a0005770d67656e406c6f63616c686f73746af36757000397fa7df100043f3b7d4000000503000000006a">>))/binary>>), '
                'H = fun(T) -> <<131, R/binary>> = term_to_binary(T), binary:encode_hex(R, lowercase) end, '
                'io:format("~s ~s ~s ~s ~s~n", [H({3, Ours, Theirs, noproc}), H({36, 16#1234567890, Ours0, Theirs}), H({2, \'\', Theirs}), '
                'binary:encode_hex(term_to_binary({Tag, yes}), lowercase), binary:encode_hex(term_to_binary({Ours0, a}), lowercase)])')
        exitc, unl, send, reply, withpid = erl(expr).split()
        self.assertEqual(self.g["exit_noproc"], "7083" + exitc)
        self.assertEqual(self.g["unlink_id_ack"], "7083" + unl)
        self.assertEqual(self.g["send"], "7083" + send + reply)
        self.assertEqual(self.g["with_pid"], withpid)

    def test_parsed_otp_control_messages(self):
        for label, tag in (("link", "1"), ("monitor", "19"), ("unlink_id", "35"), ("exit2", "8"), ("regsend_auth", "6")):
            self.assertEqual(self.g[label + " code"], "0")
            self.assertEqual(self.g[label + " tag"], tag)
        self.assertEqual(self.g["link payload at"], self.g["link length"])     # every element skipped exactly
        self.assertEqual(self.g["exit2 payload at"], self.g["exit2 length"])
        self.assertEqual(self.g["link to node"], "bees@localhost")
        self.assertEqual(self.g["regsend_auth name"], "net_kernel")
        self.assertEqual(self.g["is_auth code"], "0")
        self.assertEqual(self.g["truncated code"], "2")
        self.assertEqual(self.g["bad tag code"], "4")
        self.assertEqual(self.g["too deep code"], "6")


@unittest.skipUnless(os.path.exists(AUTH) and have_erl(), "no n2_auth golden or no erl")
class Digests(unittest.TestCase):
    def test_digests_against_erlang_md5(self):
        lines = [l.split() for l in read(AUTH).splitlines() if l.startswith("op3 ok ")]
        self.assertEqual(len(lines), 3)
        for _, _, hx in lines:
            ch = int(hx[:8], 16)
            want = erl(f'io:format("~s", [binary:encode_hex(erlang:md5(["n2cookie" | integer_to_list({ch})]), lowercase)])')
            self.assertEqual(hx[8:], want, ch)
        self.assertIn("op1 digest equals op3 of its challenge true", read(AUTH))


if __name__ == "__main__":
    unittest.main(verbosity=1)
