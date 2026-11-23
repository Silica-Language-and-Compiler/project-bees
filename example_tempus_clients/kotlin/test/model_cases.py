#!/usr/bin/env python3
"""TEST ONLY. Writes the cases the Kotlin view and store are checked against (test/NodeTestMain.kt reads them).

    model_cases.py OUT_FILE

Two independent Python models state the rules of a store a second time: tools/bees_tempus_view_model.py and
tools/bees_tempus_store_model.py. The tests tools/test_bees_tempus_view.py and tools/test_bees_tempus_store.py compute
with them every line of the goldens of trials/t0_tempus_view and trials/t1_tempus_store. This tool runs those same
computations with every call of a model function recorded (its inputs and its answer; for a store's step also the
store before and after), checks that the lines so computed ARE the recorded goldens, and then records the same kinds
of call on views and stores made from a fixed generator. Each recorded call is one line of OUT_FILE; the Kotlin test
makes the same call and must get the same answer. Nothing here is part of the extension.
"""
import glob
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import bees_tempus_view_model as vm  # noqa: E402
import bees_tempus_store_model as sm  # noqa: E402

LINES = []


def ent(e):
    return "-" if e is None else "%s~%s~%d" % (e[0], e[1], e[2])


def view(v):
    return ",".join(ent(e) for e in v) if v else "-"


def draws(d):
    if d is None:
        return "N"
    d = list(d.values) if isinstance(d, vm.Draws) else list(d)
    return ",".join(str(x) for x in d) if d else "-"


def rec(*parts):
    LINES.append("|".join(str(p) for p in parts))


def wrap_view():
    o = {n: getattr(vm, n) for n in ("age_all", "select", "outgoing", "reply_select", "merge", "prefer_sent", "backfill", "insert", "sample", "valid")}

    def age_all(v):
        r = o["age_all"](v); rec("V", "ageAll", view(v), view(r)); return r

    def select(v, length, d):
        d = list(d); r = o["select"](v, length, d)
        rec("V", "select", view(v), length, draws(d), int(r[0]), ent(r[1]), view(r[2]), view(r[3])); return r

    def outgoing(i, d, sent):
        r = o["outgoing"](i, d, sent); rec("V", "outgoing", i, d, view(sent), view(r)); return r

    def reply_select(v, length, asker, d):
        d = list(d); r = o["reply_select"](v, length, asker, d)
        rec("V", "replySelect", view(v), length, asker, draws(d), view(r[0]), view(r[1])); return r

    def merge(rest, received, i, cap):
        r = o["merge"](rest, received, i, cap); rec("V", "merge", view(rest), view(received), i, cap, view(r)); return r

    def prefer_sent(received, sent):
        r = o["prefer_sent"](received, sent); rec("V", "preferSent", view(received), view(sent), view(r)); return r

    def backfill(v, sent, cap):
        r = o["backfill"](v, sent, cap); rec("V", "backfill", view(v), view(sent), cap, view(r)); return r

    def insert(v, e, i, cap):
        r = o["insert"](v, e, i, cap); rec("V", "insert", view(v), ent(e), i, cap, view(r)); return r

    def sample(v, n, d):
        d = list(d); r = o["sample"](v, n, d); rec("V", "sample", view(v), n, draws(d), view(r)); return r

    def valid(v, i, cap):
        r = o["valid"](v, i, cap); rec("V", "valid", view(v), i, cap, int(r)); return r

    for f in (age_all, select, outgoing, reply_select, merge, prefer_sent, backfill, insert, sample, valid):
        setattr(vm, f.__name__, f)


def state(s):
    return "|".join([s.me[0], s.me[1], str(int(s.own)), str(s.cap), str(s.count), view(s.view), view(s.sent), ent(s.partner),
                     draws(s.tick_draws), draws(s.reply_draws)])


