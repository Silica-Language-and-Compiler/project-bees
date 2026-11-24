# The Rust TEMPUS extension

This directory holds the Rust extension for TEMPUS: Rust code that an application written in Rust uses to be a TEMPUS
client or a TEMPUS node. TEMPUS is the gossip membership mode of BEES: nodes find each other by exchanging small
signed records over mutually authenticated TLS 1.3 connections. A node is a program that is a member of a TEMPUS
network: it listens, keeps three lists of other members (its stores), and exchanges parts of them with other members.
A client is a peer that connects to a node, makes one request and reads the answer.

It is a usable example, to be used carefully, as [the directory's README](../README.md) says of every extension. The
section "What stands between this extension and production use" below lists what has and has not been reviewed and
tested, and so what care means here.

The extension is one implementation. The other extensions in this directory hold two gossip implementations side by
side (a lighter peer in the client library, and a node matched to the Silica node). The Rust extension holds only the
second: a node matched to the Silica node of `src/tempus/`, with the client half beneath it. It shares no code with
the Silica library or with the other extensions.

The extension cannot be a bridge. A bridge is a node that is a member of both a TEMPUS network and a TRUST network
(TRUST is the other mode of BEES, for long-lived nodes that know each other in advance), and there is no TRUST
implementation in Rust. A configuration whose role is `bridge` is refused at the start. A node of this extension can
be an edge (an ordinary member) or a sentinel (a node whose address is known in advance, which new nodes contact
first). It holds a bridge store like every node, and its application can ask it for bridges (`TempusNode::peers`) and
call one with `client::dial` and `frames::call_frame`. The section "What a bridge would need" says what is missing.

## What is in this directory

The layout is the one every extension in `example_tempus_clients/` has: `lib/` is what an application depends on,
`driver/` holds the command line and an example node application, `testing/` holds test-only code, and `test/` holds
the tests. The directory is one Cargo workspace (`Cargo.toml`) of six crates. A crate is Rust's unit of compilation and
of dependency.

- `lib/tempus/` is the extension: the crate `tempus`. An application depends on this crate and on nothing else here.
  It holds no test material and has no dependency on any other crate.
  - `src/ffi.rs` declares the functions of the installed OpenSSL that the extension calls. It contains declarations
    only.
  - `src/crypto.rs` holds Ed25519 signatures, SHA-512, random bytes and the certificate functions.
  - `src/tls.rs` holds the TLS context and one TLS connection with its one time bound.
  - `src/etf.rs` writes and reads the part of the Erlang external term format that TEMPUS uses.
  - `src/frames.rs` writes and reads the frames and the token, and checks every bound on their fields.
  - `src/admission.rs` holds an identity, the verifier that checks another peer, and the outcome of a connection.
  - `src/client.rs` holds the order of a connection, `dial`, and the check of a reply against its request.
  - `src/listener.rs` holds the listening position: a node dials the client, and the client answers one request.
  - `src/node/view.rs` holds the view rules and one store's steps, as pure functions and a value type.
  - `src/node/clock.rs` holds the decision about one reading of the clock, as a pure function, and the reading of
    the machine's clock.
  - `src/node/config.rs` holds the configuration value, its bounds and its refusal texts, and the node's identity.
  - `src/node/admit.rs` holds admission as a node judges it, with the node's reason texts, and the node's check of a
    frame's structure.
  - `src/node/sources.rs` holds the three things a node takes from the machine: the clock, timers and random numbers.
  - `src/node/mod.rs` holds the node: the join, the ticks, the shuffles, what the application is told.
  - `src/node/conn.rs` holds one connection of a node, dialed or accepted, and its audit lines.
- `driver/tempus-node-example/` is a complete application that is a node. It depends on the crate `tempus` only.
- `driver/tempus-client/` is a command line over the client half. The trials drive the client through it. It depends
  on the test-only crate, because it can make a test token (`--test-token`, `--test-entry`); it is not something an
  application uses.
- `testing/tempus-testing/` is for tests only: keys and tokens from fixed seeds, and a clock, timers and draws that a
  test sets by hand.
- `testing/tempus-node-trial/` is the program the trial `trials/c15_tempus_node_rust` runs as a node whose clock,
  timers and draws the trial sets. It is for that trial only.
- `test/tempus-tests/` holds the unit tests (`tests/codec.rs`, `tests/admission.rs`, `tests/node.rs`) and the program
  `tempus-model`, which answers calls of the store rules for `test/model_check.py`.
- `test/model_check.py` compares the store rules with the two Python models of the BEES tools and with the recorded
  outputs of two BEES trials. `test/layering_check.py` fails the build when the library, or the example node
  application, depends on the test-only crate or on any crate outside the workspace.

## Starting a node from an application

An application builds two values, makes the node, and starts it. This is a complete program; the file names and the
numbers are the application's own choices, and none of them is a default of the extension.

```rust
use std::sync::Arc;
use tempus::crypto::certificate_der;
use tempus::node::clock::{ClockBack, ClockFail};
use tempus::node::config::{NodeIdentity, PeerType, Sentinel, StoreConfig, TempusConfig};
use tempus::node::{NodeEvent, TempusNode};

fn main() {
    let pem = |path: &str| certificate_der(&std::fs::read_to_string(path).unwrap()).unwrap();
    let store = StoreConfig { capacity: 32, shuffle_length: 8, tick_ms: 10000 };
    let config = TempusConfig {
        role: PeerType::Edge, listen_address: "0.0.0.0".into(), port: 7400,
        sentinels: vec![Sentinel { host: "203.0.113.10".into(), port: 7400 }],
        edge: store, bridge: store, sentinel: store,
        producer_kid: b"k1".to_vec(), producer_key: std::fs::read("producer.pub").unwrap(),
        whitelist: vec![pem("sentinel.pem")],
        shuffle_timeout_ms: 5000, inflight_max: 16, clock_skew_ms: 10000,
        clock_back: ClockBack::Follow, clock_back_limit_s: None, clock_fail: ClockFail::Pause, clock_read_ms: 1000,
        join_retry_initial_ms: 1000, join_retry_max_ms: 60000,
    };
    let identity = NodeIdentity {
        seed: std::fs::read("identity.seed").unwrap(), certificate_der: pem("identity.pem"),
        token: std::fs::read("token.bin").unwrap(), address: "198.51.100.7:7400".into(),
    };
    let node = TempusNode::new(config, identity, Arc::new(|line: &str| println!("{}", line)), Box::new(|event| match event {
        // get a new token from the producer, then call node.replace_token(new_token)
        NodeEvent::OwnTokenNotValid { .. } | NodeEvent::KeyRotated { .. } => {}
        // the clock went back too far: stop this node and make a new one when the clock is right
        NodeEvent::Stopped(_) => {}
        _ => {}
    })).expect("the configuration is accepted");
    node.start();
    std::thread::park();
}
```

- The first function is given every line the node writes, its own lines and its audit lines, one call for each line.
  An audit line is a line a node writes when it admits or refuses something; it is never sent to the peer. The lines
  have the text of a Silica node's lines, so that an operator can compare the two.
- The second function is given what the application is told (the list is below). It is called on the node's own
  thread: it must return quickly, and it must not wait for the node.
- `node.replace_token` passes a new token; the node's own entry carries it from the next shuffle on.
  `node.replace_producer_key` passes a new producer key. `node.peers(store, count)` gives up to `count` peers of one
  store, drawn at random, which is how an application finds a bridge. `node.stop()` ends the node; a node that has
  ended is not started again.
- The node keeps no copy of the private seed: it makes its key from the seed when it is created. It never writes or
  sends the key.
- The node reads the machine's clock itself. `TempusNode::new` takes no clock, and nothing an application can call
  sets the node's time.

`driver/tempus-node-example/src/main.rs` is the same application with every value taken from its command line.

## The configuration

`TempusConfig` has the keys of the `tempus` section of `bees.config`, with the same meanings and bounds as
`tools/bees_tempus_conf.py` and design section 11. Nothing has a default. The struct has no `Default`, so leaving a
field out does not compile. A value outside its bounds is never clamped: `TempusNode::new` writes the line `tempus:
boot refused: WHY` and returns `ConfigRefused`.

| Field | Bounds | Meaning |
| --- | --- | --- |
| `role` | `Edge` or `Sentinel`; `Bridge` is refused | the node's own type, and the type its token must carry |
| `listen_address`, `port` | an IPv4 literal or `localhost`; 1 to 65535 | where the node listens |
| `sentinels` | 1 to 16, each an IPv4 literal and a port; may be empty only for role sentinel | the sentinels the node joins through |
| `edge`, `bridge`, `sentinel` | capacity 1 to 256; shuffle length 1 to 64 and at most the capacity; tick 100 to 3600000 ms | one store each |
| `producer_kid`, `producer_key` | 1 to 64 bytes; 32 bytes | the one current producer key |
| `whitelist` | certificates as DER, each self-signed over an Ed25519 key | the `tempus` whitelist: the bridges and sentinels this node accepts |
| `shuffle_timeout_ms` | 100 to 60000 | one bound for a whole connection, from the dial or the accept to the close |
| `inflight_max` | 1 to 64 | accepted connections served at once |
| `clock_skew_ms` | 0 to 300000 | the clock difference allowed when a token's times are judged |
| `clock_back` | `Follow`, `Hold`, `Stop` | what a reading of the clock earlier than the node's time does |
| `clock_back_limit_s` | 0 to 86400; required with `Stop`, refused otherwise | the greatest step back that `Stop` still follows |
| `clock_fail` | `Continue`, `Pause` | what a reading that fails after a good one does |
| `clock_read_ms` | 100 to 60000 | how often the clock is read |
| `join_retry_initial_ms`, `join_retry_max_ms` | 100 to 3600000; the maximum not below the initial | the wait before the join is tried again; it doubles up to the maximum |

`NodeIdentity` holds what the application passes as bytes: the 32-byte Ed25519 private seed, the certificate
self-signed over that key, the producer's token, and the address other nodes dial. The start is refused when the token
does not read, is for another peer type or names another key, and when the certificate is not self-signed over the
identity key.

Where this differs from the Silica node's configuration, and why:

- The three permission specifications (`edge_spec`, `bridge_spec`, `sentinel_spec`) say what a peer may call on a
  bridge. This extension is no bridge, so it has no such field.
- The identity and the whitelist are bytes, not file names. The application reads its files.
- The Silica node's listen address can only be 127.0.0.1 or every interface, a limit of its carrier. This extension
  listens on any IPv4 address of the machine.
- A sentinel is an IPv4 literal. The Silica tools also accept a host name there; this extension resolves no name, as
  the Silica node dials dotted IPv4 addresses only.
- `clock_skew_ms` is given in milliseconds, as in `bees.config`; the node judges tokens in whole seconds and uses the
  whole seconds of the value.
- The refusal texts for values are those of `tools/bees_tempus_conf.py` (`tempus.KEY: ...`), which a value meets
  first. The Silica node's own second check (`boot_why`) has looser bounds and other words for the same faults; the
  texts for the node's token and for a test node on an address that is not loopback are the Silica node's own.

## What the application is told

| Event | When |
| --- | --- |
| `Listening { address }` | the first reading of the clock succeeded and the node listens |
| `View { store, entries }` | after each step that may have changed a store: a tick, an answered shuffle, an insert |
| `Joined` | the join through the sentinels is complete |
| `OwnTokenNotValid { reason }` | a tick found the node's own token not valid any more; ticking has stopped until `replace_token` |
| `KeyRotated { kid, dialed }` | a peer answered this node's advert with `key_rotated`; the application must get a new token |
| `ClockNotRead(text)` | the clock could not be read; told once for each failure, with what it means for the node |
| `Stopped(text)` | the clock went back by more than `clock_back_limit_s` under `Stop`: the node has stopped for good |
| `PeerRefused { event, peer_id, token_verified }` | an accepted peer was refused; the identity is the SHA-512 of the key of its TLS certificate |
| `ListenFailed(text)` | the node could not listen on its address |

The Silica node tells its application of a `key_rotated` answer only on a connection the node dialed. This extension
tells its application in both cases and says which (`dialed`), as the other extensions do. Which is intended is the
owner's to say.

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
  of the advert to the TLS certificate, the producer key identifier (answered with the one `key_rotated` frame, after
  which the node reads and drops what the peer still sends), the token's time, its subject, the whitelist rule in both
  directions, the identity hash, the producer's signature, and the proof of possession. Every entry of a received
  frame is verified before any is used.
- Limits. The frame ceiling, the entry counts, `inflight_max` (a connection beyond it is closed at once after its
  handshake), and one time bound for each connection.
- The clock. The node reads the machine's clock at its start and every `clock_read_ms`. `clock_back`,
  `clock_back_limit_s` and `clock_fail` decide what a reading that is earlier, or that fails, does, as design section
  10 says. While it waits for its clock the node closes every accepted connection with the audit event
  `clock_refused`; after it has stopped, with `clock_stopped`.
- The node's own token. A tick that finds it not valid stops the ticking and tells the application; the node goes on
  listening and answering, and ticks again when the application passes a new token.

What a node of this extension does not do:

- It is not a bridge, and it keeps no score of peers. This node tells its application of every refusal of an accepted
  peer, with the peer's identity as the TLS handshake proved it and whether the producer's signature had verified,
  which is what a score would need.
- The test-only `tick` and `clock` frames do not exist in it. It refuses both as it refuses any frame that names an
  atom a production node does not hold, with the words a Silica node uses: `not a request: unknown_atom`.
- A token passed with `replace_token` is not checked when it is passed, as the Silica node does not check it; a wrong
  one shows at the next tick.

## Threads, and who owns the node's state

The extension uses threads and channels of the standard library. There is no async runtime.

- One thread, the node's thread, owns everything that changes: the three stores, the clock state, the token, the
  producer key, the counts and the join. Everything else reaches it by sending a message over one channel: a timer
  that fell due, an accepted connection, the outcome of a dialed connection, the request of an admitted peer, a call
  of the application. Nothing else reads or writes that state, so there is no lock around it.
- Each connection, dialed or accepted, runs on a thread of its own. When the connection begins it is given a copy of
  the values it needs (the node's advert, token, producer key and key identifier, the node's time, and its deadline).
  An admitted peer's request is sent to the node's thread with a channel for the answer.
- One thread accepts connections and passes each to the node's thread, which counts it before its TLS handshake
  begins.
- One thread runs the timers of a node that is not a test node.
- What all threads may read (the configuration, the key, the two TLS contexts, the whitelist) does not change after
  the node was made. The lines the node writes pass one lock, so that two lines cannot mix.

## TLS and cryptography: which library, and how much unsafe code

Rust's standard library has neither TLS nor Ed25519, and no crate may be fetched for this work, so the extension
calls the OpenSSL installed on the machine as a C library. This is what the Swift extension does, and OpenSSL is the
library the Silica node itself uses for TLS, so the extension offers exactly what a node requires: TLS 1.3 only, the
key exchange group X25519MLKEM768 only, the cipher suites TLS_AES_256_GCM_SHA384 and TLS_CHACHA20_POLY1305_SHA256,
ALPN `tempus/1`, a certificate on both sides, no authority and no date check. Ed25519 signatures, SHA-512, random
bytes and the reading and making of certificates come from the same library.

- There is no C code. `lib/tempus/src/ffi.rs` declares 67 OpenSSL functions in two `extern "C"` blocks, and
  `lib/tempus/build.rs` tells the linker where the library is. The build script looks in `OPENSSL_PREFIX` and then in
  the two Homebrew directories that `native/macos/platform.mk` names (`PLATFORM_OPENSSL_DIRS`); the Makefile passes
  `OPENSSL_PREFIX` from that file.
- Several OpenSSL settings are C macros, which Rust cannot call. The extension calls the function each macro stands
  for, `SSL_CTX_ctrl`, with the macro's command number (the protocol versions, the group list, the two lists of
  signature algorithms).
