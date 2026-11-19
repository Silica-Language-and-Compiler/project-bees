# N0d: run-time configuration through the store carrier (probe, packer, reader, example; 2026-11-18)

Scope: decisions D46 and D47 (roadmap; bees-config-file.md section 12), phase 1. Built here: a probe of Silica's hosted
`(:store)` carrier, the packer (`tools/bees_pack.py`), the reader units (`src/config/`), an example application
(`examples/store_node`) and three trial leaves. Not done here, by instruction: converting the existing trials, which still
compile their configuration in through the generators (section 8 is the plan).

Compilers: the pin `silica-999909-macos-applesilicon` and the refreshed `silica-999906-macos-applesilicon`. Every result
below says which produced it. "Observed" means run here; "read" means taken from Silica's sources or design.

## 0. Findings in one page

1. The hosted `(:store) (:backing, path, capacity, retention)` carrier works on both compilers, with the same output for
   every probe case (observed, 999909 and 999906). The carrier is stdlib source (`dangerous_store_backing_carrier.silica`,
   `storelog.silica`, `wireframe.silica`) over a C sidecar (`compiler/stdlib/net/silica_store.c`), so the layout does not
   depend on the compiler generation.
2. The on-medium layout is as Silica's design 6.8.9 says, and a Python writer reproduces it exactly: a backing written by a
   Silica program through the carrier is byte for byte the image `tools/bees_pack_store.py` builds for the same values
   (observed, both compilers; guarded by `trials/d1_store_layout`, case `write_compare`).
3. A value larger than one record is cut by `wireframe@frame(..., :storage)` into records of at most 4064 bytes and put
   back by `wireframe@unframe`; a 10006-byte frame is three records (4064, 4064, 1893) (observed).
4. What the carrier does on a bad backing (observed, both compilers): absent, it creates the file at the declared capacity
   and reports an empty log; another size, `(:link_down, :mismatch)`; held by another process, `(:link_down, :in_use)`;
   not writable, `(:link_down, :medium)`; a record with a wrong byte outside the tail block, `(:read_failed, :corrupt)`
   after the records before it.
5. Two hazards the reader must cover itself, because the carrier reports neither (observed): a wrong byte in a block
   HEADER drops the whole block without a report (`:log` then says `oldest=1`); a wrong byte in the TAIL block shortens the
   log without a report (the scan at open stops there). The reader therefore requires `oldest == 0` and an index record,
   written first, that states how many frames the store holds.
6. One build may claim a backing path once: two units that declare the same path are E2415 (observed, 999909).
7. A unit listed in `silica.config` by a real path has its `.sams` and `.iface` written BESIDE THE SOURCE (observed,
   999909). Listing `src/config/x.silica` or a stdlib unit by path would write products into BEES's `src/` and into the
   Silica tree, and two applications built at once would write the same files. So BEES units are listed through links in the
   application's directory (`lib/x.silica`), which the ruling on the compilation unit allows ("paths can be listed in
   silica.config or links in the directory"); every trial already does this.
8. The reader, the packer and the example work end to end on the pin: the same executable, started on two packed stores,
   listens on the address from the store and applies two different frame caps with no rebuild (`trials/d3_store_node`).
   Built with 999906 instead, the three leaves (`d1_store_layout` 7 cases, `d2_store_config` 18, `d3_store_node` 3) give
   the goldens recorded on the pin, unchanged (observed: `make integrate` on each with both compilers).

## 1. The probe

Programs: a writer and a reader, each a `dangerous_` root with `carried_on journal: (:store) (:backing, "<name>.sildat",
16384, :stop);`, the carrier started with `spawn_dangerous_carrier`, an owner actor that prints every message. They became
`trials/d1_store_layout`. Built with `tools/trial.mk`; the units are links to Silica's stdlib (`Carrier`, `wireframe`,
`wire_etf`, `storelog`, `dangerous_store`, `dangerous_store_backing_carrier`); the archive `libsilica_store.a` is built from
Silica's `silica_store.c` by a new on-request target of `native/Makefile` (`make -C native store`), and the wrapper's
sidecar is reached through the existing link `native/dangerous_exposure_source/sockets`.

