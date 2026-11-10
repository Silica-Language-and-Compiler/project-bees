# BEES sources

- `shim/` — the on-node shim (Track A): `bees_*.silica` units. Every module basename starts with
  `bees_` (roadmap §4.8). `bees_tcp_edge.part` is the carrier edge pasted into a node program's `dangerous_` root unit
  (`carrier_new()`: the Silica stdlib's `dangerous_tcp_carrier`); `bees_node_edge.part` is the node's startup pasted into the
  root unit of every node program (`net_launch`, `net_start`, `net_raw_writer`, `net_send_raw`), because the functions of a
  `dangerous_` unit such as `dangerous_bees_net` may be called only from an FFI worker (E4042).
- `inter_nodal/` — TRUST and BEAM-mode distribution (Track B). `dangerous_bees_net` (the receive, send and listen actors over the
  language's `(:tcp)` carrier; `dangerous_` because it holds the carrier as a `dangerous_actor_ref`, E4026), `bees_dist` (the handshake and `REG_SEND` layouts over strings), `bees_ingress` (audit).
  `bees_wire` is the M1b typed codec, kept for the `m1_wire_*` trials and the oracle; node programs encode with the
  language's `encode`/`decode` through the generated `bees_msgs`.
- `contracts/` — the Silica side of the target contract: reference lowerings that compile and run.

Units are compiled only through trial leaves: a leaf's `lib/` holds symlinks to the units it
exercises, and `make integrate` at the root builds and runs everything (see `tools/trial.mk`).
