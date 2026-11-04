# So you want to write a compiler for BEES

**Status: draft, 2026-11-04.** This is the compiler author's guide that the target contract (roadmap R0.3) will
grow out of. It says what a language-to-Silica compiler must do, what it may do, and what is still open. Every
rule cites the decision (D-number) or gap-ledger item (S-number) behind it, and the trial that shows it. Where this
guide and `development-plan/roadmap.md` disagree, the roadmap's decision table wins; where a measurement under
`trials/` disagrees with prose, the measurement wins and this guide should be fixed.

Labels used below: **MUST** (a program that breaks it is not a conforming BEES program), **MAY** (your choice),
**OPEN** (not decided; do not rely on either answer), **PROVISIONAL** (works today, expected to change).

Verified on `silica-999939-macos-applesilicon` (Silica chunk 4 and chunk 15 phase 2). Only macOS is verified so far.

---

## 1. What you are, and what BEES is

- **You are the compiler.** BEES is a shim, not a runtime that loads BEAM code. No `.beam` file is read and no
  bytecode is interpreted. Your compiler turns each BEAM-language module into Silica source, and the Silica compiler
  builds it together with BEES's units. Compilers are outside BEES (D4).
- **BEES adds only what Silica lacks** (D19, roadmap §2): the term model, BIFs, ETS, timers, ports, distribution,
  the exit hub, balancing. Anything Silica can already express, however awkwardly, is yours to lower. "Possible, not
  easy" is the goal; BEES does not promise BEAM fidelity, and neither does the contract.
- **Do not narrow Silica to the BEAM** (D32). If Silica can do more than the BEAM (richer crash reports, more
  flexible spawning), your compiler may expose it. BEAM behaviour is the floor, not a ceiling.
- **Gaps are owned.** Roadmap §2 gives every gap one owner: Silica (class U), BEES (B), the native edge (E), or the
  compilers (C). If your language needs something nobody owns, it becomes a ledger row; tell us.

## 2. What you emit

1. **Silica source units**, one per module or per generated helper. Basenames must be unique across the whole
   program (the build identifies a module by its basename).
2. **A manifest per unit** listing every BEAM atom the unit uses, one spelling per line (`<unit>.atoms`). `bees_config`
   unions the manifests into one generated unit, `bees_atoms` (D30).
3. **A module-table entry per module**, giving dispatch for `apply/3` and for funs. `bees_config` combines the
   entries into one program-wide table (roadmap §1, contract item 4). **OPEN:** the exact manifest format; the
   mechanism exists only as a sketch.
4. **A reserved module-name prefix** for your language, plus BEES's own `bees_` / `dangerous_bees_` prefixes
   (roadmap §4.8). Each language reserves one prefix so Elixir code can call Erlang code compiled by a different
   compiler.

`bees_config` generates `silica.config`, `bees_atoms`, the module table and the supervisor position map, and checks
the rules in §3. The Silica compiler itself takes no arguments: it reads `silica.config` from the working
directory, and units must be listed in use-dependency order. Build with the exit-75 reclaim loop (`tools/silica.mk`).

## 3. Atoms (D30, D16)

- **MUST:** a BEAM atom is a Silica atom, and BEES has no atom table of its own.
- **MUST:** outside the generated `bees_atoms` unit, **no unit writes a BEAM atom literal.** Obtain atom values from
  the accessors (`bees_atoms@a_mango()`), compare with `==`, or switch on `bees_atoms@index(a)`. `bees_config check`
  enforces this.
- **MAY** write an atom pattern in a `case` only for Silica's fixed atoms and the atoms its compiler interprets
  (`:ok`, `:normal`, `:permanent`, `:one_for_one`, `:no_reply`, the `stack_policy` names, and so on; the list is
  `FIXED_ATOMS` in `tools/bees_config.py`).
- **MUST NOT** create an atom at run time. `list_to_atom` and `binary_to_atom` behave as the `existing` variants:
  a lookup that fails with `badarg` when the spelling is not in the program's atoms (D16).
