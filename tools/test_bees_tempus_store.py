#!/usr/bin/env python3
"""Tests of one TEMPUS store's steps (T1, development-plan/tempus-design.md sections 3 and 10).

The trial trials/t1_tempus_store runs src/tempus/bees_tempus_store.silica (entry `steps`): one line per case, then six stores
and a silent peer for thirty rounds, then a store that is not of the node's own type (ruling NQ-15). This test computes every line again with the independent model
tools/bees_tempus_store_model.py and compares with every recorded golden (steps.<platform>.scout) and with the last run's
output (steps.sout) when there is one.

    python3 tools/test_bees_tempus_store.py
"""
import copy
import glob
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import bees_tempus_view_model as view  # noqa: E402
from bees_tempus_store_model import Store  # noqa: E402

LEAF = os.path.join(ROOT, "trials", "t1_tempus_store")


def ent(i, age):
    return (i, "@" + i, age)


def one(e):
    return "%s:%d" % (e[0], e[2])


def show(v):
    return " ".join(one(e) for e in v) if v else "(empty)"


def yes(b):
    return "yes" if b else "no"


def state_line(name, s):
    p = " partner " + one(s.partner) if s.phase == 1 else ""
    return "%s: view %s | sent %s | phase %d%s" % (name, show(s.view), show(s.sent), s.phase, p)


def act_line(name, a):
    what = {"aged": "aged only", "empty": "empty view, ask a sentinel", "skipped": "skipped, no draws"}.get(a[0])
    if a[0] == "shuffle":
        what = "shuffle with %s sending %s" % (one(a[1]), show(a[2]))
    return "%s: %s" % (name, what)


def ans_line(name, out):
    return "%s: %s" % (name, "refused" if out is None else "answers " + show(out))


def base(own):
    s = Store("me", "@me", own, 5, 3)
    for e in (ent("e", 0), ent("d", 1), ent("c", 5), ent("b", 5), ent("a", 3)):
        s.insert(e)
    return s


def part_tick():
    out = []
    s0 = Store("me", "@me", True, 5, 3)
    out.append(state_line("init", s0))
    out.append("init needs tick draws: " + yes(s0.tick_draws is None))
    out.append(act_line("tick without draws", s0.tick()))
    s0.tick_draws = [1, 0, 1]
    out.append(act_line("tick on an empty view", s0.tick()))
    b = base(True)
    out.append(state_line("base", b))
    t = copy.deepcopy(b)
    t.tick_draws = [1, 0, 1]
    out.append(act_line("tick", t.tick()))
    out.append(state_line("after tick", t))
    out.append("after tick needs tick draws: " + yes(t.tick_draws is None))
    t.tick_draws = [0, 0, 0]
    out.append(act_line("tick in flight", t.tick()))
    out.append(state_line("after tick in flight", t))
    out.append("after tick in flight needs tick draws: " + yes(t.tick_draws is None))
    r1 = copy.deepcopy(t)
    r1.reply([ent("x", 2), ent("b", 1), ent("me", 9)])
    out.append(state_line("after reply", r1))
    f1 = copy.deepcopy(t)
    f1.failed()
    out.append(state_line("after failed", f1))
    r2 = copy.deepcopy(t)
    r2.reply([ent("p", 0), ent("q", 0), ent("r", 0), ent("s", 0)])
    out.append(state_line("after an oversize reply", r2))
    r3 = copy.deepcopy(b)
    r3.reply([ent("x", 2)])
    out.append(state_line("reply when idle", r3))
    f2 = copy.deepcopy(b)
    f2.failed()
    out.append(state_line("failed when idle", f2))
    r4 = copy.deepcopy(t)
    r4.reply([ent("x", 2), ent("y", 3), ent("z", 4)])
    out.append(state_line("reply that fills the view", r4))
    return out


