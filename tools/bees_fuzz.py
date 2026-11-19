#!/usr/bin/env python3
"""F1: the BEES wire fuzzer's driver. It runs built node programs, plays generated hostile cases against them (as a hostile peer
dialing a node, as a hostile listener a node dials, as a hostile EPMD) and looks for crashes, hangs, memory growth and wrong
acceptances. Generation is tools/bees_fuzz_gen.py: seeded, deterministic, no clock. Standard library only; the same on macOS
and Linux. Spike: development-plan/spikes/F1-fuzzer.md.

    bees_fuzz.py run --seed N (--cases N|s=N,.. | --duration SEC) [--surfaces a,b,..] [--trial DIR] [--out DIR] [--slice N] [--start I]
                     [--smoke FILE]
    bees_fuzz.py replay --seed N --surface S --case I [--before K] [--repeat R] [--trial DIR]     replay one generated case on a fresh node
    bees_fuzz.py replay --file FINDING/case.json [--trial DIR]
    bees_fuzz.py show --seed N --surface S --case I [--bytes FILE]                    print a case; write the bytes it sends
    bees_fuzz.py prepare --from trials/f1_fuzz_wire --to trials/f2_fuzz_long --port-base 23600
                                                                                      copy the node sources with the ports rewritten

A run is identified by its seed and the number of cases per surface (surfaces are worked in slices of --slice cases, one node
program alive at a time, so indices are sequential per surface). --trial is the directory holding nodes/ (default
trials/f1_fuzz_wire); its port base is read from tools/trial_ports.py by the directory's name. The node programs must be built
first (make -C trials/f1_fuzz_wire build, or make -f fuzz.mk nodes in trials/f2_fuzz_long).

What is detected, per case:
  crash         the node process ended
  actor_failure the node printed an actor failure report that is not on the expected list (EXPECTED_REPORTS)
  no_redial     a dialing node with redial on stopped dialing after a failed EPMD lookup
  hang          after the case the node does not answer a known-good exchange (the probe) within its deadline
  wrong_accept  the node delivered a message, executed a request, issued a token or sent a result that the oracle model
                (bees_fuzz_gen) says no correct receiver may: an unauthenticated peer, a malformed or over-limit frame
  lost          a well-formed message of an authenticated peer was not delivered although nothing before it was wrong
  error_body    a TRUST server answered a refused request with a frame (the rule: no error body)
  memory        the node's resident set grew over a slice beyond the threshold (RSS sampled with ps)
  filter        (resolve) the address filter kept an address that may never be dialled, or differs from the model
Every finding is saved under OUT/findings/ with the case (JSON), the exact bytes sent (input.bin), the node's output around it and
a one-line replay command. Secrets: the only secret-like values are the trial's fixed test cookie and test tokens; tokens are
never written to the log.
"""
import argparse
import hashlib
import json
import os
import pty
import re
import select
import signal
import socket
import ssl
import struct
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import bees_fuzz_etf as E  # noqa: E402
import bees_fuzz_gen as G  # noqa: E402
import trial_ports  # noqa: E402

LIVE = ["beam_accept", "beam_dial", "epmd_register", "trust_plain", "trust_tls", "trust_client", "resolve"]
# actor failure reports that are this layer's design and no finding: the language's carrier ends with its link by failing
# itself (Silica 71009f96f8), which the node's reporter shows when the peer goes first
EXPECTED_REPORTS = [r"reason:\s+\(:explicit, :link_lost\)", r"reason:\s+\(:explicit, :link_unavailable\)"]
REPORT_RE = re.compile(r"=== Silica Actor Failure ===.*?(?:=== End Silica Actor Failure ===|\Z)", re.S)


def port_of(trial_dir, offset):
    name = os.path.basename(os.path.abspath(trial_dir))
    return trial_ports.base(name) + offset


class Node:
    """one node program under a pty, its output drained by a thread (a node blocks in println when nobody reads)"""
    live = set()                                     # the running ones, for the signal handler

    def __init__(self, trial_dir, name, log_path=None):
        self.dir = os.path.join(trial_dir, "nodes", name)
        self.exe = os.path.join(self.dir, "dangerous_" + name)
        if not os.path.isfile(self.exe):
            raise SystemExit(f"bees_fuzz: node program missing (build the trial first): {self.exe}")
        self.master, slave = pty.openpty()
        self.p = subprocess.Popen([self.exe], cwd=self.dir, stdin=subprocess.PIPE, stdout=slave, stderr=slave, close_fds=True)
        os.close(slave)
        Node.live.add(self)
        self.buf = bytearray()
        self.lock = threading.Lock()
        self.log = open(log_path, "wb") if log_path else None      # the last start only: a long run would fill the disk
        self.t = threading.Thread(target=self._pump, daemon=True)
        self.t.start()

    def _pump(self):
        while True:
            try:
                d = os.read(self.master, 65536)
            except OSError:
                d = b""
            if not d:
                return
            with self.lock:
                self.buf += d
            if self.log:
                self.log.write(d)
                self.log.flush()

    def mark(self):
        with self.lock:
            return len(self.buf)

    def since(self, pos):
        with self.lock:
            return bytes(self.buf[pos:]).decode("utf-8", "replace").replace("\r\n", "\n")

    def wait_for(self, text, timeout, pos=0):
        end = time.monotonic() + timeout
        while True:
            if text in self.since(pos):
                return True
            if time.monotonic() >= end or (self.p.poll() is not None and not self.t.is_alive()):
                return text in self.since(pos)
            time.sleep(0.004)

    def alive(self):
        return self.p.poll() is None

    def rss_kib(self):
        try:
            out = subprocess.run(["ps", "-o", "rss=", "-p", str(self.p.pid)], capture_output=True, text=True, timeout=5).stdout.strip()
            return int(out) if out else 0
        except (ValueError, subprocess.SubprocessError):
            return 0

    def stop(self, grace=3.0):
        """ask the program to end (its wait_for_exit reads "exit"); True when it ended by itself within grace"""
        clean = True
        if self.p.poll() is None:
            try:
                self.p.stdin.write(b"exit\n")
                self.p.stdin.flush()
            except OSError:
                pass
            try:
                self.p.wait(grace)
            except subprocess.TimeoutExpired:
                clean = False
                self.p.kill()
                self.p.wait()
        Node.live.discard(self)
        self.t.join(1.0)
        try:
            os.close(self.master)
        except OSError:
            pass
        if self.log:
            self.log.close()
            self.log = None
        return clean


