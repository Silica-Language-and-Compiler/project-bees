#!/usr/bin/env python3
"""Runs the trials of the configuration store (trials/d1_store_layout, d2_store_config, d3_store_node): a leaf whose programs
open a (:store) backing needs that backing prepared before each run, one program is run on several backings, and what
happens to the backing afterwards is part of the result. tools/trial.mk runs each entry once in the leaf, so these leaves use
tools/bees_pack_trial.mk, which builds with trial.mk and runs through this driver.

    bees_pack_trial.py run LEAF        run every case of LEAF/cases.py, writing LEAF/CASE.sout
    bees_pack_trial.py compare LEAF    compare each CASE.sout with CASE.<platform>.scout; writes .integrate_counts
    bees_pack_trial.py record LEAF     copy each CASE.sout to CASE.<platform>.scout

LEAF/cases.py defines CASES, a list of dicts:
    name     the case's name (the golden is NAME.<platform>.scout)
    exe      the built program, relative to LEAF (it is run with a fresh directory LEAF/.run/NAME as its working
             directory, so the relative path of its `carried_on` declaration lands there)
    prepare  optional: prepare(dir) writes the backing and whatever else the program reads
    during   optional: during(dir, proc) is called once the program has started (a peer that talks to a node); it may
             return lines for the output
    after    optional: after(dir) returns lines appended to the output (what the backing looks like now)
    marker   the line after which the program is told to end (default "done": its main ends in wait_for_exit())

The output of a case is deterministic: the program's standard output, then its standard error with the two reports the
runtime writes when the unsupervised store carrier ends normally removed (they are written by another thread, at no fixed
place), then `exit=N`, then the lines of `after`. Nothing in it is a wall-clock value.
"""
import importlib.util
import os
import re
import select
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import platform_id      # noqa: E402

CAP = 60.0
CARRIER_END = re.compile(r"\n?=== Silica Actor Failure ===\n(?:(?!=== End).)*?reason:\s+:normal\n(?:(?!=== End).)*?"
                         r"dangerous_(?:store_backing|tcp)_carrier_carrier\n(?:(?!=== End).)*?=== End Silica Actor Failure ===\n\n?", re.S)
ROOT_EXIT = "[silica] root actor exited (no supervisor)\n"


def load_cases(leaf):
    spec = importlib.util.spec_from_file_location("cases", os.path.join(leaf, "cases.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.CASES


def run_case(leaf, case):
    d = os.path.join(leaf, ".run", case["name"])
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    if case.get("prepare"):
        case["prepare"](d)
    marker = case.get("marker", "done").encode()
    proc = subprocess.Popen([os.path.join(leaf, case["exe"])], cwd=d, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err, extra = b"", b"", []
    start = time.monotonic()
    told, quiet_since, during_done = False, None, False
    streams = {proc.stdout.fileno(): "out", proc.stderr.fileno(): "err"}
    open_fds = set(streams)
    while open_fds:
        if not during_done and case.get("during"):
            during_done = True
            extra = list(case["during"](d, proc) or [])
        r, _, _ = select.select(list(open_fds), [], [], 0.05)
        for fd in r:
            chunk = os.read(fd, 65536)
            if not chunk:
                open_fds.discard(fd)
            elif streams[fd] == "out":
                out += chunk
            else:
                err += chunk
            quiet_since = None
        now = time.monotonic()
        if not r:
            quiet_since = quiet_since or now
        seen = any(line.strip() == marker for line in out.split(b"\n"))
        if seen and not told and quiet_since is not None and now - quiet_since >= 0.4:
            told = True
            try:
                proc.stdin.write(b"exit\n")
                proc.stdin.flush()
            except OSError:
                pass
        if now - start > CAP:
            proc.kill()
            err += b"\nTIMEOUT: the case did not end\n"
            break
    rc = proc.wait()
    text = out.decode("utf-8", "replace")
    etext = CARRIER_END.sub("\n", err.decode("utf-8", "replace")).replace(ROOT_EXIT, "")
    etext = re.sub(r"0x[0-9a-f]{6,}", "0xADDR", etext)
    lines = [text.rstrip("\n")]
    if etext.strip():
        lines.append("-- standard error --")
        lines.append(etext.strip("\n"))
    lines.append(f"exit={rc}")
    lines.extend(extra)
    if case.get("after"):
        lines.extend(case["after"](d))
    with open(os.path.join(leaf, case["name"] + ".sout"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def squeeze(text):
    return [" ".join(line.split()) for line in text.split("\n") if line.strip()]


def main(argv):
    if len(argv) != 3 or argv[1] not in ("run", "compare", "record"):
        print(__doc__)
        return 2
    leaf = os.path.abspath(argv[2])
    name = os.path.basename(leaf)
    cases = load_cases(leaf)
    if argv[1] == "run":
        for case in cases:
            run_case(leaf, case)
        return 0
    ok = ko = 0
    for case in cases:
        sout = os.path.join(leaf, case["name"] + ".sout")
        gold = os.path.join(leaf, platform_id.golden_name(case["name"] + ".scout"))
        if argv[1] == "record":
            shutil.copyfile(sout, gold)
            continue
        if not os.path.exists(gold):
            print(f"MISSING golden for {platform_id.current_id()} (record one on this platform with make record-golden): [{name}] {os.path.basename(gold)}")
            ko += 1
            continue
        with open(sout, encoding="utf-8") as a, open(gold, encoding="utf-8") as b:
            got, want = squeeze(a.read()), squeeze(b.read())
        if got == want:
            ok += 1
        else:
            print(f"DIFF: [{name}] {case['name']}")
            subprocess.call(["diff", "-Bw", gold, sout])
            ko += 1
    if argv[1] == "record":
        print(f"[{name}] goldens recorded")
        return 0
    with open(os.path.join(leaf, ".integrate_counts"), "w") as f:
        f.write(f"{ok} {ko}\n")
    print(f"[{name}] {ok} passed, {ko} failed")
    return 0 if ko == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
