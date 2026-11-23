# What do I need to do to write a TEMPUS node?

This document is for a programmer who needs an application, in any language, to be a TEMPUS node. It builds on [What
do I need to do to write a TEMPUS client?](writing-a-tempus-client.md) and does not repeat it. Read that document
first: everything it requires of a client is also required of a node, because a node is a peer in both positions on
every connection. This document adds what a node does beyond that: it keeps stores, joins, shuffles on its own timers,
answers other members, reads a clock, and tells its application what happened.

The authority for what a node does is the ruled design, `development-plan/tempus-design.md`. "Design section 3" below
means a section of that document. Every statement here was checked against the code of the BEES TEMPUS node, the
Silica library in `src/tempus/`, and where a file is named in brackets that is where it was checked. The Python
extension in `python/` was written from this list, and the trial `trials/c7_tempus_node_python` runs its nodes and
Silica nodes in one network; where that trial shows a statement, the section says so. Section 18 lists what is open
and what could not be verified.

An extension is code in a language other than Silica that lets an application in that language take part in a TEMPUS
network. The Python, Swift and Kotlin code in this directory are extensions.

## 1. More terms

The client document defines node, peer, producer, token, peer type, store, descriptor, advert, admission, shuffle, ETF,
frame and audit line. A node needs these as well:

- A view is the content of one store: a list of entries, in an order that matters.
- An entry is one peer in a view: the peer's identifier, its descriptor, and an age.
- An age is a whole number from 0 to 65535. It counts the ticks since the entry was fresh.
- A tick is one turn of a store's timer. Each of the three stores has its own timer.
- The capacity of a store is the greatest number of entries its view may hold.
- The shuffle length of a store is the greatest number of entries one frame of that store may carry.
- The partner of a tick is the entry the node shuffles with at that tick.
- A draw is one random number used for one choice. A node takes its draws from a secure random source.
- The node's own type is the peer type of its token: `tempus_edge` for an edge, `tempus_sentinel` for a sentinel.
- A store of the node's own type is the store whose type is the node's own type. The other two are stores of another
  type.
- To join is to become known to the network: a starting node asks a sentinel for entries of each store.
- The `tempus` whitelist is the list of TEMPUS certificates of the bridges and sentinels a node accepts.
- A test node is a node whose clock, timers and draws are given to it by a test. A node that is not a test node reads
  the machine's clock, runs its own timers and takes its draws from the operating system.

## 2. Which roles a node can have

The design has three roles: edge, sentinel and bridge (design section 11).

- An edge is an ordinary member. It needs at least one sentinel in its configuration.
- A sentinel is a member whose address and certificate other nodes know in advance. New nodes join through it. A
  sentinel may have sentinels of its own, or none: the first sentinel of a network has none. A sentinel is not also a
  member of TRUST, so an extension without TRUST can be one. The Silica node treats a sentinel differently from an
  edge in exactly one place: when it answers a sample (section 9).
- A bridge is also a member of a TRUST network and runs functions for edges. An extension without a TRUST
  implementation cannot be a bridge and must refuse a configuration that asks for it. Section 17 says what a bridge
  would need.

## 3. What a node must have before it starts

Everything the client document lists in its section 2, and in addition:

1. A configuration with every value of section 4 below. No value has a default.
2. The `tempus` whitelist: for each bridge and sentinel the node accepts, the SHA-512 hash of that node's certificate
   in DER form, 64 bytes. An entry names one certificate, not one key: a new certificate over the same key is another
   entry. The order of the list matters only for the node's audit lines, which name an entry by its position.
   [`dangerous_bees_tempus_conn.silica`, `wl_index`; `dangerous_bees_tempus_tls.silica`, head]
3. A clock that answers the whole seconds since 1970 UTC, or says that it cannot be read. A node reads the machine's
   clock itself. Its application does not pass it the time.
4. Timers: one per store, one for reading the clock, and one for retrying the join.
5. A secure random source, for the nonces of admission and for the draws of the stores.
6. A way to tell its application what happened (section 14) and a place to write its audit lines (section 15).

## 4. Configuration

A node takes these values. The names and bounds are those of the `tempus` section of `bees.config` (design section 11;
`tools/bees_tempus_conf.py`). How an application supplies them is for each extension to decide. What is not for an
extension to decide: no value has a default, nothing is clamped to its bound, and a missing or out-of-range value
refuses the start.

