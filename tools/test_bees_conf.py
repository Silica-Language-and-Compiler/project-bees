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

SPEC = os.path.join(ROOT, "development-plan", "bees-config-file.md")

MANIFEST = """node   bees@localhost
peer   peer@localhost 127.0.0.1 47500 dial
remote outbox @ peer@localhost cast { op: atom, n: int64, s: string }
local  inbox cast { op: atom, n: int64 }
"""
BEAM = """[ {mode, beam},
  {node, [{name, "bees@localhost"}]},
  {beam, [{transport, tcp}, {auth, none}, {listen_address, "127.0.0.1"}%s]} ]."""
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
        listen = MANIFEST.replace("47500 dial", "47500 listen")
        b = self.conf(cookie.replace('"127.0.0.1"', '"0.0.0.0"') % ", {epmd, none}, {listen_port, 47500}",
                      manifest=self.manifest(listen))["beam"]
        self.assertEqual(b["link_address"], "listen:any:47500")            # every IPv4 interface: the carrier's listen:any
        b = self.conf(cookie % ", {epmd, none}, {listen_port, 47500}", manifest=self.manifest(listen))["beam"]
        self.assertEqual(b["link_address"], "listen:47500")                # 127.0.0.1
        self.refused(cookie.replace('"127.0.0.1"', '"192.168.1.20"') % "", "beam.listen_address",
                     "192.168.1.20 is not built yet: the language's (:tcp) carrier binds only 127.0.0.1")
        self.refused(cookie.replace('"127.0.0.1"', '"::1"') % "", "beam.listen_address", "is not built yet")
        b = self.conf(cookie % ', {peers, [{"peer@localhost", [{host, "192.168.1.20"}, {port, 4370}]}]}')["beam"]
        self.assertEqual((b["link_address"], b["link_host_kind"]), ("192.168.1.20:4370", "ipv4"))
        b = self.conf(cookie % ', {peers, [{"peer@localhost", [{host, "localhost"}, {port, 4370}]}]}')["beam"]
        self.assertEqual(C.m3_link({"beam": b}, None)["link_resolve"], True)  # a name: resolved at boot by the edge
        self.refused(cookie % ', {peers, [{"peer@localhost", [{host, "::1"}, {port, 4370}]}]}', "beam.peers.peer@localhost.host",
                     "dials IPv4 literals only")
        self.refused(cookie % ', {peers, [{"peer@localhost", [{host, "localhost"}, {port, epmd}]}]}',
                     "beam.peers.peer@localhost.host", "is a name and the port is epmd")

    def test_manifest_only_node_is_loopback_only(self):
        C.manifest_only(self.manifest())
        with self.assertRaises(C.ConfError) as cm:
            C.manifest_only(self.manifest(MANIFEST.replace("127.0.0.1 47500", "192.168.1.20 47500")))
        self.assertIn("auth none, a loopback-only test setting", cm.exception.text)

    def test_trust_args_limits_reach_the_mfa_table(self):
        import bees_trust_gen as T
        self.assertEqual(T.limits(self.write("bees.config", TRUST % ", {frame_size_max, 65536}, {args_len_max, 1024}, "
                                                                 "{term_depth_max, 5}")),
                         "{ max_bytes: 1025, max_depth: 5, max_length: 1024 }")


if __name__ == "__main__":
    unittest.main(verbosity=1)
