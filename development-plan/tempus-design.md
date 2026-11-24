# TEMPUS in BEES: design

Status: design, first written 2026-11-18; redrafted the same day after the owner ruled on all 25 open questions (section 14
keeps the questions and the rulings as the record). Built: T0 (the pure view logic), T1 (the store logic and actor), T2 and
C1 (the frames, in Silica and in Python). Progress and what is verified: [tempus-progress.md](tempus-progress.md).

TEMPUS is the half of SEMP for nodes that come and go. TRUST, the half for stable nodes, is built in BEES (N3, N4). This
document says what TEMPUS requires and how BEES builds it. By the owner's ruling (OQ-1) sections 3 to 8 are the first
TEMPUS wire specification, `tempus/1`, to be offered back to SEMP.

## 0. How to read this document

Every statement carries one of three marks.

- `[S: where]` taken from a SEMP source. The only SEMP sources are the files of `~/BEAM_SEMP`; `README.md` there is cited as
  `R:line`.
- `[B: which]` decided: by a BEES ruling or plan text (a roadmap decision `D<n>`, a named document and section), or by one
  of the owner's TEMPUS rulings of 2026-11-18, cited as `[B: OQ-n]` (the ruling's own words are the line beginning "RULED"
  under that question in section 14).
- `[P]` proposed here and not ruled. After the redraft a `[P]` is either a detail the rulings leave to this specification
  (the owner reviews it section by section, OQ-1), or it names a new open question `NQ-n` of section 18.

Where the SEMP sources and the rulings are silent, no rule is invented: the point is a new open question in section 18,
with options and a recommendation, and nothing that depends on it is built.

## 1. What the SEMP sources contain about TEMPUS

Checked 2026-11-18 by listing and searching `~/BEAM_SEMP` (branch `main` at `a9c95c3`, branch `origin/multiplex_dev`, and the
41-commit log). Observed, not inferred:

- There is no TEMPUS specification apart from one section of the README, `R:347` to `R:436`, added by commit `9e5c64e`
  ("added an initial discussion of TEMPUS"). The same text is on both branches.
- There is no TEMPUS design document. `multiplexing and backpressure design doc.md` line 10 lists "TEMPUS overlay changes"
  as out of its scope.
- There is no TEMPUS Erlang code. `src/` holds `semp_*` and `src/trust/` only. Commits `538bc51` and `441d4f3` moved files
  "in anticipation of adding TEMPUS files" and "in support of adding tempus"; nothing followed.
- Three traces exist in the code:
  - `src/semp_whitelist.erl` lines 3 to 4, 30, 54 to 56: the whitelist module is "Shared whitelist for TRUST and TEMPUS",
    with a second ETS table `tempus_whitelist`, keyed like TRUST's by the SHA-512 of a certificate's DER, values a
    permission spec. No code calls it with the `tempus` profile.
  - `src/semp_policy.erl` line 190: `tempus_` is one of the forbidden module prefixes.
  - `README.md` lines 4 and 8: the introduction.

So the authority for TEMPUS is about ninety lines of prose and one diagram. Section 2 lists everything they fix. Everything
else in this design is either a BEES ruling or a proposal.

## 2. What TEMPUS requires, according to the sources

### 2.1 Purpose and shape

1. SEMP has two parts, "TRUST for stable, long-lived nodes and TEMPUS for ephemeral nodes" `[S: R:4]`.
2. TEMPUS is "a Cyclon-based network overlay" that "enables ephemeral node discovery and security, utilizing certificates,
   and mTLS" `[S: R:8]`. Note: the TEMPUS section itself (`R:347` to `R:436`) never mentions certificates, TLS or mTLS. See
   OQ-2.
3. Each SEMP RPC call "uses a connect, (token path), call, close behavior to avoid complete graph speed problems"
   `[S: R:11]`. This is said of SEMP as a whole.
4. "No errors are sent to clients that malicious actors can leverage" `[S: R:17]`, said of SEMP as a whole. See OQ-10 for
   the one place the TEMPUS section seems to differ.
5. TEMPUS is "a secure peer-sampling and membership layer that uses the Cyclon gossip protocol to keep three independent
   peer sets fresh and unbiased, within a single process. Each peer set ('type') has its own Cyclon view, capacity, and
   shuffle cadence. There is no cross-type shuffle." `[S: R:350]`
6. The goal: "peers are cryptographically verifiable, churn is handled gracefully, and sampling remains uniform within each
   population" `[S: R:352]`.

### 2.2 The three peer types

7. `tempus_edge`: ephemeral, high-churn, short-lived; "the bulk of the mesh"; they "do standard Cyclon shuffles among
   themselves" `[S: R:360-361]`.
8. `tempus_bridge`: non-ephemeral, longer-lived peers that "bridge to separate TRUST overlays/instances. They shuffle only
   with other `tempus_bridge` peers. Application logic uses them to reach TRUST; Cyclon state stays isolated."
   `[S: R:363-364]`
9. `tempus_sentinel`: non-ephemeral "membership guardians"; "peers that ephemeral nodes use to prove producer-authorized
   membership. They run Cyclon among themselves for availability, and act as admission guardians." `[S: R:366-367]`
10. "You may run different counts of each type. The only invariant is no cross-type mixing." `[S: R:369]`

### 2.3 Cyclon as TEMPUS uses it

11. "One TEMPUS server maintains three independent Cyclon stores: `tempus_edge`, `tempus_bridge`, `tempus_sentinel`."
    `[S: R:375-376]`
12. "Each store has: fixed capacity, shuffle size l, independent tick (periodic timer), and maintains `(peer, age)`
    entries." `[S: R:377]`
13. Within a store, on each tick `[S: R:378-382]`:
    1. Increment ages.
    2. Pick the oldest neighbor as the shuffle partner.
    3. Prepare an outgoing buffer (include `{self, age=0}`), remove sent entries from the local view.
    4. On merge, prefer younger entries; evict oldest to respect capacity.
14. "Across stores: there is no exchange of entries" `[S: R:383]`.

### 2.4 Identity and admission

15. "TEMPUS separates sampling (Cyclon) from trust (admission). A peer only enters a store after proving it's an authorized
    instance of your product, without any shared secret among peers." `[S: R:389]`
16. Per-install asymmetric identity: "Each node generates an Ed25519 keypair on first run and derives a `peer_id` from the
    public key." `[S: R:393-394]`
17. Producer-signed, short-lived tokens: the producer backend "issues very short-lived tokens (e.g., 2 to 5 minutes) that
    bind to the peer's public key (`sub`) and include role/type (`typ` in `tempus_edge`, `tempus_bridge`,
    `tempus_sentinel`)" `[S: R:396-397]`. The sequence diagram adds the fields `kid=current`, `nbf/exp` `[S: R:427]`.
18. No-overlap key rotation: "Verifiers pin to the current signing key via `kid`. At rotation, tokens signed with an old key
    are rejected with a precise 'rotated key' error; legitimate peers immediately re-fetch a token under the new key. Tight
    TTLs + proactive refresh (TTL/2) keep recovery fast." `[S: R:399-400]`
19. Proof of possession: "When presenting a token, the peer signs a fresh challenge with its own private key (the same
    public key carried in `sub`)." `[S: R:402-403]` The diagram: the verifier sends a "POP challenge (fresh nonce)" and the
    peer answers "Sign (nonce || token) with peer_priv" `[S: R:432-433]`.
20. Platform attestation (App Attest, Play Integrity) happens "during token issuance", at the producer `[S: R:405-406]`.
21. The sequence `[S: R:414-436]`: the peer builds an advert `{peer_id, peer_pub, token, typ}`; sends it to a "Verifier
    Peer"; the verifier checks the token (`kid=current`, signature, `nbf/exp`, `sub==peer_pub`), sends the challenge,
    verifies the response with `peer_pub`, and then "Admit peer into store by typ (no cross-type mixing)".
22. "Only peers with valid, current producer signatures and POP are admitted to the appropriate Cyclon store."
    `[S: R:408]`

### 2.5 What the sources do not fix

No wire message, no encoding of any field, no transport, no port, no ALPN; no default or bound for capacity, shuffle length
or tick; how the other entries of a shuffle are chosen, what the partner answers, what happens when a shuffle fails; how a
node joins or leaves; how a node of one type learns peers of another type; the token's format and signature algorithm; how
`peer_id` is derived; how verifiers learn the producer's key; what a sentinel returns; what a TEMPUS node may ask of a TRUST
node or the reverse; whether suspicion, quarantine, the whitelist or TRUST's reconnect token apply. Each is in section 14.

### 2.6 What BEES has already ruled

- TEMPUS is built after TRUST "as a layer on top of TRUST"; it "reuses TRUST's transport, framing, encoding and ingress
  path, and adds membership and admission for ephemeral nodes" `[B: D12]`. The roadmap still schedules it after 1.0; the
  owner has now started it (the edit is in section 15).
- "For TEMPUS traffic, admission through producer tokens and proof of possession has to stand in for the whitelist lookup,
  while TRUST's other rules stay in force" `[B: inter-nodal-modes 5]`. That text calls it "one design point to settle when
  TEMPUS work starts"; it is OQ-2 and OQ-3 here.
- Three isolated stores, each a process with a shuffle tick from Silica's `send_after`; Ed25519 in the native edge; platform
  attestation belongs to the issuer, BEES nodes only verify tokens; "a `tempus_bridge` peer is also a TRUST node with a
  whitelisted certificate. Bridging is application logic" `[B: inter-nodal-modes 5]`.
- TRUST's frames are a 4-byte length and one ETF map `[B: D36]`; peer trust is the SHA-512 pin of a certificate's DER plus
  the whitelist, a chain is optional, a certificate must be Ed25519 or ECDSA P-256 `[B: D43, D11]`; TLS engines are OpenSSL
  (hosted) and Mbed TLS (boards) `[B: D40]`; a refused peer is told nothing `[B: inter-nodal-modes 3]`.
- BEES is a source-only library; the application reads configuration through the `(:store)` carrier as ETF and passes
  values `[B: D46, N0c]`; decode limits are literals with one ceiling as a maximum `[B: D47]`; a node is a BEAM-mode node or
  a SEMP node, never both `[B: D36, D37, README]`; every atom a node needs exists at compile time `[B: D16, D30]`; timers
  are Silica's `[B: D33]`; state machines are plain Silica behaviours with a phase field `[B: D5]`; no monitors `[B: D20]`.
- The forbidden guard already refuses the `tempus_` prefix `[B: N3, from S: semp_policy.erl:190]`.
- The owner's TEMPUS rulings of 2026-11-18 (section 14), in short: this document is the specification (OQ-1); mutual TLS
  1.3 with a certificate self-signed over the node's Ed25519 identity key, plus the explicit challenge (OQ-2); the `tempus`
  whitelist lists bridge and sentinel certificates (OQ-3); an entry carries the advert, is verified offline and dies with
  its token (OQ-4); every store is shuffled with partners of that store, the node's own entry only in its own type's store
  (OQ-5); join through configured sentinels and a `sample` per store, no leave message (OQ-6); the token is an ETF map and
  an Ed25519 signature (OQ-7); `peer_id` is the SHA-512 of the public key (OQ-8); 32-byte nonce, both directions, every
  connection (OQ-9); one `key_rotated` frame, the producer key from configuration (OQ-10); no defaults for capacity,
  shuffle length and tick (OQ-11); a failed shuffle drops the partner and puts the sent entries back, sent entries fill room
  after a merge, no scoring of edges (OQ-12); TEMPUS and TRUST relate as section 7 says (OQ-13); a SEMP node runs TRUST,
  TEMPUS or both (OQ-14); every TEMPUS node is reachable (OQ-15); an explicit clock-skew allowance (OQ-16); no admission
  stand-in, admission and TLS before any networked trial (OQ-17); all of TEMPUS now, not after 1.0 (OQ-18, changing D12's
  placement); both clients are wire-only TEMPUS peers (OQ-19); the test-only tick and clock frames in a unit only a
  test program lists in its build (OQ-20, as ruled again on 2026-11-20; first behind a flag `control_test_only`); compiled-in client scenarios first (OQ-21); a bridge is a node that is both, with two keys (OQ-22); the bridge
  forwards nothing, scores and bounds each peer (OQ-23); the application picks a bridge, BEES does not retry (OQ-24); the
  bridge's bounds are the bridge application's (OQ-25).

## 3. The view and the shuffle (built: T0)

This is the only part that depends on no open question. Entries are opaque to it.

### 3.1 State of one store

- A view: at most `capacity` entries, no two with the same peer id, none for the node itself `[S: R:377 for capacity and
  the pair; P for the two invariants, which standard Cyclon also keeps]`.
- An entry is `{ id, d, age }`: `id` the peer's identity as bytes, `d` its descriptor as bytes (whatever a peer needs to
  reach and verify the other: section 4), `age` a count of ticks `[S: R:377 "(peer, age)"; P for the split]`.
