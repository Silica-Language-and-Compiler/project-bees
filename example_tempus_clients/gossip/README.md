# The gossip examples: several clients on one machine, discovering each other

This directory runs the driver applications of the four example TEMPUS clients as small TEMPUS networks on one
machine. It shows the part of TEMPUS that a single request does not show: peers that were told one address find all
the others by gossip.

Everything here is an example. The keys, certificates and tokens are TEST ONLY fixtures made from fixed seeds that
are written in this repository (`trials/t5_tempus_tls/certs`, `tools/bees_tempus_certs.py`). Anyone can reproduce
them. Never use them for a real peer.

## The six networks

| Name | Instances |
| --- | --- |
| `python` | one sentinel and three edges, all the Python driver (`../python/driver/tempus_peer.py`) |
| `kotlin` | one sentinel and three edges, all the Kotlin driver (`../kotlin/driver/Main.kt`) |
| `swift` | one sentinel and three edges, all the Swift driver (`../swift/driver/tempus-client`) |
| `silica` | one sentinel and three edges, all the Silica driver (`../silica/driver`) |
| `mixed` | a Silica sentinel and four edges, one of each language: Silica, Python, Kotlin, Swift |
| `trio` | the mixed network without the Silica driver: a Swift sentinel and three edges, one each of Python, Kotlin and Swift |

All six were run on the Mac, and the check of each is recorded.

Every instance is a separate process that listens on `127.0.0.1`. The sentinel has port 24800 and the edges have
24801 to 24804. Only one network runs at a time, because all six use these ports.

In every network:

- Each edge is given the sentinel's address and the sentinel's certificate. It is given nothing about the other edges.
- Each instance has its own identity and its own token. The sentinel's token says `tempus_sentinel` and the others
  say `tempus_edge`.
- Each store has capacity 8 and shuffle length 4. The edge store ticks every 500 ms, the sentinel store every
  1000 ms and the bridge store every 5000 ms. A connection is bounded by 3000 ms.
- Every instance reads the system clock. The tokens are valid from 1000 to 4000000000 seconds after 1970.

## What you need

Each driver needs what its own README lists:

- Python 3 with the `cryptography` package. The runner needs it for every network, because it makes the test tokens
  with the Python example.
- For `kotlin`, `mixed` and `trio`: `kotlinc` and a JDK of feature release 27.
- For `swift`, `mixed` and `trio`: Apple's Command Line Tools and OpenSSL 4.1.0 or later.
- For `silica` and `mixed`: the Silica compiler that BEES is pinned to (`tools/silica.generation`), OpenSSL 4.1.0
  or later, make and clang.

A network whose driver cannot be built fails and says what is missing. Nothing is skipped.

## How to run it

From this directory:

```
make python      # or kotlin, swift, silica: build that driver, then run its network
make mixed       # build all four drivers, then run the mixed network
make trio        # build the Python, Kotlin and Swift drivers, then run the network of those three
make start       # all six, one after the other
```

`kotlinc` and `java` must be on `PATH` (Homebrew's JDK is not registered with macOS, so `/usr/bin/java` does not find
it: put `/opt/homebrew/opt/openjdk/bin` on `PATH`). `KOTLINC`, `JAVA` and `SILICA_COMPILER` may instead be given on
the make command line. The Silica driver takes about three
minutes to build the first time. A network runs for about six seconds.

Each language's own directory also runs its network: `make -C ../python gossip`, `make -C ../kotlin gossip`,
`make -C ../swift gossip`, `make -C ../silica/driver gossip`.

As a trial, from the top of the tree:

```
tools/run_all_trials.sh --local-only --only c7_tempus_gossip
```

The trial is `trials/c7_tempus_gossip`. It builds the four drivers, runs the six networks and compares each check
with the recorded one.

## What a run prints

The runner prints a check. This is the recorded check of the `mixed` network:

