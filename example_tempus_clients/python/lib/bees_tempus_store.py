"""The Python TEMPUS extension: one store's steps (development-plan/tempus-design.md sections 3 and 10).

A store is one of a node's three (edge, bridge, sentinel). This class knows nothing of types, connections, tokens or
time: the node feeds it events and carries out what it answers. Written after src/tempus/bees_tempus_store.silica and
the store actor beside it (bees_tempus_store_actor.silica), so that the two can be compared; the tests
(test_bees_tempus_node.py) run the steps of trials/t1_tempus_store against this class and compare every line with that
trial's golden.

State: the view; while a shuffle this store started is in flight, the entries it sent and the partner it chose; two
sets of draws, one for the next tick and one for the next choice made for somebody else (a partner's request, a
sample), each used once and then gone until the holder gives a new set (draws come from outside: bees_tempus_view's
rule); the node's own entry; the capacity; the shuffle length (`count`); and `own`, whether the node's own entry
belongs in this store (true only for the store of the node's own type, ruling OQ-5).
"""
import bees_tempus_view as view


class Store:
    def __init__(self, self_id, self_d, own, cap, count):
        self.me = (self_id, self_d)
        self.own, self.cap, self.count = own, cap, count
        self.view = []
        self.sent = []
        self.partner = None          # the partner's entry while a shuffle this store started is in flight
        self.tick_draws = None       # None: used up; the holder gives a new list
        self.reply_draws = None

    @property
    def phase(self):
        return 0 if self.partner is None else 1

    def with_me(self, self_d):
        """the node's own descriptor replaced (a new token): the next buffer carries it"""
        self.me = (self.me[0], self_d)

    def insert(self, entry):
        """an admitted peer enters the view by the merge rules"""
        self.view = view.insert(self.view, entry, self.me[0], self.cap)

    def drop(self, peer):
        self.view = view.remove(self.view, peer)

    def tick(self):
        """One tick: ("skipped",) with no tick draws, and nothing else happens; else every age rises by one and the
        answer is ("aged",) when a shuffle is in flight, ("empty",) when the view is empty, or ("shuffle", partner,
        buffer): the oldest entry is the partner, the buffer is the node's own entry at age 0 (when `own`) and
        count - 1 others (count others when not `own`); they leave the view and are remembered."""
        if self.tick_draws is None:
            return ("skipped",)
        aged = view.age_all(self.view)
        if self.partner is not None:
            self.view = aged
            return ("aged",)
        if not aged:
            return ("empty",)
        _found, partner, sent, rest = view.select(aged, self.count if self.own else self.count + 1, self.tick_draws)
        self.tick_draws = None
        self.view, self.sent, self.partner = rest, sent, partner
        return ("shuffle", partner, view.outgoing(self.me[0], self.me[1], sent) if self.own else list(sent))

    def failed(self):
        """the partner was unreachable, closed, timed out or broke a rule: it stays out, the other sent entries go back"""
        if self.partner is None:
            return
        self.view = view.backfill(self.view, self.sent, self.cap)
        self.sent, self.partner = [], None

    def reply(self, received):
        """The partner's answer is merged; in a store that is not of the node's own type the partner then re-enters at
        age 0 (ruling NQ-15); then the sent entries fill what room is left. More than count entries counts as failed.
        True when it was merged, False when it counted as failed, None when no shuffle was in flight."""
        if self.partner is None:
            return None
        if len(received) > self.count:
            self.failed()
            return False
        merged = view.merge(self.view, view.prefer_sent(received, self.sent), self.me[0], self.cap)
        if not self.own:
            merged = view.insert(merged, (self.partner[0], self.partner[1], 0), self.me[0], self.cap)
        self.view = view.backfill(merged, self.sent, self.cap)
        self.sent, self.partner = [], None
        return True

    def request(self, asker, received):
        """A partner's shuffle: up to count entries drawn at random, never the asker's own, are the answer; they leave
        the view, the received ones are merged, the answered ones fill what room is left. None (nothing changes) with
        no reply draws or with more than count entries received."""
        if len(received) > self.count or self.reply_draws is None:
            return None
        out, kept = view.reply_select(self.view, self.count, asker, self.reply_draws)
        self.reply_draws = None
        merged = view.merge(kept, view.prefer_sent(received, out), self.me[0], self.cap)
        self.view = view.backfill(merged, out, self.cap)
        return out

    def sample(self, n):
        """up to n entries (at most count) drawn at random; the view is not changed. None with no reply draws."""
        if n < 1 or self.reply_draws is None:
            return None
        out = view.sample(self.view, min(n, self.count), self.reply_draws)
        self.reply_draws = None
        return out
