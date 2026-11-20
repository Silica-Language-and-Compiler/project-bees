# TEMPUS progress log

Short dated entries, newest last. The design is [tempus-design.md](tempus-design.md).

## 2026-11-18, end of phase 1 (reading)

Done: read `documents/tempus.md`, `semp.md`, `trust.md`, `README.md`; the whole of `~/BEAM_SEMP` (both branches, read-only);
roadmap decisions D1 to D47, inter-nodal-modes section 5, bees-config-file sections 5.3 and 12, silica-defects, N0c, N2b, N3;
the TRUST units and their trial layout; the outline of Silica's transport design.

Main finding (verified by listing and searching the repository, both branches `main` and `origin/multiplex_dev`, and the commit
log): **the SEMP reference contains no TEMPUS specification beyond one README section (lines 347 to 436), no TEMPUS design
document and no TEMPUS Erlang code.** The only other traces are the `tempus` profile of `semp_whitelist.erl` (a second
whitelist table), the `tempus_` prefix in `semp_policy.erl`'s forbidden prefixes, and one line of the multiplexing design
that puts TEMPUS out of its scope. The README section fixes: three isolated Cyclon stores, the per-tick steps (age, oldest
partner, self at age 0, remove sent entries, merge preferring younger, evict oldest), and the admission model (Ed25519
identity, producer token, key id pinning, proof of possession, platform attestation at the issuer). It fixes no wire message,
no field encoding, no default number, no join or leave procedure, no transport and no TRUST/TEMPUS interface.

Consequence: most of the design is open questions for the project owner. The one part that depends on none of them is the
pure Cyclon view logic over opaque entries, which is the first milestone (T0).

Next: phase 2, write tempus-design.md.

Open questions so far: listed in the design (section 14 there).

## 2026-11-18, end of phase 2 (design written)

Done: [tempus-design.md](tempus-design.md), sections 0 to 17. Every statement is marked as taken from a SEMP source (with
the README line), decided by a BEES ruling, or proposed. Three owner requirements that arrived during the phase are in it:
the Silica client (a source-only library and a thin app) and the Python client, with the ruling that "drive is the full
behavior" (section 16: two roles, a 36-row behaviour list with how each client causes and observes each row, the control
interface, milestones C1 to C3); and bridge nodes (section 17, milestone T6 widened).

Verified: only the citations (read from the files). Nothing of sections 4 to 17 is built.

Open questions: OQ-1 to OQ-25 in section 14. The ones that block the most: OQ-1 (what the specification is), OQ-2 (TLS and
proof of possession), OQ-4 (when a peer is admitted), OQ-5 (stores of another type), OQ-7 (token format), OQ-12 (failed
shuffle), OQ-19 and OQ-20 (control interface and test-only control), OQ-22 and OQ-23 (what a bridge is, protecting TRUST).

Next: phase 3, milestone T0 (the pure view logic), which depends on none of them. Its unit and trial are written; the
first compile stopped at a parse error in the trial program, being fixed.

## 2026-11-18, phase 3: milestone T0 built and verified

Done:
- `src/tempus/bees_tempus_view.silica`: the Cyclon view as pure functions (design section 3).
- `trials/t0_tempus_view`: entry `view` (hand-worked cases, then eight nodes for ten rounds) and entry
  `sd_own_len_function` (a Silica defect, below). Goldens recorded for `macos_applesilicon`.
- `tools/bees_tempus_view_model.py` (an independent Python model of the same rules) and `tools/test_bees_tempus_view.py`.

