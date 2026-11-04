#!/usr/bin/env python3
"""The BEES conformance kit runner (contract/conformance/README.md). Python 3, standard library only.

    conformance.py list
    conformance.py check-kit                 every program's `compare` reference lowering, taken from the
                                             recorded golden (.scout) of its trial leaf, passes the filter and
                                             equals expected.out. No build, no run. Run it after changing the
                                             kit or a reference lowering.
    conformance.py run LEAF ENTRY PROGRAM    build and run ENTRY in the trial-style leaf directory LEAF
                                             (make -C LEAF run), then compare it with PROGRAM's expected.out
                                             (PROGRAM is an id such as C02 or a full directory name).
    conformance.py compare OUTFILE PROGRAM   compare an already captured output (the NAME.sout format of the
                                             harness, with the final exit=N line) with PROGRAM's expected.out.

The filter: drop lines the runtime writes itself (beginning `[silica]`), drop the final `exit=N` line (N must
be 0), drop lines matching a regular expression in the program's `ignore` file, ignore blank lines and the
amount of white space inside a line. What is left must equal expected.out line for line.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PROGRAMS = os.path.join(ROOT, "contract", "conformance", "programs")


def programs():
    return sorted(d for d in os.listdir(PROGRAMS) if os.path.isdir(os.path.join(PROGRAMS, d)))


def find(program):
    for d in programs():
        if d == program or d.split("-", 1)[0] == program:
            return os.path.join(PROGRAMS, d)
    raise SystemExit(f"conformance: no program {program}; known: {', '.join(programs())}")


def norm(line):
    return " ".join(line.split())


def filtered(text, ignore):
    """-> (lines, exit status or None)"""
    out, status = [], None
    for line in text.split("\n"):
        m = re.fullmatch(r"exit=(\d+)", line.strip())
        if m:
            status = int(m.group(1))
            continue
        if line.startswith("[silica]") or not line.strip():
            continue
        if any(r.search(line) for r in ignore):
            continue
        out.append(norm(line))
    return out, status


def ignore_of(pdir):
    path = os.path.join(pdir, "ignore")
    if not os.path.exists(path):
        return []
    with open(path) as fh:
        return [re.compile(l.rstrip("\n")) for l in fh if l.strip()]


def compare(text, pdir):
    """-> list of problems (empty when the output conforms)."""
    with open(os.path.join(pdir, "expected.out")) as fh:
        want = [norm(l) for l in fh.read().split("\n") if l.strip()]
    got, status = filtered(text, ignore_of(pdir))
    problems = []
    if status is None:
        problems.append("no final exit=N line")
    elif status != 0:
        problems.append(f"exit status {status}, expected 0")
    if got != want:
        problems.append("output differs\n  expected: " + " | ".join(want) + "\n  got:      " + " | ".join(got))
    return problems


def references(pdir):
    rows = []
    with open(os.path.join(pdir, "reference")) as fh:
        for line in fh:
            line = line.split("#", 1)[0].split()
            if line:
                rows.append(tuple(line))
    return rows


def check_kit():
    bad = 0
    for name in programs():
        pdir = os.path.join(PROGRAMS, name)
        for f in ("spec.md", "expected.out", "reference"):
            if not os.path.exists(os.path.join(pdir, f)):
                print(f"{name}: missing {f}")
                bad += 1
        if bad and not os.path.exists(os.path.join(pdir, "reference")):
            continue
        compared = 0
        for role, leaf, entry in references(pdir):
            src = os.path.join(ROOT, leaf, entry + ".silica")
            gold = os.path.join(ROOT, leaf, entry + ".scout")
            if not os.path.exists(src):
                print(f"{name}: reference lowering {leaf}/{entry}.silica does not exist")
                bad += 1
            if role == "compare":
                compared += 1
                if not os.path.exists(gold):
                    print(f"{name}: no golden {leaf}/{entry}.scout")
                    bad += 1
                    continue
                with open(gold) as fh:
                    for p in compare(fh.read(), pdir):
                        print(f"{name}: reference {leaf}/{entry}: {p}")
                        bad += 1
        if not compared:
            print(f"{name}: no `compare` reference lowering")
            bad += 1
        for link in sorted(os.listdir(pdir)):
            p = os.path.join(pdir, link)
            if os.path.islink(p) and not os.path.exists(p):
                print(f"{name}: dangling symlink {link}")
                bad += 1
    print(f"conformance kit: {len(programs())} programs, {'ok' if not bad else str(bad) + ' problems'}")
    return 1 if bad else 0


def main(argv):
    if len(argv) == 2 and argv[1] == "list":
        print("\n".join(programs()))
        return 0
    if len(argv) == 2 and argv[1] == "check-kit":
        return check_kit()
    if len(argv) == 5 and argv[1] == "run":
        leaf, entry, pdir = argv[2], argv[3], find(argv[4])
        r = subprocess.run(["make", "-C", leaf, "run"], capture_output=True, text=True)
        if r.returncode != 0:
            print(r.stdout[-2000:] + r.stderr[-2000:])
            print(f"{os.path.basename(pdir)}: the leaf did not build or run")
            return 1
        with open(os.path.join(leaf, entry + ".sout")) as fh:
            problems = compare(fh.read(), pdir)
    elif len(argv) == 4 and argv[1] == "compare":
        pdir = find(argv[3])
        with open(argv[2]) as fh:
            problems = compare(fh.read(), pdir)
    else:
        print(__doc__, file=sys.stderr)
        return 2
    for p in problems:
        print(f"{os.path.basename(pdir)}: {p}")
    print(f"{os.path.basename(pdir)}: {'pass' if not problems else 'FAIL'}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
