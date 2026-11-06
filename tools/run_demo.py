#!/usr/bin/env python3
"""Run two node programs at the same time as two separate operating-system processes (M4), the way tools/run_pair.py does, with
three additions: `--kill-a-on TEXT` stops the first program with SIGKILL once TEXT has appeared in the second one's output (a node
stopped mid-run); `--time` runs each program under `/usr/bin/time -l` and writes its peak resident set size and times to
OUT.rusage; `--stamps` writes OUT.stamps with the seconds since the start at which each output line appeared. Each program's
output goes to its own OUT file with its exit code appended; a program gets "exit" on stdin once its marker has appeared and its
output has been quiet for 0.5 s (wait_for_exit returns on that line).

    run_demo.py --a EXE OUT MARKER --b EXE OUT MARKER [--stagger S] [--cap S] [--kill-a-on TEXT] [--time] [--stamps]

This is a measuring driver, not a benchmark harness: one run, one machine.
"""
import argparse
import os
import pty
import select
import signal
import subprocess
import sys
import time


class Node:
    def __init__(self, exe, out, marker, timed, t0):
        self.exe, self.out, self.marker, self.t0 = exe, out, marker, t0
        self.master, slave = pty.openpty()
        cmd = [exe]
        if timed:
            cmd = ["/usr/bin/time", "-l", "-o", out + ".rusage", exe]
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=slave, stderr=slave, close_fds=True)
        os.close(slave)
        self.chunks, self.stamps, self.partial = [], [], b""
        self.seen = self.sent = self.closed = False
        self.last = time.monotonic()
        self.killed = False

    def text(self):
        return b"".join(self.chunks).decode("utf-8", "replace")

    def pump(self):
        try:
            data = os.read(self.master, 65536)
        except OSError:
            data = b""
        if not data:
            self.closed = True
            return
        now = time.monotonic()
        self.chunks.append(data)
        self.last = now
        self.partial += data
        while b"\n" in self.partial:
            line, self.partial = self.partial.split(b"\n", 1)
            self.stamps.append((now - self.t0, line.decode("utf-8", "replace").rstrip("\r")))
        if self.marker.encode() in b"".join(self.chunks):
            self.seen = True

    def maybe_exit(self, now):
        if self.seen and not self.sent and now - self.last >= 0.5 and self.proc.poll() is None:
            try:
                self.proc.stdin.write(b"exit\n")
                self.proc.stdin.flush()
            except Exception:
                pass
            self.sent = True

    def finish(self, stamps):
        rc = self.proc.wait()
        with open(self.out, "wb") as f:
            f.write(b"".join(self.chunks).replace(b"\r\n", b"\n"))
            f.write(f"exit={rc}\n".encode())
        if stamps:
            with open(self.out + ".stamps", "w") as f:
                for t, line in self.stamps:
                    f.write(f"{t:9.3f} {line}\n")
        return rc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", nargs=3, required=True, metavar=("EXE", "OUT", "MARKER"))
    ap.add_argument("--b", nargs=3, required=True, metavar=("EXE", "OUT", "MARKER"))
    ap.add_argument("--stagger", type=float, default=0.5)
    ap.add_argument("--cap", type=float, default=120.0)
    ap.add_argument("--kill-a-on", default=None)
    ap.add_argument("--time", action="store_true")
    ap.add_argument("--stamps", action="store_true")
    o = ap.parse_args()
    t0 = time.monotonic()
    a = Node(*o.a, o.time, t0)
    time.sleep(o.stagger)
    b = Node(*o.b, o.time, t0)
    nodes = [a, b]
    capped = False
    while True:
        live = [n for n in nodes if not n.closed]
        if not live:
            break
        r, _, _ = select.select([n.master for n in live], [], [], 0.1)
        for n in live:
            if n.master in r:
                n.pump()
        now = time.monotonic()
        for n in nodes:
            n.maybe_exit(now)
            if n.proc.poll() is not None and n.master not in r:
                n.closed = True
        if o.kill_a_on and not a.killed and o.kill_a_on in b.text():
            # the pid of the node: under /usr/bin/time it is the child of the timer, otherwise the process itself
            pid = a.proc.pid
            if o.time:
                kids = subprocess.run(["pgrep", "-P", str(pid)], capture_output=True, text=True).stdout.split()
                pid = int(kids[0]) if kids else pid
            os.kill(pid, signal.SIGKILL)  # only the pid this driver started
            a.killed = True
        if now - t0 > o.cap:
            capped = True
            for n in nodes:
                if n.proc.poll() is None:
                    # a node run under /usr/bin/time has the node as the timer's child: stop that one too (only pids this driver started)
                    for kid in subprocess.run(["pgrep", "-P", str(n.proc.pid)], capture_output=True, text=True).stdout.split():
                        os.kill(int(kid), signal.SIGKILL)
                    n.proc.kill()
            break
    ra, rb = a.finish(o.stamps), b.finish(o.stamps)
    if capped:
        print("run_demo: killed after cap", file=sys.stderr)
        return 1
    return 0 if (rb == 0 and (ra == 0 or a.killed)) else 1


if __name__ == "__main__":
    sys.exit(main())