| Value | Bounds | Meaning |
| --- | --- | --- |
| `role` | `edge`, `sentinel`, `bridge` | the node's own type; its token must carry the same type |
| `listen_address`, `port` | port 1 to 65535 | where the node listens. Every TEMPUS node listens. |
| `sentinels` | 1 to 16, each a host, a port and the name of a whitelist entry | required unless the role is `sentinel` |
| `edge`, `bridge`, `sentinel` | each: `capacity` 1 to 256; `shuffle_length` 1 to 64 and at most the capacity; `tick_ms` 100 to 3600000 | one set per store |
| `producer_key` | a `kid` of 1 to 64 bytes and a key of 32 bytes | the producer's one current key |
| the identity key and certificate | an Ed25519 key; a certificate self-signed over it | the node's TEMPUS identity |
| the `tempus` whitelist | | section 3, item 2 |
| `shuffle_timeout_ms` | 100 to 60000 | one bound for a whole connection (section 11) |
| `inflight_max` | 1 to 64 | accepted connections served at once |
| `clock_skew_ms` | 0 to 300000 | the clock difference allowed when a token's time is judged |
| `clock_back` | `follow`, `hold`, `stop` | what a reading earlier than the node's time does (section 12) |
| `clock_back_limit_s` | 0 to 86400 | required when `clock_back` is `stop`; refused under `follow` and `hold` |
| `clock_fail` | `continue`, `pause` | what a reading that fails after a good one does (section 12) |
| `clock_read_ms` | 100 to 60000 | how often the clock is read |
| `join_retry_initial_ms`, `join_retry_max_ms` | 100 to 3600000; the maximum not below the initial | section 7 |

Not configuration, but passed by the application when it starts the node and replaced while it runs: the node's own
token, and the address other nodes dial to reach it, which the node's advert carries.

A key named `control_test_only` existed until 2026-11-20 and turned test frames on. It is refused now, with either
value. No configuration may turn anything test-only on (section 16).

