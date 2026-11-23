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

Ruled later on 2026-11-20 and built: the clock's behaviour is configured (design sections 10 and 11, NQ-22). Four new
keys of the `tempus` section, none with a default: `clock_back` (`follow`, `hold`, `stop`: a reading earlier than the
node's time), `clock_back_limit_s` (0 to 86400; required under `stop`, refused otherwise), `clock_fail` (`continue`,
`pause`: a reading that fails after a good one) and `clock_read_ms` (100 to 60000; the literal `read_every_ms` is gone).
- The path: `tools/bees_tempus_conf.py` validates them; the application passes them in the node's `net` record as
  `back` (1, 2, 3), `blim`, `fail` (1, 2) and `every` (`$NN$` and `$NC$` in `tools/bees_tempus_gen.py`);
  `bees_tempus_node@boot_why` refuses a choice outside its set; the clock actor's state carries `every`.
- The decision is pure: `bees_tempus_node@clock_back(last, reading, choice, limit)` and
  `bees_tempus_node@clock_turn(state, last, reading, choices)` in `src/tempus/bees_tempus_node.silica.in`; `tn_clock`
  prints the lines and does what they say. Clock states (`v.ck`): 5 holds its time, 6 goes on with its last reading, 4
  stopped, added to 0, 1, 2, 3. A stopped node closes accepted connections through role 5 of the connection actor, audit
  line `clock_stopped`, and tells its application with op 87.
- Shown by a trial: `trials/t0_tempus_clock` (new, Mac golden): every choice, both sides of the limit, the end of a hold,
  both choices for a failed reading, with readings as numbers; `trials/c4_tempus_boot`, new entry
  `dangerous_clockback` (Mac golden): a node with no `clock_back` choice is refused at boot;
  `tools/test_bees_tempus_conf.py`: six new tests of the keys. Read from the code only: the node acting on the
  decision with a real clock (`tn_clock`, `tn_timer`, `tn_accepted`, role 5), because a trial cannot set the machine's
  clock or make it fail.
- The trials' nodes pass `follow`, `pause`, 1000 ms (what was built before): no existing golden changed on the Mac. The
  Linux goldens of the two new outputs are not recorded.
- Rules a successor needs: a plain binding may not stand between a sequence's steps and its `produces` (E1040); `head`
  is a builtin name (E2020). Application ops 86 and 87 reach a bridge's application through the table actor's
  `pass_on`. A test node's `clock` frame does not go through `clock_back` (open, not ruled).

Ruled later still on 2026-11-20 and built: the test frames are out of the library (design 16.3, the new RULED line
under OQ-20). The owner saw that the `tick` and `clock` handlers were compiled into every node behind the start value
`control_test_only`, and ruled: "Move the test frames out of the library into a unit only test programs list in their
build. A production build does not contain the handlers at all."
- The test unit: `src/tempus_test/bees_tempus_test.silica` and `src/tempus_test/bees_tempus_test.atoms` (the atoms
  `tick`, `clock`, `ms`, `wait`, `later`). It holds the frames' encoders and decoders, the actor `tdrv` that acts on
  them, the banner and the loopback check. `src/tempus_test` is not a directory a production application lists. A
  test program lists the unit and the atoms file (in a trial: two links in `lib/` and `--use bees_tempus_test`).
- Gone from the library: kinds 9 and 10, `enc_tick`, `enc_clock`, `dec_tick`, `dec_clock` (`bees_tempus_frame`); the
  atoms `tick`, `clock`, `ms` (`bees_tempus.atoms`); `tn_rq_tick`, `tn_rq_clock`, the banner, the audit event
  `test_only_refused`, the start record `{ test, now, draws }` (`bees_tempus_node.part`); `tick/1` and `clock/1` of
  `bees_tempus_client` (the scenarios call `bees_tempus_test@tick`, `@clock`, `@clock_later`).
