#!/usr/bin/env python3
"""Compare the view and store rules of the Rust TEMPUS extension (lib/tempus/src/node/view.rs) with what the Silica
library was shown to do, and with the two independent Python models of the BEES tools.

    model_check.py PATH_OF_tempus-model BEES_ROOT

The Rust rules are reached through the program tempus-model (test/tempus-tests/src/bin/tempus-model.rs), which answers
one call per line. Two parts:

  recorded   the tools' own tests of the view and of the store (tools/test_bees_tempus_view.py,
             tools/test_bees_tempus_store.py) are run with the Rust rules in the place of the two models. Those tests
             compute every line of the recorded outputs of trials/t0_tempus_view and trials/t1_tempus_store again and
             compare. So every line the Silica view and store printed is computed here by the Rust code.
  generated  cases from a fixed seed, so every run makes the same ones: single calls of every view function, and runs
             of store events (ticks, replies, failures, requests, samples, inserts, drops) on stores of both kinds.
             Each case is answered by the Rust code and by the Python model, and the two must be equal.
"""
import os
import random
import subprocess
import sys
import types
import unittest

RUST = None


def enc(view):
    return ",".join("%s/%s/%d" % (i, d, a) for (i, d, a) in view) if view else "-"


def dec(text):
    if text == "-":
        return []
    out = []
    for e in text.split(","):
        i, d, a = e.split("/", 2)
        out.append((i, d, int(a)))
    return out


def draws(ds):
    return "none" if ds is None else (",".join(str(d) for d in ds) if ds else "-")


def ask(op, **fields):
    RUST.stdin.write(op + "".join("\t%s=%s" % kv for kv in fields.items()) + "\n")
    RUST.stdin.flush()
    line = RUST.stdout.readline()
    if not line:
        raise SystemExit("FAIL: [rust model] tempus-model ended: " + RUST.stderr.read())
    return line.rstrip("\n").split("\t")


# ---------------------------------------------------------------- the Rust rules with the models' interface
AGE_MAX = 65535


def age_all(view):
    return dec(ask("age_all", view=enc(view))[0])


def select(view, length, draw_values):
    r = ask("select", view=enc(view), n=length, draws=draws(list(draw_values)))
    if r == ["none"]:
        return False, None, [], []
    return True, dec(r[0])[0], dec(r[1]), dec(r[2])


def outgoing(self_id, self_d, sent):
    return [(self_id, self_d, 0)] + list(sent)


def reply_select(view, length, asker, draw_values):
    r = ask("reply_select", view=enc(view), n=length, asker=asker, draws=draws(list(draw_values)))
    return dec(r[0]), dec(r[1])


def merge(rest, received, self_id, cap):
    return dec(ask("merge", view=enc(rest), received=enc(received), self=self_id, cap=cap)[0])


def prefer_sent(received, sent):
    return dec(ask("prefer_sent", received=enc(received), sent=enc(sent))[0])


def backfill(view, sent, cap):
    return dec(ask("backfill", view=enc(view), sent=enc(sent), cap=cap)[0])


def insert(view, e, self_id, cap):
    return dec(ask("insert", view=enc(view), received=enc([e]), self=self_id, cap=cap)[0])


def sample(view, n, draw_values):
    return dec(ask("sample", view=enc(view), n=n, draws=draws(list(draw_values)))[0])


def valid(view, self_id, cap):
    return ask("valid", view=enc(view), self=self_id, cap=cap)[0] == "yes"