- Silica has no type conversion, so `atom_to_list`, printing and ETF encoding are lookups in `bees_atoms`
  (`spelling`, `from_spelling`, `index`). With more than 256 atoms `bees_config` splits the lookups into helpers,
  because Silica rejects a `case` of 512 or more literal arms (trial `r02_many_atoms`). Do the same in anything you
  generate (the module table, `apply` dispatch, byte lookups).

## 4. Processes

- **MUST:** a BEAM process is a **plain Silica actor** (D1), a **cast-only** behaviour returning `(:no_reply, state)`.
  A call-only behaviour is for a `gen_server` call half (§8). Casting to a call-only actor is a compile error when
  Silica can see it (E2237) and stops the sender at run time when it cannot (`cast_registered`), so keep the two
  kinds apart.
- **MUST:** pass `stack_policy(reserve, release)` to every `spawn`, `spawn_registered` and `spawn_dangerous`.
  `reserve` is bytes of address space; `0` means the default, which is the machine's memory plus swap.
  - With the default reserve, spawn aborts at about 3,750 to 4,000 live actors (address space).
  - With a lowered reserve, 100,000 actors take about 0.6 s and a million about 4 s (5 GB; trial `s03_actor_ceiling`).
  - **MAY** pick the reserve per process kind. `spawn_opt` options map onto it. **OPEN:** the default reserve for a
    BEAM process.
- **Reshape `receive` (D1).** A process holds no stack between messages. Code that needs a `receive` in the middle of a
  function is split by you at the receive: the paused computation lives in the actor state, and the next message
  resumes it. The helpers are `bees_recv` (the save queue for selective receive) and, for `after`, a timer. Trial
  `s09_reference_lowerings/ping_pong_selective_receive` is the reference lowering.
- **Never block, and never loop forever in one dispatch.** Silica never interrupts a running dispatch (see below). A
  long computation must end its dispatch at **yield points** you place, continuing through a cast to `self()`. This
  works only for an actor that accepts casts; a call-only actor must fit its work in one dispatch.
- **A running dispatch cannot be killed** (S-33). `kill_abnormal` and a brutal `shutdown` take effect only after the
  current dispatch returns. A compiled loop with no yield point is unkillable. Place yield points at receive boundaries
  and tail calls.
- **Recursion.** Tail calls are compiled to jumps now (the old SD-12 is closed), but you should not rely on unbounded
  recursion inside one dispatch: an actor's stack is bounded by its reserve, and exceeding it ends the actor with
  `(:explicit, :stack_exhausted)` or `:reservation_exceeded`.
- **Placement.** `spawn(..., stack_policy(...), core)` takes an optional core id; `migrate_actor(ref, core)` moves an
  actor at its next dispatch boundary and keeps message order (expressions are accepted for the core). BEES does the
  balancing; never move a process the program placed explicitly.

## 5. Startup and supervision (D18, D23)

This is the part every compiler must get right, because Silica refuses to run without it.

1. **MUST: register a FailureReporter before anything else is spawned** (E2236). Call `bees_exit@start()` first in
   `main`. It registers the BEES **listener** as the reporter and starts the **exit hub**.
2. **MUST: start a root supervisor** (a Silica `Supervisor` implementation) at program start, before your own
   actors. **`main` is not an actor** and has no supervisor; the program ends through `wait_for_exit` / `cast_exit`.
3. **MUST: every actor your compiled program spawns is added to a supervisor.** An actor you do not place under
   another supervisor is added to the root supervisor (D18, decided 2026-11-04). Use `:add_child` with
   `restart: :temporary` for an ordinary process.
4. **MUST: give each live child a distinct id.** `:add_child` rejects an id already in use (`duplicate_child_id`),
   ends `main` if the call came from `main`, and frees an id as soon as its `:temporary` child stops. Ids are atoms
   from a fixed table, so one supervisor holds only as many live children as it has ids (trial
   `a02_spawn_supervisor`). Generate a pool of id atoms per supervisor, reuse an id when its child stops, and use a
   tree of supervisors for more live processes. **OPEN:** the pool-and-tree scheme; Silica may add anonymous child
   ids.
