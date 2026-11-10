#!/usr/bin/env python3
"""Run a TRUST server program and a TRUST client program as two operating-system processes (N3 trials), the way
tools/run_demo.py does (each under a pty, output to its own file with the exit code appended), with the ordering a TRUST
scenario needs: the client is started only once the server has printed READY (its listener is bound), the client is told
"exit" once it has printed DONE and been quiet for QUIET seconds, and the server is told "exit" only after the client has
ended and the server has been quiet for QUIET seconds. With --kill TEXT the server is killed (SIGKILL) as soon as TEXT appears
in the client's output (a node stopped while a connection is open). With --time each program runs under /usr/bin/time -l
(peak resident set in OUT.rusage). A server that refuses to boot (it exits by itself) is simply recorded; the client is then
not started.

    run_trust_pair.py SERVER_EXE SERVER_OUT READY CLIENT_EXE CLIENT_OUT DONE [--kill TEXT] [--cap S] [--quiet S] [--time]
"""
import argparse
import os
import pty
import select
import signal
import subprocess
import sys
import time


class Proc:
    def __init__(self, exe, out, timed):
        self.out = out
        self.master, slave = pty.openpty()
        cmd = ["/usr/bin/time", "-l", "-o", out + ".rusage", exe] if timed else [exe]
        self.p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=slave, stderr=slave, close_fds=True)
        os.close(slave)
        self.buf = b""
        self.last = time.monotonic()
        self.closed = False
        self.sent = False

    def text(self):
        return self.buf.decode("utf-8", "replace")

    def pump(self):
        try:
            d = os.read(self.master, 65536)
        except OSError:
            d = b""
        if not d:
            self.closed = True
            return
        self.buf += d
        self.last = time.monotonic()

    def tell_exit(self):
        if not self.sent and self.p.poll() is None:
            try:
                self.p.stdin.write(b"exit\n")
                self.p.stdin.flush()
            except Exception:
                pass
        self.sent = True

    def kill(self):
        for kid in subprocess.run(["pgrep", "-P", str(self.p.pid)], capture_output=True, text=True).stdout.split():
            os.kill(int(kid), signal.SIGKILL)   # only children of a process this driver started (under /usr/bin/time)
        if self.p.poll() is None:
            self.p.kill()

    def finish(self):
        rc = self.p.wait()
        with open(self.out, "wb") as f:
            f.write(self.buf.replace(b"\r\n", b"\n"))
            f.write(f"exit={rc}\n".encode())
        return rc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("server")
    ap.add_argument("server_out")
    ap.add_argument("ready")
    ap.add_argument("client")
    ap.add_argument("client_out")
    ap.add_argument("done")
    ap.add_argument("--kill", default=None)
    ap.add_argument("--cap", type=float, default=60.0)
    ap.add_argument("--quiet", type=float, default=0.7)
    ap.add_argument("--time", action="store_true")
    o = ap.parse_args()
    t0 = time.monotonic()
    s = Proc(o.server, o.server_out, o.time)
    c = None
    killed = False
    capped = False
    while True:
        live = [p for p in (s, c) if p is not None and not p.closed]
        if not live:
            break
        r, _, _ = select.select([p.master for p in live], [], [], 0.05)
        for p in live:
            if p.master in r:
                p.pump()
            elif p.p.poll() is not None:
                p.closed = True
        now = time.monotonic()
        if c is None and o.ready in s.text():
            c = Proc(o.client, o.client_out, o.time)
        if c is None and s.closed:
            break                                  # the server ended by itself (a refused boot): no client
        if c is not None and o.kill and not killed and o.kill in c.text():
            s.kill()
            killed = True
        if c is not None and o.done in c.text() and now - c.last >= o.quiet:
            c.tell_exit()
        if c is not None and c.closed and now - s.last >= o.quiet:
            s.tell_exit()
        if now - t0 > o.cap:
            capped = True
            for p in (s, c):
                if p is not None:
                    p.kill()
            break
    rs = s.finish()
    if c is not None:
        c.finish()
    else:
        with open(o.client_out, "w") as f:
            f.write("(not started: the server did not print its ready line)\n")
    if capped:
        print("run_trust_pair: killed after cap", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
