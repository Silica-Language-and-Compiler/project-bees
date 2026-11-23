#!/usr/bin/env python3
"""C7: nodes of the Python TEMPUS extension (example_tempus_clients/python/lib/bees_tempus_node.py) and Silica nodes in one
network on 127.0.0.1.

    walk.py LEAF_DIR

The nodes (ports are this trial's block in tools/trial_ports.py):
  Q  +0  Silica, a sentinel, the first one. A test program (its clock and ticks come from this tool's test frames).
  A  +1  Silica, an edge. It joins through S: a Silica node that joins through a node of the extension.
  P  +2  Python, an edge. It joins through S.
  S  +3  Python, a sentinel. It joins through Q: a node of the extension that joins through a Silica node.
  R  +4  Python, a sentinel, NOT a test node: the program r_app.py beside this file, run as a process of its own. It
         reads the machine's clock, runs its own timers and takes its random bytes from the operating system.
  W  +5  Silica, an edge shaped like a production program (no test unit in its build). It joins through R.
  H  +6  Python, a sentinel with clock_back hold and clock_fail continue.
  T  +7  Python, an edge with clock_back stop (limit 60 s) and clock_fail pause.
  V  +8  Python, a sentinel that T joins through, started late.
  +9     the address this tool's own peer advertises; nothing listens there.
  +10    the listener of the extension's own client (bees_tempus_peer.Listener), which Q dials.
  +11    a peer of the test support that answers wrongly on purpose, which the extension's own client dials.

P, S, H, T and V run in this process and are test nodes: each is given, through the extension's ordinary construction
interface, a clock this tool sets, timers this tool fires and draws from a literal list (bees_tempus_testing.py).
No frame sets their time or ticks them: there is no such frame in the extension. The Silica test nodes Q and A are
ticked with the test-only tick frame, as in every TEMPUS trial.

Parts, each written to the transcript (walk.sout) as it goes, each step checked here (a failed check fails the trial):
  1  the mixed network: joins both ways, shuffles started by each side and answered by the other, and what the stores
     of the Python nodes then hold. What the Silica nodes hold is in their own outputs.
  2  refusals: every hostile case is sent to the Silica sentinel Q and to the Python sentinel S, by the same peer with
     the same bytes, and the audit lines the two nodes write for it must be the same, word for word.
  3  the extension as a peer that is not a node (bees_tempus_peer.dial and Listener, what a client application
     imports): against the Silica sentinel Q, and against a peer that answers wrongly on purpose.
  4  two nodes that are not test nodes, R and W: the join, a shuffle R starts on its own timer, and the test-only
     tick and clock frames refused by both in the same words.
  5  the clock's choices on Python nodes, with the test clock.
The outputs: dangerous_q.sout, dangerous_a.sout, dangerous_w.sout (the Silica nodes), py_p.sout, py_s.sout, py_r.sout,
py_h.sout, py_t.sout, py_v.sout (the Python nodes) and walk.sout. Keys, certificates and tokens are TEST ONLY.
"""
import json
import os
import re
import shutil
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import bees_tempus_certs as certs  # noqa: E402
import bees_tempus_trial as T  # noqa: E402
import trial_ports  # noqa: E402

c = T.c                                    # the test support, under its old name
sys.path.insert(0, os.path.join(ROOT, "example_tempus_clients", "python", "lib"))
import bees_tempus_admission  # noqa: E402
import bees_tempus_codec  # noqa: E402
import bees_tempus_config  # noqa: E402
import bees_tempus_node  # noqa: E402
import bees_tempus_peer  # noqa: E402

A_ = c.Atom
BASE = trial_ports.TABLE["c7_tempus_node_python"][0]
Q, A, P, S, R, W, H, TT, V, DEAD, XL, HOSTILE = ("127.0.0.1:%d" % (BASE + k) for k in range(12))
CERTS = os.path.join(ROOT, "trials", "t5_tempus_tls", "certs")
PROD, OLD = c.fixture_key(0), c.fixture_key(96)
PROD_PUB = c._raw_public(PROD)
# the tempus whitelist of every node of this trial, in the order the Silica nodes number it (roles/node.role)
WHITELIST = ("sentinel", "bridge", "x4")
SAID = []


def say(text):
    SAID.append(text)


def token(name, typ, exp=2000, **kw):
    return c.make_token(kw.get("signer", PROD), kw.get("kid", "k1"), certs.public_bytes(name), typ, kw.get("nbf", 1000), exp)


def whitelist_dir(leaf):
    """the whitelist as a directory of certificates, named so that their order is the Silica nodes' order"""
    path = os.path.join(leaf, "whitelist")
    shutil.rmtree(path, ignore_errors=True)
    os.makedirs(path)
    for k, name in enumerate(WHITELIST):
        shutil.copy(os.path.join(CERTS, name + ".pem"), os.path.join(path, "%d-%s.pem" % (k, name)))
    return path