class Store:
    """One store whose every step is computed by the Rust code. The state is held here, so that a test may copy it."""

    def __init__(self, self_id, self_d, own, cap, count):
        self.me, self.own, self.cap, self.count = (self_id, self_d), own, cap, count
        self.view, self.sent, self.partner = [], [], None
        self.tick_draws = self.reply_draws = None

    @property
    def phase(self):
        return 1 if self.partner is not None else 0

    def _step(self, op, **fields):
        r = ask(op, self=self.me[0], selfd=self.me[1], own=1 if self.own else 0, cap=self.cap, count=self.count, view=enc(self.view),
                sent=enc(self.sent), partner=enc([self.partner] if self.partner else []), **fields)
        self.view, self.sent = dec(r[0]), dec(r[1])
        self.partner = (dec(r[2]) or [None])[0]
        return r[3:]

    def insert(self, e):
        self._step("store.insert", received=enc([e]))

    def drop(self, peer):
        self._step("store.drop", id=peer)

    def tick(self):
        r = self._step("store.tick", draws=draws(self.tick_draws))
        if r[0] == "shuffle":
            self.tick_draws = None
            return ("shuffle", dec(r[1])[0], dec(r[2]))
        return (r[0],)

    def failed(self):
        self._step("store.failed")

    def reply(self, received):
        self._step("store.reply", received=enc(received))

    def request(self, asker, received):
        r = self._step("store.request", asker=asker, received=enc(received), draws=draws(self.reply_draws))
        if r[0] == "refused":
            return None
        self.reply_draws = None
        return dec(r[0])

    def sample(self, n):
        r = self._step("store.sample", n=n, draws=draws(self.reply_draws))
        if r[0] == "refused":
            return None
        self.reply_draws = None
        return dec(r[0])


# ---------------------------------------------------------------- recorded: the tools' tests over the Rust rules
def recorded(root):
    here = sys.modules[__name__]
    fake = types.ModuleType("bees_tempus_store_model")
    fake.Store = Store
    sys.modules["bees_tempus_view_model"] = here
    sys.modules["bees_tempus_store_model"] = fake
    try:
        import test_bees_tempus_store as ts
        import test_bees_tempus_view as tv
        assert tv.m is here and ts.view is here and ts.Store is Store, "the tools' tests did not take the Rust rules"
        suite = unittest.TestSuite()
        suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(tv))
        suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(ts))
        result = unittest.TestResult()
        suite.run(result)
    finally:
        del sys.modules["bees_tempus_view_model"], sys.modules["bees_tempus_store_model"]
    for _t, text in result.failures + result.errors:
        print("FAILED: " + text)
    ran = result.testsRun - len(result.skipped)
    for leaf, name in (("t0_tempus_view", "view"), ("t1_tempus_store", "steps")):
        if not any(f.startswith(name + ".") and f.endswith(".scout") for f in os.listdir(os.path.join(root, "trials", leaf))):
            print("FAILED: no recorded output %s.*.scout in trials/%s" % (name, leaf))
            return ran, 1
    # A test of the tools that compares with a trial's output of this tree is skipped when that trial has not been run in
    # this tree (a fresh checkout). That is not a failure: the recorded outputs (.scout) are still computed again here.
    for _t, why in result.skipped:
        print("skipped: " + why)
    return ran, len(result.failures) + len(result.errors)


# ---------------------------------------------------------------- generated: the Rust rules beside the two models
R = random.Random(20261123)
IDS = "abcdefghij"


def some_view(lo=0, hi=7, ages=6, without=()):
    ids = [i for i in IDS if i not in without]
    R.shuffle(ids)
    return [(i, "%s%d" % (i, R.randrange(100)), R.choice([0, 1, 2, 3, ages, 65534, 65535]) if R.random() < 0.2 else R.randrange(ages))
            for i in ids[:R.randrange(lo, hi + 1)]]


def some_list(hi=6):
    """received entries: may repeat a peer and may name the node itself"""
    return [(R.choice(IDS), "r%d" % R.randrange(100), R.randrange(8)) for _ in range(R.randrange(0, hi + 1))]


def some_draws():
    return [R.choice([-1, 0, 1, 2, 3, 5, 7, 11, 1000003]) for _ in range(R.randrange(0, 8))]


