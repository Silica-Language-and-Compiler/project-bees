#!/usr/bin/env python3
"""Check that nothing an application links depends on the TEST ONLY crate of the Rust TEMPUS extension.

  python3 layering_check.py WORKSPACE_DIR PATH_OF_cargo

The rule: the library crate (tempus) and the application example (tempus-node-example) do not depend on tempus-testing,
directly or through another crate, they depend on no crate outside this workspace at all, and no source file under
lib/ or driver/tempus-node-example/ names tempus_testing. The driver tempus-client is not in the rule: it makes TEST
ONLY tokens for the trials and links the crate on purpose. The dependencies are read from `cargo metadata --offline`,
the names from the source files. One line is printed; the exit status is 1 when the rule is broken.
"""
import json
import os
import re
import subprocess
import sys

TEST_ONLY = "tempus-testing"
CLEAN = ("tempus", "tempus-node-example")
CLEAN_DIRS = (os.path.join("lib", "tempus"), os.path.join("driver", "tempus-node-example"))


def main():
    here, cargo = sys.argv[1], sys.argv[2]
    dump = subprocess.run([cargo, "metadata", "--offline", "--format-version", "1", "--manifest-path", os.path.join(here, "Cargo.toml")],
                          capture_output=True, text=True)
    if dump.returncode != 0:
        print("FAIL: [rust layering] cargo metadata: " + dump.stderr.strip())
        return 1
    meta = json.loads(dump.stdout)
    members = set(meta["workspace_members"])
    deps = {p["name"]: [d["name"] for d in p["dependencies"]] for p in meta["packages"]}
    outside = sorted(p["name"] for p in meta["packages"] if p["id"] not in members)
    faults = ["the workspace depends on a crate outside itself: " + n for n in outside]
    for name in CLEAN:
        if name not in deps:
            faults.append("crate %s is not in the workspace" % name)
            continue
        seen, todo = set(), [name]
        while todo:
            for d in deps.get(todo.pop(), []):
                if d not in seen:
                    seen.add(d)
                    todo.append(d)
        if TEST_ONLY in seen:
            faults.append("crate %s depends on %s" % (name, TEST_ONLY))
        if name == "tempus" and seen:
            faults.append("the library crate has dependencies: " + ", ".join(sorted(seen)))
    files = 0
    for d in CLEAN_DIRS:
        for root, _, names in os.walk(os.path.join(here, d)):
            for n in names:
                if n.endswith(".rs") or n == "Cargo.toml":
                    files += 1
                    with open(os.path.join(root, n), encoding="utf-8") as f:
                        if re.search(r"tempus[_-]testing", f.read()):
                            faults.append("%s names %s" % (os.path.relpath(os.path.join(root, n), here), TEST_ONLY))
    if faults:
        for x in faults:
            print("FAIL: [rust layering] " + x)
        return 1
    print("rust layering: %d crates and %d files hold no dependency on %s, and the workspace depends on no crate outside itself" % (len(CLEAN), files, TEST_ONLY))
    return 0


if __name__ == "__main__":
    sys.exit(main())
