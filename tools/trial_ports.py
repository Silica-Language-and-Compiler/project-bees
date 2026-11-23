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
    "x1_interchange_beam": (22800, "two machines (tools/bees_interchange.py): +0 node tl's listener on the remote, every IPv4 interface, dialed directly; +1 node hl's listener here, 127.0.0.1, reached from the remote through an ssh -R forward; +2 hd, +3 td (dial only); +10 node el's listener (127.0.0.1, forwarded); +11 the stock erl node's distribution listener (127.0.0.1, forwarded); +90 the private EPMD beside the stock node (127.0.0.1, forwarded)"),
    "x2_interchange_trust": (22900, "two machines (tools/bees_interchange.py): +0 node there's TLS listener on the remote, every IPv4 interface, dialed directly; +1 node here's TLS listener, 127.0.0.1, reached from the remote through an ssh -R forward; +2 node p, +3 node u (clients, never dialed)"),
    "n5_trust_mux": (23000, "+0 s (the B2 server), +1 c (B2 client), +2 k (session 1 and 1: the compat server), +3 b (a B1 server), +4 d (a B1 client), +5 w (small-window server), +6 kc (the compat client), +7 r and +8 rc (the soak, make measure)"),
    "n5_trust_mux_tls": (23100, "+0 s (the B2 server over TLS), +1 c (B2 client), +3 b (a B1 server), +4 d (a B1 client), +7 r and +8 rc (the soak, make measure)"),
    "n2t_pair": (23200, "BEAM mode over TLS, BEES to BEES: +0 h (the one TLS listener of every scenario), +1 a, +2 b, +3 p (a plaintext listener)"),
    "n2t_live": (23300, "BEAM mode over TLS against stock erl -proto_dist inet_tls: +0 BEES node l's TLS listener; +90 the trial's private EPMD"),
    "d3_store_node": (23400, "configuration through the (:store) carrier (N0d): +0 the example node's listener (examples/store_node), +1 its peer"),
    "f1_fuzz_wire": (23500, "the fuzzer's smoke case in integrate (tools/bees_fuzz*.py, F1): node listeners and the harness's fake peers, offsets in the trial's README"),
    "f2_fuzz_long": (23600, "the fuzzer's long run (make fuzz-long, never in integrate): node listeners and fake peers, offsets in the trial's README"),
    "t5_tempus_link": (23700, "TEMPUS link over TLS (T5): +0 the listener of pair edge, +1 of pair bridge, +2 of pair p256; the dialers bind nothing"),
    "t3_tempus_nodes": (23800, "TEMPUS nodes over TLS (T3): +0 the sentinel node, +1 node A, +2 node B, +3 the Python client's listener (tools/bees_tempus_trial.py)"),
    "c2_tempus_clients": (23900, "TEMPUS clients (C2): +0 node N (driven by the Python client), +1 node M (driven by the Silica client), +2 node O (not a test node), +3 and +4 the Python client's sentinel and edge listeners, +5 and +6 the Silica client's (dangerous_cs, dangerous_ce), +7 an address nobody listens on, +8 the Python client's second edge listener"),
    "c1_codec_nodes": (24000, "C1 codec coverage, two BEES nodes exchange every kind: +0 the node a/b link"),
    "c1_codec_live": (24100, "C1 codec coverage against stock erl: +0 BEES node l's listener; +90 the trial's private EPMD"),
    "c3_tempus_bridge": (24200, "TEMPUS bridges (T6, C3): +0 the TRUST node T's listener, +1 and +2 the tempus/1 listeners of bridges B1 and B2, +3 the Python client's listener, +4 the Silica client's listener, +5 an address nobody listens on, +6 and +7 the TRUST ports in the bridges' bees.config (no whitelist: nothing listens)"),
    "c4_tempus_boot": (24300, "TEMPUS boot refusals (T7): +0 the listen address in every entry's values; no entry starts, nothing listens"),
    "n5_trust_mesh": (24400, "the five-node TRUST mesh over TLS (examples/trust_mesh, run by trials/n5_trust_mesh): +1 node n1, +2 n2, +3 n3, +4 n4, +5 n5 (each node's TLS listener; every node dials the other four)"),
    "t6_tempus_clock": (24500, "TEMPUS clock choices on running nodes, and a node built without the test unit (T6): +0 node H, +1 node S, +2 node P, +3 the Python client's sentinel listener (tools/bees_tempus_trial.py), +4 the client's own address, a value only"),
    "c6_tempus_kotlin": (24600, "the Kotlin example TEMPUS client (C6): +0 node K (a test node), +1 node Q (not a test node), +2 the Kotlin client's sentinel listener, +3 its edge listener, +4 the trial tool's Python peer that the Kotlin client dials, +5 an address nobody listens on (the Kotlin client's own tests listen on a port the system assigns)"),
    "c5_tempus_swift": (24700, "the Swift example TEMPUS client (C5): +0 node N (a test node), +1 node P (not a test node: it reads the system clock), +2 the Swift client's sentinel listener that N joins through, +3 the Swift client's edge listener, +4 the Swift client's sentinel listener that P joins through, +5 the trial tool's Python peer that the Swift client dials, +6 the Swift client's listener that the Python peer dials, +7 an address nobody listens on"),
    "c7_tempus_gossip": (24800, "the gossip examples of the example TEMPUS clients (example_tempus_clients/gossip, run by trials/c7_tempus_gossip), one network at a time: +0 the sentinel, +1 to +4 the edges (the Silica driver's instances have +0 to +3 compiled in: example_tempus_clients/silica/driver)"),
    "c7_tempus_node_python": (26100, "the Python TEMPUS extension as a node (C7): +0 node Q (Silica sentinel, a test node), +1 node A (Silica edge, a test node; it joins through S), +2 node P (Python edge, a test node), +3 node S (Python sentinel, a test node; it joins through Q), +4 node R (Python sentinel, not a test node: the program r_app.py), +5 node W (Silica edge, not a test node; it joins through R), +6 node H and +7 node T (Python test nodes for the clock's choices), +8 node V (the Python sentinel T joins through), +9 the address the trial tool's own peer advertises, a value only, +10 the listener of the extension's own client (bees_tempus_peer.Listener), +11 a peer of the test support that answers wrongly on purpose"),
    "c8_tempus_node_swift": (24900, "nodes of the Swift extension among Silica nodes (C8): +0 Silica node S (a sentinel, a test node), +1 Silica node E (an edge, a test node), +2 Silica node P (an edge, not a test node: it reads the system clock), +3 Swift node A (an edge; its clock, timers and draws are the trial's), +4 Swift node T (the stop and pause clock choices), +5 Swift node R (a sentinel, not a test node: tempus-node-example), +6 Swift node U (no clock reading at its start), +7 an address nobody listens on, +8 the listener of the Swift client's command line (steps K)"),
    "c9_tempus_node_kotlin": (25000, "nodes of the Kotlin extension among Silica nodes (C9): +0 Silica node S (a sentinel, a test node), +1 Silica node A (an edge, a test node), +2 the Kotlin test nodes KE, KH and KC (edges, one after another), +3 the Kotlin test sentinels KS and KS2, +4 the Kotlin sentinel KP (not a test node), +5 Silica node Q (an edge, not a test node), +6 the trial tool's Python peer that a node dials, +7 an address nobody listens on"),
    "c10_tempus_bridge_swift": (25100, "the Swift TEMPUS client against real bridges (C10): +0 TRUST node T, +1 bridge B1 (tempus/1), +2 bridge B2 (tempus/1), +3 the Swift client's sentinel listener that B2 joins through, +4 the address the Swift client advertises as an edge, +5 the Swift client's listener with a bridge token, +6 B1's TRUST listen port, +7 B2's TRUST listen port, +8 an address nobody listens on"),
    "c11_tempus_bridge_kotlin": (25200, "the client of the Kotlin extension against real bridges (C11): +0 the TRUST node T's listener, +1 and +2 the tempus/1 listeners of bridges B1 and B2, +3 the Kotlin client's listener, +5 an address nobody listens on, +6 and +7 the TRUST ports in the bridges' bees.config (not bound: a bridge's TRUST side only dials)"),
    "tempus_bluetooth": (25300, "the Bluetooth example (examples/tempus_bluetooth, being written): loopback ports of its Mac-only test programs"),
    "c12_tempus_csharp": (25400, "the client half of the C# TEMPUS extension (C12): +0 node K (a test node), +1 node Q (not a test node), +2 the C# client's sentinel listener, +3 its edge listener, +4 the trial tool's Python peer that the C# client dials, +5 an address nobody listens on (the extension's own tests listen on a port the system assigns)"),
    "c13_tempus_node_csharp": (25500, "nodes of the C# TEMPUS extension among Silica nodes (C13): +0 Silica node S (a sentinel, a test node), +1 Silica node A (an edge, a test node), +2 the C# test nodes CE, CH and CC (edges, one after another), +3 the C# test sentinels CS and CS2, +4 the C# sentinel CP (not a test node), +5 Silica node Q (an edge, not a test node), +6 the trial tool's Python peer that a node dials, +7 an address nobody listens on"),
    "c14_tempus_rust": (25600, "the Rust TEMPUS extension as a client (C14): +0 node N (a test node), +1 node P (not a test node: it reads the system clock), +2 the Rust client's sentinel listener that N joins through, +3 the Rust client's edge listener, +4 the Rust client's sentinel listener that P joins through, +5 the trial tool's Python peer that the Rust client dials, +6 the Rust client's listener that the Python peer dials, +7 an address nobody listens on"),
    "c15_tempus_node_rust": (25700, "nodes of the Rust extension among Silica nodes (C15): +0 Silica node S (a sentinel, a test node), +1 Silica node E (an edge, a test node), +2 Silica node P (an edge, not a test node: it reads the system clock), +3 Rust node A (an edge; its clock, timers and draws are the trial's), +4 Rust node T (the stop and pause clock choices), +5 Rust node R (a sentinel, not a test node: tempus-node-example), +6 Rust node U (no clock reading at its start), +7 an address nobody listens on, +8 the listener of the Rust client's command line (steps K); +90 to +93 the nodes of the extension's own unit tests, +99 an address they advertise"),
    "c16_tempus_bridge_csharp": (25800, "the client half of the C# TEMPUS extension against real bridges (C16): +0 the TRUST node T's listener, +1 and +2 the tempus/1 listeners of bridges B1 and B2, +3 the address the C# client advertises (nothing listens there), +5 the address the trial tool's tick driver advertises (nothing listens there), +6 and +7 the TRUST ports in the bridges' bees.config (no whitelist: nothing listens)"),
    "c17_tempus_bridge_rust": (25900, "the Rust TEMPUS client against real bridges (C17): +0 TRUST node T, +1 bridge B1 (tempus/1), +2 bridge B2 (tempus/1), +3 the Rust client's sentinel listener that B2 joins through, +4 the address the Rust client advertises as an edge, +5 the Rust client's listener with a bridge token, +6 and +7 the TRUST ports in the bridges' bees.config (not bound: a bridge's TRUST side only dials), +8 an address nobody listens on"),
    "c18_tempus_silica_client": (26000, "the Silica TEMPUS client's added coverage (C18): offsets to be recorded here by the trial's author"),
}
NEXT_BASE = 26200