def generated(vm, sm):
    bad = n = 0

    def same(what, got, want):
        nonlocal bad, n
        n += 1
        if got != want:
            bad += 1
            if bad <= 5:
                print("FAILED: %s\n   rust:  %r\n   model: %r" % (what, got, want))

    for _ in range(400):
        v, ds, k, cap = some_view(), some_draws(), R.randrange(0, 6), R.randrange(1, 7)
        me, asker = R.choice(IDS), R.choice(IDS)
        rest, rcv, sent = some_view(without=(me,)), some_list(), some_view()
        same("age_all %r" % (v,), age_all(v), vm.age_all(v))
        same("select %r %d %r" % (v, k, ds), select(v, k, ds), vm.select(v, k, ds))
        same("reply_select %r %d %s %r" % (v, k, asker, ds), reply_select(v, k, asker, ds), vm.reply_select(v, k, asker, ds))
        same("merge %r %r %s %d" % (rest, rcv, me, cap), merge(rest, rcv, me, cap), vm.merge(rest, rcv, me, cap))
        same("prefer_sent %r %r" % (rcv, sent), prefer_sent(rcv, sent), vm.prefer_sent(rcv, sent))
        same("backfill %r %r %d" % (v, sent, cap), backfill(v, sent, cap), vm.backfill(v, sent, cap))
        e = (some_list(1) or [("a", "r", 0)])[0]
        same("insert %r %r %s %d" % (rest, e, me, cap), insert(rest, e, me, cap), vm.insert(rest, e, me, cap))
        same("sample %r %d %r" % (v, k, ds), sample(v, k, ds), vm.sample(v, k, ds))
        same("valid %r %s %d" % (v, me, cap), valid(v, me, cap), vm.valid(v, me, cap))
    for run in range(60):
        me, own, cap = R.choice(IDS), R.random() < 0.5, R.randrange(1, 7)
        count = R.randrange(1, cap + 1)
        a, b = Store(me, "@" + me, own, cap, count), sm.Store(me, "@" + me, own, cap, count)
        for step in range(40):
            k = R.randrange(8)
            ds = None if R.random() < 0.1 else some_draws()
            what = "run %d step %d" % (run, step)
            if k == 0:
                a.tick_draws, b.tick_draws = ds, (None if ds is None else list(ds))
                same(what + " tick", a.tick(), b.tick())
            elif k == 1:
                a.failed(), b.failed()
            elif k == 2:
                rcv = some_list(count + 1)
                a.reply(rcv), b.reply(rcv)
            elif k == 3:
                asker, rcv = R.choice(IDS), some_list(count + 1)
                a.reply_draws, b.reply_draws = ds, (None if ds is None else list(ds))
                same(what + " request", a.request(asker, rcv), b.request(asker, rcv))
            elif k == 4:
                q = R.randrange(0, cap + 2)
                a.reply_draws, b.reply_draws = ds, (None if ds is None else list(ds))
                same(what + " sample", a.sample(q), b.sample(q))
            elif k in (5, 6):
                e = (R.choice([i for i in IDS if i != me]), "i%d" % R.randrange(100), R.randrange(5))
                a.insert(e), b.insert(e)
            else:
                peer = R.choice(IDS)
                a.drop(peer), b.drop(peer)
            same(what + " state", (a.view, a.sent, a.partner), (b.view, b.sent, b.partner))
            assert vm.valid(b.view, me, cap), "the model's own view is not valid"
    return n, bad


def main(argv):
    global RUST
    if len(argv) != 3:
        print(__doc__)
        return 2
    root = os.path.abspath(argv[2])
    sys.path.insert(0, os.path.join(root, "tools"))
    import bees_tempus_store_model as sm
    import bees_tempus_view_model as vm
    RUST = subprocess.Popen([argv[1]], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        n, bad = generated(vm, sm)
        ran, failed = recorded(root)
    finally:
        RUST.stdin.close()
        RUST.wait(timeout=10)
    print("rust model check: %d generated answers compared with the Python models, %d differ; %d of the tools' view and store "
          "tests run over the Rust rules (the recorded outputs of trials/t0_tempus_view and t1_tempus_store), %d failed" % (n, bad, ran, failed))
    return 1 if bad or failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
