# Example TEMPUS clients

The clients in this directory are examples only. They must not be used in production.

TEMPUS is the gossip membership mode of BEES: nodes find each other by exchanging small signed records over mutually
authenticated TLS connections. A TEMPUS client is a program that connects to a TEMPUS node as an ordinary peer and
makes requests of it.

The clients in this directory exist for two reasons. The first is to test BEES: the trials use them to drive TEMPUS
nodes through every behaviour a node has, including every refusal. The second is to serve as examples. If you need a
TEMPUS client in your own application, write it as part of that application, in whatever language the application
uses, and read these as worked examples of what such a client has to do. The document
[What do I need to do to write a TEMPUS client?](writing-a-tempus-client.md) lists the requirements in a form that does
not depend on any example or on any one language. An application that is to be a member of the network, with stores of its own, is a
node: [What do I need to do to write a TEMPUS node?](writing-a-tempus-node.md) lists what a node has to do beyond a
client.

## Why they are not for production

- Their keys, certificates and tokens are test fixtures made from fixed seeds that are written in this repository.
  Anyone can reproduce them.
- They can misbehave on purpose. Each has functions that send a wrong signature, an expired token, an oversize frame,
  or nothing at all, because that is how the trials reach a node's refusals.
- They take the time of day as a value the trial passes in. They do not read a clock.
- They were written to make the trials readable and repeatable, and nothing else. They have had no review as
  production code, and nothing in them is promised to stay the same.

## How each example is laid out

Every example has two parts, in two directories:

- `lib/` is the client library: the files an application would start from. It holds the frames, admission, a single
  connection in both positions (dialing and listening), and the gossip part: the three stores, the shuffle on a timer
  and the join through a sentinel.
- `driver/` is a driver application: a thin program that passes values to the library and prints what it reports.

What is for the trials only is kept out of the library where the language allows it. Each example's README says
where it is.

The Python, Swift and Kotlin directories also hold a node half, added beside the library, which lets an application
be a TEMPUS node that behaves as the Silica node does. It has gossip logic of its own. Until the project owner decides
between the two, both are kept, and each language's README compares them.

The C# directory holds one implementation only: a client half and a node half, with no second, lighter gossip peer.

`gossip/` runs the drivers. It starts several instances of one language's driver on this machine as one TEMPUS
network, and one network that mixes all four languages, and checks that the instances discover each other. Its
[README](gossip/README.md) says how to run it and what its check shows.

## What each directory holds

### python/

- Two bodies of Python code are kept here side by side until the project owner decides between them. Its own
  [README](python/README.md) says what each can do that the other cannot.
- `lib/bees_tempus_*.py` is the node half of the Python extension: seven modules an application imports to be a
  TEMPUS node (an edge or a sentinel; not a bridge) or a peer that is not a node. The trial
  `trials/c7_tempus_node_python` runs its nodes and Silica nodes in one network.
- `lib/tempus_client/` is the client library, with gossip discovery of its own in `gossip.py` (the stores, the
  shuffle and the join), and `driver/tempus_peer.py` is its driver application. `gossip/` and the trial
  `trials/c7_tempus_gossip` run it. One limit: a peer of this library accepts connections only from certificates it
  was given beforehand.
- Both are written completely in Python, each with its own writer and reader for the frames, written from the design
  document and not from the Silica code. They use Python's `ssl` module for TLS and the `cryptography` package for
  Ed25519 signatures.
- `testing/bees_tempus_testing.py` and `lib/tempus_client/testing.py` are the test support of the one and of the
  other: the test-only frames, token making, keys from fixed seeds, and deliberate misbehaviour. No module an
  application imports imports either. `bees_tempus_client.py` is the name the trial tools import; it is the first of
  the two unless the environment variable `BEES_TEMPUS_TEST_SUPPORT` names the second.
- `test_bees_tempus_client.py`, `test_bees_tempus_node.py` and `test_tempus_gossip.py` hold the tests. Run them from
  the BEES root directory with `make -C example_tempus_clients/python test`. Some compare with the recorded outputs
  of the trials `t0_tempus_view`, `t0_tempus_clock`, `t1_tempus_store`, `t2_tempus_frames`, `t4_tempus_admission`
  and `c4_tempus_boot`, so they need those recorded outputs to be current.

### silica/

- `lib/bees_tempus_client.silica` is a pure Silica unit. For each request a client can make it gives the frame to
  send, and it reads the replies. It also builds deliberately wrong frames for the trials. It opens no connection,
  holds no key and reads no file.
- `lib/bees_tempus_client.part` is the active part for single connections: the code that dials, listens and runs
  admission. It is not a unit. The tool `tools/bees_tempus_gen.py` pastes it into the root unit of a client program,
  because Silica requires the place where a carrier is started to be in the root unit. Each connection it makes is
  run by the same connection actor a BEES TEMPUS node uses (`src/tempus/dangerous_bees_tempus_conn.silica`), so the
  Silica example shares its admission code with the node. The Python example shares nothing with it.
- `lib/bees_tempus_peer.part` is the gossip part. In Silica the stores, the shuffle timer and the join are BEES's own
  library (`src/tempus`), so this part does not write them again: it starts that library as an ordinary member of a
  network, which reads the system clock and ticks by its own timers.
