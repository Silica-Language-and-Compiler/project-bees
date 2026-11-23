#!/usr/bin/env python3
"""Check that nothing an application links depends on the TEST ONLY project of the C# TEMPUS extension.

  python3 layering_check.py EXTENSION_DIR

The rule: the library project (lib/BeesTempus.csproj) and the driver project (driver/BeesTempusDriver.csproj) do not
reference testing/BeesTempusTesting.csproj, directly or through another project; neither references any package; no
source file under lib/ or driver/ names the namespace Bees.Tempus.Testing; and no source file under lib/ or driver/
holds one of the words that only test code has a use for (a fixed seed, a token maker, the test-only frames tick and
clock as frame kinds). The project references are read from the .csproj files, which are plain XML. One line is
printed; the exit status is 1 when the rule is broken.
"""
import os
import re
import sys
import xml.etree.ElementTree as ET

TEST_ONLY = "BeesTempusTesting"
TEST_NAMESPACE = "Bees.Tempus.Testing"
CLEAN = ("lib/BeesTempus.csproj", "driver/BeesTempusDriver.csproj")
CLEAN_DIRS = ("lib", "driver")
# what only test code writes: making a token, a key from a fixed seed, and the two test-only frames as kinds to send or serve
FORBIDDEN = (r"\bMakeToken\b", r"\bTokenPayload\b", r"\bFixtures\b", r'TAtom\("tick"\)', r'TAtom\("clock"\)', r'case "tick"', r'case "clock"')


def references(path):
    """(project references as normalised paths, package references) of one .csproj"""
    root = ET.parse(path).getroot()
    here = os.path.dirname(path)
    projects = [os.path.normpath(os.path.join(here, e.get("Include").replace("\\", "/"))) for e in root.iter("ProjectReference")]
    packages = [e.get("Include") for e in root.iter("PackageReference")]
    return projects, packages


def main():
    here = os.path.abspath(sys.argv[1])
    faults = []
    for name in CLEAN:
        first = os.path.join(here, name)
        if not os.path.isfile(first):
            faults.append("%s is missing" % name)
            continue
        seen, todo = set(), [first]
        while todo:
            p = todo.pop()
            projects, packages = references(p)
            for pkg in packages:
                faults.append("%s references the package %s" % (os.path.relpath(p, here), pkg))
            for d in projects:
                if d not in seen:
                    seen.add(d)
                    todo.append(d)
        if any(os.path.splitext(os.path.basename(d))[0] == TEST_ONLY for d in seen):
            faults.append("%s depends on %s" % (name, TEST_ONLY))
    files = 0
    for d in CLEAN_DIRS:
        for root, _, names in os.walk(os.path.join(here, d)):
            for n in sorted(names):
                if not n.endswith(".cs"):
                    continue
                files += 1
                rel = os.path.relpath(os.path.join(root, n), here)
                with open(os.path.join(root, n), encoding="utf-8") as f:
                    text = f.read()
                if TEST_NAMESPACE in text:
                    faults.append("%s names %s" % (rel, TEST_NAMESPACE))
                code = "\n".join(ln for ln in text.split("\n") if not ln.lstrip().startswith("//"))
                for pattern in FORBIDDEN:
                    if re.search(pattern, code):
                        faults.append("%s holds test-only code (%s)" % (rel, pattern))
    if faults:
        for x in faults:
            print("FAIL: [csharp layering] " + x)
        return 1
    print("csharp layering: %d projects and %d source files hold no dependency on %s, no package and no test-only code" % (len(CLEAN), files, TEST_ONLY))
    return 0


if __name__ == "__main__":
    sys.exit(main())
