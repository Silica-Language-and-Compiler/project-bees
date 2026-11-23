"""EXAMPLE ONLY, not for production. See ../../README.md.

Gossip discovery: what makes a client a member of a TEMPUS network instead of a program that sends one request.

  - the view rules (development-plan/tempus-design.md section 3): ageing, the choice of a partner and of the entries
    sent, the partner's choice, the merge, the eviction, putting sent entries back;
  - Store: one of a peer's three stores (edge, bridge, sentinel) and its steps: tick, reply, failed, request, sample,
    insert, drop;
  - Peer: a listener, the three stores, one tick timer per store, and the join through the configured sentinels
    (section 6). It answers the shuffles and samples of admitted peers from its stores, and when its own token says
    tempus_sentinel it puts every peer that asks it for a sample into its store of that peer's type.

The rules are the node's (src/tempus/bees_tempus_view.silica, bees_tempus_store.silica, bees_tempus_node.part), stated
again here in Python. Nothing has a default: capacity, shuffle length and tick of each store, the time bound of a
connection, the sentinels and the join's retry delays are all values the application passes.

An entry inside a store is (id, d, age): the peer's 64-byte id, its descriptor (the map of the wire) and its age in
ticks. On the wire an entry is (age, d). An entry enters a store only after its descriptor verified for that store
(Verifier.check_entry): the producer's signature, the current kid, the time, sub, the id hash, and the token's type
equal to the store's type.
"""
import os
import threading
import time

from .codec import Atom, Refused
from .connection import CLOSE, Listener, dial
from .frames import AGE_MAX, ENTRIES_MAX, TYPES, read_token, sample, sample_reply, shuffle, shuffle_reply

CAPACITY_MAX = 256


# ---------------------------------------------------------------- draws
def secure_draws(count):
    """`count` draws from the system's secure source, seven bytes each (design 3.5: used as an index modulo the number of
    candidates, so the bias for at most 256 candidates is below 2^-47)."""
    raw = os.urandom(7 * count)
    return [int.from_bytes(raw[7 * i:7 * i + 7], "big") for i in range(count)]


class _Draws:
    def __init__(self, values):
        self.values = list(values)

    def take(self):
        v = self.values.pop(0) if self.values else 0
        return v if v >= 0 else 0


# ---------------------------------------------------------------- the view rules (design section 3)
def age_all(view):
    """every age one higher; an age stops at 65535"""
    return [(i, d, min(a + 1, AGE_MAX)) for (i, d, a) in view]


def _pick(view, k, draws):
    """k entries drawn without replacement, in the order drawn, and what is left"""
    left, taken = list(view), []
    while k > 0 and left:
        taken.append(left.pop(draws.take() % len(left)))
        k -= 1
    return taken, left


def select(view, count, draw_values):
    """One tick's choice at the initiator, on a view that is not empty: (partner, sent, rest). The partner is the
    oldest entry (the first draw settles a tie); `sent` are count - 1 others drawn without replacement; `rest` is the
    view without the partner and without the sent entries."""
    draws = _Draws(draw_values)
    top = max(a for (_, _, a) in view)
    oldest = [e for e in view if e[2] == top]
    partner = oldest[draws.take() % len(oldest)]
    sent, rest = _pick([e for e in view if e[0] != partner[0]], count - 1, draws)
    return partner, sent, rest


def reply_select(view, count, asker, draw_values):
    """The partner's choice: (sent, rest). Up to count entries drawn without replacement, never the asker's own."""
    sent, _ = _pick([e for e in view if e[0] != asker], count, _Draws(draw_values))
    gone = {e[0] for e in sent}
    return sent, [e for e in view if e[0] not in gone]


def merge(rest, received, self_id, capacity):
    """The view after a shuffle. Entries for self_id are dropped; a peer that appears twice is kept once, the younger
    entry (at equal age the one this peer already had); the result is the winning received entries in arrival order,
    then the kept ones; then the oldest are evicted down to the capacity (at equal age the latest in order first)."""
    order, best = [], {}
    for e in received:
        if e[0] == self_id:
            continue
        if e[0] not in best:
            order.append(e[0])
            best[e[0]] = e
        elif e[2] < best[e[0]][2]:
            best[e[0]] = e
    have = {e[0]: e[2] for e in rest}
    win = [best[i] for i in order if i not in have or best[i][2] < have[i]]
    won = {e[0] for e in win}
    view = win + [e for e in rest if e[0] not in won]
    while len(view) > capacity:
        top = max(a for (_, _, a) in view)
        del view[max(k for k, e in enumerate(view) if e[2] == top)]
    return view