def values(leaf, role, name, addr, sentinels, **kw):
    """a node's configuration: the values of the Silica nodes of this trial (roles/node.role)"""
    v = {"role": role, "listen_address": "127.0.0.1", "port": int(addr.rpartition(":")[2]),
         "edge": {"capacity": 4, "shuffle_length": 3, "tick_ms": 1000},
         "bridge": {"capacity": 4, "shuffle_length": 2, "tick_ms": 1000},
         "sentinel": {"capacity": 4, "shuffle_length": 2, "tick_ms": 1000},
         "producer_key": ["k1", PROD_PUB.hex()],
         "identity_keyfile": os.path.join(CERTS, name + "-key.pem"), "identity_certfile": os.path.join(CERTS, name + ".pem"),
         "whitelist_cert_dir": os.path.join(leaf, "whitelist"),
         "shuffle_timeout_ms": 2000, "inflight_max": 2, "clock_skew_ms": 10000,
         "clock_back": "follow", "clock_fail": "pause", "clock_read_ms": 1000,
         "join_retry_initial_ms": 200, "join_retry_max_ms": 800}
    if sentinels:
        v["sentinels"] = [[s.rpartition(":")[0], int(s.rpartition(":")[2]), "%d-%s.pem" % (WHITELIST.index(n), n)] for s, n in sentinels]
    v.update(kw)
    return v


class PyNode:
    """A node of the extension in this process, stepped by hand. Its lines (the node's own, the audit lines, and one
    line for each thing its application is told) are kept in order; wait(pattern) is tools/bees_tempus_trial.py's."""

    def __init__(self, leaf, tag, role, name, typ, addr, sentinels=(), exp=2000, clock=1500, **kw):
        self.tag, self.leaf = tag, leaf
        self.lines, self.seen, self.lock = [], 0, threading.Condition()
        self.clock, self.timers = c.TestClock(clock), c.TestTimers()
        conf = bees_tempus_config.node_config(values(leaf, role, name, addr, sentinels, **kw))
        self.node = bees_tempus_node.Node(conf, token=token(name, typ, exp), address=addr, on_event=self.told,
                                          log=self.line, clock=self.clock, timers=self.timers, random=c.TestRandom())
        self.id8 = bees_tempus_node.peer8(self.node.identity.peer_id)
        self.node.start()

    def line(self, text):
        with self.lock:
            self.lines.append(text)
            self.lock.notify_all()

    def told(self, e):
        if e.name == "view":
            self.line(bees_tempus_node.view_line(e.store, e.entries))
        elif e.name == "token_invalid":
            self.line("application: told that the node's own token is not valid any more: " + e.why)
        elif e.name == "key_rotated":
            self.line("application: told that a peer answered key_rotated, its current kid is " + e.kid.decode())
        else:
            self.line("application: told (%s) that %s" % (e.name, e.text))

    def text(self):
        with self.lock:
            return "".join(ln + "\n" for ln in self.lines)

    def wait(self, pattern, timeout=20.0):
        rx = re.compile(pattern, re.M)
        until = time.monotonic() + timeout
        with self.lock:
            while True:
                text = "".join(ln + "\n" for ln in self.lines)
                m = rx.search(text, self.seen)
                if m:
                    self.seen = text.find("\n", m.end()) + 1
                    return m
                left = until - time.monotonic()
                if left <= 0:
                    raise SystemExit("FAIL: the Python node %s did not write /%s/ in time; its lines so far:\n%s" % (self.tag, pattern, text))
                self.lock.wait(min(left, 0.2))

    def fire(self, name):
        T.check(self.timers.fire(name), "the Python node %s has no timer `%s` pending (it has: %s)" % (self.tag, name, self.timers.names()))

    def reading(self, value):
        """the next reading of this node's clock: the test clock is set, and the node's own clock timer is fired"""
        self.clock.value = value
        self.fire("clock")
        self.node.peers("tempus_edge")       # an answer from the node's thread: the reading has been taken

    def view(self, store):
        return " ".join("%s@%d" % (bees_tempus_node.peer8(i), a) for (i, _d, a) in self.node.peers(store)) or "(empty)"

    def views(self):
        return "; ".join("%s: %s" % (s[7:], self.view(s)) for s in c.TYPES)

    def stop(self):
        self.node.stop()
        with open(os.path.join(self.leaf, "py_%s.sout" % self.tag), "w") as f:
            f.write(self.text())


def line(out):
    """What this tool's peer saw of a connection, as one line. The text of a failed handshake is the TLS library's own;
    and the step at which a peer finds its connection closed depends on which of two frames in flight came first, so
    of a close only the fact is kept (and that it was made on purpose, where it was)."""
    if out.what == "tls_failed":
        return "tls_failed"
    if out.what == "closed":
        return "closed, on purpose" if out.reason == c.ON_PURPOSE else "closed"
    return re.sub(r" peer=[0-9a-f]+", "", out.line())     # the peer is the node asked: Q or S


AUDIT = re.compile(r"^\[tempus audit\] (?!tls_established)")
CID = re.compile(r" [ad]\d+$")
CLOSED = re.compile(r"^(\[tempus audit\] closed_by_peer) peer=\S+ stage [a-z_]+")


def audit_since(text, mark):
    """the audit lines a node wrote after `mark` characters of its output, without the lines that only say a TLS
    connection was made, and with the connection's number written N (the two nodes count their own connections)"""
    out = []
    for ln in text[mark:].split("\n"):
        if AUDIT.match(ln):
            out.append(CLOSED.sub(r"\1 peer=(any) stage (any)", CID.sub(" N", ln)))
    return out


