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
GOLDEN = os.path.join(ROOT, "trials", "m3_dist_frames", "main.scout")
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


NODE = "node b@127.0.0.1\npeer a@127.0.0.1 127.0.0.1 7001 dial\n"
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
        self.assertIn("fn link_address() -> string { \"connect:127.0.0.1:7001\" }", body)
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
        for host in ("0.0.0.0", "10.0.0.1", "localhost", "127.0.0.2"):
            r, _ = self.gen(f"node b@127.0.0.1\npeer a@127.0.0.1 {host} 7001 dial\n")
            self.assertNotEqual(r.returncode, 0, host)
            self.assertIn("127.0.0.1 only", r.stderr)

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


if __name__ == "__main__":
    unittest.main()
