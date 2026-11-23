#!/usr/bin/env python3
"""C9: run the mixed network of Silica nodes and nodes of the Kotlin extension (Net.kt beside this file).

    walk.py LEAF_DIR JAVA NET_JAR

The Kotlin program holds the scenario and the Kotlin nodes, and checks every step. This tool does for it what it cannot
do itself, one request line (`@...` on the Kotlin program's standard output) at a time, each answered with one line
(`ok ...` or `fail ...`):

    @start NAME, @stop NAME   start or stop the Silica node process s, a or q of this leaf; its output goes to
                              dangerous_NAME.sout
    @wait NAME REGEX          wait for a line of that node's output
    @tick NAME STORE          send the Silica test node the test-only tick frame, with the Python test support (the
                              Kotlin extension holds no test frame), and wait for its answer
    @audit NAME               the audit lines that node wrote since this was last asked, joined by " / " (the
                              tls_established lines left out, the connection's number taken off)
    @pydial TARGET MODE       a peer that misbehaves as MODE says dials TARGET (a Silica node or a Kotlin node); the
                              answer is what that peer saw
    @inflight TARGET          two connections stay silent before their advert and a third one is dialed
    @peer MODE, @peerdone     a Python peer listens on this trial's port +6 for one connection and behaves as MODE
                              says; @peerdone answers with what it saw

Every other line of the Kotlin program is its transcript, written to kotlin.sout with the program's exit code. Keys,
certificates and tokens are TEST ONLY. The misbehaving peers are the Python example client's test support.
"""
import os
import re
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
A = c.Atom
BASE = trial_ports.TABLE["c9_tempus_node_kotlin"][0]
ADDR = {n: "127.0.0.1:%d" % (BASE + k) for n, k in (("s", 0), ("a", 1), ("ke", 2), ("kh", 2), ("kc", 2), ("ks", 3), ("kp", 4), ("q", 5))}
P_ADDR, DEAD = "127.0.0.1:%d" % (BASE + 6), "127.0.0.1:%d" % (BASE + 7)
READY = {"s": r"^join: no sentinel is configured$", "a": r"^join: done$", "q": r"^join: done$"}
PROD, OLD = c.fixture_key(0), c.fixture_key(96)
FAR = 4000000000


def ident(first, typ, exp, addr, certname=None, nbf=1000, **kw):
    i = c.fixture_identity(first, typ, nbf, exp, addr=addr, **kw)
    return c.Identity(i.seed, i.token, addr, cert_pem=T.cert(certname)) if certname else i


def line(out):
    """What the Python peer saw, as one line: of a close only the fact (the step at which a peer finds its connection
    closed depends on which of two frames in flight came first), of a failed handshake only the fact."""
    if out.what == "tls_failed":
        return "tls_failed"
    if out.what == "closed":
        return "closed, on purpose" if out.reason == c.ON_PURPOSE else "closed"
    return out.line()


