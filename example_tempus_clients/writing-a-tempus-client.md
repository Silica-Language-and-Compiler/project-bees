# What do I need to do to write a TEMPUS client?

This document is for a programmer who needs a TEMPUS client in an application, in any language. It says what the
client has to do on the wire. It was derived from the ruled design, `development-plan/tempus-design.md`, and each
statement was checked against the code of the BEES TEMPUS node (`src/tempus/`) and of the two example clients in this
directory. Section numbers below, such as "design section 5", refer to that design document. Where something could
not be checked against the code, section 14 says so.

The clients in this directory are examples only and must not be used in production. See [README.md](README.md). An
application that is to be a member of the network, with stores of its own, is a node: see [What do I need to do to
write a TEMPUS node?](writing-a-tempus-node.md).

Two names for Python code appear below. `python/` holds two bodies of code, kept side by side until the project owner
decides between them (`python/README.md`). "The Python extension" means the modules `python/lib/bees_tempus_*.py`.
"The Python example" means the code both bodies share by descent from the first Python client, which is also in the
package `python/lib/tempus_client`. A statement about the Python extension was checked against those modules only.

## 1. The terms used here

- A node is a program that is a member of a TEMPUS network. It listens for connections, keeps lists of other members,
  and exchanges parts of those lists with other members.
- A peer is the program at the other end of a connection. To a node, your client is a peer.
- A client is a peer that connects to a node to make a request. There is no separate client protocol. A client is an
  ordinary TEMPUS peer, and the node treats it exactly as it treats another node.
- The producer is the party that decides who may be a member. It signs tokens. BEES does not talk to the producer;
  getting a token from it is your application's job.
- A token is a short signed statement from the producer that a given public key may be a member, of a given type,
  between two times.
- A peer type is one of `tempus_edge`, `tempus_bridge` and `tempus_sentinel`. An edge is an ordinary member. A bridge
  is a node that is also a member of a TRUST network (TRUST is the other mode of BEES, for long-lived nodes that know
  each other in advance) and can run functions on behalf of edges. A sentinel is a node whose address is known in
  advance, which new nodes contact first.
- A store is one of the three lists of members a node keeps, one per peer type. A request that concerns a store
  names it by the peer type.
- A descriptor is the record that describes one peer: its identifier, its public key, its address and its token.
- An advert is the first message each side sends on a connection. It carries the sender's descriptor.
- Admission is the set of checks each side makes on the other before any request is read.
- A shuffle is the exchange in which two peers trade some entries of one store.
- ETF is the Erlang external term format, the binary encoding of Erlang terms. Every TEMPUS message is one ETF map.
- A frame is one message as it travels: a length followed by the message bytes.
- An audit line is a line a node writes to its own output when it refuses something. It is never sent to the peer.

## 2. What your client must have before it connects

1. An Ed25519 key pair. This is the client's TEMPUS identity. The public key is 32 bytes.
2. Its peer identifier: the SHA-512 hash of the 32-byte public key, which is 64 bytes.
3. A certificate for TLS that is self-signed over that same Ed25519 key. The node compares the key in the certificate
   your client presents with the public key in your client's advert, and refuses the connection when they differ.
4. A token from the producer for that public key (section 5 below gives its layout). Your client does not make or
   sign tokens. It carries the token bytes exactly as the producer gave them.
5. The producer's current public key and its key identifier, called `kid`, so that your client can check the node's
   token.
6. A listen address, as the text `host:port`. Every TEMPUS peer advertises one. A node that learns of your client
   through gossip will dial that address, so a client that takes part in shuffles should listen there. Section 9
   says what a client that listens must do.
7. If your client will talk to bridges or sentinels: the list of their TEMPUS certificates that your application
   accepts. This list is called the `tempus` whitelist. The design requires an edge to check that a peer claiming to be
   a bridge or a sentinel presents a certificate from that list. The list names a certificate by the SHA-512 hash of
   the certificate's DER bytes, 64 bytes. It names a certificate, not a key: a new certificate over the same key is
   another entry.
8. A source of the current time in whole seconds since 1970 UTC, for checking tokens, and a source of secure random
   bytes.

## 3. Transport and TLS

A connection is TCP with TLS on top. The node accepts a handshake only when all of the following hold. The node's code
checks each of them after the handshake and closes the connection otherwise.

