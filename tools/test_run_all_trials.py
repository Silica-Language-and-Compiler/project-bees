#!/usr/bin/env python3
"""Tests of the parallel runner's pure parts (tools/run_all_trials.py): the machines file, the skip of an unsupported platform,
the compile slots. Nothing is built or run, and no machine is contacted."""
import os
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import platform_id as P  # noqa: E402
import run_all_trials as R  # noqa: E402


def hosts_file(text):
    d = tempfile.mkdtemp()
    p = os.path.join(d, ".bees_build_hosts")
    with open(p, "w") as f:
        f.write(text)
    return p


class HostsFile(unittest.TestCase):
    def test_example_parses(self):
        hs = R.read_hosts(os.path.join(os.path.dirname(HERE), ".bees_build_hosts.example"))
        self.assertEqual(len(hs), 1)
        h = hs[0]
        self.assertEqual((h.platform, h.conn, h.path, h.openssl, h.jobs), ("linux_x86_64", "manager@aalang.org", "/opt/bees", "/opt/openssl", "2"))
        self.assertEqual(h.env()["OPENSSL_PREFIX"], "/opt/openssl")
        self.assertIn("SILICA_COMPILER", h.env())

    def test_errors_name_the_line(self):
        for text, word in (("linux_x86_64 manager@h /p\n", "expected"),
                           ("plan9 u@h /p - 2\n", "unknown platform"),
                           ("linux_x86_64 not-a-conn /p - 2\n", "not user@host"),
                           ("linux_x86_64 u@h rel/path - 2\n", "absolute"),
                           ("linux_x86_64 u@h /p - many\n", "jobs")):
            with self.assertRaises(ValueError) as c:
                R.read_hosts(hosts_file("# c\n" + text))
            self.assertIn(word, str(c.exception))
            self.assertIn(":2:", str(c.exception))

    def test_no_secrets(self):
        for bad in ("linux_x86_64 u@h /p - 2 password=hunter2\n", "linux_x86_64 u@h /p - 2 -----BEGIN OPENSSH PRIVATE KEY-----\n"):
            with self.assertRaises(ValueError) as c:
                R.read_hosts(hosts_file(bad))
            self.assertIn("no keys", str(c.exception))

    def test_only_allowed_env_tokens_pass(self):
        h = R.read_hosts(hosts_file("linux_x86_64 u@h /p - 2 LD_PRELOAD=/x SILICA_ROOT=/s\n"))[0]
        self.assertEqual(h.env(), {"SILICA_ROOT": "/s"})


class Skips(unittest.TestCase):
    def test_linux_runs_and_the_boards_are_skipped_with_a_reason(self):
        self.assertTrue(P.build_supported("linux_x86_64"))
        for pid in ("esp32s3", "nucleo"):
            self.assertFalse(P.build_supported(pid))
            self.assertIn("not supported yet", R.unsupported_reason(pid))


class CompilerChoice(unittest.TestCase):
    def test_the_compiler_of_the_environment_goes_on_the_make_command_line(self):
        # tools/silica.mk takes SILICA_COMPILER from the make command line only
        self.assertEqual(R.make_vars({"SILICA_COMPILER": "/s/binaries/silica-1"}), ["SILICA_COMPILER=/s/binaries/silica-1"])
        self.assertEqual(R.make_vars({"SILICA_ROOT": "/s"}), [])

    def test_make_takes_it_from_there_and_not_from_the_environment(self):
        root = os.path.dirname(HERE)
        mk = "BEES_ROOT := %s\ninclude %s/tools/silica.mk\nshow:\n\t@echo $(SILICA_COMPILER)\n" % (root, root)
        env = dict(os.environ, SILICA_COMPILER="/from/the/environment", SILICA_ROOT="/s")
        out = subprocess.run(["make", "-s", "-f", "-", "show"], input=mk, capture_output=True, text=True, env=env).stdout.strip()
        self.assertEqual(out, "/s/binaries/silica-compiler")
        out = subprocess.run(["make", "-s", "-f", "-", "show"] + R.make_vars(env), input=mk, capture_output=True, text=True, env=env).stdout.strip()
        self.assertEqual(out, "/from/the/environment")


class Slots(unittest.TestCase):
    def test_at_most_n_at_a_time(self):
        d = tempfile.mkdtemp()
        env = dict(os.environ, BEES_COMPILE_SLOTS="2", BEES_SLOT_DIR=os.path.join(d, "slots"))
        marks = os.path.join(d, "marks")
        os.makedirs(marks)
        # each command registers itself, counts the others that are registered, sleeps, unregisters
        script = ("m=%s; f=$m/$$; : > $f; n=$(ls $m | wc -l); echo $n >> %s/max; sleep 0.6; rm $f" % (marks, d))
        procs = [subprocess.Popen([sys.executable, os.path.join(HERE, "with_slot.py"), "sh", "-c", script], env=env) for _ in range(5)]
        t0 = time.time()
        for p in procs:
            self.assertEqual(p.wait(), 0)
        self.assertGreaterEqual(time.time() - t0, 1.5)   # 5 commands, 2 at a time, 0.6 s each: three rounds
        top = max(int(x) for x in open(os.path.join(d, "max")).read().split())
        self.assertLessEqual(top, 2)

    def test_without_limit_it_just_runs_and_passes_the_status(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith("BEES_")}
        r = subprocess.run([sys.executable, os.path.join(HERE, "with_slot.py"), "sh", "-c", "exit 7"], env=env)
        self.assertEqual(r.returncode, 7)


if __name__ == "__main__":
    unittest.main()