def reports_in(text):
    """(unexpected, expected) actor failure reports in a piece of node output"""
    bad, ok = [], 0
    for m in REPORT_RE.finditer(text):
        if any(re.search(p, m.group(0)) for p in EXPECTED_REPORTS):
            ok += 1
        else:
            bad.append(m.group(0))
    return bad, ok


def recv_some(s, timeout):
    """bytes until the peer closes or `timeout` passes with nothing new: (data, closed)"""
    out = b""
    s.settimeout(timeout)
    try:
        while True:
            d = s.recv(65536)
            if not d:
                return out, True
            out += d
    except (socket.timeout, ssl.SSLError, OSError) as e:
        return out, not isinstance(e, socket.timeout)


def recv_exact(s, n, timeout):
    s.settimeout(timeout)
    out = b""
    try:
        while len(out) < n:
            d = s.recv(n - len(out))
            if not d:
                return None
            out += d
    except (OSError, ssl.SSLError):
        return None
    return out


def send_all(s, b, chunk=0):
    try:
        if chunk:
            for i in range(0, len(b), chunk):
                s.sendall(b[i:i + chunk])
        else:
            s.sendall(b)
        return True
    except (OSError, ssl.SSLError):
        return False


def dial(port, timeout=3.0):
    end = time.monotonic() + timeout
    while True:
        try:
            s = socket.create_connection(("127.0.0.1", port), timeout=1.0)
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            return s
        except OSError:
            if time.monotonic() >= end:
                return None
            time.sleep(0.02)


def close(s):
    if s is not None:
        try:
            s.close()
        except OSError:
            pass


def listen(port):
    ls = socket.socket()
    ls.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    ls.bind(("127.0.0.1", port))
    ls.listen(16)
    return ls


def accept(ls, timeout):
    r, _, _ = select.select([ls], [], [], timeout)
    if not r:
        return None
    c, _ = ls.accept()
    c.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    return c


class FakeEpmd:
    """the driver's EPMD: answers well unless a plan says otherwise (one plan is used by the next request of its kind)"""

    def __init__(self, port, peer_port):
        self.ls = listen(port)
        self.peer_port = peer_port
        self.plan = None
        self.held = []
        self.served = 0
        self.lock = threading.Lock()
        self.stopping = False
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while not self.stopping:
            c = accept(self.ls, 0.1)
            if c is None:
                continue
            head = recv_exact(c, 2, 2.0)
            body = recv_exact(c, struct.unpack(">H", head)[0], 2.0) if head else None
            with self.lock:
                plan, self.plan = self.plan, None
            hold = True
            if plan is None:
                if body and body[0] == 120:
                    send_all(c, bytes([118, 0, 0, 0, 0, 7]))
                elif body and body[0] == 122:
                    send_all(c, G.port2_resp(self.peer_port))
                    hold = False
            elif not plan.get("silent"):
                reply = bytearray(bytes.fromhex(plan.get("reply", "")))
                if plan.get("own_port") and len(reply) >= 4:
                    reply[2:4] = struct.pack(">H", self.peer_port)
                send_all(c, bytes(reply))
                hold = bool(plan.get("hold"))
            if hold:
                self.held.append(c)
            else:
                close(c)
            with self.lock:
                self.served += 1

    def set_plan(self, plan):
        with self.lock:
            self.plan = plan
            n = self.served
        return n

    def wait_served(self, n, timeout):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            with self.lock:
                if self.served > n:
                    return True
            time.sleep(0.004)
        return False

    def drop_held(self):
        for c in self.held:
            close(c)
        self.held = []

    def stop(self):
        self.stopping = True
        self.drop_held()
        time.sleep(0.15)
        close(self.ls)


class Finding(Exception):
    def __init__(self, kind, detail):
        super().__init__(kind + ": " + detail)
        self.kind, self.detail = kind, detail


# ---- BEAM mode: the handshake, both sides ----
MY_CHALLENGE = 0x1234ABCD


def r2(s, timeout):
    head = recv_exact(s, 2, timeout)
    return recv_exact(s, struct.unpack(">H", head)[0], timeout) if head else None


def hs_rest(s, mode="good", timeout=2.0):
    """the initiator's handshake after its name message; True when the node acknowledged with the right digest"""
    st = r2(s, timeout)
    if st != b"sok":
        return False
    ch = r2(s, timeout)
    if not ch or len(ch) < 13 or ch[0] != 78:
        return False
    theirs = struct.unpack(">I", ch[9:13])[0]
    good = b"r" + struct.pack(">I", MY_CHALLENGE) + G.digest(theirs)
    if mode == "no_reply":
        return False
    msg = {"good": good, "bad_digest": good[:-1] + bytes([good[-1] ^ 1]), "truncated_reply": good[:12], "wrong_tag": b"x" + good[1:],
           "long_reply": good + bytes(40), "zero_digest": good[:5] + bytes(16)}[mode]
    send_all(s, G.f2(msg))
    if mode != "good":
        return False
    a = r2(s, timeout)
    return a == b"a" + G.digest(MY_CHALLENGE)


def acceptor(s, mode, junk, timeout=2.0):
    """the acceptor's side against a dialing node; True when the node sent the right digest and got a right acknowledgement"""
    n = r2(s, timeout)
    if not n or n[0] != 78:
        return False
    rng = E.Rng("acc", junk.hex())
    status = {"status_nok": b"nok", "status_not_allowed": b"not_allowed", "status_alive": b"alive", "status_random": junk[:rng.between(0, 20)],
              "status_long": junk * 900, "status_named": b"named:" + junk[:8]}.get(mode, b"ok")
    send_all(s, G.f2(b"s" + status))
    ch = G.name_msg(G.PEER, challenge=MY_CHALLENGE)
    if mode == "challenge_mutated":
        ch = E.mutate(rng, ch)
    elif mode == "challenge_other_name":
        ch = G.name_msg("evil@localhost", challenge=MY_CHALLENGE)
    elif mode == "challenge_truncated":
        ch = ch[:rng.between(1, len(ch) - 1)]
    send_all(s, G.f2(ch))
    r = r2(s, timeout if mode == "good" else 0.5)
    if not r or len(r) != 21 or r[0] != 114:
        return False
    right = r[5:] == G.digest(MY_CHALLENGE)
    ack = b"a" + G.digest(struct.unpack(">I", r[1:5])[0])
    if mode == "ack_bad_digest":
        ack = b"a" + junk[:16]
    elif mode == "ack_wrong_tag":
        ack = b"b" + ack[1:]
    if mode != "ack_missing":
        send_all(s, G.f2(ack))
    return right and mode in ("good", "status_named", "status_random", "status_long", "status_alive", "challenge_mutated")


