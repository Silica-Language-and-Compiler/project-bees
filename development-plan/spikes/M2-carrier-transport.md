# M2: the transport carrier of the native edge

**Status:** done 2026-11-05 on `silica-999936-macos-applesilicon` (macOS, Apple Silicon only). Two separate operating-system
processes exchange one frame of four 8-byte words over TCP on `127.0.0.1`, both directions, through an actor that speaks Silica's
planned carrier contract. The listener refuses every non-local address. Two new Silica findings (SD-30, SD-31); SD-15, SD-17
and SD-18 re-tested (silica-defects.md, last section).
**Trials:** `trials/m2_carrier_tcp` (pair and refusal), `trials/m2_ffi_shapes` (SD-15 and SD-17 re-test). Run by `make -C trials integrate`.

## 1. What was built

| Piece | Where |
| --- | --- |
| C archive entries: open (listen and accept one peer, or connect with retry), read one word with a poll timeout, last word, write one word, close. `127.0.0.1` only; a slot table (8 links) keeps every descriptor on the C side; every entry returns a status code (header). Same archive and sidecar as S4 | `native/src/silica_bees_tcp.c`, `native/dangerous_exposure_source/bees/silica_bees_native_wrapper.{h,meta}`; `make -C native` (system `cc`, nothing downloaded) |
| Foreign declarations and bound-first adapters | `src/shim/dangerous_bees_tcp.silica` |
| The carrier actor: the front actor, a conn actor, and three dangerous workers (ctl, rd, wr), written as the **edge section** | `src/shim/bees_tcp_edge.part`; atoms of the contract in `src/shim/bees_tcp.atoms` (generated `bees_atoms`, D30) |
| Generator for each program's `dangerous_` root unit (edge section plus role files), because SD-17 keeps a worker and its spawn site in one unit | `tools/bees_edge_gen.py`; the leaf Makefile runs it at parse time; the three generated units are git-ignored |
| Pair runner: starts two executables, each under `run_trial.py`, listener first | `tools/run_pair.py`; `trial.mk` gained `NAME.pair` (two entry names run together) and `dangerous_fail_*` compile-fail units (a unit with foreign declarations must be named `dangerous_*`, E4020/E4006; the fail runner now links `dangerous_exposure_source`) |
| Trial programs | `listener.role`, `connector.role` (frames A and B), `peer.role` (the owner), `refuse.role` (eight carriers in turn) |

### How the carrier maps onto the contract

| Contract message | Here |
| --- | --- |
| in `(:open, owner, address)` | `Cmd` record `{ tag, peer, text, n }` with tag `open`, `peer` the owner, `text` `"listen:127.0.0.1:PORT"` or `"connect:127.0.0.1:PORT"`. The front spawns the workers and the conn actor, then forwards |
| in `(:tx, segment, from)` | tag `tx`, `n` the segment (one word), `peer` the sender; the writer worker writes it |
| in `(:credit, n)` | tag `credit`; the conn actor casts the reader one request per credit, and the reader reads exactly one word per request: **receive credit is exact** |
| in `(:close)` | tag `close`; the ctl worker closes and reports `link_down :closed` |
| out `(:link_up, info)` | `Evt` record `{ tag, n, reason, info }`; `info` is `"127.0.0.1"` |
| out `(:rx, segment)` | tag `rx`, `n` the word, raw and undecoded |
| out `(:tx_credit, n)` | an initial grant of 8 after `link_up`, then 1 per completed write |
| out `(:tx_failed, reason)` | a failed write: reason `link_down` |
| out `(:link_down, reason)` | `closed` (peer end or local close), `reset`, `timeout` (accept, connect or an idle read longer than the poll timeout), `fault` (address refused or malformed, bind or connect failure) |

The workers' designated receiver is the **owner**, so raw results go to the owner and never through the carrier (spec 7.6: a handler
may not forward foreign data). The receive path carries raw words only and decodes nothing; `Recreatable` (chunk 13) is still absent.

## 2. Results

- **Pair** (`dangerous_m2_listener`, `dangerous_m2_connector`): each prints the four words it received, then `link_down closed`,
  `link_up seen true`, `words received 4, tx credits 5` and `done`. Frame A is `3, 42, 7522537965568991521 ("hello!!!"), -1`,
  frame B `3, 4242, 8606223222790234401 ("world!!!"), 9223372036854775807`. The goldens are identical over every run (five integrate runs in a row, plus the root `make integrate`). The word with its top bit set and the maximum int64 cross unchanged.
- **Refusal** (`dangerous_m2_refuse`): `0.0.0.0`, `192.0.2.1` (listen), `10.0.0.1` (connect), `localhost`, `127.0.0.2` and a text with no port
  are all `link_down fault`, refused in C before any endpoint is created. Two controls that are valid local addresses get past the check and
  fail only by time: a connect to a port nobody listens on, and a listen nobody connects to, both `timeout`. The first refusal case also
  shows nothing was left bound: the later connect to the same port times out.
