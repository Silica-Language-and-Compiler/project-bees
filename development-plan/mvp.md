# BEES minimum viable product: messages across nodes

**Status: proposed 2026-11-04; revised the same day to work with standard Silica and to use the Erlang distribution protocol (D34).** The first thing BEES ships that two
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
| **The underlying protocol matches the BEAM and Erlang (D34, 2026-11-04), for every mode.** The MVP is BEES to BEES using Erlang-compatible bytes. | The wire is the Erlang distribution protocol and ETF, not a BEES encoding. Interoperating with real Erlang nodes (and EPMD discovery) follows the MVP. |
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
| `bees_ingress` | The security boundary. Checks every frame before and while it is decoded: size, nesting depth, element counts, text in strings and atom spellings (ASCII only in the MVP), kind id known, and that every atom is already held by the program. **In M1 these checks live inside the decoder, in `bees_wire` (they must run before anything is allocated, so they cannot be a separate pass); the `bees_ingress` unit of M3 adds the audit entry and the delivery policy and calls them, rather than repeating them.** Any failure drops the frame silently toward the peer and writes an audit entry. |
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

### 3.4 The wire: the Erlang distribution protocol (D34)

BEES sends what an Erlang node sends. The MVP implements the following profile; the exact set of distribution flags is open
(section 9) and will be fixed against OTP's documentation and a real node. **The byte layouts below are from my knowledge of
the OTP distribution protocol and have not yet been checked against a real node.** The installed `erl` can generate ETF test
vectors (`term_to_binary`) to check the codec before any interop.

**Handshake (version 6), 2-byte length framing before it completes:**

| step | tag | contents |
| --- | --- | --- |
| initiator sends | `N` | flags (8 bytes), creation (4), name length (2), node name |
| acceptor replies | `s` | status text, `ok` to continue |
| acceptor sends | `N` | flags (8), challenge (4), creation (4), name length (2), node name |
| initiator sends | `r` | its own challenge (4), then the 16-byte digest |
| acceptor sends | `a` | the 16-byte digest |

The digest is **MD5 over the cookie followed by the challenge written as a decimal string**. The cookie is a build-time
constant in the manifest. MD5 is written in Silica (32-bit words by same-type arithmetic). Challenges come from a PRNG
seeded from Silica's `monotonic_time`: **not secure, test-only**; secure random bytes arrive through the foreign-function
boundary and are tainted, so they wait on Silica's re-creation, as the receive path does. A node name the program does not
hold is refused (D16).

**After the handshake**, frames carry a 4-byte big-endian length. A zero length is a net tick, answered in kind. A message
is the byte `p` (pass-through), then the control message as ETF, then the payload as ETF. The MVP sends and receives one
control message, `REG_SEND` (`{6, FromPid, '', ToName}`), which is exactly "send to a registered name on that node". Any
other control message is dropped and counted. `FromPid` is a pid of the sending node built from the sending proxy's 64-bit
identity (the id and serial fields).

**ETF, from the declared Silica type** (the target name fixes the type; there is no message-kind id on the wire):

| Silica type | ETF |
| --- | --- |
| `int8` to `int64`, `uint8` to `uint64`, `char` | the smallest of small integer, integer, small big; the decoder accepts any valid encoding that fits the type, and refuses anything outside its range |
| `float32`, `float64` | new float (8 bytes, IEEE 754 big-endian); a `float32` is refused if the value does not fit exactly; infinity and NaN are refused |
| `boolean` | the atoms `true` and `false` |
| `atom` | small atom UTF-8 or atom UTF-8, by spelling; refused if the program does not hold it (D16) |
| `string` | binary |
| tuple, record | small tuple (large tuple above 255), fields in declared order |
| `List[T]` | list with a nil tail; the empty list is nil |

The decoder checks the whole term against the declared type and refuses a mismatch, an unknown tag, a bad length, a non-proper
list, or a term outside the limits. **The M1 rules carry over:** text is ASCII only, the limits (frame 4 KiB, depth 16, 256
list elements, atom 255 bytes, string 1 KiB), bounds-checked reads that reject instead of faulting, and nothing allocated
before the checks. **Not in the MVP:** pids, references, ports and funs as values, maps, big integers beyond 64 bits, atom
caches and the distribution header, compressed terms, atoms outside ASCII, tagged tuples.

**The manifest** keeps `message <name> <silica type>` and adds, in M3: this node's name and cookie, `peer` lines (name, host,
port, `listen` or `dial`), and `remote` / `local` lines that tie a registered **name** to its message type. Kind ids and the
schema digest from the first codec are no longer on the wire; a schema mismatch shows up as a refused frame.

### 3.5 The connection

1. The dialing node connects and runs the handshake above; the listening node checks the peer's name against its peer table
   and the cookie digest. On any failure it closes the connection.
2. After the handshake, either side sends `REG_SEND` messages and net ticks. A frame before the handshake completes is dropped.
3. A tick is sent when the connection has been idle for a fraction of the tick time; a peer that sends nothing for the tick time
   is treated as lost, its connection closes and its proxies end (section 3.3).

