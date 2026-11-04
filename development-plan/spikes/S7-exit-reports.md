# Spike S7: Exit reports (D23)

**Status:** run 2026-11-04 on `silica-999939-macos-applesilicon` (chunk 15 phase 2). **Passes. The
Silica work the spike was meant to prototype (S-28) already exists, so no Silica branch is needed.**
**Trial:** `trials/s07_exit_reports/exit_hub_cost.silica`.

## 1. What was checked

`call_supervisor(sup, { op: :set_report_sink, sink: s })` replies with status `:sink_set`. After that,
every child exit the supervisor handles is cast to `s` as
`{ child, child_id, failure_reason, restarted, new_child }`, the record D23 proposed, spelled as
Silica's spec §15.4.10.5 gives it. The trial uses the sink as `bees_exit_hub`: for each report it casts
the next crash to the restarted `:w`, so exits run back to back.

| Check | Result |
| --- | --- |
| 5,000 crash, restart, report cycles | All 5,000 reports arrived. |
| `restarted` | `true` on every report. |
| `new_child` | A different reference from `child` on every report (new identity, D22). |
| `failure_reason` | `:language_error` on every report (division by zero). |
| Cost | 0.48 s wall for 5,000 cycles, about 96 us per crash, restart and report (includes the actor spawn). Peak RSS 2 MB. |

## 2. What this means for BEES

- **D23 and S-28 are satisfied by Silica as it is.** The hub is a plain cast-only actor. The report
  record needs no BEES-side translation.
- A sink that has ended drops reports and the supervisor is unharmed (Silica trial
  `supervisor_exit_reports_addition/report_dead_sink_dropped`). The hub must therefore be supervised
  and restarted, and reports sent while it is down are lost; the hub cannot rebuild its bookkeeping
  from them. Open for A2: the hub's state is rebuilt from the position map, or reports during a
  restart window are accepted as lost.
- Inheritance of the sink by child supervisors, ordering, and the 100,000-report RSS check are covered
  by Silica's own trials in `supervisor_exit_reports_addition`; this spike did not repeat them.
- Silica records an exit-report ordering race on Linux AArch64 (ROADMAP chunk 10, 2026-10-27). The
  Mac is clean. D29's Linux targets inherit that risk.
