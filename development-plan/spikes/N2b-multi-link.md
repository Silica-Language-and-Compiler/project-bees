# N2b: more than one live link per node (BEAM mode)

Status 2026-11-17: built and run in the main checkout (the sections from "N2c" on); the 2026-11-16 note about the worktree follows. Status 2026-11-16: written in an isolated git worktree. The code and the trial were written but not compiled or run there:
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

- **Superseded 2026-11-17 (N2c, the sections below):** reconnect is built (a peer that connects again replaces its old link; a dial peer is
  dialed again), the M3 auth-none node is multi-link too, accepted connections are no longer capped at the number of peer lines, and a
  peer this node dials is refused when it dials in (its proxies belong to the dial link).

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


# N2c (2026-11-17): the M3 node is multi-link, and a peer that connects twice is replaced

User rulings of 2026-11-17: the M3 auth-none node gets the same multi-link model as BEAM mode; a peer that connects twice is NOT refused
but REPLACES its old link; a dial-role peer whose link goes down is dialed again. Built, run and recorded on silica-999909 in the main
checkout. Trials: `m3_multilink`, `n2_reconnect`, `m3_reconnect` (all three goldens recorded after reading the outputs).

## The M3 node, multi-link

`dangerous_bees_net` and `bees_node_edge.part` now have the shape `dangerous_beam_net` and `beam_node_edge.part` have: `net_launch`
starts the node's ONE listener when any peer is listen-role (`bees_peers@listens`, `listener_address`) and, for each dial peer, its own
carrier, `tx`, `conn` (state `dial: true, peer: i`), proxies and reaper (`net_dials`, `net_dial_link`). The generated `bees_peers`
carries what `beam_conf` carries in BEAM mode: `link_dials_of(i)`, `link_resolve_of(i)`, `link_host_of(i)`, `link_port_of(i)`,
`link_address_of(i)`, `listens`, `listener_address`, and the per-peer `reaper_p<i>` / `start_proxies_p<i>(tx, mgr)` /
`start_proxies(idx, tx, mgr)` (the scalars of the first link stay). `bees_dist_gen.per_peer_proxies` is the ONE generator of the reapers
and `start_proxies`, called by both `bees_dist_gen` (bees_peers) and `bees_config_beam` (beam_peers). `conn` takes `dial` and its peer
from its own state, no longer from `bees_peers@link_dials()` / `link_peer()`. With one link the behaviour and the output are unchanged
(m3_dist 10 of 10 and m4_demo goldens as recorded; see the trial counts in the final report of the change).

## Replacing a link: the ordering

Messages `(:bees, op, k, tx, conn)` go to a chain of SLOTS, one per peer line (`dangerous_*_net@slot`; the head is held by `lsn` and by
every listening `conn`). A slot says who OWNS the peer's registered names: `cur` (its tx and conn) and, while a newer connection of the
same peer waits, `pend`. The rules, in the order they act:

1. **Claim.** A listening link claims its peer's slot when it knows the peer: `lsn` at accept when the table has one peer, `conn` at
   `established` (handshake complete, `peer_index` found the name) otherwise. Slot empty: the claimant gets `go` (conn kind `100 + k`) at
   once. Slot owned: the claimant waits as `pend` (a `pend` already waiting is told to end: conn kind 7), and the OWNER is told to end
   (conn kind 7, `replaced`): its conn closes the carrier and runs the lost-link path (audit block with reason `replaced`, tx kind 3).
2. **The owner's proxies end first.** tx kind 3 sends `(:bees, 1, 0, tx, tx)` to its reaper; the reaper does `kill_abnormal` on every
   proxy of the peer and ONLY THEN sends `(:bees, 2, k, ...)` (gone) to its manager, the slot. A registered name is released when the
   proxy ends, and `kill_abnormal` has returned before the report is sent.
