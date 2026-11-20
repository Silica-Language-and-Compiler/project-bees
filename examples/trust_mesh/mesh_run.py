#!/usr/bin/env python3
"""Runs the five nodes of examples/trust_mesh as five operating-system processes and checks what they printed.

    mesh_run.py run        start the nodes, wait until the baton has gone round, tell them to exit; writes mesh.n1.sout
                           ... mesh.n5.sout (each node's output) and mesh.check (the check of all five)
    mesh_run.py compare    compare those six files with the recorded ones of this platform; writes .integrate_counts
    mesh_run.py record     record them (NAME.<platform>.scout)

Order: nodes 2 to 5 are started first; node 1, which makes the first call, is started when each of them has printed that
it listens. A node is told to exit (the line `exit` on its standard input, which wait_for_exit() reads) when all five have
printed their `done` line and have been quiet for a second.

A node's recorded output ends at its `done` line. What a node prints after it (its sessions ending when the other nodes
exit) depends on the order in which the processes end, so it is kept in mesh.nK.raw and not compared. The raw output of
the whole run is what mesh.check is computed from.
"""
import os
import re
import shutil
import subprocess
import sys
import time
import select

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(HERE, "..", "..", "tools")
sys.path.insert(0, TOOLS)
import platform_id                  # noqa: E402
import trial_ports                  # noqa: E402
from run_trust_pair import Proc     # noqa: E402  (a program on a pty, its output kept, `exit` on its standard input)

NODES = [1, 2, 3, 4, 5]
LAPS = 2
CAP = 90.0
QUIET = 1.0
EXE = "nodes/n%d/dangerous_mesh_node"
ROOT_EXIT = "[silica] root actor exited (no supervisor)\n"
CALL = re.compile(r"^hop (\d+): n(\d+) called 127\.0\.0\.1:(\d+) mesh:relay\(\[(\d+), (\d+)\]\): (.*)$")
FAILURE = re.compile(r"Silica Actor Failure|no case arm matched|actor_not_found|\{error, |refused|goaway|suspicion fp=|quarantined|TIMEOUT")
OUTPUTS = ["mesh.n%d" % k for k in NODES] + ["mesh.check"]


def port(k):
    return trial_ports.port("n5_trust_mesh", k)


def done_text(k):
    return "n%d: done" % k


def run():
    procs = {}
    t0 = time.monotonic()
    capped = False
    for k in NODES[1:]:
        procs[k] = Proc(os.path.join(HERE, EXE % k), os.path.join(HERE, "mesh.n%d.raw" % k), False)
    told = False
    while True:
        live = [p for p in procs.values() if not p.closed]
        if not live:
            break
        r, _, _ = select.select([p.master for p in live], [], [], 0.05)
        for p in live:
            if p.master in r:
                p.pump()
            elif p.p.poll() is not None:
                p.closed = True
        now = time.monotonic()
        if 1 not in procs and all("listening on 127.0.0.1:%d" % port(k) in procs[k].text() for k in NODES[1:]):
            procs[1] = Proc(os.path.join(HERE, EXE % 1), os.path.join(HERE, "mesh.n1.raw"), False)
        if 1 not in procs and any(procs[k].closed for k in NODES[1:]):
            break                                   # a node ended by itself (a refused boot): node 1 is not started
        if not told and len(procs) == len(NODES) and all(done_text(k) in procs[k].text() for k in NODES) \
                and all(now - p.last >= QUIET for p in procs.values()):
            told = True
            for p in procs.values():
                p.tell_exit()
        if now - t0 > CAP:
            capped = True
            for p in procs.values():
                p.kill()
            break
    for k in NODES:
        if k in procs:
            procs[k].finish()
        else:
            with open(os.path.join(HERE, "mesh.n%d.raw" % k), "w") as f:
                f.write("(not started: the other nodes did not all print that they listen)\n")
    raws = {}
    for k in NODES:
        with open(os.path.join(HERE, "mesh.n%d.raw" % k), encoding="utf-8", errors="replace") as f:
            raws[k] = clean(f.read())
        with open(os.path.join(HERE, "mesh.n%d.sout" % k), "w", encoding="utf-8") as f:
            f.write(until_done(raws[k], k))
    with open(os.path.join(HERE, "mesh.check"), "w", encoding="utf-8") as f:
        f.write(check(raws, capped))
    return 0


def clean(text):
    """what differs between two runs for no reason of the example: addresses, the runtime's root-actor line, wall-clock values"""
    text = text.replace(ROOT_EXIT, "")
    text = re.sub(r"0x[0-9a-f]{6,}", "0xADDR", text)
    return re.sub(r"(age_ms|duration_ms|paused_ms)=[0-9]+", r"\1=N", text)


