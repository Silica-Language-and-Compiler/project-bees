# The Kotlin extension for TEMPUS

The Kotlin extension lets a program written in Kotlin, or in another language of the Java virtual machine, take part
in a TEMPUS network. TEMPUS is the gossip membership mode of BEES: nodes find each other by exchanging signed records
over mutually authenticated TLS 1.3 connections. The extension has two halves. The client half connects to a node as
an ordinary peer and makes one request. The node half makes the application a member of the network: a node, with
stores of its own, that joins, shuffles, answers and admits as the Silica node of `src/tempus` does.

The directory is a library (`lib/`), a driver application over it (`driver/`) and tests (`test/`). The library holds
two implementations of gossip membership, side by side. `Peer` in `lib/Gossip.kt` is the one the driver and the
gossip example use. `TempusNode` in `lib/Node.kt` is the node half. They were written separately, each is used by its
own callers, and neither uses the other. The project owner has not decided which of the two is kept. The section
"Two gossip implementations" below says what each does that the other does not.

The statement of the directory's [README](../README.md) applies to it as it stands: it is an example, and it must not
be used in production. The section "What stands between this and production use" below says what has and what has not
been done. Everything it was checked with uses keys, certificates and tokens made from fixed seeds that are written in
this repository. The documents [What do I need to do to write a TEMPUS client?](../writing-a-tempus-client.md) and
[What do I need to do to write a TEMPUS node?](../writing-a-tempus-node.md) say what a client and a node have to do,
in a form that does not depend on any one language.

## What it is

It uses nothing but the Kotlin standard library and the JDK: the JDK's own TLS for the connection, and the JDK's own
Ed25519 and SHA-512. It has its own writer and reader for the frames, written from the documents named above and from
the ruled design (`development-plan/tempus-design.md`), not from the Python or the Silica code.

The client half can dial a node and it can listen for a node to dial it. On every connection it does the whole
admission: its advert, the check of the peer's advert and token, the binding of the advert to the peer's TLS
certificate, the tempus whitelist rule, the challenge, its own proof of possession and the check of the peer's. It
makes every request a client can make (`sample`, `shuffle`, and `call` and `cast` to a bridge), reads every reply, and
verifies every entry of a reply before it reports the reply as good.

The client half can also be a member of a network through `Peer`: it keeps the three stores, shuffles each on its
own timer, joins through the configured sentinels, and answers the shuffles and samples of admitted peers from its
stores. The section "The gossip part" below says more.

The node half is described in the sections "A node" to "What a node does not cover" below.

The extension does not contain the two test-only frames, `tick` and `clock`, or their answer, `done`. To the client
and to a node they are frames of no kind, and both refuse them. No source file of the extension holds a test key, a
function that makes a token, or a peer that misbehaves.

The files:

- `lib/` is the library. An application would start from these files.
- `lib/Etf.kt` writes and reads the part of the Erlang external term format that the frames use.
- `lib/Frames.kt` holds the messages, with every bound on their fields, and the structure of a token.
- `lib/Admission.kt` holds the identity (key, certificate, token, listen address) and the client's verifier.
- `lib/Client.kt` holds the TLS setup, `dial`, `Listener`, and `Outcome`, the plain value that says what happened on
  a connection.
- `lib/Gossip.kt` holds the view rules, `Store` and `Peer`: the gossip part of the client half.
- `lib/View.kt` holds the view of one store and the steps of one store for the node half, as pure functions (the
  object `View`) and one small class (`NodeStore`, with its entries `NodeHeld`).
- `lib/Clock.kt` holds what one reading of the clock does to a node, as a pure function, and the machine's clock.
- `lib/Config.kt` holds a node's configuration and its refusals.
- `lib/Node.kt` holds the node.
- `driver/Main.kt` is the driver application: a command line over the library, for one request, for listening and
  for running a `Peer`. It is not part of the extension.
- `test/TestMain.kt` holds the tests of the frames and of single connections, `test/GossipTest.kt` the tests of the
  gossip part, and `test/NodeTestMain.kt` the tests of the node half. They are run by plain `main` functions, so no
  test library is needed. `test/model_cases.py` writes the cases the node tests read.
- `test/Fixtures.kt` and `test/NodeFixtures.kt` are for the tests and the trials only. The first makes tokens from
  the test producer's fixed seed. The second holds a clock, timers and draws that a test sets by hand. Nothing under
  `lib` or `driver` uses either.

## What an application depends on