def part_other():
    out = []
    b = base(True)
    q0 = copy.deepcopy(b)
    out.append(ans_line("request without draws", q0.request("d", [ent("d", 0)])))
    out.append(state_line("after it", q0))
    b1 = copy.deepcopy(b)
    b1.reply_draws = [2, 2, 0]
    q1 = copy.deepcopy(b1)
    out.append(ans_line("request", q1.request("d", [ent("d", 0), ent("x", 4)])))
    out.append(state_line("after request", q1))
    out.append("after request needs reply draws: " + yes(q1.reply_draws is None))
    q2 = copy.deepcopy(b1)
    out.append(ans_line("oversize request", q2.request("d", [ent("p", 0), ent("q", 0), ent("r", 0), ent("s", 0)])))
    out.append(state_line("after it", q2))
    m1 = copy.deepcopy(b1)
    out.append(ans_line("sample 2", m1.sample(2)))
    out.append(state_line("after sample", m1))
    out.append("after sample needs reply draws: " + yes(m1.reply_draws is None))
    out.append(ans_line("sample 9", copy.deepcopy(b1).sample(9)))
    out.append(ans_line("sample without draws", copy.deepcopy(b).sample(2)))
    out.append(ans_line("sample 0", copy.deepcopy(b1).sample(0)))
    o = base(False)
    o.tick_draws = [1, 0, 1]
    out.append(act_line("tick of a store of another type", o.tick()))
    out.append(state_line("after it", o))
    dr = copy.deepcopy(b)
    dr.drop("c")
    out.append(state_line("drop c", dr))
    ins = copy.deepcopy(b)
    ins.insert(ent("me", 0))
    out.append(state_line("insert of self", ins))
    b2 = copy.deepcopy(b)
    b2.tick_draws = [1, 0, 1]
    b2.tick()
    b2.reply_draws = [0, 0, 0]
    out.append(ans_line("request during a shuffle", b2.request("z", [ent("z", 0)])))
    out.append(state_line("after it", b2))
    return out


