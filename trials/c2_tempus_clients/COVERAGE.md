# C2: coverage of the behaviour list (design 16.2) by the two clients

Trial `trials/c2_tempus_clients`. The Python client (`tools/bees_tempus_client.py`, scenario `c2` of
`tools/bees_tempus_trial.py`) drives node N; the Silica client (`src/tempus_client`, thin application `client.role`,
scenarios `cs.role` as a sentinel and `ce.role` as an edge) drives node M, the same node on another port. Both send one
tick to node O, which is not a test node. Step numbers are those of `cs.role` (written s1 to s10) and `ce.role` (1 to
54); the Python scenario uses the same numbers and adds its own steps P1 to P11.

"Client" in the last column means the client sees the result on the wire: the Python scenario asserts it and the Silica
client's line is in its golden (`dangerous_cs`, `dangerous_ce`). "Node" means the result is read from the node's own
output, its golden (`dangerous_n` for the Python client, `dangerous_m` for the Silica client, `dangerous_o`), because no
frame shows it (ruling NQ-1).

| Row | Behaviour | Python client | Silica client | Result observed |
| --- | --- | --- | --- | --- |
| 1 | three isolated stores | starts N; s1, s9, 1 | starts M; s1, s9, 1 | Node: the boot lines. Client: a sample of one store answers from that store |
| 2 | join through a sentinel | listens as the sentinel before N starts; s1, 1 | `dangerous_cs` listens before M starts; s1, 1 | Client: the three `sample` requests, one per store; later samples return what the client answered. Node: the join lines, and after each answered sample the sentinel store's line holding the sentinel it joined through (ruling NQ-12) |
| 3 | leaves; others forget it | 4, 5 (and `trials/t3_tempus_nodes` step 6, where a node process is stopped) | 4, 5 | Node: the dial fails, the entry is gone. Client: the next sample (7). A client cannot stop a node: that is the trial's act (T3) |
| 4 | tick: every age rises | 12, 15, 17, 20 | 12, 15, 17, 20 | Client: the ages of the entries in the successive shuffle frames it receives are one higher after each tick. Node: the view lines |
| 5 | tick: the partner is the oldest | 4, 5, 6, 9; s3, s7 | 4, 5, 6, 9; s3, s7 | Client: it is dialed when it is the oldest (6, 9) and not before (4, 5). Node: `shuffle with` lines |
| 6 | tick: the buffer, and it leaves the view | 6, 12 | 6, 12 | Client: the frame holds the node's own entry at age 0 and at most two others. Node: the view while the shuffle runs |
| 7 | merge: younger preferred, oldest evicted | 6, 8, 9 | 6, 8, 9 | Node: the view lines after each merge. Client: the samples 7 and 10. See NQ-16 for what step 8 shows |
| 8 | shuffle as responder | 2, 3; s5, s8 | 2, 3; s5, s8 | Client: the `shuffle_reply`, then itself at age 0 in a sample |
| 9 | each store, no mixing | edge 1 to 20; sentinel s1 to s5; bridge s6 to s9; mixed s10, 42 | the same | Client: per-store frames; the mixed frame is closed with no reply. Node: `entry_refused`, no view change |
| 10 | a store of another type: no own entry; the partner that answered is put back at age 0 (ruling NQ-15) | s3, s7; the samples s4 and s9 | s3, s7; s4, s9 | Client: the shuffle frame of the sentinel store and of the bridge store holds no entry for the node (an edge); the sample after it holds the client itself at age 0 beside what it answered. Node: the view line after the merge |
| 11 | admission accepted | every step that is answered; 1 | the same | Client: the reply. Node: `admitted` |
| 12 | admission refused, each cause | 21 to 27 (signature, expired, not yet valid, sub, typ, id, proof by another key); P3 a proof over another nonce; P4 no proof; P5 a proof of 63 bytes | 21 to 27; not "no proof" (the connection actor always sends its proof) | Client: closed with no reply. Node: the audit line with the cause |
| 13 | rotated key | 28 | 28 | Client: the `key_rotated` frame naming k1. Node: the audit line |
| 14 | the node proves itself | every step (the client verifies the node's signature before its request) | every step | Client: Python's verifier accepts; the Silica client's own line `admitted peer=b19edad2...` |
| 15 | the node's own token: refresh and expiry | 48 to 54 | 48 to 54 | Client: after the refresh the node's own entry carries a token that ends at 2500 (51); after the clock passes it the client refuses the node's advert (54). Node: `own token replaced`, `ticking has stopped`, the application's two lines |
| 16 | expired entries leave the view | 44 to 47 | 44 to 47 | Node: `expired in tempus_edge`. Client: the entry is in no later frame (47) |
| 17 | a gossiped entry that does not verify | 12, 13 | 12, 13 | Node: `entry_refused`, the partner dropped, the sent entries back. Client: none of the frame's entries in the sample 13 |
| 18 | partner unreachable, closes early, silent, violating | 4, 5 nobody listens; 15 closes with no reply; 17 silent; 20 a wrong frame; P1 closes after the advert; P2 silent before its proof | 4, 5; 15; 17; 20 | Client: `done` arrives after the failure. Node: `the partner did not answer` with the reason, the sent entries back |
| 19 | bounds | 29 to 41; P6 an oversize frame as the advert | 29 to 41 | Client: closed with no reply. Node: `protocol_error` with the bound. The node's memory over many such frames is not measured in this trial |
| 20 | more connections than `inflight_max` | P8 | not driven: the client cannot hold a connection open before its advert | Client: the third connection is closed at once and the node serves afterwards. Node: `inflight_refused` |
| 21 | a tick during a shuffle in flight | 17 | 17 | Client: the second tick is answered `done` at once and the client is not dialed again. Node: `aged only (a shuffle is in flight)` |
| 22 | an empty view: ask a sentinel again | s6 | s6 | Client: the listening sentinel receives a `sample` for the bridge store. Node: `the view is empty`, the join lines |
| 23 | `sample` as a peer request | s1, s2 | s1, s2 | Client: the same reply twice |
| 24, 25 | application requests on a bridge | C3 | C3 | not built (T6) |
| 26 | TLS 1.3 only, ALPN, the certificate | P7: TLS 1.2 only; another ALPN; no certificate; a P-256 certificate; an RSA certificate; a connection that says nothing | the accepted case, every step | Client: the handshake fails or the connection closes before any frame; the silent connection is closed at the node's bound. Node: `tls_handshake_failed`, `alpn_mismatch`, `tls_verify_failed`, `tempus_cert_key`, `timeout ... stage tls_handshake` |
| 27 | draws from the platform's source | not a client's act | not a client's act | the trial's goldens are the same on every run (literal draws on a test node) |
| 28 | boot refusals of a bad configuration | T7 | T7 | not built |
| 29 to 36 | bridges | C3, T6 | C3, T6 | not built |
| 37 | test-only frames on a node that is not a test node | 43 | 43 | Client: closed with no reply. Node O: `test_only_refused` |

Rulings of 2026-11-19 that are no row of 16.2, and where this trial shows them:

| Ruling | Behaviour | Python client | Silica client | Result observed |
| --- | --- | --- | --- | --- |
| NQ-11 | a node that is not a test node reads the system clock | P9: the trial's ordinary token (valid 1000 to 3000 s after 1970, admitted by N at its clock of 1500) at node O; P10: a token that begins at 3900000000; 43: a token valid 1000 to 4000000000 | 43 | Client: closed with no reply (P9, P10). Node O: `clock: the system clock is read` before it listens; `the token has expired` (P9), `the token is not valid yet` (P10), `admitted` (43). No line holds a time of day |
| NQ-14 | `shuffle_timeout_ms` is one bound from the accept to the close | P11: connects, waits 1 s, does its TLS handshake, says nothing | not driven | Client: the scenario measures the close at 2.0 s after the connect (it asserts 1.7 to 2.75 s; one bound per stage gave 3.0 s). Node N: `timeout ... stage advert` |
| NQ-17 | a node whose own token has expired still answers | 54 and P11 (N's token expired at step 53) | 54 | Client: the node's advert arrives and is refused by the client (54). Node: the connection lines after `ticking has stopped` |

Notes.

- Row 26, the RSA certificate: the node's certificate request names Ed25519 only, so Python's TLS library, holding only
  an RSA certificate, sends none; the node's line is `the peer presented no certificate`. A peer that sends an RSA
  certificate regardless cannot be made with Python's `ssl`.
- Row 26, a key-exchange group: Python's `ssl` cannot name the groups it offers; its default offer includes
  X25519MLKEM768, which the node takes. A classical-only offer is refused by the engine's self-test in memory
  (`native/tempus/selftest`), not here.
- Row 15: the refresh is the node application's act. In this trial the application passes the new token 300 ms after the
  node tells it that a peer answered `key_rotated`; the client causes that by answering the node's advert with
  `key_rotated`.
- The Silica client's connections are the node's own connection actor, so the Silica client and the node share one
  implementation of admission. The Python client shares nothing with them.