`make build` writes `build/bees-tempus.jar`: the compiled extension alone (`lib/*.kt`, which includes `lib/Gossip.kt`), with no `main` function, no
test code and no copy of the Kotlin runtime. An application puts that file on its class path beside the Kotlin
standard library, and runs on a JDK of release 27 or later. It needs nothing else. Everything is in the one package
`bees.tempus`. What an application uses of it: `Identity`, `TempusConfig` with `StoreConfig` and `SentinelAddress`,
`TempusNode`, `NodeListener`, `NodeEvent`, `NodeEnvironment`, `ConfigRefused`, and for the client half `dial`,
`Listener`, `Verifier`, `Settings`, `Request` and `Outcome`, and for its gossip part `StoreSettings`, `PeerSettings`
and `Peer`. The declarations marked `internal` are not for an application.

## What must be installed

Two things, and nothing else. No build tool such as Gradle or Maven is used, and no library is downloaded.

1. The Kotlin compiler, `kotlinc`. Version 2.4.21 was used, installed with Homebrew: `brew install kotlin`.
2. A JDK whose TLS can offer the key exchange group X25519MLKEM768, which a TEMPUS node requires. OpenJDK 27.0.1.1
   was used. Homebrew installs it as a dependency of `kotlin`, at `/opt/homebrew/opt/openjdk`; it can also be
   installed by itself with `brew install openjdk`. OpenJDK 25.0.2 was tried and cannot be used: its TLS does not have
   that group, so it cannot complete a handshake with a TEMPUS node. `make` and the trials stop with a message that
   says so when `java` is of a release before 27.

`kotlinc` and `java` must be on `PATH`, and `java` must be that JDK. On macOS, `/usr/bin/java` is a placeholder that
runs the JDK named by `JAVA_HOME`, or one registered with the system, and fails when there is neither. Homebrew does
not register its JDK with the system, so name it:

```
export JAVA_HOME=/opt/homebrew/opt/openjdk
export PATH="$JAVA_HOME/bin:$PATH"
kotlinc -version
java -version
```

The tests and the trial also read files of this repository (the recorded output of other trials, and the TEST ONLY
certificates in `trials/t5_tempus_tls/certs`), and the trial needs what every TEMPUS trial needs: the Silica compiler,
OpenSSL for the nodes, and Python 3 with the `cryptography` package for the Python example client.

## How to build and run

From this directory:

```
make build     # writes build/bees-tempus.jar (the extension alone) and build/bees-tempus-client.jar (with the driver)
make test      # compiles the tests with the extension and runs them
make gossip    # four instances of the driver as one TEMPUS network on this machine
make clean
```

`make build` runs `kotlinc -nowarn -d build/bees-tempus.jar lib/*.kt` for the extension alone, and
`kotlinc -nowarn -include-runtime -d build/bees-tempus-client.jar lib/*.kt driver/*.kt` for the driver. The second
file holds the extension, the driver and the Kotlin runtime, so `java -jar` runs it.

The command line prints its usage when it is run with no arguments. Every option is required unless the usage says it
is optional, because none of the values has a default: the time bound of a connection, the clock difference allowed
and the shuffle length belong to the network the client joins.

```
java -jar build/bees-tempus-client.jar dial 127.0.0.1:24601 \
    --cert CERT.pem --key KEY.pem --token TOKEN.hex --addr 127.0.0.1:24603 \
    --producer-pub HEX --kid k1 --skew 10 --timeout-ms 5000 --shuffle-length 3 \
    sample tempus_edge 3
```

- `--cert` and `--key` are the client's certificate, self-signed over its Ed25519 key, and that key as an unencrypted
  PKCS#8 PEM file. The JDK has no supported way to make such a certificate, so the application's own tooling has to
  make it. The trials' certificates were made by `tools/bees_tempus_certs.py`.
- `--token` is a file that holds the token from the producer as hex digits.
- `--whitelist-cert FILE` may be given any number of times. Each names the certificate of a bridge or a sentinel the
  client accepts. With none, the client accepts no bridge and no sentinel.
- `--now SECONDS` replaces the system clock for the token checks. It exists for the trials, whose tokens are valid at
  fixed times. Without it the client reads the system clock.
