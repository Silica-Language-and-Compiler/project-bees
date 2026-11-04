# BEES minimum viable product: messages across nodes

**Status: proposed 2026-11-04, revised the same day to work with standard Silica.** The first thing BEES ships that two
separate programs can use together. It is small on purpose and is meant to be built on. Companion documents:
[roadmap.md](roadmap.md) (decisions D1-D32 and milestones), [gap-ledger.md](gap-ledger.md),
[inter-nodal-modes.md](inter-nodal-modes.md) (the full design this grows into).

## 1. Definition

Two programs, each a **node** in its own operating-system process, exchange messages over a local network connection.
The programs are **ordinary Silica programs**: they use Silica's own actors, supervisors, spawn, `cast_registered`,
operators and types exactly as the Silica specification describes, and nothing in their source mentions the network.
A message cast to a name that lives on the other node is delivered there.

**Done when** a demo of two plain Silica programs passes its trials: a client on node b casts typed messages
(integers, floats, booleans, strings, atoms, tuples, records and lists) to a service on node a with ordinary Silica code;
the service answers by casting back; malformed and hostile frames are refused without harming the receiver; losing the
peer does not crash the sender; and message rate and memory are measured.

## 2. Rulings the MVP rests on

| Ruling | Effect |
| --- | --- |
| One node per operating-system process (2026-11-04). | The link between the nodes is a real transport. |
| **Standard Silica actors, operators and constructs, as the specification describes (2026-11-04).** | User code is unchanged: no BEES calls in it. A **proxy actor** registered locally under the remote actor's name stands in for it, so `cast_registered(:name, msg impl ActorMessage {})` works whether the name is local or remote. Messages are typed Silica values (structural records, tuples, lists), not dynamic terms. |
| Remote messages are addressed by **registered name**, not by pid (agreed). | No identity-to-actor table is needed. |
| BEES uses its **own compact encoding**, not ETF (D8, agreed). | ETF and BEAM mode wait. |
| Wire encoding, distribution and the balancer belong to BEES; bytes and the host belong to the compiler (2026-11-04). | The sockets exist only for BEES's own distribution and are not exposed to user code. |
| Every peer is named in the program (D16). | Peers and remote names are fixed at build time. |
| No monitors (D20). | Sends are fire-and-forget; a lost peer is seen only as the proxy ending (section 3.3). |

## 3. What the MVP contains

### 3.1 The schema: telling BEES which messages cross

Silica types are structural and Silica has no reflection, so a program states, in a small manifest file read by
`bees_config`, which remote actors it talks to and what message each accepts. The message type is written as Silica's
own type syntax, so it is the same text the actor's behaviour declares. Proposed (format open, section 9):

```
node   b
peer   a   127.0.0.1  7001  dial
remote counter @ a   cast  { op: atom, n: int64, reply_to: atom }
local  inbox         cast  { total: int64 }
```

- `remote name @ node cast <type>`: a name that lives on a peer. `bees_config` generates a **proxy actor** registered under
  `name` on this node. It is an ordinary cast-only Silica actor whose message type is `<type>`.
- `local name cast <type>`: a name on this node that the peer may cast to. `bees_config` generates the decoder that
  delivers to it with `cast_registered`.
- Every message type gets a small numeric **kind id**, assigned in manifest order, and the whole schema gets a digest
  computed at build time.

### 3.2 Units

| Unit | Role |
| --- | --- |
| `bees_wire` (generated parts and a small hand-written core) | Generated per message type: an encoder from the typed value to bytes and a decoder back. The core holds the byte, integer, float and string primitives (lookups and same-type arithmetic, no type conversion, as proven in spike S5). |
| `bees_ingress` | The security boundary. Checks every frame before and while it is decoded: size, nesting depth, element counts, UTF-8 in strings and atom spellings, kind id known, and that every atom is already held by the program. Any failure drops the frame silently toward the peer and writes an audit entry. |
| `bees_net` | The node: its name, the peer table, one **connection actor** per peer, the generated proxies and inbound deliverers. |
| `dangerous_bees_net` and the native edge | A small C archive and its Silica adapters: listen, accept, connect, write, read, poll with a timeout, close, on `127.0.0.1` only. Bytes cross in 8-byte words until `buf(uint8)` crosses the foreign-function boundary. |
| `bees_peers` and the proxy/deliverer units | **Generated** by `bees_config` from the manifest. |

Everything runs under the program's root supervisor, with the BEES listener and hub, as the compiler guide requires. A
proxy is a supervised child like any other actor.

### 3.3 Sending, receiving and failure

- **Send.** The user's code casts to the name. The local proxy receives the typed value, encodes it into a `send` frame
  and passes the bytes to its connection actor, which writes them through a `dangerous_` writer worker.
