# The client half of the C# extension: coverage of the behaviour list (design 16.2)

Three trials use the client half of the C# extension (`example_tempus_clients/csharp`: `Client.Dial` and `Listener`).
All three are recorded for the Mac only (their `platforms` files): the .NET SDK is not installed on the project's
Linux machines.

- `trials/c12_tempus_csharp`: the walk `Walk.cs` against node K (a test program) and node Q (not a test
  program). Its steps are written A1 to A5, B1 to B5, C1 to C16, D1 to D21, E1 to E14 and Q1 to Q8, as its golden
  `csharp` prints them.
- `trials/c13_tempus_node_csharp`: the program `Net.cs`, in which the client half is the trial's own peer beside
  nodes of the C# extension and Silica nodes. Its steps are written c13 A1 and so on.
- `trials/c16_tempus_bridge_csharp` (this directory): the walk `Bridge.cs` against the bridges B1 and B2 and
  the TRUST node T, the network of `trials/c3_tempus_bridge` on this trial's own ports. Its steps are numbered 1 to
  40 in sections A to E, as its golden `csharp` prints them, and are written c16 1 and so on.

"Client" in the last column means the C# client sees the result on the wire and the trial checks it. "Node" means
the result is read from the node's own recorded output, because no frame shows it (ruling NQ-1). The C# extension
has no function that misbehaves on purpose and builds no test-only frame. Where a row needs a `tick` frame, the trial
tool sends it with the Python test support, and where a row needs a peer that misbehaves, the Python test support
plays it. The `clock` frame is sent by none of these three trials; the rows that need it say so.