- The TLS version is 1.3. No other version is offered or accepted.
- The key exchange group is X25519MLKEM768. The node offers and accepts no other group on TEMPUS connections. Your TLS
  library must be able to offer it. Python's `ssl` module cannot name the groups it offers before Python 3.15, and it
  offers X25519MLKEM768 by default when it is built over OpenSSL 3.5 or later. The Python extension reads the group
  the handshake chose and refuses a connection that chose another.
- The cipher suite is TLS_AES_256_GCM_SHA384 or TLS_CHACHA20_POLY1305_SHA256.
- The application protocol, negotiated by ALPN, is `tempus/1`.
- Both sides present a certificate. This is mutual TLS: the node requires your client's certificate, and your client
  must require the node's.
- The key of the certificate is an Ed25519 key.

The node does not check the certificate against any certificate authority, and it does not check the certificate's
validity dates. The token carries the validity period instead. Your client must do the same: it cannot verify the
node's certificate against an authority, because the certificate is self-signed. What your client must do is read the
public key out of the certificate the node presented and keep it for the binding check in section 6.

## 4. Frames and encoding

Every message is one frame: a length of 4 bytes, most significant byte first, followed by that many bytes of message
body. The body is one ETF term, a map, beginning with the version byte 131.

The body may be at most 131072 bytes. The node refuses a longer frame from its length alone, before it reads the body.

Every map has a key `t`, an atom that names the message. A map may hold only the keys listed for its message; the node
refuses a map with an unknown key, a missing key or a key that appears twice. The body must be exactly one term with no
bytes after it. Maps and lists may be nested at most as deep as the messages below need.

Every atom in a frame must be one the node holds: the key names and the closed sets of this section. The node refuses
a frame that names any other atom before it looks at the frame's kind. (Which atoms a bridge holds for the `m` and
`f` of a `call` was not checked for this document.) In the other direction, your client's reader must refuse, and not
fail on, anything a peer can send: a length that runs past the frame, an atom whose name is not valid UTF-8, a term
of a kind it does not read.

Write the ETF the way both examples write it, which gives every message exactly one byte form:

- a map as tag 116, with its keys in the byte order of their names;
- an atom as tag 119 (a small UTF-8 atom);
- a byte string as tag 109 (a binary);
- an integer from 0 to 255 as tag 97, a larger integer that fits in 32 bits as tag 98;
- a list that is not empty as tag 108 ending in tag 106, and an empty list as tag 106 alone.

The messages:

| Message | Form | Sent by |
| --- | --- | --- |
| advert | `#{t => advert, ver => 1, d => D}` | both sides, as the first frame |
| descriptor `D` | `#{id => <<64 bytes>>, pub => <<32 bytes>>, addr => <<"host:port">>, token => <<bytes>>}` | inside other messages |
| challenge | `#{t => pop_challenge, nonce => <<32 bytes>>}` | both sides |
| response | `#{t => pop_response, sig => <<64 bytes>>}` | both sides |
| rotated | `#{t => key_rotated, kid => <<bytes>>}` | the side that checked a token under another producer key |
| shuffle | `#{t => shuffle, store => Typ, entries => [E]}` | the side that dialed |
| shuffle reply | `#{t => shuffle_reply, store => Typ, entries => [E]}` | the side that was dialed |
| entry `E` | `#{age => Integer, d => D}` | inside shuffle and sample frames |
| sample | `#{t => sample, store => Typ, n => Integer}` | the side that dialed |
| sample reply | `#{t => sample_reply, store => Typ, entries => [E]}` | the side that was dialed |
| call, cast | `#{t => call or cast, ver => 1, req_id => <<bytes>>, m => Module, f => Function, a => Arity, args => List, opts => #{}}` | an edge, to a bridge |
| result | `#{t => result, ver => 1, req_id => <<bytes>>, value => Term}` | a bridge, in answer to a call |
| done | `#{t => done}` | a test program's node only, in answer to the two test-only frames of section 8 |

`Typ` is one of the atoms `tempus_edge`, `tempus_bridge` and `tempus_sentinel`.

The bounds on the fields. The node checks each one and refuses the whole frame when one is broken:

| Field | Bound |
| --- | --- |
| `id` | exactly 64 bytes |
| `pub` | exactly 32 bytes |
| `sig` | exactly 64 bytes |
| `nonce` | exactly 32 bytes |
| `kid` | 1 to 64 bytes |
| `addr` | 3 to 261 bytes |
| `token` | 65 to 1024 bytes |
| `age` | 0 to 65535 |
| `n` of a sample | 1 to the shuffle length the node is configured with for the named store |
| entries in one frame | at most the shuffle length the node is configured with, and never more than 64 |
| `req_id` of a call or cast | 1 to 16 bytes |

