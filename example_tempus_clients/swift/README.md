# The Swift TEMPUS extension

This directory holds the Swift extension for TEMPUS: Swift code that an application written in Swift uses to be a
TEMPUS client or a TEMPUS node. TEMPUS is the gossip membership mode of BEES: nodes find each other by exchanging small
signed records over mutually authenticated TLS 1.3 connections. A node is a program that is a member of a TEMPUS
network: it listens, keeps three lists of other members (its stores), and exchanges parts of them with other members.
A client is a peer that connects to a node, makes one request and reads the answer.

[The directory's README](../README.md) says that everything in `example_tempus_clients/` is an example only and must
not be used in production. That statement is the project owner's to change, and it stands: the keys, certificates and
tokens the extension is run with in this repository are test fixtures made from fixed seeds that anyone can reproduce,
and the code has had no review as production code. The section "What stands between this extension and production
use" below lists what has and has not been reviewed and tested.

This directory is the join of two lines of work, and it holds two implementations of gossip membership side by side.
The owner has not yet decided which of the two is kept. The section "Two gossip implementations" below says what each
is and what each can do that the other cannot.

The extension has two parts, and an application chooses by what it depends on:

- `TempusClient` is the wire and the client: the frame codec, TLS, admission in both directions, `dial` and a
  `Listener`, and the gossip discovery of `Gossip.swift` (`Peer`). An application that only makes requests of nodes depends on this target alone. The document
  [What do I need to do to write a TEMPUS client?](../writing-a-tempus-client.md) says what such a client has to do.
- `TempusNode` is the node, built on `TempusClient`: the stores, the join, the shuffles, admission as a node judges
  it, the limits, the clock rules, the configuration. An application that is a node depends on this target.

Neither target holds test material. Fixed test keys, the making of test tokens, and a clock, timers and draws that a
test sets by hand are in a third target, `TempusClientTesting`, which only the driver's command line, the test programs and the trial program
link. An application never depends on it, and `make test` checks that neither library does
(`test/layering_check.py`). The extension shares no code with the Silica library (`src/tempus/`), the
Python extension or the Kotlin extension.

The extension cannot be a bridge. A bridge is a node that is a member of both a TEMPUS network and a TRUST network
(TRUST is the other mode of BEES, for long-lived nodes that know each other in advance), and there is no TRUST
implementation in Swift. A configuration whose role is `bridge` is refused at the start. A node of this extension can
be an edge (an ordinary member) or a sentinel (a node whose address is known in advance, which new nodes contact
first). It holds a bridge store like every node, and its application can ask it for bridges and call one with
`dial` and `callFrame`.

## What is in this directory

The directory follows one layout: libraries in `lib/`, applications over them in `driver/`, test-only code in
`testing/`, and tests in `test/`.

- `Package.swift` describes a Swift package with no remote dependency.
- `lib/TempusClient/` is the wire and client part of the extension: the client library.
  - `ETF.swift` writes and reads the part of the Erlang external term format that TEMPUS uses.
  - `Frames.swift` writes and reads the frames and the token, and checks every bound on their fields.
  - `Crypto.swift` holds Ed25519 signatures, SHA-512 and the certificate functions.
  - `Admission.swift` holds an identity, the verifier that checks another peer, and the outcome of a connection.
  - `Connection.swift` holds the TLS connection, the order of a connection, and `dial`.
  - `Listener.swift` holds the listening position: a node dials the client, and the client answers one request.
  - `Gossip.swift` holds view rules, `Store` and `Peer`: three stores, the shuffle on a timer, and the join. It is one
    of the two gossip implementations.
- `lib/TempusNode/` is the node part of the extension: the node library.
  - `View.swift` holds the view rules and one store's steps, as pure functions and a value type.
  - `Clock.swift` holds the decision about one reading of the clock, as a pure function, and the reading of the
    machine's clock.
  - `Config.swift` holds the configuration value, its bounds and its refusal texts, and the node's identity value.
  - `Admission.swift` holds admission as a node judges it, with the node's reason texts.
  - `Sources.swift` holds the three things a node takes from the machine: the clock, timers and random numbers.
  - `Node.swift` holds the node: the join, the ticks, the shuffles, what the application is told.
  - `NodeConnection.swift` holds one connection of a node, dialed or accepted, and its audit lines.
- `lib/COpenSSL/` is a module map that names the headers and libraries of the OpenSSL installed on the machine.
  It contains declarations only. There is no C code in this directory.
- `driver/tempus-client/` is the driver application: a command line over `TempusClient`. The trials drive the client
  through it, and its `gossip` command runs a `Peer` of `Gossip.swift`. It links the test support, because it can make
  a test token (`test-token`, `--test-token`, `--test-entry`); it is not something an application uses as it is.
- `driver/tempus-node-example/` is a complete application that is a node. It links `TempusNode` and nothing of the
  test support.
- `testing/TempusClientTesting/` is for tests only, and is a module of its own so that the libraries hold nothing of
  it: `Fixtures.swift` makes test tokens and test identities from fixed seeds, and `ManualSources.swift` holds a clock,
  timers and draws that a test sets by hand.
- `testing/tempus-node-trial/` is the program the trial `trials/c8_tempus_node_swift` runs as a node whose clock,
  timers and draws the trial sets. It is for that trial only.
- `test/tempus-client-tests/` and `test/tempus-node-tests/` are the unit tests, as plain programs.
- `test/model_check.py` compares the store rules of `lib/TempusNode/View.swift` with the two Python models of the BEES
  tools.
- `test/layering_check.py` checks that neither library and not the application example depends on
  `TempusClientTesting`.
- `Makefile` builds the package, runs the unit tests and the two checks, and runs the gossip example.

## Starting a node from an application

An application builds two values, makes the node, and starts it. This is a complete program; the file names and the
numbers are the application's own choices, and none of them is a default of the extension.

```swift
import Foundation
import TempusClient
import TempusNode

let store = StoreConfig(capacity: 32, shuffleLength: 8, tickMs: 10000)
let config = TempusConfig(
    role: .edge, listenAddress: "0.0.0.0", port: 7400,
    sentinels: [Sentinel(host: "203.0.113.10", port: 7400)],
    edge: store, bridge: store, sentinel: store,
    producerKid: Array("k1".utf8),
    producerKey: Array(try Data(contentsOf: URL(fileURLWithPath: "producer.pub"))),
    whitelist: [certificateDER(pem: try String(contentsOfFile: "sentinel.pem", encoding: .utf8))!],
    shuffleTimeoutMs: 5000, inflightMax: 16, clockSkewMs: 10000,
    clockBack: .follow, clockBackLimitS: nil, clockFail: .pause, clockReadMs: 1000,
    joinRetryInitialMs: 1000, joinRetryMaxMs: 60000)
let identity = NodeIdentity(
    seed: Array(try Data(contentsOf: URL(fileURLWithPath: "identity.seed"))),
    certificateDER: certificateDER(pem: try String(contentsOfFile: "identity.pem", encoding: .utf8))!,
    token: Array(try Data(contentsOf: URL(fileURLWithPath: "token.bin"))),
    address: "198.51.100.7:7400")

let node = try TempusNode(config: config, identity: identity, lines: { print($0) }, events: { event in
    switch event {
    case .ownTokenNotValid, .keyRotated:
        break    // get a new token from the producer, then call node.replaceToken(newToken)
    case .stopped:
        break    // the clock went back too far: stop this node and make a new one when the clock is right
    default:
        break
    }
})
node.start()
dispatchMain()
```

- `lines` is given every line the node writes, its own lines and its audit lines, one call for each line. An audit
  line is a line a node writes when it admits or refuses something; it is never sent to the peer. The lines have the
  text of a BEES node's lines, so that an operator can compare the two.
- `events` is given what the application is told (the list is below). It is called on the node's own queue: it must
  return quickly, and it must not wait for the node.
- `node.replaceToken(_:)` passes a new token; the node's own entry carries it from the next shuffle on.
  `node.replaceProducerKey(kid:publicKey:)` passes a new producer key. `node.peers(of:count:_:)` gives up to `count`
  peers of one store, drawn at random, which is how an application finds a bridge. `node.stop()` ends the node; a
  node that has ended is not started again.
- The node keeps no copy of the private seed: it makes its key from the seed when it is created. It never writes or
  sends the key.
- The node reads the machine's clock itself. The initializer above takes no clock, and nothing an application can
  call sets the node's time.

`driver/tempus-node-example/main.swift` is the same application with every value taken from its command line.

## The configuration

`TempusConfig` has the keys of the `tempus` section of `bees.config`, with the same meanings and bounds as
`tools/bees_tempus_conf.py` and design section 11. Nothing has a default. A key that the Silica node requires is a
property with no default value here, so leaving it out does not compile. A value outside its bounds is never
clamped: the initializer of `TempusNode` writes the line `tempus: boot refused: WHY` and throws `ConfigRefused`.

| Property | Bounds | Meaning |
| --- | --- | --- |
| `role` | `.edge` or `.sentinel`; `.bridge` is refused | the node's own type, and the type its token must carry |
| `listenAddress`, `port` | an IPv4 literal or `localhost`; 1 to 65535 | where the node listens |
| `sentinels` | 1 to 16, each an IPv4 literal and a port; may be empty only for role sentinel | the sentinels the node joins through |
| `edge`, `bridge`, `sentinel` | capacity 1 to 256; shuffle length 1 to 64 and at most the capacity; tick 100 to 3600000 ms | one store each |
| `producerKid`, `producerKey` | 1 to 64 bytes; 32 bytes | the one current producer key |
| `whitelist` | certificates as DER, each self-signed over an Ed25519 key | the `tempus` whitelist: the bridges and sentinels this node accepts |
| `shuffleTimeoutMs` | 100 to 60000 | one bound for a whole connection, from the dial or the accept to the close |
| `inflightMax` | 1 to 64 | accepted connections at once |
| `clockSkewMs` | 0 to 300000 | the clock difference allowed when a token's times are judged |
| `clockBack` | `.follow`, `.hold`, `.stop` | what a reading of the clock earlier than the node's time does |
| `clockBackLimitS` | 0 to 86400; required with `.stop`, refused otherwise | the greatest step back that `.stop` still follows |
| `clockFail` | `.continue`, `.pause` | what a reading that fails after a good one does |
| `clockReadMs` | 100 to 60000 | how often the clock is read |
| `joinRetryInitialMs`, `joinRetryMaxMs` | 100 to 3600000; the maximum not below the initial | the wait before the join is tried again; it doubles up to the maximum |

`NodeIdentity` holds what the application passes as bytes: the 32-byte Ed25519 private seed, the certificate
self-signed over that key, the producer's token, and the address other nodes dial. The start is refused when the token
does not read, is for another peer type or names another key, and when the certificate is not self-signed over the
identity key.

Where this differs from the Silica node's configuration, and why:

- The three permission specifications (`edge_spec`, `bridge_spec`, `sentinel_spec`) say what a peer may call on a
  bridge. This extension is no bridge, so it has no such property.
- The identity and the whitelist are bytes, not file names. The application reads its files.
- The Silica node's listen address can only be 127.0.0.1 or every interface, a limit of its carrier. This extension
  listens on any IPv4 address of the machine.
- A sentinel is an IPv4 literal. The Silica tools also accept a host name there; this extension resolves no name.
- `clockSkewMs` is given in milliseconds, as in `bees.config`; the node judges tokens in whole seconds and uses the
  whole seconds of the value.

## What the application is told

| Event | When |
| --- | --- |
| `.listening(address:)` | the first reading of the clock succeeded and the node listens |
| `.view(store:entries:)` | after each step that may have changed a store: a tick, an answered shuffle, an insert |
| `.joined` | the join through the sentinels is complete |
| `.ownTokenNotValid(reason:)` | a tick found the node's own token not valid any more; ticking has stopped until `replaceToken` |
| `.keyRotated(kid:dialed:)` | a peer answered this node's advert with `key_rotated`; the application must get a new token |
| `.clockNotRead(text)` | the clock could not be read; told once for each failure, with what it means for the node |
| `.stopped(text)` | the clock went back by more than `clockBackLimitS` under `.stop`: the node has stopped for good |
| `.peerRefused(event:peerId:tokenVerified:)` | an accepted peer was refused; the identity is the SHA-512 of the key of its TLS certificate |
| `.listenFailed(text)` | the node could not listen on its address |

## What the node does

It follows the ruled design, `development-plan/tempus-design.md`, and where the design leaves a point open, the
Silica node of `src/tempus/`.

- The stores. Three, one for each peer type, with the design's rules for capacity, ages, the choice of the partner
  and of the entries sent, the merge, the eviction, and the putting back of sent entries.
- The join. One `sample` request for each store to a configured sentinel; the node keeps the sentinel that answered in
  its sentinel store; with no sentinel answering it waits and tries again, the wait doubling up to its maximum. A join
  request that falls due while the node waits for its clock is made at once when the clock is read again.
- Its own shuffles. Each store has its own timer. At a tick every age rises, the oldest entry is the partner, the
  node's own entry goes first at age 0 in the store of its own type, the reply is merged, and in a store that is not
  of the node's own type the partner that answered is put back at age 0. A partner that fails is dropped and the sent
  entries are put back. An empty store makes the node ask a sentinel again.
- Answers. A `shuffle` and a `sample` of an admitted peer are answered from the stores. A sentinel puts every peer that
  sends it a `sample` into its store of that peer's type, after the sample is taken. A `call` or a `cast` is refused:
  only a bridge serves them.
- Admission. Every check of the Silica node, in its order and with its reason texts: the advert's bounds, the binding
  of the advert to the TLS certificate, the producer key identifier (answered with the one `key_rotated` frame), the
  token's time, its subject, the whitelist rule in both directions, the identity hash, the producer's signature, and
  the proof of possession. Every entry of a received frame is verified before any is used.
- Limits. The frame ceiling, the entry counts, `inflightMax` (a connection beyond it is closed at once after its
  handshake), and one time bound for each connection.
- The clock. The node reads the machine's clock at its start and every `clockReadMs`. `clockBack`, `clockBackLimitS`
  and `clockFail` decide what a reading that is earlier, or that fails, does, as design section 10 says. While it
  waits for its clock the node closes every accepted connection with the audit event `clock_refused`; after it has
  stopped, with `clock_stopped`.
- The node's own token. A tick that finds it not valid stops the ticking and tells the application; the node goes on
  listening and answering, and ticks again when the application passes a new token.

What a node of this extension does not do:

- It is not a bridge, and it keeps no score of peers. The score, the score limit and the rule that a refusal makes a
  new score entry only after the token verified belong to the bridge's table in the Silica library. This node tells
  its application of every refusal of an accepted peer, with the peer's identity as the TLS handshake proved it and
  whether the producer's signature had verified, which is what a score would need.
- The test-only `tick` and `clock` frames do not exist in it. It refuses both as it refuses any frame that is not a
  request.

## Testing a node with a clock, timers and draws of the test's own

`TempusNode` has a second initializer that takes a `NodeSources` value: a clock (`NodeClockSource`), timers
(`NodeTimers`) and random numbers (`NodeRandom`). The first initializer uses `NodeSources.system`. A node made with
the second initializer is refused on a listen address that is not a loopback address, as the Silica node refuses an
externally driven node there. `TempusClientTesting` has a `ManualClock`, `ManualTimers` and a `ListRandom` for it. No
frame a peer can send reaches the clock or the timers.

The time bound of a connection is always measured on the machine's monotonic clock, also in a test.

## What you need

- Apple's Command Line Tools, which provide `swiftc` and the Swift Package Manager. Xcode is not needed. The extension was
  built with Swift 6.3.3 for `arm64-apple-macosx26.0`.
- An installed OpenSSL that offers the key exchange group X25519MLKEM768 and Ed25519. The extension was built and run
  with the OpenSSL 4.1.0 that Homebrew installs, which is the one the BEES Makefiles use. The Makefile finds it the way
  they do, through `native/macos/platform.mk`, or takes the directory from `OPENSSL_PREFIX`.

An application that uses the extension needs the same two things, and adds the package to its own build with the
place of OpenSSL's headers and libraries, as the Makefile here does. Nothing is downloaded. The package has no dependency that the package manager would fetch.

## How to build it, and how to run the client

From this directory:

- `make build` builds both parts of the extension and every program into `.build/debug/`.
- `make test` builds and then runs the unit tests of the client part (`tempus-client-tests`), the unit tests of the
  node part (`tempus-node-tests`), the comparison of the node's stores with the Python models
  (`test/model_check.py`) and the check that no library depends on the test support (`test/layering_check.py`).
  They need the recorded outputs of the trials `trials/t2_tempus_frames`, `trials/t0_tempus_clock` and
  `trials/t4_tempus_admission`, the test certificates in `trials/t5_tempus_tls/certs`, and Python 3.
- `make gossip` builds and then runs four instances of the driver's `gossip` command as one network (below).
- `make clean` removes `.build/`.

The Makefile calls `swift build --disable-sandbox` with the place of OpenSSL's headers and libraries. The package
manager's own sandbox cannot start inside another sandbox, and this package has no plugin and no dependency for it to
guard.

The client's command line, with its test fixtures, looks like this. `SEED` is 64 hexadecimal digits and `PUB` is the
producer's public key as 64 hexadecimal digits.

```
.build/debug/tempus-client dial 127.0.0.1:24700 \
    --seed SEED --addr 127.0.0.1:24703 --test-token tempus_edge:1000:3000 \
    --producer-pub PUB --kid k1 --now 1500 --skew 10 --timeout 5 --shuffle-length 3 \
    sample tempus_edge 3
```

It prints one line that says what happened, for example
`reply sample_reply entries=[1:9200d2990c3e9eb7] store=tempus_edge peer=b19edad2958934e1 typ=tempus_edge`. The line has
the same form as the Python example's line.

- The requests are `sample STORE N`, `shuffle STORE` (the client's own entry at age 0), `call MODULE FUNCTION
  [INTEGER...]`, `cast MODULE FUNCTION [INTEGER...]` and `raw HEX` (any body, given as bytes).
- `listen HOST:PORT` with the same options accepts connections until its standard input ends. It answers a sample or
  a shuffle with the entries given by `--test-entry`, and anything else with a close.
- The time for token checks is either `--now SECONDS` or `--system-clock`. One of the two must be given.
- `--token HEX` gives the client's token as the producer issued it. `--test-token TYP:NBF:EXP` signs one with the test
  producer key, whose seed is written in this repository. That option is for tests only.
- `--cert FILE` gives the client's certificate as a PEM file. Without it the client makes a certificate that is
  self-signed over its own key.
- `--whitelist-cert FILE`, which may be given more than once, turns on the whitelist rule described below.
- The skew, the time bound and the shuffle length must always be given. TEMPUS has no default for any of them.

## Which libraries the extension uses, and why

The client uses Foundation, the system's POSIX calls for the TCP connection, and OpenSSL for TLS, Ed25519, SHA-512 and
certificates. It does not use Network.framework, Security.framework or CryptoKit. Each of those was tried first, and
each cannot do something the protocol requires.

- Network.framework cannot complete a handshake with a TEMPUS node. A node presents a certificate whose key is
  Ed25519, so the handshake must be signed with Ed25519. The list of signature algorithms that Network.framework
  offers on this system does not contain Ed25519 (code 0x0807). The list it sent, captured from its first handshake
  message, was 0x0403, 0x0804, 0x0401, 0x0503, 0x0805, 0x0501, 0x0806, 0x0601 and 0x0201. An OpenSSL server holding a
  test TEMPUS certificate answered that offer with the error "no suitable signature algorithm". The public interface
  of Network.framework has no call that changes the list. Network.framework does offer the key exchange group
  X25519MLKEM768 (code 0x11ec), so the group was not the obstacle.
- Security.framework did not load the client's own identity in the attempts made. Importing an Ed25519 key and
  certificate with `SecPKCS12Import` failed with the status -26275 ("Unable to decode the provided data"), for a file
  written by OpenSSL in its present form and for one in its older form. One attempt to make an Ed25519 private key
  with `SecKeyCreateWithData` also failed; that attempt does not prove it cannot be done. Without an identity the
  client cannot present its certificate, and TEMPUS requires both sides to present one. This was not pursued further,
  because the signature algorithms above already rule Network.framework out.
- CryptoKit can sign with Ed25519, but its signatures are randomized: signing the same message twice with the same
  key gave two different signatures. Such signatures are valid, but tokens and proofs made with them cannot be
  compared byte for byte with the ones the Python example and the trials make. OpenSSL's Ed25519 gives the same bytes
  on every call.

OpenSSL can do all of it, and it is the library the BEES node itself uses for TLS, so the client offers exactly what
the node requires: TLS 1.3 only, the group X25519MLKEM768 only, the cipher suites TLS_AES_256_GCM_SHA384 and
TLS_CHACHA20_POLY1305_SHA256, the signature algorithm Ed25519 only, and the protocol name `tempus/1`.

Several OpenSSL settings are C macros, which Swift cannot call. The client calls the function each macro stands for,
`SSL_CTX_ctrl`, with the same arguments. That is why no C code was needed.

## What the client part covers, compared with the Python example

| Subject | Python example | Swift example |
| --- | --- | --- |
| Frames: advert, challenge, response, key_rotated, shuffle, shuffle reply, sample, sample reply, done | writes and reads all | writes and reads all, with the same bytes |
| TRUST's call, cast and result frames | writes call and cast with integer arguments, reads a result | the same, and it refuses to write a request identifier outside 1 to 16 bytes |
| The test-only tick and clock frames | writes and reads them, because the trials drive nodes with them | not implemented. The strict reader refuses both as a frame of no kind, as the library does |
| Bounds on every field, unknown, missing and repeated keys, nesting depth, the frame ceiling | checked | checked, with the same reasons |
| Token: structure, bounds, kid, time window with skew, sub, id, the producer's signature | checked | checked, in the same order and with the same reasons |
| Channel binding: the key of the peer's TLS certificate is the advert's pub | checked | checked |
| Proof of possession, both ways | made and verified | made and verified |
| The peer's certificate: Ed25519 key, issuer equal to subject, signature verifying under its own key | checked when dialing and when listening | checked when dialing and when listening |
| key_rotated: sent when the peer's token is under another kid, and read when the peer sends it | both | both |
| Dialing: admission, one request, one reply | yes | yes |
| Listening: admission, one request, one answer | yes, for peers whose certificates it was given in advance | yes, for any peer. OpenSSL lets the client accept a self-signed certificate it was not given, and admission decides |
| Closing so that the last frame arrives: TLS close, end of writing, a short read, then close | yes | yes |
| One time bound for a whole connection | yes | yes |
| The outcome of a connection as one line | yes | yes, in the same form |
| Making its own self-signed certificate | yes | yes. With the names, serial numbers and dates of `tools/bees_tempus_certs.py` it makes the same bytes |
| Deliberate misbehaviour (wrong proofs, wrong frames, silence, oversize frames, other TLS settings) | yes, because the trials need it | no. A client has no use for it |

## Two gossip implementations

Two things in this directory make a program a member of a TEMPUS network. They were written separately, they share the
wire code of `TempusClient` (frames, TLS, the client's admission) and nothing else, and each has its own callers.

- `Peer`, with `Store`, `StoreSettings` and `PeerSettings`, in `lib/TempusClient/Gossip.swift`. The driver's `gossip`
  command runs it, and the example `../gossip` and the trial `trials/c7_tempus_gossip` run that command.
- `TempusNode`, with `Store<P>`, `StoreConfig` and `TempusConfig`, in `lib/TempusNode/`. The program
  `tempus-node-example` and the trial program `tempus-node-trial` run it, and the trial `trials/c8_tempus_node_swift`
  runs those.

What both do: the three stores with the view rules of design section 3, a shuffle of each store on its own timer, the
join through the configured sentinels with a doubling wait, answers to `shuffle` and `sample` from the stores, a
sentinel's insert of every peer that asks it for a sample, and a new token passed by the application.

What `TempusNode` does and `Peer` does not: admission as a node judges it, in the Silica node's order and with its
reason texts, including the whitelist rule in both directions; the audit lines with the Silica node's text; the limit
on accepted connections (`inflightMax`); the clock rules (`clockBack`, `clockBackLimitS`, `clockFail`, `clockReadMs`),
with the wait for the clock and the stop; the stop of ticking when its own token is no longer valid; the refusal of a
`call` and a `cast` with the node's audit event; a configuration value with the keys, bounds and refusal texts of
`bees.config`; events told to the application; a replaced producer key; and a clock, timers and draws that a test can
set, so that a trial's output is the same on every run.

What `Peer` does and `TempusNode` does not: it needs only the target `TempusClient`; its settings are four small
values and a `Verifier`, whose clock is any function the application gives; it reports each newly learned peer through
`onLearned`; and it was run in one network with the Silica, Python and Kotlin drivers of the same design
(`../gossip`, the networks `mixed` and `trio`).

How each is tested: `Peer` by the gossip cases of `tempus-client-tests` (the view rules and the store's steps against
answers worked by hand, and three peers in one process over TLS) and by the checks of `../gossip` and
`trials/c7_tempus_gossip`, which run with real timers and compare what each instance learned. `TempusNode` by
`tempus-node-tests`, by `test/model_check.py` against two independent Python models, and by
`trials/c8_tempus_node_swift`, which compares its audit lines and what a peer sees with a Silica node's, step by step.

An application that imports both `TempusClient` and `TempusNode` meets one name twice: each has a type named `Store`.
Inside such a file `Store` alone means the client library's; `import struct TempusNode.Store` makes it mean the
node's, as `test/tempus-node-tests/main.swift` does.

## The gossip part of the client library

`lib/TempusClient/Gossip.swift` adds what a client needs to find other peers by itself:

- The view rules of the design's section 3: ageing, the choice of a partner, the merge, the eviction.
- `Store`, one of a peer's three stores, with its steps: tick, reply, failed, request, sample, insert, drop.
- `Peer`, which listens, joins through its sentinels, ticks each store on its own timer, and answers the shuffles and
  samples of admitted peers from its stores. A peer whose token says `tempus_sentinel` also puts every peer that asks
  it for a sample into its store of that peer's type.

Nothing in it has a default. The capacity, shuffle length and tick of each store, the time bound of a connection, the
sentinels and the retry delays of the join are values the application passes.

```
.build/debug/tempus-client gossip \
    --cert CERT.pem --key KEY.pem --token TOKEN.hex --addr 127.0.0.1:24801 \
    --producer-pub HEX --kid k1 --skew 10 --timeout-ms 3000 \
    --store-edge 8:4:500 --store-bridge 8:4:5000 --store-sentinel 8:4:1000 --join-retry-ms 500:2000 \
    --sentinel 127.0.0.1:24800 --whitelist-cert SENTINEL.pem
```

`--key` is the private key as an unencrypted PKCS#8 PEM file, and `--token` is a file that holds the token as hex
digits. The peer listens on the address of `--addr`. It prints its own lines (the join, each tick) and a line
`learned STORE ID16 HOST:PORT` for each peer it comes to know. It runs until it is interrupted, or for `--run-ms`.
A peer started this way always applies the whitelist rule: with no `--whitelist-cert` it accepts no bridge and no
sentinel.

`make gossip` starts four such instances on this machine, one sentinel and three edges, and stops them when every
instance has learned of every edge. Each edge is given the sentinel's address and nothing else.
[The gossip README](../gossip/README.md) says what the printed check means. It needs Python 3 with the `cryptography`
package, because the runner and the test tokens are made with the Python example.

## What the client part does that the Python example does not

- It verifies every entry of a reply before it reports the reply. One entry that does not verify refuses the whole
  frame, and the outcome says so. A listening client does the same to the entries of a shuffle it receives. The
  Python example reports the reply and leaves the entries to its caller. The option `verifyEntries` of `dial` and of
  `Listener`, and `--no-entry-check` on the command line, give the Python example's behaviour.
- It can apply the whitelist rule of the design: a peer whose token says `tempus_bridge` or `tempus_sentinel` must
  present a certificate that the client holds in its list. The rule is applied only when a list is given. Without
  one the client behaves as the Python example does and does not apply the rule.
- It names the key exchange group, the cipher suites and the signature algorithm it offers. The Python example relies
  on what its TLS library offers by default.
- It checks after the handshake that the TLS version is 1.3.

## What the client part was checked against

The unit tests (`make test`, which prints how many checks passed) compare the client with recorded bytes:

- every frame and token of the trial `trials/t2_tempus_frames`, built here from the same inputs, must be the same
  bytes, and every recorded frame, good or bad, must get the verdict the Silica library gave it;
- a token and a proof of possession made here with the test keys must be the bytes the Python example made
  (`native/tempus/selftest/vectors.h`);
- Ed25519 must give the signature of RFC 8032, section 7.1, test 1;
- the certificates made here must be the files of `tools/bees_tempus_certs.py`, byte for byte;
- call, cast and result frames and a set of integers must be the bytes the Python example writes;
- the client is run against itself over mutual TLS 1.3 on the loopback address: every request, each cause of
  refusal that a token can carry, key_rotated both ways, the whitelist rule, bad replies, a close, silence, several
  connections in order, and an address where nothing listens;
- the view rules and the store's steps give the answers worked by hand for a set of cases, and a sentinel and two
  edges of this library in one process, over TLS on the loopback address, come to hold each other.

The trial `trials/c7_tempus_gossip` runs four instances of the driver as one network, and one instance in a network
with the Silica, Python and Kotlin drivers. Both were run and their checks are recorded.

The trial `trials/c5_tempus_swift` runs the command line against real nodes on this machine, and against the Python
example. `tools/bees_tempus_swift_trial.py` walks the steps and checks each result, and the client's lines are
compared with a recorded golden.

- Node N is a test node whose clock is fixed. It joins through the Swift client listening as its sentinel. The Swift
  client then samples it, shuffles with it, and is dialed by it for a shuffle. The client sees the node refuse an
  expired token, a token that is not valid yet, a token another key signed, a sample above the shuffle length, an
  entry of the wrong store, and a call and a cast (the node is not a bridge). It reads the node's `key_rotated`
  frame, and it refuses the node itself when its own clock is past the node's token and when it holds another
  producer kid.
- Node P reads the system clock, and so does the Swift client there. P joins through a second Swift listener, and the
  client samples it and shuffles with it. P refuses a token that has expired by the system clock and one that is not
  valid yet.
- Against the Python example, with no node, each client dials the other. The Python example checks that the Swift
  client's sample, shuffle, call and cast are the bytes it would write itself. The Python example then misbehaves on
  purpose, so that the Swift client's own refusals are seen: another peer's advert (the channel binding), wrong
  proofs, a missing proof, wrong and oversize frames, forged entries, expired and old tokens, and other TLS settings.

The ticks that make node N shuffle are test-only frames. The Swift client does not send them; the trial tool sends
them through the Python example.

Run the trial from the BEES root directory with `tools/run_all_trials.sh --local-only --only c5_tempus_swift`, or with
`make -C trials/c5_tempus_swift integrate`.

## What the client part does not cover

- Against real bridges it was run in one trial, `trials/c10_tempus_bridge_swift` (its `walk.py` holds the steps A to
  H and its `COVERAGE.md` the rows of the behaviour list): calls and a cast answered by a bridge and through the
  TRUST node behind it, the bridge's refusals and its score, its bounds on requests in flight, the whitelist rule for
  a bridge certificate on both sides, a TRUST node that refuses or has stopped, and a bridge that is lost. Not walked
  there: the bridge's bound on one peer's requests per hour, which needs more than 20 requests of one edge.
- Its reader of TRUST's result frame understands the same subset as the Python example's: maps, atoms, binaries,
  integers and lists. A result that carries a tuple or a float is refused, and its bytes are still in the outcome.
- It keeps integers in 64 signed bits. The Python example reads an integer of up to 64 bits of magnitude. No number in
  a TEMPUS frame comes near either limit.
- It was built and run on macOS on Apple Silicon only. There is no Swift toolchain on the Linux machine the other
  trials also run on, so the trials have Mac goldens only. Each Swift trial names the Mac in its `platforms` file, so
  the trial runner reports it as not applicable on another platform; run by hand on a machine without Swift,
  `trials/c5_tempus_swift`, `trials/c8_tempus_node_swift` and `trials/c10_tempus_bridge_swift` fail and say what is
  missing.
- The client part's `dial` and `Listener` keep no stores and run no shuffle timer: `dial` makes one request, and a
  `Listener` answers requests with entries it was given. Stores and timers are in `Peer` and in the node part.
- A `Peer` does not refresh its token. `Peer.newToken` takes a new token from the application.
- A `Peer` does not serve `call` or `cast`, keeps no score of peers and has no limit on accepted connections. Its
  clock is the function the application gives the `Verifier`; it has none of a node's rules for a clock that fails
  or goes back. The node part has those rules and that limit.
- The gossip part of the client library was run only on one machine, with test keys, for a few seconds at a time. It
  was not run for a long time, with expiring tokens, with peers that stop, or against the limits of its stores.
- A failed TLS handshake is reported with the text OpenSSL gives for it. That text belongs to the OpenSSL version, so
  the trial leaves it out of its golden.
- The whitelist rule is one-sided here: it is the edge's rule. The rule a bridge or sentinel applies to its own kind
  is the node's, and is in the node part (`TempusNode`).
- It was not checked for the time its operations take, for memory use, or under load.

## What the client part was checked against, added on 2026-11-23

The trial `trials/c8_tempus_node_swift` also runs the client's command line, after its node steps, against two Silica
nodes that are not bridges (steps K1 to K15, recorded as `client`): a sample answered twice the same; a shuffle
started by a node for a store that is not of its own type, and the client put back at age 0 afterwards; an entry of
the wrong type in the client's answer, which makes the node refuse the whole frame and drop the client; three frames
that break a bound, sent as bytes another program wrote; a token issued for another key; an entry that leaves a
node's view when its token has expired; and a node whose own token has expired, which still answers and whose advert
the client refuses. `trials/c10_tempus_bridge_swift/COVERAGE.md` lists every row of the behaviour list of design
section 16.2 with the Swift trial and step that shows it, or the reason no Swift trial does.

## How the node part was tested

Unit level, run by `make test`:

- The clock. `tempus-node-tests` computes every one of the 71 case lines of the recorded output of
  `trials/t0_tempus_clock` with `clockBack` and `clockTurn` and requires the same text.
- Admission. 19 of the 20 cases of the recorded output of `trials/t4_tempus_admission` are judged with the same
  verdict text (the twentieth compares a signature with a fixture of that trial), and the whitelist rule's four cases.
- The configuration. The cases of `tools/test_bees_tempus_conf.py` that concern values (the others concern the syntax
  of a file, which this extension does not read), every bound of design section 11 on both sides, and the boot
  refusals of an identity, each with the line the node writes.
- The stores. `test/model_check.py` runs 400 generated calls of the view functions and 60 generated runs of 40 store
  events each through `View.swift` and through the two independent Python models of the BEES tools
  (`tools/bees_tempus_view_model.py`, `tools/bees_tempus_store_model.py`), which the BEES tools tests compare with the
  Silica units and the recorded outputs of `trials/t0_tempus_view` and `trials/t1_tempus_store`. Every answer must be
  equal.

The trial `trials/c8_tempus_node_swift` runs nodes of this extension with Silica nodes on 127.0.0.1. Its `walk.py`
holds the steps and checks each one.

- A Silica edge and a Swift edge (node A) join through a Silica sentinel. A starts a shuffle that the Silica edge
  answers, the Silica edge starts one that A answers, the Silica sentinel shuffles its edge store, and A shuffles its
  sentinel store with the Silica sentinel. Each side's entries appear in the other's views.
- One peer that misbehaves on purpose does 38 things to the Silica edge and to A, one after the other: bad tokens,
  another peer's advert, the whitelist rule in both directions, wrong and missing proofs, frames that break each
  bound, an entry that does not verify, a call and a cast, silence past the time bound, four TLS settings outside the
  profile, and a third connection while two are held open. For each, the two nodes must write the same audit lines
  and the peer must see the same thing.
- A's clock is set by the trial (`clockBack` hold, `clockFail` continue): the hold beginning and ending, a reading
  that fails, an entry that expires, A's own token expiring and being replaced.
- Node T (`clockBack` stop with the limit 60, `clockFail` pause): the wait, a connection closed with `clock_refused`,
  a join request that waits and is dialed at once when the clock is read again, a step back inside the limit, the
  stop above it, connections closed with `clock_stopped`, and no resume.
- Node U: a clock that cannot be read at the start. The node does not listen until a reading succeeds.
- Node R is `tempus-node-example`, which is no test program: it reads the machine's clock, runs its own timers and
  draws from the system's random source. A Silica node that is no test program either joins through it, R's own timer
  starts a shuffle that the Silica node answers, and both refuse a `tick` and a `clock` frame in the same words.

Run it from the BEES root directory with `tools/run_all_trials.sh --local-only --only c8_tempus_node_swift`.

What the tests do not show:

- A node of this extension joining through a sentinel of this extension, and a sentinel of this extension with a
  clock the trial sets, were run by hand only (two Swift nodes together); the trial's Swift sentinel is node R.
- More than one sentinel configured, and the doubling of the join's wait, are read from the code only.
- The node was not run for long, under load, or with many peers, and its memory use was not measured.
- A failing random source is read from the code only.
- Nothing was run on any machine but one Mac with Apple Silicon.

## What stands between this extension and production use

- The owner's statement that this directory holds examples only.
- Review. No person has reviewed the Swift code as production code. In particular the use of OpenSSL from Swift
  through raw pointers, the threads (one for each connection), and the handling of every error path want a reviewer.
- A bridge. An application that must reach a TRUST network needs a bridge, and this extension cannot be one.
- The producer. The extension verifies tokens and carries its own; getting a token, refreshing it at half its
  lifetime, and storing the private seed safely are the application's work.
- Operation. There is no measurement of memory or time, no soak run, no run with churn, and no run with a real
  difference between clocks.
- Platforms. It was built for macOS on Apple Silicon with Homebrew's OpenSSL 4.1.0 only.
- Stability. Nothing in the interface is promised to stay the same.
