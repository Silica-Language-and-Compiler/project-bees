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
- `trust/` — TRUST mode (N3; SEMP's wire, one request per connection, plaintext loopback with a test-only stand-in for the
  certificate fingerprint until TLS, N4). Its own implementation (D36): `bees_trust_frame` (the map frame: structural check,
  the language's `decode`/`encode` per value), `bees_trust_guard` (the forbidden guard), `bees_trust_work` (the per-request
  worker), `dangerous_bees_trust` (listen, receive and send actors, the per-fingerprint and per-server actors, the client),
  `dangerous_bees_trust_edge` and `dangerous_bees_trust_native` (random bytes and the constant-time compare). The node's
  startup is `shim/bees_trust_node.part`; `tools/bees_config_trust.py` (the TRUST half of the `bees.config` reader) and
  `tools/bees_trust_gen.py` (the MFA table, the root units) generate the rest. See development-plan/spikes/N3-trust.md.

BEAM mode (N2, a separate implementation, D36): `inter_nodal/dangerous_beam_net` (the node with Erlang's cookie handshake,
EPMD and the control messages of a stock node; M3's `dangerous_bees_net` stays the auth-none node), `inter_nodal/beam_dist`
(the layouts), `inter_nodal/dangerous_beam_auth` and `dangerous_beam_auth_ffi` (the cookie worker over
`native/src/silica_bees_beam.c`, CommonCrypto), and `shim/beam_node_edge.part` (the startup, passed to
`tools/bees_edge_gen.py` as the first role file). The beam half of the `bees.config` reader is `tools/bees_config_beam.py`.
