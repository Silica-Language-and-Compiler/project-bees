#!/usr/bin/env python3
"""C7: run the Python extension's own tests and write one line per test, in a fixed order, with nothing of the time
they took: tests.py BEES_ROOT. The exit code is 0 only when every test passed and none was skipped."""
import os
import sys
import unittest

ROOT = os.path.abspath(sys.argv[1])
EXT = os.path.join(ROOT, "example_tempus_clients", "python")
sys.path.insert(0, EXT)
os.chdir(ROOT)


def names(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from names(item)
        else:
            yield item


def main():
    bad = 0
    for module in ("test_bees_tempus_node", "test_bees_tempus_client"):
        suite = unittest.defaultTestLoader.loadTestsFromName(module)
        ids = sorted(t.id() for t in names(suite))       # before the run: a suite lets go of a test it has run
        result = unittest.TestResult()
        suite.run(result)
        failed = {t.id(): text for t, text in result.failures + result.errors}
        skipped = {t.id(): why for t, why in result.skipped}
        for test_id in ids:
            if test_id in failed:
                print("FAIL %s\n%s" % (test_id, failed[test_id]))
            elif test_id in skipped:
                print("SKIPPED %s: %s" % (test_id, skipped[test_id]))
            else:
                print("ok %s" % test_id)
        for test_id, text in failed.items():          # a failure outside a test (a module's set-up)
            if test_id not in ids:
                print("FAIL %s\n%s" % (test_id, text))
        bad += len(failed) + len(skipped)
        print("%s: %d tests, %d failed, %d skipped" % (module, result.testsRun, len(failed), len(skipped)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
