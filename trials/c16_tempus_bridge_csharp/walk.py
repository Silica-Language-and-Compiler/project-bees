#!/usr/bin/env python3
"""C16: run the walk of the C# extension's client half against real bridge nodes (Bridge.cs beside this file).

    walk.py LEAF_DIR DOTNET BRIDGE_DLL

The C# program holds the scenario and checks every step. This tool does for it what a client cannot do, one request
line (`@...` on the C# program's standard output) at a time, each answered with one line (`ok ...` or `fail ...`):

    @start NAME, @stop NAME   start or stop the node process t, b1 or b2 (each in its own directory under nodes/)
    @wait NAME REGEX          wait for a line of that node's output
    @tick NAME STORE          send the bridge (a test program) the test-only tick frame, with the Python test support
                              (the C# extension holds no test frame), and wait for its answer

Every other line of the C# program is its transcript, written to csharp.sout with the program's exit code. Keys,
certificates and tokens are TEST ONLY.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import bees_tempus_trial as T  # noqa: E402
import trial_ports  # noqa: E402

c = T.c
BASE = trial_ports.TABLE["c16_tempus_bridge_csharp"][0]
ADDR = {"b1": "127.0.0.1:%d" % (BASE + 1), "b2": "127.0.0.1:%d" % (BASE + 2)}
READY = {"t": r"listening on 127\.0\.0\.1", "b1": r"^join: no sentinel is configured$", "b2": r"^join: no sentinel is configured$"}


class Tool:
    def __init__(self, leaf):
        self.leaf = leaf
        self.nodes = {}
        self.peer = T.Peer()
        # the identity that sends the tick: an edge whose certificate no node has seen; it advertises an address nobody listens on
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

    def tick(self, name, store):
        out = c.dial(ADDR[name], self.driver, self.peer.verifier, c.tick(store), timeout=12.0)
        T.check(out.what == "reply" and out.kind == "done", "a tick to node %s: %s" % (name, out.line()))
        T.quiet()
        return ""

    def do(self, request):
        words = request.split(" ", 2)
        if words[0] not in ("start", "stop", "wait", "tick"):
            raise SystemExit("FAIL: no such request: " + request)
        return getattr(self, words[0])(*words[1:])

    def close(self):
        for n in list(self.nodes.values()):
            n.stop()


def main(argv):
    if len(argv) != 4:
        print(__doc__)
        return 2
    leaf, dotnet, dll = os.path.abspath(argv[1]), argv[2], argv[3]
    tool = Tool(leaf)
    lines = []
    proc = subprocess.Popen([dotnet, dll, ROOT, str(BASE)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
    try:
        for text in proc.stdout:
            text = text.rstrip("\n")
            if not text.startswith("@"):
                lines.append(text)
                continue
            try:
                answer = "ok " + tool.do(text[1:])
            except SystemExit as why:                      # a failed check of the trial tool or of a node's wait
                answer = "fail " + str(why).split("\n")[0]
                lines.append(str(why))
            except Exception as why:                       # a fault of this tool: say so, and let the walk end
                answer = "fail %s: %s" % (type(why).__name__, why)
            proc.stdin.write(answer + "\n")
            proc.stdin.flush()
        rc = proc.wait()
    finally:
        if proc.poll() is None:
            proc.kill()
        tool.close()
    with open(os.path.join(leaf, "csharp.sout"), "w") as f:
        f.write("".join(ln + "\n" for ln in lines))
        f.write("exit=%d\n" % rc)
    if rc != 0:
        print("\n".join(ln for ln in lines if ln.startswith("FAIL")) or "FAIL: [c16_tempus_bridge_csharp] the C# walk ended with exit code %d" % rc)
    else:
        print(lines[-1])
    return 0 if rc == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