# ---- the runners ----
class Runner:
    surface = ""
    node_name = ""
    line_re = None

    def __init__(self, ctx):
        self.ctx = ctx
        self.node = None
        self.recent = []                 # (index, allowed set) of the last cases, for deliveries that arrive late
        self.scan_pos = 0
        self.expected_reports = 0
        self.rss = []

    def start_node(self):
        self.node = Node(self.ctx.trial, self.node_name, os.path.join(self.ctx.out, "node_%s.log" % self.node_name) if self.ctx.out else None)
        self.scan_pos = 0

    def stop_node(self):
        if self.node:
            self.node.stop()
            self.node = None

    def restart(self):
        self.teardown()
        self.setup()

    def allow(self, index, allowed):
        self.recent.append((index, set(allowed)))
        del self.recent[:-60]

    def scan(self, c):
        """the node's output since the last scan: unexpected failure reports, deliveries nobody may have caused"""
        with self.node.lock:
            raw = bytes(self.node.buf[self.scan_pos:])
        raw = raw[:raw.rfind(b"\n") + 1]              # whole lines only
        self.scan_pos += len(raw)
        text = raw.decode("utf-8", "replace").replace("\r\n", "\n")
        bad, ok = reports_in(text)
        self.expected_reports += ok
        if bad:
            raise Finding("actor_failure", "actor failure report: " + " | ".join(x.strip() for x in bad[0].splitlines() if "reason:" in x or "#0" in x))
        if self.line_re:
            for m in self.line_re.finditer(text):
                got = self.delivered(m)
                if not any(got in a for _, a in self.recent):
                    raise Finding("wrong_accept", "the node printed `%s`, which no case of the last %d may have caused" % (m.group(0), len(self.recent)))
        return text

    def check_alive(self):
        if not self.node.alive():
            raise Finding("crash", "the node process ended, exit status %s" % self.node.p.returncode)

    def sample_rss(self):
        k = self.node.rss_kib() if self.node and self.node.alive() else 0
        if k:
            self.rss.append(k)
        return k


class BeamRunner(Runner):
    """shared by beam_accept, beam_dial and epmd_register"""

    def delivered(self, m):
        return (m.group(1), int(m.group(2)))

    def allowed_of(self, c, post, authed):
        # "maybe": the handshake was damaged in a way a node may still accept (the node decides, not the driver's view of it)
        if c.get("auth") == "no" or (c.get("auth") == "yes" and not authed):
            return set(), None
        model = G.beam_model(post, c["target"])
        return {(op, n) for v, op, n in model["frames"] if v in ("valid", "maybe")}, model

    def check_lost(self, c, model, text):
        """valid frames before anything questionable must have been delivered (called once the same-link probe arrived)"""
        if model is None or c.get("auth") != "yes":
            return
        for v, op, n in model["frames"]:
            if v != "valid":
                return
            if "%s got op=%s n=%d\n" % (c["target"], op, n) not in text:
                raise Finding("lost", "a well-formed %s frame (op=%s n=%d) of the authenticated peer was not delivered" % (c["target"], op, n))


class BeamAccept(BeamRunner):
    surface, node_name = "beam_accept", "bl"
    line_re = re.compile(r"^inbox got op=(\S*) n=(-?\d+)$", re.M)

    def setup(self):
        self.port = port_of(self.ctx.trial, 0)
        self.epmd = FakeEpmd(port_of(self.ctx.trial, 2), port_of(self.ctx.trial, 1))
        self.start_node()
        if not self.node.wait_for("epmd: registered", 10):
            raise SystemExit("bees_fuzz: node bl did not register with the driver's EPMD:\n" + self.node.since(0))
        self.probe_n = 0
        self.fresh_probe(None)

    def teardown(self):
        self.stop_node()
        self.epmd.stop()

    def connect_good(self):
        s = dial(self.port)
        if s is None:
            return None
        send_all(s, G.f2(G.name_msg()))
        if hs_rest(s):
            return s
        close(s)
        return None

    def probe_frame(self):
        self.probe_n += 1
        n = 900000000 + self.probe_n
        self.allow(-1, {("probe", n)})
        return G.good_frame("inbox", "probe", n), "inbox got op=probe n=%d\n" % n

    def fresh_probe(self, c, deadline=8.0):
        end = time.monotonic() + deadline
        while time.monotonic() < end:
            self.check_alive()
            s = self.connect_good()
            if s is not None:
                frame, line = self.probe_frame()
                send_all(s, frame)
                ok = self.node.wait_for(line, 2.0, self.scan_pos)
                close(s)
                if ok:
                    return
            time.sleep(0.05)
        self.check_alive()
        raise Finding("hang", "the node did not complete a good handshake and deliver a good frame within %.0f s" % deadline)

    def run_case(self, c):
        s = dial(self.port)
        if s is None:
            self.check_alive()
            raise Finding("hang", "the node's listener does not accept a connection")
        authed, post = False, b""
        for st in c["steps"]:
            if st[0] == "hs":
                send_all(s, G.f2(G.name_msg()))
                authed = hs_rest(s, st[1])
            elif st[0] == "raw":
                send_all(s, bytes.fromhex(st[1]))
            elif st[0] == "hs_rest":
                authed = hs_rest(s, "good", 0.4)
            elif st[0] in ("post", "post_chunks"):
                b = bytes.fromhex(st[1])
                post += b
                send_all(s, b, st[2] if st[0] == "post_chunks" else 0)
        allowed, model = self.allowed_of(c, post, authed)
        self.allow(c["index"], allowed)
        if c.get("auth") == "yes" and not authed:
            close(s)
            self.check_alive()
            raise Finding("hang", "a good handshake was not completed by the node")
        same = False
        if authed and c.get("same_link_probe") and not (model and (model["violation"] or model["partial"])):
            frame, line = self.probe_frame()
            send_all(s, frame)
            same = self.node.wait_for(line, 1.5, self.scan_pos)
        close(s)
        if not same:
            self.fresh_probe(c)
        text = self.scan(c)
        if same:
            self.check_lost(c, model, text)
        return "kept" if same else "new"