- Rust calls a function of another language inside a block marked `unsafe`, which says that the compiler cannot check
  it. All of the extension's unsafe code is in two files: 23 blocks in `crypto.rs` and 23 in `tls.rs`. Each block is
  one OpenSSL call, or one short run of calls, with a comment that says why it is sound. Each OpenSSL object is owned
  by a Rust type that frees it when it is dropped: `SigningKey` (a key), `Certificate` (a certificate), `MdCtx` (a
  digest context), `TlsContext` (an `SSL_CTX`) and `Conn` (an `SSL`). There are four `unsafe impl` lines, which say
  that `SigningKey` and `TlsContext` may be used from several threads; both are only read after they are made. A
  connection object is made and used on one thread.
- No function of the operating system is declared. The TCP connection is `std::net::TcpStream` in blocking mode; the
  one deadline of a connection is kept by setting the stream's read and write timeouts to what is left of it before
  each TLS operation. The cached `libc` crate is not used.
- The first handshake was tested against a running Silica node in both positions before anything was built on it.

A client offers and accepts the signature algorithm Ed25519 only. A node also lets a P-256 certificate through the
handshake, so that it can refuse it afterwards with the audit event a Silica node writes for it (`tempus_cert_key`),
ends the handshake with a fatal alert when `tempus/1` is not offered, and treats a missing certificate as a handshake
failure, as the Silica node does.

