# The Kotlin example TEMPUS client

This client is an example only. It must not be used in production.

It has had no review as production code, nothing in it is promised to stay the same, and everything it was checked
with uses keys, certificates and tokens made from fixed seeds that are written in this repository. If you need a
TEMPUS client in a Kotlin or Java application, write it as part of that application and read this one as a worked
example. The document [What do I need to do to write a TEMPUS client?](../writing-a-tempus-client.md) lists what such
a client has to do, in a form that does not depend on any one language.

## What it is

It is a TEMPUS peer written in Kotlin for the Java virtual machine. It uses nothing but the Kotlin standard library
and the JDK: the JDK's own TLS for the connection, and the JDK's own Ed25519 and SHA-512. It has its own writer and
reader for the frames, written from the document named above and from the ruled design
(`development-plan/tempus-design.md`), not from the Python or the Silica code.

It can dial a node and it can listen for a node to dial it. On every connection it does the whole admission: its
advert, the check of the peer's advert and token, the binding of the advert to the peer's TLS certificate, the tempus
whitelist rule, the challenge, its own proof of possession and the check of the peer's. It makes every request a
client can make (`sample`, `shuffle`, and `call` and `cast` to a bridge), reads every reply, and verifies every entry
of a reply before it reports the reply as good.

It does not contain the two test-only frames, `tick` and `clock`, or their answer, `done`. To this client they are
frames of no kind, and it refuses them.

The files:

- `src/Etf.kt` writes and reads the part of the Erlang external term format that the frames use.
- `src/Frames.kt` holds the messages, with every bound on their fields, and the structure of a token.
- `src/Admission.kt` holds the identity (key, certificate, token, listen address) and the verifier (the checks of a
  peer and of an entry).
- `src/Client.kt` holds the TLS setup, `dial`, `Listener`, and `Outcome`, the plain value that says what happened on
  a connection.
- `src/Main.kt` is the command line.
- `test/TestMain.kt` holds the tests. They are run by a plain `main` function, so no test library is needed.
- `test/Fixtures.kt` is for the tests and the trial only. It makes tokens from the test producer's fixed seed. A client
  never makes or signs a token, and nothing under `src` does.

## What must be installed

Two things, and nothing else. No build tool such as Gradle or Maven is used, and no library is downloaded.

1. The Kotlin compiler, `kotlinc`. Version 2.4.21 was used, installed with Homebrew: `brew install kotlin`.
2. A JDK whose TLS can offer the key exchange group X25519MLKEM768, which a TEMPUS node requires. OpenJDK 27.0.1.1
   was used. Homebrew installs it as a dependency of `kotlin`, at `/opt/homebrew/opt/openjdk`; it can also be
   installed by itself with `brew install openjdk`. OpenJDK 25.0.2 was tried and cannot be used: its TLS does not have
   that group, so it cannot complete a handshake with a TEMPUS node. The tests stop with a message that says so when
   they are run on such a runtime.

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
make build     # writes build/bees-tempus-client.jar
make test      # compiles the tests with the client and runs them
make clean
```

`make build` runs `kotlinc -nowarn -include-runtime -d build/bees-tempus-client.jar src/*.kt`. The file it writes holds
the client and the Kotlin runtime, so `java -jar` runs it.

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

From Kotlin code, the entry points are `Identity.load`, `Verifier`, `Settings`, `dial` and `Listener`. The trial's
`Walk.kt` uses them the way an application would.

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

## What it was checked against

Everything below was run on one machine: macOS on Apple Silicon, with the versions named above. Nothing was run on
Linux.

`make test` runs 36 tests:

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

The trial `trials/c6_tempus_kotlin` runs those tests and then walks the client against real BEES TEMPUS nodes:

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

## What it does not cover

- It was not run against a real bridge. `call`, `cast` and `result` were checked in three ways only: the request
  bytes are the bytes the Python example writes (which `trials/c3_tempus_bridge` runs against real bridges); a real
  node that is not a bridge was never sent one, because the client sends a call or a cast only to a peer admitted with
  a bridge token; and the Python example, holding a bridge token, answered a call and a cast.
- The arguments of a call on the command line are integers only. In code they may be any term of the codec's subset.
- The value of a `result` is read only when it is made of integers, atoms, binaries, lists and maps with atom keys. A
  value that holds a tuple, a float or anything else is refused; the outcome still carries the reply's bytes.
- The JDK has no call that reports which key exchange group a handshake used. The client offers one group only, and
  the node's own output shows the group, so the trial shows it; the client cannot check it by itself.
- It does not make keys, certificates or tokens, does not fetch or refresh a token, and keeps no store of entries.
  Joining a network, keeping the three stores and shuffling on a timer are left to the application.
- The private key is read from an unencrypted file and held in memory by the JDK. Nothing is done to protect it.
- The trial does not drive the node behaviours that only test frames or timing can reach (the connection limit, the
  node's clock moving, a node's token being replaced). The Python example drives those in `trials/c2_tempus_clients`
  and `trials/t6_tempus_clock`.
- There is no recorded output for Linux, because the Kotlin compiler is not installed on the project's Linux machine.
  There the trial fails and says that the compiler is missing; it does not skip.