class BeamDial(BeamRunner):
    surface, node_name = "beam_dial", "bd"
    line_re = re.compile(r"^outbox got op=(\S*) n=(-?\d+)$", re.M)

    def setup(self):
        self.ls = listen(port_of(self.ctx.trial, 1))
        self.epmd = FakeEpmd(port_of(self.ctx.trial, 2), port_of(self.ctx.trial, 1))
        self.probe_n = 0
        self.link = None
        self.start_node()
        self.fresh_probe(None, first=True)

    def teardown(self):
        close(self.link)
        self.stop_node()
        self.epmd.stop()
        close(self.ls)

    def drain_listener(self):
        while True:
            c = accept(self.ls, 0)
            if c is None:
                return
            close(c)

    def next_dial(self, plan, timeout):
        """drop the link and wait for the node's next EPMD request, answered by plan (None: well)"""
        close(self.link)
        self.link = None
        self.epmd.drop_held()
        n = self.epmd.set_plan(plan)
        return self.epmd.wait_served(n, timeout)

    def probe_frame(self):
        self.probe_n += 1
        n = 900000000 + self.probe_n
        self.allow(-1, {("probe", n)})
        return G.good_frame("outbox", "probe", n), "outbox got op=probe n=%d\n" % n

    def fresh_probe(self, c, deadline=12.0, first=False):
        end = time.monotonic() + deadline
        while time.monotonic() < end:
            self.check_alive()
            self.drain_listener()
            if not self.next_dial(None, 4.0):
                continue
            s = accept(self.ls, 3.0)
            if s is None:
                continue
            self.link = s
            if acceptor(s, "good", b""):
                frame, line = self.probe_frame()
                send_all(s, frame)
                if self.node.wait_for(line, 2.0, self.scan_pos):
                    return
        self.check_alive()
        raise Finding("hang", "the node did not dial, complete a good handshake and deliver a good frame within %.0f s" % deadline)

    def run_case(self, c):
        plan = c["epmd"] if isinstance(c["epmd"], dict) else None
        self.drain_listener()
        if not self.next_dial(plan, 6.0):
            self.check_alive()
            raise Finding("hang", "the node did not ask EPMD again within 6 s of losing its link")
        authed, post, model, same = False, b"", None, False
        if plan is not None:
            s = accept(self.ls, 0.4)                 # a damaged reply may still name the listener's port
            if s is not None:
                self.link = s
                authed = acceptor(s, "good", b"")
            self.allow(c["index"], set())
            if s is None:
                # the lookup failed: a node with redial on must ask again (after its back-off, at most redial_max_ms)
                n = self.epmd.set_plan(None)
                if not self.epmd.wait_served(n, 0.5 + (2.5 if plan.get("silent") or plan.get("hold") else 1.5)):
                    self.check_alive()
                    self.scan(c)
                    raise Finding("no_redial", "after this EPMD answer the dialing node (redial on) never asked EPMD again; its link stays down")
                s = accept(self.ls, 3.0)
                if s is not None:
                    self.link = s
                    if acceptor(s, "good", b""):
                        frame, line = self.probe_frame()
                        send_all(s, frame)
                        same = self.node.wait_for(line, 2.0, self.scan_pos)
        else:
            s = accept(self.ls, 3.0)
            if s is None:
                self.check_alive()
                raise Finding("hang", "the node was told its peer's port by EPMD and did not dial it within 3 s")
            self.link = s
            for st in c["steps"]:
                if st[0] == "acc":
                    authed = acceptor(s, st[1], bytes.fromhex(st[2]))
                elif st[0] == "post":
                    post = bytes.fromhex(st[1])
                    send_all(s, post)
            allowed, model = self.allowed_of(c, post, authed)
            self.allow(c["index"], allowed)
            if c.get("auth") == "yes" and not authed:
                raise Finding("hang", "a good handshake was not completed by the dialing node")
            if authed and c.get("same_link_probe") and not (model["violation"] or model["partial"]):
                frame, line = self.probe_frame()
                send_all(s, frame)
                same = self.node.wait_for(line, 1.5, self.scan_pos)
        if not same:
            self.fresh_probe(c)
        text = self.scan(c)
        if same:
            self.check_lost(c, model, text)
        return "kept" if same else "new"


class EpmdRegister(BeamAccept):
    surface = "epmd_register"

    def setup(self):
        self.port = port_of(self.ctx.trial, 0)
        self.epmd = FakeEpmd(port_of(self.ctx.trial, 2), port_of(self.ctx.trial, 1))
        self.probe_n = 0

    def teardown(self):
        self.stop_node()
        self.epmd.stop()

    def sample_rss(self):
        return 0

    def run_case(self, c):
        reply = bytes.fromhex(c["epmd"]["reply"])
        n = self.epmd.set_plan(c["epmd"])
        self.start_node()
        try:
            if not self.epmd.wait_served(n, 6.0):
                self.check_alive()
                raise Finding("hang", "the node did not send its EPMD registration within 6 s of its start")
            registered = (len(reply) >= 6 and reply[0] == 118 and reply[1] == 0) or (len(reply) >= 4 and reply[0] == 121 and reply[1] == 0)
            time.sleep(0.15)
            served = False
            if self.node.alive():
                s = self.connect_good()
                if s is not None:
                    frame, line = self.probe_frame()
                    send_all(s, frame)
                    served = self.node.wait_for(line, 2.0, 0)
                    close(s)
            if registered and not served:
                if not self.node.alive():
                    raise Finding("crash", "the node ended after a well-formed registration answer, exit status %s" % self.node.p.returncode)
                raise Finding("hang", "the node was registered by EPMD (a well-formed answer) and does not serve its listener")
            self.scan(c)
            rc = self.node.p.poll()
            if rc is not None and rc != 0:
                raise Finding("crash", "the node process ended with exit status %s" % rc)
            if not self.node.stop():
                self.node = None
                raise Finding("hang", "the node did not end within 3 s of being told to exit")
            self.node = None
            return "served" if served else "idle"
        finally:
            self.epmd.drop_held()
            self.stop_node()


