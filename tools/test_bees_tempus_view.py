#!/usr/bin/env python3
"""Tests of the TEMPUS view logic (T0, development-plan/tempus-design.md section 3).

The trial trials/t0_tempus_view runs src/tempus/bees_tempus_view.silica and prints one line per case and the views of an
eight-node, ten-round run. This test computes every one of those lines again with the independent model
tools/bees_tempus_view_model.py and compares:
  - with every recorded golden of the trial (view.<platform>.scout), and
  - with the last run's output (view.sout) when there is one.
It also checks properties of the model's own run that no single line shows (entries are conserved by an exchange, no view
ever names its own node, capacity holds).

    python3 tools/test_bees_tempus_view.py
"""
import glob
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import bees_tempus_view_model as m  # noqa: E402

LEAF = os.path.join(ROOT, "trials", "t0_tempus_view")


def ent(i, age):
    return (i, "@" + i, age)


def show(view):
    return " ".join("%s:%d" % (i, a) for (i, _, a) in view) if view else "(empty)"


def showd(view):
    return " ".join("%s:%d/%s" % (i, a, d) for (i, d, a) in view)


def yes(b):
    return "yes" if b else "no"


BASE = [ent("a", 3), ent("b", 5), ent("c", 5), ent("d", 1), ent("e", 0)]


def sel_lines(name, view, length, draws):
    found, partner, sent, rest = m.select(view, length, draws)
    return ["%s: found %s" % (name, yes(found)),
            "%s: partner %s" % (name, "%s:%d" % (partner[0], partner[2]) if found else "(none)"),
            "%s: sent: %s" % (name, show(sent)),
            "%s: rest: %s" % (name, show(rest))]


def rep_lines(name, view, length, asker, draws):
    sent, rest = m.reply_select(view, length, asker, draws)
    return ["%s: sent: %s" % (name, show(sent)), "%s: rest: %s" % (name, show(rest))]


def part_one():
    out = []
    out.append("age_all: " + show(m.age_all(BASE)))
    out.append("age_all at the bound: " + show(m.age_all([ent("t", 65535), ent("u", 65534)])))
    out.append("age_all of an empty view: " + show(m.age_all([])))
    out += sel_lines("select len 3 draws 1 0 1", BASE, 3, [1, 0, 1])
    out += sel_lines("select len 3 draws 0 7 5", BASE, 3, [0, 7, 5])
    out += sel_lines("select len 3 no draws", BASE, 3, [])
    out += sel_lines("select len 1", BASE, 1, [1, 0, 1])
    out += sel_lines("select len 9", BASE, 9, [1, 0, 1])
    out += sel_lines("select on an empty view", [], 3, [1, 0, 1])
    out += sel_lines("select len 2 negative draws", BASE, 2, [-4, -1, 2])
    _, _, sent, _ = m.select(BASE, 3, [1, 0, 1])
    out.append("outgoing: " + showd(m.outgoing("me", "@me", sent)))
    out += rep_lines("reply_select len 2 asker d", BASE, 2, "d", [2, 2, 0])
    out += rep_lines("reply_select len 3 asker x", BASE, 3, "x", [2, 2, 0])
    out += rep_lines("reply_select only the asker", [ent("d", 4)], 3, "d", [2, 2, 0])
    kept = [ent("b", 5), ent("e", 0)]
    r1 = [ent("me", 0), ent("x", 2), ent("y", 7)]
    out.append("merge drops self: " + show(m.merge(kept, r1, "me", 5)))
    out.append("merge prefers younger: " + show(m.merge(kept, [ent("b", 2), ent("e", 3)], "me", 5)))
    out.append("merge takes the younger entry whole: " + showd(m.merge(kept, [("b", "new", 2)], "me", 5)))
    out.append("merge at equal age keeps its own: " + showd(m.merge(kept, [("b", "new", 5)], "me", 5)))
    out.append("merge with a peer twice in the buffer: "
               + show(m.merge(kept, [ent("x", 6), ent("y", 4), ent("x", 1), ent("x", 3)], "me", 5)))
    out.append("merge evicts the oldest: " + show(m.merge(kept, [ent("x", 2), ent("y", 7), ent("z", 1)], "me", 3)))
    k2 = [ent("b", 4), ent("f", 4), ent("g", 1)]
    r7 = [ent("p", 4), ent("q", 4)]
    out.append("merge eviction at equal age: " + show(m.merge(k2, r7, "me", 3)))
    out.append("merge to capacity 1: " + show(m.merge(k2, r7, "me", 1)))
    out.append("merge eviction among received: " + show(m.merge([], [ent("p", 4), ent("q", 4), ent("r", 4)], "me", 2)))
    out.append("merge of nothing: " + show(m.merge(kept, [], "me", 5)))
    out.append("merge to capacity 0: " + show(m.merge(kept, r1, "me", 0)))
    v = [ent("x", 2), ent("b", 5)]
    sent = [ent("a", 3), ent("b", 9), ent("d", 1)]
    out.append("backfill with room: " + show(m.backfill(v, sent, 4)))
    out.append("backfill to capacity: " + show(m.backfill(v, sent, 3)))
    out.append("backfill of a full view: " + show(m.backfill(v, sent, 2)))
    _, _, s_sent, s_rest = m.select(BASE, 3, [1, 0, 1])
    out.append("after a failed shuffle: " + show(m.backfill(s_rest, s_sent, 5)))
    out.append("size: %d" % len(BASE))
    out.append("member c: " + yes(any(e[0] == "c" for e in BASE)))
    out.append("member x: " + yes(any(e[0] == "x" for e in BASE)))
    out.append("remove c: " + show([e for e in BASE if e[0] != "c"]))
    out.append("remove x: " + show([e for e in BASE if e[0] != "x"]))
    out.append("insert into a full view: " + show(m.insert(BASE, ent("n", 0), "me", 5)))
    out.append("insert of self: " + show(m.insert(BASE, ent("me", 0), "me", 5)))
    out.append("sample 2: " + show(m.sample(BASE, 2, [4, 0, 0])))
    out.append("sample 9 of five: " + show(m.sample(BASE, 9, [4, 0, 0])))
    out.append("valid base, cap 5: " + yes(m.valid(BASE, "me", 5)))
    out.append("valid base, cap 4: " + yes(m.valid(BASE, "me", 4)))
    out.append("valid base, self a: " + yes(m.valid(BASE, "a", 5)))
    out.append("valid with an id twice: " + yes(m.valid([ent("a", 1), ent("a", 2)], "me", 5)))
    out.append("valid with age 65536: " + yes(m.valid([ent("a", 65536)], "me", 5)))
    out.append("valid with age -1: " + yes(m.valid([ent("a", -1)], "me", 5)))
    out.append("valid with an empty id: " + yes(m.valid([ent("", 1)], "me", 5)))
    return out


