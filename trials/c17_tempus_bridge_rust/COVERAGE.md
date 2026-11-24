# Coverage of the behaviour list (design 16.2) by the client half of the Rust extension

The client half of the Rust extension is the crate `example_tempus_clients/rust/lib/tempus` (its modules outside
`node`), driven through its command line `tempus-client`. Three trials run it against real nodes, and each has
recorded outputs for a Mac with Apple Silicon:

- `trials/c14_tempus_rust`: steps N0 to N18 (node N, a test node), P0 to P5 (node P, which reads the machine's clock),
  X1 and X2 (against the Python test support, with no node).
- `trials/c15_tempus_node_rust`: steps K1 to K15, against the Silica sentinel S and the Silica edge E of that trial.
  Recorded as `client`.
- `trials/c17_tempus_bridge_rust` (this directory): steps A to H, against the bridges B1 and B2 and the TRUST node T.
  Recorded as `rust`.

"Client" in the last column means the Rust client sees the result on the wire and the trial checks its line. "Node"
means the result is read from the node's own recorded output, because no frame shows it (ruling NQ-1). The Rust
client has no function that misbehaves on purpose and builds no test-only frame. Where a row needs a tick or a clock
reading, the trial tool sends that frame with the Python test support, and the Rust client is the peer that the
node then dials or answers. Where a row needs a wrong frame, the Rust client can only send bytes another program
wrote (`raw HEX`).

| Row | Behaviour | Rust trial and step | Result observed |
| --- | --- | --- | --- |
| 1 | three isolated stores | c14 N0, N1, N2 | Node: the boot lines. Client: a sample of one store answers from that store |
| 2 | join through a sentinel | c14 N0, P0 (the client listens as the sentinel before the node starts); c17 A1 | Client: the three `sample` requests, one for each store. Node: the join lines |
| 3 | leaves; others forget it | c14 N5 (the node's first tick dials an address where nobody listens) | Node: the dial fails and the entry is gone. A client cannot stop a node: that is a trial's act |
| 4 | tick: every age rises | c14 N5; c15 K4, K6 | Node: the view lines. Client: the ages in the frames it receives |
| 5 | tick: the partner is the oldest | c14 N5; c15 K6 (four ticks before the client is the oldest) | Client: it is dialed when it is the oldest and not before. Node: the `shuffle with` lines |
| 6 | tick: the buffer, and it leaves the view | c14 N5; c17 B2 | Client: the frame holds the node's own entry at age 0. Node: the view while the shuffle runs |
| 7 | merge | c14 N5, N6 | Client: the sample N6 holds the entry the client answered with. Node: the view line. What the client cannot choose: it answers with the entries it was started with, so "a duplicate younger, a duplicate older, more than fit" are shown by the Python and Silica clients only (`trials/c2_tempus_clients`) |
| 8 | shuffle as responder | c14 N3, N4, P2, P3; c15 K12, K13 | Client: the `shuffle_reply`, then itself at age 0 in a sample |
| 9 | each store, no mixing | c14 N1, N2, N12; c15 K3 | Client: per-store answers; the mixed frame is closed with no reply. Node: `entry_refused` |
| 10 | a store of another type: no own entry; the partner put back at age 0 | c15 K4, K5 | Client: the sentinel's shuffle frame of its edge store holds no entry for the sentinel. Node: the view line after the merge holds the client at age 0 |
| 11 | admission accepted | every step that is answered | Client: the reply. Node: `admitted` |
| 12 | admission refused, each cause | c14 N7 (expired), N8 (not yet valid), N9 (signature); c15 K11 (`sub`); c17 D3, D4 (a type the node does not allow for that certificate) | Client: closed with no reply. Node: the audit line. Not reachable by this client: an `id` that is not the hash of the key, a wrong proof and no proof, because it always computes the id and always sends its proof. `trials/c15_tempus_node_rust` steps R7 and R10 to R13 show them for a node of the Rust extension, done by the Python test support |
| 13 | rotated key | c14 N10 | Client: the `key_rotated` frame naming k1. Node: the audit line |
| 14 | the node proves itself | every step | Client: its verifier accepts the node's signature before the request is sent |
| 15 | the node's own token: refresh and expiry | expiry: c15 K15. Refresh: not shown for this client | Client: it refuses the node's advert. Node: `ticking has stopped`. The refresh is the act of the node's application; no node of a Rust client trial refreshes its token (`trials/c2_tempus_clients` steps 48 to 51 show it) |
| 16 | expired entries leave the view | c15 K12 to K14 | Node: `expired in tempus_edge`. Client: the entry is in no later sample |
| 17 | a gossiped entry that does not verify | c15 K6, K7 | Node: `entry_refused`, the partner dropped. Client: none of its answer in the next sample |
| 18 | partner unreachable, closes early, silent, violating | unreachable: c14 N5. Violating: c15 K6. Closes early and silent: not reachable by this client | Node: `the partner did not answer` with the reason. The client's listener always answers at once and has no switch to close early or stay silent |
| 19 | bounds | c14 N11 (a sample above the shuffle length); c15 K8 (an unknown key), K9 (an age above 65535), K10 (no term) | Client: closed with no reply. Node: `protocol_error` with the bound. An oversize frame is not reachable: the client refuses to send a body above the ceiling |
| 20 | more connections than `inflight_max` | c17 F2 | The client makes one connection for each run and closes it when it is answered; it can hold connections open only at a bridge whose application holds its calls |
| 21 | a tick during a shuffle in flight | not reachable by this client | its listener answers a shuffle at once, so no shuffle stays in flight |
| 22 | an empty view: ask a sentinel again | c17 A2 | Client: the listening sentinel receives a `sample` again. Node: `the view is empty` |
| 23 | `sample` as a peer request | c15 K1, K2 | Client: the same answer twice |
| 24 | application requests on a bridge | refused by a node that is no bridge: c14 N13, N14. On a bridge: c17 C1 to C7, E1 to E6 | Client: the `result`, or a close with no reply |
| 25 | the bridge's function calls onward into TRUST | c17 C2, C3 | Client: 42, computed by the TRUST node |
| 26 | TLS 1.3 only, ALPN, the certificate | the accepted case: every step. The refusals: not reachable by this client | it offers only the `tempus/1` profile. Its own refusals of a peer's TLS are c14 X1.28 to X1.30 and X2.18 to X2.21 |
| 27 | draws from the platform's source | not a client's act | |
| 28 | boot refusals | not a client's act | |
| 29 | a node learns bridges | c17 B0 to B2 | Client: the listening client with a bridge token is dialed |
| 30 | an application gets a bridge | c17 B3, B4 | Client: the sample's entry, then the call through that bridge |
| 31 | a call crosses a bridge and the answer returns | c17 C2 | Client: the result. T: the request came under the bridge's TRUST certificate |
| 32 | several bridges: any serves | c17 B4, C1, C2, C3 | Client: the same results from each |
| 33 | a bridge is lost | c17 H1 to H3 | Client: unreachable once, an empty sample, then an answer through the other bridge |
| 34 | the bridge refuses an edge that misbehaves, without touching TRUST | c17 E1 to E8 | Client: closed each time, then a good request closed too. Bridge: the score lines |
| 35 | the bridge's rate and in-flight bounds per peer | in flight: c17 F1, F3, F4. Rate: not walked | the rate bound needs more than 20 requests of one edge |
| 36 | the TRUST side of a bridge is plain TRUST | not a client's act | |
| 37 | test-only frames on a node that is not a test program's | not shown for this client | it builds neither frame. `trials/c15_tempus_node_rust` steps M4 to M6 show a Silica node and a node of the Rust extension refusing them in the same words, sent by the Python test support |

Also in `trials/c17_tempus_bridge_rust` and no row of the list: the whitelist rule for a bridge certificate
at the client (D1, D2) and at the bridge (D3, D4); the TRUST node refusing the bridge's own request (G1, G2) and the
TRUST node stopped (G3, G4), which the client sees as a close with no reply while the bridge goes on answering what it
runs itself.

Also no row of the list, in `trials/c14_tempus_rust`: a reply must be the reply of its request
(`example_tempus_clients/writing-a-tempus-client.md`, section 8). Steps X1.17 to X1.24 show the client refusing a
sample reply for another store, a sample reply with more entries than the sample asked for, a shuffle reply or the
`done` frame where a sample reply was due, a sample reply where a shuffle reply was due, a shuffle reply for another
store, a result that carries another request identifier, and a sample reply where a result was due. Steps X1.11,
X1.25 and X1.26 show it refusing a whole reply for one entry that does not verify (another key's signature, a token
of another type than the store, an expired token).

Rulings that are no row of 16.2:

| Ruling | Behaviour | Rust trial and step | Result observed |
| --- | --- | --- | --- |
| NQ-11 | a node that is not a test node reads the system clock | c14 P0 to P5 | Client: admitted with a token valid now; closed with a token that has expired or is not valid yet by the machine's clock |
| NQ-12 | a joiner keeps the sentinel it joined through | c14 N1 | Client: the sample of the node's sentinel store holds the client's sentinel identity |
| NQ-14 | one time bound from the accept to the close | not reachable by this client | it cannot stay silent |
| NQ-15 | the partner put back in a store of another type | c15 K5 | Node: the view line |
| NQ-17 | a node whose own token has expired still answers | c15 K15 | Client: the node's advert arrives and the client refuses it |
