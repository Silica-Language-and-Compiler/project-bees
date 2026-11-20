# Example TEMPUS clients

These two clients are examples only. They must not be used in production.

TEMPUS is the gossip membership mode of BEES: nodes find each other by exchanging small signed records over mutually
authenticated TLS connections. A TEMPUS client is a program that connects to a TEMPUS node as an ordinary peer and
makes requests of it.

The clients in this directory exist for two reasons. The first is to test BEES: the trials use them to drive TEMPUS
nodes through every behaviour a node has, including every refusal. The second is to serve as examples. If you need a
TEMPUS client in your own application, write it as part of that application, in whatever language the application
uses, and read these two as worked examples of what such a client has to do. The document
[What do I need to do to write a TEMPUS client?](writing-a-tempus-client.md) lists the requirements in a form that does
not depend on either example or on any one language.

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

- `bees_tempus_client.py` is a client written completely in Python. It is both a module and a command line. It has
  its own writer and reader for the frames, written from the design document and not from the Silica code, so that
  the two examples agreeing byte for byte is evidence about the wire format. It uses Python's `ssl` module for TLS and
  the `cryptography` package for Ed25519 signatures. It can dial a node and it can listen for a node to dial it.
- `test_bees_tempus_client.py` holds its tests. Run them from the BEES root directory with
  `python3 example_tempus_clients/python/test_bees_tempus_client.py`. Some of the tests compare the Python client's
  bytes with the recorded output of the trial `trials/t2_tempus_frames`, so they need that trial's recorded output to
  be current.

### silica/

- `bees_tempus_client.silica` is a pure Silica unit. For each request a client can make it gives the frame to send,
  and it reads the replies. It also builds deliberately wrong frames for the trials. It opens no connection, holds no
  key and reads no file.
- `bees_tempus_client.part` is the active part: the code that dials, listens and runs admission. It is not a unit. The
  tool `tools/bees_tempus_gen.py` pastes it into the root unit of a client program, because Silica requires the place
  where a carrier is started to be in the root unit. Each connection it makes is run by the same connection actor a
  BEES TEMPUS node uses (`src/tempus/dangerous_bees_tempus_conn.silica`), so the Silica example shares its admission
  code with the node. The Python example shares nothing with it.

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