3. **Go.** On gone the slot makes `pend` the owner and sends it `go`; only on `go` does that conn start the peer's proxies
   (`start_peer`, which also hands the new reaper to tx). So the new link's proxies start only after the old link's are gone, or when
   nobody owned the names: `spawn_registered` never meets a held name (SD-33).
4. **A link that ends before it ever owned names** (refused, unlisted, closed during the handshake, or replaced while waiting) has, as the
   reaper that tx knows, the slot itself (the tx is spawned with `reaper: slot`): it reports `(:bees, 1, 0, tx, tx)` there. If it is
   `cur` that is a gone; if it is `pend` it is dropped. A link that did own names has its proxies' reaper and reports gone after
   killing them; tx's messages arrive in conn's order, so `(:who, reaper)` is always processed before kind 3, and a kind 3 that reaches the
   slot always means "no proxies exist". A `go` that reaches a conn already over (mode 10) starts nothing.
5. **Who may replace.** Only a listen-role peer's link is claimed. A peer this node DIALS and that dials in is refused as an unlisted
   one (`not_allowed` in BEAM mode, a violation in M3): its proxies belong to its dial link.
6. A connection is never refused for being a second one; the cap "one accepted connection per peer line" is gone. An unlisted, silent
   or hostile connection is bounded by the handshake rules and conn's `io_ms`.

The slots and the redial actor (below) are proven behaviours (no W2300): their new state is built from a sub-record of their own helpers
and `st.x` pass-throughs, as `conn` and `tx` are (SD-39 and SD-35 would otherwise cost 1 MiB per dispatch for the life of the node).

## Redial

One redial actor `nrd` per dial-role peer (root unit, `bees_node_edge.part` / `beam_node_edge.part`; the code is the same text in both),
started with the peer's first link; its reaper is the link's manager. Messages: 6 started (a link of the peer was started: generation
+1 and a stable timer), 2 gone (from the reaper: the link was lost), 3 dial (the timer), 5 stable. On gone with `redial` on it audits
`link lost; redial scheduled, delay in ms <peer> <ms>` and arms a timer of `initial * 2^(attempt - 1)` ms, at most `max`. The timer audits
`redial attempt <peer> <n>` and starts a NEW carrier, tx, proxies (their reaper reports to the same `nrd`), conn and, for an EPMD peer, a new
EPMD lookup (`node_redial_link` = `beam_dial` / `net_dial_link`). The old link's actors are never reused (SD-39). A link that stays up for
`max` ms (its generation still current, not lost) resets the attempt count, so a peer that flaps is not retried at the cap forever and
one that was down for an hour is not retried at the initial delay forever either.

**No defaults (user ruling 2026-11-17: "The dialer is not to have a default. It has to be explicitly stated as on or off.")**. Options (BEAM section of bees.config, build-time constants of `beam_conf` and `bees_peers`, bees-config-file.md 5.2): `redial` is REQUIRED on a node with a dial-role peer (missing: a boot error naming it; non-boolean: an error), `redial_initial_ms` (10 to 60000) and `redial_max_ms` (10 to 600000, not below the initial) are required when it is true and refused when it is false (the same dislike of silent defaults; no reason found to default them). A node with no dial-role peer refuses all three (meaningless; a stray one is more likely a copied file or a peer meant to dial). The manifest-only M3 node states it as a manifest line, `redial off` or `redial <initial_ms> <max_ms>`, required when a peer is `dial`; with a bees.config the file states it and the manifest line is refused. Trials write 250 / 4000 where they redial and `{redial, false}` elsewhere. Every attempt is an audit line;
`redial false` is silent (nothing is retried). Not retried: a host name the resolver edge could not resolve (no carrier is opened, so no link
is lost); and the attempt count is per peer.

What a caller sees meanwhile is Silica's rule, unchanged: between the link going down and the next link's proxies existing the peer's
registered names are not held, so `cast_registered` to them fails the caller (SD-33), and the proxies of an attempt that fails are ended
again by the reaper. Retried attempts are visible as `link down` audit blocks of the failed links.

