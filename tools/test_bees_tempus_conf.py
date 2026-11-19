#!/usr/bin/env python3
"""Tests of tools/bees_tempus_conf.py (T7): the three SEMP mode spellings, the tempus section's table and bounds
(development-plan/tempus-design.md section 11), and the trust part of a tempus-trust file handed to tools/bees_conf.py."""
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bees_conf as C  # noqa: E402
import bees_tempus_conf as T  # noqa: E402

KEY = "00" * 32
TEMPUS = """{tempus, [
    {role, %(role)s},
    {listen_address, "%(addr)s"},
    {port, 24300},
    %(sentinels)s
    {edge, [{capacity, %(cap)d}, {shuffle_length, %(len)d}, {tick_ms, 1000}]},
    {bridge, [{capacity, 4}, {shuffle_length, 2}, {tick_ms, 1000}]},
    {sentinel, [{capacity, 4}, {shuffle_length, 2}, {tick_ms, 1000}]},
    {producer_key, {"k1", "%(key)s"}},
    {identity_keyfile, "id-key.pem"},
    {identity_certfile, "id.pem"},
    {shuffle_timeout_ms, 2000},
    {inflight_max, 4},
    {clock_skew_ms, 10000},
    {join_retry_initial_ms, 200},
    {join_retry_max_ms, %(jmax)d}%(test)s
  ]}"""
TRUST = """{trust, [
    {port, 24301},
    {listen_address, "127.0.0.1"},
    {tls_opts, [{certfile, "../../trials/n4_trust_tls/certs/b.pem"}, {keyfile, "../../trials/n4_trust_tls/certs/b-key.pem"}]},
    {whitelist_cert_dir, "../../trials/n4_trust_tls/certs"},
    {call_timeout_ms, 2000}
  ]}"""


def tempus(role="edge", addr="127.0.0.1", sentinels='{sentinels, [{"127.0.0.1", 24310, "s.pem"}]},', cap=4, length=3,
           key=KEY, jmax=800, test=""):
    return TEMPUS % {"role": role, "addr": addr, "sentinels": sentinels, "cap": cap, "len": length, "key": key,
                     "jmax": jmax, "test": test}


class TempusConf(unittest.TestCase):
    def setUp(self):
        # inside the tree (tools/), because the trust part's certificate paths are checked relative to the file
        self.dir = tempfile.mkdtemp(dir=HERE, prefix=".tempus_conf_test_")

    def tearDown(self):
        shutil.rmtree(self.dir)

    def write(self, text):
        p = os.path.join(self.dir, "bees.config")
        with open(p, "w") as f:
            f.write(text)
        return p

    def refused(self, text, part):
        with self.assertRaises(C.ConfError) as e:
            T.validate(self.write(text))
        self.assertIn(part, e.exception.text)

    def test_mode_tempus(self):
        v = T.validate(self.write("[{mode, tempus}, %s]." % tempus()))
        self.assertEqual(v["mode"], "tempus")
        self.assertEqual(v["tempus"]["role"], "edge")
        self.assertEqual(v["tempus"]["listener"], "listen:24300")
        self.assertEqual(v["tempus"]["edge"], {"capacity": 4, "shuffle_length": 3, "tick_ms": 1000})
        self.assertEqual(v["tempus"]["edge_spec"], "none")
        self.assertIsNone(v["trust"])

    def test_mode_tempus_trust_bare_and_quoted(self):
        for spelling in ("tempus-trust", "'tempus-trust'"):
            v = T.validate(self.write("[{mode, %s}, %s, %s]." % (spelling, TRUST, tempus(role="bridge"))))
            self.assertEqual(v["mode"], "tempus-trust")
            self.assertEqual(v["tempus"]["role"], "bridge")
            self.assertTrue(v["trust"]["active"])

    def test_bare_spelling_only_as_mode(self):
        self.refused("[{mode, tempus}, %s]." % tempus(role="tempus-trust"), "syntax")

    def test_section_and_mode_agree(self):
        self.refused("[{mode, trust}, %s, %s]." % (TRUST, tempus()), "a tempus section in a trust node")
        self.refused("[{mode, tempus}].", "required under mode tempus")
        self.refused("[{mode, tempus}, %s]." % tempus(role="bridge"), "bridge needs mode tempus-trust")
        self.refused("[{mode, temp}].", "expected beam, trust, tempus or tempus-trust")

    def test_bounds(self):
        self.refused("[{mode, tempus}, %s]." % tempus(cap=257), "257 is above 256")
        self.refused("[{mode, tempus}, %s]." % tempus(length=5), "above the capacity 4")
        self.refused("[{mode, tempus}, %s]." % tempus(key="00" * 31), "32 bytes")
        self.refused("[{mode, tempus}, %s]." % tempus(jmax=150), "below join_retry_initial_ms")

    def test_sentinels(self):
        self.refused("[{mode, tempus}, %s]." % tempus(sentinels=""), "required unless the node is the first sentinel")
        v = T.validate(self.write("[{mode, tempus}, %s]." % tempus(role="sentinel", sentinels="")))
        self.assertEqual(v["tempus"]["sentinels"], [])

    def test_control_test_only_loopback(self):
        v = T.validate(self.write("[{mode, tempus}, %s]." % tempus(test=",\n    {control_test_only, true}")))
        self.assertTrue(v["tempus"]["control_test_only"])
        self.refused("[{mode, tempus}, %s]." % tempus(addr="0.0.0.0", test=",\n    {control_test_only, true}"),
                     "true only with a loopback listen_address")


if __name__ == "__main__":
    unittest.main()
