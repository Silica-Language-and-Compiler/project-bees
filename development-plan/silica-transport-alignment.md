# BEES and Silica's transport design

Source: `../silica`, branch `binary-transport-support`, `compiler/design_documents/transport_serialization_design.md`
(commit 23c198f565, 2026-11-05). **Design only: nothing in it exists in the compiler, the built-in modules or the
trials.** BEES cannot build on it yet. This note says what BEES should leave to it when it lands, what BEES keeps, and
how to write the interim code so the swap is small. Decision D35 in the roadmap records the ruling.

## 1. What Silica plans to provide

Transport becomes part of the language (Lee, 2026-11-05), in three separable pieces:

| Piece | What it is | Where it stands |
| --- | --- | --- |
| `Transportable` | `impl Transportable for T { max_bytes, max_depth, max_length }` on an inline type; the compiler derives `encode((:etf), x: T) -> string` and `decode((:etf), bytes) -> (:ok, T) \| (:rejected, atom)`. `decode` is a validator in the FFI wrapper spec's sense (§7.7): limits first, the value rebuilt from the type's own literals, never partial data, 15 fixed rejection atoms | design; shares its walk with `Recreatable` (chunk 13) |
| `WireFormat` (closed trait) | one built-in implementation per protocol. **`(:etf)` is first**, the encoding of OTP 26+ `term_to_binary` with no options, and decoding accepts what `binary_to_term` produces (older tags included). CBOR second; MessagePack, JSON, Protocol Buffers and a native format later. A program cannot add one | design; byte goldens from `erl` |
| `Carrier` (closed trait) and the carrier actor contract | a carrier is an actor: `(:open, owner, address)`, `(:tx, segment, from)`, `(:credit, n)`, `(:close)` in; `(:link_up, info)`, `(:rx, segment)`, `(:tx_credit, n)`, `(:tx_failed, reason)`, `(:link_down, reason)` out; credit-based flow control. `WireFrame` adds the 4-byte big-endian length prefix on stream carriers. Hosted carriers: `(:tcp)`, `(:udp)`, `(:serial)`, `(:ble_gatt)`, each a dangerous actor over Fifi; which a build has is per target (a transport pack, E2410) | design; the hosted ones wait for Silica chunk 9 (sockets) |

Also added: `byte_at`, `join_bytes`, float bit conversions, `atom_name`, `atom_of_name`. Decoding is the de-taint point: `decode`
may run in the handler that receives an FFI result cast, and its `(:ok, T)` is structurally pure. **Silica's own
distribution protocol is explicitly left to a later design built above this one** (their §7); BEES is that layer.

## 2. Where BEES stands against it

| BEES piece | After the transport lands | Until then |
| --- | --- | --- |
| Typed message codec: the `.wire` manifest, `tools/bees_wire_gen.py`, `bees_wire` (M1, M1b) | **The language's.** The compiler emits `impl Transportable` for each message type and a program calls `encode`/`decode((:etf), ...)`. The manifest, the generator and `bees_wire` go away | keep them, retargeted to ETF (M1b), with the same bytes the language will produce (both are checked against `erl`), behind the two-function shape `enc_<name>` / `dec_<name>` so the swap changes only the body |
| Dynamic Erlang terms (`bees_term` to and from ETF) | **BEES keeps this.** Silica's receiving type is always static (their principle 5) and an atom the program lacks is rejected, so a BEAM-compiled program that sends and receives terms of any shape needs a codec from the universal term type to ETF (section 4). Unknown atoms rejected agrees with D16 | write it in M1b: it is needed by the first BEAM-compiled program, and not by the typed MVP |
| Framing | 4-byte length prefix after the handshake: `WireFrame`. **The handshake's 2-byte framing is BEES's**; `WireFrame` has no 2-byte form | small `bees_net` framing, 2 and 4 byte, with the `unframe` shape of §5 |
| Sockets (M2) | the `(:tcp)` carrier | the M2 native-edge socket actor **speaks the carrier actor contract** of §6.2 (the nine messages, credits), so `bees_dist` is written against the contract and the carrier swaps in |
| Distribution: handshake v6, flags, ticks, control messages, `REG_SEND`, name table, proxies, atom-cache refusal, remote references, the node table | **BEES.** Their §7 lists exactly what this layer needs and says the transport provides it | M3 as planned |
| Remote PIDs | the language decodes an `actor_ref` only for its own node (`:foreign_actor`) and encodes one as `NEW_PID_EXT`. Control messages carry **foreign** PIDs, so BEES needs a pid form of its own | BEES reads and writes `NEW_PID_EXT` itself (4-byte id, 4-byte serial, 4-byte creation, node atom); see section 4 |
| Receiving untrusted bytes (M0: blocked on `Recreatable`) | `decode` is the language's re-creation of bytes; BEES writes none by hand (it could not pass the checker, M0). Still blocked until chunk 13's derivation exists, but there is now one named thing to wait for | the receive step stays behind one function |
| TRUST security (mTLS 1.3, ALPN `trust/1`) | not in Silica's design: no carrier is encrypted. BEES layers it between the carrier and the framing (a carrier owner that passes bytes through a TLS engine; section 4), still blocked on a TLS engine (S12) | none |
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
5. **The socket actor speaks the carrier contract.** The owner casts `(:open ...)`, grants credit, and receives `(:rx ...)`.
6. **Limits are declared per type** (`max_bytes`, `max_depth`, `max_length`), the way the manifest's limits already are.

## 4. What BEES implements itself (not language features)

Ruled 2026-11-05: these are BEES implementation details and stay out of the language. Silica's design is used as it is.

1. **Foreign actor references.** BEES defines its own remote-reference form `{ node, creation, id, serial }` and reads and writes
   `NEW_PID_EXT` itself; the language's `actor_ref` encoding is used only for local actors.
2. **Terms of any shape.** BEES's codec between `bees_term` and ETF, as its own code, with unknown atoms rejected (D16).
3. **The handshake's 2-byte framing.** BEES's own framing in `bees_net`, beside the language's 4-byte `WireFrame`.
4. **TLS for TRUST.** BEES puts the TLS engine between the carrier and the framing (still waiting on a TLS engine, S12).
5. **Remote-node bookkeeping:** the node table, creation numbers and atom-cache refusal, as in M3.

Silica's open point 12 (a frame and its decoded value in a small heap) does not touch BEES, which is hosted.

## 5. Effect on the plan

- **M1b is rescoped**: the typed-message half is explicitly an interim of the language's `Transportable`; the new, lasting
  part is the dynamic term codec and the rest of what the language will not provide (the pid form, the 2-byte
  handshake framing).
- **M2** is written against the carrier contract.
- **M3** is unchanged, and every `decode` is the receive step the M0 gate waits on.
- **M5**'s profile document becomes "what BEES adds to Silica's ETF binding".
- **Dependencies** gain Silica's transport work (their proposed chunk 16), chunk 9 (sockets) and chunk 13.
- The wire manifest and generator are marked interim in the roadmap and the gap ledger.