class TrustRunner(Runner):
    line_re = re.compile(r"^\[demo\] note got (-?\d+)$", re.M)
    tls = False

    def delivered(self, m):
        return int(m.group(1))

    def setup(self):
        self.port = port_of(self.ctx.trial, 11 if self.tls else 10)
        self.token = None
        self.certs = os.path.join(ROOT, "trials", "n4_trust_tls" if self.tls else "n3_trust", "certs")
        self.start_node()
        if not self.node.wait_for("listening on 127.0.0.1", 10):
            raise SystemExit("bees_fuzz: the TRUST node did not start listening:\n" + self.node.since(0))
        self.probe(None)

    def teardown(self):
        self.stop_node()

    def identity_bytes(self, ident, c):
        if ident == "good":
            return hashlib.sha512(open(os.path.join(self.certs, "b.cert"), "rb").read()).digest()
        if ident == "none":
            return hashlib.sha512(open(os.path.join(self.certs, "n.cert"), "rb").read()).digest()
        if ident == "unlisted":
            return hashlib.sha512(b"f1 fuzz: a certificate no whitelist lists").digest()
        junk = E.Rng("identity", c["seed"], c["index"]).bytes(64)
        return junk if ident == "garbage" else junk[:10]

    def open(self, ident, c):
        """a connection with the peer identity established as far as the case says; None when it could not be"""
        s = dial(self.port)
        if s is None:
            return None
        if not self.tls:
            send_all(s, self.identity_bytes(ident, c))
            return s
        if ident == "raw":
            return s
        cert = {"good": "p", "none": "n"}.get(ident, "u")
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        ctx.minimum_version = ssl.TLSVersion.TLSv1_3
        ctx.set_alpn_protocols(["trust/1"])
        ctx.load_cert_chain(os.path.join(self.certs, cert + ".pem"), os.path.join(self.certs, cert + "-key.pem"))
        s.settimeout(3.0)
        try:
            return ctx.wrap_socket(s)
        except (OSError, ssl.SSLError):
            close(s)
            return None

    @staticmethod
    def frames_of(data):
        out, pos = [], 0
        while pos + 4 <= len(data):
            n = struct.unpack(">I", data[pos:pos + 4])[0]
            if pos + 4 + n > len(data):
                break
            out.append(data[pos + 4:pos + 4 + n])
            pos += 4 + n
        return out, data[pos:]

    @staticmethod
    def frame_map(body):
        try:
            v = E.read_term(body)
        except E.Bad:
            return None
        if not (isinstance(v, tuple) and v[0] == "map"):
            return None
        return {k[1]: x for k, x in v[1] if isinstance(k, tuple) and k[0] == "atom"}

    def probe(self, c, deadline=8.0):
        end = time.monotonic() + deadline
        while time.monotonic() < end:
            self.check_alive()
            s = self.open("good", {"seed": 0, "index": 0})
            if s is not None:
                send_all(s, G.f4(G.t_hello()) + G.f4(G.t_request("call", "demo", "add", [E.integer(40), E.integer(2)], b"probe")))
                data, _ = recv_some(s, 2.0)
                close(s)
                maps = [self.frame_map(f) for f in self.frames_of(data)[0]]
                tok = [m for m in maps if m and m.get("t") == ("atom", "token_issue")]
                res = [m for m in maps if m and m.get("t") == ("atom", "result")]
                if tok and isinstance(tok[0].get("token"), tuple):
                    self.token = tok[0]["token"][1]
                if res and res[0].get("value") == 42:
                    return
            time.sleep(0.05)
        self.check_alive()
        raise Finding("hang", "the server did not answer a permitted call of a whitelisted peer within %.0f s" % deadline)

    def run_case(self, c):
        ident = c["identity"]
        s = self.open(ident, c)
        sent, live = b"", False
        if s is not None:
            for st in c["steps"]:
                b = bytes.fromhex(st[1])
                if st[0] == "send_live":
                    live = self.token is not None
                    b = G.f4(G.t_token_present(self.token if live else bytes(48))) + b
                sent += b
                send_all(s, b, st[2] if st[0] == "send_chunks" else 0)
        model = G.trust_model(sent, live) if ident == "good" else {"may_execute": False, "request": None, "verdict": "invalid"}
        allowed = set()
        if model["may_execute"] and model["request"]["f"] == "note":
            allowed.add(model["request"]["args"][0])
        self.allow(c["index"], allowed)
        data = b""
        if s is not None:
            data, _ = recv_some(s, 1.5 if model["may_execute"] else 0.3)
            close(s)
        frames, rest = self.frames_of(data)
        for f in frames:
            m = self.frame_map(f)
            t = m.get("t") if m else None
            if t == ("atom", "token_issue"):
                if ident not in ("good", "none") or G.judge_first(self.frames_of(sent)[0][0] if self.frames_of(sent)[0] else b"") == "invalid":
                    raise Finding("wrong_accept", "a token was issued to a peer that is not permitted or whose first frame is malformed")
                if isinstance(m.get("token"), tuple) and not live:
                    self.token = m["token"][1]          # the server holds one token per identity: this one replaced the probe's
            elif t == ("atom", "result"):
                if not model["may_execute"]:
                    raise Finding("wrong_accept", "the server answered with a result frame a request the model calls impossible to admit")
            else:
                raise Finding("error_body", "the server sent a frame that is neither token_issue nor result (%d bytes)" % len(f))
        if rest and not self.tls:
            raise Finding("error_body", "the server sent %d bytes that are no whole frame" % len(rest))
        self.probe(c)
        self.scan(c)
        return "answered" if any((self.frame_map(f) or {}).get("t") == ("atom", "result") for f in frames) else "closed"


class TrustPlain(TrustRunner):
    surface, node_name = "trust_plain", "ts"


class TrustTls(TrustRunner):
    surface, node_name, tls = "trust_tls", "tt", True


class TrustClient(Runner):
    """node tc calls the driver, one call per connection, for ever; each connection is answered as a case says or well (the probe)"""
    surface, node_name = "trust_client", "tc"
    line_re = None

    def setup(self):
        self.ls = listen(port_of(self.ctx.trial, 3))
        self.start_node()
        self.served = None
        self.answer(None)

    def teardown(self):
        self.stop_node()
        close(self.ls)

    def answer(self, c):
        """take the client's next connection and answer it (c None: well). Returns (request number, outcome line)"""
        end = time.monotonic() + 8.0
        while True:
            self.check_alive()
            s = accept(self.ls, 0.5)
            if s is not None:
                break
            if time.monotonic() >= end:
                raise Finding("hang", "the client made no new call within 8 s of the outcome of its last one")
        # the stand-in identity, the token step and the request, pipelined by the client
        data, frames = b"", []
        end = time.monotonic() + 2.0
        while len(frames) < 2 and time.monotonic() < end:
            d, closed = recv_some(s, 0.02)
            data += d
            frames = TrustRunner.frames_of(data[64:])[0] if len(data) > 64 else []
            if closed:
                break
        first = TrustRunner.frame_map(frames[0]) if frames else None
        req = TrustRunner.frame_map(frames[1]) if len(frames) > 1 else None
        rid = req.get("req_id")[1] if req and isinstance(req.get("req_id"), tuple) else None
        if first is None or rid is None or not re.fullmatch(rb"r[1-9]\d{5}", rid):
            close(s)
            raise Finding("hang", "the client's connection did not carry its token step and a request with the id r<number>")
        n = int(rid[1:])
        hello = first.get("t") == ("atom", "hello")
        if c is None:
            reply, hold = G.good_reply(hello), False
        else:
            reply, hold = bytes.fromhex(c["reply_hello"] if hello else c["reply_token"]), c.get("hold")
        reply = reply.replace(G.RID, rid).replace(G.VAL, bytes([98]) + struct.pack(">i", n + 1))
        send_all(s, reply)
        if not hold:
            close(s)
        line = "call %d: " % n
        ok = self.node.wait_for(line, 3.0, self.scan_pos)
        close(s)
        text = self.node.since(self.scan_pos)
        out = text[text.find(line):].split("\n")[0] if ok else None
        may, value = G.reply_model(reply, hello, rid)
        if out is None:
            self.check_alive()
            raise Finding("hang", "the client printed no outcome for call %d within 3 s (its caller is answered once, always)" % n)
        if "{ok" in out and not may:
            raise Finding("wrong_accept", "the client reported `%s` for an answer no correct client may accept" % out)
        if "{ok, int " in out and value is not None and out != line + "{ok, int %d}" % value:
            raise Finding("wrong_accept", "the client reported `%s`, the result frame's value is %d" % (out, value))
        if c is None and out != line + "{ok, int %d}" % (n + 1):
            return None
        return out

    def run_case(self, c):
        self.answer(c)
        for _ in range(4):                           # the probe: a good answer must give {ok, n + 1}
            if self.answer(None) is not None:
                self.scan(c)
                return "answered"
        raise Finding("hang", "the client did not report {ok, ..} for four good answers in a row")


