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
    %(clock)s
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
           key=KEY, jmax=800, test="", clock=None):
    if clock is None:
        clock = CLOCK
    return TEMPUS % {"role": role, "addr": addr, "sentinels": sentinels, "cap": cap, "len": length, "key": key,
                     "jmax": jmax, "test": test, "clock": clock}


# the clock's choices as the trials pass them (ruling NQ-22 of 2026-11-20): follow, pause, read once a second
CLOCK = "{clock_back, follow}, {clock_fail, pause}, {clock_read_ms, 1000},"


def clock(back="follow", fail="pause", read="1000", limit=None):
    parts = []
    if back is not None:
        parts.append("{clock_back, %s}" % back)
    if limit is not None:
        parts.append("{clock_back_limit_s, %s}" % limit)
    if fail is not None:
        parts.append("{clock_fail, %s}" % fail)
    if read is not None:
        parts.append("{clock_read_ms, %s}" % read)
    return "".join(p + ", " for p in parts)


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

    def test_control_test_only_is_no_key_any_more(self):
        # owner's ruling of 2026-11-20 on OQ-20: the test frames are in a unit only a test program lists in its build;
        # no configuration turns them on, so the old key is refused with either value, on any address
        for value in ("true", "false"):
            for addr in ("127.0.0.1", "0.0.0.0"):
                self.refused("[{mode, tempus}, %s]." % tempus(addr=addr, test=",\n    {control_test_only, %s}" % value),
                             "tempus.control_test_only: no such key any more")
        self.assertNotIn("control_test_only", T.validate(self.write("[{mode, tempus}, %s]." % tempus()))["tempus"])

    def conf(self, **kw):
        return "[{mode, tempus}, %s]." % tempus(clock=clock(**kw))

    def test_clock_choices_are_read(self):
        v = T.validate(self.write(self.conf()))["tempus"]
        self.assertEqual((v["clock_back"], v["clock_fail"], v["clock_read_ms"]), ("follow", "pause", 1000))
        self.assertNotIn("clock_back_limit_s", v)
        for back in ("follow", "hold"):
            for fail in ("continue", "pause"):
                v = T.validate(self.write(self.conf(back=back, fail=fail)))["tempus"]
                self.assertEqual((v["clock_back"], v["clock_fail"]), (back, fail))
        v = T.validate(self.write(self.conf(back="stop", limit=30, fail="continue", read=250)))["tempus"]
        self.assertEqual((v["clock_back"], v["clock_back_limit_s"], v["clock_fail"], v["clock_read_ms"]),
                         ("stop", 30, "continue", 250))

    def test_clock_choices_have_no_default(self):
        self.refused(self.conf(back=None), "tempus.clock_back: required (no default)")
        self.refused(self.conf(fail=None), "tempus.clock_fail: required (no default)")
        self.refused(self.conf(read=None), "tempus.clock_read_ms: required (no default)")
        self.refused(self.conf(back="stop"), "tempus.clock_back_limit_s: required when clock_back is stop")

    def test_clock_choices_closed_sets(self):
        self.refused(self.conf(back="ignore"), "expected one of follow, hold, stop")
        self.refused(self.conf(back='"follow"'), "expected one of follow, hold, stop")
        self.refused(self.conf(back="1"), "expected one of follow, hold, stop")
        self.refused(self.conf(fail="stop"), "expected one of continue, pause")
        self.refused(self.conf(fail="true"), "expected one of continue, pause")

    def test_clock_limit_only_under_stop(self):
        for back in ("follow", "hold"):
            self.refused(self.conf(back=back, limit=30), "remove clock_back_limit_s")
        for limit in (0, 86400):
            v = T.validate(self.write(self.conf(back="stop", limit=limit)))["tempus"]
            self.assertEqual(v["clock_back_limit_s"], limit)
        self.refused(self.conf(back="stop", limit=-1), "clock_back_limit_s")
        self.refused(self.conf(back="stop", limit=86401), "clock_back_limit_s")
        self.refused(self.conf(back="stop", limit="none"), "clock_back_limit_s")

    def test_clock_read_bounds(self):
        for ms in (100, 60000):
            self.assertEqual(T.validate(self.write(self.conf(read=ms)))["tempus"]["clock_read_ms"], ms)
        self.refused(self.conf(read=99), "clock_read_ms")
        self.refused(self.conf(read=60001), "clock_read_ms")

    def test_clock_keys_given_twice(self):
        self.refused("[{mode, tempus}, %s]." % tempus(clock=CLOCK + " {clock_back, hold},"), "clock_back")


if __name__ == "__main__":
    unittest.main()
