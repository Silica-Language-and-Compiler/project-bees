#!/usr/bin/env python3
"""Tests of the platform identifier / golden-name function (tools/platform_id.py) and the table of the trials' ports
(tools/trial_ports.py). Python 3, standard library only; nothing is built or run."""
import os
import platform
import re
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import platform_id as P  # noqa: E402
import trial_ports as T  # noqa: E402


# Linux goldens that do not exist, each with its reason (a Silica defect of development-plan/silica-defects.md, or a missing tool)
LINUX_GOLDEN_EXCEPTIONS = {
    # a missing tool: trials/c5_tempus_swift runs the Swift example client, and there is no Swift toolchain on the Linux machine
    "trials/c5_tempus_swift/dangerous_n.linux_x86_64.scout": "no Swift toolchain on Linux: the trial is skipped there",
    "trials/c5_tempus_swift/dangerous_p.linux_x86_64.scout": "no Swift toolchain on Linux: the trial is skipped there",
    "trials/c5_tempus_swift/swift.linux_x86_64.scout": "no Swift toolchain on Linux: the trial is skipped there",
    # a missing tool: trials/c6_tempus_kotlin runs the Kotlin example client, and there is no Kotlin compiler on the Linux machine
    "trials/c6_tempus_kotlin/tests.linux_x86_64.scout": "no Kotlin compiler on Linux: the trial fails there and says so",
    "trials/c6_tempus_kotlin/dangerous_k.linux_x86_64.scout": "no Kotlin compiler on Linux: the trial fails there and says so",
    "trials/c6_tempus_kotlin/dangerous_q.linux_x86_64.scout": "no Kotlin compiler on Linux: the trial fails there and says so",
    "trials/c6_tempus_kotlin/kotlin.linux_x86_64.scout": "no Kotlin compiler on Linux: the trial fails there and says so",
}


# The two-machine interchange trials (tools/bees_interchange.py): each scenario runs ONE node on each machine, so its goldens are
# NAME.here.<platform of the driver's machine>.scout and NAME.there.<platform of the remote machine>.scout, one platform each: a
# Mac golden there has no Linux twin of the same name. Their rule is interchange_problems() below, not the twin rule.
INTERCHANGE_LEAF = re.compile(r"^trials/x[0-9]+_interchange_[a-z0-9_]+/")


def interchange_problems(goldens):
    """goldens: paths of the interchange trials' goldens. Every scenario must have exactly one golden per side (here, there), and
    the two sides must be of different platforms (two machines)."""
    sides = {}
    out = []
    for g in goldens:
        d, f = os.path.split(g)
        parts = f.split(".")
        if len(parts) != 4 or parts[1] not in ("here", "there") or parts[2] not in P.PLATFORMS:
            out.append(f"{g}: an interchange golden is SCENARIO.here|there.PLATFORM_ID.scout")
            continue
        sides.setdefault((d, parts[0]), {}).setdefault(parts[1], []).append(parts[2])
    for (d, sc), by in sorted(sides.items()):
        for side in ("here", "there"):
            if len(by.get(side, [])) != 1:
                out.append(f"{d}/{sc}: {len(by.get(side, []))} goldens for side {side} (one is needed: the node of that machine)")
        if len(by.get("here", [])) == 1 and by.get("here") == by.get("there"):
            out.append(f"{d}/{sc}: both sides are {by['here'][0]}: an interchange scenario runs on two machines of different platforms")
    return out


