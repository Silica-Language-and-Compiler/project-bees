#!/usr/bin/env python3
"""n2_live: the driver of trials/n2_live (milestone N2), BEES against a stock Erlang node on this machine.

    n2_live.py LEAF_DIR SCENARIO...

Everything stays on 127.0.0.1. A private EPMD is started on 127.0.0.1:22090 (tools/trial_ports.py: n2_live +90; `epmd -port 22090 -address 127.0.0.1 -daemon`)
and both sides are pointed at it (ERL_EPMD_PORT for erl; bees.config's epmd_port for BEES); it is killed at the end. The stock
side is LEAF_DIR/stock_driver.erl, compiled with the installed erlc into LEAF_DIR/build. The stock node runs with
net_ticktime 8 and its distribution listener on 127.0.0.1 (inet_dist_use_interface). Nothing is downloaded.

Each scenario writes NAME.bees.raw and NAME.stock.raw (everything printed) and NAME.bees.sout and NAME.stock.sout, the
normalised text the goldens hold: runtime addresses become 0xADDR, the runtime's "root actor exited" line is dropped, a run of
consecutive "frame dropped, not a name this node serves" lines (the stock kernel's rex and global_name_server) is sorted, numbers in
the stock side's "evidence:" lines become N, and of the stock node's kernel log only the "** ..." lines are kept (their
timestamped headers vary).
"""
import os
import pty
import re
import select
import signal
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import trial_ports  # noqa: E402

EPMD_PORT = str(trial_ports.port("n2_live", 90))   # the table: tools/trial_ports.py
TICK = "8"
GOOD = "n2-live-cookie"
WRONG = "another-cookie"


class Proc:
    """A child whose output (stdout and stderr together) is collected line by line in a thread."""

    def __init__(self, argv, env=None, cwd=None, pty_io=False):
        self.lines, self.lock = [], threading.Lock()
        if pty_io:
            master, slave = pty.openpty()
            self.p = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=slave, stderr=slave, env=env, cwd=cwd, close_fds=True)
            os.close(slave)
            self.fd = master
        else:
            self.p = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, cwd=cwd)
            self.fd = self.p.stdout.fileno()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        buf = b""
        while True:
            try:
                r, _, _ = select.select([self.fd], [], [], 0.2)
                if not r:
                    if self.p.poll() is not None:
                        break
                    continue
                data = os.read(self.fd, 4096)
            except OSError:
                break
            if not data:
                break
            buf += data
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                with self.lock:
                    self.lines.append(line.decode("utf-8", "replace").rstrip("\r"))
        if buf:
            with self.lock:
                self.lines.append(buf.decode("utf-8", "replace").rstrip("\r"))

    def wait_for(self, text, timeout):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            with self.lock:
                if any(text in l for l in self.lines):
                    return True
            if self.p.poll() is not None:
                time.sleep(0.3)
                with self.lock:
                    return any(text in l for l in self.lines)
            time.sleep(0.05)
        return False

    def quit(self, timeout=10):
        try:
            self.p.stdin.write(b"exit\n")
            self.p.stdin.flush()
        except (BrokenPipeError, OSError):
            pass
        try:
            return self.p.wait(timeout)
        except subprocess.TimeoutExpired:
            self.p.kill()
            return self.p.wait()

    def kill(self):
        self.p.send_signal(signal.SIGKILL)
        return self.p.wait()

    def wait(self, timeout):
        try:
            return self.p.wait(timeout)
        except subprocess.TimeoutExpired:
            self.p.kill()
            return "timeout"

    def text(self):
        time.sleep(0.3)
        with self.lock:
            return list(self.lines)


def env():
    e = dict(os.environ)
    e["ERL_EPMD_PORT"] = EPMD_PORT
    return e


def stock(leaf, name, cookie, fn, bees):
    argv = ["erl", "-sname", f"{name}@localhost", "-setcookie", cookie, "-kernel", "net_ticktime", TICK,
            "-kernel", "inet_dist_use_interface", "{127,0,0,1}", "-pa", os.path.join(leaf, "build"), "-noshell",
            "-eval", f"stock_driver:{fn}('{bees}'), halt()."]
    return Proc(argv, env=env(), cwd=leaf)


def bees(leaf, node, exe):
    # run from the node's own directory, as the trial harness runs entries (bees.config's paths are resolved at build time)
    return Proc([os.path.join(leaf, "nodes", node, exe)], cwd=os.path.join(leaf, "nodes", node), pty_io=True)


DROP = "[bees audit] frame dropped, not a name this node serves"


