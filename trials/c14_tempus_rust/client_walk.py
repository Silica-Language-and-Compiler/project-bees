#!/usr/bin/env python3
"""Run the trial of the Rust example TEMPUS client (trials/c14_tempus_rust).

    client_walk.py LEAF_DIR PATH_OF_tempus-client

The node executables of the leaf are started as tools/bees_tempus_trial.py starts them (its Node class). The Rust client
is used through its command line only (example_tempus_clients/rust): `listen` processes that stay up, and one `dial`
process per request. Every line the Rust client prints is checked here (a failed check fails the trial) and written to
rust.sout in the leaf, which is compared with its golden. Nothing of the wall clock is printed.

Three parts:
  N  node N, a test node whose clock is the trial's 1500. It joins through the Rust client listening as its sentinel;
     the Rust client then dials it as that sentinel and as an edge, is dialed by it for a shuffle, and sees its refusals.
     The Rust client sends no test-only frame: the ticks that make N shuffle are sent here, with the Python example.
  P  node P, which reads the system clock. The Rust client listens as its sentinel and dials it, with the system clock.
  X  the Rust client against the Python example client, with no node: both ways, the same bytes, and every refusal
     that needs a peer that misbehaves on purpose (the Python example can; a node never does).
Keys, certificates and tokens are TEST ONLY, from fixed seeds. Ports come from tools/trial_ports.py.
"""
import os
import re
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "tools"))
sys.path.insert(0, os.path.join(HERE, "..", "..", "example_tempus_clients", "python"))  # the Python test support
import bees_tempus_client as c  # noqa: E402
import trial_ports  # noqa: E402
from bees_tempus_trial import CERTS, Node, cert, check, quiet  # noqa: E402

BASE = trial_ports.TABLE["c14_tempus_rust"][0]
N_ADDR, P_ADDR, SN_ADDR, E_ADDR, SP_ADDR, PY_ADDR, SX_ADDR, DEAD = ("127.0.0.1:%d" % (BASE + k) for k in range(8))
PRODUCER_PUB = c._raw_public(c.fixture_key(0)).hex()
FAR = 4000000000                    # a token's end that any present clock is before
BINDING = "the certificate's key is not the advert's pub"
PROOF = "the proof of possession does not verify"


def seed(first):
    return bytes(range(first, first + 32)).hex()


def id8(first):
    """the first 8 bytes of the peer id of the TEST ONLY key first.., as the clients print a peer"""
    return c.peer_id(c._raw_public(c.fixture_key(first)))[:8].hex()


class Rust:
    """The Rust client's command line, and the file its lines go to."""

    def __init__(self, exe, out_path):
        self.exe, self.out = exe, open(out_path, "w")
        self.listeners = []

    def say(self, text):
        self.out.write(text + "\n")
        self.out.flush()

    def checks(self, clock, kid="k1", timeout="5", length=3, more=()):
        return ["--producer-pub", PRODUCER_PUB, "--kid", kid] + clock + ["--skew", "10", "--timeout", timeout,
                                                                         "--shuffle-length", str(length)] + list(more)

    def dial(self, label, addr, who, clock, request, want, any_order=False, **kw):
        """One request. `want` is the whole line expected, or a function of the line. any_order: the entries of the
        reply are written in sorted order (a node that is not a test node draws its sample from the platform's random
        source, so their order is not the same on every run)."""
        r = subprocess.run([self.exe, "dial", addr] + who + self.checks(clock, **kw) + request, capture_output=True, text=True, timeout=60)
        line = r.stdout.strip()
        check(r.returncode == 0 and "\n" not in line, "%s: the Rust client ended with %d: %s %s" % (label, r.returncode, r.stdout, r.stderr))
        line = stable(line)
        if any_order:
            line = re.sub(r"entries=\[([^\]]*)\]", lambda m: "entries=[%s]" % ",".join(sorted(m.group(1).split(","))), line)
        self.say("%s -> %s" % (label, line))
        check(want(line) if callable(want) else line == want, "%s: wanted %s, got: %s" % (label, "another line" if callable(want) else want, line))
        return line

    def listen(self, label, addr, who, clock, entries=(), **kw):
        lis = Listening(self, label, [self.exe, "listen", addr] + who + self.checks(clock, **kw)
                        + [x for e in entries for x in ("--test-entry", e)])
        self.listeners.append(lis)
        return lis

    def close(self):
        for lis in self.listeners:
            lis.stop()
        self.out.close()


