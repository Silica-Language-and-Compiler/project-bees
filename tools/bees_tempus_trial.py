#!/usr/bin/env python3
"""Run a TEMPUS trial in which node processes and the Python client (example_tempus_clients/python/bees_tempus_client.py) act together.

    bees_tempus_trial.py SCENARIO LEAF_DIR

The node executables of the leaf are started here, each with its standard output on a pty and its stdin on a pipe (as
tools/run_trial.py runs one). The runtime's own stream (its reports of actors that ended, which it writes in pieces
that land anywhere among a program's lines when both go to one place) is read apart: of it the output file gets, before
the exit line, the reason of every report that is not an ordinary end and any line that is no report. Then the scenario's steps are walked, and each node is told to exit; a node's output goes to NAME.sout with its exit
code appended, as every trial's does. A step waits for the reply of its request and, where the node goes on working after
the reply, for the node line that ends that work, so a node's lines come in one order on every run. What a step can see
on the wire is asserted here (a failed assertion fails the trial); what only the node knows is in its golden.
Nothing of the wall clock is printed. Ports come from tools/trial_ports.py.

Scenarios: t3 (trials/t3_tempus_nodes), c2 (trials/c2_tempus_clients; C2_ONLY=python or C2_ONLY=silica in the
environment walks one client's half, for work on a scenario by hand), c3 (trials/c3_tempus_bridge; its nodes run in their
own directories under nodes/, each writing its NAME.sout there; C3_ONLY as C2_ONLY), t6 (trials/t6_tempus_clock; nodes
under nodes/ as c3).
"""
import os
import pty
import re
import select
import subprocess
import socket
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "example_tempus_clients", "python"))  # the example Python client
import bees_tempus_client as c  # noqa: E402
from bees_tempus_reports import BENIGN, REASON, REPORT  # noqa: E402
import trial_ports  # noqa: E402

CERTS = os.path.join(HERE, "..", "trials", "t5_tempus_tls", "certs")


class Node:
    """One node process. wait(pattern) blocks until a line after the last one matched matches the pattern."""

    def __init__(self, leaf, name):
        self.name, self.out_path = name, os.path.join(leaf, name + ".sout")
        master, slave = pty.openpty()
        self.proc = subprocess.Popen([os.path.join(leaf, name)], cwd=leaf, stdin=subprocess.PIPE, stdout=slave,
                                     stderr=subprocess.PIPE, close_fds=True)
        os.close(slave)
        self.master, self.chunks, self.seen = master, [], 0
        self.err = []
        self.lock = threading.Condition()
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()
        self.err_thread = threading.Thread(target=self._read_err, daemon=True)
        self.err_thread.start()

    def _read_err(self):
        while True:
            data = self.proc.stderr.read1(65536)
            if not data:
                break
            self.err.append(data)

    def reports(self):
        """The lines the runtime's own stream gives the output file: the reason of every actor report that is not an
        ordinary end, and any line that is no part of a report (a crash says why here)."""
        text = b"".join(self.err).decode("utf-8", "replace").replace("\r\n", "\n")
        text = text.replace("[silica] root actor exited (no supervisor)\n", "")
        out = []
        for ln in text.split("\n"):
            m = REASON.match(ln)
            if m:
                if m.group(1) not in BENIGN:
                    out.append("runtime report: an actor ended with reason " + m.group(1))
            elif ln.strip() and not REPORT.match(ln):
                out.append("runtime: " + ln.rstrip())
        return sorted(out)

    def _read(self):
        while True:
            r, _, _ = select.select([self.master], [], [], 0.1)
            if r:
                try:
                    data = os.read(self.master, 65536)
                except OSError:
                    data = b""
                if not data:
                    break
                with self.lock:
                    self.chunks.append(data)
                    self.lock.notify_all()
            elif self.proc.poll() is not None:
                break
        with self.lock:
            self.lock.notify_all()

    def text(self):
        return b"".join(self.chunks).replace(b"\r\n", b"\n").decode("utf-8", "replace")

    def wait(self, pattern, timeout=20.0):
        rx = re.compile(pattern, re.M)
        until = time.monotonic() + timeout
        with self.lock:
            while True:
                text = self.text()
                done = text.rfind("\n") + 1          # whole lines only
                m = rx.search(text[:done], self.seen)
                if m:
                    self.seen = text.find("\n", m.end()) + 1
                    return m
                left = until - time.monotonic()
                if left <= 0 or (self.proc.poll() is not None and not self.thread.is_alive()):
                    raise SystemExit("FAIL: %s did not print /%s/ in time; its output so far:\n%s" % (self.name, pattern, text))
                self.lock.wait(min(left, 0.2))

    def stop(self):
        if self.proc.poll() is None:
            try:
                self.proc.stdin.write(b"exit\n")
                self.proc.stdin.flush()
            except Exception:
                pass
        try:
            rc = self.proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            rc = self.proc.wait()
            self.chunks.append(b"\n[bees_tempus_trial] killed\n")
        self.thread.join(timeout=5)
        self.err_thread.join(timeout=5)
        with open(self.out_path, "w") as f:
            f.write(self.text())
            f.write("".join(ln + "\n" for ln in self.reports()))
            f.write("exit=%d\n" % rc)


def quiet(seconds=0.7):
    """the time a node's last actors need to end after a connection (the connection actor is reaped 500 ms after its close)"""
    time.sleep(seconds)


def check(cond, what):
    if not cond:
        raise SystemExit("FAIL: " + what)


def ids8(entries):
    return sorted(d[c.Atom("id")][:4].hex() for _age, d in entries)


def cert(name):
    with open(os.path.join(CERTS, name + ".pem"), "rb") as f:
        return f.read()


class Peer:
    """The Python client's side of a scenario: the verifier with the trial's clock, and one-line requests."""

    def __init__(self, now=1500, skew=10):
        self.clock = [now]
        self.verifier = c.Verifier(c._raw_public(c.fixture_key(0)), "k1", lambda: self.clock[0], skew)
        self.log = []

    def ask(self, addr, who, body, want="reply", kind=None, **kw):
        out = c.dial(addr, who, self.verifier, body, **kw)
        self.log.append(out.line())
        check(out.what == want and (kind is None or out.kind == kind),
              "a request to %s: wanted %s %s, got: %s" % (addr, want, kind or "", out.line()))
        return out