The shuffle length is a value of the node's configuration. It has no default, and a client cannot ask a node for it.
Your application has to know it for the network it joins.

## 5. The token

A token is 64 bytes of signature followed by a payload. The payload is an ETF term, beginning with the byte 131, that
is a map of exactly five keys:

`#{kid => <<1 to 64 bytes>>, sub => <<32 bytes>>, typ => Typ, nbf => Seconds, exp => Seconds}`

- `kid` names the producer key that signed the token.
- `sub` is the public key the token was issued for.
- `typ` is the peer type the holder may act as.
- `nbf` and `exp` are the first second at which the token is valid and the second at which it stops being valid, in
  whole seconds since 1970 UTC. `exp` must be later than `nbf`.

The signature is the producer's Ed25519 signature over the payload bytes exactly as they are. A verifier checks the
signature over the bytes it received and never encodes the payload again.

A token travels in gossip to other members, so it must contain nothing secret.

## 6. The order of a connection, and admission

One connection carries one request and its reply. The order is: the TLS handshake, the two adverts, the two
challenges, the two responses, one request, one reply, close. Both sides do the same thing up to the request.

What your client does, in order:

1. It completes the TLS handshake of section 3 and reads the public key from the node's certificate.
2. It sends its advert at once. The advert must be the first frame; the node refuses any other first frame.
3. It reads the node's advert and checks it:
   - the fields have the lengths of section 4, and the token has the structure of section 5;
   - the binding: the `pub` of the advert is the key of the certificate the node presented in the TLS handshake.
     Without this check a party in the middle, using its own certificate, could pass on someone else's advert and
     proof;
   - the token's `kid` is the producer key your client holds as current. If it is not, your client may send one
     `key_rotated` frame naming its current `kid` and then close (step 7 says how to close after it);
   - the time: `nbf - skew <= now < exp + skew`, where `skew` is the clock difference your application allows;
   - the token's `sub` is the advert's `pub`;
   - the advert's `id` is the SHA-512 hash of its `pub`;
   - the producer's signature on the token verifies under the current producer key;
   - if the token's `typ` is `tempus_bridge` or `tempus_sentinel`: the certificate is one of your `tempus` whitelist.
4. It sends its challenge: 32 bytes from a secure random source, fresh for this connection.
5. It reads the node's challenge and answers it with a response whose `sig` is the Ed25519 signature, made with the
   client's own private key, over the node's nonce followed by the client's own token bytes.
6. It reads the node's response and verifies that `sig` is a signature, under the `pub` of the node's advert, over
   the nonce the client sent followed by the node's token bytes. This exchange is called proof of possession: each
   side proves that it holds the private key its token was issued for.
7. Where the node's challenge was due, the node may send `key_rotated` instead. That means your client's token is
   signed under a producer key the node no longer takes as current. The frame names the `kid` the node does take. The
   node then closes. Your application must get a new token; trying again with the same token will get the same answer.
8. It sends its one request and reads the one reply. Then the connection is closed.

The node makes the same checks on your client, in this order: the advert's bounds, the binding, the `kid` (answered
with `key_rotated`), the time, `sub`, the whitelist rule, the `id` hash, the producer's signature, and then the proof
of possession. The whitelist rule at the node has two sides: a peer whose token says `tempus_bridge` or
`tempus_sentinel` must present a certificate of the node's `tempus` whitelist, and a peer whose certificate is in that
whitelist must present such a token. A client with a `tempus_edge` token needs no entry in any whitelist.

A side that sends `key_rotated` should not close at once. Closing a connection while bytes from the peer are still
unread can make the operating system reset the connection, and a reset can destroy the `key_rotated` frame before the
peer has read it. The node reads and drops what the peer still sends until the peer closes or the connection's time
bound passes. The Python example closes its sending direction and then reads for a short time before it closes.

## 7. What a refusal looks like

Except for `key_rotated`, a refusal is silent. The node closes the connection and sends nothing. It writes the reason
in an audit line in its own output, which your client cannot see. All your client can observe is a frame, a close, or
nothing until its own timer ends. Do not expect an error message, and do not try to work out the reason from the
moment of the close.

