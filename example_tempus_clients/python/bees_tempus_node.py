"""The Python TEMPUS extension: a TEMPUS node (development-plan/tempus-design.md sections 3 to 6 and 8 to 11).

An application that imports this module can be a member of a TEMPUS network: an edge, or a sentinel. It cannot be a
bridge: a bridge is also a member of a TRUST network, and this extension has no TRUST.

    import bees_tempus_config, bees_tempus_node
    config = bees_tempus_config.node_config({...})          # the keys of the tempus section; no defaults
    node = bees_tempus_node.Node(config, token=token_bytes, address="192.0.2.7:7400", on_event=told)
    node.start()
    ...
    node.set_token(new_token_bytes)                         # at half of the token's lifetime
    node.stop()

What the node does is what the BEES TEMPUS node does (src/tempus/bees_tempus_node.part, the Silica library), and this
file is written after it, decision for decision: it reads its clock, listens when the first reading has come, joins
through its sentinels with one sample request per store, ticks each store on its own timer and shuffles with the
oldest entry, answers the shuffles and samples of admitted peers from its stores, and tells its application what the
Silica node tells its application. Its lines (the node's own and the audit lines) have the Silica node's wording, so
that an operator can compare the two.

Threads. One thread, the node's, owns all of the node's state and runs every decision; nothing else touches the
stores. Each connection has a thread of its own for its blocking reads and writes, and tells the node thread what
happened. The application's on_event function and the `log` function are called on the node's thread or on a
connection's thread and must not block.

A test can step a node by hand, because the three things a node takes from the machine are given at construction:
`clock` (read() answers the whole seconds since 1970 UTC, or None when the clock cannot be read), `timers`
(call_later(ms, function, name) runs the function once, later) and `random` (bytes(n) and draws(store, purpose, n)).
An application passes none of the three: the node then reads the machine's clock itself, runs its own timers and
takes its random bytes from the operating system. There is no frame and no message by which a peer could set a node's
time or cause a tick: a tick or clock frame is to this node a frame of no kind, refused like any other.
"""
import os
import queue
import socket
import sys
import threading
import time

from bees_tempus_admission import Verifier, token_rules
from bees_tempus_codec import (Atom, ENTRIES_MAX, Refused, TYPES, frame, kind_of, read_body, read_token, sample,
                               sample_reply, shuffle, shuffle_reply, structure_reason)
from bees_tempus_peer import ROTATED_TEXT, Ended, Identity, TlsRefused, Wire, admit, read_frame, tls_available, tls_open
from bees_tempus_store import Store

# the node's clock states (bees_tempus_node@clock_turn)
NO_READING, GOOD, PAUSED, NO_READING_TOLD, STOPPED, HOLDING, GOING_ON = 0, 1, 2, 3, 4, 5, 6
_BACK = {"follow": 1, "hold": 2, "stop": 3}


# ---------------------------------------------------------------- the clock's decisions (pure; design section 10)
def clock_back(last, n, back, limit):
    """One good reading n (seconds since 1970) after the node's time `last`: (the node's time after it, what
    happened): 0 the reading is not earlier; 1 earlier, followed; 2 earlier, held; 3 earlier by more than the limit:
    the node's time stays and the node stops. back is "follow", "hold" or "stop"; limit is read under "stop" only."""
    if n >= last:
        return n, 0
    if back == "hold":
        return last, 2
    if back == "stop" and last - n > limit:
        return last, 3
    return n, 1


def clock_turn(state, last, n, back, limit, fail):
    """One reading of the clock, n the seconds or None when there was none. Returns (now, state, say, again): the
    node's time and state after it; `again`, whether the clock is read again after a pause (one line, before what
    `say` names); and say, what the node does:
      0 nothing                          1 the first reading: one line, the node listens
      2 no time at start: one line, the application told; the node has not started
      3 no time after a good reading, pause: one line, the application told
      4 no time after a good reading, continue: one line, the application told
      6 a step back, followed: one line  7 a step back, held from now on: one line
      8 the clock has reached the held time: one line
      9 a step back above the limit: one line, the application told, the node stops for good"""
    if state == STOPPED:
        return last, STOPPED, 0, False
    if n is None or n < 0:
        if state == NO_READING:
            return last, NO_READING_TOLD, 2, False
        if state in (GOOD, HOLDING):
            return (last, GOING_ON, 4, False) if fail == "continue" else (last, PAUSED, 3, False)
        return last, state, 0, False
    if state in (NO_READING, NO_READING_TOLD):
        return n, GOOD, 1, False
    now, act = clock_back(last, n, back, limit)
    again = state == PAUSED
    if act == 0:
        return now, GOOD, 8 if state == HOLDING else 0, again
    if act == 1:
        return now, GOOD, 6, again
    if act == 2:
        return now, HOLDING, 0 if state == HOLDING else 7, again
    return now, STOPPED, 9, again