def norm_bees(lines, rc):
    out = []
    # the runtime's root-actor line (stderr) can land inside a stdout line: removed with its newline wherever it is
    # (tools/silica.mk STRIP_ROOT_EXIT), which rejoins the stdout line
    text = "\n".join(lines).replace("[silica] root actor exited (no supervisor)\n", "")
    for l in text.split("\n"):
        if l.startswith("[silica] root actor exited"):
            continue
        out.append(re.sub(r"0x[0-9a-f]{6,}", "0xADDR", l))
    # the stock kernel's own nodeup messages (rex, global_name_server) come from independent processes in either order:
    # a run of consecutive drops of them is sorted
    i = 0
    while i < len(out):
        j = i
        while j < len(out) and out[j].startswith(DROP):
            j += 1
        if j > i + 1:
            out[i:j] = sorted(out[i:j])
        i = max(j, i + 1)
    out.append(f"exit={rc}")
    return out


def norm_stock(lines, rc):
    out = []
    for l in lines:
        if l.startswith("evidence:"):
            out.append(re.sub(r"\d+", "N", l))
        elif l.startswith("stock:"):
            out.append(l)
        elif l.strip().startswith("** "):
            out.append(re.sub(r"<\d+\.\d+\.\d+>", "<PID>", l.strip()))
    out.append(f"exit={rc}")
    return out


def write(leaf, name, side, lines, normed):
    with open(os.path.join(leaf, f"{name}.{side}.raw"), "w") as fh:
        fh.write("\n".join(lines) + "\n")
    with open(os.path.join(leaf, f"{name}.{side}.sout"), "w") as fh:
        fh.write("\n".join(normed) + "\n")


def scenario(leaf, name):
    if name == "stock_dials":
        b = bees(leaf, "l", "dangerous_beesl")
        ok = b.wait_for("epmd: registered", 15)
        s = stock(leaf, "stock", GOOD, "stock_dials", "beesl@localhost")
        if ok and s.wait_for("KILL NOW", 90):
            brc = b.kill()
            brc = "killed (SIGKILL)" if brc == -9 else brc
        else:
            brc = b.quit()
        src = s.wait(60)
    elif name == "bees_dials":
        s = stock(leaf, "stock", GOOD, "bees_dials", "beesd@localhost")
        s.wait_for("waiting in registered process inbox", 20)
        time.sleep(0.5)
        b = bees(leaf, "d", "dangerous_beesd")
        s.wait_for("stock: done", 60)
        time.sleep(1.0)
        brc = b.quit()
        src = s.wait(30)
    elif name == "wrong_ping":
        b = bees(leaf, "l", "dangerous_beesl")
        b.wait_for("epmd: registered", 15)
        s = stock(leaf, "stock", WRONG, "wrong_ping", "beesl@localhost")
        s.wait_for("stock: done", 60)
        src = s.wait(30)
        time.sleep(1.0)
        brc = b.quit()
    elif name == "wrong_listen":
        s = stock(leaf, "stock", WRONG, "wrong_listen", "beesd@localhost")
        s.wait_for("waiting with another cookie", 20)
        time.sleep(0.5)
        b = bees(leaf, "d", "dangerous_beesd")
        s.wait_for("stock: done", 60)
        time.sleep(0.5)
        brc = b.quit()
        src = s.wait(30)
    elif name == "unlisted":
        b = bees(leaf, "l", "dangerous_beesl")
        b.wait_for("epmd: registered", 15)
        s = stock(leaf, "intruder", GOOD, "unlisted_ping", "beesl@localhost")
        s.wait_for("stock: done", 60)
        src = s.wait(30)
        time.sleep(1.0)
        brc = b.quit()
    else:
        print(f"n2_live: unknown scenario {name}")
        return 1
    bl, sl = b.text(), s.text()
    write(leaf, name, "bees", bl, norm_bees(bl, brc))
    write(leaf, name, "stock", sl, norm_stock(sl, src))
    print(f"[n2_live] {name}: bees exit {brc}, stock exit {src}")
    return 0


def main(argv):
    leaf, names = os.path.abspath(argv[1]), argv[2:]
    os.makedirs(os.path.join(leaf, "build"), exist_ok=True)
    r = subprocess.run(["erlc", "-o", os.path.join(leaf, "build"), os.path.join(leaf, "stock_driver.erl")], capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout + r.stderr)
        return 1
    subprocess.run(["epmd", "-port", EPMD_PORT, "-kill"], capture_output=True, env=env())
    subprocess.run(["epmd", "-port", EPMD_PORT, "-address", "127.0.0.1", "-daemon"], env=env(), check=True)
    time.sleep(0.5)
    rc = 0
    try:
        for n in names:
            rc |= scenario(leaf, n)
            time.sleep(1.0)
    finally:
        subprocess.run(["epmd", "-port", EPMD_PORT, "-kill"], capture_output=True, env=env())
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv))
