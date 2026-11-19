#!/usr/bin/env python3
"""An independent model of the TEMPUS view rules (development-plan/tempus-design.md section 3), for tests only.

The Silica unit src/tempus/bees_tempus_view.silica is the implementation. This file states the same rules a second time, in a
different style (Python lists and dictionaries, loops), so that tools/test_bees_tempus_view.py can compare the two: agreement
is then evidence about the rules and not one mistake copied twice. Nothing in BEES imports this at run time.

An entry is a tuple (id, d, age). A view is a list of entries. Draws are a list of integers; a missing or negative draw is 0.
"""

AGE_MAX = 65535


class Draws:
    def __init__(self, values):
        self.values = list(values)

    def take(self):
        v = self.values.pop(0) if self.values else 0
        return v if v >= 0 else 0


def age_all(view):
    return [(i, d, min(a + 1, AGE_MAX)) for (i, d, a) in view]


def pick(view, k, draws):
    """k entries drawn without replacement, in the order drawn, and what is left."""
    left = list(view)
    taken = []
    while k > 0 and left:
        taken.append(left.pop(draws.take() % len(left)))
        k -= 1
    return taken, left


def select(view, length, draw_values):
    """(found, partner, sent, rest): the partner is the oldest (first draw settles a tie); length - 1 others are sent."""
    if not view:
        return False, None, [], []
    draws = Draws(draw_values)
    top = max(a for (_, _, a) in view)
    oldest = [e for e in view if e[2] == top]
    partner = oldest[draws.take() % len(oldest)]
    others = [e for e in view if e[0] != partner[0]]
    sent, rest = pick(others, length - 1, draws)
    return True, partner, sent, rest


def outgoing(self_id, self_d, sent):
    return [(self_id, self_d, 0)] + list(sent)


def reply_select(view, length, asker, draw_values):
    candidates = [e for e in view if e[0] != asker]
    sent, _ = pick(candidates, length, Draws(draw_values))
    gone = {e[0] for e in sent}
    return sent, [e for e in view if e[0] not in gone]


def merge(rest, received, self_id, cap):
    # each received peer once: the youngest, the earliest at equal age, at the place of its first arrival
    order = []
    best = {}
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
    while len(view) > cap:
        top = max(a for (_, _, a) in view)
        last = max(k for k, e in enumerate(view) if e[2] == top)
        del view[last]
    return view


def prefer_sent(received, sent):
    """NQ-16, ruled (b) 2026-11-19: a received entry whose peer was just sent, sent strictly younger, becomes the sent one"""
    ages = {}
    for e in sent:
        ages.setdefault(e[0], e)
    return [ages[e[0]] if e[0] in ages and ages[e[0]][2] < e[2] else e for e in received]


def backfill(view, sent, cap):
    view = list(view)
    for e in sent:
        if len(view) < cap and all(e[0] != x[0] for x in view):
            view.append(e)
    return view


def insert(view, e, self_id, cap):
    return merge(view, [e], self_id, cap)


def sample(view, n, draw_values):
    taken, _ = pick(view, n, Draws(draw_values))
    return taken


def valid(view, self_id, cap):
    ids = [e[0] for e in view]
    return (len(view) <= cap and len(set(ids)) == len(ids)
            and all(i != "" and i != self_id and 0 <= a <= AGE_MAX for (i, _, a) in view))