For the person who runs the node, these are the events the node's code writes, with what each means:

| Event in the node's audit line | Cause |
| --- | --- |
| `tls_handshake_failed`, `tls_verify_failed`, `alpn_mismatch`, `tls_group_refused`, `tempus_cert_key` | the handshake did not meet section 3: the version, suite or signature; the certificate, or none; the ALPN name; the key exchange group; a certificate key that is not Ed25519 |
| `protocol_error` | a frame that is too long, is not well-formed ETF, breaks a bound, has an unknown key, is not the frame due at that point, or is not a request |
| `binding_refused` | the advert's `pub` is not the key of the TLS certificate |
| `key_rotated` | the token is under another `kid`; the peer was sent the `key_rotated` frame |
| `admission_refused` | the token is not valid yet, has expired, has a `sub` that is not the advert's `pub`, has an `id` that is not the hash of `pub`, or has a signature that does not verify |
| `whitelist_reject` | the whitelist rule of section 6 |
| `pop_failed` | no response where one was due, or a proof of possession that does not verify |
| `entry_refused` | an entry of a shuffle or sample reply does not verify |
| `shuffle_refused` | the store refused a shuffle frame |
| `request_refused` | a `call` or `cast` sent to a node that is not a bridge |
| `timeout` | the connection's time bound passed while the node waited for the peer |
| `closed_by_peer` | the peer closed while the node waited for a frame |
| `inflight_refused` | the node already serves as many accepted connections as it is configured for |
| `clock_refused` | the node cannot read its system clock and is configured to wait until it can |
| `clock_stopped` | the node stopped because its system clock went back by more than its configured limit |

## 8. The requests a client can make

A client sends one of these after admission, on a connection it dialed.

### sample

`#{t => sample, store => Typ, n => N}` asks for up to `N` entries of the named store. The reply is
`#{t => sample_reply, store => Typ, entries => [E]}`, and then the node closes. Any admitted peer may send it.

A sentinel that answers a sample also adds the asking peer to its own store of the asker's type, after it has taken
the sample, so the reply never contains the asker. This is how a new member joins: it connects to a sentinel and sends
one sample request per store. The design also rules that a joiner keeps the sentinel it joined through: when the peer
that answered has a `tempus_sentinel` token, the joiner puts that sentinel's descriptor into its own sentinel store at
age 0.

### shuffle

`#{t => shuffle, store => Typ, entries => [E]}` offers entries of the named store and asks for some in return. The
reply is `#{t => shuffle_reply, store => Typ, entries => [E]}`, and then the node closes.

Every entry must verify by the rules of section 6 that need no connection: the field lengths, the current `kid`, the
time, `sub`, the `id` hash and the producer's signature. In addition the `typ` of each entry's token must be the type
of the store the frame names. One entry that does not verify makes the node refuse the whole frame; nothing from it
enters the node's store. Your client must apply the same rule to every reply it receives before it uses any entry.

The initiator of a shuffle puts its own entry first at age 0, when its own type is the type of the store.

### A reply must be the reply of its request

Before your client uses a reply it must check that the reply answers what was asked. A node that dials another node
makes these checks, and so must a client:

- the reply to a `shuffle` is a `shuffle_reply`, and the reply to a `sample` is a `sample_reply`. Any other frame,
  including the other of the two and the `done` frame, is refused;
- the reply names the store the request named;
- the reply holds at most the shuffle length of that store. A node never answers a `sample` with more entries than the
  `n` asked for, so a client may also refuse more than `n`, and the Python extension does;
- every entry verifies, as above. One entry that does not verify refuses the whole reply;
- the `result` of a `call` carries the `req_id` of the call. A `cast` has no reply at all.

A reply that fails any of these is treated as no reply: nothing of it is used.

### call and cast, to a bridge only

A client with a `tempus_edge` token may ask a bridge to run a function. The frames are TRUST's request frames,
unchanged: the module and function as atoms, the number of arguments in `a`, the arguments as a list in `args`, an
empty map in `opts`, and a `req_id` of the client's choosing. A `call` is answered with a `result` frame carrying the
same `req_id` and the function's return value, and then the bridge closes. A `cast` is never answered: the bridge
closes when the outcome of the cast is known.

