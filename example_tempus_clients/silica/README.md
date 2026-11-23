# The Silica example TEMPUS client

This is an example only. It must not be used in production. The reasons are in
[the directory's README](../README.md): its keys, certificates and tokens are test fixtures made from fixed seeds,
part of it exists to build wrong frames on purpose for the trials, and it has had no review as production code.

[What do I need to do to write a TEMPUS client?](../writing-a-tempus-client.md) lists what a client in any language
has to do.

## What is in here

The directory has two parts: a library, and a driver application that uses it.

| Path | What it is |
| --- | --- |
| `lib/bees_tempus_client.silica` | A pure unit. For each request a client can make it gives the frame to send, and it reads the replies. It also builds deliberately wrong frames, each by a named function, for the trials. |
| `lib/bees_tempus_client.part` | The active part for single connections: `tempus_client_start`, `tempus_client_dial`, `tempus_client_set`, `tempus_client_answer`, `tempus_client_close`. |
| `lib/bees_tempus_peer.part` | The gossip part: `tempus_peer_boot` and `tempus_peer_start`. |
| `driver/peer.role` | The driver application: a thin program over `bees_tempus_peer.part` and `bees_tempus_client.part`. |
| `driver/gs.role`, `g1.role`, `g2.role`, `g3.role` | The values of one instance each: a sentinel and three edges. |
| `driver/Makefile`, `driver/lib/` | The build leaf of the driver: links to the units it compiles. |

### Why two of the library's files are parts and not units

Silica requires the place where a carrier is started to be in the program's root unit, and a root unit may not call
a function of a `dangerous_` unit. So code that dials or listens cannot be a library unit. It is written as a part,
and the tool `tools/bees_tempus_gen.py` pastes the parts a program names into its root unit, before the program's own
role files. A program that is a client names the parts it needs with `--part`.

### What the gossip part is

In the other three examples the gossip part is new code: the stores, the shuffle on a timer and the join are written
again in that language. In Silica they are not written again. They are BEES's own library, the units of `src/tempus`
(`bees_tempus_view`, `bees_tempus_store`, `bees_tempus_store_actor`, `bees_tempus_node`, `dangerous_bees_tempus_draws`)
and the node part `src/tempus/bees_tempus_node.part`. A Silica application uses that library by listing its units.
The single-connection part of this client already does the same for admission: every connection it makes is the
node's own connection actor.

So `bees_tempus_peer.part` is small. `tempus_peer_start(app, idn, net, sz)` starts the node library as an ordinary
member of a network:

- It is never externally driven. It reads the system clock through the TEMPUS native edge, each store ticks by its own
  timer, and the draws come from the platform's secure random source.
- A program built with it lists nothing of the test unit, so it holds no `tick` and no `clock` frame.
- Nothing has a default. Every value is an argument: the identity, the token, the listen address, the sentinels, the
  whitelist, the producer key, and for each store its capacity, shuffle length and tick.

## The driver application

`driver/peer.role` passes values to `tempus_peer_start` and prints what the peer tells its application. The peer's
own lines are printed by the library: the join, every tick, and the peer it shuffles with.

The driver also starts the single-connection part, `tempus_client_start`, with the same identity. Every 700 ms it
dials its own peer over loopback and asks for a `sample` of one store: the edge store, the sentinel store and the
bridge store in turn. For each peer in a reply that it had not seen in that store it prints
`learned STORE ID16 HOST:PORT`. This is how a Silica application learns who its peer knows. A store is reached over
`tempus/1` only; the node library has no call that returns one, by design.

A Silica program here reads no command line and no file. The values of one instance are compiled in, from that
instance's role file. That is why there are four programs:

| Program | Role | Identity | Listens on |
| --- | --- | --- | --- |
| `dangerous_gs` | the sentinel | `sentinel` | 127.0.0.1:24800 |
| `dangerous_g1` | an edge | `node` | 127.0.0.1:24801 |
| `dangerous_g2` | an edge | `other` | 127.0.0.1:24802 |
| `dangerous_g3` | an edge | `x1` | 127.0.0.1:24803 |

Each edge is given the sentinel's address and nothing else. The identities are the TEST ONLY ones of
`tools/bees_tempus_ids.py`. The tokens are valid from 1000 to 4000000000 seconds after 1970, because these programs
read the system clock.

## How to run it

You need the Silica compiler that BEES is pinned to (`tools/silica.generation`), OpenSSL 4.1.0 or later, python3
with the `cryptography` package, make and clang.

From the top of the BEES tree:

```
make -C example_tempus_clients/silica/driver gossip
```

This builds the four programs, which takes about three minutes, and runs them together as one network for a few
seconds. `SILICA_COMPILER=/path/to/silica-compiler` may be given on the make command line.
[The gossip README](../gossip/README.md) says what the printed check means, and how the mixed network uses the
sentinel and one edge of this driver beside the Python, Kotlin and Swift drivers.

The programs are started and stopped by the runner. None is meant to run alone.

## What it was checked against

- `trials/c7_tempus_gossip` runs the four programs as one network, and runs the sentinel and one edge in a network
  with the Python, Kotlin and Swift drivers. Both were run on the Mac and their checks are recorded.
- The single-connection part is checked by `trials/t2_tempus_frames`, `trials/c2_tempus_clients` and
  `trials/c3_tempus_bridge`. Its files moved into `lib/` unchanged, apart from one comment line.

## What it does not cover

- A sentinel's application samples its own peer like any other. A sentinel puts every peer that asks it for a sample
  into its store of that peer's type, and here that peer is itself; the merge drops an entry that names the peer
  itself, so nothing changes. Its certificate must be in its own `tempus` whitelist for that connection.
- The single-connection part takes the time as a value. The driver passes 1500, which is inside every token of the
  example. A real application would pass the time it reads.
- The driver's values are compiled in. A change of port, identity or sentinel needs a new role file and a build.
- The gossip part was run only on one machine, with test keys, for a few seconds at a time.
- What the node library does not do, a peer built with this part does not do either.