Verified (observed on this machine, compiler `silica-999909-macos-applesilicon`, passed on the make command line):
- `make -C trials/t0_tempus_view integrate`: 2 passed, 0 failed, five runs in a row after the goldens were recorded.
- The golden of `view` was recorded only after its 78 case lines were read against the hand-worked answers in the source
  comments, and after `tools/test_bees_tempus_view.py expected` (the model's output) was identical to the program's output,
  the 80 simulated exchanges included. `python3 tools/test_bees_tempus_view.py`: 4 tests pass.
- Peak resident set of `view`: 1.6 MiB (one run).

Not verified: anything on Linux or the boards; identities that are not text; the unit inside an actor (T1).

Silica defect found (small repro: `trials/t0_tempus_view/sd_own_len_function.silica`, golden records the defect). Proposed
entry for silica-defects.md, to be numbered by whoever merges it (SD-47 if still free):

> A program's own function named `len`, taking no arguments, called as `len()`, does not return what its body says:
> `fn len() -> int64 { 3 }` read back as 4341129520 and then 4341129560 in one run (address-like, different at each read);
> a function with the same body under another name returns 3. Nothing is reported at compile time. A parameter named `len`
> was not affected in the cases tried. Found 2026-11-18 on `silica-999909-macos-applesilicon`, where a recursion
> counted by that value ended in a fault (`[silica] fault ... in main+...`, exit 70; the cause of the fault is inferred from
> the debugger's call chain, the wrong value itself is observed). BEES: no unit names a
> function `len` (the trial's is `shuffle_len`; the view unit's parameter was renamed `count` as a precaution).

While looking for it, two things were seen once each and NOT established as defects (both disappeared when `len()` was
renamed; not investigated further): a `sequence ... produces pure f(...) end` written inside a case-arm block after a
binding, and a record literal bound directly in a sequence.

Edits needed in existing files (not made): see design section 15, plus the silica-defects.md entry above.

Open questions: OQ-1 to OQ-25 (design section 14). Every milestone after T0 depends on at least one of them; T1 needs only
OQ-12 and OQ-5 and could start on the recommended answers if the owner agrees to provisional work.

Next: T1 (the store actor), beginning with the SD-35 measurement of an actor that holds a view, once OQ-12 and OQ-5 are
ruled; or C1/T2 once OQ-1, 4, 7 and 8 are.

## 2026-11-18, after the owner's rulings: redraft, T1, T2, C1, and the start of T4

Redraft. tempus-design.md now states the ruled design as decided (marks `[B: OQ-n]`); section 14 is kept as the record.
Changed by the rulings: one node may run TRUST, TEMPUS or both (section 11); a bridge has two keys (4, 17.2); no control
interface, both clients are wire-only peers, the test-only `tick` and `clock` are frames (5, 16.3); the bridge's bounds are
the application's, with literal ceilings in BEES (17.5); milestone order T0, T1, T2 and C1, T4, T5, T3, C2, T6, C3, T7, T8
(13). Seven new questions, none blocking what was built: NQ-1 to NQ-7 (section 18).

Ed25519, checked early as asked (observed):
- OpenSSL 4.1.0 at `/opt/homebrew/opt/openssl` (the first directory native/macos/platform.mk names): the `openssl` command
  signed and verified an Ed25519 message; `native/tempus/silica_bees_tempus.c` (EVP calls) built against it by hand and its
  self-test passed 15 of 15 checks against vectors made by Python's `cryptography` package (public key from seed, SHA-512
  identity, a token's producer signature, proof of possession over nonce || token, and their refusals).
- Python: `cryptography` 46.0.3 is installed for `/opt/homebrew/bin/python3` and does Ed25519; its `ssl` module is linked to
  OpenSSL 3.6.2 and has TLS 1.3. Nothing was installed.
- Mbed TLS: the only copy on this machine is ESP-IDF's (`~/esp/esp-idf/components/mbedtls/mbedtls`, 4.1.0). It has the TLS
  signature-scheme constant for Ed25519 and the PSA identifiers, and no Ed25519 implementation that a file search finds
  (no `PSA_WANT` switch, nothing in `library/` or the drivers). So the boards cannot be TEMPUS nodes with it: NQ-6. Not
  checked: any newer Mbed TLS (nothing was fetched), Linux's OpenSSL (no ssh).

T1, built and verified. `src/tempus/bees_tempus_store.silica` (one store's steps, pure) and
`src/tempus/bees_tempus_store_actor.silica` (the actor). Trial `trials/t1_tempus_store`: entry `steps` (36 hand-worked
lines; six stores and a silent peer for 30 rounds, after which no view holds the silent peer) and entry `actors` (four
store actors and a driver, 400 ticks, one failed shuffle with a peer that does not exist, memory check). Observed:
integrate 2 passed, 0 failed, six runs in a row; both outputs identical to the independent model
(`tools/bees_tempus_store_model.py`, `tools/test_bees_tempus_store.py`, 6 tests). The SD-35 measurement: an actor holding a
view in its state does not grow on 999909 (49 KiB for a small view, 1.0 MiB for the worst case, flat from message 10 to
3,000); design section 9 has the numbers. Not built in T1: the timer that ticks a store (the node part, T3).

T2 and C1, built and verified. `src/tempus/bees_tempus_frame.silica` and `src/tempus/bees_tempus.atoms` (every frame of
design section 5 written and read with the language's encode and decode, the bounds of section 8, the token's structure,
TRUST's map walk reused unchanged); `src/tempus_client/bees_tempus_client.silica` (the Silica client library's pure part:
the operations as frames and seven named wrong frames); `tools/bees_tempus_client.py` (the Python client's own codec,
tokens, identities). Trial `trials/t2_tempus_frames`. Observed: integrate 1 passed, 0 failed, three runs; the Python test
(`tools/test_bees_tempus_client.py`, 10 tests) finds the same bytes from the same inputs for 31 frames and tokens, and the
same verdict (accepted or refused) from the Python reader on all 44 byte strings the Silica program prints; identities that
are not text compare by their bytes; peak resident set 3.9 MiB with 20,000 refusals (read at that one count, so "flat" is
not shown). Not built: the 4-byte length on a carrier (wireframe, as TRUST; nothing in T2 touches a carrier), the client's
active part (C2).

T4, started. The native edge is written and self-tested (above). The Silica side cannot be built until existing makefiles
gain the lines listed in design section 15; that is the next step and it is blocked on those edits, not on a ruling.

Silica notes from this stretch (no new defect entry needed beyond SD-48):
- `len` again: SD-48 is better stated as "a function named like the builtin `len` gets no E2020"; a helper named `send`
  did get E2020 ("ambiguous: a builtin and a function of this module"), which is the diagnostic `len` should have had.
- `link`, `bytes` and `buf` are reserved words as parameter or binding names (E1040, E1000): expected, noted for the next
  writer.
- `substring` on a byte string that is not UTF-8 ends the program (exit 74, no report). The trial prints such strings as
  hex. Whether that is a defect or the documented behaviour of `substring` was not checked against the specification.

Linux goldens needed (I did not ssh): `trials/t1_tempus_store` (steps, actors) and `trials/t2_tempus_frames` (frames).

Next: T4's Silica side (token check, proof of possession, key id, expiry and skew, as one-process trials) once the build
wiring exists; then T5.

## 2026-11-18, T4 built and verified; T5 waits on a decision

T4 (admission in one process). New: `src/tempus/bees_tempus_admit.silica` (the rules that need no key: field lengths, token
structure, the current kid first, the time window with skew, sub, typ), `src/tempus/dangerous_bees_tempus_native.silica`
and `dangerous_bees_tempus_edge.silica` (the edge worker over `native/tempus`), `src/tempus/dangerous_bees_tempus_verify.silica`
(one actor per check: SHA-512 identity, then the signature), the sidecar `native/dangerous_exposure_source/tempus/`,
`tools/bees_tempus_fixtures.py` (TEST-ONLY keys, tokens and proofs from fixed seeds, written as a Silica unit kept in the
tree), `trials/t4_tempus_admission`, `tools/test_bees_tempus_admission.py`.

Observed (silica-999909, Apple Silicon, OpenSSL 4.1.0): integrate 1 passed, 0 failed, ten runs in a row; all 20 cases
(15 descriptors: admitted, expired, not valid yet, the skew edges, another kid, another kid and expired, a signature not the
producer's, sub, typ, id, a changed payload, a cut token; 4 proofs of possession; the node's own signature equal to the
fixture's) give the verdict the Python client's own checks give for the same bytes (6 tests). The post-processing
(`sout.sed`) removes only the runtime's report of each verifier actor's normal end, whose place among the lines varies.

What the compiler taught: a `dangerous_` unit's functions cannot be called outside an FFI worker (E4042) and only a
`dangerous_` unit may hold the edge's reference (E4026), so the verifier is exported as a behaviour and spawned by the
program's root unit, as TRUST's actors are; `stop_self` only in the behaviour function itself (E2091).

Not built in T4: the `key_rotated` frame being sent (the verdict exists; sending is the connection actor's, T3); expiry of
view entries over time (needs the node's clock message, T3); bytes instead of files for keys (N0c, later for both parts).

T5 (TLS for `tempus/1`): not started. The existing TLS link cannot be reused as it is; design 17.6 lists exactly what is
missing: (1) the ALPN is a constant, (2) one context per role per process, so no second credential, (3) no call that gives
the peer certificate's public key, which TEMPUS needs to bind the TLS channel to the advert's key. Coordinator's decision:
a small change there or a TEMPUS copy. T3, C2, T6 and C3 follow T5.

Also to check at C2 (not verified): whether Python 3.14's `ssl` (OpenSSL 3.6.2) offers X25519MLKEM768 by default; it
cannot be asked to by name.

Linux golden needed: `trials/t4_tempus_admission` (dangerous_admit); it needs `make -C native tempus` on that machine.
Edits needed in existing files: `.gitignore` line `!trials/t4_tempus_admission/dangerous_exposure_source`; top-level
Makefile: `python3 tools/test_bees_tempus_admission.py` in the tools-test list.

## 2026-11-18, the rulings on NQ-1 to NQ-7 folded in; the TLS engine's three additions; T5 begun

Design: NQ-1 to NQ-7 are stated as decided (`[B: NQ-n]`). `mode` has the owner's three SEMP spellings; for the hyphen in
`tempus-trust` the choice written in section 11 (to be confirmed) is: BEES's own reader accepts the bare spelling as the
value of `mode` only, and also the quoted atom `'tempus-trust'`, which is valid Erlang for the same atom; inside BEES the
mode is a byte string, never a Silica atom (which cannot be spelled with a hyphen); nothing is renamed.

TLS engine (coordinator's decision: additions, not a copy). Changed, one write per file, at 13:52:38:
`native/tls/silica_bees_tls.c`, `native/dangerous_exposure_source/tls/silica_bees_tls_wrapper.h` and `.meta`,
`src/trust/dangerous_bees_tls_native.silica`. Additive:
- the profile travels in `bees_tls_set_args`' second argument for `bees_tls_open` (0 TRUST, which is what every existing
  caller passes; 1 TEMPUS); a TEMPUS context offers and selects only `tempus/1`; bit 0 of `bees_tls_facts` means "the
  ALPN of the connection's profile was selected" (for TRUST: `trust/1`, as before);
- contexts are kept per (profile, role), so a node that is both holds two credentials;
- `bees_tls_peer_key`: the peer certificate's raw Ed25519 public key (32 bytes); another key type is refused
  (`BEES_TLS_E_CERT`), no certificate is `BEES_TLS_E_NO_CERT`;
- the Silica face gains `open_conn_profile/3` and `peer_key/1`; no existing function, signature or export changed.
`src/trust/dangerous_bees_tls.silica` was not touched.

Observed on the Mac, before and after the change: `make -C native tls-selftest` 21 PASS lines, identical text;
`trials/n4_trust_tls` integrate 11 passed, 0 failed; `trials/n3_trust` integrate 7 passed, 0 failed; no golden changed.
New self-test, `native/tempus/selftest/bees_tempus_tls_selftest.c` (run by `trials/t5_tempus_tls`, golden recorded,
integrate 1 passed twice): 23 checks pass: a TEMPUS pair with ALPN `tempus/1` and each side reading the other's key
(compared with keys derived by Python's `cryptography`); a `trust/1` client refused by a `tempus/1` server and the reverse
(error 4, no common ALPN); a TRUST pair and a TEMPUS pair open at once in one process, each with its own credential; a
P-256 peer's key refused; profiles that do not exist refused.

Python TLS risk, checked with a real handshake: Python 3.14's `ssl` (OpenSSL 3.6.2), with nothing set but TLS 1.3 and the
ALPN, completed a handshake against an OpenSSL 4.1.0 `s_server` restricted to `-groups X25519MLKEM768` (TLS 1.3,
TLS_AES_256_GCM_SHA384, ALPN `tempus/1`). So its default offer includes the hybrid group. Not yet shown: the same against
the engine itself with a client certificate (C2).

T5, what remains: the TEMPUS link in Silica (a new unit in `src/tempus`, the counterpart of TRUST's 600-line
`dangerous_bees_tls.silica`, using `open_conn_profile(role, 1, spec)` and `peer_key`), the check that the certificate's key
is the advert's `pub`, the `tempus` whitelist for bridges and sentinels (NQ-4), and a two-process trial. Then T3.

Needed in existing files: `.gitignore`: `!trials/t5_tempus_tls/certs/` (TEST-ONLY fixtures the golden depends on, as
`trials/n4_trust_tls/certs/`). Linux golden needed: `trials/t5_tempus_tls` (selftest). Port blocks: none taken yet; T3
will take one at NEXT_BASE and run `tools/trial_ports.py check`.

## 2026-11-18, T5 finished: the TEMPUS link, the channel binding, the whitelist, two processes over TLS

New (no existing file changed except the port table, adding only): `src/tempus/dangerous_bees_tempus_tls.silica` (the
link: TRUST's link with the TEMPUS profile, its values in its state, no pin; it hands its owner the peer certificate's
Ed25519 key and then its SHA-512 before any plaintext, in both roles), `src/tempus/dangerous_bees_tempus_conn.silica` (one
connection, both roles: adverts, the binding, the token rules, the whitelist with the token also checked, the two
challenges and proofs, one request and reply, verification of every entry of a received frame, the signer actor that
alone holds the private seed), `src/tempus/bees_tempus_link.part` (the spawns, pasted into a program's root unit),
`tools/bees_tempus_gen.py` (writes the root unit), `tools/bees_tempus_ids.py` (TEST-ONLY identities as a Silica unit),
`tools/bees_tempus_sort.py` (orders a listener's lines by connection), `trials/t5_tempus_link` (port block 23700).
The TLS engine files were not touched in this step.

Observed (silica-999909, Apple Silicon): `make -C trials/t5_tempus_link integrate` 6 passed, 0 failed, repeated runs.
Three pairs of processes over real TLS on 127.0.0.1, the goldens read line by line before recording:
- an edge admitted by a sentinel and its request answered; the sentinel admitted by the edge through the edge's
  whitelist entry;
- refusals at the listener: another peer's advert under the dialer's certificate (binding_refused: the relay case), a
  tempus_bridge token under a certificate that is not whitelisted, an expired token, a proof signed with another key, a
  whitelisted certificate with a tempus_edge token (NQ-4), a P-256 certificate (refused by the link, tempus_cert_key);
- the one key_rotated frame, in both directions (the dialer reads the listener's current kid);
- refusals at the dialer: the listener's sentinel token when the dialer's whitelist is empty.
Not shown in T5: a TLS 1.2 or wrong-ALPN peer against the Silica link (the engine's self-test shows the ALPN refusal in
memory; the Python client covers row 26 in C2); the handshake timeout.

Post-processing in the trial, each a race between independent actors and nothing else: the runtime's reports of normal
ends and the carrier's link_lost report are removed; the stage and peer of a closed_by_peer line are written `(any)`;
a listener's lines are put in the order of its connections.

Found while building: a function may have at most 8 parameters (E1070). A side that sends key_rotated and closes at once
can lose the frame to a connection reset, because the peer's challenge is usually already on its way: the sender now
reads and drops until the peer closes (design section 5).

The Python client's active part (C2's Python half) was written in parallel by a subagent: `tools/bees_tempus_client.py`
dials and listens as a TEMPUS peer over Python's `ssl`; `tools/test_bees_tempus_client.py` 26 tests pass, Python against
Python only. Limit, observed in Python's ssl: a listening Python peer can accept only client certificates it was given
in advance (they are loaded as trust anchors); dialing needs nothing in advance. Not yet run against a Silica node.

New questions (design section 18), none blocking: NQ-8 classical key exchange for TEMPUS (provisional: hybrid only),
NQ-9 whitelist check of gossiped bridge and sentinel entries (provisional: at first contact), NQ-10 certificate validity
dates (provisional: not checked, the token's window is the validity).

Linux goldens needed: `trials/t5_tempus_link` (dangerous_l1, d1, l2, d2, l3, d3); it needs `make -C native tempus tls`.
Needed in existing files: `.gitignore`: `!trials/t5_tempus_link/dangerous_exposure_source`; and the generated root units
`trials/t5_tempus_link/dangerous_[ld][123].silica` are build products (ignore them, as the TRUST nodes' are). Top-level
Makefile tools-test list: nothing new.

Next: T3 (the node part: stores behind connections, join, ticks, the test-only frames).

## 2026-11-18, after T5: Python against the Silica link, and the plan for T3

Observed once, by hand (not yet a trial): the Python client (`tools/bees_tempus_client.py dial`, Python's `ssl`, its own
Ed25519 client certificate) against the Silica listener of `trials/t5_tempus_link` (the BEES engine, profile 1): the
handshake completed, both sides admitted each other, and the `sample` request was answered
(`reply sample_reply entries=[] store=tempus_edge ... typ=tempus_sentinel`; the listener's lines: tls_established with
X25519MLKEM768, admitted tempus_edge, the request). So Python's default key-share offer works against the engine itself.
C2 must make this a trial.

Coordinator, 2026-11-18: the .gitignore lines for T5 are in and the Linux goldens of `trials/t5_tempus_link` are recorded
(byte-identical to the Mac's). NQ-8 to NQ-10 are with the owner; work goes on under the provisional choices. For C2: the
engine is gaining a third profile (2, BEAM distribution over TLS, which accepts classical key exchange and RSA); C2's
trial should show a `tempus/1` listener refusing a peer that offers only what profile 2 accepts, as far as the Python
client can express it (an RSA certificate it can; a key-share group it cannot name).

T3, not started. The design the T5 units were built for:
- The node actor lives in a part pasted into the root unit (`src/tempus/bees_tempus_node.part`, through
  `tools/bees_tempus_gen.py --part`), because it dials (carrier_new stays in the root unit). Its message type is `$NM$`
  of the generator: the carrier contract (it owns the listening link: `(:accepted, link, _)`) and
  `(:bees, op, s1, s2, n, m, who)`. It holds the clock value and builds each connection's `cfg` with it.
- The three `bees_tempus_store_actor` stores speak their own record type to their link, so each gets a small adapter
  actor that turns a store message into a `(:bees, ...)` for the node (entries carried as an encoded frame body).
- The connection actor already hands the node a verified request (op 63) and takes its answer (20 a reply body, 21
  close); it reports a dialed request's outcome (60, 61, 62). Still to add there: role 3 (an accepted connection beyond
  `inflight_max` is opened and closed at once), and the node's own entry check for expiry on every tick.
- Under `control_test_only`: `tick` (op 1 to that store; `done` when the store says the tick ended, op 24) and `clock`;
  draws from a literal list given at start; no timer. Otherwise `send_after` per store and the platform's random edge.
- Trial: three node processes and the Python client where a hostile or listening peer is needed.

## 2026-11-18, NQ-8 to NQ-10 ruled

The owner accepted the three provisional choices: hybrid key exchange only (NQ-8), the whitelist check of a gossiped
bridge or sentinel entry at first contact (NQ-9), certificate dates not checked (NQ-10). Recorded in design section 18;
the provisional marks are gone from `dangerous_bees_tempus_tls.silica` and the Python client (comments only, no code
changed, so `trials/t5_tempus_link` was not rebuilt for it). One PROVISIONAL mark remains in the Python client: how
TRUST's call, cast and result frames are read, which is C3's to decide.

## 2026-11-18, T3 built and verified: networked nodes

New: `src/tempus/bees_tempus_node.part` (the node actor `tnode` and `tempus_node_start`, pasted into the root unit),
`src/tempus/bees_tempus_node.silica.in` (the store adapters `tadp` and the pure helpers of the part; a unit written with
the generator's type names, expanded by `tools/bees_tempus_gen.py unit` into the leaf's `lib/bees_tempus_node.silica`),
`src/tempus/dangerous_bees_tempus_draws.silica` (random bytes into draws for a node that is not a test node),
`tools/bees_tempus_trial.py` (starts the node processes and walks a scenario with the Python client),
`tools/bees_tempus_reports.py` (takes the runtime's reports of normal actor ends out of a node's output line by line,
because two reports can be written into each other; any other reason is kept as a line), `trials/t3_tempus_nodes`
(port block 23800). Changed, all mine: `bees_tempus_store.silica` and `bees_tempus_store_actor.silica` (op 11, the node's
own descriptor replaced), `dangerous_bees_tempus_conn.silica` (role 3: an accepted connection beyond `inflight_max` is
closed when its link is up; nothing else), `tools/bees_tempus_gen.py` (the node's type names, `unit`),
`trials/t5_tempus_link/Makefile` (generation through an included makefile, see below), `tools/trial_ports.py` (one
block added). No other existing file was edited.

Observed (silica-999909, Apple Silicon):
- `make -C trials/t3_tempus_nodes integrate` from a clean leaf: goldens recorded after reading the three outputs line
  by line; the scenario run four times by hand before that gave byte-identical outputs each time.
  Three nodes under `control_test_only` (sentinel S, edges A and B) and the Python client:
  the join of A and of B through S (three samples each; S inserts the joiner after the sample); a tick on an empty view
  (done at once, the node asks its sentinel again); A shuffles with B (initiator and responder, two Silica nodes);
  the Python client shuffles with B as initiator and gets B's entries; `sample`; B shuffles with the listening Python
  client, which answers with one forged entry among good ones: the whole frame is refused, the partner is dropped and
  the sent entry is back in the view at its age (OQ-12); A is stopped: B's shuffle to it fails (connect_failed) and it
  leaves the view; `clock` to 1700 and a tick at S: the entry whose token ended at 1600 is dropped; a token under the
  old kid gets `key_rotated`; with `inflight_max` 2, the third connection at once is closed (`inflight_refused`) and
  the two held ones end by themselves; `clock` past the node's own token: the tick is answered `done`, ticking stops
  and the application is told.
- `trials/t1_tempus_store` 2 passed and `trials/t5_tempus_link` 6 passed after the changes to the store and the
  connection actor, goldens unchanged.
- By hand, not a trial (a copy of the leaf with `control_test_only` false and an edge tick of 400 ms): the stores tick on
  their own timers, the draws come from the random edge (no tick was skipped for want of draws), an edge started before
  its sentinel failed to join four times, waited each time and then joined, and a `tick` frame was closed with no
  reply. Inferred from the code, not measured: that the waits grow from the initial delay and stop at the maximum.

Rules a successor needs:
- A root unit may not call a function of a `dangerous_` unit (E4042) and only a `dangerous_` unit may name
  `dangerous_actor_ref` (E4026). So the part's helpers are in the plain unit `bees_tempus_node`, and the one actor that
  casts to the random edge is in `dangerous_bees_tempus_draws`.
- `bytes` cannot be a parameter name (E1000, reported at the next line). `cons` is not a builtin: `prepend[T,
  mem(normal)](h, t)` inside `sequence proc[mem(normal)]`. A `sequence proc[x]` whose steps do not need `x` is E3010.
- make 3.81 on the Mac lists a directory once: units generated while the makefiles are read are not seen by
  `tools/trial.mk`'s wildcards in the same run (after `make clean` no entry was built). Both TEMPUS leaves that generate
  root units now do it in the rule of an included `.gen.mk`, which makes make start again.
- A node prints everything it has to say about a connection before it answers it, and the adapter sends the view line
  before the store's message that follows a change. That is why the outputs need no reordering. Keep it so: a new line
  that is printed after the reply has gone will race with the next step.
- The scenario waits `quiet()` (0.7 s) after each step: a connection actor is reaped 500 ms after its close.

New questions (design section 18), none blocking, each built provisionally as said there: NQ-11 the time of day on a
node that is not a test node (built: the application's value at start plus the monotonic clock), NQ-12 whether a joiner
keeps the sentinel it joined through (built: no), NQ-13 which requests make a sentinel insert the asker (built: every
sample), NQ-14 what `shuffle_timeout_ms` bounds (built: connect, handshake and the admitted connection each), NQ-15 a
store of another type than the node's own loses its partner at every shuffle (built: the rules as written).

Not built in T3: host names in adverts are not resolved (an address that is not a dotted quad and a port fails the
shuffle, one line); the test-only frames are not checked against the peer's address, because the listening link does
not hand it up (a test node listens on loopback only, which the configuration check of T7 must enforce).

Needed in existing files: `.gitignore`: `!trials/t3_tempus_nodes/dangerous_exposure_source`; build products
`trials/t3_tempus_nodes/dangerous_[sab].silica`, `trials/t3_tempus_nodes/lib/bees_tempus_node.silica`,
`trials/t3_tempus_nodes/.gen.mk`, `trials/t5_tempus_link/.gen.mk`. Linux goldens needed: `trials/t3_tempus_nodes`
(dangerous_s, dangerous_a, dangerous_b); it needs `make -C native tempus tls` and Python's `cryptography`.

Plan for C2 (next):
- Python half: a scenario `c2` in `tools/bees_tempus_trial.py` against one test node and, for row 37, one node without
  `control_test_only` whose three ticks are 3600000 ms (it never ticks in the trial, so its golden is fixed). Rows 2 to
  23 of design 16.2: the client as a listening sentinel uses the fixture certificate `sentinel.pem` (the node's
  whitelist holds its fingerprint: `tempus_ids@fp_hex(2)`); every refusal of row 12 and bound of row 19 through
  the client's `Misbehaviour` functions; row 21 with a held shuffle and a second connection's tick; row 26 with
  `tls12_only`, `other_alpn`, `no_certificate`, `p256_cert` and an RSA certificate; the handshake timeout by a TCP
  connection that sends nothing (the link's bound is the node's `ms`). The handshake of the Python client against the
  engine is already a trial: every step of `t3` is one.
- Silica half: `src/tempus_client/dangerous_bees_tempus_client.silica` can be thin: the connection actor already is a
  TEMPUS peer in both roles and takes the request as bytes. The client needs: a listening position that answers with
  bytes the scenario chose (a small owner actor that plays the node for `tcon`: it gets op 63 and answers 20 or 21),
  dialing with a frame of `bees_tempus_client` (the pure part), and the deliberately wrong frames. What the connection
  actor cannot do on purpose (a wrong proof, silence, a close at a chosen stage) needs either switches in its `cfg` or
  a second, small raw connection actor in the client library; the second keeps the node's code free of test switches.
- Coverage table `trials/c2_tempus_clients/COVERAGE.md`: row, scenario step, for each client.
Then T6 (read design section 17 first; reuse `src/trust` unchanged), C3, and T7's parts.

## 2026-11-18, C2 built and verified: both clients drive the behaviour list

New: `src/tempus_client/bees_tempus_client.part` (the Silica client's active part: `tempus_client_start`, `_dial`, `_set`,
`_answer`, `_close`; pasted into the application's root unit as the node part is, because the carrier's spawn site stays
there; each connection is the node's own `tcon`), `trials/c2_tempus_clients` (port block 23900; five entries:
`dangerous_n` and `dangerous_m`, the same test node on two ports, one per client; `dangerous_o`, not a test node;
`dangerous_cs` and `dangerous_ce`, the Silica client as a sentinel and as an edge, each the thin application
`client.role` with its compiled-in scenario; `COVERAGE.md`, the coverage table). Changed, all mine:
`src/tempus_client/bees_tempus_client.silica` (`show`, `request_store`, `bad_nested`), `src/tempus/bees_tempus_view.silica`
(`cons` exported, nothing else), `tools/bees_tempus_gen.py` (the client's type names, `--part DIR/NAME`, a role file's
own type names as `//$ NAME = text`), `tools/bees_tempus_certs.py` (identities x1 to x4; the first four certificates are
the bytes they were), `tools/bees_tempus_ids.py` (token variants 6 to 13), `tools/bees_tempus_client.py`
(`rsa_certificate`, `rsa_cert`), `tools/test_bees_tempus_client.py` (one test more: 27), `tools/bees_tempus_trial.py`
(scenario `c2`; a node's standard error is read apart, see below), `lib/tempus_ids.silica` of `t3_tempus_nodes` and
`t5_tempus_link` (rewritten by the tool: more functions, the old values unchanged), `tools/trial_ports.py` (one block
added), design sections 16.4 and 18. No other existing file was edited.

How the trial works. `tools/bees_tempus_trial.py c2` starts node O, then walks the Python client's steps against node N
(its sentinel is the Python client's listener, started first), then starts `dangerous_cs`, node M (which joins through
it), waits for `done`, starts `dangerous_ce` and waits for `done`. The two scenarios are the same steps (the numbers of
`cs.role` and `ce.role`); Python adds P1 to P8. With ports and connection numbers set aside, N's and M's outputs are the
same line for line through every common step; they differ only where Python's extra steps stand and in the ages those
steps add. That is the evidence that the two clients, which share no code, drive a node alike.

Rules a successor needs (added to those of the T3 entry):
- A string-returning call written inline in a cast's message faults the runtime with no line (SD-45; the process ends
  with signal 5). Bind the string to a name first. It cost one build here (`node.role`, the refresh).
- The runtime writes its actor reports to standard error in pieces. When both streams go to one pty the pieces land
  inside program lines and inside each other, and no line filter can take them out again (seen in the client programs,
  whose connection actors end in pairs). `Node` in `tools/bees_tempus_trial.py` now reads standard error apart and
  writes, before the exit line, only the reasons that are not ordinary ends and any line that is no report.
  `tools/bees_tempus_reports.py` still runs afterwards for the `closed_by_peer` lines and the addresses.
- An entry already in a view keeps its age when a shuffle offers it older: to be the oldest entry a client must be
  absent from the view and then shuffle itself in at a high age (`old()` in `ce.role`).
- A role file may not use a `$NAME$` the generator does not know; its own record types go in `//$ NAME = { ... }` lines.
- The Silica client's connection bound (`ms`) must be longer than the node's `shuffle_timeout_ms`, or a tick that waits
  for a failing shuffle times out at the client first.
- One build in five of this leaf (the second `make integrate`, on a loaded machine) gave a `silica.atoms` without the
  atoms of the stdlib carrier unit; every listening link then ended at start with `no case arm matched` and the node
  printed nothing. The same sources built whole the next time. The leaf's Makefile now checks the file before the run.
  Not reproduced on demand, so no SD entry is written; the bad file is described in the hand-back report.

New questions (design section 18), none blocking, each built provisionally as said there: NQ-16 a received entry that is
older than the entry of the same peer the node has just sent replaces it (built: the rules of 3.4 as written;
recommended: keep the younger of the two), NQ-17 whether a node whose own token has expired still answers peers (built:
it does, as T3 left it; recommended: keep that).

Not built in C2, and why: the Silica client does not cause row 12 "no proof", row 18 "closes after the advert" or
"silent before its proof", or row 20 (the connection actor it shares with the node has no switch for them, and adding
one would put test switches into the node's code); the Python client causes all four. Row 19's "memory flat over many"
is not measured in the trial. Row 26: a peer that offers only a classical key-exchange group cannot be made with
Python's `ssl`; an RSA-certificate peer is refused, but as "no certificate", because the node's certificate request
names Ed25519 only and Python's TLS library then sends none.

What TEMPUS configuration needs from the store reader and packer (read: `development-plan/spikes/N0d-store-config.md`;
nothing of that agent's files was edited). The packer's table has no TEMPUS rows yet (the spike says so). Needed, each a
row of `GROUPS` in `tools/bees_pack.py`, at most four fields per record, integers, byte strings and booleans only:
- the index record's `mode` as the byte strings `tempus` and `tempus-trust` (design section 11: the mode is never a
  Silica atom), and `tools/bees_conf.py` accepting `{mode, tempus}`, `{mode, tempus-trust}` (bare and quoted) and the
  `tempus` section with the bounds of section 11;
- tempus net: `role`, `listen_address`, `listener` (the carrier text, as the trust record has it), `control_test_only`;
- tempus stores: `edge`, `bridge`, `sentinel`, each `{ capacity, shuffle_length, tick_ms }`;
- tempus time: `shuffle_timeout_ms` as a number and as the text the carrier's dial budget takes, `inflight_max`,
  `clock_skew_ms`, `join { initial_ms, max_ms }`;
- tempus producer: `kid`, `key` (32 bytes);
- tempus identity: `cert_pem`, `key_pem` (secret), and, computed by the packer as it computes `fp` for TRUST, the 32-byte
  seed (secret), the public key and the peer id (SHA-512 of the key): the node's signer takes the seed, not a PEM;
- tempus sentinel, one per entry: the address as `a.b.c.d:port` text and the whitelist fingerprint its `CertName` names;
- tempus peer, one per whitelist entry: `cert`, `fp` (128 hex characters), `spec { all, perms }`;
- tempus specs: `edge_spec`, `bridge_spec`, `sentinel_spec`, each `{ all, perms }`;
- a generated reader `bees_cfg_tempus` with `fresh`, `take`, `finish`, `show`, and its reader actor; for `tempus-trust`
  ONE reader that gives both configurations, because one build may claim a backing path once (the spike's finding 6);
- the TLS engine takes certificate and key as file paths today; bytes are N0c's later step for TRUST and TEMPUS alike.
The node part already takes every one of these as an argument of `tempus_node_start` (idn, net, sz, tst), so the
conversion is in the application: it builds those four records from the reader's value.

Plan for the next milestones.
- T7's parts that need no reader (small, do first): (1) `tempus_node_start` refuses `control_test_only` unless the
  listen text is a loopback one (`listen:PORT`, not `listen:any:PORT`): one boot line, the application is told, the node
  does not listen; a boot-refusal entry in a new leaf `trials/c4_tempus_boot` beside entries for each refusal the node
  part can make from its arguments (shuffle_length above capacity, a role whose token has another typ, an empty
  producer key). (2) `tools/bees_tempus_conf.py` (new, mine): the `tempus` section's table and bounds as a validator
  with tests, written so that `tools/bees_conf.py` (not mine) can call it; the edit there is the owner's of that file.
- T6 (read design section 17 first, then `src/trust/dangerous_bees_trust.silica` for how a TRUST node calls out): a
  node part `bees_tempus_bridge.part` that starts `tempus_node_start` and the TRUST node in one program (two keys; the
  engine's profile 0 and 1 are both in place). In `tn_request` the kinds 12 and 13 (call, cast) go, on a bridge, to a
  new per-peer table actor (score by TRUST's rules, rate and in-flight bounds passed in by the application with literal
  ceilings), then to the per-type permission spec (default none), then to the application's exported function; the
  reply is TRUST's result frame. The bridge forwards nothing by itself: the exported function calls onward through the
  TRUST side. N5 is changing `src/trust` for multiplexing: read its progress note before choosing what to call, and if
  the bridge needs a change there, list it and stop short.
- C3: `call` and `cast` in both clients (the Python client's reading of TRUST's frames is marked PROVISIONAL), a library
  function that picks a bridge at random from a sample, and a trial with two bridges and one TRUST node (rows 24, 25,
  29 to 36), written as `c2` is: one scenario, twice.

## 2026-11-19, C2 closed: goldens recorded (successor agent)

The previous agent stopped before recording the goldens of `trials/c2_tempus_clients` (its last run, 2026-11-18 17:36,
had passed the Python client's 78 requests with no goldens). Nothing had changed since that run. Done now: a clean
rebuild and run (`make integrate`), then `make record-golden`; the five outputs of the run before the rework of `ce.role`
step 43, of the rebuild and of the recording run are byte-identical where the sources were the same (three identical
runs of the current sources). Read line by line before recording: node O, the two Silica client outputs, node M; node
N against M with ports and connection numbers set aside (the difference is Python's extra steps P1 to P8 and the ages
they add, as the entry above says). Small things seen, not changed: an unknown key in a request is audited as
`not a request: unknown kind`, and nesting too deep as `bad_tag`; both are refused as the row requires.

Needed in existing files (`.gitignore`, the coordinator's): `!trials/c2_tempus_clients/dangerous_exposure_source`; build
products `trials/c2_tempus_clients/dangerous_{n,m,o,cs,ce}.silica`, `trials/c2_tempus_clients/lib/bees_tempus_node.silica`,
`trials/c2_tempus_clients/.gen.mk`. Linux goldens needed: `trials/c2_tempus_clients` (five entries; it needs `make -C
native tempus tls` and Python's `cryptography`).

## 2026-11-19, NQ-16 ruled (b) and built; T6 and C3 built and verified; T7 in part

NQ-16 and NQ-17 ruled by the owner (design section 18). NQ-16 (b) built: `bees_tempus_view@prefer_sent(received, sent)`
puts the sent entry of a peer in place of a received older one before the merge (at equal age the received one stays: it
may carry a newer token); `bees_tempus_store` applies it at both merges; the Python models
(`tools/bees_tempus_view_model.py`, `bees_tempus_store_model.py`) the same. Re-recorded after reading: `t1_tempus_store`
(actors, steps: equal to the independent model) and `c2_tempus_clients` (ce, m, n: x3 stays at 6). Unchanged: t0, t3.

T6, the bridge. New: `src/tempus/bees_tempus_bridge.silica` (the table actor `tbr`: the per-peer score by TRUST's rule,
the per-peer rate and in-flight bounds, the bridge's in-flight bound, entries pruned when their token expires and the
soonest-expiring dropped when the table is full; then TRUST's request frame, the forbidden guard, the per-type spec, the
MFA table and its type check; the per-request actor `trq`; `tonw`, the reply-to of one TRUST call; `lim_why`, the literal
ceilings of 17.5), `src/tempus/bees_tempus_bridge.part` (`tempus_bridge_start(app, idn, net, sz, tst, lim)`,
`tempus_bridge_onward(rq, addr, m, f, arity, args)`). Changed, all mine: `bees_tempus_node.part` (kinds 12 and 13 go to
the application actor on a bridge, the node's clock in `m`; `tempus_node_boot` and the boot refusal in
`tempus_node_start`), `bees_tempus_node.silica.in` (`boot_why`, `loopback`), `src/tempus_client/bees_tempus_client.silica`
(`call_frame`, `cast_frame`, `pick_bridge`, `show` of a result), `tools/bees_tempus_gen.py` (`bridge`, `spec`, the types
`$BL$`, `$BTL$`), `tools/bees_tempus_client.py` (`call_frame`, `result_value`), `tools/bees_tempus_trial.py` (scenario
`c3`). The bridge application answers each admitted request once (NQ-18); BEES forwards nothing by itself. `src/trust`,
`tools/bees_trust_gen.py` and `tools/bees_config_trust.py` are used as they are: no change there is needed.

C3. `trials/c3_tempus_bridge` (port block 24200): node T (TRUST), bridges B1 and B2, the Silica client (identity x2,
`roles/c.role`, 20 steps) and the Python client (the same steps with its own identity, then rows 29 and 33, the rate
bound, a second edge served while the first is at its bound, and the bridge quarantined at T by the trial, 17.7). Each
program is built in its own directory under `nodes/` (each TRUST side needs its own `bees.config`); the top Makefile copies
the four outputs beside it and compares them. Verified: two runs from a fresh build each, byte-identical; goldens recorded
after reading all four outputs. `COVERAGE.md` is the table for rows 24, 25 and 29 to 36.

T7 in part. `tempus_node_boot(idn, net, sz, tst)` refuses, with one line, the values section 8 bounds and the rule that a
test node listens on loopback only (`trials/c4_tempus_boot`, five entries, port block 24300, goldens recorded after
reading). `tools/bees_tempus_conf.py` (new) checks the three SEMP mode spellings (bare and quoted `tempus-trust`) and the
`tempus` section of design section 11, using `tools/bees_conf.py`'s grammar and checks without changing it;
`tools/test_bees_tempus_conf.py`, 7 tests, pass. What TEMPUS configuration needs from N0d (the store reader and packer)
is the list in the C2 entry above, unchanged; the conversion of these values into the node's four argument records is
the application's, once the reader exists.

Rules a successor needs (added to those above):
- E4045 at the carrier spawn of a bridge root with 33 units; 32 compiled (silica-defects.md, the 2026-11-19 T6 note). The
  bridge leaves out `bees_reporter`; keep a bridge program at 32 units or fewer until that is understood.
- Silica will not take `cast` as the name of a function even when qualified (`bees_tempus_client@cast(...)`: the call is
  read as the builtin, E2005 "argument count mismatch" at the enclosing call): the frame builders are `call_frame` and
  `cast_frame`. `run`, `result`, `fail` were renamed too (`rq_run`, `rq_result`, `rq_fail`) after an E1069 in the unit.
- A tuple pattern with an atom in a sequence binding (`(:bees, op: int64, ...) <- msg;`) is E1069; take the message apart
  in a `case`.
- The compiler exits after each unit (code 75) and is run again by tools/silica.mk's loop: one direct call compiles one
  unit only. A hand-built bisect must loop as that file does.
- An admitted peer's frame that is no TEMPUS request is refused by the connection actor and never reaches the bridge's
  score; a bridge's hostile steps use TRUST requests that fail TRUST's own checks (an arity that is not the arguments'
  length).
- `make run` of the bridge leaf rebuilds all four programs (tools/trial.mk compiles on every build): about ten minutes.

New questions (design section 18, none blocking, each built provisionally as said there): NQ-18 how the bridge application
runs a request (built: one message per admitted request, answered once), NQ-19 what raises an edge's score (built: as
listed there; recommended: also the connection actor's refusals), NQ-20 when a cast is closed (built: at its outcome),
NQ-21 the bare `tempus-trust` in tools/bees_conf.py's reader (built: a stand-in in tools/bees_tempus_conf.py).

Needed in existing files (not made):
- `tools/bees_conf.py` (owner of the mode and the reader): `TOP_KEYS` with `tempus`; `mode` taking `tempus` and
  `tempus-trust` (the reader taking the bare spelling as the value of `mode` only); a call of
  `bees_tempus_conf.tempus_section(top, mode, fname)`; the trust section validated under `tempus-trust` as under `trust`.
- `.gitignore`: build products `trials/c3_tempus_bridge/nodes/*/dangerous_*.silica`, `trials/c3_tempus_bridge/nodes/*/.gen.mk`,
  `trials/c3_tempus_bridge/nodes/b?/trust_root.part`, the generated `lib/bees_trust_conf.*`, `lib/bees_trust_mfa.silica`,
  `lib/bees_tempus_spec.silica`, `lib/bees_tempus_node.silica`, `lib/tempus_ids.silica` under `nodes/*`, the four
  `trials/c3_tempus_bridge/*.sout`; `!trials/c3_tempus_bridge/nodes/*/dangerous_exposure_source`;
  `trials/c4_tempus_boot/dangerous_*.silica`, `trials/c4_tempus_boot/lib/bees_tempus_node.silica`,
  `trials/c4_tempus_boot/lib/tempus_ids.silica`, `trials/c4_tempus_boot/.gen.mk`, `!trials/c4_tempus_boot/dangerous_exposure_source`.
- Linux goldens: `trials/c3_tempus_bridge` (t, b1, b2, c; needs `make -C native tempus tls`, Python's `cryptography`, and
  the N4.1 certificates), `trials/c4_tempus_boot` (five entries), and the re-recorded `t1_tempus_store` and
  `c2_tempus_clients`.

Plan for what remains:
- T7's store-carrier part: once N0d's reader and packer have TEMPUS rows (the list in the C2 entry), a leaf like
  `d*_store_*` that reads a `tempus` and a `tempus-trust` configuration and starts a node and a bridge from the reader's
  value; the bridge's limits stay the application's (OQ-25).
- The edits above in tools/bees_conf.py (its owner), then tools/bees_tempus_conf.py's stand-ins go.
- T8 (churn and soak, measurements) has not begun; NQ-11 to NQ-15 and NQ-18 to NQ-21 are with the owner.

Addendum, 2026-11-19 (Linux run of c3_tempus_bridge): every TRUST TLS open failed there with `tls_identity_error`.
Cause: `tools/bees_config_trust.py` writes the certificates' ABSOLUTE paths into `lib/bees_trust_conf.silica`
(`tls_server_spec`, `tls_client_spec`), and the leaf's node Makefiles regenerated only when `.gen.mk` was older than its
inputs, so the synced Mac units (`/Users/yenrab/project-bees/...`) were compiled on Linux. `trials/n4_trust_tls` regenerates
at every make, so it never showed this. Fixed in `nodes/{t,b1,b2}/Makefile`: a stamp `.gen.root` holding the tree's path,
rewritten only when it differs, is an input of `.gen.mk`. The Mac units and goldens are unchanged. `.gitignore` also needs
`trials/c3_tempus_bridge/nodes/*/.gen.root`.

## 2026-11-19, the rulings on NQ-11 to NQ-20 built

The owner ruled NQ-11 to NQ-20 (design section 18). NQ-13, NQ-18 and NQ-20 were ruled as built: nothing changed but
the text. NQ-16 and NQ-17 were built or kept in the entry above. Built now, each with what shows it:

- NQ-11, the clock. New native function `bees_tempus_wall_clock` (`native/tempus/silica_bees_tempus.c`, C11
  `timespec_get`, whole seconds since 1970 as 8 bytes in an ETF binary; a failure of the operating system or a time
  before 1970 is tag 1, no made-up time), its sidecar entry, `dangerous_bees_tempus_native@wall_etf`, op 5 of the edge
  worker `ted` (answer kind 35). A node that is not a test node has a clock actor
  (`dangerous_bees_tempus_draws@tck`): it asks at start and once a second and tells the node each reading (op 130); the
  node's clock is the last reading (`tn_clock`, `tn_now`). Such a node does not listen, join or tick before its first
  reading (`tempus_listen` is called from `tn_clock`). The application's start value plus the monotonic clock is gone;
  `tst.now` is read only under `control_test_only`. Observed: `make -C native tempus-selftest` (three lines more: the
  shape, agreement with the C library's `time()`, a second reading not earlier); `trials/c2_tempus_clients`, node O:
  `clock: the system clock is read` before it listens; the trial's ordinary token (valid 1000 to 3000) is refused as
  expired (P9), a token that begins at 3900000000 as not valid yet (P10), a token valid 1000 to 4000000000 admitted
  (43). Before the change O admitted P9's token (its clock ran on from the trial's 1500). Not shown by a trial, read
  from the code only: a reading that fails, and a reading earlier than the one before (a trial cannot set the
  machine's clock). What those do is design section 10 and question NQ-22.
- NQ-12. A joiner keeps the sentinel it joined through: the connection actor's message 60 now carries the admitted
  peer's descriptor and type (as 63 does); when a sample was answered by a peer whose token says `tempus_sentinel`, the
  node inserts that peer into its sentinel store at age 0 after the sample's entries (`tn_keep_sentinel`, waiting kind
  9). Observed: `trials/t3_tempus_nodes` (A and B hold `9e1113ab@0` in the sentinel store after each answered sample;
  it was empty), `trials/c2_tempus_clients` (N, M).
- NQ-14. One bound from dial to close. `tempus_dial` and `tempus_conn` (`bees_tempus_link.part`) turn
  `shuffle_timeout_ms` into a deadline (the monotonic clock's value in ms) once per connection; the listener does the
  same for an accepted link at the accept. The link's handshake timer (`dangerous_bees_tempus_tls@tlnk`) and the
  connection actor's timer are each armed with what is left of it; the carrier's connect budget is the same number
  from the same moment. `cfg.ms` in the connection actor and `hs_ms` in a link are therefore DEADLINES now, not
  durations (`hs_ms` in the listener stays a duration). It is one deadline shared by the stage timers and not one
  timer object: a single timer in the connection actor would race the carrier's own connect budget at the same
  instant, and which line a trial then printed would not be fixed. Observed: `trials/c2_tempus_clients` P11: a client
  that connects, waits 1 s, does its handshake and says nothing is closed 2.0 s after the connect (the scenario asserts
  1.7 to 2.75 s; one bound per stage gave 3.0 s), node line `timeout ... stage advert`. The dialing side uses the same
  deadline code and is not timed by a trial (inferred). The wait for the node's own answer (phase 16) is not bounded
  by this, as before: the node always answers, and a bridge's call timeout may be longer.
- NQ-15. In a store that is not of the node's own type the partner that answered re-enters at age 0, after the merge
  and before the sent entries fill the room (`bees_tempus_store@reply`); a failed shuffle still leaves the partner out.
  The Python store model the same. Observed: `trials/t1_tempus_store` entry `steps`, part 3 (ten lines more, each
  equal to the independent model's): a store of another type holding three entries keeps three through twelve ticks
  answered with nothing; `tools/test_bees_tempus_store.py`: by the rules before the ruling the same store is empty
  after three ticks, and a model run of 500 rounds of a sentinel among two edges that shuffle with each other keeps
  both edges at every round where the old rules reach none at round 3 and stay there (with five edges and room for
  four: always four, where the old rules fell to two). `trials/t3_tempus_nodes`: S's edge store after its shuffle is
  `1fae2ad7@0 b19edad2@1` (it was `b19edad2@1`). `trials/c2_tempus_clients`: the samples s4 and s9.
- NQ-19. The connection actor tells the node of every refusal of an accepted peer whose identity it knows (message 67;
  `report` in `dangerous_bees_tempus_conn`), the node passes it to the bridge's table actor (83), which raises that
  peer's score by one (`conn_refused` in `bees_tempus_bridge`). The identity is the SHA-512 of the key of the peer's TLS
  certificate, never the id the advert claims (a refusal before the id was checked asks the edge for that hash first).
  A refusal makes a NEW entry only when the producer's signature on the token had verified; before that it raises an
  existing entry only (question NQ-23 says why). Not counted: this node's own random or signer failure, `key_rotated`,
  a timeout while the node is not waiting for the peer. Observed: `trials/c3_tempus_bridge`, golden `b1`, the last
  33 lines: edge Q goes from no entry to score 6 through six refused connections (`pop_failed`, `protocol_error`
  twice, `admission_refused` twice, `timeout`), and its first good request is `bridge_refused ... score 6 is above the
  limit 5`; edge Z, never served, gets no entry from two bad tokens and is then served.

Goldens re-recorded on the Mac, each after reading the difference, each then passed three runs in a row:
`t1_tempus_store/steps`, `t3_tempus_nodes/dangerous_{a,b,s}`, `c2_tempus_clients/dangerous_{cs,m,n,o}`,
`c3_tempus_bridge/b1`. Unchanged and passing: t0, t1 `actors`, t2, t4, t5_tempus_tls, t5_tempus_link, c2 `ce`, c3 `t`,
`b2`, `c`, c4. The Linux twins of the nine re-recorded files are stale until re-recorded there (needs
`make -C native tempus tls`; `tools/test_bees_tempus_store.py` fails on `steps.linux_x86_64.scout` until then).

Rules a successor needs (added to those above):
- Message numbers. The connection actor tells its `cfg.node`; a client's `cfg.node` is the client application, which
  already uses 66 ("the client listens"). So the refusal report is 67. Check `src/tempus_client/bees_tempus_client.part`
  before taking a number for a new message of the connection actor.
- The edge worker answers with TRUST's five-field tuple; the node's messages have seven fields. Anything the node wants
  from the edge goes through a small actor in `dangerous_bees_tempus_draws` (the draw converter, the clock actor).
- A node that is not a test node needs tokens that are valid by the machine's clock: in a trial, fixture 14 (valid 1000
  to 4000000000) or the like. No line of such a node may print a time.
- `cfg.ms` handed to `tempus_dial`, `tempus_accept` or `tempus_conn` is still a duration; `tempus_conn_at` puts the
  deadline in its place. Nothing else may build a connection actor's state.
- An interrupted build of a TEMPUS leaf (make stopped while compiling) rebuilt whole at the next make: no stale unit
  was seen.

New questions (design section 18): NQ-22 (a system clock that fails or goes back, and how often it is read; built: at
start no start until a reading, later the last reading is kept; a step back is followed with one line; read once a
second), NQ-23 (which refused connections make a new score entry; built: only those after the token verified). NQ-21 is
still open.

Ruled 2026-11-20: NQ-22 (a step back is followed; a clock that fails after a good reading now stops the node admitting
and ticking until it is read again, audit line `clock_refused`; read once a second) and NQ-23 (new score entries only
after the token verified; the score limit is the bridge application's value). The failing-clock change is built and the
eight TEMPUS trials pass with it on the Mac; no golden changed, because no trial can make the clock fail, so that path
is still read from the code only. Also ruled that day: a file that configures BEAM together with TRUST or with TEMPUS
is refused (`tools/bees_conf.py`, `tools/bees_tempus_conf.py`, development-plan/bees-config-file.md section 3).

What remains is the plan of the entry above (T7's store-carrier part, the edits in tools/bees_conf.py by its owner, T8).