def wrap_store():
    S = sm.Store
    o = {n: getattr(S, n) for n in ("insert", "drop", "tick", "failed", "reply", "request", "sample")}

    def step(name, args, show):
        def f(self, *a):
            before = state(self)
            r = o[name](self, *a)
            rec("S", before, name, args(*a), show(r), state(self))
            return r
        setattr(S, name, f)

    def tick_show(r):
        return r[0] if r[0] != "shuffle" else "shuffle;%s;%s" % (ent(r[1]), view(r[2]))

    step("insert", lambda e: ent(e), lambda r: "")
    step("drop", lambda p: p, lambda r: "")
    step("tick", lambda: "", tick_show)
    step("failed", lambda: "", lambda r: "")
    step("reply", lambda received: view(received), lambda r: "")
    step("request", lambda asker, received: asker + ";" + view(received), lambda r: "N" if r is None else view(r))
    step("sample", lambda n: str(n), lambda r: "N" if r is None else view(r))


def goldens():
    import test_bees_tempus_view as tv
    import test_bees_tempus_store as ts
    said = 0
    for mod, leaf, name in ((tv, "t0_tempus_view", "view"), (ts, "t1_tempus_store", "steps")):
        want = mod.expected()
        files = sorted(glob.glob(os.path.join(ROOT, "trials", leaf, name + ".*.scout")))
        if not files:
            raise SystemExit("FAIL: no golden of trials/%s to compare with" % leaf)
        for path in files:
            if mod.read_lines(path) != want:
                raise SystemExit("FAIL: the model's lines are not the golden %s" % path)
            said += 1
    # the store-actor script of the T1 trial and the long runs of the store test use the store model too
    ts.ActorSim().lines()
    ts.Sentinel(True, 20, 8, 3).sizes(60)
    return said


def generated(count):
    r = random.Random(20261123)
    names = ["p%d" % k for k in range(12)]

    def some_view(most=8):
        ids = r.sample(names, r.randint(0, most))
        return [(i, "@" + i + str(r.randint(0, 3)), r.choice([0, 0, 1, 2, 5, 5, 9, 65534, 65535])) for i in ids]

    def some_draws():
        return [r.choice([-3, 0, 1, 2, 7, 11, 255, 72057594037927935]) for _ in range(r.randint(0, 6))]

    def loose(most=6):
        return [(r.choice(names), "@x" + str(r.randint(0, 3)), r.randint(0, 9)) for _ in range(r.randint(0, most))]

    for _ in range(count):
        v, me, cap, length = some_view(), r.choice(names), r.randint(1, 8), r.randint(1, 5)
        vm.age_all(v)
        vm.select(v, length, some_draws())
        vm.reply_select(v, length, r.choice(names), some_draws())
        vm.merge([e for e in v if e[0] != me], loose(), me, cap)
        vm.prefer_sent(loose(), loose())
        vm.backfill(v, loose(), cap)
        vm.sample(v, r.randint(0, 9), some_draws())
        vm.valid(v, me, cap)
        s = sm.Store(me, "@me", r.random() < 0.5, cap, min(length, cap))
        for _ in range(r.randint(3, 14)):
            if r.random() < 0.5:
                s.tick_draws = some_draws()
            if r.random() < 0.5:
                s.reply_draws = some_draws()
            k = r.randint(0, 6)
            if k == 0:
                s.insert((r.choice(names), "@i", r.randint(0, 4)))
            elif k == 1:
                s.drop(r.choice(names))
            elif k == 2:
                s.tick()
            elif k == 3:
                s.failed()
            elif k == 4:
                s.reply(loose(5))
            elif k == 5:
                s.request(r.choice(names), loose(5))
            else:
                s.sample(r.randint(0, 6))


def main(argv):
    if len(argv) != 2:
        print(__doc__)
        return 2
    wrap_view()
    wrap_store()
    files = goldens()
    from_goldens = len(LINES)
    generated(400)
    with open(argv[1], "w") as f:
        f.write("# goldens %d\n# from the goldens' computations %d\n" % (files, from_goldens))
        f.write("".join(ln + "\n" for ln in LINES))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