- The requests are `sample STORE N`, `shuffle STORE` (which offers the client's own entry at age 0), and
  `call REQ_ID MODULE FUNCTION [INT]...` and `cast REQ_ID MODULE FUNCTION [INT]...` to a bridge.
- `listen HOST:PORT ... --count N` accepts N connections and answers a sample or a shuffle with the client's own
  entry, or with no entries when the store is of another type than the client's token.
- `read-hex HEX SHUFFLE_LENGTH` reads one frame body and says what it is.

The outcome of a connection is printed as one line, for example
`reply sample_reply entries=[0:1fae2ad7f75a0ded] store=tempus_edge peer=b19edad2958934e1 typ=tempus_edge`. The first
word is one of `reply`, `served`, `key_rotated`, `refused` (this client refused the peer; the reason follows),
`closed` (the connection closed with no reply, which is all that a refusal by the peer ever shows, and is also the
ordinary end of a `cast`), `timeout`, `tls_failed` and `unreachable`.

From Kotlin code, the entry points of the client half are `Identity.load`, `Verifier`, `Settings`, `dial` and
`Listener`, and for a member of a network `StoreSettings`, `PeerSettings` and `Peer`. The trial's `Walk.kt` uses the
first five the way an application would, and `driver/Main.kt` uses `Peer`.

## The gossip part

`lib/Gossip.kt` adds what a client needs to find other peers by itself:

- The view rules of the design's section 3: ageing, the choice of a partner, the merge, the eviction.
- `Store`, one of a peer's three stores, with its steps: tick, reply, failed, request, sample, insert, drop.
- `Peer`, which listens, joins through its sentinels, ticks each store on its own timer, and answers the shuffles and
  samples of admitted peers from its stores. A peer whose token says `tempus_sentinel` also puts every peer that asks
  it for a sample into its store of that peer's type.

Nothing in it has a default. The capacity, shuffle length and tick of each store, the time bound of a connection, the
sentinels and the retry delays of the join are values the application passes.

```
java -jar build/bees-tempus-client.jar gossip \
    --cert CERT.pem --key KEY.pem --token TOKEN.hex --addr 127.0.0.1:24801 \
    --producer-pub HEX --kid k1 --skew 10 --timeout-ms 3000 \
    --store-edge 8:4:500 --store-bridge 8:4:5000 --store-sentinel 8:4:1000 --join-retry-ms 500:2000 \
    --sentinel 127.0.0.1:24800 --whitelist-cert SENTINEL.pem
```

It listens on the address of `--addr`. It prints the peer's own lines (the join, each tick) and a line
`learned STORE ID16 HOST:PORT` for each peer it comes to know. It runs until it is interrupted, or for `--run-ms`.

`make gossip` starts four such instances on this machine, one sentinel and three edges, and stops them when every
instance has learned of every edge. Each edge is given the sentinel's address and nothing else.
[The gossip README](../gossip/README.md) says what the printed check means. It needs Python 3 with the `cryptography`
package, because the runner and the test tokens are made with the Python example.

## Two gossip implementations

The library holds two sets of code for the same job, because two lines of work each wrote one. Both are kept whole
until the project owner decides between them. They share `lib/Etf.kt`, `lib/Frames.kt`, `lib/Admission.kt` and the
TLS setup of `lib/Client.kt`, and nothing else.

| | `Peer` (`lib/Gossip.kt`) | `TempusNode` (`lib/Node.kt`, `View.kt`, `Clock.kt`, `Config.kt`) |
| --- | --- | --- |
| Store and entry types | `Store`, `Held` | `NodeStore`, `NodeHeld`, with the pure functions in the object `View` |
| Connections | `dial` and `Listener` of the client half, one request each | its own connection code (`NodeConn`), in the Silica node's order of checks |
| Settings | `PeerSettings` and `StoreSettings`, checked with `require` | `TempusConfig`, with the keys, bounds and refusal texts of the Silica node's `bees.config` |
| Clock | the function given to the `Verifier` | read by the node, with `clockBack` (`follow`, `hold`, `stop`), `clockFail` (`continue`, `pause`) and `clockReadMs` |
| Limit on accepted connections | none | `inflightMax`, with the close `inflight_refused` |
| What it writes | its own lines, through `onLine` | the Silica node's boot, `join:`, `tick` and `clock:` lines and `[tempus audit]` lines, word for word |
| What the application is told | `onLearned(store, descriptor)` for each new peer | `NodeEvent`: own token invalid, key rotated, clock unreadable, stopped, listen failed, view changed |
| New token while running | `newToken` | `setToken`, and `setProducerKey` for a new producer key |
| How a test drives it | real timers and the system clock; draws may be passed | a `NodeEnvironment` with a clock, timers and draws the test sets by hand |
| Unit tests | `test/GossipTest.kt`, 10 tests on cases worked by hand and one network in one process | `test/NodeTestMain.kt`, 24 tests against the two Python models and the Silica goldens |
| Run with other implementations | `../gossip` (`kotlin`, `mixed`, `trio`) and `trials/c7_tempus_gossip`, against the drivers of the other languages | `trials/c9_tempus_node_kotlin`, against Silica nodes, with the audit lines compared |
| A command line | `gossip` in `driver/Main.kt` | none |

Two names were changed so that both compile in the one package `bees.tempus`. The node half's store and entry classes
were called `Store` and `Held`, which are the names `lib/Gossip.kt` uses; they are now `NodeStore` and `NodeHeld`.
Nothing of `lib/Gossip.kt` was renamed.


## A node

A node of the extension is an edge or a sentinel. An edge is an ordinary member. A sentinel is a member that others
join through; its certificate is listed in the other nodes' tempus whitelist. The third type, the bridge, is not
provided: a bridge is also a member of a TRUST network, and the extension has no TRUST side. A configuration whose
role is `bridge` is refused. The section "What a node does not cover" says what a bridge would need.

### How an application starts a node

The application supplies three things: its identity, its configuration, and a listener that is told what happens.

The JDK has no supported call that makes an X.509 certificate, so the application's own tooling makes the Ed25519 key
and the certificate that is self-signed over it, once, and the node takes them from files or from values. From files:
`Identity.load(certificateFile, keyFile, token, address)` reads a PEM certificate and an unencrypted PKCS#8 PEM key.
From values: `Identity(certificate, privateKey, token, address)` takes a `java.security.cert.X509Certificate` and a
`java.security.PrivateKey` the application made or read in any way it likes. `token` is the bytes the producer gave
the application. `address` is the text `host:port` that other nodes dial; it is what the node advertises. The
private key stays inside the `Identity` object and the JDK's TLS and signature code. The extension never writes it
to a line or a frame, and keeps no other copy.

```kotlin
import bees.tempus.*
import java.nio.file.Files
import java.nio.file.Path

fun main() {
    val token = Files.readAllBytes(Path.of("token.bin"))                    // from the producer; the application fetched it
    val me = Identity.load(Path.of("node.pem"), Path.of("node-key.pem"), token, "192.0.2.10:7000")
    val sentinel = readCertificate(Files.readAllBytes(Path.of("sentinel.pem")))
    val config = TempusConfig(
        role = "edge", listenAddress = "0.0.0.0", port = 7000,
        sentinels = listOf(SentinelAddress("192.0.2.1", 7000, "s1")),
        edge = StoreConfig(capacity = 20, shuffleLength = 5, tickMs = 10000),
        bridge = StoreConfig(capacity = 8, shuffleLength = 3, tickMs = 30000),
        sentinel = StoreConfig(capacity = 8, shuffleLength = 3, tickMs = 30000),
        producerKid = "k1".toByteArray(), producerKey = Files.readAllBytes(Path.of("producer.pub")),
        whitelist = mapOf("s1" to sentinel),
        shuffleTimeoutMs = 5000, inflightMax = 16, clockSkewMs = 30000,
        clockBack = "follow", clockBackLimitS = null, clockFail = "pause", clockReadMs = 1000,
        joinRetryInitialMs = 1000, joinRetryMaxMs = 60000)
    val node = TempusNode.start(config, me, NodeListener { n, event ->
        when (event) {
            is NodeEvent.OwnTokenInvalid -> { /* fetch a new token, then n.setToken(bytes) */ }
            is NodeEvent.KeyRotated -> { /* the producer has a new key: fetch a token under it, then n.setToken(bytes) */ }
            is NodeEvent.ClockUnreadable -> System.err.println(event.what)
            is NodeEvent.Stopped -> System.err.println(event.why)        // only a new node ends this
            is NodeEvent.ListenFailed -> System.err.println(event.why)
            is NodeEvent.ViewChanged -> {}
        }
    })
    Thread.currentThread().join()                                           // the node runs on its own threads
}
```

The numbers in the example are an example's; none of them is a default. Every parameter of `TempusConfig` must be
written, and the compiler refuses a call that leaves one out. `TempusNode.start` throws `ConfigRefused` and writes
the line `tempus: boot refused: WHY` when a value is outside its bounds or the identity does not fit; nothing is
started then. The node reads the machine's clock itself: no call passes it the time of day.

A running node takes three calls from its application. `setToken(bytes)` passes a new token; the application
refreshes its token at half the token's lifetime. `setProducerKey(kid, key)` passes a new producer key. `sample(store,
n)` gives up to `n` entries of one of the node's stores, drawn at random, which is how an application finds a
bridge to call. `close()` stops the node.

### The configuration

The parameters of `TempusConfig` are the keys of the `tempus` section of `bees.config` (design section 11) in camel
case, with the same meanings and the same bounds. A value outside its bounds is refused with the text
`tools/bees_tempus_conf.py` uses, without the file's name and line, which a value does not have.

| Parameter | Bounds | Meaning |
| --- | --- | --- |
| `role` | `edge`, `sentinel` (`bridge` is refused) | the node's own type, and the type its token must carry |
| `listenAddress`, `port` | an IPv4 literal or a host name; 1 to 65535 | where the node listens |
| `sentinels` | 1 to 16; empty only for a sentinel that is the first | each a host, a port, and the name of its certificate in `whitelist` |
| `edge`, `bridge`, `sentinel` | capacity 1 to 256; shuffle length 1 to 64 and at most the capacity; tick 100 to 3600000 ms | the three stores |
| `producerKid`, `producerKey` | 1 to 64 bytes; 32 bytes | the one current producer key |
| `whitelist` | | by name, the certificate of each bridge and sentinel the node accepts |
| `shuffleTimeoutMs` | 100 to 60000 | one bound for a whole connection, from the dial or the accept to the close |
| `inflightMax` | 1 to 64 | accepted connections at once |
| `clockSkewMs` | 0 to 300000 | the clock difference allowed when a token's time is judged |
| `clockBack` | `follow`, `hold`, `stop` | what a reading of the clock earlier than the node's time does |
| `clockBackLimitS` | 0 to 86400 under `stop`; `null` under the other two, where a number is refused | the greatest step back that `stop` still follows |
| `clockFail` | `continue`, `pause` | what a reading that fails after a good one does |
| `clockReadMs` | 100 to 60000 | how often the clock is read |
| `joinRetryInitialMs`, `joinRetryMaxMs` | 100 to 3600000, the second not below the first | the delays between attempts to join |

Four things differ from the section, and each is a choice the project owner has not ruled on.

- The keys `edge_spec`, `bridge_spec` and `sentinel_spec` are absent. They say what an admitted peer may call, and
  only a bridge serves calls.
- `identity_keyfile`, `identity_certfile`, `whitelist_file` and `whitelist_cert_dir` are not parameters: the
  application passes an `Identity` and the certificates themselves. The address the node advertises is the
  `Identity`'s, which the section does not name.
- A sentinel whose certificate name is not in `whitelist` is refused. The Silica tools do not check this.
- `clockSkewMs` is turned into the whole seconds the node compares tokens with by dividing by 1000 and dropping the
  rest. How the Silica side converts it is not built yet.

The Silica tool refuses a listen address other than `127.0.0.1`, `localhost` and `0.0.0.0` as not built yet. That is
a limit of the Silica carrier, not a rule, and the extension listens on any IPv4 address or host name the JDK binds.
The Silica node refuses an externally driven node on an address that is not loopback; the extension has no such
node, so it has no such refusal.

### What the application is told

The listener is called on the node's own thread, in order, and must return soon. It may call the node's methods.

| Event | When | The Silica node's message |
| --- | --- | --- |
| `OwnTokenInvalid(why)` | a tick found the node's own token not valid any more; ticking has stopped until `setToken` | 80 |
| `KeyRotated(kid)` | a peer answered the node's advert with `key_rotated` and named its current kid | 81 |
| `ClockUnreadable(what)` | the clock could not be read; told once for each failure, not once for each reading | 86 |
| `Stopped(why)` | the clock went back by more than `clockBackLimitS` under `stop`: the node admits nobody and does not tick, for good | 87 |
| `ListenFailed(why)` | the node could not listen on its address | none: the Silica node writes a line |
| `ViewChanged(store, entries)` | after each step that may have changed a store: a join's answer, a tick, an answered shuffle, an insert | none: a Silica test node writes a line |

One difference is deliberate. The Silica node tells its application of `key_rotated` only when the node itself
dialed; when the peer dialed, it writes the audit line and tells nobody. The extension tells its application in both
cases, because the design says that the node reports `key_rotated` to its application.

The node writes the Silica node's lines, word for word: the boot lines, the `join:`, `tick` and `clock:` lines, and
one `[tempus audit]` line for each admission, refusal and close. They go to the standard output, or to the function
given to `NodeEnvironment.system(log)`.

### How it is built inside

All of the node's state belongs to one thread, the node thread: the three stores, the clock state, the node's token
and producer key, the counts of connections, the join. Everything else sends that thread a message: the timers, the
clock reader, the acceptor, each connection and the application's calls. Each connection runs on a virtual thread of
its own with a copy of the values it needs, taken on the node thread when the connection begins; it does the TLS
handshake and the admission, hands an admitted peer's request to the node thread and waits for the answer. No store
is ever touched by two threads, and there is no lock around one.

The clock, the timers and the draws come from a `NodeEnvironment`. `NodeEnvironment.system()` is the machine's
clock, real timers and the platform's secure random source (seven bytes for each draw), and it is the default: an
application passes nothing. A test passes its own clock, timers and draws through the same constructor. That is the
only way a test drives a node. No frame a peer can send sets the clock or causes a tick.

## What a node does, against the design

- The stores (design section 3): capacity, ages to 65535, the oldest entry as partner with a draw to settle a tie,
  the buffer with the node's own entry only in the store of its own type (OQ-5), the merge that prefers the younger
  entry also against an entry just sent (NQ-16), the partner put back at age 0 in a store of another type (NQ-15),
  sent entries put back after a failed shuffle and into what room a merge leaves (OQ-12).
- Joining (section 6): one `sample` for each store to a configured sentinel, the next sentinel when one does not
  answer, retries with a delay that doubles from `joinRetryInitialMs` to `joinRetryMaxMs`, the sentinel kept in the
  node's sentinel store (NQ-12), the request that waits while the clock is paused (ruling 1.d), and a sentinel asked
  again when a tick finds a view empty. A sentinel inserts every peer that samples it, after the sample (NQ-13).
- Shuffles: each store on its own timer, entries whose token has expired dropped before each tick, one connection
  with one deadline (NQ-14), a tick during a shuffle in flight only ages, a failed partner dropped.
- Admission (section 4): the channel binding, the token's structure, kid, time with the skew, `sub`, the tempus
  whitelist rule in both directions (NQ-4), the id hash, the producer's signature, the proof of possession in both
  directions, `key_rotated` with the wait that keeps the frame from a reset, and every entry of a received frame
  verified without contact. The events and the reasons are the Silica node's.
- Limits (section 8): the frame ceiling judged from the length alone, the entry count against the store's shuffle
  length, `inflightMax` with the connection beyond it closed after its handshake (`inflight_refused`), one bound for
  a connection, and the closes `clock_refused` and `clock_stopped`.
- The clock (sections 4 and 10): seconds since 1970 UTC from the machine's clock, read at start and every
  `clockReadMs`; no listening before the first reading; `follow`, `hold`, `stop` with its limit; `continue`, `pause`.
- A node whose own token has expired stops ticking, tells its application and goes on answering (NQ-17).

Not done, because only a bridge does it: the score of a peer (NQ-19, NQ-23). The Silica connection actor tells its
node of each refusal of an accepted peer, and every node that is not a bridge drops that message. The extension
sends no such message.

## What a node does not cover

- The bridge role. A bridge needs a TRUST implementation in Kotlin (mutual TLS 1.3 with pins and the TRUST whitelist,
  the reconnect token, TRUST's frames and its client), a second identity with its own key, the table of exported
  functions with the forbidden guard and the permission spec for each peer type, the table of scores for each peer
  with its bounds from the application, and the hand-over of each admitted call to the application (design section
  17). None of it exists here.
- The text of a refusal of a malformed frame is the Silica node's for every case the trials show. For other
  malformed frames the verdict is the same and the words may differ, because the Silica reader's words come from the
  Silica language's own decoder.
- A node dials a gossiped address only when it is an IPv4 literal and a port, as the Silica node does. Sentinels may
  be named by host name.
- One refusal of the TLS handshake is worded differently from the Silica node's. A peer whose certificate has a key
  that is not Ed25519 is reported as presenting no certificate (`tls_verify_failed`), where the Silica node says
  `tempus_cert_key`: such a peer's TLS library sends no certificate when the node offers the signature scheme
  ed25519 alone, so the node never sees the key.
- A node says `not a request: unknown_atom` of a frame that names an atom outside `tempus/1` and TRUST's frames, as
  a Silica program built without the test unit does. A Silica program that holds more atoms says `unknown kind` of
  some of those frames.

## What the client checks

On the TLS connection, for both directions: TLS 1.3 only; the group X25519MLKEM768 only; the cipher suites
TLS_AES_256_GCM_SHA384 and TLS_CHACHA20_POLY1305_SHA256 only; the signature scheme ed25519 only; the application
protocol `tempus/1`; a certificate from the peer, whose key is Ed25519 and which is signed by its own key with issuer
equal to subject. No certificate authority is consulted and the certificate's dates are not checked, as the design
rules.

On the peer's advert, in the node's order: the bounds of every field; the binding (the advert's `pub` is the key of the
certificate the peer presented); the token's `kid` (a token under another `kid` is answered with the one `key_rotated`
frame); the time; `sub`; the whitelist rule in both directions; the identifier as the SHA-512 of the key; the
producer's signature over the token's payload bytes as they were received. Then the proof of possession.

On a reply: it is the reply the request calls for; it names the store of the request; a sample's reply holds no more
entries than were asked for; every entry verifies for that store. One entry that does not verify refuses the whole
reply. A `result` must carry the `req_id` of the call.

As a listener: the same admission, then one request. A `shuffle` is given to the application's handler only when its
every entry verifies. A `sample` and a `shuffle` are answered for the same store. Anything else is closed with no reply.

One time bound covers a whole connection. A frame above 131072 bytes is refused from its length alone. When the client
closes a connection it first ends its own sending, then reads until the peer has closed or half a second has passed,
so that a frame it has just sent (a `key_rotated`, a reply) is not lost.

## What the client was checked against

Everything below was run on one machine: macOS on Apple Silicon, with the versions named above. Nothing was run on
Linux.

`make test` runs 41 tests of the frames and of single connections (`test/TestMain.kt`):

- The frames golden of `trials/t2_tempus_frames`. That trial prints every frame and token the Silica frame unit writes
  or deliberately breaks, as hex, with what the Silica reader made of each. The Kotlin client builds the 27 frames and
  tokens that concern a client from the same inputs and gets the same bytes, and it reads every recorded frame and
  gives the same verdict. The test frames `tick` and `clock` and their answer `done` are checked to be refused.
- The codec by itself: round trips, the order of map keys, the integer forms, the reader's refusals.
- The TEST ONLY identities of `tools/bees_tempus_ids.py`: the public key, identifier and certificate fingerprint of the
  eight test certificates, and the 112 test tokens, signed here from the same seeds and compared byte for byte.
  Ed25519 signatures are deterministic, so the bytes must be the same.
- The 20 admission cases of `trials/t4_tempus_admission`, with the verdict and the reason the Silica node gave for each.
- The channel binding and the whitelist rule.
- The client against itself over real mutual TLS 1.3 on 127.0.0.1: admission both ways, each request, each cause of
  refusal, `key_rotated` in both directions, replies that must be refused, a peer nobody listens for and a peer that
  never answers.

`make test` then runs the 10 tests of the gossip part (`test/GossipTest.kt`): the view rules and the store's steps on
cases worked by hand, and a sentinel and two edges of this library in one process over TLS on 127.0.0.1, where each
edge must come to hold the other.

The trial `trials/c7_tempus_gossip` runs four instances of the driver as one network, and one instance in a network
with the Silica, Python and Swift drivers. Both were run and their checks are recorded.

The trial `trials/c6_tempus_kotlin` runs the first 41 tests and then walks the client against real BEES TEMPUS nodes:

- A test node joins through the Kotlin client, which listens as a sentinel. The client samples and shuffles as a
  sentinel and as an edge, is dialed by the node for a shuffle, and sees what it answered in the node's stores.
- The node refuses the client for each reason a token can be wrong, and for requests that break a bound. The client
  sees the close and nothing else; the node's own output, which is recorded, says why.
- The client refuses the node when the client's clock says the node's token has expired or is not valid yet, when the
  client holds another producer key as current, and when the whitelist rule is broken.
- The client meets a peer that misbehaves on purpose, in both positions. That peer is the Python example client,
  which can do so. This covers the channel binding, a wrong or missing proof of possession, `key_rotated` each way,
  forged entries, replies that are not what was asked for, oversize frames, silence, and wrong certificates and TLS
  settings.
- A node that is not a test node and reads the machine's clock, met by the client reading the machine's clock too.
- The command line, dialing and listening.

Run it from the BEES root directory with `tools/run_all_trials.sh --local-only --only c6_tempus_kotlin`.

## What the node was checked against

`make test` also runs the node tests (`test/NodeTestMain.kt`), 24 of them:

- the view and the store: 20623 calls of view functions and 6006 store steps, which are the calls the two
  independent Python models (`tools/bees_tempus_view_model.py`, `tools/bees_tempus_store_model.py`) make to compute
  every line of the goldens of `trials/t0_tempus_view` and `trials/t1_tempus_store`, and 9508 more on generated
  views and stores; each is made again in Kotlin and must give the model's answer;
- the clock: every line of the golden of `trials/t0_tempus_clock` computed again;
- the configuration: the refusals of `tools/test_bees_tempus_conf.py` that a value can show, with their words, and
  five start refusals of `trials/c4_tempus_boot` with the Silica node's line (the sixth, an externally driven node
  on an address that is not loopback, has no counterpart);
- the node's judgement of an entry on the cases of `trials/t4_tempus_admission`, verdict and reason.

The trial `trials/c9_tempus_node_kotlin` runs nodes of the extension and Silica nodes in one network on the Mac. It
shows a Kotlin edge joining through a Silica sentinel and a Silica edge joining through a Kotlin sentinel; shuffles
started by each side and answered by the other, in the store of the node's own type and in stores of another type,
with each side's entries in the other's store; a partner that is not there; a good peer and 25 kinds of bad peer
sent to a Silica node and to a Kotlin node, with the audit lines required to be the same, and the inflight limit and
three refusals of the TLS handshake in the same way; a fourth refusal of the handshake that the two word differently; the clock's choices on Kotlin nodes whose clock the trial sets (the hold beginning and ending,
going on with the last reading, the pause with `clock_refused` and the join that waits, the step back that is
followed and the stop with `clock_stopped`); the node's own token expiring and being replaced; `key_rotated` told to
the application; and a Kotlin node that is not a test node, on the machine's clock and its own timers, through
which a Silica node that is not a test node joins, both refusing the `tick` and `clock` frames. It has recorded
output for the Mac only. There is no Kotlin compiler on the Linux machines, so the trial is declared for the Mac in
`trials/c9_tempus_node_kotlin/platforms`, and the trial runner reports it as not applicable on Linux.

Not shown by any test or trial: a clock that cannot be read at start; the retry delay of a join doubling over real
time; a tick that finds a view empty and asks a sentinel again; a listen address that cannot be bound; many
connections at once beyond the inflight test; and a node that runs for longer than a trial.

## What stands between this and production use

- No review as production code, by anyone.
- No test under load, no long run, no measurement of memory, and no test on Linux or on another JDK than OpenJDK
  27.0.1.1.
- Every key, certificate and token it was run with is a test fixture.
- A connection whose peer never closes holds its thread until the connection's bound; a node that is closed leaves
  connections in hand to end by that bound.
- The four choices listed under "The configuration", and the difference in what the application is told of
  `key_rotated`, are not ruled.
- Two gossip implementations stand side by side, and which is kept is not decided.
- The bridge role is absent.

## What the client does not cover

- It was not run against a real bridge. `call`, `cast` and `result` were checked in three ways only: the request
  bytes are the bytes the Python example writes (which `trials/c3_tempus_bridge` runs against real bridges); a real
  node that is not a bridge was never sent one, because the client sends a call or a cast only to a peer admitted with
  a bridge token; and the Python example, holding a bridge token, answered a call and a cast.
- The arguments of a call on the command line are integers only. In code they may be any term of the codec's subset.
- The value of a `result` is read only when it is made of integers, atoms, binaries, lists and maps with atom keys. A
  value that holds a tuple, a float or anything else is refused; the outcome still carries the reply's bytes.
- The JDK has no call that reports which key exchange group a handshake used. The client offers one group only, and
  the node's own output shows the group, so the trial shows it; the client cannot check it by itself.
- It does not make keys, certificates or tokens, and does not fetch or refresh a token. `Peer.newToken` takes a new
  token from the application.
- A `Peer` does not serve `call` or `cast`, keeps no score of peers and has no limit on accepted connections. Its
  clock is the function the application gives the `Verifier`; it has none of a node's rules for a clock that fails
  or goes back. `TempusNode` has those rules and that limit.
- The gossip part was run only on one machine, with test keys, for a few seconds at a time. It was not run for a long
  time, with expiring tokens, with peers that stop, or against the limits of its stores.
- The private key is read from an unencrypted file and held in memory by the JDK. Nothing is done to protect it.
- The trial does not drive the node behaviours that only test frames or timing can reach (the connection limit, the
  node's clock moving, a node's token being replaced). The Python example drives those in `trials/c2_tempus_clients`
  and `trials/t6_tempus_clock`.
- There is no recorded output for Linux, because the Kotlin compiler is not installed on the project's Linux
  machines. The trials are declared for the Mac in their `platforms` files, and the trial runner reports them as not
  applicable on Linux. Run by hand on a machine without the compiler, a trial fails and says that the compiler is
  missing; it does not skip.