- The hook: the node's last start argument is `drv`, `{ driven, ext, draws }` (`$NT$`). `driven` true: no clock
  actor, no store timers, literal draws and view lines (what `test` did), and three things for `ext`: the node
  introduces itself (133); a well-formed frame of no kind from an admitted peer is handed over (the connection actor
  sends it to the node as 68 only when its `cfg.ext` is true, which is the node's `driven`); a tick or a reading that
  carried a tag is reported when it has ended or is taken (131, 132, with the actor reference that came with it). The
  driver casts the node the clock actor's and the timers' own messages: 130 (n: seconds or -1; m: a tag) and 1 (n: a
  tag; m: the store). `ext` answers the connection actor 20, 21 or the new 22 (refuse as a frame that is not a
  request: the same audit line and the same score at a bridge as on a production node). `boot_why` refuses `driven`
  on a listen address that is not loopback; the test unit checks the listen text the node gives it as well.
- The `done` of a tick keeps its timing: the test unit casts the tick with the connection's number as the tag, the
  node reports 131 where it answered `done` before (`tn_done`: at the end of the shuffle, or at once), and the unit
  answers the connection. One more actor hop, the same moment.
- A `clock` frame is now a clock reading: it goes through `clock_turn` with the node's choices, `ms` -1 says the clock
  could not be read, and the form with `wait` and `later` carries a second reading for later (a node that waits for
  its clock closes every connection, so the reading that ends the wait cannot come in a frame).
- The configuration key `control_test_only` is removed. `tools/bees_tempus_conf.py` refuses it with either value and
  says where the test frames went.
- New trial `trials/t6_tempus_clock` (Mac golden; port block 24500; scenario `t6` of `tools/bees_tempus_trial.py`), three
  programs each in its own directory with its own unit list. H (hold, continue): the hold begins, a token that ended
  inside the held span is refused, a reading still behind prints nothing, the hold ends; a failed reading, the node
  goes on, 86. S (stop with limit 60, pause): the wait for the clock with its line, 86, a connection closed
  `clock_refused`, the join retry that falls due and waits, `read again` and the dial at once; a step back of 30 s
  followed; a step back of 100 s: the stop line, 87, a connection closed `clock_stopped`, and no resume at a later
  good reading. P (no unit and no atom of the test unit in its build, the machine's clock): `tick` and both `clock`
  forms refused `protocol_error ... not a request: unknown_atom`. `make production-check` (part of integrate) searches
  P's compiled units (.sams), atom table, unit list and linked program for the unit's name, functions, atoms and
  banner, finds none, and finds them in H.
- Goldens re-recorded on the Mac, each after reading the difference. One line more and the banner moved up (the
  banner is printed by the test unit before the node's first reading; the node then says `clock: the system clock is
  read` and listens): `t3_tempus_nodes/dangerous_{a,b,s}`, `c2_tempus_clients/dangerous_{n,m}`, `c3_tempus_bridge/b1`,
  `b2`. The refusal text: `c2_tempus_clients/dangerous_o` (two lines), `c4_tempus_boot/dangerous_any` (`an externally
  driven node on a listen address that is not loopback`). `t2_tempus_frames/frames`: the tick and clock lines now say
  that the library refuses the frame and the test unit reads it, four new frames (no time, a later reading, before
  -1, a wait of 0) in place of `clock before 0`, and four lines of the unit's loopback check. New: t6's `h`, `s`, `p`.
  The Linux twins of all of these are stale until re-recorded there; until then `tools/test_bees_tempus_client.py`
  fails twice on `frames.linux_x86_64.scout` (it reads every platform's golden; with the Mac golden alone it passes).
- Still read from the code only: the clock actor itself (the native reading, its timer) and a system clock that cannot
  be read at start.
- Node O of `trials/c2_tempus_clients` is not the proof of absence: that trial builds five programs in one directory
  with one unit list, which holds the test unit for N and M, and the build links every listed unit into every program.
  O's root unit does not use the unit and O is not driven, so O refuses a tick as a frame of no kind (its golden's two
  lines changed from `test_only_refused` to `protocol_error ... not a request: unknown kind`), but the unit's code is
  in O's linked program. The proof of absence is node P of t6, built in a directory of its own.
- Rules a successor needs: a trial node that needs ticks or a set clock is a test program: `x <- bees_tempus_test@start(now)`,
  `drv { driven: true, ext: x, draws }`. Message numbers taken at the node: 68, 131, 132, 133 (and 22 as an answer to
  the connection actor). A program whose leaf lists the test atoms holds the atom `tick`, so its refusal of a tick
  frame reads `unknown kind`; a program without them reads `unknown_atom`. A connection actor's `cfg` has one field
  more, `ext` (a client passes false).

What remains is the plan of the entry above (T7's store-carrier part, the edits in tools/bees_conf.py by its owner, T8).

## 2026-11-20, the two clients moved to example_tempus_clients (owner's request)

The owner asked for the Python and Silica clients to leave the library and the tools: they are examples, not production
code. Moved with `git mv`, nothing in them changed but the paths they name:

- `src/tempus_client/bees_tempus_client.silica` and `bees_tempus_client.part` to `example_tempus_clients/silica/`;
  `src/tempus_client` is gone.
- `tools/bees_tempus_client.py` and `tools/test_bees_tempus_client.py` to `example_tempus_clients/python/`.
- New: `example_tempus_clients/README.md` (examples only, not for production; what each directory holds; how the trials
  use them) and `example_tempus_clients/writing-a-tempus-client.md` (what a client in any language has to do, each
  statement checked against the node's code and the two examples; its last section lists what was not checked).
- What follows the move: the three `lib/bees_tempus_client.silica` links (`trials/t2_tempus_frames`,
  `trials/c2_tempus_clients`, `trials/c3_tempus_bridge/nodes/c`) point to the new place; `tools/bees_tempus_gen.py`
  takes a `--part` with a slash as a path from the BEES root (it was a path under `src`), and the two Makefiles that
  paste the client part name `example_tempus_clients/silica/bees_tempus_client.part`; `tools/bees_tempus_trial.py`,
  `bees_tempus_fixtures.py`, `bees_tempus_ids.py` and `test_bees_tempus_admission.py` add
  `example_tempus_clients/python` to their import path; the top-level `Makefile` runs the client's tests from the new
  place; comments and documents that named the old paths name the new ones. Earlier entries of this file keep the
  paths as they were on their day.
- No golden changed: the generated root units are the same text (the generator names a part by its file name only),
  and the twelve TEMPUS trials pass on the Mac against the goldens as they were. The test unit `src/tempus_test` did
  not move.
- Still true of the tools: the trial driver and the fixture tools import the Python example, so the trials depend on
  `example_tempus_clients/python`.

2026-11-20, a Swift example client (owner's request): `example_tempus_clients/swift` (a Swift package over the installed
OpenSSL, no Xcode and nothing fetched; an example only, with no misbehaviour and no tick or clock frame), its unit tests
against the goldens of `trials/t2_tempus_frames`, and the trial `trials/c5_tempus_swift` (nodes N and P and the Python
example, driven by `tools/bees_tempus_swift_trial.py`; Mac goldens only, because there is no Swift on the Linux machine).

2026-11-20, a Kotlin example client (owner's request): `example_tempus_clients/kotlin` (Kotlin on the JDK's own TLS and
Ed25519, no other library and nothing fetched; it needs OpenJDK 27, because the TLS of OpenJDK 25 has no X25519MLKEM768;
an example only, with no misbehaviour and no tick or clock frame), its 36 tests against the goldens of
`trials/t2_tempus_frames` and `trials/t4_tempus_admission` and the tokens of `tools/bees_tempus_ids.py`, and the trial
`trials/c6_tempus_kotlin` (nodes K and Q and the Python example as the misbehaving peer, walked by `Walk.kt` with
`walk.py`; Mac goldens only, because there is no Kotlin compiler on the Linux machine, where the trial fails and says so;
not run against a bridge).

2026-11-23, the Python extension as a TEMPUS node (owner's ruling of that day: "nodes on non-silica are the plan"; the
non-Silica code is called an extension from now on). `example_tempus_clients/python` is now seven modules an
application imports (`bees_tempus_codec`, `bees_tempus_admission`, `bees_tempus_peer`, `bees_tempus_view`,
`bees_tempus_store`, `bees_tempus_config`, `bees_tempus_node`) and one test-support module, `bees_tempus_testing.py`
(the tick and clock frames, token making, fixed seeds and nonces, misbehaving peers, and a clock, timers and draws a
test steps by hand); `bees_tempus_client.py` is kept as a thin module of the old name, because the trial tools import
it. A node of the extension is an edge or a sentinel; the role bridge is refused (no TRUST in Python). It has the
stores, the join, its own shuffles, admission in the node's order with the whitelist rule, the limits, the clock's
choices, the configuration's keys and refusals, and the Silica node's lines. A test gives a node its clock, timers and
draws through the constructor; no frame does.
- Fixed in the extension: an atom that is not UTF-8 is a refusal and not an exception; the channel binding is checked
  first and the `tempus` whitelist rule is applied; a dialed reply must be the reply of its request (kind, store,
  entry count, `req_id`) and its entries are verified; the negotiated key exchange group is read from the handshake
  and anything but X25519MLKEM768 is refused; a listener accepts a peer whose certificate it was not given in advance.
- Proof: `example_tempus_clients/python/test_bees_tempus_node.py` (the stores against the recorded outputs of
  `trials/t0_tempus_view` and `trials/t1_tempus_store`, the clock against `trials/t0_tempus_clock`, admission against
  `trials/t4_tempus_admission`, the configuration against `tools/test_bees_tempus_conf.py` and
  `trials/c4_tempus_boot`), and the new trial `trials/c7_tempus_node_python` (port block 24800; Mac goldens): Python
  and Silica nodes in one network, joins and shuffles both ways, 44 hostile cases sent to a Silica sentinel and to a
  Python sentinel with the audit lines required to be the same, a Python node that is not a test node beside a Silica
  node built without the test unit, the clock's choices on Python nodes, and the extension's own client.
- No golden of an earlier trial changed: `t2`, `t3`, `t6`, `c2`, `c5` and `c6` pass through
  `tools/run_all_trials.sh` on the Mac with the pinned compiler. `c3_tempus_bridge` did not build that day: the
  compiler refuses the root unit of bridge B1 (E4045 at `carrier_new`, in a file generated on 2026-11-20 from sources
  that have not changed since), which is not a matter of the Python code. Its scenario, walked by hand with the node
  programs built on 2026-11-20, gives the four recorded outputs unchanged.
- New documents: `example_tempus_clients/writing-a-tempus-node.md` and `example_tempus_clients/python/README.md`;
  `writing-a-tempus-client.md` corrected (the `done` frame, a reply must be the reply of its request, how the
  whitelist names a certificate, atoms a node holds, what was since traced through the code); the two COVERAGE.md
  files of `trials/c2_tempus_clients` and `trials/c3_tempus_bridge` reviewed, with what no trial shows for the Silica
  client listed there.
- Found and not decided: a Silica node does not tell its application of `key_rotated` on an accepted connection (the
  extension does, and says which); the comment in `bees_tempus_node.part` that the clock is read once a second is
  stale (the code reads every `clock_read_ms`); a join answered with a frame that is not a sample reply puts the
  frame's bytes into the Silica node's line; how `clock_skew_ms` becomes the node's seconds is not built.

## 2026-11-23, the Kotlin extension can run an application as a TEMPUS node (owner: "nodes on non-silica are the plan")

- `example_tempus_clients/kotlin` gained a node half beside its client half: `src/View.kt` (the view and the store's
  steps), `src/Clock.kt` (`clockTurn`, the machine's clock), `src/Config.kt` (`TempusConfig`, the refusals of
  `tools/bees_tempus_conf.py` and of `bees_tempus_node@boot_why`), `src/Node.kt` (`TempusNode`: join, ticks, shuffles,
  answers, admission, limits, the clock's states, what the application is told, the Silica node's lines word for
  word). A node is an edge or a sentinel; the role `bridge` is refused, because the extension has no TRUST side.
- One owner of the state: a single node thread holds the stores, the clock state, the token and the counts; timers,
  the clock reader, the acceptor, connections (one virtual thread each, with copies) and the application post to it.
- No test code in the extension: the clock, the timers and the draws are a `NodeEnvironment` given at construction
  (the default is the machine's clock, real timers and the secure random source); the test clock, hand-run timers,
  literal draws and token making are under `test/`. The command line moved from `src/Main.kt` to `cli/Main.kt`, so
  `build/bees-tempus.jar` is the extension alone; `build/bees-tempus-client.jar` is as before.
- Tests (`test/NodeTestMain.kt`, 22): every call of the two Python models behind every line of the goldens of
  `t0_tempus_view` and `t1_tempus_store` (20623 view calls, 6006 store steps) and 9508 generated ones made again in
  Kotlin; every line of the golden of `t0_tempus_clock`; the configuration's refusals; five start refusals of
  `c4_tempus_boot` with the node's line; the entry check on the cases of `t4_tempus_admission`.
- Trial `trials/c9_tempus_node_kotlin` (port block 25000, Mac goldens, 11 outputs): a Kotlin edge joins through a
  Silica sentinel and a Silica edge through a Kotlin sentinel; shuffles started by each side and answered by the
  other; a good peer, 25 kinds of bad peer, the inflight limit and three TLS refusals against a Silica node and a
  Kotlin node with the audit lines required to be the same; the clock's choices, the node's own token and `key_rotated` on Kotlin nodes whose clock
  the trial sets; a Kotlin sentinel that is not a test node, through which a Silica node that is not a test node
  joins by the machine's clock. The golden of `c6_tempus_kotlin` did not change.
- Trial `trials/c11_tempus_bridge_kotlin` (port block 25200; the Kotlin client against real bridges, and rows 3, 4,
  7, 16, 20 and 21 of 16.2 with the test frames) is written and has NOT run: its bridge programs, copies of
  `trials/c3_tempus_bridge/nodes/b1` and `b2`, fail E4045 at the carrier's spawn with the pinned compiler, as that
  trial's own `nodes/b1` does on this day (the fault noted in silica-defects.md). `COVERAGE.md` there lists what the
  Kotlin client's trials cover, row by row.
- Found and not decided: a Silica node does not tell its application of `key_rotated` on an accepted connection (the
  extension does); a join answered with a frame that is not a sample reply puts the frame's bytes into the Silica
  node's line (the extension writes `the reply is not a sample_reply`); what a Silica node says of a `tick` frame
  depends on the atoms its program holds (`unknown_atom` without the test unit's atoms, `unknown kind` with them);
  how `clock_skew_ms` becomes the node's seconds is not built (the extension divides by 1000 and drops the rest);
  the three spec keys, the file keys and the advertised address of section 11 have no ruled form for a node that
  takes its configuration as a value.

2026-11-23, the Swift extension as a TEMPUS node (the same ruling of that day). `example_tempus_clients/swift` is now
one Swift package with two targets an application depends on, `TempusClient` (the wire and client part, as before)
and `TempusNode` (new: the stores, the join, the node's own shuffles, admission as a node judges it, the limits, the
clock's choices, the configuration, the Silica node's lines), a complete application `tempus-node-example`, and a
target `TempusTestSupport` that only tests and trial programs link (`Fixtures.swift` moved there out of
`TempusClient`, with a clock, timers and draws a test sets by hand). A node of the extension is an edge or a sentinel;
the role bridge is refused at the start (no TRUST in Swift). The node part is compiled in the Swift 6 language mode;
everything that changes is owned by one serial queue, and each connection runs on a thread of its own with a copy of
the values it needs.
- Changed in `TempusClient`, for the node: a TLS context can end the handshake when the dialer's protocols do not
  include `tempus/1` and can let a P-256 certificate through the handshake so that the node refuses it afterwards (a
  client's context is as it was); an identity can be made from a key already held; the values the node passes between
  threads are marked as safe to pass.
- Proof: `make -C example_tempus_clients/swift test` (348 checks of the client part as before; 207 of the node part:
  the 71 case lines of `trials/t0_tempus_clock`, 19 of the 20 cases of `trials/t4_tempus_admission`, the value cases
  of `tools/test_bees_tempus_conf.py` and every bound of design section 11, the boot refusals; 2860 generated cases of
  the view and store rules, each equal to the answer of the two Python models of the BEES tools), and the new trial
  `trials/c8_tempus_node_swift` (port block 24900; nine Mac goldens): a Silica edge and a Swift edge join through a
  Silica sentinel; shuffles started by each side and answered by the other; 38 hostile cases done to a Silica edge
  and to a Swift edge, the audit lines and what the peer saw required to be the same; the clock's choices on Swift
  nodes (hold, continue, stop inside and above the limit, pause with a connection closed and a join that waits, no
  reading at the start); a Swift sentinel that is no test program (`tempus-node-example`) through which a Silica
  node built without the test unit joins, shuffling on its own timer; and both refusing `tick` and `clock` in the same
  words (`unknown_atom`).
- The Swift client: the same trial runs its command line against two Silica nodes for rows of 16.2 that
  `trials/c5_tempus_swift` does not show (steps K1 to K15, golden `client`). `trials/c10_tempus_bridge_swift` (port
  block 25100) was written to run it against real bridges, with `COVERAGE.md` for the Swift client in the form of
  C2's; it has NOT run: its bridge programs, the text of `trials/c3_tempus_bridge/nodes/b1` and `b2` with other
  ports, fail E4045 at the carrier's spawn with the pinned compiler (the fault of the bridge program noted in
  silica-defects.md), also with C3's own ports and role files. It has no goldens and is not among the committed
  trials until that is settled.
- The golden of `trials/c5_tempus_swift` did not change.
- Found and not decided, beside what the Python entry lists: the design says a peer that fails its proof of
  possession is removed from the view, and the Silica node does that only for the partner it dialed; a Silica node
  accepts a P-256 certificate in the handshake and refuses it afterwards (`tempus_cert_key`) although its certificate
  request names Ed25519 only; the configuration has no key for the address a node advertises when it listens on every
  interface; the extension listens on any IPv4 address and resolves no sentinel name, both unlike the Silica tools.
2026-11-20, the four example clients divided into library and driver, each with a gossip part (owner's request):
design 16.7.
- Layout. `python/lib/tempus_client/` (codec, frames, connection, gossip; `testing.py` for the trials only),
  `python/driver/tempus_peer.py`, and `python/bees_tempus_client.py` kept as the module the trial tools import;
  `kotlin/lib/` and `kotlin/driver/Main.kt` (was `kotlin/src/`); `swift/lib/`, `swift/driver/`, `swift/testing/`
  (the fixtures, now a module of their own) and `swift/test/` (was `swift/Sources/`); `silica/lib/` (the two files
  that were in `silica/`, and the new `bees_tempus_peer.part`) and `silica/driver/` (a build leaf: `peer.role` and
  four instance roles). The three `lib/bees_tempus_client.silica` links and the two Makefiles that paste the client
  part name the new place. The client root units of `trials/c2_tempus_clients`, generated again, differ from the
  earlier ones in one comment line.
- Gossip. `Store` and `Peer` in Python, Kotlin and Swift; in Silica the node library, started by
  `tempus_peer_start`. Tests: `python/test_tempus_gossip.py` (the rules against the two models of `tools/`, 400 and
  1200 random steps; three peers in one process), `kotlin/test/GossipTest.kt` (10), and part D of the Swift tests.
- Networks on one machine, `example_tempus_clients/gossip/` and `trials/c7_tempus_gossip` (ports 24800 to 24804):
  four instances of one driver, for each language; a Silica sentinel with one edge of each language (`mixed`); the
  same without Silica (`trio`). All six run and recorded on the Mac, each 4 times with the same check.
- The Silica driver. Its application starts the peer (`tempus_peer_start`) and the single-connection part with the
  same identity, and every 700 ms asks its own peer for a sample over loopback, to print each peer it learns of. A
  version that printed nothing of its own and was judged by the peer's `tick ... shuffle with` lines did not show
  every peer within 90 s: an entry that is refreshed again and again is never the oldest, so it is never dialed.
- These are the first BEES TEMPUS nodes that tick by their own timers, with draws from the platform's random source
  and the system clock, against each other; the trials' nodes that are not test programs tick once an hour.

2026-11-20, the standard library's new listener form followed (owner's ruling of the same day: "The silica change is
to be accepted as it is found in the ../silica directory. BEES is to be updated to match").
- The change. Silica's `dangerous_tcp_carrier` listener (Silica commit `00d39ce0eb`, in the checkout at merge
  `92fd73c810`) tells its owner `(:accepted, fd: int64, peer)` and starts no actor; the owner starts the connection's
  carrier from the descriptor (the state the unit's header gives) and decides where it sits in its supervision tree.
  Until then the listener spawned the connection carrier and handed over its actor.
- What BEES does now: it starts each connection's carrier unsupervised, as the listener itself used to, in four
  places. The three TLS listeners, which own their listening carrier, do it in their own units
  (`dangerous_bees_tls@ttlsl`, `dangerous_beam_tls@btlsl`, `dangerous_bees_tempus_tls@tlnkl`; each now names
  `dangerous_tcp_carrier`). For a plaintext listener the carrier edge has `carrier_listen(c, owner, address)` and a
  small actor `cacc` (`src/shim/bees_tcp_edge.part`) that owns the listening carrier, starts the carrier of each
  accepted descriptor and tells the owner what it was told before, `(:accepted, connection_carrier, peer)`; the three
  parts that opened a listening carrier for a plain owner call it (`bees_node_edge.part`, `beam_tls_none.part`,
  `bees_trust_link_plain.part`). So `dangerous_bees_net@lsn`, `dangerous_beam_net@lsn`, `dangerous_bees_trust@tlsn`
  and the session listener `mlsn` are unchanged, and so is every message above the links.
- Two programs that own a raw listening carrier themselves follow the new form directly:
  `trials/m2_carrier_tcp/peer.role` and `examples/store_node/dangerous_store_node.silica.in`.
- Not done: no connection is put under a supervisor. That is what the new form allows; BEES keeps the earlier
  behaviour (an unsupervised root actor per connection) until it is decided otherwise.
- What was seen before the change was followed (the first run of the Silica gossip driver): a program built against
  the new unit took the descriptor's number for an actor reference, the accepted connection was never opened, and
  whichever actor had that number ended (the clock actor with `no case arm matched`; the failure reporter with a
  trap).
- The compiler stopping in `Emitting...` (four builds in a row around 17:00 to 17:30, while a build of the Silica
  compiler ran on the machine): not seen again in the builds after 18:00. Recorded in `silica-defects.md` as a note.
- Trials after the change, the whole set on the Mac (`tools/run_all_trials.sh --local-only`, compiler
  `silica-999900`, which is not the pin): 92 of 100 leaves passed, among them every TEMPUS leaf (t0 to t6, c2 to c7),
  `m2_carrier_tcp`, the M3 and M4 leaves, `n3_trust`, `n5_trust_mux_tls`, `n5_trust_mesh`, `d3_store_node` and
  `f1_fuzz_wire`. No golden of an existing trial was recorded again. New goldens: the six checks of
  `example_tempus_clients/gossip`. Generated files that are tracked and changed with the parts:
  `trials/n2_carrier_leak/dangerous_leak.silica`, `examples/store_node/dangerous_store_node.silica`.
- The 8 leaves that failed, none through the listener's new form as far as could be told:
  - `n2_auth`: its link `dangerous_exposure_source` is not in the repository (E4030, the sidecar is not found).
  - `n1_addr`: the manifest check refuses the build (`redial: required`).
  - `s03_actor_ceiling`: `ceiling_default_reservation` printed 8000 and ended 0 where the golden has the runtime's
    abort (`stack reservation failed`): the compiler's generation.
  - `n2t_live`: the stock Erlang node now agrees X25519MLKEM768 where the goldens say X25519, and its TLS 1.2
    scenarios connect: the installed Erlang and OpenSSL.
  - `n4_trust_tls` and `n5_trust_mux` (`negative`, `compat_negative`): `demo:slow(300000000)` answered before the
    call timeout, so the timeout, the suspicion and the quarantine that follow in the golden did not happen. Seen
    again when `n4_trust_tls` was run alone. `n3_trust` and `n5_trust_mux_tls` passed the same step.
  - `n2_dist` (`wrong_cookie_listen`; in a third run also `ticks_alive`) and `n2t_pair` (`three_nodes.hub`, two
    lines in another order): a program that was just built takes about 2 s to listen the first time it is run on
    this machine (measured: 1.98 s for a fresh copy of `dangerous_a_wrong`, 0.01 s the second time), and the pair
    runner starts the dialer 0.5 s after the listener. The same pair run by hand, and by `tools/run_pair.py` alone,
    gave the golden's lines, and `n2t_pair` run alone passed 22 of 22.

2026-11-20, the eight failed leaves and one failing unit test looked into, by the owner's order ("confirm and fix each
one"). Compiler `silica-999900`; system python3 3.15.2, OpenJDK 27.0.1.1, kotlinc 2.4.21, Erlang/OTP 29.
- `n4_trust_tls`, `n5_trust_mux` (the call timeout step). Cause: the workload, not the timeout. `demo:slow` was a loop
  of n steps and the step asked for 300000000; measured alone on this machine, three runs each: 303 to 390 ms on
  999900, 236 to 343 ms on the pin 999909, against the server's `call_timeout_ms` of 400. The timeout fired only when
  the machine was busy enough (it did in `n3_trust` and `n5_trust_mux_tls` in the same full run). Change:
  `trials/n3_trust/roles/n3_demo.silica` waits by the clock, in the form `n5_demo.silica` already had, and the step
  asks for 1200 ms, three times the timeout. The step's printed text changed with its argument, in six goldens
  (`negative.b` of n3 and n4, `compat_negative.b` of n5_trust_mux, both platforms): the Mac ones are what the three
  trials printed afterwards (7 of 7, 11 of 11, 30 of 30); the Linux ones had the same one line edited by hand and
  were not run.
- `n2_auth`. Cause: the leaf's link `dangerous_exposure_source` was never in the repository; `.gitignore`'s
  `trials/*/*` hid it (`git check-ignore`). Added the link and its exception. Every other leaf whose units declare
  foreign functions has its link (checked by a script over the tracked files, and by the full run: no other E4030).
- `n1_addr`. Cause: node l has no bees.config and a `dial` peer, and its manifest had no `redial` line, which is
  required since the user's ruling of 2026-11-17 (`contract/so-you-want-to-write-a-compiler.md`, the manifest table).
  Added `redial off` to `nodes/l/node.wire`; the check was not touched.
- `s03_actor_ceiling`. Not changed. On the pin 999909 it prints 8000 and ends 0 as on 999900, so it is not the
  compiler's generation. The default stack reservation is the machine's memory plus swap, and this machine has 16 GiB
  and, today, no swap at all (`vm.swapusage: total = 0.00M`): 8000 times 16 GiB is exactly the address space. The
  Mac golden (abort near 4000) was recorded with swap in use. `silica-defects.md`, the note on the default
  reservation, says so. Left for the owner: what the entry should show on a Mac whose swap comes and goes.
- `n2t_live`. Cause: the installed Erlang is OTP 29, which offers TLS 1.3 by default and puts x25519mlkem768 first
  (`ssl:groups(default)`); the trial was written against OTP 28, which offers TLS 1.2 only by default and has no
  hybrid group, and it left both to the defaults. Change, in the stock node's option files only
  (`tools/bees_beam_tls_live.py`): the TLS 1.3 files say `{supported_groups, [x25519]}`, and the "TLS 1.2 only" file
  says `{versions, ['tlsv1.2']}`. No golden changed, and the trial passes 22 of 22 on OTP 29. Left for the owner:
  whether a scenario of a stock node on the hybrid group is wanted (only an OTP that has the group can run it).
- Python `test_tls_refusals`. Cause: a race a dialer cannot win. In TLS 1.3 the dialer's handshake is complete
  before the listener has judged its certificate; the refusal comes afterwards as an alert and a close. Probed: when
  the dialer writes its advert before the listener has closed, its next read gives the alert (`tls_failed`); when it
  writes 0.3 s later the write fails with EPIPE and the alert is never read (`closed`). With Python 3.15.2 and
  OpenSSL 4.1.0 the second happens every time. The guide (section 7) says a client can tell no more than a close, and
  `tools/bees_tempus_trial.py` already accepted both for row 26. Change: the test accepts both for the three cases in
  which the listener refuses the dialer's certificate; the stage and the listener's own outcome are still required
  exactly. The client was not changed. Left for the owner: whether a reset before any frame should be named
  `tls_failed`, which would give one answer but would also name a node's close at its connection limit that way.
- `n2_dist` and `n2t_pair` (the start race). Cause measured: a program that was just built takes 1.98 s to listen
  the first time it is run on this machine and 0.01 s afterwards, and the runners started the next program 0.5 s
  after STARTING the first. Change: `tools/run_trial.py` marks the program's first byte of output, and
  `tools/run_pair.py`, `run_trio.py` and `run_demo.py` start the next program STAGGER seconds after that (a program
  that prints nothing before its peer arrives is waited for 5 s at most). No comparison was made order-insensitive.
- The whole set after these changes: 99 of 100 leaves passed; the one that failed is `s03_actor_ceiling`.
- Seen and left: `trials/c1_codec_live/kinds.bees.raw` and `trials/m3_decode_probe/main.silica.derived` are tracked
  and rewritten by every run; `tools/test_platform_and_ports.py` fails on Linux goldens missing for
  `c1_codec_term`, `c4_tempus_boot`, `n5_trust_mux` and `n5_trust_mux_tls`.

## 2026-11-23, the two lines joined (merge of main into tempus-extension-nodes)

The entries above this one and below the entry of 2026-11-20 come from two lines of work that did not know of each
other: the node halves of the Python, Swift and Kotlin extensions (built on 8041473) and main's commits of 2026-11-21
to 2026-11-23 (the library and driver split, gossip discovery in the client libraries, one compiler pin per platform,
the three-platform runner, load balancing). The merge keeps both, in main's layout, and loses nothing of either.

Python. The node half (seven modules) is in example_tempus_clients/python/lib beside the client library package
lib/tempus_client; its test support is in python/testing. Neither uses the other. bees_tempus_client.py, the name the
trial tools import, is the node half's test support by default and the client library's with
BEES_TEMPUS_TEST_SUPPORT=tempus_client.testing; test_bees_tempus_client.py passes both ways. Two corrections were
carried from the node half into lib/tempus_client: an atom that is not UTF-8 is refused and not raised, and the
channel binding is judged before the token. Two differences remain in lib/tempus_client: its dial returns a reply
unchecked (its Peer checks it), and the whitelist rule is applied only when a whitelist is given. Trial
c7_tempus_node_python moved to ports 26100 to 26111, because main's c7_tempus_gossip owns 24800; 38 lines of nine Mac
goldens changed, port numbers only. It is declared for the Mac only; Linux goldens are still to be recorded.

Swift. The node half moved into main's layout (lib/TempusNode, driver/tempus-node-example, test/tempus-node-tests,
test/model_check.py, testing/tempus-node-trial); the test-support target TempusTestSupport was folded into main's
TempusClientTesting (ManualClock, ManualTimers and ListRandom in ManualSources.swift), and test/layering_check.py now
checks that neither library nor tempus-node-example depends on it. TempusClient builds in Swift 5 mode, TempusNode
and the test support in Swift 6 mode. Both libraries have a public type named Store, and a file that imports both
selects the node's with `import struct TempusNode.Store`. c8_tempus_node_swift has a platforms file (Mac only).
Where the entries above say TempusTestSupport, read TempusClientTesting.

Kotlin. Main's layout kept (lib, driver, test). The node half (Node.kt, View.kt, Clock.kt, Config.kt,
NodeTestMain.kt, NodeFixtures.kt, model_cases.py) moved into it. Its store and entry classes were renamed NodeStore
and NodeHeld because lib/Gossip.kt declares Store and Held in the same package; nothing of main's was renamed.
cli/Main.kt was removed (it was the unchanged base file; driver/Main.kt is main's). The Makefile builds
bees-tempus.jar from lib alone and runs three test programs. The tests golden of c9_tempus_node_kotlin was recorded
again because the node tests now also read the Linux AArch64 goldens main added to other trials (22 tests became 24
and the golden counts in six lines rose). c9 has a platforms file (Mac only).

All three. The old LINUX_GOLDEN_EXCEPTIONS entries are replaced by main's platforms files. Each language now holds
two gossip implementations side by side: main's Peer in the client library (lighter, on real timers, run in the
four-language gossip networks) and the node half (admission in the Silica node's order, its configuration keys and
refusals, the clock choices, the in-flight limit, audit lines word for word, compared with Silica nodes case by
case). Open for the owner: which to keep, or how to make one that has both sets of properties.

Building. main pins silica-999899-macos-applesilicon and uses Silica's new TCP listener contract. The merge was built
and run against a read-only export of Silica's main with that compiler, because the Silica checkout beside the BEES
checkout on this machine held neither.

## 2026-11-23, the C# extension

example_tempus_clients/csharp: a client half and a node half (edge and sentinel; bridge refused), one implementation,
in main's layout (lib, driver, testing, test). .NET SDK 11.0.100, no package. TLS, Ed25519 and SHA-512 through
Homebrew OpenSSL 4.1.0 by P/Invoke, because SslStream on macOS cannot load an Ed25519 key or complete a handshake with
a node (the README records each failure). One node thread owns all node state. 44 client tests and 25 node tests.
Trials, Mac goldens only (platforms files): c12_tempus_csharp (client, 4 outputs), c13_tempus_node_csharp (mixed
network; 42 hostile cases, the inflight limit and four TLS refusals with audit lines equal to a Silica node's, the
P-256 case included; 11 outputs), c16_tempus_bridge_csharp (the client against real bridges, 40 steps, 4 outputs;
COVERAGE.md). The tests and the three trials were also run from a clean export of the index, and pass there. Found: a
call that names an atom the node does not hold is refused as protocol_error unknown_atom, not request_refused; the
Kotlin node's atom list lacks `erlang` and the error atoms. Not ruled: the four configuration differences the Kotlin
extension also has, the Dialed flag of key_rotated, where OpenSSL is looked for.

## 2026-11-23, the Rust extension: client and node, three trials (owner's request)

example_tempus_clients/rust is a Cargo workspace with no dependency outside itself, built with cargo 1.91.1 in
offline mode. TLS 1.3, Ed25519, SHA-512 and certificates are Homebrew OpenSSL 4.1.0, called through 67 extern "C"
declarations (lib/tempus/src/ffi.rs) with no C code and no libc crate; all unsafe code is in crypto.rs and tls.rs (46
blocks). The TCP side is the standard library's TcpStream in blocking mode, one deadline per connection kept through
its read and write timeouts. The first handshake was tested against a Silica node in both positions before anything
was built on it. Layout as main's: lib/tempus (client half and node half in one crate), driver (tempus-client,
tempus-node-example), testing (tempus-testing, tempus-node-trial), test (cargo tests, tempus-model, model_check.py,
layering_check.py). One implementation only: the node matched to the Silica node, no second Peer and no gossip
command. The node's state has one owning thread that everything else sends messages to; a connection runs on its own
thread with copied values.

Unit level: 18 tests (the t2 frames on three platforms' goldens, the vectors, the eight certificates byte for byte,
19 of the 20 t4 cases, the 71 lines of t0_tempus_clock, the configuration cases and bounds, the boot refusals, a node
in the test process); the tools' own view and store tests run over the Rust rules, which replays the t0_tempus_view
and t1_tempus_store goldens, and 6885 generated answers equal the two Python models.

Trials, Mac goldens: c14_tempus_rust (the client against a test node, a node on the system clock, and the Python test
support; its outputs equal c5's Swift goldens but for ports and names, plus ten steps for a reply that is not the
reply of its request), c15_tempus_node_rust (Rust nodes among Silica nodes; 54 hostile cases sent to a Silica edge and
a Rust edge with identical audit lines; the clock choices; tempus-node-example on the machine's clock beside a Silica
node built without the test unit) and c17_tempus_bridge_rust (the client against bridges B1 and B2 and TRUST node T,
rebuilt from c3's network: calls, a cast, the whitelist rule both ways, the score and in-flight bounds, the TRUST side
refusing and gone, a bridge lost; COVERAGE.md row by row). The tests and the three trials were also run from a clean
export of the index. That run first failed: model_check.py counted as a failure the three tests of the tools that are
skipped when trials t0_tempus_view and t1_tempus_store have not been run in the tree. It now prints them as skipped,
and the clean run passes.

Found: the Swift node's list of known atoms lacks the rejection atoms and trpc results of src/trust/bees_trust.atoms,
which a Silica node holds; c15 cases R41 to R43 show the Silica node's words for them. The Rust node uses the Silica
node's text for a test node off loopback; its value refusals are the tool's texts, which differ from boot_why's. The
Rust client checks the binding first and applies a given whitelist both ways. Not built: the bridge role (refused), a
gossip driver command. Mac only (platforms files).

## 2026-11-23, the Swift client against real bridges (c10_tempus_bridge_swift)

The trial written on 2026-11-23 and not run then (its bridge programs of 33 units could not be built by compiler
999909) builds with silica-999899 and passes: bridges B1 and B2 and TRUST node T, steps A to H, 45 checked lines, four
Mac goldens (t, b1, b2, swift). Every expectation of the draft held on the first run and the Swift client needed no
change. The walk now also waits for the bridge's or T's own line, with the exact peer id, on every step that ends in a
close with no reply. Not walked: the per-peer rate bound (row 35 of design 16.2). Mac only (platforms file). Run in the
working tree, through the runner, and from a clean export of the index. Where the entries above say this trial has not
run, read this entry.

## 2026-11-23, the Kotlin client against real bridges (c11_tempus_bridge_kotlin), and the Kotlin node's atom list

The trial written on 2026-11-23 and not run then builds with silica-999899 and passes: bridges B1 and B2 and TRUST
node T, 43 steps, four Mac goldens (t, b1, b2, kotlin). Its nodes and roles are those of c16_tempus_bridge_csharp
with the ports changed. All 40 expectations of the draft held on the first run and the Kotlin client needed no
change. Three steps were added because the draft claimed more than it showed: a third request of an edge with two
calls in flight is closed with the bridge's bridge_inflight line (row 35), the edge calls a bridge at the address of
an entry it sampled (row 30), and after a bridge is lost the next call succeeds through the other (row 33). The waits
for held calls now name the peer and the connection. COVERAGE.md is corrected in the rows it had misattributed. Rows
3, 4, 5, 7, 10, 12, 16, 18, 20, 21, 24, 25, 29 to 35 and section 17.7 are reached by the Kotlin client.

The Kotlin node's list of the atoms a node holds was incomplete (46 of 68). Shown against a Silica node: to a call of
erlang:ok/0 the Silica node wrote request_refused and the Kotlin node wrote protocol_error, not a request:
unknown_atom. The list is now every atom of src/tempus/bees_tempus.atoms and src/trust/bees_trust.atoms. The case is
step D32 of c9_tempus_node_kotlin: seven lines added to three of its goldens, none removed or changed. Where the
entries above say c11 has not run, read this entry.
