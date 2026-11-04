# BEES Gap Ledger

This ledger maps each BEAM construct that compiled BEAM-language code relies on to what it becomes on Silica. The
target is one of four things:

- a Silica construct;
- a component of the BEES shim;
- an obligation on the language compilers, specified by the BEES target contract;
- the native edge.

BEES makes compiling a BEAM language to Silica **possible, not easy** (roadmap D19). So a row's goal is a *route*
to Silica, not a reproduction of BEAM behaviour. Where Silica can already express something, however awkwardly,
the row goes to the compilers (class C). What BEES deliberately does not provide is listed in §5.

For each construct the ledger records Silica's status today and who owns closing the gap. It is the checklist behind
the [roadmap](roadmap.md)'s definition of 1.0, and the seed of the target contract (roadmap R0.3). A row marked
**1.0** is closed only by trials, or by an explicit move out of scope in the README.

**Silica status** (at Apple Silicon fixed point 1, commit `8aff9cdc5`):

- **Tested**: implemented and covered by Silica trials.
- **Stub**: typed by the compiler, but the runtime does nothing.
- **Spec**: specified, not implemented.
- **Absent**: neither specified nor implemented.

**Spec (2026-09-15)** marks text written into Silica's specification, sibling design documents and ROADMAP on
2026-09-15 to carry the BEES decisions. It is on Silica's `main`, awaiting review, and none of it is implemented yet.
Where a row says what the implementation does, that is the fixed-point behaviour above.

**Class** (roadmap §2):

- **U**: upstream; Silica owns it (a Track S item).
- **B**: the BEES shim.
- **C**: an obligation on each language's compiler. Compilers are outside BEES, and the target contract specifies the
  obligation.
- **E**: the native edge.
- **—**: a Silica construct used as-is.