def clock_ticks(state):
    """a node ticks with a good last reading, while it holds its time, and while it goes on with its last reading"""
    return state in (GOOD, HOLDING, GOING_ON)


def clock_closes(state):
    """the audit event with which an accepted connection is closed at once in this state, or "" """
    return {PAUSED: "clock_refused", STOPPED: "clock_stopped"}.get(state, "")


# ---------------------------------------------------------------- what the node takes from the machine
class SystemClock:
    """The machine's clock: whole seconds since 1970 UTC, or None when the operating system gives no time or a time
    before 1970. Never a made-up time."""

    def read(self):
        try:
            now = time.time()
        except (OSError, OverflowError, ValueError):
            return None
        return int(now) if now >= 0 else None


class ThreadTimers:
    """Timers of the machine: call_later(ms, function, name) runs the function once, ms milliseconds later, on a
    thread of its own; the answer has cancel(). The name says what the timer is for and is not used here."""

    def call_later(self, ms, function, name):
        t = threading.Timer(ms / 1000.0, function)
        t.daemon = True
        t.start()
        return t


class SecureRandom:
    """The operating system's secure random source. bytes(n) answers n random bytes, or None when the source
    refuses. draws(store, purpose, n) answers n draws for a store's choices (purpose "tick" or "reply"), each a
    non-negative integer made of seven random bytes, so that the bias of a draw modulo at most 256 candidates is below
    2^-47 (design 3.5); None when the source refuses."""

    def bytes(self, n):
        try:
            return os.urandom(n)
        except (OSError, NotImplementedError):
            return None

    def draws(self, store, purpose, n):
        raw = self.bytes(7 * n)
        if raw is None or len(raw) != 7 * n:
            return None
        return [int.from_bytes(raw[7 * k:7 * k + 7], "big") for k in range(n)]


# ---------------------------------------------------------------- what the application is told
class Event:
    """One thing the node tells its application: a name and its values.

      token_invalid     why: the node's own token is not valid any more by the node's own admission rules (so no peer
                        would admit the node), and ticking has stopped until set_token() gives a new one
      key_rotated       kid, dialed: a peer answered the node's advert with key_rotated and named this kid; dialed
                        says whether the node had dialed that peer. The application fetches a new token.
      clock_unreadable  text: the clock could not be read; the text says what that means for the node. Told once per
                        failure, not once per reading.
      stopped           text: the clock went back by more than clock_back_limit_s under clock_back "stop". The node
                        does not tick, closes every accepted connection at once, and stays so whatever is read later.
                        Only a new node, started by the application, ends it.
      listen_failed     text: the node could not open its listen address
      view              store, entries: a store's view after a change, as a list of (peer id, descriptor, age)
    """

    def __init__(self, name, **values):
        self.name = name
        self.__dict__.update(values)

    def __repr__(self):
        return "Event(%s)" % ", ".join([self.name] + ["%s=%r" % kv for kv in sorted(self.__dict__.items()) if kv[0] != "name"])


class BootRefused(Exception):
    """The node was not started; the text is the Silica node's boot refusal for the same fault."""


def peer8(pid):
    """the first 8 hex digits of a peer id, as the node's own lines show it"""
    return bytes(pid)[:4].hex()


def peer16(d):
    """the first 16 hex digits of a descriptor's id, as the audit lines show a peer; "-" when there is none"""
    return "-" if d is None else d[Atom("id")][:8].hex()


def view_line(store, entries):
    """a view as the Silica test node prints it: "view tempus_edge: 1fae2ad7@0 9e1113ab@2", or "(empty)" """
    return "view %s:%s" % (store, "".join(" %s@%d" % (peer8(i), a) for (i, _d, a) in entries) if entries else " (empty)")


