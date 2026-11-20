# Swift example TEMPUS client

This client is an example only. It must not be used in production.

It is a worked example, in Swift, of what a TEMPUS client has to do: connect to a TEMPUS node as an ordinary peer over
mutual TLS 1.3, be admitted, make one request and read the answer, and answer a node that dials it. If you need a
TEMPUS client in a Swift application, write it as part of that application and read this one as an example. The
document [What do I need to do to write a TEMPUS client?](../writing-a-tempus-client.md) lists the requirements in a
form that does not depend on any example. The reasons in [the directory's README](../README.md) for not using an
example in production apply here as they are: the keys, certificates and tokens it is run with in this repository are
test fixtures made from fixed seeds that anyone can reproduce, and the code has had no review as production code.

The client was written from the design document and from the requirements document, with the Python example as the
reference for behaviour on the wire. It shares no code with the Python example, the Silica example or the node.

## What is in this directory

- `Package.swift` describes a Swift package with no remote dependency.
- `Sources/TempusClient/` is the library.
  - `ETF.swift` writes and reads the part of the Erlang external term format that TEMPUS uses.
  - `Frames.swift` writes and reads the frames and the token, and checks every bound on their fields.
  - `Crypto.swift` holds Ed25519 signatures, SHA-512 and the certificate functions.
  - `Admission.swift` holds an identity, the verifier that checks another peer, and the outcome of a connection.
  - `Connection.swift` holds the TLS connection, the order of a connection, and `dial`.
  - `Listener.swift` holds the listening position: a node dials the client, and the client answers one request.
  - `Fixtures.swift` makes test tokens and test identities from fixed seeds. It is for tests only.
- `Sources/tempus-client/` is a command line over the library.
- `Sources/tempus-client-tests/` is the unit tests, as a plain program.
- `Sources/COpenSSL/` is a module map that names the headers and libraries of the OpenSSL installed on the machine.
  It contains declarations only. There is no C code in this directory.
- `Makefile` builds the package and runs the unit tests.

## What you need

- Apple's Command Line Tools, which provide `swiftc` and the Swift Package Manager. Xcode is not needed. The client was
  built with Swift 6.3.3 for `arm64-apple-macosx26.0`.
- An installed OpenSSL that offers the key exchange group X25519MLKEM768 and Ed25519. The client was built and run
  with the OpenSSL 4.1.0 that Homebrew installs, which is the one the BEES Makefiles use. The Makefile finds it the way
  they do, through `native/macos/platform.mk`, or takes the directory from `OPENSSL_PREFIX`.

Nothing is downloaded. The package has no dependency that the package manager would fetch.

## How to build and run it

From this directory:

- `make build` builds the library, `tempus-client` and `tempus-client-tests` into `.build/debug/`.
- `make test` builds and then runs the unit tests. They need the recorded output of the trial
  `trials/t2_tempus_frames` and the test certificates in `trials/t5_tempus_tls/certs`.
- `make clean` removes `.build/`.

The Makefile calls `swift build --disable-sandbox` with the place of OpenSSL's headers and libraries. The package
manager's own sandbox cannot start inside another sandbox, and this package has no plugin and no dependency for it to
guard.

The command line, with its test fixtures, looks like this. `SEED` is 64 hexadecimal digits and `PUB` is the
producer's public key as 64 hexadecimal digits.

```
.build/debug/tempus-client dial 127.0.0.1:24700 \
    --seed SEED --addr 127.0.0.1:24703 --test-token tempus_edge:1000:3000 \
    --producer-pub PUB --kid k1 --now 1500 --skew 10 --timeout 5 --shuffle-length 3 \
    sample tempus_edge 3
```

It prints one line that says what happened, for example
`reply sample_reply entries=[1:9200d2990c3e9eb7] store=tempus_edge peer=b19edad2958934e1 typ=tempus_edge`. The line has
the same form as the Python example's line.

- The requests are `sample STORE N`, `shuffle STORE` (the client's own entry at age 0), `call MODULE FUNCTION
  [INTEGER...]`, `cast MODULE FUNCTION [INTEGER...]` and `raw HEX` (any body, given as bytes).
- `listen HOST:PORT` with the same options accepts connections until its standard input ends. It answers a sample or
  a shuffle with the entries given by `--test-entry`, and anything else with a close.
- The time for token checks is either `--now SECONDS` or `--system-clock`. One of the two must be given.
- `--token HEX` gives the client's token as the producer issued it. `--test-token TYP:NBF:EXP` signs one with the test
  producer key, whose seed is written in this repository. That option is for tests only.
- `--cert FILE` gives the client's certificate as a PEM file. Without it the client makes a certificate that is
  self-signed over its own key.
- `--whitelist-cert FILE`, which may be given more than once, turns on the whitelist rule described below.
- The skew, the time bound and the shuffle length must always be given. TEMPUS has no default for any of them.

## Which libraries it uses, and why

The client uses Foundation, the system's POSIX calls for the TCP connection, and OpenSSL for TLS, Ed25519, SHA-512 and
certificates. It does not use Network.framework, Security.framework or CryptoKit. Each of those was tried first, and
each cannot do something the protocol requires.

- Network.framework cannot complete a handshake with a TEMPUS node. A node presents a certificate whose key is
  Ed25519, so the handshake must be signed with Ed25519. The list of signature algorithms that Network.framework
  offers on this system does not contain Ed25519 (code 0x0807). The list it sent, captured from its first handshake
  message, was 0x0403, 0x0804, 0x0401, 0x0503, 0x0805, 0x0501, 0x0806, 0x0601 and 0x0201. An OpenSSL server holding a
  test TEMPUS certificate answered that offer with the error "no suitable signature algorithm". The public interface
  of Network.framework has no call that changes the list. Network.framework does offer the key exchange group
  X25519MLKEM768 (code 0x11ec), so the group was not the obstacle.
- Security.framework did not load the client's own identity in the attempts made. Importing an Ed25519 key and
  certificate with `SecPKCS12Import` failed with the status -26275 ("Unable to decode the provided data"), for a file
  written by OpenSSL in its present form and for one in its older form. One attempt to make an Ed25519 private key
  with `SecKeyCreateWithData` also failed; that attempt does not prove it cannot be done. Without an identity the
  client cannot present its certificate, and TEMPUS requires both sides to present one. This was not pursued further,
  because the signature algorithms above already rule Network.framework out.
- CryptoKit can sign with Ed25519, but its signatures are randomized: signing the same message twice with the same
  key gave two different signatures. Such signatures are valid, but tokens and proofs made with them cannot be
  compared byte for byte with the ones the Python example and the trials make. OpenSSL's Ed25519 gives the same bytes
  on every call.

OpenSSL can do all of it, and it is the library the BEES node itself uses for TLS, so the client offers exactly what
the node requires: TLS 1.3 only, the group X25519MLKEM768 only, the cipher suites TLS_AES_256_GCM_SHA384 and
TLS_CHACHA20_POLY1305_SHA256, the signature algorithm Ed25519 only, and the protocol name `tempus/1`.

Several OpenSSL settings are C macros, which Swift cannot call. The client calls the function each macro stands for,
`SSL_CTX_ctrl`, with the same arguments. That is why no C code was needed.

## What it covers, compared with the Python example

| Subject | Python example | Swift example |
| --- | --- | --- |
| Frames: advert, challenge, response, key_rotated, shuffle, shuffle reply, sample, sample reply, done | writes and reads all | writes and reads all, with the same bytes |
| TRUST's call, cast and result frames | writes call and cast with integer arguments, reads a result | the same, and it refuses to write a request identifier outside 1 to 16 bytes |
| The test-only tick and clock frames | writes and reads them, because the trials drive nodes with them | not implemented. The strict reader refuses both as a frame of no kind, as the library does |
| Bounds on every field, unknown, missing and repeated keys, nesting depth, the frame ceiling | checked | checked, with the same reasons |
| Token: structure, bounds, kid, time window with skew, sub, id, the producer's signature | checked | checked, in the same order and with the same reasons |
| Channel binding: the key of the peer's TLS certificate is the advert's pub | checked | checked |
| Proof of possession, both ways | made and verified | made and verified |
| The peer's certificate: Ed25519 key, issuer equal to subject, signature verifying under its own key | checked when dialing and when listening | checked when dialing and when listening |
| key_rotated: sent when the peer's token is under another kid, and read when the peer sends it | both | both |
| Dialing: admission, one request, one reply | yes | yes |
| Listening: admission, one request, one answer | yes, for peers whose certificates it was given in advance | yes, for any peer. OpenSSL lets the client accept a self-signed certificate it was not given, and admission decides |
| Closing so that the last frame arrives: TLS close, end of writing, a short read, then close | yes | yes |
| One time bound for a whole connection | yes | yes |
| The outcome of a connection as one line | yes | yes, in the same form |
| Making its own self-signed certificate | yes | yes. With the names, serial numbers and dates of `tools/bees_tempus_certs.py` it makes the same bytes |
| Deliberate misbehaviour (wrong proofs, wrong frames, silence, oversize frames, other TLS settings) | yes, because the trials need it | no. A client has no use for it |

## What it does that the Python example does not

- It verifies every entry of a reply before it reports the reply. One entry that does not verify refuses the whole
  frame, and the outcome says so. A listening client does the same to the entries of a shuffle it receives. The
  Python example reports the reply and leaves the entries to its caller. The option `verifyEntries` of `dial` and of
  `Listener`, and `--no-entry-check` on the command line, give the Python example's behaviour.
- It can apply the whitelist rule of the design: a peer whose token says `tempus_bridge` or `tempus_sentinel` must
  present a certificate that the client holds in its list. The rule is applied only when a list is given. Without
  one the client behaves as the Python example does and does not apply the rule.
- It names the key exchange group, the cipher suites and the signature algorithm it offers. The Python example relies
  on what its TLS library offers by default.
- It checks after the handshake that the TLS version is 1.3.

## What it was checked against

The unit tests (`make test`, which prints how many checks passed) compare the client with recorded bytes:

- every frame and token of the trial `trials/t2_tempus_frames`, built here from the same inputs, must be the same
  bytes, and every recorded frame, good or bad, must get the verdict the Silica library gave it;
- a token and a proof of possession made here with the test keys must be the bytes the Python example made
  (`native/tempus/selftest/vectors.h`);
- Ed25519 must give the signature of RFC 8032, section 7.1, test 1;
- the certificates made here must be the files of `tools/bees_tempus_certs.py`, byte for byte;
- call, cast and result frames and a set of integers must be the bytes the Python example writes;
- the client is run against itself over mutual TLS 1.3 on the loopback address: every request, each cause of
  refusal that a token can carry, key_rotated both ways, the whitelist rule, bad replies, a close, silence, several
  connections in order, and an address where nothing listens.

The trial `trials/c5_tempus_swift` runs the command line against real nodes on this machine, and against the Python
example. `tools/bees_tempus_swift_trial.py` walks the steps and checks each result, and the client's lines are
compared with a recorded golden.

- Node N is a test node whose clock is fixed. It joins through the Swift client listening as its sentinel. The Swift
  client then samples it, shuffles with it, and is dialed by it for a shuffle. The client sees the node refuse an
  expired token, a token that is not valid yet, a token another key signed, a sample above the shuffle length, an
  entry of the wrong store, and a call and a cast (the node is not a bridge). It reads the node's `key_rotated`
  frame, and it refuses the node itself when its own clock is past the node's token and when it holds another
  producer kid.
- Node P reads the system clock, and so does the Swift client there. P joins through a second Swift listener, and the
  client samples it and shuffles with it. P refuses a token that has expired by the system clock and one that is not
  valid yet.
- Against the Python example, with no node, each client dials the other. The Python example checks that the Swift
  client's sample, shuffle, call and cast are the bytes it would write itself. The Python example then misbehaves on
  purpose, so that the Swift client's own refusals are seen: another peer's advert (the channel binding), wrong
  proofs, a missing proof, wrong and oversize frames, forged entries, expired and old tokens, and other TLS settings.

The ticks that make node N shuffle are test-only frames. The Swift client does not send them; the trial tool sends
them through the Python example.

Run the trial from the BEES root directory with `tools/run_all_trials.sh --local-only --only c5_tempus_swift`, or with
`make -C trials/c5_tempus_swift integrate`.

## What it does not cover

- It was not run against a bridge. The call, cast and result frames were checked against the Python example's bytes
  and against a node that is not a bridge, which refuses them. The trial with real bridges, `trials/c3_tempus_bridge`,
  is driven by the Python and Silica examples only.
- Its reader of TRUST's result frame understands the same subset as the Python example's: maps, atoms, binaries,
  integers and lists. A result that carries a tuple or a float is refused, and its bytes are still in the outcome.
- It keeps integers in 64 signed bits. The Python example reads an integer of up to 64 bits of magnitude. No number in
  a TEMPUS frame comes near either limit.
- It was built and run on macOS on Apple Silicon only. There is no Swift toolchain on the Linux machine the other
  trials also run on, so the trial has Mac goldens only, and on a machine without Swift it reports that it was
  skipped.
- It keeps no stores of its own and runs no shuffle timer. It makes one request per run, or answers requests with
  entries it was given. It does not refresh its token, and it does not take part in gossip by itself.
- A failed TLS handshake is reported with the text OpenSSL gives for it. That text belongs to the OpenSSL version, so
  the trial leaves it out of its golden.
- The whitelist rule is one-sided here: it is the edge's rule. The rule a bridge or sentinel applies to its own kind
  is the node's, and is not in this client.
- It was not checked for the time its operations take, for memory use, or under load.
