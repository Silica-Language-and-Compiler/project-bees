# N5: windowed multiplexing for TRUST (B2)

**Status: design written 2026-11-18 before any code; built and run the same day on macOS on Apple Silicon with
`silica-999909` (section 11): plaintext and mutual TLS 1.3, 17 scenarios, five runs in a row each. Not run on Linux (the
goldens there are still to be recorded). The choices made where SEMP is silent or contradicts itself are the questions of
section 9; the owner ruled on all of them on 2026-11-18 (the rulings follow the table), and the code names the question at
each place (`N5 Qn`). Sections 1 to 8 are the design as written before the code, with the rulings worked in where they
changed it; what turned out differently is in 11.1.** Plan:
[mvp.md](../mvp.md) section 5, the N5 row; behaviour: [inter-nodal-modes.md](../inter-nodal-modes.md) 3.6 to 3.10; options:
[bees-config-file.md](../bees-config-file.md) 5.3; what N3 and N4 built: [N3-trust.md](N3-trust.md),
[N4-silica-mtls-example.md](N4-silica-mtls-example.md).

## 1. What the SEMP sources say, and where they are silent

Read (read-only): `~/BEAM_SEMP/README.md`, `~/BEAM_SEMP/multiplexing and backpressure design doc.md` (called M below), and the
Erlang code under `~/BEAM_SEMP/src/`.

- **The Erlang code has no multiplexing.** `trust_conn.erl` serves one request and closes; `trpc.erl` opens one connection per
  call; there is no `trust_conn_fsm`, no worker supervisor, no GOAWAY, no session option, no telemetry call. M is the only
  source for B2, and it is a design ("Status: Draft" on every requirement), so every rule below is M's text or a marked choice.
- **What M requires (R-1 to R-9, its tables and its acceptance criteria 1 to 10):** several CALL/CAST per connection inside a
  session window; the window ends on the first of `max_age_ms`, `max_calls`, `idle_ms`, then one GOAWAY and a graceful close;
  at most `max_inflight` requests in work, by pausing reads, with no decoding and no queue while paused, resumed when a worker
  ends; results matched by `req_id`, in any order; duplicates of an in-flight `req_id` dropped silently and counted; GOAWAY
  reasons `limit_reached`, `shutdown` (drain, then close) and `deny`, `protocol` (close at once); suspicion raised only for
  `deny` and `protocol`; new requests after GOAWAY ignored and counted; effective drain `min(drain_ms, idle_ms)`; a client
  close in `active` or `draining` cancels the session, ends its workers, raises no suspicion; no error frame ever; limits of 1
  behave as one request per connection and never send GOAWAY; the telemetry events and metrics of its "Observability" section;
  fail-fast configuration.
