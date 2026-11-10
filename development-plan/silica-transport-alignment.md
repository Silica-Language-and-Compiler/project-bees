# BEES and Silica's transport design

Source: `../silica`, branch `binary-transport-support`, `compiler/design_documents/transport_serialization_design.md`
(first read at commit 23c198f565, 2026-11-05; re-read in full 2026-11-09 at `bf2e18a4a2`, whose section 14 records phases 0 to 2
implemented on Apple Silicon). This note says what BEES leaves to the language, what BEES keeps, and how BEES's code calls into the
language's transport. Decision D35 in the roadmap records the ruling.

> **Update 2026-11-10: the port below is built and run on `silica-999926` (now pinned); `make integrate` passes with the goldens
> re-recorded after each diff was read.** What changed from the 2026-11-09 text when it met the compiler (details and the golden
> diffs: the 2026-11-10 section of [silica-defects.md](silica-defects.md)): the unit is `dangerous_bees_net` (E4026) and exports only
> its behaviours `tx`, `conn` and a new listen actor `lsn`, because a call to any function of a `dangerous_` unit is E4042 outside
> an FFI worker; the node's startup is `src/shim/bees_node_edge.part` in the root unit. A listening node's `lsn` owns the listening
> carrier and starts the link on the first accepted connection, so `tx` and `conn` never change carrier (SD-39: a replaced
> `dangerous_actor_ref` defeats the state-release proof and grew both actors by hundreds of MB). Every byte builtin, `encode` and
> `decode` run in a `sequence` that declares `transport` (E3013). A record of a message type has at most four fields (SD-37);
> a decoded `char` is compared by code (SD-38). The connection actor grants the carrier one receive credit at a time, when the
> per-frame assembler asks for more bytes (a lost-segment race, BEES's bug, found by the rate run). N0.1: `decode` of carrier bytes
> passes the checker in both actor shapes (with SD-25's caveat). M4 rate: 311 round trips per second, 6.3 MiB per node.
>
> **Update 2026-11-09: BEES's code is ported to the language's transport (the N0.0 and N1 code of [mvp.md](mvp.md) section 5),
> by reading only (checked 2026-11-10, above).** What the design changed since BEES last read it (2026-11-06), and
> what BEES changed to match:
>
> | Design (as of 2026-11-09) | BEES before | BEES now |
> | --- | --- | --- |
> | The carrier is the language's: `dangerous_tcp_carrier@carrier`, a library FFI worker installed with `spawn_dangerous` from any `dangerous_` program; the contract (6.2) is spoken as tagged tuples with `string` segments and `int64` counts; addresses are `"host:port"` and `"listen:port"` (127.0.0.1); an initial `(:tx_credit, 8)`; `:rx` only against `:credit` | BEES's own M2 carrier (`silica_bees_tcp.c`, `dangerous_bees_tcp.silica`, `bees_tcp_edge.part`): flat records, parts of 1 to 8 bytes as `int64`, `listen:127.0.0.1:PORT`, a C idle timeout | the edge section is one `carrier_new()` that spawns the stdlib carrier; `dangerous_bees_net` speaks the contract as written; the C, the adapters and the native edge's TCP entries are deleted; the loopback-only rule is the manifest reader's and the language listener's (127.0.0.1) |
> | **Listeners (6.2, 2026-11-09):** a `(:tcp)` listener keeps listening, answers `(:link_up, "port:<n>")`, and for each accepted peer spawns a connection carrier and tells its owner `(:accepted, conn, "peer:accepted")`; the owner adopts it with `(:open, owner, "")` and then receives that connection's `:link_up`, credits, `:rx`, `:link_down` | a listener accepted one peer and became the connection | `dangerous_bees_net@conn` adopts the first accepted connection (and tells `tx` the carrier to write to); later ones are left unopened (one live link per node, M3) |
> | `Carrier.silica`: `mtu`, `boundaries`, `delivery`, `addressing`, **`provides`** (renamed from `provided` 2026-11-09, a keyword); the tag is written `(:tcp)` or `:tcp`, both the same row | | `bees_dist@frame4` calls `wireframe@frame(body, carrier@mtu((:tcp)), carrier@boundaries((:tcp)))` |
> | `wireframe`: `fresh(boundaries)`, `frame/3`, `unframe/3`; the state is `{ mode: atom, expected: int64, pending: string }` (not the design's `parts` list); one frame per call, drained with an empty segment; a zero length is an empty frame | BEES's own 4-byte framing over words | 4-byte framing is `wireframe`; the handshake's 2-byte framing is `bees_dist@unframe2` over the same state record and result shape; a tick is the empty frame |
> | `encode((:etf), v) -> string`; `decode((:etf), frame, { max_bytes, max_depth, max_length })` with the limits only for variable-sized types (E2402 otherwise); both in a `sequence proc[mem(normal)]`; the rejection atoms of 4.3 | the typed codec `bees_wire` (buffers in regions, `{ code, v }` results) | the generated `bees_msgs` unit: `enc_<name>(v) -> string`, `dec_<name>(frame) -> (:ok, T) \| (:rejected, atom)`, `validate_named(frame, name) -> atom`; the limits are generator constants (4096, 16, 1024) until `bees.config` (N1, R1); `bees_wire` stays only for the `m1_wire_*` trials and the oracle |
> | No marker traits; `recreate(x)` exists for scalars; `decode` is the de-taint point; E2406 fires today only inside `external_danger` blocks (the FFI result-cast handler is not yet a taint source) | the stub `bees_ingress@recreate` | deleted; the deliverer decodes in its `produces pure` block; the per-frame assembler stays (SD-35) and holds the wireframe state |
> | Builtins actually shipped (14): `byte_at`, `byte_slice`, `bytes_of(List[int64])`, `join_bytes`, `atom_name`, `atom_index_of_name`/`atom_of_bits` (not `atom_of_name`), the float and char conversions, `to_int64` and friends; byte builtins answer `int64` | | `bees_dist` is written over `byte_at`, `byte_slice`, `bytes_of`, `join_bytes`, `length_bytes` |
> | The socket wrappers: `compiler/stdlib/net/silica_sockets.c` + `silica_sockets_wrapper.meta`, module `dangerous_sockets`; a project links `libsilica_sockets.a` and places the sidecar under `dangerous_exposure_source/sockets/`; a configuration lists `wire_etf.silica`, `wireframe.silica`, `carrier.silica`, `dangerous_sockets.silica`, `dangerous_tcp_carrier.silica` | | `native/Makefile` builds the archive from the Silica tree into `native/dangerous_exposure_source/lib/` and links `sockets -> ../silica/compiler/stdlib/net`; every node leaf's `lib/` links the five stdlib units |
> | The language's carrier has **no idle timeout** (`:timeout` is never produced) and **connects or fails at once** (no retry) | the C edge's `io_ms` read timeout and `open_ms` connect retry | `dangerous_bees_net@conn` keeps its own idle check (`io_ms`, a timer; a silent peer ends the link with reason `timeout`); `open_ms` is unused (the pair runner starts the listener first) |
>
> **Open, and flagged for the user (2026-11-09; all five settled 2026-11-10: pin 999926, the rename done, SD-35 still worked around, credit now gated on the assembler, goldens re-recorded):** (1) the compiler pin: `tools/silica.generation` says 999935 (verified 2026-11-06), but the listener behaviour BEES now relies on landed in the Silica tree on 2026-11-09 (`3c3a489ea3`, with a placement-checker change), so the pin must move to a generation that carries it before `make integrate` can pass; `binaries/silica-compiler` currently points at 999926. (2) `dangerous_bees_net` is a plain (non-`dangerous_`) module that holds and casts to a `dangerous_actor_ref`; the FFI wrapper specification's prefix rule is about modules that *use* a `dangerous_` module, which `dangerous_bees_net` does not, but the language's own programs do this only from `dangerous_` modules; if the checker objects, the fix is to rename the unit `dangerous_bees_net`. (3) SD-35: the per-frame assembler keeps the design's reassembly record (a string) in its state for one frame, as M4's assembler kept a list; whether the receive actor can absorb it is still N0's measurement. (4) `send credit` stays advisory, as in the language's carrier itself (it does not count `:tx` against `:tx_credit`). (5) Goldens: `m2_carrier_tcp` (new output), `m3_dist`, `m3_dist_frames` and `m4_demo` must be re-recorded; the expected differences are listed in [silica-defects.md](silica-defects.md) (2026-11-09 section).

> **Update 2026-11-06 (verified read-only against `silica-999935`, now pinned):** the design below is **implemented in the newest binary**: `encode((:etf), value) -> string`, `decode((:etf), frame) -> (:ok, T) | (:rejected, atom)` (replacing `recreate`), `wireframe@frame`/`unframe` (4-byte framing, no 2-byte form), the hosted `(:tcp)` carrier (`dangerous_tcp_carrier`, the carrier's host-wrapper module (named in the Silica tree), `carrier@mtu(:tcp)`), usage in the Silica tree's `programmer_tools/transport_beam_demo`. BEES's interim pieces (typed codec, M2 carrier, the receive stub) are to be replaced by these in N0.0 and N1 ([mvp.md](mvp.md) section 5); BEES keeps what the table below says it keeps. **Also (D36, same date): TRUST is not layered around the distribution stream; the row below that says BEES layers TLS between the carrier and the framing for TRUST is corrected: TRUST is its own implementation with SEMP's wire (a 4-byte length and one ETF map per frame, mutual TLS 1.3), which can use the language's `wireframe` and `encode`/`decode` for its frames.** The conversion rule (user ruling): encode and decode each in the `sequence` of a `sequence ... produces pure` block, in a connection's separate send and receive actors; unproven for carrier bytes until N0.1.

> **Update 2026-11-05 (user, from Silica):** both marker traits (`Transportable`, `Recreatable`) are being dropped. What stays is derived calls: `encode`, `decode`, and a future `recreate`, with the limits passed **as arguments** instead of declared per type. §4.1 of the transport design and §7.7 of the FFI wrapper specification are being amended together so decoding and re-creation remain one mechanism. Silica's branch also now has an implementation commit (9f103d161f: transport builtins, derived `encode`/`decode`, the ETF protocol on Apple Silicon); its design file has uncommitted edits. BEES has not tried either with a compiler binary, so the text below that says "design only" or `impl Transportable` describes the earlier design, and the exact call forms must be re-read when the amended design is committed. Nothing in /Users/yenrab/silica was changed from here.

## 1. What Silica plans to provide

Transport becomes part of the language (Lee, 2026-11-05), in three separable pieces:

| Piece | What it is | Where it stands |
| --- | --- | --- |
| `Transportable` | `impl Transportable for T { max_bytes, max_depth, max_length }` on an inline type; the compiler derives `encode((:etf), x: T) -> string` and `decode((:etf), bytes) -> (:ok, T) \| (:rejected, atom)`. `decode` is a validator in the FFI wrapper spec's sense (§7.7): limits first, the value rebuilt from the type's own literals, never partial data, 15 fixed rejection atoms | design; shares its walk with `Recreatable` (chunk 13) |
| `WireFormat` (closed trait) | one built-in implementation per protocol. **`(:etf)` is first**, the encoding of OTP 26+ `term_to_binary` with no options, and decoding accepts what `binary_to_term` produces (older tags included). CBOR second; MessagePack, JSON, Protocol Buffers and a native format later. A program cannot add one | design; byte goldens from `erl` |
| `Carrier` (closed trait) and the carrier actor contract | a carrier is an actor: `(:open, owner, address)`, `(:tx, segment, from)`, `(:credit, n)`, `(:close)` in; `(:link_up, info)`, `(:rx, segment)`, `(:tx_credit, n)`, `(:tx_failed, reason)`, `(:link_down, reason)` out; credit-based flow control. `WireFrame` adds the 4-byte big-endian length prefix on stream carriers. Hosted carriers: `(:tcp)`, `(:udp)`, `(:serial)`, `(:ble_gatt)`, each a dangerous actor over Fifi; which a build has is per target (a transport pack, E2410) | design; the hosted ones wait for Silica chunk 9 (transports) |

Also added: `byte_at`, `join_bytes`, float bit conversions, `atom_name`, `atom_of_name`. Decoding is the de-taint point: `decode`
may run in the handler that receives an FFI result cast, and its `(:ok, T)` is structurally pure. **Silica's own
distribution protocol is explicitly left to a later design built above this one** (their §7); BEES is that layer.

## 2. Where BEES stands against it

| BEES piece | After the transport lands | Until then |
| --- | --- | --- |
| Typed message codec: the `.wire` manifest, `tools/bees_wire_gen.py`, `bees_wire` (M1, M1b) | **The language's (ported 2026-11-09).** A program calls `encode`/`decode((:etf), ...)` with the limits at the call; BEES's generated `bees_msgs` keeps the two-function shape `enc_<name>` / `dec_<name>` over those calls (`tools/bees_dist_gen.py`). The manifest stays (it names the peers and the message types); `bees_wire` and the typed-codec half of the generator remain only for the `m1_wire_*` trials and the 232-vector oracle | done: the swap changed only the bodies, as planned |
| Dynamic Erlang terms (`bees_term` to and from ETF) | **Not BEES's (ruled 2026-11-05).** An any-type term is not supported by Silica; the language transpiler handles it, not BEES and not Silica. M1b's version was deleted. Reason it is needed at all: Silica's receiving type is always static (their principle 5) and an atom the program lacks is rejected, so a BEAM-compiled program that sends and receives terms of any shape needs a codec from the universal term type to ETF (section 4). Unknown atoms rejected agrees with D16 | write it in M1b: it is needed by the first BEAM-compiled program, and not by the typed MVP |
| Framing | 4-byte length prefix after the handshake: `wireframe` (ported 2026-11-09). **The handshake's 2-byte framing is BEES's**: `bees_dist@unframe2`, the same state record and result shape as `wireframe@unframe` | done |
| Transports (M2) | the `(:tcp)` carrier (ported 2026-11-09: `src/shim/bees_tcp_edge.part` is one `carrier_new()` over the stdlib's `dangerous_tcp_carrier`; the M2 C edge is deleted) | done; the M2 trial now exercises the language's carrier between two BEES programs |
| Distribution: handshake v6, flags, ticks, control messages, `REG_SEND`, name table, proxies, atom-cache refusal, remote references, the node table | **BEES.** Their §7 lists exactly what this layer needs and says the transport provides it | M3 as planned |
| Remote PIDs | the language decodes an `actor_ref` only for its own node (`:foreign_actor`) and encodes one as `NEW_PID_EXT`. Control messages carry **foreign** PIDs, so BEES needs a pid form of its own | BEES reads and writes `NEW_PID_EXT` itself (4-byte id, 4-byte serial, 4-byte creation, node atom); see section 4 |
| Receiving untrusted bytes (M0: blocked on `Recreatable`) | `decode` is the language's re-creation of bytes; BEES writes none by hand (it could not pass the checker, M0). **Ported 2026-11-09:** the stub `bees_ingress@recreate` is deleted; the deliverer (generated `dlv_<name>`) calls `bees_msgs@dec_<name>` in the `sequence` of its `produces pure` block, and the connection actor validates with `bees_msgs@validate_named` first | done in code; the taint result on carrier bytes is still N0.1's to measure |
| TRUST security (mTLS 1.3, ALPN `trust/1`) | not in Silica's design: no carrier is encrypted. **corrected 2026-11-06 (D36): TRUST is a separate implementation with SEMP's wire, not a layer around the distribution stream**; its TLS engine sits between the carrier and TRUST's own framing (a carrier owner that passes bytes through a TLS engine; section 4), still blocked on a TLS engine chosen with the user's explicit approval (S12, D38) | none |
| Timers, balancer, exit hub, supervision duty | unchanged | |

## 3. Interim rules, so the swap is cheap

1. **Message codecs are two functions per message**, `enc_<name>(rg, b, msg)` and `dec_<name>(rg, b, len)`, in a unit the
   generator writes; nothing else in BEES touches frame bytes.
2. **Every frame is an ETF term** with the `131` prefix for a whole term, and bare terms after a distribution header,
   exactly as the language will write them. Any byte golden from `erl` serves both.
3. **A rejection uses the language's atoms** (`:bad_version`, `:truncated`, `:trailing_bytes`, `:bad_tag`, `:too_large`,
   `:too_deep`, `:too_long`, `:out_of_range`, `:bad_utf8`, `:unknown_atom`, `:bad_variant`, `:missing_field`,
   `:duplicate_field`, `:unknown_field`, `:foreign_actor`, `:unsupported`), not BEES-specific ones, so a trial written now still
   holds then. M1b maps the reasons M1 uses onto these.
4. **Records are ETF maps and `unit` is `{}`**, as their §4.7 proposes; a program that talks to an Erlang record declares a
   tagged tuple.
5. **The transport actor speaks the carrier contract.** The owner casts `(:open ...)`, grants credit, and receives `(:rx ...)`.
6. **Limits are named in one place** (`max_bytes`, `max_depth`, `max_length`), as the manifest's limits are now. Silica is moving them from a per-type declaration to arguments of the call (update above), so keep them behind the generated `enc_<name>`/`dec_<name>` and the swap changes only their bodies.

## 4. What BEES implements itself (not language features)

Ruled 2026-11-05: these are BEES implementation details and stay out of the language. Silica's design is used as it is.

1. **Foreign actor references.** BEES defines its own remote-reference form `{ node, creation, id, serial }` and reads and writes
   `NEW_PID_EXT` itself; the language's `actor_ref` encoding is used only for local actors.
2. ~~Terms of any shape.~~ **Withdrawn 2026-11-05:** any-type is not supported by Silica; the language transpiler handles it, not BEES and not Silica.
3. **The handshake's 2-byte framing.** BEES's own framing in `dangerous_bees_net`, beside the language's 4-byte `WireFrame`.
4. **TLS for TRUST.** BEES puts the TLS engine between the carrier and TRUST's own framing (TRUST is not layered around the distribution stream, D36; still waiting on a TLS engine chosen with the user's explicit approval, S12, D38).
5. **Remote-node bookkeeping:** the node table, creation numbers and atom-cache refusal, as in M3.

Silica's open point 12 (a frame and its decoded value in a small heap) does not touch BEES, which is hosted.

## 5. Effect on the plan

- **M1b is rescoped**: the typed-message half is explicitly an interim of the language's `Transportable`; the new, lasting
  part is the rest of what the language will not provide (the pid form, the 2-byte
  handshake framing).
- **M2** is written against the carrier contract.
- **M3** is unchanged, and every `decode` is the receive step the M0 gate waits on.
- **M5**'s profile document becomes "what BEES adds to Silica's ETF binding".
- **Dependencies** gain Silica's transport work (their proposed chunk 16), chunk 9 (transports) and chunk 13.
- The wire manifest and generator are marked interim in the roadmap and the gap ledger.