- `shuffle_length` (the source's `l`) and `tick_ms`, per store `[S: R:377]`.
- Ages are whole numbers from 0 and stop at 65535 `[P]`: a 16-bit age is far above anything a live entry reaches (the
  oldest entry is the next partner), and a bound is needed for the wire (section 8).

### 3.2 One tick, at the initiator

1. Every age rises by one `[S: R:379]`.
2. The partner is the oldest entry `[S: R:380]`. Among several of the same greatest age, one is taken by a random draw
   `[P; the source does not say]`.
3. The outgoing buffer is the node's own entry at age 0 `[S: R:381]` and `shuffle_length - 1` other entries, chosen
   uniformly at random without replacement from the view without the partner `[P: this is Cyclon's own rule (Voulgaris,
   Gavidia and van Steen, 2005, cited from memory, not a project source); the SEMP text says only "standard Cyclon
   shuffles", R:361]`. With fewer entries than that, all of them go.
4. The partner's entry and the sent entries leave the view `[S: R:381 for the sent entries; P for the partner, as in
   Cyclon, where the node's own fresh entry takes the partner's place in the buffer]`. The node remembers them until the
   shuffle ends (3.4 step 4 and section 10 say what happens to them, `[B: OQ-12]`).
5. The node's own entry is included only in a store of the node's own type `[B: OQ-5]`.

### 3.3 At the partner

The partner picks up to `shuffle_length` of its entries at random, never the asker's own entry `[P, Cyclon]`, answers with
them, removes them from its view and merges what it received (3.4).

### 3.4 Merge

1. Entries naming the node itself are dropped `[P, Cyclon]`.
2. When the same peer appears twice (in what was received, or received and still in the view), the younger entry is kept
   `[S: R:382 "prefer younger entries"]`; at equal age the one the node already had `[P]`. A received entry is also
   compared with the entry of the same peer the node has just sent (3.2 step 4, 3.3): when the sent one is strictly
   younger it is kept in the received one's place, so a node does not give up fresher news of a peer for older; at equal
   age the received one stays, because it may carry a newer token `[B: NQ-16]`.
3. While the view is above capacity the oldest entry is evicted `[S: R:382]`. At equal age an entry the node already had
   is evicted before a received one, and among those the one latest in the view's order `[P; the source does not say. The
   reason: a shuffle exists to exchange entries.]`
4. In a store that is not of the node's own type, the partner that answered re-enters the view at age 0, by the rules of
   steps 2 and 3 (it was just reached) `[B: NQ-15]`. The reason: in such a store the node's own entry is not sent
   (3.2 step 5), so the partner cannot hold the node and nothing else would bring the link back; without this step the
   store loses one entry at every shuffle and a sentinel or a bridge forgets its edges. In the store of the node's own
   type the partner is not put back: there the partner holds the node's fresh entry, which is Cyclon's exchange.
5. If there is room afterwards, entries that were sent are put back, in the order they were sent `[B: OQ-12]`. After a
   shuffle that failed the partner is never put back, in any store (section 10).

### 3.5 Randomness

The view functions hold no generator. Each takes the draws it needs as a list of non-negative integers, and uses each as an
index modulo the number of candidates. In a node the draws come from the platform's secure source
(`bees_platform_random`, through the native edge that TRUST's tokens already use), seven bytes each, so the modulo bias for
at most 256 candidates is below 2^-47 `[B: standing ruling on random numbers; P for the form]`. In a trial the draws are
literals in the trial's source: an explicit test-only input.

### 3.6 The unit

`src/tempus/bees_tempus_view.silica`, plain Silica, no carrier, no actor, no atom of its own. Functions: `age_all`,
`select` (partner, sent, rest), `reply_select`, `merge`, `backfill`, `insert`, `remove`, `member`, `size`, `sample`, `valid`
(the invariants of 3.1, used on every view a trial prints and later on everything decoded), `outgoing`, `append`,
`prefer_sent` (3.4 step 2, NQ-16). Step 4 of 3.4 (NQ-15) is in the store's steps, `src/tempus/bees_tempus_store.silica`,
which knows whether a store is of the node's own type; `trials/t1_tempus_store` (part 3 of entry `steps`) shows a store
of another type keeping its three entries through twelve answered ticks, and `tools/test_bees_tempus_store.py` runs the
independent model for 500 rounds of a sentinel among edges. Trial:
`trials/t0_tempus_view`: 78 lines of hand-worked cases (the expected answer is in a comment beside each) and a run of eight
nodes for ten rounds (80 exchanges, capacity 4, shuffle length 3) with the invariants checked after every exchange.
`tools/test_bees_tempus_view.py` computes every line again with an independent Python model of the rules
(`tools/bees_tempus_view_model.py`) and compares it with the golden. Not yet shown: that `==` on identities holding
arbitrary bytes (not text) behaves as on text; T2 checks it with 64-byte identities.

## 4. Identity, descriptors and admission

- Identity: an Ed25519 key pair made on first run `[S: R:393]`, the node's TEMPUS identity key. The application stores the
  private key and passes its bytes, as it passes certificate and key bytes to TRUST `[B: N0c ruling 2]`; BEES keeps no copy
  outside the TLS engine and the signing call, and logs none.
- A node that also runs TRUST has two keys: its TRUST certificate key and, separately, its TEMPUS identity key
  `[B: OQ-22, OQ-14]`. Nothing in TEMPUS uses the TRUST key and nothing in TRUST uses the TEMPUS key.
- The TEMPUS certificate: self-signed over the TEMPUS identity key `[B: OQ-2]`; made by the application's tooling, passed
  as bytes. It is what a `tempus/1` TLS handshake presents, and, for a bridge or sentinel, what other nodes list in their
  `tempus` whitelist `[B: OQ-3]`.
- `peer_id`: 64 bytes, the SHA-512 of the 32-byte public key `[B: OQ-8]`.
- A bridge or sentinel is admitted by both checks `[B: NQ-4]`: its TEMPUS certificate is in the node's `tempus` whitelist,
  and it presents a token like any peer, whose `typ` must be `tempus_bridge` or `tempus_sentinel`. For such a peer the
  whitelist entry's permission spec replaces the per-type spec.
- The TLS certificate and the advert are bound: the public key of the certificate a peer presents in the `tempus/1`
  handshake must be the `pub` of its advert (the certificate is self-signed over the identity key). Without this the
  proof of possession would not tie the TLS channel to the peer `[P, a consequence of OQ-2; the engine call for it is
  in 17.6]`.
- Token `[B: OQ-7]`: an ETF map of the five fields and an Ed25519 signature over the map's exact bytes. The layout
  `[P, a detail of the specification]`: 64 signature bytes, then the payload, the external term (first byte 131) of
  `#{kid => <<1 to 64 bytes>>, sub => <<32 bytes>>, typ => tempus_edge | tempus_bridge | tempus_sentinel, nbf => Seconds,
  exp => Seconds}`, times in whole seconds since 1970 UTC. The signature is the producer's, made with the key `kid` names,
  over the payload bytes as they are; a verifier never re-encodes. Five keys are one more than the language's derived
  decoder reads on Apple Silicon (SD-37), so BEES walks the map structurally and decodes each value with the language's
  `decode`, as TRUST does for its request frame.
- Descriptor `d`: the advert of `R:429`, `{peer_id, peer_pub, token, typ}` `[S]`, plus the address the peer listens on
  `[B: OQ-15, every node is reachable]`. On the wire `typ` is read from the token, not repeated in the descriptor.
- A gossiped entry is admitted to a store only when its descriptor verifies without contact `[B: OQ-4]`: the token's
  signature under the current producer key, `kid` current, `nbf - skew <= now < exp + skew` `[B: OQ-16]`, `sub == pub`,
  `typ` equal to the store's type, `id` equal to the SHA-512 of `pub`. An entry is dropped when its token expires. Tokens
  travel in gossip, so a token must contain nothing secret.
- The clock of the token checks `[B: NQ-11]`. A node that is not externally driven (16.3) reads the system (wall) clock through the
  TEMPUS native edge (`bees_tempus_wall_clock` in `native/tempus/`: whole seconds since 1970 UTC, C11's `timespec_get`;
  an error of the operating system, or a time before 1970, is an error and never a made-up time). The node asks for a
  reading at start and every `clock_read_ms` afterwards (configured, section 11; its clock is in whole seconds), and its
  clock is the last reading, unless the configured choices of section 10 say otherwise for a reading that fails or is
  earlier than the node's time. It does not listen, join or tick before the first reading. The application passes no time of day to such a node. An
  externally driven node (16.3: a test program's node) never reads the system clock: it has no clock actor, and its
  readings are cast to it by its driver, the test unit, which gives it the test program's fixture value first and
  then what a `clock` frame says. It judges each such reading exactly as a reading of the system clock, by the same
  configured choices. What a reading that fails, and a reading earlier than the node's time, do is in
  section 10 (ruling NQ-22): each is a choice the configuration must make (`clock_fail`, `clock_back`).
- Proof of possession happens when two nodes connect, in both directions, on every connection: a 32-byte nonce from the
  platform's secure source, answered by the Ed25519 signature of `nonce || token` `[S: R:432-433; B: OQ-9]`. A peer that
  fails it is removed from the view `[B: OQ-4]`.
- Key rotation: one current producer key, by `kid` `[S: R:399]`, from configuration only `[B: OQ-10]`. A token under any
  other `kid` gets the one `key_rotated` frame. A running node takes a new key from its application, which passes the new
  `{Kid, PublicKey}` as it passes a new token `[B: NQ-5]`.
- Platform attestation is not a BEES concern `[B: inter-nodal-modes 5; S: R:405 places it at issuance]`.
- Where Ed25519 comes from: OpenSSL on the hosted platforms (checked 2026-11-18: OpenSSL 4.1.0 at
  `/opt/homebrew/opt/openssl` signs and verifies Ed25519). The boards' Mbed TLS has none (checked the same day in the local
  ESP-IDF copy, Mbed TLS 4.1.0: only the TLS signature-scheme constant and the PSA identifiers, no implementation), so the
  boards are not TEMPUS nodes in the first build `[B: NQ-6]`.

## 5. Wire messages

The sources define none; this section is the specification `[B: OQ-1]`. Following TRUST's wire `[B: D36, D12]`: mutual TLS
1.3 `[B: OQ-2]`, ALPN `tempus/1`, then frames of a 4-byte big-endian length and one ETF map, key `t` naming the message. One
request per connection `[S: R:11]`. No message has more than four keys and no nested record more than four fields, so the
language's own `decode((:etf), ...)` reads each whole frame into a typed record (SD-37). Unknown keys are refused. Maps are
written with keys in name order, as the language's encoder writes a record, so a frame has one byte form. Atoms on the wire
are only key names and the closed sets below; all are used in BEES's code, so every program holds them `[B: D16]`.

| Message | ETF form | Direction |
| --- | --- | --- |
| advert | `#{t => advert, ver => 1, d => D}` | both, first frame |
| descriptor `D` | `#{id => <<64 bytes>>, pub => <<32 bytes>>, addr => <<"host:port">>, token => <<bytes>>}` | inside others |
| challenge | `#{t => pop_challenge, nonce => <<32 bytes>>}` | both |
| response | `#{t => pop_response, sig => <<64 bytes>>}` | both |
| rotated | `#{t => key_rotated, kid => <<bytes>>}` | verifier to peer, then close `[B: OQ-10]` |
| shuffle | `#{t => shuffle, store => Typ, entries => [E]}` | initiator to partner |
| shuffle reply | `#{t => shuffle_reply, store => Typ, entries => [E]}` | partner to initiator, then close |
| entry `E` | `#{age => 0..65535, d => D}` | inside shuffle frames |
| sample | `#{t => sample, store => Typ, n => 1..shuffle_length}` | any admitted peer; a joiner to a sentinel (section 6) |
| sample reply | `#{t => sample_reply, store => Typ, entries => [E]}` | then close |
| call, cast, result | TRUST's frames, unchanged `[B: D36, OQ-13]` | edge to bridge (sections 7 and 17) |
| done | `#{t => done}` | the answer to the two frames of the test unit below, then close |

The frames of the test unit. They are no part of `tempus/1` as the library of `src/tempus` reads it: no unit there
decodes, answers or names them, and a program that does not list the test unit does not hold their atoms (owner's ruling
of 2026-11-20 on OQ-20; 16.3). They are specified here because the two clients send them to test programs:

| Message | ETF form | Direction |
| --- | --- | --- |
| tick | `#{t => tick, store => Typ}` | an admitted peer to a test program's node `[B: OQ-19, OQ-20]` |
| clock | `#{t => clock, ms => Milliseconds}`; `ms` -1 says the clock could not be read | the same |
| clock, two readings | `#{t => clock, ms => M, wait => W, later => L}`: the reading `M`, and `W` milliseconds (1 to 60000) after it is taken the reading `L` (either may be -1) | the same |

`Typ` is `tempus_edge`, `tempus_bridge` or `tempus_sentinel`. The advert carries no `typ` of its own: the type is the one
in the token `[P, a detail: one source of truth]`.

