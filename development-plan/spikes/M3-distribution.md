# M3: the distribution layer (handshake, ticks, REG_SEND, peer table, proxies, deliverers)

**Status:** run 2026-11-05 on `silica-999936-macos-applesilicon` (macOS, Apple Silicon only) with Erlang/OTP 28 as the byte oracle.
Two plain Silica programs, in two operating-system processes, complete the Erlang distribution handshake (version 6, no digest)
over the M2 carrier transport actor on `127.0.0.1`, and a cast to a registered name on the other node arrives. The receive step is
a **stub** (section 3). Plan: [`mvp.md`](../mvp.md) sections 3.4, 3.5 and 4 and milestone M3. Compiler and language findings are in
[`silica-defects.md`](../silica-defects.md) (SD-32 to SD-34 and the notes of the M3 section).

## 1. Step 1: is decode or recreate callable in the linked compiler?

**No.** Read-only, on the linked binary (`../silica/binaries/silica-compiler` is silica-999936) and a tiny trial, `trials/m3_decode_probe`:

| Call | Result |
| --- | --- |
| `encode((:etf), v)` | E2007 unknown function |
| `decode((:etf), frame)` | E2007 unknown function |
| `recreate(v)` | E2007 unknown function |
| `impl Transportable for { ... };` | accepted and ignored (no such trait in this generation); the program runs |

Silica's branch `binary-transport-support` has `encode`/`decode` (commit 9f103d161f, Apple Silicon) and its design file (uncommitted
edits read with `git diff` only) drops both marker traits: `decode` takes its limits as a third argument, `recreate` is still planned
(chunk 13) and shares decode's walk. The linked binary predates that commit. Nothing was downloaded or installed and `../silica` was
not changed. **So no taint-clearing call is available and the receive step stays a stub behind one function.**
Re-run the probe on each new generation; when `decode` compiles, replace `bees_ingress@recreate` (section 3).

## 2. What was built

