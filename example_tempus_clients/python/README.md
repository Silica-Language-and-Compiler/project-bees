# The Python TEMPUS extension

This directory holds the Python extension for TEMPUS. An extension is code in a language other than Silica that lets an
application written in that language take part in a TEMPUS network. TEMPUS is the gossip membership mode of BEES: nodes
find each other by exchanging small signed records over mutually authenticated TLS 1.3 connections.

With this extension a Python application can be one of two things:

- a TEMPUS peer that is not a node: it connects to nodes and makes requests of them, or listens and answers them. The
  document [What do I need to do to write a TEMPUS client?](../writing-a-tempus-client.md) describes what such a peer
  does.
- a TEMPUS node: a member of the network that keeps its own stores, joins through a sentinel, shuffles on its own
  timers and answers other members. The document [What do I need to do to write a TEMPUS
  node?](../writing-a-tempus-node.md) describes what a node does.

A node of this extension can be an edge or a sentinel. It cannot be a bridge. A bridge is a node that is also a member
of a TRUST network (TRUST is the other mode of BEES, for long-lived nodes that know each other in advance), and there
is no TRUST in Python. A configuration that asks for the role `bridge` is refused.

The statement at the top of [the directory's README](../README.md), that what is in this directory tree is an example
and must not be used in production, stands until the project owner changes it. The section "What stands between this
and production" below says what has and has not been reviewed.

## The files, and the line between the extension and the test support

The extension is seven modules. An application imports these and nothing else.

| Module | What it holds |
| --- | --- |
| `bees_tempus_codec.py` | the frames: the writer and reader of every `tempus/1` message, every bound, the token's structure, and the structure check a node makes before it looks at a frame's kind |
| `bees_tempus_admission.py` | the checks one peer makes of another, in the node's order: the channel binding, the token rules, the `tempus` whitelist rule, the identity hash, the producer's signature, the proof of possession |
| `bees_tempus_peer.py` | one connection: mutual TLS 1.3 with the `tempus/1` profile, frames, admission in both positions, `dial()` and `Listener` for a peer that is not a node |
| `bees_tempus_view.py` | the view of one store, as pure functions |
| `bees_tempus_store.py` | one store's steps: tick, reply, failed, request, sample, insert, drop |
| `bees_tempus_config.py` | a node's configuration: the keys, bounds and refusals of the `tempus` section of `bees.config` |
| `bees_tempus_node.py` | the node |

The test support is one module, `bees_tempus_testing.py`. It holds everything that exists only so that the trials can
test nodes: the two test-only frames `tick` and `clock`, token making (a token is made by the producer, never by a
peer), keys from fixed seeds that are written in this repository, fixed nonces, and peers that misbehave on purpose. It
also holds a clock, a timer source and a random source that a test steps by hand. No module of the extension imports
it, and the trial `trials/c7_tempus_node_python` fails if any module of the extension contains any of those things.

`bees_tempus_client.py` is the old name of the Python code. The trial tools import that name, so it is kept as a thin
module that passes on every name of the test support. An application never imports it.

`test_bees_tempus_client.py` and `test_bees_tempus_node.py` are the tests. Run them from the BEES root directory:

```
python3 example_tempus_clients/python/test_bees_tempus_client.py
python3 example_tempus_clients/python/test_bees_tempus_node.py
```

## What an application must install

- Python 3. The version used here is 3.14.5. The extension uses no syntax or module newer than Python 3.8, but no
  other version was run.
- A Python whose `ssl` module is built over OpenSSL 3.5 or later. TEMPUS connections use the key exchange group
  X25519MLKEM768 and no other, and OpenSSL has that group from 3.5 on. The version used here is OpenSSL 3.6.2. Check
  with `python3 -c "import ssl; print(ssl.OPENSSL_VERSION)"`.
- The `cryptography` package, for Ed25519 signatures and for reading certificates. The version used here is 46.0.3.
  Install it with `python3 -m pip install cryptography`.

Nothing else is needed. The Silica compiler and the BEES sources are needed only to run Silica nodes to test against.

## How an application starts a node

The application must have, before it starts a node:

- an Ed25519 key pair, in a file (PEM, PKCS8, not encrypted), and a certificate self-signed over that key, in a file
  (PEM). The key is the node's TEMPUS identity.
- a token from the producer for that key, of the node's own type. The producer is the party that decides who may be a
  member; getting a token from it is the application's job.
- the producer's current public key and its key identifier, called `kid`.
- for every bridge and sentinel the node accepts: that node's TEMPUS certificate, as a PEM file in one directory. This
  directory is the `tempus` whitelist.
- the address other nodes dial to reach it.

A complete application that is a TEMPUS edge:

```python
import sys
import bees_tempus_config
import bees_tempus_node

def told(event):
    # called on the node's thread; it must not block
    if event.name == "token_invalid":
        print("the node's token is not valid any more:", event.why)      # get a new token; node.set_token(...)
    elif event.name == "key_rotated":
        print("a peer takes another producer key:", event.kid)           # get a new token under that key
    elif event.name in ("clock_unreadable", "stopped", "listen_failed"):
        print(event.name, event.text)

config = bees_tempus_config.node_config({
    "role": "edge",
    "listen_address": "0.0.0.0", "port": 7400,
    "sentinels": [("192.0.2.1", 7400, "sentinel-1.pem")],
    "edge": {"capacity": 32, "shuffle_length": 8, "tick_ms": 10000},
    "bridge": {"capacity": 8, "shuffle_length": 4, "tick_ms": 30000},
    "sentinel": {"capacity": 8, "shuffle_length": 4, "tick_ms": 30000},
    "producer_key": ("k1", bytes.fromhex(sys.argv[1])),
    "identity_keyfile": "identity-key.pem", "identity_certfile": "identity.pem",
    "whitelist_cert_dir": "tempus-whitelist",
    "shuffle_timeout_ms": 5000, "inflight_max": 16, "clock_skew_ms": 30000,
    "clock_back": "hold", "clock_fail": "pause", "clock_read_ms": 1000,
    "join_retry_initial_ms": 1000, "join_retry_max_ms": 60000,
})
with open("token.bin", "rb") as f:
    token = f.read()
node = bees_tempus_node.Node(config, token=token, address="198.51.100.7:7400", on_event=told)
node.start()
```

The numbers in this example are only there to make it complete. They are not recommendations and they are not
defaults: no value of the configuration has a default, and a missing key is refused.

While the node runs, the application:

- calls `node.set_token(new_token)` when it has a new token. The source material for the design says to get a new
  token at half of the token's lifetime.
- calls `node.set_producer_key(kid, public_key)` when the producer's key changes.
- may call `node.peers(store)` for a copy of one store's view, for example to choose a bridge to call.
- calls `node.stop()` to stop it.

The application does not pass the time of day to the node. The node reads the machine's clock itself, runs its own
timers and takes its random bytes from the operating system. The constructor has three more arguments, `clock`,
`timers` and `random`, through which a test gives the node a clock, timers and draws that the test controls. An
application passes none of them.

## The configuration

The keys, their meanings and their bounds are those of the `tempus` section of `bees.config`
(`development-plan/tempus-design.md` section 11, `tools/bees_tempus_conf.py`). The application passes them as a Python
dict. This is the choice made for Python; nothing reads a `bees.config` file here. A refusal raises `ConfigRefused`
with the text `tempus.KEY: what is wrong`, in the words of the Silica node's configuration tool where that tool has
the same refusal.

| Key | Value | Bounds |
| --- | --- | --- |
| `role` | `"edge"` or `"sentinel"` | `"bridge"` is refused |
| `listen_address`, `port` | an IPv4 literal or `"localhost"`; an integer | port 1 to 65535 |
| `sentinels` | a list of `(host, port, cert_name)` | 1 to 16; required unless the role is `"sentinel"`; the host is an IPv4 literal; `cert_name` is a file name in `whitelist_cert_dir` |
| `edge`, `bridge`, `sentinel` | each `{"capacity", "shuffle_length", "tick_ms"}` | capacity 1 to 256; shuffle_length 1 to 64 and at most the capacity; tick_ms 100 to 3600000 |
| `producer_key` | `(kid, key)` | kid 1 to 64 bytes; key 32 bytes, or 64 hex digits |
| `identity_keyfile`, `identity_certfile` | paths | an Ed25519 key; the certificate self-signed over it |
| `whitelist_cert_dir` | a path, optional | every file whose name ends in `.pem` and not in `-key.pem` is one entry; the entries are numbered in the order of their names |
| `shuffle_timeout_ms` | an integer | 100 to 60000; one bound for a whole connection |
| `inflight_max` | an integer | 1 to 64 |
| `clock_skew_ms` | an integer | 0 to 300000 |
| `clock_back` | `"follow"`, `"hold"` or `"stop"` | |
| `clock_back_limit_s` | an integer | 0 to 86400; required under `"stop"`, refused otherwise |
| `clock_fail` | `"continue"` or `"pause"` | |
| `clock_read_ms` | an integer | 100 to 60000 |
| `join_retry_initial_ms`, `join_retry_max_ms` | integers | 100 to 3600000; the maximum not below the initial |
| `edge_spec`, `bridge_spec`, `sentinel_spec` | optional; only `"none"` | what a peer may call is served by a bridge only |

Not configuration: the node's token and the address it advertises. They are arguments of `Node(...)`, as the Silica
node takes them from its application.

Three things differ from the Silica node's configuration, and each is a choice the owner has not ruled on:

- `whitelist_file` is refused. In TRUST it gives what each whitelisted peer may call, and only a bridge serves calls.
- `clock_skew_ms` is turned into whole seconds by dropping the remainder, because the node's clock is in whole
  seconds. The Silica side has no code yet that turns the configured milliseconds into the seconds its node takes.
- A sentinel's host must be an IPv4 literal. The Silica configuration tool also accepts a host name; the Silica node
  itself dials dotted addresses only.

## What the application is told

`on_event` is called with one `Event`. Its `name` says what happened.

| Event | Values | When |
| --- | --- | --- |
| `token_invalid` | `why` | the node's own token is not valid by the node's own admission rules, so no peer would admit the node. Ticking has stopped until `set_token` gives a valid token. Told once. |
| `key_rotated` | `kid`, `dialed` | a peer answered the node's advert with `key_rotated` and named that `kid` |
| `clock_unreadable` | `text` | the clock could not be read. The text says what that means for the node. Told once per failure, not once per reading. |
| `stopped` | `text` | the clock went back by more than `clock_back_limit_s` under `clock_back` `"stop"`. The node stays stopped whatever is read later. |
| `listen_failed` | `text` | the node could not open its listen address |
| `view` | `store`, `entries` | a store's view after a change |

The node also writes lines: its own (`join: ...`, `tick ...`, `clock: ...`) and its audit lines (`[tempus audit]
EVENT peer=... WHAT aN`). They have the wording of the Silica node's lines, so that an operator can compare the two.
They go to the function given as `log`, or to standard output when none is given, as the Silica node's do. No line
holds a time of day, a key or a token.

## What is tested, and by which trial

- `test_bees_tempus_node.py`:
  - the stores, by running the tools' own view and store tests with the extension's modules in the place of the two
    independent models, so that every line of the recorded outputs of `trials/t0_tempus_view` and
    `trials/t1_tempus_store` is computed again by the extension and compared;
  - the clock's decisions, by computing every line of the recorded output of `trials/t0_tempus_clock` again;
  - admission, with every case of `trials/t4_tempus_admission` and that trial's recorded reasons;
  - the configuration's refusals, with the cases and words of `tools/test_bees_tempus_conf.py` and the boot refusals
    of `trials/c4_tempus_boot`;
  - that a reply must be the reply of its request and that its entries are verified;
  - nodes in one process, stepped by hand.
- `trials/c7_tempus_node_python` runs Python nodes and Silica nodes in one network on the loopback address:
  - a Python sentinel joins through a Silica sentinel, and a Silica edge joins through that Python sentinel;
  - shuffles started by each side and answered by the other, in the edge store and in the sentinel store;
  - 44 hostile cases, each sent to the Silica sentinel and to the Python sentinel by the same peer with the same
    bytes. The trial requires the audit lines the two nodes write to be the same, word for word;
  - a Python node that is not a test node (`r_app.py`, a process of its own) and a Silica node built without the test
    unit: the Silica node joins through the Python node, the Python node shuffles with it on its own timer, and both
    refuse the test-only `tick` and `clock` frames in the same words;
  - the clock's choices on Python nodes: the hold beginning and ending, going on with the last reading, the wait for
    the clock with a connection closed as `clock_refused` and a join request that waits, a step back inside the limit,
    and the stop above it with a connection closed as `clock_stopped`; and an expired own token, a new token and a new
    producer key;
  - the extension's `dial` and `Listener` as a peer that is not a node, against a Silica node and against peers that
    answer wrongly.
- The trials that existed before (`t2_tempus_frames`, `t3_tempus_nodes`, `t6_tempus_clock`, `c2_tempus_clients`,
  `c3_tempus_bridge`, `c5_tempus_swift`, `c6_tempus_kotlin`) use the test support, which is built on the extension's
  codec, admission checks and connection. Their recorded outputs did not change.

## What is not covered

- The bridge role, and with it everything of design section 17: serving `call` and `cast`, the permission specs, the
  per-peer score and its limit, the per-peer rate and requests in progress. A node of this extension refuses `call`
  and `cast` as the Silica node that is not a bridge does. Scoring exists on a bridge only: a Silica node that is not a
  bridge is told of each refused peer and drops the report, and this node keeps no score either.
- Calling a bridge from a node. `dial()` can send a `call` or a `cast` and checks the result's `req_id`, but the node
  has no function that picks a bridge from its bridge store and calls it.
- Host names. The node dials dotted IPv4 addresses only, as the Silica node does, and listens on IPv4 only.
- A soak. Nothing here measures memory or behaviour over many hours or many peers.
- Any platform but the Mac the trials ran on. A Linux run of `trials/c7_tempus_node_python` has not been made.

## What stands between this and production

- The owner's statement that nothing in this directory tree is for production has not been changed.
- No review. The extension was written and tested by one author in one day. Nobody else has read it.
- A private hook of Python's `ssl` module. Python's `ssl` gives a server the client's certificate only when it
  verifies it against trust anchors, and has no verification callback, while a TEMPUS node must accept a certificate
  it has never seen. The extension solves this with `SSLContext._msg_callback`, which Python provides for debugging
  and does not document: it reads the client's certificate out of the handshake and makes it the only trust anchor of
  that one connection. The same hook is how the extension learns which key exchange group was negotiated. If a Python
  release removes or changes that hook, the extension refuses to start a node and says why; it does not fall back to
  something weaker. Python 3.15 has `SSLContext.set_groups`, which the extension calls when it exists, but it has not
  been run on 3.15.
- The third TLS 1.3 cipher suite, TLS_AES_128_GCM_SHA256, cannot be taken out of Python's offer. A connection that
  negotiated it is refused after the handshake. A Silica node never chooses it.
- Threads. Each connection has a thread of its own. `inflight_max` bounds the accepted connections that are served,
  but a connection above the limit still gets a thread for its TLS handshake before it is closed, as the Silica node
  also completes that handshake. Nothing bounds the number of such handshakes in progress.
- The private key is held in memory by the `cryptography` package's key object and by the TLS library, for the
  process's whole life. Python cannot wipe it.
- The choices listed under "The configuration" and in the report of 2026-11-23 that the owner has not ruled on.