def golden_files():
    """The goldens under trials/: git's list, or, in a tree without .git (a remote machine's synced copy), the files there."""
    files = subprocess.run(["git", "-C", ROOT, "ls-files", "trials"], capture_output=True, text=True).stdout.split()
    if not files:
        for dp, dn, fn in os.walk(os.path.join(ROOT, "trials")):
            dn[:] = [d for d in dn if d != ".fail"]
            files.extend(os.path.relpath(os.path.join(dp, f), ROOT) for f in fn)
    return [f for f in files if f.endswith(P.GOLDEN_EXTENSIONS)]


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
        goldens = golden_files()
        self.assertTrue(goldens)
        for g in goldens:
            self.assertIsNotNone(P.golden_platform(g), g)

    def test_make_and_python_agree(self):
        mk = subprocess.run(["make", "-s", "-f", "-", "show"], input="BEES_ROOT := %s\ninclude %s/tools/platform.mk\nshow:\n\t@echo $(BEES_PLATFORM_ID) $(BEES_PLATFORM)\n" % (ROOT, ROOT),
                            capture_output=True, text=True)
        self.assertEqual(mk.stdout.split(), [P.current_id(), P.native_dir()], mk.stderr)

    def test_build_switches(self):
        self.assertTrue(P.build_supported("macos_applesilicon"))
        self.assertTrue(P.build_supported("linux_x86_64"))   # the Linux port landed 2026-11-18
        self.assertFalse(P.build_supported("esp32s3"))
        self.assertFalse(P.build_supported("nucleo"))
        self.assertFalse(P.build_supported("plan9"))

    def test_a_platform_that_builds_has_its_directory(self):
        # the switch and native/<dir>/platform.mk go together, with one C file per function of bees_platform.h
        for pid, (d, _, _, builds) in P.PLATFORMS.items():
            mk = os.path.join(ROOT, "native", d, "platform.mk")
            self.assertEqual(os.path.exists(mk), builds, mk)
            if builds:
                for f in ("bees_platform_random.c", "bees_platform_md5.c"):
                    self.assertTrue(os.path.exists(os.path.join(ROOT, "native", d, f)), f"native/{d}/{f}")

    def test_selection_from_uname(self):
        saved, env = (platform.system, platform.machine), os.environ.pop("BEES_PLATFORM_ID", None)
        try:
            for s_, m_, pid, d in (("Darwin", "arm64", "macos_applesilicon", "macos"), ("Linux", "x86_64", "linux_x86_64", "linux")):
                platform.system, platform.machine = (lambda s_=s_: s_), (lambda m_=m_: m_)
                self.assertEqual(P.current_id(), pid)
                self.assertEqual(P.native_dir(), d)
            platform.system, platform.machine = (lambda: "Linux"), (lambda: "riscv64")
            with self.assertRaises(SystemExit):
                P.current_id()
        finally:
            platform.system, platform.machine = saved
            if env is not None:
                os.environ["BEES_PLATFORM_ID"] = env

    def test_each_platform_mk_sets_every_variable(self):
        # the same variable names in every platform.mk: a common Makefile may use any of them
        names = ("PLATFORM_CFLAGS", "PLATFORM_SRC_CFLAGS", "PLATFORM_ASFLAGS", "PLATFORM_LDFLAGS", "PLATFORM_NATIVE_SRCS", "PLATFORM_TRUST_SRCS",
                 "PLATFORM_NATIVE_NEEDS_CRYPTO", "PLATFORM_RPATH_FLAG", "PLATFORM_OPENSSL_DIRS", "PLATFORM_CLANG", "PLATFORM_SED_INPLACE",
                 "PLATFORM_LOCAL_IPV4")
        for pid, (d, _, _, builds) in P.PLATFORMS.items():
            if not builds:
                continue
            text = open(os.path.join(ROOT, "native", d, "platform.mk")).read()
            for n in names:
                self.assertRegex(text, r"(?m)^%s :?= ?" % n, f"native/{d}/platform.mk does not set {n}")

    def test_apple_only_text_stays_under_native_macos(self):
        # native/README.md's rule, checked over the common C and the Linux directory
        words = ("CommonCrypto", "CCRandomGenerateBytes", "CC_MD5", "mmacosx-version-min", "macos_version_min", "/opt/homebrew", "ipconfig")
        for top in ("src", "tls", "trust", "linux"):
            for dp, _, fn in os.walk(os.path.join(ROOT, "native", top)):
                for f in fn:
                    if f.endswith(".md"):
                        continue
                    text = open(os.path.join(dp, f), errors="replace").read()
                    for w in words:
                        self.assertNotIn(w, text, os.path.join(dp, f))

    def test_a_platform_golden_exists_beside_each_mac_golden(self):
        # every golden recorded on the Mac has its Linux counterpart, except those listed (with the reason) in LINUX_GOLDEN_EXCEPTIONS
        # (the two-machine interchange trials have one platform per side: test_interchange_goldens_pair_the_two_machines)
        mac = [g for g in golden_files() if P.golden_platform(g) == "macos_applesilicon" and not INTERCHANGE_LEAF.match(g)]
        self.assertTrue(mac)
        missing = []
        for g in mac:
            twin = g.replace(".macos_applesilicon.", ".linux_x86_64.")
            if not os.path.exists(os.path.join(ROOT, twin)) and twin not in LINUX_GOLDEN_EXCEPTIONS:
                missing.append(twin)
        self.assertEqual(missing, [])
        for twin in LINUX_GOLDEN_EXCEPTIONS:
            self.assertFalse(os.path.exists(os.path.join(ROOT, twin)), f"{twin} exists now: take it off LINUX_GOLDEN_EXCEPTIONS")


    def test_interchange_goldens_pair_the_two_machines(self):
        self.assertEqual(interchange_problems([g for g in golden_files() if INTERCHANGE_LEAF.match(g)]), [])
        # the rule itself: one golden per side, of different platforms; nothing else under an interchange trial
        t = "trials/x1_interchange_beam/"
        ok = [t + "s.here.macos_applesilicon.scout", t + "s.there.linux_x86_64.scout"]
        self.assertEqual(interchange_problems(ok), [])
        self.assertTrue(interchange_problems(ok[:1]))                                             # the other machine's node is missing
        self.assertTrue(interchange_problems([ok[0], t + "s.there.macos_applesilicon.scout"]))    # one machine twice
        self.assertTrue(interchange_problems(ok + [t + "s.here.linux_x86_64.scout"]))             # two goldens for one side
        self.assertTrue(interchange_problems([t + "s.a.macos_applesilicon.scout"]))               # not a side
        self.assertTrue(INTERCHANGE_LEAF.match(ok[0]))
        self.assertFalse(INTERCHANGE_LEAF.match("trials/n2_live/bees_dials.bees.macos_applesilicon.scout"))


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