def prefer_sent(received, sent):
    """Ruling NQ-16: a received entry whose peer was just sent, and sent strictly younger, becomes the sent one."""
    mine = {}
    for e in sent:
        mine.setdefault(e[0], e)
    return [mine[e[0]] if e[0] in mine and mine[e[0]][2] < e[2] else e for e in received]


def backfill(view, sent, capacity):
    """sent entries go back at the end of the view, in order, while there is room; one already there is skipped"""
    view = list(view)
    for e in sent:
        if len(view) < capacity and all(e[0] != x[0] for x in view):
            view.append(e)
    return view


def insert(view, entry, self_id, capacity):
    """one entry enters the view by the merge rules"""
    return merge(view, [entry], self_id, capacity)


def take_sample(view, n, draw_values):
    taken, _ = _pick(view, n, _Draws(draw_values))
    return taken


# ---------------------------------------------------------------- one store
class Store:
    """One store's steps (design sections 3 and 10). It knows nothing of tokens, connections or time: its holder gives
    it verified entries and draws, and carries out what it answers. `own` says whether the peer's own entry belongs in
    this store: true only for the store of the peer's own type (ruling OQ-5)."""

    def __init__(self, self_id, own, capacity, shuffle_length):
        self.self_id, self.own, self.capacity, self.count = self_id, own, capacity, shuffle_length
        self.view = []
        self.sent = []
        self.partner = None          # set while a shuffle this store started is in flight

    def tick(self, draws):
        """("aged",) a shuffle is in flight: the view was aged and nothing else; ("empty",) nothing to do; or
        ("shuffle", partner, others): the partner and the entries to send it besides the peer's own. They have left the
        view and are remembered until reply() or failed()."""
        aged = age_all(self.view)
        if self.partner is not None:
            self.view = aged
            return ("aged",)
        if not aged:
            return ("empty",)
        partner, sent, rest = select(aged, self.count if self.own else self.count + 1, draws)
        self.view, self.sent, self.partner = rest, sent, partner
        return ("shuffle", partner, list(sent))

    def failed(self):
        """the partner was unreachable, closed, timed out or violated: it stays out; the other sent entries go back"""
        if self.partner is None:
            return
        self.view = backfill(self.view, self.sent, self.capacity)
        self.sent, self.partner = [], None

    def reply(self, received):
        """the partner's answer, every entry already verified. More than the shuffle length counts as failed."""
        if self.partner is None:
            return
        if len(received) > self.count:
            self.failed()
            return
        merged = merge(self.view, prefer_sent(received, self.sent), self.self_id, self.capacity)
        if not self.own:
            # ruling NQ-15: in a store that is not of this peer's type the partner cannot hold this peer, so nothing
            # else would bring the link back: the partner that answered re-enters at age 0
            merged = insert(merged, (self.partner[0], self.partner[1], 0), self.self_id, self.capacity)
        self.view = backfill(merged, self.sent, self.capacity)
        self.sent, self.partner = [], None

    def request(self, asker, received, draws):
        """A partner's shuffle, every entry already verified: the entries to answer with, or None when refused (more
        than the shuffle length). It does not matter whether a shuffle of this store's own is in flight."""
        if len(received) > self.count:
            return None
        out, kept = reply_select(self.view, self.count, asker, draws)
        merged = merge(kept, prefer_sent(received, out), self.self_id, self.capacity)
        self.view = backfill(merged, out, self.capacity)
        return out

    def sample(self, n, draws):
        """up to n entries (at most the shuffle length) drawn at random; the view is not changed"""
        return take_sample(self.view, min(n, self.count), draws)

    def insert(self, entry):
        self.view = insert(self.view, entry, self.self_id, self.capacity)

    def drop(self, peer):
        self.view = [e for e in self.view if e[0] != peer]


