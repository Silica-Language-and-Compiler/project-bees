#!/usr/bin/env python3
"""Tests of the TRUST half of the bees.config reader (tools/bees_config_trust.py, N3) and of the trust/1 frames BEES writes.

Every validation rule of bees-config-file.md section 4 that concerns `mode` or the `trust` section has a rejecting case here, each
checked for the `bees.config:LINE: PATH: MESSAGE` form; the defaults of section 5.3 read back when a key is absent; the whitelist
and pin files parse in both of SEMP's spec forms; the fingerprint is the SHA-512 of the DER inside a PEM file. When an `erl` is
installed (/usr/local/erlang/bin/erl or on PATH), the frames recorded in trials/n3_trust_frames/frames.scout are read back by
erl's binary_to_term (the reference reader, safe mode) and must be maps with the expected keys.

    python3 tools/test_bees_config_trust.py
"""
import base64
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest


def slurp(p):
    with open(p) as f:
        return f.read()

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bees_config_trust as B  # noqa: E402

GOOD_TRUST = """[{mode, trust}, {trust, [{port, 47501}, {listen_address, "127.0.0.1"}, {plaintext_test_only, true}%s]}]."""


class Conf(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def tearDown(self):
        for root, dirs, files in os.walk(self.d):
            for n in files + dirs:
                os.chmod(os.path.join(root, n), 0o700)
        shutil.rmtree(self.d)

    def write(self, name, text, mode=None):
        p = os.path.join(self.d, name)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(text)
        if mode is not None:
            os.chmod(p, mode)
        return p

    def verdict(self, text):
        return B.run(self.write("bees.config", text))

    def refused(self, text, path_part, msg_part):
        v, notes, err = self.verdict(text)
        self.assertIsNotNone(err, "expected a boot error")
        self.assertRegex(err, r"^bees\.config:\d+: ")
        self.assertIn(path_part, err)
        self.assertIn(msg_part, err)
        return err

    def test_good_minimal_and_defaults(self):
        v, notes, err = self.verdict(GOOD_TRUST % "")
        self.assertIsNone(err)
        for k, (_, default) in B.TRUST_OPTS.items():
            if k in ("port", "listen_address", "plaintext_test_only", "args_len_max", "session"):
                continue
            self.assertEqual(v[k], default, k)
        self.assertEqual(v["args_len_max"], v["frame_size_max"])          # default: equal to frame_size_max (R1)
        self.assertEqual(v["frame_eff"], B.BUILD_FRAME_MAX)              # the build implements 4096 until N1
        self.assertEqual(v["session"], {k: d for k, (_, d) in B.SESSION_OPTS.items()})
        self.assertIn("TRUST standalone", " ".join(notes))               # an unset whitelist is bannered, not silent

    def test_no_mode_is_trust(self):
        v, _, err = self.verdict("""[{trust, [{listen_address, "127.0.0.1"}, {plaintext_test_only, true}]}].""")
        self.assertIsNone(err)
        self.assertEqual(v["mode"], "trust")

    def test_syntax(self):
        self.refused("[{mode, trust}]", "(syntax)", "expected '.'")
        self.refused("[{mode, trust}]. [].", "(syntax)", "one term")
        self.refused("[{trust, [{call_timeout_ms, 1.5}]}].", "(syntax)", "floats")
        self.refused("[{trust, [{call_timeout_ms, X}]}].", "(syntax)", "variables")

    def test_mode(self):
        self.refused("[{mode, [beam, trust]}].", "mode", "reserved")
        self.refused("[{mode, other}].", "mode", "beam or trust")

    def test_unknown_and_duplicate(self):
        self.refused(GOOD_TRUST % ", {colour, red}", "trust.colour", "unknown key")
        self.refused(GOOD_TRUST % ", {token_ttl_ms, 300000}", "trust.token_ttl_ms", "token_ttl_sec")
        self.refused(GOOD_TRUST % ", {port, 1}", "trust.port", "duplicate key")
        self.refused("[{other, 1}].", "(top).other", "unknown key")

    def test_types_and_bounds(self):
        self.refused(GOOD_TRUST % ", {call_timeout_ms, \"5\"}", "trust.call_timeout_ms", "expected an integer")
        self.refused(GOOD_TRUST % ", {call_timeout_ms, 0}", "trust.call_timeout_ms", "outside 1 to 600000")
        self.refused(GOOD_TRUST % ", {call_timeout_ms, 600001}", "trust.call_timeout_ms", "outside")
        self.refused(GOOD_TRUST % ", {token_bytes, 31}", "trust.token_bytes", "outside 32 to 64")
        self.refused(GOOD_TRUST % ", {whitelist_autoload, yes}", "trust.whitelist_autoload", "true or false")
        self.refused(GOOD_TRUST % ", {tls_opts, [{password, \"x\"}]}", "trust.tls_opts.password", "unknown key")
        self.refused(GOOD_TRUST % ", {session, #{idle_ms => 70000, max_age_ms => 60000}}", "trust.session.idle_ms", "above max_age_ms")

    def test_cross_fields_and_not_built(self):
        self.refused(GOOD_TRUST % ", {frame_size_max, 2048}, {args_len_max, 4096}", "trust.args_len_max", "above frame_size_max")
        self.refused(GOOD_TRUST % ", {frame_size_max, 8192}", "trust.frame_size_max", "not built yet")
        self.refused(GOOD_TRUST % ", {dns_ns_timeout_ms, 6000}", "trust.dns_ns_timeout_ms", "dns_total_timeout_ms")

    def test_required_by_mode(self):
        self.refused("""[{trust, [{plaintext_test_only, true}]}].""", "trust.listen_address", "no default (R6)")
        self.refused("""[{trust, [{listen_address, "127.0.0.1"}]}].""", "trust.plaintext_test_only", "TLS is not built")
        self.refused("""[{trust, [{listen_address, "10.0.0.7"}, {plaintext_test_only, true}]}].""", "trust.listen_address", "loopback")
        # in mode beam the trust section is validated (types, bounds) but its required values are not demanded
        v, _, err = self.verdict("""[{mode, beam}, {trust, [{port, 6469}]}].""")
        self.assertIsNone(err)
        self.refused("""[{mode, beam}, {trust, [{port, 0}]}].""", "trust.port", "outside")

    def test_whitelist_files(self):
        self.refused(GOOD_TRUST % ', {whitelist_file, "wl.config"}', "trust.whitelist_file", 'whitelist file "wl.config" does not exist')
        self.write("wl.config", "#{}.", mode=0o000)
        self.refused(GOOD_TRUST % ', {whitelist_file, "wl.config"}', "trust.whitelist_file", "not readable")
        os.chmod(os.path.join(self.d, "wl.config"), 0o600)
        self.write("wl.config", "#{ oops")
        self.refused(GOOD_TRUST % ', {whitelist_file, "wl.config"}', "trust.whitelist_file", "does not parse")

    def test_whitelist_specs_and_fingerprints(self):
        der = b"\x30\x03\x02\x01\x07"
        pem = "-----BEGIN CERTIFICATE-----\n" + base64.b64encode(der).decode() + "\n-----END CERTIFICATE-----\n"
        self.write("certs/a.pem", pem)
        self.write("certs/b.cert", "raw stand-in")
        self.write("certs/c.cert", "raw stand-in")              # same bytes as b: one fingerprint, a boot note
        self.write("wl.config", """#{"a.pem" => #{demo => all, other => [{f, 1}]}, "b.cert" => [{demo, any}],
                                     "c.cert" => none, "gone.pem" => any}.""")
        v, notes, err = self.verdict(GOOD_TRUST % ', {whitelist_file, "wl.config"}')
        self.assertIsNone(err)
        fps = {cert: fp for cert, fp, _ in v["peers"]}
        self.assertEqual(fps["a.pem"], hashlib.sha512(der).hexdigest())          # the DER inside the PEM (D11)
        self.assertEqual(fps["b.cert"], hashlib.sha512(b"raw stand-in").hexdigest())
        self.assertNotIn("c.cert", fps)
        self.assertTrue(any("gone.pem" in n and "skipped" in n for n in notes))
        self.assertTrue(any("same fingerprint" in n for n in notes))
        specs = {cert: spec for cert, _, spec in v["peers"]}
        self.assertEqual(specs["a.pem"], {"demo": "any", "other": [("f", 1)]})
        self.assertEqual(specs["b.cert"], {"demo": "any"})
        self.write("wl.config", """#{"b.cert" => [{demo, [{f, 300}]}]}.""")
        self.refused(GOOD_TRUST % ', {whitelist_file, "wl.config"}', "b.cert", "Arity =< 255")

    def test_pins(self):
        self.write("pins.config", """#{"127.0.0.1:47501" => "a.cert"}.""")
        v, _, err = self.verdict(GOOD_TRUST % ', {server_pins_file, "pins.config"}')
        self.assertIsNone(err)
        self.assertEqual([a for a, _ in v["servers"]], ["127.0.0.1:47501"])
        self.refused(GOOD_TRUST % ', {server_pins_file, "nope.config"}', "trust.server_pins_file", "does not exist")

    def test_generated_unit(self):
        self.write("certs/b.cert", "raw stand-in")
        self.write("wl.config", """#{"b.cert" => [{demo, [{add, 2}]}]}.""")
        p = self.write("bees.config", GOOD_TRUST % ', {whitelist_file, "wl.config"}, {tls_opts, [{certfile, "certs/b.cert"}]}')
        v, notes, err = B.run(p)
        B.gen(os.path.join(self.d, "lib"), v, notes, err)
        unit = slurp(os.path.join(self.d, "lib", "bees_trust_conf.silica"))
        self.assertIn('fn boot_error() -> string { "" }', unit)
        self.assertIn('(ms == "demo" and ((fs == "add" and a == 2)))', unit)
        self.assertIn(hashlib.sha512(b"raw stand-in").hexdigest(), unit)
        self.assertIn("bees_trust_peer_0", slurp(os.path.join(self.d, "lib", "bees_trust_conf.atoms")))
        v, notes, err = B.run(self.write("bees.config", "[{mode, 1}]."))
        B.gen(os.path.join(self.d, "lib"), v, notes, err)
        self.assertIn("bees.config:1: mode: expected beam or trust", slurp(os.path.join(self.d, "lib", "bees_trust_conf.silica")))


def find_erl():
    for c in ("/usr/local/erlang/bin/erl", shutil.which("erl")):
        if c and os.path.exists(c):
            return c
    return None


class Frames(unittest.TestCase):
    """erl's binary_to_term (safe) reads every frame BEES writes, as a map with the expected keys"""

    def test_erl_reads_frames(self):
        erl = find_erl()
        if not erl:
            self.skipTest("no erl installed")
        golden = os.path.join(HERE, "..", "trials", "n3_trust_frames", "frames.scout")
        if not os.path.exists(golden):
            self.skipTest("no frames golden recorded yet")
        hexes = dict(re.findall(r"^(hello|call|result) hex ([0-9a-f]+)$", slurp(golden), re.M))
        want = {"hello": "[t,ver]", "call": "[a,args,f,m,opts,req_id,t,ver]", "result": "[req_id,t,value,ver]"}
        for name, h in hexes.items():
            # the atoms a TRUST node's code holds exist first, as in the reference server; then safe mode reads the frame
            expr = ('[list_to_atom(A) || A <- ["t", "ver", "a", "args", "f", "m", "opts", "req_id", "value", "hello", "call", '
                    '"result", "demo", "add"]], B = binary:decode_hex(<<"%s">>), M = binary_to_term(B, [safe]), '
                    'io:format("~w~n", [lists:sort(maps:keys(M))]), halt().') % h
            out = subprocess.run([erl, "-noshell", "-eval", expr], capture_output=True, text=True, timeout=60).stdout.strip()
            self.assertEqual(out, want[name], name)
        self.assertEqual(set(hexes), set(want))


if __name__ == "__main__":
    unittest.main(verbosity=1)