## What you need

- A Rust toolchain: `cargo` and `rustc`. The extension was built with Rust 1.91.1 for `aarch64-apple-darwin`. The
  Makefile finds `cargo` on the `PATH` or under `~/.cargo/bin`.
- An installed OpenSSL that offers the key exchange group X25519MLKEM768 and Ed25519. The extension was built and run
  with the OpenSSL 4.1.0 that Homebrew installs, which is the one the BEES Makefiles use.

Nothing is downloaded. The workspace has no dependency outside itself, and every `cargo` command of the Makefile is
run with `--offline`. An application that uses the extension adds `tempus = { path = ".../lib/tempus" }` to its own
`Cargo.toml` and sets `OPENSSL_PREFIX` when OpenSSL is not in one of the two Homebrew directories.

## How to build it, and how to run the client

From this directory:

- `make build` builds the library and every program into `target/debug/`.
- `make test` builds and then runs the unit tests (`cargo test --offline -p tempus-tests`), the comparison of the
  stores with the Python models and the recorded outputs (`test/model_check.py`), and the check of the dependencies
  (`test/layering_check.py`). They need the recorded outputs of the trials `trials/t2_tempus_frames`,
  `trials/t0_tempus_clock`, `trials/t4_tempus_admission`, `trials/c4_tempus_boot`, `trials/t0_tempus_view` and
  `trials/t1_tempus_store`, the test certificates in `trials/t5_tempus_tls/certs`, and Python 3.
