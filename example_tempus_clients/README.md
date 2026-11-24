# TEMPUS extensions

The extensions in this directory are usable examples. Use them carefully.

TEMPUS is the gossip membership mode of BEES: nodes find each other by exchanging small signed records over mutually
authenticated TLS connections. A TEMPUS client is a program that connects to a TEMPUS node as an ordinary peer and
makes requests of it. A TEMPUS node is a member of the network, with stores of its own. An extension is code in a
language other than Silica that lets an application written in that language be a client or a node.

The extensions exist for two reasons. The first is to test BEES: the trials run them against Silica nodes and Silica
bridges, and require an extension node to answer as a Silica node does, line for line. The second is to be used. An
application may build on the extension for its language, or read it as a worked example when writing its own. The
document [What do I need to do to write a TEMPUS client?](writing-a-tempus-client.md) lists the requirements in a form
that does not depend on any extension or on any one language, and
[What do I need to do to write a TEMPUS node?](writing-a-tempus-node.md) lists what a node has to do beyond a client.

## What "use them carefully" means

- No person has reviewed this code as production code. Each extension's README lists what was tested and by which
  trial, and what was not.
- They were run on one platform, macOS on Apple Silicon, with one version of each toolchain and of OpenSSL. The Python
  extension can run on Linux, and has not been recorded there yet.
- None has had a soak test, a load test or a memory measurement.
- An application supplies its own keys, certificates and tokens, and decides how they are stored. The keys,
  certificates and tokens in this repository are test fixtures made from fixed seeds that are written here; anyone can
  reproduce them. They are in each extension's test support, which an application does not link, and each extension
  has a check that its library does not depend on it.
- Code that misbehaves on purpose, and the two frames `tick` and `clock` that only test nodes accept, are in the test
  support and the trials, not in the libraries.
- No extension can be a bridge. A bridge is also a member of a TRUST network, and there is no TRUST implementation in
  these languages.
- The interfaces are not promised to stay the same.

## How each example is laid out

Every example has two parts, in two directories:

- `lib/` is the client library: the files an application would start from. It holds the frames, admission, a single
  connection in both positions (dialing and listening), and the gossip part: the three stores, the shuffle on a timer
  and the join through a sentinel.
- `driver/` is a driver application: a thin program that passes values to the library and prints what it reports.

What is for the trials only is kept out of the library where the language allows it. Each example's README says
where it is.

Each extension has one implementation: a client half and, beneath an application, a node half that behaves as the
Silica node does (an edge or a sentinel; none can be a bridge).

`gossip/` runs the drivers. It starts several instances of one language's driver on this machine as one TEMPUS
network, and one network that mixes all four languages, and checks that the instances discover each other. Its
[README](gossip/README.md) says how to run it and what its check shows.

## What each directory holds

### python/

- `lib/bees_tempus_*.py` is the Python extension: seven modules an application imports to be a TEMPUS node (an edge or
  a sentinel; not a bridge) or a peer that is not a node. It is written completely in Python, with its own writer and
  reader for the frames, from the design document. It uses Python's `ssl` module for TLS and the `cryptography`
  package for Ed25519. The trial `trials/c7_tempus_node_python` runs its nodes and Silica nodes in one network and
  compares their audit lines case by case. Its [README](python/README.md) says what care means for it.
- `driver/tempus_peer.py` is its driver application. Its `gossip` command runs a node from a command line; `gossip/`
  and the trial `trials/c7_tempus_gossip` run it.
- `testing/bees_tempus_testing.py` is the test support: the test-only frames, token making, keys from fixed seeds and
  deliberate misbehaviour. No module an application imports imports it. `bees_tempus_client.py` is a plain name for
  it, the name the trial tools import.
- `test_bees_tempus_client.py` and `test_bees_tempus_node.py` hold the tests. Run them from the BEES root directory
  with `make -C example_tempus_clients/python test`. Some compare with the recorded outputs of the trials
  `t0_tempus_view`, `t0_tempus_clock`, `t1_tempus_store`, `t2_tempus_frames`, `t4_tempus_admission` and
  `c4_tempus_boot`, so those recorded outputs must be current.

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