- **SD-18** is closed on this compiler: the reader and writer workers each answer many requests.
- **SD-15 and SD-17** (silica-defects.md): the adapter must be in its own `dangerous_` unit, bound-first; the worker stays in the root unit.

## 3. Compiler findings (details in silica-defects.md)

- **SD-30**: a foreign function cannot mix scalars with a pointer-plus-length pair (E2005). `open` is two foreign calls with thread-local C state between them.
- **SD-31**: a record-returning call written inline as a cast's message corrupts the message. Every message is bound first. This one cost the most time: the symptom was a silent hang (the front dropped a command whose tag read as an unknown atom).
- `ref` and `link` are reserved words: a record field or a function named either is E1040 or E1069. The record uses `peer`; the actor behaviour is `conn`.
- A sequence that declares `device_io` but only calls helpers that print is E3010 (the effect must be used directly in that sequence).
- `a == b and c == d` was avoided by binding the comparison first (not shown to fail, avoided after the first hang).
- Unchanged and respected: `state_policy` on every spawn, regions with buffers (none here), atoms only through `bees_atoms`, no type conversion (a `b2i` case, a status-to-atom case), records built inline in the returned state tuple (no W2300 reported for the actors here). The code is small per unit (each root is about 330 lines).

## 4. Decisions to review

1. **Branching on tainted tags in the owner.** The owner reads the events' `tag` and `reason`, counts them and prints words. Strict taint (spec 7.4) says a branch on foreign data is itself derived data, so a conforming owner could not even read the tag. It works today only because the handler of an FFI result cast is unchecked (SD-25), and the workers cast records they built by branching on status codes (allowed inside the worker's `external_danger` sequence, since the cast is the FFI result cast). When Silica checks handlers, or starts treating the carrier events as tainted, this stops compiling and needs `Recreatable`. The M0 rule (do not forward) is kept: no handler passes a word on; printing is the only use.
2. **A segment is one 8-byte word (an `int64`), not a `string`.** A string cannot be built from foreign bytes without re-creation. A frame is a run of segments; the trial's frame is four words and the owner grants four receive credits. The contract's `(:tx, segment: string, ...)` swaps in when `Recreatable` and `buf(uint8)` at the boundary are available.
3. **Flat records for the contract's tagged tuples**, because a tag is an atom and D30 keeps atom literals in `bees_atoms`. The language's carrier will use real tuples; the owner's two small `case` helpers change, nothing else.
4. **Address text** `listen:`/`connect:` with `127.0.0.1` literally; any other host text is refused, `localhost` and `127.0.0.2` included. A listener accepts **one** peer and closes its listening endpoint. The contract's "a listener spawns one carrier per accepted peer" is not built.
5. **Refusal is `link_down :fault`**, the same reason as a bind failure. The C status code (10 refused, 11 malformed, 12 failure) is not visible to the owner; adding a reason atom would extend the contract's list, so it was not done.
6. **An idle read ends the link** with `timeout` after `io_ms` (the poll timeout). That is a dead-link rule like a tick, not TCP's own. A real node will want a longer value and ticks above it (M3).
7. **Send credit is advisory.** The carrier does not count `:tx` against `:tx_credit` and never answers `(:tx_failed, :no_credit)`: the completion of a write is foreign data, so the carrier (a handler) could not use it for accounting. Receive credit is exact.
8. **Five actors and three OS threads per link** (front, conn, ctl, rd, wr), because a worker can answer only its designated receiver and the owner is known only at `:open`. A pool (A8.3) is not built.
9. **Generated root unit.** The edge section is generated into each program's root unit (SD-17), as S4 anticipated. If Silica accepts a worker in a library, `bees_edge_gen.py` and the `.pair`-style duplication go away.
10. **The slot is chosen by the program** (0 to 7) and no descriptor is ever returned to Silica, because a returned value is tainted and could not be handed back to a worker.

## 5. Not covered

- **`Recreatable` and decoding.** Words are printed, not decoded or checked; no frame is parsed. M3's receive path still waits on chunk 13.
- **Strings as segments, `WireFrame`'s length prefix, ETF on this link, the handshake.** M3.
- **TLS** (S12), **credit enforcement on send**, `:tx_failed` with `:no_credit` or `:too_long`, **more than one peer per listener**, reconnect, orderly drain on `:close` (a close races any write still queued in the writer: the trial closes only after every write completed).
- **Supervision**: the trial programs spawn plainly under the runtime's root supervisor; a compiler lowering must add the carrier to its root supervisor (memory: compiler supervises every actor).
- **Other platforms.** Built and run on macOS arm64 only; the C uses `SO_NOSIGPIPE` under `#ifdef` and POSIX calls, untested on Linux. The pair uses fixed ports (47311, 47321, 47322): a program already holding one fails the trial.
- **Connector started first** is supported by the C retry (25 ms until `open_ms`) but the committed pair runs the listener first.
- **Throughput and memory**: not measured. Each event is built by record-returning helpers, which leak stack per call (SD-21 was closed, but not re-measured here).
