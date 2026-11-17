# N0b: the boot-time configuration reader (plan, 2026-11-17)

**Status: PLAN ONLY. Nothing here was built, compiled or run; no code, trial or other document was changed.** It follows the user's
ruling of 2026-11-16, "silica can now read files using transport, so this can be done": the boot-time reader that
[bees-config-file.md](../bees-config-file.md) section 11 left as a proposal (and the user, on 2026-11-10, left to another agent) is
to be built. This plan checks that ruling against what Silica actually has, because **the first finding changes the plan**.

Everything marked *(unverified)* was read in the sources but not run. Silica sources read: `/Users/yenrab/silica/compiler` at its
current checkout (HEAD `c7b73b2707`); whether BEES's pinned compiler (`tools/silica.generation`: `silica-999909-macos-applesilicon`)
contains the storage carriers is *(unverified)*: they were committed 2026-11-12 (`d11c763a1d`) and the pin file names a number, not a
date.

## 0. The short version

1. **What Silica's transport reads is a record log, not a text file.** The storage carrier `(:store) (:backing, "x.sildat", capacity,
   retention)` reads and writes a durable log with its own on-medium format (4096-byte blocks, CRC-32C, sequence numbers). It cannot
   open an operator's hand-written `bees.config`. A tool must first write the file into that format. So "read files using transport"
   is true only for files that Silica (or a packer) wrote.
2. **There is a second, older route that does read plain text: the intrinsic `read_lines(path)`** (the whole file as one string, run-time
   path, hosted targets, `proc[device_io]`). It has no error cause, no size cap, no file-mode check, and its taint status is
   *(unverified)*. It is not "transport".
3. **The taint rule decides the design more than the carrier does.** Whatever bytes a foreign call (carrier, native edge) delivers are
   tainted; a hand-written parser's output is tainted too (M0, spikes/S8); only `decode((:etf), ...)` de-taints. So a Silica parser can
   run only on text that arrived through `decode` (the §11 proposal's trick: the edge hands the bytes over as one ETF binary term) or
   through an untainted intrinsic (`read_lines`, if that is what it is).
4. **Atoms are the easy part: `decode` already rejects `:unknown_atom` and `:bad_variant`.** A config value that names an atom the
   program does not contain is a boot error with no code of BEES's own (D30 holds; section 3.6).
5. **About 40 percent of today's options really are run-time values; the rest need either a code-structure change (the whitelist, the pins,
   the peer table's per-link values) or must stay build-time (decode limits, atoms, pool sizes).** The Python reader therefore cannot be
   retired; it becomes the build-time extractor and the test oracle (section 3.9).

Recommendation (section 3.1): **read text through BEES's own native edge, wrap it as an ETF binary, de-taint it with `decode`, parse and
validate in Silica; use the storage carrier for what it is good at (a board's packed config, persisted quarantine state), not as the
reader of an operator's text file.** This is the user's call (questions Q1 to Q3).

## 1. What Silica provides now

### 1.1 Route A: the storage carrier `(:store)` (this is what the ruling most probably means)

| Item | Fact | Where |
| --- | --- | --- |
| Declaration | `carried_on NAME: (:store) (:backing, "PATH.sildat", CAPACITY, RETENTION);` at top level of a `dangerous_` module. The path is a **string literal in the declaration** ("the path appears only here"); capacity is a positive multiple of 4096; retention is always written: `:ring`, `:stop` or `:trim` | transport_serialization_design.md 693-720 (line 698 is the example); spec 16.4.11 (silica-specification.md 10814) |
| Starting it | `c: dangerous_actor_ref <- spawn_dangerous_carrier(NAME, stack_policy(0, :keep_last_message), state_policy(:keep_state_area))`, then `cast(c, (:open, self(), "") impl ActorMessage {})`. The `(:memory)` store is an ordinary `actor_ref`; the `(:backing)` store is a dangerous actor | `trials/transport_addition/app_transport_store_backing/dangerous_store_backing_restart.silica` (read) |
| Contract, program to carrier | `(:open, owner, "")`, `(:tx, record, from)`, `:sync`, `(:read, from)`, `:read_stop`, `(:credit, n)`, `(:trim, upto)`, `:close` | design 735-760; spec 16.4.11 |
| Contract, carrier to owner | `(:link_up, info)`, `(:log, oldest, next, capacity)`, `(:tx_credit, n)`, `(:synced, next)`, `(:rx, record)`, `(:rx_end, next)`, `(:tx_failed, why)`, `(:read_failed, why)` with `:trimmed :beyond_tail :busy :corrupt`, `(:link_down, why)` with `:closed :in_use :mismatch :medium` | same |
| How a "file" is read | Open, wait for `:link_up` then `:log`; grant receive credit `(:credit, n)`; send `(:read, 0)`; receive one `(:rx, record)` per credit until `(:rx_end, next)`; each record is at most **4064 bytes** (`Carrier@mtu`), a larger value is segmented by `wireframe@frame(..., :storage)` and put back by `wireframe@unframe` in `:storage` mode; then `:close` (the carrier ends). A record is an ETF (or CBOR) frame with an optional `wireframe@record` header (format id, schema) | design 790-826, 961-1005 |
| On the medium | 4096-byte blocks; 16-byte block header `{first_seq, state, crc32c}`; 16-byte record envelope `{length, seq, crc32c}`; all big-endian; a sync pads to the 512-byte write unit | design 975-985; `compiler/stdlib/storelog.silica` (371 lines) |
| Size limits | fixed `capacity` per declaration, **an existing backing of another size ends the open with `(:link_down, :mismatch)`**; one value (frame) is held whole in RAM and bounded by the `decode` limits and a 32768-segment ceiling | design 705-709, 810-826 |
| Errors | `:medium` (cannot be opened, read, written, flushed), `:in_use` (an `flock` is held, by this or another process), `:mismatch`, `:corrupt` (a record failed its CRC; the replay stops). **A missing path is not an error: the first open creates the backing at the declared size** | design 705-709, 760, 1021-1032; `compiler/stdlib/dangerous_store_backing_carrier.silica` header (read) |
| Taint | The carrier keeps no byte of the log; a record leaves only as the foreign result `(:rx, payload)` cast to the owner, whose `decode` re-creates the value: "every stored byte is untrusted on every target" | design 824-826 (decision 8), 1033-1050 |
| Targets | Apple Silicon macOS: built and trialled (S0, S1, 2026-11-12). Linux AArch64 and x86-64: in the pack source, "built and run in the next trial pass", not verified. Boards: `(:sd_blocks, n, ...)` and `(:flash_region, n, ...)` are named and checked by the language and provided by **no target yet** (E2412); `(:memory)` works everywhere | design 883-892; spec 16.4.11 |
| Trials | `trials/transport_addition/app_transport_store_memory/` (seven programs), `app_transport_store_backing/` (six programs, a second process run, `make_backings.py` writing damaged backings independently in Python), `trials/error_enforcement_addition/store_*` (eight) | design 975, 1007-1032 |
| Wrapper | `compiler/stdlib/dangerous_store.silica` (96 lines, Fifi bindings `silica_store_open/read/write/flush/close`) over `compiler/stdlib/net/silica_store.c` (open under `flock`, `pwrite`, `F_FULLFSYNC`) | read |

**What this means for `bees.config`.**

* The file is not text, not operator-editable, and not found by a run-time path. A **packer** (a tool, not the program) must write it
  at the exact declared capacity with correct block headers and CRCs. `trials/.../make_backings.py` is a Python precedent that writes
  this format; nothing in Silica's tree writes a backing from text.
* The path and the capacity are literals of the program: **where the configuration lives is a build-time fact**, and the `.sildat`
  name is a convention (design line 710).
* A missing configuration is invisible as an error: the open creates an empty log. The reader would have to treat
  `(:log, 0, 0, ...)` (empty) as "file missing" and a stray empty `.sildat` is left behind.
* Each of `bees.config`, the whitelist and the pin file would be its own declaration (own literal path, own capacity), and the
  whitelist's and pin file's variable number of files would not fit "one declaration, one region".
* A 64 KiB file is 16 blocks and about 17 segmented records, read with credit. It is workable; it is not a one-call read.
* What the route does give: an integrity check (CRC), torn-write recovery, and a medium that exists on boards (`:flash_region`) once a
  target provides it.

### 1.2 Route B: the intrinsic `read_lines`

| Item | Fact | Where |
| --- | --- | --- |
| Signature | `read_lines(path: string) -> string proc[device_io]` (the spec's design says `list<string>`; the compilers return the whole content as one string); `read_file` does **not** exist; `file_exists(path) -> boolean` exists | silica-specification.md 3525-3537 ("Implementation status (2026-10-16)"), 14846 |
| Where it runs | Inline emitters per target (`compiler/src/emitter/<target>/terms/file_io_inline.silica`: apple_silicon_mac, linux_aarch64, linux_x86_64, and STM32/ESP32 copies) call `_silica_read_file_path` (`compiler/src/silica_rt_shim.s:111`). The compiler's own driver uses it to read `silica.config` (`compiler/src/main_driver.silica:37`) | read |
| Behaviour | `open`, `lseek` to the end for the size, `malloc(size+1)`, `read`, NUL-terminate, close; returns `(success, SilicaString*)`. **Any failure returns success 0 and a null string, so a missing file, a permission error, a directory and a read error look the same.** No size cap (a huge file is one `malloc`); no `fstat`, so no regular-file test and no mode test; a short read is silently kept | `silica_rt_shim.s:111-190` (read) |
| `file_exists` | is implemented as the same read attempt (`file_io_inline.silica`, "bootstrap parity"), so it costs a whole read and answers false for an unreadable file | read |
| Taint | It is a language intrinsic under `device_io`, not a `dangerous_` foreign call, so the FFI taint rules (ffi wrapper spec) should not apply. **Not verified**; the compiler's own use proves only that the result can be parsed by hand in the compiler | *(unverified)* |
| Examples/trials in Silica | None found for user programs (`grep read_lines` over `trials/` and `examples/` returns nothing); the only uses are the compiler's own driver, lexer runner and module reader | grep |
| Targets | hosted macOS and Linux; the boards have no file system (the STM32/ESP32 emitters carry the inline emitter, whether it works there is *(unverified)* and irrelevant: section 3.8) | |

### 1.3 Route C: BEES's own native edge (already proven for the cookie)

`native/src/silica_bees_beam.c` `bees_beam_load_cookie` (lines 37-65) already does what a configuration read needs: `open(O_NOFOLLOW)`,
`fstat`, regular-file test (tag 4), mode test `(st_mode & 077) != 0` (tag 2, with the mode), size and ASCII test (tag 3), `errno` as the
error code (tag 1), and a secret kept in C memory under a lock, never in Silica. The resolver edge is the second precedent. The §11
proposal's `bees_conf_read_etf(path)` is this shape, returning the file as an ETF binary term. About 60 to 100 lines; the
Silica face is a worker like `dangerous_bees_resolve@rslv` (one request, one tainted cast to the requester).

### 1.4 What is missing or awkward: requests for Silica (SR-n style, not filed)

* **SR-A. A plain-file read with typed errors.** `read_file(path, max_bytes) -> (:ok, string) | (:error, :enoent | :eacces | :not_regular | :too_large | :io)`; or a `(:file, path)` read-only carrier link. Today `read_lines` merges every failure and has no cap.
* **SR-B. A file-metadata read.** `file_stat(path) -> (:ok, { size, mode, kind }) | (:error, ...)` (needed for the key and cookie mode check, rule 8, and for "is a regular file").
* **SR-C. State whether `read_lines` output is taint-free**, and say so in the FFI wrapper specification; add a trial that parses it by hand and sends the result to an actor.
* **SR-D. `decode` limits as run-time values.** Limits are a record literal baked into the derived decoder (E2402; the `DECODE_WHY` of tools/bees_conf.py). A config-driven `frame_size_max` and `args_len_max` could then become boot values.
* **SR-E. Store: a text-to-store importer or an explicit "read-only existing file" mode** (never create on open; `(:link_down, :missing)`), a run-time path, and a way to read a store of unknown size (no `:mismatch` for an operator's file).
* **SR-F. A process-wide immutable value** (read once, visible to all actors) or a documented pattern for "boot configuration"; today every consumer is a zero-argument function of generated constants, and values cross actors by spawn state or by message (SD-35 makes a heap value in actor state expensive).
* **SR-G. `int_to_string` and `string_to_int`** are absent (spec 14846); BEES keeps hand-written copies (`int_text` in three units). A parser and a banner need both.
* **SR-H. Spec 5.2/22.6 say `read_file` exists in design; the status paragraph and the ruling disagree with what a programmer meets.** Ask the Silica owner what "can now read files using transport" covers (Q1).

## 2. Inventory: every value BEES reads from files, where it is consumed, and its class

Classes: **(a)** a run-time value today and can be read at boot with no change to generated code (it is only a generated constant);
**(b)** needs a code-structure change to become a run-time value; **(c)** must stay build-time. The table starts from section 11 of
bees-config-file.md and is checked against the code; **corrections to section 11 are marked CORRECTED**.

Consumers: "generated" means a zero-argument or indexed function of `beam_conf` (tools/bees_config_beam.py `gen_conf`),
`bees_trust_conf` (tools/bees_config_trust.py `gen`) or `bees_peers` (tools/bees_dist_gen.py `generate` from `bees_conf.m3_link`).

### 2.1 `node` and `beam` (BEAM mode)

| Value | Consumed as | Class | Note |
| --- | --- | --- | --- |
| `node.name` | `bees_peers@node_name()`, atoms of the manifest | **c** | the node name is an atom (D16, D30); the boot check is "file equals the built name" (rule 10) |
| `node.creation` | `beam_conf@creation()` (handshake and REG_SEND/pid encoding) | **a** | read in `beam_dist@put_n_*`, `dangerous_beam_net` |
| `beam.transport`, `beam.auth` | `beam_conf@auth_cookie()`, banner | **a** | closed atom set, validated by a table |
| `beam.cookie_file` (path) | `beam_conf@cookie_path()` into the cookie worker's state | **a**, and half-done | the file is already read by the native edge at each handshake with the mode check (`bees_beam_load_cookie`); at boot only the **path** is needed and the check moves from "handshake" to "boot" (trial `n2_dist/loose_cookie` changes: section 4) |
| `beam.listen_address`, `listen_port`, `epmd`, `epmd_port` | `listener_address()`, `epmd_address()`, `epmd_lookup_address_of(i)`, `link_*_of(i)` strings built in Python with the open timeout appended | **b** | the address strings are composed in the generator (`:open_ms` appended, `listen:any:PORT` vs `listen:PORT`); the composition (`listen_form`, `dial_check`, loopback rule) must be ported to Silica, then they are values. Table-driven in the Python, so a straight port |
| `beam.net_ticktime_s`, `open_timeout_ms` | `tick_ms()`, `io_ms()`, `open_text()` | **a** | derived values (`io_ms`, `tick_ms` from the tick time) must be ported |
| `beam.spawn`, `spawn_allowlist` | not consumed by a generated unit I found (spawn is none in the built nodes) | **a** *(unverified: only the reader and docs name them; no consumer found by grep)* | |
| `beam.peers` | the manifest's `peer` lines: `bees_peers@peer_index/peer_name/peer_count`, per-peer proxies `start_proxies_p<i>`, reapers; `link_dials_of(i)`, `link_by_epmd_of(i)`, `link_resolve_of(i)`, `link_host_of(i)`, `link_port_of(i)`, `link_address_of(i)`, `peer_short(i)` | **c for names and count; b for host, port, role** | the peer names, their count and the remote/local names are atoms and per-peer generated units (D16, D30, the user ruling of 2026-11-16). The per-link host/port/role are `case i of` constants today; they become boot values if the table of links is a boot record indexed by the build's peer index (the "in-flight" `eff['links']` model, section 5) |
| `beam.frame_size_max` | `beam_conf@frame_max()` into `wireframe@unframe(..., cap)` and `bees_dist@reg_send_body_max(..., cap)`, **and** the literal limits of the derived `decode` in `bees_msgs` | **c for the decode literal; a for the unframe/send cap** | CORRECTED nuance: section 11 is right. Boot rule: the file's value must be `<=` the built value, else a boot error "not built yet" (rule 9, the same wording as a value above what the build implements) |
| `beam.redial`, `redial_initial_ms`, `redial_max_ms` | `beam_conf@redial*()`, `bees_peers` | **a** (CORRECTED: the reader's table marks them `when="build"`, "constants of the generated beam_conf and bees_peers"; they are plain scalars and need no atom or limit literal, so they are class **a** like `net_ticktime_s`. In flight, section 5) |
| the manifest (`.wire` lines, `.beam` pid lines) | atoms, codecs, proxies, pid tables | **c** | never a boot option |

### 2.2 `trust` (TRUST mode)

| Value | Consumed as | Class | Note |
| --- | --- | --- | --- |
| `port`, `listen_address`, `listen_prefix` | `bees_trust_conf@listen_spec()`, `port()`, `listens()` | **a** (address composition as above) | `listens()` also depends on the whitelist being configured |
| `tls_opts`, `client_tls_opts` (three paths each) | `tls_server_spec()`, `tls_client_spec()`: the three paths made absolute, each ended by a NUL, plus a classical flag, built with `bytes_of` | **a** | needs absolute-path resolution against the config's directory at boot (the C edge or a Silica string join); the key-file mode check (rule 8, a **new boot check**, SR-B) |
| `whitelist_file`, `whitelist_cert_dir`, `whitelist_default_spec`, `whitelist_autoload` | the whitelist: `peer_count/peer_hex(i)/peer_index(fp)/peer_name(i)/permitted(i,m,f,a)` with one generated function `perm_i` per entry; one registered `tpeer` actor per entry named `bees_trust_peer_<i>` (an atom per entry) | **b (the data) and c (the pool)** | CORRECTED nuance: the atoms are `bees_trust_peer_0..K-1` and carry **no content** (the content is the fingerprint string and the spec), so a fixed pool of K names, sized at build, serves any whitelist of at most K entries; K is a new build-time number (section 3.5). The gate must be data-driven: the spec (`none`, `any`, per-module lists of `{function, arity}`) becomes a decoded value, `permitted` a function over it |
| `classical_allowed_certs` (D44) | `peer_classical(i)`, the second TLS flag | **b** (with the whitelist) | CORRECTED: the reader's table says `when="build"`; it is data of whitelist entries, so it moves with them |
| `server_pins_file` | one registered client cache per pinned server `bees_trust_srv_<i>`; `server_index(addr)`, `tls_server_pin(i)` | **b and c** (pool of M server names, M a build number) | same pattern as the whitelist |
| certificate files named by the whitelist and pins | `peer_hex`, `tls_server_pin`: SHA-512 of the DER (PEM base64 decoded) computed by Python at build (`fingerprint`) | **b** | a boot read needs the fingerprint from a file: native edge `bees_conf_sha512_der(path)` (CommonCrypto on Apple, OpenSSL on Linux, D40) returning hex; Silica has no SHA-512 *(unverified: `crypto-proposal-introduction.md` is a proposal)* |
| `call_timeout_ms`, `suspicion_limit`, `token_bytes`, `token_ttl_sec`, `connect_timeout_ms`, `connect_stagger_ms`, `client_handshake_timeout`, `first_frame_timeout_ms`, `dns_*`, `acceptors`, `session_slots_max`, `session.*`, `plaintext_test_only` | `bees_trust_conf@call_timeout_ms()` etc., `dial_text()` (a string of `connect_timeout_ms`) | **a** | pure scalars; `plaintext_test_only` selects the link part (`bees_trust_link_plain.part` vs `_tls.part`) **at build** today, so it is **c unless the two links are both built in** (section 3.7; in-tree today only one is) |
| `frame_size_max`, `args_len_max`, `term_depth_max` | `bees_trust_conf@frame_size_max()` etc., **and** the literal limits of the generated `bees_trust_mfa` `decode` | **c (decode literal) / a (unframe cap)** | as `beam.frame_size_max` |
| quarantine and token state | none persisted ("lost on restart", D10) | not a file today | a later `(:store)` use, section 3.8 |

### 2.3 Not files but build outputs that look like config

`bees_atoms` (D30; `*.atoms` manifests), `bees_peers`, `bees_msgs`, `bees_trust_mfa` (the `.trust` manifest: the MFA table, "a
function that was not compiled in does not exist"), `beam_peers`. All **c**.

## 3. Design

### 3.1 The read route (decision D-1, recommended; the user decides, Q1/Q2)

| | A: store carrier | B: `read_lines` | C: BEES native edge (ETF-wrapped) |
| --- | --- | --- | --- |
| Operator edits a text file | no (needs a packer) | yes | yes |
| Path at run time | no (literal) | yes | yes |
| Distinguishes missing / unreadable / not regular / too big | no (missing creates) | no (all "empty") | **yes** (errno, tags) |
| Mode check for keys, cookie | no | no (no stat) | **yes** (precedent) |
| Size cap before reading | capacity | none | **yes (64 KiB)** |
| Taint | de-tainted by `decode` | unverified | de-tainted by `decode` (the ETF-wrapped binary) |
| New code outside Silica | packer | none | ~100 lines C |
| Boards | `:flash_region` when a target provides it | no FS | no FS |
| Works today on the pin | unverified | unverified (probably) | yes (cookie and resolver edges are built) |

**Recommendation: C for hosted targets, A for boards and for persisted state, B as a probe only.** Reasons: C is the only route that keeps
every message the Python reader prints today ("does not exist", "not readable (permissions)", "readable by group or others") and the
2026-11-06 ruling R2 (a configured file missing or unreadable is a loud, named failure). The ruling of 2026-11-16 is honoured in its
spirit (the boot reader is built, in Silica); its literal route (transport) is used for the board answer and for state, where a log is the
right medium. B is attractive because it needs no C, but cannot satisfy R2's wording or rule 8 without SR-A and SR-B.

### 3.2 Where the reader lives

* `src/shim/bees_conf.silica` (hand-written Silica, D26), the parser and validator, as pure functions over a `string`: no foreign call, no
  actor. It `use`s only `bees_atoms` and its own table units.
* `src/shim/dangerous_bees_conf_native.silica` and `dangerous_bees_conf.silica`: the face and the worker of the native edge, in the style of
  `dangerous_bees_resolve_native.silica` and `dangerous_bees_resolve.silica` (read for their shape only).
* `native/src/silica_bees_conf.c` (new, in the same archive `libsilica_bees_native.a`): `bees_conf_read(path)` (open `O_NOFOLLOW`, `fstat`
  regular, size <= 65536, `read`, close; result **an ETF binary term** or a tagged error), `bees_conf_mode(path)` (the mode, for keys),
  `bees_conf_sha512_der(path)` (hex). Nothing else: no parsing in C.
* The boot actor (a behaviour, phase field, in `bees_trust_node.part` / `beam_node_edge.part`, the same files the generators splice) sequences:
  read `bees.config`, parse, then for each configured file read it, then start the node. Phases are messages, not a loop (a
  block has no loop, the store carrier's `:recover`/`:step` pattern is the precedent).

### 3.3 How the text is parsed

* The grammar is section 4 of bees-config-file.md (one term and a full stop; lists, tuples, atoms, integers with `_`, strings with four
  escapes, maps; `%` comments; ASCII only; 64 KiB); the oracle is `tools/bees_conf.py` (`Reader`, lines 58-183) and the vectors of
  `tools/test_bees_conf.py` (six test classes; the worked example of section 6 is parsed from the document itself).
* **Output representation: flat, not a tree.** A recursive term tree needs a recursive type (`ref?(L, S, rec)`), and the checker's cost
  around nested types is known to be bad (SD-36, SD-29 family). The parser emits a flat `List[Entry]`, `Entry = { path: string, line: int64,
  kind: atom, num: int64, text: string }` where `path` is the option path (`trust.session.idle_ms`, `beam.spawn_allowlist.0`,
  `trust.tls_opts.certfile`). A table-driven validator (the `OPTIONS` table as `case` functions: kind, lo, hi, choices, default) then
  checks unknown key, duplicate key, type, bounds, cross-field rules and mode-required values, and answers one line
  `bees.config:LINE: PATH: MESSAGE`. This is a port of `proplist`, `want_*`, `beam_section` and `trust_section`.
* The messages must be **byte-identical** to the Python reader's, because the goldens contain them (n3_trust `boot_missing.sout`:
  `[trust] boot refused: bees.config:8: trust.whitelist_file: whitelist file "..." does not exist (relative to the directory of bees.config)`).
  Differential oracle: a new `bees_conf.py dump FILE` command (prints `path=value` lines and the verdict) and the same dump printed by the
  Silica reader; the trial diffs them over the whole corpus (section 4, phase 4).
* Integers: hand-written `int_text` exists; a hand-written `parse_int` with the `_` rule is new (SR-G).

### 3.4 How results reach the node (the Silica constraints)

* **No globals.** Every consumer today calls a zero-argument generated function. Boot values must travel by (i) spawn state, (ii) message, or
  (iii) a registered **config actor** answering requests. Rule of thumb for this design: **scalars go in spawn state; strings go to the
  worker that needs them at spawn** (the cookie worker already holds its path in state, `dangerous_beam_auth`); anything read on every
  frame stays a scalar in the receive actor's state.
* **SD-35** (heap values in actor state cost a whole-state copy per dispatch; still open, worked around): do not keep the whitelist's
  strings in the hot connection actor. Keep the gate in its own actor (one `tpeer` already exists per entry) and reach it by message
  at the one place a call is checked (`permitted`). Cost to measure, not assumed (spike S3's method).
* **E1070** (at most eight parameters per function): the boot record cannot be one eight-parameter call; it is passed as a record value
  (allowed; the connection actor already uses a fourteen-field sub-state) or in groups.
* **SD-3/D30** (atoms): see 3.6.
* The boot actor owns the parsed `Conf`; it starts the node by spawning actors with the scalars. Nothing is cast while tainted (3.6).
* **Transitional shape that avoids a flag day:** keep the module names and function names (`beam_conf@frame_max()`), but generate them as
  *accessors of the config actor* in a later phase only for (a) values; phase 3 converts one consumer family at a time (section 4).

### 3.5 Build-time facts that remain (the "build facts" record)

The Python reader still runs at build and writes a small generated unit `bees_build_facts` with: node name and peer names (already atoms);
the decode limits it baked in (`frame_max_built`, `args_len_max_built`, `term_depth_max_built`); the pool sizes **K** (whitelist names) and
**M** (pinned-server names); `tls_built` (which link part is compiled in). **New build-time options** (the one reader's table gains
`trust.whitelist_slots_max`, `trust.pinned_servers_max`, `when="build"`): the build needs a number to size the atom pools and cannot read
the whitelist file's entries at boot to learn it. Default: the entry count of the file at build time, rounded up to a multiple of 8, with
the build printing the number; a boot file that needs more is refused with `trust.whitelist_file: N entries, the program has names for K
(rebuild with trust.whitelist_slots_max N)`. The boot reader validates the file against the facts: equal for names and the node name,
at most for limits and pools.

### 3.6 Taint, untrusted text, and atoms (D30)

* The file's text is untrusted. Path: native edge worker (dangerous, `external_danger` sequence) casts `(:text, etf_binary)` to the boot
  actor; the boot actor, in a `sequence proc[mem(normal), transport] ... produces pure` block (the 2026-11-06 ruling, mvp.md section 4), calls
  `decode((:etf), frame, { max_bytes: 65600, max_length: 65536, max_depth: 4 })` into **`(:ok, string) | (:rejected, atom)`**; the `string` is
  pure; everything after is ordinary Silica. The same shape for the cookie check (it stays in C), for fingerprints (hex string) and for
  mode bytes (an integer). **SD-25's caveat holds** (the checker accepts the handler; whether it truly gates is the compiler's, silica-defects.md
  SD-25 text in "Checked 2026-11-10").
* **Whether the ETF-wrapped binary's `decode` into `string` passes the taint checker on BEES's pin is *(unverified)*** and is the first
  spike (section 4, phase 0); the §11 proposal assumed it.
* **Atoms.** All atoms are known at compile time (D30, user ruling 2026-11-16: "all atoms must be known at compile time", and the
  listening node that learns its peer at handshake creates no atom at run time). Config-derived atoms and how each is validated at boot:

| Config-derived atom | Present at compile time because | Boot validation |
| --- | --- | --- |
| `beam.transport` (`tcp`, `tls`), `beam.auth` (`cookie`, `none`), `beam.epmd` (`external`, `none`), `beam.spawn` (`none`, `allowlist`, `any`), `mode` (`beam`, `trust`) | closed sets in the reader's table: Silica atom-union types and `case` literals | the parser's table rejects anything else with the Python reader's message; no atom is created |
| node name, peer names, remote/local message names | manifest -> `bees_atoms` | file value compared as a **string** with `bees_atoms@spelling(...)`; a name not equal to a compiled name is "does not name a peer of the build (D16)"; `bees_atoms@from_spelling(s)` answers `found: false` for an atom not in the program, which is the boot error |
| `trust.whitelist` module/function names in specs | MFA table `bees_trust_mfa` (the `.trust` manifest) | held as **strings** (the gate compares strings, as `perm_i` does today); a spec naming a function not in the MFA table is allowed and simply never matches (SEMP's behaviour); an optional warning note is a new, deliberate difference to decide (Q6) |
| registered names `bees_trust_peer_<i>`, `bees_trust_srv_<i>` | generated into `bees_trust_conf.atoms` for i < K, M | more entries than K or M is a boot error (3.5) |
| any atom inside a decoded value | the program's atom table | `decode` answers `(:rejected, :unknown_atom)` or `:bad_variant`; the boot actor reports `bees.config: (decode): ... names an atom the program does not contain` |

* **Secrets.** The cookie and the TLS keys never enter Silica: the native edge reads and checks them (cookie already does), Silica holds
  paths only; the boot banner and summary print no path of a key and no secret (rule 11, unchanged). Mode check: regular file, no group or
  other bit (`0600`), at boot for the cookie file, `keyfile` of both TLS blocks (the same text as the Python reader's, rule 8). Error
  text from C is mapped to the Python reader's wording with `errno` rendered by the edge, not by Silica.

### 3.7 Fail-fast, banner, exit codes

* Boot aborts before any actor of the node starts, prints **the same line**, exits 1 (TRUST: `[trust] boot refused: <line>` then
  `[trust] no actor was started`, `exit=1`, as `trials/n3_trust/boot_missing.sout`; BEAM mode: today the *build* stops; at boot it prints
  `[bees] boot refused: <line>` and `[bees] no actor was started` (a new pair of lines, mirroring TRUST) and exits 1).
* A refusal the boot actor itself raises uses a root `stop_self` ordering that the node already uses for TRUST (`bees_trust_node.part:41-50`);
  how an exit status of 1 is returned from a Silica program that is not `main` is *(unverified here; the TRUST part already does it)*.
* The boot summary and notes: ported from the Python `summary` / `banner` / `notes` strings so the output is unchanged (3.3). Where a value
  is a number, `int_text`. The banner/summary lines stay the first lines printed, before any other output.
* `plaintext_test_only` and the two TLS link parts: today the choice is made at build (`bees_trust_link_plain.part` vs `_tls.part`). A boot
  reader can read `plaintext_test_only` as a value only if both link parts are compiled in and the choice is a boot branch. That is
  a code change with a cost in program size and a security question (a test-only mode compiled into a production binary). **Recommendation:
  keep it class c (build-time) and make the boot reader refuse a file whose `plaintext_test_only` disagrees with the build**; ask the
  user (Q5).

### 3.8 The whitelist and pin files, reload, targets without a file system

* Both are read at boot with the same parser (same grammar, 64 KiB), **after** `bees.config`. Missing, unreadable or unparseable
  is always a loud failure (R2). A whitelist entry whose certificate is missing is logged and skipped (SEMP), as today. A certificate
  file is read by the edge only for its SHA-512 (no certificate bytes enter Silica).
* **Reload.** `bees-config-file.md` rule 12: **no live reload; changes apply at restart.** The plan keeps that: a boot reader makes
  "change the whitelist, restart the node" possible **without a rebuild**, which is the whole gain. Operator reset of quarantine
  (D10, "operator reset only") stays a restart for now. A later design may persist suspicion and quarantine in a `(:store)`
  carrier (Route A's proper use: a log of `{fingerprint, state}` records read at boot, replayed, trimmed); that is a TRUST feature,
  not part of this plan.
* **Boards (no file system, section 1 of the config doc).** The stand-in "the same reader over a generated module `bees_conf_embedded`" stays
  for NUCLEO-L476RG and ESP32-S3 until a target provides `(:flash_region)`; then the packed text sits in a flash region and is
  read through the store carrier with the same `decode` gate. Boards use Mbed TLS (D40) and a different tls edge; not part of N0b.

### 3.9 The Python reader afterwards

`tools/bees_conf.py` **stays**. It becomes (1) the build-time extractor of build facts (3.5) and generator input for everything class c;
(2) the test oracle (`test_bees_conf.py`, a new `dump` command); (3) an optional validator the operator runs before deploying
(`bees_conf.py check FILE`, same text as boot). The generators `bees_config_trust.py` and `bees_config_beam.py` shrink to emitting build
facts, atoms, the pools and the permission-gate *function shape*; the run-time constants (a) and the data (b) leave them. **Decision
D-2 (Q4): is a bad `bees.config` at build still a build failure** (BEAM mode today) **or only a warning, since the file may be fixed
after the build?** Recommendation: fail the build only for class-c violations (a value the build cannot implement), warn for the rest,
because a boot reader exists for them.

## 4. Phases, exit criteria, trials, goldens

Nothing below is run now. User rule (memory): spikes are documentation; no builds, fetches or toolchain installs without an explicit ask.
Each phase therefore starts with "ask to build". Sizes are estimates in working days of one agent, with the checks that cost
(compiling BEES units is slow, SD-29/SD-36).

| # | Phase | Exit criterion (testable) | New or changed trials | Size |
| --- | --- | --- | --- | --- |
| 0 | **Spikes that decide the route** (3 probes, one hour each once approved): (a) `decode((:etf), frame, limits)` into `string` of an edge-produced ETF binary passes the taint checker and the result can be parsed by hand and sent to an actor; (b) `read_lines` output: same question, plus failure behaviour (missing, directory, 1 MiB file); (c) store carrier: pack a 64 KiB text, read it back, parse | one written verdict per probe; D-1 confirmed or reversed | `trials/n0b_probe_etf_string`, `_read_lines`, `_store_text` (new, not goldens of existing trials) | 2 |
| 1 | **The native edge** `silica_bees_conf.c` + face + worker; Silica reads a file into a pure string at boot | trial prints byte length and the first line for: a good file, missing, unreadable (mode 000), directory, a symlink, over 64 KiB, non-ASCII, a key file with mode 0644; each message equals the Python reader's text | `trials/n0b_read` (new) | 3 |
| 2 | **The parser and the validator** `src/shim/bees_conf.silica`; `bees_conf.py dump` | the Silica `dump` equals the Python `dump` byte for byte over **all** vectors of `test_bees_conf.py` (extracted to `trials/n0b_conf/cases/*.config`, one file each: both modes, defaults, every rejecting case, worked example of section 6 of the document) and over the defaults table; error lines identical | `trials/n0b_conf` (new) | 8 to 10 (the port of ~700 lines of Python rules; the checker's cost on large `case` tables is the risk) |
| 3 | **Run-time scalars (class a)**: `beam_conf` and `bees_trust_conf` scalars come from the boot actor; address composition; `creation`, timeouts, TLS specs, cookie path | with a file edited and **no rebuild**, `n2_dist`, `n3_trust`, `n1_limits` scenarios run with the new values; the existing goldens do not change (3.7) | existing trials unchanged; one new `trials/n0b_norebuild` (edit the file between two runs of one binary) | 5 |
| 4 | **The data (class b)**: data-driven permission gate, whitelist and pins read at boot into the K and M name pools, fingerprints by `bees_conf_sha512_der`, per-link host/port/role from a boot record indexed by the build's peer index | an unmodified binary refuses a changed whitelist's removed entry and accepts an added one (within K); a whitelist larger than K is refused with the message of 3.5; `n3_trust` and `n4_trust_tls` scenarios still pass | `trials/n0b_whitelist` (new); `n3_trust`, `n4_trust_tls` rerun | 8 (the gate, SD-35 measurement, K/M) |
| 5 | **Retire the stand-in's run-time role**; the cookie mode check moves to boot; the build keeps the extractor and (per D-2) the gate | a grep finds no run-time constant in `bees_trust_conf`/`beam_conf` that the file can set; `make kit` clean; `bees-config-file.md` section 11 rewritten ("built") | n2_dist `loose_cookie` goldens change (below) | 2 |
| 6 | **Boards**: unchanged; note the `:flash_region` route (a spike when a target provides it) | n/a | none | 0 |

**Goldens.** The boot banner and summary lines (`[bees] mode=beam ...`, `[bees] BEAM mode: ...`, `[trust] mode trust, ...`, `[trust] <note>`)
must be **identical**: they are the first lines of `n1_addr/*`, `n2_dist/*`, `n3_trust/*`, `n4_trust_tls/*` outputs. Goldens that **would
change**:

* `n2_dist/loose_cookie.*`: today the loose-mode cookie is refused at the first handshake (`bees_beam_load_cookie` tag 2); with the check at
  boot, the node never starts and prints `[bees] boot refused: ...` instead. (I read `loose_cookie.a.sout`'s head, which shows the banner, then an audit
  block; the post-change text is a new golden.)
* Any BEAM-mode trial whose config is refused **at build** today (the `bees_peers`/`beam_conf` generation stops with exit 1): its
  assertion becomes a boot refusal if D-2 makes the build warn. Which trials do this: *(unverified: needs a grep of trial Makefiles for
  expected build failures, which I did not complete; `n1_addr` mentions "refused by the reader" for the loopback rule)*.
* `n3_trust/boot_missing`, `boot_unreadable`: text unchanged by design (3.7); they stay a regression gate, now exercising the real
  file system instead of the compiled-in verdict.
* Trials that print a rebuilt config (none found) would also change.

**Risks.** (1) Phase 2's size and the checker's cost on big units (SD-29, SD-36); mitigation: flat entries, table functions split across
units, the parser pure. (2) SD-35 on the gate. (3) Taint: if (a) of phase 0 fails, no Silica parser can run on file text at all and the
fallback is a C parser (rejected by the user earlier for the FFI rule? *(unverified)*) or the Python packer feeding typed ETF (Route A
with a typed record decoded directly, no Silica parser). (4) Exit-status-of-1 from a non-main boot actor. (5) `int_to_string` absent. (6)
Atom-pool sizing (K, M) is a new build-time option the operator must know.

## 5. Dependencies on other agents' in-flight work, and sequencing

Concurrent edits I could see in the working tree (`git status`; read-only): `tools/bees_conf.py` (+42 lines), `tools/bees_config.py`,
`tools/bees_config_beam.py`, `tools/bees_dist_gen.py` (+73), `tools/test_bees_conf.py`, `src/inter_nodal/dangerous_beam_net.silica` and
`dangerous_bees_net.silica` (about 500 changed lines, multi-link and reconnect), `tools/trial.mk` and `run_trial.py` (harness flakes),
several `.wait_for_exit` goldens.

* **The multi-link model `eff['links']`** (one entry per manifest peer: name, dials, by_epmd, host, port, resolve, address) is the
  structure phase 4 turns into a boot record. **Do not start phase 3/4 before it settles**; phases 0 to 2 do not depend on it (they port
  the reader's rules, whose multi-link part is the last to be added: port it after the other agent's merge).
* **Reconnect options** (`redial`, `redial_initial_ms`, `redial_max_ms`): the reader's table currently marks them build-time; this plan
  reclassifies them as class a (2.1). **Coordinate**: ask that agent to leave them as plain scalars of `beam_conf` so they can move.
* **D43/D44** (`classical_allowed_certs`, optional `cacertfile`): data of whitelist entries (class b); the whitelist data-driven gate must
  carry the classical flag per entry (phase 4). `cacertfile` optional means the TLS spec string has an empty third field: keep the NUL-terminated
  triple exactly.
* **M3 manifest path** (a node built from `.wire` alone, no `bees.config`, auth none): nothing to read at boot; it stays entirely build-time
  and must keep working (`bees_conf.manifest_only`).
* **Harness work** (`trial.mk`, `run_trial.py`): new trials (`n0b_*`) should be added after that lands, and use the same trial Makefile
  macros; no edit of those files by this plan.
* **Sequence:** phase 0 (spikes) any time, in a scratch directory; phase 1 and 2 on new files only (`native/src/silica_bees_conf.c`,
  `src/shim/bees_conf.silica`, `src/shim/dangerous_bees_conf*.silica`, `trials/n0b_*`, plus **one added command `dump` in
  `tools/bees_conf.py` after the other agent's edits are committed**); phase 3 and 4 after multi-link/reconnect merge; phase 5 last.
  Files outside the new set that these phases must touch: `tools/bees_config_beam.py`, `tools/bees_config_trust.py`,
  `tools/bees_dist_gen.py`, `src/shim/*_node*.part`, `src/trust/dangerous_bees_trust.silica` (the gate), `src/inter_nodal/dangerous_beam_net.silica`
  (the `beam_conf@...` reads): all currently being edited or adjacent to edits.

## 6. Questions for the user

* **Q1.** By "silica can now read files using transport", do you mean the **storage carrier** (`(:store) (:backing, "x.sildat", ...)`, a record log)? It
  cannot open a hand-written text file; it needs a packer and a literal path. If yes, is a packer step acceptable, or do you want BEES's
  text file read some other way?
* **Q2.** Approve the recommended route (3.1): BEES's own native edge returns the file as an ETF binary, Silica de-taints it with `decode`
  and parses; the store carrier is kept for boards and persisted state. Or choose `read_lines` (after Silica answers SR-A to SR-C), or the store route?
* **Q3.** Is it acceptable to ask Silica for SR-A, SR-B, SR-D, SR-G (typed file errors, stat, run-time decode limits, int/string conversion)?
* **Q4.** Is a bad `bees.config` still a **build failure** in BEAM mode, or only a warning now that boot validates it (D-2)?
* **Q5.** Keep `plaintext_test_only` a build-time fact (recommended), or compile both TLS link parts and decide at boot?
* **Q6.** A whitelist spec that names a function the MFA table does not have: silent (SEMP) or a boot note/warning?
* **Q7.** The new build-time options `trust.whitelist_slots_max` and `trust.pinned_servers_max` (3.5): acceptable names and defaults?
* **Q8.** May I build and run the three phase-0 probes when this plan is approved (your rule is "no compiles unless asked")?

## 7. What I could not verify

That BEES's pinned compiler has the storage carriers; that `read_lines` is untainted; that `decode` into `string` of an ETF binary passes
the taint check on the pin; that Linux and the boards behave as the sources say; which existing trials expect a build-time refusal; that
SHA-512 is unavailable in Silica; how `beam.spawn`/`spawn_allowlist` are consumed; the cost of the data-driven gate under SD-35. Nothing
was compiled or run.