## Trials

- `m3_multilink`: hub, ea, ec as in n2_multilink, M3 node (auth none): 3 of 3.
- `n2_reconnect` (BEAM, cookie), `m3_reconnect` (M3): hub `h` (one listener for peers `e` and `d`), `e` (e1 and e2: the same node name started
  twice, redial false), `d` (redial on, 250 ms doubling to 4000). Scenario replace: e1 asks and is answered; e2 connects while e1 is
  up; the hub ends e1's link (check file: links replaced by the hub: 1), e1's proxy is killed (its marker), e2 asks and gets its
  answer over the new link: no name clash. Scenario redial: d asks and is answered by h1; h1 stops; h2 starts later on the same port; d
  dials again (check file: a redial attempt logged, the first after 250 ms) and its second request is answered over the new link.
- The trials that end a dial link on purpose (m3_dist, m4_demo, n1_addr, n1_frames, n2_dist, n2_live, n2_multilink) write `{redial, false}` in
  their dialers' bees.config, so their goldens are unchanged.

## Open

- An ended link leaves its idle `tx`, `conn` (mode 10), the carrier and the reaper alive: a few KiB per ended link, reclaimed only with the
  node. Ending them would make casts to them fail their senders (SD-43's rule for ended actors); a later step can end them after the
  slot or `nrd` has dropped its references.
- Extra listen peers' ports are ignored (one listener per node, accepted).
- A dial-role peer that is also listed to dial in is refused; a node that wants both directions to one peer needs two peer lines (not
  possible: a peer name is listed once) or a config role.
- The name-not-resolved case is not retried.


# Teardown: the actors of an ended link end (user ruling 2026-11-17: "this will blow up on long-lived nodes")

Measured before the change (`trials/n2_soak`, 300 cycles each, tools/soak.py): a node that was connected to, or dialed, over and over grew by
about **68 KiB per cycle**, linearly, in both modes (M3 listener 2.0 to 22.9 MiB, BEAM listener 2.1 to 23.1 MiB, M3 dialer 7.8 to 28.1 MiB, BEAM
dialer 8.1 to 28.4 MiB over 300 cycles): each ended link left its writer, connection actor, current assembler and reaper (and the EPMD lookup
actor of an EPMD-dialed peer) alive for the life of the node. (The earlier estimate "a few KiB" was wrong by an order of magnitude.)

What the runtime allows (checked 2026-11-17 in a probe, `trials/zz_probe`, and in the specification): a cast to an ENDED actor_ref ends the
CALLER with `(:explicit, :actor_not_found)`; a timer that fires at an ended actor is dropped silently; `remove_actor(ref)` ends another actor
`:normal` at its next dispatch boundary and returns without failing its caller even when the target already ended; `stop_self` only in a
behaviour; `kill_abnormal` ends at once; the carrier casts `(:link_down, why)` as the LAST message to its owner and ends itself (no later
cast to the owner, and its `:tx_credit` goes to the owner, not to the writer). So an actor may end only when no live actor can still cast to
it, and only the last party to hold a reference may end it.

## Who can cast to whom, and the order that follows

writer tx: the proxies (killed by the reaper first), conn (its last cast is kind 3, "the link is lost"), the reaper (kind 1 from tx only), timers.
conn: the carrier (events, last `link_down`), the assembler (one result per segment), the manager (slot or redial actor: go, replace), the cookie worker
(BEAM: replies to its asks), timers. assembler: conn only. reaper: tx only.

1. conn, when the link is over (mode 10): audits, tells tx kind 3. tx casts the reaper `(:bees, 1, 0, tx, conn)` (tx learns its conn from `(:car, conn)`,
   sent right after conn is spawned).
2. The reaper kills the proxies, casts its manager `(:bees, 2, k, tx, conn)` and ENDS ITSELF (stop_self): nothing casts to it again.
3. The manager (the slot of a listening node; the redial actor `nrd` of a dialing one) updates what it owns (go to the waiting link, or the redial timer)
   and RELEASES the link: `(:bees, 9, ...)` to its conn, once. A link that ended before it owned any names is released by the slot at the end of its chain.
4. conn ends when ALL of: the carrier's `link_down` has arrived (flag 1; the carrier ended itself), the release has arrived (flag 2; the manager holds no
   reference), the cookie worker cannot still reply (flag 4: always with auth none; with cookie auth a link that ended during the handshake waits a 2 s
   grace timer, the one time-based wait, because a reply cast to an ended conn would end the shared worker), and its assembler is not busy with a segment
   (a busy one would cast the result; it reports and the check repeats). The flags live in the `step` field (E1070 leaves no room for a ninth
   field), so no constructor changed. Then conn removes the idle assembler (`remove_actor`), tells tx kind 9 and `stop_self`s. Its senders are all done.
