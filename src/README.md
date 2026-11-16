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
  **N4.1 (2026-11-12): TRUST over mutual TLS 1.3**, whenever `bees.config` does not set `plaintext_test_only`:
  `dangerous_bees_tls` (between the language's `(:tcp)` carrier and TRUST's framing: `ttls`, the link, which owns the carrier, runs
  the handshake, judges what it shows (ALPN `trust/1`, the certificate, the verify result, the client's pin, the OpenSSL minimum
  version) and hands plaintext up; `ttlsw`, the writer, the only actor that casts ciphertext to the carrier; `ttlsl`, the plain
  listener; upward the link speaks the carrier contract, so the N3 actors use it as a carrier) and `dangerous_bees_tls_native`
  (the bindings of `native/tls/silica_bees_tls.c`, a thin C shim over the programmer-installed OpenSSL, 4.1.0 or later with no
  exception (compile-time `#error`, a `native/Makefile` refusal naming the version found, and a run-time refusal in the link): memory buffers only, the
  TRUST profile fixed: TLS 1.3, X25519MLKEM768 only, AES-256-GCM or ChaCha20-Poly1305, Ed25519 or ECDSA P-256, both certificates,
  the chain against `cacertfile` only, the SHA-512 of the peer certificate's DER (D11)). `shim/bees_trust_link_tls.part` / `shim/bees_trust_link_plain.part` are
  pasted by `tools/bees_trust_gen.py` from the node's generated configuration, so a plaintext node needs no OpenSSL. See
  development-plan/spikes/N4-silica-mtls-example.md and the N4 row of development-plan/mvp.md.
  **Since Silica commit 71009f96f8** the language's carriers end with their link and a write to a gone peer is a failed write,
  not SIGPIPE (SD-42 resolved): TRUST no longer removes closed carriers with `remove_actor`, and after a carrier's `:link_down`
  nothing casts to it (a cast to an ended carrier ends the sender, SD-43).

BEAM mode (N2, a separate implementation, D36): `inter_nodal/dangerous_beam_net` (the node with Erlang's cookie handshake,
EPMD and the control messages of a stock node; M3's `dangerous_bees_net` stays the auth-none node), `inter_nodal/beam_dist`
(the layouts), `inter_nodal/dangerous_beam_auth` and `dangerous_beam_auth_ffi` (the cookie worker over
`native/src/silica_bees_beam.c`, CommonCrypto), and `shim/beam_node_edge.part` (the startup, passed to
`tools/bees_edge_gen.py` as the first role file). The beam half of the `bees.config` reader is `tools/bees_config_beam.py`.

`bees.config` (N0.2): the ONE reader is `tools/bees_conf.py` (a BUILD-TIME STAND-IN for the boot-time reader the design asks for:
Silica cannot read a file at boot; development-plan/bees-config-file.md section 11). `tools/bees_config_beam.py`,
`tools/bees_config_trust.py` and `tools/bees_config.py generate --config` only generate units from its verdict.

N1, addresses: `shim/dangerous_bees_resolve_native.silica` and `shim/dangerous_bees_resolve.silica` (the resolver worker over
`native/src/silica_bees_resolve.c`, getaddrinfo, because the language's `(:tcp)` carrier dials IPv4 literals only),
`shim/bees_resolve_edge.part` (pasted by `tools/bees_edge_gen.py --resolve`: a dialer whose host is a name resolves it first) and
`shim/bees_resolve_none.part` (the stub every other node program gets). See development-plan/spikes/N1-addresses-and-limits.md.
