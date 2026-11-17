#!/usr/bin/env python3
"""Tests of the platform identifier / golden-name function (tools/platform_id.py) and the table of the trials' ports
(tools/trial_ports.py). Python 3, standard library only; nothing is built or run."""
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import platform_id as P  # noqa: E402
import trial_ports as T  # noqa: E402


class GoldenNames(unittest.TestCase):
    def test_infix_before_extension(self):
        self.assertEqual(P.golden_name("scenario.a.scout", "macos_applesilicon"), "scenario.a.macos_applesilicon.scout")
        self.assertEqual(P.golden_name("hub.scout", "macos_applesilicon"), "hub.macos_applesilicon.scout")
        self.assertEqual(P.golden_name("x.golden_fail", "linux_x86_64"), "x.linux_x86_64.golden_fail")
        self.assertEqual(P.golden_name("trials/t/redial.check.scout", "linux_x86_64"), "trials/t/redial.check.linux_x86_64.scout")

    def test_refuses_non_goldens_and_double_infix(self):
        for bad in ("a.sout", "a", "a.txt"):
            with self.assertRaises(ValueError):
                P.golden_name(bad, "linux_x86_64")
        with self.assertRaises(ValueError):
            P.golden_name("a.linux_x86_64.scout", "linux_x86_64")

    def test_platform_of_a_golden(self):
        self.assertEqual(P.golden_platform("a.b.macos_applesilicon.scout"), "macos_applesilicon")
        self.assertIsNone(P.golden_platform("a.b.scout"))
        self.assertIsNone(P.golden_platform("a.sout"))

    def test_environment_overrides(self):
        old = os.environ.get("BEES_PLATFORM_ID")
        os.environ["BEES_PLATFORM_ID"] = "linux_x86_64"
        try:
            self.assertEqual(P.current_id(), "linux_x86_64")
            self.assertEqual(P.golden_name("a.scout"), "a.linux_x86_64.scout")
        finally:
            if old is None:
                del os.environ["BEES_PLATFORM_ID"]
            else:
                os.environ["BEES_PLATFORM_ID"] = old

    def test_every_tracked_golden_carries_a_platform(self):
        files = subprocess.run(["git", "-C", ROOT, "ls-files", "trials"], capture_output=True, text=True).stdout.split()
        goldens = [f for f in files if f.endswith(P.GOLDEN_EXTENSIONS)]
        self.assertTrue(goldens)
        for g in goldens:
            self.assertIsNotNone(P.golden_platform(g), g)

    def test_make_and_python_agree(self):
        mk = subprocess.run(["make", "-s", "-f", "-", "show"], input="BEES_ROOT := %s\ninclude %s/tools/platform.mk\nshow:\n\t@echo $(BEES_PLATFORM_ID) $(BEES_PLATFORM)\n" % (ROOT, ROOT),
                            capture_output=True, text=True)
        self.assertEqual(mk.stdout.split(), [P.current_id(), P.native_dir()], mk.stderr)

    def test_linux_build_switch(self):
        self.assertTrue(P.build_supported("macos_applesilicon"))
        self.assertFalse(P.build_supported("linux_x86_64"))   # flips when the Linux port lands


class Ports(unittest.TestCase):
    def test_table_is_consistent(self):
        self.assertEqual(T.problems_in_table(), [])

    def test_blocks_do_not_overlap(self):
        spans = sorted((b, t) for t, (b, _) in T.TABLE.items())
        for (b1, t1), (b2, t2) in zip(spans, spans[1:]):
            self.assertLessEqual(b1 + T.BLOCK, b2, f"{t1} / {t2}")

    def test_port_and_owner(self):
        self.assertEqual(T.port("n3_trust", 3), 22403)
        self.assertEqual(T.owner(22403), "n3_trust")
        self.assertIsNone(T.owner(47311))
        with self.assertRaises(ValueError):
            T.port("n3_trust", 100)
        with self.assertRaises(KeyError):
            T.port("no_such_trial")

    def test_overlap_is_detected(self):
        saved = dict(T.TABLE)
        try:
            T.TABLE["x"] = (T.base("n3_trust") + 50, "clash")
            self.assertTrue(T.problems_in_table())
        finally:
            T.TABLE.clear()
            T.TABLE.update(saved)

    def test_foreign_port_in_a_leaf_is_detected(self):
        self.assertEqual(T.problems_in_text("n3_trust", "peer a@h 127.0.0.1 22400 dial\nlisten:22401\n{port, 22403}\n"), [])
        bad = T.problems_in_text("n3_trust", "peer a@h 127.0.0.1 22500 dial\n")
        self.assertEqual(len(bad), 1)
        self.assertIn("n4_trust_tls", bad[0])
        self.assertTrue(T.problems_in_text("n3_trust", 'x "127.0.0.1:29999"'))

    def test_every_leaf_keeps_to_its_block(self):
        self.assertEqual(T.problems_in_leaves(), [])

    def test_every_trial_with_a_listener_is_in_the_table(self):
        # a leaf whose files name a listen address or a listen_port must be in the table
        out = subprocess.run(["git", "-C", ROOT, "grep", "-lE", r"listen:[0-9]|listen_port|trust_servers|peer .* listen$", "--", "trials"],
                             capture_output=True, text=True).stdout.split()
        leaves = {f.split("/")[1] for f in out}
        for leaf in leaves:
            self.assertTrue(leaf in T.TABLE or leaf in T.DATA_ONLY, f"{leaf} listens but has no ports in tools/trial_ports.py")


if __name__ == "__main__":
    unittest.main()