# ---------------------------------------------------------------- settings (no defaults: design section 11)
class StoreSettings:
    """capacity 1 to 256; shuffle_length 1 to 64 and at most the capacity; tick_ms 100 to 3600000"""

    def __init__(self, capacity, shuffle_length, tick_ms):
        if not 1 <= capacity <= CAPACITY_MAX:
            raise ValueError("a capacity is 1 to %d" % CAPACITY_MAX)
        if not 1 <= shuffle_length <= ENTRIES_MAX or shuffle_length > capacity:
            raise ValueError("a shuffle length is 1 to %d and at most the capacity" % ENTRIES_MAX)
        if not 100 <= tick_ms <= 3600000:
            raise ValueError("tick_ms is 100 to 3600000")
        self.capacity, self.shuffle_length, self.tick_ms = capacity, shuffle_length, tick_ms


class PeerSettings:
    """stores: {"tempus_edge": StoreSettings, "tempus_bridge": ..., "tempus_sentinel": ...}, all three; the time bound of
    a whole connection in ms (100 to 60000); the sentinels as "host:port" texts (none for a first sentinel; at most 16);
    the join's first and greatest retry delay in ms (100 to 3600000 each)."""

    def __init__(self, stores, shuffle_timeout_ms, sentinels, join_retry_initial_ms, join_retry_max_ms):
        if set(stores) != set(TYPES):
            raise ValueError("the three stores are %s" % (TYPES,))
        if not 100 <= shuffle_timeout_ms <= 60000:
            raise ValueError("shuffle_timeout_ms is 100 to 60000")
        if len(sentinels) > 16:
            raise ValueError("at most 16 sentinels")
        if not (100 <= join_retry_initial_ms <= 3600000 and 100 <= join_retry_max_ms <= 3600000):
            raise ValueError("a join retry delay is 100 to 3600000 ms")
        self.stores, self.shuffle_timeout_ms, self.sentinels = dict(stores), shuffle_timeout_ms, list(sentinels)
        self.join_retry_initial_ms, self.join_retry_max_ms = join_retry_initial_ms, join_retry_max_ms


def peer8(pid):
    """the first 8 hex digits of a peer id, as a node prints it in its own lines"""
    return bytes(pid)[:4].hex()