class Resolve(Runner):
    """resolver answers through the one filter: a batch of generated answers is compiled into one program (Silica reads no file
    and takes no input), run once, and each printed line is compared with the model"""
    surface = "resolve"
    batch = 60

    def setup(self):
        self.leaf = os.path.join(self.ctx.trial, "resolve")
        self.cache = {}

    def teardown(self):
        pass

    def sample_rss(self):
        return 0

    @staticmethod
    def lit(s):
        return '"' + s + '"'

    def build(self, first):
        cases = [G.case(self.ctx.seed, "resolve", i) for i in range(first, first + self.batch)]
        lines = ["// Generated by tools/bees_fuzz.py (seed %d, resolve cases %d..%d). Do not edit." % (self.ctx.seed, first, first + self.batch - 1),
                 "use bees_addr;", "module fz_resolve;", "fn region_dump_limit() -> int64 { 0 }",
                 'fn b2s(b: boolean) -> string { case b of { true -> "true"; false -> "false" } }',
                 "fn kept_of(text: string, lo: boolean) -> string {",
                 '    case bees_addr@ans_ok(text) of { true -> bees_addr@usable(bees_addr@ans_csv(text), lo).kept; false -> "" }', "}",
                 "fn show(i: string, text: string, lo: boolean) -> atom {", "    sequence proc[device_io]",
                 '        a: string <- concat(concat("v ", i), concat(" ok=", b2s(bees_addr@ans_ok(text))));',
                 '        b: string <- concat(concat(" kept=[", kept_of(text, lo)), concat("] reason=[", concat(bees_addr@ans_reason(text), "]")));',
                 "        _: atom <- println(concat(a, b))", "    produces pure :ok end", "}"]
        parts = []
        for p in range(0, self.batch, 15):
            parts.append("part%d" % p)
            lines += ["fn part%d() -> atom {" % p, "    sequence"]
            chunk = cases[p:p + 15]
            for j, c in enumerate(chunk):
                lines.append("        _: atom <- show(%s, %s, %s)%s" % (self.lit(str(c["index"])), self.lit(c["answer"]), "true" if c["loopback_only"] else "false", ";" if j < len(chunk) - 1 else ""))
            lines += ["    produces pure :ok end", "}"]
        lines += ["fn main() -> int64 {", "    sequence"]
        lines += ["        _: atom <- %s()%s" % (p, ";" if i < len(parts) - 1 else "") for i, p in enumerate(parts)]
        lines += ["    produces pure 0 end", "}"]
        with open(os.path.join(self.leaf, "fz_resolve.silica"), "w") as f:
            f.write("\n".join(lines) + "\n")
        cmd = ["make", "-C", self.leaf, "build"] + (["SILICA_COMPILER=" + self.ctx.compiler] if self.ctx.compiler else [])
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0 or not os.path.isfile(os.path.join(self.leaf, "fz_resolve")):
            raise SystemExit("bees_fuzz: the resolve batch did not build (cases %d..):\n%s" % (first, (r.stdout + r.stderr)[-3000:]))
        try:
            r = subprocess.run([os.path.join(self.leaf, "fz_resolve")], capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
            out, rc = r.stdout + r.stderr, r.returncode
        except subprocess.TimeoutExpired as e:
            out, rc = (e.stdout or b"").decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or ""), "timeout"
        self.cache = {"rc": rc, "out": out}
        for m in re.finditer(r"^v (\d+) ok=(true|false) kept=\[(.*)\] reason=\[(.*)\]$", out, re.M):
            self.cache[int(m.group(1))] = (m.group(2) == "true", m.group(3), m.group(4))

    def run_case(self, c):
        i = c["index"]
        if i not in self.cache:
            self.build(i - i % self.batch)
        if i not in self.cache:
            bad, _ = reports_in(self.cache["out"])
            kind = "hang" if self.cache["rc"] == "timeout" else "crash"
            raise Finding(kind, "the filter program printed no line for this answer (exit status %s)%s" % (self.cache["rc"], "; an actor failure report" if bad else ""))
        ok, kept, reason = self.cache[i]
        ans = c["answer"]
        if ok != ans.startswith("ok "):
            raise Finding("filter", "ans_ok is %s for the answer text" % ok)
        parts = [q for q in kept.split(",") if q] if kept else []
        if kept and "" in kept.split(","):
            raise Finding("filter", "an empty address in the kept list [%s]" % kept)
        for q in parts:
            if G.never_usable(q):
                raise Finding("filter", "the filter kept `%s`, which may never be dialled" % q)
            if c["loopback_only"] and not q.startswith("127."):
                raise Finding("filter", "the filter kept `%s` under a loopback-only setting" % q)
        if len(set(parts)) != len(parts):
            raise Finding("filter", "the filter kept an address twice: [%s]" % kept)
        m = G.resolve_model(ans, c["loopback_only"])
        if m[0] == "ok":
            want = [q for q in m[1]]
            if parts != want:
                raise Finding("filter", "kept [%s], the model says [%s]" % (kept, ",".join(want)))
        elif m[0] == "err" and m[1] == "no_usable_address" and parts:
            raise Finding("filter", "kept [%s], the model says nothing is usable" % kept)
        if not ok and reason not in ("nxdomain", "no_address", "temporary", "bad_name", "failed"):
            raise Finding("filter", "ans_reason gave `%s`, not one of the five reasons" % reason)
        return "checked"