```
TEMPUS gossip example `mixed`: 5 instances on 127.0.0.1, one network; every edge was given the sentinel's address only
  s   tempus_sentinel  silica driver  identity sentinel  9e1113ab416dc197  127.0.0.1:24800
  e1  tempus_edge      silica driver  identity node      b19edad2958934e1  127.0.0.1:24801
  e2  tempus_edge      python driver  identity other     1fae2ad7f75a0ded  127.0.0.1:24802
  e3  tempus_edge      kotlin driver  identity x1        9200d2990c3e9eb7  127.0.0.1:24803
  e4  tempus_edge      swift  driver  identity x2        12eb7f449478f2aa  127.0.0.1:24804
s learned of, in its edge store: e1 e2 e3 e4
e1 learned of, in its edge store: e2 e3 e4; in its sentinel store: s
e2 learned of, in its edge store: e1 e3 e4; in its sentinel store: s
e3 learned of, in its edge store: e1 e2 e4; in its sentinel store: s
e4 learned of, in its edge store: e1 e2 e3; in its sentinel store: s
every instance learned of every edge: yes
every edge learned of the sentinel: yes
every instance merged a shuffle of its edge store that it started: yes
no shuffle failed while all instances ran: yes
every instance ran until it was stopped: yes
```

The check is the same on every run, so it is what the trial compares. Each instance's own output is in
`.run/NAME.LABEL.out`, for example `.run/mixed.e3.out`. That output shows the join, every tick and every peer as it
is learned. It depends on timing and on random draws, so it differs from run to run and is not compared.

## How the runner knows what an instance has learned

Every driver prints `learned STORE ID16 HOST:PORT` when it first sees a peer in one of its stores.

- The Python, Kotlin and Swift libraries call their driver at the moment a peer enters a store.
- The Silica driver cannot be called at that moment: BEES's node library has no call that returns a store, by design.
  Its application asks instead, as any admitted peer may. Every 700 ms it sends its own peer a `sample` request over
  loopback, for the edge, sentinel and bridge store in turn, and prints each peer it had not seen. So a Silica
  instance shows a peer a little later than it learned of it.

The runner also reads the lines `tick STORE: shuffle with ID8 at HOST:PORT`, which every driver prints. A peer named
there is one the instance holds in that store, because it dials only what its store holds.

The runner stops the network when nothing is left to learn, every instance has merged a shuffle that it started, and
six seconds have passed. It fails after 90 seconds.

## What the check shows

- An edge that knew only the sentinel's address came to hold every other edge, in every language.
- The sentinel came to hold every edge, from their `sample` requests.
- Every instance started a shuffle of its edge store, was answered, and merged the reply. In the `mixed` and `trio`
  networks the partners are drivers of other languages, so the frames, the admission and the verification of entries
  agree across the four examples. The Silica driver's connections are BEES's own node code.
- No shuffle failed while all the instances were running.

## What the check does not show

- It does not show which peer learned of which other through a shuffle and which through the sentinel's sample. An
  edge that joins last is given the earlier edges by the sentinel at once.
- It does not show that every pair of languages shuffled with each other. Partners are chosen by age and at random.
- It does not show a peer leaving, a token expiring, a refused peer, or a store at its capacity. Four or five peers
  do not fill a store of capacity 8.
- It does not show a bridge. No instance has a bridge token, so every bridge store stays empty.
- It runs on one machine, on the loopback address, for a few seconds.
- The trials that drive a node through every refusal are `trials/c2_tempus_clients`, `trials/c5_tempus_swift` and
  `trials/c6_tempus_kotlin`. This directory does not repeat them.

## What is in here

| Path | What it is |
| --- | --- |
| `gossip_run.py` | Starts the instances of one network, reads their output, stops them, and writes the check. It also writes the Silica driver's token unit. |
| `Makefile` | Builds the drivers and runs the networks. |
| `NAME.check.PLATFORM.scout` | The recorded check of each network, one set per platform. Recorded so far: all six, on the Mac. |
| `.run/` | What the last run wrote. It is not kept in the repository. |
