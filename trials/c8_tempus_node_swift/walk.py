#!/usr/bin/env python3
"""Walk the trial of the Swift TEMPUS extension as a node (trials/c8_tempus_node_swift).

    walk.py LEAF_DIR DIRECTORY_OF_THE_SWIFT_PROGRAMS

A mixed network on 127.0.0.1: Silica nodes (the programs under nodes/, started as tools/bees_tempus_trial.py starts
them) and nodes of the Swift extension. Every step is checked here (a failed check fails the trial); what only a node
knows is in that node's own output, which is compared with its golden. The steps and what each saw on the wire are
written to walk.sout. Nothing of the wall clock is printed. Ports come from tools/trial_ports.py.

Part 1, clock 1500 everywhere, nothing left to chance (the Silica nodes S and E are test programs whose ticks are the
test-only tick frames this tool sends with the Python test support; the Swift node A is made with a clock, timers and
draws of the trial's, set through its command lines):
  join      the Silica edge E and the Swift edge A join through the Silica sentinel S
  shuffle   A starts a shuffle that E answers; E starts one that A answers; S (a store not of its own type) shuffles
            with one of them; A shuffles its sentinel store with S; each side's entries appear in the other's views
  refusals  one peer that misbehaves (the Python test support) does the same thing to E and to A, step by step, and the
            audit lines the two nodes write for it must be the same, as must what the peer saw of each
  clock     A's configured choices, clock_back hold and clock_fail continue: the hold beginning and ending, a reading
            that fails, an entry that expires, A's own token expiring and being replaced
  client    after A has stopped: the Swift CLIENT (the command line tempus-client) against S and E, for the rows of the
            behaviour list that the first Swift trial does not show and that need no bridge; its lines are client.sout
Part 2, the other clock choices on Swift nodes with no Silica node:
  T         clock_back stop with the limit 60 and clock_fail pause: the wait (an accepted connection closed with
            clock_refused, a join request that waits and is dialed at once when the clock is read again), a step back
            inside the limit, the stop above it (a connection closed with clock_stopped, no resume)
  U         a clock that cannot be read at the start: the node does not listen until a reading succeeds
Part 3, the machine's clock: the Swift node R is the program tempus-node-example, which is no test program: it links
nothing of the tests, reads the machine's clock, runs its own timers and draws from the system's random source. The
Silica node P, no test program either, joins through it; R's own timer then starts a shuffle that P answers; a tick
and a clock frame are refused by both in the same words.
Keys, certificates and tokens are TEST ONLY, from fixed seeds.
"""
import os
import re
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(HERE, "..", "..", "tools")
sys.path.insert(0, TOOLS)
sys.path.insert(0, os.path.join(HERE, "..", "..", "example_tempus_clients", "python"))  # the Python test support
import bees_tempus_client as c  # noqa: E402
import trial_ports  # noqa: E402
from bees_tempus_trial import CERTS, Node, cert, check, quiet  # noqa: E402
from bees_tempus_swift_trial import Swift as SwiftClient, seed  # noqa: E402

BASE = trial_ports.TABLE["c8_tempus_node_swift"][0]
S_ADDR, E_ADDR, P_ADDR, A_ADDR, T_ADDR, R_ADDR, U_ADDR, DEAD = ("127.0.0.1:%d" % (BASE + k) for k in range(8))
K_ADDR = "127.0.0.1:%d" % (BASE + 8)      # where the Swift client (the command line tempus-client) listens
PRODUCER = c._raw_public(c.fixture_key(0))
FAR = 4000000000                    # a token's end that any present clock is before
A = c.Atom


