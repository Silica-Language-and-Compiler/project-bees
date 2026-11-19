#!/usr/bin/env python3
"""Diagnostic (not part of integrate): run a TRUST server and client as run_trust_pair.py does and print every line of both with the
seconds since the start, S or C:  stamp_pair.py SERVER_EXE CLIENT_EXE DONE_TEXT"""
import os, pty, select, subprocess, sys, time
srv, cli, done = sys.argv[1], sys.argv[2], sys.argv[3]
t0 = time.monotonic()
def start(exe):
    m, s = pty.openpty()
    p = subprocess.Popen([exe], stdin=subprocess.PIPE, stdout=s, stderr=s, cwd=os.path.dirname(exe))
    os.close(s); return p, m
procs = {"S": start(srv)}
bufs = {"S": b"", "C": b""}
seen_done = None
while True:
    fds = {m: k for k, (p, m) in procs.items()}
    r, _, _ = select.select(list(fds), [], [], 0.05)
    for m in r:
        k = fds[m]
        try: d = os.read(m, 65536)
        except OSError: d = b""
        if not d:
            continue
        bufs[k] += d
        while b"\n" in bufs[k]:
            line, bufs[k] = bufs[k].split(b"\n", 1)
            t = time.monotonic() - t0
            print("%7.3f %s %s" % (t, k, line.decode("utf-8", "replace").rstrip()[:150]), flush=True)
            if k == "S" and b"listening on" in line and "C" not in procs:
                procs["C"] = start(cli)
            if k == "C" and done.encode() in line:
                seen_done = time.monotonic()
    if seen_done and time.monotonic() - seen_done > 1.5:
        for k, (p, m) in procs.items():
            try: p.stdin.write(b"exit\n"); p.stdin.flush()
            except Exception: pass
        time.sleep(0.5)
        for k, (p, m) in procs.items():
            p.kill()
        break
    if time.monotonic() - t0 > 40:
        for k, (p, m) in procs.items(): p.kill()
        break
