#!/usr/bin/env python3
"""Generate dependency-graph.md and dependency-graph.yaml from the node list below.

Run from the repository root:  python3 development-plan/gen-dependency-graph.py
Edit the node list here, never the generated files.
"""
import json

# id, title, owner, area, start_after (hard), close_after (hard-to-close), soft (dep -> interim), note
N = []
def node(id, title, owner, area, start=(), close=(), soft=(), note=""):
    N.append(dict(id=id, title=title, owner=owner, area=area, start=list(start), close=list(close),
                  soft=[list(s) for s in soft], note=note))

# ---------------- Stage 0 ----------------
node("R0.1", "Repository, trial harness, bees_config skeleton", "BEES", "tools")
for sid, title, extra in [
    ("S1", "Spike: trait mapping (Supervisor, split gen_server, state-machine shape)", {}),
    ("S2", "Spike: cross-unit atoms", {}),
    ("S3", "Spike: actor ceiling and spawn/message cost", {}),
    ("S4", "Spike: native edge (clock_gettime, poll) through spawn_dangerous", {"area": "native"}),
    ("S5", "Spike: bytes without conversion; int64/float64 comparison (open)", {}),
    ("S6", "Spike: bees_term in a region; evacuation cost", {}),
    ("S7", "Spike: exit reports to a report sink (D23) in a Silica branch", {"area": "silica", "owner": "BEES+Silica"}),
    ("S8", "Spike: re-creation shapes for every native-edge flow", {}),
    ("S9", "Spike: four reference lowerings", {"area": "contract"}),
    ("S10", "Spike: BIF failure paths and the crash report", {}),
    ("S11", "Spike: balancing through migrate_actor()", {}),
]:
    node(sid, title, extra.get("owner", "BEES"), extra.get("area", "trials"), start=["R0.1"])
node("S12", "Spike: TLS engine (rustls hosted; C library on ESP32-S3; both profiles)", "BEES", "native",
     note="Needs only the Rust and ESP-IDF toolchains; no Silica.")
node("S13", "Spike: lifecycle cost (supervised spawn, message copies, yield vs mailbox depth, exit through the hub)",
     "BEES", "trials", start=["R0.1"], soft=[["S7", "exit part measured without S7's report prototype"]])
node("R0.3", "Contract v0 (contract/target-contract.md)", "BEES", "contract",
     start=["S1", "S2", "S5", "S6", "S9", "S10"], note="Reviewed by at least one compiler project before M0 closes.")
node("M0", "Stage 0 exit: all thirteen spike notes merged, S-5 filed, contract v0 reviewed", "BEES", "plan",
     start=["R0.1", "S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10", "S11", "S12", "S13", "R0.3"],
     note="S-5 is filed with S8's shapes before M0 closes; the S-5 node below is the item landing in Silica.")

# ---------------- Track S (Silica repo) ----------------
# Silica's AI_POLICY: human-vetted, no AI co-authors. A sub-agent may draft the proposal and the failing trial;
# a person files and lands it.
TS = [
    ("S-5",  "Re-creation (Recreatable trait) — THE CRITICAL PATH", ["S8"], "Filed first, before any other Track S item."),
    ("S-26", "64-bit actor identity", [], ""),
    ("S-28", "Supervisor exit reports to a report sink", ["S7"], ""),
    ("S-2",  "Runtime link", [], ""),
    ("S-9",  "Stopping and shutdown for ordinary actors", ["S10"], ""),
    ("S-29", "Atom-keyed registry", [], ""),
    ("S-3",  "Monotonic clock and timers (delivered 2026-10; no BEES timer module)", [], ""),
    ("S-15", "Region release inside a living actor", ["S6"], ""),
    ("S-11", "Big integers", [], ""),
    ("S-17", "State-machine behaviour trait", ["S1"], ""),
    ("S-6",  "Per-core scheduler and growable stacks", ["S3"], ""),
    ("S-23", "migrate_actor() and exclusive pins on the ESP32-S3", ["S11"], ""),
    ("S-24", "Fifi on the ESP32-S3", ["S4"], ""),
    ("S-8",  "Mailbox introspection and a dispatch tracing hook", [], ""),
    ("S-21", "buf(uint8) across the FFI boundary", ["S5"], ""),
    ("S-22", "Silica's own TCP/IP", [], ""),
    ("S-31", "Run-time calling-convention check", [], ""),
    ("S-32", "Silica Linux x86_64 path (exists per Silica ROADMAP; unverified by BEES)", [], ""),
]
for sid, title, deps, note in TS:
    node(sid, title, "Silica", "silica", start=deps, note=note)