class Walk:
    def __init__(self, leaf):
        self.leaf = leaf
        self.silica, self.py = {}, {}
        self.peer = T.Peer()                                               # the producer key, kid k1, the clock 1500, skew 10
        self.v = self.peer.verifier
        self.d = c.fixture_identity(112, "tempus_edge", 1000, 3000, addr=DEAD)   # this tool's own peer
        self.far = c.fixture_identity(112, "tempus_edge", 1000, 4000000000, addr=DEAD)

    # ---- processes
    def start(self, name, ready):
        n = self.silica[name] = T.Node(os.path.join(self.leaf, "nodes", name), "dangerous_" + name)
        n.wait(ready)
        T.quiet()
        return n

    def stop(self, name):
        T.quiet()
        self.silica.pop(name).stop()
        shutil.copy(os.path.join(self.leaf, "nodes", name, "dangerous_%s.sout" % name), os.path.join(self.leaf, "dangerous_%s.sout" % name))

    def python(self, tag, *a, **kw):
        n = self.py[tag] = PyNode(self.leaf, tag, *a, **kw)
        return n

    def tick(self, addr, store, who=None):
        """the test-only tick frame, to a Silica test node; its answer comes when the tick has ended"""
        out = c.dial(addr, who or self.d, self.v, c.tick(store), timeout=8.0)
        T.check(out.what == "reply" and out.kind == "done", "a tick to %s: %s" % (addr, out.line()))
        T.quiet()

    def close(self):
        for n in list(self.py.values()):
            n.stop()
        for name in list(self.silica):
            self.silica.pop(name).stop()

    # ---- part 1
    def part1(self):
        say("part 1: a mixed network of Silica nodes (Q a sentinel, A an edge) and Python nodes (S a sentinel, P an edge)")
        q = self.start("q", r"^join: no sentinel is configured$")
        s = self.python("s", "sentinel", "bridge", "tempus_sentinel", S, [(Q, "sentinel")])
        s.wait(r"^join: done$")
        q.wait(r"^view tempus_sentinel: %s@0$" % s.id8)
        T.quiet()
        say("S, a Python sentinel, joined through the Silica sentinel Q; S holds: %s" % s.views())
        T.check(s.view("tempus_sentinel") == "9e1113ab@0", "S did not keep the sentinel it joined through")
        a = self.start("a", r"^join: done$")
        s.wait(r"^view tempus_edge: b19edad2@0$")
        say("A, a Silica edge, joined through the Python sentinel S; S holds: %s" % s.views())
        p = self.python("p", "edge", "other", "tempus_edge", P, [(S, "bridge")])
        p.wait(r"^join: done$")
        T.quiet()
        say("P, a Python edge, joined through S; P holds: %s" % p.views())
        say("S holds: %s" % s.views())
        T.check(p.view("tempus_edge") == "b19edad2@0", "P was not told of A by its sentinel")
        # shuffles of the edge store, started by each side
        p.fire("tick tempus_edge")
        p.wait(r"^tick tempus_edge: shuffle merged$")
        a.wait(r"^view tempus_edge: %s@0$" % p.id8)
        T.quiet()
        say("P ticked its edge store and shuffled with the Silica edge A, which now holds P (A's output); P holds: %s" % p.views())
        self.tick(A, "tempus_edge")
        a.wait(r"^tick tempus_edge: shuffle merged$")
        say("A ticked its edge store and shuffled with the Python edge P; P holds: %s" % p.views())
        T.check(p.view("tempus_edge") == "b19edad2@0", "P does not hold A after A's shuffle")
        # shuffles of the sentinel store between the two sentinels, started by each side
        s.fire("tick tempus_sentinel")
        s.wait(r"^tick tempus_sentinel: shuffle merged$")
        T.quiet()
        say("S ticked its sentinel store and shuffled with the Silica sentinel Q; S holds: %s" % s.views())
        self.tick(Q, "tempus_sentinel")
        q.wait(r"^tick tempus_sentinel: shuffle merged$")
        say("Q ticked its sentinel store and shuffled with the Python sentinel S; S holds: %s" % s.views())
        # a store that is not of the node's own type: the sentinel S shuffles its edge store with an edge
        s.fire("tick tempus_edge")
        s.wait(r"^tick tempus_edge: shuffle merged$")
        T.quiet()
        say("S ticked its edge store (a store of another type than its own); S holds: %s" % s.views())
        T.check(len(s.node.peers("tempus_edge")) == 2, "S lost an edge at a shuffle of its edge store (ruling NQ-15)")
        # the edges shuffle their sentinel stores with a sentinel of the other kind
        self.tick(A, "tempus_sentinel")
        a.wait(r"^tick tempus_sentinel: shuffle (merged|failed)$")
        say("A ticked its sentinel store; S holds: %s" % s.views())
        p.fire("tick tempus_sentinel")
        p.wait(r"^tick tempus_sentinel: shuffle (merged|failed)$")
        T.quiet()
        say("P ticked its sentinel store; P holds: %s" % p.views())
        # the stores of two more ticks each, so that entries travel between the kinds
        for _ in range(2):
            p.fire("tick tempus_edge")
            p.wait(r"^tick tempus_edge: (shuffle merged|shuffle failed|the view is empty)$")
            T.quiet()
            self.tick(A, "tempus_edge")
            a.wait(r"^tick tempus_edge: (shuffle merged|shuffle failed|the view is empty)$")
        say("after two more ticks of each edge; P holds: %s" % p.views())
        say("S holds: %s" % s.views())

    # ---- part 2
    def same(self, name, act, note=""):
        """one hostile case, sent to the Silica sentinel Q and to the Python sentinel S; the audit lines must agree"""
        q, s = self.silica["q"], self.py["s"]
        mq, ms = len(q.text()), len(s.text())
        seen_q = act(Q)
        T.quiet()
        seen_s = act(S)
        T.quiet()
        lines_q, lines_s = audit_since(q.text(), mq), audit_since(s.text(), ms)
        say("case: %s%s" % (name, " (%s)" % note if note else ""))
        say("  the peer saw: %s" % seen_q)
        for ln in lines_q:
            say("  both nodes: %s" % ln)
        T.check(seen_q == seen_s, "case `%s`: the peer saw `%s` of the Silica node and `%s` of the Python node" % (name, seen_q, seen_s))
        T.check(lines_q == lines_s and lines_q, "case `%s`: the Silica node wrote %s and the Python node wrote %s" % (name, lines_q, lines_s))

    def dialer(self, who, body, **kw):
        return lambda addr: line(c.dial(addr, who, self.v, body, timeout=6.0, **kw))

    def no_tls(self, who, body, **kw):
        """A dial that must end with no tempus/1 connection. How a peer learns of that differs between the two TLS
        libraries (an alert during the handshake, or a close after it), so only the fact is kept."""
        def act(addr):
            out = c.dial(addr, who, self.v, body, timeout=6.0, **kw)
            T.check(out.what in ("tls_failed", "closed") and out.advert is None, "a dial to %s that must fail in TLS: %s" % (addr, out.line()))
            return "no tempus/1 connection"
        return act

    def part2(self):
        say("part 2: refusals; each case goes to the Silica sentinel Q and to the Python sentinel S, and the lines must agree")
        d, v = self.d, self.v
        smp = c.sample("tempus_edge", 2)
        tok = lambda **kw: c.make_token(kw.get("signer", PROD), kw.get("kid", "k1"), kw.get("sub", d.pub), kw.get("typ", "tempus_edge"), kw.get("nbf", 1000), kw.get("exp", 3000))  # noqa: E731
        other = lambda first, typ="tempus_edge", **kw: c.fixture_identity(first, typ, 1000, kw.pop("exp", 3000), addr=DEAD, **kw)  # noqa: E731
        x1, x2, x3 = other(176), other(192), other(208)
        raw = lambda body: c.Misbehaviour(replace={"request": c.raw_frame(body)})  # noqa: E731
        # ---- the token
        self.same("an expired token", self.dialer(d.with_token(tok(exp=1400)), smp))
        self.same("a token that is not valid yet", self.dialer(d.with_token(tok(nbf=1800)), smp))
        self.same("a token under another kid", self.dialer(d.with_token(tok(signer=OLD, kid="k0")), smp), "the one refusal a peer is told")
        self.same("a token under another kid that has also expired", self.dialer(d.with_token(tok(signer=OLD, kid="k0", exp=1400)), smp))
        self.same("a token signed by a key that is not the producer's", self.dialer(d.with_token(tok(signer=OLD)), smp))
        self.same("a token whose sub is another key", self.dialer(d.with_token(tok(sub=x1.pub)), smp))
        self.same("a token that is not a token", self.dialer(d.with_token(tok()[:-1]), smp))
        # ---- the advert
        self.same("an advert whose pub is not the key of the TLS certificate (the binding)", self.dialer(d, smp, misbehaviour=c.wrong_advert(x2.advert())))
        wrong_id = c.advert(c.descriptor(c.peer_id(x1.pub), d.pub, DEAD, d.token))
        self.same("an advert whose id is not the hash of its pub", self.dialer(d, smp, misbehaviour=c.wrong_advert(wrong_id)))
        short_id = c.etf_encode({A_("t"): A_("advert"), A_("ver"): 1, A_("d"): {A_("id"): bytes(63), A_("pub"): d.pub, A_("addr"): b"127.0.0.1:1", A_("token"): d.token}})
        self.same("an advert whose id is 63 bytes", self.dialer(d, smp, misbehaviour=c.wrong_advert(short_id)))
        ver2 = c.etf_encode({A_("t"): A_("advert"), A_("ver"): 2, A_("d"): d.descriptor()})
        self.same("an advert of version 2", self.dialer(d, smp, misbehaviour=c.wrong_advert(ver2)))
        self.same("a sample where the advert is due", self.dialer(d, smp, misbehaviour=c.wrong_advert(smp)))
        self.same("a frame above the ceiling where the advert is due", self.dialer(d, smp, misbehaviour=c.oversize_frame_at("advert")))
        # ---- the tempus whitelist, both ways
        self.same("a tempus_sentinel token under a certificate that is not in the whitelist", self.dialer(d.with_token(tok(typ="tempus_sentinel")), smp))
        self.same("a tempus_bridge token under a certificate that is not in the whitelist", self.dialer(d.with_token(tok(typ="tempus_bridge")), smp))
        listed = c.Identity(bytes(range(224, 256)), token("x4", "tempus_edge", 3000), DEAD, cert_pem=T.cert("x4"))
        self.same("a tempus_edge token under a certificate of the whitelist", self.dialer(listed, smp))
        # ---- the proof of possession
        self.same("a proof over another nonce", self.dialer(d, smp, misbehaviour=c.wrong_proof_other_nonce()))
        self.same("a proof by another key", self.dialer(d, smp, misbehaviour=c.wrong_proof_other_key(c.fixture_key(224))))
        self.same("a proof of 63 bytes", self.dialer(d, smp, misbehaviour=c.wrong_proof_bytes(bytes(63))))
        self.same("no proof: the request where the response is due", self.dialer(d, smp, misbehaviour=c.no_proof()))
        self.same("a sample where the challenge is due", self.dialer(d, smp, misbehaviour=c.wrong_frame_at("challenge", smp)))
        # ---- the request and its bounds
        self.same("a sample of 9 from a store whose shuffle length is 3", self.dialer(d, c.sample("tempus_edge", 9)))
        self.same("a sample of 3 from a store whose shuffle length is 2", self.dialer(d, c.sample("tempus_bridge", 3)))
        self.same("a sample of 0", self.dialer(d, c.sample("tempus_edge", 0)))
        four = c.shuffle("tempus_edge", [d.entry(0), x1.entry(1), x2.entry(1), x3.entry(1)])
        self.same("a shuffle of 4 entries, above every shuffle length of the node", self.dialer(d, four))
        b1, b2, b3 = other(176, "tempus_bridge"), other(192, "tempus_bridge"), other(208, "tempus_bridge")
        three = c.shuffle("tempus_bridge", [b1.entry(1), b2.entry(1), b3.entry(1)])
        self.same("a shuffle of 3 entries of a store whose shuffle length is 2", self.dialer(d, three))
        forged = other(192, producer=OLD)
        self.same("a shuffle with an entry whose token another key signed", self.dialer(d, c.shuffle("tempus_edge", [d.entry(0), forged.entry(0)])))
        self.same("a shuffle with an entry whose token has expired", self.dialer(d, c.shuffle("tempus_edge", [other(192, exp=1400).entry(0)])))
        self.same("a shuffle of the edge store with an entry of a bridge", self.dialer(d, c.shuffle("tempus_edge", [b1.entry(0)])))
        aged = c.etf_encode({A_("t"): A_("shuffle"), A_("store"): A_("tempus_edge"), A_("entries"): [{A_("age"): 65536, A_("d"): d.descriptor()}]})
        self.same("a shuffle with an age of 65536", self.dialer(d, aged))
        self.same("a call (served by a bridge only)", self.dialer(d, c.call_frame("r1", "erlang", "ok", [1])))
        self.same("a cast (served by a bridge only)", self.dialer(d, c.call_frame("r2", "erlang", "ok", [1], kind="cast")))
        self.same("a frame of no kind", self.dialer(d, c.etf_encode({A_("t"): A_("hello")})))
        self.same("a reply where a request is due", self.dialer(d, c.sample_reply("tempus_edge", [])))
        self.same("a request with bytes after it", self.dialer(d, smp, misbehaviour=raw(smp + b"\x00")))
        self.same("a request that is not a map", self.dialer(d, smp, misbehaviour=raw(c.etf_encode([1, 2]))))
        self.same("a frame above the ceiling where the request is due", self.dialer(d, smp, misbehaviour=c.oversize_frame_at("request")))
        # ---- closes and silence
        self.same("the peer closes after its advert", self.dialer(d, smp, misbehaviour=c.close_after_advert()))
        self.same("the peer is silent where its challenge is due, past the connection's one bound", self.dialer(d, smp, misbehaviour=c.silent_at("challenge", 3.0)))
        # ---- TLS
        self.same("TLS 1.2", self.no_tls(d, smp, **c.tls12_only()))
        self.same("another ALPN name", self.no_tls(d, smp, **c.other_alpn()))
        self.same("no certificate", self.no_tls(d, smp, **c.no_certificate()))
        self.same("a certificate whose key is not Ed25519", self.no_tls(d, smp, **c.p256_cert()))
        # ---- the limit of accepted connections served at once (inflight_max 2)
        self.same("a third connection while two are served", self.three)

    def three(self, addr):
        seen = []

        def hold():
            seen.append(line(c.dial(addr, self.d, self.v, c.sample("tempus_edge", 2), timeout=6.0, misbehaviour=c.silent_at("challenge", 1.6))))
        held = [threading.Thread(target=hold) for _ in range(2)]
        for t in held:
            t.start()
            time.sleep(0.4)
        third = line(c.dial(addr, self.d, self.v, c.sample("tempus_edge", 2), timeout=6.0))
        for t in held:
            t.join()
        return "%s; the two that were served: %s" % (third, ", ".join(sorted(seen)))

    # ---- part 3: the extension as a peer that is not a node
    def part3(self):
        say("part 3: the extension as a peer that is not a node (bees_tempus_peer.dial and Listener)")
        px, cd = bees_tempus_peer, bees_tempus_codec
        fps = [bees_tempus_admission.fingerprint(bees_tempus_admission.certificate_der(T.cert(n))) for n in WHITELIST]
        v = bees_tempus_admission.Verifier(PROD_PUB, "k1", 1500, 10, fps)
        me = px.Identity(os.path.join(CERTS, "x3.pem"), os.path.join(CERTS, "x3-key.pem"), token("x3", "tempus_edge", 3000), XL)
        show = lambda out: re.sub(r" peer=[0-9a-f]+", "", out.line())  # noqa: E731
        dial = lambda addr, body: px.dial(addr, me, v, body, timeout=4.0, shuffle_length=3)  # noqa: E731
        q = self.silica["q"]
        # against a Silica node: the whitelist rule passes (Q's certificate is entry 0), the reply is the reply of the
        # request and its entries verify
        out = dial(Q, cd.sample("tempus_edge", 3))
        T.check(out.what == "reply" and out.kind == "sample_reply" and out.typ == "tempus_sentinel", "the extension's sample of Q: " + out.line())
        say("a sample of Q's edge store: %s" % show(out))
        out = dial(Q, cd.sample("tempus_sentinel", 2))
        T.check(out.what == "reply" and len(out.fields["entries"]) == 1, "the extension's sample of Q's sentinel store: " + out.line())
        say("a sample of Q's sentinel store, whose one entry (the Python sentinel S) verified: %s" % show(out))
        out = dial(Q, cd.shuffle("tempus_edge", [me.entry(0)]))
        T.check(out.what == "reply" and out.kind == "shuffle_reply", "the extension's shuffle with Q: " + out.line())
        say("a shuffle of the edge store with Q: %s" % show(out))
        out = dial(Q, cd.call_frame("r1", "erlang", "ok", [1]))
        T.check(out.what == "closed", "the extension's call to Q, which is no bridge: " + out.line())
        say("a call to Q, which is no bridge: %s" % show(out))
        T.quiet()
        # listening: Q holds this peer in its edge store (the samples above put it there) and dials it at its next tick.
        # The listener was given no certificate of Q in advance.
        asked = []

        def serve(rq):
            asked.append("%s of %s, %d entries" % (rq.kind, rq.fields["store"], len(rq.fields.get("entries", []))))
            return cd.shuffle_reply(rq.fields["store"], []) if rq.kind == "shuffle" else cd.sample_reply(rq.fields["store"], [])
        with px.Listener(me, v, serve, host="127.0.0.1", port=BASE + 10, timeout=4.0, shuffle_length=3) as heard:
            self.tick(Q, "tempus_edge")
            q.wait(r"^tick tempus_edge: shuffle merged$")
            outs = heard.outcomes(1, wait=8.0)
        T.check(len(outs) == 1 and outs[0].what == "served" and outs[0].typ == "tempus_sentinel", "the extension's listener, dialed by Q: %s" % outs)
        say("the extension's listener, dialed by Q at Q's tick: %s; it was asked: %s" % (show(outs[0]), asked[0]))
        # against a peer that answers wrongly: every reply that is not the reply of its request is refused
        x1 = c.Identity(bytes(range(176, 208)), token("x1", "tempus_edge", 3000), HOSTILE, cert_pem=T.cert("x1"))
        x2 = c.fixture_identity(192, "tempus_edge", 1000, 3000, addr=DEAD)
        x4 = c.fixture_identity(64, "tempus_edge", 1000, 3000, addr=DEAD)
        forged = c.fixture_identity(192, "tempus_edge", 1000, 3000, addr=DEAD, producer=OLD)
        result = lambda rid: c.etf_encode({A_("t"): A_("result"), A_("ver"): 1, A_("req_id"): rid, A_("value"): 5})  # noqa: E731
        smp = cd.sample("tempus_edge", 2)
        good = lambda rq: c.sample_reply("tempus_edge", [x2.entry(1)])  # noqa: E731
        bad_atom = c.raw_frame(b"\x83\x74\x00\x00\x00\x01\x77\x01t\x77\x02\xff\xfe")
        cases = (  # name, request, the wrong peer's answer, its switches, its identity
            ("a good sample reply", smp, good, {}, x1),
            ("a shuffle reply to a sample", smp, lambda rq: c.shuffle_reply("tempus_edge", []), {}, x1),
            ("a sample reply to a shuffle", cd.shuffle("tempus_edge", [me.entry(0)]), lambda rq: c.sample_reply("tempus_edge", []), {}, x1),
            ("a sample reply for another store", smp, lambda rq: c.sample_reply("tempus_bridge", []), {}, x1),
            ("three entries to a sample of two", smp, lambda rq: c.sample_reply("tempus_edge", [x2.entry(1), x4.entry(2), x1.entry(0)]), {}, x1),
            ("a reply with an entry whose token another key signed", smp, lambda rq: c.sample_reply("tempus_edge", [x2.entry(1), forged.entry(0)]), {}, x1),
            ("the test unit's done frame", smp, lambda rq: c.done(), {}, x1),
            ("a reply whose atom is not UTF-8", smp, lambda rq: c.send_raw(bad_atom), {}, x1),
            ("a frame above the ceiling", smp, lambda rq: c.send_raw(b"\x00\x02\x00\x01"), {}, x1),
            ("a result with the call's req_id", cd.call_frame("r1", "erlang", "ok", [1]), lambda rq: result(b"r1"), {}, x1),
            ("a result with another req_id", cd.call_frame("r1", "erlang", "ok", [1]), lambda rq: result(b"zz"), {}, x1),
            ("a result to a cast", cd.call_frame("r1", "erlang", "ok", [1], kind="cast"), lambda rq: result(b"r1"), {}, x1),
            ("no reply", smp, lambda rq: c.CLOSE, {}, x1),
            ("an advert under another certificate (the binding), with an expired token", smp, good,
             {"misbehaviour": c.wrong_advert(c.fixture_identity(192, "tempus_edge", 1000, 1400, addr=DEAD).advert())}, x1),
            ("an advert with a tempus_sentinel token under a certificate that is not in the whitelist", smp, good, {},
             x1.with_token(token("x1", "tempus_sentinel", 3000))),
            ("an advert with a token under another kid", smp, good, {}, x1.with_token(token("x1", "tempus_edge", 3000, signer=OLD, kid="k0"))),
            ("a wrong proof", smp, good, {"misbehaviour": c.wrong_proof_other_nonce()}, x1),
        )
        for name, request, answer, switches, who in cases:
            with c.Listener(who, self.v, answer, [T.cert("x3")], port=BASE + 11, timeout=4.0, **switches):
                out = dial(HOSTILE, request)
            say("against a peer that sends %s: %s" % (name, show(out)))
            T.check((out.what == "reply") == name.startswith(("a good", "a result with the call")), "the extension's dial, `%s`: %s" % (name, out.line()))
        T.quiet()

    # ---- part 4
    def part4(self):
        say("part 4: two nodes that are not test nodes, the Python sentinel R and the Silica edge W, by the machine's clock")
        leaf = self.leaf
        v = values(leaf, "sentinel", "x4", R, [], edge={"capacity": 4, "shuffle_length": 3, "tick_ms": 8000},
                   bridge={"capacity": 4, "shuffle_length": 2, "tick_ms": 3600000},
                   sentinel={"capacity": 4, "shuffle_length": 2, "tick_ms": 3600000})
        v["address"] = R
        v["token_file"] = os.path.join(leaf, "r_token.hex")
        with open(v["token_file"], "w") as f:
            f.write(token("x4", "tempus_sentinel", 4000000000).hex() + "\n")
        with open(os.path.join(leaf, "r_app.json"), "w") as f:
            json.dump(v, f, indent=1)
        r = T.Node(leaf, "r_app.py")
        self.silica["r_app"] = r                       # stopped like a Silica node on a failure
        r.wait(r"^join: no sentinel is configured$")
        w = self.silica["w"] = T.Node(os.path.join(leaf, "nodes", "w"), "dangerous_w")
        w.wait(r"^join: done$")
        say("W, a Silica edge, joined through the Python sentinel R")
        far = self.far

        def frames(addr):
            return "; ".join("%s: %s" % (name, line(c.dial(addr, far, self.v, body, timeout=6.0))) for name, body in (
                ("tick", c.tick("tempus_edge")), ("clock", c.clock(1500000)), ("clock with a later reading", c.clock(1500000, 100, 1600000))))
        mr, mw = len(r.text()), len(w.text())
        seen_w = frames(W)
        seen_r = frames(R)
        T.quiet()
        lines_w, lines_r = audit_since(w.text(), mw), audit_since(r.text(), mr)
        say("the test-only tick and clock frames, sent to both; the peer saw: %s" % seen_w)
        for ln in lines_w:
            say("  both nodes: %s" % ln)
        T.check(seen_w == seen_r, "the test frames: the peer saw `%s` of W and `%s` of R" % (seen_w, seen_r))
        T.check(lines_w == lines_r and len(lines_w) == 6, "the test frames: W wrote %s and R wrote %s" % (lines_w, lines_r))
        r.wait(r"^tick tempus_edge: shuffle merged$", timeout=30.0)
        say("R ticked its edge store on its own timer and shuffled with W")
        T.quiet()
        self.silica.pop("r_app").stop()
        os.replace(os.path.join(leaf, "r_app.py.sout"), os.path.join(leaf, "py_r.sout"))
        self.stop("w")
        with open(os.path.join(leaf, "py_r.sout")) as f:
            T.check("application: test support loaded: none\n" in f.read(), "the program of node R loaded test support")
        say("the program of node R loaded no test support")

    # ---- part 5
    def shut(self, addr):
        out = c.dial(addr, self.d, self.v, c.sample("tempus_edge", 2), timeout=4.0)
        T.check(out.what in ("closed", "tls_failed"), "a connection to %s was not closed at once: %s" % (addr, out.line()))
        return "closed"

    def ask(self, addr, who=None, verifier=None):
        return line(c.dial(addr, who or self.d, verifier or self.v, c.sample("tempus_edge", 2), timeout=4.0))

    def part5(self):
        say("part 5: the clock's choices on Python nodes; the readings are the test clock's")
        d = self.d
        short = d.with_token(c.make_token(PROD, "k1", d.pub, "tempus_edge", 1000, 1480))
        # ---- H: clock_back hold, clock_fail continue
        h = self.python("h", "sentinel", "sentinel", "tempus_sentinel", H, clock_back="hold", clock_fail="continue")
        h.wait(r"^join: no sentinel is configured$")
        say("H (hold, continue) at 1500: a peer whose token ended at 1480, expired by 1500: %s" % self.ask(H, short))
        h.reading(1450)
        h.wait(r"the node holds its time until the system clock has reached it$")
        say("H read 1450, 50 s back: it holds 1500; a token that ended at 1480 (good by 1450, expired by 1500): %s; a good one: %s"
            % (self.ask(H, short), self.ask(H)))
        h.wait(r"admission_refused peer=\S+ the token has expired")
        h.fire("tick tempus_bridge")
        h.wait(r"^tick tempus_bridge: the view is empty$")
        h.reading(1460)
        say("H read 1460, still behind: no line; the token that ended at 1480: %s" % self.ask(H, short))
        h.reading(1500)
        h.wait(r"^clock: the system clock has reached the held time; the node follows it again$")
        h.reading(None)
        h.wait(r"^clock: the system clock could not be read: the node goes on with its last reading$")
        h.wait(r"^application: told \(clock_unreadable\)")
        h.fire("tick tempus_bridge")
        h.wait(r"^tick tempus_bridge: the view is empty$")
        say("H could not read its clock: it goes on with its last reading, ticks, and answers: %s" % self.ask(H))
        h.reading(1510)
        h.reading(None)
        h.wait(r"^clock: the system clock could not be read: the node goes on with its last reading$")
        say("H read 1510 without a line, and a second failure was told again")
        # H's own token ends at 2000: by 2100 it is not valid, and ticking stops until the application gives a new one
        h.reading(2100)
        h.fire("tick tempus_bridge")
        h.wait(r"^own token: the token has expired; ticking has stopped$")
        h.wait(r"^application: told that the node's own token is not valid any more: the token has expired$")
        late = c.Verifier(PROD_PUB, "k1", 2100, 10)
        say("H at 2100, its own token expired: it has stopped ticking; it still listens, and a peer that checks its advert: %s"
            % self.ask(H, d, late))
        h.node.set_token(token("sentinel", "tempus_sentinel", 3000))
        h.wait(r"^own token replaced$")
        h.fire("tick tempus_bridge")
        h.wait(r"^tick tempus_bridge: the view is empty$")
        say("H was given a new token: it ticks again, and the same peer: %s" % self.ask(H, d, late))
        # the producer's key changes: the application gives the node the new one
        new = c.fixture_key(160)
        h.node.set_producer_key("k9", c._raw_public(new))
        h.wait(r"^producer key replaced, kid k9$")
        say("H was given the producer's new key, kid k9; a peer with a token under k1: %s" % self.ask(H))
        h.wait(r"key_rotated peer=\S+ the peer's token is under another kid; it was told the current one")
        T.quiet()
        self.py.pop("h").stop()
        # ---- T: clock_back stop with a limit of 60 s, clock_fail pause; its sentinel V does not listen yet
        t = self.python("t", "edge", "other", "tempus_edge", TT, [(V, "bridge")], clock_back="stop", clock_back_limit_s=60, clock_fail="pause")
        t.wait(r"^join: no sentinel answered for tempus_edge; waiting to try again$")
        say("T (stop above 60 s, pause): no sentinel answered; the join's retry timer is armed with %d ms" % t.timers.delay("join retry"))
        t.reading(None)
        t.wait(r"^clock: the system clock could not be read: the node admits no connection and does not tick until it is read again$")
        t.wait(r"^application: told \(clock_unreadable\)")
        say("T could not read its clock: it waits; a connection: %s" % self.shut(TT))
        t.wait(r"clock_refused peer=- the system clock cannot be read: closed at once")
        t.fire("tick tempus_edge")
        t.fire("join retry")
        t.wait(r"^join: the request for tempus_edge waits until the system clock is read again$")
        say("the join's retry fell due while T waited: it dialed nobody")
        vv = self.python("v", "sentinel", "bridge", "tempus_sentinel", V)
        vv.wait(r"^join: no sentinel is configured$")
        t.reading(1500)
        t.wait(r"^clock: the system clock is read again$")
        t.wait(r"^join: done$")
        say("T read its clock again and dialed the waiting join request at once; T holds: %s" % t.views())
        t.reading(1470)
        t.wait(r"^clock: the system clock went back by 30 s; the node follows it$")
        say("T read 1470, 30 s back, inside the limit: it follows; a connection: %s" % self.ask(TT))
        t.reading(1370)
        t.wait(r"^clock: the system clock went back by 100 s, more than clock_back_limit_s 60: the node has stopped")
        t.wait(r"^application: told \(stopped\)")
        say("T read 1370, 100 s back, above the limit: it has stopped; a connection: %s" % self.shut(TT))
        t.wait(r"clock_stopped peer=- the node stopped after its system clock went back: closed at once")
        t.reading(2000)
        t.fire("tick tempus_edge")
        say("T read 2000: it stays stopped and does not tick; a connection: %s" % self.shut(TT))
        t.wait(r"clock_stopped peer=- the node stopped after its system clock went back: closed at once")
        T.quiet()
        self.py.pop("t").stop()
        self.py.pop("v").stop()


def main(argv):
    if len(argv) != 2:
        print(__doc__)
        return 2
    leaf = os.path.abspath(argv[1])
    whitelist_dir(leaf)
    walk = Walk(leaf)
    rc = 0
    try:
        walk.part1()
        walk.part2()
        walk.part3()
        for name in ("p", "s"):
            walk.py.pop(name).stop()
        walk.stop("a")
        walk.stop("q")
        walk.part4()
        walk.part5()
        say("done")
    except SystemExit as why:
        say(str(why))
        print(str(why).split("\n")[0])
        rc = 1
    finally:
        walk.close()
    with open(os.path.join(leaf, "walk.sout"), "w") as f:
        f.write("".join(ln + "\n" for ln in SAID))
        f.write("exit=%d\n" % rc)
    if rc == 0:
        print("[c7_tempus_node_python] the walk ended: %d lines" % len(SAID))
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv))
