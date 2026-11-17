#!/usr/bin/env python3
"""The one table of listener ports of the trials: trial name -> base port.

Trials start listeners on fixed ports (a role file's "listen:21000", a node's bees.config listen_port and node.wire peer lines, a
scenario's trust_servers pins). Two trials that share a port cannot run at the same time. So every trial leaf that binds or dials a
port owns a block of 100 consecutive ports starting at its base here, and nothing outside the block:

    port = BASE[trial] + offset          offset 0..99

Scheme: bases are 21000 + 100*k, k handed out once, in the order the trials were added (never renumbered: a changed port changes
every golden that prints it). 21000..29999 lies below the Linux ephemeral range (32768..60999) and macOS's (49152..65535), so no
outgoing connection of the machine can hold one of them. A leaf's offsets are its own business (see each entry's note); the table
records the nodes' offsets so a reader finds them. Next free base: NEXT_BASE.

The files of a leaf keep the port numbers as literals (a manifest, a bees.config, a golden must say what they say), checked here:
`trial_ports.py check` fails when a leaf's tracked files mention a number of ANOTHER trial's block, when blocks overlap, or when a
leaf's literal lies outside its own block. Makefile recipes and tools that need a port ask this module: `trial_ports.py port TRIAL [OFFSET]`.

    trial_ports.py list | check | port TRIAL [OFFSET] | next
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BLOCK = 100
FIRST = 21000

# trial -> (base, note: what the offsets are)
TABLE = {
    "m2_carrier_tcp": (21000, "+0 the listener"),
    "m3_dist": (21100, "+0 the node a/b link"),
    "m3_dist_frames": (21200, "data only (the manifest names a peer port; nothing listens)"),
    "m3_multilink": (21300, "+0 the hub's one listener"),
    "m3_reconnect": (21400, "+0 the hub's one listener"),
    "m4_demo": (21500, "+0 the service node's listener"),
    "n1_addr": (21600, "+0 a, +8 w, +10 b, +11 v, +12 n, +13 e, +14 o, +15 s (listen_port of each node; l has no TCP listener port of its own)"),
    "n1_frames": (21700, "+0 the node a/b link"),
    "n1_limits": (21800, "data only (the manifest names a peer port; nothing listens)"),
    "n2_dist": (21900, "+0 a, +1 b, +2 x"),
    "n2_live": (22000, "+0 BEES node l's listener; +90 the trial's private EPMD"),
    "n2_multilink": (22100, "+0 hub, +1 ea, +2 ec"),
    "n2_reconnect": (22200, "+0 h, +1 e, +2 d"),
    "n2_soak": (22300, "+0 m3l, +1 m3d, +2 bl, +3 bd (a measurement; make measure)"),
    "n3_trust": (22400, "+0 s, +1 c, +2 g1, +3 g2"),
    "n4_trust_tls": (22500, "+0 s, +1 c, +2 m, +3 q"),
    "n2_mesh": (22600, "+0 a (dials only), +1 b's listener (a dials it), +2 c's one listener (a and b dial it)"),
    "m3_mesh": (22700, "+0 a (dials only), +1 b's listener (a dials it), +2 c's one listener (a and b dial it)"),
}
NEXT_BASE = 22800

# leaves that never bind a port but whose files may carry a port number as DATA (a frame's field): not checked for literals
DATA_ONLY = {"n2_frames": "the EPMD ALIVE2 frame carries port 47500 as a value; nothing listens"}


def base(trial):
    return TABLE[trial][0]


def port(trial, offset=0):
    if trial not in TABLE:
        raise KeyError(f"trial {trial} has no ports in tools/trial_ports.py")
    if not 0 <= offset < BLOCK:
        raise ValueError(f"offset {offset} outside 0..{BLOCK - 1}")
    return TABLE[trial][0] + offset


def owner(p):
    """The trial whose block holds port p, or None."""
    for t, (b, _) in TABLE.items():
        if b <= p < b + BLOCK:
            return t
    return None


def problems_in_table():
    out = []
    seen = sorted((b, t) for t, (b, _) in TABLE.items())
    for (b1, t1), (b2, t2) in zip(seen, seen[1:]):
        if b1 + BLOCK > b2:
            out.append(f"blocks of {t1} ({b1}) and {t2} ({b2}) overlap")
    for t, (b, _) in TABLE.items():
        if b < FIRST or b + BLOCK > 30000 or (b - FIRST) % BLOCK:
            out.append(f"{t}: base {b} not on the {FIRST} + {BLOCK}*k scheme below 30000")
    if seen and NEXT_BASE < seen[-1][0] + BLOCK:
        out.append("NEXT_BASE is not above the last block")
    return out


# a port in context: host:PORT, listen:PORT, "port ... PORT", listen_port, PORT, a manifest's peer line "peer NAME HOST PORT"
NUM = re.compile(r"(?:[:]|\bport\b\D{0,16}?|^peer\s+\S+\s+\S+\s+)(2[0-9]{4})(?![0-9])", re.M)


def problems_in_text(leaf, text):
    out = []
    for m in NUM.finditer(text):
        p = int(m.group(1))
        if p < FIRST:
            continue
        o = owner(p)
        if o is None:
            out.append(f"port {p} is in no trial's block")
        elif o != leaf:
            out.append(f"port {p} belongs to {o}'s block, not {leaf}'s")
    return out


def problems_in_leaves(root=ROOT):
    """Every 5-digit number 20000..29999 in a leaf's tracked text files must be in that leaf's own block."""
    out = []
    files = subprocess.run(["git", "-C", root, "ls-files", "trials"], capture_output=True, text=True).stdout.split("\n")
    for f in files:
        parts = f.split("/")
        if len(parts) < 3 or f.endswith(".txt"):
            continue
        leaf = parts[1]
        if leaf in DATA_ONLY or f.endswith((".pem", ".cert")):
            continue
        try:
            with open(os.path.join(root, f), encoding="utf-8") as fh:
                text = fh.read()
        except (OSError, UnicodeDecodeError):
            continue
        out.extend(f"{f}: {x}" for x in problems_in_text(leaf, text))
    return out


def main(argv):
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "list":
        for t, (b, note) in sorted(TABLE.items(), key=lambda kv: kv[1][0]):
            print(f"{t:16} {b}..{b + BLOCK - 1}  {note}")
    elif cmd == "port" and len(argv) >= 3:
        print(port(argv[2], int(argv[3]) if len(argv) > 3 else 0))
    elif cmd == "next":
        print(NEXT_BASE)
    elif cmd == "check":
        bad = problems_in_table() + problems_in_leaves()
        for b in bad:
            print("trial_ports:", b)
        print("trial_ports:", "FAIL" if bad else f"ok, {len(TABLE)} trials, no shared ports")
        return 1 if bad else 0
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