def until_done(text, k):
    out, seen = [], False
    for line in text.split("\n"):
        if seen:
            if line.startswith("exit="):
                out.append(line)
            continue
        out.append(line)
        seen = done_text(k) in line
    return "\n".join(out).rstrip("\n") + "\n"


def check(raws, capped):
    """Every call's line names the hop, the caller and the address called, and its answer is Hop * 100 + Caller * 10 + the
    number of the node that answered: a call counts when the answer is {ok, int N} with the N of the node at that address."""
    n = len(NODES)
    good = {(x, y): 0 for x in NODES for y in NODES if x != y}
    bad, hops = [], []
    for k in NODES:
        for line in raws[k].split("\n"):
            m = CALL.match(line.strip())
            if not m:
                continue
            hop, caller, to_port, a_hop, a_caller, result = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5)), m.group(6)
            y = to_port - port(0)
            want = "{ok, int %d}" % (hop * 100 + caller * 10 + y)
            if caller == k and a_hop == hop and a_caller == caller and (caller, y) in good and result == want:
                good[(caller, y)] += 1
                hops.append(hop)
            else:
                bad.append(line.strip())
    L = ["examples/trust_mesh: five TRUST nodes over mutual TLS 1.3, every node a server and a client of the other four",
         "calls answered by the right node, caller in rows, server in columns (%d laps, so %d for every pair):" % (LAPS, LAPS),
         "     " + "  ".join("n%d" % y for y in NODES)]
    for x in NODES:
        L.append("n%d   " % x + "  ".join(" -" if x == y else "%2d" % good[(x, y)] for y in NODES))
    pairs = sum(1 for v in good.values() if v == LAPS)
    L.append("directed pairs with every call answered: %d of %d" % (pairs, n * (n - 1)))
    L.append("calls answered: %d of %d" % (sum(good.values()), LAPS * n * (n - 1)))
    L.append("hops in order, none twice, none missing: %s" % ("yes" if sorted(hops) == list(range(1, LAPS * n * (n - 1) + 1)) else "no"))
    L.append("calls with another outcome: %d" % len(bad))
    L.extend("  " + b for b in bad)
    for what, word in (("as client", "opened as a client"), ("as server", "accepted as a server")):
        L.append("TLS connections %s, n1 to n5: %s" % (word, " ".join(str(sum(1 for line in raws[k].split("\n") if "tls_established" in line and what in line)) for k in NODES)))
    before = {k: until_done(raws[k], k) for k in NODES}
    L.append("sessions ended before a node's done line: %d" % sum(before[k].count("session.end") for k in NODES))
    L.append("failure lines before a node's done line: %d" % sum(1 for k in NODES for line in before[k].split("\n") if FAILURE.search(line)))
    L.append("nodes that printed their done line: %d of %d" % (sum(1 for k in NODES if done_text(k) in raws[k]), n))
    L.append("nodes that ended with exit=0: %d of %d" % (sum(1 for k in NODES if raws[k].rstrip("\n").endswith("exit=0")), n))
    if capped:
        L.append("the run was stopped at the time limit")
    return "\n".join(L) + "\n"


def squeeze(text):
    return [" ".join(line.split()) for line in text.split("\n") if line.strip()]


def golden(name):
    return os.path.join(HERE, platform_id.golden_name(name + ".scout"))


def current(name):
    return os.path.join(HERE, name if name.endswith(".check") else name + ".sout")


def main(argv):
    if len(argv) != 2 or argv[1] not in ("run", "compare", "record"):
        print(__doc__)
        return 2
    if argv[1] == "run":
        return run()
    ok = ko = 0
    for name in OUTPUTS:
        cur, gold = current(name), golden(name)
        if argv[1] == "record":
            shutil.copyfile(cur, gold)
            continue
        if not os.path.exists(gold):
            print(f"MISSING golden for {platform_id.current_id()} (record one on this platform with make record-golden): [n5_trust_mesh] {os.path.basename(gold)}")
            ko += 1
            continue
        with open(cur, encoding="utf-8") as a, open(gold, encoding="utf-8") as b:
            same = squeeze(a.read()) == squeeze(b.read())
        if same:
            ok += 1
        else:
            print(f"DIFF: [n5_trust_mesh] {os.path.basename(cur)}")
            subprocess.call(["diff", "-Bw", gold, cur])
            ko += 1
    if argv[1] == "record":
        print("[n5_trust_mesh] goldens recorded")
        return 0
    with open(os.path.join(HERE, ".integrate_counts"), "w") as f:
        f.write(f"{ok} {ko}\n")
    print(f"[n5_trust_mesh] {ok} passed, {ko} failed")
    return 0 if ko == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
