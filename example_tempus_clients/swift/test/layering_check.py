#!/usr/bin/env python3
"""Check that nothing an application links depends on the TEST ONLY target of the Swift TEMPUS extension.

  python3 layering_check.py PACKAGE_DIR

The rule: the library targets (TempusClient, TempusNode) and the application example (tempus-node-example) do not
depend on TempusClientTesting, directly or through another target, and no source file under lib/ or
driver/tempus-node-example/ imports it. The driver tempus-client is not in the rule: it makes TEST ONLY tokens for the
trials and links the target on purpose. The dependencies are read from `swift package dump-package`, the imports from
the source files. One line is printed; the exit status is 1 when the rule is broken.
"""
import json
import os
import re
import subprocess
import sys

TEST_ONLY = "TempusClientTesting"
CLEAN = ("TempusClient", "TempusNode", "tempus-node-example")
CLEAN_DIRS = ("lib", os.path.join("driver", "tempus-node-example"))


def main():
    here = sys.argv[1]
    dump = subprocess.run(["swift", "package", "--package-path", here, "--disable-sandbox", "dump-package"],
                          capture_output=True, text=True)
    if dump.returncode != 0:
        print("FAIL: [swift layering] swift package dump-package: " + dump.stderr.strip())
        return 1
    deps = {}
    for t in json.loads(dump.stdout)["targets"]:
        deps[t["name"]] = [n for d in t.get("dependencies", []) for v in d.values() for n in v[:1] if isinstance(n, str)]
    faults = []
    for name in CLEAN:
        if name not in deps:
            faults.append("target %s is not in Package.swift" % name)
            continue
        seen, todo = set(), [name]
        while todo:
            for d in deps.get(todo.pop(), []):
                if d not in seen:
                    seen.add(d)
                    todo.append(d)
        if TEST_ONLY in seen:
            faults.append("target %s depends on %s" % (name, TEST_ONLY))
    files = 0
    for d in CLEAN_DIRS:
        for root, _, names in os.walk(os.path.join(here, d)):
            for n in names:
                if n.endswith(".swift"):
                    files += 1
                    with open(os.path.join(root, n), encoding="utf-8") as f:
                        if re.search(r"^\s*(@\w+\s+)*import\s+" + TEST_ONLY + r"\b", f.read(), re.M):
                            faults.append("%s imports %s" % (os.path.relpath(os.path.join(root, n), here), TEST_ONLY))
    if faults:
        for x in faults:
            print("FAIL: [swift layering] " + x)
        return 1
    print("swift layering: %d targets and %d source files hold no dependency on %s" % (len(CLEAN), files, TEST_ONLY))
    return 0


if __name__ == "__main__":
    sys.exit(main())
