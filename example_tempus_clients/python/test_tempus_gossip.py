#!/usr/bin/env python3
"""Tests of the gossip part of the Python example TEMPUS client library (lib/tempus_client/gossip.py).

    python3 example_tempus_clients/python/test_tempus_gossip.py        (from the BEES root)

1. The view rules and the store's steps against the independent models of tools/ (bees_tempus_view_model.py,
   bees_tempus_store_model.py), which state the rules of src/tempus/bees_tempus_view.silica and bees_tempus_store.silica
   and are themselves compared with those units by tools/test_bees_tempus_view.py and tools/test_bees_tempus_store.py:
   the same random steps are given to both and every view must be the same.
2. Three peers of this library in one process, over real TLS on loopback: a sentinel and two edges that are given the
   sentinel's address only. Each edge must come to hold the other.
The keys and tokens are TEST ONLY fixtures from fixed seeds.
"""
import os
import random
import sys
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "lib"))
sys.path.insert(0, os.path.join(HERE, "..", "..", "tools"))
import bees_tempus_store_model as store_model  # noqa: E402
import bees_tempus_view_model as view_model  # noqa: E402
import tempus_client as tc  # noqa: E402
from tempus_client import gossip, testing  # noqa: E402


def entries(rng, names, most):
    picked = rng.sample(names, rng.randint(0, min(most, len(names))))
    return [(n, "d-" + n, rng.randint(0, 40)) for n in picked]


class Rules(unittest.TestCase):
    def test_view_rules_agree_with_the_model(self):
        rng = random.Random(7)
        names = ["p%02d" % i for i in range(12)]
        for _ in range(400):
            view = entries(rng, names, 8)
            other = entries(rng, names, 6)
            draws = [rng.randint(0, 1000) for _ in range(9)]
            cap, count = rng.randint(1, 8), rng.randint(1, 5)
            self.assertEqual(gossip.age_all(view), view_model.age_all(view))
            self.assertEqual(gossip.merge(view, other, "p00", cap), view_model.merge(view, other, "p00", cap))
            self.assertEqual(gossip.prefer_sent(other, view), view_model.prefer_sent(other, view))
            self.assertEqual(gossip.backfill(view, other, cap), view_model.backfill(view, other, cap))
            self.assertEqual(gossip.take_sample(view, count, draws), view_model.sample(view, count, draws))
            self.assertEqual(gossip.reply_select(view, count, "p01", draws), view_model.reply_select(view, count, "p01", draws))
            if view:
                _, partner, sent, rest = view_model.select(view, count, draws)
                self.assertEqual(gossip.select(view, count, draws), (partner, sent, rest))

    def test_store_steps_agree_with_the_model(self):
        rng = random.Random(11)
        names = ["p%02d" % i for i in range(10)]
        for own in (True, False):
            mine = gossip.Store("me", own, 5, 3)
            model = store_model.Store("me", "d-me", own, 5, 3)
            for step in range(600):
                draws = [rng.randint(0, 1000) for _ in range(5)]
                what = rng.choice(("tick", "tick", "reply", "failed", "request", "sample", "insert", "drop"))
                if what == "tick":
                    model.tick_draws = list(draws)
                    got, want = mine.tick(draws), model.tick()
                    self.assertEqual(got[0], {"aged": "aged", "empty": "empty", "shuffle": "shuffle"}[want[0]])
                    if got[0] == "shuffle":
                        buffer = ([("me", "d-me", 0)] if own else []) + got[2]
                        self.assertEqual((got[1], buffer), (want[1], want[2]))
                elif what == "reply":
                    received = entries(rng, names + ["me"], 4)
                    mine.reply(received)
                    model.reply(received)
                elif what == "failed":
                    mine.failed()
                    model.failed()
                elif what == "request":
                    received = entries(rng, names + ["me"], 4)
                    model.reply_draws = list(draws)
                    self.assertEqual(mine.request("p03", received, draws), model.request("p03", received))
                elif what == "sample":
                    n = rng.randint(1, 5)
                    model.reply_draws = list(draws)
                    self.assertEqual(mine.sample(n, draws), model.sample(n))
                elif what == "insert":
                    e = entries(rng, names, 1)
                    for x in e:
                        mine.insert(x)
                        model.insert(x)
                else:
                    name = rng.choice(names)
                    mine.drop(name)
                    model.drop(name)
                self.assertEqual(mine.view, model.view, "step %d, %s" % (step, what))
                self.assertTrue(view_model.valid(mine.view, "me", 5))


class Network(unittest.TestCase):
    def test_two_edges_find_each_other_through_a_sentinel(self):
        far = 4000000000
        ids = [testing.fixture_identity(128, "tempus_sentinel", 1000, far), testing.fixture_identity(32, "tempus_edge", 1000, far),
               testing.fixture_identity(64, "tempus_edge", 1000, far)]
        # one subject name per certificate: Python's ssl finds a trusted certificate by its subject (connection.py)
        ids = [tc.Identity(i.seed, i.token, common_name="bees tempus gossip test %d" % k) for k, i in enumerate(ids)]
        producer_pub = testing._raw_public(testing.fixture_key(0))
        pems = [i.cert_pem for i in ids]
        learned = [dict() for _ in ids]
        lock = threading.Lock()
        peers = []
        stores = {t: tc.StoreSettings(4, 3, 150) for t in tc.TYPES}
        sentinel_addr = None
        try:
            for k, me in enumerate(ids):
                verifier = tc.Verifier(producer_pub, "k1", lambda: int(time.time()), 10, whitelist={tc.certificate_fingerprint(pems[0])})
                settings = tc.PeerSettings(stores, 3000, [] if k == 0 else [sentinel_addr], 200, 800)

                def on_learned(store, d, k=k):
                    with lock:
                        learned[k].setdefault(store, set()).add(d[tc.Atom("id")])
                port = self._free_port()
                p = tc.Peer(me.with_addr("127.0.0.1:%d" % port), verifier, settings, host="127.0.0.1", port=port,
                            trusted=[x for j, x in enumerate(pems) if j != k], on_learned=on_learned).start()
                peers.append(p)
                if k == 0:
                    sentinel_addr = p.address
            until = time.monotonic() + 20

            def complete():
                with lock:
                    return (ids[2].peer_id in learned[1].get("tempus_edge", ()) and ids[1].peer_id in learned[2].get("tempus_edge", ())
                            and all(ids[0].peer_id in learned[k].get("tempus_sentinel", ()) for k in (1, 2))
                            and {ids[1].peer_id, ids[2].peer_id} <= learned[0].get("tempus_edge", set()))
            while not complete() and time.monotonic() < until:
                time.sleep(0.05)
            self.assertTrue(complete(), learned)
            for p in peers:
                for t in tc.TYPES:
                    self.assertTrue(view_model.valid([(i, "", a) for (i, _, a) in p.view(t)], p.identity.peer_id, 4))
        finally:
            for p in peers:
                p.stop()

    @staticmethod
    def _free_port():
        import socket
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        return port


if __name__ == "__main__":
    unittest.main()