5. tx ends on kind 9 (stop_self): its senders (proxies, conn, reaper) are all done; a pending tick timer is dropped.
6. The EPMD lookup actor of a dial attempt ends on its carrier's `link_down` (the registration actor lives with the node). The carrier ended itself.

Never fails a sender: every cast above is to an actor that is still alive by construction; the only casts that can reach an ended actor are timers
(dropped silently). A registered name is never held by an ended actor: the proxies are killed before the manager is told. What is left per peer for the life
of the node is bounded: the slot chain (one slot per peer line), the redial actor (one per dial peer), the listener.

## Memory, before and after (trials/n2_soak, tools/soak.py; resident set from `ps`, KiB; one run on this machine, the numbers vary a little)

A listening node (one peer line, so it claims at accept; proxies, reaper and slot all take part) that a peer connects to and drops at once, and a dialing node
(redial 10 ms) whose peer accepts and drops at once. `overlap` opens the next connection before the old one is closed (the old link is REPLACED every cycle).

| leaf, cycles | start | after 300 | after 1000 | per cycle |
| --- | --- | --- | --- | --- |
| M3 listener, BEFORE (300 cycles) | 2,048 | 22,880 | (68 MiB by extension) | **68 KiB** |
| M3 listener, replace, BEFORE | 2,032 | 22,784 | | 68 KiB |
| M3 dialer, BEFORE | 7,760 | 28,128 | | 68 KiB |
| BEAM listener, BEFORE | 2,128 | 23,072 | | 70 KiB |
| BEAM listener, replace, BEFORE | 2,128 | 22,752 | | 69 KiB |
| BEAM dialer, BEFORE | 8,128 | 28,400 | | 68 KiB |
| M3 listener, AFTER | 2,048 | 2,784 | 3,264 | 0.6 |
| M3 listener, replace, AFTER | 2,048 | 2,656 | 3,136 | 0.6 |
| M3 dialer, AFTER | 2,560 | 2,976 | 3,392 | 0.6 |
| BEAM listener, AFTER (final, 4 s after the last cycle) | 2,112 | | 3,664 (peak 8.5 MiB: links in the 2 s cookie grace) | 1.5 |
| BEAM listener, replace, AFTER | 2,112 | | 3,376 (peak 6.2 MiB) | 1.3 |
| BEAM dialer, AFTER | 2,768 | | 3,936 (peak 9.9 MiB) | 1.2 |

Files: trials/n2_soak/measure_before_teardown.txt, measure_after_teardown.txt (the full series). The 100-fold drop is the teardown; what is left (about
0.5 to 0.6 KiB per link in M3; 1.2 to 1.5 KiB in BEAM mode, where the extra 0.7 KiB is not explained: the sample is taken 4 s after the last cycle, so links waiting out the 2 s
cookie grace are gone, and the python peer never starts a handshake, so no cookie worker call is involved) is not any BEES actor that is still alive: `trials/n2_carrier_leak`
shows the same growth with NO BEES actor at all (SD-46 in silica-defects.md: a refused (:tcp) carrier leaves 0.52 KiB behind).

