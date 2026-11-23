# The client half of the Kotlin extension: coverage of the behaviour list (design 16.2)

Three trials use the client half of the Kotlin extension (`example_tempus_clients/kotlin`: `dial` and `Listener`).

- `trials/c6_tempus_kotlin`: the walk `Walk.kt` against node K (a test program) and node Q (not a test program).
  Recorded for the Mac. Its steps are written A1 to A5, B1 to B5, C1 to C13 and so on, as its golden `kotlin` prints
  them.
- `trials/c9_tempus_node_kotlin`: the program `Net.kt`, in which the client is the trial's own peer beside nodes of
  the Kotlin extension and Silica nodes. Recorded for the Mac. Its steps are written c9 A1 and so on.
- `trials/c11_tempus_bridge_kotlin` (this directory): the walk `Bridge.kt` against the bridges B1 and B2 and the TRUST
  node T, the network of `trials/c3_tempus_bridge` on this trial's own ports. Recorded for the Mac. Its 43 steps are
  numbered through sections A to F, as its golden `kotlin` prints them; they are written c11 and the number below.

The extension's sources are in `example_tempus_clients/kotlin/lib`. All three trials are declared for the Mac alone
(their `platforms` files), because the Kotlin compiler and a JDK 27 are installed there only.

"Client" in the last column means the Kotlin client sees the result on the wire and the trial checks it. "Node" means
the result is read from the node's own recorded output, because no frame shows it (ruling NQ-1). The Kotlin client
has no function that misbehaves on purpose and builds no test-only frame. Where a row needs a `tick` or a `clock`
frame, the trial tool sends it with the Python test support, and where a row needs a peer that misbehaves, the Python
test support plays it.

