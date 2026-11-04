# A2 steps 1-2: the BEES exit listener and hub

**Status:** built and measured 2026-11-04 on `silica-999939-macos-applesilicon`.
**Code:** `src/shim/bees_exit.silica`. **Trials:** `trials/a02_exit_listener/` (`listener_collects`,
`listener_throughput`) and `trials/a02_spawn_supervisor/spawn_probe`.

## What exists

The listener is registered as Silica's FailureReporter, so it receives the text of every failure report. It
parses each into `{ kind, actor_id, agent, reason, tag, acb, frame0 }` and casts it to the hub, a registered actor
that counts by reason tag and keeps the highest identity. The hub prints and ends the program once it has seen the
number of reports it was told to expect. Silica has no string-to-integer conversion, so numbers are read digit by
digit through a lookup.

## Findings

| Question | Result |
| --- | --- |
| Does every kind of end reach the hub? | Yes: `stop_self(:normal)` (tag 0), division by zero (tag 2, `:language_error`), `fail_self(:badarg)` and `kill_abnormal` (tag 4, `(:explicit, ...)`). Counts correct, stable over four runs. |
| Do supervised children report here too? | Yes (a stopped `:temporary` child produced a report in `spawn_probe`). The listener is the single source for all exits. The supervisor sink adds only `restarted` and `new_child`. |
| Throughput | 20,000 reports in about 1 s. 100,000 in about 10 s; memory grew from 27 MB to 143 MB because the listener's mailbox backed up. Parsing costs about 50-100 us per report. |
| Can the listener recognise a root-supervisor report? | No. A plain actor's report has the same text signature (`supervisor_acb: 0x0`, frame `<unknown behavior>`). The listener never ends the program itself; the boot code decides. |
| `:add_child` ids | A duplicate id is rejected (`duplicate_child_id`); an id is free again once its `:temporary` child stops. One supervisor holds only as many live children as it has id atoms (D18). |

## Silica details met on the way

`foreign`, `normal`, `explicit` and `update` are keywords and cannot be field or function names. A computed record
cannot be written inline as a cast's message: bind it first. A call that can spawn an actor before the reporter is
registered is E2236, so `bees_exit@start` registers the listener before it spawns the hub. For plain-spawned
actors frame #0 was `<unknown behavior>` here, though a named frame appeared in the S10 relay report; not explained.

## Open

- Cheaper parsing, or fanning the raw text out to parse workers (only one FailureReporter is allowed).
- A structured failure report from Silica would remove the dependence on the banner text (noted, not asked for).
- How `exit(Pid, Reason)` reaches an actor for any reason other than `(:explicit, :killed)`.