# N2d (2026-11-17): the three-node mesh (no hub), both modes

User question: is there an exercise for the non-hub three-node system? Until now every multi-link trial was a hub (the hub listens for two peers, two edges dial it), so no node both listened for one peer and dialed another. `trials/n2_mesh` (BEAM mode, cookie, epmd none) and `trials/m3_mesh` (the M3 auth-none node) are the triangle.

## Role layout (one connection per link, one dialer and one listener; every node has a mixed role)

| link | dialer | listener | port |
|---|---|---|---|
| a-b | a | b | b's listener (base + 1) |
| a-c | a | c | c's one listener (base + 2) |
| b-c | b | c | the same listener of c (base + 2) |

a dials b and c (two dial peers, no listener use); b listens for a and dials c (listen peer plus dial peer); c listens ONCE for a and b (both peer lines carry c's port). Bases 22600 (n2_mesh) and 22700 (m3_mesh), `tools/trial_ports.py`. Leaves: `a`, `b`, `c` (entries `cm` mesh, `c1`, `c2` redial) and `ar`, `br` (a and b with `{redial, true}`, 250 ms doubling to 2000 ms; c has no dial peer and so states no redial).

Requests: node X casts `rq_XY` to Y (value 100 * round + 10 * X + Y, a=1 b=2 c=3) and receives its own answer on `an_XY` (10 * request + Y). The responder casts the answer to the registered name of the ASKER, so it leaves over that peer's link; a misrouted reply would carry the wrong sender or responder digit. Registered proxy names are per peer (`rq_XY`, `an_YX`), so the two links of one node never clash.

## Scenario mesh

Stagger 1 s (c, b, a; the listeners first, nobody redials); six requests at 0.6 s intervals, then every node prints `done`. Proves: a node that listens for one peer and dials another works in both roles at once; each of the three nodes asks both others and is answered by each, over the right link, in both modes. The `*.check` file records that no node printed a failure (`no case arm matched`, `actor_not_found`, `failure report`, `not_allowed`). A node that is not linked to another is not reachable (no forwarding) by construction: there is no `remote` line, so there is no name to cast to; not exercised separately.

## Scenario redial

c1, b, a (stagger 1 s), then c2 (the same node c, same port) at 10 s. Round 0: a asks b and c, b asks c, all answered; c1 is ended by the harness. a and b lose their c link and redial (a and b each log redial attempts; check file: attempts logged, first delay 250 ms). During the outage the OTHER link, a-b (a dialed, b listens), keeps answering in both directions (6.5 s and 7.0 s). c2 comes up; a and b dial it again and are answered over the NEW links (12.5 s and 13.0 s) while a-b still answers (13.5 s and 14.0 s). Proves: a listen link and a dial link of the same node are independent (b listens for a and redials c while a's link stays up), and the redialed link's proxies start without a registered-name clash.

## Determinism

Requests are spaced 0.5 s or more apart in time, so each node's own lines are in a fixed order. What races: a node that dials two peers at once (a) completes the two handshakes in either order, and in the redial scenario a and b redial c2 independently. The Makefile therefore sorts every run of consecutive `[bees audit]` lines (the handshake lines carry the peer's manifest index, so none is lost); the link-down blocks, the reaper lines and the redial-attempt lines are dropped as in n2_reconnect, and their content is recorded in `redial.check`.

## What had to change

See the report of the change: the config reader (`bees_conf.py`, `bees_config_beam.py`), `bees_dist_gen.py`, `bees_edge_gen.py` and the net code accepted the mixed-role nodes as they were (listener for the listen peers, a carrier per dial peer, one `register_epmd` per node); no source change.