The start is also refused when the node's own token does not have the structure of a token, is of another type than
the node's role, or names another key than the node's identity key. [`bees_tempus_node.silica.in`, `boot_why`] The
Silica node's words for these are `the node's token does not read: ...`, `the node's token is for another peer type
than the node's` and `the node's token names another key`, each after `tempus: boot refused: `.

## 5. A store

A node has three stores and never moves an entry from one to another (design section 2.3). One store holds:

- its view: at most `capacity` entries, no two with the same peer identifier, none for the node itself, every age from
  0 to 65535;
- while a shuffle that this store started is under way: the entries it sent and the partner it chose;
- the node's own entry, which is the node's own descriptor;
- whether the node's own entry belongs in it. It does only in the store of the node's own type.

Every choice below uses one draw, as an index modulo the number of candidates. A missing or negative draw counts as 0.
"Drawn without replacement" means: take the entry at the drawn position out of the candidates, and draw again among
those left. [`bees_tempus_view.silica`]

### 5.1 One tick, when this store starts a shuffle

1. Every age rises by one, and stops at 65535.
2. The partner is the entry with the greatest age. Among several of that age, one draw picks one, counted in the
   view's order.
3. Other entries are drawn without replacement from the view without the partner: `shuffle_length - 1` of them in the
   store of the node's own type, and `shuffle_length` of them in a store of another type. With fewer entries than
   that, all of them.
4. The frame that goes to the partner holds, in the store of the node's own type, the node's own entry first at age
   0, and then the drawn entries in the order drawn. In a store of another type it holds only the drawn entries.
5. The partner's entry and the drawn entries leave the view. The store remembers them until the shuffle ends.

[`bees_tempus_view.silica`, `select`; `bees_tempus_store.silica`, `start`]

### 5.2 When the partner's reply arrives

1. A reply with more entries than the shuffle length counts as a failed shuffle (5.4).
2. Each received entry whose peer is among the entries just sent, where the sent one is strictly younger, is replaced
   by the sent one. At equal age the received one stays.
3. The merge (5.5) of the view with the received entries.
4. In a store of another type, the partner that answered is put back at age 0, by the rules of the merge. In the store
   of the node's own type it is not put back. The reason is in design section 3.4: in a store of another type the
   node's own entry was not sent, so nothing else would bring the partner back, and the store would lose one entry at
   every shuffle.
5. Sent entries are put back at the end of the view, in the order they were sent, while there is room. One whose peer
   is already in the view is skipped.

[`bees_tempus_store.silica`, `reply`]

### 5.3 When another peer's shuffle arrives

1. The request is refused, and nothing changes, when it holds more entries than this store's shuffle length.
2. Up to `shuffle_length` entries are drawn without replacement from the view without the asking peer's own entry.
   They are the answer, in the order drawn, and they leave the view. An entry of the asking peer, if the view has one,
   stays in the view for the merge to replace.
3. Each received entry whose peer is among the entries just answered, where the answered one is strictly younger, is
   replaced by the answered one.
4. The merge (5.5) of what is left of the view with the received entries.
5. Answered entries are put back while there is room, as in 5.2 step 5.

It does not matter whether a shuffle of this store's own is under way. [`bees_tempus_store.silica`, `request`]

### 5.4 When a shuffle this store started fails

The partner stays out of the view. The other sent entries are put back while there is room. Nothing is tried again
before the next tick. A shuffle fails when the partner cannot be reached, closes early, stays silent until the
connection's bound, breaks any rule, or sends a reply that is not a shuffle reply for this store.

### 5.5 The merge

Given the entries the store kept and the entries it received:

1. Received entries for the node itself are dropped.
2. A peer that was received more than once is kept once: the youngest of them, the earliest at equal age, at the
   place of its first arrival.
3. A received entry wins when the view has no entry of that peer, or has an older one. At equal age the view's entry
   stays.
4. The new view is the winning received entries in their order, followed by the kept entries in their order, without
   those a winner replaced.
5. While the view is above capacity, the entry with the greatest age is removed. Among several of that age, the last
   in the view's order goes. Because received entries are in front, a kept entry goes before a received one of the
   same age.

Inserting one entry (a peer that joined, the sentinel a node joined through) is a merge with that one entry received.
[`bees_tempus_view.silica`, `merge`, `insert`]

### 5.6 A sample

Up to `n` entries, and never more than the shuffle length, are drawn without replacement. The view is not changed.

### 5.7 Draws

A store uses one set of draws for each tick that starts a shuffle and one set for each request or sample it answers.
The Silica node asks its random source for one more draw than the shuffle length each time, seven random bytes for
each draw. When the random source gives nothing, a tick is skipped whole, with no ageing, and a request or a sample is
refused. Nothing is ever chosen without a draw. [`bees_tempus_store.silica`, `tick`, `request`, `sample`;
`bees_tempus_node.part`, `tn_draws`]

### 5.8 Proving a store implementation

The repository has two independent models of these rules in Python (`tools/bees_tempus_view_model.py`,
`tools/bees_tempus_store_model.py`) and recorded outputs of the Silica code for hand-worked cases and for runs of many
nodes (`trials/t0_tempus_view`, `trials/t1_tempus_store`). Compute every line of those recorded outputs with your
implementation. The Python extension does this in `python/test_bees_tempus_node.py`.

## 6. Starting

In this order [`bees_tempus_node.part`, `tn_start`, `tn_clock`, `tn_up`]:

1. The node checks its configuration and its own token. Any fault refuses the start.
2. It reads its clock. Until the first reading succeeds it does not listen, does not join and does not tick. If the
   first reading fails it says so in one line, tells its application, and begins when a later reading succeeds.
3. At the first good reading it opens its listen address.
4. It writes one line that names its type, the first 8 hex digits of its identifier and its address, and one line
   per store with the capacity and the shuffle length.
5. It joins (section 7).

The store timers run from the start, each with its store's `tick_ms`. A tick that falls due when the node may not
tick (section 12) does nothing.

## 7. Joining

[`bees_tempus_node.part`, `tn_join` to `tn_join_failed`, `tn_dialed_join`, `tn_keep_sentinel`, `tn_inserted`]

A node with no sentinel in its configuration writes `join: no sentinel is configured` and is done.

Otherwise it asks one sentinel for each store, one store after another, in the order edge, bridge, sentinel. Each
request is one connection: admission, then `sample` for that store with `n` equal to that store's shuffle length.

When the sentinel answers with a `sample_reply`:

1. Its entries enter the store by the merge rules, with the ages they came with, if the reply is for the store asked
   and holds at most that store's shuffle length. Every entry has been verified before (section 10).
2. If the peer that answered has a `tempus_sentinel` token, its own descriptor then enters the node's sentinel store
   at age 0. This happens after every answered sample, whichever store was asked. A sentinel is not in its own stores,
   so without this step a network with one sentinel would leave every node's sentinel store empty.
3. The node goes on to the next store, starting again with its first sentinel. After the third store the join is
   done.

When the sentinel does not answer, for any reason:

1. The node asks its next configured sentinel for the same store.
2. When no sentinel is left, it waits and then tries the same store again from its first sentinel. The first wait is
   `join_retry_initial_ms`. Each later wait is twice the one before, and never more than `join_retry_max_ms`. The wait
   goes back to the initial value when a store is answered.

A node asks a sentinel again later, outside the join: when a tick finds a store's view empty, the join is done, and no
request for that store is already under way, the node asks for that store once more. This request tries each
configured sentinel once and is not retried by a timer.

The node dials nobody while it waits for its clock (section 12). A join request that falls due in that time, from the
retry timer or as the next store after an answer, is remembered, with one line, and is dialed at once when the clock
is read again. After the node has stopped for a step back of its clock, a join request dials nobody.

What the sentinel does on its side is in section 9.

## 8. The node's own shuffles

[`bees_tempus_node.part`, `tn_timer`, `tn_tick`, `tn_out`, `tn_dialed_shuffle`, `tn_ended`;
`bees_tempus_node.silica.in`, `sweep`, `on_reply`]

When a store's timer fires, the node arms it again and, if the clock's state lets it tick (section 12):

1. It checks its own token as it would check a peer's: structure, `kid`, time, `sub`. If its own token would not be
   admitted, it does not tick. The first time, it writes one line and tells its application (section 13).
2. It removes from that store every entry whose token has expired by the node's clock, `now >= exp + skew`, and
   writes one line naming them.
3. The store's tick (5.1). The outcome is one of:
   - no draws: the tick is skipped;
   - a shuffle of this store is already under way: the ages rose and nothing else happens;
   - the view is empty: nothing to shuffle; the node may ask a sentinel again (section 7);
   - a shuffle: the node dials the partner.
4. The partner's address is the `addr` of its descriptor. The Silica node dials only an address that is a dotted IPv4
   address, a colon and a port from 1 to 65535. Any other address fails the shuffle without a connection.
5. On the connection: admission, then the `shuffle` frame, then one reply. The reply is accepted for the merge only
   when it is a `shuffle_reply`, for this store, with at most the shuffle length, and every entry verifies (section
   10). Anything else fails the shuffle (5.4).

One connection is one shuffle. The connection is bounded by `shuffle_timeout_ms` from the dial.

## 9. Serving other peers

[`bees_tempus_node.part`, `tn_accepted`, `tn_request`, `tn_rq_shuffle`, `tn_rq_sample`;
`dangerous_bees_tempus_conn.silica`, `c_up`, `c_request`]

For each accepted connection, the node decides at the accept, in this order:

1. If the clock's state closes connections (section 12), the connection is closed as soon as its TLS handshake is
   done, with the audit event `clock_refused` or `clock_stopped`.
2. If the node already serves `inflight_max` accepted connections, the connection is closed as soon as its TLS
   handshake is done, with the audit event `inflight_refused`. It does not count as served.
3. Otherwise it is served and counts until it closes.

A connection that is closed in this way gets no advert and no frame. Its TLS handshake is still completed.

A served connection runs admission (section 10) and then reads one request:

- `shuffle`: the frame must hold at most the greatest shuffle length of the node's three stores, and every entry must
  verify for the store the frame names. Then the store's own rule applies (5.3): a frame with more entries than that
  store's shuffle length, or a store with no draws, is refused with the audit event `shuffle_refused`. Otherwise the
  node sends the `shuffle_reply` for the same store.
- `sample`: `n` must be from 1 to the shuffle length of the store named. The node sends a `sample_reply` for the same
  store (5.6). When the node's role is sentinel, it then puts the asking peer into its store of the asking peer's
  type, at age 0, whoever asks and whichever store was asked. The sample is taken first and the insert follows, so a
  node that joins is not answered with itself the first time.
- `call` and `cast`: a node that is not a bridge refuses both, with the audit event `request_refused`.
- anything else, including the test-only `tick` and `clock` frames: refused, with the audit event `protocol_error`
  and the text `not a request: ` followed by the reason.

After the reply, or with no reply after a refusal, the node closes. A connection carries one request.

## 10. Admission and the checks of entries, with the node's reasons

The client document's section 6 gives the order of a connection. The node's checks of the peer's advert are, in this
order [`dangerous_bees_tempus_conn.silica`, `c_advert`, `c_advert_ok`, `c_hash`, `c_prod`; `bees_tempus_admit.silica`]:

| Order | Check | Audit event | The Silica node's text |
| --- | --- | --- | --- |
| 1 | the first frame is an advert | `protocol_error` | `the first frame is not an advert` |
| 2 | its structure and bounds | `protocol_error` | the bound, for example `id is not 64 bytes`, `ver is not 1` |
| 3 | the binding: `pub` is the key of the TLS certificate | `binding_refused` | `the advert's pub is not the key of the peer's TLS certificate` |
| 4 | the token's structure | `admission_refused` | the fault, for example `truncated` |
| 5 | the token's `kid` is the current one | `key_rotated` | the peer is sent the `key_rotated` frame |
| 6 | the time, `nbf - skew <= now < exp + skew` | `admission_refused` | `the token is not valid yet`, `the token has expired` |
| 7 | the token's `sub` is `pub` | `admission_refused` | `sub is not the peer's key` |
| 8 | the whitelist rule, both ways | `whitelist_reject` | see below |
| 9 | `id` is the SHA-512 of `pub` | `admission_refused` | `id is not the SHA-512 of pub` |
| 10 | the producer's signature on the token | `admission_refused` | `the signature does not verify` |

