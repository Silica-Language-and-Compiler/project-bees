#!/usr/bin/env python3
"""Unit tests of milestone N2T (BEAM-mode links inside TLS; development-plan/spikes/N2T-beam-tls.md):

  - the reader's rules for beam.transport, beam.tls_opts and beam.tls_verify (tools/bees_conf.py), each with a rejecting case;
  - what tools/bees_config_beam.py writes for a TLS node and for a plaintext node (beam_conf@tls, the engine's specs, the banner);
  - tools/bees_edge_gen.py pastes the TLS part only into a program that uses dangerous_beam_tls;
  - tools/bees_beam_tls_certs.py: the test certificates are what the tool writes, from fixed inputs, and say what the trials need.
"""
import datetime
import os
import re
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TOOL = os.path.join(HERE, "bees_config_beam.py")
EDGE = os.path.join(HERE, "bees_edge_gen.py")
sys.path.insert(0, HERE)
import bees_beam_tls_certs as CERTS  # noqa: E402

MANIFEST = """node   bees@localhost
peer   stock@localhost 127.0.0.1 47500 listen
peer   other@far.example 127.0.0.1 47501 dial
remote outbox @ stock@localhost cast { op: atom, n: int64 }
local  inbox cast { op: atom, n: int64 }
"""
TLS = '{tls_opts, [{certfile, "node.pem"}, {keyfile, "node-key.pem"}, {cacertfile, "ca.pem"}]}, {tls_verify, verify_peer}'
GOOD = """[ {mode, beam},
  {node, [{name, "bees@localhost"}]},
  {beam, [{transport, tls}, %s, {cookie_file, "cookie"}, {listen_address, "127.0.0.1"}, {listen_port, 47500},
          {epmd_port, 4399}, {net_ticktime_s, 8}, {redial, false}]} ].
""" % TLS
PLAIN = GOOD.replace("{transport, tls}, %s, " % TLS, "{transport, tcp}, ")


def read(p):
    with open(p) as fh:
        return fh.read()


def spec_bytes(unit, name):
    """the bytes a generated spec function answers (a bytes_of list literal), or b"" for the empty string"""
    if re.search(r'fn %s\(\) -> string \{ "" \}' % re.escape(name), unit):
        return b""
    m = re.search(r"fn %s\(\) -> string \{\n(.*?)\n\}" % re.escape(name), unit, re.S)
    assert m is not None, name
    xs = re.search(r"<- \[([0-9, ]*)\];", m.group(1))
    return bytes(int(x) for x in xs.group(1).split(",")) if xs else b""