There is **no encryption and only a shared-secret cookie** in the MVP; the demo binds to `127.0.0.1`, and every build prints a
banner that the transport is for testing only. TRUST's security options (mutual TLS and certificate fingerprints) replace this
step later, on the same protocol.

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
| **M1** | **Done 2026-11-04 as a typed tag-free codec (in memory only; superseded in part by M1b, D34; see [spikes/M1-wire-codec.md](spikes/M1-wire-codec.md)).** The schema manifest, the `bees_config` generator for encoders and decoders, and the `bees_wire` core. | Round-trip trials for every supported type and for nested values (`m1_wire_types`); rejection trials for truncated, oversized, too-deep, over-long, unknown-atom, unknown-kind, bad-text and other hostile input (`m1_wire_reject`); word packing (`m1_wire_words`); a message type with an unsupported field is a build error (`tools/test_bees_wire_gen.py`); no allocation grows on rejection: 200,000 frames, 1.9 MB peak (`m1_wire_memory`). Excluded and why: tagged tuples (atom-literal types), `float16`, non-ASCII text. |
| **M1b** | Retarget the M1 generator and `bees_wire` from the typed tag-free encoding to **ETF** (D34): the encoders and decoders per type, dispatch by target name, ETF integers of every width and encoding, floats, atoms, binaries, tuples, lists; keep the manifest, limits, rejection reasons and the memory behaviour. Test vectors generated by the installed `erl` (`term_to_binary`) are the oracle. | Every supported type encodes to the same bytes as `term_to_binary` and decodes from every valid encoding (including the ones `erl` can produce for the same value); the rejection trials of M1 pass on ETF; the memory check holds. |
| **M2** | The native edge sockets, `127.0.0.1` only, with a poll timeout. | Two OS processes exchange one frame of words over a TCP connection; the listener refuses non-local addresses. |
| **M3** | `bees_net`, `bees_dist` and `bees_ingress`: MD5, the handshake, ticks, `REG_SEND`, the generated peer table, proxies and deliverers, delivery by registered name. | Two plain Silica programs complete the version-6 handshake and a cast to a remote name arrives; a connection from an unlisted node or with a wrong cookie is closed; a frame before the handshake is dropped; a tick keeps an idle link alive and its absence ends the proxies. The MD5 and the digest equal `erl`'s (`erlang:md5`). |
| **M4** | The demo and measurements. A plain Silica service on node a and a client on node b exchange casts with a payload that uses every supported type, the service answering through `reply_to`; a node stopped mid-run; a hostile frame injected. | The answers arrive with the payload intact; the surviving node's sender sees only Silica's normal dead-actor behaviour; the hostile frame is refused; message rate and each node's peak memory are recorded in a spike note. |
| **M5** | Documentation. `contract/wire-v1.md` rewritten as the Erlang profile BEES implements (flags, control messages, ETF subset, limits); the node behaviour added to the compiler guide's "what BEES provides"; roadmap updated. | The profile is complete enough that a second implementation could be written from it, and says exactly where it differs from OTP. |

## 6. Dependencies

| Dependency | State |
| --- | --- |
| Silica FFI (`dangerous_` workers, several messages per worker) | Works (spike S4 and the re-run). |
| `buf(uint8)` across the foreign-function boundary | Not delivered. The edge moves 8 bytes per call as an `int64`. |
| Silica re-creation (`Recreatable`) | Not delivered, and no hand-written substitute passes the checker (M0). **Blocks the receive path.** |
| Registered names (`spawn_registered`, `cast_registered`) | Work. Silica's later `register` / `whereis` are not needed. |
| The exit listener and hub | Exist (A2). |
| A pair-of-processes trial driver | New, small. |
| MD5 (the handshake digest) | New, in Silica (32-bit words, same-type arithmetic); checked against `erlang:md5` from the installed `erl`. |
| A PRNG seeded from Silica's `monotonic_time` for handshake challenges | New; insecure, test-only. Secure random waits on re-creation. |
| Erlang/OTP on the development machine | Installed (`/usr/local/erlang`, `epmd`, `erl`). Used only to generate test vectors in M1b and M3, not at run time. |
| `bees_config` schema and peer generators | New. |
| A C compiler for the edge | `clang`, already used for `native/`. No downloads. |

## 7. Out of scope, with where each goes next

| Left out | Why, and where it goes |
| --- | --- |
| **Synchronous `call` across nodes.** | A Silica call returns its reply at the end of the callee's dispatch, and results of foreign calls reach an actor as casts, so a proxy cannot hold a call open until the network reply arrives. The `reply_to` cast above covers the need. It becomes possible with a Silica deferred reply or a foreign call that returns to its caller; it is a Silica request to file. |
| Dynamic terms (`bees_term`) as a message type | ETF already carries tagged terms; a decoder to `bees_term` is the next step for compilers of dynamic languages. |
| Sum types, optional references, maps and sets, `buf` | Added to the codec one at a time. |
| TLS, mutual authentication, certificates | TRUST's security options on the same protocol (roadmap B1); need the TLS engine (spike S12) and re-creation. |
| Sends to a pid, links, remote spawn, node-down notification | After the MVP, once an identity-to-actor table or Silica's registry exists. |
| EPMD discovery, and interoperating with real Erlang nodes | Next after the MVP (roadmap B3): EPMD registration and lookup, the full distribution flag set, and testing against `erl -sname`. |
| Pids, references, ports and funs as values; links; remote spawn; the distribution header and atom cache | Later control messages and terms on the same protocol (roadmap B3, B4). |
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

1. The set of distribution flags BEES offers and requires, the handshake's `creation` value, and the tick time. To be fixed
   against OTP's documentation and a real node; the byte layouts in section 3.4 are from memory and unchecked.
2. The manifest lines for the node name, the cookie, peers and remote and local names (M3), and whether the cookie belongs in
   a manifest at all (it is a build-time constant and test-only here).
3. The proposed limits (frame 4 KiB, depth 16, 256 list elements, atom 255 bytes, string 1 KiB), now measured against ETF.
4. Whether a cast to a name nobody holds should leave an audit entry (proposed: yes, counted, not per message).
5. Whether a lost connection should end its proxies (proposed) or leave them running and drop silently.
6. How a `float32` that does not fit exactly, and a `uint64` above the `int64` range, should be handled when ETF can carry
   them (proposed: refuse the first, accept the second as a small big).