class Tool:
    def __init__(self, leaf):
        self.leaf = leaf
        self.nodes = {}
        self.marks = {}
        self.verifier = T.Peer().verifier                                  # the producer key, kid k1, the clock 1500, skew 10
        self.real = c.Verifier(c._raw_public(PROD), "k1", lambda: int(time.time()), 10)   # the machine's clock
        self.k9 = c.Verifier(c._raw_public(PROD), "k9", 1500, 10)
        self.driver = ident(112, "tempus_edge", 3000, DEAD)                 # a certificate no node has seen
        self.far = ident(112, "tempus_edge", FAR, DEAD)                     # valid by the machine's clock
        self.x3 = ident(208, "tempus_edge", 3000, P_ADDR, "x3")
        self.x2 = ident(192, "tempus_edge", 3000, DEAD)
        self.forged = ident(192, "tempus_edge", 3000, DEAD, producer=OLD)   # signed with a key that is not the producer's
        self.listener = None

    def start(self, name):
        n = self.nodes[name] = T.Node(self.leaf, "dangerous_" + name)
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
        out = c.dial(ADDR[name], self.driver, self.verifier, c.tick(store), timeout=8.0)
        T.check(out.what == "reply" and out.kind == "done", "a tick to node %s: %s" % (name, out.line()))
        T.quiet()
        return ""

    def audit(self, name):
        T.quiet()
        lines = [ln for ln in self.nodes[name].text().split("\n") if ln.startswith("[tempus audit] ")]
        new = lines[self.marks.get(name, 0):]
        self.marks[name] = len(lines)
        out = []
        for ln in new:
            if " tls_established " in ln:
                continue
            ln = re.sub(r" [ad]\d+$", "", ln)
            out.append(re.sub(r"^(\[tempus audit\] closed_by_peer) peer=\S+ stage [a-z]+", r"\1 peer=(any) stage (any)", ln))
        return " / ".join(out)

    def pydial(self, target, mode):
        real = target in ("q", "kp")
        d = self.far if real else self.driver
        smp = c.sample("tempus_edge", 2)
        tok = lambda **kw: c.make_token(kw.get("signer", PROD), kw.get("kid", "k1"), kw.get("sub", d.pub), kw.get("typ", "tempus_edge"), kw.get("nbf", 1000), kw.get("exp", 3000))  # noqa: E731
        listed = ident(128, "tempus_edge", 3000, DEAD, "sentinel")
        modes = {  # mode -> (identity, request body, dial's switches)
            "good": (d, smp, {}),
            "short": (d.with_token(tok(exp=1480)), smp, {}),
            "expired": (d.with_token(tok(exp=1400)), smp, {}),
            "not-yet": (d.with_token(tok(nbf=1800)), smp, {}),
            "old-kid": (d.with_token(tok(signer=OLD, kid="k0")), smp, {}),
            "forged": (d.with_token(tok(signer=OLD)), smp, {}),
            "other-sub": (d.with_token(tok(sub=self.x2.pub)), smp, {}),
            "sentinel-token": (d.with_token(tok(typ="tempus_sentinel")), smp, {}),
            "listed-edge": (listed, smp, {}),
            "binding": (d, smp, {"misbehaviour": c.wrong_advert(self.x2.advert())}),
            "proof-other-key": (d, smp, {"misbehaviour": c.wrong_proof_other_key(c.fixture_key(224))}),
            "no-proof": (d, smp, {"misbehaviour": c.no_proof()}),
            "wrong-frame": (d, smp, {"misbehaviour": c.wrong_frame_at("challenge", c.sample("tempus_edge", 1))}),
            "oversize-advert": (d, smp, {"misbehaviour": c.oversize_frame_at("advert")}),
            "oversize-request": (d, smp, {"misbehaviour": c.oversize_frame_at("request")}),
            "closes": (d, smp, {"misbehaviour": c.close_after_advert()}),
            "sample-9": (d, c.sample("tempus_edge", 9), {}),
            "sample-3-bridge": (d, c.sample("tempus_bridge", 3), {}),
            "four-entries": (d, c.shuffle("tempus_edge", [d.entry(0), self.x2.entry(1), self.x3.entry(2), self.x2.entry(3)]), {}),
            "three-entries-bridge": (d, c.shuffle("tempus_bridge", [d.entry(0), self.x2.entry(1), self.x3.entry(2)]), {}),
            "forged-shuffle": (d, c.shuffle("tempus_edge", [d.entry(0), self.forged.entry(0)]), {}),
            "other-store": (d, c.shuffle("tempus_sentinel", [d.entry(0)]), {}),
            "age-65536": (d, c.etf_encode({A("t"): A("shuffle"), A("store"): A("tempus_edge"), A("entries"): [{A("age"): 65536, A("d"): d.descriptor()}]}), {}),
            "no-kind": (d, c.etf_encode({A("t"): A("tempus_edge")}), {}),
            "an-advert": (d, d.advert(), {}),
            "call": (d, c.call_frame(b"r1", "demo", "add", [1, 2]), {}),
            "trailing": (d, smp + b"\x00", {}),
            "tick": (d, c.tick("tempus_edge"), {}),
            "clock": (d, c.clock(1700000), {}),
            "clock-later": (d, c.clock(c.NO_TIME, 1000, 1700000), {}),
            "tls12": (d, smp, c.tls12_only()),
            "alpn": (d, smp, c.other_alpn()),
            "p256": (d, smp, c.p256_cert()),
            "no-cert": (d, smp, c.no_certificate()),
        }
        who, body, switches = modes[mode]
        return line(c.dial(ADDR[target], who, self.real if real else self.verifier, body, timeout=6.0, **switches))

    def inflight(self, target):
        """inflight_max is 2: two connections stay silent before their advert, the third is closed at once. They are
        opened half a second apart, so the node's lines about them come in one order."""
        d, smp = self.driver, c.sample("tempus_edge", 1)
        held = [threading.Thread(target=c.dial, args=(ADDR[target], d, self.verifier, smp), kwargs={"misbehaviour": c.silent_at("advert", 1.6), "timeout": 4.0})
                for _ in range(2)]
        for t in held:
            t.start()
            time.sleep(0.5)
        out = c.dial(ADDR[target], d, self.verifier, smp, timeout=3.0)
        for t in held:
            t.join()
        T.quiet(1.0)
        again = c.dial(ADDR[target], d, self.verifier, smp, timeout=4.0)
        return "the third: %s; afterwards: %s" % ("closed at once" if out.what in ("closed", "tls_failed") else out.line(), again.what)

    def peer(self, mode):
        x3 = self.x3
        good = lambda rq: c.shuffle_reply("tempus_edge", [])  # noqa: E731
        modes = {"names-k9": (x3, good, {}, self.k9), "good": (x3, good, {}, None)}
        who, handler, switches, verifier = modes[mode]
        self.listener = c.Listener(who, verifier or self.verifier, handler, [T.cert("other")], port=BASE + 6, timeout=5.0, **switches).start()
        return ""

    def peerdone(self):
        outs = self.listener.outcomes(1, wait=8.0)
        self.listener.close()
        self.listener = None
        T.check(len(outs) == 1, "the Python listener saw no connection end")
        return line(outs[0])

    def do(self, request):
        words = request.split(" ", 2)
        if words[0] not in ("start", "stop", "wait", "tick", "audit", "pydial", "inflight", "peer", "peerdone"):
            raise SystemExit("FAIL: no such request: " + request)
        return getattr(self, words[0])(*words[1:])

    def close(self):
        if self.listener is not None:
            self.listener.close()
        for n in list(self.nodes.values()):
            n.stop()


def main(argv):
    if len(argv) != 4:
        print(__doc__)
        return 2
    leaf, java, jar = os.path.abspath(argv[1]), argv[2], argv[3]
    tool = Tool(leaf)
    lines = []
    proc = subprocess.Popen([java, "-cp", jar, "bees.tempus.trial.NetKt", ROOT, str(BASE), leaf], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
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
            except Exception as why:                       # a fault of this tool: say so, and let the program end
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
        print("\n".join(ln for ln in lines if ln.startswith("FAIL")) or "FAIL: [c9_tempus_node_kotlin] the Kotlin program ended with exit code %d" % rc)
    else:
        print(lines[-1])
    return 0 if rc == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
