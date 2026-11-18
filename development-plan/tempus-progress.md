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