class Reader(unittest.TestCase):
    def run_tool(self, cfg, files=("node.pem", "node-key.pem", "ca.pem"), key_mode=0o600):
        d = os.path.realpath(tempfile.mkdtemp())
        with open(os.path.join(d, "node.wire"), "w") as fh:
            fh.write(MANIFEST)
        p = os.path.join(d, "cookie")
        with open(p, "wb") as fh:
            fh.write(b"secret\n")
        os.chmod(p, 0o600)
        for f in files:
            with open(os.path.join(d, f), "w") as fh:
                fh.write("test\n")
            os.chmod(os.path.join(d, f), key_mode if f.endswith("-key.pem") else 0o644)
        with open(os.path.join(d, "bees.config"), "w") as fh:
            fh.write(cfg)
        r = subprocess.run([sys.executable, TOOL, "generate", "--config", os.path.join(d, "bees.config"), "-o", os.path.join(d, "out"),
                            os.path.join(d, "node.wire")], capture_output=True, text=True)
        return r, d

    def refuse(self, cfg, pattern, **kw):
        r, _ = self.run_tool(cfg, **kw)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertRegex(r.stderr.strip(), r"^bees\.config:\d+: " + pattern)

    def test_tls_node_is_generated(self):
        r, d = self.run_tool(GOOD)
        self.assertEqual(r.returncode, 0, r.stderr)
        conf = read(os.path.join(d, "out", "beam_conf.silica"))
        self.assertIn("fn tls() -> boolean { true }", conf)
        own = b"".join(os.path.join(d, f).encode() + b"\0" for f in ("node.pem", "node-key.pem", "ca.pem")) + b"0\0"
        self.assertEqual(spec_bytes(conf, "tls_server_spec"), own)
        # peer 0 is listened for: nothing is dialed, so no client spec; peer 1 is dialed: the host part of ITS NODE NAME is the name
        # the server's certificate is checked against (as a stock Erlang node does), not the address it is dialed at
        self.assertEqual(spec_bytes(conf, "tls_client_spec_0"), b"")
        self.assertEqual(spec_bytes(conf, "tls_client_spec_1"), own + b"far.example\0")
        self.assertIn("1 -> tls_client_spec_1();", conf)
        self.assertIn("export tls_client_spec_of/1;", conf)
        self.assertIn("transport=tls tls_verify=verify_peer auth=cookie", conf)
        self.assertIn("Erlang cookie authentication inside TLS 1.3 (transport tls, verify_peer against cacertfile, 127.0.0.1)", conf)
        self.assertIn("X25519MLKEM768 or classical X25519; certificates Ed25519, ECDSA P-256 or RSA (PSS, 2048 bits or more)", conf)
        self.assertNotIn("no encryption", conf)

    def test_plaintext_node_is_unchanged(self):
        r, d = self.run_tool(PLAIN, files=())
        self.assertEqual(r.returncode, 0, r.stderr)
        conf = read(os.path.join(d, "out", "beam_conf.silica"))
        self.assertIn("fn tls() -> boolean { false }", conf)
        self.assertEqual(spec_bytes(conf, "tls_server_spec"), b"")
        self.assertEqual(spec_bytes(conf, "tls_client_spec_1"), b"")
        self.assertIn("transport=tcp auth=cookie", conf)
        self.assertIn("no encryption (transport tcp, 127.0.0.1)", conf)

    def test_required_with_tls(self):
        self.refuse(GOOD.replace(TLS + ", ", "{tls_verify, verify_peer}, "), r"beam\.tls_opts: required when transport is tls")
        self.refuse(GOOD.replace(", {tls_verify, verify_peer}", ""), r"beam\.tls_verify: required when transport is tls")
        # no default (ruled 2026-11-18, N2T Q8; D25's default is withdrawn): a beam section says tcp or tls
        self.refuse(PLAIN.replace("{transport, tcp}, ", ""), r"beam\.transport: required, no default")
        self.refuse(GOOD.replace("{transport, tls}, ", ""), r"beam\.transport: required, no default")
        self.refuse(GOOD.replace(', {cacertfile, "ca.pem"}', ""), r"beam\.tls_opts: needs certfile, keyfile and cacertfile \(cacertfile missing\)")
        self.refuse(GOOD.replace('{certfile, "node.pem"}, ', ""), r"beam\.tls_opts: needs certfile, keyfile and cacertfile \(certfile missing\)")

    def test_closed_sets_and_keys(self):
        self.refuse(GOOD.replace("verify_peer}", "verify_none}"), r"beam\.tls_verify: expected one of verify_peer")
        self.refuse(GOOD.replace("verify_peer}", "pins}"), r"beam\.tls_verify: expected one of verify_peer")
        self.refuse(GOOD.replace('{cacertfile, "ca.pem"}', '{cacertfile, "ca.pem"}, {versions, "tlsv1.2"}'), r"beam\.tls_opts\.versions: unknown key")
        self.refuse(GOOD.replace('{cacertfile, "ca.pem"}', '{cacertfile, "ca.pem"}, {cacertfile, "ca.pem"}'), r"beam\.tls_opts\.cacertfile: duplicate key")
        self.refuse(GOOD.replace('{certfile, "node.pem"}', "{certfile, node}"), r"beam\.tls_opts\.certfile: expected a string")

    def test_files(self):
        self.refuse(GOOD, r'beam\.tls_opts\.cacertfile: file "ca\.pem" does not exist', files=("node.pem", "node-key.pem"))
        self.refuse(GOOD, r'beam\.tls_opts\.certfile: file "node\.pem" does not exist', files=("node-key.pem", "ca.pem"))
        self.refuse(GOOD, r'beam\.tls_opts\.keyfile: key file "node-key\.pem" is readable or writable by group or others \(mode 644', key_mode=0o644)

    def test_refused_without_tls(self):
        self.refuse(PLAIN.replace("{transport, tcp}, ", "{transport, tcp}, %s, " % TLS), r"beam\.tls_opts: transport is tcp, so there is no TLS to configure")
        self.refuse(PLAIN.replace("{transport, tcp}, ", "{transport, tcp}, {tls_verify, verify_peer}, "), r"beam\.tls_verify: transport is tcp")

    def test_auth_none_is_not_built_inside_tls(self):
        self.refuse(GOOD.replace('{cookie_file, "cookie"}', "{auth, none}"), r"beam\.auth: none is the loopback test wire")