RUNNERS = {"beam_accept": BeamAccept, "beam_dial": BeamDial, "epmd_register": EpmdRegister, "trust_plain": TrustPlain, "trust_tls": TrustTls, "trust_client": TrustClient, "resolve": Resolve}
WEIGHT = {"beam_accept": 4, "beam_dial": 2, "epmd_register": 1, "trust_plain": 4, "trust_tls": 3, "trust_client": 2, "resolve": 1}      # slice sizes, relative
RSS_FACTOR, RSS_SLACK_KIB = 3.0, 65536


class Ctx:
    def __init__(self, a):
        self.seed = a.seed
        self.trial = os.path.abspath(a.trial)
        self.out = os.path.abspath(a.out) if getattr(a, "out", None) else None
        self.compiler = os.environ.get("SILICA_COMPILER", "")
        self.findings = {}
        self.saved = {}
        if self.out:
            os.makedirs(os.path.join(self.out, "findings"), exist_ok=True)

    def replay_cmd(self, c, before=0):
        rel = os.path.relpath(self.trial, ROOT)
        return "python3 tools/bees_fuzz.py replay --seed %d --surface %s --case %d%s --trial %s" % (c["seed"], c["surface"], c["index"], " --before %d" % before if before else "", rel)

    def record(self, c, f, node_text, slice_first):
        sig = "%s %s %s" % (c["surface"], f.kind, "/".join(c["kind"].split("/")[:2]))
        self.findings[sig] = self.findings.get(sig, 0) + 1
        line = "FINDING %s case %d %s (%s): %s" % (c["surface"], c["index"], c["kind"], f.kind, f.detail)
        if not self.out or self.findings[sig] > 5:
            return line
        d = os.path.join(self.out, "findings", "%s-%06d-%s" % (c["surface"], c["index"], f.kind))
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "case.json"), "w") as fh:
            json.dump(c, fh, indent=1, sort_keys=True)
        with open(os.path.join(d, "input.bin"), "wb") as fh:
            fh.write(G.case_bytes(c))
        with open(os.path.join(d, "node_output.txt"), "w") as fh:
            fh.write(node_text[-20000:])
        with open(os.path.join(d, "repro.txt"), "w") as fh:
            fh.write(line + "\n\nreplay this case alone on a fresh node:\n  " + self.replay_cmd(c) + "\nwith the cases of its slice before it (when the case alone does not show it):\n  "
                     + self.replay_cmd(c, c["index"] - slice_first) + "\n")
        return line


def run_slice(ctx, surface, first, count, say, deadline=None):
    """cases first..first+count-1 of one surface on one node; returns (cases run, findings)"""
    r = RUNNERS[surface](ctx)
    r.setup()
    done, found = 0, 0
    try:
        r.sample_rss()
        for i in range(first, first + count):
            if deadline is not None and time.monotonic() >= deadline:
                break
            c = G.case(ctx.seed, surface, i)
            try:
                res = r.run_case(c)
                say("case %s %06d %s id=%s ok" % (surface, i, c["kind"], G.case_id(c)), res)
            except Finding as f:
                found += 1
                text = r.node.since(max(0, r.node.mark() - 30000)) if r.node else r.__dict__.get("cache", {}).get("out", "")
                say(ctx.record(c, f, text, first), None)
                r.restart()
            done += 1
            if done % 50 == 0:
                r.sample_rss()
        k = r.sample_rss()
        if len(r.rss) >= 2 and k > r.rss[0] * RSS_FACTOR + RSS_SLACK_KIB:
            found += 1
            c = G.case(ctx.seed, surface, first)
            say(ctx.record(c, Finding("memory", "resident set %d KiB at the slice's start, %d KiB after %d cases (samples: %s)" % (r.rss[0], k, done, r.rss)), "", first), None)
    finally:
        rss = list(r.rss)
        try:
            r.teardown()
        except Exception:
            pass
    return done, found, rss


def cmd_run(a):
    ctx = Ctx(a)
    surfaces = [s for s in (a.surfaces.split(",") if a.surfaces else LIVE)]
    for s in surfaces:
        if s not in RUNNERS:
            raise SystemExit("bees_fuzz: %s" % (G.TEMPUS_REASON if s == "tempus" else "no such surface: " + s))
    smoke = open(a.smoke, "w") if a.smoke else None
    t0 = time.monotonic()
    totals = {s: 0 for s in surfaces}
    rss_all = {s: [] for s in surfaces}
    found = 0

    def say(line, res):
        if smoke:
            smoke.write(line + "\n")
            smoke.flush()
        if res is None or a.verbose:
            print(line if res is None else line + " (" + res + ")", flush=True)

    def write_summary(finished):
        """summary.json, rewritten after every slice so that a run that is stopped still leaves its figures"""
        elapsed = time.monotonic() - t0
        total = sum(totals.values())
        summary = {"seed": a.seed, "start_index": a.start, "cases": totals, "next_index": nxt, "findings": found, "finding_signatures": ctx.findings, "finished": finished,
                   "seconds": round(elapsed, 1), "cases_per_second": round(total / elapsed, 2) if elapsed else 0, "rss_kib_first_last_per_slice": rss_all,
                   "compiler": ctx.compiler or "(not given: the node programs were built before this run)", "platform": sys.platform, "trial": os.path.relpath(ctx.trial, ROOT)}
        if ctx.out:
            with open(os.path.join(ctx.out, "summary.json.tmp"), "w") as fh:
                json.dump(summary, fh, indent=1, sort_keys=True)
            os.replace(os.path.join(ctx.out, "summary.json.tmp"), os.path.join(ctx.out, "summary.json"))
        return summary

    deadline = t0 + a.duration if a.duration else None
    nxt = {s: a.start for s in surfaces}
    left = None
    if a.cases:                                      # N for every surface, or surface=N,surface=N
        per = dict(x.split("=") for x in a.cases.split(",")) if "=" in a.cases else {s: a.cases for s in surfaces}
        surfaces = [s for s in surfaces if s in per]
        left = {s: int(per[s]) for s in surfaces}
    rounds = 0
    while True:
        progressed = False
        for s in surfaces:
            if deadline is not None and time.monotonic() >= deadline:
                break
            if left:                                 # a resolve batch is one compile, and a smoke report is one slice per surface
                n = left[s] if (smoke or s == "resolve") else min(left[s], a.slice * WEIGHT[s])
            else:
                n = Resolve.batch if s == "resolve" else a.slice * WEIGHT[s]
            if n <= 0:
                continue
            done, f, rss = run_slice(ctx, s, nxt[s], n, say, deadline)
            nxt[s] += done
            totals[s] += done
            rss_all[s] += rss[:1] + rss[-1:]
            found += f
            if left:
                left[s] -= done
            progressed = progressed or done > 0
            write_summary(False)
            if not smoke:
                print("progress %s: %d cases so far (next index %d), %d findings in all, %.0f s" % (s, totals[s], nxt[s], found, time.monotonic() - t0), flush=True)
        rounds += 1
        if not progressed or (deadline is not None and time.monotonic() >= deadline) or (left and all(v <= 0 for v in left.values())):
            break
    summary = write_summary(True)
    if smoke:
        smoke.write("cases %d findings %d\n" % (sum(totals.values()), found))
        smoke.close()
    else:
        print("summary " + json.dumps(summary, sort_keys=True), flush=True)
    return 1 if found else 0