A node that is not a bridge refuses both. A bridge runs only functions its application has exported, and only when
its configuration permits the caller's peer type to call them; with no permission configured, nothing is permitted.
The bridge also keeps a score for each peer and limits on how many requests a peer may send in an interval and have in
progress at once. Refusals, failures and timeouts raise the score, and above the limit even a good request is refused.
The limits are chosen by the bridge's application; BEES has no defaults for them. Every refusal, a function that fails
and a call that times out look the same to your client: the connection closes with no reply and no error text.

### No other request exists

A production node accepts no other request. In particular there is no request that returns a node's whole store, and
there is no leave message: a member that stops is forgotten as its entries grow old and its token expires.

The trials in this repository also send two frames named `tick` and `clock`, and the examples contain code that
builds them. They are for testing only. The code that reads them is in a separate test unit, `src/tempus_test/`, that
only a test program includes in its build. A production node has no such code and refuses both frames as it refuses
any frame that is not a request. Do not build them into a client. A test program's node answers them with the frame
`#{t => done}`. A `done` frame is never the reply to a `sample`, a `shuffle` or a `call`, and a client that receives
one in their place must refuse it.

## 9. A client that listens

When a node dials your client, the same admission runs with the roles unchanged: both sides send an advert at once,
challenge each other and answer. After admission your client reads one request and answers it:

- a `shuffle` with a `shuffle_reply` for the same store;
- a `sample` with a `sample_reply` for the same store;
- anything else with a close and no reply.

Your client must make the checks of sections 4 and 6 on what it receives, and must close with no reply on any
violation, as the node does.

A client that only listens and answers with its own entry is reachable, but it is not yet a member that finds other
peers. Section 16 says what a member has to keep and do.

## 10. Limits and timeouts the node enforces

- One time bound covers a whole connection, from the moment the node dialed or accepted it to the close. It is not a
  bound per step. The value is the node's configured `shuffle_timeout_ms`; it has no default. While a node itself is
  working on a request it has admitted, such as a bridge's call, the wait is governed by the node's own bounds instead.
- The node serves at most its configured `inflight_max` accepted connections at once and closes any further one as
  soon as it is accepted.
- The frame and field bounds of section 4.
- The token's time window, judged by the node's clock and its configured `clock_skew_ms`.

Give your client a time bound of its own for a whole connection. A node may stay silent until its bound passes.

## 11. How a connection ends, and why

- After the reply, the node closes. This is the normal end. A connection is never reused for a second request.
- With no reply, at any step, when the node refuses something (section 7).
- At once after the TLS handshake, before the node sends its advert, in three cases. Your client sees only the close.
  - The node already serves `inflight_max` accepted connections.
  - The node's audit line says `clock_refused`. The node could not read its system clock, and it is configured to
    wait rather than go on with its last reading. It closes every connection it accepts until the clock can be read
    again. Trying again later can succeed.
  - The node's audit line says `clock_stopped`. The node's system clock went back by more than its configured limit,
    and it is configured to stop in that case. It admits nobody until its application starts it again. Trying again
    will not succeed until then.
- When the node's own token has expired, the node still listens and answers, but its advert carries the expired
  token, and your client's own check of that advert must refuse it.

## 12. What a client must never assume

- That a refusal comes with a reason. Only `key_rotated` is ever said.
- That a close means the request was refused for good. An early close can be the connection limit or the node's clock.
- That a node's certificate proves anything by itself. Only the binding check, the token checks and the proof of
  possession together admit a peer.
- That an entry received in a reply is good. Each one must be verified before it is used or passed on.
- That a peer in a store is still alive. Entries are hearsay with an age.
- That a connection can carry a second request.
- That a node will accept a token after its `exp`, or the same token after the producer's key has changed.
- That any value has a default. The shuffle length, the time bound, the skew and the bridge's limits are all set by
  whoever runs the node.
- That a bridge passes the client's identity or its bytes on to the TRUST network. It does not: the bridge's own
  function builds any onward request.
- That the `tick` and `clock` frames exist on a real node.
- That anything said in a token is private.

## 13. Checklist

1. Hold an Ed25519 key pair, the SHA-512 of the public key, and a certificate self-signed over that key.
2. Hold a current token from the producer, and replace it before it expires. The source material for the design says
   to refresh at half of the token's lifetime.
3. Hold the producer's current public key and `kid`, and take a new one from your application when it changes.
4. Offer TLS 1.3 only, the group X25519MLKEM768, ALPN `tempus/1`, and your certificate. Require the peer's
   certificate and read its Ed25519 key.