| Row | Behaviour | Kotlin client | Result observed |
| --- | --- | --- | --- |
| 1 | three isolated stores | c6 A2, A5, B1 | Client: a sample of one store answers from that store. Node: the boot lines |
| 2 | join through a sentinel | c6 A1 (the client listens as the sentinel before K starts) | Client: the three `sample` requests. Node: the join lines |
| 3 | leaves; others forget it | c11 41 and 42 (B1 is stopped, a tick of B2's bridge store, then a sample). c9 C4 shows the same for an entry at an address where nobody listens, on a node of the extension | Client: the sample no longer returns the entry. Node: the dial fails. A client cannot stop a node: that is the trial's act |
| 4 | tick: every age rises | c11 26 and 27 (the entry x2 goes in at age 2 and arrives in the tick's shuffle frame at age 3) | Client: the age in the frame its listener receives |
| 5 | tick: the partner is the oldest | c6 B4 (the client is dialed at the third tick, when it is the oldest, and not before); c11 27 (the client, at age 5, is dialed and x2, at age 2, is not) and 29 (then x2 is the oldest) | Client: it is dialed. Node: the `shuffle with` lines |
| 6 | tick: the buffer, and it leaves the view | c6 B4 | Client: the frame holds the node's own entry at age 0 |
| 7 | merge: younger preferred, oldest evicted | c11 28 (the listener answers with the same peer at a younger age; the next sample shows the younger entry). Eviction of the oldest is not reached on the wire by this client: with the stores of these trials (capacity 4, shuffle length 3) a merge never exceeds the capacity. It is shown by the extension's own view against the Python model (c9 `tests`) | Client: the sample after the merge |
| 8 | shuffle as responder | c6 B2 | Client: the `shuffle_reply`, then itself in a sample |
| 9 | each store, no mixing | c6 A2 to A5 (sentinel, bridge), B (edge), C8 (an edge's entry offered to the sentinel store) | Client: closed with no reply. Node: `entry_refused` |
| 10 | a store of another type: no own entry | c6 A3; c11 27 (a bridge's edge store) | Client: the frame holds no entry for the node |
| 11 | admission accepted | every step that is answered | Client: the reply. Node: `admitted` |
| 12 | admission refused, each cause | c6 C1 to C5 (signature, expired, not yet valid, `sub`, a type the certificate may not carry); c11 24 (a bridge token under a certificate the bridge does not list). Not reachable by this client: an `id` that is not the hash of the key, a wrong proof and no proof, because it always computes the id and always sends its proof. c9 D10 and D11 show the wrong proof and the missing proof for a node of the extension and a Silica node, driven by the Python test support; the `id` case is one of the admission cases of `trials/t4_tempus_admission` that the extension's own tests judge (c6 `tests`, c9 `tests`) | Client: closed with no reply. Node: the audit line |
| 13 | rotated key | c6 C6 | Client: the `key_rotated` frame and the kid it names |
| 14 | the node proves itself | every step (the client verifies the node's proof before its request) | Client: no refusal |
| 15 | the node's own token: refresh and expiry | Expiry: c6 C11 (the client's clock past the node's token). Refresh: not reached by this client. It is the act of the node's application; the bridges' application of c11 does not do it, and c6's node K does it only after a peer answers `key_rotated`, which this client's listener would have to do with a verifier that names another kid. c9 E6 and E7 show expiry and refresh on a node of the extension | Client: it refuses the node's advert after the expiry |
| 16 | entries whose token expired leave the view | c11 31 and 32 (the bridge's clock is set to 1700 with the test support's `clock` frame, a tick, then a sample) | Client: the entry is in no later sample. Node: `expired in` |
| 17 | a gossiped entry that does not verify | c6 D (the client's own refusal of a reply with a forged entry, from the Python test support listening) and E (of a shuffle with one, from the Python test support dialing) | Client: `refused`, and it uses nothing of the frame |
| 18 | partner unreachable, closes early, silent, violating | c11 29 (unreachable); the others need a peer that misbehaves, which this client is not | Node: `shuffle failed`. Client: the next sample |
| 19 | bounds | c6 C7, C9 (a sample above the shuffle length, too many entries). This client cannot send an oversize frame, an age above 65535, a wrong field length or an unknown key: its functions refuse to build them. c9 D13, D14, D16 to D19, D22 and D26 show an oversize frame, too many entries, an age above 65535 and a byte after the frame for a node of the extension and a Silica node, driven by the Python test support | Client: closed with no reply |
| 20 | more connections than `inflight_max` | c11 16 (four calls held open at a bridge whose application holds them, then a fifth connection). The client makes one connection for each `dial` and closes it when it is answered, so it can hold connections open only in this way. c9 D27 shows the limit on a node of the extension and a Silica node | Client: the fifth is closed before any frame. Node: `inflight_refused` |
| 21 | a tick during a shuffle in flight only ages | c11 30 (the client's listener holds the tick's shuffle open for 2.5 s while the tool sends a second tick) | Client: it is dialed once. Node: `aged only` |
| 22 | an empty view: ask a sentinel again | not reached by this client's trials; c9 does not show it either (its test nodes' ticks are of stores that hold an entry) | |
| 23 | `sample` as a peer request | c6 B1, B3, B5 | Client: the reply |
| 24 | application requests on a bridge | refused by a node that is no bridge: c6 C10 (the client's own refusal). On a bridge: c11 1 to 6 (calls and a cast) and 7 to 12 (a function that fails, the timeout, the forbidden guard, the permission of the peer's type; no error body in any of them) | Client: the `result`, or a close with no reply |
| 25 | the bridge's function calls onward into TRUST | c11 3 and 4 | Client: 42, computed by the TRUST node. Node: T's line `admitted ... call demo:add/2` under the bridge's TRUST certificate |
| 26 | TLS profile | the accepted case in every step; c6 D18 to D21 and E14 (the client's own refusals of a certificate another key issued, a P-256 key, TLS 1.2 and another ALPN, played by the Python test support) | Client: `tls_failed` or `refused` at the handshake |
| 27, 28, 36 | draws, boot refusals, the TRUST side | not reachable by a client by their nature (design 16.2) | |
| 29 | a node learns bridges | c11 33 (B1's entry shuffled into B2's bridge store by a peer with a bridge token) and 42 (a tick of that store). The bridges of this trial have no sentinel and no other bridge to learn from by themselves | Client: the sample |
| 30 | an application gets a bridge | c11 33 and 34 (an edge samples the bridge store, dials the address of the entry and is answered there) | Client: the entry, and the result of the call |
| 31, 32 | a call crosses a bridge; several bridges | c11 1 to 4 | Client: the same result from each |
| 33 | a bridge is lost | c11 41 to 43 | Client: `unreachable`, then the entry is gone from the sample, then a call through the other bridge is answered |
| 34 | the bridge refuses an edge that misbehaves | c11 13 and 14 (six refused requests, then a good one refused for its score) | Client: closed with no reply. Node: `bridge_refused`; T's output has no line for any of them |
| 35 | the bridge's rate and in-flight bounds | c11 15 (a third request of an edge that has two calls in flight), 19 to 21 (the rate) | Client: the third request and the twenty-first are closed; another edge is served. Node: `bridge_inflight`, `bridge_rate` |
| 37 | test-only frames on a node built without the test unit | not reachable by this client: the extension builds no `tick` and no `clock` frame, and `dial` sends only its four kinds of request. c9 F2 shows a Silica node and a node of the extension, neither of them a test node, refusing the three test frames sent by the Python test support | Node: `protocol_error ... not a request` |
| 17.7 | the TRUST side refuses, or cannot be reached | c11 35 to 40 (T quarantines B1; then T is stopped) | Client: closed with no reply, and nothing else |
