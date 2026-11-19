# F1: the wire fuzzer

Status 2026-11-18: built and run on this Mac (macOS, Apple Silicon) with the pinned compiler
`silica-999909-macos-applesilicon`; every node program and every result below is from that compiler. The harness, a smoke case in
`make integrate` (golden recorded for macOS) and a smoke run of 30 minutes are done. **The 24-hour runs are not started**: the
commands for the Mac and for the Linux machine are in section 8. Nothing was downloaded or installed; nothing in the Silica tree
was changed; no file of another work stream was edited.

Why: roadmap row B1 ("the frame fuzzer runs 24 hours with no crash"), the ingress gate that is "a security boundary, fuzzed as
one" and "fuzzed per validator", and M4-demo's note that its six hostile frames were "not a fuzzing campaign".

## 1. What was built

| Piece | File | What it does |
| --- | --- | --- |
| deterministic source, ETF writer, lenient ETF reader, hostile-term generator | `tools/bees_fuzz_etf.py` | `Rng` is splitmix64 seeded from the SHA-256 of (run seed, surface, case index): no clock, no `os.urandom`, no `random` module. The writer makes every ETF tag in every encoding (four atom encodings, small and large tuples and bignums, improper lists, pids, ports, references, funs, bit binaries, compressed terms). The generator makes well-formed and hostile terms: lengths that claim more than is there, counts up to 4294967295, nesting from 2 to 1000 levels around the limits 16 and 32, atoms no node holds (prefix `zz_fuzz_`), every tag byte. The reader is the oracle's: it accepts everything OTP writes, so "the reader refuses it" means no decoder may accept it. |
| case generators and oracle models | `tools/bees_fuzz_gen.py` | `case(seed, surface, index)` returns one JSON case: the steps the driver plays and the bytes, the same on every machine. The models say what a correct receiver may do with exactly those bytes (section 3). |
| driver | `tools/bees_fuzz.py` | Runs node programs under a pty, plays cases as a hostile peer dialing a node, as a hostile listener a node dials and as a hostile EPMD, and detects crash, actor failure, hang, wrong acceptance, lost message, error body, memory growth (section 4). Saves each finding with a reproducer (section 5). `run`, `replay`, `show`, `prepare`. Standard library only; no macOS-only call (`ps -o rss=`, pty, sockets, `ssl`). |
| unit tests | `tools/test_bees_fuzz.py` | 21 tests of the pure parts: determinism (pinned `Rng` values, same case twice, JSON round trip, no clock or random import), writer and reader against each other and against `erl` (`binary_to_term`, `term_to_binary`), the verdicts of the three models. Picked up by `python3 -m unittest discover -s tools -p 'test_*.py'`. |
| nodes under test and the smoke case | `trials/f1_fuzz_wire/` | Five node programs of its own (`nodes/bl`, `bd`, `ts`, `tt`, `tc`), the `resolve/` leaf, roles, `Makefile` (a trial leaf: in `make integrate`), golden `smoke.macos_applesilicon.scout`. Ports 23500..23599. |
| the long run | `trials/f2_fuzz_long/` | `fuzz.mk` (no `Makefile`, so it is no trial leaf and never in integrate): `nodes` copies the node sources with the ports of its own block (23600..23699) and builds them; `fuzz-long` runs for `DURATION`; `replay`. |

The nodes are ordinary BEES programs built from `src/` through the same generators as the N2, N3 and N4 trials; only their
roles are the fuzzer's. Each prints what it delivers or executes with the value in decimal on one line (`inbox got op=inc n=41000`,
`[demo] note got 57000`, `call 100011: {ok, int 100012}`) and prints every actor failure report but a normal end behind the
marker line `[fuzz actor failure report]`. `trials/f1_fuzz_wire/README.md` lists nodes and ports.

## 2. Surfaces and what is generated