| Piece | Where |
| --- | --- |
| Byte layouts of the protocol as pure functions on a frame buffer: handshake `N` / `s` / `N` with 2-byte framing and the mandatory flags `0x4_0307_0F94`, REG_SEND `{6, FromPid, '', ToName}` with `FromPid` a NEW_PID_EXT (tag 88: node atom, 4-byte id, 4-byte serial, 4-byte creation: a BEES-own typed value, not a term shape), 4-byte framing, the payload as ETF from M1b | `src/inter_nodal/bees_dist.silica` |
| The receive step (stub) and the audit trail | `src/inter_nodal/bees_ingress.silica` |
| The node: `conn` (the carrier's owner and the receive state machine), `tx` (the one writer, the idle timer and the net tick, and the reaper call), `start` | `src/inter_nodal/bees_net.silica` |
| Generator: manifest lines `node`, `creation`, `timing`, `peer`, `remote name @ peer cast type`, `local name cast type`; writes `bees_peers` (the peer table, one proxy per remote name, one deliverer per local name, a reaper) | `tools/bees_dist_gen.py`; `remote` and `local` lines also declare the message types for `bees_wire_gen.py`; hooked into `bees_config.py generate` |
| Carrier change: parts of 1 to 8 bytes instead of whole words (`bees_tcp_read_part`, `bees_tcp_write_part`; a credit is one request for exactly k bytes). The distribution frames are byte-exact and not multiples of 8; the M2 trial is unchanged in behaviour (its golden did not move) | `native/src/silica_bees_tcp.c`, `src/shim/dangerous_bees_tcp.silica`, `src/shim/bees_tcp_edge.part` |
| `bees_edge_gen.py --use UNIT` for a node program's root unit | `tools/bees_edge_gen.py` |
| Trials | `trials/m3_dist_frames` (layouts, no network), `trials/m3_dist` (five two-process scenarios over node leaves `nodes/a`, `nodes/b`, `nodes/x`), `trials/m3_decode_probe`, `trials/m3_actor_shapes` |
| Tests | `tools/test_bees_dist.py` (in `make kit`; the kit also gained the line in the root Makefile): manifest errors, the flag set against kernel's `dist.hrl`, the frames against a live `erl` |

### How a message travels

`cast_registered(:inbox, m)` on node b reaches the proxy registered under `inbox` (generated, a plain cast-only actor typed by the
manifest). It encodes the payload with the M1b encoder, builds `4-byte length, 112, control message, payload` in a fresh region
and casts the region with its buffer to `tx` (a message carries a buffer only with its region). `tx` writes the frame part by part
through the carrier. On node a, `conn` asks the carrier for exactly the next 2 or 4 bytes (the length), then the body 8 bytes at a
time, keeping the parts as a list of words in its state (a buffer cannot be in an actor's initial state, E4038). When a frame is
complete it builds the buffer in a fresh region (the stub), checks `112`, the control message, that the pid is from the connected
peer and the target is a name this node serves, validates the payload against that name's type, and spawns a deliverer that
decodes and `cast_registered`s it. A short-lived deliverer, because `cast_registered` to a name nobody holds fails the caller (SD-33).

## 3. The receive step, and what is and is not safe

`bees_ingress@recreate` copies the parts into a buffer and nothing else. It **does not clear taint**. The checker does not see
the copy because the handler that receives a foreign-function result is not checked (SD-25), and the owner also reads event tags
(M2 decision 1). Safe against hostile bytes, by BEES's own checks after the copy: the frame length is bounded before a byte is
stored (handshake 512, frame 4096); every read is bounds-checked and rejects with a reason instead of faulting; a handshake message
must have exactly its layout and the mandatory flags; the node name must be in the peer table; a pid from another node than the
connected peer is refused; a control message other than REG_SEND is refused; a target name must be an atom the program holds and a
local name; the payload is validated (depth, element counts, atoms, ASCII) before anything is decoded. Not safe, or not
guaranteed: the language gives no taint guarantee here and a compiler that checks handlers will reject this code; a peer that
claims a 4096-byte frame and sends it slowly ties up the one link until the idle limit; there is no authentication or encryption.
Every node prints a test-only banner at start (section 6, item 9).

## 4. Results

| Check | Result |
| --- | --- |
| `make integrate` | **99 passed, 0 failed** (was 65 before M2/M3; the new leaves: `m3_decode_probe` 5, `m3_actor_shapes` 4, `m3_dist_frames` 1, `m3_dist` 10) |
| `make kit` | conformance kit 8 programs ok; lowering checker 9 tests; wire generator 18 tests; **new** `tools/test_bees_dist.py` 17 tests; all ok |
| `trials/m3_dist`, five scenarios, each two separate OS processes, listener first, each program's output against its golden (10 comparisons) | `handshake_cast`: both print `handshake complete`, the client prints that its cast was sent, `inbox got op=inc n=41` on a. `unlisted`: a audits `unlisted node, link closed x@127.0.0.1`, x sees the link close, nothing delivered. `before_handshake`: a raw peer's first bytes are a REG_SEND data frame; a audits `frame before handshake dropped, link closed`, nothing delivered. `ticks_alive`: both idle 4.5 s with a 1.5 s silence limit; a prints `net ticks seen 1` and the cast arrives. `ticks_absent`: b sends no ticks; a ends the link with reason `timeout` after 1.5 s and `proxy ended (killed)`. Stable over 4 consecutive integrate runs after the fixes below (earlier runs flaked on teardown races and one carrier hang, see section 5) |
| Byte layouts against OTP 28 | handshake `N` messages equal what `dist_util` writes (`<<$N, Flags:64, ...>>`, laid out by a live `erl`); the flag set `0x4_0307_0F94` equals the union of kernel's `MANDATORY_DFLAGS_25` and `_26` read from `dist.hrl`; the whole REG_SEND frame (112, control message with a NEW_PID_EXT, payload) equals `term_to_binary({6, Pid, '', counter})` and `term_to_binary(#{...}, [deterministic])`, and the NEW_PID_EXT round-trips through `binary_to_term`/`term_to_binary` |
| Silica warnings | W2300 (state release not proven) is reported for the `conn` and `tx` behaviours; the programs run, nothing here is deep enough to show SD-27/SD-28 cost |

**Stock Erlang node (stretch goal): not done.** A stock node cannot complete this handshake anyway (it sends the digest `r`/`a`
steps, which BEES does not speak, D34; **planned as BEAM mode's cookie digest, N2, D36**). An attempt to capture a stock node's `N` message with a fake EPMD on a high port did not get
a connection out of `erl -name` (distribution started, `net_kernel:connect_node` returned false); not pursued. The only live checks
against OTP are the byte layouts above.

Load note: the machine was also running Silica's own trial suites during part of this work; two flakes (a compiler crash on a
generated unit, a 60 s harness cap) coincided with it.

## 5. Compiler findings

SD-32 (no decode/recreate/encode in the binary), SD-33 (`cast_registered` to an unheld name fails the caller), SD-34 (`link` has no
visible effect), the E4038 and E3010 rules, `send_after` takes `uint64`, and one more transient `compiler crashed` on a generated
unit (SD-29 family, gone on the retry; the node leaves build twice). Details in silica-defects.md.

## 6. Decisions to review

1. **A stub, not a safe receive path**, as section 3 says; the alternative was to stop. It is one function.
2. **Parts of 1 to 8 bytes in the carrier contract** (`k` per request). A contract with only whole words cannot carry this protocol.
3. **One live link per node**, from the first `peer` line (`dial` connects, `listen` accepts one connection and it must name a listed node). The table can hold more; the M2 transport holds one peer per listener.
4. **A violation closes the link**: a frame before the handshake completes, a bad handshake message, an unlisted name, a bad length. A bad *content* of an intact frame (wrong pid node, unknown target, payload refused) drops the frame, audits it and keeps the link. The refusal is silent toward the peer (no `s not_allowed`): a close right after a write races the writer (M2 note).
5. **`FromPid` id is the proxy's index in the manifest, serial 0**, not the 64-bit actor identity: `actor_id` is a `uint64` and there is no uint64 to int64 conversion to write it as bytes.
6. **A data frame before the link is up is dropped** by `tx` (no queue); there is no reconnect.
7. **Ticks**: `tx` sends a net tick when a whole interval (`tick_ms`) passed with no frame written; a peer silent for `io_ms` (the carrier's read timeout) is lost. Defaults 15 s and 60 s as in OTP; the trials use 0.5 s and 1.5 s. `tick_ms` 0 sends none (a test setting).
8. **Proxies are ended with `kill_abnormal`** by a generated reaper (reason `(:explicit, :killed)`), not `fail_self` and not `link` (SD-34). A cast to a dead proxy then fails the sender, Silica's own rule.
9. **The test-only banner** is printed once by `bees_net@start` (`[bees] TEST ONLY: no authentication, no encryption ...`), so it heads every program's output and golden.
10. **No `bees_ingress` count of "name held by nobody"** (SD-33).
11. **Roles are generated into the root unit** (SD-17), including a `node_start` that a compiler's startup would write; a "plain" program source calls `node_start` in `main`.

## 7. Not covered

- **A net tick is not echoed.** mvp.md 3.4 says "a zero length is a net tick, answered in kind". Implemented as OTP does: each side sends a tick when *it* has been idle for a tick interval, and any received frame, a tick included, keeps the peer alive; an echo of every tick would ping-pong forever. The receipt of ticks is counted and audited (`net ticks seen`). Decision 7 above.
- **Taint**: the receive step is a stub (section 3); no authentication or encryption (banner printed); `127.0.0.1` only; macOS arm64 only; fixed ports (47411 for the trials; 47311, 47321, 47322 for M2).
- **A stock Erlang node** (section 4). No EPMD. No `s` status other than `ok` is ever sent (a refusal is a silent close).
- **One live link per node**, one frame in flight per direction, no reconnect (a lost link ends the proxies and the node does not redial), no backpressure beyond the carrier's, frames up to 4096 bytes (a payload up to about 4,000 bytes), control messages other than REG_SEND are dropped and audited, not counted apart.
- **Pids**: `FromPid` is a proxy's index, not its actor identity; a received pid is only checked for its node. Remote pids as values, links, monitors, remote spawn, the distribution header, atom cache, fragments: not built.
- **A local name nobody holds**: the delivery fails the short-lived deliverer, which is visible only as a failure report; it is not counted (SD-33).
- **Throughput and memory**: not measured here; **measured in M4** ([M4-demo.md](M4-demo.md)), which also found that the connection actor's list state cost about 1 MiB of memory per dispatch (SD-35) and moved the list into a per-frame assembler actor (the "frames in a list in `conn`'s state" design of this note, sections 2 and 3, is replaced; the wire behaviour and the goldens are unchanged). A frame is held as a list of words in `conn`'s state and each message copies a region with two buffers; quadratic in the frame's parts (a 4096-byte frame is 512 parts, about 1.5 s of CPU in `list_state`).
- **The root supervisor**: the trial programs spawn plainly. A compiler lowering must add `conn`, `tx`, the proxies and the deliverers to its root supervisor and give them ids from its pool (memory: compiler supervises every actor).
- **`node_start`** in each trial program is hand-written role code; nothing generates it yet.
