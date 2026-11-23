"""The Python TEMPUS extension: the view of one store, as pure functions (development-plan/tempus-design.md section 3).

An entry is a tuple (id, d, age): the peer's identity as bytes, its descriptor (opaque here) and its age in ticks. A
view is a list of entries with no id twice and none for the node itself, at most `cap` long. Nothing here makes a
random number, reads a clock or opens a connection: every function that chooses takes its draws as a list of
non-negative integers and uses one draw per choice, as an index modulo the number of candidates; a missing or negative
draw counts as 0.

Written after src/tempus/bees_tempus_view.silica, function for function, so that the two can be compared. The tests
(test_bees_tempus_node.py) run the cases of trials/t0_tempus_view against this module and compare every line with that
trial's golden.
"""

AGE_MAX = 65535


def _draw(draws, k):
    """the k-th draw, 0 when there is none or it is negative"""
    if k >= len(draws) or draws[k] < 0:
        return 0
    return draws[k]


def member(view, peer):
    return any(e[0] == peer for e in view)


def remove(view, peer):
    """the view without that peer's entry, order kept"""
    return [e for e in view if e[0] != peer]


def age_all(view):
    """every age one higher, stopping at AGE_MAX"""
    return [(i, d, a + 1 if a < AGE_MAX else AGE_MAX) for (i, d, a) in view]


def _pick(view, k, draws, used):
    """k entries drawn without replacement, in the order drawn; what is left, in order; the number of draws used"""
    left, taken = list(view), []
    while k > 0 and left:
        taken.append(left.pop(_draw(draws, used) % len(left)))
        used += 1
        k -= 1
    return taken, left, used


def select(view, count, draws):
    """One tick's choice at the initiator, on a view the caller has aged: (found, partner, sent, rest). The partner is
    the oldest entry (the first draw settles a tie among the oldest, in the view's order); `sent` are count - 1 other
    entries drawn without replacement (all of them when there are fewer); `rest` is the view without the partner and
    without the sent entries. found is False on an empty view."""
    if not view:
        return False, None, [], []
    top = max(e[2] for e in view)
    oldest = [k for k, e in enumerate(view) if e[2] == top]
    partner = view[oldest[_draw(draws, 0) % len(oldest)]]
    sent, rest, _ = _pick(remove(view, partner[0]), count - 1, draws, 1)
    return True, partner, sent, rest


def outgoing(self_id, self_d, sent):
    """the buffer that goes to the partner: the node's own entry at age 0, then the sent entries"""
    return [(self_id, self_d, 0)] + list(sent)


def reply_select(view, count, asker, draws):
    """The partner's choice: (sent, rest). Up to count entries drawn without replacement, never the asker's own entry;
    rest is the view without them (the asker's old entry, if any, stays in rest)."""
    sent, _, _ = _pick(remove(view, asker), count, draws, 0)
    gone = [e[0] for e in sent]
    return sent, [e for e in view if e[0] not in gone]


def merge(rest, received, self_id, cap):
    """The view after a shuffle. Entries for self_id are dropped. A peer received twice is kept once, the younger, the
    earlier at equal age, at the place of its first arrival. A received entry wins against the view when the view has
    no entry of that peer or an older one. The result is the winners in arrival order, then the kept entries in their
    order; then, while it is above cap, the oldest entry goes, at equal age the last in order."""
    once = []
    for e in received:
        if e[0] == self_id:
            continue
        for k, have in enumerate(once):
            if have[0] == e[0]:
                if e[2] < have[2]:
                    once[k] = e
                break
        else:
            once.append(e)
    ages = dict((e[0], e[2]) for e in rest)
    win = [e for e in once if e[0] not in ages or e[2] < ages[e[0]]]
    won = [e[0] for e in win]
    view = win + [e for e in rest if e[0] not in won]
    while len(view) > cap:
        top = max(e[2] for e in view)
        for k in range(len(view) - 1, -1, -1):
            if view[k][2] == top:
                del view[k]
                break
    return view


def backfill(view, sent, cap):
    """entries of `sent` go back at the end of the view, in order, while there is room; one already there is skipped"""
    view = list(view)
    for e in sent:
        if len(view) < cap and not member(view, e[0]):
            view.append(e)
    return view


def prefer_sent(received, sent):
    """Ruling NQ-16: a received entry whose peer was just sent, and sent strictly younger, is replaced by the sent one
    (the first of that peer in `sent`); at equal age the received entry stays."""
    out = []
    for e in received:
        mine = next((s for s in sent if s[0] == e[0]), None)
        out.append(mine if mine is not None and mine[2] < e[2] else e)
    return out


def insert(view, entry, self_id, cap):
    """one entry enters the view by the merge rules (an admitted peer, a joiner)"""
    return merge(view, [entry], self_id, cap)


def sample(view, n, draws):
    """up to n entries drawn without replacement; the view is not changed"""
    return _pick(view, n, draws, 0)[0]


def valid(view, self_id, cap):
    """at most cap entries, no id twice, no empty id, none for self_id, every age in 0..AGE_MAX"""
    ids = [e[0] for e in view]
    return (len(view) <= cap and len(set(ids)) == len(ids)
            and all(len(i) > 0 and i != self_id and 0 <= a <= AGE_MAX for (i, _d, a) in view))