def stable(line):
    """a failed handshake's reason is the TLS library's text, which belongs to its version: it is left out"""
    return re.sub(r' reason=".*"$', "", line) if line.startswith("tls_failed") else line


class Listening:
    """A `tempus-client listen` process. next(label, want) waits for the line of the next connection."""

    def __init__(self, swift, label, argv):
        self.swift, self.lines, self.taken = swift, [], 0
        self.lock = threading.Condition()
        self.proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        threading.Thread(target=self._read, daemon=True).start()
        first = self._take(10.0)
        check(first is not None and first.startswith("listening "), "%s: the Rust listener did not start: %r %s" % (
            label, first, "" if self.proc.poll() is None else self.proc.stderr.read()))
        swift.say("%s -> %s" % (label, first))

    def _read(self):
        for line in self.proc.stdout:
            with self.lock:
                self.lines.append(line.rstrip("\n"))
                self.lock.notify_all()

    def _take(self, wait):
        until = time.monotonic() + wait
        with self.lock:
            while len(self.lines) <= self.taken:
                left = until - time.monotonic()
                if left <= 0:
                    return None
                self.lock.wait(left)
            self.taken += 1
            return self.lines[self.taken - 1]

    def pending(self):
        with self.lock:
            return len(self.lines) - self.taken

    def next(self, label, want, wait=15.0):
        line = self._take(wait)
        check(line is not None, "%s: the Rust listener reported no connection" % label)
        line = stable(line)
        self.swift.say("%s -> %s" % (label, line))
        check(want(line) if callable(want) else line == want, "%s: wanted %s, got: %s" % (label, "another line" if callable(want) else want, line))
        return line

    def stop(self):
        if self.proc.poll() is None:
            try:
                self.proc.stdin.close()
            except OSError:
                pass
            try:
                self.proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        with self.lock:
            left = self.lines[self.taken:]
        check(not left, "a Rust listener reported connections nobody waited for: %r" % left)