# ---------------------------------------------------------------- the peer
class Peer:
    """A member of a TEMPUS network: it listens, joins through its sentinels, ticks its three stores and answers the
    shuffles and samples of admitted peers.

    identity   this peer's Identity; its address is the one other peers dial
    verifier   its Verifier: producer key, kid, clock, skew and the tempus whitelist
    settings   a PeerSettings
    host, port where it listens
    trusted    the PEM certificates of the peers that may dial this peer (a limit of Python's ssl: see connection.py)
    on_line    called with each line the peer has to say (what a node prints: the join, each tick)
    on_learned called as on_learned(store, descriptor) when a peer that was not in a store enters it
    draws      a function count -> that many non-negative integers; the default is the system's secure source

    start() begins, stop() ends. view(store) is a copy of a store's entries. new_token(bytes) replaces the peer's own
    token (the application refreshes it; this library never speaks to the producer).
    """

    def __init__(self, identity, verifier, settings, *, host, port, trusted=(), on_line=None, on_learned=None, draws=None):
        self.identity, self.verifier, self.settings = identity, verifier, settings
        self.typ = read_token(identity.token)[0]["typ"]
        self._host, self._port, self._trusted = host, port, tuple(trusted)
        self._on_line = on_line or (lambda line: None)
        self._on_learned = on_learned or (lambda store, d: None)
        self._draws = draws or secure_draws
        self._lock = threading.RLock()
        self._stores = {t: Store(identity.peer_id, t == self.typ, s.capacity, s.shuffle_length)
                        for t, s in settings.stores.items()}
        self._stopping = threading.Event()
        self._threads = []
        self._listener = None
        self._joined = False
        self._asking = set()            # stores for which a sample to a sentinel is on its way
        self._token_stopped = False
        self.address = None

    # ---- the application's side
    def start(self):
        longest = max(s.shuffle_length for s in self.settings.stores.values())
        self._listener = Listener(self.identity, self.verifier, self._serve, self._trusted, host=self._host, port=self._port,
                                  timeout=self.settings.shuffle_timeout_ms / 1000.0, shuffle_length=longest,
                                  keep=False).start()
        self.address = self._listener.address
        self._on_line("%s peer %s listening on %s" % (self.typ, peer8(self.identity.peer_id), self.identity.addr or self.address))
        for t in TYPES:
            s = self.settings.stores[t]
            self._on_line("store %s: capacity %d, shuffle length %d" % (t, s.capacity, s.shuffle_length))
        self._run(self._join)
        for t in TYPES:
            self._run(self._ticker, t)
        return self

    def stop(self):
        self._stopping.set()
        for t in list(self._threads):
            t.join()
        if self._listener is not None:
            self._listener.close()

    def view(self, store):
        with self._lock:
            return list(self._stores[store].view)

    def new_token(self, token):
        with self._lock:
            self.identity = self.identity.with_token(token)
            self._token_stopped = False
        if self._listener is not None:
            self._listener.identity = self.identity
        self._on_line("own token replaced")

    # ---- helpers
    def _run(self, fn, *args):
        t = threading.Thread(target=fn, args=args, daemon=True)
        self._threads = [x for x in self._threads if x.is_alive()]
        self._threads.append(t)
        t.start()

    def _count(self, store):
        return self.settings.stores[store].shuffle_length

    def _put(self, store, entries):
        """verified entries enter a store by the merge rules; a peer new to the store is told to the application"""
        with self._lock:
            st = self._stores[store]
            for e in entries:
                before = {x[0] for x in st.view}
                st.insert(e)
                self._told(store, before)

    def _told(self, store, before):
        for (pid, d, _) in self._stores[store].view:
            if pid not in before:
                self._on_learned(store, d)

    def _verified(self, store, wire_entries):
        """the entries of a frame as store entries, or None when one of them does not verify for this store"""
        out = []
        for (age, d) in wire_entries:
            try:
                self.verifier.check_entry(d, store)
            except Refused:
                return None
            out.append((d[Atom("id")], d, age))
        return out

    def _dial(self, addr, body, store):
        return dial(addr, self.identity, self.verifier, body, timeout=self.settings.shuffle_timeout_ms / 1000.0,
                    shuffle_length=self._count(store))

    def _why(self, out):
        return out.reason or out.what

    # ---- the join (design section 6): one sample per store to a sentinel
    def _ask(self, store):
        """One sample of `store` from the first sentinel that answers. True when one did: its entries are in the store,
        and the sentinel itself is in this peer's sentinel store at age 0 (ruling NQ-12)."""
        for addr in self.settings.sentinels:
            if self._stopping.is_set():
                return False
            self._on_line("join: asking the sentinel at %s for %s" % (addr, store))
            out = self._dial(addr, sample(store, self._count(store)), store)
            entries = None
            if out.what == "reply" and out.kind == "sample_reply" and out.fields["store"] == store:
                entries = self._verified(store, out.fields["entries"])
            if entries is None:
                self._on_line("join: the sentinel did not answer for %s, %s" % (store, self._why(out)))
                continue
            self._on_line("join: the sentinel answered for %s" % store)
            self._put(store, entries)
            if out.typ == "tempus_sentinel":
                self._put("tempus_sentinel", [(out.advert[Atom("id")], out.advert, 0)])
            return True
        return False

    def _join(self):
        if not self.settings.sentinels:
            self._on_line("join: no sentinel is configured")
            self._joined = True
            return
        for store in TYPES:
            delay = self.settings.join_retry_initial_ms
            while not self._ask(store):
                if self._stopping.is_set():
                    return
                self._on_line("join: no sentinel answered for %s; waiting to try again" % store)
                if self._stopping.wait(delay / 1000.0):
                    return
                delay = min(delay * 2, self.settings.join_retry_max_ms)
        self._on_line("join: done")
        self._joined = True

    def _ask_again(self, store):
        try:
            if not self._ask(store) and not self._stopping.is_set():
                self._on_line("join: no sentinel answered for %s" % store)
        finally:
            with self._lock:
                self._asking.discard(store)

    # ---- ticks (design 3.2 and section 10)
    def _ticker(self, store):
        every = self.settings.stores[store].tick_ms / 1000.0
        due = time.monotonic() + every
        while not self._stopping.wait(max(0.0, due - time.monotonic())):
            due += every
            self._tick(store)

    def _own_token_why(self):
        try:
            self.verifier.check_descriptor(self.identity.descriptor(self.identity.addr or self.address))
        except Refused as why:
            return str(why)
        return ""

    def _expired(self, store):
        now, skew = self.verifier.clock(), self.verifier.skew
        st = self._stores[store]
        gone = [e for e in st.view if now >= read_token(e[1][Atom("token")])[0]["exp"] + skew]
        for e in gone:
            st.drop(e[0])
        if gone:
            self._on_line("expired in %s: %s" % (store, " ".join(peer8(e[0]) for e in gone)))

    def _tick(self, store):
        with self._lock:
            why = self._own_token_why()
            if why:
                # a peer whose own token is not valid cannot be admitted anywhere: it stops ticking and says so once
                if not self._token_stopped:
                    self._token_stopped = True
                    self._on_line("own token: %s; ticking has stopped" % why)
                return
            self._expired(store)
            st = self._stores[store]
            act = st.tick(self._draws(st.count + 1))
            if act[0] == "empty":
                again = self._joined and store not in self._asking and bool(self.settings.sentinels)
                if again:
                    self._asking.add(store)
            elif act[0] == "shuffle":
                me = self.identity.descriptor(self.identity.addr or self.address)
                buffer = ([(self.identity.peer_id, me, 0)] if st.own else []) + act[2]
        if act[0] == "aged":
            self._on_line("tick %s: aged only (a shuffle is in flight)" % store)
        elif act[0] == "empty":
            self._on_line("tick %s: the view is empty" % store)
            if again:
                self._run(self._ask_again, store)
        else:
            self._run(self._shuffle, store, act[1], buffer)

    def _shuffle(self, store, partner, buffer):
        addr = partner[1][Atom("addr")].decode("utf-8", "replace")
        self._on_line("tick %s: shuffle with %s at %s" % (store, peer8(partner[0]), addr))
        host, _, port = addr.rpartition(":")
        if not host or not port.isdigit():
            out, received = None, None
            why = "its address is not one this peer dials"
        else:
            out = self._dial(addr, shuffle(store, [(age, d) for (_, d, age) in buffer]), store)
            received = None
            if out.what == "reply" and out.kind == "shuffle_reply" and out.fields["store"] == store:
                received = self._verified(store, out.fields["entries"])
            why = self._why(out) if received is None else ""
            if received is None and out.what == "reply":
                why = "a reply that does not verify"
        with self._lock:
            st = self._stores[store]
            before = {x[0] for x in st.view} | {x[0] for x in st.sent} | {partner[0]}
            if received is None:
                st.failed()
            else:
                st.reply(received)
                self._told(store, before)
        if received is None:
            self._on_line("tick %s: the partner did not answer, %s" % (store, why))
            self._on_line("tick %s: shuffle failed" % store)
        else:
            self._on_line("tick %s: shuffle merged" % store)

    # ---- an admitted peer's request
    def _serve(self, rq):
        if rq.kind == "shuffle":
            store = rq.fields["store"]
            received = self._verified(store, rq.fields["entries"])
            if received is None:
                return CLOSE
            with self._lock:
                st = self._stores[store]
                before = {x[0] for x in st.view} | {x[0] for x in st.sent} | ({st.partner[0]} if st.partner else set())
                out = st.request(rq.advert[Atom("id")], received, self._draws(st.count + 1))
                if out is None:
                    return CLOSE
                self._told(store, before)
            return shuffle_reply(store, [(age, d) for (_, d, age) in out])
        if rq.kind == "sample":
            store, n = rq.fields["store"], rq.fields["n"]
            if n > self._count(store):
                return CLOSE
            with self._lock:
                st = self._stores[store]
                out = st.sample(n, self._draws(st.count + 1))
                if self.typ == "tempus_sentinel":
                    # the join (design section 6, ruling NQ-13): a sentinel puts every peer that asks it for a sample
                    # into its store of that peer's type, after the sample was taken
                    self._put(rq.typ, [(rq.advert[Atom("id")], rq.advert, 0)])
            return sample_reply(store, [(age, d) for (_, d, age) in out])
        return CLOSE                    # a call or a cast is served by a bridge only; anything else is no request
