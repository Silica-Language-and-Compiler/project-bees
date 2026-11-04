# Spike S8 (M0 of the MVP): can BEES re-create bytes by hand?

**Status:** run 2026-11-04 on `silica-999939-macos-applesilicon`. **Result: no safe hand-written route exists today. The
receive path needs Silica's `Recreatable`.**
**Trials:** `trials/m0_recreation` (two passing entries, five rejected sources in `rejected/`).

## Question

Bytes returned by a foreign call are tainted and may not leave the handler that receives them. `Recreatable`
(compiler-derived re-creation) is not implemented. Could BEES rebuild each value from literals chosen by branching on
the tainted bytes (a 256-way `case` from a byte to its literal), so that the result depends on the input only through
control flow?

## What the checker does today (read from `compiler/src/ffi/ffi_taint_checker.silica`, then confirmed by compiling)

1. **Taint is seeded only on calls qualified with a `dangerous_` module** (`dangerous_m0_fixture@fixture_word(...)`).
   A raw `foreign c_wrapper` binding called directly in the worker's own unit is **not tracked**. The earlier S4 spike
   used that shape, so its values were never tainted.
2. **Inside the worker's `external_danger` sequence taint is enforced** (E2100 in `produces pure`, E2101 regions in ordinary
   casts, E2102 region escape, E2103 restricted effects).
3. **The handler that receives the FFI result cast is not checked at all.** Nothing marks its parameter tainted.
   Forwarding the raw word onward by an ordinary cast compiles and runs. The specification (7.6) forbids it.
4. **Re-creation is not implemented** (specification status note, 2026-10-16).

## Result

| Variant | Outcome |
| --- | --- |
| Worker puts an untainted literal in `produces pure` (control) | Compiles and runs. |
| Worker puts the raw word in `produces pure` | **E2100.** |
| ... a `case` over the word with literal arms | **E2100.** |
| ... the result of a helper that does that `case` | **E2100.** |
| ... `word + 1` | **E2100.** |
| ... a comparison turned into literals | **E2100.** |
| Handler forwards the raw word by an ordinary cast | Compiles and runs (unchecked). |

Silica treats **every value derived from a tainted one as tainted**, including a literal chosen by a branch on it. The
hand-written route is rejected where Silica enforces taint, as the specification says it must be.

## Consequences for BEES

- The MVP's receive path cannot rebuild frames inside the worker. The only route that compiles is forwarding from the
  unchecked handler, which the specification forbids and which Silica may start rejecting at any time. **BEES does not
  build on it.**
- Receiving from the network waits on Silica's `Recreatable` (Silica ROADMAP chunk 13). The sending half, the wire
  codec and the sockets do not.
- The old S4 spike results stand, but they proved less than they appeared to: the foreign values there were untracked.

## Silica details met

- A plain adapter must keep the foreign call out of tail position (`raw(idx) + 0`) or it faults at run time (the known
  adapter tail-call defect); an adapter written as a `sequence proc[external_danger]` is treated as a worker (E4041).
- A unit that declares a foreign function must be named `dangerous_*`, so a compile-fail trial cannot use the harness's
  `fail_` prefix (E4006).
