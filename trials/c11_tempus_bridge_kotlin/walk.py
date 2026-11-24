#!/usr/bin/env python3
"""C11: run the Kotlin client's walk against real bridge nodes (Bridge.kt beside this file).

    walk.py LEAF_DIR JAVA JAR

The Kotlin program holds the scenario and checks every step. This tool does for it what a client cannot do, one request
line (`@...` on the Kotlin program's standard output) at a time, each answered with one line (`ok ...` or `fail ...`):

    @start NAME, @stop NAME   start or stop the node process t, b1 or b2 (each in its own directory under nodes/)
    @wait NAME REGEX          wait for a line of that node's output
    @tick NAME STORE          send the bridge (a test program) the test-only tick frame, with the Python test support
                              (the Kotlin extension holds no test frame), and wait for its answer
    @ticks2 NAME STORE        a tick, and 0.8 s later, while the shuffle it started is held open by the Kotlin
                              listener, a second tick; both answers are waited for
    @clock NAME MS            send the bridge the test-only clock frame

Every other line of the Kotlin program is its transcript, written to kotlin.sout with the program's exit code. Keys,
certificates and tokens are TEST ONLY.
"""
import os
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import bees_tempus_trial as T  # noqa: E402
import trial_ports  # noqa: E402

c = T.c
BASE = trial_ports.TABLE["c11_tempus_bridge_kotlin"][0]
ADDR = {"b1": "127.0.0.1:%d" % (BASE + 1), "b2": "127.0.0.1:%d" % (BASE + 2)}
READY = {"t": r"listening on 127\.0\.0\.1", "b1": r"^join: no sentinel is configured$", "b2": r"^join: no sentinel is configured$"}


class Tool:
    def __init__(self, leaf):
        self.leaf = leaf
        self.nodes = {}
        self.peer = T.Peer()
        self.driver = c.fixture_identity(112, "tempus_edge", 1000, 3000, addr="127.0.0.1:%d" % (BASE + 5))

    def start(self, name):
        n = self.nodes[name] = T.Node(os.path.join(self.leaf, "nodes", name), "dangerous_" + name)
        n.wait(READY[name])
        T.quiet()
        return ""

    def stop(self, name):
        T.quiet()
        self.nodes.pop(name).stop()
        return ""

    def wait(self, name, pattern):
        self.nodes[name].wait(pattern)
        return ""

    def _ask(self, name, body):
        out = c.dial(ADDR[name], self.driver, self.peer.verifier, body, timeout=12.0)
        T.check(out.what == "reply" and out.kind == "done", "a test frame to node %s: %s" % (name, out.line()))

    def tick(self, name, store):
        self._ask(name, c.tick(store))
        T.quiet()
        return ""

    def ticks2(self, name, store):
        first = threading.Thread(target=self._ask, args=(name, c.tick(store)))
        first.start()
        time.sleep(0.8)
        self._ask(name, c.tick(store))
        first.join()
        T.quiet()
        return ""

    def clock(self, name, ms):
        self._ask(name, c.clock(int(ms)))
        self.peer.clock[0] = int(ms) // 1000
        T.quiet()
        return ""

    def do(self, request):
        words = request.split(" ", 2)
        if words[0] not in ("start", "stop", "wait", "tick", "ticks2", "clock"):
            raise SystemExit("FAIL: no such request: " + request)
        return getattr(self, words[0])(*words[1:])

    def close(self):
        for n in list(self.nodes.values()):
            n.stop()


def main(argv):
    if len(argv) != 4:
        print(__doc__)
        return 2
    leaf, java, jar = os.path.abspath(argv[1]), argv[2], argv[3]
    tool = Tool(leaf)
    lines = []
    proc = subprocess.Popen([java, "-cp", jar, "bees.tempus.trial.BridgeKt", ROOT, str(BASE)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
    try:
        for text in proc.stdout:
            text = text.rstrip("\n")
            if not text.startswith("@"):
                lines.append(text)
                continue
            try:
                answer = "ok " + tool.do(text[1:])
            except SystemExit as why:
                answer = "fail " + str(why).split("\n")[0]
                lines.append(str(why))
            except Exception as why:
                answer = "fail %s: %s" % (type(why).__name__, why)
            proc.stdin.write(answer + "\n")
            proc.stdin.flush()
        rc = proc.wait()
    finally:
        if proc.poll() is None:
            proc.kill()
        tool.close()
    with open(os.path.join(leaf, "kotlin.sout"), "w") as f:
        f.write("".join(ln + "\n" for ln in lines))
        f.write("exit=%d\n" % rc)
    if rc != 0:
        print("\n".join(ln for ln in lines if ln.startswith("FAIL")) or "FAIL: [c11_tempus_bridge_kotlin] the Kotlin walk ended with exit code %d" % rc)
    else:
        print(lines[-1])
    return 0 if rc == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
