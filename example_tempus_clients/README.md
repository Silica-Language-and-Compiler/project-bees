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
not depend on any example or on any one language.

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

`gossip/` runs the drivers. It starts several instances of one language's driver on this machine as one TEMPUS
network, and one network that mixes all four languages, and checks that the instances discover each other. Its
[README](gossip/README.md) says how to run it and what its check shows.

## What each directory holds

### python/

- `lib/tempus_client/` is the library, written completely in Python. It has its own writer and reader for the frames,
  written from the design document and not from the Silica code, so that the two examples agreeing byte for byte is
  evidence about the wire format. It uses Python's `ssl` module for TLS and the `cryptography` package for Ed25519
  signatures. `gossip.py` in it holds the stores, the shuffle and the join.
- `driver/tempus_peer.py` is the driver application.
- `lib/tempus_client/testing.py` and `bees_tempus_client.py` are for the trials: the test-only frames, tokens made
  with the test producer's key, and deliberate misbehaviour. The trial tools import `bees_tempus_client`.
- `test_bees_tempus_client.py` and `test_tempus_gossip.py` hold the tests. Run them from the BEES root directory with
  `make -C example_tempus_clients/python test`. Some of the tests compare the Python client's bytes with the recorded
  output of the trial `trials/t2_tempus_frames`, so they need that trial's recorded output to be current.
- Its own [README](python/README.md) says more, including one limit: a Python peer accepts connections only from
  certificates it was given beforehand.

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

- A client written in Swift, as a Swift package: a library (`lib/`), a driver application (`driver/`, the command
  line `tempus-client`), a test-only module (`testing/`) and unit tests (`test/`). It is
  also an example only and must not be used in production. Its own [README](swift/README.md) says how to build and
  run it, which libraries it uses and why, what it covers compared with the Python example, and what it does not
  cover. It builds with Apple's Command Line Tools and the OpenSSL installed on the machine; it needs no Xcode and
  downloads nothing.
- It differs from the two examples above in what it is for. It was written as an example of a client, not to drive the
  trials: it has no function that misbehaves on purpose, it does not build the test-only `tick` and `clock` frames,
  and it can read the system clock.
- Its library holds the gossip part (`lib/TempusClient/Gossip.swift`), and `tempus-client gossip` runs it.
- The trial `trials/c5_tempus_swift` runs it against nodes and against the Python example. The tool
  `tools/bees_tempus_swift_trial.py` walks its steps. The trial runs on the Mac only.

### kotlin/

- A client written in Kotlin for the Java virtual machine: a library (`lib/`), a driver application (`driver/`, a
  command line) and tests (`test/`). Its library holds the gossip part (`lib/Gossip.kt`), and the command `gossip`
  runs it. It is also an example
  only and must not be used in production. Its own [README](kotlin/README.md) says what must be installed, how to
  build and run it, what it checks, what it was checked against and what it does not cover. It uses the JDK's own TLS
  and Ed25519 and no other library. It needs the Kotlin compiler and a JDK whose TLS has the key exchange group
  X25519MLKEM768 (OpenJDK 27 has it; OpenJDK 25 does not).
- Like the Swift example it was written as an example of a client, not to drive the trials: it has no function that
  misbehaves on purpose, it does not build the test-only `tick` and `clock` frames, and it reads the system clock
  unless it is given a time.
- The trial `trials/c6_tempus_kotlin` runs its tests and then walks it against nodes and against the Python example.
  The walk is `Walk.kt` in the trial's directory, with the tool `walk.py` beside it. The trial has recorded output
  for the Mac only.

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