def t3(leaf):
    base = trial_ports.TABLE["t3_tempus_nodes"][0]
    s_addr, a_addr, b_addr = ("127.0.0.1:%d" % (base + k) for k in (0, 1, 2))
    c_addr = "127.0.0.1:%d" % (base + 3)
    # C listens and misbehaves; its token ends at 1600. D sends the test-only frames and never listens (its address is
    # only a value in its advert).
    cc = c.fixture_identity(96, "tempus_edge", 1000, 1600, addr=c_addr)
    dd = c.fixture_identity(112, "tempus_edge", 1000, 3000, addr="127.0.0.1:%d" % (base + 4))
    old = c.fixture_identity(112, "tempus_edge", 1000, 2000, addr=dd.addr, kid="k0", producer=c.fixture_key(1))
    forged = c.fixture_identity(144, "tempus_edge", 1000, 2000, addr=dd.addr, producer=c.fixture_key(64))
    p = Peer()
    nodes = {}
    seen_by_c = []

    def handler(rq):
        seen_by_c.append((rq.kind, ids8(rq.fields.get("entries", [])), [age for age, _d in rq.fields.get("entries", [])]))
        if len(seen_by_c) == 1:
            # hostile: one entry whose token another producer signed, beside a good one (the whole frame must be refused)
            return c.shuffle_reply("tempus_edge", [dd.entry(0), forged.entry(0)])
        return c.CLOSE

    try:
        s = nodes["s"] = Node(leaf, "dangerous_s")
        s.wait(r"^join: no sentinel is configured$")
        a = nodes["a"] = Node(leaf, "dangerous_a")
        a.wait(r"^join: done$")
        b = nodes["b"] = Node(leaf, "dangerous_b")
        b.wait(r"^join: done$")
        quiet()

        # 1. a tick on A's empty edge store: nothing to shuffle; A asks the sentinel again and learns B
        p.ask(a_addr, dd, c.tick("tempus_edge"), kind="done")
        a.wait(r"^join: the sentinel answered for tempus_edge")
        a.wait(r"^view tempus_edge:")
        quiet()
        # 2. the next tick: A shuffles with B (two Silica nodes, initiator and responder)
        p.ask(a_addr, dd, c.tick("tempus_edge"), kind="done")
        quiet()
        # 3. the client shuffles with B as the initiator: its own entry at age 0
        out = p.ask(b_addr, cc, c.shuffle("tempus_edge", [cc.entry(0)]), kind="shuffle_reply")
        check(out.fields["store"] == "tempus_edge", "the shuffle_reply names another store")
        quiet()
        # 4. sample: B's edge store now holds the client
        out = p.ask(b_addr, dd, c.sample("tempus_edge", 3), kind="sample_reply")
        check(cc.peer_id[:4].hex() in ids8(out.fields["entries"]), "the client is not in B's sample: " + out.line())
        quiet()
        # 5. ticks on B until it has dialed the client's listener, which answers with a forged entry among good ones
        with c.Listener(cc, p.verifier, handler, [cert("other"), cert("node"), cert("sentinel")], port=base + 3,
                        timeout=5.0) as lis:
            for _ in range(4):
                p.ask(b_addr, dd, c.tick("tempus_edge"), kind="done")
                quiet()
                if seen_by_c:
                    break
            check(len(seen_by_c) == 1 and seen_by_c[0][0] == "shuffle", "B did not shuffle with the client: %r" % seen_by_c)
            lis.outcomes(1)
        # 6. A stops; B's ticks reach it as the oldest entry and the dial fails
        nodes.pop("a").stop()
        for _ in range(3):
            p.ask(b_addr, dd, c.tick("tempus_edge"), kind="done")
            quiet()
        # 7. the clock: a sample to the sentinel puts the client into the sentinel's edge store; at 1700 its token has
        #    expired, and the sentinel's next tick drops the entry
        p.ask(s_addr, cc, c.sample("tempus_edge", 3), kind="sample_reply")
        quiet()
        p.clock[0] = 1700
        p.ask(s_addr, dd, c.clock(1700000), kind="done")
        p.ask(s_addr, dd, c.tick("tempus_edge"), kind="done")
        quiet(1.0)
        # 8. a token under the old kid gets the one key_rotated frame
        out = p.ask(s_addr, old, c.sample("tempus_edge", 1), want="key_rotated")
        check(out.kid == b"k1", "key_rotated names another kid: " + out.line())
        quiet()
        # 9. inflight_max is 2: two connections stay silent before their advert, the third is closed at once. The three
        #    are opened half a second apart and the two held ones close in that order, so the sentinel's lines about
        #    them come in one order (each stays well inside the node's 2 s bound of a connection)
        held = [threading.Thread(target=c.dial, args=(s_addr, dd, p.verifier, c.sample("tempus_edge", 1)),
                                 kwargs={"misbehaviour": c.silent_at("advert", 1.6), "timeout": 4.0})
                for _ in range(2)]
        for t in held:
            t.start()
            time.sleep(0.5)
        out = c.dial(s_addr, dd, p.verifier, c.sample("tempus_edge", 1), timeout=3.0)
        check(out.what in ("closed", "tls_failed") and out.stage in ("tls", "advert"),
              "the connection beyond inflight_max was not closed at once: " + out.line())
        for t in held:
            t.join()
        quiet(1.0)
        # ... and afterwards the sentinel serves again
        p.ask(s_addr, dd, c.sample("tempus_sentinel", 1), kind="sample_reply")
        quiet()
        # 10. the clock passes the nodes' own tokens (2000 + skew): the sentinel stops ticking and tells its application
        p.clock[0] = 1990
        p.ask(s_addr, dd, c.clock(2100000), kind="done")
        p.ask(s_addr, dd, c.tick("tempus_edge"), kind="done")
        quiet()
    finally:
        for n in list(nodes.values()):
            n.stop()
    print("[t3] the client's steps passed (%d requests)" % len(p.log))
    return 0