| Row | Behaviour | C# client | Result observed |
| --- | --- | --- | --- |
| 1 | three isolated stores | c12 A2, A5, B1 | Client: a sample of one store answers from that store. Node: the boot lines |
| 2 | join through a sentinel | c12 A1 (the client listens as the sentinel before K starts) | Client: its listener serves the three `sample` requests, one per store, of a peer admitted as the node. Node: the join lines |
| 3 | leaves; others forget it | c16 39 and 40 (B1 is stopped; a tick of B2's bridge store; then a sample) | Client: `unreachable`, then the sample no longer returns the entry. Node: `shuffle failed`. A client cannot stop a node: that is the trial's act |
| 4 | tick: every age rises | not reached by the client: it would need an entry of a chosen age seen again after a tick in a frame the client's listener receives. Shown for nodes of the extension by the store tests against the models | |
| 5 | tick: the partner is the oldest entry | c12 B4 (the client is in K's edge store and is dialed at a tick; up to five ticks are sent, because K's other entries may be older) | Client: its listener is dialed. Node: the tick line names the partner |
| 6 | tick: the buffer holds the node's own entry at age 0 first | c12 B4 | Client: the first entry of the `shuffle` frame its listener receives is the node's, at age 0 |
| 7 | tick: the merge prefers younger entries and evicts the oldest | c12 B4 and B5 in part (the listener answers with two entries, and a later sample holds both); the preference and the eviction are not driven by the client | Client: the later sample. Shown in full for nodes of the extension by the store tests |
| 8 | shuffle as responder | c12 B2 and B3, Q2 and Q3 | Client: the `shuffle_reply`; a later sample returns the client at age 0 |
| 9 | each of the three stores, and no mixing | c12 A2 to A5 (sentinel and bridge stores), B1 (edge store), C8 (an edge's entry offered to the sentinel store) | Client: per-store replies; C8 closed with no reply. Node: `entry_refused ... typ is not the store's type` |
| 10 | a store of another type than the node's: shuffled without the node's own entry | c12 A3 (K, an edge, shuffles its sentinel store with the client, which holds a sentinel token) | Client: the `shuffle` frame its listener receives has no entry |
| 11 | admission accepted | every step that is answered, first c12 A2; with a bridge c16 1 | Client: the node's advert and challenge arrive and verify, and the request is answered |
| 12 | admission refused, each cause | c12 C1 (signature), C2 (expired), C3 (not yet valid), C4 (`sub`), C5 (`typ` not allowed: a bridge token under a certificate K does not list). c16 27 and 28 (the whitelist rule at a bridge, both ways). Not sent by the client: an `id` that is not the key's hash, a wrong proof and no proof, because the extension cannot build them; c13 D13, D17 to D20 send them with the Python test support to a Silica node and to a C# node | Client: closed with no reply. Node: one audit line each |
| 13 | rotated key | c12 C6 | Client: the `key_rotated` frame naming `k1` |
| 14 | the node proves itself to the peer | every answered step; the refusal of a wrong proof is c12 D6 (a peer of the Python test support) | Client: it verifies the node's signature over its nonce and the node's token before it sends its request |
| 15 | the node's own token: refresh and expiry | c12 C11 (the client's clock at 2600: K's token has expired, and the client's own check refuses K's advert). The refresh is not driven: it needs the `clock` frame or the node application's act | Client: `refused at=advert`, the token has expired |
| 16 | entries whose token expired leave the view | not reached by the client: it needs the `clock` frame. A node of the extension drops such entries before each tick (`lib/Node.cs`); no trial of the extension shows it | |
| 17 | a gossiped entry that does not verify refuses the whole frame | as the sender: c12 C8. As the receiver: c12 D9 (a reply with one forged entry beside a good one) and E11 (a shuffle with a forged entry, to the client's listener) | Client: C8 closed; D9 and E11 refused whole, and the listener's handler is not asked |
| 18 | partner unreachable, closes early, silent, or violating | not driven by the client against a Silica node (it would need a tick while the client misbehaves on purpose). For nodes of the extension: c13 C4 (nobody listens) and E8 (`key_rotated`) | Node: `the partner did not answer`, `shuffle failed` |
| 19 | bounds | c12 C7 (a sample of 9), C9 (four entries). The extension cannot write an oversize frame, an age above 65535 or a wrong field length; c13 D14 (an id of 63 bytes), D15 (version 2), D22 and D23 (oversize), D35 (an age of 65536) and D43 (a byte after the request) send them with the Python test support to both kinds of node. An unknown key and nesting that is too deep are sent by no trial of the extension; the codec tests show the reader refusing them. As the receiver: c12 D12, D13, E6, E12 | Client: closed with no reply; as the receiver, refused with the bound's name |
| 20 | more connections than `inflight_max` | not driven by the client alone; c13 D44 (the Python test support holds two connections open; the third is closed at once on a Silica node and on a C# node, with the same lines) | Node: `inflight_refused` |
| 21 | a tick during a shuffle in flight only ages | not reached by the client: it needs a second tick while the client's listener holds the first tick's shuffle open, and no trial here does that. Shown for the store of the extension by the store tests | |
| 22 | an empty view: the node asks a sentinel again | not reached: K's views are not empty once the client has answered its join | |
| 23 | `sample` as a peer request | c12 A2, A4, A5, B1, B3, B5, Q1, Q3; c16 26, 30, 32, 40 | Client: the reply's entries, each verified |
| 24 | application requests on a bridge: `call`, `cast`, the forbidden guard, the permission, the timeout, no error body | c16 1, 2 (call), 5 and 6 (cast), 7 (the function fails), 9 (timeout), 15 (forbidden), 16 (not permitted), 29 (a peer with a bridge token may call nothing) | Client: the `result` with the call's `req_id`, or closed with no reply (no error body ever). Bridge: `bridge_admitted`, `bridge_done`, `user_code_error`, `timeout`, `forbidden_mfa`, `permission_denied` |
| 25 | the bridge's function calls onward into TRUST | c16 3, 4 | Client: `demo:onward(20, 22)` answers 42, computed by T's `demo:add`. T: the request under the bridge's TRUST fingerprint |
| 26 | TLS: only TLS 1.3, ALPN `tempus/1`, a certificate self-signed over an Ed25519 key | the accepted case: every step. As the refusing side: c12 D18 (a certificate another key issued), D19 and E14 (a P-256 certificate), D20 (TLS 1.2 only), D21 (another ALPN name). The client cannot offer TLS 1.2, another ALPN or no certificate to a node; c13 D45 to D48 do that with the Python test support | Client: `refused at=tls` or `tls_failed at=tls` |
| 27 | draws from the platform's secure source | not a client operation | |
| 28 | boot refusals | not a client operation; the extension's node refuses the same faults with the Silica node's lines (node tests, against `trials/c4_tempus_boot`) | |
| 29 | a node learns bridges | c16 30 and 32 in part: the client, with a bridge token under a certificate the bridges list (x4), shuffles a bridge's entry into the other bridge's bridge store. A tick of the bridge store that dials a listening client is not driven here | Client: a later sample of that store holds the entry |
| 30 | an application gets a bridge | c16 30 and 31: a sample of B1's bridge store gives B2's entry, verified; the client dials the entry's address and its call is answered | Client: the sample's entry, then the result |
| 31 | a call crosses a bridge and the answer returns | c16 3 | Client: 42. T: the request came under B1's TRUST certificate |
| 32 | several bridges: any serves | c16 1 and 2, 3 and 4 | Client: the same results from each. T: calls under both fingerprints |
| 33 | a bridge is lost | c16 37 to 40: T is stopped (an onward call is closed, B2 itself still answers); B1 is stopped (a call to it is `unreachable`); a tick of B2's bridge store fails and B1's entry is gone | Client: closed, unreachable, then the empty sample. Bridge: `shuffle failed` |
| 34 | the bridge refuses an edge that misbehaves, without touching TRUST | c16 15 to 19: forbidden, not permitted, each twice; then a good request is refused. The extension cannot write a malformed TRUST request | Client: closed with no reply each time, then the good request closed too. Bridge: `bridge_score` up to 6, then `bridge_refused ... score 6 is above the limit 5`. T: no suspicion line for any of these |
| 35 | the bridge's rate and in-flight bounds per peer | c16 11 to 14 (two calls held, a third refused, another edge served, the held calls closed at the call timeout, then `release` answered); c16 21 to 23 (20 calls answered, the 21st refused, another edge served) | Client: the refusals and the results. Bridge: `bridge_inflight`, `bridge_rate` |
| 36 | the TRUST side of a bridge is plain TRUST | not a client operation | T: its own lines |
| 37 | test-only frames on a node built without the test unit | the extension cannot send them. c12 E10 shows the client's listener refusing a `tick` frame as a frame of no kind; c13 F2 sends `tick` and `clock` with the Python test support to a Silica node built without the test unit in its root and to a C# node that is not a test node | Node: `protocol_error ... not a request` on both |
| 17.7 | the bridge quarantined at T | c16 33 to 36: three calls of `demo:bad`, whose application calls T's `demo:secret/0`; T quarantines B1; `demo:onward` on B1 is then closed; B1 still answers `demo:add`; B2 still reaches T | Client: closed and nothing else. T: `suspicion` three times, `quarantined` |

Totals. Of the 34 rows a client can reach by its nature (all but 27, 28 and 36), the C# client causes and observes
27 in whole or in part: 1, 2, 3, 5, 6, 7 (in part), 8, 9, 10, 11, 12 (in part), 13, 14, 15 (in part), 17, 19 (in
part), 23, 24, 25, 26, 29 (in part), 30, 31, 32, 33, 34, 35. Rows 4, 16, 18, 20, 21, 22 and 37 are not reached by
the C# client, and row 7's preference and eviction are not; the reason for each is in its row. Each of those needs
a frame the extension does not hold (a test-only frame, or a frame that is malformed on purpose) or timing that only
a trial tool can arrange.

What the bridge trial shows that no other trial of the C# extension does: `call`, `cast` and `result` against a real
bridge. Before this trial they had been checked against the bytes the Python extension writes and against a peer of
the Python test support only.

Not shown here: what a client sees when a bridge's per-peer table is full; a `result` whose value is not an integer;
arguments that are not integers.