The `kid` is judged before the time: a token under another `kid` gets the `key_rotated` answer whatever else is wrong
with it. After sending `key_rotated` the node reads and drops what the peer still sends, until the peer closes or the
connection's bound passes, and only then closes.

The whitelist rule has two sides. A peer whose token says `tempus_bridge` or `tempus_sentinel` must have presented a
certificate of the whitelist. A peer whose certificate is in the whitelist must have a token that says
`tempus_bridge` or `tempus_sentinel`. A node with an empty whitelist therefore accepts no bridge and no sentinel.

Then the proof of possession, in both directions. Where the peer's challenge is due, the node accepts a
`pop_challenge` or a `key_rotated` and refuses anything else (`protocol_error`, `a challenge was expected`). Where the
peer's response is due, anything that is not a well-formed response, and a signature that does not verify, are
`pop_failed`.

An entry of a received `shuffle`, `shuffle_reply` or `sample_reply` is checked without a connection: checks 4 to 7,
then that the token's type is the type of the store the frame names (`typ is not the store's type`), then checks 9 and
10. A token under another `kid` is a refusal like any other here; no `key_rotated` is sent for an entry. One entry
that fails refuses the whole frame, with the audit event `entry_refused` and the text `entry K: ` and the reason,
where K counts from 0. Nothing of a refused frame enters a store. A node must make these checks on the replies to its
own shuffles and samples as well as on the shuffles it is sent.

A node accepts a frame only when its structure is sound: one map whose keys are atoms, of terms nested at most 6
deep, with no bytes after it, and naming only atoms the node knows. The Silica node makes this check before it looks
at a frame's kind, and a frame that names an atom it does not hold is refused with the reason `unknown_atom`. That is
why a production Silica node refuses a `tick` frame with `not a request: unknown_atom`: it does not hold the atom
`tick`. A frame that is sound and whose `t` is a known atom that is no request is refused with `not a request:
unknown kind`. [`src/trust/bees_trust_frame.silica`, `check`; `bees_tempus_frame.silica`, `kind`, `why_refused`]

The trial `trials/c7_tempus_node_python` sends 44 hostile cases to a Silica sentinel and to a Python sentinel and
requires the audit lines of the two to be the same. Its transcript, `walk.macos_applesilicon.scout`, is a list of the
cases with the Silica node's exact line for each.

## 11. Limits and timeouts

- One time bound covers a whole connection: `shuffle_timeout_ms` from the dial, or from the accept, to the close. It
  is one deadline, not one timer per step. The TCP connect, the TLS handshake and every wait for a frame of the peer
  each get what is left of it. [`bees_tempus_link.part`, `tempus_deadline`]
- When the bound passes while the node waits for the peer, the node closes and writes the audit event `timeout` with
  the step it waited at.
- A frame longer than 131072 bytes is refused from its length alone, before any byte of its body is kept.
- The bounds on fields and on entries in a frame are those of the client document's section 4.
- `inflight_max` bounds the accepted connections served at once (section 9).
- A node keeps nothing for a peer outside its views: no table of peers seen, no cache of tokens. The number of edges
  is not bounded, so any such table would be a way to exhaust a node.

## 12. The clock

[`bees_tempus_node.silica.in`, `clock_back`, `clock_turn`, `clock_ticks`, `clock_closes`; `bees_tempus_node.part`,
`tn_clock`; `dangerous_bees_tempus_draws.silica`, `tck`]

The node reads its clock at start and then every `clock_read_ms`. Its clock is in whole seconds since 1970 UTC. A
reading that is an error of the operating system, or a time before 1970, is "no time", never a made-up time. The
node's time is its last good reading, except as the two choices below say.

The node is in one of these states:

| State | Ticks | Accepted connections | Dials |
| --- | --- | --- | --- |
| no reading yet | no | it does not listen | no |
| good | yes | served | yes |
| going on with the last reading | yes | served | yes |
| holding its time | yes | served | yes |
| waiting for the clock | no | closed at once, `clock_refused` | no; a join request waits |
| stopped | no | closed at once, `clock_stopped` | no |

A reading that fails after a good one is decided by `clock_fail`:

- `continue`: the node goes on with its last reading. It says so once and tells its application. Its time stands
  still until the next good reading, which it takes without a line.
- `pause`: the node waits for the clock. It says so once and tells its application. The next good reading is said in
  one line, and a join request that waited is dialed at once.

A good reading earlier than the node's time is decided by `clock_back`:

- `follow`: the reading becomes the node's time, with one line that gives the number of seconds.
- `hold`: the node's time stays. The node says once that it holds. Later readings that are still behind change
  nothing and say nothing. When a reading is equal to the held time or later, the node says so in one line and
  follows the clock again. If a reading fails while the node holds and the next good reading is still behind, the
  hold line is said once more.
- `stop`: a step back of at most `clock_back_limit_s` seconds is followed. A larger one stops the node for good: one
  line, the application is told, the node's time stays, and no later reading changes anything. Only the application
  starting a node again ends it.

A failure while the node waits, or goes on with its last reading, is not said again.

These decisions are one pure function in the Silica library, and the trial `trials/t0_tempus_clock` records its
answer for every case. Compute every line of that recorded output with your implementation. The trial
`trials/c7_tempus_node_python` shows the states on running Python nodes.

## 13. The node's own token, and the producer's key

- The application replaces the node's token while the node runs. From then on the node's adverts and the node's own
  entry in its shuffles carry the new token. [`bees_tempus_node.part`, `tn_token`]
- A node whose own token is not valid by its own clock stops ticking and tells its application once. It goes on
  listening and answering. Its advert then carries the expired token, so every correct peer refuses it. It ticks again
  when the application gives it a valid token; nothing is restarted.
- The application gives the node the producer's new key and `kid` when they change. From then on the node judges
  every advert and entry by the new key. [`bees_tempus_node.part`, `tn_key`]
- When a peer answers the node's advert with `key_rotated`, the node's token is under a `kid` that peer no longer
  takes. The node tells its application, which must get a new token.

## 14. What the application is told

The Silica node tells its application of these, and of nothing else [`bees_tempus_node.part`, head]:

| What | When |
| --- | --- |
| the node's own token is not valid any more, with the reason | once, at the first tick that finds it so |
| a peer answered `key_rotated`, with the `kid` it named | each time, on a connection the node dialed |
| the clock could not be read, with what that means for the node | once per failure, not once per reading |
| the node has stopped after a step back of its clock | once |
| the start was refused, with the reason | at the start |

A test node of the Silica library also writes one line with a store's view after each change. A production Silica
node does not. An extension should give its application the view after a change in some form, because an application
that calls a bridge has to choose one from its bridge store.

## 15. Audit lines

A node writes one line for each refusal, each admitted peer and each TLS connection made. The Silica node's form is

`[tempus audit] EVENT peer=PEER WHAT CONNECTION`

where PEER is the first 16 hex digits of the peer's identifier once its advert was read, or `-`, and CONNECTION is
`a` or `d` (accepted or dialed) and that connection's number, each kind counted from 1. The node's own lines (the
join, the ticks, the clock) show a peer by the first 8 hex digits. An extension whose lines have the same events and
texts lets an operator compare a mixed network line by line, and lets a trial compare the extension with the Silica
node by machine. No line may hold a private key, a token, or a time of day.

## 16. Testing a node, and what a node must not contain

The owner ruled on 2026-11-20 that the Silica library holds no code for the test-only `tick` and `clock` frames. The
same holds for an extension:

- A node must be testable with a clock, a timer source and a random source that the test supplies. Supply them
  through the node's ordinary construction interface, in the idiom of your language. Never through a frame, a message
  or a configuration key that a peer or an operator could use on a running node.
- A node refuses `tick` and `clock` frames as it refuses any frame of no kind.
- Keys from fixed seeds, token making, fixed nonces and peers that misbehave on purpose belong in test sources. No
  source file that an application builds may contain them. Have a check that fails the build or the trial when one
  does.
- Compare with the Silica node, not only with yourself. Run both in one network, send both the same hostile bytes,
  and require the same lines.

## 17. What a bridge would need

Not built in any extension, and stated here so that nobody assumes it is small (design section 17; not traced through
the code for this document, see section 18):

- a TRUST implementation in the same language: TRUST's mutual TLS with pinned certificates, its whitelist with
  permission specs, its reconnect token, its suspicion and quarantine rules, and its request frames;
- two identities in one program: a TRUST certificate key and a separate TEMPUS identity key;
- serving `call` and `cast` from edges: the forbidden-module guard, a permission spec per peer type, a call timeout,
  no error body;
- a per-peer table with a score, a limit, a rate bound and a bound on requests in progress, sized by values the bridge
  application passes. On a bridge every refusal of an accepted peer whose identity is known raises that peer's score,
  and a new entry is made only after the token's signature verified.

## 18. What is open, and what was not verified

- Scoring. On a Silica node that is not a bridge, the connection code tells the node of every refused accepted peer,
  and the node drops the report (`tn_refused_peer`). So a node that is not a bridge keeps no score and has no score
  limit. The rules of that report were not built into the Python extension and are not listed above as requirements.
- `key_rotated` on an accepted connection. When a peer that dialed the node answers the node's advert with
  `key_rotated`, the Silica node writes the audit line and does not tell its application; it tells its application
  only when the node itself dialed (`c_challenge` in `dangerous_bees_tempus_conn.silica` passes it on for a dialed
  connection only). Design section 10 says without a condition that the node reports `key_rotated` to the
  application. The Python extension tells its application in both cases and says which. Which is intended is the
  owner's to say.
- How often the clock is read. A comment at the head of `bees_tempus_node.part` says the clock is read "once a second
  after each answer". The code reads it every `clock_read_ms` (`tck` in `dangerous_bees_tempus_draws.silica`), as the
  design says. The comment is stale.
- A join answered with a frame that is not a sample reply. The Silica node then writes the frame's bytes into its
  `join: the sentinel did not answer` line where the other cases have a reason in words (`tn_dialed`, `what`). The
  Python extension writes `the reply is not a sample reply`.
- A new token is not checked by the Silica node when the application passes it; a wrong one shows at the next tick.
  The Python extension refuses a token that cannot be the node's own at once.
- `clock_skew_ms`. The Silica node takes its skew in seconds. The code that turns the configured milliseconds into
  those seconds is not built on the Silica side (it waits on the store reader of open question NQ-21).
- The advertised address when the node listens on every interface. The configuration has no key for it; the Silica
  node's application passes the address with the identity. An extension has to take it from the application too.
- Host names. The configuration tool accepts a host name for a sentinel; the Silica node dials dotted IPv4 addresses
  only. Who resolves a name is not in the code read for this document.
- The self-signature of a certificate. The Silica node checks that the certificate's key is Ed25519 and equals the
  advert's `pub`. Whether its TLS engine also checks that the certificate is signed by its own key was not traced.
- The order in which a Silica node writes two lines that come from different actors, for example an audit line of a
  connection and a line of the node, is fixed by which message arrives first, not by a rule. The trials wait for each
  step to end before the next begins.
- The bridge. Section 17 is from the design and from the head of `src/tempus/bees_tempus_bridge.silica`, not from
  every line of that unit.
- Memory and time. Nothing in this document was measured: no soak, no number of peers, no rate of connections.
- Platforms. The mixed trial was run on a Mac with Apple Silicon only.