def cmd_replay(a):
    if a.file:
        c = json.load(open(a.file))
        a.seed, a.surface, a.case = c["seed"], c["surface"], c["index"]
        regenerated = G.case(a.seed, a.surface, a.case)
        if regenerated != c:
            print("note: the generator now gives a different case for this seed and index; replaying the file's bytes")
    else:
        c = G.case(a.seed, a.surface, a.case)
    ctx = Ctx(a)
    r = RUNNERS[a.surface](ctx)
    r.setup()
    rc = 0
    try:
        todo = [G.case(a.seed, a.surface, i) for i in range(max(0, a.case - a.before), a.case)] + [c] * max(1, a.repeat)
        for x in todo:
            try:
                res = r.run_case(x)
                print("case %s %06d %s id=%s ok (%s)" % (a.surface, x["index"], x["kind"], G.case_id(x), res))
            except Finding as f:
                rc += 1
                print("FINDING %s case %d %s (%s): %s" % (a.surface, x["index"], x["kind"], f.kind, f.detail))
                if r.node:
                    print("---- node output (tail) ----\n" + r.node.since(max(0, r.node.mark() - 6000)))
                r.restart()
    finally:
        r.teardown()
    if len(todo) > 1:
        print("%d of %d cases played gave a finding" % (rc, len(todo)))
    return 1 if rc else 0


def cmd_show(a):
    c = G.case(a.seed, a.surface, a.case)
    print(json.dumps(c, indent=1, sort_keys=True))
    print("id " + G.case_id(c))
    if a.bytes:
        with open(a.bytes, "wb") as fh:
            fh.write(G.case_bytes(c))
    return 0


SOURCE_NAMES = ("Makefile", "bees.config", "node.wire", "node.atoms", "node.beam", "demo.trust", "none.trust", "trust_whitelist.config", "trust_servers.config")


def cmd_prepare(a):
    """copy nodes/ and resolve/ of one fuzz trial directory into another (same depth under trials/), sources and links only, with
    the ports of the source's block rewritten into the destination's"""
    src, dst = os.path.abspath(a.src), os.path.abspath(a.to)
    old = trial_ports.base(os.path.basename(src))
    new = a.port_base
    for sub in ("nodes", "resolve"):
        for d, dirs, files in os.walk(os.path.join(src, sub)):
            rel = os.path.relpath(d, src)
            os.makedirs(os.path.join(dst, rel), exist_ok=True)
            for n in dirs + files:
                p, q = os.path.join(d, n), os.path.join(dst, rel, n)
                if os.path.islink(p):
                    if os.path.lexists(q):
                        os.remove(q)
                    os.symlink(os.readlink(p), q)
                elif os.path.isfile(p) and n in SOURCE_NAMES:
                    text = open(p).read()
                    text = re.sub(r"\b%d(\d\d)\b" % (old // 100), lambda m: "%d%s" % (new // 100, m.group(1)), text)
                    text = text.replace("trials/%s/nodes" % os.path.basename(src), "trials/%s/nodes" % os.path.basename(dst))
                    if not os.path.isfile(q) or open(q).read() != text:
                        with open(q, "w") as fh:
                            fh.write(text)
            dirs[:] = [x for x in dirs if not os.path.islink(os.path.join(d, x))]
    print("prepared %s from %s (ports %d.. -> %d..)" % (os.path.relpath(dst, ROOT), os.path.relpath(src, ROOT), old, new))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    default_trial = os.path.join(ROOT, "trials", "f1_fuzz_wire")
    p = sub.add_parser("run")
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--cases", default="", help="cases per surface: N, or surface=N,surface=N")
    p.add_argument("--duration", type=float, default=0, help="seconds")
    p.add_argument("--surfaces", default="")
    p.add_argument("--trial", default=default_trial)
    p.add_argument("--out", default="")
    p.add_argument("--slice", type=int, default=250, help="cases per slice for a surface of weight 1")
    p.add_argument("--start", type=int, default=0, help="first case index of every surface")
    p.add_argument("--smoke", default="", help="write the deterministic per-case report to this file")
    p.add_argument("--verbose", action="store_true")
    p = sub.add_parser("replay")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--surface", default="")
    p.add_argument("--case", type=int, default=0)
    p.add_argument("--before", type=int, default=0, help="also play this many cases before it")
    p.add_argument("--repeat", type=int, default=1, help="play the case this many times (a finding that depends on timing)")
    p.add_argument("--file", default="")
    p.add_argument("--trial", default=default_trial)
    p = sub.add_parser("show")
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--surface", required=True)
    p.add_argument("--case", type=int, required=True)
    p.add_argument("--bytes", default="")
    p = sub.add_parser("prepare")
    p.add_argument("--from", dest="src", required=True)
    p.add_argument("--to", required=True)
    p.add_argument("--port-base", type=int, required=True)
    a = ap.parse_args()

    def stop(_sig, _frame):                          # SIGTERM: end the node programs (one left without its pty spins), then end
        for n in list(Node.live):
            try:
                n.p.kill()
            except OSError:
                pass
        sys.stdout.write("bees_fuzz: stopped (the node programs were ended; summary.json holds the figures up to the last slice)\n")
        sys.stdout.flush()
        os._exit(130)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    if a.cmd == "run" and not (a.cases or a.duration):
        ap.error("run needs --cases or --duration")
    return {"run": cmd_run, "replay": cmd_replay, "show": cmd_show, "prepare": cmd_prepare}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