- **Where M is silent or contradicts itself** (each is a question in section 9): how a client learns that a server multiplexes
  (its FSM table says the server sends `OK` after the token step, a frame that appears nowhere else, and R-6 says limits of 1 are
  identical to the old behaviour, which has no such frame); the shape of that `OK`; which refusals are `deny` and which
  `protocol`; what a user-code failure or a call timeout does to a session (the README closes the connection, which was the
  request; M's table only says a worker ending lowers `inflight`); which of a client's requests were taken when a GOAWAY crosses
  them on the wire; whether frames are read while draining; what `session_slots_max` refuses with; histogram buckets; the
  `acceptors` pool on a runtime with one accepting carrier; `req_id` (12 random bytes in the README, a small integer in M, at
  most 16 bytes in BEES).

## 2. The wire (additions to `trust/1`; nothing existing changes)

Frames are as in N3: a 4-byte length and one ETF map. B2 adds two frames and one optional key.

| Frame | Direction | Keys | Rule |
| --- | --- | --- | --- |
| `hello`, `token_present` | client to server | as N3, plus optionally `opts => #{goaway => 1}` | The **session offer**: "this client reads `goaway` and `ok`". Only atoms every B1 build already holds (`opts`, `goaway`), so a B1 server ignores the key (unknown and unused top-level keys are ignored) and does not refuse an atom. PROVISIONAL (Q2). |
| `ok` | server to client | `t`, `ver` | The **session acknowledgement** (M's `OK`): sent once, after the token step (after `token_issue` on the hello path) and before any result, only to a client that offered and only by a node whose limits are not both 1. From then on the connection is a session. PROVISIONAL (Q2). |
| `call`, `cast`, `result` | as N3 | as N3 | `req_id` 1 to 16 bytes, unique among the client's requests in flight on the connection. Results in any order. |
| `goaway` | server to client | `t`, `ver`, `reason`, `drain_ms` | `reason` is one of the atoms `limit_reached`, `shutdown`, `deny`, `protocol`; `drain_ms` a non-negative integer (0 for `deny` and `protocol`). At most one per session. The sender closes. Sent only on a session (after an offer). An unknown `reason` is read as `protocol`. |

New atoms (file `src/trust/bees_trust_mux.atoms`, held only by nodes built with sessions): `reason`, `drain_ms`,
`limit_reached`, `shutdown`, `deny`, `protocol`, and the registered names of the node's session actors. `ok`, `goaway`, `opts`
were already in `bees_trust.atoms`.

**How B1 and B2 peers recognise each other.** The client offers; the server acknowledges; anything else is B1.

| Client | Server | What happens |
| --- | --- | --- |
| B1 | B1 | N3 and N4, unchanged. |
| B1 (no offer) | B2 | The server serves that connection with limits 1 and 1: one request, no `ok`, no `goaway`, the same closes as B1. |
| B2 (offers) | B1 | The server ignores the offer, serves the pipelined first request and closes. The client saw a result (or a close) with no `ok` before it: the server is B1, and every later request goes on its own connection. |
| B2 (offers) | B2 | `ok`, then a session until `goaway` or a close. |

A B2 client sends a request on a connection only (a) as the first, pipelined request of a connection it opened, exactly as a
B1 client does, or (b) after that connection's `ok`. So no request is ever written to a B1 server behind another one.

## 3. Configuration

- **A node multiplexes when its `bees.config` writes `trust.session`** (the five keys, defaults and bounds of M, already
  validated by `tools/bees_conf.py`). Ruled (Q1): a node whose file has no `session` key multiplexes too, with the defaults 8
  and 100. That half is built and switched off (`SESSION_DEFAULT_ON = False` in `tools/bees_conf.py`): until it is switched
  on, such a node serves and calls one request per connection with N3's actors, untouched, which is what keeps every
  existing trial and golden as it is (section 12).
- `session` with `max_inflight` 1 and `max_calls` 1 runs the new session actors with limits 1: no offer is made, no `ok` and no
  `goaway` are sent, no telemetry line is printed, and the summary line still ends `one request per connection (B1)`. Trial
  `compat` shows the N3 goldens come out byte for byte (M's R-6, criterion 9).
- The client side of a node uses the same `session` map: `max_inflight` is the number of its own calls that may wait for results
  on one session; a call beyond that goes on its own connection. The other four keys are the server's.
- `acceptors`: validated, **not used** (the language's carrier has one accepting actor; a boot note says so when it is set). Q9.
- `session_slots_max`: when set, the listener refuses a new connection while that many sessions are open: closed before any byte
  is read, one audit line, no suspicion. PROVISIONAL (Q8).
- Values are compiled into `bees_trust_conf` by the build-time stand-in, as all TRUST options are today (D46 not built).
  `effective drain = min(drain_ms, idle_ms)` is computed there. The idle check runs every `max(10, idle_ms / 10)` ms (a timer's
  delay cannot be computed at run time: no int64 to uint64 conversion), so an idle session is noticed between `idle_ms` and
  `idle_ms` plus one tenth.

## 4. Actors and messages

Per connection there is still exactly **one receive actor and one send actor**; workers and their supervisor are behind the
receive actor and reach the send actor only through it. Every value is decoded and encoded in the `sequence` of a
`sequence ... produces pure` block (the language's `decode` and `encode`), in `bees_trust_frame` and the new
`bees_trust_mux_frame`.

Server side (new unit `dangerous_bees_trust_mux`, expanded from `src/trust/dangerous_bees_trust_mux.silica.in`):

| Actor | Lives | State | Job |
| --- | --- | --- | --- |
| `mlsn` | the node | references and three counters | The listen actor of a session node (registered): per accepted connection one `mtx` and one `msess`; counts open sessions for `session_slots_max`; holds the node's shutdown flag, which sessions ask for at each idle tick. |
| `msess` | a connection | scalars and references only (SD-35, SD-39) | The **receive actor** and the connection's state machine: phases 1 to 5 are N3's (fingerprint, gate, first frame, token), then `active`, `draining`, closed. Checks each frame, runs the guard, the permission gate and the type check, asks the supervisor to admit, counts `inflight` and `calls`, pauses and resumes reading, arms the age, idle and drain timers, sends `ok`, results and `goaway` through `mtx`, prints audit and telemetry lines. |
| `mtx` | a connection | two words | The **send actor**: encodes and frames typed values (N3's kinds plus `ok`, `goaway` and the two offer frames), hands them to the link; closes it last. |
| `tasm` (N3's) | one frame | the reassembly record | Unchanged. The next one is created **held** and released only when the session may take another request: this is the read pause. |
| `msup` (generated, `bees_trust_slots`) | a connection | `5 * max_inflight` integers | The **per-connection supervisor**: a table of the requests in work (the `req_id` as three words, a sequence number, flags). Refuses a duplicate `req_id`, starts one `twork` per admitted request, arms the call timer, receives the worker's answer and passes it to `msess`; after `msess` detaches (close, cancel) it drops results and ends when its last worker has answered. |
| `twork` (N3's) | one request | none | Unchanged: decode args, call, encode the result, answer, end (`fail_self` when the user code failed, D2). |
| `mmet` | the node | integer counters | The metrics of section 7; printed on request. |

Client side:

| Actor | Lives | Job |
| --- | --- | --- |
| `trust_mgr` (root unit, `src/shim/bees_trust_mux.part`, one per pinned server, registered) | the node | Routes a `trpc` request: to the open session if there is one; otherwise it opens a connection with this request as its first (offering a session); while that connection has no `ok` yet, further requests each go on their own connection (N3's `tcli`). It lives in the root unit because only the root unit may create a carrier. |
| `mcli` | a connection | The receive actor of a client connection: connect, token cache, the pipelined fingerprint (plaintext only), `hello` or `token_present` with the offer, then reads `token_issue`, `ok`, `result`, `goaway`. |
| `mpend` (generated) | a connection | The table of calls waiting for a result (`3 * max_inflight` words: who to answer, its number, a sequence number) and the session's request entry: allocates a `req_id` (the slot and a 7-byte sequence number, 8 bytes), hands the frame to `mtx`, answers the caller on result, timeout or close, sends a request it cannot take (full, or the session is ending) back to `trust_mgr`. |
| `mtx`, `tasm`, `tcache` | as above | |

Messages are tuples whose first element is `:bees`, as in N3. No message carries a heap value into a long-lived actor's state.

**Teardown order** (a cast to an ended actor ends the sender on this compiler; written so that it is also right when the cast
only returns false): `msess` ends only after its link said `:link_down` or was closed and 500 ms passed, after `msup`
acknowledged the detach (`msup`'s last cast to it), and after every answer it asked of a fingerprint actor or the listener
arrived. `msup` ends only after the detach and its last worker's answer. `mpend` ends only after `mcli`'s last message and
`trust_mgr`'s acknowledgement that it will route nothing more to it. Nothing casts to a link after its `:link_down`.

## 5. The server state machine

Phases 1 to 5 as N3 (same audit lines). Then, per connection:

- **Single** (no offer, or the node's limits are 1 and 1): one request, N3's timers (`first_frame_timeout_ms`,
  `call_timeout_ms`) and N3's closes. No `ok`, no `goaway`.
- **Session** (offer and limits above 1): `ok`; `active`:
  - a frame: structural check and decode; `call` or `cast` passes the forbidden guard, the permission gate, the MFA table, the
    type check of `args`; then `msup` admits it (or reports a duplicate, which is dropped and counted); `calls` and `inflight`
    rise. If `calls == max_calls`: GOAWAY `limit_reached`, `draining`. Else if `inflight == max_inflight`: **paused** (the next
    assembler stays held, the link gets no receive credit, nothing is decoded). Else the next frame is released.
  - a worker's answer: `inflight` falls; a call's value is sent as `result` and suspicion falls by one; a failure is audited
    `user_code_error` and raises suspicion by one, nothing is sent, **the session goes on** (PROVISIONAL, Q4); if paused, reading
    resumes.
  - a call older than `call_timeout_ms`: audited `timeout`, suspicion raised by one, its late result dropped
    (`late_result_dropped`), **the session goes on** and the slot stays taken until the worker ends (PROVISIONAL, Q4).
  - after every suspicion rise the fingerprint's actor is asked whether it is now quarantined; if so: GOAWAY `deny`, close.
  - a malformed frame, an oversize length, an unknown `t`, wrong `ver`, a bad `req_id`, `args` of the wrong type: audit
    `protocol_error`, suspicion, GOAWAY `protocol`, close at once. Forbidden MFA, permission denied, a function not in the
    program, an invalid token: audit as N3, suspicion, GOAWAY `deny`, close at once (PROVISIONAL, Q3).
  - `max_age_ms` reached, or no event for `idle_ms`: GOAWAY `limit_reached`, `draining`. The node's shutdown flag: GOAWAY
    `shutdown`, `draining`.
  - `draining`: frames are still read while not paused, **not decoded**, counted as refused (`draining`); results of requests
    in work are sent; closes when `inflight == 0` or after the effective drain. A framing error while draining closes at once.
  - the link goes down in `active` or `draining`: **cancel by close**. `msess` detaches from `msup`, results are dropped, no
    suspicion, telemetry `client_cancel` with the number in work. A worker that is already running is **not stopped**: Silica
    has no preemption (`remove_actor` acts at the next dispatch boundary, and a worker has one dispatch). Q6.

## 6. Backpressure and bounds

- **Where:** in `msess`, by not releasing the next `tasm`. One-at-a-time credit (D45) means the link reads only when an
  assembler asks for bytes, so a paused session holds no credit and the peer's bytes stay in the kernel's buffers and then in
  the peer. There is no queue of requests anywhere in the server: a request is in a worker or not yet read.
- **What a paused session holds:** the bytes that arrived in the same segment as the last frame (at most one carrier read,
  held undecoded in the waiting assembler) and nothing else.
- **Bounds on decoded values:** unchanged from N3 (`frame_size_max` at `unframe` before a byte of the body is stored;
  `args_len_max`, `term_depth_max`, 16 keys, `req_id` 1 to 16 bytes, token 32 to 64 bytes; atoms the program holds). New:
  `reason` an atom the program holds, `drain_ms` an integer 0 to 60000 (the option's bound; anything else is a protocol error
  on the client), `ok` has no payload.
- **Bounds on memory per session:** `max_inflight` workers and table rows (at most 64), one assembler, at most one frame of
  `frame_size_max` being assembled, results in the send actor's mailbox (at most `max_inflight`). Per node: `session_slots_max`
  sessions when set. The session's life is bounded by `max_age_ms` plus the drain.
- **Client:** `max_inflight` waiting calls per session; a request beyond that opens its own connection (no queue).
- **Known cost (SD-35):** `tasm` and, over TLS, the link worker `ttls` take the whole-state copy; `tasm` lives one frame, but
  `ttls` now lives as long as a session. Its growth per dispatch is measured in the soak (section 11).

## 7. Telemetry and metrics

BEES has no `bees_telemetry` yet (D24), so events are lines on standard output, one `println` each, written by `msess`:
`[trust telemetry] <event> key=value ... conn=<id>`. Events: `session.start` (client_id: the first 16 hex digits of the
fingerprint; `peer_ip` and `sni` are not known to the carrier's owner and are not printed), `session.end` (reason, age_ms,
calls_total, inflight_peak, refused, duplicates), `goaway` (reason, drain_ms, inflight), `request.accept` (type, req_id in hex),
`request.refuse` (reason `draining`, `duplicate`, `malformed`; `max_inflight` never occurs, because reading stops before the
next request is taken), `request.finish` (req_id, outcome, duration_ms), `pause`, `resume` (paused_ms), `worker.crash` (req_id,
class `error`, reason), `client_cancel` (inflight_at_cancel). Arguments and tokens are never printed. A node whose limits are 1
and 1 prints none of them.

Metrics: `mmet` holds M's counters (sessions started and ended by reason, goaway by reason, requests by type and outcome,
refused by reason, duplicates, client cancels, worker crashes, protocol closes, resumes), the gauge `trust_sessions_active`, and
count and sum for the three histograms (no buckets, Q10). `trust_metrics_dump()` prints them as `[trust metrics] name value`.
`trust_inflight_requests{conn}` is the `inflight` field of the events.

Trials replace wall-clock values (`age_ms`, `duration_ms`, `paused_ms`, the histogram sums) with `N` before comparing.

## 8. Failure handling

| Failure | Server | Client |
| --- | --- | --- |
| Refusal before or in the first frame (unknown fingerprint, quarantine, garbage, timeout, a request before the token step) | N3's silent close, audit, suspicion | `closed` |
| Refusal on a session | audit, suspicion, GOAWAY `deny` or `protocol`, close at once, results in work dropped | every waiting call `closed`; the cached token is forgotten; the next request opens a new connection |
| User code fails | audit, suspicion, no frame, session goes on | that call ends in `timeout` (its own `call_timeout_ms`) |
| Window ends (`limit_reached`, `shutdown`) | GOAWAY, drain, close | requests not yet written go to a new session; written calls wait for their result until the close, then `closed` (never re-sent: Q5) |
| Peer closes | cancel by close | waiting calls `closed` |
| Server killed | | waiting calls `closed` |
| A result nobody waits for, a duplicate `req_id` | duplicate dropped and counted | result dropped and counted |
| Unknown frame type on the client | | the session is closed, waiting calls `protocol_error` |
| A worker that faults outright and never answers | its slot stays taken until the session ends; `msup` stays (one small actor), as N3's connection actor does today | `timeout` |
| A write to a peer that has just closed (SD-43's residual) | as in N3: the send actor can end with `actor_not_found` on this compiler if the carrier ended between the close and the cast; the window is wider in a session because results are written while the link holds a read credit | |

## 9. Questions (Q1 to Q13 ruled 2026-11-18; Q14 and Q15 open; the table is the record of the options and of what was provisional)

Q15 (OPEN, 2026-11-19). On the 2-core Linux box a CPU-busy request stops the whole server (SD-47; 11.2b). Four properties are
then shown only on the Mac: answers out of order, duplicate detection while a request is in work, a cancel while a call is in
work, and the read pause and resume.

Options:
- (a) Per-platform goldens. Linux records what it does (in order, no pause); this note says which property each platform proves.
- (b) The 12 outputs run only where the machine has at least 4 cores; on Linux they are reported as skipped, not passed.
- (c) Make the in-work requests not CPU-bound. That needs a sleep, a yield or preemption from Silica (asked under SD-47); until
  Silica has one, this means (a) or (b).
- (d) A BEES change: spawn request workers from one long-lived actor instead of each connection's supervisor, in the hope that the
  runtime places them away from the session's actors. This rests on a guess about the runtime's placement and is not built.

Recommendation: (a) now plus (c) asked of Silica. Linux then still checks that sessions answer every call correctly when the server is serialised; the
properties stay proven on the Mac; and the gap is written down instead of hidden. The two varying outputs (`shutdown.a`, TLS
`protocol`) still need their ordering race post-processed or the step moved out of the busy window under (a). Built
provisionally: nothing; no Linux golden recorded for the 12.


| # | Question | Options | Provisional | Recommendation |
| --- | --- | --- | --- | --- |
| Q1 | Does a node without a `session` key multiplex? | (a) no: B1 unless `session` is written; (b) yes, with M's defaults 8/100 (what bees-config-file.md 5.3 says) | (a), because (b) changes every existing golden and the task forbids that | (b) once the existing TRUST goldens may be re-recorded; until then (a) and say so in bees-config-file.md |
| Q2 | How do peers agree on a session, and what is M's `OK`? | (a) offer key `opts => #{goaway => 1}` in the first frame and an `ok` frame back; (b) the server always sends `OK` (breaks B1 clients); (c) the client learns it from configuration per server; (d) a new ALPN `trust/2` | (a) | (a), or (d) if the owner wants the versions separated at TLS; (a) needs no new atom on a B1 node |
| Q3 | Which refusal is `deny` and which `protocol`? | as section 5; or everything `protocol` except permission | section 5 | section 5 |
| Q4 | Does a failed or timed-out request end the session? | (a) no: suspicion and audit only, as M's table implies; (b) yes, GOAWAY `deny`; (c) yes, silent close as B1 | (a), and the session ends anyway once the fingerprint is quarantined | (a) |
| Q5 | Which requests did the server take when a GOAWAY crossed them? | (a) the client cannot know: unanswered calls end `closed` and are never re-sent; (b) GOAWAY carries the number of request frames taken, so the client re-sends the rest; (c) `ok` carries `max_calls` so a client never overruns the count | (a) | (b) and (c) together, as an addition to the frame the owner approves |
| Q6 | What is "kill workers" without preemption? | (a) drop results, let the worker finish; (b) ask Silica for a preempting stop | (a) | (b) as a Silica request; (a) until then |
| Q7 | Are frames read while draining? | (a) read and discard undecoded, count refused; (b) stop reading | (a) | (a): it also lets a client close be seen |
| Q8 | What does `session_slots_max` refuse with? | (a) close before reading; (b) read the first frame, then GOAWAY `limit_reached` to an offering client | (a) | (b) later; (a) costs an attacker nothing to trigger but also gives nothing away |
| Q9 | `acceptors` | (a) validate and ignore; (b) several listening carriers | (a) | (a) until the carrier offers more than one accepting actor |
| Q10 | Histogram buckets | (a) count and sum; (b) fixed buckets | (a) | leave buckets to the telemetry backend (D24) |
| Q11 | The per-connection supervisor is a plain behaviour, not Silica's `Supervisor` | (a) plain behaviour with a slot table; (b) `Supervisor` with `:temporary` children | (a): a `Supervisor` needs a registered name and one child id atom per live child, both from fixed atom tables, per connection | (b) when Silica has unnamed dynamic supervisors; then a worker that faults is seen (today it is seen only as a timeout) |
| Q12 | Reconnect backoff and jitter (M: base 100 to 500 ms, cap 5 s) | (a) none: a session is opened only when a request needs one; (b) a backoff state per server | (a) | (b) when a client keeps sessions open ahead of demand |
| Q13 | No `trpc` function cancels a session (M has none either) | (a) none; (b) `trpc_close(addr)` | (a) | ask the owner |
| Q14 (OPEN, 2026-11-19) | With the default on, how does a node ask for N3's actors (no session units at all), and how do the N5 B1 scenarios keep a B1 node? | (a) none: `{session, #{max_inflight => 1, max_calls => 1}}` is the only spelling and runs the session actors with limits 1 (behaviour and output equal N3's, `compat`); (b) a value `{session, none}` that builds the node without session units (N3's actors, smaller build); (c) (b) as a build-time option outside `bees.config` | (a) is what is built; nothing new was added | (b): a constrained device or an operator who wants the smaller audited path can ask for it in the one file, and the N5 `b1client`/`b1server` scenarios keep testing B1 after the flip |

### Rulings on these questions

RULED 2026-11-18 (owner), relayed by the coordinator while the code was being written. The table above is kept as the record
of the options.

- RULED 2026-11-18 (owner), Q1: **yes, (b).** A node without a `session` key multiplexes, with the defaults of
  bees-config-file.md 5.3 (`max_inflight` 8, `max_calls` 100). This is the target behaviour. It is implemented and sits behind
  one switch, `SESSION_DEFAULT_ON` in `tools/bees_conf.py`, which is still `False` in the tree, because turning it on changes the
  goldens of the existing TRUST trials, which other work is using as "must pass unchanged" checks. Section 12 lists what changes
  and the commands. A node is kept at one request per connection by the setting the multiplexing design already has (R-6):
  `{session, #{max_inflight => 1, max_calls => 1}}`.
- RULED 2026-11-18 (owner), Q5: **(a) stays.** The owner's words: "to say yes seems to open a security vulnerability". So
  `goaway` does not carry the number of requests taken and `ok` does not carry `max_calls`: a server tells a peer nothing about
  its limits or about what it has and has not read. Unanswered calls end `closed` and are never sent again. (b) and (c) are not
  built.
- RULED 2026-11-18 (owner), Q13: **yes, (b).** `trpc_close(addr)` is built (section 4a) and trialled (`cancel`).
- RULED 2026-11-18 (owner), Q2, Q3, Q4, Q6, Q7, Q8, Q9, Q10, Q11, Q12: the provisional choice is accepted; they are no longer
  provisional.

### 4a. `trpc_close(addr)` (Q13)

`trpc_close(addr) -> atom`, beside `trpc_call` and `trpc_cast` (same address form, `"host:port"` of a pinned server). It closes
the open session to that server, if there is one, and returns at once; no answer message is sent to anyone.

- The session's send actor closes the connection after the frames it already holds.
- Every call of this node waiting for a result on that session is answered `closed` immediately. None is sent again.
- A cast already handed to the session was answered `cast` when it was written; whether the server ran it is not known (as
  always for a cast).
- The server sees a client close: cancel by close. Results of requests in work are dropped, no suspicion is raised, and a
  worker that is running finishes on its own (Q6).
- A request made after `trpc_close` opens a new connection. The cached token of that server is forgotten by the close (the
  connection actor cannot tell this close from a server's), so that connection starts with `hello`.
- With no acknowledged session to that server (none open, or a connection whose `ok` has not arrived yet), an address that is
  not pinned, or on a node whose limits are 1 and 1, it does nothing.


RULED 2026-11-19 (owner): Q14 option (b): `{session, none}` builds a TRUST node without the session units, using N3's one-request-per-connection actors. To be built; once the default-on switch is flipped, trials and nodes that need a true one-request node use `{session, none}`.

## 10. Trial plan

`trials/n5_trust_mux` (plaintext, as N3) and `trials/n5_trust_mux_tls` (mutual TLS 1.3, as N4); ports 23000 and 23100 blocks.

| Scenario | Shows |
| --- | --- |
| `compat` | a node with `session` 1 and 1 runs N3's scenario and negative suites; outputs equal N3's goldens after the port numbers are replaced (criterion 9) |
| `interleave` | one connection, a slow call then fast calls and a cast; results come back out of order and each caller gets its own (criterion 1); telemetry lines (criterion 8) |
| `window` | `max_calls` reached: one GOAWAY `limit_reached`, results in work still delivered, close, the next request on a new session (criterion 2); idle and age limits |
| `pause` | `max_inflight` 2, two slow calls, then a raw peer writes several MiB of requests: `pause`, nothing admitted, the server's resident set sampled before and during the pause (criterion 3), `resume` when a worker ends |
| `goaways` | `shutdown` (operator), `deny` (forbidden, permission), `protocol` (malformed, oversize mid-session), suspicion per request, quarantine mid-session (criteria 5, 6; R-7) |
| `cancel` | a raw peer closes with a slow call in work: `client_cancel`, no suspicion, no result (criterion 4) |
| `mixed` | a B1 client against the B2 node and a B2 client against a B1 node (R-6) |
| `measure` (not in integrate) | calls per second and resident set growth per call on one-session-per-`max_calls` against N3's one connection per call (criterion 10) |

## 11. Results (2026-11-18, macOS on Apple Silicon, `silica-999909`)

### 11.1 What was built

| Piece | Where |
| --- | --- |
| the frames and frame parts sessions add (`ok`, `goaway`, the offer), pure | `src/trust/bees_trust_mux_frame.silica`, atoms `src/trust/bees_trust_mux.atoms` |
| `mlsn`, `msess`, `mtx`, `mcli` | `src/trust/dangerous_bees_trust_mux.silica.in`, expanded into a session node's `lib/` |
| `msup`, `mpend`, `mmet` (tables sized by `max_inflight`) | generated `bees_trust_slots` (`tools/bees_trust_mux_gen.py`) |
| the session manager `trust_mgr`, `trpc_close`, `trust_shutdown`, `trust_metrics_dump` | `src/shim/bees_trust_mux.part` |
| when a node multiplexes; the `session_*` values; the summary line | `tools/bees_conf.py` (`session_set`, `SESSION_DEFAULT_ON`), `tools/bees_config_trust.py` |
| the generators' hook | `tools/bees_trust_gen.py` (`mfa` writes or removes the session units; `edge` pastes the part) |
| the harness | `tools/run_trust_pair.py` (`--settle`, `--rss`) |
| unit tests | `tools/test_bees_trust_mux.py` (17 tests) |

Not touched: `src/trust/dangerous_bees_trust.silica`, `bees_trust_frame.silica`, `bees_trust_work.silica`, every TLS file, every
existing trial and golden. A node without sessions is built from exactly the units and the root unit it had (a unit test
compares the root unit text). The TLS link needed no change: `msess` and `mcli` speak the carrier contract, as N3's actors do.

Differences from the plan of section 4, found while building:

- `msup` does not raise suspicion after a detach (section 4 said it would): after a close every later result is dropped
  silently, as the multiplexing design's cancel says. A peer could send a failing request and close at once to avoid the
  suspicion rise; the owner may want that closed (it needs the supervisor to know the fingerprint).
- Each actor prints every line of an event before it tells the fingerprint's actor, and the metrics are printed by their own
  actor: two actors printing at once can mix their lines (silica-defects SD-49).
- `request.refuse reason=draining` is printed once per session (the first such frame); every frame is counted.
- The pending table (`mpend`), not the connection actor, ends a client connection's send actor, so that no request is ever
  handed to a send actor that has ended.

### 11.2 Trials and what each shows

`trials/n5_trust_mux` (plaintext, 13 scenarios, 26 goldens and 4 comparisons with N3's goldens) and
`trials/n5_trust_mux_tls` (mutual TLS 1.3, 6 scenarios, 12 goldens). Both passed five runs in a row (26 of 26 and 12 of 12 each
time), the plaintext runs partly with a load average above 40 from other work. Re-run 2026-11-19 on the final sources (the
F1-3 fix and the client's own window were made after those runs): five in a row again, 30 of 30 (with the two `hostile`
scenarios) and 12 of 12, load average 10 to 30. "Observed" is in a golden; "inferred" is not.

| Scenario | Observed | Inferred or not shown |
| --- | --- | --- |
| `interleave` (both trials) | one connection (one `session.start`, connection id 0 throughout); a 600 ms call, a quick call, a cast and a binary call handed over at once; answers arrive as 3, 4, 5, 2 and each caller gets its own value; `pause` and `resume` at `max_inflight` 2; the metrics | that the answers were matched by `req_id` and not by order follows from the order being different and the values being right |
| `window` | five calls on one session, at the fifth ONE `goaway limit_reached` with `inflight=1`, that call still answered, `session.end`, the sixth call on a new connection (fast-path token); a session ended by `idle_ms` (900 ms of silence against 600); a session ended by `max_age_ms` (four calls 400 ms apart, the next call lands on a new connection); a second connection refused while one is open (`session_slots_full`, 0 bytes back); the boot note for `acceptors` | whether it was age or idle that ended the third session is known from the timing (a call every 400 ms against `idle_ms` 600), not from the line: both say `limit_reached` |
| `pause` | two slow calls admitted, `pause inflight=2`, nothing else admitted for 1.2 s although about 6 MiB of requests had been written by the peer; the server's resident set 3536 KiB at the pause and 3552 KiB one second later (a first run; the golden says "within 1024 KiB"); `resume` when the first call ends; the next request (a cast) admitted, pause and resume again; then the first of 65536 forbidden requests: `goaway deny` | that the unread megabytes sat in the kernel and in the peer is inferred from the flat resident set and from the fact that no line was printed for them; the peer's side of the reset connection is not compared |
| `deny` (both) | forbidden MFA and permission denied on a session: audit, `goaway deny`, `session.end reason=deny`, the caller sees `closed`, suspicion 1 then 2; a permitted call lowers it; a call whose user code fails gets no frame (the caller's own timeout: `timeout`), suspicion rises, and the session goes on (the next requests use the same connection id); two failing casts take suspicion above the limit: `quarantined`, `session closed`, `goaway deny`; the next connection is refused at the gate | |
| `protocol` (both) | a duplicate `req_id` in work: dropped, `request.refuse reason=duplicate`, counted in `session.end` and the metrics, the other requests answered; a malformed map mid-session and an oversize length mid-session: `protocol_error`, `goaway protocol`, closed at once (175 bytes back: `token_issue`, `ok`, `goaway`); an invalid token with the offer: `token_reject`, `goaway deny` and nothing else (54 bytes) | that the 54 bytes are a goaway frame is inferred from its size and from the server's line; the raw peer counts bytes, it does not decode |
| `shutdown` | a call in work when the node is told to shut down: `goaway shutdown` with `inflight=1`, the call's result delivered, `session.end reason=shutdown`; a call after it: `closed`, and the server's `shutdown ... closed before reading` | the shutdown is asked by a demo function that sends the listener the message `trust_shutdown()` sends; `trust_shutdown()` itself is compiled and not called |
| `cancel` (both) | a raw peer closes 300 ms into a 1500 ms call: `client_cancel inflight_at_cancel=1`, `session.end reason=client_cancel`, no suspicion line, no result written; `trpc_close` does the same from the program and its waiting call is answered `closed`; the next call opens a new connection | that the abandoned worker ran to its end is inferred (nothing is printed for it): Silica cannot stop it |
| `b1client` (both) | N3's (N4's) scenario program, built without sessions, against the session server: four connections, one request each, no `ok`, no `goaway`; the client's output is N3's | |
| `b1server` (both) | the session client against a server built without sessions: six requests, six connections, all answered; the server prints N3's lines | that the client wrote nothing behind its first request is by construction (section 2), not observed on the wire |
| `compat_scenario`, `compat_negative` | nodes built with `session` 1 and 1 run N3's two programs on the session actors; all four outputs equal N3's goldens after the port numbers are replaced (the Makefile's `compat_same`) | |
| `hostile_b1`, `hostile_session` (added 2026-11-19, F1-3) | a hostile server (`trials/n5_trust_mux/hostile_server.py`, a Python script on node s's address) answers 18 calls one after another: calls 1 to 12 and 14 to 17 with answers a correct client refuses, each followed at once by more bytes (a `token_issue` whose token is an atom, the fuzzer's seed 1 case 5; a result where the `token_issue` must be; a good `token_issue` then a length above `frame_size_max`; a frame that is not a map), calls 13 and 18 rightly. The B1 client (node d, `tcli`) and the session client (node c, `mcli`, which offers a session each time) print `{error, protocol_error}` for each refused answer, `{ok, int 113}` and `{ok, int 118}` for the right ones, and no actor failure report; the server's lines show the client said `hello` every time except after the good answer (call 14: `token_present`) | that the trial catches the defect is observed for `tcli` only: with the file's state before the fix (git HEAD) in a scratch copy, node d's client printed 16, 16 and 22 `actor_not_found` failure reports of `dangerous_bees_trust_tcli` in three runs (the outcomes were the same); the pre-fix `mcli` no longer exists, so for it the case is a regression check |

Not trialled: `max_inflight` 64 in a run (a 64-row node compiles, 4 min 8 s against about 1 min, and only `carrier` and `tasm`
are reported W2300); a hard fault of user code in a session; a server killed in the middle of a session (N3's `kill` covers
the one-request case); two machines; Linux.

### 11.2a Two changes made after the first measurements

- **The client's own window.** With several calls outstanding, the calls written behind the last request of a window ended
  `closed` (never re-sent, Q5): 7 of 2,000 with 8 outstanding and 3 of 2,000 with 4 outstanding at one `max_calls` boundary,
  53 and 23 of 20,000 (first soak run). The pending table now stops putting requests on a session after the client's own
  `session.max_calls` (the next request opens a new connection). The server tells the client nothing; the number is the
  client's configuration, so an operator who gives both ends the same `max_calls` loses none at that boundary (observed after
  the change: 6,000 of 6,000 with 8 and with 4 outstanding). Calls written just before a goaway for age, idle or shutdown can
  still end `closed`.
- **F1-3 (the fuzzer's finding in N3's client, `tcli`), fixed here because the session client had the same shape.** A hostile
  server could end the client's connection actor with `actor_not_found`: the assembler for the next frame was let go before
  the current frame was judged, could end itself on the bytes that followed, and was then told to stop (a cast to an ended
  actor ends the sender); a framing refusal did the same (the assembler that reported it had ended). Now the next assembler is
  created held and let go only after the frame was accepted, and a refusing assembler is not told to stop, in
  `dangerous_bees_trust@tcli` and in `mcli`. Checked with the fuzzer in a scratch copy of the tree: `python3
  tools/bees_fuzz.py replay --seed 1 --surface trust_client --case 5 --repeat 20` gave a finding in 15 of 20 before and 0 of 20
  after; case 9: 0 of 20; `run --seed 5 --cases 300 --surfaces trust_client`: 0 findings (80 of 300 in the fuzzer's run). The
  fuzzer has no surface for the session client: for `mcli` the fix is by the same construction, not by a run. Re-checked
  2026-11-19 on a freshly built node `tc` (scratch copy): case 5 and case 9, 0 of 20 each. The deterministic trial case is
  `hostile_b1` / `hostile_session` (11.2): before the fix it gave 16 to 22 `actor_not_found` reports per run, after it none, in
  five runs of the whole trial. What is left of
  this family in both clients and in the server: an assembler that has just handed over a frame and ended, while its owner
  handles a timer or a `:link_down` that was ahead of that frame in its mailbox, is still told to stop (the window is one
  message long; it closes when a cast to an ended actor returns false, which newer compilers do).

### 11.2b Linux (2 cores, `silica-999944-linux-x86_64`), 2026-11-19: open

The coordinator's first Linux run: 25 outputs equal the Mac's (their Linux goldens are recorded), 13 differ (plaintext `cancel.a`,
`interleave.a/b`, `pause.a/b`, `protocol.a/b`, `shutdown.a`; TLS `cancel.a`, `interleave.a/b`, `protocol.a/b`).

- `pause.b` ended in `[silica] fault ... exit=70`. That is the CLIENT, the trial's raw peer: the server's output shows no connection
  at all (no `token_issued`, no `session.start`), so BEES's server backpressure path was not reached and nothing there buffers
  the unread requests. The raw peer built the 6 MiB as one string, held it in its state and handed it to the send actor in one
  message. It now writes the same bytes as a head and 16 pieces of about 380 KiB (`roles/client_pause.role`, `praw`); the Mac
  goldens are unchanged (three runs and a full integrate). Which stage faulted on Linux is being measured with
  `nodes/c/dangerous_c_bigprobe` (a diagnostic with no golden: building the string, an actor holding it, a cast of it, the raw peer).
  If one of those stages faults on Linux and not on the Mac, it is a Silica defect and gets an SD entry with the probe as reproduction.
- The other 12 differ in one consistent way: while a CPU-busy `demo:slow` worker runs, the server's session actors on Linux do
  nothing until it ends. The quick calls of `interleave` are read after the slow one finished (in order, no pause), the duplicate
  `req_id` of `protocol` is not a duplicate (the first finished before the second was read), the client close of `cancel` is
  seen after the result, and the `pause` and `resume` lines vanish. That is SD-47 at its strongest, on a 2-core box. Silica has no
  sleep and no yield, so `slow` has to burn CPU.

Measured on Linux (coordinator, `scratchpad/n5_diag.out`):

- The probe faults at stage 1 (building the 6 MiB string in `main` with `doubled`, 16 calls deep, each joining two strings with
  `join_bytes`): `[silica] fault ... addr=0x00007ffd00610140 actor=0`, which is the main thread on the 8 MiB process stack. The
  recursion is 16 calls deep, so the depth cannot explain it. Inferred: the joins use stack in proportion to their size on that
  thread (the SD-59 family: Linux `main` runs on the 8 MiB process stack). With the pieces fix, `pause.b` on Linux is
  byte-identical to the Mac golden. `pause.a` differs from line 8 on (the pause lines, see below).
- Timed runs, three each of `interleave` and `cancel`: identical to the millisecond. In `interleave` the server admits the 600 ms
  call at 0.03 s and does nothing else until 0.63 s, when that call finishes; then it takes the other requests at once. A busy
  worker stops the whole server for as long as it runs.
- Repeat runs: every output of both trials is stable on Linux except `shutdown.a` (plaintext) and `protocol.a` and `protocol.b`
  (TLS).

Classification of the 13:

| Output | Linux | What the Mac golden shows that Linux cannot |
| --- | --- | --- |
| `pause.b` | equal to the Mac after the pieces fix | nothing |
| `interleave.a/b` (both trials) | stable, in order, no pause/resume | answers out of order; the read pause at `max_inflight` |
| `pause.a` | stable, from line 8 on | the read pause and resume while two slow calls are in work (the 6 MiB stays unread either way) |
| `protocol.a/b` (plaintext) | stable | a duplicate `req_id` refused while the first is in work |
| `protocol.a/b` (TLS) | varies | same; the order varies besides |
| `cancel.a` (both) | stable | a client close seen while a call is in work (`client_cancel`) |
| `shutdown.a` | varies | `goaway shutdown` with a call in work (`inflight=1`) |

Each property in the last column needs a request in work while the server goes on reading. On this Linux box a request in work
stops the server, so the scenario cannot show the property there, whatever its timing. This is owner question Q15 (section 9).
Until it is ruled, no Linux golden is recorded for these 12.

### 11.3 The soak (`make measure`)

Run 2026-11-19 on the final sources (macOS, Apple Silicon, `silica-999909`, load average 6 to 15 from other work), one pair at a
time; not part of `integrate`. Each row is one run of each count; "growth per call" is the difference of the peak resident set
(`/usr/bin/time -l`) between two counts divided by the difference in calls (server / client). Commands:
`make -C trials/n5_trust_mux measure CALLS_LIST="2000 6000" SILICA_COMPILER=...`, the same with `CALLS_LIST=20000` and the two
session pairs `sessions_seq`, `sessions_win`, and `make -C trials/n5_trust_mux_tls measure SILICA_COMPILER=...`. Raw lines:
`trials/n5_trust_mux/measure.txt` (all three runs) and `trials/n5_trust_mux_tls/measure.txt`.

Plaintext (`n5_trust_mux`; sessions: server `r`, `max_calls` 1000, `max_inflight` 8; baseline: the B1 server `b`, one connection per
call):

| Pair | Calls per second (2000 / 6000 / 20000) | Growth per call, KiB, 2000 to 6000 (server / client) | 6000 to 20000 | All answered |
| --- | --- | --- | --- | --- |
| sessions, 1 outstanding | 724 / 825 / 324 | 0.20 / 0.27 | 0.20 / 0.11 | yes (20,000 of 20,000) |
| sessions, 4 outstanding | 184 / 185 / - | 0.21 / 0.21 | - | yes |
| sessions, 8 outstanding (read pause at every request) | 318 / 362 / 320 | 0.23 / 0.24 | 0.20 / 0.18 | yes (20,000 of 20,000) |
| baseline, 1 connection per call, 1 at a time | 239 / 348 / - | 1.13 / 0.95 | - | yes |
| baseline, 8 connections at a time | 532 / 496 / - | 0.83 / 0.71 | - | yes |

Read against `development-plan/silica-defects.md` (SD-46: N3 0.83 / 0.62 KiB per call on this compiler, about 0.5 KiB of it the
residue of each ended carrier): the baseline here is the same order (0.83 to 1.13 / 0.71 to 0.95). A session carries 1000 calls
on one carrier, so the carrier residue all but goes, and the growth falls to about 0.2 KiB per call on each side, four to five
times less. What the remaining 0.2 KiB per call is was not examined (inferred candidates: the per-frame assembler `tasm`, spawned
for every frame, and the request worker; plain actors were measured at a few bytes each in SD-46, so it is more likely the
dangerous spawns). One call at a time on a session is 2.4 to 3 times the baseline's rate (no connect, no token step). The 20,000
row of `sessions_seq` (324 per second) was slower than the 6,000 row (825) while the load rose; it is not a property of the count
(latencies stayed under 2 ms for 17,022 of the calls).

Mutual TLS 1.3 (`n5_trust_mux_tls`, same servers over TLS; 2000 and 6000 calls):

| Pair | Calls per second (2000 / 6000) | Growth per call, KiB, 2000 to 6000 (server / client) | All answered |
| --- | --- | --- | --- |
| sessions, 1 outstanding | 742 / 771 | 0.47 / 0.53 | yes |
| sessions, 4 outstanding | 174 / 174 | 0.54 / 0.37 | yes |
| sessions, 8 outstanding | 325 / 322 | 0.96 / 1.12 | yes |
| baseline, 1 TLS connection per call, 1 at a time | 169 / 181 | 6.77 / 6.50 | yes |
| baseline, 8 connections at a time | 354 / 327 | 6.80 / 6.60 | yes |

Over TLS a connection per call costs about 6.6 to 6.8 KiB of resident set per call on each side (peak 52 MiB after 6,000 calls),
far above SD-46's 0.5 KiB per plaintext carrier; the previous agent's run on 2026-11-18 gave the same (24 to 51 MiB). That
residue per TLS connection is not attributed (the engine's session objects, the link worker `ttls`, or the carrier) and has no
SD entry yet; with sessions it falls to 0.5 to 1.1 KiB per call, and one call at a time on a session is 4.3 times the baseline's
rate (no handshake per call).

Several calls outstanding on one session are slower than one at a time: with 4 or 8 outstanding almost every call took 20 to
50 ms (`<50` bucket: 5,458 of 6,000 and 5,909 of 6,000), against under 2 ms one at a time. The carrier sets `TCP_NODELAY`
(`silica_sockets.c`), so it is not Nagle against delayed acknowledgement; where the 20 to 50 ms goes (the read credit of one frame
at a time, the per-frame assembler, the client's pending table, or the scheduler, SD-47) was not examined. It does not lose
calls (every call was answered) and it is the same with the read pause (8) and without it (4). Until it is understood,
windowing gives no throughput gain over one call at a time on this compiler; it should be looked at before the default is turned
on for workloads that issue calls concurrently.

## 12. The default (Q1): what changes when `SESSION_DEFAULT_ON` becomes `True`

The ruling: a node without a `session` key multiplexes with `max_inflight` 8 and `max_calls` 100. The code is in place; the
switch is one line, `SESSION_DEFAULT_ON = False` in `tools/bees_conf.py`. Nothing else needs to change: the node Makefiles
of the existing trials already call `bees_trust_gen.py mfa --config`, which writes the session units when the reader says
the node multiplexes, and `edge` pastes the session part.

Checked on 2026-11-18 in a scratch copy of the tree with the switch on (N3's and N4's server and client nodes rebuilt, their
`scenario` and `negative` pairs and N3's `kill` run; ports moved into this trial's block; goldens untouched):

| Golden | Lines in the golden, with the switch on | What changes |
| --- | --- | --- |
| `n3_trust` `scenario.a` | 14, 21 | the summary line ends `sessions (B2): max_inflight 8, max_calls 100, ...`; ONE connection carries the four requests, so the three `token_accepted` lines go and every `admitted` line ends in connection id 0; telemetry lines are added (`session.start`, `request.accept`, `request.finish`, `session.end`) |
| `n3_trust` `scenario.b`, `kill.b` | 9, 9 and 7, 7 | only the summary line |
| `n3_trust` `negative.a` | 51, 76 | summary line; telemetry lines; connection ids shift (requests share sessions); refusals on a session add `goaway deny`; the quarantine arrives in the middle of a session (`quarantined ... session closed`); `late_result_dropped` goes (the session was closed first) |
| `n3_trust` `negative.b` | 21, 21 | summary line; step 13 (user code fails) is `{error, timeout}` instead of `{error, closed}`: a failed request no longer closes the connection (Q4) |
| `n4_trust_tls` `scenario.a`, `scenario.b` | 18, 21 and 13, 10 | as N3's, and three fewer `tls_established` lines on each side (one handshake instead of four); the number at the end of the client's `tls_established` line is the server's index, not the request's |
| `n4_trust_tls` `negative.a`, `negative.b` | 65, 87 and 35, 32 | as N3's, with fewer handshakes; step 13 `timeout` |

So the change is not only added lines: lines go, ids change, and one result changes. Not run, by reading: `n3_trust`
`boot_missing`, `boot_unreadable` (a refused boot prints no summary: unchanged); `n3_trust_frames` (in memory: unchanged);
`n4_trust_tls` `selftest` (unchanged), `kill.b`, `pin.a`, `pin.b`, `noca.a`, `noca.b`, `refusals.a` (the summary line at
least; `noca` also gains session lines); `x2_interchange_trust`, every golden (TRUST nodes on two machines: the summary line
and session lines); `t5_tempus_tls` (an engine selftest: unchanged). The timing of N3's negative suite (steps 150 ms apart,
the operator reset at 9 s) was written for one request per connection and held in the one scratch run; it needs the usual
three runs after the flip.

To flip, on each platform, when the other work is done:

```
# 1. tools/bees_conf.py: SESSION_DEFAULT_ON = True   (and tools/test_bees_trust_mux.py test_the_switch_is_off_in_the_tree)
# 2. re-record, Mac and Linux:
make -C trials/n3_trust record-golden SILICA_COMPILER=<the pinned compiler>
make -C trials/n4_trust_tls record-golden SILICA_COMPILER=<the pinned compiler>
python3 tools/bees_interchange.py ...        # x2_interchange_trust, as that trial's own instructions say
# 3. read the diffs against this section, then run each three times
```

The generated session units appear in those trials' `lib/` directories (`bees_trust_slots.silica`,
`dangerous_bees_trust_mux.silica`, and the links `bees_trust_mux_frame.silica`, `bees_trust_mux.atoms`): `.gitignore` needs the
four names for `trials/n3_trust`, `trials/n4_trust_tls` and `trials/x2_interchange_trust`, as it has them for the N5 trials.
A trial that must stay at one request per connection writes `{session, #{max_inflight => 1, max_calls => 1}}` (it then runs
the session actors with limits 1, whose output is N3's, section 11.2 `compat`).

### 12.1 Re-checked 2026-11-19 (scratch copy of the tree, switch on, final sources; ports moved to private blocks)

Every leaf that builds a TRUST node from a `bees.config` was found by searching the trials for the TRUST generators:
`n3_trust`, `n4_trust_tls`, `x2_interchange_trust`, `f1_fuzz_wire`, `f2_fuzz_long` (not in integrate), `d2_store_config`, and the
N5 trials (whose nodes write `session`, or leave it out on purpose: nodes b and d of `n5_trust_mux`, which would multiplex too).
No TEMPUS trial (`t*`, `c2_*`) builds a TRUST node; `t5_tempus_tls` is an engine selftest.

| Leaf | Run? | Goldens that change (Mac; each has a Linux twin that changes the same way) | How |
| --- | --- | --- | --- |
| `n3_trust` | run (integrate: 2 pass, 5 differ) | `scenario.a`, `scenario.b`, `negative.a`, `negative.b`, `kill.b` | not only added lines: `scenario.a` 14 to 21 lines (three `token_accepted` lines go, telemetry lines come, every connection id becomes 0); `negative.a` 51 to 81 (17 lines go, 47 come: telemetry, `goaway deny`, a quarantine in the middle of a session, connection ids shift, `late_result_dropped` goes); `negative.b` step 13 `{error, closed}` becomes `{error, timeout}` (Q4) and, in one run of two, step 15 ("while quarantined") `{ok, int 3}` (see below); `scenario.b` and `kill.b` only the summary line. `boot_missing`, `boot_unreadable` unchanged |
| `n4_trust_tls` | run (1 passes, 10 differ) | `scenario.a`, `scenario.b`, `negative.a`, `negative.b`, `kill.b`, `noca.a`, `noca.b`, `pin.a`, `pin.b`, `refusals.a` | as N3, plus fewer handshakes: `scenario.b` 13 to 10 lines (three `tls_established` go; the client's index becomes 0), `noca.b` and `pin.b` the client index 1 becomes 0, `noca.a` gains three telemetry lines, `pin.a`, `refusals.a`, `kill.b` only the summary line; `negative.b` step 13 `timeout` and step 15 `{ok, int 3}`; `selftest` unchanged |
| `x2_interchange_trust` | not run (two machines, ssh) | all 12 (6 Mac, 6 Linux) | by reading: each carries the line `one request per connection (B1)` (none of its nodes writes `session`); the `*_calls` pairs will also change as N4's `scenario` does; `*_wrong_pin` as `pin`; `*_unlisted` at least the summary line |
| `f1_fuzz_wire` | run (passes) | none | observed: its TRUST nodes were rebuilt as session nodes and the smoke golden (case outcomes only) is unchanged |
| `d2_store_config` | run (passes) | none | the packer always carries the session values; the switch is read only by the bees.config reader of a node build |
| `n5_trust_mux`, `n5_trust_mux_tls` | not run | `b1client.*`, `b1server.*`, `hostile_b1.*` of the plaintext trial and `b1client.*`, `b1server.*` of the TLS trial | by construction: nodes b and d exist to be B1 nodes and leave `session` out; with the switch on they would multiplex and those scenarios would no longer test B1. When flipping, give them a spelling that means "B1 actors" (owner question below) or drop the B1 scenarios |

Two things the flip needs besides re-recording, both found here:

- **Wall-clock values.** With sessions, N3's and N4's server outputs carry `age_ms=` and `duration_ms=` in telemetry lines. Their
  Makefiles do not mask them (N5's `CLEAN_OUT` does): the flip must add the same substitutions to `trials/n3_trust/Makefile`,
  `trials/n4_trust_tls/Makefile` and the interchange driver, or the goldens hold times.
- **N3's negative timing no longer holds.** Step 13 (user code fails) now waits for the client's own 2 s timeout instead of an
  immediate close, which moves steps 14 and 15 two seconds later. Step 15 is meant to land while the peer is quarantined, before
  node a's operator reset at 9 s. Timed in a scratch run (line stamper): quarantine at 4.96 s, step 15 refused at 6.99 s, reset at
  9.01 s, a 2 s margin; in the integrate runs of N3 and of N4 step 15 was served after the reset (`{ok, int 3}`, conn 11 in
  `negative.a`, no `connection refused` line). Not a hole: the call was made after the reset. But the step then shows nothing.
  The flip must move the operator reset later (`roles/operator_reset.role`, e.g. 12 s) or shorten step 13's wait, in N3 and N4,
  then run three times.

So the exact list to re-record when the switch is turned on, on the Mac and on Linux: `n3_trust` (`scenario.a`, `scenario.b`,
`negative.a`, `negative.b`, `kill.b`), `n4_trust_tls` (`scenario.a`, `scenario.b`, `negative.a`, `negative.b`, `kill.b`, `noca.a`,
`noca.b`, `pin.a`, `pin.b`, `refusals.a`), `x2_interchange_trust` (all 12), and the N5 B1 scenarios unless their nodes get the
B1 spelling. Commands, after the two Makefile edits and the timing edit:

```
# tools/bees_conf.py: SESSION_DEFAULT_ON = True; tools/test_bees_trust_mux.py: the test that the switch is off
make -C trials/n3_trust record-golden SILICA_COMPILER=/Users/yenrab/silica/binaries/silica-999909-macos-applesilicon
make -C trials/n4_trust_tls record-golden SILICA_COMPILER=/Users/yenrab/silica/binaries/silica-999909-macos-applesilicon
make -C trials/x2_interchange_trust -f interchange.mk record-golden SILICA_COMPILER=...   # needs both machines
make -C trials/n5_trust_mux record-golden ...; make -C trials/n5_trust_mux_tls record-golden ...   # only if the B1 scenarios change
# on Linux the same with silica-999944-linux-x86_64 (the coordinator); then three integrate runs of each
```

One request per connection with the switch on: yes, `{session, #{max_inflight => 1, max_calls => 1}}` (the ruling of Q1 and R-6;
the summary line then reads `one request per connection (B1)`, and `compat` shows N3's output byte for byte). What it does not
give is N3's own actors: the node is still built with the session units and runs them with limits 1, and it offers no session.
There is no spelling that builds a node without the session units (owner question Q14 below).

## 13. Edits needed in the documents this work does not own (listed, not made)

- `development-plan/mvp.md`, N5 row: status "built 2026-11-18" with the pointer to this note; criterion 9 is met for N3 (the N4
  goldens were not compared: N4's roles on session nodes with limits 1 and 1 are not a trial); criterion 10 as measured in
  11.3 (latency buckets, not a p95); `acceptors` validated and unused. The status paragraph at the top ("N5 not started").
- `development-plan/roadmap.md`: B2 row status; a decision entry for the rulings of section 9 (Q1 default on, behind the
  switch until the goldens are re-recorded; Q5 no counts in `goaway` or `ok`; Q13 `trpc_close`; Q2 to Q12 accepted).
- `development-plan/inter-nodal-modes.md`: 3.6, the frame table (`hello` and `token_present` may carry `opts => #{goaway =>
  1}`; a new row `ok`; `goaway` only on a session) and the state diagram (`active` entered by `ok`; a failed or timed-out
  request does not leave `active`); 3.7 (quarantine closes open sessions at the next suspicion rise); 3.9 item 6 (requests
  never re-sent; no backoff: sessions are opened on demand; `trpc_close`); 3.10, the table (the per-connection supervisor is
  a plain behaviour with a table, no `count_children`; cancel does not stop a running worker; telemetry is lines); 3.11.
- `development-plan/bees-config-file.md` 5.3: `session` row ("effective from N5" is now true; the default applies when the
  key is absent once the switch is on; limits 1 and 1 keep one request per connection); the client's use of `max_inflight`;
  the idle tick (`idle_ms` plus up to a tenth); `acceptors` (validated, unused, boot note); `session_slots_max` (counts open
  connections, refuses before reading). Section 12: the session values are among the options a store-carried configuration
  passes; the tables' size (`max_inflight`) is a build-time value of generated code, like the decode literals.
- `contract/wire-v1.md`: the `trust/1` additions of section 2 of this note (there is no TRUST frame table there yet).
- `documents/trust.md` (no bold): "Each call is one request on its own connection" and "One request per connection keeps the
  number of connections small" need the session wording: a bounded session of several requests, ended by the server with a
  goaway; step 6 "The connection closes".
- `development-plan/silica-defects.md`: done (the 2026-11-18 N5 section: SD-47 on the Mac, SD-49, two notes).
- `development-plan/spikes/F1-fuzzer.md` 6.3, row F1-3: status "fixed 2026-11-18 in `tcli` and `mcli` (N5); replay case 5 and
  case 9 0 of 20; deterministic trial `trials/n5_trust_mux` `hostile_b1`, `hostile_session`"; owner question 2 there is answered
  for `tcli` by (b).
- At the flip (section 12.1), in files this work does not own: `trials/n3_trust/Makefile` and `trials/n4_trust_tls/Makefile`
  (mask `age_ms=`, `duration_ms=`), `roles/operator_reset.role` of both (the reset later than 9 s), `.gitignore` (the session unit
  names for those leaves and `x2_interchange_trust`), the interchange driver's post-processing.
- `development-plan/spikes/N3-trust.md` section 4 ("Multiplexing (N5); `session`, `acceptors`, `session_slots_max` are
  validated, not used"): now used, except `acceptors`.