| Question | Result | Compiler |
| --- | --- | --- |
| open, `:link_up`, `:log` | `link_up backing`, then `log oldest=0 next=N capacity=16384` | observed, both |
| block and record size | block 4096; `carrier@mtu((:store))` answers 4064; block header 16, envelope 16 | observed, both |
| a value larger than one record | a 10006-byte ETF frame: records of 4064, 4064 and 1893 bytes, each with the 4-byte segment header; reassembled by `unframe` in `:storage` mode | observed, both |
| replay | `(:read, oldest)`, one `:rx` per record under credit, `(:rx_end, next)` | observed, both |
| write, sync | 5 records, `tx_credit 8`, `tx_credit 5`, `synced 5`; records lie back to back; a record that does not fit opens the next block | observed, both |
| a Python-written backing read by Silica | every value decoded: a record, a 10000-byte string, a record with a boolean, a list of records, a negative and a 32-bit-wide integer | observed, both |
| a Silica-written backing against the Python image | byte for byte equal (16384 bytes) | observed, both |
| missing backing | created at the declared capacity, mode 0600; `log oldest=0 next=0`; `rx_end 0` | observed, both |
| wrong size (smaller and larger) | `(:link_down, :mismatch)`; the carrier stays until `:close`, then `(:link_down, :closed)`; the file is untouched | observed, both |
| a wrong payload byte, record not in the tail block | the records before it, then `(:read_failed, :corrupt)` | observed, both |
| a wrong payload byte, record in the tail block | no report: the log ends before that record (`next` is smaller) | observed, 999909 |
| a wrong byte in a block header | no report: the block is not part of the log (`oldest=1`), the later blocks are replayed | observed, both |
| second owner | a lock held by another process: `(:link_down, :in_use)` | observed, both |
| a backing that is not writable (mode 0444) | `(:link_down, :medium)` | observed, both |
| an unfinished frame before a whole one | the unfinished one is dropped without a report, the whole one arrives | observed, both |
| a stored frame with format id 9 | `wireframe@unrecord` answers `(:rejected, :bad_format)` | observed, both |
| a term of the wrong type for the decode | `(:rejected, _)` from `decode` | observed, both |
| taint | the owner (a plain actor in a `dangerous_` unit, or a behaviour of a `dangerous_` library unit) keeps the pending segments in its state, passes them to plain units (`wireframe`, the generated `bees_cfg_*`) and decodes there: accepted by both compilers | observed, both |

The carrier's normal end is reported on standard error by the runtime (it has no supervisor), from another thread, at no
fixed place in the output: the trial driver captures standard error apart and removes exactly that report.

## 2. The layout the packer writes (Silica's, read and observed)

All integers big-endian. `tools/bees_pack_store.py` is the only place BEES states it.

| Layer | Form |
| --- | --- |
| backing | `capacity` bytes, a multiple of 4096, zero where nothing was written |
| block | 4096 bytes: header, then records back to back |
| block header | `first_seq` (8), `state` (4; 1 in use), CRC-32C of those 12 bytes (4) |
| record | `length` (4), `seq` (8), CRC-32C over length, seq and payload (4), payload; never spans blocks; payload at most 4064 |
| payload | `frame_seq` (2, zero), `index` (2, bit 15 on the last segment), then at most 4060 bytes of the stored frame |
| stored frame | format id (1; `(:etf)` is 1), schema version (2), the encoded value (`wireframe@record`) |
| value | `term_to_binary` form: 131, then the `(:etf)` binding of design 4.7; a record is a map with atom keys in field-name order |