# ---------------- Stage 1 ----------------
node("M1.A", "PoC shim v0: bees_term subset, evacuation, receive helpers, PoC BIFs, one Supervisor mapping",
     "BEES", "shim", start=["M0"])
node("M1.T", "PoC contract slice: reference lowerings end to end; bees_config generating module table and atom lookup",
     "BEES", "contract", start=["M1.A"])
node("M1.B", "PoC protocol layers over an in-process loopback transport (TRUST call path; EPMD, handshake, delivery)",
     "BEES", "inter_nodal", start=["M1.A"])
node("M1.N", "PoC on real sockets: TRUST over mTLS between two BEES nodes; cleartext to an erl -sname node",
     "BEES", "inter_nodal", start=["M1.B", "S-5", "S12", "S4"],
     note="If S-5 has not landed when the rest of M1 is done, this moves into B1 and B3.")
node("M1", "Stage 1 exit: three programs match the BEAM; latency and memory measured; ledger updated", "BEES", "plan",
     start=["M1.A", "M1.T", "M1.B"], soft=[["M1.N", "deferred to B1 and B3"]])

# ---------------- Track A ----------------
node("A1", "Terms and memory", "BEES", "shim", start=["M1"], close=["S-11", "S-15"])
node("A2", "Processes and signals (save queue, pdict, exit hub, child-id pools, names)",
     "BEES", "shim", start=["M1"], close=["A1", "S-2", "S-26", "S-28"],
     soft=[["S-9", "shutdown: 0, no terminate/2"], ["S-29", "BEES name table, hub removes names"]])
node("A3", "ERTS modules and BIFs (tiers, result-returning variants, ets, persistent_term, code, bees_log, crypto)",
     "BEES", "shim", start=["A1", "A2"], close=["S-5", "S-8"])
node("A4", "OTP behaviours on Silica constructs (Supervisor, split gen_server, state machine; proc_lib/sys support)",
     "BEES", "shim", start=["A2"], close=["S-17", "S-2"])
node("A5", "Host I/O and observability (bees_io, bees_inet, bees_file, I/O server, telemetry)",
     "BEES", "shim", start=["A3"], close=["S-5", "S-8"], soft=[["S-22", "native-edge sockets"]])
node("A6", "Balancing and placement (bees_place, spawn supervisors, dispatch budget, watchdog, statistics)",
     "BEES", "shim", start=["A2", "S11"], close=["S-6", "S-23", "S-24"])

# ---------------- Track T ----------------
node("T1", "Contract 1.0 (all eight items, cross-language rules, versioning)", "BEES", "contract",
     start=["R0.3"], close=["A1", "A2", "A4"])
node("T2", "Conformance kit (reference lowerings + self-check suite, packaged for compiler CI)", "BEES", "contract",
     start=["T1"], close=["T1"])

# ---------------- Track B ----------------
node("B1", "TRUST 1.0 single request (trust/1 spec and codec, FSM, whitelist, tokens, suspicion, pins, audit)",
     "BEES", "inter_nodal", start=["M1"], close=["A2", "S-5", "S12"],
     soft=[["S-17", "FSM as a plain behaviour with a phase field"]])
node("B2", "TRUST windowed multiplexing", "BEES", "inter_nodal", start=["B1"], close=["B1", "A5"])
node("B3", "BEAM mode L1–L2 (EPMD, handshake, ETF, links, bees_gen, tls transport, node-down by send)",
     "BEES", "inter_nodal", start=["M1"], close=["A2", "S-2", "S-5", "S-22", "S12"])
node("B4", "BEAM mode L3–L4 (remote spawn; BEES's erpc, rpc, net_kernel, global, pg) — after 1.0",
     "BEES", "inter_nodal", start=["B3"])