| Surface | Node | The driver is | Generated (kinds) |
| --- | --- | --- | --- |
| `beam_accept` | `bl` (listens, cookie auth, cap 4096) | a peer dialing as `stock@localhost` | bytes instead of a handshake (random, zero bytes, a TLS record, a data frame); the name message damaged (flags, lengths, 0 to 4000-byte names, version 5 form, other node names); the challenge reply wrong, short, long, missing, wrong tag, each followed by good frames (nothing may be delivered); after a good handshake: payloads (byte damage, bad version, unknown atom, extra, missing and repeated key, wrong types, bignums at the int64 edges, every atom encoding, deep nesting, random terms), control messages (every operation 0 to 40 with right and wrong arities, foreign and never-handed-out pids, names nobody serves, `net_kernel`'s `is_auth` damaged, large tuples, nesting), the pass-through byte, lengths (above the cap up to 4294967295, at the cap, overstated, understated, partial prefix, partial frame), good and bad frames in one write, tick floods, everything again written 1 to 7 bytes at a time |
| `beam_dial` | `bd` (asks EPMD, dials, redial on) | its EPMD and the listener it dials | EPMD `PORT2_RESP` answers (random, not found, 1 to 3 bytes, empty and close, other reply tags, 60000 trailing bytes, damaged, port 0, silence); the acceptor's handshake (statuses `nok`, `not_allowed`, `alive`, `named:`, random, 57600 bytes; the challenge damaged, cut, from another name; the acknowledgement wrong, missing, wrong tag); then the same frames as above towards `outbox` |
| `epmd_register` | `bl` at boot | its EPMD | `ALIVE2` answers: random, refused, 1 and 3 bytes, the old `ALIVE2_RESP`, empty and close, 60000 trailing bytes, other tags, creation 4294967295; held open or closed |
| `trust_plain` | `ts` (TRUST server, plaintext test mode) | a TRUST peer | the 64-byte identity (permitted, whitelisted with `none`, unlisted, random, short); the first frame (hello damaged, `ver` not 1, a request first, other `t`, random bytes); token step (random, zero, wrong-length, non-binary tokens; the live token of the last probe); the request: 24 kinds (byte damage, random term, random map of 0 to 18 keys, `ver`, `req_id` of 0 and 17 to 300 bytes, forbidden and unpermitted MFAs, unknown atoms, arity against `args`, argument types, `args` around `args_len_max` 1024 and up to 4090 bytes, `opts`, `t`, 9 to 18 keys, repeated key, each key missing, nesting at 29 to 400 around `term_depth_max` 32, pids, references, funs, bit binaries and compressed terms, key that is no atom, `STRING_EXT` args); lengths (first or second frame above the cap, overstated, understated, partial, zero); a second request; 1 to 5 bytes at a time |
| `trust_tls` | `tt` (TRUST server, mutual TLS 1.3) | a TLS client with `p.pem` (permitted), `n.pem` (`none`), `u.pem` (unlisted) | the same frames inside TLS; and raw bytes at the TLS listener with no handshake (random, TLS record headers with lengths 0 to 65535, a TRUST frame in the clear, an HTTP request) |
| `trust_client` | `tc` (TRUST client, plaintext test mode, calls for ever) | the server it has pinned | answers to hello and to token_present: `token_issue` damaged, tokens of 0 to 4000 bytes, token no binary, no `token_issue`, result before `token_issue`; `result` damaged, other `req_id`, `ver`, `t`, each key missing, value any term (deep, large, unknown atom, pid), 1 to 30 extra keys, two results; lengths above the cap, overstated, partial, zero; garbage; close; silence |
| `resolve` | `resolve/fz_resolve` (generated program) | the resolver's native edge | answer texts `ok <csv> <n6>` / `err <reason>`: quads in and around the dropped ranges, malformed quads (octal-looking, signs, spaces, five fields, IPv6), repeats, up to 200 addresses, unknown reasons, damaged structure, random text |
| `tempus` | none | | **not live: a hook** (section 7) |

The ETF decoder limits (lengths, depth, sizes, unknown atoms, every tag) are reached through the wire: the BEAM-mode control
skipper (`beam_dist`, depth 16), the language's `decode` of the payload, TRUST's structural walk (`bees_trust_frame@check`,
depth 32, 16 keys, `args_len_max`) and its `decode` of each value all receive the generator's terms in the frames above.

**How the resolve surface works.** Silica reads no file and takes no input, and the stub native edge has fixed answers in C
(`native/src/silica_bees_resolve.c`, a shared file). So the driver writes a batch of 60 generated answers as string literals into
`fz_resolve.silica`, which puts each through `bees_addr@ans_ok`, `ans_csv`, `usable` and `ans_reason`, compiles it with the leaf
rules and compares each printed line with the model. Limit: answers hold printable ASCII only (no NUL, control or non-ASCII
byte), because they are literals; the worker `dangerous_bees_resolve@rslv`, its tag echo and the dial path's timer are not driven
(they need a native edge that returns chosen bytes at run time; owner question 4).

## 3. The oracle models (what "must be refused" means)

Only a **certain** verdict makes a finding. A model returns `valid` (the canonical bytes: must be accepted), `invalid` (no
correct receiver may accept) or `maybe` (the plan does not settle it, or another decoder might read it: never a finding).

- **BEAM mode** (`beam_model`): the bytes sent after a completed handshake are cut into frames the way a correct receiver does
  (4-byte length; a length above `frame_size_max` is a framing violation and nothing after it is read; a zero length is a tick).
  A frame is `invalid` when its type byte is not 112, the control message does not read as a tuple of a delivering operation
  (SEND, REG_SEND, their trace-token forms, SEND_SENDER, ALIAS_SEND), or the payload is not exactly a map `#{op, n}` with an atom
  the node holds and an integer in int64. Nothing may be delivered before authentication, after a wrong or missing digest, or
  from a peer name the node does not list. The rule checked is M3's decision 4 as M4 states it: bad content of an intact frame
  is dropped and the link continues (the probe is then sent on the same link and must be delivered); a framing violation ends
  the link (the probe goes on a new connection).
- **TRUST** (`trust_model`, `judge_request`): a request may be executed only when the identity is the permitted one, the first
  frame reads as `hello` (or `token_present` with the live token), and the second frame is a map of at most 16 atom keys, none
  twice, no unsupported term, no atom the node cannot hold, `ver` 1, `t` call or cast, `req_id` a binary of 1 to 16 bytes, an
  MFA the whitelist permits with `a` equal to the length of `args`, arguments of the manifest's type in int64, `args` at most
  `args_len_max`, `opts` a map when present, nothing after the term. Evidence of execution: the `[demo] note got N` line (N is
  the case's canary) or a `result` frame. A token issued to an unlisted identity, a frame that is neither `token_issue` nor
  `result` (the rule: no error body) are findings too.
- **TRUST client** (`reply_model`): `{ok, V}` may be reported only when the answer holds a `result` frame with `ver` 1, this
  call's `req_id` and a value, after a `token_issue` with a binary token when the client said hello; and V must be the frame's
  value.
- **resolve** (`resolve_model`, `never_usable`): whatever the text, no kept address may be a non-strict quad, in 0.0.0.0/8,
  224.0.0.0/4 or 240.0.0.0/4, outside 127.0.0.0/8 under a loopback-only setting, or kept twice; for a well-formed `ok` answer
  the kept list must equal the model's.

## 4. What is detected

| Kind | How |
| --- | --- |
| `crash` | the node process ended (exit status or signal) |
| `actor_failure` | a Silica actor failure report in the node's output that is not on the expected list. Expected (the language's carrier ends with its link by failing itself, Silica 71009f96f8): `(:explicit, :link_lost)` and `(:explicit, :link_unavailable)` |
| `hang` | after the case the node does not answer the **probe**, a known-good exchange, within its deadline (8 to 12 s): a good handshake and a delivered frame (BEAM mode), a permitted call answered 42 (TRUST server), `{ok, n + 1}` for a good answer (TRUST client); or the node does not end within 3 s of being told to exit |
| `no_redial` | a dialing node with redial on never asks EPMD again after a failed lookup (finding F1-1) |
| `wrong_accept` | a delivery, an execution, a token or a result the model calls impossible; a delivery line no case of the last 60 can account for |
| `lost` | a canonical message of an authenticated peer was not delivered although nothing before it on the link was wrong |
| `error_body` | a TRUST server sent a frame that is neither `token_issue` nor `result` |
| `memory` | the node's resident set (`ps -o rss=`, sampled at the slice's start, every 50 cases and at its end) ended above 3 times its start plus 64 MiB |
| `filter` | (resolve) the filter's output breaks a rule of the model |