- **Receive.** A `dangerous_` reader worker per connection reads whole frames in word-sized calls and casts the raw words
  to the connection actor. The connection actor **re-creates** the frame (section 4), runs `bees_ingress`, decodes it to a
  typed value in a fresh region, and delivers it with `cast_registered` to the local name for that kind id. If no actor
  holds the name, the message is dropped and counted.
- **Reply.** There is no new mechanism. The request carries a `reply_to` name (an atom field in the message, as the
  Silica specification's own examples do with `reply_to`), and the service casts its answer to that name. On the service
  node that name is a proxy for an actor on the client's node.
- **Failure maps onto Silica's own rules, with no new failure kind.** When a connection is closed or fails, its proxies
  end themselves with `fail_self` and a reason. A cast to an ended actor fails the sender in Silica, so a sender
  learns of a lost peer the way it learns of any dead actor, and the supervisor restarts the proxy. There is no
  reconnect in the MVP, so a restarted proxy drops its messages until the program restarts the connection.

### 3.4 The wire (version 1, to be written in `contract/wire-v1.md`)

A **frame** is `u32 length (big-endian) | u8 version (1) | u8 kind | body`.

| kind | meaning | body |
| --- | --- | --- |
| 0 | hello | the sender's node name as an atom spelling, then the 8-byte schema digest |
| 1 | send | `u16` message kind id, then the value |

A **value** is encoded from its Silica type, with no tag bytes (the type is known from the kind id): integers of each width
big-endian (`int8` to `int64`, `uint8` to `uint64`), `float32` and `float64` as IEEE 754 big-endian, `boolean` as one
byte, `char` as its code point, `atom` as a `u8` byte count then UTF-8 spelling, `string` as a `u32` byte count then UTF-8
bytes, a tuple or record field by field in declared order, and `List[T]` as a `u32` count then the elements.

An atom travels as its **spelling**, because two programs have different atom tables; the receiver turns the spelling
back into its own atom with a lookup and refuses a frame whose atom it does not hold (D16). The spelling-to-atom lookups
in `bees_atoms` are therefore used **inside BEES** by the wire layer; they are not exposed to compilers.

**Types in the MVP:** the integer widths, `float32`, `float64`, `boolean`, `char`, `atom`, `string`, tuples, records
(including tagged tuples), and `List[T]` of these. **Not in the MVP:** `actor_ref`, regions and references, `buf`,
functions, sum types, optional references, and the standard data structures (maps, sets). A message type that uses one is
a build error from `bees_config`.

**Limits (proposed, tunable):** frame at most 4 KiB, nesting depth at most 16, at most 256 elements in a list, atom
spelling at most 255 bytes, string at most 1 KiB.

### 3.5 The handshake and the connection

1. The dialing node connects and sends a `hello` frame with its node name and schema digest.
2. The listening node checks the name against its peer table and the digest against its own. On any mismatch it closes
   the connection without a reply. Otherwise it replies with its own `hello`.
3. The dialer checks the reply the same way.
4. From then on either side may send `send` frames. Frames before a completed handshake are dropped.

There is **no authentication and no encryption** in the MVP; the demo binds to `127.0.0.1`, and every build prints a
banner that the transport is for testing only. TRUST (mutual TLS) replaces this step later.

## 4. The gate: receiving bytes from the network

Bytes returned by a foreign call are **tainted**, and Silica's rules stop a tainted value leaving the handler that
receives it. The compiler-derived re-creation trait (`Recreatable`) that would clean such values is **not delivered in
Silica yet**.

**Milestone M0 was run on 2026-11-04** ([spikes/S8-hand-recreation.md](spikes/S8-hand-recreation.md)) to see whether BEES
could re-create received bytes by hand, rebuilding each value from literals by branching on the tainted bytes. **It
cannot.** Silica's checker treats every value derived from a tainted one as tainted, a `case` over literals included, and
rejects it in the worker's `produces pure` (E2100). The only thing that compiles is forwarding the raw value from the
receiving handler, which the specification forbids and Silica does not check; the MVP does not build on it.

**Consequence:** the **receive path waits on Silica's `Recreatable`** (Silica ROADMAP chunk 13). Everything else in the
MVP does not: the schema and generators, the wire codec, the sockets, the sending half, the handshake and the proxies
can be built and tested now, with the receive step stubbed behind one function (`bees_ingress@recreate`) that will call
`recreate` when it exists.

## 5. Milestones

Each milestone ends with trials in `trials/`, run by `make -C trials integrate`; the paired-process ones also run through
a small driver script that starts two executables and compares their outputs.

| # | Milestone | Exit criteria |
| --- | --- | --- |
| **M0** | **Done 2026-11-04: blocked.** Re-creation by hand does not pass Silica's checker (trial `m0_recreation`, note S8). | The written finding: the receive path needs `Recreatable`. |
| **M1** | The schema manifest, the `bees_config` generator for encoders and decoders, and the `bees_wire` core. In memory only. | Round-trip trials for every supported type and for nested values; rejection trials for truncated, oversized, too-deep, over-long, unknown-atom, unknown-kind and bad-UTF-8 input; a message type with an unsupported field is a build error; no allocation grows without bound on rejection. |
| **M2** | The native edge sockets, `127.0.0.1` only, with a poll timeout. | Two OS processes exchange one frame of words over a TCP connection; the listener refuses non-local addresses. |
| **M3** | `bees_net` and `bees_ingress`: the generated peer table, proxies and deliverers, the handshake, delivery by registered name. | Two plain Silica programs complete the handshake and a cast to a remote name arrives; a connection from an unlisted node, or with a different schema digest, is closed; a frame before the handshake is dropped; a closed connection ends its proxies. |
| **M4** | The demo and measurements. A plain Silica service on node a and a client on node b exchange casts with a payload that uses every supported type, the service answering through `reply_to`; a node stopped mid-run; a hostile frame injected. | The answers arrive with the payload intact; the surviving node's sender sees only Silica's normal dead-actor behaviour; the hostile frame is refused; message rate and each node's peak memory are recorded in a spike note. |
| **M5** | Documentation. `contract/wire-v1.md`; the schema manifest and node behaviour added to the compiler guide's "what BEES provides"; roadmap updated (Track B slice done to this point). | The wire spec is complete enough that a second implementation could be written from it. |

## 6. Dependencies

| Dependency | State |
| --- | --- |
| Silica FFI (`dangerous_` workers, several messages per worker) | Works (spike S4 and the re-run). |
| `buf(uint8)` across the foreign-function boundary | Not delivered. The edge moves 8 bytes per call as an `int64`. |
| Silica re-creation (`Recreatable`) | Not delivered, and no hand-written substitute passes the checker (M0). **Blocks the receive path.** |
| Registered names (`spawn_registered`, `cast_registered`) | Work. Silica's later `register` / `whereis` are not needed. |
| The exit listener and hub | Exist (A2). |
| A pair-of-processes trial driver | New, small. |
| `bees_config` schema and peer generators | New. |
| A C compiler for the edge | `clang`, already used for `native/`. No downloads. |

## 7. Out of scope, with where each goes next

| Left out | Why, and where it goes |
| --- | --- |
| **Synchronous `call` across nodes.** | A Silica call returns its reply at the end of the callee's dispatch, and results of foreign calls reach an actor as casts, so a proxy cannot hold a call open until the network reply arrives. The `reply_to` cast above covers the need. It becomes possible with a Silica deferred reply or a foreign call that returns to its caller; it is a Silica request to file. |
| Dynamic terms (`bees_term`) as a message type | A second codec kind (tagged terms) on the same frames, for compilers of dynamic languages. |
| Sum types, optional references, maps and sets, `buf` | Added to the codec one at a time. |
| TLS, mutual authentication, certificates | TRUST (roadmap B1); needs the TLS engine (spike S12) and re-creation. |
| Sends to a pid, links, remote spawn, node-down notification | After the MVP, once an identity-to-actor table or Silica's registry exists. |
| ETF, EPMD, BEAM-compatible mode | Roadmap B3 and B4. |
| Reconnect, backoff, flow control, more than one frame in flight | A later step on the same connection actor. |
| More than two nodes | The peer table already supports it; the demo uses two. |
| Frames larger than 4 KiB | Raised when `buf(uint8)` crosses the foreign-function boundary. |
| Windowed multiplexing and cancel-by-close | Roadmap B2. |

## 8. Risks

- **The receive path waits on Silica's `Recreatable`** (M0 result). Mitigation: build and test everything else; stub the
  receive step behind one function; ask Silica to prioritise chunk 13.
- **A generator must understand Silica type syntax.** It reads a restricted subset of the type grammar. Mitigation: start
  with records, tuples, `List[T]` and the primitives; reject the rest at build time.
- **Word-sized foreign calls are slow.** 4 KiB is 512 calls per frame. Acceptable for the MVP; measured in M4.
- **The proxy is a second name registered under the same atom as the remote actor.** The name must not also exist locally;
  `bees_config` rejects a manifest that declares a name both ways.
- **One listener for exits.** The failure listener handles about 20,000 reports per second and sees every actor end; not
  an MVP concern unless the demo spawns heavily.
- **Silica's failure-report text is the listener's interface.** A change to it breaks exit tracking, not message passing.

## 9. Open points for a human

1. The manifest format in section 3.1, the port numbers, and whether the schema is one file per program or per unit.
2. The proposed frame and field limits in section 3.4.
3. Whether a cast to a name nobody holds should leave an audit entry (proposed: yes, counted, not per message).
4. Whether a lost connection should end its proxies (proposed) or leave them running and drop silently, which hides
   the failure from the sender but matches the earlier "fire-and-forget" wording.