- `driver/` is the driver application, as a build leaf: the thin program `peer.role` and one small file of values
  per instance, because a Silica program here reads no command line. Its application asks its own peer for samples,
  through the single-connection part, to print each peer it learns of.
- Its own [README](silica/README.md) says more.

### swift/

- The Swift extension is one Swift package: `lib/TempusClient` (the client library, with the gossip discovery of
  `Gossip.swift`), `lib/TempusNode` (the node library, matched to the Silica node: an edge or a sentinel, not a
  bridge), `driver/tempus-client` (the command line) and `driver/tempus-node-example` (an application that is a
  node), `testing/TempusClientTesting` (test fixtures and a clock, timers and draws that a test sets by hand; no
  library depends on it, which `make test` checks) and `test/`.
- It holds two gossip implementations side by side, `Peer` in the client library and `TempusNode` in the node
  library. The project owner has not yet decided which is kept, and its own [README](swift/README.md) says what each
  can do that the other cannot. Both libraries have a public type named `Store`; a file that imports both must select
  one.
- It builds with Apple's Command Line Tools and the OpenSSL installed on the machine; it needs no Xcode and downloads
  nothing. The statement at the top of this document applies to it as it stands.
- Its client part has no function that misbehaves on purpose and does not build the test-only `tick` and `clock`
  frames. Its node part reads the machine's clock itself.
- The trial `trials/c5_tempus_swift` runs the client against nodes and against the Python test support; the tool
  `tools/bees_tempus_swift_trial.py` walks its steps. The trial `trials/c8_tempus_node_swift` runs nodes of the
  extension in one network with Silica nodes, and the client against two of those. `gossip/` and the trial
  `trials/c7_tempus_gossip` run the driver's `Peer`. All are declared for the Mac only.

### kotlin/

- The Kotlin extension, for the Java virtual machine. Its library (`lib/`) holds the client half, the node half
  (`TempusNode`: an edge or a sentinel that behaves as the Silica node does; the bridge role is refused) and the
  gossip part of the client half (`Peer` in `Gossip.kt`, which the driver and the gossip example use).
  `driver/Main.kt` is the command line, and `test/` holds the tests and everything that is for tests only.
- `TempusNode` and `Peer` are two implementations of gossip membership kept side by side until the project owner
  decides between them; its own [README](kotlin/README.md) compares them. The node half's store and entry classes are
  named `NodeStore` and `NodeHeld`, because `Gossip.kt` declares `Store` and `Held` in the same package.
- `make build` writes `build/bees-tempus.jar` (the extension alone: no main function, no test code) and
  `build/bees-tempus-client.jar` (with the driver). It uses the JDK's own TLS and Ed25519 and no other library. It
  needs the Kotlin compiler and a JDK of release 27 or later, whose TLS has the key exchange group X25519MLKEM768
  (OpenJDK 25 does not). The statement at the top of this document applies to it as it stands.
- The trial `trials/c6_tempus_kotlin` runs the client's tests and then walks the client against nodes and against the
  Python test support. The trial `trials/c9_tempus_node_kotlin` runs the node tests and then nodes of the extension
  in one network with Silica nodes. `gossip/` and the trial `trials/c7_tempus_gossip` run the driver's `Peer`. All
  are declared for the Mac only.

### csharp/

- The C# extension, for .NET. Its library (`lib/`) holds the client half and the node half, one implementation: it has
  no second, lighter gossip peer. `driver/` is the command line and an example application that is a node. It needs
  the .NET SDK 11 and OpenSSL 4.1.0 or later, which it calls through P/Invoke for TLS and Ed25519, because .NET's own
  TLS and cryptography on macOS can neither load an Ed25519 key nor complete a handshake with a TEMPUS node. Its own
  [README](csharp/README.md) says what was tried. The statement at the top of this document applies to it as it
  stands.
- The trial `trials/c12_tempus_csharp` runs the client tests and then walks the client half against nodes and against
  the Python test support. The trial `trials/c13_tempus_node_csharp` runs the node tests and then nodes of the
  extension and Silica nodes in one network. The trial `trials/c16_tempus_bridge_csharp` walks the client half against
  two real bridges. All three are recorded for the Mac only.

## How the trials use them

- `trials/t2_tempus_frames` builds every frame with the Silica unit, in memory. The Python tests build the same frames
  and require the same bytes.
- `trials/t3_tempus_nodes` and `trials/t6_tempus_clock` run nodes that the Python client drives.
- `trials/c2_tempus_clients` runs both clients against nodes, as dialers and as listeners. Its `COVERAGE.md` says
  which behaviour of a node each client reaches.
- `trials/c3_tempus_bridge` runs both clients against bridge nodes. A bridge is a node that is a member of both a
  TEMPUS network and a TRUST network.
- `tools/bees_tempus_trial.py` starts the processes of these trials and walks the Python client through its steps.
  The Silica client's steps are compiled into small programs in the trial directories (the files ending in `.role`).
- `tools/bees_tempus_fixtures.py` and `tools/bees_tempus_ids.py` use the Python client to make the test tokens and
  identities the trials compile in.
- `trials/c7_tempus_gossip` runs the six networks of `gossip/` and compares each check with a recorded one.

The trials also send two frames, `tick` and `clock`, that are for testing only. They are not part of what a client
can use. The code that understands them is in a separate test unit, `src/tempus_test/`, which only a test program
includes in its build. A production node holds no such code and refuses both frames.