5. Frame every message with a 4-byte length. Refuse a frame above 131072 bytes from its length.
6. Write maps with their keys in name order and with only the listed keys. Refuse unknown, missing and repeated keys.
7. Send your advert first. Check the peer's advert completely, including the binding to the TLS certificate.
8. Send a fresh 32-byte random challenge. Sign the peer's nonce followed by your own token. Verify the peer's
   signature over your nonce followed by its token.
9. Handle `key_rotated` where a challenge was due, and report it to your application.
10. Send one request. Read one reply. Verify every entry in it. Close.
11. On any violation by the peer, close and say nothing.
12. Bound the whole connection with one timer of your own.
13. Never log or send your private key, and send nothing but what this document lists.

## 14. What is open, and what could not be checked against the code

- One question of the design is still open: NQ-21. It concerns how a configuration file spells the mode of a node
  that is both TEMPUS and TRUST, and which tool reads that spelling. It does not concern the wire format, so nothing in
  this document depends on it. This document does not say how it will be decided.
- The design says a TEMPUS certificate is self-signed over the identity key. The node's code checks that the
  certificate's key is Ed25519 and that it equals the advert's `pub`; it verifies no chain, and no separate check of
  the self-signature was found in it. The Python example does check, for a peer it dials, that the issuer equals the
  subject and that the certificate's signature verifies under its own key.
- The nesting depth: the design's table says 4. The node's structure check, made on every frame before its kind is
  looked at, allows 6, and the decoder of each message then allows what that message needs (an advert 3, a frame of
  entries 5, the others 2). A client that sends only the messages of section 4 stays inside all of them.
- Whether a node accepts ETF written in another valid form (for example a different integer or atom tag) was not
  checked. The form in section 4 is what both examples write and what the trials compare byte for byte.
- The refresh at half of the token's lifetime is taken from the design and its source material. No code of the node
  enforces it: refreshing is the application's act.
- The check that a `result` carries the `req_id` of its `call` is made by the Python extension. It was not traced in
  the Silica client.
- Traced through the node's code on 2026-11-23, for the document on writing a node, and no longer open here: an
  initiator puts its own entry first at age 0 in the store of its own type; a joiner keeps the sentinel it joined
  through; a node whose own token has expired goes on listening and answering.
- The bridge's behaviour in section 8 was checked against the header of `src/tempus/bees_tempus_bridge.silica` and
  the design's section 17, not against every line of that unit.

## 15. What to install for a Swift, a Kotlin, a C# or a Rust client on a Mac

This section lists what a Mac with Apple Silicon needs before a client written in Swift, in Kotlin, in C# or in Rust can be compiled
and run. The versions are the ones on the machine where the examples in this directory were written, on 2026-11-20.
They are what was used, not a stated minimum. Other languages need the same three kinds of thing: a compiler, a TLS
library that can meet section 3, and Ed25519 signatures.

Whatever the language, check the TLS library against section 3 before writing anything else. The two requirements a
library most often lacks are the key exchange group X25519MLKEM768 and certificates whose key is Ed25519. A library
that cannot offer both cannot connect to a TEMPUS node, and no setting of the node changes that.

### Swift

- Apple's Command Line Tools. Install them with `xcode-select --install`. They supply the Swift compiler (`swiftc`),
  the Swift Package Manager (`swift build`), the linker and the macOS SDK with its frameworks. Version used: Command
  Line Tools 26.6, Swift 6.3.3.
- Xcode is not needed. The application called Xcode is a separate, much larger install, and nothing in a
  command-line Swift client depends on it.
- One thing the Command Line Tools alone do not reliably supply is the XCTest test framework. Plan to write tests as
  an ordinary program with a `main` function, or confirm that your test framework is present before relying on it.