def c2_silica(leaf, nodes):
    """the Silica client's half of c2: its scenarios are compiled into dangerous_cs and dangerous_ce; this only starts them
    in order and waits for each to say it has finished"""
    cs = nodes["cs"] = Node(leaf, "dangerous_cs")
    cs.wait(r"^the client listens")
    m = nodes["m"] = Node(leaf, "dangerous_m")
    m.wait(r"^join: done$")
    cs.wait(r"^done$", timeout=120.0)
    quiet()
    ce = nodes["ce"] = Node(leaf, "dangerous_ce")
    ce.wait(r"^done$", timeout=300.0)
    quiet(1.0)


def c2(leaf):
    nodes = {}
    try:
        o = nodes["o"] = Node(leaf, "dangerous_o")
        o.wait(r"^join: no sentinel is configured$")
        if os.environ.get("C2_ONLY", "") != "silica":
            c2_python(leaf, nodes)
        if os.environ.get("C2_ONLY", "") != "python":
            c2_silica(leaf, nodes)
    finally:
        for n in list(nodes.values()):
            n.stop()
    return 0


def c2_python(leaf, nodes):
    """The Python client's half of c2, against node N (and node O for row 37): the same steps as the Silica client's
    compiled-in scenarios (trials/c2_tempus_clients/cs.role and ce.role; the step numbers in the comments are theirs),
    and after them what only this client can do (steps named P)."""
    A = c.Atom
    base = trial_ports.TABLE["c2_tempus_clients"][0]
    n_addr, o_addr, s_addr, e_addr, dead = ("127.0.0.1:%d" % (base + k) for k in (0, 2, 3, 4, 7))
    seeds = {1: 176, 2: 192, 3: 208, 4: 224}

    def ident(first, typ, exp, addr, certname=None, nbf=1000, **kw):
        i = c.fixture_identity(first, typ, nbf, exp, addr=addr, **kw)
        return c.Identity(i.seed, i.token, addr, cert_pem=cert(certname)) if certname else i

    def x(i, age, typ="tempus_edge", exp=2000, **kw):
        return ident(seeds[i], typ, exp, dead, **kw).entry(age)

    def b3(typ, age, exp=2000):
        return ident(160, typ, exp, dead).entry(age)

    def id8(entry):
        return entry[1][A("id")][:4].hex()

    def view(out):
        return ["%s@%d" % (id8(e), e[0]) for e in out.fields["entries"]]

    S = ident(128, "tempus_sentinel", 3000, s_addr, "sentinel")
    SB = ident(128, "tempus_bridge", 3000, s_addr, "sentinel")
    E = ident(64, "tempus_edge", 3000, e_addr, "other")
    s8, e8, n8 = S.peer_id[:4].hex(), E.peer_id[:4].hex(), c.peer_id(c._raw_public(c.fixture_key(32)))[:4].hex()
    p = Peer()
    k9 = c.Verifier(c._raw_public(c.fixture_key(0)), "k9", lambda: p.clock[0], 10)
    joined, seen_s, seen_e, mode = [False], [], [], [0]
    smp, tck = c.sample("tempus_edge", 3), c.tick("tempus_edge")
    bad_kind = c.etf_encode({A("t"): A("tempus_edge")})

    def h_s(rq):
        store = rq.fields.get("store")
        seen_s.append((rq.kind, str(store), [id8(e) for e in rq.fields.get("entries", [])]))
        if rq.kind == "sample":
            if store == "tempus_edge":
                return c.sample_reply(store, [x(1, 1)])
            if store == "tempus_bridge":
                return c.sample_reply(store, [SB.entry(0)] if joined[0] else [])
            return c.sample_reply(store, [S.entry(0)])
        if rq.kind == "shuffle":
            if store == "tempus_bridge":
                return c.shuffle_reply(store, [b3("tempus_bridge", 2)])
            return c.shuffle_reply(store, [b3("tempus_sentinel", 1)])
        return c.CLOSE

    def h_e(rq):
        seen_e.append((mode[0], rq.kind, rq.fields.get("entries", [])))
        k = mode[0]
        if k == 6:
            return c.shuffle_reply("tempus_edge", [x(2, 4), x(3, 6), x(4, 1)])
        if k == 9:
            return c.shuffle_reply("tempus_edge", [x(1, 3), x(4, 0), x(3, 70)])
        if k == 12:
            return c.shuffle_reply("tempus_edge", [x(1, 0), x(4, 0, producer=c.fixture_key(96))])
        if k == 17:
            second = c.dial(n_addr, E, p.verifier, tck)
            check(second.what == "reply" and second.kind == "done", "the second tick during a held shuffle: " + second.line())
            return c.stay_silent(2.2)
        if k == 20:
            return c.send_raw(c.raw_frame(bad_kind))
        if k == 51:
            return c.shuffle_reply("tempus_edge", [])
        return c.CLOSE

    def step(k, who, body, want="reply", kind=None, addr=n_addr, wait=0.7, **kw):
        mode[0] = k
        out = p.ask(addr, who, body, want=want, kind=kind, **kw)
        quiet(wait)
        return out

    def refused(k, who, body, **kw):
        """the node closes with no reply (the reason is in its own output)"""
        return step(k, who, body, want="closed", **kw)

    def dialed(k, n_before, what):
        check(len(seen_e) == n_before + 1 and seen_e[-1][1] == "shuffle", "step %s: the node did not shuffle with the client (%s)" % (k, what))
        return seen_e[-1][2]

    def old(k):
        return step(k, E, c.shuffle("tempus_edge", [E.entry(50)]), kind="shuffle_reply")

    with c.Listener(S, p.verifier, h_s, [cert("node")], port=base + 3, timeout=5.0) as ls, \
            c.Listener(E, p.verifier, h_e, [cert("node")], port=base + 4, timeout=6.0) as le:
        n = nodes["n"] = Node(leaf, "dangerous_n")
        n.wait(r"^join: done$")
        quiet()
        # row 2: the node joined through the client: one sample per store
        check([(k, st) for k, st, _ in seen_s] == [("sample", "tempus_edge"), ("sample", "tempus_bridge"), ("sample", "tempus_sentinel")],
              "the join did not ask the client's sentinel for the three stores: %r" % seen_s)
        joined[0] = True
        # ---- the sentinel's steps (cs.role 1 to 10)
        one = step(1, S, c.sample("tempus_sentinel", 2), kind="sample_reply")
        two = step(2, S, c.sample("tempus_sentinel", 2), kind="sample_reply")
        check(view(one) == [s8 + "@0"] and view(two) == view(one), "rows 2, 23: the sentinel store's samples: %s, %s" % (one.line(), two.line()))
        step(3, S, c.tick("tempus_sentinel"), kind="done")
        check(seen_s[-1] == ("shuffle", "tempus_sentinel", []), "rows 5, 10: the shuffle of the sentinel store: %r" % (seen_s[-1],))
        out = step(4, S, c.sample("tempus_sentinel", 2), kind="sample_reply")
        # the entry the client answered with, and the client itself: the partner that answered is put back at age 0 in a
        # store that is not of the node's own type (ruling NQ-15); before the ruling the store held the answered entry alone
        check(sorted(view(out)) == sorted([id8(b3("tempus_sentinel", 0)) + "@1", s8 + "@0"]), "the sentinel store after its shuffle: " + out.line())
        step(5, S, c.shuffle("tempus_sentinel", [S.entry(0), x(3, 7, typ="tempus_sentinel")]), kind="shuffle_reply")
        step(6, S, c.tick("tempus_bridge"), kind="done")
        n.wait(r"^view tempus_bridge: %s@0$" % s8)
        check(seen_s[-1][:2] == ("sample", "tempus_bridge"), "row 22: the node did not ask its sentinel again: %r" % (seen_s[-1],))
        quiet()
        ls.identity = SB
        step(7, SB, c.tick("tempus_bridge"), kind="done")
        check(seen_s[-1] == ("shuffle", "tempus_bridge", []), "rows 5, 10: the shuffle of the bridge store: %r" % (seen_s[-1],))
        step(8, SB, c.shuffle("tempus_bridge", [SB.entry(0)]), kind="shuffle_reply")
        ls.identity = S
        out = step(9, S, c.sample("tempus_bridge", 2), kind="sample_reply")
        check(sorted(view(out)) == sorted([id8(b3("tempus_bridge", 0)) + "@2", s8 + "@0"]), "the bridge store: " + out.line())
        refused(10, S, c.shuffle("tempus_sentinel", [x(1, 0)]))
        # ---- the edge's steps (ce.role 1 to 54)
        out = step(1, E, smp, kind="sample_reply")
        check(view(out) == [id8(x(1, 0)) + "@1"] and out.typ == "tempus_edge", "rows 2, 11, 14: " + out.line())
        step(2, E, c.shuffle("tempus_edge", [E.entry(0), x(2, 2)]), kind="shuffle_reply")
        out = step(3, E, smp, kind="sample_reply")
        check(e8 + "@0" in view(out), "row 8: the client is not in the node's view at age 0: " + out.line())
        step(4, E, tck, kind="done")
        step(5, E, tck, kind="done")
        before = len(seen_e)
        step(6, E, tck, kind="done")
        got = dialed(6, before, "rows 4, 5, 6")
        check([(id8(e), e[0]) for e in got] == [(n8, 0)],
              "row 6: the shuffle frame does not hold the node's own entry at age 0 alone: %r" % ([(id8(e), e[0]) for e in got],))
        out = step(7, E, smp, kind="sample_reply")
        check(sorted(view(out)) == sorted([id8(x(2, 0)) + "@4", id8(x(3, 0)) + "@6", id8(x(4, 0)) + "@1"]), "the view after the client's answer: " + out.line())
        step(8, E, c.shuffle("tempus_edge", [E.entry(50), x(2, 1), x(3, 40)]), kind="shuffle_reply")
        before = len(seen_e)
        step(9, E, tck, kind="done")
        dialed(9, before, "row 7")
        step(10, E, smp, kind="sample_reply")
        old(11)
        before = len(seen_e)
        step(12, E, tck, kind="done")
        dialed(12, before, "row 17")
        out = step(13, E, smp, kind="sample_reply")
        check(id8(x(4, 0)) + "@0" not in view(out), "row 17: an entry of the refused frame is in the view: " + out.line())
        old(14)
        before = len(seen_e)
        step(15, E, tck, kind="done")
        dialed(15, before, "row 18, closes with no reply")
        old(16)
        before = len(seen_e)
        step(17, E, tck, kind="done", timeout=8.0)
        dialed(17, before, "rows 18, 21, silent")
        quiet(1.0)
        step(18, E, smp, kind="sample_reply")
        old(19)
        before = len(seen_e)
        step(20, E, tck, kind="done")
        dialed(20, before, "row 18, a wrong frame")
        # P1, P2 (Python only): the partner closes after the node's advert; the partner is silent before its proof
        old("P1a")
        le.misbehaviour = c.close_after_advert()
        step("P1", E, tck, kind="done")
        old("P2a")
        le.misbehaviour = c.silent_at("response", 2.4)
        step("P2", E, tck, kind="done", timeout=8.0, wait=1.2)
        le.misbehaviour = None
        # row 12
        prod, other = c.fixture_key(0), c.fixture_key(96)
        tok = lambda **kw: c.make_token(kw.get("signer", prod), "k1", kw.get("sub", E.pub), kw.get("typ", "tempus_edge"), kw.get("nbf", 1000), kw.get("exp", 2000))  # noqa: E731
        refused(21, E.with_token(tok(signer=other)), smp)
        refused(22, E.with_token(tok(exp=1400)), smp)
        refused(23, E.with_token(tok(nbf=1800)), smp)
        refused(24, E.with_token(tok(sub=c._raw_public(other))), smp)
        refused(25, E.with_token(tok(typ="tempus_bridge")), smp)
        refused(26, E, smp, misbehaviour=c.wrong_advert(c.advert(c.descriptor(c.peer_id(c._raw_public(c.fixture_key(176))), E.pub, E.addr, E.token))))
        refused(27, E, smp, misbehaviour=c.wrong_proof_other_key(c.fixture_key(224)))
        refused("P3", E, smp, misbehaviour=c.wrong_proof_other_nonce())
        refused("P4", E, smp, misbehaviour=c.no_proof())
        refused("P5", E, smp, misbehaviour=c.wrong_proof_bytes(bytes(63)))
        out = step(28, E.with_token(c.make_token(other, "k0", E.pub, "tempus_edge", 1000, 2000)), smp, want="key_rotated")
        check(out.kid == b"k1", "row 13: key_rotated names another kid: " + out.line())
        # row 19
        short = dict(x(2, 0)[1])
        short[A("id")] = short[A("id")][:63]
        wrong = [b"\x82" + smp[1:], smp[:-1], smp + b"\x00", bytes([131, 104, 1]) + c.etf_encode(A("done"))[1:], bad_kind,
                 c.etf_encode({A("t"): A("done"), A("ver"): 1}),
                 c.etf_encode({A("n"): 1, A("store"): A("done"), A("t"): A("sample")}),
                 bytes([131]) + b"\x6c\x00\x00\x00\x01" * 8 + b"\x6a" * 9,
                 c.shuffle("tempus_edge", [E.entry(0), x(1, 1), x(2, 1), x(3, 1)]),
                 c.shuffle("tempus_edge", [E.entry(65536)]),
                 c.shuffle("tempus_edge", [(0, short)])]
        for k, body in enumerate(wrong, start=29):
            refused(k, E, smp, misbehaviour=c.wrong_frame_at("request", body))
        refused(40, E, smp, misbehaviour=c.oversize_frame_at("request"))
        refused(41, E, c.sample("tempus_edge", 9))
        refused("P6", E, smp, misbehaviour=c.oversize_frame_at("advert"))
        refused(42, E, c.shuffle("tempus_edge", [ident(128, "tempus_sentinel", 2000, dead).entry(0)]))
        # row 37
        # (node O is not a test node: its clock is the system's, ruling NQ-11, so the token for it ends far away)
        refused(43, E.with_token(tok(exp=4000000000)), tck, addr=o_addr)
        # P9, P10 (Python only), ruling NQ-11: node O reads the system clock. The trial's own tokens (valid 1000 to 3000
        # seconds after 1970, which test node N admits at its clock of 1500) have expired for it, and a token that
        # begins at 3900000000 is not valid yet; the reason is in O's output. Neither line holds a time of day.
        refused("P9", E, smp, addr=o_addr)
        refused("P10", E.with_token(tok(nbf=3900000000, exp=4000000000)), smp, addr=o_addr)
        # P7 (Python only), row 26: what the TLS link refuses, and a peer that connects and says nothing
        for name, how in (("TLS 1.2 only", c.tls12_only()), ("another ALPN", c.other_alpn()), ("no certificate", c.no_certificate()),
                          ("a P-256 certificate", c.p256_cert()), ("an RSA certificate", c.rsa_cert())):
            out = c.dial(n_addr, E, p.verifier, smp, timeout=4.0, **how)
            p.log.append(out.line())
            check(out.what in ("tls_failed", "closed") and out.stage in ("tls", "advert"), "row 26, %s: %s" % (name, out.line()))
            quiet()
        t0 = time.monotonic()
        with socket.create_connection(("127.0.0.1", base), timeout=3.0) as raw:
            raw.settimeout(8.0)
            try:
                data = raw.recv(16)
            except socket.timeout:
                data = None
        took = time.monotonic() - t0
        check(data == b"" and 1.0 < took < 6.0, "row 26: a connection that says nothing was not closed at the handshake bound (%.1f s, %r)" % (took, data))
        quiet()
        # P8 (Python only), row 20: inflight_max is 2: two connections stay silent before their advert, the third is closed
        held = [threading.Thread(target=c.dial, args=(n_addr, E, p.verifier, smp),
                                 kwargs={"misbehaviour": c.silent_at("advert", 1.6), "timeout": 4.0}) for _ in range(2)]
        for t in held:
            t.start()
            time.sleep(0.5)
        out = c.dial(n_addr, E, p.verifier, smp, timeout=3.0)
        check(out.what in ("closed", "tls_failed") and out.stage in ("tls", "advert"), "row 20: the connection beyond inflight_max was served: " + out.line())
        for t in held:
            t.join()
        quiet(1.0)
        step("P8", E, smp, kind="sample_reply")
        # row 16
        step(44, E, c.shuffle("tempus_edge", [b3("tempus_edge", 1, exp=1600)]), kind="shuffle_reply")
        step(45, E, c.clock(1700000), kind="done")
        p.clock[0] = 1700
        step(46, E, tck, kind="done")
        out = step(47, E, smp, kind="sample_reply")
        check(id8(b3("tempus_edge", 0)) not in " ".join(view(out)), "row 16: the expired entry is still sampled: " + out.line())
        # row 15: the client answers the node's advert with key_rotated; the node's application passes a new token
        old(48)
        le.verifier = k9
        step(49, E, tck, kind="done")
        n.wait(r"^own token replaced$")
        le.verifier = p.verifier
        quiet()
        old(50)
        before = len(seen_e)
        step(51, E, tck, kind="done")
        got = dialed(51, before, "row 15")
        mine = [e for e in got if id8(e) == n8]
        check(len(mine) == 1 and mine[0][0] == 0 and c.read_token(mine[0][1][A("token")])[0]["exp"] == 2500,
              "row 15: the node's entry does not carry the new token")
        step(52, E, c.clock(2600000), kind="done")
        step(53, E, tck, kind="done")
        p.clock[0] = 2600
        out = step(54, E, smp, want="refused")
        check("expired" in out.reason, "row 15: the client did not refuse the node's expired token: " + out.line())
        # P11 (Python only), ruling NQ-14: shuffle_timeout_ms (2000 here) is ONE bound from the accept to the close. The
        # client connects, waits a second before its TLS handshake, finishes it and then says nothing: the node closes
        # two seconds after the accept (stage advert), not two seconds after the handshake (three seconds, as it was
        # when each stage had the bound to itself).
        ctx = c._context(False, E, "1.3", c.ALPN, "own", ())
        t0 = time.monotonic()
        raw = socket.create_connection(("127.0.0.1", base), timeout=3.0)
        time.sleep(1.0)
        tls = ctx.wrap_socket(raw)
        shook = time.monotonic() - t0
        tls.settimeout(8.0)
        try:
            while tls.recv(4096):
                pass
            ended = "closed"
        except socket.timeout:
            ended = "still open"
        except OSError:
            ended = "closed"
        took = time.monotonic() - t0
        tls.close()
        check(ended == "closed" and shook < 1.8 and 1.7 < took < 2.75,
              "NQ-14: a connection silent after a late handshake was not closed at one bound from its accept "
              "(handshake done at %.2f s, %s at %.2f s; 2.0 s wanted, 3.0 s is one bound per stage)" % (shook, ended, took))
        quiet()
    print("[c2] the Python client's steps passed (%d requests)" % len(p.log))


