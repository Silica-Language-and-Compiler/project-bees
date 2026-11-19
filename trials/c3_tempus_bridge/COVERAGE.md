# T6 and C3: coverage of the bridge rows of the behaviour list (design 16.2) by the two clients

Trial `trials/c3_tempus_bridge`. Node T is a plain TRUST node; bridges B1 and B2 are each the TRUST node as built and a
TEMPUS node of role bridge in one program (`src/tempus/bees_tempus_bridge.part`, `bees_tempus_bridge.silica`). The Silica
client (`src/tempus_client`, thin application `roles/client.role`, scenario `roles/c.role`, identity x2) runs first; the
Python client (`tools/bees_tempus_client.py`, scenario `c3` of `tools/bees_tempus_trial.py`) walks the same steps
afterwards with its own identity ("other"), then the steps only it takes (named P below): with a second edge (x3), an
edge for the rate bound ("sentinel"'s key with an edge token), a bridge identity that listens (x4), the edge of the
quarantine ("node"), and the two edges of ruling NQ-19 (Q and Z, below the table). Step numbers are those of `c.role` (1 to 20).

"Client" means the client sees the result on the wire: the Python scenario asserts it and the Silica client's line is in
its golden (`c`). "Bridge" and "T" mean the result is read from that node's golden (`b1`, `b2`, `t`), because no frame
shows it (ruling NQ-1). Rows 1 to 23, 26, 27 and 37 are `trials/c2_tempus_clients` (its COVERAGE.md); row 28 is
`trials/c4_tempus_boot`.

| Row | Behaviour | Silica client | Python client | Result observed |
| --- | --- | --- | --- | --- |
| 24 | application requests on a bridge: call, cast, the forbidden guard, the per-type permission, the timeout, no error body | 2, 3, 7 (cast), 8 (the function fails), 10 (timeout), 16 (forbidden), 17 (unpermitted) | the same steps | Client: the result, or closed with no reply (no error body ever). Bridge: `bridge_admitted`, `bridge_done`, `user_code_error`, `timeout`, `forbidden_mfa`, `permission_denied`, one audit line each |
| 25 | the bridge's function calls onward into TRUST | 5, 6 | the same | Client: `demo:onward(20, 22)` answers 42, computed by T's `demo:add`. T: `admitted ... call demo:add/2` under the bridge's TRUST fingerprint |
| 29 | a node learns bridges | not driven (its identity is no bridge in this trial) | P: the bridge identity x4 shuffles itself into B1's bridge store; a tick of that store dials it; it answers with B2's entry | Client: the listening client is dialed, the sample then holds B2. Bridge: the view lines of `tempus_bridge` |
| 30 | an application gets a bridge | 1 and 2: `sample` of B1's bridge store, then `bees_tempus_client@pick_bridge` (draw 7) picks B2, which answers the call | the same, picking by the same draw in Python | Client: the sample's entry, the pick's line, the result |
| 31 | a call crosses a bridge and the answer returns | 5 | the same | Client: 42. T: the request came under B1's TRUST certificate (`fp=7e6dfd84...`, b.pem) |
| 32 | several bridges: any serves | 3 and 4, 5 and 6 (the same requests to B1 and to B2) | the same | Client: the same results from each. T: calls under both fingerprints (b.pem, w.pem) |
| 33 | a bridge is lost | not driven (the Silica client has finished when B2 is stopped) | P: the trial stops B2; a call to B2 fails (unreachable); a tick of B1's bridge store dials B2 and fails; B1's sample is then empty; a call through B1 succeeds | Client: unreachable, then the empty sample, then the result. Bridge: `the partner did not answer, connect_failed`, the empty view |
| 34 | the bridge refuses an edge that misbehaves, without touching TRUST | 16 to 19: forbidden, unpermitted, two malformed TRUST requests (arity 3 and 0 with two arguments); 20: a good request refused | the same | Client: closed with no reply each time, then the good request closed too. Bridge: `bridge_score` up to 6, then `bridge_refused ... score 6 is above the limit 5`. T: no suspicion line for any of these |
| 35 | the bridge's rate and in-flight bounds per peer | 12 and 13 held, 14 refused (`bridge_inflight`); the held calls are closed at the call timeout; 15 answered | the same; P: a second edge is served while the first is at its bound; P: 20 requests of one edge answered, the 21st refused (`bridge_rate`), another edge served after | Client: the refusals, the results. Bridge: `bridge_inflight`, `bridge_rate`, the scores |
| 36 | the TRUST side of a bridge is plain TRUST | not a client operation | not a client operation | T: token issue and fast path, admission, permission, suspicion and quarantine lines for the bridges' TRUST certificates, as in the TRUST trials |
| 17.7 | the bridge quarantined at T by the trial | not driven | P: three calls of `demo:bad`, whose application calls T's `demo:secret/0` (not permitted for B1): closed each time; T quarantines B1; a call of `demo:onward` is then closed too | Client: closed and nothing else. T: `suspicion` three times, `quarantined`, then `connection refused` |

Ruling NQ-19 (2026-11-19), Python client only, the last steps of its scenario: what the connection actor refuses of an
edge raises that edge's score at the bridge. Edge Q (a key of its own, seed 96) never has a request answered or refused
by the bridge's table. Six of its connections are refused by B1's connection actor: a proof of possession that does not
verify (`pop_failed`), a frame that is no request and a frame above the ceiling (`protocol_error`, twice), an expired
token and a token another key signed (`admission_refused`, twice), and silence where its challenge was due until the
connection's bound (`timeout`). B1's golden shows `bridge_score ... raised to 1 by pop_failed` up to `raised to 6 by
timeout`; Q's first good request is then `bridge_refused ... score 6 is above the limit 5`. Client: closed with no reply
each time. Edge Z (seed 112), which B1 has never served, shows a token another key signed and an expired one: refused
twice by admission, no `bridge_score` line (no entry is made from a token the producer's signature was not verified
on: design 17.5 and NQ-23); its good request is then answered 5.

Also seen in the goldens and not a row: the bridge's per-peer table full (size 4) drops the entry whose token expires
first, audited `bridge_table_full`. The hostile steps of row 34 use TRUST requests that pass the frame check and fail
TRUST's own (arity); since ruling NQ-19 a frame that is no TEMPUS request at all counts too (edge Q above).

Totals for rows 24, 25, 29 to 36: the Silica client causes 7 of the 9 client rows (24, 25, 30, 31, 32, 34, 35), the Python
client all 9 (24, 25, 29 to 35); row 36 is the TRUST node's own lines.