class Sim:
    """Part 2 of the trial: eight nodes, capacity 4, shuffle length 3, the trial's TEST-ONLY generator and seeds."""
    N, CAP, LEN, SEED = 8, 4, 3, 20261118

    def __init__(self):
        self.world = [[ent("n%d" % ((i + k) % self.N), 0) for k in (1, 2, 3, 4)] for i in range(self.N)]
        self.ok = True
        self.done = 0
        self.conserved = True

    def draws(self, x, k):
        out = []
        for _ in range(k):
            x = (x * 1103515245 + 12345) % 2147483648
            out.insert(0, x // 65536)  # the trial builds the list by prepending
        return out

    def step(self, r, i):
        me = "n%d" % i
        seed = self.SEED + r * 1000 + i * 10
        aged = m.age_all(self.world[i])
        found, partner, sent, rest = m.select(aged, self.LEN, self.draws(seed, self.LEN))
        if not found:
            self.world[i] = aged
            return
        q = int(partner[0][1:])
        qname = "n%d" % q
        r_sent, r_rest = m.reply_select(self.world[q], self.LEN, me, self.draws(seed + 1, self.LEN))
        before = len(aged) + len(self.world[q])
        q2 = m.backfill(m.merge(r_rest, m.outgoing(me, "@" + me, sent), qname, self.CAP), r_sent, self.CAP)
        p2 = m.backfill(m.merge(rest, r_sent, me, self.CAP), sent, self.CAP)
        self.ok = self.ok and m.valid(p2, me, self.CAP) and m.valid(q2, qname, self.CAP)
        # an exchange never makes entries: together the two views hold at most what they held, plus the initiator's own entry
        self.conserved = self.conserved and len(p2) + len(q2) <= before + 1
        self.world[i], self.world[q] = p2, q2
        self.done += 1

    def lines(self):
        out = ["start"] + self.world_lines()
        for r in range(1, 11):
            for i in range(self.N):
                self.step(r, i)
            if r in (1, 10):
                out.append("after round %d" % r)
                out += self.world_lines()
        out.append("every view valid after every exchange: " + yes(self.ok))
        indeg = [sum(1 for v in self.world if any(e[0] == "n%d" % i for e in v)) for i in range(self.N)]
        out.append("in how many views each node is:" + "".join(" %d" % k for k in indeg))
        return out

    def world_lines(self):
        return ["  n%d: %s" % (i, show(v)) for i, v in enumerate(self.world)]


def expected():
    return part_one() + Sim().lines() + ["exit=0"]


def read_lines(path):
    with open(path) as f:
        return [line.rstrip("\n") for line in f if line.strip() != ""]


class ViewRules(unittest.TestCase):
    def test_goldens_match_the_model(self):
        goldens = sorted(glob.glob(os.path.join(LEAF, "view.*.scout")))
        self.assertTrue(goldens, "no golden recorded in trials/t0_tempus_view")
        for g in goldens:
            self.assertEqual(read_lines(g), expected(), g)

    def test_last_run_matches_the_model(self):
        sout = os.path.join(LEAF, "view.sout")
        if not os.path.exists(sout):
            self.skipTest("the trial has not been run in this tree")
        self.assertEqual(read_lines(sout), expected())

    def test_model_run_properties(self):
        s = Sim()
        s.lines()
        self.assertTrue(s.ok)
        self.assertTrue(s.conserved)
        self.assertEqual(s.done, 80)
        for i, v in enumerate(s.world):
            self.assertTrue(v, "node %d ended with an empty view" % i)
            self.assertLessEqual(len(v), s.CAP)

    def test_model_hand_cases(self):
        # the cases whose answers are worked by hand in the comments of trials/t0_tempus_view/view.silica
        self.assertEqual(m.select(BASE, 3, [1, 0, 1]),
                         (True, ent("c", 5), [ent("a", 3), ent("d", 1)], [ent("b", 5), ent("e", 0)]))
        self.assertEqual(m.select(BASE, 3, [0, 7, 5]),
                         (True, ent("b", 5), [ent("e", 0), ent("d", 1)], [ent("a", 3), ent("c", 5)]))
        self.assertEqual(show(m.merge([ent("b", 4), ent("f", 4), ent("g", 1)], [ent("p", 4), ent("q", 4)], "me", 3)),
                         "p:4 q:4 g:1")
        self.assertEqual(show(m.backfill([ent("x", 2), ent("b", 5)], [ent("a", 3), ent("b", 9), ent("d", 1)], 4)),
                         "x:2 b:5 a:3 d:1")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "expected":
        print("\n".join(expected()))
    else:
        unittest.main()