A run works one surface at a time in **slices** (250 cases times the surface's weight; one node program alive at a time, started
fresh for each slice, restarted after a finding), so case indices are sequential per surface and a run is identified by its seed
and the count per surface (`summary.json`, rewritten after every slice).

## 5. Reproducers

Every finding is saved under `RUNS/SEED/findings/SURFACE-INDEX-KIND/` (the first five of each signature; all are counted in
`summary.json`): `case.json` (the generated case), `input.bin` (the exact bytes sent), `node_output.txt` (the node's last 30000
bytes) and `repro.txt` with the one-line command, for example

```
python3 tools/bees_fuzz.py replay --seed 1118 --surface beam_dial --case 39 --trial trials/f2_fuzz_long
```

which regenerates that case from the seed and index and plays it on a freshly started node (`--file FINDING/case.json` plays the
saved bytes instead; `--before K` plays the K cases before it first; `--repeat R` plays it R times and prints how many gave a
finding, for a finding that depends on timing). `show --bytes FILE` prints a case and writes its bytes.

## 6. Results

### 6.1 The smoke case in integrate

`make -C trials/f1_fuzz_wire integrate SILICA_COMPILER=/Users/yenrab/silica/binaries/silica-999909-macos-applesilicon`:
seed 1; 24 `beam_accept`, 12 `beam_dial`, 4 `epmd_register`, 24 `trust_plain`, 16 `trust_tls`, 60 `resolve` cases; **140 cases,
0 findings, 1 passed, 0 failed**, the same output in the recording run and in two integrate runs after it. The 80 wire cases
take 6.4 s (measured alone, and their lines were again the golden's); the rest of the leaf's time is its builds, five nodes and the
resolve batch, about 8 minutes with one compile at a time. `smoke.sout` holds one line
per case (surface, index, kind, the 12-digit SHA-256 id of the generated case, `ok`) and no wall-clock value. `trust_client` is
not in the smoke case: its outcome depends on timing while F1-3 is open.

### 6.2 The 30-minute smoke run (Mac, seed 1118)

`make -C trials/f2_fuzz_long -f fuzz.mk fuzz-long SEED=1118 DURATION=1800` on nodes built by `silica-999909-macos-applesilicon`,
ports 23600..23699, one node program alive at a time. `trust_client` was added after this run started and is not in it
(its figures are below the table).

| Surface | Cases | Seconds in its slices | Cases per second | Findings (raw) | Resident set, KiB (smallest slice start, largest slice end) |
| --- | --- | --- | --- | --- | --- |
| `beam_accept` | 6000 | 86 | 69.8 | 0 | 2848, 8592 |
| `beam_dial` | 2626 | 1314 | 2.0 | 193 `no_redial` (F1-1) | 2864, 3920 |
| `epmd_register` | 1250 | 224 | 5.6 | 0 | not sampled (the node is started per case) |
| `trust_plain` | 5000 | 75 | 66.7 | 13 `wrong_accept` (F1-4, the model's error) | 2592, 6608 |
| `trust_tls` | 3750 | 96 | 39.1 | 12 `wrong_accept` (F1-4, the model's error) | 7632, 19696 |
| `resolve` | 300 | 5 | 60.0 | 0 | not sampled (a program that runs once) |
| **all** | **18926** | **1800** | **10.5** | **218 raw, 2 signatures after triage** | |

- **18,926 cases in 1,800 s of run time, 10.5 per second over all.** Four surfaces run at 40 to 70 cases per second;
  `beam_dial` runs at 2 because each of its 193 F1-1 cases costs a wait and a node restart (73 % of the run's time). With F1-1
  fixed the same run would be several times larger.
- The 193 `no_redial` findings are **every** one of the 193 `epmd/*` cases whose answer is not "found" (9 kinds: random, not
  found, 1 to 3 bytes, empty and close, other tags, damaged, silence); the 86 `epmd/*` cases that name a port were dialled.
- The 25 `wrong_accept` lines are all `missing_opts` (F1-4): the model was wrong, and is corrected.
- Resident set: every slice starts at about 3 MiB (8 MiB with TLS) and ends below 9 MiB (20 MiB with TLS) after 750 to 1000
  cases; no slice came near the threshold (3 times the start plus 64 MiB). Growth inside a slice is there (about 5 KiB per case
  on `beam_accept`, up to 16 KiB per case on `trust_tls`); whether it levels off is for the 24-hour run to show, because a
  slice restarts its node.
- The machine went to sleep during the run (macOS, about 15 minutes of wall time): the driver's clock is `time.monotonic`,
  which stands still while the machine sleeps, so the run still did 1,800 s of work. Section 8's Mac command uses
  `caffeinate -i`.
- Other runs on the smoke nodes (`trials/f1_fuzz_wire`, same compiler): seed 7, 400 cases each of `beam_accept`,
  `trust_plain`, `trust_tls`, `beam_dial` (F1-1 29 times, F1-2 once, F1-6 once); seed 1, 60 and seed 5, 300 cases of
  `trust_client` at 3.8 cases per second (F1-3 in 15 and 80 of them; nothing else).

### 6.3 Findings and triage

| Id | What | Where | Whose | Reproducer | Status |
| --- | --- | --- | --- | --- | --- |
| **F1-1** | **A dialing BEAM-mode node with `redial true` stops dialing for ever after one failed EPMD lookup.** After `epmd: the peer is not registered`, `epmd: not an answer EPMD gives` or `epmd: connection closed` (a peer that is not registered yet, a cut or damaged answer, a silent EPMD) nothing schedules the next attempt: the node stays up with no link. A peer that restarts and is briefly absent from EPMD is enough; no hostile input is needed. Not documented as a limit (N2b says a redial attempt makes "a new EPMD lookup"; S14 (b) names only the failed name lookup). | `src/inter_nodal/dangerous_beam_net.silica`: `epm_look` (the `_` arm: audit, `close_link`, no word to the redial actor `nrd`), `epm_event` (`:link_down` before an answer), the `epm` arm for code 4 | BEES | `python3 tools/bees_fuzz.py replay --seed 7 --surface beam_dial --case 39` (every time; so does every `epmd/*` case whose answer is not "found") | **reported, not fixed** (the file is the N2T work stream's). Suggested fix: on every EPMD outcome that is not "found", tell `nrd` what a lost link tells it (the same back-off), and count it |
| **F1-2** | **A `tx` actor of BEAM mode fails with `(:explicit, :actor_not_found)`** when the node closes a link for a framing violation while a write of its own is still on its way to the carrier (a good `hello` frame, which the node answers, followed at once by a length above the cap). The link was closing anyway and the node goes on serving; the visible effect is an unplanned actor failure report caused by a remote peer. Seen once in 400 `beam_accept` cases of seed 7 and not once in the 6,000 of the 30-minute run. | `src/inter_nodal/dangerous_beam_net.silica`, `tx` (the cast `(:tx, seg, me)` to a carrier that has ended) | Silica's open **SD-43** (a cast to an ended carrier fails its sender), reached through a window BEES still has | `python3 tools/bees_fuzz.py replay --seed 7 --surface beam_accept --case 273 --repeat 300`: timing-dependent, 0 of 300 on an idle node; it showed once in 400 cases under load | **reported.** No new SD number: section "2026-11-18: F1" of silica-defects.md records the two new places SD-43 is reached |
| **F1-3** | **The TRUST client's connection actor `tcli` fails with `(:explicit, :actor_not_found)`, and then its carrier too, when the server's answer is refused in the token step** (garbage, a `token_issue` with a non-binary or odd-sized token, no `token_issue`, a result first, two results). The caller still gets its one outcome (`{error, protocol_error}`) and the next call works; a hostile or broken server can make every call end in two actor failures. | `src/trust/dangerous_bees_trust.silica`, `tcli` / `cli_handle` (the close path after a refused answer casts to an actor that has ended; the carrier then casts its event to the ended `tcli`) | SD-43 again, through BEES's client | `python3 tools/bees_fuzz.py replay --seed 1 --surface trust_client --case 5 --repeat 20` (9 of 20; case 9: 17 of 20) | **reported, not fixed** (the file is the N5 work stream's) |
| F1-4 | A request with **no `opts` key** is admitted and executed. The first model called that impossible (N3: "`opts` a map"). | `src/trust/bees_trust_frame.silica`, `parse_req` (refuses `opts` only when it is there and no map) | not a defect as built; **owner question 1** | `python3 tools/bees_fuzz.py replay --seed 1118 --surface trust_tls --case 56 --trial trials/f2_fuzz_long` (now `ok`) | model corrected (`opts` may be absent); the smoke run's 9 `missing_opts` lines are this |
| F1-5 | A whitelisted identity whose permission is `none` is issued a token on hello. | `tconn`, token step | by design (the whitelist admits the identity; the permission gate refuses every request) | | model corrected before the run |
| F1-6 | An acceptor's challenge message with damaged bytes is accepted when its digest is right for the damaged challenge. | | correct (the challenge is any 32-bit number) | | driver corrected before the run |
| F1-7 | **A node whose standard output is not read stops serving.** With the node on a pty that nobody drained, the first TRUST connection was answered and every later one got no byte back (audit lines are printed synchronously; macOS's pty holds about 1 KiB). | every `println` on the serving path | an operational fact, not a wire defect; **owner question 3** | start a TRUST server with its output on an unread pty and make three calls | noted; the driver drains every node's output in a thread |

No crash of a node process, no hang of a listening node, no wrong acceptance that survived triage, no memory finding and no
filter finding in the 18,926 cases of the 30-minute run and about 2,100 more of the shorter runs cases. What that does **not** show is in section 9.

Kept examples (case, bytes, node output, replay command): `trials/f2_fuzz_long/findings/` (`seed1118-beam_dial-000016-no_redial`,
`seed7-beam_accept-000273-actor_failure`, `seed1-trust_client-000005-actor_failure`, `seed1118-trust_tls-000056-wrong_accept`).

## 7. TEMPUS: a documented hook, not a surface

`src/tempus` is in flux (tempus-progress.md, 2026-11-18): the view, the store, the frame codecs and admission exist as in-memory
units with their own trials, the TLS link is being written, and no node listens or dials a TEMPUS frame yet (milestone T3 is
not built). There is nothing stable to dial. The hook: `SURFACES["tempus"] = False` in `tools/bees_fuzz_gen.py` (asking for it
prints the reason), `test_tempus_is_a_documented_hook`. To make it live when T3 exists: a node leaf under
`trials/f1_fuzz_wire/nodes/` that prints what it merges, a `case_tempus` generator over the frames of
`tools/bees_tempus_client.py`, a model from tempus-design.md's validation rules, and a `Runner` subclass like `TrustRunner`
(about 150 lines; the ETF generator and the probe machinery are reused).

## 8. The 24-hour runs (not started; for the coordinator)

**Mac** (from the tree root; about 12 minutes of builds first; one node program and the driver at a time, plus one compile of
60 resolver answers per round):

```
BEES_COMPILE_SLOTS=1 make -C trials/f2_fuzz_long -f fuzz.mk nodes SILICA_COMPILER=/Users/yenrab/silica/binaries/silica-999909-macos-applesilicon
nohup caffeinate -i make -C trials/f2_fuzz_long -f fuzz.mk fuzz-long SEED=2026111801 DURATION=86400 \
      SILICA_COMPILER=/Users/yenrab/silica/binaries/silica-999909-macos-applesilicon > /dev/null 2>&1 &
```

Results: `trials/f2_fuzz_long/runs/2026111801/` (`run.log`, `summary.json` after every slice, `findings/`). Watch:
`tail -f trials/f2_fuzz_long/runs/2026111801/run.log`. Stop early: `pkill -f 'bees_fuzz.py run --seed 2026111801'` (the nodes
are ended by the driver's signal handler; `summary.json` holds the figures up to the last slice). `caffeinate -i` keeps the Mac
awake: the duration is counted on a clock that stands still while the machine sleeps.

**Linux** (`manager@aalang.org`, `/opt/bees`; the tree must be synced first, as `tools/run_all_trials.sh --remote` does, and
`native/` built there). `RUNS` is outside the tree because the runner's `rsync --delete` would remove `runs/` at the next sync:

```
ssh -o BatchMode=yes manager@aalang.org 'cd /opt/bees && make -C native OPENSSL_PREFIX=/opt/openssl SILICA_ROOT=/opt/silica && \
  make -C trials/f2_fuzz_long -f fuzz.mk nodes SILICA_COMPILER=/opt/silica/binaries/silica-compiler-linux_x86_64 SILICA_ROOT=/opt/silica OPENSSL_PREFIX=/opt/openssl'
ssh -o BatchMode=yes manager@aalang.org 'cd /opt/bees && mkdir -p $HOME/bees_fuzz_runs && nohup setsid make -C trials/f2_fuzz_long -f fuzz.mk fuzz-long \
  SEED=2026111802 DURATION=86400 RUNS=$HOME/bees_fuzz_runs SILICA_COMPILER=/opt/silica/binaries/silica-compiler-linux_x86_64 \
  SILICA_ROOT=/opt/silica OPENSSL_PREFIX=/opt/openssl > /dev/null 2>&1 < /dev/null &'
```

Collect: `rsync -a manager@aalang.org:bees_fuzz_runs/2026111802/ trials/f2_fuzz_long/runs/linux-2026111802/`. Check that
nothing is left: `ssh manager@aalang.org 'pgrep -fl "bees_fuzz|f2_fuzz_long/nodes"'`. Not verified, because no ssh was allowed
in this phase: that the Linux machine's `python3` `ssl` completes TLS 1.3 with `p.pem` against the engine (the node allows
classical X25519 for `p.pem` so that an OpenSSL without the hybrid group works), and the exact spelling `make -C native` needs
there (native/linux/README.md). Run `make -C trials/f1_fuzz_wire record-golden` there first (it also proves the nodes and the
driver on Linux in a few minutes).

Different seeds on the two machines on purpose: two runs of one seed would play the same cases. After a run, triage with
`summary.json`'s `finding_signatures`, then `repro.txt` of each saved finding. A finding that is known (F1-1 will be most of
`beam_dial`'s) costs its restart only.

## 9. What is not covered

- **TEMPUS** (section 7). **N5's multiplexed TRUST sessions** (`bees_trust_mux*`, another work stream, in flux): the TRUST nodes
  under test are single-request (B1). **BEAM mode over TLS** (N2T, in flux). **The TLS handshake itself** is OpenSSL's; only
  raw bytes at the listener and three identities are tried, no damaged TLS records after the handshake.
- **The TRUST client over TLS**, and a BEAM-mode node's **second link** (N2b multi-link), mesh and replace paths.
- **The resolver worker at run time** (section 2): only the filter, and only printable answers.
- **Slow-sender and many-connection exhaustion**: every case is one connection; a peer that holds hundreds of half-open
  connections or sends one byte a second is not generated. Memory is judged per slice of at most 1000 cases, so a leak of a few
  bytes per case shows only in the 24-hour run's `rss_kib_first_last_per_slice`, and only between restarts.
- **Coverage is not measured** (Silica has no coverage instrument); the generator's kinds were chosen from the validators'
  source and from the spike documents' negative cases.
- **The models are one-sided**: a `maybe` is never a finding, so an over-strict node (a valid message refused) is seen only for
  the canonical forms (`lost`, the probe).
- **Frame cap 4096 only** (the trials' cap); frames near BEAM's 4294967295 default are not sent.
- **Linux**: nothing was run there; the goldens of section 10 are missing until phase 2.

## 10. Goldens that need a Linux twin

- `trials/f1_fuzz_wire/smoke.macos_applesilicon.scout` → `trials/f1_fuzz_wire/smoke.linux_x86_64.scout` (record on Linux with
  `make -C trials/f1_fuzz_wire record-golden`; the case ids must be the same as the Mac's, line for line: they depend on the
  generator only).

## 11. Owner questions

1. **Is `opts` required in a TRUST request?** BEES admits a call or cast with no `opts` key (it reads it as the empty map);
   N3 lists "`opts` a map" among the request's fields. Options: (a) optional, as built, and say so in inter-nodal-modes 3.6;
   (b) required, `protocol_error` when absent. Recommendation: (a) if SEMP's reference reads it with a default (to be checked
   in `~/BEAM_SEMP`), otherwise (b); the fuzzer's model follows the ruling in one line (`judge_request`). Until ruled, the
   model treats it as optional (the conservative choice for a finding: no false wrong-acceptance).
2. **Should the two SD-43 windows (F1-2, F1-3) be closed in BEES now or wait for Silica?** Options: (a) wait for Silica to make a
   cast to an ended carrier a no-op (D31's rule for `!`); (b) close them in BEES (never cast to a carrier after deciding to
   close; end `tx` through the reaper). Recommendation: (b) for `tcli` (it fails on every refused token step, a remote peer
   chooses when), (a) for `tx` (rare, and harmless in effect). While open, the 24-hour criterion "no crash" should be read as
   "no process crash and no actor failure other than these two signatures".
3. **Should a node keep serving when its standard output blocks?** (F1-7.) Options: (a) leave as is and document that a node's
   output must be read (a supervisor, a file, `/dev/null`); (b) audit through a bounded, non-blocking writer that counts what it
   drops. Recommendation: (a) now, (b) with the audit-log design (the N3 "audit log" row).
4. **A native resolver test edge that returns chosen bytes at run time** (an environment-named file read by the stub) would let
   the fuzzer drive `dangerous_bees_resolve@rslv`, the tag echo and the dial path with arbitrary bytes, including NUL.
   `native/src/silica_bees_resolve.c` is shared, so it was not added. Recommendation: add it to the existing stub
   (`bees_resolve_stub_etf`), test builds only.
5. **Known findings in a golden.** The smoke case has no finding line today. If a later seed or count is wanted that includes an
   `epmd/*` case, the golden would hold a `FINDING ... (no_redial)` line until F1-1 is fixed. Recommendation: keep the smoke
   case free of known findings (as now) and let the long run count them.
6. **`trials/f2_fuzz_long/nodes` and `resolve/` are generated copies** (ignored by git). The alternative is one set of nodes
   whose ports come from the environment, which needs the boot-time config reader (N0.2/D46). Recommendation: keep the copies
   until the reader exists.
