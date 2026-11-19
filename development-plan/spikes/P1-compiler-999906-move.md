# P1: moving the compiler pin from 999909 to 999906 (phase 1: measurement only)

**Status: measured 2026-11-18 on macOS Apple Silicon. Nothing in the project was changed: the pin (`tools/silica.generation`,
`silica-999909-macos-applesilicon`) stands, no golden was re-recorded, no workaround was removed. Phase 2 (section 7) does that.**
Read with: Silica's replies (`~/Downloads/silica-requests-replies.md`, 2026-11-17), BEES's requests (`~/silica-requests.md`),
[silica-defects.md](../silica-defects.md), [roadmap.md](../roadmap.md) D30, D42, D45,
[N0c-library-api-probe.md](N0c-library-api-probe.md) sections 0, 2.3, 10, [S14-name-resolution.md](S14-name-resolution.md),
[N1-addresses-and-limits.md](N1-addresses-and-limits.md), [N2b-multi-link.md](N2b-multi-link.md).

Every statement below is marked **observed** (with the compiler that produced it: 909 = `silica-999909-macos-applesilicon`, the
pin; 906 = `silica-999906-macos-applesilicon`, the refreshed one) or **inferred** / **read** (taken from a source text, not run).

## 0. Method, and the findings in one page

**Method.** The project tree was copied twice into the session scratch directory with `rsync -a` and the exclude list of
`tools/run_all_trials.py` (`SYNC_EXCLUDES` plus `exe_excludes()`: objects, archives, `.sams`, `.iface`, `.sout`, built executables,
`silica.*` products, `native/build`, `native/dangerous_exposure_source/lib`, `.git`, `trial_runs`): one copy for 906
(`.../scratchpad/p1/project-bees`) and one for 909 (`.../scratchpad/p1/909/project-bees`), each beside a link `silica ->
/Users/yenrab/silica` so that the trials' relative `lib/` links resolve. Native was built once per copy (`make -C native`, which
compiles the Silica tree's `silica_sockets.c` into the copy). Every `make` took `SILICA_COMPILER=<path>` and
`SILICA_ROOT=/Users/yenrab/silica` on its command line (the runner hands the compiler on from its environment). One compile ran at a
time (the runner's compile slot, shared by every probe build through `BEES_SLOT_DIR`). After the runs no file under
`/Users/yenrab/silica/compiler/stdlib` or `binaries` was newer than the start stamp (**observed**): the compiler writes its
`.iface`, `.o`, `.sams` beside the link in the copy's `lib/`, not through it. The copy was taken at about 14:03; files other agents
changed after that are not in it.

**Findings.**

1. **No existing trial changes its output on 906.** 65 of 65 leaves pass against the goldens in the tree (211 entries, 0 failed;
   **observed, 906**, `tools/run_all_trials.sh --local-only --compile-jobs 1 -j 2 --no-kit`, 2,380 s). The one known change,
   `s01_trait_mapping/sd23_cast_from_region_state_child_second_dispatch`, is already recorded for 906 and therefore fails on the
   pin (**observed, 909**: `s01_trait_mapping` 4 passed, 1 failed in the 909 copy). Section 1.
2. **Fixed on 906, each with a small program run on both compilers** (section 2): atoms used only in a type and a pattern (A1);
   records of more than four fields in the derived decoder (SD-37); the state-release proof with a `dangerous_actor_ref`
   (SD-39); `cast` to an ended actor returns `false` (SD-43), from a plain actor, to an ended carrier, and from an FFI worker;
   the per-carrier leak (SD-46).
3. **Not fixed on 906: SD-44.** A tagged-tuple-returning call written inline as an argument beside a string-returning call
   still faults at run time, on 909 and on 906 alike (**observed, both**), with a one-file reproduction (section 2.3). Silica's
   reply lists C2 (SD-44 and SD-45) as done. **The bind-before-passing rule stays.** This is the one thing to report to Silica.
4. **Unchanged between 909 and 906:** SD-35 (the whole-state copy). The same behaviours are unproven (W2300) on both, and the
   8 MiB frame of `trials/n1_frames` peaks at 89 MiB and 184 MiB on both (it was 628 and 703 MiB on 999926). The reduction
   Silica reports was already in the pin. Section 2.6.
5. **The carrier leak is gone on 906:** 0.53 KiB per ended carrier on 909, about 0.01 on 906; a BEAM-mode or M3 link 0.55 KiB
   on 909, 0.07 on 906; a TRUST call 0.83 (server) and 0.62 (client) KiB on 909, 0.31 and 0.09 on 906. Section 3.
6. **The new address forms of the `(:tcp)` carrier are a stdlib and C feature, not a compiler feature:** every probe gave the
   same result on 909 and on 906 (**observed, both**), because both compile the same `dangerous_tcp_carrier.silica`,
   `dangerous_sockets.silica` and `silica_sockets.c` from the Silica tree. Task C does not wait on the pin. Section 4.
7. **The carrier does not dial a name.** It binds one IPv4 address, binds and dials IPv6, and binds a listener by name; a dial
   takes an address only (`"localhost:23690:1000"` ends `(:explicit, :bad_address)`, **observed, both**), by Silica's decision
   (design 6.3: "a name binds, a name is not dialled ... Project BEES resolves its peers itself, by ruling"). So D42's goal
   ("resolution moves fully to Silica") is not met by this release, and **the BEES resolver stays**; it gains IPv6. Section 4.4.

## 1. Which trials change output on 906

**Run (observed, 906).** In the 906 copy: `SILICA_COMPILER=.../silica-999906-macos-applesilicon SILICA_ROOT=/Users/yenrab/silica
tools/run_all_trials.sh --local-only --compile-jobs 1 -j 2 --no-kit --only <the 65 leaves> --log-dir .../p1/logs906`. Result:
`65 of 65 trials passed`, 211 entries passed, 0 failed. The machine was shared (load average 11 to 32) and other agents ran the
same trials in the real tree on the same ports during the run; no leaf needed a second run.

| Leaf / entry | 906 | 909 | Diff | Cause |
| --- | --- | --- | --- | --- |
| all 65 leaves run (list below) | pass | (the goldens are the pin's) | none | no golden prints anything the fixes changed |
| `s01_trait_mapping/sd23_cast_from_region_state_child_second_dispatch` | pass (golden re-recorded for 906 earlier today) | **fails** (observed in the 909 copy: 4 passed, 1 failed) | 909 prints one failure report, `reason: :language_error` then `(:explicit, :actor_not_found)`, `exit=1`; the golden holds a second report, `0`, `0`, `exit=0` | `cast` to an ended actor returns `false` on 906 and ends the caller on 909 |

Leaves run: `a02_exit_listener a02_ring a02_spawn_supervisor a03_id_pools a03_module_table a03_position_map m0_recreation
m1_wire_memory m1_wire_reject m1_wire_types m1_wire_types_b m1_wire_types_float32 m1_wire_types_float64 m1_wire_types_lists
m1_wire_types_lists_b m1_wire_types_records m1_wire_types_signed_a m1_wire_types_signed_a_b m1_wire_types_signed_b
m1_wire_types_signed_b_b m1_wire_types_text m1_wire_types_text_b m1_wire_types_u64 m1_wire_types_u64_b m1_wire_words
m2_carrier_tcp m2_ffi_shapes m3_actor_shapes m3_decode_probe m3_dist m3_dist_frames m3_mesh m3_multilink m3_reconnect m4_demo
n1_addr n1_frames n1_limits n2_auth n2_carrier_leak n2_dist n2_frames n2_live n2_mesh n2_multilink n2_reconnect n2_soak n3_trust
n3_trust_frames n4_trust_tls name_resolution r01_harness r02_many_atoms s01_trait_mapping s02_cross_unit_atoms s03_actor_ceiling
s04_native_edge s05_bytes_without_conversion s06_terms_and_regions s07_exit_reports s09_reference_lowerings s10_failure_paths
s11_balancing_migrate s13_lifecycle_cost silica_defects`.

What the unchanged goldens say about the replies (**observed, 906**, each by its leaf passing):

- **Atom numbers did not shift anywhere a golden prints one.** The only printed atom number is `agent_type_atom: 29`
  (`s01_trait_mapping`), unchanged. Programs that return an atom as their exit code: none among the goldens changed.
- **Reports did not change** (`a02_spawn_supervisor`, `s07_exit_reports`, `s10_failure_paths`, the negative suites of
  `n3_trust` and `n4_trust_tls`).
- **Defects whose golden records the wrong output are still there on 906:** SD-26 (`sd26_float_prepend_argument`: 0.0),
  SD-38 (`sd38_char_of_code_misses_literal_pattern`), SD-40 (`dangerous_sd40_ffi_string_argument_from_call`: `inline 1`),
  SD-33 (`m3_actor_shapes/missing_name`: `cast_registered` to an unheld name still ends the caller, as Silica's reply says),
  SD-34 (`m3_actor_shapes/link_death`). `trials/silica_defects` is 16 of 16 on both compilers (**observed, 909 and 906**).
- **The unproven behaviours are the same.** The W2300 lines of the build logs of `m3_dist`, `n2_dist`, `m4_demo`, `n1_frames`,
  `n3_trust` and `n4_trust_tls` name the same behaviours on 906 as in the real tree's 909 run `trial_runs/20261118-135130`
  (`asm` and `tasm`: slot `rx` replaced; `epm`; `ttls`; the stdlib `carrier`; a trial's `owner`) (**observed, both**; the counts
  differ only where the 909 log is of a partly built leaf).

**Not run, to check in phase 2** (leaves other agents were changing; several did not exist when the copy was taken):
`t0_tempus_view t1_tempus_store t2_tempus_frames t3_tempus_nodes t4_tempus_admission t5_tempus_link t5_tempus_tls n5_trust_mux
n5_trust_mux_tls n2t_live n2t_pair c1_codec_map c1_codec_optref c1_codec_sum c1_codec_term f1_fuzz_wire f2_fuzz_long`, and the
two-machine `x1_interchange_beam`, `x2_interchange_trust` (`make interchange`). Expect a change wherever one of them prints the
result of a cast to an ended actor or records a workaround's failure (for example `t0_tempus_view/sd_own_len_function`, SD-48,
which was not tried on 906; and the wire generator's refusal of a sum that starts with an atom literal,
`tools/bees_wire_gen.py:233`, a pin defect seen by C1 that was not tried on 906).

## 2. Which workarounds can go

Probe programs are in the scratch area (`.../scratchpad/p1/wk_src/`, built as leaves `trials/p1_wk`, `p1_wkc`, `p1_44`, `p1_wide`
of the two copies); the ones that matter are quoted inline. File and line numbers are of the real tree at about 14:15 to 14:30
today; other agents are editing some of these files, so re-run the greps in phase 2.

| | Workaround | 909 (observed) | 906 (observed) | Can it go |
| --- | --- | --- | --- | --- |
| a | atoms-first unit rule (A1; N0c section 10) | fails: `no case arm matched` | **fixed**: `go received`, `stop received` | the ordering rule, yes; `bees_atoms` itself stays (2.1) |
| b | four-field limit (SD-37) | fails to compile: `more than 8 parameters` | **fixed**: 5, 9 and 22 fields decode | yes, for decoded records (2.2) |
| c | bind before passing (SD-44, SD-45, SD-31) | SD-44 faults; SD-45 and SD-31 not reproduced by small probes | **SD-44 still faults**; SD-45 and SD-31 probes pass | **no** (2.3) |
| d | teardown order, 2 s wait (SD-43) | caster ends with `actor_not_found` | **fixed**: `cast` returns `false` (plain, carrier, FFI worker) | the wait and the ordering, yes; the teardown itself stays (2.4) |
| e | one-at-a-time carrier credit (D45) | not measured | not measured; its cause (SD-43) is fixed | TLS: yes, to be measured; M3/BEAM assembler: no (2.5) |
| f | whole-state copy handling (SD-35) | W2300 on `asm`; 89 / 184 MiB for an 8 MiB frame | the same | **no** (2.6) |
| g | never replace a `dangerous_actor_ref` in state (SD-39) | W2300: `'car_after' is not a logging updater` | **fixed**: no W2300 | yes (2.7) |
| | SD-46 per-carrier leak | 0.53 KiB per carrier | about 0.01 | nothing to remove; section 3 |

### 2.1 (a) Atoms used only in a type and a pattern (A1)

**Probe (observed).** N0c's variant `v1`: `lib/rx.silica` holds a behaviour over `(:go, int64) | (:stop, int64)` with a pattern
for each and no expression literal; the root, compiled later, casts `(:go, 1)` and `(:stop, 2)`. 909: the failure report
`:language_error — no case arm matched, #0 rx_beh`. 906: `go received`, `stop received`.

**Where the rule lives.**

- The decision and its check: `development-plan/roadmap.md` D30 (line 608 and 172, 298 to 314, 341, 416, 423);
  `tools/bees_config.py:8,48,114,122,312,645,660,669` (generation of `bees_atoms`, and the check that refuses an atom literal
  outside it); `tools/trial.mk:57`; `tools/bees_dist_gen.py:32,282`; `tools/gen_bees_term.py:31`; `tools/bees_config_beam.py:180`;
  `contract/so-you-want-to-write-a-compiler.md:246`.
- The narrowed rule ("the atom unit is listed first and writes every atom as an expression literal"):
  `development-plan/spikes/N0c-library-api-probe.md` section 0 item 3 and section 10 (the defect draft is now answered), and the
  rulings at the top of that file.
- Its mark on the code: every message between BEES units carries the one tag `:bees` and an integer kind instead of a tag per
  message (`src/inter_nodal/dangerous_bees_net.silica:35,60`, `src/inter_nodal/dangerous_beam_net.silica:54,806`,
  `src/trust/dangerous_bees_trust.silica:45,80`, `src/trust/dangerous_bees_trust_edge.silica:20`,
  `src/inter_nodal/dangerous_beam_auth.silica:85`, `src/tempus/dangerous_bees_tempus_conn.silica:178,196,356`,
  `src/tempus/dangerous_bees_tempus_edge.silica:26`, `src/shim/bees_trust_node.part:158`, `tools/bees_trust_mux_gen.py:272,376`),
  and atoms come from `bees_atoms@a_<name>()` (`src/trust/dangerous_bees_tls.silica:40`, `dangerous_bees_trust.silica:46`,
  `src/shim/bees_term.silica:9`; the generated `trials/*/lib/bees_atoms.silica`).

**Can it go.** The ordering rule and the "expression literal somewhere earlier" condition can go: a library behaviour may name
its message tags in its type and patterns only (**observed, 906**, one shape: tuple tags, a behaviour spawned by reference from a
later unit). `bees_atoms` stays for what it is besides a workaround: the table that maps BEAM atoms to spellings for the wire
(`spelling`, `from_spelling`, D16's unknown-atom check). The `:bees`-and-kind messages work and need not be rewritten. **Risk:**
only `v1` was run; N0c's other variants (`v9` single-variant union, `v12` unit order, `v7`/`v8` stale `silica.atoms`) were not
re-run on 906, and a build that mixes object files of both compilers was not tried (atom numbers shift, so a stale `.o` or
`silica.atoms` from 909 must not survive the move: clean first).

### 2.2 (b) The four-field limit (SD-37)

**Probe (observed).** `encode` then `decode((:etf), frame)` of a flat record of `int64` fields:

| Fields | 909 | 906 |
| --- | --- | --- |
| 5 | does not compile: `function '__tr_decm_etf__…' has more than 8 parameters; AArch64 calling convention supports at most 8 register arguments` | prints `five fields sum 15` |
| 9 | (not built: same error class) | prints `nine fields sum 45` |
| 22 | not tried | compiles and prints `22 fields, first plus last 23` (SD-36's 22-field case, which did not finish in 300 s on 999936) |

A hand-written function of nine parameters is still E1070 on 906 (**observed**): only the derived walker changed, as the reply says.

**Where it lives.** `src/trust/bees_trust_frame.silica:7,214,433` (the frame is walked by BEES and each value decoded singly);
`src/tempus/bees_tempus_frame.silica:3-4` (every message and nested map at most four keys); `trials/m4_demo/roles/gen_types.py:29,55`
(the payload split into two halves of groups); `contract/wire-v1.md:566`; `development-plan/spikes/N0c-library-api-probe.md` 5.2
("each record at most 4 fields, nested for more": the configuration groups of the store-configuration work);
`development-plan/tempus-design.md` and `mvp.md` where they cite SD-37.

**Can it go.** Yes for records that `decode` reads: configuration groups, TEMPUS bodies and the M4 payload may be flat. **Not
all of the TRUST walk goes with it:** `bees_trust_frame` also walks the map because SEMP ignores unknown top-level keys while the
language's `decode` answers `:unknown_field` (file header, line 5 to 7); that reason is untouched. **Risk:** only `int64` fields
were tried; a wide record of strings, nested records or sums was not; compile time and compiler memory for wide records in a large
program (SD-29, SD-36, SD-41 family) were not measured; the Linux compiler must have the fix before a flat record of five fields
is written anywhere both platforms build (section 6).

### 2.3 (c) Bind every tagged tuple or string before passing it (SD-44, SD-45, SD-31): NOT fixed for SD-44

**Probe (observed, 909 and 906: the same on both).** One file, `use wire_etf;` and the stdlib unit `wire_etf` in `lib/`:

```
use wire_etf;
fn span(body: string, k: int64) -> string {
    sequence proc[mem(normal), transport]
        s: string <- byte_slice(body, k, length_bytes(body))
    produces pure s end
}
fn dec_str(s: string) -> (:ok, string) | (:rejected, atom) {
    sequence proc[mem(normal), transport]
        r: (:ok, string) | (:rejected, atom) <- decode((:etf), s, { max_bytes: 4096, max_depth: 2, max_length: 4000 })
    produces pure r end
}
fn show(a: (:ok, string) | (:rejected, atom), b: string) -> int64 {
    sequence proc[device_io]
        _: atom <- case a of {
            (:ok, t: string) -> println(concat("ok ", t));
            (:rejected, w: atom) -> print_atom(w)
        };
        _: atom <- print(" second length ");
        _: atom <- print_int64(length_bytes(b));
        _: atom <- println("")
    produces pure 0 end
}
fn main() -> int64 {
    sequence proc[mem(normal), transport]
        frame: string <- encode((:etf), "request-17");
        body: string <- concat(frame, "value");
        a: (:ok, string) | (:rejected, atom) <- dec_str(span(frame, 0));
        b: string <- span(body, 3);
        _: int64 <- show(dec_str(frame), span(body, 3))
    produces pure 0 end
}
```

Output on 906: `ok request-17`, then ` second length [silica] fault at 0x… in sd44v_c___tr_dec_etf_string_6_71329895_l4096_2_4000_0_0+0x…
addr=0x…`, `exit=70`. Expected: `ok request-17`, ` second length 18`, `exit=0`. Variants on 906 (**observed**):

| Call | Result |
| --- | --- |
| `show(a, b)` (both bound) | correct |
| `show(dec_str(frame), b)` (only the tagged tuple inline) | correct |
| `show(a, span(body, 3))` (only the string inline) | correct |
| `show(dec_str(span(frame, 0)), b)` (nested call, second bound) | correct |
| `show(dec_str(frame), span(body, 3))` (**both inline**) | **fault**, exit 70 |
| `show(dec_str(span(frame, 0)), length_text(body))` (both inline, the second a `substring` helper) | **fault**, exit 70 |

The first argument arrives intact (its text is printed); the second, the string, is what is wrong when it is read. On 909 the
form `show(dec_str(span(frame, 0)), span(body, 3))` faults the same way (**observed, 909**; the other variants were not built on
909). This is SD-44 as recorded ("a call that returns a tagged tuple, written inline as an argument beside another call
argument"). **It is not a new defect; it is SD-44 still open on 906, against Silica's reply (C2 "Done").** The reply describes the
fix as "a call result typed `discard` or empty was treated as a bare word when it was copied into a message", which is the
message path (SD-45, SD-31), not the argument path.

SD-45 (a string-returning call inline in a cast's tuple) and SD-31 (a record-returning call inline as the cast message) were each
tried with a small program: both deliver correctly on 909 **and** on 906 (**observed**), so these probes do not reproduce the
defects on the pin and prove nothing about the fix. No minimal program for either exists in the tree (silica-defects.md says so).

**Where it lives.** `src/trust/bees_trust_frame.silica:467-468` (SD-44, the parsers); `src/shim/bees_resolve_edge.part:85` (SD-45);
`src/trust/dangerous_bees_trust.silica:617`; `src/shim/bees_tcp_edge.part:9-10`, `src/shim/bees_node_edge.part:7`,
`src/shim/beam_node_edge.part:7` (SD-31, the carrier's initial record spelled out); `src/trust/dangerous_bees_tls.silica:467`,
`src/inter_nodal/dangerous_beam_tls.silica:417`, `src/tempus/dangerous_bees_tempus_tls.silica:444`,
`src/trust/dangerous_bees_trust_mux.silica.in:756`; `tools/bees_pack_gen.py:87`, `tools/bees_wire_gen.py:1005`;
`trials/m2_carrier_tcp/dangerous_m2_connector.silica:19`, `dangerous_m2_listener.silica:19`, `trials/n2_carrier_leak/dangerous_leak.silica:19`;
N0c section 2.3 (the API's examples bind first).

**Can it go.** No. Keep the rule everywhere, including the message forms, until Silica confirms SD-44 and BEES has a program that
fails on the pin and passes on the new compiler for each of SD-45 and SD-31.

### 2.4 (d) Teardown ordering and the 2 s wait (SD-43: a cast to an ended actor)

**Probes (observed).**

| Program | 909 | 906 |
| --- | --- | --- |
| `cast_ended`: a plain actor casts to an actor that has ended | the caster ends: `(:explicit, :actor_not_found)`, `#0 cast_ended_poker` | `cast returned false`; the caster goes on |
| `dangerous_cast_ended_carrier`: the owner casts `(:credit, 1)` to its carrier after a refused open | the owner ends: `actor_not_found` | `cast to the ended carrier returned false`, twice; the owner goes on |
| `dangerous_worker_cast_ended`: an FFI worker (a `spawn_dangerous` behaviour, `external_danger` sequence) casts its answer to an ended actor, then is asked again | the worker ends (`actor_not_found`), and then the actor that casts to the dead worker ends too | the worker survives and answers the next request (`driver: the worker answered, tag 3`) |

`cast_registered` to a name nobody holds still ends the caller on 906 (**observed**, `m3_actor_shapes/missing_name` golden
unchanged); `send`, `call`, `call_with_timeout` were not probed (**read**: Silica's reply says they still raise).

**Where it lives.** `src/inter_nodal/dangerous_bees_net.silica:189,496-506,579` (the flags `fl`, `done`, `fin`: a link's actors end
only when nothing can cast to them); `src/inter_nodal/dangerous_beam_net.silica:160,555-562` (`grace`, `arm_grace`: `send_after(2000,
…)`, the wait for the cookie worker's late replies), `:677,782,981`; `src/trust/dangerous_bees_trust.silica:27,86-88` (`tx_end` kind 10
against kind 3), `:444`, and the 500 ms reap; `src/trust/dangerous_bees_tls.silica:19,42`; `src/tempus/dangerous_bees_tempus_tls.silica:3`;
`tools/bees_dist_gen.py:207`; `tools/soak.py:64` (the 4 s settle for the grace timers); `src/README.md:36`;
`development-plan/spikes/N2b-multi-link.md` "Teardown".

**Can it go.** In parts. (1) The **2 s grace** in `dangerous_beam_net` exists only so that the shared cookie worker never casts
to an ended connection actor; on 906 that cast returns `false` and the worker lives (**observed** for the shape, not for the cookie
worker itself): it can go. (2) The **ordering conditions** (wait for the carrier's last word, for the assembler to be idle, for the
manager's release) can be relaxed to "end at once, senders see `false`". (3) The **teardown itself stays**: ending the actors of an
ended link is what took a link from 68 KiB to the floor (N2b). **Risk:** every caster must tolerate `false` (today most discard the
boolean, which is right for late answers but hides a lost segment: see 2.5); deliverers use `cast_registered`, which still raises;
the Linux compiler shows the old behaviour (`native/linux/README.md`, the `sd23` row), so nothing may rely on `false` until that
platform's compiler has the change. Take this in two steps: remove the grace first and run `n2_soak`, `n2_mesh`, `n2_reconnect`,
`n2_live`; relax the ordering only if the code gets simpler.

### 2.5 (e) One-at-a-time carrier credit (D45)

Two different rules share the name.

- **TRUST over TLS (D45 proper):** `src/trust/dangerous_bees_tls.silica:40-43` (the link holds at most one credit so that a
  carrier with no credit never reads, and so cannot end on its own while the writer still casts to it),
  `src/tempus/dangerous_bees_tempus_tls.silica` (same structure), roadmap D45, silica-defects.md (the 20 ms poll note). Its cause is
  fixed on 906 (**observed**: a cast to an ended carrier returns `false`). **It can go, to be measured:** eager credit should lift the
  TLS rate from about 40 calls per second towards N3's (**inferred**; `trials/n4_trust_tls` `make measure` was not run on either
  compiler in phase 1). **Risk:** the writer `ttlsw` must treat a `false` from the carrier as link down; D45 is a user decision and
  its text says "revisit", so the removal needs the user's word.
- **M3 and BEAM-mode assemblers:** `src/inter_nodal/dangerous_bees_net.silica:9-12` (one receive credit, only when the assembler asks,
  so that no segment reaches an assembler that has ended). That was a BEES fault (segments lost between assemblers), not SD-43. On
  906 a segment cast to an ended assembler would return `false` and still be lost. **It stays** unless the connection actor is
  changed to keep the segment when the cast returns `false`.

### 2.6 (f) Whole-state copy (SD-35): unchanged from 909 to 906

**Measured with the existing trial (observed).** `trials/n1_frames` `make measure` (b sends 64 KiB, 1 MiB and 8 MiB frames, a echoes):

| | 999926 (N1 spike, 2026-11-10) | 909 | 906 |
| --- | --- | --- | --- |
| 8 MiB round trip | 4.48 s | 4.28 s | 4.29 s |
| peak resident set, a / b, the 8 MiB run | 628 / 703 MiB | 89.3 / 183.6 MiB | 88.6 / 183.7 MiB |
| peak resident set, a / b, 64 KiB and 1 MiB only | 22.7 / 31.7 MiB | (a not kept) / 21.8 MiB | 16.1 / 20.8 MiB |

So the copy is reduced against 999926 (about 23 times the frame at the peak instead of 75) and that reduction is already in the
pin; 906 adds nothing. The compiler still reports the same unproven behaviours (section 1). A small probe (an actor whose state
holds a `List[int64, mem(normal)]`, W2300 on both compilers, 400 dispatches) kept 16 KiB committed on both compilers
(`get_actor_memory_usage`), so it does not show SD-35's growth and is not evidence either way. `trials/s13_lifecycle_cost` passes
on both and measures message copies, not state copies. The quadratic repros `sd27` and `sd28` pass on both and finish in under a
second on both (**observed**, wall time through `tools/run_trial.py`).

**Where it lives.** `src/inter_nodal/dangerous_bees_net.silica:7,138` and `dangerous_beam_net.silica:22` (no heap value in `conn`;
the per-frame `asm`); `src/trust/dangerous_bees_trust.silica:17,31,38` (`tasm`; the token held as seven-byte words);
`src/trust/dangerous_bees_tls.silica:26,240,468` (the listener `ttlsl` kept apart from `ttls`); `src/tempus/dangerous_bees_tempus_tls.silica:444`;
`trials/t1_tempus_store/actors.silica:7`; `src/shim/bees_exit.silica:137` (SD-28's remedy); `contract/wire-v1.md:360,571`; N0c section 0
item 2 (a list of config records is consumed at the message, not kept in state).

**Can it go.** No. Nothing changes in phase 2 for SD-35.

### 2.7 (g) The state-release proof and `dangerous_actor_ref` (SD-39)

**Probe (observed).** A behaviour whose new state computes its `dangerous_actor_ref` field with a helper
(`(:no_reply, { c: car_after(st, msg), n: st.n + 1 })`), beside the same with an `actor_ref`. 909: `W2300 state release not proven
for behaviour 'holds_dangerous': 'car_after' is not a logging updater`; no warning for the `actor_ref` twin. 906: no W2300 for
either.

**Where it lives.** `src/inter_nodal/dangerous_bees_net.silica:23-24,63` and `dangerous_beam_net.silica:24,727` (`tx` and `conn` are
spawned only when their carrier is known and never replace it; this is why the listen actor `lsn` exists); `src/shim/bees_node_edge.part:71`
and `src/shim/bees_resolve_edge.part:24` (a redial builds a fresh carrier, `tx` and `conn` each time).

**Can it go.** The constraint can; the structure need not. A state may now compute its carrier reference with a helper without the
fallback (**observed, 906**). `lsn` and the fresh-actors-per-redial shape work and are not worth rewriting for its own sake; what
becomes possible is an actor that swaps its carrier (the S14 dial actor `dlr` adopting the first carrier that comes up, a link that
redials in place). **Risk:** the probe is one shape (a helper returning the field); a state that receives the reference from a
message and stores it was not tried, and the replaced carrier's end is the owner's to arrange.

## 3. The carrier leak (SD-46), 909 against 906

All runs in the scratch copies, **observed**, resident set from `ps` (`tools/rss_watch.py`, `tools/soak.py`) or `/usr/bin/time -l`.

**`trials/n2_carrier_leak` `make measure`** (a carrier opened against a closed port, ended by its own `stop_self`, one every 10 ms;
no BEES actor involved):

| Carriers | 909, KiB | 906, KiB |
| --- | --- | --- |
| 0 | 2,096 | 2,064 |
| 500 | 2,704 | 2,496 |
| 2,500 | 3,728 | 2,512 |
| 5,500 | 5,392 | 2,528 |
| 6,500 | 5,888 | 2,192 |
| **per ended carrier** | **0.53 KiB** (500 to 6,500) | **about 0.01 KiB** (32 KiB over 500 to 5,500; the last two samples fell to 2,192) |

The figure recorded in the tree for the pin of 2026-11-17 is 0.51 KiB (`trials/n2_carrier_leak/measure.txt`).

**`trials/n2_soak`**, 1,000 connect-and-close cycles against a listening node. `make measure` runs six such series and each took
about six minutes on the loaded machine, so only two series were run on both compilers (`tools/soak.py connect nodes/<n>/dangerous_<n>
<port> 1000` directly, the command `make measure` issues); `m3l connect --overlap`, `m3d accept`, `bl connect --overlap` and `bd accept`
were not compared.

| Series | | start | 100 | 1,000 | final (4 s later) | per link, 100 to 1,000 |
| --- | --- | --- | --- | --- | --- | --- |
| M3 listener (`m3l connect`) | 909 | 2,112 | 2,784 | 3,280 | 3,280 | **0.55 KiB** |
| | 906 | 2,096 | 2,736 | 2,800 | 2,800 | **0.07 KiB** |
| BEAM listener, cookie (`bl connect`) | 909 | 2,208 | 7,168 | 7,664 | 3,776 | **0.55 KiB** |
| | 906 | 2,208 | 7,008 | 7,072 | 3,280 | **0.07 KiB** |

The BEAM listener's final sample is about 1 MiB above its start on both compilers (1,568 KiB on 909, 1,072 on 906) while its
slope on 906 is nearly flat: the "extra 0.7 KiB per link, not explained" of N2b reads as a one-time amount of about 1 MiB (the
links waiting out the 2 s grace during the run), not as growth per link (**inferred** from two runs; a 3,000-cycle run would settle it).

**`trials/n3_trust` `make measure`** (2,000, 6,000 and 20,000 calls, one TRUST connection per call, plaintext loopback):

| | 909: server / client peak, MiB | 906: server / client peak, MiB |
| --- | --- | --- |
| 2,000 calls | 8.14 / 7.83 | 7.19 / 6.97 |
| 6,000 calls | 11.61 / 10.34 | 8.75 / 7.70 |
| 20,000 calls | 22.92 / 18.78 | 13.00 / 8.94 |
| **per call, 6,000 to 20,000** | **0.83 / 0.62 KiB** | **0.31 / 0.09 KiB** |
| 20,000 calls, wall | 58.0 s | 60.6 s |

On the server about 0.3 KiB per call is left on 906: the amount silica-defects.md already lists as "not yet attributed" beside
SD-46's 0.52. It is not the carrier (**inferred** from the carrier-only run above being flat); Silica's reply also says "some growth
remains that this fix does not explain". Still to attribute in BEES: the per-call edge-worker dispatches, the per-request worker.

## 4. Task C: IPv6 and single-address binding

### 4.1 What the carrier offers now (read in the Silica tree, read-only)

`compiler/stdlib/dangerous_tcp_carrier.silica` (header, lines 18 to 124), `dangerous_sockets.silica`, `net/silica_sockets.c`,
`design_documents/transport_serialization_design.md` 6.2 and 6.3, and the trials `trials/transport_addition/app_transport_tcp_link_rules/`
(`dangerous_link_dial_ip6_*`, `dangerous_link_listen_ip6_*`, `dangerous_link_listen_name_*`, `dangerous_link_ip6_echo`):

| Address given to `(:open, owner, address)` | Meaning |
| --- | --- |
| `"listen:<port>"` | bind 127.0.0.1 (or a declared link's first IPv4 address) |
| `"listen:any:<port>"` | bind 0.0.0.0: every IPv4 interface, never IPv6 |
| `"listen:<ipv4>:<port>"` | bind that one IPv4 address (strict dotted quad, no leading zeros) |
| `"listen:[<ipv6>]:<port>"` | bind that one IPv6 address; `[::]` is every IPv6 interface and never IPv4 (`IPV6_V6ONLY`) |
| `"listen:name:<name>:<port>:<timeout_ms>"` | resolve the name once (`getaddrinfo`), bind the first of its addresses that binds; the timeout is the resolver's, required, no default |
| `"<ipv4>:<port>:<timeout_ms>"` | dial; the connect timeout is required, 1 to 9 digits, above 0, no default |
| `"[<ipv6>]:<port>:<timeout_ms>"` | dial an IPv6 address; brackets always |

IPv6 text is the canonical form of RFC 5952 only (lowercase, no leading zeros, `::` for the longest zero run; no dotted-quad tail,
no zone). Link-local (`fe80::/10`) is refused: it needs a zone the forms do not carry. To the owner a failed open is
`(:link_down, :fault)` or `(:link_down, :timeout)`; the carrier then ends with `(:explicit, :bad_address)` (malformed address or
missing timeout), `(:explicit, :link_unavailable)` (refused, not this host's address, a name that does not resolve) or
`(:explicit, :link_timeout)`. Those three reasons are the carrier's **end reason** (seen by a supervisor or the failure reporter),
not a message to the owner. An accepted peer is announced `(:accepted, conn, "peer:<ipv4>:<port>")` or
`"peer:[<ipv6>]:<port>"`; a dialled connection's `:link_up` carries `"<ipv4>:<port>"` or `"[<ipv6>]:<port>"`. The atoms `:ip6`
and `:name` are the carrier's own classification of a listen address (`listen_form`, lines 297 to 310) and `:addr6` selects the
IPv6 listen wrapper (line 500 to 509; the peer's IPv6 address is read as four words by `dangerous_sockets@peer_addr6_word`); none of
them is in a message an owner receives. A name is never dialled, by decision (design 6.3).

### 4.2 Probes (observed; the same on 909 and on 906)

One program (`trials/p1_probe/dangerous_probe.silica` of the copies): a driver opens one carrier per address, 2.5 s apart, each with
an owner that prints what it receives; the failure reporter prints each carrier's end reason. Ports 23690 to 23699. Built with 906
and with 909: the outputs are equal line for line apart from the order of two lines printed by different actors.

| Address | Owner received | Carrier ended with |
| --- | --- | --- |
| `listen:127.0.0.1:23690` | `link_up port:23690` | |
| `127.0.0.1:23690:1000` | `link_up 127.0.0.1:23690`; the listener: `accepted peer:127.0.0.1:<n>` | |
| `listen:[::1]:23691` | `link_up port:23691` | |
| `[::1]:23691:1000` | `link_up [::1]:23691`; the listener: `accepted peer:[::1]:<n>` | |
| `127.0.0.1:23691:1000` (the IPv6 listener's port) | `link_down fault` | `:link_unavailable` |
| `listen:[::]:23692` | `link_up port:23692` | |
| `127.0.0.1:23692:1000` | `link_down fault` | `:link_unavailable` (**IPv6-only: no dual stack**) |
| `[::1]:23692:1000` | `link_up`; `accepted peer:[::1]:<n>` | |
| `listen:any:23693` then `[::1]:23693:1000` | `link_down fault` | `:link_unavailable` (`any` is IPv4 only) |
| `listen:name:localhost:23694:2000` | `link_up port:23694` | |
| `127.0.0.1:23694:1000` | `link_down fault` | `:link_unavailable` |
| `[::1]:23694:1000` | `link_up`; `accepted peer:[::1]:<n>` (**on this Mac `localhost` bound `::1` only**) | |
| `listen:name:no-such-host.invalid:23695:2000` | `link_down fault` | `:link_unavailable` |
| `localhost:23690:1000` (**dial a name**) | `link_down fault` | **`:bad_address`** |
| `10.255.255.1:23696:700` (no answer) | `link_down timeout` | `:link_timeout` |
| `127.0.0.1:23697:1000`, `[::1]:23697:1000` (nothing listens) | `link_down fault` | `:link_unavailable` |
| `[fe80::1]:23697:1000`, `listen:[fe80::1]:23697` (link-local) | `link_down fault` | `:bad_address` |
| `[0:0:0:0:0:0:0:1]:23690:1000`, `[::ffff:127.0.0.1]:23690:1000` (not canonical) | `link_down fault` | `:bad_address` |
| `listen:10.25.164.98:23698` (this machine's `en0` address) | `link_up port:23698` | |
| `127.0.0.1:23698:1000` | `link_down fault` | `:link_unavailable` (**one address bound, not loopback**) |
| `10.25.164.98:23698:1000` | `link_up`; `accepted peer:10.25.164.98:<n>` | |
| `listen:192.0.2.1:23699` (not this host's) | `link_down fault` | `:link_unavailable` |
| `127.0.0.1:23690` (no timeout), `listen:name:localhost:23699` (no timeout) | `link_down fault` | `:bad_address` |
| `listen:name:LOCALHOST:23699:2000` | `link_up port:23699` (upper case is accepted in a name) | |

**E2418 (observed, both compilers).** The build-time check applies only to a carrier started with `spawn_dangerous_carrier` from a
`carried_on <name>: (:tcp) (:loopback);` declaration and opened with a literal. Under `(:loopback)`: `"listen:any:23699"` and
`"listen:10.25.164.98:23699"` are E2418 at compile time; `"listen:[::]:23699"` **compiles** and is refused only at run time
(`link_down`, `(:explicit, :link_unavailable)`). So E2418 ignores IPv6 literals, as the reply says, on 909 and 906 alike.
BEES does not use `carried_on` (it starts carriers with `spawn_dangerous` and the initial record spelled out, `link_spec: ""`,
`src/shim/bees_tcp_edge.part:13`), so E2418 never applies to a BEES node today. A side fact: BEES's own D30 check refuses a
`carried_on ... (:loopback)` line in a program's root unit (`BEAM atom literal :loopback outside bees_atoms (D30)`, **observed**,
`tools/bees_config.py check`), so declaring a link would first need that check to know the declaration's atoms.

**What is a compiler feature and what is a stdlib feature.** Every row above is the stdlib's and the C wrappers' (the Silica
tree's `dangerous_tcp_carrier.silica`, `dangerous_sockets.silica`, `net/silica_sockets.c`, which BEES links and compiles from the
tree whatever the compiler): the pin has all of it today. E2418 behaves the same in both compilers. The compiler-only differences
between 909 and 906 are those of section 2 (atoms, SD-37, SD-39, cast to an ended actor) and the leak of section 3.

### 4.3 BEES today against the carrier, behaviour by behaviour

BEES side read in `src/shim/bees_addr.silica`, `src/shim/dangerous_bees_resolve.silica` (and `_native`, `_stub`, `_stub_native`),
`src/shim/bees_resolve_edge.part`, `bees_resolve_none.part`, `native/src/silica_bees_resolve.c`, `tools/bees_conf.py:426-470` and its
callers, `development-plan/bees-config-file.md` section 4, S14, N1, roadmap D42.

| Behaviour | BEES today | Silica's carrier | Gap |
| --- | --- | --- | --- |
| bind 127.0.0.1 / every IPv4 interface | `listen_address` `127.0.0.1` or `localhost` gives `listen:PORT`; `0.0.0.0` gives `listen:any:PORT` | the same forms | none |
| bind one IPv4 address | boot error "not built yet" (`bees_conf.listen_form`, `CARRIER_LISTEN`) | `listen:<ipv4>:<port>`; not this host's address: `:link_unavailable` at open | BEES's reader only. S14 section 4's "must equal an address of one of the host's interfaces, else a boot error" becomes the carrier's refusal at open, which BEES must report as its boot error |
| bind an IPv6 address | boot error "not built yet" (`CARRIER_LISTEN_V6`) | `listen:[<ipv6>]:<port>`, canonical text only, IPv6-only | the reader; a canonical-text check (the reader's `addr_kind` accepts upper case, leading zeros and a dotted tail, which the carrier ends `:bad_address`); **one `listen_address` per mode cannot serve both families**: two listeners are needed, so the option must take two addresses or a list |
| bind by name | only `localhost`, mapped to 127.0.0.1 without a lookup; any other name is a boot error | `listen:name:<name>:<port>:<timeout_ms>`, first address that binds; `localhost` bound `::1` here | meaning differs for `localhost` (BEES: IPv4 loopback; the carrier: whatever the resolver lists first); the resolver timeout has no source-given default and BEES has no option for it; the bound address is not reported (`link_up` says only `port:N`) |
| dial an IPv4 literal | `"<ipv4>:<port>:<open_ms>"` after `bees_addr@quad_value` (strict, as the carrier's parser) | the same | none |
| dial an IPv6 literal | refused: boot error (`dial_check`, `CARRIER_DIAL_V6`), `dns_error not_built_yet` at run time (`net_resolve`) | `"[<ipv6>]:<port>:<timeout_ms>"`, canonical, not link-local | the reader, `bees_addr` (quad-only: `usable` drops every IPv6 part), the address builders (`rs_answer`, `tools/bees_config_beam.py:100-136`, `tools/bees_dist_gen.py:298`, `tools/bees_config_trust.py:136`) which must write brackets |
| dial a name | the resolver worker `dangerous_bees_resolve@rslv` (`getaddrinfo` in BEES's C), owned by `rdial` | **not offered**: `:bad_address`; "resolving a peer's name is the program's own" | everything stays BEES's |
| try each address in turn | attempt k takes the (k mod n)th screened address, a fresh carrier each time | dial: none; listen by name: resolver order until one binds | BEES's, unchanged; IPv6 addresses join the list (S14 section 7: IPv6 first) |
| result codes | `nxdomain`, `no_address`, `temporary`, `bad_name`, `failed`; plus `timeout`, `not_loopback`, `no_usable_address`, `not_built_yet`, printed as `[bees] resolve NAME: dns_error REASON` | for a listener's name only: does not resolve or binds nowhere `:link_unavailable`; resolver late `:link_timeout`; malformed `:bad_address` | the carrier's are coarser and reach only the failure report; BEES keeps its codes for dials. `not_built_yet` goes when IPv6 is wired |
| address filter | never dialled: unparseable, 0.0.0.0/8, 255.255.255.255, 224.0.0.0/4, 240.0.0.0/4; a repeat dropped | dial: none (a literal is dialled as given); it refuses only link-local IPv6 and non-canonical text | the filter stays BEES's and needs IPv6 rules: unspecified `::`, multicast `ff00::/8`, link-local `fe80::/10`, IPv4-mapped `::ffff:0:0/96` (to be ruled) |
| loopback-only settings | `beam.auth none`, `trust.plaintext_test_only`, the M3 node: a name is refused (`not_loopback`) if ANY of its addresses is outside 127.0.0.0/8; applied to the resolved address, never the name | listeners only, and only under a declared `(:loopback)` link (127.0.0.0/8 and `::1`); "dials under `(:loopback)` are unchanged" | BEES's rule stays; `::1` becomes a loopback address in `bees_addr@is_loopback` and in `bees_conf.is_loopback` (which already says so for the text `::1`) |
| timeouts | the dial budget `open_ms` (`beam.open_timeout_ms`) is the connect timeout written into the address and the lookup's timer; TRUST: `connect_timeout_ms` (`bees_trust_node.part:144`, `dial_text`); `dns_ns_timeout_ms`, `dns_total_timeout_ms`, `connect_stagger_ms` are validated by `bees_conf.py:251-254,835` and used by no Silica code (the staggered dial actor `dlr` is not built) | a required connect timeout per dial; a required resolver timeout per listen-by-name; a write waits at most 1,000 ms per piece; no per-name-server time, no stagger | none for connect. The DNS budgets stay BEES's (`getaddrinfo` has no timeout: the owner's timer drops the late answer by its tag) |
| per-address retry | redial (250 ms doubling to 2,000 ms) takes the next address | none ("the supervisor's restart policy is the retry") | BEES's, unchanged |
| new reasons | BEES prints the owner's `link_down` reason | `:bad_address`, `:link_unavailable`, `:link_timeout` are end reasons, not owner messages; the owner sees `:fault` or `:timeout` | to expose them (D32) BEES either checks the address itself with the same strict rules before opening (then `:bad_address` cannot happen) and maps `:fault` at open to "unavailable", or reads the carrier's failure report in the exit hub |
| peer address | not used (`"peer:accepted"` is passed on by the TLS links) | `peer:<ipv4>:<port>` or `peer:[<ipv6>]:<port>` | optional: BEES could expose the peer address (audit lines, TRUST's pin by IP when no name is used) |

### 4.4 Recommendation on the BEES resolver

**Keep the resolver; retire none of the dial path.** The carrier resolves a name only for a listener and Silica has decided that
dialling by name is the program's. Of D42's two conditions for moving resolution to Silica, the first is now met (IPv6 literal
dialling, SR-2) and the second is not (a resolver in the standard library, or resolution in the carrier's dial). The design's
table lists a `(:udp)` carrier as built with trials (design 6.3), so S14 section 9's first route (a DNS stub client in Silica over
`(:udp)`, which would let BEES drop its resolver C) may now be open; it was not probed here and is a decision for the user, not
part of phase 2.

- **Keep as it is:** the worker `rslv` and its C, the owner `rdial` (tag, budget, in-turn addresses), the stub for trials, the
  result codes.
- **Keep and extend:** the one filter `bees_addr` (IPv6 parse in the carrier's canonical form, IPv6 reserved ranges, `::1` as
  loopback), the C entry (return the IPv6 addresses in canonical text instead of only counting them: `n6`), the address builders
  (brackets).
- **Use Silica's instead of building BEES's own:** binding one IPv4 address, binding an IPv6 address, and, if the user wants
  names in `listen_address`, the carrier's `listen:name` form (then `localhost` must be ruled: keep BEES's meaning 127.0.0.1, or
  take the resolver's first address).
- **Do not narrow (D32):** accept every address form the carrier accepts, in the config and in a TRUST call; show `:timeout`
  apart from `:fault`; name the three reasons in BEES's own lines.

### 4.5 Phase 2 steps for C (none needs the new pin)

1. Rulings needed first (user): (a) two listen addresses per mode, or one and a second option, for a node that serves IPv4 and
   IPv6; (b) the meaning of `listen_address "localhost"`; (c) whether a name other than `localhost` may be a `listen_address`, and
   the option that states its resolver timeout (no source-given default: it must be explicit); (d) the IPv6 ranges the filter
   never dials; (e) whether IPv6 goes before IPv4 when a name has both; (f) non-canonical IPv6 text in `bees.config`: refuse, or
   rewrite to the canonical form before it reaches the carrier.
2. `tools/bees_conf.py`: `listen_form` returns `listen:<ipv4>:` and `listen:[<ipv6>]:` (and `listen:name:...` if ruled);
   `dial_check` accepts IPv6; remove `CARRIER_LISTEN`, `CARRIER_LISTEN_V6`, `CARRIER_DIAL_V6`; canonical-form check; the loopback
   rules for `::1`; tests in `tools/test_bees_conf.py`, `test_bees_config_trust.py`; `bees-config-file.md` section 4 rule 9 and the
   tables of 5.2 and 5.3.
3. The generators that write carrier addresses: `tools/bees_config_beam.py:100-136`, `tools/bees_dist_gen.py:298`,
   `tools/bees_config_trust.py:136` (brackets around an IPv6 host; the EPMD address too).
4. `src/shim/bees_addr.silica`: an IPv6 parser equal to the carrier's (or a call of `dangerous_sockets@parse_ipv6` where the
   placement rules allow it), `usable` over both families, `is_loopback` for `::1`, the ruled never-dial ranges.
5. `native/src/silica_bees_resolve.c`: write IPv6 addresses into the answer in canonical text (the answer's size bound and the
   owner's decode limits, `max_bytes: 700`, must grow with it); the stub gets an IPv6 name.
6. `src/shim/bees_resolve_edge.part`: `net_resolve` no longer refuses an IPv6 literal; `rs_answer` builds `"[<ipv6>]:port:ms"`.
7. Reasons: map `:fault` and `:timeout` at open to BEES lines that name `link_unavailable` and `link_timeout`; decide whether the
   exit hub reads the carrier's end reason.
8. Trials: extend `trials/n1_addr` (bind one address, bind `[::1]`, dial `[::1]`, IPv6-only, a name with both families through
   the stub, loopback-only with `::1`, link-local refused) with ports from its own block; TRUST: a call to `[::1]`; the pins file
   keyed by an IPv6 address. Record goldens on both platforms (the Linux box must have an IPv6 loopback).
9. Documents: S14 section 7 (removed, as it says), N1 section 1, roadmap D42 (the standing note: IPv6 done; the resolver stays
   because the carrier does not dial names), `documents/trust.md` and `semp.md` if they state IPv4 only (no bold text there).

### 4.6 The six rulings of 4.5 item 1: options and a recommendation for each (added for the owner, 2026-11-18)

| # | Question | What BEES does today | Options | Recommendation |
| --- | --- | --- | --- | --- |
| (a) | A node that serves IPv4 and IPv6: the carrier's IPv6 listeners are IPv6-only (no dual stack), so one listener cannot take both. | One `listen_address` per mode, `"127.0.0.1"` or `"0.0.0.0"` only; an IPv6 literal is refused as "not built yet". | 1. `listen_address` takes one address or a list of at most two (one per family), one listener each. 2. Keep `listen_address` and add `listen_address6`. 3. One address only: a node is IPv4 or IPv6. | Option 1. One option name, the list form says exactly what is bound, and a single string keeps every existing file valid. Two entries of one family, or more than two, are refused. |
| (b) | What `listen_address "localhost"` means. The carrier's `listen:name:localhost` bound `::1` only on this Mac, so the same file would bind different addresses on different machines. | `"localhost"` is taken as `127.0.0.1` (the loopback test settings accept `localhost`). | 1. Keep: `"localhost"` is exactly `127.0.0.1`, never resolved. 2. Both loopbacks, `127.0.0.1` and `[::1]`, two listeners. 3. Hand it to the carrier's name form (whatever the system resolver puts first). | Option 1. It is deterministic, changes no golden, and a node that wants `::1` writes `"::1"`. |
| (c) | May a name other than `localhost` be a `listen_address`, and which option states its resolver timeout (there is no source-given default, so it must be explicit). | Refused: a listen address is a literal. | 1. Literals only (and `localhost` as in (b)). 2. Names allowed through the carrier's `listen:name:`, with a required new option `listen_resolve_timeout_ms`. 3. Names allowed, resolved by BEES's resolver edge, timeout from the existing `dns_total_timeout_ms` (TRUST) and a new BEAM option. | Option 1 for now. Binding by name makes what a node listens on depend on the resolver at boot; no trial or user asks for it. If it is wanted later, option 2 with the explicit option. |
| (d) | The IPv6 ranges the address filter never dials. | IPv4 only. Never dialled: `0.0.0.0/8` (this network), `224.0.0.0/4` (multicast), `240.0.0.0/4` (reserved; it contains `255.255.255.255`, the limited broadcast). Kept: everything else, private ranges included. With a loopback-only setting (`auth none`, `plaintext_test_only`) every address outside `127.0.0.0/8` is refused. | 1. The list below. 2. The list below without the mapped and translation rows (dial them as the system does). 3. No IPv6 filter: whatever the resolver answers is dialled. | Option 1. Never dialled: `::/128` (unspecified, the twin of 0.0.0.0/8); `ff00::/8` (multicast, the twin of 224.0.0.0/4); `::ffff:0:0/96` (IPv4-mapped: an IPv4 address in disguise that would pass the IPv4 filter unseen; the IPv4 form must be written); `64:ff9b::/96` and `64:ff9b:1::/48` (NAT64 translation, the same reason); `fe80::/10` (link-local: the carrier refuses it as `:bad_address`, it needs a scope); `2001:db8::/32` and `3fff::/20` (documentation); `100::/64` (discard-only). Kept, like the IPv4 private ranges: `fc00::/7` (unique local), global unicast. Loopback: `::1/128` only, and a loopback-only setting refuses every other IPv6 address. |
| (e) | The order of addresses when a name has both families. | The resolver edge answers IPv4 addresses only (it counts the IPv6 ones), each tried in turn in the resolver's order, with the per-address retry of S14. | 1. The system resolver's order as it is (RFC 6724; usually IPv6 first). 2. IPv4 first, then IPv6. 3. IPv6 first, then IPv4. 4. A new option that states the order. | Option 1, with every address still tried in turn. It is what the stock `inet` and other programs on the host do, and it needs no option; the trials use the stub resolver, whose order is fixed, so goldens stay deterministic. |
| (f) | Non-canonical IPv6 text in `bees.config` (`::0001`, upper case, a zero run not compressed); the carrier accepts the canonical form only and ends `:bad_address` otherwise. | No IPv6 literal is accepted at all. | 1. Refuse at validation, with the canonical form in the message. 2. Rewrite to the canonical form silently before it reaches the carrier. 3. Pass it on and let the carrier refuse it. | Option 1. The validation rule of bees-config-file.md section 4 ("nothing is repaired, rounded or defaulted around a bad value") already decides it; the message names the canonical spelling (RFC 5952) so the fix is one copy. Pins and whitelist keys compare as text, which a silent rewrite would confuse. |


Owner rulings, 2026-11-19:
- (a) RULED: option 1, and a listen address may be any valid address, not only 127.0.0.1 or 0.0.0.0 (one address, or a list of at most two, one per family, one listener each).
- (b) RULED: option 1, "localhost" is exactly 127.0.0.1, never resolved.
- (c) RULED: option 3, a listen address may be a name, resolved by BEES's resolver (TRUST's existing resolver timeout; a new BEAM-mode option for the same, stated explicitly with no default).
- (d) RULED 2026-11-19: option 1 with the full list. The filter stays on both families. IPv4 as today (0.0.0.0/8, multicast, broadcast, reserved refused; private kept). IPv6 never dialled: ::/128, ff00::/8, ::ffff:0:0/96 (IPv4-mapped), 64:ff9b::/96 and 64:ff9b:1::/48 (NAT64), fe80::/10, 2001:db8::/32 and 3fff::/20, 100::/64. Kept: fc00::/7 and global unicast. Loopback is ::1/128 only; a loopback-only setting refuses every other IPv6 address.
- (e) RULED: option 1, the system resolver's order, every address tried in turn.
- (f) RULED (owner wrote "(c): accept option 1" a second time; read as (f), to be confirmed): option 1, refuse non-canonical IPv6 text at validation with the canonical form in the message.

## 5. New defects, and things to report

- **SD-44 is still open on 906** (section 2.3, file inline). Not a new entry: an update to SD-44, and a line for Silica ("C2 is
  not done for the argument path").
- No new Silica defect was found on 906.
- Notes that are BEES's own: the D30 check refuses a `carried_on` declaration (4.2); `listen_address "localhost"` and the
  carrier's `listen:name:localhost` do not mean the same address on this Mac (4.2, 4.3).

## 6. Linux (not run: no ssh in phase 1)

Generation numbers are not comparable across platforms. The remote machine (`.bees_build_hosts.example`: `manager@aalang.org`,
`/opt/silica/binaries/silica-compiler-linux_x86_64`) had `silica-999944-linux-x86_64` when its goldens were recorded
(`native/linux/README.md`), and that compiler shows the pin's behaviour for a cast to an ended actor. This Mac's Silica checkout
holds `silica-999942-linux-x86_64` (`binaries/silica-compiler-linux_x86_64` points at it) (**read**); whether the box has it was
not checked. To check there in phase 2, before anything relies on a fix on both platforms:

1. Which compiler the box runs: `ssh -o BatchMode=yes manager@aalang.org 'readlink /opt/silica/binaries/silica-compiler-linux_x86_64;
   cd /opt/silica && git log --oneline -1'`. The fixes are in Silica commit `c063517bd9` ("BEES requests A1, A2, C1-C5"); the box's
   checkout must be at or after it and its compiler built from it.
2. Which fixes that compiler has: copy the probe leaves of section 2 (`atoms_v1`, `sd37_five`, `cast_ended`,
   `dangerous_worker_cast_ended`, `dangerous_sd39`, the SD-44 file) into a scratch directory there and build them with the box's
   compiler; expected results are the 906 column of section 2. Until all of A1, SD-37 and the cast change are there, no source may
   use them (one source tree serves both platforms).
3. The leak: `make -C trials/n2_carrier_leak measure` there (the per-thread destructor is platform code).
4. Which goldens change: run `tools/run_all_trials.sh` with the hosts file after the box's compiler moves; expect the Linux
   `sd23` golden to change to the Mac's shape (the README's last row then goes), and expect `agent_type_atom` rows to move if atom
   numbering changed there. Read each `.sout` against its golden before `make record-golden` on the box.
5. The Linux stdlib is the box's `/opt/silica` checkout, not this Mac's: the address forms of section 4 need that checkout at
   `c063517bd9` or later too, and its `silica_sockets.c` rebuilt (`make -C native`). IPv6 loopback must be up on the box for the
   new `n1_addr` entries. `SD-47` (two cores) can reorder lines in new trials.
6. The interchange trials (`make interchange`) after both sides moved.

## 7. Phase 2 step list

Order matters: the pin first, then one workaround at a time, each with its trials, so that a regression points at one change.
Coordinate before step 1 with the owners of the leaves in flux: TEMPUS (`t*_tempus_*`, `src/tempus`), N5 (`n5_*`,
`dangerous_bees_trust_mux`), N2T (`n2t_*`, `dangerous_beam_tls`), C1 (`c1_codec_*`, `tools/bees_wire_gen.py`), the interchange
(`x*`, `tools/bees_interchange*.py`), the fuzzer (`f1_fuzz_wire`, `f2_fuzz_long`), and the store-configuration work (N0d): their
goldens are the pin's, and all must move in one sitting.

1. **Freeze and clean.** Every agent stops building. `make clean` (the root: `trials` and `native`), and remove every
   `silica.atoms`, `silica.shapes`, `.iface`, `.o` (atom numbers shift between the compilers: no product of 909 may survive).
2. **Move the pin.** `printf 'silica-999906-macos-applesilicon\n' > tools/silica.generation`. The generation is named nowhere
   else that a build reads (`grep -rIl 999909 . --exclude-dir=.git --exclude-dir=trial_runs`: the other hits are documents and
   comments: `native/linux/README.md`, `silica-defects.md`, `tempus-design.md`, `tempus-progress.md`, spikes N0b, N0c, N2b, N5, C1,
   X1, `tools/bees_wire_gen.py:233`, `trials/t0_tempus_view/sd_own_len_function.silica`). `binaries/silica-compiler` in the Silica
   tree already points at 999906, so the default compiler and the pin agree again: `make check-compiler` must print
   `compiler generation silica-999906-macos-applesilicon (verified)`.
3. **Run everything on the Mac.** `tools/run_all_trials.sh --local-only` (65 leaves measured here pass; the leaves of section 1's
   "not run" list are the unknown). For each failing entry read `NAME.sout` against the golden; record only what a fix explains:
   `make -C trials/<leaf> record-golden SILICA_COMPILER=/Users/yenrab/silica/binaries/silica-999906-macos-applesilicon`.
   Then `make kit` and `python3 -m unittest discover -s tools -p 'test_*.py'`.
4. **silica-defects.md** (the caller's file): a section "2026-11-18: pin moved to silica-999906" with: A1 fixed; SD-37 fixed (derived
   decoder; E1070 for hand-written functions stays); SD-39 fixed; SD-43 fixed for `cast` (plain, carrier, FFI worker);
   SD-46 fixed (figures of section 3); SD-44 **still open** with the file of 2.3; SD-45 and SD-31 unverified; SD-35 unchanged;
   SD-26, SD-33, SD-34, SD-38, SD-40 still open; SD-48 and the C1 sum-order defect to re-try.
5. **Linux.** Section 6, steps 1 to 4. If the box's compiler lacks a fix, stop here for that fix: record the Linux goldens for the
   new compiler only, and leave the workaround in.
6. **Remove the 2 s grace** (2.4 step 1): `src/inter_nodal/dangerous_beam_net.silica` (`grace`, `arm_grace`, message kind 11, the
   `fl` bit 4 wait), `tools/soak.py:64` (the 4 s settle). Run `n2_auth n2_dist n2_live n2_mesh n2_multilink n2_reconnect n2_soak`
   and `make -C trials/n2_soak measure`: the BEAM listener's first-100 jump (7 MiB) should go.
7. **Eager credit for TLS** (2.5), after the user revisits D45: `src/trust/dangerous_bees_tls.silica` (credit rule in `ttls`,
   `ttlsw` treats a `false` cast as link down), the same in `src/tempus/dangerous_bees_tempus_tls.silica` and
   `src/inter_nodal/dangerous_beam_tls.silica` with their owners. Measure `make -C trials/n4_trust_tls measure` before and after.
8. **Flat records** (2.2): `trials/m4_demo/roles/gen_types.py` (drop the two halves), the configuration groups of N0c 5.2 and N0d,
   `src/tempus/bees_tempus_frame.silica` (with its owner). `bees_trust_frame`'s walk stays. Time the compile of each changed unit.
9. **The atoms ordering rule** (2.1): drop the "listed first, expression literal" condition from N0c's rulings and from whatever
   `bees_config check` enforces for the library API; keep `bees_atoms`. Re-run N0c's variants `v9` and `v12` on 906 first.
10. **SD-39** (2.7): no code change; update the comments that call it open (`dangerous_bees_net.silica:23`,
    `dangerous_beam_net.silica:24`, `bees_node_edge.part:71`, `bees_resolve_edge.part:24`) and allow the shape in new code.
11. **Keep:** bind-before-passing (2.3), SD-35's shapes (2.6), the M3/BEAM assembler's single credit (2.5), the teardown (2.4).
12. **Re-record on both platforms** after each of steps 6 to 9 that changes output: `tools/run_all_trials.sh` (with
    `.bees_build_hosts`), `make -C trials/<leaf> record-golden` here and on the box, `tools/test_platform_and_ports.py` (every Mac
    golden has its Linux twin), then `make interchange`.
13. **Task C** (4.5) is independent of the pin and can run beside steps 3 to 12.

## 8. What was not done

- The leaves of other agents (section 1's list) and the two-machine trials were not run on 906.
- Linux: nothing was run (no ssh).
- `trials/n2_soak`: two of the six series on both compilers (the full target takes over half an hour on the loaded machine).
- `trials/n4_trust_tls` `make measure` (the TLS rate behind D45) was not run.
- SD-45 and SD-31 have no program that fails on the pin, so their fix is unverified.
- N0c's atom variants other than `v1`; wide records of non-integer fields; `send` and `call` to an ended actor; SD-48 and the C1
  sum-order defect on 906; a DNS stub over `(:udp)`.
- The 909 column of the SD-44 variants table has one row (the composite form); the timing figures were taken on a machine at
  load 11 to 32 and are not benchmarks.
