# SD-41: per-message state compaction uses up an actor's reservation (`type_surface_cache` → `:out_of_memory`)

A report for whoever fixes the Silica compiler and runtime. BEES does not change Silica (its rule is to report a defect
and wait). The entry in `development-plan/silica-defects.md` is SD-41.

- **Found:** 2026-11-12. **Diagnosed:** 2026-11-13. **Fixed:** in `silica-999916-macos-applesilicon` (2026-11-13); the three BEES leaves build and pass with it, at peak RSS 361-558 MB.
- **Compiler:** `silica-999919-macos-applesilicon`, built from the tree at `43a22cef4e` (2026-11-12).
- **Host:** macOS (Darwin 25.6.0) on Apple Silicon, 16 GB RAM, about 3 GB of swap when diagnosed (macOS grows swap on demand).

## 1. Summary

An actor whose behaviour is **unproven** (ACB #560 = 0) and that runs with the release algorithm **`:keep_high_water`**
loses about **1 MB of its reservation on every message**, however small its state is.

- After each message, `_silica_rt_state_dispatch_end` calls `_silica_rt_state_copy_all`.
- `copy_all` always puts its scratch block below the bottom of the committed run, so every call commits at least one
  more growth chunk (1 MB).
- `:keep_high_water` never gives those pages back, so the committed run creeps down 1 MB per message.
- When it reaches the base of the reservation, `_silica_rt_stack_grow_to` reports the reservation exhausted, `copy_all`
  returns 2 (no room), and `dispatch_end` ends the actor with `(:explicit, :out_of_memory)`.

The compiler's own `type_surface_cache` actor fits this pattern. It gets one message per type-surface lookup, so any
unit that makes more lookups than its reservation has megabytes crashes the compiler. On this host that is about
19,000 to 22,000 lookups.

## 2. Effects

- **The compiler crashes on ordinary, small units.**
  - The log shows `type_surface_cache_cache_beh` ending with `(:explicit, :out_of_memory)`, then `main_compile_beh`
    ending with `(:explicit, :actor_not_found)`, then `:restart_intensity_breach`, and the process exits 76.
  - The unit is recorded in `silica.compile.crashed` and skipped.
  - In BEES, three leaves fail this way. In `a03_module_table`, the failing unit is `lib/bees_modules.silica` (about
    15 KB); it uses `mod_wide`, which has 120 entries.
- **Whether a unit passes depends on the host, not on the unit alone.**
  - The default reservation is `hw.memsize + vm.swapusage.xsu_total`, read once at process start
    (`prims_actors_stack_asm.silica`, around lines 160–200).
  - So the same unit passes on a machine with more RAM and fails on one with less. These leaves passed on 2026-11-10
    on a larger machine.
  - It can even change between runs on the same machine, because macOS resizes swap. One run failed at 19,456 MB,
    another at 22,171 MB.
- **It is misdiagnosed as memory pressure.**
  - The pages are committed with `mprotect(PROT_READ|PROT_WRITE)`, and each 1 MB chunk has only about 37 KB written
    to it.
  - So RSS stays near 1 GB, the compressor holds nothing for the process, and the machine reports 78% free while the
    actor fails "out of memory".
  - Closing other applications does not help.
- **The same failure was already seen on Linux.** `compiler/design_documents/transport_hosted_ethernet_plan.md`, under
  "Compiler problems found", records `type_surface_cache` failing with `:out_of_memory` on a 3.9 GB host at about
  500 MB RSS, and passing once the host had 16 GB. That note guessed this cause; the measurements below confirm it.
- **Two other actors are probably exposed. This is inferred, not measured.**
  - `compiler/src/type_checker/type_checker_callee_env_cache.silica:145` (`:callee_env_cache`) and
    `compiler/src/parser/parse_in_actor.silica:236` use the same `stack_policy(0, :keep_high_water)` and
    `state_policy(:keep_state_area)`.
  - A second actor in the trace (ACB `0x1012f0f40`) made 1,029 `copy_all` calls in the same compile.
  - Any user program with a long-lived, unproven actor under `:keep_high_water` has the same limit.

## 3. Mechanism, with code

All paths are in `compiler/src/emitter/apple_silicon_mac/terms/prims/`.

**1. The reservation and how it grows.** See the header of `prims_actors_stack_asm.silica` (lines 18–30) and
`_silica_rt_stack_grow_to` (line 564).

- At spawn the runtime reserves one contiguous `PROT_NONE` range of the default size.
- `grow_to(ACB, addr)` makes pages usable below the committed run in chunks (#304: one page at first, doubling to 1 MB,
  then 1 MB per chunk) until `addr` is covered.
- It returns 1 when it would reach the reservation's lowest page.

**2. Every message of an unproven behaviour ends in `copy_all`.** `_silica_rt_state_dispatch_end` (line 1933):

```
ldr x9, [x19, #560]   ; proven?
cbz x9, Lsde_copy_all ; no  -> full copy
ldr x9, [x19, #584]   ; compaction requested?
cbnz x9, Lsde_copy_all
...                   ; proven: _silica_rt_state_evacuate
```

**3. `copy_all` always places its scratch below the committed run.** `_silica_rt_state_copy_all` (line 1765):

```
B       = measure(root) rounded to 16
newbot  = top - 1040 - B                 ; where the compacted state will live
runbot  = top - committed(#288)
hi      = min(newbot, runbot)
scratch = hi - B                         ; always below runbot
if scratch < runbot: grow_to(ACB, scratch)   ; ret 1 or 2 -> Lsca_noroom (X1 = 2)
copy into [scratch, hi), memcpy to [newbot, newbot + B), heads zeroed, #528 = newbot, #568 = B
```

- `scratch` is below `runbot` on every call, so every call reaches `grow_to`.
- `grow_to` commits a whole chunk (1 MB in steady state), not B bytes. The next call's `runbot` is therefore 1 MB
  lower, and its scratch goes below that.
- The space between the state area and `runbot` is dead. It held the behaviour's frames, which are gone by the time
  `dispatch_end` runs, and earlier scratch blocks. It is never reused.

**4. Nothing gives the pages back.** With release algorithm 5 (`:keep_high_water`, ACB #312 = 5), the release step at
the message boundary keeps the committed run at its high-water mark. The state policy is 0 (`:keep_state_area`) and
does not touch the stack side.

**5. The end.** Once `runbot` is less than B above the reservation base, `grow_to` returns 1, `copy_all` returns
`X1 = 2`, and `dispatch_end` fails the actor with `(:explicit, :out_of_memory)`, because #376 = 0, the default
reservation (the comment near line 2146).

**Possibly the same in the proven path. Not verified.** `_silica_rt_state_evacuate`'s header says its scratch "grows
down from the bottom of the committed run". If so, a proven behaviour under `:keep_high_water` may creep the same way,
in steps the size of the evacuated nodes.

## 4. Evidence

The compile of `a03_module_table` was run under lldb. Mach `EXC_BAD_ACCESS` was ignored so that the runtime's own
fault-driven growth works, with breakpoints on `silica_rt_state_copy_all`, `silica_rt_stack_grow_to` and
`silica_rt_actor_fail_current`.

**The failing actor's ACB when it failed** (an earlier run with a 19 GB reservation):

| Field | Value |
| --- | --- |
| #272 base | `0x8c80000000` |
| #280 reservation | `0x4c0000000` (19,456 MB) |
| #288 committed | `0x4bfffc000` (the reservation less one 16 KB page) |
| #296 high water | `0x4bfffc000` |
| #528 edge | `0x913fff6a10` (about 38 KB below the top) |
| #568 live state bytes | `0x91e0` (37,344) |
| failure site | `silica_rt_actor_fail_current` ← `silica_rt_state_dispatch_end + 296` ← `actor_thread_main` |

**Every `copy_all` call on that actor** (a later run with a 22 GB reservation; values read from the ACB on entry):

| Call | committed (MB) | live bytes (#568) | #312 algorithm | #576 state policy | #560 proven | #584 compact |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 0 | 96 | 5 | 0 | 0 | 0 |
| 1,000 | 994 | 32,976 | 5 | 0 | 0 | 0 |
| 5,000 | 4,994 | 32,976 | 5 | 0 | 0 | 0 |
| 10,000 | 9,994 | 32,976 | 5 | 0 | 0 | 0 |
| 22,177 (last) | 22,171 | 43,776 | 5 | 0 | 0 | 0 |

- **The step is exactly 1 MB per call.** In the `grow_to` trace, 19,199 of 19,200 consecutive commits on this actor were
  exactly +1.00 MB, all from `silica_rt_state_copy_all + 120` ← `silica_rt_state_dispatch_end + 296`.
- **The whole process stayed small.** RSS peaked at 1.57 GB (`/usr/bin/time -l`), the footprint was about 1 GB, the
  compressor held 0 B for the process, and the system was 78% free. The virtual size was about 580 GB: roughly 30
  reservations of about 19 GB each.

## 5. How to reproduce

From a BEES checkout next to the Silica checkout (`../silica`):

```
cd trials/a03_module_table
rm -f silica.compile.crashed silica.compile.inprogress    # the crash record outlives a batch
make build SILICA_COMPILER=../../../silica/binaries/silica-999919-macos-applesilicon
# -> "lib/bees_modules.silica ... Type checking..." then the failures in §2, exit 76
```

`trials/m1_wire_reject` and `trials/m1_wire_types_records` fail the same way.

**The lldb probe** (run in the leaf after the `rm` above, so that one process compiles every unit):

```python
# ca.py
import lldb
def ca(frame, bp_loc, d):
    p = frame.GetThread().GetProcess(); e = lldb.SBError()
    a = frame.FindRegister("x0").GetValueAsUnsigned()
    q = lambda o: p.ReadUnsignedFromMemory(a + o, 8, e)
    print("CA acb=%x committedMB=%d live=%d alg=%d spol=%d proven=%d compact=%d"
          % (a, q(288) >> 20, q(568), q(312), q(576), q(560), q(584)))
    return False
```

```
settings set platform.plugin.darwin.ignored-exceptions EXC_BAD_ACCESS
process handle SIGSEGV -s false -p true -n false
process handle SIGBUS -s false -p true -n false
process handle SIGALRM -s false -p true -n false
command script import ca.py
br set -n silica_rt_state_copy_all
br command add -F ca.ca 1
br set -n silica_rt_actor_fail_current
```

`lldb -b -s probe.cmds -o run -k "bt 6" -k quit <compiler>`

**A minimal reproducer in Silica alone (suggested, not built):** a registered actor with a small record state, an
unproven behaviour, `stack_policy(0, :keep_high_water)` and `state_policy(:keep_state_area)`, sent about 30,000 casts.
On a 16 GB host it should end with `:out_of_memory` at about (RAM + swap) / 1 MB messages. With a lowered reservation,
such as `stack_policy(64 MB, :keep_high_water)`, it should end with `:reservation_exceeded` after about 64 messages,
which makes a fast, host-independent test.

## 6. What a fix has to achieve

These are criteria, not a prescribed design. The choice belongs to Silica.

1. A long-lived actor's committed run must be bounded by its live state plus its deepest stack, not by the number of
   messages it has handled.
2. The test from §5 with a lowered reservation must survive any number of messages when the live state and the stack
   fit in the reservation.
3. `trials/a03_module_table`, `m1_wire_reject` and `m1_wire_types_records` must build on a 16 GB host, and their peak
   RSS should not rise.
4. The same must hold in the proven (evacuation) path, if §3's note about it turns out to be true.

**Directions seen while diagnosing, none tried:**

- Place `copy_all`'s scratch inside the already-committed dead area between the state area and `runbot` when it fits
  (it is at least 1 MB after the first chunk), and commit below `runbot` only when it does not.
- Or release the scratch's pages after the `memcpy`. This is the same as `_silica_rt_stack_release_to`, applied to the
  scratch whatever the release algorithm.
- Separately, ask why `type_surface_cache`'s behaviour is unproven (#560 = 0). A proven behaviour would avoid a full
  copy per lookup, which would also save time.
- Separately, reconsider whether `:keep_high_water` is the right policy for the compiler's caches.

## 7. Related BEES-side change

BEES's `tools/trial.mk` did not delete `silica.compile.crashed` or `silica.compile.inprogress` at the start of a batch,
so later builds of a crashed leaf reported the old crash without compiling anything. This is fixed in BEES
(2026-11-13) and is not a Silica defect, but anyone repeating an earlier BEES result should know about it.