class EdgeGen(unittest.TestCase):
    def gen(self, uses):
        d = tempfile.mkdtemp()
        role = os.path.join(d, "x.role")
        with open(role, "w") as fh:
            fh.write("// role\n")
        out = os.path.join(d, "dangerous_x.silica")
        args = [sys.executable, EDGE, "dangerous_x", out]
        for u in uses:
            args += ["--use", u]
        r = subprocess.run(args + [role], capture_output=True, text=True, cwd=d)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return read(out)

    def test_plaintext_beam_program_uses_no_tls_unit(self):
        unit = self.gen(["dangerous_beam_net"])
        self.assertIn("fn beam_tls_link(c: dangerous_actor_ref, peer: int64) -> dangerous_actor_ref { c }", unit)
        self.assertIn("fn beam_tls_listen(c: dangerous_actor_ref, owner: actor_ref, address: string) -> boolean {", unit)
        self.assertNotIn("dangerous_beam_tls", unit.replace("`--use dangerous_beam_tls`", ""))

    def test_tls_beam_program_wraps_its_carriers(self):
        unit = self.gen(["dangerous_beam_net", "dangerous_beam_tls"])
        self.assertIn("use dangerous_beam_tls;", unit)
        self.assertIn("dangerous_beam_tls@btls", unit)
        self.assertIn("dangerous_beam_tls@btlsl", unit)
        self.assertNotIn("dangerous_actor_ref { c }", unit)

    def test_other_programs_get_neither(self):
        self.assertNotIn("beam_tls_link", self.gen(["bees_msgs"]))

    def test_node_edge_part_calls_the_hooks(self):
        part = read(os.path.join(ROOT, "src", "shim", "beam_node_edge.part"))
        self.assertIn("beam_tls_link(c0, i)", part)
        self.assertIn("beam_tls_listen(c, l, beam_conf@listener_address())", part)


class Engine(unittest.TestCase):
    """the engine's BEAM profile and the Silica link agree, and what the BEAM profile relaxes stays in the BEAM profile"""

    def test_profile_number_and_the_one_place_for_rsa(self):
        c = read(os.path.join(ROOT, "native", "tls", "silica_bees_tls.c"))
        link = read(os.path.join(ROOT, "src", "inter_nodal", "dangerous_beam_tls.silica"))
        m = re.search(r"#define BEES_TLS_PROFILE_BEAM (\d+)", c)
        self.assertIsNotNone(m)
        self.assertNotIn(m.group(1), ("0", "1", "2"))     # 0 TRUST, 1 TEMPUS; 2 is what TEMPUS's self-test opens as "no such profile"
        self.assertIn("false -> 1 }, %s, case st.role == 2" % m.group(1), link)
        # RSA is named once, used by the BEAM list only; the other profiles keep the TRUST list
        self.assertEqual(c.count(":rsa_pss"), 6)     # the six entries of the one list (comments name the families without a colon)
        self.assertEqual(len(re.findall(r"^#define BEES_TLS_BEAM_RSA_SIGALGS ", c, re.M)), 1)
        self.assertIn('beam ? BEES_TLS_BEAM_SIGALGS : "ed25519:ecdsa_secp256r1_sha256"', c)
        self.assertNotIn("rsa_pkcs1", c.split("#define BEES_TLS_BEAM_RSA_SIGALGS", 1)[1].split("\n", 1)[0])
        self.assertIn("if (beam) SSL_CTX_set_security_level(c, 2);", c)
        self.assertIn("if (beam) classical = 1;", c)
        self.assertIn("if (beam && ca[0] == 0) return 0;", c)


class Certs(unittest.TestCase):
    def test_files_are_what_the_tool_writes(self):
        r = subprocess.run([sys.executable, os.path.join(HERE, "bees_beam_tls_certs.py"), "check"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_fixed_inputs_give_the_same_files(self):
        self.assertEqual(CERTS.files(), CERTS.files())

    def test_what_the_trials_need(self):
        from cryptography import x509
        c = {n: CERTS.cert_of(n) for n in CERTS.CERTS}
        now = datetime.datetime(2026, 11, 18)
        self.assertLess(c["expired"].not_valid_after_utc.replace(tzinfo=None), now)
        for n in ("h", "a", "b", "l", "d", "stock", "rogue", "otherhost"):
            self.assertGreater(c[n].not_valid_after_utc.replace(tzinfo=None), now, n)
        for n in ("h", "a", "b", "l", "d", "stock", "expired", "otherhost"):
            self.assertEqual(c[n].issuer, c["ca"].subject, n)
            c["ca"].public_key().verify(c[n].signature, c[n].tbs_certificate_bytes)
        self.assertEqual(c["rogue"].issuer, c["rogue_ca"].subject)
        san = lambda n: c[n].extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.DNSName)  # noqa: E731
        self.assertEqual(san("stock"), ["localhost"])
        self.assertEqual(san("otherhost"), ["otherhost"])
        self.assertTrue(c["ca"].extensions.get_extension_for_class(x509.BasicConstraints).value.ca)


if __name__ == "__main__":
    unittest.main()