Spec section numbers refer to `silica/compiler/silica-compiler/design_documents/silica-specification.md`. Decisions
are in [roadmap §6](roadmap.md#6-decisions), and every decision the ledger cites has been made.

---

## 1. Construct mapping

### 1.1 Language constructs

| BEAM construct | On Silica | Silica today | Class | Closed by | Target |
| --- | --- | --- | --- | --- | --- |
| Modules, exported and local functions | Silica modules and functions over `bees_term`, using a reserved per-language module prefix | Tested | C (naming in the contract) | T1 | 1.0 |
| Functions with more than 8 parameters | Arguments packed into one tuple, as the contract specifies | Silica allows at most 8 parameters (E3010) | C | T1 | 1.0 |
| `case`, clause patterns, guards | Silica `case` over `bees_term` tags | Tested (`case` is Silica's only branching construct) | C | T1 | 1.0 |
| Tail calls (loops) | Silica tail calls, with an evacuation point and a yield point at each loop back-edge | Tested (recursion is the only loop) | C, B (evacuation and yield helpers) | T1, A1, A6 | 1.0 |
| Deep body recursion | Silica stacks | Fixed 512 KB stacks; growable stacks are roadmap chunk 1 | U (S-6) | X2 | 1.0 |
| `receive` with selective matching and `after` | **A plain Silica actor.** The compiler reshapes the code around each `receive` (D1), keeping the paused computation in actor state. BEES supplies the save queue for messages that don't match, and the `after` timers. | User `recv()` is forbidden by design (§15.1.2). Spec (2026-09-15): `send_after` and `cancel_timer` (§22.14), which the `after` timers can use | C, B | T1, A2 | 1.0 |
| `try`/`catch`/`throw`/`error`/`exit`, stack traces | **Nothing is caught inside the actor** (D2). A failing BIF, `badmatch`, `badarith`, `throw` and similar all fail the actor, and its supervisor reports the exit (D23). **Compilers reject `catch` clauses, `after` clauses and `catch Expr` at compile time.** BIFs never return failures as values. BEES provides result-returning versions of commonly caught BIFs, and Silica's `call_with_timeout` returns `:timeout` as a value; a compiler may rewrite a `try` that catches exactly one of those failures into a call to the variant. Stack traces come from Silica's crash report. | No exceptions (§6.2.3); errors are data; a fault or `panic` ends the actor with `:language_error`. Spec (2026-09-15): `fail_self(reason)` ends the actor with `(:explicit, reason)` (§15.1.2.3); `call_with_timeout` (§16.1.1.2) | C (compile-time rejection and rewrites); B (the BIF variants); U (S-9) | T1, A2, A3 | 1.0 |
| Funs (closures), `fun M:F/A` | A fun term (module, index, captured environment), plus a per-module `apply_fun` dispatch entry | Silica closures cannot escape their frame (defect A2, E1067) | C | T1 | 1.0 |
| `apply/2,3`, dynamic `M:F(...)` | Per-module dispatch entries, combined by `bees_config` into the program-wide module table | No dynamic dispatch | C, B (`bees_config`) | T1 | 1.0 |
| Binary construction, bit-syntax matching | Compiler lowering over binaries held as `buf(uint8)` plus a bit length. Literals become bytes at compile time; run-time values use lookups the compiler generates and same-type arithmetic (roadmap §4.5). | No type conversion, by design (§8.2.3); `buf(uint8)` exists | C | T1 | 1.0 |
| Integer bitwise operators (`band`, `bor`, `bxor`, `bnot`, `bsl`, `bsr`) | Compiler lowering: an `int64` crosses to `uint64` byte by byte through lookups the compiler generates, Silica's `uint64` operators apply, and the result crosses back. `bxor` is `(a bor b) band bnot (a band b)`. | `bor`, `band`, `bnot`, `shl` and `shr` on `uint64` only (§7.3.1); no `bxor` | C; U (S-11) beyond `int64` | T1 | 1.0 |
| Maps, map patterns, map updates | BEES term maps: `wbt_map` ordered by Erlang term order | `wbt_map` tested | B | A1 | 1.0 |

### 1.2 Data

| BEAM construct | On Silica | Silica today | Class | Closed by | Target |
| --- | --- | --- | --- | --- | --- |
| `term()`, i.e. every value | `bees_term`: a recursive tagged tuple (`recursive_tuple_specification.md`) in a region held in actor state | No dynamic type and no recursive unions; recursive tuples exist | B | R0.3, A1 | 1.0 |
| Garbage collection | Evacuation at the compiler's evacuation points, where every root is explicit (roadmap §4.2) | No GC by design; the per-actor arena is never reclaimed | B (API), C (placement); U (S-15) for region release | A1, T1 | 1.0 |
| Small integers | Silica `int64` with checked arithmetic | Tested (`checked_int64_add`, `checked_int64_mul`, `checked_int64_add1`); now also in the spec (§5.7, 2026-09-15) | — | Stage 1 | 1.0 |
| Big integers | Silica big integers | Spec (roadmap chunk 7) | U (S-11) | A1 | 1.0 |
| Floats | Silica `float64` | Tested | — | — | — |
| Atoms | **Silica atoms**, in Silica's atom table. Every BEAM atom literal is written in the generated `bees_atoms` unit (D30); compilers list their atoms in manifests and reach them through its accessors. BEES has no atom table of its own (roadmap §4.6). | Tested as compile-time constants. The spec requires one program-wide table (§4.1.7); the implementation numbers atoms per unit (spike S2, SD-3), which D30 makes harmless. | B (`bees_atoms`); C (manifests, accessors) | Stage 1 | 1.0 |
| `atom_to_list`, `list_to_existing_atom`, `list_to_atom`, and their binary forms | **Lookups, not conversions.** BEES BIFs over `bees_atoms@spelling` and `bees_atoms@from_spelling`, generated by `bees_config` from compiler manifests (roadmap §4.6, D30). No atom is created at run time: `list_to_atom` returns an atom only if the lookup holds it (D16). | Silica has no type conversion, and BEES adds none | B; C (manifests list atoms) | T1, A1 | 1.0 |
| Term order, `==` versus `=:=` | BEES comparison over `bees_term` | — | B | A1 | 1.0 |
| Pids, references, ports | A local pid is an `actor_ref`, identified by its **64-bit identity**: a 32-bit spawner position and a 32-bit child number (D22). A remote pid is the node plus that identity. References and ports are BEES terms carrying their node. | Spec (2026-09-15): the identity, with equality and order on every actor reference type, and `actor_id` (§15.1.4, §4.5.1, §7.4). Implementation: a pointer to a control block that is freed at teardown | U (S-26); B for remote pids | R0.3, A2, B3 | 1.0 |
| `term_to_binary`, `binary_to_term` | BEES ETF codec, encoder and decoder both in Silica, using BEES's own lookups and same-type arithmetic (roadmap §4.5); big integers wait on S-11 | §16.3 contains no serialization | B | A1, B3 | 1.0 |
| References (`make_ref/0`) | A BEES term: the node, the creating process's 64-bit identity (D22) and a per-process counter, so no counter is shared and no two live references are equal | — | B | A2 | 1.0 |

### 1.3 Processes and signals

| BEAM construct | On Silica | Silica today | Class | Closed by | Target |
| --- | --- | --- | --- | --- | --- |
| Process | **A plain Silica actor** whose messages are `bees_term` (D1) | Tested | — | Stage 1 | 1.0 |
| Lightweight processes in massive numbers | Silica's per-core scheduler, running many plain Silica actors on each core's carrier thread (spec §15.1.2, Actor Pinning Policy; §23.1.1). BEES balances them across cores (D3). | Specified, with yield points defined (§15.1.2, 2026-09-15; Silica ROADMAP chunk 12); one pthread per actor today | U (S-6); B for balancing | A6, X2 | 1.0 |
| `spawn`, `spawn_opt`, spawning on a given core | Silica `spawn`, with the entry function reached through the module table. **Every actor has a supervisor** (D18): a plain `spawn` adds a `temporary` child to a BEES supervisor, and those supervisors are sharded per core. Before one runs out of child numbers, it is replaced by a supervisor at a fresh position (S-26). | Tested | — (B for the BIF and the supervisors) | Stage 1, A2 | 1.0 |
| `!` (send) | Silica `cast` of a `bees_term` | Tested | — | Stage 1 | 1.0 |
| Call timeouts (`gen_server:call(S, M, Timeout)`) | A timeout fails the caller (D2). **Silica's `call_with_timeout` returns `:timeout` as a value instead**, for code that expects to handle it; the late reply is discarded, so it never reaches the caller's mailbox. | Spec (2026-09-15): plain `call` has no timeout (§16.1.1); `call_with_timeout(actor, msg, timeout_ms) -> (:reply, R) \| :timeout` (§16.1.1.2). The fixed 5-second rule in §22.4 is gone | — (C for the lowering); U (S-9) | A2, A3 | 1.0 |
| Message order per sender/receiver pair | Silica FIFO mailbox | Tested | — | — | — |
| Links, `spawn_link` | **The compiler's choice** (D18). It can use Silica `link` as it is, where a normal exit also ends the peer, or it can build link-like behaviour from exit requests to supervisors. | Stub (spec §15.4.8.4–5) | C; U (S-2) | T1, A2 | 1.0 |
| Monitors (`erlang:monitor/2`, `spawn_monitor`, `monitor_node`) | **Not provided** (D20, §5). A pending Silica `call` already wakes with the callee's death result, and supervisors handle fate-sharing. | Specified; a stub in the runtime (§15.4.8.6) | — | — | — |
| `trap_exit`, `{'EXIT', Pid, Reason}` | **Not provided** (D18, §5). In Silica only supervisors trap exits. Exits are handled by supervisors. | Absent by design | — | — | — |
| `exit/1,2` | **A request to the target's supervisor** (D18). The pid's supervisor position (D22) identifies the supervisor, through the program-wide position map (a `wbt_map` that `bees_config` generates and the runtime keeps current); the supervisor shuts the target down and reports it. Reasons are Silica `failure_reason` atoms. A process ends itself with Silica's `stop_self` (orderly) or `fail_self` (immediate); `remove_actor` must not name the caller (S-9). A restarted child has a new identity (D22), so a request aimed at an old pid never reaches its replacement. | `call_supervisor` `:terminate_child` tested. Spec (2026-09-15): `:terminate_actor` ends a child by `actor_ref` and returns `:not_found` for an old ref (§15.4.8.3); `stop_self`, `fail_self` (§15.1.2.3); identity equality (§15.1.4). No lookup of an actor's supervisor | B (the position map and the request); C (the lowering); U (S-26, S-9) | T1, A2 | 1.0 |
| `kill` | Silica `kill_abnormal`, or the supervisor's brutal shutdown (`shutdown: 0`) | Spec (2026-09-15): `kill_abnormal(target: actor_ref \| atom) -> :ok`, reason `(:explicit, :killed)`, never the calling actor (§22.4, §15.1.2.3). The implementation already accepts an `actor_ref` or a registered name | — ; U (S-9) | A2 | 1.0 **Note 2026-11-04:** a running dispatch cannot be ended: nothing preempts it, so `kill_abnormal` and a brutal `shutdown: 0` take effect only after the current dispatch returns (Silica spec §15.4.12.2 status note, 2026-10-15; ROADMAP chunk 2). Silica's §15.1.2 wording ("end an actor where it stands") disagrees and is left as it is; BEES follows the behaviour. A compiled loop with no yield point is therefore unkillable, and the A6 watchdog can only report it. Compilers must place yield points (contract item 6). |
| Crash isolation | Silica crash containment and `FailureReporter` | Tested | — | — | — |
| Registered names | **Silica's registry** (§20.3.1): `register/2`, `unregister/1` and `whereis/1` become thin BEES BIFs over `register`, `unregister` and `whereis`, keyed by Silica atoms. Silica removes a name when its actor ends and carries it to a restarted child, so the exit hub's name bookkeeping (D23) is needed only until S-29 lands. | Spec (2026-09-15, §20.3.1): register after spawn, one name per actor, removal at teardown before the supervisor handles the exit, names carried across restarts. Implementation: registration at spawn only; a supervised child is re-registered under its child-spec `id` on restart; a name registered with plain `spawn_registered` is never removed, so after the actor dies it points at a freed control block. | B (BIFs); U (S-29) | A2 | 1.0 |
| Timers: `send_after`, `start_timer`, `cancel_timer` | BEES BIFs over **Silica's timers** (`send_after`, `cancel_timer`, `timer_ref`); `start_timer`'s `{timeout, TRef, Msg}` wrapping is the BIF's. Until S-3 lands, `bees_timer`: a deadline heap (`brodal_okasaki`) over the native clock | Spec (2026-09-15): `monotonic_time`, `current_time`, `send_after`, `cancel_timer`, `timer_ref`; a timer is cancelled when its target ends; no `sleep` (§22.14, §4.5.2) | B; U (S-3); E for the clock until S-3 | Stage 1, A2 | 1.0 |
| Process dictionary | A term map kept in actor state, with BEES helpers for it | — | C, B | T1, A2 | 1.0 |
| `process_info`, `processes/0`, `is_process_alive/1` | BEES BIFs over Silica actor introspection | Absent | B; U (S-8) for mailbox data | A2, A3 | 1.0 |
| `hibernate` | An evacuation of the actor's compiler-held state | — | B, C | A4 | 1.0 |
| Group leaders | A process attribute, plus the BEES I/O protocol server | — | B | A5 | 1.0 |

### 1.4 OTP behaviours

| BEAM construct | On Silica | Silica today | Class | Closed by | Target |
| --- | --- | --- | --- | --- | --- |
| `supervisor` | Silica's `Supervisor` trait; each child's start MFA goes through the module table. Every actor has a supervisor (D18). | Tested | — (C for the mapping, B for the start adapter) | Stage 1, A4 | 1.0 |
| `gen_server` (`handle_call`, `handle_cast` and `handle_info`) | **Two Silica gen_server-style actors**, one call-only and one cast-only (D5). The contract fixes only what other languages and nodes can observe: which actor a `gen_server` pid denotes (it must accept casts, S-31) and how a call and a cast reach the right half. Where the state lives, where `handle_info` goes, and cast-then-call order are each compiler's choice. | Tested: a Silica behaviour is either call-only or cast-only (§16.2.6.1) | — (C for the split) | T1, A4 | 1.0 |
| `gen_statem` (states, state and event timeouts, postponement) | **Silica's state-machine actors** (§15.5): the `StateMachine` trait, `spawn_state_machine`, inserted events, postponement, and state, event and generic timeouts. They are cast-only, so a compiler lowers a `gen_statem:call` to a cast carrying a reply-to (D1). A timeout carries an atom, so a compiler keeps a term payload in the data under that atom. There are no state-enter calls, so a compiler emulates them with a `:next_event` action. | Spec (2026-09-15, §15.5; Silica ROADMAP chunk 13) | U (S-17); C (calls, timeout payloads, state enter) | A4 | 1.0 |
| `gen_event`, `application`, `proc_lib`, `sys` | Converted to Silica constructs by each compiler, for the languages that use them; BEES holds no OTP source (D24). BEES supplies only the runtime pieces underneath (`proc_lib` and `sys` support, A4). | Absent | C; B (runtime support) | A4, I3 | 1.0 |
| Releases, `code_change` upgrades | — | Absent | U (S-12), B | Post-1.0 | Post |

### 1.5 ERTS modules and BIFs

| BEAM construct | On Silica | Silica today | Class | Closed by | Target |
| --- | --- | --- | --- | --- | --- |
| `erlang` BIFs | BEES BIF library, in coverage tiers. A failing BIF fails the actor (D2). Commonly caught BIFs also get result-returning versions, for example `{ok, Atom} \| error`. | — | B | Stage 1, A3 | 1.0 |
| `ets` | `bees_table`: actor-owned `wbt_map` tables (`set`, `ordered_set`, `bag`, `duplicate_bag`). The exit hub deletes a table when the process that owns it exits (D23). | Absent | B | A3 | 1.0 |
| `persistent_term`, `atomics`, `counters` | BEES; `atomics` uses Silica's `atomic` memory space where possible | Silica atomics are roadmap chunk 6 | B; U for atomics | A3 | 1.0 |
| `os`, `init`, boot | BEES | Absent | B | A3 | 1.0 |
| `code` | BEES over the program-wide module table; `load_*` and `purge` are unsupported until after 1.0 | Absent | B | A3 | 1.0 |
| `crypto` (hash, HMAC, `strong_rand_bytes`) | BEES over the native edge | Absent (crypto labels are a proposal, chunk 9) | B, E | A3 | 1.0 |
| Pure-Erlang OTP libraries (`lists`, `maps`, `string`, `logger`, …) | Converted by each compiler, for the languages that use them (D24). BEES depends on none of them. | — | C | I3 | 1.0 |
| Logging | `bees_log`: BEES's own logging, which its audit log uses and which a compiler's `logger` may sit on | — | B | A3 | 1.0 |
| Tracing (`erlang:trace`, `dbg`) | BEES trace hooks | Absent | B; U (S-8) for dispatch hooks | A5 (partial) | Post (full) |
| `zlib`, compressed `term_to_binary` | — | Absent | E | Post-1.0 | Post |

### 1.6 Host I/O

| BEAM construct | On Silica | Silica today | Class | Closed by | Target |
| --- | --- | --- | --- | --- | --- |
| `gen_tcp`, `gen_udp`, `inet` | `bees_inet`: BEES's own implementations, in Silica (D24), over `bees_io` and the socket wrappers (S-22) | Silica ROADMAP chunk 10; spec §20.4 sketches it | B; U (S-22); E until S-22 | A5 | 1.0 |
| Event loop; ports with `{active, once}` | `bees_io`, one loop per core | Absent | B (the S-22 wrappers) | A5 | 1.0 |
| `file` | `bees_file`: BEES's own implementation, in Silica (D24), over Silica file operations and the native edge | `read_lines`, `append_file` and `delete_file` only | B, E | A5 | 1.0 |
| Standard I/O and the I/O protocol | BEES I/O server | `print`/`println` | B | Stage 1 subset, A5 | 1.0 |
| DNS | the `getaddrinfo` wrapper (S-22); until then, native `getaddrinfo`, whose results need re-creation (S-5) | Spec only | B (S-22 wrapper) | B1 | 1.0 |
| `ssl` | Not provided in 1.0. TLS belongs to TRUST and BEAM-mode TLS, through the native edge. An `ssl`-compatible subset over the same edge comes after 1.0. | Absent | E, B | Post-1.0 | Post |

### 1.7 Scheduling and observability

| BEAM construct | On Silica | Silica today | Class | Closed by | Target |
| --- | --- | --- | --- | --- | --- |
| Schedulers, run queues, fairness, priorities | **Silica's per-core scheduler** (spec §23.1.1). Silica never interrupts a dispatch (§15.1.2), so BEES adds a dispatch-budget helper that compiled code checks at yield points. | Spec (2026-09-15): reconciled. The scheduler switches only at yield points (a behaviour's return, or a wait such as a call awaiting its reply) and never preempts (§15.1.2, §23.1.1); `priority_level` is `:low`, `:normal` or `:high` (§22.10). Not implemented | U (S-6); C, B for yield points | A6 | 1.0 |
| Preemption of long-running code | Yield points at tail calls and receive boundaries, placed by compilers (contract item 6). A process whose budget is spent ends its dispatch there and continues through `cast(self())`. | None | C, B | T1, A6 | 1.0 |
| Core pinning, topology | Silica's Actor Pinning Policy (§15.1.2): every actor is pinned from spawn until it terminates. Running raw, a pin is exclusive and hard. OS-hosted, the actor is bound hard to its core's carrier thread, but the OS may move that thread, so exclusivity is never guaranteed (roadmap §4.10). | Specified; tested as hints only on macOS | — | — | — |
| Placement, balancing, overload protection, runaway watchdog | **BEES** (D3), entirely through `migrate_actor()` and the core id given at spawn. OS-hosted, it balances BEAM-style between the runtime's carrier threads; running raw, directly onto the cores. It keeps cores reserved for blocking and dangerous actors. Each migration takes effect at a dispatch boundary, and explicitly placed processes are never moved. | Specified: the runtime never moves an actor, and programs migrate with `migrate_actor()` (§15.1.2). Spec (2026-09-15): it returns `:ok` when the move is requested, or `:invalid_target`, `:actor_not_found` or `:migration_blocked` | B; U (S-23) for `migrate_actor()` on the raw targets | A6 | 1.0 |
| Telemetry | BEES | Absent | B | A5 | 1.0 |

### 1.8 Distribution and security

| BEAM construct | On Silica | Silica today | Class | Closed by | Target |
| --- | --- | --- | --- | --- | --- |
| `node()`, node names, `nodes()` | BEES node identity and distribution BIFs | Absent | B | B1, B3 | 1.0 |
| **SEMP/TRUST** (`trpc:call`, `trpc:cast`) | `bees_trust`, with TLS in the native edge | Absent (the design is in BEAM_SEMP) | B, E | Stage 1, B1, B2 | 1.0 |
| **Standard distribution** (EPMD, handshake, remote send, links, the `tls` transport) | `bees_dist`, with `inet_tls_dist`-compatible TLS in the native edge (D25) | Absent | B, E | Stage 1, B3 | 1.0 |
| `nodedown`, `monitor_node`, `net_kernel:monitor_nodes` | **Discovery by sending** (D28). A send to a node that cannot be reached fails the sender with `noconnection`, or returns it from the result-returning variant. No notification is pushed, and `monitor_node` is not provided (§5). | Absent | B (the send BIFs) | B3 | 1.0 |
| `gen_server` and `gen_statem` calls and casts to and from OTP nodes | `bees_gen` in `bees_dist`: the OTP `gen` call and cast protocol on the wire ([inter-nodal-modes §4.7](inter-nodal-modes.md#47-calls-and-casts-to-and-from-otp-behaviours)) | Absent | B | B3 | 1.0 |
| Remote spawn, `erpc`, `rpc` | SPAWN_REQUEST in `bees_dist`; BEES's own `erpc` and `rpc`, in Silica (D24) | Absent | B | B4 | Post |
| `global`, `pg`, `net_kernel` | BEES's own implementations, in Silica (D24), over the distribution BIFs | Absent | B | B4 | Post |
| Bringing FFI-derived data into BEES | **Re-creation** (S-5), a compiler-implemented trait, followed by `bees_ingress` protocol validation | The FFI spec keeps FFI-derived data tainted however it is copied (§7.4). Spec (2026-09-15): re-creation is FFI spec §7.7's validator, and the only one. Not implemented | U (S-5), B (`bees_ingress`) | Stage 1, B1 | 1.0 |
| TEMPUS | `bees_tempus`, with Ed25519 in the native edge | Absent | B, E | Post-1.0 | Post |

### 1.9 Code management

| BEAM construct | On Silica | Silica today | Class | Closed by | Target |
| --- | --- | --- | --- | --- | --- |
| Ahead-of-time compilation | Language compiler → Silica compiler → native executable | — | C | I3 | 1.0 |
| Hot code loading, two versions of a module | Silica dynamic linking and `hot_swap` | Spec bullets only (§26.3.2); roadmap chunk 8 | U (S-12), B | Post-1.0 | Post |
| NIFs | **Reworked by the language compiler** into a Silica actor that wraps the external call through Fifi: a `dangerous_*` module and a `spawn_dangerous` worker, as standard Silica does (D13). `erlang:load_nif` is not provided. | Fifi tested | C; U (S-5) for results used beyond the receiving handler; U (S-24) on the raw targets | T1 | 1.0 |
| Ports to external programs (`open_port` with `spawn`/`spawn_executable`, `os:cmd`) | **The same route as NIFs** (D13): the language compiler reworks each use into a Silica actor that wraps the external call through Fifi, in a `dangerous_*` module run by a `spawn_dangerous` worker. BEES provides no `open_port`. Not available on the ESP32-S3, which has no processes to spawn. | Fifi tested | C; U (S-5) for results used beyond the receiving handler | T1 | 1.0 |

---

## 2. BEES components

| Component | Class | Milestone | Role |
| --- | --- | --- | --- |
| Target contract and conformance kit | B | R0.3, T1, T2 | The specification that all language compilers share, plus reference lowerings and a self-check suite. |
| `bees_config` | B (tooling) | R0.1, T1 | Assembles `silica.config`; generates the `bees_atoms` unit (D30), the program-wide module table and the position map (D18) from compiler manifests; checks that no other unit writes a BEAM atom literal. |
| `bees_term`, `bees_cmp`, `bees_map`, `bees_bits`, `bees_heap` | B | Stage 1, A1 | The term model (atoms are Silica atoms), term order, maps, bit syntax, and the evacuation API. |
| `bees_etf` | B, E | A1, B3 | `term_to_binary`/`binary_to_term`, and the BEAM-mode wire codec. TRUST has its own encoding (D8). |
| `bees_recv` (save queue, `after` timers), `bees_pdict`, `bees_signal`, `bees_names`, `bees_timer`, `bees_exit_hub` (one supervised actor per node) | B | Stage 1, A2 | Runtime helpers that reshaped code calls, and the exit hub that receives supervisor exit reports (D23). None of them wraps an actor. `bees_names` and `bees_timer` shrink to BIF layers once Silica's registry (S-29) and timers (S-3) land. |
| `bees_bif_*`, `bees_table`, `bees_pterm`, `bees_atomics`, `bees_os`, `bees_init`, `bees_code`, `bees_crypto` | B, E | A3 | The ERTS-level modules. |
| Behaviour adapters: Silica's `Supervisor` trait, the call/cast gen_server split, and the state-machine trait | B | A4 | The runtime side of contract item 5. |
| `bees_io`, `bees_inet`, `bees_file`, `bees_stdio`, `bees_log`, `bees_telemetry` | B, E | A3, A5 | Host I/O, logging and observability. `bees_inet` and `bees_file` are BEES's own `gen_tcp`/`gen_udp`/`inet` and `file` (D24). |
| `bees_place` (balancer, placement hook, reserved cores for blocking and dangerous actors, dispatch-budget helper, watchdog, load statistics) | B | A6 | Balancing and placement across cores through `migrate_actor()` (D3). |
| `bees_ingress` | B | Stage 1, B1 | Protocol validation for all network input: TLS plaintext after re-creation, and bytes from Silica's own sockets. |
| `bees_trust` (listener, connection FSM, client, whitelist, tokens, suspicion, the `trust/1` term codec), exposed as `trpc` | B, E | Stage 1, B1, B2 | See inter-nodal-modes.md §3. |
| `bees_dist` (EPMD, handshake, control messages, node connections, the `tls` transport, distribution BIFs, `bees_gen` for the OTP `gen` call protocol on the wire; after 1.0 `erpc`, `rpc`, `net_kernel`, `global`, `pg`) | B, E | Stage 1, B3, B4 | See inter-nodal-modes.md §4. All of it is BEES's own Silica (D24). |

---

## 3. Track S — Silica prerequisites

These are work items in the Silica repository. BEES files each one as a small proposal with a reproducing trial,
under Silica's `AI_POLICY.md` and fixed-point rules, and may contribute the implementation. The **Interim** column
says what BEES does until the item lands. IDs are stable: a withdrawn item keeps its number.

| ID | Item | Why BEES needs it | Blocks | Interim | Evidence |
| --- | --- | --- | --- | --- | --- |
| **S-1** | Atom identity across compilation units: the one global atom table the spec promises. **Confirmed missing by spike S2 (SD-3), 2026-09-17.** | BEES no longer needs it: every BEAM atom literal lives in the generated `bees_atoms` unit (D30). It stays filed as a defect against spec §4.1.7; stdlib callback atoms would benefit. | Nothing (D30) | `bees_atoms` | `trials/s02_cross_unit_atoms/`; spec §4.1.7 |
| **S-2** | Runtime `link`, per spec §15.4.8.4–5. BEES does not need Silica's `monitor` or `demonitor` (D20). | Compilers may use Silica links for BEAM links (D18), and a library cannot observe deaths it does not supervise, which is why exit reports exist (S-28, spike S7). | A2, B3, I1 | Supervisor-only lifecycle in the PoC | `Phase2_TODO/actor_monitor_demonitor_todo.md`; the stubs in `prims_actors_runtime_asm.silica` |
| **S-3** | Monotonic clock and timer primitives. There is no `sleep`: an actor waits by ending its dispatch until a timer's message arrives. | Every timeout depends on them. | Nothing hard once S-5 has landed; until then, clock values cannot leave the edge handler | Native `clock_gettime` and a bounded `poll` | **Spec (2026-09-15):** `monotonic_time`, `current_time`, `send_after`, `cancel_timer` (§22.14) and `timer_ref` (§4.5.2); Silica ROADMAP chunk 12. Not implemented. |
| **S-4** | *Withdrawn.* Byte primitives: byte access to `string`, conversion between `string` and `buf(uint8)`, `bxor`, integer width conversions, and float bit-casts. | Not needed. Silica has no type conversion and BEES adds none: compilers lower bit syntax and bitwise operators with lookups they generate, BEES's codecs do the same, and binaries are never Silica strings (roadmap §4.5). What remains is S-21 and S-22. | — | — | — |
| **S-5** | **Re-creation:** a compiler-implemented trait, `Recreatable`, now specified as FFI spec §7.7's validator. It is established on an inline type, with limits only. The compiler derives `recreate(x) -> (:ok, T) \| (:rejected, atom)`, which checks the declared limits before reading contents, rebuilds the value in a fresh region the caller owns, rebuilds enumerations from the type's own literals, and range-checks everything else. It may be called only where tainted data may legally be. Its output is pure, but still barred from `hot_swap` and command execution (§7.2). | TLS and secure random bytes come through the native edge (D17). Without re-creation, TLS plaintext and ciphertext, random bytes, digests and peer-certificate data cannot leave the handler that receives them (§7.3, §7.6). | B1, B3, every native-edge flow | None: FFI output is unusable outside its handler. The protocol layers run over an in-process loopback transport. | **Spec (2026-09-15):** FFI spec §7.7. Limits `max_bytes`, `max_depth`, `max_length` and `utf8`; rejection atoms `:too_large`, `:too_deep`, `:bad_tag`, `:out_of_range`, `:bad_utf8`; errors `RecreateCallSiteError` and `RecreatableLimitError`. §7.2, §7.4 and §7.6 now refer to it, and open questions 4 and 5 in §16 are resolved. Silica ROADMAP chunk 14. Not implemented. |
| **S-6** | **Silica's per-core scheduler, as its spec describes** (Actor Pinning Policy §15.1.2, §23.1.1): a carrier thread per logical core running many actors, with fairness and priority, switching only at yield points. Also: **growable stacks** (roadmap chunk 1). | Per-core scheduling is Silica's (D3). BEAM process counts need many actors per carrier thread, and deep recursion needs stacks that grow during a dispatch. | A6 (scale), X2; conformance for deep recursion | One thread per actor; PoC scale taken from spike S3 | **Spec (2026-09-15):** "dispatch boundary" and "scheduler yield point" are defined (§15.1.2), and §23.1.1 no longer claims preemption; `priority_level` (§22.10); stacks unlimited by default (`actor_growable_stack_design.md`). Silica ROADMAP chunks 1 and 12. What remains is the implementation. `Phase1_TODOs/actor_stack_growth_plan.md` |
| **S-7** | Library consumption: a search path, `wrapper_meta` paths rooted at the library, and prebuilt library artifacts | Consuming BEES and compiled standard libraries without copying files around. | Nothing hard | `bees_config` | FFI wrapper spec §14.1, §14.3 |
| **S-8** | Mailbox introspection, and a tracing hook in message dispatch | `process_info`, overload protection, and tracing. | A3, A5 (in part) | Counters kept by BEES | Spec §16.2.8 |
| **S-9** | **Stopping and shutdown** for ordinary actors, now specified:<br>• an actor stops itself with `stop_self(:normal \| (:explicit, atom))`, which is orderly (the current dispatch finishes and a call still gets its reply), or `fail_self(atom)`, which is immediate; `remove_actor` and `kill_abnormal` must not name the caller;<br>• a supervisor's orderly shutdown: it stops dispatching, lets the current dispatch finish, ends the child with `(:explicit, :shutdown)` and kills it after `shutdown` ms, with no message sent to the child;<br>• `temporary` rows are removed from the child table when the child ends;<br>• `kill_abnormal(target: actor_ref \| atom) -> :ok`, with reason `(:explicit, :killed)`;<br>• one call-timeout rule: `call` has none, and `call_with_timeout` returns `:timeout` and discards the late reply;<br>• `:terminate_actor` ends a child by `actor_ref`.<br>**Still open:** what "raises `actor_not_found`" means for `call` and `cast` in a language without exceptions. D2 needs it to fail the caller. | Every actor has a supervisor, and exits go through supervisors (D18). Without a self-stop, a process asking its own supervisor to end it waits out its shutdown timeout. Without the signal, no cleanup code can run. Without removal, the table grows with every `spawn`. | A2 (soft) | `shutdown: 0` (brutal) for BEAM processes; cleanup such as `terminate/2` does not run | **Spec (2026-09-15):** §15.1.2.3, §15.4.8.3, §15.4.11.2, §15.4.12.2, §15.4.13.2–3, §16.1.1.2, §22.4. Silica ROADMAP chunk 11 (the timeout in chunk 12). Not implemented. |
| **S-10** | Variant types (roadmap chunk 5) | A cleaner `bees_term`. | Nothing hard | Recursive tagged tuples | ROADMAP chunk 5 |
| **S-11** | Big integers (roadmap chunk 7) | Erlang integer semantics. | **1.0** (A1) | `int64`, with overflow raising `system_limit` | ROADMAP chunk 7 |
| **S-12** | Dynamic linking and `hot_swap` loading (roadmap chunk 8) | Hot code upgrade. | Post-1.0 | None | Spec §26.3.2 |
| **S-13** | Native TLS intrinsics, with a hook that exposes the peer certificate or its SHA-512 fingerprint | Retiring the TLS native edge; TRUST whitelisting. | Retiring E | rustls through the native edge (D6) | `tls_quantum_safe_future.md` §5 |
| **S-14** | Crypto labels, `CtMask`, `proc[secret]` (roadmap chunk 9) | Constant-time comparison and zeroization inside Silica. | Retiring E | Native constant-time compare | `crypto-proposal-introduction.md` |
| **S-15** | Region release inside a living actor (roadmap chunk 4) | Evacuation, BEES's substitute for GC (roadmap §4.2). | **1.0** (A1) | Short-lived processes only | `region_memory_safety_todo.md` |
| **S-16** | A hash map | O(1) ETS operations. | Nothing hard | `wbt_map` | `atom_actor_registry_direct_index_design.md` §1 |
| **S-17** | A state-machine behaviour trait: states, state and event timeouts, postponement | State machines belong in Silica beside the gen_server-style behaviours and the `Supervisor` trait (D5). `gen_statem` modules and the TRUST connection FSM compile to it. | A4; B1 (soft) | The TRUST FSM as a plain behaviour with an explicit phase field | **Spec (2026-09-15):** §15.5: the `StateMachine` trait (`init`, `handle_event`), `spawn_state_machine`, `state_machine_behavior(T)` for child specs, inserted events, postponement, and state, event and generic timeouts. Cast-only, and no state-enter calls. The capabilities draft (§9.2) notes that postponement is not protocol deferral. Silica ROADMAP chunk 13. Not implemented. |
| **S-18** | *Withdrawn.* A selective-`receive` primitive for stackful processes. | Not needed: D1 decided that processes are plain actors and compilers reshape code. | — | — | — |
| **S-19** | *Withdrawn 2026-09-15.* A gen_server trait in which one process handles `call`, `cast` and raw messages. | Not needed: an Erlang `gen_server` that uses both becomes two Silica gen_server-style actors, one call-only and one cast-only (D5). | — | — | — |
| **S-20** | *Withdrawn.* Spelling access to Silica's atom table. | Not needed: Silica has no type conversion and BEES adds none, so atom spellings come from the generated atom lookup (roadmap §4.6). | — | — | — |
| **S-21** | `buf(region, uint8)` across the FFI boundary, as the FFI wrapper spec describes | Whatever still passes through the native edge (TLS records until S-13, file data) must cross as bytes, because binaries are `buf(uint8)` and never Silica strings (roadmap §4.5). | Nothing hard | The edge packs bytes into records of `uint64` words, which BEES unpacks with `shr`, `band` and lookups | FFI wrapper spec §6.1–§6.4 and §8, which now use the one form `buf(L, Space, uint8, N)` (2026-09-15); Silica ROADMAP chunk 14; `ffi_abi_checker.silica` E2112 (scalars and inline records only at FP1) |
| **S-22** | **Socket and DNS wrappers through Fifi, written by BEES.** Silica will not write a TCP/IP stack: its ROADMAP chunk 9 and spec §20.4 put networking behind the Foreign Function Interface, inside guarded regions in `dangerous_` actors. S-22 consumes that requirement: BEES creates the host-socket and `getaddrinfo` wrappers (a `dangerous_` exposure source and its Silica adapters), following Silica chunk 9's wrapper shape and its trials. (Decided 2026-11-04; supersedes "Silica's own TCP/IP implementation".) | Sockets for `bees_inet`, TRUST and BEAM mode, with network bytes delivered as `buf(uint8)` and sent with their region. Network bytes stay tainted and reach a process only through re-creation (S-5), permanently, since no Silica stack will retire the edge. Every networked program has a `dangerous_` root. | Nothing hard once S-5 has landed; until then, socket bytes cannot leave the wrapper's handler | The native edge's kqueue/epoll entries | Silica ROADMAP chunk 9 ("no TCP/IP stack is written"); spec §20.4; FFI wrapper spec; on the ESP32-S3, sockets come from the board's lwIP through Fifi (S-24, D29) |
| **S-23** | `migrate_actor()` and exclusive pins **implemented** on the OS-free target, the ESP32-S3 (D29) | Running raw, BEES balances directly onto the cores, and `migrate_actor()` is the only way anything changes core (roadmap §4.10). | A6 (raw) | None; running raw, processes stay where they were spawned | Now specified: the Actor Pinning Policy (§15.1.2) makes pins exclusive on OS-free targets, lets only the program move an actor, applies a move at the actor's next dispatch boundary, and preserves message order. `migrate_actor` returns `:ok` when the move is requested, or an error atom (2026-09-15). What remains is the implementation; the ESP32-S3 port runs a cooperative scheduler on one core (`esp32s3_port_status.md`). |
| **S-24** | Fifi on the ESP32-S3 (D29) | The OS-free port reaches the native edge's facilities (sockets, TLS, hashes, random bytes, the clock) through Fifi, with the edge built against the board's own C libraries, lwIP under ESP-IDF and a C TLS library (D6), instead of an OS (roadmap §5, Release 1.0 item 8). | The native edge on the ESP32-S3 | None | `esp32s3_port_status.md`: "foreign (C) calls are not supported on this target" (no C runtime; the hosted guarded FFI is setjmp and signal based); Silica ROADMAP: ESP32-S3 FP1 replaces "Fifi against OS libraries" with board-pack equivalents. **Spec (2026-09-15):** `porting_for_os_free_targets.md` §9.1 specifies Fifi on OS-free targets, linked only against the board pack's minimal C runtime, where a trap ends the worker; `esp32s3_port_status.md` marks foreign calls as planned; Silica ROADMAP chunk 14. |
| **S-25** | *Withdrawn 2026-09-15.* Runtime notifications to an actor whose message type is something else. | Not needed by BEES: monitors are not part of BEES (D20). It remains an issue inside Silica: an actor that calls `monitor/1` is killed by a `DOWN` its message type does not admit (§16.2.3). | — | — | — |
| **S-26** | **The 64-bit actor identity** (D22), with equality and a total order on every actor reference type, as spec §15.1.4 now defines it:<br>• a 32-bit **position**, naming the spawner that numbered the actor, and a 32-bit **child number**, mapping one-to-one onto `NEW_PID_EXT`'s id and serial;<br>• positions belong to spawners: supervisors, any other actor that spawns, and `main`, which is position 0; root supervisors take the next positions; Silica's compiler numbers them at build time, in tree order;<br>• in BEES every spawn goes through a supervisor, so a process's position is its supervisor's;<br>• each spawner numbers its own children from 0 upward and never reuses a number, so no counter is shared and a restarted child gets a new identity;<br>• a spawner's position is stable across its restarts, and its numbering continues: its supervisor keeps the high-water mark in the child-table row;<br>• a spawner that starts spawners at run time owns a block of positions, sized by the compiler, and hands slices to the spawners it starts; BEES's per-core spawn supervisors move to a fresh position before they run out of child numbers and let the old one drain;<br>• exhaustion fails the spawner with `(:explicit, :identity_exhausted)`, which a supervisor treats as a breach of its restart intensity;<br>• equality and order compare (position, child number); `actor_id` returns the value;<br>• named actors compare by pid, not by name, as in Erlang;<br>• **stale refs:** a ref to a dead actor is only guaranteed never to equal a live actor, which never-reused numbers already give. BEES does not require stale refs to be detectable. Sending to one must not read a freed control block. | Compiled code compares pids constantly, and the D18 actor-to-supervisor map needs equality to find entries. Today an `actor_ref` is a pointer to a control block that is `free`d when the actor dies. A later spawn can reuse that address, so pointer identity can make a stale pid equal to a new actor. | A2, T1, B3 | Comparing `actor_ref_bits` words, which is unsafe because of address reuse | **Spec (2026-09-15):** §15.1.4, §4.5.1, §7.4, §15.4.12.1, §15.4.13.3; Silica ROADMAP chunk 11. D22 was aligned with this text the same day. The implementation still frees the ACB at teardown (`prims_actors_runtime_asm.silica`, around line 460), and the crash report prints the pointer as `actor_id`. |
| **S-27** | *Withdrawn 2026-09-17.* Silica's bare-metal AArch64 path. | Not needed: bare-metal AArch64 is no longer a 1.0 platform (D29). | — | — | — |
| **S-28** | **Supervisor exit reports to a report sink.** A supervisor is given a report sink (an `actor_ref`) with the `call_supervisor` op `:set_report_sink`, and its child supervisors inherit it. After the supervisor handles a child's exit, whether or not it restarts the child, the runtime casts `exit_report ::= { child, child_id, failure_reason, restarted, new_child }` to the sink. Reports are sent in supervision-ingress order, and the supervisor never waits on the sink. | With every actor supervised (D18) and no monitors (D20), supervisor reports are the only reliable news of a death (D23). BEES's exit hub needs them to remove names, delete owned tables, end BEES-level link partners, and tell BEAM-mode node connections about remote links. | A2, B3, I1 | None: without reports, links and remote links can only poll supervisors | **Spec (2026-09-15):** §15.4.10.5, §15.4.8.3; Silica ROADMAP chunk 11. The sink is set with an op, not in the supervisor's flags as D23 first proposed; setting it on the root supervisors covers the whole tree. Not implemented. |
| **S-29** | **The atom-keyed registry** as spec §20.3.1 defines it:<br>• `register(name, actor)` after spawn, returning `:ok`, `:name_taken`, `:already_registered` or `:actor_not_found`, with one name per actor;<br>• `whereis(name) -> Some(actor_ref) \| None`;<br>• `unregister(name)`;<br>• a name is removed when its actor ends, before the supervisor handles the exit;<br>• a restarted child that held a name gets it back before it handles its first message. | `register/2`, `whereis/1` and `unregister/1` map straight onto it, and it takes name bookkeeping out of the exit hub (D23). | A2 (soft) | The BEES name table, with the exit hub removing a dead pid's names | **Spec (2026-09-15):** §20.3.1; Silica ROADMAP chunk 11. The implementation registers only at spawn and re-registers a restarted child under its child-spec `id`, where the spec says under the name it held; a `spawn_registered` name is never removed. |
| **S-30** | *Withdrawn 2026-09-17.* Supervisor children in a `child_spec`. | Not needed: Silica supervisors can have supervisors as children. The reading of §15.4.13.2 behind this item was wrong. | — | — | — |
| **S-31** | **Run-time calling-convention check.** When the compiler cannot see a reference's convention, the runtime checks it: a `call()` to a cast-only actor, or a `cast()` to a call-only one, enqueues nothing and fails the caller with `:language_error`. | Compiled BEAM code keeps pids inside `bees_term`, so almost every send goes through a reference whose convention the compiler cannot see. With the D5 split, the contract must say which of a `gen_server`'s two actors a pid denotes. | A2, T1 | The contract's convention for which pid is exposed, with no check | **Spec (2026-09-15):** §16.2.6.4; Silica ROADMAP chunk 11. Not implemented. |
| **S-32** | **Silica's Linux x86_64 path:** an emitter and a hosted runtime for x86_64. | Linux x86_64 is a 1.0 platform (D29). Silica has emitters only for Apple Silicon, Linux AArch64 and the ESP32-S3. | Release 1.0 item 8 (Linux x86_64) | The two AArch64 hosts | Silica's ROADMAP lists no x86_64 path yet. |
| **S-33** | **Ending a running dispatch (noted, not filed).** Silica's spec contradicts itself: §15.1.2 says `kill_abnormal` ends an actor "where it stands", §15.4.12.2 (status 2026-10-15) says a child finishes its current dispatch whatever `shutdown` says. Noted 2026-11-04 on a BEES-documentation-only basis: BEES does not ask Silica to change its text. | `exit(Pid, kill)`, brutal shutdown and runaway-loop recovery behave as "after the current dispatch". | Nothing hard; contract item 6 (yield points) carries the consequence | The A6 watchdog reports the runaway dispatch and nothing more | Silica spec §15.1.2, §15.4.12.2; ROADMAP chunk 2 |

---

## 4. Native edge inventory

The native edge is one C archive, `libdangerous_bees_native.a`, reached through Silica's Fifi. It is built for each
target: against the OS on the hosted targets (Apple Silicon, Linux AArch64, Linux x86_64), and against the board's own
C libraries on the ESP32-S3 (lwIP under ESP-IDF and a C TLS library, D6; Fifi there is S-24, D29). Silica code reaches it only through `dangerous_bees_*` wrapper modules and `spawn_dangerous` workers,
and every value it returns is re-created (S-5) before anything else uses it. Network content then passes `bees_ingress`. Byte payloads cross the boundary as `buf(uint8)` (pointer and length) once S-21 lands, and as
records of `uint64` words until then; they are never Silica `string` values. Structured results cross as flat
records.

| Entry | Purpose | Retires when |
| --- | --- | --- |
| `clock_monotonic_ns`, `clock_system_ns`, `poll_wait(ms)` | Time and the timer tick | S-3 |
| TCP and UDP socket calls; kqueue/epoll registration and wait | `bees_io`, `bees_inet` | the socket wrappers BEES creates (S-22) |
| `getaddrinfo` (A/AAAA records only) | DNS | the `getaddrinfo` wrapper (S-22) |
| File write, directory operations, file metadata | `bees_file` | Silica `device_io` completion |
| TLS 1.3 session operations through rustls on the hosted targets and a C TLS library on the ESP32-S3 (D6), with no sockets of its own: configure, handshake, read, write, peer certificate DER and its SHA-512, ALPN | TRUST, BEAM-mode TLS | A Silica TLS built-in (S-13; not planned at first, D17) |
| SHA-2 family, MD5, HMAC | `crypto`, certificate fingerprints, the Erlang cookie challenge | S-14 (MD5 stays for as long as BEAM mode exists) |
| `random_bytes(n)` | `crypto:strong_rand_bytes`, tokens, challenges | A Silica secure-random built-in (not planned at first, D17) |
| `ct_equal(a, b)` | Token validation | S-14 |

**Rules for the edge:**

- No handles are visible to Silica beyond connection identifiers owned by one worker actor.
- No callbacks.
- Every entry point enforces a hard limit on the size of its inputs.
- The archive is rebuilt from pinned sources, and its hash is recorded in the trial tree.

---

## 5. Not provided

BEES makes compiling a BEAM language to Silica possible, not easy (D19), so it does not duplicate every BEAM
construct. These are left out on purpose. Where a compiler wants something similar, it builds it from what Silica
and BEES do provide.

| Feature | Status | Reason |
| --- | --- | --- |
| Loading or interpreting `.beam` bytecode at run time | Not provided | Code is compiled ahead of time by the language compilers. |
| Catching failures (`catch throw:…`, `catch error:…`, `catch exit:…`, `after` clauses, Erlang's `catch Expr`) | Not provided (D2); compilers reject them at compile time | Every failure, `throw` included, fails the actor, and its supervisor handles it. Silica aims to catch failures at compile time. BEES offers result-returning versions of commonly caught BIFs. |
| `trap_exit` for ordinary processes | Not provided (D18) | In Silica only supervisors trap exits, and `exit/2` goes to the target's supervisor. |
| Monitors (`erlang:monitor/2`, `spawn_monitor`, `monitor_node`, Elixir's `Process.monitor`) | Not provided (D20). In BEAM mode, monitor requests from OTP peers are dropped (D21), and a lost node is discovered by sending to it (D28). | A pending Silica `call` already wakes with the callee's death result, and supervisors handle fate-sharing. Other uses, such as cleaning up after a client that dies, are for compilers to build from what Silica and BEES provide. |
| BEAM-shaped failure messages (`{'DOWN', …}`, `{'EXIT', …}`, term exit reasons) | Not provided (D18) | Compiled code sees Silica's own shapes and atom reasons. At a BEAM-mode node boundary, BEES translates reasons to and from Erlang terms on the wire. |
| Processes without a supervisor | Not provided (D18) | BEES requires every actor to have a supervisor. |
| Creating atoms at run time | Not provided. `list_to_atom` and `binary_to_atom` return only atoms the atom lookup holds (D16); the wire accepts only those atoms too. | Decided in D16, for security. Atoms are Silica atoms. Silica's atom table is fixed at compile time, and BEES has no atom table of its own. In BEAM mode, the same rule makes the set of peers that may connect fixed at build time: a node must be named in the code. |
| Calling a local fun received from an Erlang node in BEAM mode | Not provided. The fun is carried as an opaque term, and calling it raises `badfun`. | Its code is BEAM bytecode. Export funs (`fun M:F/A`) work through the module table. |
| Hot code loading | Post-1.0 (S-12) | Needs Silica dynamic linking. |
| NIFs loaded at run time (`erlang:load_nif`) | Not provided (D13) | Each compiler reworks a NIF into a Silica actor that wraps the external call. |
| ETS concurrency guarantees | The options are accepted, and the actual semantics are documented | Silica actors share no mutable memory, so every table access is serialized through the table's owner. |
| Emulator introspection (`erts_debug`, scheduler `system_flag`s, GC statistics) | Accepted as no-ops or mapped (`garbage_collect` triggers an evacuation), and documented | These describe emulator internals that do not exist here. |
| Bug-for-bug OTP compatibility | Not claimed | As the README states; semantics follow one named OTP release (D14). |
