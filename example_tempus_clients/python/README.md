# The Python example TEMPUS client

This is an example only. It must not be used in production. The reasons are in
[the directory's README](../README.md): its keys, certificates and tokens in the trials are test fixtures made from
fixed seeds, part of it exists to misbehave on purpose, and it has had no review as production code.

[What do I need to do to write a TEMPUS client?](../writing-a-tempus-client.md) lists what a client in any language
has to do.

## What is in here

The directory has two parts: a library, and a driver application that uses it.

| Path | What it is |
| --- | --- |
| `lib/tempus_client/` | The client library. An application would start from these files. |
| `lib/tempus_client/codec.py` | The part of the Erlang external term format that the frames use. |
| `lib/tempus_client/frames.py` | Descriptors, the structure and checks of a token, every frame body, and `read_body`, which checks every bound. |
| `lib/tempus_client/connection.py` | `Identity`, `Verifier`, `dial`, `Listener` and `Outcome`: one connection, in both positions. |
| `lib/tempus_client/gossip.py` | The view rules, `Store` and `Peer`: the three stores, the shuffle on a timer, and the join. |
| `lib/tempus_client/testing.py` | For the trials only. See below. |
| `driver/tempus_peer.py` | The driver application: a command line over the library. |
| `bees_tempus_client.py` | The module the trial tools import. See below. |
| `test_bees_tempus_client.py` | Tests of the codec, the frames and single connections. |
| `test_tempus_gossip.py` | Tests of the gossip part. |

The library needs Python 3 and the `cryptography` package, for Ed25519 signatures and for reading certificates. TLS is
Python's own `ssl` module. Nothing else is needed.

### What is for the trials only

`lib/tempus_client/testing.py` holds what a client must not contain: the two frames of the test unit (`tick` and
`clock`), tokens signed with the test producer's fixed seed, identities made from fixed seeds, certificates that a
node must refuse, and each way to misbehave on purpose. `from tempus_client import *` does not import it.

`bees_tempus_client.py` exists because the trial tools were written against one module of that name. It imports the
library and the test-only part together, and it has the trials' own command line. A program that is a client imports
`tempus_client` from `lib/` and never this file.

Two things of the trials are still inside the library, because the connection code has to consult them:

- `dial` and `Listener` take a `misbehaviour` argument, and a listener's handler may return an instruction such as
  "stay silent". A program that is not a trial passes neither.
- `read_body` reads the `tick`, `clock` and `done` frames, because the trials' listeners must be able to show them.
  The functions that write those frames are in `testing.py`.

## The gossip part

`gossip.py` adds what a client needs to find other peers by itself:

- The view rules of the design's section 3: ageing, the choice of a partner, the merge, the eviction.
- `Store`, one of a peer's three stores, with its steps: tick, reply, failed, request, sample, insert, drop.
- `Peer`, which listens, joins through its sentinels, ticks each store on its own timer, and answers the shuffles
  and samples of admitted peers from its stores. A peer whose token says `tempus_sentinel` also puts every peer that
  asks it for a sample into its store of that peer's type.

Nothing in it has a default. The capacity, shuffle length and tick of each store, the time bound of a connection,
the sentinels and the retry delays of the join are values the application passes.

```
import time
import tempus_client as tc

me = tc.Identity.from_pem(cert_pem, key_pem, token, "192.0.2.7:7000")
verifier = tc.Verifier(producer_pub, "k1", lambda: int(time.time()), 10, whitelist={tc.certificate_fingerprint(sentinel_pem)})
store = tc.StoreSettings(capacity=8, shuffle_length=4, tick_ms=500)
settings = tc.PeerSettings({t: store for t in tc.TYPES}, shuffle_timeout_ms=3000, sentinels=["192.0.2.1:7000"],
                           join_retry_initial_ms=500, join_retry_max_ms=2000)
peer = tc.Peer(me, verifier, settings, host="192.0.2.7", port=7000, trusted=certificates_of_peers,
               on_learned=lambda store, d: print(store, d[tc.Atom("addr")])).start()
```

## How to run it

All commands are run from the top of the BEES tree.

The tests:

```
make -C example_tempus_clients/python test
```

Four instances of the driver as one TEMPUS network on this machine, one sentinel and three edges:

```
make -C example_tempus_clients/python gossip
```

Each edge is given the sentinel's address and nothing else. The run ends when every instance has learned of every
edge. [The gossip README](../gossip/README.md) says what the printed check means.

One instance by hand. `tempus_peer.py` with no arguments prints every option:

```
python3 example_tempus_clients/python/driver/tempus_peer.py gossip \
    --cert node.pem --key node-key.pem --token node.token --addr 127.0.0.1:24801 \
    --producer-pub HEX --kid k1 --skew 10 --timeout-ms 3000 \
    --store-edge 8:4:500 --store-bridge 8:4:5000 --store-sentinel 8:4:1000 --join-retry-ms 500:2000 \
    --sentinel 127.0.0.1:24800 --whitelist-cert sentinel.pem --trusted-cert sentinel.pem --trusted-cert other.pem
```

It prints the peer's own lines (the join, each tick) and a line `learned STORE ID16 HOST:PORT` for each peer it comes
to know.

## What it was checked against

- `test_tempus_gossip.py` gives the same random steps to the rules in `gossip.py` and to the independent models in
  `tools/bees_tempus_view_model.py` and `tools/bees_tempus_store_model.py`, and requires the same view after each
  step. Those models are themselves compared with the node's Silica units by the tests in `tools/`.
- The same file runs a sentinel and two edges of this library in one process, over TLS on loopback.
- `trials/c7_tempus_gossip` runs four instances of the driver as one network, and one instance in a network with
  the Silica, Kotlin and Swift drivers. Both were run and their checks are recorded.
- The codec, the frames and single connections are checked as before, by `test_bees_tempus_client.py` and by the
  trials that drive nodes with this client.

## What it does not cover

- **A Python peer accepts a connection only from a certificate it was given beforehand.** Python's `ssl` module
  hands a server the client's certificate only when the server verifies it against loaded certificates. So every
  peer that may dial a Python peer must be named with `--trusted-cert`, or `trusted=` in the library. A real TEMPUS
  network admits any peer that holds a token, so a Python peer cannot be a full member of one. The Kotlin and Swift
  examples do not have this limit. Two trusted certificates must also not share a subject name, because `ssl` finds
  a trusted certificate by its subject.
- It does not refresh its token. `Peer.new_token` takes a new one from the application.
- It does not serve `call` or `cast`. Those are for a bridge.
- Its clock choices are the application's: `Verifier` takes a function that returns the time. It has none of a
  node's rules for a clock that fails or goes back.
- It keeps no score of peers and has no limit on accepted connections.
- `Verifier` applies the whitelist rule only when it is given a whitelist. The trials' clients are given none.