# leaves that never bind a port but whose files may carry a port number as DATA (a frame's field): not checked for literals
DATA_ONLY = {"n2_frames": "the EPMD ALIVE2 frame carries port 47500 as a value; nothing listens",
             "t2_tempus_frames": "frames and adverts carry the address 127.0.0.1:22801 as a value; nothing listens or dials",
             "t4_tempus_admission": "the fixture adverts carry the address 127.0.0.1:22801 as a value; nothing listens or dials",
             "d2_store_config": "the packed bees.config fixtures carry ports of d3_store_node's block as values; nothing listens or dials",
             "c1_codec_sum": "an in-process codec trial: the manifest names a peer port as a value; nothing listens or dials",
             "c1_codec_optref": "an in-process codec trial: the manifest names a peer port as a value; nothing listens or dials",
             "c1_codec_map": "an in-process codec trial: the manifest names a peer port as a value; nothing listens or dials",
             "c1_codec_set": "an in-process codec trial: the manifest names a peer port as a value; nothing listens or dials",
             "c1_codec_buf": "an in-process codec trial: the manifest names a peer port as a value; nothing listens or dials",
             "c1_codec_termmsg": "an in-process codec trial: the manifest names a peer port as a value; nothing listens or dials",
             "c1_codec_wide": "an in-process codec trial: the manifest names a peer port as a value; nothing listens or dials"}


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