A sync pads to the next 512-byte write unit; the packer writes one run of records with no sync, which is what one drain of
the carrier writes, so no padding is needed and the bytes match.

Guard against a layout change in Silica: `trials/d1_store_layout` (seven cases). `read_packed` is a Silica program reading
a packer-written store and printing what it decoded; `write_compare` writes the same values from Silica and compares the
backing with the packer's image; the other five are the failure cases of section 1. `tools/test_bees_pack.py` checks the
Python side against vectors written out by hand (the CRC-32C check value, the first record's bytes, the segment headers).

## 3. The packer

`tools/bees_pack.py pack --config bees.config --capacity BYTES -o node.sildat [MANIFEST.wire ...]`

- Validation is `tools/bees_conf.py`'s, so a refusal is the same line `bees.config:LINE: PATH: MESSAGE`, exit 1. The file
  checks (exists, readable, the cookie's mode) stay there, at pack time.
- `--capacity` has no default: it is the capacity literal of the application's declaration.
- The backing is written to a temporary name with mode 0600 and moved into place.
- `bees_pack.py show FILE` prints a packed store with every secret as its length; `shapes` prints the record set.

The record set, version 1 (one table, `GROUPS` in `tools/bees_pack.py`, also drives the generated Silica reader):

| Schema | Record | Mode | Fields |
| --- | --- | --- | --- |
| 1 | index (first) | both | `frames`, `kind` ("bees.config"), `mode`, `version` |
| 2 | node | both | `creation`, `name` |
| 10 | net | beam | `epmd { mode, port }`, `listen_address`, `listen_port`, `listener` |
| 11 | time | beam | `frame_max`, `io_ms`, `open_ms`, `tick_ms` |
| 12 | auth | beam | `auth`, `cookie` (secret), `redial { initial_ms, max_ms, on }`, `transport` |
| 13 | link (one per peer) | beam | `address`, `host`, `how { by_epmd, dials, port, resolve }`, `name` |
| 20 | net | trust | `listen_address`, `listener`, `plaintext_test_only`, `port` |
| 21 | limits | trust | `args_len_max`, `frame_size_max`, `suspicion_limit`, `term_depth_max` |
| 22 | time | trust | `call_timeout_ms`, `connect_stagger_ms`, `connect_timeout_ms`, `more { client_handshake_timeout, dns_ns_timeout_ms, dns_total_timeout_ms, first_frame_timeout_ms }` |
| 23 | token | trust | `token_bytes`, `token_ttl_sec`, `whitelist_autoload`, `whitelist_default_spec` |
| 24 | session | trust | `idle_ms`, `max_age_ms`, `max_inflight`, `more { drain_ms, max_calls }` |
| 25 | tls | trust | `ca_pem`, `cert_pem`, `key_pem` (secret), `self_fp` |
| 26 | peer (one per whitelist entry) | trust | `cert`, `classical`, `fp` (128 hex characters, computed by the packer), `spec { all, perms: list of { a, f, m } }` |
| 27 | pin (one per pinned server) | trust | `addr`, `fp` |

Choices made, each the conservative one:

- Every record has at most four fields (nested for more), because the derived decoder of the pin takes four (SD-37; the
  refreshed compiler lifts this, and the table can then be flattened).
- Values are integers, byte strings and booleans only. No value is an atom, so a decode needs no atom beyond the field
  names and `true`/`false`, and the store does not depend on the atoms-in-types fix.
- One stored frame per record, a repeated record for each list entry: no decode is large, and a 1000-entry whitelist is
  1000 small frames.
- A carrier address is written beside its numbers (`listener: "listen:23400"`), so the application needs no
  integer-to-text code to open a carrier.
- Not yet in the table (they are in flux in other agents' work, or have no consumer yet): `client_tls_opts`, the BEAM-mode
  TLS options of N2T, `acceptors`, `session_slots_max`, `spawn` and its allowlist, the N5 multiplexing options, TEMPUS.
  Adding one is a row in the table; the generator and the tests follow.

## 4. The reader units (`src/config/`, generated)

`tools/bees_pack_gen.py write` writes them from the packer's table; `tools/test_bees_pack.py` fails when they are stale.

| Unit | Kind | What it is |
| --- | --- | --- |
| `bees_cfg_beam.silica`, `bees_cfg_trust.silica` | plain | `fresh/0`, `take/3` (one stored frame: schema number and `(:etf)` bytes), `finish/1` answering `(:ok, cfg) \| (:error, { record, schema, text })`, `show/1` (the sanitized summary, rule 11), `frame_cap/0` |
| `dangerous_bees_cfg_beam_store.silica`, `dangerous_bees_cfg_trust_store.silica` | behaviour | the reader actor: owner of the application's store carrier for the replay; sends the application exactly one message, `(:ok, cfg)` or `(:error, reason)`, after `(:link_down, :closed)` |
| `bees_cfg_beam.shapes`, `bees_cfg_trust.shapes` | text | the types an application spells (Silica has no alias) |

- D47: every `decode` carries `max_bytes: 4294967295` and `max_length: 4294967295` as literals, with `max_depth` from the
  type. What bounds a frame at run time is the cap given to `wireframe@unframe` (`frame_cap()`, 1 MiB for one
  configuration frame) and the per-field bounds checked after decode. Compiled and run on the pin.
- The second check: after decode every field is checked against the table's bounds again (a stale or hand-made store), with
  the two cross-field rules that lie inside one record (`args_len_max` against `frame_size_max`, `idle_ms` against
  `max_age_ms`). The text is `PATH: MESSAGE`; the line number belongs to the packer, which has the file.
- Refusals the reader produces (all observed in `trials/d2_store_config`, 999909): no readable record; another capacity;
  a record failing its check; a log not starting at record 0; a store for the other mode; fewer frames than the index
  states; a group missing; a group twice; an unknown kind; a value out of bounds; a record that does not decode as its
  kind; a first record that is not the index.
- The library never ends the program and prints nothing by itself: the application gets the value or the reason.
- Secrets: the cookie and the key are fields of the value the application receives; the reader actor holds the empty
  collection again after its one message; `show` prints `(secret, not shown)`. `trials/d2_store_config` checks that the
  cookie's text is in no output. No scrubbing is claimed.
- The reader actor's state holds the growing configuration, so SD-35's whole-state copy applies while it reads: for N
  whitelist entries the cost is quadratic in N. It runs once at boot; 42 entries read at once in the trial; a 1000-entry
  store was not measured.

What an application writes (the whole of it is in `examples/store_node/dangerous_store_node.silica.in`):

```silica
carried_on config: (:store) (:backing, "node.sildat", 65536, :stop);
...
car: dangerous_actor_ref <- spawn_dangerous_carrier(config, stack_policy(0, :keep_last_message), state_policy(:keep_state_area));
rd: actor_ref <- spawn({ acc: bees_cfg_beam@fresh(), car: car, rx: wireframe@fresh(:storage), to: me, why: "" },
                       dangerous_bees_cfg_beam_store@reader, stack_policy(0, :keep_last_message), state_policy(:keep_state_area));
_: boolean <- cast(car, (:open, rd, "") impl ActorMessage {});
```

and `me` is an actor whose message type includes `(:ok, <cfg>) | (:error, { record: int64, schema: int64, text: string })`.

## 5. The example application (`examples/store_node`, run by `trials/d3_store_node`)

One compilation unit: `silica.config` in the example's directory lists the root, BEES's three units (the two of `src/config` and the failure reporter) and the
language's eight through links in `lib/`; one compiler run; nothing copied, nothing compiled ahead. `make pack` writes `node.sildat` from
`bees.config`; `make start` runs the node.

What it shows (observed, 999909): the node actor receives `(:ok, cfg)`, prints the summary, opens its listener on
`cfg.net.listener` and cuts frames under `cfg.time.frame_max`. The trial starts the same executable on a store packed with
`frame_size_max` 4096 (a 10-byte frame is answered with the node's name, a 5000-byte frame is refused and the link closed)
and on one packed with 512 (500 accepted, 600 refused), and on no store (the refusal, nothing started).

What it is not: BEES's BEAM-mode or TRUST node. Those units read the generated constants (`bees_peers@...`, `beam_conf@...`,
`bees_trust_conf@...`), so they cannot be started from run-time values without changing them, and they belong to other
agents in this phase. The example's node is a listener, the frame cap and one answer.

## 6. Defects and oddities met

None is recorded as a Silica defect: nothing here was reduced to a one-file repro that shows wrong behaviour against the
specification. For the record, on 999909:

- A `case` over a union-typed binding, written inside a block that is itself an arm of an outer `case` over the message,
  was refused with E2005 "invalid or unsupported case pattern"; the same code moved into its own function compiles. A
  binding `r: (:ok, T) | (:error, E) <- case c of { true -> f(); false -> g() }` was refused with E2005 "case pattern does
  not match scrutinee type"; a function with the same body compiles. Both were worked around, neither isolated.
- `decode` of `[]` (131, 106) into a record type answers `(:rejected, :truncated)`, where `:bad_tag` would say more.
- By design, not a defect, but it shapes the reader: damage to a block header or inside the tail block is not reported
  (section 0, finding 5).

BEES-side finding: `tools/bees_config.py check` (the D30 rule that atom literals live in `bees_atoms`) refuses the store
carrier's vocabulary (`:store`, `:backing`, `:stop`, `:storage`, `:rx_end`, `:read_failed`, ...) in a leaf that has a
`.wire` manifest. It is a shared file and was not changed; the example keeps its manifest in `manifest/` so the build-time
generators do not run for it. The check must learn these atoms before a generated node can read a store (section 8, step 2).

Owner ruling (2026-11-18, through the coordinator): the store carrier's own vocabulary atoms may go on the language list of
the D30 check, because they are Silica's carrier atoms, not BEES protocol atoms; only atoms the store carrier itself
defines, taken from Silica's design and stdlib, with the source cited and a unit test. Done the same day: 25 atoms added to
`FIXED_ATOMS` in `tools/bees_config.py` (design 6.8.1, 6.8.2, 6.8.3, 6.8.9), tests in `tools/test_bees_pack.py`
(`StoreAtoms`). The carrier's private self-messages (`:drain`, `:recover`, `:step`) are not on the list. Also from the
coordinator: the Linux goldens of `d1_store_layout`, `d2_store_config` and the example were recorded on the remote machine
(28 outputs, byte-identical to the Mac's), and `make -C native store` built Silica's sidecar on Linux.

## 7. Owner questions

| # | Question | Options | Recommendation (the provisional choice made here) |
| --- | --- | --- | --- |
| Q1 | The record set: typed records per group, no atoms as values, an index record first. Is this the contract? | (a) as built; (b) one big term; (c) atoms for the closed sets (`mode`, `auth`, `epmd`) | (a). (b) needs one large decode and a larger literal state; (c) ties the store to the atom table |
| Q2 | A missing backing is created empty by the carrier, so a wrong path leaves a new file of the declared capacity and the node reports "no configuration". | (a) accept and document; (b) ask Silica for an open that does not create (request B2 was rejected) | (a) |
| Q3 | The carrier opens the backing read-write under an exclusive lock; a read-only file is `:medium`. A configuration store is therefore writable by the node's user, and one node at a time can hold it. | (a) accept: mode 0600, owned by the node's user; the reader never sends `:tx`; (b) ask Silica for a read-only open | (a) |
| Q4 | The capacity is a literal of the application; a configuration that outgrows it fails at pack time (`:full`) and needs a rebuild with a larger literal. Which capacity do BEES's examples and trials state? | (a) 65536 everywhere (enough for about 200 whitelist entries); (b) 1048576 (about 3000 entries); (c) per trial | (b) for the converted TRUST nodes, (a) for BEAM mode and small examples |
| Q5 | The cookie: BEAM mode's C edge reads the cookie FILE at each handshake today. Under D46 the cookie arrives as a value from the store. | (a) the edge takes the cookie as bytes from the node (N0c 4.3), `cookie_file` becomes a pack-time option; (b) keep the file read for the cookie only | (a); (b) is a C file read of configuration, which D46 rules out |
| Q6 | TLS material: certificates and the key as PEM bytes through the store, the engines taking bytes (N0c 4.1). The key is then in the store file. | (a) as N0c ruled; (b) key by path, read by the engine | (a), with Q3's file mode |
| Q7 | Goldens of an example live in `examples/store_node/`; `tools/test_platform_and_ports.py` scans `trials/` only for the Linux twins. | (a) leave; (b) extend the scan to `examples/` | (b), in phase 2 with the Linux recording |
| Q8 | A whitelist change needs the node stopped (one owner at a time), the store repacked, the node started. SEMP's `whitelist_autoload` reloads a file at run time. | (a) restart only (rule 12 says no live reload); (b) a second store for the whitelist that the node reopens | (a) |

## 8. What remains, and the migration plan

Inventory (counted 2026-11-18): 47 `bees.config` files in 15 trial leaves (m3_dist, m3_mesh, m3_multilink, m3_reconnect,
m4_demo, n1_frames, n1_limits, n2_dist, n2_live, n2_mesh, n2_multilink, n2_reconnect, n2_soak, n3_trust, n4_trust_tls), plus
the leaves other agents are building (n5, n2t, x1, x2, tempus). The node units read generated constants at these many
places in `src/`: `bees_peers@` 21 functions at 53 sites, `beam_conf@` 30 functions at 53 sites, `bees_trust_conf@` 42
functions at 113 sites. 44 `decode((:etf), ...)` calls in `src/` and the generators do not yet carry the literal ceiling;
`tools/bees_dist_gen.py` (line 196) and `tools/bees_trust_gen.py` (lines 84 to 87) write the configured value into the
literal.

Steps, in order; each keeps `make integrate` green, and the old path works until step 8.

1. Owners' agreement on the record set (Q1) and on Q5/Q6. Add the missing rows (section 3, last bullet) with N5, N2T and
   TEMPUS, who own those options.
2. (Done 2026-11-18: the store carrier's atoms are on the language list of `tools/bees_config.py check`.) `native/Makefile`:
   move `store` into `all` (it builds on Linux, coordinator's run).
3. D47 in the generators (owners: codec, N5): every generated `decode` gets the literal 4294967295; the cap is passed to
   `wireframe@unframe` and to the proxies as a value (it already is a run-time argument there). This changes no golden by
   itself; it can land before any trial is converted. Re-run: every m3, n1, n2, n3, n4, n5 leaf.
4. BEAM mode (owner of `dangerous_beam_net.silica` and `beam_node_edge.part`: N2T): replace the `beam_conf@` and
   `bees_peers@` VALUE functions (addresses, ports, timings, redial, frame cap, creation) by fields of a configuration
   value held by the node's actors; the NAME functions (peer names, indexes, the atoms) stay generated, since every atom
   exists at compile time. The node starts on `(:start, cfg)` as N0c 5.4 describes. First with the value built from the
   generated constants (no behaviour change, goldens unchanged), then from the store.
5. The cookie as bytes (Q5): `native/src` cookie edge and `dangerous_beam_auth*.silica` take the cookie from the node.
6. TRUST mode (owner: N5): the same for `bees_trust_conf@`; the whitelist's permission gate becomes data-driven over the
   `peer` records, with a pool of registered names sized at build time (N0c 3.1); TLS material as bytes (Q6).
7. Convert the leaves one mode at a time. Per leaf: the Makefile runs `bees_pack.py pack` where it runs the generators
   today; the root declares the store; the node waits for the reader's message. A changed `bees.config` then needs no
   rebuild, so the scenario sets that build one node per variant (n3_trust's negative cases, n2_dist's wrong cookie) can
   reuse one executable: fewer compiles. Goldens change where the boot text changes: record on both platforms.
8. Remove the build-time stand-in from the generators (`--config` of `bees_config.py generate`), and the
   "BUILD-TIME STAND-IN" notes; `bees_conf.py` stays as the packer's validator. Boot refusals that were build failures
   (BEAM mode) become the packer's exit 1; `trials/n3_trust` (g) keeps its boot-time form through the reader's
   `(:error, ...)`.
9. Boards: no `(:flash_region)` medium exists yet, so a board build takes its configuration from `(:memory)` filled by a
   generated unit, or from literals (N0c 5.6 item 3). Nothing was done for the boards here.

## 9. Files

New: `tools/bees_pack.py`, `tools/bees_pack_store.py`, `tools/bees_pack_gen.py`, `tools/bees_pack_trial.py`,
`tools/bees_pack_trial.mk`, `tools/test_bees_pack.py`; `src/config/` (six generated files); `examples/store_node/`;
`trials/d1_store_layout/`, `trials/d2_store_config/`, `trials/d3_store_node/`; this document.

Shared files, add-only: `tools/trial_ports.py` (blocks `d3_store_node` 23400, `f1_fuzz_wire` 23500, `f2_fuzz_long` 23600;
`d2_store_config` on the data-only list), `.gitignore` (the store lines at the end), `native/Makefile` (the on-request
`store` target at the end).

Goldens recorded for `macos_applesilicon` on the pin; the `linux_x86_64` twins were recorded by the coordinator on 2026-11-18:
`trials/d1_store_layout` 7, `trials/d2_store_config` 18, `examples/store_node` 3. On Linux, to check first: that
`silica_store.c` builds with the platform's flags (`make -C native store`) and that the Linux compiler's stdlib has the
`(:backing)` rows (Silica's own run of 2026-11-13 says so).

## Owner rulings on section 7 (2026-11-19, recorded by the coordinator)

- Q1 RULED: the record set as built (one record per group, at most four fields while SD-37 stands on the pin; flattened after the compiler move).
- Q2 RULED: accepted that the carrier creates a missing backing; the reader then reports that there is no configuration and the node starts nothing.
- Q3 RULED: accepted that the backing is opened read-write, mode 0600; BEES's reader never writes to it.
- Q4 RULED: the examples and trials use a capacity of 1 MiB for a TRUST node and 64 KiB otherwise. These are not BEES defaults: the application states the capacity in its own declaration and gives the packer the same number.
- Q5 RULED: the cookie travels as bytes in a record of the store.
- Q6 RULED: TLS certificates and private keys travel as PEM bytes in records of the store; the TLS engine is given bytes, not paths.
- Q7 RULED: the Linux-twin golden test is extended to `examples/`.
- Q8 RULED, not as recommended: a whitelist change does NOT need a restart. The node loads its store again while running. The trigger is a message sent by the user: the application sends BEES a reload message, and the application receives the operator's request through Silica's input support (a Silica version that accepts input exists and is not merged yet). To be designed with the conversion: which groups may change at a reload (the whitelist and pins at least), what happens to connections and sessions of a peer that the new whitelist no longer lists, what a reload does when the new store is refused (keep the running configuration and report), and how the trials send the message before Silica's input support is merged (a test-only path).
- Q8, follow-up RULED 2026-11-19 (owner): when a reload removes a peer from the whitelist, that peer's open connections and sessions are cut at once; calls in flight are not allowed to finish.
