#!/usr/bin/env python3
"""Order a TEMPUS node's output by connection (trials): bees_tempus_sort.py FILE...

Every line a connection causes ends with its connection id (a<N> accepted, d<N> dialed). Lines of ONE connection are
written in their causal order, but two connections are independent actors, so where the last lines of one fall among the
first lines of the next varies between runs. This puts the lines that end with a connection id in the order of their ids
(accepted before dialed, then by number), keeping each connection's own order, into the places such lines held; every
other line stays where it was. Nothing is removed or changed.
"""
import re
import sys

CID = re.compile(r" ([ad])(\d+)$")


def order(lines):
    slots = [i for i, ln in enumerate(lines) if CID.search(ln)]
    tagged = sorted((lines[i] for i in slots), key=lambda ln: (CID.search(ln).group(1), int(CID.search(ln).group(2))))
    out = list(lines)
    for i, ln in zip(slots, tagged):
        out[i] = ln
    return out


def main(argv):
    for path in argv[1:]:
        with open(path) as f:
            lines = f.read().split("\n")
        with open(path, "w") as f:
            f.write("\n".join(order(lines)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