5. **MUST: a supervisor is typed by one child shape.** The child spec fixes the state type and the behaviour type, so
   one supervisor supervises one process shape. Use one supervisor per shape, or one uniform process shape for all
   compiled processes (the D1 shape: state record plus a continuation).
6. **MAY: set the root supervisor's report sink to the hub** (`call_supervisor` op `:set_report_sink`) to receive
   `restarted` and `new_child` for supervised children. **OPEN:** the hub reference needed for this is not exported
   yet. The listener already reports every exit, so the hub learns of every death without a sink.
7. **A supervised child's initial state** is the one in its child spec at each (re)start; a restart gives a fresh
   state (trials `s01_trait_mapping`, `a02_ring/restart`). A state that holds a region and a term in it works. **OPEN (SD-23):** a supervised cast-only child that holds a region and an
   `actor_ref` and casts from inside its dispatch dies on its second message; call it out of your lowering until
   Silica fixes it.
8. **Identity.** A pid is an `actor_ref`; its identity is 64 bits: the spawner's position (32) and a child number (32),
   printed as `<position.child>`. A restarted child has a new identity (D22). Equality and order are on identity. A
   pid you held for a restarted process is a dead pid.

## 6. Failures (D2, D20, D31)

- **MUST NOT** emit anything that catches a failure. Runtime failures (a failing BIF, a bad match, a division by zero)
  end the actor; the supervisor reports it; nothing inside the actor handles it (D2). Reject `catch`, `try ... catch`
  and `after` clauses at compile time. A `try` that catches exactly one failure may be rewritten onto a BEES
  **result-returning variant** of the BIF (for example the existing-atom conversions). `throw` is a failure.
- **Fail with a reason.** `fail_self(reason_atom)` ends the actor with `(:explicit, reason)`; `stop_self(:normal)`
  ends it normally (trial `s10_failure_paths`). Silica's own faults carry Silica's reasons (`:language_error` for a
  division by zero, `(:explicit, :buf_bounds)`, `(:explicit, :list_index)`, `(:explicit, :region_alloc_failed)`). If
  you want `badarith`, guard the division yourself and call `fail_self`.
- **A `case` without a catch-all arm is a compile error** (E2008). Emit an explicit failing arm for the Erlang
  `case_clause` (`fail_self` with an atom you list in your manifest).
- **A `call` to a dead callee fails the caller** with `(:explicit, :actor_not_found)` (the old zero-value result is
  gone). A `cast` to a dead actor fails the sender the same way.
- **The lowering of `!` is yours (D31).** On the BEAM, `Pid ! Msg` to a dead pid does nothing. Silica's `cast` ends
  the sender instead, and a listener that consumes the report does not help: the sender has already died, the rest of
  its dispatch is skipped, a restart loses its state and changes its pid, its queued messages are dropped, restarts
  count against the supervisor's limit, and a `:temporary` sender is simply gone. BEES gives no send primitive and
  does not forbid `cast`. Routes you might take (none tested): a proxy actor that takes the failure; a liveness check
  before the cast (racy); Silica's planned value-returning send. State your choice in your own documentation.
- **No monitors, no `trap_exit`** (D20, D18). `exit(Pid, Reason)` is yours to lower into a request to Pid's supervisor,
  found through the position map. **OPEN:** only `kill_abnormal` exists in Silica, which yields `(:explicit, :killed)`;
  other exit reasons have no route yet. How `link` is lowered is your choice.
- **Every exit reaches the hub.** The BEES listener parses Silica's failure report for every ended actor, supervised
  or not. It does not end the program on a root-supervisor report: your startup decides what that means.

## 7. Terms and memory