- OpenSSL 4.1.0 or later. Install it with `brew install openssl@4`; that needs Homebrew (https://brew.sh). Swift
  calls it as a C library through a module map, with no C code of your own. Apple's own frameworks were tried first
  on macOS 26 and could not be used, for these reasons:
  - The Network framework offers the group X25519MLKEM768 but does not offer Ed25519 as a signature algorithm in its
    handshake, and has no public call to change that. A node's certificate has an Ed25519 key, so the handshake
    fails.
  - The Security framework did not load an Ed25519 identity from a PKCS12 file (`SecPKCS12Import` returned -26275).
    One other way of loading the key was tried and also failed; that does not prove no way exists.
  - CryptoKit's Ed25519 signatures differ from one call to the next for the same message. They verify correctly, but
    they cannot be compared byte for byte with the signatures another library makes, which is how the examples are
    tested.
- The file `swift/README.md` gives the details and the build commands.

### Kotlin

- A Java Development Kit of feature release 27 or later. Install one with `brew install openjdk`. Version used:
  OpenJDK 27.0.1.1. The JDK supplies the TLS library (JSSE), Ed25519 signatures (the algorithm named `Ed25519`) and
  SHA-512, so no other library is needed. JDK 25 was tried and cannot connect: its TLS library does not have the
  group X25519MLKEM768.
- The Kotlin compiler. Install it with `brew install kotlin`. Version used: Kotlin 2.4.21 (about 97 MB). It supplies
  `kotlinc`. Homebrew installs or updates its `openjdk` package as part of this.
- Homebrew's JDK is not registered with macOS: `/usr/libexec/java_home` does not find it. Put
  `/opt/homebrew/opt/openjdk/bin` on the `PATH`, or call `java` by that full path.
- A build tool such as Gradle or Maven is not needed for a client of this size. `kotlinc` can compile the sources into
  one jar file, and `java -jar` runs it.
- Three things to know about the JDK's TLS library before you start:
  - The group must be chosen with `SSLParameters.setNamedGroups`. The library cannot report which group a
    connection negotiated, so offer only X25519MLKEM768.
  - The default trust manager checks a certificate against authorities and must be replaced. The replacement is
    where the checks of section 3 belong: the key is Ed25519, the issuer equals the subject, and the certificate's
    own signature verifies.
  - The JDK has no supported call that makes an X.509 certificate. Make the client's certificate with another tool
    and give the client the certificate and key files.
- The file `kotlin/README.md` gives the details and the build commands.

### C#

- The .NET SDK, release 11. Install it with `brew install dotnet`. Version used: 11.0.100.
- OpenSSL 4.1.0 or later. Install it with `brew install openssl@4`. C# calls it as a C library through P/Invoke, with
  no C code of your own. .NET's own TLS and cryptography were tried first on macOS 26 and could not be used:
  - `X509Certificate2.CreateFromPemFile` does not load an Ed25519 key (`'1.3.101.112' is not a known key algorithm`),
    so a client cannot present its certificate.
  - `SslStream` asked for TLS 1.3 alone fails with `The requested security protocol is not supported`; with Apple's
    Network framework as its engine the handshake fails with error -9824, as the Swift attempt did.
  - .NET 11 has no Ed25519 signature type.
- No NuGet package and no test framework are needed. A project with no package reference builds with no network when
  its `nuget.config` clears the package sources.
- Three things to know about OpenSSL from C#: several settings are C macros and must be called as `SSL_CTX_ctrl` with
  the macro's number; the two callbacks are static methods marked `UnmanagedCallersOnly`; and memory BIOs with a .NET
  `Socket` keep every wait under one deadline.
- The file `csharp/README.md` gives the details and the build commands.

### Rust

- A Rust toolchain: cargo and rustc. Version used: 1.91.1.
- OpenSSL 4.1.0 or later. Install it with `brew install openssl@4`. Rust's standard library has neither TLS nor
  Ed25519. Without fetching any crate, a client calls OpenSSL through `extern "C"` declarations and a build script
  that names the library directory. No C code and no `libc` crate are needed.
- The settings that are C macros go through `SSL_CTX_ctrl` with the macro's number, as in C#.
- A blocking `TcpStream` with read and write timeouts keeps the one deadline of a connection without any operating
  system call of your own.
- Tests can be ordinary `cargo test`, since the test harness ships with the toolchain. `cargo build --offline` makes
  sure that no network request is made.
- The file `rust/README.md` gives the details and the build commands.

### What none of them needs

- The Silica compiler and the BEES sources are needed only to run a TEMPUS node to test against. A client needs
  neither to be compiled.
- Python and its `cryptography` package are needed only for the Python example and for the tools that make the test
  certificates and tokens.

## 16. A client that takes part in gossip

Sections 1 to 13 are enough for a client that sends one request to an address it was given. A client that has to
find other peers by itself must also be a member of the network. A member keeps stores, shuffles them on a timer,
joins through a sentinel and answers from its stores. The rules below are the node's own, from the design's sections
3, 6 and 10 and from `src/tempus/bees_tempus_view.silica`, `bees_tempus_store.silica` and `bees_tempus_node.part`.
Each example in this directory has them in its library, and `gossip/` runs them.

### What a member is configured with

None of these has a default. They are values of the network your client joins.

- For each of the three stores (`tempus_edge`, `tempus_bridge`, `tempus_sentinel`): a capacity (1 to 256), a shuffle
  length (1 to 64, and at most the capacity) and a tick in milliseconds (100 to 3600000).
- The time bound of a whole connection (section 10).
- The sentinels' addresses, and the certificates of the sentinels and bridges your client accepts (item 7 of
  section 2). A first sentinel has no sentinel.
