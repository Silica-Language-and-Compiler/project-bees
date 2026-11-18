#!/usr/bin/env python3
"""Tests of the pure parts of the two-machine interchange driver (tools/bees_interchange.py): the scenario table against the port
table, the normalisation of the outputs, the choice of the remote machine, and the clean skip without a hosts file. Python 3,
standard library only; nothing is built, no machine is contacted."""
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import bees_interchange as X  # noqa: E402
import run_all_trials as R  # noqa: E402
import trial_ports as T  # noqa: E402


class Scenarios(unittest.TestCase):
    def test_every_port_is_in_its_trial_block(self):
        for s in X.scenarios():
            ports = [p for _, p in s["forwards"]] + ([s["direct"]] if s["direct"] else [])
            self.assertTrue(ports, s["name"])
            for p in ports:
                self.assertEqual(T.owner(p), s["trial"], f"{s['name']}: port {p}")

    def test_names_are_unique_and_both_directions_exist(self):
        names = [(s["trial"], s["name"]) for s in X.scenarios()]
        self.assertEqual(len(names), len(set(names)))
        for trial in X.TRIALS:
            mine = [n for t, n in names if t == trial]
            self.assertTrue(any(n.startswith("here_") for n in mine) and any(n.startswith("there_") for n in mine), trial)

    def test_a_scenario_is_direct_or_forwarded_and_its_nodes_are_built_where_they_run(self):
        for s in X.scenarios():
            self.assertNotEqual(bool(s["direct"]), bool(s["forwards"]), s["name"])   # one network path, said in `path`
            self.assertIn("direct" if s["direct"] else "ssh", s["path"])
            placed = [s[k] for k in ("listener", "dialer", "bees", "server", "client") if k in s]
            self.assertTrue(placed)
            for side, node, exe in placed:
                self.assertIn(exe, X.NODES[s["trial"]][side][node], s["name"])
            if s["kind"] != "erl":
                self.assertEqual({p[0] for p in placed}, {"here", "there"}, s["name"])   # one node on each machine
            else:
                self.assertEqual(s["stock"], X.other(s["bees"][0]))

    def test_here_address_runs_that_direction_directly(self):
        # --here-address: only the BEES-with-BEES scenarios in which the remote dials this machine, without a forward, under their own names
        direct = X.scenarios("203.0.113.7")
        self.assertEqual(sorted((s["trial"], s["name"]) for s in direct),
                         [(X.X1, "there_dials_direct"), (X.X2, "there_calls_direct"), (X.X2, "there_unlisted_direct"), (X.X2, "there_wrong_pin_direct")])
        for s in direct:
            self.assertEqual(s["forwards"], [])
            self.assertEqual(T.owner(s["direct_back"]), s["trial"])
            self.assertIn("direct: ", s["path"])
            self.assertIn("HERE_IPV4", s["path"])
        ordinary = {s["name"] for s in X.scenarios()}
        self.assertFalse(ordinary & {s["name"] for s in direct})     # their goldens are their own
        self.assertEqual(X.norm_trust(["listen 203.0.113.7:1"], 0, "", "", "203.0.113.7"), ["listen HERE_IPV4:1", "exit=0"])

    def test_a_stock_node_is_never_dialed_directly(self):
        for s in X.scenarios():
            if s["kind"] == "erl":
                self.assertIsNone(s["direct"])

    def test_node_directories_exist(self):
        for trial, sides in X.NODES.items():
            self.assertFalse(os.path.exists(os.path.join(ROOT, "trials", trial, "Makefile")), "an interchange trial is not a leaf of make integrate")
            for side, nodes in sides.items():
                for node in nodes:
                    self.assertTrue(os.path.isfile(os.path.join(ROOT, "trials", trial, "nodes", node, "Makefile")), f"{trial}/{node}")

    def test_the_ordinary_runner_does_not_list_them(self):
        for trial in X.TRIALS:
            self.assertNotIn(trial, R.leaves())


class Normalise(unittest.TestCase):
    def test_no_machine_is_named(self):
        out = X.norm_trust(["[bees] resolve box.example.org: ok 203.0.113.9", "actor 0x7ff01234abcd", ""], 0, "box.example.org", "203.0.113.9")
        self.assertEqual(out, ["[bees] resolve THERE_HOST: ok THERE_IPV4", "actor 0xADDR", "exit=0"])

    def test_root_exit_line_is_removed_wherever_it_lands(self):
        out = X.norm_trust(["client: answer seq [silica] root actor exited (no supervisor)", "1", "[silica] root actor exited (no supervisor)", "done"], 0)
        self.assertEqual(out, ["client: answer seq 1", "done", "exit=0"])

    def test_beam_pair_stops_at_the_marker_and_drops_the_racy_lines(self):
        lines = ["banner", "[bees audit] net ticks seen (1 yes, 0 no) - 0", "dialer: answered op=ans n=68", "[bees audit] link down, proxies ended; reason closed 1", "proxy ended (killed)"]
        self.assertEqual(X.norm_beam_pair(lines, 0, "answered op=ans n=68"), ["banner", "dialer: answered op=ans n=68", "exit=0"])
        self.assertEqual(X.norm_beam_pair(["banner"], "timeout", "never"), ["banner", "exit=timeout"])

    def test_golden_names_carry_the_side_and_the_platform(self):
        self.assertTrue(X.golden_path(X.X1, "here_dials", "there", "linux_x86_64").endswith("trials/x1_interchange_beam/here_dials.there.linux_x86_64.scout"))


class Hosts(unittest.TestCase):
    def test_skipped_cleanly_without_a_hosts_file(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = X.main(["x", "--hosts-file", os.path.join(tempfile.gettempdir(), "no-such-bees-hosts-file")])
        self.assertEqual(rc, 0)
        self.assertIn("skipped: no remote", buf.getvalue())

    def test_the_partner_is_another_platform_that_builds(self):
        H = R.Host
        hosts = [H("esp32s3", "u@a", "/x", "-", "-", "", 1), H("macos_applesilicon", "u@b", "/x", "-", "-", "", 2), H("linux_x86_64", "u@c", "/x", "-", "-", "", 3)]
        self.assertEqual(X.pick_host(hosts, "macos_applesilicon").conn, "u@c")
        self.assertIsNone(X.pick_host(hosts[:2], "macos_applesilicon"))

    def test_skipped_when_the_file_names_no_partner(self):
        with tempfile.NamedTemporaryFile("w", suffix=".hosts", delete=False) as f:
            f.write("esp32s3 u@board /opt/bees - -\n")
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = X.main(["x", "--hosts-file", f.name])
            self.assertEqual(rc, 0)
            self.assertIn("skipped: no remote", buf.getvalue())
        finally:
            os.remove(f.name)


if __name__ == "__main__":
    unittest.main()