def with_nodes(leaf, sw):
    now = ["--now", "1500"]
    sentinel_pem = os.path.join(CERTS, "sentinel.pem")
    n8, s8, e8, x1, x2 = id8(32), id8(128), id8(64), id8(176), id8(192)
    # the Rust client's two identities: S, the sentinel node N joins through (its certificate is the one N's whitelist
    # holds), and E, an edge whose certificate the Rust client makes itself
    S = ["--seed", seed(128), "--addr", SN_ADDR, "--test-token", "tempus_sentinel:1000:3000", "--cert", sentinel_pem]
    E = ["--seed", seed(64), "--addr", E_ADDR, "--test-token", "tempus_edge:1000:3000"]

    def e_with(token):
        return ["--seed", seed(64), "--addr", E_ADDR] + token

    nodes = {}
    ticker = c.fixture_identity(112, "tempus_edge", 1000, 3000, addr=DEAD)   # the trial tool's own peer, for the ticks
    py = c.Verifier(c._raw_public(c.fixture_key(0)), "k1", 1500, 10)
    try:
        # ---------------- N: a test node, clock 1500
        sw.say("# N: node N, a test node whose clock is 1500")
        ls = sw.listen("N0 the Rust client listens as the sentinel", SN_ADDR, S, now, entries=[
            "tempus_edge=1:176:tempus_edge:1000:2000:" + DEAD, "tempus_sentinel=0:128:tempus_sentinel:1000:3000:" + SN_ADDR])
        n = nodes["n"] = Node(leaf, "dangerous_n")
        n.wait(r"^join: done$")
        quiet()
        # the node joined through the Rust client: one sample per store, each admitted and answered
        served = "served sample n=%d store=%s sent=reply peer=" + n8 + " typ=tempus_edge"
        ls.next("N0 the node's join, edge store", served % (3, "tempus_edge"))
        ls.next("N0 the node's join, bridge store", served % (2, "tempus_bridge"))
        ls.next("N0 the node's join, sentinel store", served % (2, "tempus_sentinel"))
        peer = " peer=" + n8 + " typ=tempus_edge"
        # the node keeps the sentinel it joined through (ruling NQ-12)
        sw.dial("N1 as the sentinel: sample tempus_sentinel 2", N_ADDR, S, now, ["sample", "tempus_sentinel", "2"],
                "reply sample_reply entries=[0:%s] store=tempus_sentinel%s" % (s8, peer), length=2)
        quiet()
        sw.dial("N2 as an edge: sample tempus_edge 3", N_ADDR, E, now, ["sample", "tempus_edge", "3"],
                "reply sample_reply entries=[1:%s] store=tempus_edge%s" % (x1, peer))
        quiet()
        sw.dial("N3 shuffle tempus_edge, its own entry at age 0", N_ADDR, E, now, ["shuffle", "tempus_edge"],
                lambda ln: ln.startswith("reply shuffle_reply entries=[") and ln.endswith(" store=tempus_edge" + peer))
        quiet()
        sw.dial("N4 sample: the client is in the node's view at age 0", N_ADDR, E, now, ["sample", "tempus_edge", "3"],
                lambda ln: ln.startswith("reply sample_reply ") and "0:" + e8 in ln)
        quiet()
        # the node dials the Rust client: the trial tool sends ticks until the client is the oldest entry
        le = sw.listen("N5 the Rust client listens as the edge", E_ADDR, E, now, entries=["tempus_edge=4:192:tempus_edge:1000:2000:" + DEAD])
        ticks = 0
        while le.pending() == 0 and ticks < 4:
            out = c.dial(N_ADDR, ticker, py, c.tick("tempus_edge"))
            check(out.what == "reply" and out.kind == "done", "a tick to node N (the trial tool's own, test-only frame): " + out.line())
            ticks += 1
            quiet(1.0)
        sw.say("N5 the trial tool sent node N %d test-only ticks" % ticks)
        le.next("N5 the node shuffles with the Rust client", "served shuffle entries=[0:%s] store=tempus_edge sent=reply%s" % (n8, peer))
        quiet()
        sw.dial("N6 sample: the node took the entry the client answered with", N_ADDR, E, now, ["sample", "tempus_edge", "3"],
                lambda ln: ln.startswith("reply sample_reply ") and "4:" + x2 in ln)
        quiet()
        # what a client sees of the node's refusals: a close with no reply, and the one frame key_rotated
        closed = "closed at=challenge" + peer
        sw.dial("N7 an expired token", N_ADDR, e_with(["--test-token", "tempus_edge:1000:1400"]), now, ["sample", "tempus_edge", "3"], closed)
        quiet()
        sw.dial("N8 a token that is not valid yet", N_ADDR, e_with(["--test-token", "tempus_edge:1800:2000"]), now, ["sample", "tempus_edge", "3"], closed)
        quiet()
        other = c.fixture_key(96)
        e_pub = c._raw_public(c.fixture_key(64))
        sw.dial("N9 a token another key signed", N_ADDR, e_with(["--token", c.make_token(other, "k1", e_pub, "tempus_edge", 1000, 2000).hex()]),
                now, ["sample", "tempus_edge", "3"], closed)
        quiet()
        sw.dial("N10 a token under the old kid", N_ADDR, e_with(["--token", c.make_token(other, "k0", e_pub, "tempus_edge", 1000, 2000).hex()]),
                now, ["sample", "tempus_edge", "3"], "key_rotated at=challenge kid=6b31" + peer)
        quiet()
        gone = "closed at=reply" + peer
        sw.dial("N11 a sample of more than the shuffle length", N_ADDR, E, now, ["sample", "tempus_edge", "9"], gone, length=9)
        quiet()
        sw.dial("N12 a shuffle of the sentinel store that holds an edge's entry", N_ADDR, E, now, ["shuffle", "tempus_sentinel"], gone)
        quiet()
        sw.dial("N13 a call to a node that is not a bridge", N_ADDR, E, now, ["call", "m", "f", "2", "40"], gone)
        quiet()
        sw.dial("N14 a cast to a node that is not a bridge", N_ADDR, E, now, ["cast", "m", "f"], gone)
        quiet()
        # what the client itself refuses of the node
        sw.dial("N15 the client's clock is past the node's token", N_ADDR, E, ["--now", "2600"], ["sample", "tempus_edge", "3"],
                'refused at=advert peer=%s reason="the token has expired"' % n8)
        quiet()
        # (its own token is the good one, under k1, given as bytes: --test-token would sign under the kid of the command line)
        k1_token = c.make_token(c.fixture_key(0), "k1", e_pub, "tempus_edge", 1000, 3000).hex()
        sw.dial("N16 the client holds another producer kid and says so", N_ADDR, e_with(["--token", k1_token]), now, ["sample", "tempus_edge", "3"],
                'refused at=advert peer=%s reason="key_rotated"' % n8, kid="k9")
        n.wait(r"key_rotated peer=\S+ the peer says this node's token is under another kid")
        quiet()
        sw.dial("N17 with a whitelist: an edge needs no entry in it", N_ADDR, E, now, ["sample", "tempus_edge", "1"],
                lambda ln: ln.startswith("reply sample_reply "), more=["--whitelist-cert", sentinel_pem])
        quiet()
        sw.dial("N18 an address nobody listens on", DEAD, E, now, ["sample", "tempus_edge", "1"], "unreachable at=tls")
        ls.stop()
        le.stop()
        nodes.pop("n").stop()

        # ---------------- P: not a test node, the system clock
        sw.say("# P: node P, which reads the system clock; the Rust client reads it too")
        sw.say("# (P draws from the platform's random source: the entries of each reply are written here in sorted order)")
        real = ["--system-clock"]
        SP = ["--seed", seed(128), "--addr", SP_ADDR, "--test-token", "tempus_sentinel:1000:%d" % FAR, "--cert", sentinel_pem]
        far = e_with(["--test-token", "tempus_edge:1000:%d" % FAR])
        lp = sw.listen("P0 the Rust client listens as the sentinel", SP_ADDR, SP, real,
                       entries=["tempus_edge=2:176:tempus_edge:1000:%d:%s" % (FAR, DEAD)])
        pn = nodes["p"] = Node(leaf, "dangerous_p")
        pn.wait(r"^join: done$")
        quiet()
        lp.next("P0 the node's join, edge store", served % (3, "tempus_edge"))
        lp.next("P0 the node's join, bridge store", served % (2, "tempus_bridge"))
        lp.next("P0 the node's join, sentinel store", served % (2, "tempus_sentinel"))
        sw.dial("P1 sample tempus_edge 3", P_ADDR, far, real, ["sample", "tempus_edge", "3"],
                "reply sample_reply entries=[2:%s] store=tempus_edge%s" % (x1, peer), any_order=True)
        quiet()
        sw.dial("P2 shuffle tempus_edge, its own entry at age 0", P_ADDR, far, real, ["shuffle", "tempus_edge"],
                lambda ln: ln.startswith("reply shuffle_reply entries=[") and ln.endswith(" store=tempus_edge" + peer), any_order=True)
        quiet()
        sw.dial("P3 sample: the client is in the node's view at age 0", P_ADDR, far, real, ["sample", "tempus_edge", "3"],
                lambda ln: ln.startswith("reply sample_reply ") and "0:" + e8 in ln, any_order=True)
        quiet()
        sw.dial("P4 the trial's token of 1000 to 3000 has expired by the system clock", P_ADDR, E, real, ["sample", "tempus_edge", "3"], closed)
        quiet()
        sw.dial("P5 a token that begins at 3900000000 is not valid yet", P_ADDR, e_with(["--test-token", "tempus_edge:3900000000:%d" % FAR]), real,
                ["sample", "tempus_edge", "3"], closed)
        quiet()
        lp.stop()
    finally:
        for node in list(nodes.values()):
            node.stop()