- The first and the greatest delay between two attempts to join.

### The stores

- A store holds entries. An entry is a peer's identifier, its descriptor and an age, which counts ticks.
- A store never holds two entries for one peer, never holds your client itself, and never holds more entries than
  its capacity.
- An entry enters a store only after its descriptor verified for that store, by the rule of section 8: the checks of
  section 6 that need no connection, and a token whose `typ` is the store's type.
- Before each tick of a store, drop every entry whose token has expired by your clock and your skew.

### One tick of one store

1. If your client's own token would not be admitted now (the same check as for a peer), do not tick. Tell your
   application once; it owns the refresh.
2. Every age in the store rises by one. An age stops at 65535.
3. If a shuffle that this store started has not ended yet, stop here.
4. If the store is empty, stop here. If the join has finished, ask a sentinel for a `sample` of this store again.
5. The partner is the oldest entry. If several are equally old, choose one of them at random.
6. Choose at random, without choosing one twice, the other entries to send. In the store of your client's own type
   send the shuffle length minus one of them, after your own entry at age 0. In the other two stores send the shuffle
   length of them and do not send your own entry. If the store holds fewer, send all it holds.
7. Take the partner and the chosen entries out of the store and remember them.
8. Dial the partner's address, send the `shuffle` and read the `shuffle_reply`.

Use a secure random source for every choice.

### When the reply arrives

Verify every entry of the reply for the store. If one fails, or the reply holds more entries than the shuffle length,
treat the shuffle as failed. Otherwise merge:

1. If a received entry is for a peer you just sent, and the entry you sent is strictly younger, use the entry you
   sent in its place.
2. Drop received entries that name your client.
3. If a peer appears twice among the received entries, keep the younger one. If the ages are equal, keep the first.
4. A received entry replaces the store's entry for the same peer only if it is strictly younger. A received entry
   for a peer the store does not hold is added. Put the received entries that were taken in front of the others.
5. While the store is above its capacity, remove the oldest entry. If several are equally old, remove the last one
   in the store's order.
6. In a store that is not of your client's own type, put the partner back at age 0. The partner cannot hold your
   client in that store, so nothing else would bring it back.
7. Put the entries you sent back at the end, in the order you sent them, while there is room. Skip a peer the store
   holds again already.

### When the shuffle fails

The partner could not be reached, closed early, did not answer within the time bound, or answered with something
that does not verify. Leave the partner out of the store. Put the other entries you sent back, by rule 7. Do not try
again within the same tick.

### Answering

- A `shuffle` for a store: verify every entry for that store, and refuse the whole frame if one fails or if there are
  more than the shuffle length. Choose at random up to the shuffle length of your entries for the reply, never the
  asking peer's own entry. Take them out, merge what you received by rules 1 to 5, then put the entries you answered
  with back by rule 7.
- A `sample` of `n` entries for a store: refuse `n` above the store's shuffle length. Answer with up to `n` entries
  chosen at random. The store does not change.
- If your client's token says `tempus_sentinel`: after it has taken the sample, it puts the asking peer into its
  store of that peer's type at age 0. This is how a joining peer becomes known.

### The join

1. For each store in turn (edge, bridge, sentinel), dial a sentinel and ask for a `sample` of that store, with `n`
   equal to the store's shuffle length.
2. Verify every entry of the reply and put each into the store with the age it came with, by merge rules 2 to 5.
3. If the peer that answered was admitted with a `tempus_sentinel` token, put its descriptor into your sentinel store
   at age 0.
4. If no sentinel answered for a store, wait and try again. Start with the first delay and double it up to the
   greatest delay.

Your client's listener and its tick timers start with the join. They do not wait for it.

### What the examples show

`gossip/` runs four instances of each example's driver as one network on one machine, and networks that mix the
languages. Its README says what the check of such a run shows and what it does not.