- `make clean` removes what cargo built.

The client's command line, with its test fixtures, looks like this. `SEED` is 64 hexadecimal digits and `PUB` is the
producer's public key as 64 hexadecimal digits.

```
target/debug/tempus-client dial 127.0.0.1:25600 \
    --seed SEED --addr 127.0.0.1:25603 --test-token tempus_edge:1000:3000 \
    --producer-pub PUB --kid k1 --now 1500 --skew 10 --timeout 5 --shuffle-length 3 \
    sample tempus_edge 3
```

It prints one line that says what happened, for example
`reply sample_reply entries=[1:9200d2990c3e9eb7] store=tempus_edge peer=b19edad2958934e1 typ=tempus_edge`. The line has
the same form as the lines of the Swift and Python command lines.

- The requests are `sample STORE N`, `shuffle STORE` (the client's own entry at age 0), `call MODULE FUNCTION
  [INTEGER...]`, `cast MODULE FUNCTION [INTEGER...]` and `raw HEX` (any body, given as bytes).
- `listen HOST:PORT` with the same options accepts connections until its standard input ends. It answers a sample or
  a shuffle with the entries given by `--test-entry`, and anything else with a close.
- The time for token checks is either `--now SECONDS` or `--system-clock`. One of the two must be given.
- `--token HEX` gives the client's token as the producer issued it. `--test-token TYP:NBF:EXP` signs one with the test
  producer key, whose seed is written in this repository. That option is for tests only.
- `--cert FILE` gives the client's certificate as a PEM file. Without it the command line makes a certificate that is
  self-signed over its own key, with the dates of the test certificates.
- `--whitelist-cert FILE`, which may be given more than once, turns on the whitelist rule: a peer whose token says
  `tempus_bridge` or `tempus_sentinel` must present one of the listed certificates.
- The skew, the time bound and the shuffle length must always be given. TEMPUS has no default for any of them.

The command line has no `gossip` command, which the Swift, Kotlin and Python drivers have for the four-language
example in `../gossip`. The section "What the tests do not show" says what that would take.

## What the client half does

- Frames. It writes and reads the advert, the challenge, the response, `key_rotated`, shuffle, shuffle reply, sample,
  sample reply and `done`, with the bytes the Silica library and the other extensions write, and TRUST's call, cast
  and result frames with integer arguments. It checks every bound on every field, unknown, missing and repeated keys,
  the nesting depth and the frame ceiling.
- TLS. What the section above lists. After the handshake it checks the version, the group, the protocol name, and the
  peer's certificate: an Ed25519 key, issuer equal to subject, and the signature verifying under its own key. It keeps
  the certificate for the binding.
- Admission in both directions, in the node's order: the binding of the advert to the TLS certificate first, the
  token's structure, the key identifier (it sends the one `key_rotated` frame and then reads and drops what the peer
  still sends until the peer closes or the connection's bound passes; and it reads a `key_rotated` frame where a
  challenge was due), the time window, the subject, the whitelist rule when a list is given, the identity hash, the
  producer's signature, and the proof of possession both ways.
- A reply is checked against its request before it is reported: a sample is answered by a sample reply for the same
  store with at most the entries asked for, a shuffle by a shuffle reply for the same store, a call by a result with
  the call's request identifier. Every entry of a reply is verified, and one entry that does not verify refuses the
  whole reply. A listening client does the same to the entries of a shuffle it receives.
- Dialing and listening, each connection with one time bound, and a close that lets the last frame arrive.

The whitelist rule in the client half is applied only when the application gives a list, and then in both directions:
a peer whose token says `tempus_bridge` or `tempus_sentinel` must present a listed certificate, and a peer that
presents a listed certificate must have such a token.

## How it was tested

Unit level, run by `make test`:

- The codec. Every frame and token of the trial `trials/t2_tempus_frames`, built here from the same inputs, must be
  the same bytes, and every recorded frame, good or bad, must get the verdict the Silica library gave it. Integers and
  TRUST's frames must be the bytes the Python extension writes. The node's list of wire atoms must be the union of
  `src/tempus/bees_tempus.atoms` and `src/trust/bees_trust.atoms`.
- Cryptography. Ed25519 gives the signature of RFC 8032, section 7.1, test 1. A token and a proof of possession made
  with the test keys are the bytes the Python extension made (`native/tempus/selftest/vectors.h`). The eight test
  certificates made here are the files of `tools/bees_tempus_certs.py`, byte for byte.
- Admission. 19 of the 20 cases of the recorded output of `trials/t4_tempus_admission` are judged with the same
  verdict text (the twentieth compares a signature with a fixture of that trial), the order of the checks, and the
  whitelist rule's four cases.
- The clock. Every one of the 71 case lines of the recorded output of `trials/t0_tempus_clock` is computed with
  `clock_back` and `clock_turn` and must be the same text.
- The configuration. The cases of `tools/test_bees_tempus_conf.py` that concern values (the others concern the syntax
  of a file, which this extension does not read), every bound of design section 11 on both sides, and the boot
  refusals of an identity, each with the line the node writes; the texts that are the Silica node's own are those
  `trials/c4_tempus_boot` recorded.
- The stores. `test/model_check.py` runs the tools' own tests of the view and of the store
  (`tools/test_bees_tempus_view.py`, `tools/test_bees_tempus_store.py`) with the Rust rules in the place of the two
  Python models, so every line of the recorded outputs of `trials/t0_tempus_view` and `trials/t1_tempus_store` is
  computed by the Rust code. It also runs generated calls of every view function and generated runs of store events
  through the Rust rules and through the two models, and every answer must be equal.
- A node in the test process, with a clock, timers and draws the test sets, dialed by the extension's own client.

Three trials run the extension with real nodes on 127.0.0.1. Each has a `walk` script that holds the steps and checks
each one, and recorded outputs for a Mac with Apple Silicon.

- `trials/c14_tempus_rust` is the client trial. Node N is a Silica test node whose clock is fixed; it joins through
  the Rust client listening as its sentinel, and the client then samples it, shuffles with it, is dialed by it for a
  shuffle, and sees it refuse an expired token, a token that is not valid yet, a token another key signed, a sample
  above the shuffle length, an entry of the wrong store, and a call and a cast. It reads the node's `key_rotated`
  frame, and it refuses the node itself when its own clock is past the node's token and when it holds another
  producer key identifier. Node P is a Silica node that reads the system clock, as the Rust client does there.
  Against the Python test support, with no node, each side dials the other: the Python side checks that the Rust
  client's requests are the bytes it would write itself, and then misbehaves on purpose so that the Rust client's own
  refusals are seen.
- `trials/c15_tempus_node_rust` is the node trial: a mixed network of Silica nodes and Rust nodes. A Rust edge joins
  through a Silica sentinel and a Silica edge joins through a Rust sentinel; each side starts shuffles that the other
  answers, and each side's entries appear in the other's views. One peer that misbehaves on purpose does the same
  things to a Silica node and to a Rust node, one after the other, and the two nodes must write the same audit lines.
  The clock choices are shown on Rust nodes whose clock the trial sets. One Rust node is `tempus-node-example`, which
  is no test program: it reads the machine's clock and runs its own timers, beside a Silica node built without the
  test unit. After the node steps, the Rust client's command line is run against two Silica nodes for the rows of the
  behaviour list that the client trial does not show.
- `trials/c17_tempus_bridge_rust` is the bridge trial: the Rust client against two real bridges and a TRUST node.
  `trials/c17_tempus_bridge_rust/COVERAGE.md` lists every row of the behaviour list of design section 16.2 with the
  trial and step that shows it for the Rust client, or the reason no trial does.

Run one from the BEES root directory with `tools/run_all_trials.sh --local-only --only c15_tempus_node_rust`, or with
`make -C trials/c15_tempus_node_rust integrate`.

## What the tests do not show

- A node of this extension joining through a sentinel of this extension. Each was shown against a Silica node only.
- More than one sentinel configured, and the doubling of the join's wait, are read from the code only.
- A failing random source is shown for a tick (it is skipped) and not for a request.
- The node was not run for long, under load, or with many peers, and its memory use was not measured.
- Nothing was run on any machine but one Mac with Apple Silicon. There is no Rust toolchain on the Linux machines the
  other trials also run on, so the three trials are declared for the Mac only (the file `platforms` in each) and have
  Mac recorded outputs only. On a machine without `cargo` or OpenSSL each trial fails and says what is missing.
- The four-language gossip example in `../gossip` does not include Rust. To join it, the driver would need a `gossip`
  command with that example's options: the key read from a PEM file (which needs declarations of OpenSSL's PEM
  reader; the node takes a 32-byte seed today), the token read as hexadecimal digits from a file, the stores and the
  retry delays in that example's spelling, and a line `learned STORE ID16 HOST:PORT` for each peer first seen, which
  the node's `View` event gives. `gossip_run.py` would need an entry for the Rust driver. The node itself needs no
  change: it is the same protocol.
- The reader of TRUST's result frame understands maps, atoms, binaries, integers and lists. A result that carries a
  tuple or a float is refused, and its bytes are still in the outcome.
- A failed TLS handshake is reported with the text OpenSSL gives for it. That text belongs to the OpenSSL version, so
  the trials leave it out of their recorded outputs.

## What a bridge would need

A bridge is not built. It would need, in Rust:

- a TRUST implementation: TRUST's mutual TLS with pinned certificates, its whitelist with permission specifications,
  its reconnect token, its suspicion and quarantine rules, and its request frames with every term TRUST carries (this
  extension's term reader has no tuples and no floats);
- two identities in one program: a TRUST certificate key and a separate TEMPUS identity key;
- serving `call` and `cast` from edges: a table of exported functions, the guard against forbidden modules, a
  permission specification for each peer type, a call timeout, and no error body;
- a table with a score, a limit, a rate bound and a bound on requests in progress for each peer, sized by values the
  bridge's application passes. The node already reports what the table would be fed (`PeerRefused`).

## What stands between this extension and production use

- Review. No person has reviewed the Rust code. In particular the 46 unsafe blocks that call OpenSSL, the two types
  marked as usable from several threads, the threads (one for each connection, with no bound on their number beyond
  `inflight_max` for accepted connections), and every error path want a reviewer.
- A bridge. An application that must reach a TRUST network needs a bridge, and this extension cannot be one.
- The producer. The extension verifies tokens and carries its own; getting a token, refreshing it at half its
  lifetime, and storing the private seed safely are the application's work. The seed and the key are not wiped from
  memory when they are dropped.
- Operation. There is no measurement of memory or time, no soak run, no run with churn, and no run with a real
  difference between clocks.
- Platforms. It was built for macOS on Apple Silicon with Homebrew's OpenSSL 4.1.0 only. The declarations in `ffi.rs`
  were written against the headers of that version.
- Stability. Nothing in the interface is promised to stay the same.
