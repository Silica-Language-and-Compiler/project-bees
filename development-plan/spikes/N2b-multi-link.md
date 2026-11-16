# N2b: more than one live link per node (BEAM mode)

Status 2026-11-16: written in an isolated git worktree. The code and the trial are written but were NOT compiled or run there:
the trial leaves' committed relative links to the Silica tree (`../../../../../../silica/compiler/stdlib/...`) resolve to
`.claude/worktrees/silica` from a worktree, which does not exist, and creating a link there was refused. Verify in the main checkout
(or a checkout whose depth matches) before anything else; goldens of n2_multilink are not recorded, and two n2_live goldens were
edited by hand (the added `[bees] resolve localhost: ok 127.0.0.1 1 1` line; re-record if the real line differs).

## What changed and why

Before: `tools/bees_conf.py` took the manifest's first peer and wrote scalar `link_*` values; `lsn` held a `started` flag and ignored
later `(:accepted, ...)`; `start_proxies(tx)` made one registered proxy per remote name, all bound to the one writer; the reaper
killed all proxies when the link dropped. The stdlib carrier needed no change: a listener keeps listening and reports each accepted
connection as `(:accepted, conn, "peer:<ip>:<port>")`; the limit was BEES's.

## Design

Configuration (BEAM mode only; `bees_conf.py`, `bees_config_beam.py`):
- `eff["links"]`: one entry per manifest `peer` line in manifest order (the index is `bees_peers@peer_index`), each with role, host,
  host kind, port or epmd, address. The first link's values are still written as scalars (`link_dials`, `link_address`, ...) so M3's
  node and the one-link roles read what they read before.
- The node has ONE listener when any peer's role is listen: `beam.listen_port`, else the first listen peer's manifest port
  (the other listen peers' ports are not used). `register_epmd` (ALIVE2) happens once per node, when the listener is bound.
- `beam_conf` gains `listens`, `listener_address`, `epmd_port` and the indexed `link_dials_of(i)`, `link_by_epmd_of(i)`,
  `link_resolve_of(i)`, `link_host_of(i)`, `link_port_of(i)`, `link_address_of(i)`, `epmd_lookup_address_of(i)`, `peer_short(i)`.
- `beam_peers` gains per-peer `reaper_p<i>` and `start_proxies_p<i>(tx)` (only the remotes declared `@` that peer; registered names
  are unique, SD-33) and `start_proxies(idx, tx)` picking by index.

Runtime (`src/shim/beam_node_edge.part`, `src/inter_nodal/dangerous_beam_net.silica`):
- Per dial peer: its own carrier (the first dial peer of a node that does not listen takes the caller's `c`), writer `tx`, connection
  actor `conn` (state `peer: i, dial: true`), proxies and reaper. The carrier is held by the per-link actors; no replaceable table
  (SD-39). A peer dialed through EPMD gets its own EPMD carrier and `epm` (kind 2, `peer: i`).
- Per listen peer: the one `lsn` counts accepted connections (`accepted: int64` replaces `started`) and, for each, spawns that
  connection's own `tx` and `conn` (`dial: false, peer: -1`), up to one per peer line (more are ignored, as the second accept was).
- The conn actor now takes its role from its own state (`dial`), not from `beam_conf`.
- Who is the peer on a listening node: it is unknown at accept until the handshake names it. With ONE peer line it is known, so
  the proxies start on accept exactly as before (same output for one-link nodes, including the `proxy ended (killed)` line after a
  refused unlisted node). With more, `established` (handshake complete, after `peer_index(name)` found the name) starts that peer's
  proxies and tells `tx` its reaper. An unlisted name gets `not_allowed` and no proxies.
- Replies: a message to a remote name goes to that name's proxy, which writes through the `tx` of its own peer's link.

## Atoms (user ruling 2026-11-16: every atom a node needs is in its compile-time set)

A listening node learns the peer's NAME (a string) at the handshake, never an atom: `peer_index` is a string `case`. The registered
names its proxies use (`bees_atoms@a_<name>`) come from the manifest's `remote` lines of every peer, so all are in `bees_atoms` at
compile time, including those of peers the node learns only at the handshake. Nothing is created at run time.

## Limits and open points

- Reconnect of a peer is not built (as before): a peer that connects twice, or a peer that is both dialed and dials in, would start
  its proxies twice and clash on the registered names. Accepted connections are capped at the number of peer lines, which only
  bounds the worst case.
- The M3 auth-none node (`dangerous_bees_net`, `bees_node_edge.part`) keeps the first-line-only rule. Decision needed if it must
  also be multi-link.
- The listener refuses no listed peer by role: a table entry whose role here is `dial` is still accepted if it dials in.

## Change 3: a name host with port epmd

The EPMD lookup dials the peer host's EPMD, so the name is resolved first: `beam_lookup` opens a per-peer EPMD carrier through
`net_resolve(ec, epm, host, epmd_port, open_ms)` (the resolver edge is a one-shot FFI worker spawned in the root unit, D30 per unit
unaffected: it handles strings only). `epm` reads the address the EPMD connection reports in its `:link_up` (`"<ipv4>:<port>"`)
and dials the link there, so a name host never reaches the carrier. The leaf must be built with `bees_edge_gen.py --resolve`
(n2_live node d now is, with host `localhost`).

## Trial

`trials/n2_multilink`: hub (listens once, two listen peers), edges `ea` and `ec` (dial the hub). `ea` casts `req_a` (21) and gets 42 on
`ans_a`; `ec` casts `req_c` (34) and gets 68 on `ans_c`. Runner: `tools/run_trio.py`. Goldens: record with `make record-golden`
after reading the three outputs.