# ---------------- Integration ----------------
node("I1", "Remote lifecycle: A2 exits × B3 control messages", "BEES", "plan", start=["A2", "B3"])
node("I2", "Network I/O: A5 bees_io × B1 transport", "BEES", "plan", start=["A5", "B1"])
node("EXT", "External: first language-to-Silica compiler (expected Erlang)", "external", "external")
node("I3", "First external compiler passes the conformance kit", "BEES+external", "plan", start=["T2", "EXT"])
node("X1", "Cluster semantics: three-node mixed cluster survives a partition", "BEES", "plan", start=["I1", "I2", "I3"])
node("X2", "Scale: benchmarks against the BEAM, 1 million idle processes", "BEES", "plan", start=["A6", "A4", "S-6"])
node("SEC", "External security review: TRUST, bees_ingress, re-creation points, native edge", "external", "plan",
     start=["B1", "B3", "A5"])
node("R1", "Release 1.0", "BEES", "plan", start=["X1", "X2", "B2", "B3", "SEC", "T2", "S-24", "S-32"])

# ---------------- checks ----------------
ids = {n["id"] for n in N}
for n in N:
    for d in n["start"] + n["close"] + [s[0] for s in n["soft"]]:
        assert d in ids, (n["id"], d)
# waves: a node starts after its start-deps have *closed*; it closes after its close-deps have closed
byid = {n["id"]: n for n in N}
sw, cw = {}, {}
def close_wave(i):
    if i in cw: return cw[i]
    n = byid[i]
    sw[i] = 1 + max([close_wave(d) for d in n["start"]], default=-1)
    cw[i] = max([sw[i]] + [close_wave(d) for d in n["close"]])
    return cw[i]
for n in N: close_wave(n["id"])
nw = max(sw.values()) + 1
waves = [[n for n in N if sw[n["id"]] == w] for w in range(nw)]

unblocks = {n["id"]: [] for n in N}
for n in N:
    for d in n["start"]: unblocks[d].append(n["id"])

# ---------------- YAML ----------------
y = ["# Generated by gen-dependency-graph.py; edit the node list there, not this file.",
     "# start: may begin when all are closed. close: cannot close until all are closed.",
     "# soft: [dep, interim] — may start and close on the interim; the dep replaces it later.",
     "nodes:"]
for n in N:
    y.append(f"  - id: {json.dumps(n['id'])}")
    y.append(f"    title: {json.dumps(n['title'])}")
    y.append(f"    owner: {json.dumps(n['owner'])}")
    y.append(f"    area: {json.dumps(n['area'])}")
    y.append(f"    start: {json.dumps(n['start'])}")
    y.append(f"    close: {json.dumps(n['close'])}")
    y.append(f"    soft: {json.dumps(n['soft'])}")
    if n["note"]: y.append(f"    note: {json.dumps(n['note'])}")
open("development-plan/dependency-graph.yaml", "w").write("\n".join(y) + "\n")

# ---------------- Markdown ----------------
def mm(sub):
    out = []
    for n in N:
        if not sub(n): continue
        for d in n["start"]:
            out.append(f"  {q(d)} --> {q(n['id'])}")
        for d in n["close"]:
            out.append(f"  {q(d)} -.closes.-> {q(n['id'])}")
    return "\n".join(out)
def q(i): return i.replace("-", "_").replace(".", "_")
def decl(sub):
    out = []
    for n in N:
        if sub(n):
            shape = "([%s])" if n["owner"] == "Silica" else ("{{%s}}" if n["area"] == "plan" else "[%s]")
            out.append(f"  {q(n['id'])}{shape % n['id']}")
    return "\n".join(out)

SPIKES = ["S%d" % i for i in range(1, 14)]
stage0 = lambda n: n["id"] in SPIKES + ["R0.1", "R0.3", "M0", "S-5"]
s0ids = {n["id"] for n in N if stage0(n)}
def stage0_edges():
    out = []
    for n in N:
        if n["id"] not in s0ids: continue
        for d in n["start"]:
            if d in s0ids: out.append(f"  {q(d)} --> {q(n['id'])}")
        for d in n["close"]:
            if d in s0ids: out.append(f"  {q(d)} -.closes.-> {q(n['id'])}")
    return "\n".join(out)
later = lambda n: n["id"] not in s0ids or n["id"] == "M0"
def later_edges():
    out, used = [], set()
    for n in N:
        if not later(n): continue
        for d in n["start"]:
            out.append(f"  {q(d)} --> {q(n['id'])}"); used.update([d, n["id"]])
        for d in n["close"]:
            out.append(f"  {q(d)} -.closes.-> {q(n['id'])}"); used.update([d, n["id"]])
    return "\n".join(out), used
LATER_EDGES, LATER_USED = later_edges()

