# Spike S10: Failure paths

**Status:** run 2026-09-17 on `silica-999977-macos-applesilicon`. **Confirms D2's shape; the explicit
reason atoms (S-9) do not exist yet.**
**Trial:** `trials/s10_failure_paths/bif_failure_restarts_child.silica`.

## 1. What happens today

| Event in a supervised, permanent, call-only child | Result |
| --- | --- |
| Integer division by zero (the analogue of `badarith`) | The actor ends. Crash report: `reason_tag: 1`, the child's `agent_type_atom`, the supervisor's ACB, and the behaviour's symbol as frame #0. The supervisor restarts the child **with its initial state** (`get_child` then returns a working child whose state is fresh). |
| A `case` with no matching clause (the analogue of `case_clause`) | The same, with `reason_tag: 2`. |
| The pending `call` whose callee died | **Returns the zero value of the reply type** (`0` for `int64`), not a distinguishable death result (SD-9). |
| The crash report | Goes to stderr (no `FailureReporter` registered), asynchronously; it appears before the caller's next line. |

## 2. What this means for BEES

- **D2 holds:** a failing BIF ends the actor and the supervisor handles it; nothing is caught inside
  the actor, and the restart gives a fresh state.
- **Reasons are numbers, not atoms:** `reason_tag` 0/1/2 (normal / abnormal / case clause). The
  spec's `(:explicit, :badarg)` and `fail_self(reason)` are S-9, specified 2026-09-15 and not
  implemented. Until then a BEES BIF cannot name its failure; it can only fail (division by zero,
  or an unmatched `case`). The exit hub and BEAM-mode `EXIT` translation will see `reason_tag`
  only.
- **A `call` to a dying or dead actor cannot detect the death from its result** (SD-9): the
  reply is the zero value of the reply type. For a `bees_term` reply that zero value is a null
  region reference, which the caller must not dereference. This weakens D20's rationale ("a
  pending call already wakes with the callee's death result") until Silica gives `call` a real
  failure result; the ledger's S-9 already lists this as its open question.
- `call_supervisor` needs no effect declaration; a sequence around it alone must not declare
  `concurrency` (E3010).

## 4. Re-run 2026-11-04 on `silica-999939-macos-applesilicon`

The trial was rewritten (`bif_failure_restarts_child.silica`); the 2026-09-17 results above are history.

| Event | Result now |
| --- | --- |
| `fail_self(:badarg)` in a supervised call-only worker | Report `reason: (:explicit, :badarg)`, `reason_tag: 4`. S-9's explicit reason now exists. The supervisor restarts the worker with its initial state. |
| Integer division by zero | Report `reason: :language_error — integer division by zero`, `reason_tag: 2` (the old tag 1 is no longer written). |
| A `call` whose callee dies | **Raises `actor_not_found` in the caller**, which fails with `(:explicit, :actor_not_found)`. It no longer returns the zero value. **SD-9 is closed by design.** |
| A `case` with no catch-all arm | Rejected at compile time (E2008). The old "case_clause" runtime failure can no longer be written, which fits D2 ("catch failures at compile time"). A compiler lowering Erlang `case` must emit an explicit failing catch-all (`fail_self(:case_clause)`). |

Consequences for BEES:
- D2 holds, and a BIF now names its failure: `fail_self(:badarg)` reaches the supervisor, and the
  exit hub, as `(:explicit, :badarg)`. S-9's explicit stop is delivered.
- D20's rationale ("a pending call already wakes with the callee's death result") is restored: the
  death result is a failure of the caller, not a value. A BEES `call` to a dead process fails the
  caller; code that wants a value uses the call-with-timeout variant (D2) instead.
- The first banner order is asynchronous (reports are written by the FailureReporter); the trial
  separates phases with a spin, so it is timing-sensitive. A deterministic version needs the
  exit hub (S7).
