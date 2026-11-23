#!/usr/bin/env python3
"""C12: run the walk of the client half of the C# TEMPUS extension (Walk.cs beside this file) against real nodes.

    walk.py LEAF_DIR DOTNET WALK_DLL DRIVER_DLL

The C# program holds the scenario and checks every step. This tool does for it what a client cannot do, one request
line (`@...` on the C# program's standard output) at a time, each answered with one line (`ok ...` or `fail ...`):

    @start k | @start q      start a node process of this leaf and wait until it serves
    @stop k | @stop q        tell it to exit; its output goes to dangerous_k.sout or dangerous_q.sout
    @wait NAME REGEX         wait for a line of that node's output
    @tick NAME STORE         send the node the test-only tick frame, with the Python example client (the C# client
                             has no such frame), and wait for its answer
    @peer MODE, @peerdone    the Python example client listens on this trial's port +4 for one connection and behaves
                             as MODE says; @peerdone answers with what that listener saw
    @pydial MODE             the Python example client dials the C# client's listener (port +3) as MODE says; the
                             answer is what the dialer saw
    @cli-dial, @cli-listen   run the C# client's command line once against node Q, and once listening

Every other line of the C# program is its transcript, written to csharp.sout with the program's exit code. The node
processes are run as tools/bees_tempus_trial.py runs them. Keys, certificates and tokens are TEST ONLY.
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import bees_tempus_trial as T  # noqa: E402
import trial_ports  # noqa: E402

c = T.c
A = c.Atom
BASE = trial_ports.TABLE["c12_tempus_csharp"][0]
K, Q, S_ADDR, E_ADDR, P_ADDR, DEAD = ("127.0.0.1:%d" % (BASE + k) for k in range(6))
READY = {"k": r"^join: done$", "q": r"^join: no sentinel is configured$"}
PROD, OLD = c.fixture_key(0), c.fixture_key(96)


def ident(first, typ, exp, addr, certname=None, nbf=1000, **kw):
    i = c.fixture_identity(first, typ, nbf, exp, addr=addr, **kw)
    return c.Identity(i.seed, i.token, addr, cert_pem=T.cert(certname)) if certname else i


def line(out):
    """What the Python peer saw, as one line. The text of a failed handshake is the TLS library's own and differs between
    versions; and the step at which a peer finds its connection closed depends on which of two frames in flight came
    first, so of a close only the fact is kept (and that it was made on purpose, where it was)."""
    if out.what == "tls_failed":
        return "tls_failed"
    if out.what == "closed":
        return "closed, on purpose" if out.reason == c.ON_PURPOSE else "closed"
    return out.line()


class Tool:
    def __init__(self, leaf, dotnet, driver):
        self.leaf, self.dotnet, self.driver_dll = leaf, dotnet, driver
        self.nodes = {}
        self.verifier = T.Peer().verifier                                  # the producer key, kid k1, the clock 1500, skew 10
        self.k9 = c.Verifier(c._raw_public(PROD), "k9", 1500, 10)
        self.driver = ident(112, "tempus_edge", 3000, DEAD)                 # sends the ticks; a certificate no node has seen
        self.x3 = ident(208, "tempus_edge", 3000, P_ADDR, "x3")             # the listening peer
        self.x4 = ident(224, "tempus_bridge", 3000, P_ADDR, "x4")           # the listening peer with a bridge token
        self.x1 = ident(176, "tempus_edge", 2000, DEAD)
        self.x2 = ident(192, "tempus_edge", 2000, DEAD)
        self.forged = ident(192, "tempus_edge", 2000, DEAD, producer=OLD)   # signed with a key that is not the producer's
        self.listener = None

    # ---- nodes
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
        out = c.dial({"k": K, "q": Q}[name], self.driver, self.verifier, c.tick(store), timeout=8.0)
        T.check(out.what == "reply" and out.kind == "done", "a tick to node %s: %s" % (name, out.line()))
        return ""

    # ---- the Python client as a listening peer that the C# client dials
    def peer(self, mode):
        x3, x4 = self.x3, self.x4
        good = lambda rq: c.sample_reply("tempus_edge", [self.x1.entry(1)])  # noqa: E731
        result = lambda rid: c.etf_encode({A("t"): A("result"), A("ver"): 1, A("req_id"): rid, A("value"): 5})  # noqa: E731
        issued = c.certificate_pem(x3.key, "bees tempus test issued", 9, issuer_key=c.fixture_key(160), issuer_name="bees tempus test issuer")
        modes = {  # mode -> (identity, handler, the Listener's switches, its verifier)
            "bridge-result": (x4, lambda rq: result(rq.fields["req_id"]), {}, None),
            "bridge-other-req-id": (x4, lambda rq: result(b"zz"), {}, None),
            "bridge-cast": (x4, lambda rq: None, {}, None),
            "binding": (x3, good, {"misbehaviour": c.wrong_advert(self.x2.advert())}, None),
            "wrong-proof": (x3, good, {"misbehaviour": c.wrong_proof_other_nonce()}, None),
            "names-k9": (x3, good, {}, self.k9),
            "old-kid": (ident(208, "tempus_edge", 3000, P_ADDR, "x3", kid="k0", producer=OLD), good, {}, None),
            "forged-entry": (x3, lambda rq: c.sample_reply("tempus_edge", [self.x1.entry(1), self.forged.entry(0)]), {}, None),
            "other-store": (x3, lambda rq: c.sample_reply("tempus_bridge", []), {}, None),
            "shuffle-reply": (x3, lambda rq: c.shuffle_reply("tempus_edge", []), {}, None),
            "three-entries": (x3, lambda rq: c.sample_reply("tempus_edge", [self.x1.entry(1), self.x2.entry(2), x3.entry(0)]), {}, None),
            "oversize": (x3, lambda rq: c.send_raw(b"\x00\x02\x00\x01"), {}, None),
            "closes": (x3, lambda rq: c.CLOSE, {}, None),
            "silent": (x3, lambda rq: c.stay_silent(3.0), {}, None),
            "wrong-frame": (x3, good, {"misbehaviour": c.wrong_frame_at("challenge", c.sample("tempus_edge", 1))}, None),
            "done": (x3, lambda rq: c.done(), {}, None),
            "issued": (x3, good, {"tls_cert": (issued, x3.key_pem)}, None),
            "p256": (x3, good, {"tls_cert": c.p256_certificate()}, None),
            "tls12": (x3, good, c.tls12_only(), None),
            "alpn": (x3, good, c.other_alpn(), None),
        }
        who, handler, switches, verifier = modes[mode]
        self.listener = c.Listener(who, verifier or self.verifier, handler, [T.cert("other")], port=BASE + 4, timeout=5.0, **switches).start()
        return ""

    def peerdone(self):
        outs = self.listener.outcomes(1, wait=8.0)
        self.listener.close()
        self.listener = None
        T.check(len(outs) == 1, "the Python listener saw no connection end")
        return line(outs[0])

    # ---- the Python client as a dialing peer of the C# client's listener
    def pydial(self, mode):
        d = self.driver
        smp = c.sample("tempus_edge", 2)
        tok = lambda **kw: c.make_token(kw.get("signer", PROD), kw.get("kid", "k1"), d.pub, kw.get("typ", "tempus_edge"), 1000, kw.get("exp", 3000))  # noqa: E731
        modes = {  # mode -> (identity, request body, dial's switches)
            "good": (d, smp, {}),
            "shuffle": (d, c.shuffle("tempus_edge", [d.entry(0)]), {}),
            "binding": (d, smp, {"misbehaviour": c.wrong_advert(self.x2.advert())}),
            "proof-other-key": (d, smp, {"misbehaviour": c.wrong_proof_other_key(c.fixture_key(224))}),
            "no-proof": (d, smp, {"misbehaviour": c.no_proof()}),
            "oversize-advert": (d, smp, {"misbehaviour": c.oversize_frame_at("advert")}),
            "expired": (d.with_token(tok(exp=1400)), smp, {}),
            "old-kid": (d.with_token(tok(signer=OLD, kid="k0")), smp, {}),
            "sentinel-token": (d.with_token(tok(typ="tempus_sentinel")), smp, {}),
            "tick": (d, c.tick("tempus_edge"), {}),
            "forged-shuffle": (d, c.shuffle("tempus_edge", [d.entry(0), self.forged.entry(0)]), {}),
            "sample-9": (d, c.sample("tempus_edge", 9), {}),
            "closes": (d, smp, {"misbehaviour": c.close_after_advert()}),
            "p256": (d, smp, c.p256_cert()),
        }
        who, body, switches = modes[mode]
        return line(c.dial(E_ADDR, who, self.verifier, body, timeout=6.0, **switches))

    # ---- the C# client's command line
    def _cli(self, tmp, token, *words):
        path = os.path.join(tmp, "token.hex")
        with open(path, "w") as f:
            f.write(token.hex() + "\n")
        certs = os.path.join(ROOT, "trials", "t5_tempus_tls", "certs")
        return [self.dotnet, self.driver_dll, words[0], words[1], "--cert", os.path.join(certs, "other.pem"), "--key", os.path.join(certs, "other-key.pem"),
                "--token", path, "--addr", E_ADDR, "--producer-pub", c._raw_public(PROD).hex(), "--kid", "k1", "--skew", "10",
                "--timeout-ms", "5000", "--shuffle-length", "3"] + list(words[2:])

    def cli_dial(self):
        """against node Q, by the machine's clock (no --now)"""
        me = ident(64, "tempus_edge", 4000000000, E_ADDR)
        with tempfile.TemporaryDirectory(prefix="bees_c12_") as tmp:
            r = subprocess.run(self._cli(tmp, me.token, "dial", Q, "sample", "tempus_edge", "3"), capture_output=True, text=True, timeout=30)
        T.check(r.returncode == 0, "the command line failed: " + r.stderr)
        T.quiet()
        return r.stdout.strip()

    def cli_listen(self):
        """listening on port +3 for one connection, with the trial's clock; the Python client dials it with a shuffle"""
        me = ident(64, "tempus_edge", 3000, E_ADDR)
        with tempfile.TemporaryDirectory(prefix="bees_c12_") as tmp:
            p = subprocess.Popen(self._cli(tmp, me.token, "listen", E_ADDR, "--now", "1500", "--count", "1"), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                said = p.stderr.readline()
                if not said.startswith("listening on"):
                    raise SystemExit("FAIL: the command line did not listen: " + (said + p.stderr.read()).strip())
                out = c.dial(E_ADDR, self.driver, self.verifier, c.shuffle("tempus_edge", [self.driver.entry(0)]), timeout=6.0)
                served = p.stdout.readline().strip()
                T.check(p.wait(timeout=15) == 0, "the listening command line did not end")
            finally:
                if p.poll() is None:
                    p.kill()
        return "%s; the peer: %s" % (served, line(out))

    def do(self, request):
        words = request.split(" ", 2)
        name = words[0].replace("-", "_")
        if name not in ("start", "stop", "wait", "tick", "peer", "peerdone", "pydial", "cli_dial", "cli_listen"):
            raise SystemExit("FAIL: no such request: " + request)
        return getattr(self, name)(*words[1:])

    def close(self):
        if self.listener is not None:
            self.listener.close()
        for n in list(self.nodes.values()):
            n.stop()


def main(argv):
    if len(argv) != 5:
        print(__doc__)
        return 2
    leaf, dotnet, walk_dll, driver = os.path.abspath(argv[1]), argv[2], argv[3], argv[4]
    tool = Tool(leaf, dotnet, driver)
    lines = []
    proc = subprocess.Popen([dotnet, walk_dll, ROOT, str(BASE)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
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
        print("\n".join(ln for ln in lines if ln.startswith("FAIL")) or "FAIL: [c12_tempus_csharp] the C# walk ended with exit code %d" % rc)
    else:
        print(lines[-1])
    return 0 if rc == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