rows = []
for n in N:
    soft = "; ".join(f"{d} ({i})" for d, i in n["soft"]) or "—"
    rows.append(f"| **{n['id']}** | {n['title']} | {n['owner']} | `{n['area']}` | {', '.join(n['start']) or '—'} | {', '.join(n['close']) or '—'} | {soft} | {', '.join(unblocks[n['id']]) or '—'} |")

wave_lines = []
for i, w in enumerate(waves):
    wave_lines.append(f"- **Wave {i}:** " + ", ".join(n["id"] + ("" if cw[n["id"]] == sw[n["id"]] else f" (closes in wave {cw[n['id']]})") for n in w))

md = f"""# BEES Dependency Graph

This is the [roadmap](roadmap.md) laid out as a graph, so that work can be handed to people or sub-agents
concurrently wherever nothing unmet stands in the way. It adds no decisions; where it disagrees with the roadmap,
the roadmap wins and this file is wrong. This file and [dependency-graph.yaml](dependency-graph.yaml) (the same
node list, for tooling) are generated by [gen-dependency-graph.py](gen-dependency-graph.py); edit the node list
there and re-run it.

## 1. How to read it

Every node is a piece of work with an ID from the roadmap: a spike (S1–S13), a Stage 0 deliverable (R0.x), a
stage or milestone (M0, M1, A1–A6, T1–T2, B1–B4), an integration point (I1–I3, X1–X2), a Track S item in the
Silica repository (S-n), or an external event (EXT, SEC).

Each node has three kinds of dependency:

- **Start after** (solid arrow). Hard. The node may not begin until every one of these is closed.
- **Closes only after** (dotted arrow). The node may begin, but cannot be called done until these have landed.
  Work on it proceeds on the interim the roadmap names.
- **Soft** (listed, not drawn). The node may start *and close* on the named interim; the dependency replaces the
  interim later without reopening the node.

**Rules for concurrent work:**

1. Any set of nodes whose *start after* lists are all closed may run at the same time.
2. Two concurrent nodes in the same `area` must have one owner, or agree on file ownership first. The areas are
   `contract/` (R0.3, T1, T2, S9, M1.T), `src/shim/` (M1.A, A1–A6), `src/inter_nodal/` (M1.B, M1.N, B1–B4),
   `native/` (S4, S12), `trials/` (the other spikes, S13) and `tools/` (R0.1).
3. **Track S nodes are in the Silica repository and follow Silica's `AI_POLICY.md`: human-vetted, no AI
   co-authors, smallest reasonable PRs.** A sub-agent may draft the proposal text and the failing trial in the
   BEES repository; a person files and lands the Silica change. Do not hand a Track S node to a sub-agent as
   implementation work.
4. A node is closed by trials, not by code that merely compiles (roadmap §5).
5. **S-5 is the critical path.** Whenever a choice exists, the work that shortens the path to S-5 landing (spike
   S8, then filing S-5, then offering to implement it) goes first.

## 2. Stage 0

Everything here can start now except R0.3 and M0. The thirteen spikes are independent of each other and of the
Silica prerequisites; the one soft edge is S13's exit measurement, which is better with S7's prototype.

```mermaid
graph LR
{decl(lambda n: n["id"] in s0ids)}
{stage0_edges()}
```

## 3. After Stage 0

Silica items are rounded; integration points are hexagons. Dotted arrows are *closes only after*. Soft
dependencies are not drawn; they are in the table. Stage 0 nodes appear here only where a later node depends on
them directly.

```mermaid
graph LR
{decl(lambda n: n["id"] in LATER_USED)}
{LATER_EDGES}
```

## 4. Waves

Nodes grouped by the earliest wave in which they may start: the wave after every *start after* dependency has
closed, where a node closes only once its *closes only after* dependencies have closed too (shown in brackets
where that is later than its start). A wave says only what *may* run together. Track S items run in the Silica
repository on Silica's schedule, so their wave is when they can be filed, and the waves after them assume they
land in time; if one slips, everything that closes after it slips with it.

{chr(10).join(wave_lines)}

## 5. Node table

| ID | Work | Owner | Area | Start after | Closes only after | Soft (interim) | Unblocks |
| --- | --- | --- | --- | --- | --- | --- | --- |
{chr(10).join(rows)}
"""
open("development-plan/dependency-graph.md", "w").write(md)
print(len(N), "nodes,", len(waves), "waves")
