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

## What each directory holds

### python/

- The Python extension: seven modules an application imports to be a TEMPUS peer or a TEMPUS node (an edge or a
  sentinel; not a bridge), written completely in Python. It has its own writer and reader for the frames, written
  from the design document and not from the Silica code, so that the two agreeing byte for byte is evidence about the
  wire format. It uses Python's `ssl` module for TLS and the `cryptography` package for Ed25519 signatures. Its own
  [README](python/README.md) says what it is, what to install, how an application starts a node with it, what
  configuration it takes, what the application is told, what is tested and what is not covered. The trial
  `trials/c7_tempus_node_python` runs its nodes and Silica nodes in one network.
- `bees_tempus_testing.py` is the test support: the test-only `tick` and `clock` frames, token making, keys from
  fixed seeds, and peers that misbehave on purpose. It is what the trials drive nodes with. It is no part of the
  extension, and no module of the extension imports it. `bees_tempus_client.py` is its old name, kept as a thin
  module because the trial tools import that name.
- `test_bees_tempus_client.py` and `test_bees_tempus_node.py` hold the tests. Run them from the BEES root directory
  with `python3 example_tempus_clients/python/test_bees_tempus_client.py` and
  `python3 example_tempus_clients/python/test_bees_tempus_node.py`. Some of the tests compare with the recorded
  outputs of the trials `t0_tempus_view`, `t0_tempus_clock`, `t1_tempus_store`, `t2_tempus_frames`,
  `t4_tempus_admission` and `c4_tempus_boot`, so they need those recorded outputs to be current.

### silica/

- `bees_tempus_client.silica` is a pure Silica unit. For each request a client can make it gives the frame to send,
  and it reads the replies. It also builds deliberately wrong frames for the trials. It opens no connection, holds no
  key and reads no file.
- `bees_tempus_client.part` is the active part: the code that dials, listens and runs admission. It is not a unit. The
  tool `tools/bees_tempus_gen.py` pastes it into the root unit of a client program, because Silica requires the place
  where a carrier is started to be in the root unit. Each connection it makes is run by the same connection actor a
  BEES TEMPUS node uses (`src/tempus/dangerous_bees_tempus_conn.silica`), so the Silica example shares its admission
  code with the node. The Python example shares nothing with it.

### swift/

- The Swift extension, as a Swift package with two parts an application can depend on: the wire and client part
  (target `TempusClient`) and the node part (target `TempusNode`), which lets an application written in Swift be a
  TEMPUS node, as an edge or as a sentinel. It cannot be a bridge. Its own [README](swift/README.md) says what to
  install, how an application starts a node, what configuration the node takes, what the application is told, what
  was tested and by which trial, and what stands between it and production use. Test keys, test tokens and a clock,
  timers and draws that a test sets by hand are in a separate target (`TempusTestSupport`) that no application links.
  The statement at the top of this document applies to it as it stands.
- It builds with Apple's Command Line Tools and the OpenSSL installed on the machine; it needs no Xcode and downloads
  nothing.
- Its client part has no function that misbehaves on purpose and does not build the test-only `tick` and `clock`
  frames. Its node part reads the machine's clock itself.
- The trial `trials/c5_tempus_swift` runs the client against nodes and against the Python test support; the tool
  `tools/bees_tempus_swift_trial.py` walks its steps. The trial `trials/c8_tempus_node_swift` runs nodes of the
  extension in one network with Silica nodes, and the client against two of those; `walk.py` in that directory walks
  its steps. The trial `trials/c10_tempus_bridge_swift` was written to run the client against real bridges and has
  not run yet (its `COVERAGE.md` says why). All three are for the Mac only.

### kotlin/

- The Kotlin extension, for the Java virtual machine: a client half (dial and listen as an ordinary peer) and a node
  half, which lets an application written in Kotlin be a TEMPUS node, as an edge or as a sentinel. It cannot be a
  bridge. Its own [README](kotlin/README.md) says what to install, what an application depends on (one file,
  `build/bees-tempus.jar`, beside the Kotlin standard library), how an application starts a node, what configuration
  the node takes, what the application is told, what was tested and by which trial, and what stands between it and
  production use. It uses the JDK's own TLS and Ed25519 and no other library. It needs the Kotlin compiler and a JDK
  of release 27 or later, whose TLS has the key exchange group X25519MLKEM768 (OpenJDK 25 does not). The statement
  at the top of this document applies to it as it stands.
- It has no function that misbehaves on purpose and does not build the test-only `tick` and `clock` frames. A node
  of it reads the machine's clock itself. Test keys, test tokens and a clock, timers and draws that a test sets by
  hand are under `test/`, which no application compiles. The command line of the client is under `cli/`.
- The trial `trials/c6_tempus_kotlin` runs the client's tests and then walks the client against nodes and against the
  Python test support (`Walk.kt` and `walk.py` in that directory). The trial `trials/c9_tempus_node_kotlin` runs the
  node tests and then nodes of the extension in one network with Silica nodes (`Net.kt` and `walk.py`). The trial
  `trials/c11_tempus_bridge_kotlin` was written to run the client against real bridges and has not run yet (its
  `COVERAGE.md` says why, and lists what the client's trials cover). All three are for the Mac only.

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

The trials also send two frames, `tick` and `clock`, that are for testing only. They are not part of what a client
can use. The code that understands them is in a separate test unit, `src/tempus_test/`, which only a test program
includes in its build. A production node holds no such code and refuses both frames.