A connection: TLS handshake; the two adverts; the two challenges; the two responses; one request and its reply; close.
The order on each side, the same for both until the request `[P, a detail of the specification; built in T5]`: its own
advert at once; it reads the peer's advert and checks it (section 4), then sends its challenge; it reads the peer's
challenge and sends its response; it reads the peer's response and verifies it. The side that dialed then sends its
request. A side that answers `key_rotated` does not close at once: it reads and drops what the peer still sends until the
peer closes or the connection's bound passes, because closing with unread bytes resets the connection and the reset can
destroy the `key_rotated` frame before the peer has read it (the peer's challenge is usually on its way already).
Any violation closes without a reply `[S: R:17]`, with one audit line locally `[B: inter-nodal-modes 3]`; the one exception
is `key_rotated` `[B: OQ-10]`.

The two test-only requests exist only in a test program: one whose build lists the test unit
(`src/tempus_test/bees_tempus_test.silica` and its atoms) and which starts its node externally driven with that unit's
actor (16.3). Such a node listens on a loopback address only, the unit prints a boot banner, and the node takes no tick
from a timer of its own (so that a trial's ticks are exactly the ones a client sends) `[B: OQ-20; P for the last
clause]`. On any other node they are frames of no kind: the connection actor refuses them like any frame that is not a
request (`protocol_error`, `not a request: ...`), and the program holds no code that could do otherwise.

## 6. Joining and leaving

The sources say nothing about either; ruled `[B: OQ-6]`.

- Join. The configuration names one or more sentinels (`host:port`, each with its TEMPUS certificate in the `tempus`
  whitelist `[B: OQ-3]`). A starting node has a token from the producer (the application's job: BEES does not speak to the
  producer), connects to a sentinel, is admitted (section 4), and sends one `sample` request per store. The sentinel answers
  from its own stores and inserts the joiner into its store of the joiner's type. Every `sample` a sentinel answers
  does that, whoever asks (an admitted peer that asks is alive, and an insert of a peer already there only makes its
  entry younger); the sample is taken first and the insert follows, so a joiner is never answered with itself
  `[B: NQ-13]`. The joiner keeps the sentinel it joined through: when a sample was answered by a peer whose token says
  `tempus_sentinel` (its certificate is then one of the `tempus` whitelist, section 4), that sentinel's entry goes into
  the joiner's sentinel store at age 0, after the sample's entries `[B: NQ-12]`. A sentinel is not in its own stores, so
  without this a network with one sentinel leaves every node's sentinel store empty. The joiner's first tick then runs
  as usual. With no sentinel reachable the node keeps trying with explicit initial and maximum delays, no defaults
  `[B: user ruling 2026-11-17 on beam.redial; P that TEMPUS follows it]`.
- Token refresh. The application refreshes its token at half the lifetime `[S: R:400]` and hands the new bytes to BEES; the
  node's own entry carries the newest token from the next shuffle on. A node whose own token has expired stops ticking
  and tells its application (section 10); it goes on listening and answering `sample` and `shuffle`, with an advert
  whose token every correct peer refuses, and is whole again, with no restart of its listener, when its application
  passes a new token `[B: NQ-17]`.
- Leave. There is no leave message. A node that stops is forgotten as its entries age: it becomes some node's oldest
  entry, is chosen as partner, does not answer, and is removed (section 10); and its token expires within minutes.

## 7. TEMPUS and TRUST

Sources: bridges "bridge to separate TRUST overlays/instances"; "Application logic uses them to reach TRUST"
`[S: R:363-364]`. BEES: "a `tempus_bridge` peer is also a TRUST node with a whitelisted certificate. Bridging is application
logic" `[B: inter-nodal-modes 5]`; "TEMPUS decides who may be a member. TRUST decides what a member may do"
`[B: documents/semp.md]`.

Ruled `[B: OQ-13, OQ-14, OQ-22]`. A SEMP node runs TRUST, TEMPUS or both; "bridge" below is a node that runs both, with
TEMPUS role `bridge`:

| Who asks whom | Allowed | Security properties that apply |
| --- | --- | --- |
| edge to edge | shuffle only | TLS 1.3 both sides; producer token and proof of possession in place of the whitelist; no pins (an edge is not known in advance); no reconnect token; no suspicion state per edge `[B: OQ-2, OQ-12]` |
| edge to sentinel | admission, `sample`; shuffle of the edge's sentinel store | as above, and the sentinel's TEMPUS certificate must be in the edge's `tempus` whitelist `[B: OQ-3]` |
| edge to bridge | `call` and `cast` of an MFA, TRUST's frames; shuffle of the edge's bridge store | as above, the bridge's TEMPUS certificate in the edge's `tempus` whitelist; on the bridge the per-peer score and bounds (17.5), the forbidden guard `[B: N3]`, then a permission spec per peer type (`none` by default) in place of the per-fingerprint whitelist entry; call timeout; no error body |
| bridge to TRUST node | plain TRUST: `trpc` under the bridge's TRUST certificate | all of TRUST: mutual TLS, pin, whitelist, reconnect token, suspicion and quarantine `[B: D36, D43, D10]`. The TRUST node sees the bridge, never the edge |
| TRUST node to bridge | plain TRUST | all of TRUST |
| TRUST node to edge, bridge to edge | not provided | an edge may be gone or unreachable; an application that needs it has the edge poll |
| bridge to bridge, sentinel to sentinel | shuffle only | TLS both sides, token and proof of possession; each lists the others' TEMPUS certificates in its `tempus` whitelist `[B: OQ-3]` |

BEES forwards nothing by itself: an edge's call runs a function the bridge's application exported, and that function may
call onward with `trpc` `[S: R:364 "application logic"]`.

## 8. Bounds

Every bound is a literal in the code; a configured value may only be at or below the ceiling and is enforced at run time
before decode sees the bytes `[B: D47]`. The numbers are `[P]`, details of the specification.

| Value | Bound | Enforced where |
| --- | --- | --- |
| `id` | exactly 64 bytes | after decode |
| `pub` | exactly 32 bytes | after decode |
| `sig` | exactly 64 bytes | after decode |
| `nonce` | exactly 32 bytes | after decode |
| `kid` | 1 to 64 bytes | after decode |
| `addr` | 3 to 261 bytes (a 253-byte name, a colon, five digits); parsed by `bees_addr` before any dial `[B: D42]` | after decode |
| `token` | 65 to 1024 bytes: 64 signature bytes and a payload whose `kid` is 1 to 64 bytes `[B: OQ-7]` | after decode |
| `age` | 0 to 65535 | after decode |
| `n` of `sample` | 1 to the configured `shuffle_length` | after decode |
| entries in one frame | the configured `shuffle_length`; ceiling 64 | decode `max_length` ceiling, then the configured value |
| frame | ceiling 131072 bytes: 64 entries of at most about 1.5 KiB | `wireframe@unframe`, then decode `max_bytes` |
| nesting | 4 (frame map, list, entry map, descriptor map) | decode `max_depth` |
| view | the configured `capacity`; ceiling 256 per store | `bees_tempus_view@merge` evicts; `valid` checks |
| accepted connections at once | configured `inflight_max`; ceiling 64 | the listener refuses beyond it |
| time for a whole connection | configured `shuffle_timeout_ms`: ONE bound from the dial (on the accepting side, from the accept) to the close, not one per stage `[B: NQ-14]` | one deadline, fixed at the dial or the accept (`tempus_dial`, `tempus_conn` in `src/tempus/bees_tempus_link.part`; the listener for an accepted link); the carrier's connect budget, the link's handshake timer and the connection actor's timer each get what is left of it. While the node itself works on an admitted request (a tick frame's shuffle, a bridge's call) the connection waits for the node, which always answers: that wait is bounded by the node's own bounds (the shuffle's connection, the bridge's call timeout), not by this one |
| `ms` and `later` of the test unit's `clock` | -1 (no time) or 0 to 2^53; `wait` 1 to 60000 | after decode, in the test unit (`bees_tempus_test@dec_clock`); the library has no such frame |

Memory, worst case, at the ceilings: three stores of 256 entries of about 1.5 KiB are about 1.2 MiB; 64 connections with one
frame each are about 8 MiB; the sent entries of one shuffle in flight per store are 64 entries. Nothing is kept per peer
outside the views: no suspicion table and no token cache for edges, because the number of edges is unbounded.

## 9. Actors and their messages in Silica

`[P]`, engineering detail; the shapes follow TRUST's `[B: N3 section 1]`. Names avoid "socket" `[B: naming ruling 2026-11-05]`.

| Actor | Lives | Holds | Receives |
| --- | --- | --- | --- |
| `tstore`, one per store | the node's life | the view; phase (idle, shuffling); the entries sent in the shuffle in flight | `tick` (its own `send_after` `[B: D33]`); `draws` (from the random edge); `shuffle_done` with the partner's entries, or `shuffle_failed`; `incoming` (a partner's request: entries and who to answer); `insert` (an admitted peer); `sample` (the application or a joiner asks for `n` entries); `token` (the node's new token) |
| `tout`, one per outgoing shuffle | one connection | phase; the carrier; its store | carrier events; admission results; a timeout |
| `tin`, one per accepted connection | one connection | phase; the carrier | carrier events; admission results; the store's answer; a timeout |
| `tlsn`, the listener | the node's life | the count of live connections | accepted connections; `ended` |
| `tasm`, per frame | one frame | the reassembly record (SD-35) | segments |
| `tver`, per check | one check | nothing | a descriptor to verify or a signature to check; answers its asker. The Ed25519 call is in the native edge (`native/tempus/`, OpenSSL, hosted platforms only: NQ-6) |
| the random edge | TRUST's `trnd` reused | nothing | a request for `n` bytes |

How a store actor holds its view (measured 2026-11-18, T1): as a list in its state. SD-35 (an actor whose state holds a
heap value grows by about 1 MiB a dispatch) was measured on an earlier compiler and is why TRUST keeps a token as words. On
the pinned compiler (`silica-999909`, Apple Silicon) a call-style actor whose state is a record holding a view, replaced
at every message, stayed at the same committed memory from the 10th to the 3,000th message: 49 KiB for 20 entries of about
470 bytes, 1.0 MiB (high water 2.0 MiB) for the worst case of section 8, 256 entries of about 1.5 KiB, with a select, a
merge and an insert per message at 0.9 ms each. The compiler still reports W2300 (the whole state is copied at the end of
each dispatch), so the cost is proportional to the view; it does not grow. The trial `trials/t1_tempus_store` (entry
`actors`) checks on every run that a store actor's committed memory is the same after tick 40 and after tick 400, so a
compiler that brings the growth back fails the trial. To re-measure when the pin moves.

What is built of this table (T1): `tstore` as `src/tempus/bees_tempus_store_actor.silica` over the pure steps of
`src/tempus/bees_tempus_store.silica`. It asks its link for draws (two sets: one for its next tick, one for its next answer
to somebody else; each is used once; a tick with no tick draws is skipped and a request with no reply draws is refused, so
nothing is ever chosen without a draw), takes ticks as messages, and tells its link what to send and when a tick has
ended. It arms no timer itself: the node part (T3) does, or, for an externally driven node (16.3), nobody does: its
driver casts the node the timer's message.

What is built of this table (T3). The node actor is `tnode` in `src/tempus/bees_tempus_node.part`, pasted into the
program's root unit because it dials; it is also the listener's owner (`tlsn`: it counts the accepted connections and
gives one beyond `inflight_max` to a connection actor of role 3, which closes it when its link is up, one audit line
`inflight_refused`; the TLS handshake of such a connection is still done, because the link accepts before its owner
knows of it). `tout` and `tin` are the one connection actor of T5. Each store actor has a front, `tadp`
(`src/tempus/bees_tempus_node.silica.in`), which turns frame bodies into the store's typed messages and back, drops the
entries whose token has expired before every tick, answers the store's requests for draws (an externally driven node: from the literal
list; any other: random bytes through the node's converter, `dangerous_bees_tempus_draws@trc`, seven bytes a draw) and,
on an externally driven node, sends the node the view line before the message that follows a change. The node handles byte strings
only. A node that is not externally driven arms one `send_after` per store and has a clock actor
(`dangerous_bees_tempus_draws@tck`), which asks the native edge for the system clock at start and every `clock_read_ms` and
tells the node each reading (NQ-11; section 4); what the node does with a reading is decided by the pure
`bees_tempus_node@clock_turn` (NQ-22; section 10). The node's application is told when the node's
own token is not valid any more (the check is admission's own, `bees_tempus_admit@pre`, so ticking stops exactly when no
peer would admit the node), when a dialed peer answered `key_rotated`, when the system clock could not be read, and when the node stopped because the system clock went back by
more than its limit; it
passes a new token or a new producer key as a message (NQ-5). The connection actor tells the node of every refusal of
an accepted peer whose identity it knows (NQ-19; 17.5); only a bridge does anything with that.

## 10. Failure handling

- A partner that cannot be reached, closes early, times out or violates the protocol: its entry stays removed `[P,
  Cyclon]`; the other sent entries are put back `[B: OQ-12]`; one audit line; the store returns to idle and waits for the next
  tick. Nothing is retried within a tick.
- A tick that arrives while a shuffle is in flight ages the view and does nothing else `[P]`.
- An empty view: the tick does nothing in that store; the node asks a sentinel again (section 6).
- A received frame that breaks any bound of section 8, or an entry whose descriptor does not verify: the whole frame is
  refused, nothing from it enters the view, the connection closes with no reply `[S: R:17; P]`.
- An expired own token: the node cannot be admitted anywhere; it stops ticking and reports to the application, which owns
  the refresh (section 6).
- `key_rotated`: the node reports to the application, which fetches a new token `[S: R:400]`.
- A failed random request or a failed signature call: the tick is skipped, audited.
- The clock (the system clock's readings, or, for an externally driven node, its driver's: section 4 and 16.3) `[S: ruling NQ-22, both rulings of 2026-11-20]`. What the
  node does with a reading that fails after a good one, and with a reading earlier than its time, are two choices of the
  configuration, `clock_fail` and `clock_back`; how often the clock is read is `clock_read_ms`; none has a default
  (section 11). The decision is one pure function, `bees_tempus_node@clock_turn` (with `clock_back` inside it), so
  `trials/t0_tempus_clock` shows every case below with readings given as numbers; the node part (`tn_clock`) prints the
  lines and does what the function says, and `trials/t6_tempus_clock` shows that on running nodes: two test programs
  whose readings come from `clock` frames through the test unit (the hold beginning and ending; the wait for the clock
  with its line, the application told, a connection closed with `clock_refused`, the line when the clock is read again;
  going on with the last reading; a step back inside the limit followed; the stop above the limit with its line, the
  application told, a connection closed with `clock_stopped`, and no resume at a later good reading).
- The system clock cannot be read at start: this is not a choice. The node does not begin (it does not listen, join or
  tick), says so in one line, tells its application (86), and begins when a later reading succeeds.
- A reading fails after a good one, `clock_fail`:
  - `continue`: the node goes on with its last reading. It says so once (`clock: the system clock could not be read: the
    node goes on with its last reading`), tells its application (86), and keeps ticking and admitting; its time stands
    still until the next good reading, which it takes without a line. A token that expires while the clock cannot be
    read is still accepted for that long.
  - `pause`: the node says so once, tells its application (86), and until the clock is read again it does not tick (so
    it dials nobody) and closes every accepted connection at once with the audit line `clock_refused`; its time stands
    still and no token is judged by it. The next good reading is said in one line (`clock: the system clock is read
    again`) and the node goes on. A join request that falls due meanwhile (a retry timer, or the next store after an
    answer) is not dialed: the node remembers it, with one line, and dials it at once when the clock is read again
    (owner's ruling of 2026-11-20, option d of the join question; `tn_join`, `tn_clock_join`; shown by
    `trials/t6_tempus_clock`, node S: the retry falls due during the wait, its line, and the dial at once when the
    clock is read again).
- The system clock goes back (a reading earlier than the node's time), `clock_back`:
  - `follow`: the node follows it, with one line (`clock: the system clock went back by N s; the node follows it`). Its
    clock is the system's and it remembers no earlier one. What follows from that: a token that had expired by the old
    reading and has not by the new one is accepted again from then on, in a new connection or a newly received entry;
    nothing that already happened is undone (an entry dropped as expired stays dropped until it is gossiped again; a
    node that stopped ticking for its own expired token starts again only when its application passes a token).
  - `hold`: the node's time never goes back. It keeps its greatest reading, says once that it holds (`clock: the system
    clock went back by N s; the node holds its time until the system clock has reached it`), and goes on ticking and
    admitting by the held time; later readings that are still behind change nothing and print nothing. When a reading
    is equal to the held time or later, the node says one line (`clock: the system clock has reached the held time; the
    node follows it again`) and its clock is the system's again. No token comes back to life; a clock that was wrongly
    ahead and is corrected leaves the node refusing good tokens as not valid yet for as long as the error was large. A
    reading that fails while the node holds is handled by `clock_fail`; if the next good reading is still behind, the
    hold line is said once more.
  - `stop`: a step back of at most `clock_back_limit_s` seconds is followed as under `follow`. A larger one stops the
    node: one line (`clock: the system clock went back by N s, more than clock_back_limit_s L: the node has stopped; it
    admits no connection and does not tick until its application starts it again`), the application is told (87), the
    node's time stays at its last value, it does not tick, a waiting join retry dials nobody, and every accepted
    connection is closed at once with the audit line `clock_stopped` (role 5 of the connection actor, beside role 4 and
    `clock_refused` for the clock that cannot be read, so the two causes can be told apart). The node stays stopped
    whatever is read afterwards; only the application starting a node again ends it. Connections that were already
    admitted when the node stopped end by themselves within `shuffle_timeout_ms`.
- An externally driven node (a test program's, 16.3) reads no system clock, and all of these apply to it: every
  reading its driver casts it, the first value and each `clock` frame's, is judged by `clock_turn` with the node's
  configured choices, and a `clock` frame can say that the clock could not be read. Under `follow` a `clock` frame
  therefore sets the node's time to any value, with the node's one line when the value is earlier. What is still read
  from the code only: the clock actor's own path (the native edge's reading and the timer between readings), and a
  system clock that cannot be read at start.
- A cast to an ended actor fails the sender in Silica (SD-43), so the teardown order of a connection follows TRUST's: an
  actor ends only when nothing can still cast to it `[B: N2b teardown]`.

## 11. Configuration

The application reads the values through the `(:store)` carrier and passes them `[B: D46]`.

Which parts a node runs `[B: OQ-14, NQ-3]`: a node is a BEAM-mode node or a SEMP node, never both; a SEMP node runs TRUST,
TEMPUS or both, and `mode` says which, in the owner's spelling:

| `mode` | The node |
| --- | --- |
| `{mode, beam}` | a BEAM-mode node |
| `{mode, trust}` | a TRUST-only node (the default, as today) |
| `{mode, tempus}` | a TEMPUS-only node |
| `{mode, tempus-trust}` | a node that is both: with `tempus.role` `bridge` it is a bridge (section 17) |

`tempus-trust` is not an unquoted atom in Erlang term text (Erlang reads it as `tempus - trust`). How the reader accepts
it, chosen here and to be confirmed `[P]`: BEES's reader is its own (D26, D37), not `file:consult`, and it accepts, as the
value of `mode` and nowhere else, the bare spelling `tempus-trust` exactly as the owner wrote it; it also accepts the
quoted atom `'tempus-trust'`, which is the same atom in Erlang's own syntax, so a file can be kept readable by Erlang
tools by quoting it. Both mean the same; the documents show the owner's spelling. Inside BEES the mode is never a Silica
atom (a Silica atom cannot be spelled with a hyphen, and the generated accessor would need the name as an identifier):
the packer writes the mode into the store as the byte string of the same characters, and the node compares byte strings.
Nothing is renamed. A `tempus` section in a `{mode, trust}` file, or a missing one under `tempus` or `tempus-trust`, is
refused; `role` `bridge` needs `tempus-trust`.

The `tempus` section. Names and bounds are BEES's because SEMP names none. "None: required" follows the owner's rulings that
nothing here has a built-in default `[B: OQ-11, OQ-16, D39 R6, the redial ruling]`.

| Option | Type | Default | Bounds | Note |
| --- | --- | --- | --- | --- |
| `role` | `edge`, `bridge`, `sentinel` | none: required | closed set | the node's own type, and the `typ` its token must carry |
| `listen_address`, `port` | string, integer | none: required | as TRUST's | every TEMPUS node listens `[B: OQ-15]` |
| `sentinels` | list of `{Host, Port, CertName}` | none: required unless the node is the first sentinel | 1 to 16 | `[B: OQ-6]`; `CertName` names an entry of the `tempus` whitelist |
| `edge`, `bridge`, `sentinel` | each `{capacity, shuffle_length, tick_ms}` | none: required | capacity 1 to 256; shuffle_length 1 to 64 and at most capacity; tick_ms 100 to 3600000 | one per store `[S: R:377; B: OQ-11]` |
| `producer_key` | `{Kid, PublicKey}` | none: required | `Kid` 1 to 64 bytes, key 32 bytes | the one current key `[B: OQ-10]`; the application passes a new one to the running node as it passes a new token `[B: NQ-5]` |
| `identity_keyfile`, `identity_certfile` | paths or bytes `[B: N0c]` | none: required | Ed25519; the certificate self-signed over the key | the TEMPUS identity, never the TRUST one `[B: OQ-2, OQ-22]` |
| `whitelist_file`, `whitelist_cert_dir` | as TRUST's | none | as TRUST's | the `tempus` whitelist: TEMPUS certificates of the bridges and sentinels this node accepts, and what each may call `[B: OQ-3]` |
| `shuffle_timeout_ms` | integer | none: required | 100 to 60000 | one bound for a whole connection, from the dial or the accept to the close (section 8) `[B: NQ-14]` |
| `inflight_max` | integer | none: required | 1 to 64 | accepted connections at once |
| `clock_skew_ms` | integer | none: required | 0 to 300000 | `[B: OQ-16]` |
| `clock_back` | `follow`, `hold`, `stop` | none: required | closed set | what a reading of the system clock earlier than the node's time does (section 10) `[B: NQ-22]` |
| `clock_back_limit_s` | integer, seconds | none: required when `clock_back` is `stop`; refused under `follow` and `hold` | 0 to 86400 | the greatest step back that `stop` still follows; a larger one stops the node |
| `clock_fail` | `continue`, `pause` | none: required | closed set | what a reading that fails after a good one does (section 10) `[B: NQ-22]` |
| `clock_read_ms` | integer | none: required | 100 to 60000 | how often the system clock is read |
| `join_retry_initial_ms`, `join_retry_max_ms` | integers | none: required | 100 to 3600000 | section 6 |
| `edge_spec`, `bridge_spec`, `sentinel_spec` | `none`, `any`, or the per-module list, as `whitelist_default_spec` | `none` | closed forms | what an admitted peer of that type may call here `[B: OQ-13]` |

There is no `control_test_only` key (owner's ruling of 2026-11-20 on OQ-20). The key existed until that day and turned
the test-only frames on in any node. Now no configuration can: the frames are in a unit a production build does not
contain (16.3). `tools/bees_tempus_conf.py` refuses a file that holds the key, with either value, and says where the
test frames went. A test program needs no key: its own source starts its node externally driven.

The four clock values are required of every TEMPUS node. A test program's node uses three of them (`clock_back`, its
limit and `clock_fail` judge the readings its driver gives it; `clock_read_ms` is not used, because it has no clock
actor). The node is passed the
choices as numbers (`clock_back` 1 follow, 2 hold, 3 stop; `clock_fail` 1 continue, 2 pause) in the same record as
`clock_skew`, and its boot check refuses a number outside the set (`trials/c4_tempus_boot`, entry `dangerous_clockback`).
The node does not look at the limit unless the choice is `stop`.

Not configuration: the bridge's per-peer bounds (17.5) are values the bridge application passes when it starts the node
`[B: OQ-25]`; the node's own token is passed and replaced by the application at run time (section 6). There is no
`plaintext_test_only` for TEMPUS: no admission stand-in exists `[B: OQ-17]`.

## 12. What trials can test

| Subject | Kind of trial | Deterministic because |
| --- | --- | --- |
| view logic (T0) | one process, in memory, literal draws | no clock, no carrier, draws are literals |
| the store's steps and the store actor (T1) | one process: the pure step functions on literal inputs; then store actors exchanging through a driver that plays the wire, draws from a literal table | the driver steps one shuffle at a time |
| frames (T2, C1) | in memory: every frame written decodes back; hostile frames refused with the language's reason; the Python client's own codec writes the same bytes and reads them (tools test) | no carrier |
| admission (T4) | one process: fixed test keys and tokens made once by a tool, a fixed clock value as a test-only input | no real time in the checks |
| TLS (T5) | as `trials/n4_trust_tls` | fixtures |
| nodes (T3), clients (C2, C3), bridge (T6), the clock on running nodes (`trials/t6_tempus_clock`) | processes over TLS on loopback, test programs (externally driven nodes with the test unit, 16.3): ticks and the clock come from client frames, draws from a test-only list passed at start | fixed ports from the port table; a legitimate ordering race is post-processed in the Makefile as `trials/n2_mesh` does |
| properties (in-degree spread, removal of a dead node within a known number of ticks) | T1's driver with a fixed draw table | bounded and exact for that table, not statistical |

Not testable by a deterministic trial: uniformity of sampling at scale, behaviour under real churn, real clock skew, the
real timer tick. They are measurements (a soak, as `trials/n2_soak`), reported, not goldens.

## 13. Milestones

The order follows OQ-17 (admission and TLS before any networked node trial) and OQ-18 (all of it now).

| Order | | What | Closes when | Status |
| --- | --- | --- | --- | --- |
| 1 | T0 | The pure view logic of section 3: `src/tempus/bees_tempus_view.silica`, trial `trials/t0_tempus_view` | golden recorded after reading it against hand-worked expectations and an independent model | built 2026-11-18 |
| 2 | T1 | The store: its steps as pure functions (`bees_tempus_store`), the store actor, the measurement of how an actor can hold a view (SD-35) and the choice that follows | the step trial matches an independent model; a store actor's memory is flat over many ticks (measured); a population of store actors converges under a fixed draw table | built 2026-11-18 |
| 3 | T2 | Frames in Silica: every message of section 5 written and read, the bounds of section 8, hostile frames | goldens; flat memory over many refused frames, as N3 | built 2026-11-18 (memory read at one count only) |
| 3 | C1 | The Python client's codec (`example_tempus_clients/python/bees_tempus_client.py`), independent of the Silica one; the Silica client library's pure part (`example_tempus_clients/silica/`) | each side's bytes for every frame equal the other's, and each reads the other's | built 2026-11-18 |
| 4 | T4 | Admission: Ed25519 verify and sign and SHA-512 in the native edge (`native/tempus/`), the token check, proof of possession, `kid` pinning, expiry and skew, `key_rotated`; a tool that makes test keys and tokens | goldens for acceptance and for each refusal, in one process | built 2026-11-18: the rules, the native edge, the verifier actor, `trials/t4_tempus_admission` (the `key_rotated` frame itself is written by T3's connection actor; T4 gives the verdict) |
| 5 | T5 | Mutual TLS 1.3 with ALPN `tempus/1` and self-signed Ed25519 certificates; the `tempus` whitelist | as N4.1 | built 2026-11-18: the engine's three additions (`trials/t5_tempus_tls`), the TEMPUS link and the connection actor's admission with the channel binding and the whitelist (`trials/t5_tempus_link`, two processes over TLS on loopback) |
| 6 | T3 | Nodes over TLS on loopback: listener, connection actors, join through a sentinel, test-only ticks and clock (then `control_test_only`, since 2026-11-20 the test unit of 16.3); a three-node trial | goldens for join, shuffle, a dead partner, a hostile peer | built 2026-11-18: the node part (`src/tempus/bees_tempus_node.part`), the store adapters (`bees_tempus_node.silica.in`), the draw converter (`dangerous_bees_tempus_draws.silica`), `trials/t3_tempus_nodes` (three nodes and the Python client; port block 23800); NQ-11 to NQ-14 are open and built provisionally |
| 7 | C2 | Both clients as TEMPUS peers on the wire (dialing and listening); the thin Silica app; the rows of 16.2 that need no bridge | each such row has a trial from each client | built 2026-11-18, goldens 2026-11-19: `example_tempus_clients/silica/lib/bees_tempus_client.part`, `trials/c2_tempus_clients` (port block 23900) with `COVERAGE.md`; rows 12 "no proof", 18 "closes after the advert" and 20 from the Python client only (16.4) |
| 8 | T6 | The bridge node (section 17): TRUST and TEMPUS in one program, two keys, per-type spec, per-peer score and bounds from the application | goldens with an edge client, two bridges and a TRUST node | built 2026-11-19: `src/tempus/bees_tempus_bridge.silica` (the per-peer table and the per-request actor), `bees_tempus_bridge.part` (`tempus_bridge_start`, `tempus_bridge_onward`), the node's call and cast going to the bridge's table (`bees_tempus_node.part`), `tools/bees_tempus_gen.py bridge` and `spec`; `src/trust` unchanged; NQ-18 to NQ-20 |
| 9 | C3 | The clients against the bridge: the rest of 16.2 | every row of 16.2 has a trial from each client | built 2026-11-19: `trials/c3_tempus_bridge` (port block 24200) with `COVERAGE.md`; rows 29 and 33 and the quarantine of 17.7 from the Python client only |
| 10 | T7 | Configuration: the `tempus` section and the three `mode` spellings through the `(:store)` carrier, validation, the packer | when D46's store reader exists for TRUST | in part 2026-11-19: the node's boot refusals from its arguments (`tempus_node_boot`, `bees_tempus_node@boot_why`, `trials/c4_tempus_boot`, port block 24300), `tools/bees_tempus_conf.py` (the mode spellings and the `tempus` section, with tests); the store-carrier conversion waits on D46's reader (NQ-21) |
| 11 | T8 | Churn and soak measurements (hosted platforms; the boards are not TEMPUS nodes in the first build, NQ-6) | numbers recorded | not started |

## 14. Open questions for the project owner

Each has the options and a recommendation. A question the owner has ruled on carries a line beginning "RULED"; the others are not decided.

Rulings so far (2026-11-18): OQ-1 (a), OQ-2 (a), OQ-3 (a), OQ-4 (a), OQ-5 (a), OQ-6 (join a, leave a), OQ-7 (b), OQ-8 (a), OQ-9 (as recommended), OQ-10 (1a, 2a), OQ-11 (a), OQ-12 (a), OQ-13 (as section 7), OQ-14 (owner's own answer: a node can be both TEMPUS and TRUST), OQ-15 (a), OQ-16 (a), OQ-17 (b), OQ-18 (all TEMPUS now, in parallel), OQ-19 (owner's own answer, see there), OQ-20 (a), OQ-21 (c then a), OQ-22 (a node that is both, with two keys), OQ-23 (a, b and c; not d), OQ-24 (a), OQ-25 (owner's own answer: set by the bridge application, not BEES). All 25 are ruled; the follow-ups to OQ-19 are recorded there.

OQ-1. Which document is the TEMPUS specification? The reference has only the README section. Options: (a) this document's
sections 3 to 8 become the first TEMPUS wire specification, `tempus/1`, and are offered back to SEMP; (b) the owner writes
the SEMP specification first and BEES follows it. Recommendation: (a), reviewed by the owner section by section, because
BEES is the first implementation of SEMP and nothing else exists to follow.
RULED 2026-11-18 (owner): option (a): sections 3 to 8 of this document become the first TEMPUS wire specification, `tempus/1`, and are offered back to SEMP.

OQ-2. What secures a TEMPUS connection? `R:8` says TEMPUS uses "certificates, and mTLS"; the TEMPUS section describes only
Ed25519 keys, producer tokens and proof of possession; D12 says TEMPUS reuses TRUST's transport. Options: (a) mutual TLS 1.3
where each node's certificate is self-signed over its Ed25519 identity key (D43 already accepts self-signed Ed25519
certificates), plus the README's explicit challenge and response; (b) the same TLS, and the TLS handshake itself counts as
the proof of possession (the verifier checks that the certificate's key equals the token's `sub`), no challenge frames;
(c) no TLS between edges, only the token and the challenge. Recommendation: (a). It keeps the README's sequence literally,
keeps every SEMP connection on TLS 1.3 (`documents/semp.md`), and reuses the N4 engine. (b) saves a round trip and could
be adopted later by a ruling. A risk to check before T4, from memory and not verified: Mbed TLS, the boards' engine (D40),
may not provide Ed25519; if so, boards cannot be TEMPUS nodes until it does, or need another signature library.
RULED 2026-11-18 (owner): option (a): mutual TLS 1.3 with each node's certificate self-signed over its Ed25519 identity key, plus the README's explicit challenge and response. The Mbed TLS Ed25519 check for the boards is still to be done before T4.

OQ-3. What is SEMP's `tempus` whitelist for? `semp_whitelist.erl` keeps a second table, certificate fingerprint to
permission spec, for a `tempus` profile, and nothing uses it; ephemeral peers cannot be listed in advance. Options: (a) it
lists the certificates of the non-ephemeral TEMPUS peers (bridges and sentinels) a node accepts, with what each may call;
(b) it is unused and BEES has no TEMPUS whitelist; (c) it lists edges after all, for small closed deployments.
Recommendation: (a): an edge's pins for sentinels and bridges, and a bridge's or sentinel's whitelist of its own kind, use
the same file format as TRUST's whitelist.
RULED 2026-11-18 (owner): option (a): the `tempus` whitelist lists the certificates of the non-ephemeral TEMPUS peers (bridges and sentinels) a node accepts, with what each may call.

OQ-4. When is a peer "admitted", and who checks? `R:389` says a peer enters a store only after proving itself; the diagram
shows one verifier. Gossip hands a node entries for peers it has never met. Options: (a) an entry carries the peer's whole
advert; a receiver verifies the token offline and admits the entry; proof of possession happens at first contact and a
failure removes the entry; an entry dies when its token expires; (b) an entry enters a view only after the node itself has
connected to the peer and run the whole admission, so gossip yields candidates, not entries; (c) a sentinel signs a
membership statement that travels with the entry. Recommendation: (a). It needs no new signer and no extra connections,
and a stolen descriptor is useless without the key. It does mean tokens travel in gossip, so a token must contain nothing
secret.
RULED 2026-11-18 (owner): option (a): an entry carries the peer's whole advert; a receiver verifies the token offline and admits the entry; proof of possession happens at first contact and a failure removes the entry; an entry dies when its token expires. Tokens travel in gossip, so a token must contain nothing secret.

OQ-5. How does a node hold peers of another type when there is "no cross-type shuffle"? `R:375` gives every TEMPUS server
three stores; `R:364` says bridges shuffle only with bridges. An edge is not a bridge, so the source does not say how an
edge's bridge store is filled. Options: (a) a node shuffles each store with a partner taken from that store, and includes
its own entry only in the store of its own type (an edge exchanges bridge entries with a bridge without adding itself);
(b) a node shuffles only its own type's store, and fills the other two by `sample` requests; (c) an edge holds only an edge
store and learns bridges and sentinels from configuration. Recommendation: (a): entries of one type never enter another
type's store, every store stays fresh by the same mechanism, and each keeps its own tick as `R:377` says.
RULED 2026-11-18 (owner): option (a): a node shuffles each store with a partner taken from that store, and includes its own entry only in the store of its own type.

OQ-6. How does a node join and leave? Not in the sources. Options for join: (a) configured sentinels, admission, then a
`sample` per store (section 6); (b) Cyclon's own join by random walks from an introducer. Options for leave: (a) none,
entries age out; (b) a leave message. Recommendation: join (a), leave (a).
RULED 2026-11-18 (owner): join (a), configured sentinels, admission, then a `sample` per store; leave (a), no leave message, entries age out.

OQ-7. What is the token's format and signature? The source gives fields (`kid`, `sub`, `typ`, `nbf`, `exp`) and no
encoding; the names are those of JSON Web Tokens. Options: (a) a compact JWT signed with Ed25519: the producer can use
standard libraries, BEES needs a bounded base64url and JSON reader in Silica; (b) an ETF map of those five fields and an
Ed25519 signature over its exact bytes: BEES needs nothing new, the producer needs an ETF writer; (c) a fixed binary
layout. Recommendation: (b) if the producer service is the owner's to write, since BEES already checks ETF and a second
parser is a second attack surface; (a) if the producer must be an off-the-shelf service. The owner knows which.
RULED 2026-11-18 (owner): option (b): the token is an ETF map of the five fields with an Ed25519 signature over its exact bytes.

OQ-8. How is `peer_id` derived from the public key? Options: (a) the SHA-512 of the 32-byte key, as SEMP identifies
certificates by SHA-512; (b) the key itself; (c) the SHA-512 of the node's certificate DER, TRUST's identity exactly.
Recommendation: (a). The advert of `R:429` carries both `peer_id` and `peer_pub`, so they differ; (c) would change the
identity whenever the certificate is re-issued over the same key.
RULED 2026-11-18 (owner): option (a): `peer_id` is the SHA-512 of the 32-byte public key.

OQ-9. Details of the proof of possession. The source fixes the signed bytes (`nonce || token`). Open: the nonce's length;
whether both ends prove (the diagram shows one direction); whether the proof is per connection. Recommendation: 32 bytes
from the platform's secure source; both directions; every connection.
RULED 2026-11-18 (owner): as recommended: a 32-byte nonce from the platform's secure source; both directions; every connection.

OQ-10. Key rotation. (1) `R:399` says an old-key token is refused "with a precise 'rotated key' error", while `R:17` says
no errors go to clients. Options: (a) one explicit `key_rotated` frame carrying only the current `kid`, the single
exception; (b) silence, and a node refreshes its token after any refusal. Recommendation: (a), the TEMPUS text is specific.
(2) How does a verifier learn the current key? Options: (a) configuration only, a rotation is a configuration change on
every verifier; (b) sentinels distribute it; (c) nodes fetch it from the producer. Recommendation: (a) for the first
build; it needs a ruling on how a running node takes a configuration change, which D46 does not cover.
RULED 2026-11-18 (owner): (1) option (a): one explicit `key_rotated` frame carrying only the current `kid`, the single exception to silence. (2) option (a): the current producer key comes from configuration only; how a running node takes a configuration change still needs a ruling.

OQ-11. Defaults for capacity, shuffle length and tick. The source gives none. Options: (a) no defaults, each stated in the
configuration, as the owner ruled for the redial values; (b) defaults from the Cyclon paper (from memory: views of 20 to
50, shuffle length 3 to 8, a period of seconds). Recommendation: (a), with the bounds of section 11.
RULED 2026-11-18 (owner): option (a): no defaults; capacity, shuffle length and tick are each stated in the configuration, within the bounds of section 11.

OQ-12. A failed shuffle, and room after a merge. The source says sent entries are removed from the view and says nothing
more. Options: (a) the partner is dropped, the other sent entries are put back on failure, and after a successful merge
sent entries fill any room left; (b) sent entries are gone for good in both cases. Recommendation: (a). Under (b) every
failed shuffle shrinks the view by `shuffle_length` entries, and one unreachable partner per tick empties it. Related: no
suspicion or quarantine state is kept for edges (their number is unbounded and their identities cost an attacker nothing
beyond a token); bridges and sentinels, which hold certificates, could be scored as TRUST scores peers. Recommendation: no
edge scoring in the first build.
RULED 2026-11-18 (owner): option (a): on a failed shuffle the partner is dropped and the other sent entries are put back; after a successful merge, sent entries fill any room left. No suspicion or quarantine state for edges in the first build.

OQ-13. What may a TEMPUS node ask of a TRUST node, and the reverse? Section 7 is the proposal. The points needing a
ruling: an edge calls MFAs on a bridge with TRUST's frames; what an edge may call is a per-type permission spec, `none` by
default; the bridge never forwards by itself; nothing calls into an edge; edges do not call each other. Recommendation: as
section 7.
RULED 2026-11-18 (owner): as section 7: an edge calls MFAs on a bridge with TRUST's frames under a per-type permission spec, `none` by default; the bridge never forwards by itself; nothing calls into an edge; edges do not call each other.

OQ-14. How is a TEMPUS node configured, given that a node is a BEAM-mode node or a SEMP node? Options: (a) `mode` gains the
value `tempus` for an edge (no TRUST listener); bridges and sentinels are `mode trust` nodes with a `tempus` section and a
second listener; (b) `mode trust` for all, with `tempus.role`. Recommendation: (a): an edge has no whitelist and no
whitelisted certificate, so it is not a TRUST node.
RULED 2026-11-18 (owner): neither option as written. The owner's answer: "A node can be both tempus and trust." So TEMPUS and TRUST are not exclusive modes of a SEMP node: a SEMP node runs TRUST, TEMPUS, or both (the exclusion that stands is BEAM mode against SEMP). The configuration must let one node enable either or both; the spelling of that in `bees.config` (section 11) is to be redrafted to follow this ruling, and section 17's bridge (a node that is both) follows from it directly.

OQ-15. Addresses and reachability. Cyclon needs every node to accept connections; phones and browsers
(`documents/tempus.md`) usually cannot; the carrier dials IPv4 literals only (D42). Options: (a) every TEMPUS node,
edges included, has a reachable listen address, and one that has none cannot be a member; (b) edges behind address
translation relay through sentinels or bridges, a design that does not exist. Recommendation: (a) for the first build,
stated plainly in `documents/tempus.md`, and (b) recorded as later work.
RULED 2026-11-18 (owner): option (a): every TEMPUS node, edges included, has a reachable listen address in the first build; relaying is later work, to be stated in `documents/tempus.md`.

OQ-16. Clock skew for `nbf` and `exp`. Options: (a) an explicit configured allowance with no default; (b) a fixed 30
seconds. Recommendation: (a).
RULED 2026-11-18 (owner): option (a): an explicit configured clock-skew allowance with no default.

OQ-17. A test-only stand-in for admission in T3, before Ed25519 and TLS exist for TEMPUS, as the owner accepted for TRUST in
N3 (R5): the peer's first bytes are taken as its identity, on loopback only, with a boot banner. Options: (a) accept it
for T3; (b) build T4 and T5 first. Recommendation: (a).
RULED 2026-11-18 (owner): option (b): no admission stand-in. T4 and T5 (Ed25519 tokens, proof of possession, TLS for TEMPUS) are built before any networked node trial; the milestone order of section 13 is to be redrafted accordingly.

OQ-18. Order. D12 places TEMPUS after 1.0. Which of T1 to T8 are wanted before 1.0, and before or after N5?
Recommendation: T1 and T2 can proceed beside the other work once OQ-1, 4, 5, 7, 8 and 12 are ruled; the rest in order.
RULED 2026-11-18 (owner): all TEMPUS now, in parallel: TEMPUS is no longer held until after 1.0 (this changes D12's placement). All milestones T1 to T8 and the clients C1 to C3 proceed beside the other work as fast as the rulings allow.

OQ-19. What does a node expose for control, and to whom? The owner ruled (2026-11-18) that the clients drive the full
behaviour; the ruling does not name the interface. A Python program cannot call a Silica function, so some of the control
must be reachable over a transport. Options: (a) a control listener on a loopback address only, plaintext, ETF map frames,
off unless a port is configured; (b) the same frames over mutual TLS 1.3 to operator certificates the node pins, on any
address; (c) no listener in the library: control is a Silica interface only, and an application that wants it remotely
writes its own. Recommendation: the library always offers control as messages to one actor (section 16.3); BEES also
supplies a control-carrier unit an application may list, built first as (a) under `plaintext_test_only` for C2, then as
(b); a node that lists neither has no remote control.
RULED 2026-11-18 (owner): none of the options as written. The owner's answer: "The python client written completely in python that communicates with the TEMPUS&TRUST bridge node via TCP. No use of the silica library". So the Python client is pure Python, uses nothing of the Silica library, and its peer is the bridge node (a node that is both TEMPUS and TRUST, OQ-14), reached over TCP. Still to be ruled or designed: what protects that TCP connection (OQ-2 rules mutual TLS 1.3 for TEMPUS connections), and which frames the client uses to cause the behaviours that are not ordinary peer traffic (section 16.3).
RULED 2026-11-18 (owner), follow-ups: (1) the Python client's connection to the bridge is mutual TLS 1.3 as an ordinary TEMPUS peer: its own Ed25519 key, producer token and self-signed certificate, and the same frames a Silica node sends. (2) The Silica client is wire only, like the Python client: a separate program that connects to the bridge over the same transport and frames; it does not drive a node by actor messages. Consequence to design: the test-only tick and clock operations of OQ-20 must be reachable over that same wire (under `control_test_only`), since neither client has another channel; section 16.3 is to be redrafted.

OQ-20. Test-only control. Causing "each per-tick step" on demand, and token expiry without waiting minutes, needs a tick the
client triggers and a clock the client sets. Both would be dangerous on a real node. Options: (a) the two operations exist
only when the application passes `control_test_only`, loopback only, with a boot banner, as `plaintext_test_only`; (b) no
such operations: trials use short real ticks and real token lifetimes of seconds, and post-process timing. Recommendation:
(a): it keeps the trials deterministic, which is a standing rule.
RULED 2026-11-18 (owner): option (a): the test-only tick and clock operations exist only under `control_test_only`, loopback only, with a boot banner.
RULED (owner, 2026-11-20): option (a) is replaced. The owner saw that under (a) the handlers of the two frames were compiled into every node, a production node too, behind one flag, and ruled: "Move the test frames out of the library into a unit only test programs list in their build. A production build does not contain the handlers at all." Built the same day (16.3): the frames, their atoms, their decoders and what is done with them are in `src/tempus_test/bees_tempus_test.silica` (with `bees_tempus_test.atoms`), which is not among the units a production application compiles; the node has a narrow hook (it can be started externally driven, and then hands frames of no `tempus/1` kind to one extension actor); `control_test_only` is gone, as a start value and as a configuration key (the key is refused). The safeguards of (a) stay with the test unit: a loopback listen address only, and the boot banner. `trials/t6_tempus_clock` searches the compiled units and the linked program of a node built without the test unit and finds no trace of it, and shows that node refusing the frames as frames of no kind.

OQ-21. Where the thin Silica client app takes its operations from. Options: (a) a script of operations packed as ETF records
in a `(:store)` log, the ruled configuration source (D46); (b) the program's standard input, if Silica gives a program more
than `wait_for_exit` (not checked yet); (c) one compiled-in scenario per trial role, as the TRUST trials do. Recommendation:
(c) for C2, because it needs nothing unproven, and (a) when D46's reader is built.
RULED 2026-11-18 (owner): option (c) for C2, one compiled-in scenario per trial role, and option (a), a `(:store)` script, when D46's reader is built.

OQ-22. What kind of node is a bridge? The owner ruled that bridges exist (section 17); the README says only that they are
longer-lived TEMPUS peers that bridge to TRUST. Options: (a) a TRUST node (`mode trust`, a whitelisted certificate, TRUST's
listener) that also runs the TEMPUS side with role `bridge`, as inter-nodal-modes 5 already says; (b) a TEMPUS node that
holds a TRUST client identity only (it can call TRUST nodes, nothing in TRUST calls it); (c) a third mode. And: one key for
both sides (the certificate is over the Ed25519 key the producer token names) or two. Recommendation: (a), with one key, so
that the bridge has one identity an operator can pin, whitelist and quarantine.
RULED 2026-11-18 (owner): a bridge is a node that is both TEMPUS and TRUST (OQ-14), with TWO keys, not the recommended one: a TRUST certificate key and a separate TEMPUS identity key (the Ed25519 key its producer token names). Sections 17 and 4 are to be redrafted for two identities per bridge.

OQ-23. How is TRUST protected from what edges do through a bridge? A TRUST node sees only the bridge's certificate, so every
refused or failing request an edge causes there raises the bridge's suspicion, and a quarantined bridge stays out until an
operator resets it (D10). The sources say nothing. Options, which combine: (a) the bridge forwards nothing by itself: an
edge can only run functions the bridge's application exported, and those decide what goes onward (already section 7);
(b) the bridge scores each admitted peer (by `peer_id`, in a table bounded by a literal ceiling, an entry dropped when the
peer's token expires) with TRUST's rules, and refuses a peer above the limit; (c) the bridge bounds each peer's rate and
its requests in flight; (d) the bridge passes the edge's `peer_id` onward so the TRUST node can score the edge and not the
bridge, which would change TRUST's wire. Recommendation: (a), (b) and (c); not (d). A new identity costs an attacker a new
producer token, so the producer's issuance is the last limit, and that should be said in `documents/tempus.md`.
RULED 2026-11-18 (owner): options (a), (b) and (c): the bridge forwards nothing by itself; it scores each admitted peer in a bounded table with TRUST's rules; it bounds each peer's rate and requests in flight. Not (d): TRUST's wire is unchanged.

OQ-24. Who chooses a bridge, and what happens when it is lost? Options: (a) BEES gives the application a sample of its
bridge store and the application picks and calls; a failed call returns `closed` (as `trpc` does) and removes that bridge's
entry; BEES does not call another bridge by itself, because a request may not be safe to repeat; (b) BEES picks at random
and retries on another bridge up to a configured count. Recommendation: (a), plus one library function that picks one
bridge by a random draw for applications that want no policy.
RULED 2026-11-18 (owner): option (a): the application picks a bridge from a sample of its bridge store; a failed call returns `closed` and removes that bridge's entry; BEES does not retry on another bridge; plus one library function that picks one bridge by a random draw.

OQ-25. Numbers for the bridge's bounds (requests per peer per interval, requests in flight per peer and in total, the size
of the scoring table). The sources give none. Recommendation: explicit configuration with no defaults, with literal
ceilings in the code, as for the other TEMPUS options.
RULED 2026-11-18 (owner): neither option. The owner's answer: "Set by the bridge application, not BEES." The bridge's bounds (rate per peer, requests in flight, scoring-table size) are values the bridge application chooses and passes to BEES; BEES has no defaults and no configuration options of its own for them. Whether BEES keeps literal ceilings above the application's values (the D47 pattern for decoded sizes) is for the redraft of section 17 to state.

## 15. Edits this design needs in existing files (not made, except the port table)

- `development-plan/roadmap.md`: D12's row and the "Post-1.0" list: TEMPUS is no longer after 1.0 (OQ-18); a decision row
  for the 25 rulings of 2026-11-18, pointing here; a row each for the new questions of section 18 when ruled.
- `development-plan/inter-nodal-modes.md` section 5: point to this document; "a `tempus_bridge` peer is also a TRUST node
  with a whitelisted certificate" stays true, and gains "with a separate TEMPUS identity key" (OQ-22).
- `development-plan/bees-config-file.md`: the `tempus` section of section 11 here, and the statement that a SEMP node runs
  TRUST, TEMPUS or both (OQ-14), once NQ-3 is ruled.
- `development-plan/mvp.md` section 5: rows for T0 to T8 and C1 to C3 in the order of section 13.
- `development-plan/silica-defects.md`: the `len()` entry (SD-48, text in tempus-progress.md); the coordinator adds it.
- `documents/tempus.md`, `documents/semp.md`, `README.md`: "planned for after the first release" is no longer true
  (OQ-18); a sentence that every TEMPUS node must be reachable in the first build (OQ-15); a sentence that the producer's
  issuance is the final limit on hostile edges (17.5).
- `Makefile` (top level): `python3 tools/test_bees_tempus_view.py`, `test_bees_tempus_store.py` and
  `test_bees_tempus_client.py` in the tools-test list.
- For T4, the build wiring of the TEMPUS native edge (the C is written and self-tested: `native/tempus/`):
  - `native/Makefile`: an archive `libsilica_bees_tempus.a` from `tempus/*.c`, the same five lines as the TRUST archive
    (`TEMPUS_SRCS`, `TEMPUS_OBJS`, `TEMPUS_ARCHIVE`, the pattern rule with `-I$(OPENSSL_PREFIX)/include
    -I$(THIS_DIR)tempus`, a `clean-tempus`), built only when `OPENSSL_PREFIX` is set and never for the boards; and a
    `tempus-selftest` target that builds and runs `tempus/selftest/bees_tempus_selftest.c` with `-lcrypto`.
  - `tools/trial.mk`, in the link step beside the two existing `case "$$archives"` lines: `case "$$archives" in
    *libsilica_bees_tempus.a*) archives="$$archives $(OPENSSL_LIBDIR_FLAGS) -lcrypto";; esac`.
  - a sidecar for the four foreign functions under `native/dangerous_exposure_source/tempus/` (a wrapper header and
    `.meta`, as `dangerous_exposure_source/trust/`); the TEMPUS work can write these new files once the form of the
    `.meta` for a pointer-and-length argument and a bytes result is confirmed against the TRUST one.
- `tools/trial_ports.py`: a block per TEMPUS trial that binds a port (the first is T3); this file may now be edited by the
  TEMPUS work, adding only.
- `.gitignore`: `!trials/t4_tempus_admission/dangerous_exposure_source` (the leaf's link to the native sidecar, as the other
  leaves that read one). Nothing for T0 to T2 and C1 (plain leaves). T3's node leaves will need the same block of rules as
  `trials/n3_trust`.

## 16. The clients (owner requirement and rulings, 2026-11-18)

Decided by the owner `[B: requirement of 2026-11-18; OQ-19 with its follow-ups; OQ-20; OQ-21]`:

1. A client that can drive a TEMPUS node is required, written in Silica, and a second one written completely in Python.
2. "Drive is to be the full behavior": both clients must be able to exercise every behaviour of a TEMPUS node. A behaviour
   neither client can reach is a gap in the design. Trials use the clients to cover the list.
3. Both clients are wire only. Each is an ordinary TEMPUS peer: its own Ed25519 key, a producer token, a self-signed
   certificate, mutual TLS 1.3 over TCP, and the same frames a node sends. Neither drives a node by actor messages, and
   the Python client uses nothing of the Silica library. Their peer is the bridge node, a node that is both TEMPUS and
   TRUST.
4. The Silica client is a separate program: a source-only library (units an application lists by path in its own
   `silica.config`, one compiler run, values passed in, no file reads of its own) and a thin app that only wires the
   library to its inputs and outputs. The thin app's operations are compiled-in scenarios, one per trial role, until D46's
   reader exists; then a `(:store)` script.
5. The test-only tick and clock operations exist, loopback only, with a boot banner; they travel on the same wire,
   since no other channel exists. First ruled "only under `control_test_only`"; since the ruling of 2026-11-20 they
   exist only in a program whose build lists the test unit (16.3).

### 16.1 What a client is

An admitted peer, in two positions:

- Dialing: it connects to the node, is admitted, and sends one request: `shuffle`, `sample`, `call`, `cast`, or, to a
  test program's node, `tick` or `clock`.
- Listening: as an ordinary peer it has a listen address (OQ-15), so the node dials it: for the node's own shuffles when
  the client's entry is the oldest, and, when the client's token says `tempus_sentinel`, for the node's join. The client
  then sees exactly the frames the node writes and chooses what to answer.

The type of a client is the `typ` of its token; the trial's test producer key signs tokens of any type. In either position
a client may misbehave on purpose (a wrong signature, an expired token, an oversize frame, silence): that is how every
refusal and failure path is reached. No operation puts an entry into a view without admission: a client fills a node's
view the way any peer does, by shuffling entries whose descriptors verify.

What a client can observe is what the wire shows: the frames it receives, a close, a timeout. What only the node knows (its
whole view after a step, the reason of a refusal) is in the node's own output, which every trial records as that node's
golden beside the client's. There is no test-only frame that returns a node's whole view: trials read the node's own output for what a client cannot
observe `[B: NQ-1]`. The clients work against any TEMPUS node; trials use the bridge node as the node under test wherever
the row allows `[B: NQ-2]`.

### 16.2 The behaviour list, and how each client causes and observes each item

Both clients have the same operations, so one column serves both. "Node output" means the node's own lines in the trial
(audit lines, and for a test program's node one line per view change).

| # | Behaviour of the node (source) | How a client causes it | How it is observed | From |
| --- | --- | --- | --- | --- |
| 1 | Starts with three isolated stores, each with its own capacity, shuffle length and tick `[S: R:350, R:375-377]` | the trial starts the node | node output at boot; `sample` on each store answers from that store only | T3 |
| 2 | Joins through a sentinel: admission, then a `sample` per store (section 6) | a client with a sentinel token listens at the address the node's configuration names | the client receives the advert, the proof and the three `sample` frames; a later `sample` to the node returns entries the client answered with | C2 |
| 3 | Leaves: stops; others forget it (section 6) | the trial stops a node; the client sends `tick` to a second node until the stopped one is the oldest | the second node's shuffle to it fails; `sample` no longer returns it; node output | C2 |
| 4 | Tick step 1: every age rises by one `[S: R:379]` | `tick` | the ages in the next `shuffle` frame the listening client receives, and in node output | C2 |
| 5 | Tick step 2: the partner is the oldest entry `[S: R:380]` | the client shuffles in entries of chosen ages, listening at each entry's address, then `tick` | the listener at the oldest entry's address is the one dialed | C2 |
| 6 | Tick step 3: the buffer holds the node's own entry at age 0 and `shuffle_length - 1` others; they leave the view `[S: R:381]` | as 5 | the listening client reads the `shuffle` frame; node output | C2 |
| 7 | Tick step 4: merge prefers younger entries and evicts the oldest `[S: R:382]` | the listening client answers with entries it chose (a duplicate younger, a duplicate older, more than fit) | node output; later `shuffle` and `sample` frames | C2 |
| 8 | Shuffle as responder (3.3) | the client dials and sends `shuffle` | the `shuffle_reply`; a later `sample` returns the client at a low age | C2 |
| 9 | Each of the three stores, and no mixing `[S: R:369, R:383]` | rows 4 to 8 once per store; a `shuffle` naming one store with an entry whose token has another type | per-store frames; the mixed frame is refused (close, no reply) and node output shows no change | C2 |
| 10 | A store of another type than the node's: shuffled without the node's own entry `[B: OQ-5]` | the client, with a token of that other type, listens and is dialed for that store | the `shuffle` frame has no entry for the node | C2 |
| 11 | Admission accepted: token (`kid` current, signature, `nbf`, `exp`, `sub`, `typ`), then proof of possession `[S: R:430-435]` | the client dials with a good advert and answers the challenge | the node's advert and challenge arrive, and the request is answered | C2 |
| 12 | Admission refused, each cause: wrong signature, expired, not yet valid, `sub` not the key, `typ` not allowed, `id` not the key's hash, wrong proof, no proof | the client sends that advert or that response | the connection closes with no reply; node output has the audit line | C2 |
| 13 | Rotated key: a token under another `kid` gets `key_rotated` `[S: R:399; B: OQ-10]` | the client presents a token under the old test key | the `key_rotated` frame | C2 |
| 14 | The node proves itself to the peer | the client challenges the node | the client verifies the node's signature over `nonce || token` | C2 |
| 15 | The node's own token: refresh, and expiry `[S: R:400]` | refresh is the node application's act (its compiled-in scenario does it); expiry: `clock` past the node's token | the next `shuffle` frame carries the new token; after expiry the node's advert is refused by the client's own check and node output says it stopped | C2 |
| 16 | Entries whose token expired leave the view `[B: OQ-4]` | `clock` past an entry's expiry, then `tick` | the entry is in no later frame; node output | C2 |
| 17 | A gossiped entry that does not verify: the whole frame is refused (section 10) | the listening client answers a shuffle with one bad entry among good ones | none of them appears in later frames; node output | C2 |
| 18 | Partner unreachable, closes early, silent until the timeout, or violating: partner dropped, sent entries put back `[B: OQ-12]` | the client does not listen; closes after the advert; stays silent; sends a wrong frame | `done` arrives after the failure; later frames; node output | C2 |
| 19 | Bounds: oversize frame, too many entries, an age above 65535, wrong field lengths, unknown key, nesting too deep (section 8) | the client sends each | closed with no reply; node output; the node's memory flat over many (measured) | C2 |
| 20 | More connections than `inflight_max` | the client opens that many and one more | the last is refused; the others are served | C2 |
| 21 | A tick during a shuffle in flight only ages (section 10) | the listening client holds the shuffle open; a second connection sends `tick` | no second dial; ages one higher in the next frames | C2 |
| 22 | An empty view: the tick does nothing in that store and the node asks a sentinel again | `tick` on a fresh node | the client listening as the sentinel is dialed | C2 |
| 23 | `sample` as a peer request | the client sends `sample` | the reply's entries; the view is unchanged (a second `sample` with the same draws answers the same) | C2 |
| 24 | Application requests on a bridge: `call`, `cast`, the forbidden guard, the per-type permission, the timeout, no error body (sections 7, 17) | the client sends TRUST's frames after admission | the `result`, or a close with no reply; node output | C3 |
| 25 | The bridge's function calls onward into TRUST | the client calls that function | the result that came back through the TRUST node | C3 |
| 26 | TLS: only TLS 1.3, ALPN `tempus/1`, a peer with no certificate or a certificate that is not self-signed over an Ed25519 key refused `[B: OQ-2]` | the Python client offers TLS 1.2, another ALPN, no certificate (as `tools/run_tls_refusals.py` does for TRUST); the Silica client covers the accepted case | handshake failure; node output | C2 |
| 27 | Draws come from the platform's secure source | not caused by a client: a test node takes a list of draws at start (3.5) | two runs of a trial give the same frames | T3 |
| 28 | Boot refusals of a bad `tempus` configuration | not a running node: the trial starts it | boot lines, as `trials/n3_trust` boot_missing | T7 |
| 29 | A node learns bridges: its bridge store fills and stays fresh (17.3) | clients with bridge tokens listen; `tick` on the bridge store | the listening clients are dialed; `sample` on the bridge store | C3 |
| 30 | An application gets a bridge to use `[B: OQ-24]` | the edge node's compiled-in scenario asks; a client asks by `sample` | one of the live bridges | C3 |
| 31 | A call crosses a bridge and the answer returns | the client, admitted as an edge, sends `call` to the bridge | the `result`; the TRUST node's output shows the request came under the bridge's TRUST certificate | C3 |
| 32 | Several bridges: any of them serves | the client calls through each in turn | the same result from each | C3 |
| 33 | A bridge is lost: its entry goes and another is used `[B: OQ-24]` | the trial stops one bridge; the client calls, then samples again | `closed` once; the entry is gone from later samples; the next call succeeds through the other | C3 |
| 34 | The bridge refuses an edge that misbehaves, without touching TRUST `[B: OQ-23]` | the client sends forbidden, unpermitted and malformed requests until the bridge's limit | closed with no reply each time; then even a good request is refused; bridge output; the TRUST node's output shows the bridge's suspicion unchanged | C3 |
| 35 | The bridge's rate and in-flight bounds per peer, set by the bridge application `[B: OQ-25]` | the client sends faster than the bound; holds more calls open than the bound | the excess is refused; another admitted client is still served | C3 |
| 36 | The TRUST side of a bridge is plain TRUST | the trial's TRUST node does; not a TEMPUS client operation | the TRUST trials' own lines | T6 |
| 37 | Test-only frames on a node built without the test unit (16.3) | the client sends `tick` and `clock` to an ordinary node | closed with no reply; node output: `protocol_error ... not a request`, as for any frame of no kind | C2 (node O, `tick`), `trials/t6_tempus_clock` (node P, whose build lists no unit of the test unit: `tick` and both `clock` forms) |

Rows 27, 28 and 36 are not reachable by a TEMPUS client by their nature (they happen before or outside a running node's
`tempus/1` interface); trials cover them directly. Rows whose observation rests on node output are read from the node's golden
`[B: NQ-1]`.

### 16.3 The test-only operations on the wire, and the test unit

There is no control interface `[B: OQ-19]`. The two test-only requests of section 5 are ordinary requests of an admitted
connection:

| Request | Effect | Reply |
| --- | --- | --- |
| `#{t => tick, store => Typ}` | one tick of that store, as the timer would cause | `#{t => done}` when the shuffle the tick started has ended (succeeded, failed or timed out), or at once when the tick started none |
| `#{t => clock, ms => N}` | a clock reading for the node: `N` milliseconds since 1970, or -1, the clock could not be read. The node judges it as it judges a reading of the system clock, by its configured `clock_back` and `clock_fail` (section 10) | `#{t => done}` when the node has taken the reading |
| `#{t => clock, ms => N, wait => W, later => L}` | the same, and `W` milliseconds after the reading is taken a second reading `L` | `#{t => done}` when the node has taken the first reading |

The third form exists because a node that waits for its clock (`clock_fail` `pause`) closes every connection: the reading
that ends the wait cannot arrive in a frame, so the frame that begins the wait carries it.

Where they are `[B: OQ-20, the owner's ruling of 2026-11-20]`. Not in the library. Until that ruling the handlers were
in the node part behind a start value `control_test_only`, so every node, a production node too, held them. Now:

- The test unit is `src/tempus_test/bees_tempus_test.silica`, with its atoms in `src/tempus_test/bees_tempus_test.atoms`.
  It holds everything of the two frames: the atoms `tick`, `clock`, `ms`, `wait`, `later`; the encoders the Silica
  client's scenarios use; the decoders; the actor that acts on them; the banner; the loopback check.
- `src/tempus_test` is not among the units a production application compiles. An application lists the units of
  `src/tempus`; it must not list `src/tempus_test`. (The two clients of 16.4 and 16.5 are examples, in
  `example_tempus_clients/` since 2026-11-20, and are not for production: an application that is a client writes its
  own, see `example_tempus_clients/writing-a-tempus-client.md`.) A test program does:
  one more unit and one more atoms file in its build (in a trial: two links in `lib/`, and `--use bees_tempus_test`
  for the generated root unit).
- No unit of `src/tempus` or `example_tempus_clients/silica` decodes, answers or names a `tick` or a `clock` frame, with any start
  value. `bees_tempus_frame@kind` gives such a frame 0, as for any `t` that is no kind.

The hook in the node. The node's last start argument is `drv`, `{ driven, ext, draws }`. A production application passes
`driven` false, and `ext` and `draws` are then never read. With `driven` true the node is externally driven:

1. It starts no clock actor and arms no store timer. It waits for the messages those would send: a clock reading
   `(:bees, 130, "", "", Seconds or -1, Tag, Who)` and a tick of a store `(:bees, 1, "", "", Tag, Store, Who)`. Nobody
   sends them by itself, so an externally driven node that nobody drives never gets a first reading and never
   listens.
2. Its draws are the literal list `draws` and it prints one line per view change (as a node under the old flag did).
3. Once, at its start, it tells the actor `ext` who it is and its listen text (133).
4. A frame from an admitted peer, as the one request of an accepted connection, that is well formed (one ETF map inside
   the structural bounds, at most 131072 bytes) and whose `t` is an atom the program holds that is no kind of
   `tempus/1`, is handed to `ext` unread (68, with the peer's descriptor and the connection actor). `ext` answers the
   connection actor once: a reply body, a close, or "refuse it as you would" (22), which gives the same audit line and
   the same score at a bridge as on a production node.
5. When a tick or a reading that carried a tag has ended or is taken, the node tells `ext` (131, 132), handing back the
   actor reference that came with it. This is how the `done` of a tick is sent when the shuffle has ended, as before:
   the test unit casts the tick with the connection's number as the tag and the connection actor as the reference,
   and answers `done` when it is told 131.
6. `tempus_node_boot` refuses `driven` on a listen address that is not loopback.

What the hook lets an application do, and what it does not. With `driven` false: nothing; no frame leaves the library,
`ext` is never read, the connection actor refuses a frame of no kind itself, and messages 130 and 1 behave as the clock
actor's and the timers' own (a tag is ignored). An application always could cast any message to its own node, since it
holds the node's actor reference: that is so with or without this hook, and such a cast comes from the application's
own code, never from the network. With `driven` true, on a loopback listener only: the application's actor sees, and
answers, frames of no `tempus/1` kind from peers that were admitted (token and proof of possession checked), one per
connection; it sets the node's clock readings and causes ticks. It cannot see or change a frame of a known kind, see
anything from a peer that was not admitted, reach a store, or lift a bound. A production application could misuse the
hook only by choosing to: it would have to pass `driven` true, listen on loopback only, and supply both the clock and
the ticks itself; the literal draws would then make its shuffles predictable, as they are meant to be in a trial.

The test unit, as that actor. `bees_tempus_test@start(Now)` gives the actor for one node; the test program passes it as
`ext`. When the node has introduced itself the unit checks the node's listen text (loopback, or it prints `TEST ONLY
refused: ...` and gives no reading, so the node never listens), prints the banner `TEST ONLY: tick and clock frames are
accepted`, and gives the node its first reading, `Now`, the trial's fixture. A loopback listener is reached from the
same machine only, so the frames it is handed come from loopback peers. Everything else a client does (join as
sentinel, shuffles, samples, calls) uses the frames every node uses.

A node that is not externally driven reads the system clock (section 4, `[B: NQ-11]`) and ticks by its timers.

### 16.4 The Silica client

Moved 2026-11-20 (owner): both clients are in `example_tempus_clients/` (`silica/` and `python/`), out of `src` and
`tools`. They were examples only, not for production; since 2026-11-24 (owner) they are usable examples, to be used
carefully, and `example_tempus_clients/README.md` says what care means;
`example_tempus_clients/writing-a-tempus-client.md` says what a client in any language has to do.

- Library, `example_tempus_clients/silica/lib/` (in `silica/` itself until the division of 2026-11-20, 16.7): `bees_tempus_client` (pure: for every operation of 16.2 the frame to send and the reading
  of the reply, over the node's own frame unit `bees_tempus_frame`; also the deliberately wrong frames, each by a named
  function) and, from C2, `dangerous_bees_tempus_client` (the active part: one actor per connection, dialing or accepting
  through the language's carrier and the TLS link, running admission, sending one request, handing the typed reply to the
  actor the caller named; a `dangerous_` unit because it spawns a carrier). It reads no file: addresses, key bytes, token
  bytes and draws are arguments `[B: N0c, D46]`.
  Built in C2 `[P, forced by the language: the carrier's spawn site stays in the root unit (SD-17) and a root unit may not
  call a function of a dangerous_ unit (E4042)]`: the active part is not a unit but `example_tempus_clients/silica/lib/bees_tempus_client.part`,
  pasted into the application's root unit by `tools/bees_tempus_gen.py` as the node part is. Each connection is the node's
  own connection actor (`dangerous_bees_tempus_conn@tcon`), so the client and the node share one implementation of
  admission; the Python client is the independent one. Functions: `tempus_client_start(app, ci)`, `tempus_client_dial`,
  `tempus_client_set` (the token, peer id, clock, kid, public key or whitelist for the connections that follow: the way
  to every refusal of row 12), `tempus_client_answer` and `tempus_client_close` (the listening position: the application
  is handed each admitted peer's request and answers it when it chooses). What this client cannot do on purpose, because
  the connection actor has no such switch: leave out its proof, stay silent or close before its request, hold a
  connection open before its advert (rows 12 "no proof", 18 "closes after the advert", 20). The Python client does those.
- Thin app: an entry unit that calls the library per its compiled-in scenario and prints each reply as one line
  `[B: OQ-21]`. It lives in the trial leaves, one per scenario role.

### 16.5 The Python client

`example_tempus_clients/python/bees_tempus_client.py`: a module and a command line, pure Python, nothing of the Silica library `[B: OQ-19]`.
Since 2026-11-24 (16.7) that file is a plain name for the test support `example_tempus_clients/python/testing/bees_tempus_testing.py`,
and the codec is `example_tempus_clients/python/lib/bees_tempus_codec.py`, one of the seven modules of the Python
extension; what this section says of the module is true of them together. It has
its own ETF writer and reader for the subset of section 5 (maps, atoms, binaries, integers, lists), written independently
of the Silica side, so that agreement between the two is evidence and not a shared mistake. TLS is Python's `ssl` module;
Ed25519 and SHA-512 are the `cryptography` package and `hashlib` (checked 2026-11-18: `cryptography` 46.0.3 is installed
for `/opt/homebrew/bin/python3` and signs and verifies Ed25519; nothing was installed for this). The same module makes the
trial fixtures: test keys, self-signed certificates and tokens. Tests: `example_tempus_clients/python/test_bees_tempus_client.py`.

### 16.6 The clients in trials

From C2 on, a TEMPUS trial is a node under test (the bridge node where the row allows, as ruled) and one or more clients.
A scenario is written twice, once as a thin Silica app (its output is a golden beside the node's) and once as a Python
script (it asserts the same replies); both walk the rows of 16.2 the milestone reaches. The Python client also carries the
hostile cases Silica's carrier cannot produce (row 26). Coverage is kept as a table in the trial directory: row of 16.2,
trial, scenario step, for each client.

### 16.7 Library and driver, and the gossip part of each example (owner's request, 2026-11-20)

Each of the four examples in `example_tempus_clients/` is divided into a library (`lib/`: the files an application
would start from) and a driver application (`driver/`: a thin program over the library). Each library holds, beside
frames, admission and single connections, a gossip part: the three stores with the rules of section 3, a shuffle on
each store's timer, the join of section 6, and the answers to `shuffle` and `sample` from the stores, with a
sentinel's insert of the asking peer (NQ-13).

- RULED 2026-11-24 (owner): one implementation per language. Asked which of two gossip implementations to keep in
  Python, Swift and Kotlin (the `Peer` of each client library, added on main on 2026-11-21, and the node half matched
  to the Silica node, added on the branch tempus-extension-nodes), the owner ruled: "select the implementation for
  each language that is the most complete, produces the smallest code, and will be the most usable and stable". The
  node half was kept in all three; `Peer` was removed (Python `lib/tempus_client/`, Kotlin `lib/Gossip.kt`, Swift
  `lib/TempusClient/Gossip.swift`). Each driver's `gossip` command now runs a node, with its command line and output
  unchanged, and states in one place the values a node requires that the gossip example does not pass (in-flight
  limit 16, clock_back follow, clock_fail continue, clock_read_ms 1000: the drivers' choices for the example, not
  defaults of any library). The C# and Rust extensions had only the node half.
- Silica (`lib/bees_tempus_peer.part`) does not state the rules again `[P]`: in Silica they are the units of
  `src/tempus` and the node part, as admission already is for the single-connection part. `tempus_peer_start` starts
  that library not externally driven and without the test unit.
- `example_tempus_clients/gossip/` runs instances of the drivers as one network on one machine
  (`trials/c7_tempus_gossip`): four instances of each driver, a Silica sentinel with one edge of each language, and
  that network without Silica. All six were run and recorded on the Mac on 2026-11-20. The Silica driver's
  application learns who its peer knows by asking it for samples over loopback, through the single-connection part.

## 17. Bridge nodes (owner requirement, 2026-11-18)

Decided by the owner `[B: requirement of 2026-11-18, relayed by the coordinator]`: "TEMPUS nodes of a system also need a
'bridge' node or nodes to the TRUST part of the system." A SEMP system that has a TEMPUS part therefore has one or more
bridge nodes connecting it to its TRUST part. This section replaces nothing in section 7; it adds the detail.

### 17.1 What the sources say

- `tempus_bridge` peers are non-ephemeral, "longer-lived peers that bridge to separate TRUST overlays/instances. They
  shuffle only with other `tempus_bridge` peers. Application logic uses them to reach TRUST; Cyclon state stays isolated."
  `[S: R:363-364]`
- Every TEMPUS server keeps a `tempus_bridge` store beside the other two `[S: R:375-376]`.
- The comparison table: "TEMPUS load balanced without external tools" `[S: R:453]`. It does not say what is balanced; with
  several bridges, uniform sampling of the bridge store spreads edges over them, which may be what is meant (not stated).
- Nothing else: not what a bridge is in TRUST's terms, not what crosses it, not how an edge picks one, not what protects
  TRUST. BEES's own earlier text: "a `tempus_bridge` peer is also a TRUST node with a whitelisted certificate. Bridging is
  application logic" `[B: inter-nodal-modes 5]`; "when it needs a stable service it goes through a bridge peer. The bridge
  peer is part of a TRUST network, and from that point TRUST's rules apply" `[B: documents/semp.md]`.

### 17.2 What a bridge is

A bridge is a SEMP node that runs both TRUST and TEMPUS, with TEMPUS role `bridge` `[B: OQ-14, OQ-22]`. The rule that no
node is both a BEAM-mode node and a SEMP node is untouched `[B: D36, README]`. It is not a third role and not a special
program: it is the TRUST node as built (listener, whitelist, pins, tokens, suspicion: `src/trust/`) and the TEMPUS node of
this design (a second listener with ALPN `tempus/1`, the three stores, admission) in one program.

It has two identities with two keys `[B: OQ-22]`:

| | TRUST side | TEMPUS side |
| --- | --- | --- |
| Key | the TRUST certificate key | the TEMPUS identity key (Ed25519), the key its producer token names |
| Certificate | the TRUST certificate (`trust.tls_opts`) | self-signed over the TEMPUS identity key (`tempus.identity_certfile`) |
| Known to others as | the SHA-512 of the TRUST certificate's DER, in TRUST nodes' whitelists and pins | `peer_id` (SHA-512 of the public key) in views; the SHA-512 of the TEMPUS certificate's DER in other nodes' `tempus` whitelists |
| Presented on | the TRUST listener and `trpc` calls | the `tempus/1` listener and its own shuffles |

Neither key is ever used on the other side, and nothing on the wire links the two identities: a TRUST node cannot tell
which TEMPUS peer its bridge is, and an edge never sees the TRUST certificate.

### 17.3 How TEMPUS nodes find and choose a bridge

Ruled `[B: OQ-5, OQ-24]`. A node's bridge store is filled at join (the sentinel's `sample` answer) and kept fresh by shuffling
it with bridges. An application asks its node for bridges (`sample` on the bridge store) and calls one. With several
bridges every edge holds a random subset, so load spreads without a balancer. A bridge that does not answer is removed
from the view like any dead partner; the call that found it dead returns `closed`, and the application calls again
through another. If the bridge store is empty the node asks a sentinel again. BEES repeats no request by itself. The
library has one function that picks one bridge by a random draw, for applications that want no policy of their own.

### 17.4 What crosses, and what is checked on each side

| Step | Direction | Checks |
| --- | --- | --- |
| 1 | edge to bridge, TEMPUS side: TLS, adverts, proof of possession, then one `call` or `cast` frame (TRUST's frame format) | on the bridge: TLS 1.3 and ALPN; the edge's producer token and proof (section 4); the bridge's per-peer score, rate and in-flight bounds (17.5); frame bounds; the forbidden guard; the per-type permission spec, `none` by default; the MFA table's type check of `args`. On the edge: the bridge's TEMPUS certificate in the edge's `tempus` whitelist `[B: OQ-3]`, the bridge's token (`typ` is `tempus_bridge`) and proof |
| 2 | on the bridge: the admitted request is handed to the bridge's application as one message, after all of BEES's checks, and the application answers it exactly once `[B: NQ-18]`: with a value, with a failure, with "run the MFA function" (BEES runs the function the application exported, in a per-request worker `[B: N3]`), or with one TRUST call of its own making whose result becomes the answer (`tempus_bridge_onward`). A TRUST MFA function is synchronous and `trpc` answers by a message, which is why the application is asked and the function is not called directly | call timeout, whichever answer the application chooses; a failure of the function fails only its worker `[B: D2]`; the edge's identity is never passed on |
| 3 | bridge to TRUST node, if that function calls `trpc`: plain TRUST | all of TRUST, under the bridge's TRUST certificate: mutual TLS 1.3, the bridge pins the server, the server's whitelist entry for the bridge and its permission spec, reconnect token, suspicion and quarantine of the bridge `[B: D36, D43, D10]` |
| 4 | the result returns: TRUST `result` to the bridge, the function's return value as `result` to the edge | no error body at either hop `[S: R:17, R:46]`; the edge learns only `closed` |
| 5 | TRUST node to bridge: plain TRUST calls of functions the bridge exports to TRUST peers | TRUST's, unchanged |
| not provided | TRUST node or bridge to an edge | OQ-13 |

Nothing an edge sends is passed to a TRUST node as it arrived: the bridge's function builds the onward request. The TRUST
node's whitelist entry for the bridge should name only the functions the bridge needs, as for any TRUST peer.

An edge's `cast` is closed, with no reply, when its outcome is known (it ran, failed or timed out), not when it is
admitted as TRUST does `[B: NQ-20]`: the bridge's lines about a cast then come before its close, and the edge sees the
same either way.

### 17.5 Keeping ephemeral nodes from weakening TRUST

Ruled `[B: OQ-23, OQ-25]`. The risk, observed from how TRUST is built: a TRUST node scores the certificate it sees, which is
the bridge's TRUST certificate, and a quarantine lasts until an operator's reset `[B: D10]`. So an edge that could make the
bridge send bad requests could take the bridge out of the TRUST network. The defences are at the bridge, before anything
reaches TRUST:

- No forwarding: only exported functions with typed arguments run (17.4).
- A score per peer, by `peer_id`, with TRUST's rule (up on a refusal, a failure or a timeout, down on success,
  refused above the limit). An entry lives until that peer's token expires. What counts `[B: NQ-19]`:
  - up by one, at the bridge's table: the peer's in-flight bound, the peer's rate bound, a refused TRUST request (frame,
    forbidden guard, permission spec, not in the program, argument types), a failed function, a timeout (also of a
    call the application held on purpose);
  - up by one, from the connection actor: every refusal of the peer's connection before or instead of a request: a bad
    token (expired, not yet valid, another `sub`, a signature that does not verify), an advert that is malformed or is
    not bound to the TLS certificate, a whitelist mismatch, a failed proof of possession, a frame that is malformed,
    oversize or no request, a shuffle entry that does not verify, and a timeout while the peer is waited for;
  - down by one: an answered call or a cast that ran;
  - no change: the score refusal itself, the bridge's in-flight bound in total (not the peer's doing), a failure of the
    bridge's own random source or signer, and a `key_rotated` answer (a token under an old key is not misbehaviour).
  Whose score: the identity is never the advert's word alone. It is the SHA-512 of the key of the peer's TLS
  certificate, which the handshake proved the peer holds (section 4, the binding); so nobody can raise another peer's
  score by showing that peer's advert. A refusal counts for a peer the table already holds, and makes a new entry only
  when the producer's signature on the peer's token had verified (from the proof of possession on): an entry lives until
  its token expires, and an expiry the producer did not sign is not to be believed (ruling NQ-23). The score limit is
  not a constant of BEES: the bridge application passes it when it starts the node, with the other limits below.
- A rate bound and an in-flight bound per peer, and an in-flight bound for the whole TEMPUS side.
- TRUST's wire is unchanged: the edge's identity is not passed onward by BEES.

The numbers are the bridge application's `[B: OQ-25]`: it passes, when it starts the node, the score limit, the table size,
the requests per peer per interval and the interval, the requests in flight per peer, and the requests in flight in total.
BEES has no defaults and no `bees.config` options for them; a bridge started without them does not start. BEES does keep
literal ceilings above the application's values, because a Silica table and a decode bound are fixed when the program is
compiled `[B: D47's pattern; stated here as OQ-25's ruling asks]`: table size at most 4096 entries, in flight in total at
most 64 (the ceiling of `inflight_max`), in flight per peer at most 64, rate at most 1000000 per interval, interval 1 ms
to 3600000 ms. A value above its ceiling is refused at start, never clamped. When the table is full the entry whose token
expires first is dropped, and that is audited.

What this cannot do: stop an attacker who can get many valid tokens. The producer's issuance (attestation, `[S: R:405]`)
is that limit.

### 17.6 What the bridge needs from the existing TRUST code

From reading `src/trust/` and spikes/N3-trust.md, to be confirmed when T5 and T6 start (inferred, not built):

- Reused unchanged: `bees_trust_frame` (the request and result frames and their checks; T2 already reuses its map walk for
  the token), `bees_trust_guard`, the generated MFA table, `bees_trust_work`, and the whole TRUST node for the TRUST side.
- New, in `src/tempus/`: the TEMPUS-side connection actors (admission, then the request), the per-peer table, and a node
  part that starts both sides in one program.
- The TLS link cannot be reused as it is for `tempus/1` (read 2026-11-18 in `native/tls/silica_bees_tls.c` and
  `src/trust/dangerous_bees_tls*.silica`; nothing there was changed). What is missing, exactly:
  1. The ALPN is the constant `ALPN_TRUST` (`trust/1`): offered by a client (`SSL_CTX_set_alpn_protos`), the only one a
     server selects (`alpn_select`), and the bit `bees_tls_facts` reports (`alpn_is_trust_1`). TEMPUS needs the protocol
     name as a parameter of the context, `tempus/1`, and a facts bit that means "the configured ALPN".
  2. There is one `SSL_CTX` per role for the whole process (`ctxs[role]`, made at the first `bees_tls_open` and reused for
     every later one), so the certificate, key, CA and classical flag of the first connection are those of all. A node
     that runs TRUST and TEMPUS (a bridge) needs two credentials in one process: the context must be keyed by more than
     the role (for example role and a profile number 0 TRUST, 1 TEMPUS, passed through `bees_tls_set_args`, whose second
     argument is unused today).
  3. The engine gives the SHA-512 of the peer certificate's DER (`bees_tls_peer_fp`) and not the peer certificate's
     public key. TEMPUS must check that the key of the peer's TLS certificate is the `pub` of its advert (the certificate
     is self-signed over the identity key, OQ-2): without that check the proof of possession does not bind the TLS
     channel to the peer, and a node in the middle with its own certificate could relay the advert and the proof. Needed:
     the raw 32-byte Ed25519 public key of the peer certificate (and a refusal when the certificate's key is not
     Ed25519), in the form `bees_tls_peer_fp` returns its bytes.
  4. For TEMPUS the peer certificate must be self-signed over that key and no CA is involved; the engine's no-CA path
     (`accept_any_chain_cb`, D43) already accepts it, so nothing is missing there. Certificate and key are given as file
     paths, as for TRUST (bytes are N0c's later step for both).
  The choice between a small change there (three additions: an ALPN parameter, a profile in the context key, a peer-key
  call) and a TEMPUS copy under `native/tempus/` is the coordinator's. A copy would duplicate about 400 lines of the
  engine and the Silica link unit, and the two would have to be kept in step.
- The permission functions `tools/bees_config_trust.py` generates are per whitelisted fingerprint, and the bridge needs
  one per peer type, which a new `tools/bees_tempus_gen.py` can write without touching the TRUST one.
- For the Python client (C2), to check with a real handshake: Python 3.14's `ssl` cannot name key-exchange groups
  (`set_ecdh_curve("X25519MLKEM768")` is refused, there is no `set_groups`); whether its default offer (OpenSSL 3.6.2)
  includes X25519MLKEM768, which the engine requires (D40), is not verified. If it does not, the Python client needs the
  per-peer classical opt-in (D44) or another TLS binding; that would be a question for the owner.

Confirmed in T6 (2026-11-19): `src/trust` is used unchanged. A bridge program is the root unit `tools/bees_trust_gen.py
edge` writes from the TRUST side's `bees.config`, with the TEMPUS link, node and bridge parts and the roles pasted after it
(`tools/bees_tempus_gen.py bridge`); the generated MFA table (`bees_trust_gen.py mfa`) lists the functions edges may name,
`bees_trust_frame@parse_req`, `bees_trust_guard@forbidden` and `bees_trust_work@twork` are reused as they are, and the
per-type specs are a unit of their own (`bees_tempus_gen.py spec`, `bees_tempus_spec@permitted`; a whitelisted peer's entry
line replaces its type's, NQ-4). The bridge's TRUST side calls out with `trpc_call` (a plain TRUST client: pins, token,
suspicion at the server); `tempus_bridge_onward` gives it the application's request. Nothing in `src/trust`,
`tools/bees_trust_gen.py` or `tools/bees_config_trust.py` was changed. The client library gained `call_frame`,
`cast_frame`, a reading of `result` in `show`, and `pick_bridge(body, count, draw)`, the one function that picks a bridge.

### 17.7 Trials

T6 and C3's trial has two bridges and one TRUST node, driven by both clients admitted as edges (rows 24, 25, 29 to 36 of 16.2): a call
through each bridge; one bridge stopped and the call repeated through the other; a hostile edge refused at the bridge
while the TRUST node's score of the bridge stays where it was; the rate bound; and the bridge quarantined at the TRUST
node by the trial itself, to show that edges then see `closed` and nothing else.

## 18. New open questions after the rulings

NQ-1 to NQ-10 were all ruled by the owner on 2026-11-18 and NQ-11 to NQ-20 on 2026-11-19 (the lines beginning "RULED");
the sections above state the results as `[B: NQ-n]`, and all of them are built (tempus-progress.md, the entry of
2026-11-19 on the rulings NQ-11 to NQ-20). Where a question's text below says "Provisional behaviour, built", it is the
question as it was asked: the line beginning "RULED" under it is what holds now. Open: NQ-21.

None of these blocks T1, T2, C1 or T4. Each says what it blocks.

NQ-1. May a test-only frame return a node's whole view to a client? The rulings name tick and clock as the test-only
operations. Without more, a client observes a view only through `sample` (random, at most `shuffle_length` entries) and
through shuffle frames; the whole view after a step is visible only in the node's own output. Options: (a) add a test-only
`#{t => view, store => Typ}` answered with all entries, under the same `control_test_only` conditions; (b) no: trials read
the node's output. Recommendation: (a), because "the client observes the result" is then true of every row of 16.2
without leaning on the node's log. Blocks: nothing; it changes how C2's trials assert.
RULED 2026-11-18 (owner): option (b), no: there is no test-only frame that returns a node's whole view. Trials read the node's own output for what the client cannot observe.

NQ-2. Are the clients limited to the bridge node? The ruling names the bridge node as the Python client's peer. The frames
are the same for every TEMPUS node. Options: (a) the clients work against any TEMPUS node, and trials use the bridge node
as the node under test wherever the row allows; (b) bridge only, and behaviours of edge-only or sentinel-only nodes are
covered by node-to-node trials. Recommendation: (a). Blocks: nothing before C2.
RULED 2026-11-18 (owner): option (a), as recommended: the clients work against any TEMPUS node; trials use the bridge node as the node under test wherever the row allows.

NQ-3. The spelling in `bees.config` of "a SEMP node runs TRUST, TEMPUS or both" (OQ-14 asks for a redraft). Options: (a)
`{mode, beam}` or `{mode, semp}`, and a SEMP node runs each part whose section (`trust`, `tempus`) is present; `{mode,
trust}` stays accepted and means `semp` with only the `trust` section; (b) `mode` takes a list, `[trust]`, `[tempus]`,
`[trust, tempus]`; (c) keep `{mode, trust}` as the SEMP spelling and let the presence of a `tempus` section enable TEMPUS,
with a new key to switch TRUST off for an edge-only node. Recommendation: (a). Blocks: T7 only.
RULED 2026-11-18 (owner): none of the options as written. The owner's spelling: `{mode, trust}` is a TRUST-only node, `{mode, tempus}` is a TEMPUS-only node, `{mode, tempus-trust}` is a bridge node (a node that is both). (Note for the reader's implementation: `tempus-trust` with a hyphen is not an unquoted Erlang atom; how the reader accepts the value as the owner wrote it is to be worked out and reported, not changed silently.)

NQ-4. Must a bridge's `tempus` whitelist entry and its token agree? A peer whose TEMPUS certificate is in a node's `tempus`
whitelist presents a token too. Options: (a) both are checked and the token's `typ` must be `tempus_bridge` or
`tempus_sentinel`; the whitelist entry's permission spec then replaces the per-type spec for that peer; (b) the whitelist
alone admits such a peer and no token is needed. Recommendation: (a): the whitelist says who is accepted as a bridge or
sentinel, the token says the producer still vouches for it. Blocks: T5.
RULED 2026-11-18 (owner): option (a), as recommended: both are checked; a whitelisted bridge or sentinel also presents a token whose `typ` must be `tempus_bridge` or `tempus_sentinel`, and the whitelist entry's permission spec replaces the per-type spec for that peer.

NQ-5. How does a running node take a new producer key (left open by OQ-10's ruling)? Options: (a) restart with the new
configuration; (b) the application passes the new `{Kid, PublicKey}` to the running node, as it passes a new token.
Recommendation: (b): it is the same act as a token refresh and needs no new mechanism; the application decides when.
Blocks: nothing before T4's rotation trial, which can use either.
RULED 2026-11-18 (owner): option (b), as recommended: the application passes the new `{Kid, PublicKey}` to the running node, as it passes a new token.

NQ-6. The boards. Mbed TLS, the boards' TLS engine (D40), has no Ed25519 in the copy checked (4.1.0 in the local ESP-IDF
tree). Options: (a) the boards are not TEMPUS nodes in the first build; (b) a separate Ed25519 implementation for the
boards, which must be chosen, fetched and vetted (the no-downloads rule applies); (c) wait for Mbed TLS. Recommendation:
(a) now, (c) watched. Blocks: T8's board part only.
RULED 2026-11-18 (owner): as recommended: the boards are not TEMPUS nodes in the first build; Mbed TLS is watched for Ed25519.

NQ-7. May a client that is not a bridge or sentinel send `sample`? Section 5 lets any admitted peer ask; the join only needs
a joiner asking a sentinel. Options: (a) any admitted peer may ask any node; (b) only a sentinel answers. Recommendation:
(a): it reveals nothing a shuffle would not, and it is how an application finds a bridge. Blocks: nothing.
RULED 2026-11-18 (owner): option (a), yes: any admitted peer may send `sample` to any node.

NQ-8. May a TEMPUS connection use the classical key exchange (X25519 alone)? D44 lets a TRUST peer do so when its whitelist
entry is marked classical-allowed (for the boards); nothing rules it for TEMPUS, and the boards are not TEMPUS nodes
(NQ-6). Options: (a) no: `tempus/1` accepts X25519MLKEM768 only; (b) the D44 opt-in for whitelisted bridges and sentinels.
Recommendation: (a) until a board is a TEMPUS node. Provisional behaviour, built: (a) (`dangerous_bees_tempus_tls`, marked
as provisional). Blocks: nothing.
RULED 2026-11-18 (owner): provisional choice accepted: TEMPUS connections use the hybrid key exchange (X25519MLKEM768) only; no classical opt-in.

NQ-9. A gossiped entry whose token says `tempus_bridge` or `tempus_sentinel` cannot be checked against the `tempus`
whitelist without contact: the whitelist is keyed by the SHA-512 of a certificate (OQ-3) and an entry carries only the
public key. Options: (a) such an entry is admitted to the store by its token alone and the whitelist is checked when the
node first connects to that peer (a peer not in the whitelist is then refused and its entry dropped, as a failed
shuffle); (b) BEES also derives each whitelisted certificate's public key when the whitelist is read, and an entry of
those two types is admitted only when its `pub` is one of them. Recommendation: (b): it keeps a bridge nobody listed out
of the bridge store altogether, and the key is in the certificate already. Provisional behaviour, built: (a), the weaker
one, because (b) needs a second form of the whitelist that nothing rules; no unlisted bridge or sentinel is ever spoken
to past its advert either way. Blocks: nothing; it changes T3's entry check.
RULED 2026-11-18 (owner): provisional choice accepted: option (a): a gossiped bridge or sentinel entry is checked against the `tempus` whitelist at first contact.

NQ-10. Are the validity dates of a TEMPUS certificate checked? The certificate is self-signed over the identity key and
no chain is verified (OQ-2, D43); the engine's no-CA path does not check dates, and the token already carries the
producer's validity window. Options: (a) not checked: the token's `nbf` and `exp` are the validity of a TEMPUS identity;
(b) checked against the node's clock. Recommendation: (a). Provisional behaviour, built: (a) (what the engine does for
TRUST's pins). Blocks: nothing.
RULED 2026-11-18 (owner): provisional choice accepted: option (a): certificate validity dates are not checked; the producer token carries the validity window.

NQ-11. Where does a node that is not a test node read the time of day for token checks? The language has a monotonic
clock and no wall clock. Options: (a) the application passes the time of day once, at start, and BEES adds the monotonic
time since then; (b) the application passes the time again whenever it likes (a message, as it passes a new token) and
BEES never advances it by itself; (c) a call in the TEMPUS native edge that reads the system clock, as the random source
is read through an edge. Recommendation: (c) on the hosted platforms: (a) never sees a clock that was corrected or a
machine that slept. Provisional behaviour, built: (a) (`tn_now` in `bees_tempus_node.part`, marked PROVISIONAL); a test
node's clock is the value passed at start until a `clock` frame. Blocks: nothing in the trials (they run under
`control_test_only`); it decides what a deployed node's token window means.
RULED 2026-11-19 (owner): the recommendation: a node that is not a test node reads the system clock through the native edge (the application's start value plus the monotonic clock, built provisionally, is replaced).

NQ-12. Does a joiner put the sentinel it joined through into its own sentinel store? Section 6 says the sentinel answers
from its stores and inserts the joiner; a sentinel is not in its own stores, so with one sentinel every node's sentinel
store stays empty (seen in `trials/t3_tempus_nodes`), and a node reaches a sentinel again only through its
configuration. Options: (a) no, as the text says; (b) yes: the joiner inserts the sentinel that answered, at age 0, into
its sentinel store (its advert was verified and its certificate is in the whitelist). Recommendation: (b): the sentinel
store is otherwise empty until a second sentinel exists, and Cyclon's views are filled the same way from an introducer.
Provisional behaviour, built: (a). Blocks: nothing.
RULED 2026-11-19 (owner): the recommendation: yes, a joiner keeps the sentinel it joined through in its sentinel store.

NQ-13. Which requests make a sentinel insert the asker? Section 6 names the joiner's `sample`; NQ-7 lets any admitted
peer send `sample` to any node. Options: (a) every `sample` a sentinel answers inserts the asker into the sentinel's
store of the asker's type (an insert of a peer already there changes nothing but its age); (b) only the first, or only
a peer the sentinel does not hold; (c) a separate join request. Recommendation: (a): a sample to a sentinel is the join,
and an admitted peer that asks is alive. Provisional behaviour, built: (a); the sample is taken first and the insert
follows, so a joiner is never answered with itself. Blocks: nothing.
RULED 2026-11-19 (owner): as built and recommended: every sample request makes a sentinel insert the asker, the sample taken before the insert.

NQ-14. What does `shuffle_timeout_ms` bound? Section 8 says "time for a whole connection". Built: the carrier's connect
budget, the TLS handshake and the admitted connection (from the link being up to its close) each get that value, so a
dialed connection can last up to three times it. Options: (a) as built; (b) one timer from the dial to the close.
Recommendation: (b), when the connection actor is next changed. Provisional behaviour, built: (a). Blocks: nothing.
RULED 2026-11-19 (owner): the recommendation: `shuffle_timeout_ms` is one timer from dial to close (not one per stage, as built provisionally).

NQ-15. A store of another type than the node's own loses an entry at every shuffle. In such a store the node's own entry
is not sent (OQ-5), and the partner leaves the view as in every shuffle (3.2 step 4), so nothing puts the link back: the
partner cannot hold the node in that store. Seen by hand with three nodes on their own timers (not a trial): the
sentinel's edge store went from two entries to none in four ticks and stayed empty until an edge asked it again
(the insert of NQ-13). Options: (a) as built, the rules as written; (b) in a store that is not of the node's own type,
a partner that answered is put back at age 0 after the merge (it was just reached); (c) a node does not tick the stores
that are not of its own type and only answers in them. Recommendation: (b). Provisional behaviour, built: (a). Blocks:
nothing; it decides how long a sentinel or a bridge keeps knowing edges, and an edge keeps knowing bridges (17.3).
RULED 2026-11-19 (owner): the recommendation: a partner that answered a shuffle is put back into the store at age 0, so a store not of the node's own type does not drain.

NQ-16. A received entry that names a peer the node has just SENT replaces it even when the received one is older. 3.4
step 2 compares a received entry only with what was "received and still in the view"; the sent entries have left the
view (3.2 step 4, 3.3) and return only where there is room and the peer is not there (step 4). Seen in
`trials/c2_tempus_clients` (both clients, step 8): the node held x3 at age 6, answered a shuffle with it, received x3 at
age 40 in the same shuffle, and now holds x3 at age 40. Options: (a) as built, the rules as written; (b) a received
entry is also compared with the sent one of the same peer and the younger of the two is kept (R:382 "prefer younger
entries"). Recommendation: (b): the node had the fresher news of that peer and gives it up for older news. Provisional
behaviour, built: (a), `bees_tempus_view@merge` and `backfill` unchanged. Blocks: nothing.
RULED 2026-11-19 (owner): option (b), keep the younger of the two: a received entry is also compared with the entry of the same peer the node just sent, and the younger is kept.

NQ-17. Does a node whose own token has expired still answer peers? Section 6 and row 15 say it stops ticking and tells
its application. Built in T3: nothing else changes, so it still accepts connections, admits peers and answers `sample`
and `shuffle` with an advert whose token every correct peer refuses (seen in `trials/c2_tempus_clients`, step 54: the
client refuses the node's advert, the node records a closed connection). Options: (a) as built; (b) it stops listening
until its application passes a new token (ops 70, 71); (c) it goes on listening and closes every accepted connection at
once with one audit line. Recommendation: (a): a peer's own check already refuses it, and a refreshed token makes the
node whole again with no restart of its listener. Provisional behaviour, built: (a). Blocks: nothing.
RULED 2026-11-19 (owner): option (a), as built: a node whose own token has expired still answers peers.


NQ-18. How does a bridge's application run an edge's request? Section 17.4 says the request runs "a function the bridge's
application exported, in a per-request worker", and that function may call onward with `trpc`. A TRUST MFA function is
synchronous (`(:ok, V) | (:error, R)`) and `trpc` answers by a message, so a function in the MFA table cannot wait for a
TRUST call. Options: (a) every admitted request is handed to the bridge application as a message, after all of BEES's checks
(score, bounds, guard, per-type spec, the MFA table's type check), and the application answers it once: with a value, a
failure, "run the MFA function" (BEES runs it in a per-request worker, `bees_trust_work`, as TRUST does), or one TRUST call
of its own making whose result becomes the answer (`tempus_bridge_onward`); the call timeout bounds it either way; (b) MFA
functions only, no onward calls (the bridge then cannot reach TRUST, which is its purpose); (c) a new kind of manifest
line that names a TRUST call to make (BEES would then forward by configuration, which 7 and 17.4 rule out).
Recommendation: (a). Built: (a) (`bees_tempus_bridge.silica`, `tempus_bridge_start`; the edge's identity is never passed on).
Blocks: nothing.
RULED 2026-11-19 (owner): as built and recommended: the bridge application answers each admitted request exactly once (a value, a failure, run the MFA function, or one onward TRUST call).

NQ-19. What raises an edge's score at a bridge? 17.5 says TRUST's rule: up on a refusal, a failure or a timeout, down on
success. Built: +1 for the peer's in-flight bound, the peer's rate bound, a refused TRUST request (frame, guard, spec, not in
the program, argument types), a failed function and a timeout (also of a call the application held on purpose); no change
for the score refusal itself and for the bridge's in-flight bound in total (not the peer's doing); -1 on an answered call or
a cast that ran. A frame that is no TEMPUS request at all is refused by the connection actor before the bridge sees it and
does not count. Options: (a) as built; (b) count the connection actor's refusals of an admitted peer too (the node would be
told). Recommendation: (b), when the connection actor is next changed: an admitted peer sending garbage is misbehaving.
Blocks: nothing.
RULED 2026-11-19 (owner): the recommendation: the connection actor's refusals of an edge (token, proof, malformed frame) also raise that edge's score at the bridge (built provisionally without).

NQ-20. When is an edge's cast closed? TRUST closes a cast's connection when the cast is admitted. Built: the bridge closes
it when the cast's outcome is known (it ran, failed or timed out), so that the bridge's lines about it come before the close
and a trial's outputs have one order. The edge sees the same (a close with no reply) either way. Options: (a) as built; (b)
at admission, as TRUST. Recommendation: (a). Blocks: nothing.
RULED 2026-11-19 (owner): as built and recommended: an edge's cast is closed when its outcome is known, not at admission.

NQ-21. The bare `{mode, tempus-trust}`. Section 11 chose that BEES's reader accepts the owner's bare spelling as the value
of `mode` (and the quoted atom). `tools/bees_conf.py` (not TEMPUS's file) reads `'tempus-trust'` but refuses the bare form
as a syntax error, and knows only `beam` and `trust`. Built, provisionally, in `tools/bees_tempus_conf.py`: the bare
spelling is quoted before the text reaches that reader (as the value of `mode` only), and the trust part of a
`tempus-trust` file is checked by that reader on a copy with `{mode, trust}` and no `tempus` section. Options: (a) the reader
of `tools/bees_conf.py` takes the bare spelling for `mode` and the two new modes, and calls `bees_tempus_conf.tempus_section`
(three small edits, listed in tempus-progress.md); (b) keep the stand-in. Recommendation: (a), by that file's owner. Blocks:
T7's store-carrier part only.

NQ-22. The system clock that fails or goes back (follows the ruling on NQ-11). The ruling says a node that is not a test
node reads the system clock through the native edge. It does not say (1) what the node does when a reading fails, (2) what
it does when a reading is earlier than the one before (an operator or a time service set the clock back), or (3) how
often the clock is read. Options for (2): (a) the node follows the system clock as it reads it, and says so in one line;
(b) the node's clock never goes back: it keeps the greatest reading it has seen until the system clock passes it again
(a token cannot come back to life, but a clock that was wrongly ahead and is corrected leaves the node refusing good
tokens, as "not yet valid", for as long as the error was large); (c) a step back larger than the skew allowance stops
the node (it stops ticking and refuses connections) until its application restarts it. Recommendation: (a). The clock
is the producer's and the nodes' shared reference, a correction is most often the clock becoming right, and the token
lifetime of minutes bounds what a wrong clock can admit; (b) and (c) make a node unusable after an honest correction.
Built: (a) (`tn_clock` in `src/tempus/bees_tempus_node.part`): the reading is followed, one line `clock: the system
clock went back by N s; the node follows it`; nothing already done is undone (section 10). For (1), built: at start the
node does not begin until a reading succeeds; later it goes on with its last reading, says so once and tells its
application (op 86). The other choice is to stop serving while the clock cannot be read. For (3), built: at start and
once a second (the clock is in whole seconds; the literal is `read_every_ms` in `dangerous_bees_tempus_draws`); a reading
is therefore at most about a second old, inside any skew allowance of a second or more. Not shown by a trial: a failing
clock and a clock going back (a trial cannot set the machine's clock); those two paths are read from the code only.
Blocks: nothing.
RULED (owner, 2026-11-20): (2) option (a), the node follows the system clock. Confirmed the same day after the owner was
told that daylight saving time never produces a step back (the reading is seconds since 1970 in UTC) and was shown what
each option risks: under (a), a step back of N seconds lets a token that expired in the last N seconds be used again for
up to N seconds (its holder must still prove possession of the key), and a time source that is not authenticated lets
somebody on the network path cause the step; under (b) and (c) the same person can stop nodes instead. The token
lifetime bounds what (a) can admit. (1) the other choice: a node whose clock fails after a good reading stops admitting connections
and stops ticking until the clock is read again, and tells its application (built: `tn_clock`, `tn_timer`, `tn_accepted`
and role 4 of `dangerous_bees_tempus_conn`, audit line `clock_refused`). (3) kept: at start and once a second.
RULED (owner, 2026-11-20, later the same day): "It seems to me that these three choices should be configurable by the user
along with the times", and then "make 22.2 a configurable choice as well". This replaces "(a) is the behaviour" above
with "(a), (b) or (c) as configured", and "the other choice" of (1) with "either choice as configured". Built: (2) is
`clock_back`, one of `follow` (a), `hold` (b) and `stop` (c); the limit of (c) is its own value, `clock_back_limit_s`, and
no longer the skew allowance; (1) is `clock_fail`, one of `continue` (the node goes on with its last reading, the
behaviour before the first ruling of this day) and `pause` (it stops admitting and ticking until the clock is read
again, the behaviour of the first ruling); what a node does with no reading at start is not a choice; (3) is
`clock_read_ms`, and the literal `read_every_ms` is gone. None has a default: a file without one of them is refused
(`tools/bees_tempus_conf.py`), `clock_back_limit_s` is required under `stop` and refused under the other two, and the
node's boot check refuses a choice outside its set. Sections 10 and 11 say what each does and its bounds. Shown by
`trials/t0_tempus_clock`: the decision for every choice, both sides of the limit, the end of a hold, both choices for a
failed reading, as a pure function given readings as numbers. Read from the code only, as before: the node acting on
that decision with a real clock (its lines, the application told, the stop, audit line `clock_stopped`), because a
trial cannot set the machine's clock or make it fail. The trials' nodes pass `follow`, `pause` and 1000 ms, which is
what was built before, so their goldens did not change. Not built, for the owner to rule: a test node's `clock` frame
still sets the node's time to any value and does not go through `clock_back`.
Built later on 2026-11-20, with the test unit of 16.3 (the ruling under OQ-20): a `clock` frame is now a clock reading.
It goes through `clock_turn` like the system clock's, with the node's configured choices, and it can say that the clock
could not be read. `trials/t6_tempus_clock` shows on running nodes what the paragraph above lists as read from the code
only: the hold, the wait for the clock, going on with the last reading, the stop, the two audit lines, the application
told with 86 and 87, and the join request that waits. Still read from the code only: the clock actor itself (the native
reading and its timer) and a clock that cannot be read at start.

NQ-23. Which refused connections make a NEW score entry at a bridge (follows the ruling on NQ-19). The ruling says the
connection actor's refusals of an edge (token, proof, malformed frame) raise that edge's score. Two things had to be
settled to build it. (1) Whose score: built, the identity is the SHA-512 of the key of the TLS certificate the peer
proved it holds, never the id an advert claims, so a peer cannot raise another's score by showing that peer's advert.
(2) An entry of the table lives until its token expires, and a refusal for a bad token comes before the producer's
signature is checked, so its `exp` is whatever the peer wrote. Options: (a) such a refusal raises the score of a peer the
table already holds and makes no new entry; a refusal after the token verified (proof of possession, frames, entries,
timeout) makes a new entry as a request does; (b) every refusal makes an entry, with the `exp` the token claims (anybody
with a key pair can then put entries into the table that never expire, and push out the entries of real edges, whose
scores start again at 0); (c) every refusal makes an entry that lives for a time the bridge application passes (a new
limit beside those of OQ-25). Recommendation: (a): a peer that was never admitted and shows only bad tokens is refused
by admission every time, which is all a score could do to it; (c) if the owner wants such peers remembered. Built: (a)
(`report` in `dangerous_bees_tempus_conn`, `conn_refused` in `bees_tempus_bridge`; `trials/c3_tempus_bridge` shows edge Q
reaching the limit by six refused connections alone, and edge Z, never served, keeping no score from two bad tokens).
Blocks: nothing.
RULED (owner, 2026-11-20): (a), and the score limit must be a value that can be configured. It is: the bridge application
passes `score_limit` (with the table size, the rate and the in-flight bounds) when it starts the node (OQ-25), and
`bees_tempus_bridge@lim_why` refuses a value below 0; BEES holds no constant for it.