def c3(leaf):
    """C3 (trials/c3_tempus_bridge): node T (TRUST), bridges B1 and B2, the Silica client (nodes/c, scenario c.role) and the
    Python client. Order: T, B1, B2; the Python client's first part (row 29: B1 learns B2 through a listening client with a
    bridge token); the Silica client's scenario; the Python client's second part (the same steps as c.role with its own
    identity, then what only it does: the rate bound, a second edge served while the first is at its bound, a bridge lost,
    and bridge B1 quarantined at T by the trial itself, design 17.7). C3_ONLY=python or C3_ONLY=silica walks one client."""
    A = c.Atom
    base = trial_ports.TABLE["c3_tempus_bridge"][0]
    t_dir, b1_dir, b2_dir, c_dir = (os.path.join(leaf, "nodes", n) for n in ("t", "b1", "b2", "c"))
    b1, b2, lp = ("127.0.0.1:%d" % (base + k) for k in (1, 2, 3))
    only = os.environ.get("C3_ONLY", "")
    p = Peer()

    def ident(first, typ, addr, certname=None):
        i = c.fixture_identity(first, typ, 1000, 3000, addr=addr)
        return c.Identity(i.seed, i.token, addr, cert_pem=cert(certname)) if certname else i

    P = ident(64, "tempus_edge", lp)          # the Python client's edge ("other")
    R = ident(128, "tempus_edge", lp)         # the edge of the rate bound ("sentinel"'s key with an edge token)
    H = ident(208, "tempus_edge", lp)         # the second edge, then the hostile one ("x3")
    N = ident(32, "tempus_edge", lp)          # the edge of the quarantine ("node")
    X4 = ident(224, "tempus_bridge", lp, "x4")
    B2E = ident(176, "tempus_bridge", b2).entry(0)
    seen = []

    def handler(rq):
        seen.append((rq.kind, str(rq.fields.get("store"))))
        if rq.kind == "shuffle":
            return c.shuffle_reply("tempus_bridge", [B2E])
        return c.CLOSE

    def call(rid, f, args, kind="call", m="demo"):
        return c.call_frame(rid, m, f, args, kind)

    def ask(who, addr, body, want="reply", kind=None, wait=0.7):
        out = p.ask(addr, who, body, want=want, kind=kind)
        quiet(wait)
        return out

    def result(who, addr, body, value):
        out = ask(who, addr, body, kind="result")
        check(c.result_value(out) == value, "a call to %s: wanted %r, got %s" % (addr, value, out.line()))
        return out

    def closed(who, addr, body, wait=0.7):
        return ask(who, addr, body, want="closed", wait=wait)

    nodes = {}
    try:
        t = nodes["t"] = Node(t_dir, "dangerous_t")
        t.wait(r"listening on 127\.0\.0\.1")
        n1 = nodes["b1"] = Node(b1_dir, "dangerous_b1")
        n1.wait(r"^join: no sentinel is configured$")
        n2 = nodes["b2"] = Node(b2_dir, "dangerous_b2")
        n2.wait(r"^join: no sentinel is configured$")
        with c.Listener(X4, p.verifier, handler, [cert("bridge")], port=base + 3, timeout=5.0):
            # ---- part 1, row 29: a client with a bridge token shuffles itself into B1's bridge store; a tick of that store
            # dials it (it is the only entry), and it answers with B2's entry; B1's bridge store then holds B2 alone
            ask(X4, b1, c.shuffle("tempus_bridge", [X4.entry(0)]), kind="shuffle_reply")
            ask(X4, b1, c.tick("tempus_bridge"), kind="done")
            check(seen == [("shuffle", "tempus_bridge")], "row 29: B1 did not dial the listening bridge client: %r" % seen)
            one = ask(P, b1, c.sample("tempus_bridge", 2), kind="sample_reply")
            check([e[1][A("addr")] for e in one.fields["entries"]] == [b2.encode()], "row 29: B1's bridge store: " + one.line())
        if only != "python":
            cl = nodes["c"] = Node(c_dir, "dangerous_c")
            cl.wait(r"^done$", timeout=180.0)
            quiet(1.0)
        if only == "silica":
            return 0
        # ---- part 2: the steps of c.role with the Python client's own identity
        smp = ask(P, b1, c.sample("tempus_bridge", 2), kind="sample_reply")              # 1 (row 30)
        entries = smp.fields["entries"]
        pick = entries[7 % len(entries)][1][A("addr")].decode()                           # the same draw as c.role's
        result(P, pick, call("p2", "add", [2, 3]), 5)                                     # 2
        result(P, b1, call("p3", "add", [2, 3]), 5)                                       # 3 (row 32)
        result(P, b2, call("p4", "add", [2, 3]), 5)                                       # 4
        result(P, b1, call("p5", "onward", [20, 22]), 42)                                 # 5 (rows 25, 31)
        result(P, b2, call("p6", "onward", [20, 22]), 42)                                 # 6
        closed(P, b1, call("p7", "note", [7], kind="cast"))                               # 7 (row 24: a cast)
        closed(P, b1, call("p8", "crash", [1]))                                           # 8 (no error body)
        result(P, b1, call("p9", "add", [2, 3]), 5)                                       # 9
        closed(P, b1, call("p10", "slow", [1]))                                           # 10 (the call timeout)
        result(P, b1, call("p11", "add", [2, 3]), 5)                                      # 11
        held = []

        def hold(rid, n):
            th = threading.Thread(target=lambda: held.append(c.dial(b1, P, p.verifier, call(rid, "hold", [n]), timeout=8.0)))
            th.start()
            n1.wait(r"bridge_admitted peer=\S+ call demo:hold/1")
            return th

        h1 = hold("p12", 1)                                                               # 12 (row 35)
        quiet()
        h2 = hold("p13", 2)                                                               # 13
        quiet()
        closed(P, b1, call("p14", "add", [2, 3]))                                         # 14: the in-flight bound
        result(H, b1, call("q14", "add", [2, 3]), 5)                                      # another edge is served meanwhile
        h1.join()
        h2.join()                                                                         # the bridge closes them at its call timeout
        check([o.what for o in held] == ["closed", "closed"], "row 35: the held calls: %s" % [o.line() for o in held])
        quiet()
        result(P, b1, call("p15", "release", []), 2)                                      # 15
        closed(P, b1, call("p16", "apply", [], m="erlang"))                               # 16 (rows 24, 34)
        closed(P, b1, call("p17", "secret", []))                                          # 17
        closed(P, b1, c.call_frame("p18", "demo", "add", [2, 3], arity=3))               # 18: arity 3, two arguments
        closed(P, b1, c.call_frame("p19", "demo", "add", [2, 3], arity=0))               # 19: the score passes the limit
        closed(P, b1, call("p20", "add", [2, 3]))                                         # 20: refused, the score
        # ---- the rate bound (row 35): 20 requests per hour for one peer; the 21st is refused, another peer is served
        for k in range(20):
            out = p.ask(b1, R, call("r%d" % k, "add", [k, 1]), kind="result")
            check(c.result_value(out) == k + 1, "row 35: request %d of the rate: %s" % (k + 1, out.line()))
        quiet()
        closed(R, b1, call("r20", "add", [2, 3]))
        result(H, b1, call("q21", "add", [2, 3]), 5)
        # ---- row 33: a bridge is lost
        n2.stop()
        del nodes["b2"]
        quiet()
        ask(H, b2, call("q22", "add", [2, 3]), want="unreachable")
        ask(H, b1, c.tick("tempus_bridge"), kind="done")
        gone = ask(H, b1, c.sample("tempus_bridge", 2), kind="sample_reply")
        check(gone.fields["entries"] == [], "row 33: B2 is still in B1's bridge store: " + gone.line())
        result(H, b1, call("q23", "add", [2, 3]), 5)
        # ---- design 17.7: B1 quarantined at T by the trial itself (its application's demo:bad calls a function T does not
        # permit for B1); edges then see closed and nothing else
        for k in range(3):
            closed(N, b1, call("n%d" % k, "bad", []))
        t.wait(r"quarantined")
        closed(N, b1, call("n3", "onward", [20, 22]))
        # ---- ruling NQ-19: what the connection actor refuses of an edge raises that edge's score at the bridge. Edge Q
        # never has a request answered or refused by the bridge itself: six refusals of its connections (a proof of
        # possession that does not verify, a frame that is no request, a frame above the ceiling, an expired token, a
        # token another key signed, silence where its challenge was due until the bound) take its score to 6, above the
        # limit of 5, and its first good request is then refused for its score.
        Q = ident(96, "tempus_edge", lp)
        prod = c.fixture_key(0)
        qtok = lambda signer=prod, exp=3000: c.make_token(signer, "k1", Q.pub, "tempus_edge", 1000, exp)  # noqa: E731
        good = call("s0", "add", [2, 3])
        p.ask(b1, Q, good, want="closed", misbehaviour=c.wrong_proof_bytes())
        quiet()
        p.ask(b1, Q, good, want="closed", misbehaviour=c.wrong_frame_at("request", c.etf_encode({A("t"): A("tempus_edge")})))
        quiet()
        p.ask(b1, Q, good, want="closed", misbehaviour=c.oversize_frame_at("request"))
        quiet()
        closed(Q.with_token(qtok(exp=1400)), b1, good)
        closed(Q.with_token(qtok(signer=c.fixture_key(96))), b1, good)
        p.ask(b1, Q, good, want="closed", misbehaviour=c.silent_at("challenge", 7.0), timeout=9.0)
        quiet()
        n1.wait(r"bridge_score peer=\S+ raised to 6 by timeout")
        closed(Q, b1, call("s1", "add", [2, 3]))
        n1.wait(r"bridge_refused peer=\S+ score 6 is above the limit 5")
        # an edge the bridge has never served and whose token the producer did not sign gets no entry (the table is
        # bounded by tokens the producer signed): Z is refused twice, then served with a score of 0
        Z = ident(112, "tempus_edge", lp)
        ztok = c.make_token(c.fixture_key(96), "k1", Z.pub, "tempus_edge", 1000, 3000)
        closed(Z.with_token(ztok), b1, good)
        closed(Z.with_token(c.make_token(prod, "k1", Z.pub, "tempus_edge", 1000, 1400)), b1, good)
        result(Z, b1, call("z0", "add", [2, 3]), 5)
        print("[c3] the Python client's steps passed (%d requests)" % len(p.log))
    finally:
        for n in list(nodes.values()):
            n.stop()
    return 0