def dialable(addr):
    """An address this extension dials: a dotted quad, a colon, a port of 1 to 65535 in decimal. A name is not
    resolved (the Silica node's rule, bees_tempus_node@addr_ok)."""
    try:
        text = addr.decode("ascii") if isinstance(addr, (bytes, bytearray)) else addr
    except UnicodeDecodeError:
        return False
    host, colon, port = text.partition(":")
    parts = host.split(".")
    if not colon or len(host) < 7 or len(parts) != 4 or not all(p.isdigit() and 1 <= len(p) <= 3 for p in parts):
        return False
    return port.isdigit() and len(port) <= 6 and 1 <= int(port) <= 65535


def _own_token_why(token, typ, pub):
    """why a token cannot be this node's own, in the words of the Silica node's boot check; "" when it can"""
    try:
        fields, _payload, _sig = read_token(token)
    except Refused as why:
        return "the node's token does not read: %s" % why
    if fields["typ"] != typ:
        return "the node's token is for another peer type than the node's"
    if fields["sub"] != pub:
        return "the node's token names another key"
    return ""


class _Snapshot:
    """What one connection needs of the node, taken when the connection begins (the Silica node's cfg record)."""
    __slots__ = ("identity", "verifier", "count", "deadline")


class Node:
    """A TEMPUS node. See the module's text.

      config     a bees_tempus_config.NodeConfig
      token      the producer's token for the node's identity key, of the node's own type
      address    the address other nodes dial to reach this node, "a.b.c.d:port": what its advert carries
      on_event   a function of one Event: what the application is told
      log        a function of one line of text, for the node's own lines and its audit lines; when it is not given
                 the lines go to standard output, as the Silica node's do
      clock, timers, random    for tests only: see the module's text. An application passes none of them.
    """

    def __init__(self, config, *, token, address, on_event, log=None, clock=None, timers=None, random=None):
        self.c = config
        self._on_event = on_event
        self._log = log if log is not None else self._stdout
        self._log_lock = threading.Lock()
        self.clock = clock if clock is not None else SystemClock()
        self.timers = timers if timers is not None else ThreadTimers()
        self.random = random if random is not None else SecureRandom()
        why = tls_available()
        if why:
            raise self._boot_refused(why)
        try:
            self.identity = Identity(config.identity_certfile, config.identity_keyfile, token, address)
        except (OSError, ValueError) as exc:
            raise self._boot_refused("this node's TEMPUS certificate or key could not be loaded: %s" % exc)
        why = _own_token_why(token, config.typ, self.identity.pub)
        if not why and not (isinstance(address, str) and 3 <= len(address.encode()) <= 261):
            why = "the node's address is not 3 to 261 bytes"
        if why:
            raise self._boot_refused(why)
        self.kid, self.producer_pub = config.producer_kid, config.producer_pub
        self.now, self.state = 0, NO_READING
        self.token_bad = False               # the application was told that the node's own token is not valid
        self.live = self.accepted = self.dialed = 0
        self.join_stage, self.join_delay = 0, config.join_retry_initial_ms   # 0 not begun, 1..3 the store asked, 4 done, 10+ waiting for the clock
        self.join_pending = set()            # the stores a join sample is on its way for
        self.stores = {}
        for typ in TYPES:
            z = config.stores[typ]
            self.stores[typ] = Store(self.identity.peer_id, self.identity.descriptor(), typ == config.typ,
                                     z["capacity"], z["shuffle_length"])
        self._box = queue.Queue()
        self._thread = None
        self._listener = None
        self._accept_thread = None
        self._conns = []
        self._stopping = False
        self._timers = []
        self._up = False

    # ---- lines, events
    @staticmethod
    def _stdout(line):
        sys.stdout.write(line + "\n")
        sys.stdout.flush()

    def _say(self, line):
        with self._log_lock:
            self._log(line)

    def _boot_refused(self, why):
        self._say("tempus: boot refused: " + why)
        return BootRefused(why)

    def _audit(self, event, peer, what, cid):
        self._say("[tempus audit] %s peer=%s %s %s" % (event, peer16(peer), what, cid))

    def _tell(self, name, **values):
        try:
            self._on_event(Event(name, **values))
        except Exception as exc:                 # the application's fault must not end the node
            self._say("application: on_event raised %s: %s" % (type(exc).__name__, exc))

    # ---- the application's side
    def start(self):
        """Starts the node's thread. The node reads its clock at once and listens when the first reading has come."""
        if self._thread is not None:
            raise RuntimeError("the node was started before; a node is started once")
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._post(self._boot)
        return self

    def stop(self):
        """Stops the node: it stops listening and ticking, and its connections end within shuffle_timeout_ms."""
        if self._thread is None or self._stopping:
            return
        self._stopping = True
        for t in self._timers:
            try:
                t.cancel()
            except Exception:
                pass
        if self._listener is not None:
            try:
                self._listener.close()
            except OSError:
                pass
        self._box.put(None)
        self._thread.join()
        if self._accept_thread is not None:
            self._accept_thread.join()
        for t in list(self._conns):
            t.join()

    def set_token(self, token):
        """A new token for the node's own key (the application refreshes it at half of its lifetime). The node's own
        entry carries it from the next shuffle on, and a node that had stopped ticking for its token ticks again.
        ValueError when the token cannot be this node's (it does not read, is of another type or names another key)."""
        token = bytes(token)
        why = _own_token_why(token, self.c.typ, self.identity.pub)
        if why:
            raise ValueError(why)
        self._post(lambda: self._token(token))

    def set_producer_key(self, kid, public_key):
        """The producer's new current key (ruling NQ-5): kid 1 to 64 bytes, key 32 bytes."""
        kid = kid.encode() if isinstance(kid, str) else bytes(kid)
        if not 1 <= len(kid) <= 64 or len(public_key) != 32:
            raise ValueError("the producer key is not a kid of 1 to 64 bytes and a 32-byte key")
        self._post(lambda: self._key(kid, bytes(public_key)))

    def peers(self, store):
        """A copy of one store's view, [(peer id, descriptor, age)]: for an application that picks a peer itself (a
        bridge to call, for example). Entries are hearsay with an age; a peer in a store may be gone."""
        if store not in TYPES:
            raise ValueError("store is a peer type")
        if self._thread is None or self._stopping:
            raise RuntimeError("the node is not running")
        answer = queue.Queue()
        self._post(lambda: answer.put(list(self.stores[store].view)))
        while True:
            try:
                return answer.get(timeout=0.2)
            except queue.Empty:
                if self._stopping:
                    raise RuntimeError("the node is not running")

    # ---- the node's thread
    def _post(self, function):
        self._box.put(function)

    def _run(self):
        while True:
            function = self._box.get()
            if function is None:
                return
            try:
                function()
            except Exception as exc:             # a fault of this module: say so; the node goes on
                self._say("tempus: internal error: %s: %s" % (type(exc).__name__, exc))

    def _later(self, ms, function, name):
        if self._stopping:
            return
        self._timers = [t for t in self._timers if getattr(t, "is_alive", lambda: True)()]
        self._timers.append(self.timers.call_later(ms, lambda: self._post(function), name))

    def _boot(self):
        for typ in TYPES:
            self._refill(typ, "tick")
            self._refill(typ, "reply")
            self._arm_tick(typ)
        self._read_clock()

    def _arm_tick(self, typ):
        self._later(self.c.stores[typ]["tick_ms"], lambda: self._timer(typ), "tick " + typ)

    def _refill(self, typ, purpose):
        s = self.stores[typ]
        if getattr(s, purpose + "_draws") is None:
            setattr(s, purpose + "_draws", self.random.draws(typ, purpose, s.count + 1))

    def _changed(self, typ, before):
        view = self.stores[typ].view
        if view != before:
            self._tell("view", store=typ, entries=list(view))

    def _verifier(self):
        return Verifier(self.producer_pub, self.kid, self.now, self.c.clock_skew_s, self.c.whitelist)

    def _snapshot(self, count, deadline):
        s = _Snapshot()
        s.identity = Identity.__new__(Identity)
        s.identity.__dict__.update(self.identity.__dict__)
        s.verifier, s.count, s.deadline = self._verifier(), count, deadline
        return s

    def _max_count(self):
        return max(z["shuffle_length"] for z in self.c.stores.values())

    # ---- the clock
    def _read_clock(self):
        self._later(self.c.clock_read_ms, self._read_clock, "clock")
        self._reading(self.clock.read())

    def _reading(self, n):
        c = self.c
        was = self.now
        now, state, say, again = clock_turn(self.state, self.now, n, c.clock_back, c.clock_back_limit_s, c.clock_fail)
        if again:
            self._say("clock: the system clock is read again")
        back = "the system clock went back by %d s" % (was - n) if n is not None else ""
        self.now, self.state = now, state
        if say == 1:
            self._say("clock: the system clock is read")
            self._listen()
        elif say in (2, 3, 4):
            text = "the system clock could not be read: " + {
                2: "the node has not started",
                3: "the node admits no connection and does not tick until it is read again",
                4: "the node goes on with its last reading"}[say]
            self._say("clock: " + text)
            self._tell("clock_unreadable", text=text)
        elif say == 6:
            self._say("clock: %s; the node follows it" % back)
        elif say == 7:
            self._say("clock: %s; the node holds its time until the system clock has reached it" % back)
        elif say == 8:
            self._say("clock: the system clock has reached the held time; the node follows it again")
        elif say == 9:
            text = ("%s, more than clock_back_limit_s %d: the node has stopped; it admits no connection and does not "
                    "tick until its application starts it again" % (back, c.clock_back_limit_s))
            self._say("clock: " + text)
            self._tell("stopped", text=text)
        if again and self.join_stage > 10:       # the join request that waited for the clock is made at once
            store = self.join_stage - 10
            self.join_stage = store
            self._join(store, 1)

    # ---- listening
    def _listen(self):
        c = self.c
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((c.listen_host, c.port))
            sock.listen(64)
        except OSError as exc:
            sock.close()
            self._say("the listening link has gone down")
            self._tell("listen_failed", text=str(exc))
            return
        self._listener = sock
        self._accept_thread = threading.Thread(target=self._accept, args=(sock,), daemon=True)
        self._accept_thread.start()
        self._up = True
        self._say("%s node %s listening on %s" % (c.typ, peer8(self.identity.peer_id), self.identity.addr))
        for typ in TYPES:
            self._say("store %s: capacity %d, shuffle length %d" % (typ, c.stores[typ]["capacity"], c.stores[typ]["shuffle_length"]))
        if not c.sentinels:
            self._say("join: no sentinel is configured")
            self.join_stage = 4
        else:
            self.join_stage, self.join_delay = 1, c.join_retry_initial_ms
            self._join(1, 1)

    def _accept(self, sock):
        while not self._stopping:
            try:
                conn, _ = sock.accept()
            except OSError:
                break
            began = time.monotonic()
            self._post(lambda conn=conn, began=began: self._accepted(conn, began))

    def _accepted(self, sock, began):
        closes = clock_closes(self.state)
        full = self.live >= self.c.inflight_max
        self.accepted += 1
        cid = "a%d" % self.accepted
        role = closes or ("inflight_refused" if full else "")
        if not role:
            self.live += 1
        snap = self._snapshot(self._max_count(), began + self.c.shuffle_timeout_ms / 1000.0)
        self._spawn(lambda: self._serve(sock, snap, cid, role))

    def _spawn(self, function):
        self._conns = [t for t in self._conns if t.is_alive()]
        t = threading.Thread(target=function, daemon=True)
        self._conns.append(t)
        t.start()

    # ---- an accepted connection (its own thread)
    def _open(self, sock, snap, cid, server):
        """the TLS handshake with its audit line; None when it failed"""
        try:
            link = tls_open(sock, snap.identity, server, snap.deadline)
        except TlsRefused as why:
            self._audit(why.event, None, why.what, cid)
            return None
        self._audit("tls_established", None, link.established(), cid)
        return link

    def _serve(self, sock, snap, cid, role):
        try:
            self._serve_in(sock, snap, cid, role)
        except Exception as exc:                 # a fault of this module, never the peer's doing
            self._say("tempus: internal error on %s: %s: %s" % (cid, type(exc).__name__, exc))
            try:
                sock.close()
            except OSError:
                pass
        if not role:
            self._post(self._closed)

    def _serve_in(self, sock, snap, cid, role):
        link = self._open(sock, snap, cid, True)
        if link is None:
            return
        wire = Wire(link.tls, snap.deadline)
        if role:
            self._audit(role, None, {
                "inflight_refused": "more accepted connections than inflight_max: closed at once",
                "clock_refused": "the system clock cannot be read: closed at once",
                "clock_stopped": "the node stopped after its system clock went back: closed at once"}[role], cid)
            wire.close()
            return
        try:
            nonce = self.random.bytes(32)
            if nonce is None or len(nonce) != 32:
                self._audit("internal_error", None, "random bytes refused", cid)
                wire.close()
                return
            peer = admit(wire, link, snap.identity, snap.verifier, nonce,
                         lambda d: self._audit("key_rotated", d, ROTATED_TEXT, cid))
            self._audit("admitted", peer.d, self._how(peer), cid)
            body = read_frame(wire, "request", peer.d, True)
            kind = kind_of(body)
            fields = None
            if kind == "shuffle":
                try:
                    _k, fields = read_body(body, snap.count)
                except Refused as why:
                    raise Ended("protocol_error", str(why), "request", peer.d, proved=True)
                try:
                    snap.verifier.check_entries(fields["store"], fields["entries"])
                except Refused as why:
                    raise Ended("entry_refused", str(why), "request", peer.d, proved=True)
            elif kind not in ("sample", "call", "cast"):
                raise Ended("protocol_error", "not a request: %s" % (structure_reason(body) or "unknown kind"),
                            "request", peer.d, proved=True)
        except Ended as why:
            if why.event == "key_rotated":
                pass                             # its line was written when the frame went out
            elif why.event != "key_rotated_received":
                self._audit(why.event, why.peer, why.what, cid)
            else:
                self._audit("key_rotated", why.peer, why.what, cid)
                self._post(lambda: self._tell("key_rotated", kid=why.kid, dialed=False))
            wire.close()
            return
        answer = queue.Queue()
        self._post(lambda: answer.put(self._request(kind, body, fields, peer, cid)))
        while True:                              # the node always answers; a node that is being stopped does not
            try:
                reply = answer.get(timeout=0.2)
                break
            except queue.Empty:
                if self._stopping:
                    wire.close()
                    return
        if reply is not None:
            wire.send(frame(reply))
        wire.close()

    @staticmethod
    def _how(peer):
        return "%s, %s" % (peer.typ, "tempus whitelist entry %d" % peer.index if peer.index >= 0
                           else "token and proof of possession")

    def _closed(self):
        self.live -= 1

    # ---- an admitted peer's request (the node's thread): the reply body, or None to close with no reply
    def _request(self, kind, body, fields, peer, cid):
        if kind == "shuffle":
            return self._rq_shuffle(fields, peer, cid)
        if kind == "sample":
            return self._rq_sample(body, peer, cid)
        self._audit("request_refused", peer.d, "call and cast are served by a bridge only", cid)
        return None

    def _rq_shuffle(self, fields, peer, cid):
        typ = fields["store"]
        s = self.stores[typ]
        before = list(s.view)
        received = [(d[Atom("id")], d, age) for age, d in fields["entries"]]
        out = s.request(peer.d[Atom("id")], received) if len(received) <= s.count else None
        self._refill(typ, "reply")
        if out is None:
            self._audit("shuffle_refused", None, "the store refused the frame", cid)
            return None
        self._changed(typ, before)
        return shuffle_reply(typ, [(age, d) for (_i, d, age) in out])

    def _rq_sample(self, body, peer, cid):
        try:
            _k, fields = read_body(body, ENTRIES_MAX)
            _k, fields = read_body(body, self.c.stores[fields["store"]]["shuffle_length"])
        except Refused as why:
            self._audit("protocol_error", peer.d, str(why), cid)
            return None
        typ = fields["store"]
        out = self.stores[typ].sample(fields["n"])
        self._refill(typ, "reply")
        if self.c.typ == "tempus_sentinel":
            # a sentinel inserts the peer that asks it into its store of the peer's type, after the sample was taken
            # (the join, design section 6; ruling NQ-13), so a joiner is never answered with itself
            mine = self.stores[peer.typ]
            before = list(mine.view)
            mine.insert((peer.d[Atom("id")], peer.d, 0))
            self._changed(peer.typ, before)
        if out is None:
            return None
        return sample_reply(typ, [(age, d) for (_i, d, age) in out])

    # ---- ticks
    def _own_why(self):
        try:
            token_rules(self.identity.descriptor(), self.kid, self.now, self.c.clock_skew_s)
        except Refused as why:
            return str(why)
        return ""

    def _timer(self, typ):
        self._arm_tick(typ)
        if clock_ticks(self.state):
            self._tick(typ)

    def _tick(self, typ):
        why = self._own_why()
        if why:
            if not self.token_bad:
                self._say("own token: %s; ticking has stopped" % why)
                self._tell("token_invalid", why=why)
            self.token_bad = True
            return
        s = self.stores[typ]
        before = list(s.view)
        skew = self.c.clock_skew_s
        gone = [e[0] for e in s.view if self.now >= read_token(e[1][Atom("token")])[0]["exp"] + skew]
        for pid in gone:                          # an entry dies with its token (ruling OQ-4)
            s.drop(pid)
        if gone:
            self._say("expired in %s:%s" % (typ, "".join(" " + peer8(p) for p in gone)))
        act = s.tick()
        self._changed(typ, before)
        if act[0] == "skipped":
            self._refill(typ, "tick")
            self._tick_ended(typ, "skipped (no draws)")
        elif act[0] == "aged":
            self._tick_ended(typ, "aged only (a shuffle is in flight)")
        elif act[0] == "empty":
            self._tick_ended(typ, "the view is empty")
            if self.join_stage == 4 and typ not in self.join_pending and self.c.sentinels:
                self._join(TYPES.index(typ) + 1, 0)      # an empty view: the node asks a sentinel again
        else:
            self._refill(typ, "tick")
            self._shuffle_out(typ, act[1], act[2])

    def _tick_ended(self, typ, how):
        self._say("tick %s: %s" % (typ, how))

    def _shuffle_out(self, typ, partner, buffer):
        d = partner[1]
        addr = d[Atom("addr")]
        head = "tick %s: shuffle with %s" % (typ, peer8(partner[0]))
        if not dialable(addr):
            self._say(head + ": its address is not one this build dials")
            self._shuffle_failed(typ)
            return
        self.dialed += 1
        cid = "d%d" % self.dialed
        addr = addr.decode("ascii")
        self._say("%s at %s %s" % (head, addr, cid))
        body = shuffle(typ, [(age, dd) for (_i, dd, age) in buffer])
        self._dial(addr, body, cid, self.stores[typ].count, lambda what, value, peer: self._shuffle_done(typ, cid, what, value))

    def _shuffle_failed(self, typ):
        s = self.stores[typ]
        before = list(s.view)
        s.failed()
        self._changed(typ, before)
        self._tick_ended(typ, "shuffle failed")

    def _shuffle_done(self, typ, cid, what, value):
        s = self.stores[typ]
        if what != "reply":
            self._say("tick %s: the partner did not answer, %s %s" % (typ, value, cid))
            self._shuffle_failed(typ)
            return
        try:
            kind, fields = read_body(value, s.count)
            ok = kind == "shuffle_reply" and fields["store"] == typ
        except Refused:
            ok = False
        if not ok:
            self._shuffle_failed(typ)
            return
        before = list(s.view)
        merged = s.reply([(d[Atom("id")], d, age) for age, d in fields["entries"]])
        self._changed(typ, before)
        self._tick_ended(typ, "shuffle merged" if merged else "shuffle failed")

    # ---- the join (design section 6): one sample per store to a sentinel
    def _join(self, store, x):
        """store 1..3; x // 2 is the sentinel asked; x odd: part of the join at start, which goes on to the next store
        and retries; x even: asked again after a tick found the view empty"""
        typ = TYPES[store - 1]
        if self.state == PAUSED:
            # while the node waits for its clock it dials nobody: the request is remembered and made at once when the
            # clock is read again (owner's ruling of 2026-11-20, option d of the join question)
            self._say("join: the request for %s waits until the system clock is read again" % typ)
            self.join_stage = 10 + store
            return
        if self.state == STOPPED:
            return
        self.dialed += 1
        cid = "d%d" % self.dialed
        addr = self.c.sentinels[x // 2][0]
        count = self.stores[typ].count
        self._say("join: asking the sentinel at %s for %s %s" % (addr, typ, cid))
        self.join_pending.add(typ)
        self._dial(addr, sample(typ, count), cid, count, lambda what, value, peer: self._join_done(store, x, cid, what, value, peer))

    def _join_done(self, store, x, cid, what, value, peer):
        typ = TYPES[store - 1]
        self.join_pending.discard(typ)
        s = self.stores[typ]
        fields = None
        if what == "reply":
            try:
                kind, fields = read_body(value, ENTRIES_MAX)
                if kind != "sample_reply":
                    fields, value = None, "the reply is not a sample reply"
            except Refused as why:
                fields, value = None, str(why)
        if fields is None:
            self._say("join: the sentinel did not answer for %s, %s %s" % (typ, value, cid))
            self._join_failed(store, x)
            return
        self._say("join: the sentinel answered for %s %s" % (typ, cid))
        if fields["store"] == typ and len(fields["entries"]) <= s.count:
            before = list(s.view)
            for age, d in fields["entries"]:
                s.insert((d[Atom("id")], d, age))
            self._changed(typ, before)
        if peer.typ == "tempus_sentinel":
            # the joiner keeps the sentinel it joined through (ruling NQ-12): into the sentinel store at age 0, after
            # the sample's entries; an entry of it already there only becomes younger
            mine = self.stores["tempus_sentinel"]
            before = list(mine.view)
            mine.insert((peer.d[Atom("id")], peer.d, 0))
            self._changed("tempus_sentinel", before)
        if x % 2 == 1:
            if store < 3:
                self.join_stage, self.join_delay = store + 1, self.c.join_retry_initial_ms
                self._join(store + 1, 1)
            else:
                self._say("join: done")
                self.join_stage, self.join_delay = 4, self.c.join_retry_initial_ms

    def _join_failed(self, store, x):
        typ = TYPES[store - 1]
        if x // 2 + 1 < len(self.c.sentinels):
            self._join(store, x + 2)
        elif x % 2 == 0:
            self._say("join: no sentinel answered for %s" % typ)
        else:
            self._say("join: no sentinel answered for %s; waiting to try again" % typ)
            self._later(self.join_delay, lambda: self._join_retry(store), "join retry")
            self.join_stage = store
            self.join_delay = min(self.join_delay * 2, self.c.join_retry_max_ms)

    def _join_retry(self, store):
        if self.state != STOPPED:
            self._join(store, 1)

    # ---- a dialed connection: `done(what, value, peer)` runs on the node's thread with ("reply", body, Admitted) or
    # ("failed", the event, None)
    def _dial(self, addr, request, cid, count, done):
        snap = self._snapshot(count, time.monotonic() + self.c.shuffle_timeout_ms / 1000.0)
        self._spawn(lambda: self._dialing(addr, request, cid, snap, done))

    def _dialing(self, addr, request, cid, snap, done):
        try:
            what, value, peer = self._dialing_in(addr, request, cid, snap)
        except Exception as exc:                 # a fault of this module, never the peer's doing
            self._say("tempus: internal error on %s: %s: %s" % (cid, type(exc).__name__, exc))
            what, value, peer = "failed", "internal_error", None
        self._post(lambda: done(what, value, peer))

    def _dialing_in(self, addr, request, cid, snap):
        host, _, port = addr.rpartition(":")
        try:
            sock = socket.create_connection((host, int(port)), timeout=max(0.001, snap.deadline - time.monotonic()))
        except OSError:
            return "failed", "connect_failed", None
        link = self._open(sock, snap, cid, False)
        if link is None:
            return "failed", "connect_failed", None
        wire = Wire(link.tls, snap.deadline)
        try:
            nonce = self.random.bytes(32)
            if nonce is None or len(nonce) != 32:
                self._audit("internal_error", None, "random bytes refused", cid)
                wire.close()
                return "failed", "internal_error", None
            peer = admit(wire, link, snap.identity, snap.verifier, nonce,
                         lambda d: self._audit("key_rotated", d, ROTATED_TEXT, cid))
            self._audit("admitted", peer.d, self._how(peer), cid)
            wire.send(frame(request))
            body = read_frame(wire, "reply", peer.d, True)
            kind = kind_of(body)
            if kind in ("shuffle_reply", "sample_reply"):
                try:
                    _k, fields = read_body(body, snap.count)
                except Refused as why:
                    raise Ended("protocol_error", str(why), "reply", peer.d, proved=True)
                try:
                    snap.verifier.check_entries(fields["store"], fields["entries"])
                except Refused as why:
                    raise Ended("entry_refused", str(why), "reply", peer.d, proved=True)
            elif kind not in ("done", "result"):
                raise Ended("protocol_error", "the reply is not a reply frame", "reply", peer.d, proved=True)
        except Ended as why:
            wire.close()
            if why.event == "key_rotated_received":
                self._audit("key_rotated", why.peer, why.what, cid)
                self._post(lambda: self._tell("key_rotated", kid=why.kid, dialed=True))
                return "failed", "key_rotated", None
            if why.event == "key_rotated":
                return "failed", "key_rotated_sent", None
            self._audit(why.event, why.peer, why.what, cid)
            return "failed", why.event, None
        wire.close()
        return "reply", body, peer

    # ---- the application's values
    def _token(self, token):
        self.identity.token = token
        self.token_bad = False
        self._say("own token replaced")
        for s in self.stores.values():
            s.with_me(self.identity.descriptor())

    def _key(self, kid, public_key):
        self.kid, self.producer_pub = kid, public_key
        self._say("producer key replaced, kid %s" % kid.decode("utf-8", "replace"))