def with_python(sw):
    """The Rust client and the Python example client, with no node."""
    A = c.Atom
    now = ["--now", "1500"]
    e8, py8, t8 = id8(64), id8(160), id8(128)
    other_pem = os.path.join(CERTS, "other.pem")
    # the Rust client here presents the certificate of tools/bees_tempus_certs.py for its key, because the Python
    # example's listener must be given the certificates of the peers that dial it
    E = ["--seed", seed(64), "--addr", E_ADDR, "--test-token", "tempus_edge:1000:2000", "--cert", other_pem]
    E_py = c.Identity(bytes(range(64, 96)), c.make_token(c.fixture_key(0), "k1", c._raw_public(c.fixture_key(64)), "tempus_edge", 1000, 2000),
                      E_ADDR, cert_pem=cert("other"))
    PY = c.fixture_identity(160, "tempus_edge", 1000, 2000, addr=PY_ADDR)
    THIRD = c.fixture_identity(128, "tempus_edge", 1000, 2000, addr=DEAD)
    forged = c.fixture_identity(128, "tempus_edge", 1000, 2000, addr=DEAD, producer=c.fixture_key(96))
    v = c.Verifier(c._raw_public(c.fixture_key(0)), "k1", 1500, 10)
    smp = ["sample", "tempus_edge", "2"]
    peer = " peer=%s typ=tempus_edge" % py8
    result = c.etf_encode({A("t"): A("result"), A("ver"): 1, A("req_id"): b"1", A("value"): 42})

    # ---- X1: the Rust client dials the Python example. Each step: (label, the Rust request, what the Python listener
    # does: its misbehaviour, another identity, or the handler's answer; the bytes the request must be; the Rust line)
    steps = [
        ("a sample", smp, {"answer": c.sample_reply("tempus_edge", [THIRD.entry(3)]), "body": c.sample("tempus_edge", 2)},
         "reply sample_reply entries=[3:%s] store=tempus_edge%s" % (t8, peer)),
        ("a shuffle", ["shuffle", "tempus_edge"], {"answer": c.shuffle_reply("tempus_edge", [THIRD.entry(1)]), "body": c.shuffle("tempus_edge", [E_py.entry(0)])},
         "reply shuffle_reply entries=[1:%s] store=tempus_edge%s" % (t8, peer)),
        ("a call", ["call", "m", "f", "2", "40"], {"answer": result, "body": c.call_frame("1", "m", "f", [2, 40])},
         "reply result req_id=31 value=42 ver=1" + peer),
        ("a cast, which has no reply", ["cast", "m", "f"], {"answer": None, "body": c.call_frame("1", "m", "f", [], kind="cast")}, "closed at=reply" + peer),
        ("the peer presents somebody else's advert", smp, {"mis": c.wrong_advert(THIRD.advert())},
         'refused at=advert peer=%s reason="%s"' % (t8, BINDING)),
        ("the peer's proof is over another nonce", smp, {"mis": c.wrong_proof_other_nonce()}, 'refused at=response%s reason="%s"' % (peer, PROOF)),
        ("the peer's proof is by another key", smp, {"mis": c.wrong_proof_other_key(c.fixture_key(224))}, 'refused at=response%s reason="%s"' % (peer, PROOF)),
        ("the peer's proof is 63 bytes", smp, {"mis": c.wrong_proof_bytes(bytes(63))}, 'refused at=response%s reason="sig is not 64 bytes"' % peer),
        ("the peer closes after its advert", smp, {"mis": c.close_after_advert()}, "closed at=challenge" + peer),
        ("the peer sends a second advert where its challenge was due", smp, {"mis": c.wrong_frame_at("challenge", PY.advert())},
         'refused at=challenge%s reason="advert where pop_challenge or key_rotated was due"' % peer),
        ("a reply with an entry another key signed, beside a good one", smp, {"answer": c.sample_reply("tempus_edge", [THIRD.entry(1), forged.entry(2)])},
         'refused at=reply%s reason="an entry does not verify: the signature does not verify"' % peer),
        ("a reply of more entries than the shuffle length", smp, {"answer": c.sample_reply("tempus_edge", [THIRD.entry(i) for i in range(4)])},
         'refused at=reply%s reason="more entries than the shuffle length"' % peer),
        ("a reply above the frame ceiling", smp, {"answer": c.send_raw(b"\x00\x02\x00\x01")}, 'refused at=reply%s reason="a frame above the ceiling"' % peer),
        ("a reply that is no term", smp, {"answer": c.send_raw(c.raw_frame(b"hello"))}, 'refused at=reply%s reason="bad_version"' % peer),
        ("the peer closes instead of replying", smp, {"answer": c.CLOSE}, "closed at=reply" + peer),
        ("the peer's token has expired", smp, {"who": c.fixture_identity(160, "tempus_edge", 1000, 1400, addr=PY_ADDR)},
         'refused at=advert peer=%s reason="the token has expired"' % py8),
        # a reply must be the reply of its request (writing-a-tempus-client.md section 8)
        ("a sample_reply for another store than the one asked", smp, {"answer": c.sample_reply("tempus_bridge", [])},
         'refused at=reply%s reason="the reply is for another store than the request"' % peer),
        ("a sample of 1 answered with two entries", ["sample", "tempus_edge", "1"], {"answer": c.sample_reply("tempus_edge", [THIRD.entry(1), PY.entry(2)])},
         'refused at=reply%s reason="more entries than the sample asked for"' % peer),
        ("a sample answered with a shuffle_reply", smp, {"answer": c.shuffle_reply("tempus_edge", [])},
         'refused at=reply%s reason="shuffle_reply where sample_reply was due"' % peer),
        ("a sample answered with the done frame of the test unit", smp, {"answer": c.etf_encode({A("t"): A("done")})},
         'refused at=reply%s reason="done where sample_reply was due"' % peer),
        ("a shuffle answered with a sample_reply", ["shuffle", "tempus_edge"], {"answer": c.sample_reply("tempus_edge", [])},
         'refused at=reply%s reason="sample_reply where shuffle_reply was due"' % peer),
        ("a shuffle answered for another store", ["shuffle", "tempus_edge"], {"answer": c.shuffle_reply("tempus_sentinel", [])},
         'refused at=reply%s reason="the reply is for another store than the request"' % peer),
        ("a call answered with a result for another request id", ["call", "m", "f", "2", "40"],
         {"answer": c.etf_encode({A("t"): A("result"), A("ver"): 1, A("req_id"): b"2", A("value"): 42})},
         'refused at=reply%s reason="the result is not for this call\'s req_id"' % peer),
        ("a call answered with a sample_reply", ["call", "m", "f", "2", "40"], {"answer": c.sample_reply("tempus_edge", [])},
         'refused at=reply%s reason="sample_reply where result was due"' % peer),
        ("a reply with an entry whose token is of another type than the store", smp,
         {"answer": c.sample_reply("tempus_edge", [c.fixture_identity(128, "tempus_bridge", 1000, 2000, addr=DEAD).entry(1)])},
         'refused at=reply%s reason="an entry does not verify: the entry\'s typ is not the store\'s"' % peer),
        ("a reply with an entry whose token has expired", smp,
         {"answer": c.sample_reply("tempus_edge", [c.fixture_identity(128, "tempus_edge", 1000, 1400, addr=DEAD).entry(1)])},
         'refused at=reply%s reason="an entry does not verify: the token has expired"' % peer),
        ("the peer's token is under the old kid: the client says key_rotated", smp,
         {"who": c.fixture_identity(160, "tempus_edge", 1000, 2000, addr=PY_ADDR, kid="k0", producer=c.fixture_key(96)), "python": ("key_rotated", b"k1")},
         'refused at=advert peer=%s reason="key_rotated"' % py8),
    ]
    sw.say("# X1: the Rust client dials the Python example client")
    seen = []

    def handler(rq):
        seen.append(rq.body)
        return steps[rq.index][2].get("answer", c.CLOSE)

    with c.Listener(PY, v, handler, [cert("other")], port=BASE + 5, timeout=5.0, misbehaviour=lambda i: steps[i][2].get("mis")) as lis:
        for i, (label, rq, how, want) in enumerate(steps):
            lis.identity = how.get("who", PY)
            before = len(seen)
            sw.dial("X1.%d %s" % (i + 1, label), PY_ADDR, E, now, rq, want)
            (out,) = lis.outcomes(i + 1)[i:]
            if "body" in how:
                check(len(seen) == before + 1 and seen[-1] == how["body"],
                      "X1.%d: the Rust client's request is not the bytes the Python example writes for it: %s" % (i + 1, seen[before:]))
                check(out.what == "served" and out.advert == E_py.descriptor(), "X1.%d: the Python example did not admit the Rust client: %s" % (i + 1, out.line()))
            if "python" in how:
                check((out.what, out.kid) == how["python"], "X1.%d: the Python example saw: %s" % (i + 1, out.line()))
    # a listener that speaks another ALPN protocol, and one with a P-256 certificate (the client's handshake offers Ed25519 only)
    for k, (label, how, want) in enumerate((("another ALPN protocol", c.other_alpn("h2"), 'refused at=tls reason="the ALPN protocol is not tempus/1"'),
                                            ("a P-256 certificate", c.p256_cert(), "tls_failed at=tls"),
                                            ("TLS 1.2 only", c.tls12_only(), "tls_failed at=tls")), start=len(steps) + 1):
        with c.Listener(PY, v, lambda rq: c.CLOSE, [cert("other")], port=BASE + 5, timeout=5.0, **how) as lis:
            sw.dial("X1.%d the peer offers %s" % (k, label), PY_ADDR, E, now, smp, want)
            lis.outcomes(1)

    # ---- X2: the Python example dials the Rust client
    sw.say("# X2: the Python example client dials the Rust client")
    SX = ["--seed", seed(64), "--addr", SX_ADDR, "--test-token", "tempus_edge:1000:2000"]
    lx = sw.listen("X2.0 the Rust client listens", SX_ADDR, SX, now, entries=["tempus_edge=3:128:tempus_edge:1000:2000:" + DEAD,
                                                                              "tempus_edge=5:192:tempus_edge:1000:2000:" + DEAD])
    dpeer = " peer=%s typ=tempus_edge" % py8
    x2 = id8(192)
    old = c.fixture_identity(160, "tempus_edge", 1000, 2000, addr=PY_ADDR, kid="k0", producer=c.fixture_key(96))
    tls = "tls_failed at=tls"
    dials = [
        ("a sample", PY, c.sample("tempus_edge", 2), {}, "served sample n=2 store=tempus_edge sent=reply" + dpeer,
         lambda o: o.what == "reply" and o.body == c.sample_reply("tempus_edge", [THIRD.entry(3), c.fixture_identity(192, "tempus_edge", 1000, 2000, addr=DEAD).entry(5)])),
        ("a sample of 1", PY, c.sample("tempus_edge", 1), {}, "served sample n=1 store=tempus_edge sent=reply" + dpeer,
         lambda o: o.what == "reply" and o.body == c.sample_reply("tempus_edge", [THIRD.entry(3)])),
        ("a shuffle", PY, c.shuffle("tempus_edge", [PY.entry(0)]), {}, "served shuffle entries=[0:%s] store=tempus_edge sent=reply%s" % (py8, dpeer),
         lambda o: o.what == "reply" and o.kind == "shuffle_reply" and [d[A("id")][:8].hex() for _a, d in o.fields["entries"]] == [t8, x2]),
        ("a sample of a store the client holds nothing for", PY, c.sample("tempus_bridge", 2), {}, "served sample n=2 store=tempus_bridge sent=reply" + dpeer,
         lambda o: o.what == "reply" and o.body == c.sample_reply("tempus_bridge", [])),
        ("a test-only tick: to a client a frame of no kind, closed with no reply", PY, c.tick("tempus_edge"), {},
         "served tick store=tempus_edge sent=close" + dpeer, lambda o: (o.what, o.stage) == ("closed", "reply")),
        ("a call: a client is no bridge", PY, c.call_frame("1", "m", "f", [1]), {}, "served call a=1 args=[1] f=f m=m opts={} req_id=31 ver=1 sent=close" + dpeer,
         lambda o: (o.what, o.stage) == ("closed", "reply")),
        ("somebody else's advert", PY, c.sample("tempus_edge", 2), {"misbehaviour": c.wrong_advert(THIRD.advert())},
         'refused at=advert peer=%s reason="%s"' % (t8, BINDING), lambda o: o.what == "closed"),
        ("a proof by another key", PY, c.sample("tempus_edge", 2), {"misbehaviour": c.wrong_proof_other_key(c.fixture_key(224))},
         'refused at=response%s reason="%s"' % (dpeer, PROOF), lambda o: o.what == "closed"),
        ("a proof over another nonce", PY, c.sample("tempus_edge", 2), {"misbehaviour": c.wrong_proof_other_nonce()},
         'refused at=response%s reason="%s"' % (dpeer, PROOF), lambda o: o.what == "closed"),
        ("no proof: the request comes where it was due", PY, c.sample("tempus_edge", 2), {"misbehaviour": c.no_proof()},
         'refused at=response%s reason="sample where pop_response was due"' % dpeer, lambda o: o.what == "closed"),
        ("the dialer closes instead of its proof", PY, c.sample("tempus_edge", 2), {"misbehaviour": c.close_at("response")},
         "closed at=response" + dpeer, lambda o: o.what == "closed"),
        ("a request above the frame ceiling", PY, c.sample("tempus_edge", 2), {"misbehaviour": c.oversize_frame_at("request")},
         'refused at=request%s reason="a frame above the ceiling"' % dpeer, lambda o: o.what == "closed"),
        ("a request with an unknown key", PY, c.etf_encode({A("t"): A("sample"), A("store"): A("tempus_edge"), A("n"): 1, A("x"): 1}), {},
         'refused at=request%s reason="unknown_field"' % dpeer, lambda o: o.what == "closed"),
        ("a shuffle with an entry another key signed", PY, c.shuffle("tempus_edge", [PY.entry(0), forged.entry(2)]), {},
         'refused at=request%s reason="an entry does not verify: the signature does not verify"' % dpeer, lambda o: o.what == "closed"),
        ("a shuffle of the bridge store with an edge's entry", PY, c.shuffle("tempus_bridge", [PY.entry(0)]), {},
         'refused at=request%s reason="an entry does not verify: the entry\'s typ is not the store\'s"' % dpeer, lambda o: o.what == "closed"),
        ("an expired token", c.fixture_identity(160, "tempus_edge", 1000, 1400, addr=PY_ADDR), c.sample("tempus_edge", 2), {},
         'refused at=advert peer=%s reason="the token has expired"' % py8, lambda o: o.what == "closed"),
        ("a token under the old kid: the client says key_rotated", old, c.sample("tempus_edge", 2), {},
         'refused at=advert peer=%s reason="key_rotated"' % py8, lambda o: (o.what, o.kid) == ("key_rotated", b"k1")),
        ("TLS 1.2 only", PY, c.sample("tempus_edge", 2), c.tls12_only(), tls, lambda o: o.what == "tls_failed"),
        ("another ALPN protocol", PY, c.sample("tempus_edge", 2), c.other_alpn("h2"), 'refused at=tls reason="the ALPN protocol is not tempus/1"',
         lambda o: o.what in ("closed", "tls_failed")),
        ("no certificate", PY, c.sample("tempus_edge", 2), c.no_certificate(), tls, lambda o: o.what in ("closed", "tls_failed")),
        ("a P-256 certificate", PY, c.sample("tempus_edge", 2), c.p256_cert(), tls, lambda o: o.what in ("closed", "tls_failed")),
    ]
    for i, (label, who, body, kw, want, python_sees) in enumerate(dials, start=1):
        out = c.dial(SX_ADDR, who, v, body, shuffle_length=3, **kw)
        lx.next("X2.%d %s" % (i, label), want)
        check(python_sees(out), "X2.%d %s: the Python example saw: %s" % (i, label, out.line()))
        if out.what == "reply" and out.kind in ("sample_reply", "shuffle_reply"):
            for _age, d in out.fields["entries"]:
                v.check_descriptor(d)          # the entries the Rust client made verify under the Python example's checks
    lx.stop()


def main(argv):
    if len(argv) != 3:
        print(__doc__)
        return 2
    leaf, exe = os.path.abspath(argv[1]), os.path.abspath(argv[2])
    sw = Rust(exe, os.path.join(leaf, "rust.sout"))
    try:
        if os.environ.get("C14_ONLY", "") != "python":
            with_nodes(leaf, sw)
        if os.environ.get("C14_ONLY", "") != "nodes":
            with_python(sw)
    finally:
        sw.close()
    print("[c14] the Rust client's steps passed")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
