#!/usr/bin/env python3
"""An independent model of one TEMPUS store's steps (development-plan/tempus-design.md sections 3 and 10), for tests only.

The Silica unit src/tempus/bees_tempus_store.silica is the implementation; this states the same rules a second time, as a
Python class over the view model (bees_tempus_view_model.py), so that tools/test_bees_tempus_store.py can compare the two.
Nothing in BEES imports this at run time.
"""
import bees_tempus_view_model as view


class Store:
    def __init__(self, self_id, self_d, own, cap, count):
        self.me = (self_id, self_d)
        self.own = own
        self.cap = cap
        self.count = count
        self.view = []
        self.sent = []
        self.partner = None      # set while a shuffle this store started is in flight
        self.tick_draws = None   # None: used up
        self.reply_draws = None

    @property
    def phase(self):
        return 1 if self.partner is not None else 0

    def insert(self, e):
        self.view = view.insert(self.view, e, self.me[0], self.cap)

    def drop(self, peer):
        self.view = [e for e in self.view if e[0] != peer]

    def tick(self):
        """('skipped',) | ('aged',) | ('empty',) | ('shuffle', partner, buffer)"""
        if self.tick_draws is None:
            return ("skipped",)
        aged = view.age_all(self.view)
        if self.partner is not None:
            self.view = aged
            return ("aged",)
        if not aged:
            return ("empty",)
        others = self.count if self.own else self.count + 1
        _, partner, sent, rest = view.select(aged, others, self.tick_draws)
        self.tick_draws = None
        self.view, self.sent, self.partner = rest, sent, partner
        return ("shuffle", partner, (view.outgoing(self.me[0], self.me[1], sent) if self.own else list(sent)))

    def failed(self):
        if self.partner is None:
            return
        self.view = view.backfill(self.view, self.sent, self.cap)
        self.sent, self.partner = [], None

    def reply(self, received):
        if self.partner is None:
            return
        if len(received) > self.count:
            self.failed()
            return
        merged = view.merge(self.view, view.prefer_sent(received, self.sent), self.me[0], self.cap)
        if not self.own:
            # NQ-15, ruled 2026-11-19: the partner that answered re-enters at age 0 (it cannot hold this node in a store
            # that is not of this node's type, so nothing else would bring the link back)
            merged = view.insert(merged, (self.partner[0], self.partner[1], 0), self.me[0], self.cap)
        self.view = view.backfill(merged, self.sent, self.cap)
        self.sent, self.partner = [], None

    def request(self, asker, received):
        """None when refused, else the entries answered."""
        if len(received) > self.count or self.reply_draws is None:
            return None
        out, kept = view.reply_select(self.view, self.count, asker, self.reply_draws)
        self.reply_draws = None
        merged = view.merge(kept, view.prefer_sent(received, out), self.me[0], self.cap)
        self.view = view.backfill(merged, out, self.cap)
        return out

    def sample(self, n):
        if n < 1 or self.reply_draws is None:
            return None
        out = view.sample(self.view, min(n, self.count), self.reply_draws)
        self.reply_draws = None
        return out
