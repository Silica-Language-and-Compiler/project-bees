#!/usr/bin/env python3
"""Tests of THE bees.config reader, tools/bees_conf.py (N0.2: the beam and trust halves merged; N1: addresses and frame caps).

The N0.2 exit criteria that a reader test can show (mvp.md section 5, N0 row), each a test below:
  - the worked example of bees-config-file.md section 6 parses and every option reads back as written;
  - every default (and bound) of the document's tables in section 5 equals the reader's table (the document is parsed);
  - one rejecting case per validation rule, each `bees.config:LINE: PATH: MESSAGE`, never clamped;
  - a missing listen_address in both modes (R6); a missing or unreadable configured whitelist_file (R2);
  - no sys.config is read anywhere.
And the N1 rules: frame caps up to BEAM's 4294967295 are accepted (R1) and become the generated limits; auth none and
plaintext_test_only refuse non-loopback addresses; the carrier's address forms (127.0.0.1, 0.0.0.0, IPv4 literals, names
resolved at boot, no IPv6).

    python3 tools/test_bees_conf.py
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import bees_conf as C  # noqa: E402
import bees_dist_gen as D  # noqa: E402
import trial_ports  # noqa: E402

SPEC = os.path.join(ROOT, "development-plan", "bees-config-file.md")

MANIFEST = """node   bees@localhost
peer   peer@localhost 127.0.0.1 47500 dial
remote outbox @ peer@localhost cast { op: atom, n: int64, s: string }
local  inbox cast { op: atom, n: int64 }
"""
BEAM = """[ {mode, beam},
  {node, [{name, "bees@localhost"}]},
  {beam, [{transport, tcp}, {auth, none}, {listen_address, "127.0.0.1"}, {redial, false}%s]} ]."""
TRUST = """[{mode, trust}, {trust, [{port, 47501}, {listen_address, "127.0.0.1"}, {plaintext_test_only, true}%s]}]."""


class Base(unittest.TestCase):
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

    def manifest(self, text=MANIFEST):
        return D.parse([self.write("node.wire", text)])

    def conf(self, text, manifest=True):
        return C.validate(self.write("bees.config", text), self.manifest() if manifest is True else manifest)

    def refused(self, text, path, msg, manifest=True):
        with self.assertRaises(C.ConfError) as cm:
            self.conf(text, manifest)
        err = cm.exception.text
        self.assertRegex(err, r"^bees\.config:\d+: ")
        self.assertIn(f": {path}: ", err)
        self.assertIn(msg, err)
        return err


# ---------------------------------------------------------------- the document
def doc_section(text, title):
    i = text.index(title)
    j = text.find("\n### ", i + 1)
    return text[i:j if j > 0 else len(text)]


def doc_rows(section):
    """{option: (default cell, bounds cell)} from a table whose first column is `option`"""
    rows = {}
    head = None
    for line in section.splitlines():
        if not line.startswith("| "):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells[0] == "Option":
            head = cells
            continue
        m = re.fullmatch(r"`([a-z_.]+)`", cells[0])
        if m and head:
            rows[m.group(1)] = (cells[head.index("Default")], cells[head.index("Bounds")])
    return rows


def first_int(cell):
    m = re.search(r"\d[\d_,]*", cell)
    return int(m.group(0).replace("_", "").replace(",", "")) if m else None


class Document(Base):
    """the document's tables (section 5) against the reader's table (OPTIONS)"""

    @classmethod
    def setUpClass(cls):
        with open(SPEC) as f:
            cls.text = f.read()

    def check_table(self, title, opts, prefix):
        rows = doc_rows(doc_section(self.text, title))
        self.assertEqual(set(rows) - {k for k in rows if "." in k}, set(opts), f"{title}: the options listed differ")
        for k, o in opts.items():
            d, b = rows[k]
            with self.subTest(option=prefix + k):
                if o.required:
                    self.assertIn("required", d + b)
                elif o.kind in ("int", "creation") and o.default is not None:
                    self.assertEqual(first_int(d), o.default, d)
                elif isinstance(o.default, bool):
                    self.assertIn(f"`{str(o.default).lower()}`", d)
                elif isinstance(o.default, str):
                    self.assertTrue(f"`{o.default}`" in d or f'`"{o.default}"`' in d, d)
                elif o.manifest:
                    self.assertIn("manifest", d)
                else:
                    self.assertTrue(re.search(r"unset|none|equal to|2 \*|the value of|defaults below|`\[\]`", d), d)
                if o.kind in ("int", "creation") and k != "args_len_max":
                    m = re.search(r"(\d[\d_,]*) to (\d[\d_,]*)", b)
                    self.assertIsNotNone(m, b)
                    self.assertEqual((first_int(m.group(1)), first_int(m.group(2))), (o.lo, o.hi), b)
                if o.choices:
                    for c in o.choices:
                        self.assertIn(f"`{c}`", self.text[self.text.index(f"| `{k}` |"):][:600], c)

    def test_node_table(self):
        self.check_table("### 5.1 `node`", C.NODE_OPTS, "node.")

    def test_beam_table(self):
        self.check_table("### 5.2 `beam`", C.BEAM_OPTS, "beam.")

    def test_trust_table(self):
        self.check_table("### 5.3 `trust`", C.TRUST_OPTS, "trust.")
        rows = doc_rows(doc_section(self.text, "### 5.3 `trust`"))
        for k, ((lo, hi), d) in C.SESSION_OPTS.items():
            dc, bc = rows[f"session.{k}"]
            self.assertEqual(first_int(dc), d, k)
            m = re.search(r"(\d[\d_,]*) to (\d[\d_,]*)", bc)
            self.assertEqual((first_int(m.group(1)), first_int(m.group(2))), (lo, hi), k)

    def test_worked_example_reads_back(self):
        """section 6's file parses and every option reads back as written (its mode, trust without plaintext, is refused at
        boot until N4, so the values are read with the grammar and the type and bound checks of each option)"""
        m = re.search(r"## 6\. A full worked example\s+```erlang\n(.*?)```", self.text, re.S)
        p = self.write("bees.config", m.group(1))
        top = C.proplist(C.read_file(p), "", C.TOP_KEYS)
        tr = C.proplist(top["trust"][0], "trust", C.TRUST_OPTS)
        bm = C.proplist(top["beam"][0], "beam", C.BEAM_OPTS)
        self.assertEqual(str(top["mode"][0].value), "trust")
        written = {"port": 6464, "listen_address": "10.0.0.7", "call_timeout_ms": 5000, "suspicion_limit": 3, "token_bytes": 48,
                   "token_ttl_sec": 300, "frame_size_max": 4294967295, "args_len_max": 4294967295, "term_depth_max": 32,
                   "acceptors": 8, "session_slots_max": 1000, "whitelist_file": "trust_whitelist.config",
                   "server_pins_file": "trust_servers.config", "whitelist_cert_dir": "certs"}
        for k, want in written.items():
            o = C.TRUST_OPTS[k]
            got = C.want_int(tr[k][0], k, o.lo, o.hi) if o.kind == "int" else C.want_str(tr[k][0], k)
            self.assertEqual(got, want, k)
        self.assertEqual(C.want_bool(tr["whitelist_autoload"][0], "x"), False)
        self.assertEqual(C.parse_spec(tr["whitelist_default_spec"][0], "x"), "none")
        self.assertEqual({str(k.value): v.value for k, v in tr["session"][0].value},
                         {"max_inflight": 8, "max_age_ms": 60000, "idle_ms": 5000, "max_calls": 100, "drain_ms": 1000})
        self.assertEqual(C.want_int(bm["frame_size_max"][0], "x", 512, C.BEAM_FRAME_MAX), 4294967295)
        self.assertEqual(C.want_atom(bm["epmd"][0], "x", ("external", "none")), "external")
        self.assertEqual(C.want_str(bm["cookie_file"][0], "x"), "secrets/erlang.cookie")
        # and the whole file: TRUST over TLS (N4.1) is built, so the verdict is no longer "TLS is not built" but the carrier's
        # address limit on the example's listen address 10.0.0.7 (SR-1; rule 9)
        with self.assertRaises(C.ConfError) as cm:
            C.validate(p, None)
        self.assertIn("trust.listen_address: 10.0.0.7 is not built yet", cm.exception.text)

    def test_defaults_table_is_complete(self):
        paths = [r[0] for r in C.defaults_rows()]
        self.assertEqual(len(paths), len(C.NODE_OPTS) + len(C.BEAM_OPTS) + len(C.TRUST_OPTS) + len(C.SESSION_OPTS))
        for path, d, b, when, why in C.defaults_rows():
            self.assertIn(when, ("boot", "build"), path)
            if when == "build":
                self.assertTrue(why, path)

    def test_defaults_read_back_when_absent(self):
        conf = self.conf(TRUST % "", manifest=None)
        t = conf["trust"]
        for k, o in C.TRUST_OPTS.items():
            if k in ("port", "listen_address", "plaintext_test_only", "args_len_max", "session"):
                continue
            self.assertEqual(t[k], o.default, k)
        self.assertEqual(t["args_len_max"], C.BEAM_FRAME_MAX)
        b = self.conf(BEAM % "")["beam"]
        self.assertEqual((b["epmd"], b["epmd_port"], b["frame_max"], b["auth"]), ("external", 4369, C.BEAM_FRAME_MAX, "none"))
        self.assertEqual((b["io_ms"], b["tick_ms"], b["open_ms"]), (60000, 15000, 10000))     # the manifest's timing defaults


# ---------------------------------------------------------------- one rejecting case per rule (section 4)
class Rules(Base):
    def test_1_syntax(self):
        self.refused("[{mode, beam}", "(syntax)", "expected")
        self.refused("[{mode, beam}]. [].", "(syntax)", "a second term")
        self.refused("[{mode, 1.5}].", "(syntax)", "floats")
        self.refused("[{mode, <<\"x\">>}].", "(syntax)", "unexpected character")

    def test_2_3_unknown_and_duplicate_keys(self):
        self.refused(BEAM % ", {colour, red}", "beam.colour", "unknown key")
        self.refused(BEAM % ", {transport, tcp}", "beam.transport", "duplicate key")
        self.refused(TRUST % ", {token_ttl_ms, 1}", "trust.token_ttl_ms", "token_ttl_sec", manifest=None)

    def test_4_5_type_and_bounds_never_clamped(self):
        self.refused(BEAM % ", {epmd_port, \"x\"}", "beam.epmd_port", "expected an integer")
        self.refused(BEAM % ", {epmd_port, 0}", "beam.epmd_port", "0 is below 1 (bounds 1 to 65535; never clamped)")
        self.refused(BEAM % ", {epmd_port, 65536}", "beam.epmd_port", "65536 is above 65535")
        self.refused(TRUST % ", {call_timeout_ms, 600001}", "trust.call_timeout_ms", "600001 is above 600000", manifest=None)

    def test_6_cross_fields(self):
        self.refused(TRUST % ", {session, #{idle_ms => 70000, max_age_ms => 60000}}", "trust.session.idle_ms",
                     "70000 is above max_age_ms 60000", manifest=None)
        self.refused(TRUST % ", {frame_size_max, 2048}, {args_len_max, 4096}", "trust.args_len_max",
                     "4096 is above frame_size_max 2048", manifest=None)
        self.refused(BEAM % ", {listen_port, 0}, {epmd, none}", "beam.listen_port", "0 needs epmd external")

    def test_7_required_by_mode(self):
        self.refused(BEAM.replace('{listen_address, "127.0.0.1"}', '{epmd_port, 4369}') % "", "beam.listen_address", "required")
        self.refused("""[{trust, [{plaintext_test_only, true}]}].""", "trust.listen_address", "no default (R6)", manifest=None)
        self.refused(BEAM.replace("{auth, none}", "{auth, cookie}") % "", "beam.cookie_file", "required when auth is cookie")
        self.refused("""[{trust, [{listen_address, "127.0.0.1"}]}].""", "trust.tls_opts", "required in mode trust unless plaintext_test_only",
                     manifest=None)

    def test_8_files(self):
        cfg = BEAM.replace("{auth, none}", '{auth, cookie}, {cookie_file, "cookie"}') % ""
        self.refused(cfg, "beam.cookie_file", "cookie does not exist")
        self.write("cookie", "secret\n", mode=0o644)
        self.refused(cfg, "beam.cookie_file", "readable or writable by group or others")
        self.write("key.pem", "k", mode=0o644)
        self.refused(TRUST % ', {tls_opts, [{keyfile, "key.pem"}]}', "trust.tls_opts.keyfile", "readable or writable by group",
                     manifest=None)
        self.refused(TRUST % ', {whitelist_file, "wl.config"}', "trust.whitelist_file", 'whitelist file "wl.config" does not exist',
                     manifest=None)
        self.write("wl.config", "#{}.", mode=0o000)
        self.refused(TRUST % ', {whitelist_file, "wl.config"}', "trust.whitelist_file", "not readable", manifest=None)

    def test_redial_options(self):
        """N2c, no defaults (user ruling 2026-11-17): redial is required on a node with a dial-role peer and must be a boolean;
        redial_initial_ms and redial_max_ms are required when it is true and refused when it is false; a node with no dial-role peer
        refuses all three."""
        nored = BEAM.replace(", {redial, false}", "")
        self.refused(nored % "", "beam.redial", "required: this node dials a peer, so write {redial, true}")
        self.refused(nored % "", "beam.redial", "there is no default")
        self.refused(nored % ", {redial, maybe}", "beam.redial", "expected true or false")
        self.refused(nored % ", {redial, 1}", "beam.redial", "expected true or false")
        self.refused(nored % ", {redial, true}", "beam.redial_initial_ms", "required when redial is true")
        self.refused(nored % ", {redial, true}, {redial_initial_ms, 100}", "beam.redial_max_ms", "required when redial is true")
        b = self.conf(nored % ", {redial, true}, {redial_initial_ms, 100}, {redial_max_ms, 800}")["beam"]
        self.assertEqual((b["redial"], b["redial_initial_ms"], b["redial_max_ms"]), (True, 100, 800))
        b = self.conf(BEAM % "")["beam"]
        self.assertEqual((b["redial"], b["redial_initial_ms"], b["redial_max_ms"]), (False, 0, 0))
        self.refused(BEAM % ", {redial_initial_ms, 100}", "beam.redial_initial_ms", "redial is false, so there is no delay to set")
        self.refused(nored % ", {redial, true}, {redial_initial_ms, 5}, {redial_max_ms, 800}", "beam.redial_initial_ms", "5 is below 10")
        self.refused(nored % ", {redial, true}, {redial_initial_ms, 100}, {redial_max_ms, 600001}", "beam.redial_max_ms", "600001 is above 600000")
        self.refused(nored % ", {redial, true}, {redial_initial_ms, 900}, {redial_max_ms, 800}", "beam.redial_initial_ms", "900 is above redial_max_ms 800")
        m3 = C.m3_link({"beam": self.conf(nored % ", {redial, true}, {redial_initial_ms, 100}, {redial_max_ms, 800}")["beam"]}, None)
        self.assertEqual((m3["redial"], m3["redial_initial_ms"], m3["redial_max_ms"]), (True, 100, 800))

    def test_redial_listen_only_node(self):
        """a node with no dial-role peer refuses the redial options: they would be meaningless, and a stray one is more likely a
        mistake (a dialing peer meant, or a copied file) than a wish; the stricter rule is still friendly: the message says to remove them"""
        listen = MANIFEST.replace("47500 dial", "47500 listen")
        nored = BEAM.replace(", {redial, false}", "")
        self.conf(nored % ", {epmd, none}, {listen_port, 47500}", manifest=self.manifest(listen))
        self.refused(BEAM % ", {epmd, none}, {listen_port, 47500}", "beam.redial", "no dial-role peer", manifest=self.manifest(listen))
        # a config can also turn a manifest listen peer into a dial peer: then redial is required again
        over = nored % ', {epmd, none}, {listen_port, 47500}, {peers, [{"peer@localhost", [{role, dial}]}]}'
        self.refused(over, "beam.redial", "required", manifest=self.manifest(listen))

    def test_redial_manifest_line(self):
        """the manifest-only node states redial in the manifest (`redial off` or `redial <initial> <max>`); no default; a program with a
        bees.config states it there only"""
        with self.assertRaises(C.ConfError) as cm:
            C.manifest_only(self.manifest())
        self.assertIn("`redial off` line", cm.exception.text)
        self.assertIn("no default", cm.exception.text)
        m = self.manifest("redial 100 800\n" + MANIFEST)
        self.assertEqual(m["redial"], (100, 800))
        l = C.m3_link(None, m)
        self.assertEqual((l["redial"], l["redial_initial_ms"], l["redial_max_ms"]), (True, 100, 800))
        l = C.m3_link(None, self.manifest("redial off\n" + MANIFEST))
        self.assertEqual((l["redial"], l["redial_initial_ms"], l["redial_max_ms"]), (False, 0, 0))
        with self.assertRaises(C.ConfError) as cm:
            C.manifest_only(self.manifest("redial off\n" + MANIFEST.replace("47500 dial", "47500 listen")))
        self.assertIn("no dial-role peer", cm.exception.text)
        with self.assertRaises(D.DistError):
            self.manifest("redial 900 800\n" + MANIFEST)
        with self.assertRaises(D.DistError):
            self.manifest("redial on\n" + MANIFEST)
        self.refused(BEAM % "", "beam.redial", "stated in bees.config", manifest=self.manifest("redial off\n" + MANIFEST))

    def test_9_not_built_yet(self):
        self.refused(BEAM.replace("{transport, tcp}, ", "") % "", "beam.transport", "tls (the default, D25) is not built yet")
        self.refused(BEAM % ", {spawn, any}", "beam.spawn", "any is not built yet")

    def test_10_name_and_mode(self):
        self.refused(BEAM.replace("bees@localhost", "other@localhost") % "", "node.name", "differs from the manifest")
        self.refused(BEAM.replace("{mode, beam}", "{mode, [beam, trust]}") % "", "mode", "the list form is reserved")
        self.refused(BEAM.replace("{mode, beam},", "") % "", "mode", "absent, so the mode is trust")

    def test_no_sys_config_is_read(self):
        self.write("sys.config", "this is not read.")
        self.conf(BEAM % "")                       # a sys.config beside bees.config changes nothing
        for f in os.listdir(HERE):
            if f.endswith(".py") and not f.startswith("test_"):
                src = open(os.path.join(HERE, f)).read()
                self.assertNotRegex(src, r"open\([^)]*sys\.config", f)


# ---------------------------------------------------------------- N1: frame caps and addresses
class N1(Base):
    def test_beam_frame_cap_up_to_beams_and_generated(self):
        conf = self.conf(BEAM % ", {frame_size_max, 4294967295}")
        self.assertEqual(conf["beam"]["frame_max"], 4294967295)
        out = os.path.join(self.d, "out")
        os.makedirs(out)
        D.generate(out, [os.path.join(self.d, "node.wire")], C.m3_link(conf, self.manifest()))
        msgs = open(os.path.join(out, "bees_msgs.silica")).read()
        self.assertIn("{ max_bytes: 4294967295, max_depth: 2, max_length: 4294967295 }", msgs)
        self.assertIn("fn frame_max() -> int64 { 4294967295 }", open(os.path.join(out, "bees_peers.silica")).read())
        self.refused(BEAM % ", {frame_size_max, 4294967296}", "beam.frame_size_max", "4294967296 is above 4294967295")

    def test_auth_none_is_loopback_only(self):
        self.refused(BEAM.replace('"127.0.0.1"', '"0.0.0.0"') % "", "beam.listen_address",
                     "0.0.0.0 is not a loopback address, and auth none is a loopback-only test setting")
        self.refused(BEAM % ', {peers, [{"peer@localhost", [{host, "192.168.1.20"}]}]}', "beam.peers.peer@localhost.host",
                     "auth none is a loopback-only test setting")

    def test_plaintext_test_only_is_loopback_only(self):
        self.refused(TRUST.replace('"127.0.0.1"', '"0.0.0.0"') % "", "trust.listen_address",
                     "plaintext_test_only binds a loopback address only", manifest=None)

    def test_carrier_address_forms_with_cookie(self):
        self.write("cookie", "secret\n", mode=0o600)
        cookie = BEAM.replace("{auth, none}", '{auth, cookie}, {cookie_file, "cookie"}')
        nodial = cookie.replace(", {redial, false}", "")     # a listen-only node states no redial option
        listen = MANIFEST.replace("47500 dial", "47500 listen")
        b = self.conf(nodial.replace('"127.0.0.1"', '"0.0.0.0"') % ", {epmd, none}, {listen_port, 47500}",
                      manifest=self.manifest(listen))["beam"]
        self.assertEqual(b["link_address"], "listen:any:47500")            # every IPv4 interface: the carrier's listen:any
        b = self.conf(nodial % ", {epmd, none}, {listen_port, 47500}", manifest=self.manifest(listen))["beam"]
        self.assertEqual(b["link_address"], "listen:47500")                # 127.0.0.1
        self.refused(cookie.replace('"127.0.0.1"', '"192.168.1.20"') % "", "beam.listen_address",
                     "192.168.1.20 is not built yet: the language's (:tcp) carrier binds only 127.0.0.1")
        self.refused(cookie.replace('"127.0.0.1"', '"::1"') % "", "beam.listen_address", "is not built yet")
        self.refused(cookie.replace('"127.0.0.1"', '"fe80::1"') % "", "beam.listen_address", "silica-defects.md SR-2")
        b = self.conf(cookie % ', {peers, [{"peer@localhost", [{host, "192.168.1.20"}, {port, 4370}]}]}')["beam"]
        self.assertEqual((b["link_address"], b["link_host_kind"]), ("192.168.1.20:4370", "ipv4"))
        b = self.conf(cookie % ', {peers, [{"peer@localhost", [{host, "localhost"}, {port, 4370}]}]}')["beam"]
        self.assertEqual(C.m3_link({"beam": b}, None)["link_resolve"], True)  # a name: resolved at boot by the edge
        self.refused(cookie % ', {peers, [{"peer@localhost", [{host, "::1"}, {port, 4370}]}]}', "beam.peers.peer@localhost.host",
                     "dials IPv4 literals only")
        # N2b: a name host with port epmd works: the name is resolved first, then the peer host's EPMD is dialed at the IPv4 literal
        b = self.conf(cookie % ', {peers, [{"peer@localhost", [{host, "localhost"}, {port, epmd}]}]}')["beam"]
        self.assertEqual((b["link_by_epmd"], b["links"][0]["resolve"], b["links"][0]["host_kind"]), (True, True, "name"))

    def test_one_link_per_peer_line(self):
        two = MANIFEST + "peer   other@localhost 127.0.0.1 47501 listen\n"
        cookie = BEAM.replace("{auth, none}", '{auth, cookie}, {cookie_file, "cookie"}')
        self.write("cookie", "c", 0o600)
        b = self.conf(cookie % ", {epmd, none}, {listen_port, 47600}", manifest=self.manifest(two))["beam"]
        self.assertEqual([(k["name"], k["dials"], k["address"]) for k in b["links"]],
                         [("peer@localhost", True, "127.0.0.1:47500"), ("other@localhost", False, "listen:47600")])
        self.assertTrue(b["listens"])
        self.assertEqual(b["listener_address"], "listen:47600")
        self.assertEqual((b["link_dials"], b["link_address"]), (True, "127.0.0.1:47500"))   # the scalars are the first link's

    def test_manifest_only_node_is_loopback_only(self):
        R = "redial off\n"
        C.manifest_only(self.manifest(R + MANIFEST))
        with self.assertRaises(C.ConfError) as cm:
            C.manifest_only(self.manifest(R + MANIFEST.replace("127.0.0.1 47500", "192.168.1.20 47500")))
        self.assertIn("auth none, a loopback-only test setting", cm.exception.text)

    def test_trust_args_limits_reach_the_mfa_table(self):
        import bees_trust_gen as T
        self.assertEqual(T.limits(self.write("bees.config", TRUST % ", {frame_size_max, 65536}, {args_len_max, 1024}, "
                                                                 "{term_depth_max, 5}")),
                         "{ max_bytes: 1025, max_depth: 5, max_length: 1024 }")


class CheckAtomManifestTests(unittest.TestCase):
    """`bees_config.py check`: any unit, under src/ or not, may write the atoms its own manifest lists (guide A1.2); nothing else."""

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d)
        import bees_config as BC
        self.BC = BC

    def put(self, name, text, d=None):
        path = os.path.join(d or self.d, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(text)
        return path

    def run_check(self, *units):
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = self.BC.check(list(units))
        return rc, buf.getvalue()

    UNIT = "module x;\nfn f() -> atom { :hub_in }\n"

    def test_listed_literal_passes(self):
        u = self.put("x.silica", self.UNIT)
        self.put("x.atoms", "# the unit's symbols\n\n  hub_in  # trailing\n")
        self.assertEqual(self.run_check(u), (0, ""))

    def test_unlisted_literal_fails(self):
        u = self.put("x.silica", self.UNIT + "fn g() -> atom { :other }\n")
        self.put("x.atoms", "hub_in\n")
        rc, out = self.run_check(u)
        self.assertEqual(rc, 1)
        self.assertIn(":other", out)
        self.assertNotIn(":hub_in", out)

    def test_no_manifest_fails(self):
        rc, out = self.run_check(self.put("x.silica", self.UNIT))
        self.assertEqual(rc, 1)
        self.assertIn(":hub_in", out)

    def test_manifest_beside_another_unit_does_not_leak(self):
        u = self.put("x.silica", self.UNIT)
        self.put("y.silica", "module y;\n")
        self.put("y.atoms", "hub_in\n")
        self.assertEqual(self.run_check(u)[0], 1)

    def test_symlinked_unit_uses_manifest_beside_the_real_path(self):
        real = self.put("real/x.silica", self.UNIT)
        self.put("real/x.atoms", "hub_in\n")
        link = os.path.join(self.d, "linkdir", "x.silica")
        os.makedirs(os.path.dirname(link))
        os.symlink(real, link)
        self.assertEqual(self.run_check(link), (0, ""))
        # a manifest beside the link only (not beside the real file) does not count
        real2 = self.put("real2/z.silica", self.UNIT)
        link2 = os.path.join(self.d, "linkdir", "z.silica")
        os.symlink(real2, link2)
        self.put("linkdir/z.atoms", "hub_in\n")
        self.assertEqual(self.run_check(link2)[0], 1)

    def test_unit_under_src_with_manifest_passes(self):
        unit = os.path.join(ROOT, "src", "shim", "zz_check_probe.silica")
        manifest = os.path.join(ROOT, "src", "shim", "zz_check_probe.atoms")
        try:
            with open(unit, "w") as fh:
                fh.write(self.UNIT)
            with open(manifest, "w") as fh:
                fh.write("hub_in\n")
            self.assertEqual(self.run_check(unit), (0, ""))
            # an atom the manifest does not list still fails there
            with open(unit, "a") as fh:
                fh.write("fn g() -> atom { :other }\n")
            rc, out = self.run_check(unit)
            self.assertEqual(rc, 1)
            self.assertIn(":other", out)
            # and through a symlink from outside src/ (the manifest beside the real path counts)
            link = os.path.join(self.d, "zz_check_probe.silica")
            os.symlink(unit, link)
            self.assertEqual(self.run_check(link)[0], 1)
        finally:
            for f in (unit, manifest):
                if os.path.exists(f):
                    os.remove(f)

    def test_fixed_atoms_not_extended_and_output_deterministic(self):
        before = set(self.BC.FIXED_ATOMS)
        u = self.put("x.silica", self.UNIT + "fn g() -> atom { :b_one }\nfn h() -> atom { :a_two }\n")
        self.put("x.atoms", "hub_in\n")
        first = self.run_check(u)
        self.assertEqual(first, self.run_check(u))
        self.assertEqual(set(self.BC.FIXED_ATOMS), before)
        self.assertLess(first[1].index(":b_one"), first[1].index(":a_two"))  # source order, not hash order


class MultiLinkGenerationTests(unittest.TestCase):
    """N2b: the hub of trials/n2_multilink generates per-peer proxies, and every registered name is in bees_atoms at compile time"""

    def test_hub_generation(self):
        hub = os.path.join(ROOT, "trials", "n2_multilink", "nodes", "hub")
        with tempfile.TemporaryDirectory() as d:
            cookie = os.path.join(d, "cookie")
            with open(cookie, "w") as f:
                f.write("c\n")
            os.chmod(cookie, 0o600)
            cfg = os.path.join(d, "bees.config")
            with open(os.path.join(hub, "bees.config")) as f:
                text = f.read().replace("../../cookie", cookie)
            with open(cfg, "w") as f:
                f.write(text)
            wire = os.path.join(hub, "node.wire")
            out = os.path.join(d, "out")
            os.makedirs(out)
            r = subprocess.run([sys.executable, os.path.join(HERE, "bees_config_beam.py"), "generate", "--config", cfg, "-o", out, wire],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            peers = open(os.path.join(out, "beam_peers.silica")).read()
            self.assertIn("fn start_proxies_p0(tx: actor_ref, mgr: actor_ref)", peers)
            self.assertIn("proxy_ans_a, bees_atoms@a_ans_a()", peers.split("fn start_proxies_p1")[0])
            self.assertIn("proxy_ans_c, bees_atoms@a_ans_c()", peers.split("fn start_proxies_p1")[1])
            self.assertNotIn("proxy_ans_c", peers.split("fn start_proxies_p1")[0].split("fn start_proxies_p0")[1])
            conf = open(os.path.join(out, "beam_conf.silica")).read()
            self.assertIn("fn listens() -> boolean { true }", conf)
            self.assertIn('fn listener_address() -> string { "listen:%d" }' % trial_ports.port("n2_multilink"), conf)
            r = subprocess.run([sys.executable, os.path.join(HERE, "bees_config.py"), "generate", "-o", out, "--config", cfg, wire,
                                os.path.join(hub, "node.atoms")], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            atoms = open(os.path.join(out, "bees_atoms.index")).read()
            for name in ("ans_a", "ans_c", "req_a", "req_c"):
                self.assertRegex(atoms, r"\t" + name + r"\n")


    def test_m3_hub_generation(self):
        """N2c: the M3 node's bees_peers has one link per peer line, the listener, per-peer reapers that report to a manager"""
        hub = os.path.join(ROOT, "trials", "m3_multilink", "nodes", "hub")
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "out")
            os.makedirs(out)
            r = subprocess.run([sys.executable, os.path.join(HERE, "bees_config.py"), "generate", "-o", out, "--config",
                                os.path.join(hub, "bees.config"), os.path.join(hub, "node.wire"), os.path.join(hub, "node.atoms")],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            peers = open(os.path.join(out, "bees_peers.silica")).read()
            self.assertIn("fn listens() -> boolean { true }", peers)
            self.assertIn('fn listener_address() -> string { "listen:%d" }' % trial_ports.port("m3_multilink"), peers)
            self.assertIn("fn start_proxies_p1(tx: actor_ref, mgr: actor_ref)", peers)
            self.assertIn("fn start_proxies(idx: int64, tx: actor_ref, mgr: actor_ref)", peers)
            self.assertIn("cast(st.mgr, (:bees, 2, 1, t, c)", peers)
            self.assertIn("stop_self(:normal)", peers.split("fn reaper_p1")[1].split("fn start_proxies_p1")[0])
            self.assertIn("fn link_dials_of(i: int64) -> boolean {", peers)
            self.assertIn("fn redial_on() -> boolean { false }", peers)
            self.assertNotIn("fn start_proxies(tx: actor_ref)", peers)


if __name__ == "__main__":
    unittest.main(verbosity=1)