- **Every value is a `bees_term`** (roadmap §4.1): a cell in a region. **PROVISIONAL (v0):** a cell is the tuple
  `(tag, n, f, a, p, h, t)`, spelled in full in every signature. Tags: 0 nil, 1 int, 2 float, 3 atom, 4 pid,
  5 cons, 6 tuple, 7 binary, 8 fun. `src/shim/bees_term.silica` is generated by `tools/gen_bees_term.py`; do not edit it.
- **Spell the outer type.** Silica now requires the recursive type in full: `ref?(L, normal, (…, ref?(L, normal, rec)))`.
  A bare `ref?(L, normal, rec)` outside a tuple is E2010.
- **Rules from the defects found** (all verified on the current compiler, trials under `trials/silica_defects`):
  - Name every term lifetime `L`, and type every region that carries terms `region(L, normal)`.
  - Constructors and accessors return **one reference**, not a record or tuple. (The old stack leak is fixed, but
    this keeps the shapes simple.)
  - The heap is a record `{ r: region(L, normal) }`, passed in to every constructor and kept in the actor state.
  - A message is a record carrying its region: `{ r: region(L, normal), c: <term> }`. Build it in a function that returns
    it, once per send (`msg_of(new_heap(), …)`); do not bind the fresh region to a local name first.
  - Do not pass a computed record or a call as the inline message of a `cast`: bind it to a name first. (Observed in the
    exit listener; the same class as SD-11 and SD-19, closed for those but still hit here.)
  - A record literal in a sequence needs `mem(normal)` declared on the enclosing function.
- **Reclamation.** Silica now releases a replaced state region at the end of a dispatch and frees message regions when
  the receiving dispatch returns; 100,000 evacuations peak at 5 MB (trial `s06_terms_and_regions`). **OPEN:** the
  contract's "evacuation points" (roadmap §4.2) were designed before this and need rewriting; treat explicit
  evacuation as unnecessary until the contract says otherwise.