class Swift:
    """One Swift node process. Its output goes to NAME.sout with its exit code, as a Silica node's does."""

    def __init__(self, leaf, name, argv):
        self.name, self.out_path, self.seen, self.chunks = name, os.path.join(leaf, name + ".sout"), 0, []
        self.proc = subprocess.Popen(argv, cwd=leaf, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.lock = threading.Condition()
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()

    def _read(self):
        for line in self.proc.stdout:
            with self.lock:
                self.chunks.append(line)
                self.lock.notify_all()
        with self.lock:
            self.lock.notify_all()

    def text(self):
        return b"".join(self.chunks).decode("utf-8", "replace")

    def wait(self, pattern, timeout=20.0):
        rx = re.compile(pattern, re.M)
        until = time.monotonic() + timeout
        with self.lock:
            while True:
                text = self.text()
                m = rx.search(text, self.seen)
                if m:
                    self.seen = text.find("\n", m.end()) + 1
                    return m
                left = until - time.monotonic()
                if left <= 0 or (self.proc.poll() is not None and not self.thread.is_alive()):
                    raise SystemExit("FAIL: %s did not print /%s/ in time; its output so far:\n%s" % (self.name, pattern, text))
                self.lock.wait(min(left, 0.2))

    def tell(self, command, wait=None):
        """one command line of tempus-node-trial; `wait`: the line that shows it was carried out"""
        self.proc.stdin.write((command + "\n").encode())
        self.proc.stdin.flush()
        if wait:
            self.wait(wait)
        quiet(0.3)

    def stop(self):
        if self.proc.poll() is None:
            try:
                self.proc.stdin.write(b"exit\n")
                self.proc.stdin.flush()
                self.proc.stdin.close()
            except Exception:
                pass
        try:
            rc = self.proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            rc = self.proc.wait()
            self.chunks.append(b"[walk] killed\n")
        self.thread.join(timeout=5)
        with open(self.out_path, "w") as f:
            f.write(self.text())
            f.write("exit=%d\n" % rc)


def ident(first, typ, exp, addr, certname=None, nbf=1000, **kw):
    i = c.fixture_identity(first, typ, nbf, exp, addr=addr, **kw)
    return c.Identity(i.seed, i.token, addr, cert_pem=cert(certname)) if certname else i


def id8(first):
    return c.peer_id(c._raw_public(c.fixture_key(first)))[:4].hex()


def audit_lines(text):
    """the audit lines of a node's output that say what it did with a peer, without the connection's number"""
    out = []
    for ln in text.split("\n"):
        if ln.startswith("[tempus audit] ") and " tls_established " not in ln:
            ln = re.sub(r" [ad]\d+$", "", ln)
            out.append(re.sub(r"^(\[tempus audit\] closed_by_peer) peer=\S+ stage [a-z_]+", r"\1 peer=(any) stage (any)", ln))
    return out


class Walk:
    def __init__(self, leaf, bindir):
        self.leaf, self.bindir, self.nodes = leaf, bindir, {}
        self.out = open(os.path.join(leaf, "walk.sout"), "w")
        self.sentinel_pem = os.path.join(CERTS, "sentinel.pem")

    def say(self, text):
        self.out.write(text + "\n")
        self.out.flush()

    def silica(self, name):
        self.nodes[name] = Node(os.path.join(self.leaf, "nodes", name), "dangerous_" + name)
        return self.nodes[name]

    def swift(self, name, **kw):
        """a node made by tempus-node-trial: its clock, timers and draws are the trial's"""
        args = {"stores": "4/3,4/2,4/2", "inflight_max": "2", "shuffle_timeout_ms": "2000", "draws": "0,1,2,3", "join_retry": "3000/3000"}
        args.update(kw)
        argv = [os.path.join(self.bindir, "tempus-node-trial")] + ["%s=%s" % kv for kv in sorted(args.items())]
        self.nodes[name] = Swift(self.leaf, name, argv)
        return self.nodes[name]

    def stop(self, name):
        self.nodes.pop(name).stop()

    def close(self):
        for name in list(self.nodes):
            self.stop(name)
        self.out.close()

    def tick(self, addr, store, who, verifier):
        out = c.dial(addr, who, verifier, c.tick(store))
        check(out.what == "reply" and out.kind == "done", "a test-only tick frame to the Silica node at %s: %s" % (addr, out.line()))



def settle(node, mark, wait, limit=10.0):
    """Wait until the node has written at least one audit line since `mark` (a node under load may take longer than
    `wait` to write it), then `wait` more for any further line of the same connection. Each node in these comparisons
    writes at least one audit line for each case, so the wait ends; `limit` bounds it if a node writes none."""
    until = time.monotonic() + limit
    while not audit_lines(node.text()[mark:]) and time.monotonic() < until:
        time.sleep(0.05)
    quiet(wait)

def part_one(w):
    v = c.Verifier(PRODUCER, "k1", 1500, 10)
    ticker = ident(112, "tempus_edge", 3000, DEAD)            # the trial tool's own peer, for the test-only ticks
    e8, a8, s8 = id8(32), id8(176), id8(128)
    w.say("# part 1: the Silica sentinel S, the Silica edge E and the Swift edge A; every clock is 1500")
    s = w.silica("s")
    s.wait(r"^join: no sentinel is configured$")
    e = w.silica("e")
    e.wait(r"^join: done$")
    quiet()
    a = w.swift("a", role="edge", port=BASE + 3, seed=176, token="tempus_edge:1000:4000", sentinels=S_ADDR,
                whitelist=w.sentinel_pem, clock_back="hold", clock_fail="continue", now=1500)
    a.wait(r"^join: done$")
    quiet()
    text = a.text()
    check("view tempus_edge: %s@0" % e8 in text, "A's join did not bring it E from S's edge store:\n" + text)
    check("view tempus_sentinel: %s@0" % s8 in text, "A did not keep the sentinel it joined through (ruling NQ-12):\n" + text)
    w.say("J1 E joined through S, then A joined through S: A holds E in its edge store and S in its sentinel store")
    # a shuffle A starts and E answers
    a.tell("tick tempus_edge", r"^tick tempus_edge: shuffle merged$")
    quiet()
    e.wait(r"^view tempus_edge: %s@0$" % a8)
    w.say("H1 A's tick: A shuffled its edge store with E, its own entry first at age 0; E holds A at age 0")
    # a shuffle E starts and A answers
    w.tick(E_ADDR, "tempus_edge", ticker, v)
    e.wait(r"^tick tempus_edge: shuffle merged$")
    quiet()
    a.wait(r"^view tempus_edge: %s@0$" % e8)
    w.say("H2 E's tick: E shuffled its edge store with A; A answered and holds E at age 0")
    # the sentinel S shuffles its edge store, which is not of its own type, with one of the two edges
    w.tick(S_ADDR, "tempus_edge", ticker, v)
    m = s.wait(r"^tick tempus_edge: shuffle with (\S+) at ")
    s.wait(r"^tick tempus_edge: shuffle merged$")
    quiet()
    check(m.group(1) in (e8, a8), "S shuffled with somebody else: " + m.group(1))
    w.say("H3 S's tick: S shuffled its edge store with %s" % ("A" if m.group(1) == a8 else "E"))
    # A shuffles its sentinel store, which is not of its own type, with S: S is put back at age 0 (ruling NQ-15)
    a.tell("tick tempus_sentinel", r"^tick tempus_sentinel: shuffle merged$")
    quiet()
    check(a.text().rstrip().split("\n")[-2] == "view tempus_sentinel: %s@0" % s8, "A did not put S back (ruling NQ-15):\n" + a.text())
    w.say("H4 A's tick of its sentinel store: A shuffled with S and holds S at age 0 again")
    # what a peer sees of A: the Python test support samples A, and every entry A answers with verifies
    x = ident(208, "tempus_edge", 3000, DEAD)
    out = c.dial(A_ADDR, x, v, c.sample("tempus_edge", 3), shuffle_length=3)
    check(out.what == "reply" and out.kind == "sample_reply", "a sample of A: " + out.line())
    for _age, d in out.fields["entries"]:
        v.check_descriptor(d)
    w.say("H5 a sample of A's edge store by another peer -> " + out.line())
    quiet()
    refusals(w, s, e, a, v)
    clock_of_a(w, a, v)
    w.stop("a")
    client(w, s, e, v, ticker)
    w.stop("e")
    w.stop("s")


def refusals(w, s, e, a, v):
    """The same misbehaviour to the Silica node E and to the Swift node A: the same audit lines, and the peer sees the same."""
    w.say("# refusals: each step is done to the Silica node E and to the Swift node A, and their audit lines are compared")
    other = c.fixture_key(96)
    x = ident(208, "tempus_edge", 3000, DEAD)
    third = ident(224, "tempus_edge", 3000, DEAD)
    forged = ident(224, "tempus_edge", 3000, DEAD, producer=other)
    smp = c.sample("tempus_edge", 3)
    wrong_id = c.advert(c.descriptor(third.peer_id, x.pub, DEAD, x.token))
    bridges = [ident(f, "tempus_bridge", 3000, DEAD).entry(1) for f in (160, 208, 224)]
    steps = [
        ("an expired token", ident(208, "tempus_edge", 1400, DEAD), smp, {}),
        ("a token that is not valid yet", ident(208, "tempus_edge", 2000, DEAD, nbf=1800), smp, {}),
        ("a token another key signed", ident(208, "tempus_edge", 3000, DEAD, producer=other), smp, {}),
        ("a token under the old kid", ident(208, "tempus_edge", 3000, DEAD, kid="k0", producer=other), smp, {}),
        ("a token whose sub is another key", ident(208, "tempus_edge", 3000, DEAD, sub=third.pub), smp, {}),
        ("somebody else's advert", x, smp, {"misbehaviour": c.wrong_advert(third.advert())}),
        ("an advert whose id is not the hash of its pub", x, smp, {"misbehaviour": c.wrong_advert(wrong_id)}),
        ("a sentinel token under a certificate that is not whitelisted", ident(208, "tempus_sentinel", 3000, DEAD), smp, {}),
        ("a whitelisted certificate with an edge token", ident(128, "tempus_edge", 3000, DEAD, "sentinel"), smp, {}),
        ("a proof by another key", x, smp, {"misbehaviour": c.wrong_proof_other_key(c.fixture_key(224))}),
        ("a proof over another nonce", x, smp, {"misbehaviour": c.wrong_proof_other_nonce()}),
        ("a proof of 63 bytes", x, smp, {"misbehaviour": c.wrong_proof_bytes(bytes(63))}),
        ("no proof: the request comes where it was due", x, smp, {"misbehaviour": c.no_proof()}),
        ("a first frame that is no advert", x, smp, {"misbehaviour": c.wrong_frame_at("advert", smp)}),
        ("a second advert where the challenge was due", x, smp, {"misbehaviour": c.wrong_frame_at("challenge", x.advert())}),
        ("a first frame above the frame ceiling", x, smp, {"misbehaviour": c.oversize_frame_at("advert")}),
        ("a request above the frame ceiling", x, smp, {"misbehaviour": c.oversize_frame_at("request")}),
        ("a sample of more than the shuffle length", x, c.sample("tempus_edge", 9), {}),
        ("a sample of more than the store's shuffle length", x, c.sample("tempus_bridge", 3), {}),
        ("a sample with an unknown key", x, c.etf_encode({A("t"): A("sample"), A("store"): A("tempus_edge"), A("n"): 1, A("age"): 1}), {}),
        ("a sample of a store that is no peer type", x, c.etf_encode({A("t"): A("sample"), A("store"): A("advert"), A("n"): 1}), {}),
        ("a shuffle of more entries than the shuffle length", x, c.shuffle("tempus_edge", [x.entry(0)] + [third.entry(k) for k in (1, 2, 3)]), {}),
        ("a shuffle with an age above 65535", x, c.etf_encode({A("t"): A("shuffle"), A("store"): A("tempus_edge"),
                                                              A("entries"): [{A("age"): 65536, A("d"): x.descriptor()}]}), {}),
        ("a shuffle with an entry another key signed, beside a good one", x, c.shuffle("tempus_edge", [x.entry(0), forged.entry(2)]), {}),
        ("a shuffle of the sentinel store with an edge's entry", x, c.shuffle("tempus_sentinel", [x.entry(0)]), {}),
        ("a shuffle of the bridge store with more entries than that store's shuffle length", x, c.shuffle("tempus_bridge", bridges), {}),
        ("a request that is no term", x, smp, {"misbehaviour": c.wrong_frame_at("request", b"hello")}),
        ("a reply frame where a request was due", x, c.shuffle_reply("tempus_edge", []), {}),
        ("a call: neither node is a bridge", x, c.call_frame("1", "m", "f", [2, 40]), {}),
        ("a cast: neither node is a bridge", x, c.call_frame("1", "m", "f", [], kind="cast"), {}),
        ("the peer closes after its advert", x, smp, {"misbehaviour": c.close_after_advert()}),
        ("the peer stays silent where its request was due, past the node's time bound", x, smp, {"misbehaviour": c.silent_at("request", 2.6), "wait": 0.3}),
        ("the peer stays silent where its proof was due, past the node's time bound", x, smp, {"misbehaviour": c.silent_at("response", 2.6), "wait": 0.3}),
        ("TLS: another ALPN protocol", x, smp, c.other_alpn("h2")),
        ("TLS: no certificate", x, smp, c.no_certificate()),
        ("TLS: a P-256 certificate", x, smp, c.p256_cert()),
        ("TLS: version 1.2 only", x, smp, c.tls12_only()),
    ]
    for k, (label, who, body, how) in enumerate(steps, start=1):
        how = dict(how)
        wait = how.pop("wait", 0.7)
        seen = []
        for name, node, addr in (("E", e, E_ADDR), ("A", a, A_ADDR)):
            mark = len(node.text())
            out = c.dial(addr, who, v, body, shuffle_length=3, **how)
            settle(node, mark, wait)
            seen.append((name, (out.what, out.stage if out.what != "tls_failed" else "tls"), audit_lines(node.text()[mark:])))
        compare(w, "R%d" % k, label, seen)
    # more accepted connections than inflight_max (2): two are held open, the third is closed at once
    seen = []
    for name, node, addr in (("E", e, E_ADDR), ("A", a, A_ADDR)):
        mark = len(node.text())
        held = [threading.Thread(target=c.dial, args=(addr, x, v, smp), kwargs={"misbehaviour": c.silent_at("request", 1.2)}) for _ in range(2)]
        for t in held:
            t.start()
            quiet(0.3)
        out = c.dial(addr, x, v, smp, shuffle_length=3)
        for t in held:
            t.join()
        quiet()
        lines = [ln for ln in audit_lines(node.text()[mark:]) if "closed_by_peer" not in ln and " admitted " not in ln]
        seen.append((name, (out.what, out.stage), lines))
    compare(w, "R%d" % (len(steps) + 1), "a third connection while two are held open (inflight_max is 2)", seen)


def client(w, s, e, v, ticker):
    """The Swift CLIENT (the command line tempus-client, target TempusClient) against the Silica nodes S and E: the rows of
    the behaviour list (design 16.2) that trials/c5_tempus_swift does not show for it and that need no bridge
    (trials/c10_tempus_bridge_swift/COVERAGE.md). The client's lines go to client.sout. It sends no test-only frame: the
    ticks and clock readings are sent here with the Python test support."""
    sw = SwiftClient(os.path.join(w.bindir, "tempus-client"), os.path.join(w.leaf, "client.sout"))
    now = ["--now", "1500"]
    s8, e8, k8 = c.peer_id(c._raw_public(c.fixture_key(128)))[:8].hex(), c.peer_id(c._raw_public(c.fixture_key(32)))[:8].hex(), \
        c.peer_id(c._raw_public(c.fixture_key(64)))[:8].hex()
    K = ["--seed", seed(64), "--addr", K_ADDR, "--test-token", "tempus_edge:1000:3000"]
    ps, pe = " peer=%s typ=tempus_sentinel" % s8, " peer=%s typ=tempus_edge" % e8
    gone = "closed at=reply" + pe
    producer = c._raw_public(c.fixture_key(0))
    late = ident(112, "tempus_edge", 5000, DEAD)            # the trial tool's own peer: its token is still good at E's last clock

    def dial(label, addr, who, words, want, **kw):
        line = sw.dial(label, addr, who, kw.pop("clock", now), words, want, **kw)
        quiet()
        return line

    def frame(addr, body, clock=1500):
        out = c.dial(addr, late, c.Verifier(producer, "k1", clock, 10), body)
        check(out.what == "reply" and out.kind == "done", "a test-only frame to %s (the trial tool's own): %s" % (addr, out.line()))

    def until_dialed(lis, addr, store, label):
        ticks = 0
        while lis.pending() == 0 and ticks < 5:
            frame(addr, c.tick(store))
            ticks += 1
            quiet(1.0)
        sw.say("%s the trial tool sent %d test-only ticks" % (label, ticks))

    try:
        sw.say("# the Swift client against the Silica nodes S (a sentinel) and E (an edge); their clock is 1500")
        one = dial("K1 sample tempus_edge 3 of E", E_ADDR, K, ["sample", "tempus_edge", "3"], lambda ln: ln.startswith("reply sample_reply "), any_order=True)
        dial("K2 the same sample again: the same entries, the view is unchanged", E_ADDR, K, ["sample", "tempus_edge", "3"], one, any_order=True)
        dial("K3 sample tempus_edge 3 of the sentinel S, which then holds the client in its edge store", S_ADDR, K, ["sample", "tempus_edge", "3"],
             lambda ln: ln.startswith("reply sample_reply ") and ln.endswith(ps), any_order=True, more=["--whitelist-cert", w.sentinel_pem])
        # a store that is not of the node's own type: S's edge store. S's shuffle frame holds no entry for S itself
        lis = sw.listen("K4 the Swift client listens as the edge", K_ADDR, K, now, entries=["tempus_edge=2:192:tempus_edge:1000:3000:" + DEAD])
        until_dialed(lis, S_ADDR, "tempus_edge", "K4")
        lis.next("K4 S shuffles its edge store, which is not of its own type, with the client: no entry for S in the frame",
                 lambda ln: ln.startswith("served shuffle entries=[") and s8 not in ln.split(" store=")[0] and ln.endswith(" store=tempus_edge sent=reply" + ps))
        s.wait(r"^tick tempus_edge: shuffle merged$")
        quiet()
        last = [ln for ln in s.text().split("\n") if ln.startswith("view tempus_edge:")][-1]
        check(" %s@0" % k8[:8] in last and " %s@2" % c.peer_id(c._raw_public(c.fixture_key(192)))[:4].hex() in last,
              "K5: S did not put the client back at age 0 beside the entry it answered with (ruling NQ-15): " + last)
        sw.say("K5 S's own view line after the merge holds the client at age 0 (ruling NQ-15) and the entry the client answered with at age 2")
        lis.stop()
        # an entry that does not verify in the client's answer: a bridge's token in the edge store
        lis = sw.listen("K6 the Swift client listens again; it will answer with an entry whose token is of another type", K_ADDR, K, now,
                        entries=["tempus_edge=1:208:tempus_bridge:1000:3000:" + DEAD])
        until_dialed(lis, S_ADDR, "tempus_edge", "K6")
        lis.next("K6 S shuffles with the client", lambda ln: ln.startswith("served shuffle entries=[") and ln.endswith(" store=tempus_edge sent=reply" + ps))
        s.wait(r"entry_refused peer=\S+ entry 0: typ is not the store's type")
        s.wait(r"^tick tempus_edge: shuffle failed$")
        quiet()
        lis.stop()
        dial("K7 sample: nothing of that answer entered S's view, and the client, which gave it, is gone from it", S_ADDR, K, ["sample", "tempus_edge", "3"],
             lambda ln: ln.startswith("reply sample_reply ") and k8 not in ln.split(" store=")[0], any_order=True)
        # bounds, sent as bytes another program wrote (the Swift client builds no wrong frame itself)
        dial("K8 a sample with an unknown key", E_ADDR, K, ["raw", c.etf_encode({A("t"): A("sample"), A("store"): A("tempus_edge"), A("n"): 1, A("age"): 1}).hex()], gone)
        e.wait(r"protocol_error peer=\S+ unknown_field")
        me = c.fixture_identity(64, "tempus_edge", 1000, 3000, addr=K_ADDR)
        dial("K9 a shuffle with an age above 65535", E_ADDR, K, ["raw", c.etf_encode({A("t"): A("shuffle"), A("store"): A("tempus_edge"),
             A("entries"): [{A("age"): 65536, A("d"): me.descriptor()}]}).hex()], gone)
        e.wait(r"protocol_error peer=\S+ age is not 0 to 65535")
        dial("K10 a request that is no term", E_ADDR, K, ["raw", b"hello".hex()], gone)
        e.wait(r"protocol_error peer=\S+ not a request: bad_version")
        other = c._raw_public(c.fixture_key(96))
        dial("K11 a token issued for another key", E_ADDR, ["--seed", seed(64), "--addr", K_ADDR, "--token",
             c.make_token(c.fixture_key(0), "k1", other, "tempus_edge", 1000, 3000).hex()], ["sample", "tempus_edge", "3"], "closed at=challenge" + pe)
        e.wait(r"admission_refused peer=\S+ sub is not the peer's key")
        # entries whose token has expired leave the view; then the node's own token expires
        short = ["--seed", seed(208), "--addr", DEAD, "--test-token", "tempus_edge:1000:2000"]
        x8 = c.peer_id(c._raw_public(c.fixture_key(208)))[:8].hex()
        dial("K12 as an edge whose token ends at 2000: shuffle tempus_edge with E", E_ADDR, short, ["shuffle", "tempus_edge"],
             lambda ln: ln.startswith("reply shuffle_reply "), any_order=True)
        dial("K13 sample: E holds that edge", E_ADDR, K, ["sample", "tempus_edge", "3"], lambda ln: "0:" + x8 in ln, any_order=True)
        frame(E_ADDR, c.clock(2100 * 1000))
        frame(E_ADDR, c.tick("tempus_edge"), 2100)
        e.wait(r"^expired in tempus_edge:.* %s" % x8[:8])
        e.wait(r"^tick tempus_edge: ")
        quiet(2.5)
        dial("K14 the trial tool set E's clock to 2100 and sent a tick: that edge's entry has left E's view", E_ADDR, K, ["sample", "tempus_edge", "3"],
             lambda ln: ln.startswith("reply sample_reply ") and x8 not in ln, any_order=True, clock=["--now", "2100"])
        frame(E_ADDR, c.clock(3100 * 1000), 2100)
        frame(E_ADDR, c.tick("tempus_edge"), 2100)
        e.wait(r"^own token: the token has expired; ticking has stopped$")
        quiet()
        dial("K15 the trial tool set E's clock to 3100, past E's own token: E still answers, and the client refuses its advert", E_ADDR,
             ["--seed", seed(64), "--addr", K_ADDR, "--test-token", "tempus_edge:1000:5000"], ["sample", "tempus_edge", "3"],
             'refused at=advert peer=%s reason="the token has expired"' % e8, clock=["--now", "3100"])
    finally:
        sw.close()


def compare(w, tag, label, seen):
    (n1, saw1, lines1), (n2, saw2, lines2) = seen
    check(lines1, "%s %s: the Silica node %s wrote no audit line" % (tag, label, n1))
    check(lines1 == lines2, "%s %s: the audit lines differ\n  %s: %s\n  %s: %s" % (tag, label, n1, lines1, n2, lines2))
    check(saw1 == saw2, "%s %s: the peer saw %s of %s and %s of %s" % (tag, label, saw1, n1, saw2, n2))
    w.say("%s %s -> the peer saw %s at=%s; both nodes: %s" % (tag, label, saw1[0], saw1[1], " | ".join(ln[len("[tempus audit] "):] for ln in lines1)))


def clock_of_a(w, a, v):
    w.say("# the clock of A: clock_back hold, clock_fail continue")
    e8 = id8(32)
    smp = c.sample("tempus_edge", 3)
    short = ident(208, "tempus_edge", 1500, DEAD)           # a token that ends at 1500: with the skew 10, good until 1509
    a.tell("clock 1505")
    out = c.dial(A_ADDR, short, v, smp, shuffle_length=3)
    check(out.what == "reply", "C1: " + out.line())
    quiet()
    w.say("C1 A's clock reads 1505: a token that ends at 1500 is inside the skew of 10 -> " + out.what)
    a.tell("clock 1510")
    a.tell("clock 1490", r"^clock: the system clock went back by 20 s; the node holds its time until the system clock has reached it$")
    out = c.dial(A_ADDR, short, v, smp, shuffle_length=3)
    quiet()
    check(out.what == "closed", "C2: " + out.line())
    a.wait(r"admission_refused peer=\S+ the token has expired")
    w.say("C2 the clock goes back to 1490 and A holds 1510: the same token has expired by the held time -> " + out.what)
    a.tell("clock fail", r"^clock: the system clock could not be read: the node goes on with its last reading$")
    a.wait(r"^application: told that the system clock could not be read: the node goes on with its last reading$")
    x = ident(208, "tempus_edge", 3000, DEAD)
    out = c.dial(A_ADDR, x, v, smp, shuffle_length=3)
    quiet()
    check(out.what == "reply", "C3: " + out.line())
    w.say("C3 a reading fails: A goes on with its last reading and still serves -> " + out.what)
    a.tell("clock 1495", r"^clock: the system clock went back by 15 s; the node holds its time until the system clock has reached it$")
    a.tell("clock 1510", r"^clock: the system clock has reached the held time; the node follows it again$")
    w.say("C4 the next reading, 1495, is still behind: the hold is said once more; at 1510 the hold ends")
    # an entry whose token has expired leaves the view at the next tick (E's token ends at 3000)
    a.tell("clock 3050")
    a.tell("tick tempus_edge", r"^expired in tempus_edge: %s$" % e8)
    a.wait(r"^join: no sentinel answered for tempus_edge$")
    quiet()
    w.say("C5 A's clock reads 3050: E's entry, whose token ended at 3000, left A's view; the view is empty, so A asked S again, and refused S's token, which has ended too")
    # A's own token (it ends at 4000) expires: ticking stops and the application is told; a new token starts it again
    a.tell("clock 4100")
    a.tell("tick tempus_edge", r"^own token: the token has expired; ticking has stopped$")
    a.wait(r"^application: told that the node's own token is not valid any more: the token has expired$")
    late = c.Verifier(PRODUCER, "k1", 4100, 10)
    out = c.dial(A_ADDR, ident(208, "tempus_edge", 5000, DEAD), late, smp, shuffle_length=3)
    quiet()
    check(out.what == "refused" and out.reason == "the token has expired", "C6: " + out.line())
    w.say("C6 A's clock reads 4100, past its own token: ticking stopped; A still listens, and a peer's own check refuses A's advert -> " + out.what)
    a.tell("token tempus_edge:1000:6000", r"^own token replaced$")
    a.tell("tick tempus_edge", r"^tick tempus_edge: the view is empty$")
    out = c.dial(A_ADDR, ident(208, "tempus_edge", 5000, DEAD), late, smp, shuffle_length=3)
    quiet()
    check(out.what == "reply", "C7: " + out.line())
    a.wait(r"^join: no sentinel answered for tempus_edge$")
    w.say("C7 the application passes a new token: A ticks again and a peer admits it -> " + out.what)


def part_two(w):
    v = c.Verifier(PRODUCER, "k1", 1500, 10)
    x = ident(208, "tempus_edge", 3000, DEAD)
    smp = c.sample("tempus_edge", 3)
    w.say("# part 2, node T: clock_back stop with the limit 60, clock_fail pause; no sentinel answers it")
    t = w.swift("t", role="edge", port=BASE + 4, seed=192, token="tempus_edge:1000:3000", sentinels=DEAD, whitelist=w.sentinel_pem,
                clock_back="stop", clock_back_limit_s=60, clock_fail="pause", now=1500)
    t.wait(r"^join: no sentinel answered for tempus_edge; waiting to try again$")
    t.tell("clock fail", r"^clock: the system clock could not be read: the node admits no connection and does not tick until it is read again$")
    t.wait(r"^application: told that the system clock could not be read")
    out = c.dial(T_ADDR, x, v, smp, shuffle_length=3)
    check(out.what == "closed" and out.stage == "advert", "T1: " + out.line())
    t.wait(r"clock_refused peer=- the system clock cannot be read: closed at once a1$")
    w.say("T1 a reading fails: T waits for its clock; a connection is closed at once after its handshake -> %s at=%s" % (out.what, out.stage))
    t.tell("tick tempus_edge")
    t.tell("retry", r"^join: the request for tempus_edge waits until the system clock is read again$")
    t.tell("clock 1501", r"^clock: the system clock is read again$")
    t.wait(r"^join: asking the sentinel at %s for tempus_edge d2$" % re.escape(DEAD))
    t.wait(r"^join: no sentinel answered for tempus_edge; waiting to try again$")
    w.say("T2 the join's retry falls due during the wait and dials nobody; when the clock is read again it is dialed at once")
    t.tell("clock 1450", r"^clock: the system clock went back by 51 s; the node follows it$")
    w.say("T3 a step back of 51 s, inside the limit of 60: followed")
    t.tell("clock 1380", r"^clock: the system clock went back by 70 s, more than clock_back_limit_s 60: the node has stopped")
    t.wait(r"^application: told that the system clock went back by 70 s")
    out = c.dial(T_ADDR, x, v, smp, shuffle_length=3)
    check(out.what == "closed" and out.stage == "advert", "T4: " + out.line())
    t.wait(r"clock_stopped peer=- the node stopped after its system clock went back: closed at once a2$")
    w.say("T4 a step back of 70 s, above the limit: T has stopped; a connection is closed at once -> %s at=%s" % (out.what, out.stage))
    t.tell("clock 2000")
    t.tell("retry")
    t.tell("tick tempus_edge")
    out = c.dial(T_ADDR, x, v, smp, shuffle_length=3)
    check(out.what == "closed" and out.stage == "advert", "T5: " + out.line())
    t.wait(r"clock_stopped peer=- .* a3$")
    w.say("T5 a later good reading, the join's retry and a tick change nothing: T stays stopped -> %s at=%s" % (out.what, out.stage))
    w.stop("t")

    w.say("# part 2, node U: its clock cannot be read at its start")
    u = w.swift("u", role="sentinel", port=BASE + 6, seed=160, token="tempus_sentinel:1000:3000", cert=os.path.join(CERTS, "bridge.pem"),
                clock_back="follow", clock_fail="pause")
    u.wait(r"^clock: the system clock could not be read: the node has not started$")
    u.wait(r"^application: told that the system clock could not be read: the node has not started$")
    out = c.dial(U_ADDR, x, v, smp, shuffle_length=3)
    check(out.what == "unreachable", "U1: " + out.line())
    w.say("U1 no reading at the start: U has not begun and does not listen -> " + out.what)
    u.tell("clock fail")
    u.tell("clock 1500", r"^clock: the system clock is read$")
    u.wait(r"^join: no sentinel is configured$")
    out = c.dial(U_ADDR, x, v, smp, shuffle_length=3)
    check(out.what == "reply", "U2: " + out.line())
    quiet()
    w.say("U2 the first reading that succeeds: U listens and serves -> " + out.what)
    w.stop("u")


def part_three(w):
    w.say("# part 3: the Swift node R (tempus-node-example, no test program) and the Silica node P; both read the machine's clock")
    with open(os.path.join(w.leaf, "r.seed"), "wb") as f:
        f.write(bytes(range(128, 160)))
    with open(os.path.join(w.leaf, "r.token"), "wb") as f:
        f.write(c.make_token(c.fixture_key(0), "k1", c._raw_public(c.fixture_key(128)), "tempus_sentinel", 1000, FAR))
    p = w.silica("p")                   # built without the test unit (nodes/p)
    p.wait(r"^join: no sentinel answered for tempus_edge; waiting to try again$")
    # P tries again 3 s from now. R's edge store ticks 6 s after R starts: after P's join, on R's own timer
    argv = [os.path.join(w.bindir, "tempus-node-example"), "role=sentinel", "listen_address=127.0.0.1", "port=%d" % (BASE + 5),
            "address=" + R_ADDR, "seed_file=r.seed", "cert_file=" + w.sentinel_pem, "token_file=r.token", "producer_kid=k1",
            "producer_key=" + PRODUCER.hex(), "edge=4/3/6000", "bridge=4/2/3600000", "sentinel=4/2/3600000",
            "shuffle_timeout_ms=2000", "inflight_max=2", "clock_skew_ms=10000", "clock_back=follow", "clock_fail=pause",
            "clock_read_ms=100", "join_retry_initial_ms=3000", "join_retry_max_ms=3000"]
    r = w.nodes["r"] = Swift(w.leaf, "r", argv)
    r.wait(r"^join: no sentinel is configured$")
    p.wait(r"^join: done$")
    w.say("M1 P's first try found nobody; R started; P's retry joined through R")
    r.wait(r"^tick tempus_edge: shuffle with %s at %s d1$" % (id8(64), re.escape(P_ADDR)))
    r.wait(r"^tick tempus_edge: shuffle merged$")
    w.say("M2 R's own timer ticked its edge store: R shuffled with P, and P answered")
    real = c.Verifier(PRODUCER, "k1", lambda: int(time.time()), 10)
    x = ident(208, "tempus_edge", FAR, DEAD)
    out = c.dial(R_ADDR, x, real, c.sample("tempus_edge", 3), shuffle_length=3)
    check(out.what == "reply" and [d[A("id")][:4].hex() for _a, d in out.fields["entries"]] == [id8(64)], "M3: " + out.line())
    quiet()
    w.say("M3 a sample of R's edge store by another peer, which reads the machine's clock too -> " + out.line())
    for k, (label, body) in enumerate((("a test-only tick frame", c.tick("tempus_edge")), ("a test-only clock frame", c.clock(1500000)),
                                       ("a test-only clock frame with two readings", c.clock(1500000, wait=100, later=1600000))), start=4):
        seen = []
        for name, node, addr in (("P", p, P_ADDR), ("R", r, R_ADDR)):
            mark = len(node.text())
            out = c.dial(addr, x, real, body, shuffle_length=3)
            settle(node, mark, 0.7)
            seen.append((name, (out.what, out.stage), audit_lines(node.text()[mark:])))
        compare(w, "M%d" % k, label + ": to a node that is no test program a frame of no kind", seen)
    w.stop("r")
    w.stop("p")


def main(argv):
    if len(argv) != 3:
        print(__doc__)
        return 2
    w = Walk(os.path.abspath(argv[1]), os.path.abspath(argv[2]))
    only = os.environ.get("C8_ONLY", "")
    try:
        if only in ("", "1"):
            part_one(w)
        if only in ("", "2"):
            part_two(w)
        if only in ("", "3"):
            part_three(w)
    finally:
        w.close()
    print("[c8] the steps of the Swift node's trial passed")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
