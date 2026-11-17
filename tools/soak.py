#!/usr/bin/env python3
"""soak: a long-lived BEES node program against a peer that connects, or is dialed, over and over; records the node's resident set
(ps, KiB) along the way and its peak (/usr/bin/time -l). A measurement tool (N2c: do the idle actors of ended links add up?), not a test:
the numbers vary, so no golden; trials/n2_soak `make measure` calls it.

    soak.py connect EXE PORT CYCLES [--overlap]   the node LISTENS on PORT (one peer line, listen role): this tool connects CYCLES times,
                                                  closing each connection at once; with --overlap it opens connection k+1 BEFORE it closes
                                                  connection k, so that the node replaces its old link every time
    soak.py accept  EXE PORT CYCLES               the node DIALS PORT (redial on, 10 ms): this tool listens and accepts CYCLES connections,
                                                  closing each at once; the node's redial actor dials again every time

Prints `cycle rss_kib` lines (cycle 0 is the settled node before the first cycle) and `peak_kib`. The node is stopped with "exit" on its stdin.
"""
import os
import socket
import subprocess
import sys
import time


def rss_kib(pid):
    out = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    return int(out) if out else -1


def main(argv):
    mode, exe, port, cycles = argv[1], argv[2], int(argv[3]), int(argv[4])
    overlap = "--overlap" in argv
    rus = exe + ".soak.rusage"
    node = subprocess.Popen(["/usr/bin/time", "-l", "-o", rus, exe], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.5)
    # /usr/bin/time forks the program: sample the child of the timer
    kids = subprocess.run(["pgrep", "-P", str(node.pid)], capture_output=True, text=True).stdout.split()
    pid = int(kids[0]) if kids else node.pid
    step = max(1, cycles // 10)
    print(f"{0:6d} {rss_kib(pid):8d}", flush=True)
    srv = None
    if mode == "accept":
        srv = socket.socket()
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", port))
        srv.listen(16)
    prev = None
    for k in range(1, cycles + 1):
        if mode == "connect":
            c = socket.create_connection(("127.0.0.1", port), timeout=10)
            if overlap:
                time.sleep(0.02)          # the node claims the peer's slot at accept: let it take the new connection before the old one goes
                if prev:
                    prev.close()
                prev = c
            else:
                time.sleep(0.005)
                c.close()
            time.sleep(0.01)
        else:
            c, _ = srv.accept()
            c.close()
        if k % step == 0:
            time.sleep(0.3)               # let the node's own reclaiming settle before the sample
            print(f"{k:6d} {rss_kib(pid):8d}", flush=True)
    if prev:
        prev.close()
    time.sleep(4.0)                       # the grace timers of BEAM-mode links that ended during the handshake (2 s) have run
    print(f"final  {rss_kib(pid):8d}", flush=True)
    try:
        node.stdin.write(b"exit\n")
        node.stdin.flush()
    except Exception:
        pass
    try:
        node.wait(timeout=15)
    except subprocess.TimeoutExpired:
        node.kill()
    peak = 0
    if os.path.exists(rus):
        for line in open(rus):
            if "maximum resident set size" in line:
                peak = int(line.split()[0]) // 1024
    print(f"peak_kib {peak}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
