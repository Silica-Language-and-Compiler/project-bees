#!/usr/bin/env python3
"""Compare the view and store rules of the Swift TEMPUS extension (Sources/TempusNode/View.swift) with the two
independent Python models of the BEES tools (tools/bees_tempus_view_model.py, tools/bees_tempus_store_model.py), which
the BEES tools tests compare with the Silica units and their recorded trial outputs.

    model_check.py PATH_OF_tempus-node-tests

Cases are generated from a fixed seed, so every run makes the same ones: single calls of every view function, and runs
of store events (ticks, replies, failures, requests, samples, inserts, drops) on stores of both kinds. Each case is
answered by the Swift program (`tempus-node-tests model`) and by the model, and the two lines must be equal.
"""
import json
import os
import random
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "..", "tools"))
import bees_tempus_store_model as sm  # noqa: E402
import bees_tempus_view_model as vm  # noqa: E402

R = random.Random(20261123)
IDS = "abcdefghij"


def show(view):
    return " ".join("%s:%d/%s" % (i, a, d) for (i, d, a) in view) if view else "(empty)"


def wire(view):
    return [[i, d, a] for (i, d, a) in view]


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


def view_cases():
    out = []
    for _ in range(400):
        v, ds, n, cap = some_view(), some_draws(), R.randrange(0, 6), R.randrange(1, 7)
        me = R.choice(IDS)
        k = R.randrange(9)
        if k == 0:
            out.append(({"op": "age_all", "view": wire(v)}, show(vm.age_all(v))))
        elif k == 1:
            found, partner, sent, rest = vm.select(v, n, ds)
            out.append(({"op": "select", "view": wire(v), "n": n, "draws": ds},
                        "partner %s | sent %s | rest %s" % (show([partner]), show(sent), show(rest)) if found else "none"))
        elif k == 2:
            asker = R.choice(IDS)
            sent, rest = vm.reply_select(v, n, asker, ds)
            out.append(({"op": "reply_select", "view": wire(v), "n": n, "asker": asker, "draws": ds}, "sent %s | rest %s" % (show(sent), show(rest))))
        elif k == 3:
            rest, rcv = some_view(without=(me,)), some_list()
            out.append(({"op": "merge", "view": wire(rest), "received": wire(rcv), "self": me, "cap": cap}, show(vm.merge(rest, rcv, me, cap))))
        elif k == 4:
            rcv, sent = some_list(), some_view()
            out.append(({"op": "prefer_sent", "received": wire(rcv), "sent": wire(sent)}, show(vm.prefer_sent(rcv, sent))))
        elif k == 5:
            sent = some_view()
            out.append(({"op": "backfill", "view": wire(v), "sent": wire(sent), "cap": cap}, show(vm.backfill(v, sent, cap))))
        elif k == 6:
            rest, e = some_view(without=(me,)), some_list(1) or [("a", "r", 0)]
            out.append(({"op": "insert", "view": wire(rest), "received": wire(e[:1]), "self": me, "cap": cap}, show(vm.insert(rest, e[0], me, cap))))
        elif k == 7:
            out.append(({"op": "sample", "view": wire(v), "n": n, "draws": ds}, show(vm.sample(v, n, ds))))
        else:
            out.append(({"op": "valid", "view": wire(v), "self": me, "cap": cap}, "yes" if vm.valid(v, me, cap) else "no"))
    return out


def store_cases():
    out = []
    for run in range(60):
        me, own, cap = R.choice(IDS), R.random() < 0.5, R.randrange(1, 7)
        count = R.randrange(1, cap + 1)
        s = sm.Store(me, "@" + me, own, cap, count)
        out.append(({"op": "store.new", "self": me, "own": own, "cap": cap, "n": count}, "new"))
        for _ in range(40):
            k = R.randrange(8)
            ds = None if R.random() < 0.1 else some_draws()
            if k == 0:
                s.tick_draws = ds
                t = s.tick()
                head = t[0] if t[0] != "shuffle" else "shuffle %s | out %s" % (show([t[1]]), show(t[2]))
                out.append(({"op": "store.tick", "draws": ds}, "%s | %s" % (head, show(s.view))))
            elif k == 1:
                s.failed()
                out.append(({"op": "store.failed"}, show(s.view)))
            elif k == 2:
                rcv = some_list(count + 1)
                s.reply(rcv)
                out.append(({"op": "store.reply", "received": wire(rcv)}, show(s.view)))
            elif k == 3:
                asker, rcv = R.choice(IDS), some_list(count + 1)
                s.reply_draws = ds
                got = s.request(asker, rcv)
                out.append(({"op": "store.request", "asker": asker, "received": wire(rcv), "draws": ds},
                            "%s | %s" % ("refused" if got is None else show(got), show(s.view))))
            elif k == 4:
                n = R.randrange(0, cap + 2)
                s.reply_draws = ds
                got = s.sample(n)
                out.append(({"op": "store.sample", "n": n, "draws": ds}, "%s | %s" % ("refused" if got is None else show(got), show(s.view))))
            elif k in (5, 6):
                e = (R.choice([i for i in IDS if i != me]), "i%d" % R.randrange(100), R.randrange(5))
                s.insert(e)
                out.append(({"op": "store.insert", "received": wire([e])}, show(s.view)))
            else:
                peer = R.choice(IDS)
                s.drop(peer)
                out.append(({"op": "store.drop", "id": peer}, show(s.view)))
            assert vm.valid(s.view, me, cap), "the model's own view is not valid"
    return out


def main(argv):
    if len(argv) != 2:
        print(__doc__)
        return 2
    cases = view_cases() + store_cases()
    r = subprocess.run([argv[1], "model"], input="".join(json.dumps(c) + "\n" for c, _ in cases), capture_output=True, text=True, timeout=120)
    got = r.stdout.split("\n")[:-1]
    bad = 0
    if r.returncode != 0 or len(got) != len(cases):
        print("FAILED: the Swift program answered %d of %d cases (exit %d) %s" % (len(got), len(cases), r.returncode, r.stderr[-400:]))
        return 1
    for (c, want), line in zip(cases, got):
        if line != want:
            bad += 1
            if bad <= 5:
                print("FAILED: %s\n   swift: %s\n   model: %s" % (json.dumps(c), line, want))
    print("model_check: %d passed, %d failed" % (len(cases) - bad, bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