def t6(leaf):
    """T6 (trials/t6_tempus_clock): what a node does with a clock that fails or goes back, on running nodes, and that a
    program built without the test unit refuses the test frames. Three programs, each in its own directory under nodes/:
    H and S are test programs (externally driven, with the test unit of src/tempus_test: a clock frame is a clock
    reading, judged by the node's configured choices); P is shaped like a production program. Every step waits for the
    node line that ends it. Two steps wait for a real time to pass (the join's retry of 3 s, and the later reading of a
    clock frame); nothing of the wall clock is printed."""
    base = trial_ports.TABLE["t6_tempus_clock"][0]
    h_addr, s_addr, p_addr, sent_addr, c_addr = ("127.0.0.1:%d" % (base + k) for k in (0, 1, 2, 3, 4))
    h_dir, s_dir, p_dir = (os.path.join(leaf, "nodes", n) for n in ("h", "s", "p"))
    E = c.fixture_identity(64, "tempus_edge", 1000, 3000, addr=c_addr)
    short = c.fixture_identity(64, "tempus_edge", 1000, 1480, addr=c_addr)       # ends at 1480
    far = c.fixture_identity(64, "tempus_edge", 1000, 4000000000, addr=c_addr)   # valid by the machine's clock
    i = c.fixture_identity(128, "tempus_sentinel", 1000, 3000, addr=sent_addr)
    SENT = c.Identity(i.seed, i.token, sent_addr, cert_pem=cert("sentinel"))
    smp, tck = c.sample("tempus_edge", 3), c.tick("tempus_edge")
    p = Peer()
    asked = []

    def sentinel(rq):
        asked.append((rq.kind, str(rq.fields.get("store"))))
        return c.sample_reply(rq.fields["store"], []) if rq.kind == "sample" else c.CLOSE

    def ask(addr, who, body, want="reply", kind=None, wait=0.7):
        out = p.ask(addr, who, body, want=want, kind=kind)
        quiet(wait)
        return out

    def shut(addr, who, body):
        """the node closes the connection at once, before any frame: the dial ends closed or with a failed handshake"""
        out = c.dial(addr, who, p.verifier, body, timeout=4.0)
        p.log.append(out.line())
        check(out.what in ("closed", "tls_failed"), "a connection to %s was not closed: %s" % (addr, out.line()))
        quiet()
        return out

    nodes = {}
    try:
        # ---- H: clock_back hold, clock_fail continue
        h = nodes["h"] = Node(h_dir, "dangerous_h")
        h.wait(r"^join: no sentinel is configured$")
        quiet()
        # H1. the clock goes back by 50 s: the node holds its time (1500)
        ask(h_addr, E, c.clock(1450000), kind="done")
        h.wait(r"the node holds its time")
        # H2. it goes on admitting by the held time: a token that ended at 1480 is refused (it has expired at 1500; by
        #     the clock's own 1450 it would be valid), a good one is served, and a tick is taken
        ask(h_addr, short, smp, want="closed")
        ask(h_addr, E, smp, kind="sample_reply")
        ask(h_addr, E, tck, kind="done")
        #     ... and what the test unit does not serve is refused as on a node without it: a frame of no kind, and
        #     a clock frame that breaks a bound (the reason is in H's output)
        ask(h_addr, E, c.etf_encode({c.Atom("t"): c.Atom("tempus_edge")}), want="closed")
        ask(h_addr, E, c.clock(5, 0, 6), want="closed")
        # H3. a reading that is still behind changes nothing and prints nothing
        ask(h_addr, E, c.clock(1460000), kind="done")
        ask(h_addr, short, smp, want="closed")
        # H4. the clock reaches the held time: the hold ends
        ask(h_addr, E, c.clock(1500000), kind="done")
        h.wait(r"has reached the held time")
        # H5. a reading fails: the node goes on with its last reading, admits and ticks
        ask(h_addr, E, c.clock(c.NO_TIME), kind="done")
        h.wait(r"goes on with its last reading$")
        h.wait(r"^application: told \(86\)")
        ask(h_addr, E, smp, kind="sample_reply")
        ask(h_addr, E, tck, kind="done")
        # H6. the next good reading is taken without a line; a second failure is told again
        ask(h_addr, E, c.clock(1510000), kind="done")
        ask(h_addr, E, c.clock(c.NO_TIME), kind="done")
        h.wait(r"goes on with its last reading$")
        quiet()
        nodes.pop("h").stop()

        # ---- S: clock_back stop with a limit of 60 s, clock_fail pause; its sentinel does not listen yet
        s = nodes["s"] = Node(s_dir, "dangerous_s")
        s.wait(r"^join: no sentinel answered for tempus_edge; waiting to try again$")
        # S1. the reading fails: the node waits for its clock. The frame also holds the reading that ends the wait, 7 s
        #     later (no frame can bring it: the waiting node closes every connection)
        ask(s_addr, E, c.clock(c.NO_TIME, 7000, 1500000), kind="done", wait=0.2)
        s.wait(r"admits no connection and does not tick until it is read again$")
        s.wait(r"^application: told \(86\)")
        # S2. an accepted connection is closed at once (audit line clock_refused)
        shut(s_addr, E, smp)
        s.wait(r"clock_refused")
        # S3. the join's retry falls due (3 s after the failed dial): it is not dialed, it waits for the clock
        s.wait(r"^join: the request for tempus_edge waits until the system clock is read again$")
        with c.Listener(SENT, p.verifier, sentinel, [cert("node")], port=base + 3, timeout=5.0):
            # S4. the clock is read again: one line, and the waiting request is dialed at once
            s.wait(r"^clock: the system clock is read again$")
            s.wait(r"^join: done$")
            quiet()
            check([k for k, _st in asked] == ["sample"] * 3, "the join after the wait did not ask the sentinel for the three stores: %r" % asked)
        ask(s_addr, E, smp, kind="sample_reply")
        # S5. a step back of 30 s, inside the limit: followed
        ask(s_addr, E, c.clock(1470000), kind="done")
        s.wait(r"went back by 30 s; the node follows it$")
        ask(s_addr, E, smp, kind="sample_reply")
        # S6. a step back of 100 s, above the limit: the node stops. The frame holds a later, good reading too.
        ask(s_addr, E, c.clock(1370000, 2500, 2000000), kind="done", wait=0.2)
        s.wait(r"the node has stopped")
        s.wait(r"^application: told \(87\)")
        # S7. an accepted connection is closed at once (audit line clock_stopped)
        shut(s_addr, E, smp)
        s.wait(r"clock_stopped")
        # S8. the later reading comes and changes nothing: the node stays stopped
        s.wait(r"^clock: 2000 s \(the later reading of a clock frame\)$")
        quiet()
        shut(s_addr, E, smp)
        s.wait(r"clock_stopped")
        quiet()
        nodes.pop("s").stop()

        # ---- P: built without the test unit; its clock is the machine's
        pn = nodes["p"] = Node(p_dir, "dangerous_p")
        pn.wait(r"^join: no sentinel is configured$")
        quiet()
        ask(p_addr, far, smp, kind="sample_reply")
        for body in (tck, c.clock(1700000), c.clock(c.NO_TIME, 1000, 1700000)):
            ask(p_addr, far, body, want="closed")
        ask(p_addr, far, smp, kind="sample_reply")
    finally:
        for n in list(nodes.values()):
            n.stop()
    print("[t6] the client's steps passed (%d requests)" % len(p.log))
    return 0


SCENARIOS = {"t3": t3, "c2": c2, "c3": c3, "t6": t6}


def main(argv):
    if len(argv) != 3 or argv[1] not in SCENARIOS:
        print(__doc__)
        return 2
    return SCENARIOS[argv[1]](os.path.abspath(argv[2]))


if __name__ == "__main__":
    sys.exit(main(sys.argv))