- The Swift extension is one package: `lib/TempusClient` (the wire, admission, `dial` and a listener, for a client),
  `lib/TempusNode` (the node, matched to the Silica node: an edge or a sentinel, not a bridge), `driver/tempus-client`
  (the command line; its `gossip` command runs a node, as the gossip example does), `driver/tempus-node-example` (an
  application that is a node), `testing/TempusClientTesting` (test fixtures and a clock, timers and draws a test sets;
  no library depends on it, which `make test` checks) and `test/`. Its [README](swift/README.md) says what care means
  for it.
- It builds with Apple's Command Line Tools and the OpenSSL installed on the machine; it needs no Xcode and downloads
  nothing.
- The trial `trials/c5_tempus_swift` runs the client against nodes and against the Python test support; the tool
  `tools/bees_tempus_swift_trial.py` walks its steps. The trial `trials/c8_tempus_node_swift` runs nodes of the
  extension in one network with Silica nodes, and `trials/c10_tempus_bridge_swift` the client against real bridges.
  `gossip/` and the trial `trials/c7_tempus_gossip` run the driver's `gossip` command. All are declared for the Mac
  only.

### kotlin/

- The Kotlin extension, for the Java virtual machine: a client half and a node half (`TempusNode`: an edge or a
  sentinel that behaves as the Silica node does; the bridge role is refused) in `lib/`. `driver/Main.kt` is the
  command line; its `gossip` command runs a node, and is the Kotlin member of the gossip example. `test/` holds the
  tests and everything that is for tests only. Its [README](kotlin/README.md) says what care means for it.
- `make build` writes `build/bees-tempus.jar` (the extension alone: no main function, no test code) and
  `build/bees-tempus-client.jar` (with the driver). It uses the JDK's own TLS and Ed25519 and no other library. It
  needs the Kotlin compiler and a JDK of release 27 or later, whose TLS has the key exchange group X25519MLKEM768
  (OpenJDK 25 does not).
- The trial `trials/c6_tempus_kotlin` runs the client's tests and then walks the client against nodes and against the
  Python test support. The trial `trials/c9_tempus_node_kotlin` runs the node tests and then nodes of the extension
  in one network with Silica nodes, and `trials/c11_tempus_bridge_kotlin` the client against real bridges. All are
  declared for the Mac only.

### csharp/

- The C# extension, for .NET. Its library (`lib/`) holds the client half and the node half, one implementation: it has
  no second, lighter gossip peer. `driver/` is the command line and an example application that is a node. It needs
  the .NET SDK 11 and OpenSSL 4.1.0 or later, which it calls through P/Invoke for TLS and Ed25519, because .NET's own
  TLS and cryptography on macOS can neither load an Ed25519 key nor complete a handshake with a TEMPUS node. Its own
  [README](csharp/README.md) says what was tried. Its driver has no `gossip` command, so `gossip/` does not run it.
- The trial `trials/c12_tempus_csharp` runs the client tests and then walks the client half against nodes and against
  the Python test support. The trial `trials/c13_tempus_node_csharp` runs the node tests and then nodes of the
  extension and Silica nodes in one network. The trial `trials/c16_tempus_bridge_csharp` walks the client half against
  two real bridges. All three are recorded for the Mac only.

### rust/

- The Rust extension is one Cargo workspace: `lib/tempus` (the one crate an application depends on: the client half
  and the node half, an edge or a sentinel that behaves as the Silica node does; the bridge role is refused),
  `driver/tempus-client` (the command line) and `driver/tempus-node-example` (an application that is a node),
  `testing/` (test fixtures, a clock, timers and draws that a test sets by hand, and the trial's node program; the
  library does not depend on them, which `make test` checks) and `test/`.
- Its driver has no `gossip` command, so `gossip/` does not run it; its own [README](rust/README.md) says what joining
  would take.
- It builds with cargo in offline mode and has no dependency outside itself. TLS and the cryptography are the OpenSSL
  installed on the machine, called through declarations in `lib/tempus/src/ffi.rs`, with no C code.
- Its client half has no function that misbehaves on purpose and does not build the test-only `tick` and `clock`
  frames. Its node half reads the machine's clock itself.
- The trial `trials/c14_tempus_rust` runs the client against nodes and against the Python test support. The trial
  `trials/c15_tempus_node_rust` runs nodes of the extension in one network with Silica nodes, and the client against
  two of those. The trial `trials/c17_tempus_bridge_rust` runs the client against two real bridges and a TRUST node.
  All are declared for the Mac only.

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