class Sim:
    """Part 2: six stores and the silent peer n9, the trial's TEST-ONLY generator and seeds."""
    N, CAP, LEN, SEED, ROUNDS = 6, 4, 3, 20261118, 30

    def __init__(self):
        self.world = []
        for i in range(self.N):
            s = Store("n%d" % i, "@n%d" % i, True, self.CAP, self.LEN)
            s.insert(ent("n%d" % ((i + 2) % self.N), 0))
            s.insert(ent("n%d" % ((i + 1) % self.N), 0))
            if i % 2 == 0:
                s.insert(ent("n9", 0))
            self.world.append(s)
        self.ok = True
        self.failures = 0

    @staticmethod
    def draws(x, k):
        out = []
        for _ in range(k):
            x = (x * 1103515245 + 12345) % 2147483648
            out.insert(0, x // 65536)
        return out

    def step(self, r, i):
        seed = self.SEED + r * 1000 + i * 10
        s = self.world[i]
        s.tick_draws = self.draws(seed, self.LEN)
        act = s.tick()
        if act[0] != "shuffle":
            return
        name = act[1][0]
        if name == "n9":
            s.failed()
            self.failures += 1
            return
        q = self.world[int(name[1:])]
        q.reply_draws = self.draws(seed + 1, self.LEN)
        answer = q.request(s.me[0], act[2])
        if answer is None:
            s.failed()
        else:
            s.reply(answer)
        self.ok = self.ok and view.valid(s.view, s.me[0], self.CAP) and view.valid(q.view, q.me[0], self.CAP)

    def holders(self):
        return sum(1 for s in self.world if any(e[0] == "n9" for e in s.view))

    def world_lines(self):
        return ["  n%d: %s" % (i, show(s.view)) for i, s in enumerate(self.world)]

    def lines(self):
        out = ["start, views holding the silent peer: %d" % self.holders()] + self.world_lines()
        for r in range(1, self.ROUNDS + 1):
            for i in range(self.N):
                self.step(r, i)
            if r in (1, 2, self.ROUNDS):
                out.append("after round %d, views holding the silent peer: %d" % (r, self.holders()))
                out += self.world_lines()
        out.append("every view valid after every exchange: " + yes(self.ok))
        return out


def drain(own, ticks, put_back=True):
    """A store holding p q r, each tick answered with nothing: the states after every tick"""
    s = Store("me", "@me", own, 4, 2)
    for e in (ent("r", 0), ent("q", 0), ent("p", 0)):
        s.insert(e)
    states = [copy.deepcopy(s)]
    for _ in range(ticks):
        s.tick_draws = [0, 0, 0]
        if s.tick()[0] == "shuffle":
            if put_back:
                s.reply([])
            else:           # the rules before ruling NQ-15: merge and backfill only
                s.view = view.backfill(view.merge(s.view, [], s.me[0], s.cap), s.sent, s.cap)
                s.sent, s.partner = [], None
        states.append(copy.deepcopy(s))
    return states


def part_drain():
    out = []
    o = base(False)
    o.tick_draws = [1, 0, 1]
    o.tick()
    r1 = copy.deepcopy(o)
    r1.reply([ent("x", 2)])
    out.append(state_line("another type, after reply", r1))
    r2 = copy.deepcopy(o)
    r2.reply([ent("x", 2), ent("y", 3), ent("z", 4)])
    out.append(state_line("another type, a reply that fills the view", r2))
    f = copy.deepcopy(o)
    f.failed()
    out.append(state_line("another type, after failed", f))
    b = base(True)
    b.tick_draws = [1, 0, 1]
    b.tick()
    b.reply([ent("x", 2)])
    out.append(state_line("own type, after the same reply", b))
    states = drain(False, 12)
    out.append(state_line("another type, before twelve ticks", states[0]))
    for k in (1, 2, 3, 12):
        out.append(state_line("another type, after tick %d" % k, states[k]))
    out.append("another type, the smallest view over twelve ticks: %d" % min(len(s.view) for s in states))
    return out


class Sentinel:
    """NQ-15 as a model run: a sentinel's edge store (not its own type) among edges that shuffle with each other.

    Every round each edge ticks its own store and then the sentinel ticks its edge store. Nobody asks the sentinel, so
    nothing but the rule keeps its edge store filled. With two edges this is the run of design NQ-15 (seen by hand before
    the ruling: the sentinel's edge store went from two entries to none and stayed empty)."""
    SEED = 20261119

    def __init__(self, put_back, edges, cap, length):
        self.put_back, self.length = put_back, length
        self.x = self.SEED
        self.edges = {}
        for i in range(edges):
            s = Store("e%d" % i, "@e%d" % i, True, cap, length)
            for j in range(1, edges):
                s.insert(ent("e%d" % ((i + j) % edges), 0))
            self.edges[s.me[0]] = s
        self.s = Store("s", "@s", False, cap, length)
        for i in range(min(cap, edges)):
            self.s.insert(ent("e%d" % i, 0))

    def draws(self):
        out = []
        for _ in range(self.length + 1):
            self.x = (self.x * 1103515245 + 12345) % 2147483648
            out.insert(0, self.x // 65536)
        return out

    def tick(self, s):
        s.tick_draws = self.draws()
        act = s.tick()
        if act[0] != "shuffle":
            return
        q = self.edges[act[1][0]]
        q.reply_draws = self.draws()
        answer = q.request(s.me[0], act[2])
        if s is self.s and not self.put_back:    # the rules before ruling NQ-15: merge and backfill only
            s.view = view.backfill(view.merge(s.view, view.prefer_sent(answer, s.sent), "s", s.cap), s.sent, s.cap)
            s.sent, s.partner = [], None
        else:
            s.reply(answer)

    def sizes(self, rounds):
        out = []
        for _ in range(rounds):
            for s in list(self.edges.values()) + [self.s]:
                self.tick(s)
            out.append(len(self.s.view))
        return out


def expected():
    return part_tick() + part_other() + Sim().lines() + part_drain() + ["exit=0"]


class ActorSim:
    """The script of the trial's entry `actors`: four store actors and the driver, as one sequential model.

    The driver's one generator serves the stores' requests for draws in the order they are made: at the start each store
    asks for tick draws and reply draws; a store that used its tick draws asks before its shuffle goes out; a partner that
    used its reply draws asks before its answer goes back."""
    N, CAP, LEN, SEED, TICKS, SHOWN = 4, 3, 2, 20261118, 400, 16

    def __init__(self):
        self.x = self.SEED
        self.world = []
        for i in range(self.N):
            s = Store("n%d" % i, "@n%d" % i, True, self.CAP, self.LEN)
            self.world.append(s)
        for s in self.world:
            s.tick_draws = self.draws()
            s.reply_draws = self.draws()
        for i, s in enumerate(self.world):
            first = [ent("n%d" % ((i + 1) % self.N), 0), ent("n%d" % ((i + 2) % self.N), 0)]
            if i == 0:
                first.insert(0, ent("n9", 0))
            for e in first:
                s.insert(e)
        self.failed = 0

    def draws(self):
        out = []
        for _ in range(self.LEN):
            self.x = (self.x * 1103515245 + 12345) % 2147483648
            out.insert(0, self.x // 65536)
        return out

    def tick(self, k):
        s = self.world[k % self.N]
        act = s.tick()
        if act[0] == "skipped":
            s.tick_draws = self.draws()
            return "skipped, no draws"
        if act[0] == "aged":
            return "aged only"
        if act[0] == "empty":
            return "empty view"
        s.tick_draws = self.draws()
        name = act[1][0]
        if name == "n9":
            s.failed()
            self.failed += 1
            return "shuffle failed"
        q = self.world[int(name[1:])]
        answer = q.request(s.me[0], act[2])
        if answer is None:
            s.failed()
            return "shuffle failed"
        q.reply_draws = self.draws()
        s.reply(answer)
        return "shuffle merged"

    def lines(self):
        out = []
        for k in range(self.TICKS):
            how = self.tick(k)
            if k < self.SHOWN:
                out.append("tick %d of n%d: %s" % (k + 1, k % self.N, how))
        out.append("store actor's committed memory the same after tick 40 and after the last tick: yes")
        out += ["  n%d: %s" % (i, show(s.view)) for i, s in enumerate(self.world)]
        return out + ["done", "exit=0"]


def read_lines(path):
    with open(path) as f:
        return [line.rstrip("\n") for line in f if line.strip() != ""]


class StoreRules(unittest.TestCase):
    def test_goldens_match_the_model(self):
        goldens = sorted(glob.glob(os.path.join(LEAF, "steps.*.scout")))
        self.assertTrue(goldens, "no golden recorded in trials/t1_tempus_store")
        for g in goldens:
            self.assertEqual(read_lines(g), expected(), g)

    def test_last_run_matches_the_model(self):
        sout = os.path.join(LEAF, "steps.sout")
        if not os.path.exists(sout):
            self.skipTest("the trial has not been run in this tree")
        self.assertEqual(read_lines(sout), expected())

    def test_actor_goldens_match_the_model(self):
        goldens = sorted(glob.glob(os.path.join(LEAF, "actors.*.scout")))
        self.assertTrue(goldens, "no golden recorded for the entry actors")
        for g in goldens:
            self.assertEqual(read_lines(g), ActorSim().lines(), g)

    def test_actor_last_run_matches_the_model(self):
        sout = os.path.join(LEAF, "actors.sout")
        if not os.path.exists(sout):
            self.skipTest("the trial has not been run in this tree")
        self.assertEqual(read_lines(sout), ActorSim().lines())

    def test_actor_script_properties(self):
        a = ActorSim()
        a.lines()
        self.assertEqual(a.failed, 1, "the shuffle with the peer that does not exist fails once, then the peer is gone")
        for st in a.world:
            self.assertTrue(view.valid(st.view, st.me[0], a.CAP))
            self.assertFalse(any(e[0] == "n9" for e in st.view))

    def test_store_of_another_type_does_not_drain(self):
        """NQ-15: with the partner put back the store keeps its entries; by the rules before the ruling it empties"""
        self.assertEqual([len(s.view) for s in drain(False, 12)], [3] * 13)
        self.assertEqual([len(s.view) for s in drain(False, 12, put_back=False)][:4], [3, 2, 1, 0])
        self.assertTrue(all(view.valid(s.view, "me", 4) for s in drain(False, 12)))
        # a store of the node's own type is unchanged by the ruling: its partner is not put back
        own = drain(True, 1)[1]
        self.assertEqual(len(own.view), 2)

    def test_sentinel_edge_store_over_many_ticks(self):
        """NQ-15 as a model run, 500 rounds: the sentinel's edge store keeps every edge; before the ruling it emptied"""
        self.assertEqual(set(Sentinel(True, 2, 3, 2).sizes(500)), {2})
        before = Sentinel(False, 2, 3, 2).sizes(500)
        self.assertEqual(before[:3], [1, 1, 0])
        self.assertEqual(set(before[2:]), {0})
        # five edges, room for four: full at every round; before the ruling it fell to two
        self.assertEqual(set(Sentinel(True, 5, 4, 2).sizes(500)), {4})
        self.assertEqual(min(Sentinel(False, 5, 4, 2).sizes(500)), 2)

    def test_silent_peer_is_forgotten(self):
        s = Sim()
        s.lines()
        self.assertTrue(s.ok)
        self.assertGreater(s.failures, 0)
        self.assertEqual(s.holders(), 0, "the peer that never answers is still in a view after the run")
        for st in s.world:
            self.assertTrue(st.view)
            self.assertEqual(st.phase, 0)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "expected":
        print("\n".join(expected()))
    elif len(sys.argv) > 1 and sys.argv[1] == "expected-actors":
        print("\n".join(ActorSim().lines()))
    else:
        unittest.main()