- **Integers** are `int64`; overflow fails the actor with `system_limit`. Bignums wait on Silica (S-11).
- **Binaries (decided 2026-11-04):** a binary is a `buf(uint8)` plus a bit length, never a `string`. A `buf` may be a
  message only when its region is sent with it (by Silica's design, for memory safety). **PROVISIONAL:** v0
  `bees_term` stores a binary as a list of byte cells.
- **Bit syntax and integer bitwise operators are yours** (class C). Silica has no type conversion and its bitwise
  operators take `uint64`, so build and read bytes with lookups you generate (a 256-way `case` from a byte to the
  matching literal) and same-type arithmetic. Floats too: an exact float64 codec without conversion exists as a
  worked example (trial `s05_bytes_without_conversion`). Literal binaries, strings and floats become bytes at compile
  time.
- **Calling convention.** Silica allows 8 parameters; you pack more. Results come back as one value. A runtime
  failure is never returned as a value (D2).
- **Funs and `apply/3`** go through the module table: each compiled module provides dispatch entries
  (trial `s09_reference_lowerings/funs_and_apply`).

## 8. OTP behaviours (D5, D13)

- **`supervisor`:** map onto Silica's `Supervisor` trait. The child spec's fixed shape is the constraint in §5.
- **`gen_server` (D5):** Silica behaviours are call-only or cast-only, not both. A module that handles calls **and**
  casts becomes **two Silica actors**, one call-only and one cast-only. The contract fixes only what outside code can
  see: which actor a `gen_server` pid denotes (it must accept casts), and how a call and a cast reach the right half.
  Where the state lives, where `handle_info` goes, and how a cast followed by a call stays in order are your choice.
- **`gen_statem`:** Silica's state-machine trait is **not delivered** (S-17). Until it is, use a plain behaviour with a
  phase field.
- **NIFs (D13):** wrap each NIF as a Silica actor around the external call (a `dangerous_` module and a
  `spawn_dangerous` worker), re-create any result that leaves the handler, and link the worker to its caller so a
  fault fails both. BEES provides no `load_nif`. A worker answers more than one message now (SD-18 closed), but each
  dangerous actor is an OS thread, so pool workers.
- **ETS, timers, ports, distribution:** BEES provides them as it lands (roadmap A3, A5, B1-B4). Silica has timers
  (`send_after`, `cancel_timer`); `cancel_timer` returns no remaining time, so `read_timer` needs BEES bookkeeping.

## 9. Silica details that will cost you an afternoon

- `foreign`, `normal`, `explicit` and `update` are keywords: do not use them as field or function names.
- A function body that is a bare record literal does not parse; use `sequence … produces pure r end`.
- A `case` over an integer needs a catch-all arm (`_: int64 -> …`); `print_bool` is now `print_boolean`.
- A call to a function that can spawn an actor, made before the reporter is registered, is E2236, even through a
  library call. Register the reporter first.
- Unused effect declarations are errors (E3010), and missing ones are errors (E3002): declare exactly what a sequence
  uses. A computed record needs `mem(normal)`.
- `spawn` takes a mandatory third argument (`stack_policy`). `migrate_actor`'s core may be an expression.
- A `foreign c_wrapper` function may be called only inside a worker's `external_danger` sequence; the declarations,
  the worker and its spawn site had to be in one unit on the previous compiler (SD-17); not re-tested on this one.
- Silica has no string-to-integer conversion, no atom-to-string, no generics. The BEES parser for failure reports reads
  digits through a lookup; copy that technique.
- The Silica compiler writes `silica.atoms` and `silica.shapes` beside the build; they are generated, not source.

## 10. What BEES gives you today, and what it does not

**Available (v0, may change):** `bees_term` (the cell constructors and accessors), `bees_recv` (save queue), `bees_atoms`
(generated lookups), `bees_exit` (listener and hub), `bees_reporter` (a plain reporter for tests), `bees_config`
(atoms, checks), the trial harness (`tools/trial.mk`), and reference lowerings in `trials/s09_reference_lowerings`
(selective receive with `after`, a try rewritten onto a result-returning BIF, funs and `apply/3`, binary matching) and
`trials/a02_ring` (a ring and a supervised restart, written as a compiler would lower them).

**Not available yet:** a published contract and conformance kit (R0.3, T1, T2); the module table and position map
generators; `bees_timer`, `bees_proc`/spawn helpers, ETS, `process_info`, registered-name helpers (Silica's registry is
not implemented, S-29); re-creation of foreign data (S-5/S8, Silica has no `Recreatable` yet); sockets and TLS
(S-22, B1, B3); a non-failing send (yours, D31).

**Platforms:** only Apple Silicon macOS is verified. Linux AArch64, Linux x86-64 and ESP32-S3 are 1.0 targets (D29) and
have not been run.

## 11. A checklist for a first conforming program

1. `main` calls `bees_exit@start()` first, then starts a root supervisor.
2. Every unit's atoms are in its manifest; no unit writes a BEAM atom literal; `bees_config check` is clean.
3. Every actor is cast-only unless it is the call half of a `gen_server`; every spawn passes `stack_policy`.
4. Every spawned actor is added to a supervisor with a distinct child id; ids are reused when children stop.
5. No `catch`, `try ... catch` or `after` is emitted; every `case` has a failing catch-all; failures use `fail_self`.
6. Long computations end their dispatch at yield points.
7. Messages carry their region; computed messages are bound before the cast; the outer recursive type is spelled out.
8. Your documentation says how you lowered `!`, `exit/2`, `link`, and binary and bit-syntax operations.
9. The program builds with Silica's compiler through `bees_config`, and your reference programs run: a ping-pong with
   selective receive, a process ring, and a supervised worker restarted after a crash.

## 12. Where to look

- Decisions: `development-plan/roadmap.md` §6 (D1-D32). Gaps and owners: `development-plan/gap-ledger.md`.
- Silica defects and their status: `development-plan/silica-defects.md`.
- Spike notes with the measurements behind these rules: `development-plan/spikes/`.
- Working examples: `trials/` (each leaf has `.scout` goldens you can read as expected output).
