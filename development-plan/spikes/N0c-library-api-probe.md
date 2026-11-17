# N0c: BEES as a source-only library (probe and plan, 2026-11-18)

**Status: PROBE AND PLAN. No repository file other than this document was created or changed.** The probes were compiled and run
with the pinned compiler (`silica-999909-macos-applesilicon`) in a scratch directory outside the repository
(`/private/tmp/claude-1331430978/-Users-yenrab-project-bees/2e742689-9b61-46cc-b8c9-af30f64162f8/scratchpad/api_probe/`: `p1a`, `n1`, `n2`, `p2`,
`p3`, `p4`, `p5`, and the build script `build.sh`; they are not kept in the tree). One compile at a time, `nice -n 10`, no network (one
probe resolved `localhost`, one dialled a closed loopback port), nothing installed, nothing committed, `/Users/yenrab/silica` only read.
What I read but did not run is marked *(read)*; what no probe could settle is marked *(open)*.

The rulings this plan serves (user, 2026-11-18):

1. BEES is a **library**. The application reads its configuration, whitelist, pins, cookie and certificates (disk or flash) itself,
   as a documented **example**, and calls BEES with the values.
2. The library accepts PEM certificate and key **bytes** as well as paths; `bees.config` stays the file format the examples read, through
   a small optional parser helper; validation returns `(:ok, cfg) | (:error, reason)` instead of aborting.
3. The library is **source only**: "This library is not a pre-compiled library." The app's own build compiles BEES's Silica
   sources with the app's units (linked through `lib/` as the trial leaves do) and compiles the native C itself; BEES ships no binary.

## Rulings (user, 2026-11-18)

The user accepted all eleven suggestions of section 9 and defined the compilation model. Text elsewhere in this document that assumed
otherwise is marked **Superseded** or rewritten; what the probes proved is kept.

**One compilation unit (the user's definition, verbatim):** "A single compilation unit is all the source files and one execution of the
silica compiler against all those files. That means they are all listed in the silica.config file in the application's directory.
Copying and duplication of the files is not needed since paths can be listed in silica.config or links in the directory." (This matches
`/Users/yenrab/silica/compiler/design_documents/APPLICATION_IS_ONE_COMPILATION_UNIT.md`.) So BEES's units are **listed by path in the
app's `silica.config`** (or linked into its directory); nothing is copied, no unit is compiled by itself, nothing is pre-compiled.

| # | Decision | Ruling |
| --- | --- | --- |
| 1 | API shape | **Accepted.** One source unit, one compile; BEES's node actors are started by reference and driven by messages (the only shape the rules allow without pasting) |
| 2 | Message tags | **Accepted: no integer opcodes; atoms, shared.** Messages carry atoms (`(:start, ...)`, `(:started, ...)`). Because of the atoms finding (section 10) BEES's atom list must be **registered by an expression literal in an earlier-listed unit** until Silica fixes it |
| 3 | First example's configuration source | **Accepted, and changed:** the example reads its config through Silica's **local storage transport**, **not `read_lines`**. A small Python **packer** validates `bees.config` at deploy time (with `tools/bees_conf.py` as the oracle) and writes a storage record whose value is an **ETF-encoded config term**; the app reads the record through the storage carrier and `decode((:etf), ...)`s it into a typed record. **No Silica text parser. `decode` de-taints.** |
| 4 | Validation messages | **Accepted:** byte for byte `bees.config:LINE: PATH: MESSAGE`. The file-mode and "does not exist" wording lives in the packer and the examples |
| 5 | Secrets | **Accepted:** BEES guarantees **no retention and no logging**. **Ruled 2026-11-18 (user): when Silica releases memory it will zero it (planned, not today), so scrubbing is not a request.** Until then the guarantee stays as stated; when it lands, BEES documents that secrets are cleared on release and tests it |
| 6 | Fingerprints | **Accepted:** the whitelist carries **hex fingerprints computed by the packer** (no SHA-512 in Silica) |
| 7 | Link kinds | **Accepted:** plain and TLS links are **two source fragments the app chooses** in `silica.config`, not a run-time flag |
| 8 | Pool sizes | **Accepted:** stated by the **app at build time** (`bees_build`) |
| 9 | Silica requests | **To draft:** run-time decode limits, a stated taint status of the storage carrier. **Struck 2026-11-18 (user): `int_to_string`/`string_to_int` and a way to name a record shape (hard no), and zeroisation (Silica will zero on release).** **`read_lines` is NOT to be used, so its requests (runtime shim in the link line, taint status) are dropped.** One new defect is drafted in section 10 (tuple-tag atoms) |
| 10 | "N2T" | **BEAM-mode TLS** (an `inet_tls_dist`-compatible profile), **after the Linux port** |
| 11 | Sequencing | **Accepted as proposed:** L1 and L2 start after the multi-link/reconnect/`make integrate` work has landed and is committed |

Consequences applied below: (a) the compile-time facts (atoms, `bees_build`, the generated per-peer and MFA units) are **source files the app lists in its `silica.config`**, produced by BEES's Python tool or written from BEES's templates; (b) the
`.part` pasting question is a source-composition question, answered in 1.3 (no pasting needed); (c) versioning is by source revision, no ABI; (d) the config packer is a deploy-time Python tool, so BEES needs **no Silica text parser** and no `read_lines`; (e) native C is chosen per platform by the app's build.

## 0. Findings in one page

1. **The `.part` pasting is not forced by E4026/E4042, but the shape of the API is.** Three rules decide it, all proven by probes:
   a unit that holds `dangerous_actor_ref` or calls `spawn_dangerous` must be named `dangerous_*` (E4026, probe `n2`); every unit that
   `use`s a `dangerous_*` unit must itself be `dangerous_*` (E4021, probe `p1a`), so the app's root is `dangerous_<app>`; and the app
   (or any unit) may not **call** any function of a `dangerous_*` unit outside an FFI worker (E4042, probe `n1`: even a function that does
   `x + 1`). What a root **can** do is *spawn a `dangerous_*` unit's behaviour by reference and cast to it*. A behaviour of a
   `dangerous_*` library unit can itself call `spawn_dangerous` (carrier: probe `p1a`; BEES's own native-edge FFI worker
   `dangerous_bees_dns@resolver` (retired 2026-11-17, folded into `dangerous_bees_resolve@rslv`; the probe stands) with its C: probe `p4`) and cast to what it spawned. So BEES's start-up code can live in the library as
   **node actors** that the app starts by reference and talks to by message. Today's root-unit functions (`net_launch`, `trust_start`,
   `trpc_call`, `trust_reset`) become messages; their return values become reply messages.
2. **A typed config record travels** as a function parameter, a function result, and an actor message value, including a list of 1000
   records with 128-hex-character fingerprints and a spec each (probe `p2`; a wide, nested record: probe `p3`). Holding that list in an
   actor's **state** costs about 100 times the CPU per dispatch (SD-35, measured: 2.9 s against 0.03 s for 30000 messages), so the
   list is consumed at the message, not kept in state.
3. **No pre-compiled anything is needed, and the compile-time facts become source the app owns.** The genuinely build-time items are
   the atom table (D30; re-proved and narrowed in section 10: a tuple-tag atom that a receiving unit uses only in a type and a pattern is not registered, so a receiver listed before its sender mismatches at run time), the module table, the per-peer/per-link code of BEAM mode, the decode limits (E2402 proven by probe `p5`: a non-literal limits record is a
   compile error), and the pool sizes of registered names. Everything else in `bees.config` can be a run-time value (section 3).
4. **Bytes instead of paths is a small C change** in both engines (OpenSSL memory BIOs, Mbed TLS buffer parsers; the cookie as a value), inside the existing FFI shapes (section 4). Nothing was built; the cost is a plan, not a measurement.
5. **A side fact (kept, no longer used): `read_lines` links only with the runtime shim.** A program that uses the intrinsic `read_lines`
   compiles (no taint complaint, from a plain unit, `proc[device_io]`) but does not link under BEES's `trial.mk` link line:
   `Undefined symbols: _silica_read_file_path`; linking `compiler/src/silica_rt_shim.s` fixed it (probe `p3`). The user ruled that `read_lines` is **not used**, so this is not a BEES issue and the matching Silica request is dropped.
6. The old SD-17 row ("FFI workers cannot live in a library unit") is **stale for this layout**: `dangerous_bees_dns@resolver` (retired 2026-11-17, folded into `dangerous_bees_resolve@rslv`; the probe stands)
   (a worker in a library unit, with `external_danger`) was spawned by `spawn_dangerous` from a *different* library unit's behaviour
   and ran (probe `p4`). SD-17 survives only as: the worker's behaviour and its `spawn_dangerous` call must both be in `dangerous_*` units.

## 1. Q1: what a library unit may start and call

### 1.1 The rules (compiler source *(read)*, each confirmed by a probe)

| Rule | Source | Probe |
| --- | --- | --- |
| E4026: `spawn_dangerous`, `spawn_dangerous_registered` and the type `dangerous_actor_ref` (parameter, result, annotation, expression) may appear only in a module named `dangerous_*` | `src/module_checker/module_checker_ffi.silica:237-310` | `n2`: `fn f(c: dangerous_actor_ref) -> int64` in `plainx` gives E4026 |
| E4021: a module that imports or uses a `dangerous_*` module must be named `dangerous_*` (and the file name is the module name) | error_codes.md:184 | `p1a`: a plain `plib` that `use`d `dangerous_dlib` gave E4021; `main.silica` with `module main` too, so the root is `dangerous_<app>.silica` |
| E4042: a call qualified with a `dangerous_*` module (and an unqualified call of a unit's own function that reaches foreign work, in a `dangerous_` unit) is allowed only in the `external_danger` sequence of an FFI worker | `src/ffi/ffi_placement_checker.silica:343-372, 508-520` | `n1`: `dangerous_dlib@info(1)` from the root: E4042, though `info` does no foreign work |
| E4041: `external_danger` sequences only directly in the cast-only behaviour installed by `spawn_dangerous` | ffi_placement_checker.silica:478-496 | (BEES trials `m2_ffi_shapes`) |
| Spawning a `dangerous_*` unit's behaviour **by reference** with plain `spawn` is allowed from any `dangerous_*` unit, including the root | silica-defects.md "Rename (E4026, E4042)" row | `p1a`, `p2`, `p4` |

### 1.2 What a library unit may do, by kind

| Unit kind | May | May not | Evidence |
| --- | --- | --- | --- |
| **plain** unit (no `dangerous_*` use) | define pure functions, records, lists; `spawn`/`spawn_registered` plain actors; start a **supervisor** (`impl X for Supervisor;` inside the unit, `spawn_registered_supervisor`); `read_lines`; `cast`, `send_after`; be **called from a `dangerous_*` root** | mention `dangerous_actor_ref`; call `spawn_dangerous`; `use` any `dangerous_*` unit; spawn a `dangerous_*` unit's behaviour (it cannot name it without `use`) | `p2` (`cfglib`: validate, builders, called from the root), `p3` (`biglib`: `spawn_plain`, `start_sup()` printed "plain-unit supervisor started", `read_conf`) |
| **`dangerous_*`** unit | define behaviours; inside a behaviour call `spawn_dangerous` (carrier, FFI workers), hold `dangerous_actor_ref` in state, cast to carriers; `spawn` other behaviours | be **called** by anything but an FFI worker (E4042): no exported "start" function for the app to call | `p1a`: behaviour `launcher` spawned the carrier and received `(:link_down, ...)`; `p4`: behaviour `boot` spawned the resolver worker (C `getaddrinfo` through the native archive) and printed `resolved localhost: 127.0.0.1` |
| the app's **root** (`dangerous_<app>`, has `main`) | everything above; spawn BEES's node actors by reference; cast config to them | call any BEES `dangerous_*` function | `p1a`, `p2` |

Exports: a unit's functions are local labels unless `export name/arity;` is declared; a behaviour spawned from another unit must be
exported (probe `p1a`, link error until `export launcher/2;`).

### 1.3 Why the `.part` files are pasted today, and what must stay in the root

The `.part` files are pasted because the **start-up is written as functions the root calls** (`net_launch(c, io_ms, tick_ms)`,
`trust_start()`, `trpc_call(...)`, `carrier_new()`), and every one of them touches `dangerous_actor_ref` (E4026 forces a `dangerous_*`
unit) and `spawn_dangerous` (the carrier, `ttls`, `trnd`); a function in a `dangerous_*` library unit cannot then be called by the
root (E4042). Pasting the text into the root unit is the one place where both rules hold. Nothing in E4026/E4042/E4021 forces
pasting if the same code runs *inside a behaviour*. Per file:

| `.part` function group | Needs `dangerous_*`? | Can move into a library unit? | How |
| --- | --- | --- | --- |
| `bees_tcp_edge.part`: `carrier_new` | yes (`spawn_dangerous`, return type) | yes, as a **local function of the library's `dangerous_` unit**, called from a node-actor behaviour (probe `p1a` did exactly this) | |
| `bees_node_edge.part`: `net_launch`, `net_listen_and_dial`, `net_dials`, `net_dial_link`, `net_listen`, the redial actor `nrd` (`dangerous_actor_ref` in its state) | yes | yes, into `dangerous_bees_net` (or a sibling unit) as a behaviour `node` | the root's `me: actor_ref <- self()` becomes the node actor itself; the returned `{conn, tx}` pair becomes a reply message |
| `beam_node_edge.part` (218 lines: the same for BEAM mode: EPMD actor, cookie worker, proxies) | yes | yes, same | |
| `bees_resolve_edge.part`: `net_resolve`, `rdial` | yes (spawns `dangerous_bees_resolve@rslv`, holds `dangerous_actor_ref`) | yes (`p4` shows the shape) | |
| `bees_trust_link_tls.part` / `_plain.part`: `trust_link`, `trust_listen_link` | yes | yes; but the **choice** of plain vs TLS link is a source choice (section 3, `plaintext_test_only`) | two behaviours or one unit per link kind chosen by what the app puts in `silica.config` |
| `bees_trust_node.part`: `trust_start`, `trust_listen`, `trpc_open`, `trust_raw_*` | yes (carrier, edge worker) | yes | |
| `bees_trust_node.part`: `trust_say`, `trust_notes`, `trust_boot` (banner), `trust_ipv4_char`, `trust_ipv4_at`, `trust_reply`, `trpc_request` before it opens a link | **no** | yes, into a **plain** unit (`trust_boot`'s banner becomes a returned string list, section 5) | callable from the app root (probe `p2`/`p3` shape) |
| `bees_trust_node.part`: `trust_start_peers`, `trust_start_caches` (spawn registered actors of `dangerous_bees_trust` by reference, state holds `dangerous_actor_ref`) | yes (state type) | yes, inside the node behaviour | |

**What must stay in the app's root unit after the move: only** (a) the failure-reporter registration (`bees_reporter@start()`, E2236: any
spawn before it is a compile error, probe `p1a`'s first attempt), (b) `spawn(0, dangerous_bees_node@node, ...)` by reference, and
(c) the application's own logic. Nothing of BEES's logic has to be pasted; a hand-written root of about ten lines replaces
`tools/bees_edge_gen.py`'s output. The generators remain useful only for what is genuinely generated (section 3.2).

Two shape consequences the probes exposed:

* **The initial state of a spawned behaviour is spelled by the spawner** (SD-31 rule: write the literal). A node behaviour whose state is
  `int64` (spawn with `0`) keeps that out of the app; I did not probe a record state spelled across units but the existing `.part` code
  spells whole state records in the root (`net_dial_link`), which is the coupling to avoid. *(Recommendation, not probed with a library
  node: scalar initial state `0`; the node keeps its real state after its first message.)*
* **Atoms in the API messages need the shared atom table to be filled before the receiver is compiled** (probe `p1a`: the same program fails with "no case arm matched" until a `probe_atoms` unit,
  listed before the receiver and holding the atoms as expression literals, exists; section 10 narrows the condition). **Ruled (2026-11-18): no integer opcodes; atoms, shared**, so the app's `silica.config` lists BEES's atom unit first.

## 2. Q2: config records as parameters and as message values

### 2.1 What was proven (probes `p2`, `p3`; compiler 999909; Apple Silicon)

| Test | Result |
| --- | --- |
| A 7-field record `{ name, port, tls, tick_ms, cookie, pem, wl: List[{ fp, spec }] }` built in a plain unit, **passed as a parameter** to `cfglib@validate`, returned inside `(:ok, cfg) | (:error, string)`, and **cast as the payload of `(:start, cfg)`** to a behaviour of a `dangerous_*` unit | compiles and runs |
| The whitelist: **1000 entries**, each `fp` a 128-hex-character string and `spec: "any"`, plus a 4.6 KB PEM-like string | validated, cast, received, counted (1000 valid entries) in both holders |
| A wide record (14 fields, nested `{ a, b: { c, d } }`), a list of strings, a 64 KiB string, 1000 and **10000** list elements | passed through a message to a plain actor; 10000 strings (about 1.3 MB) and a 256 KiB string also pass (RSS 39 MB for 3000 strings of 128 bytes plus 256 KiB) |
| **SD-35 at this size** | holder with the 1000-entry list **in its state**: 30000 pings = **2.91 s user**, max RSS 8.6 MB. Holder that keeps only the count: **0.03 s**, 7.7 MB. About 100 times the CPU, no leak. So: **consume the whitelist at the start message (spawn the per-entry actors, or hand it on), never hold it in an actor's state** |
| Eight-argument limit (E1070) | not a constraint for a record **parameter**: one record is one argument. It bites only for a function that spreads config into scalar parameters, and for builders (`mk` with more than 8 fields; keep builders to groups of at most 8, and write a record literal in groups) |
| SD-37 (derived decoder, 4 fields) | irrelevant to in-memory passing; it matters only if a config record is ever `decode`d from ETF (the optional ETF route below) |
| No type aliases (spec 1.3.8, 3.4.2) | every signature spells the record shape; a 7-field record with a nested list is one long line (probe sources). **Design consequence: split the config into groups of at most 4 to 5 fields** (`net`, `tls`, `limits`, `trust_tuning`) and pass the groups as separate tuple elements or small records |

Not settled: a single **1 MiB** string in a record. The probe faulted (`[silica] fault ... biglib_int_text`), but its builder is
quadratic (it concatenated 1024-byte pieces 1024 times and committed 270 MB), so the fault says nothing about messages. *(open)* PEM
chains are a few KiB, so it does not matter to this plan; a 64 KiB `bees.config` file (the doc's cap) is covered by the 256 KiB pass.

### 2.2 Taint: what the app's config bytes are (rewritten for the rulings)

* **Superseded:** the first draft said the app reads files with `read_lines` and needs no `decode`. Probe `p3` did show that `read_lines` output passes the FFI-taint pass and links only with the runtime shim (`silica_rt_shim.s`), but the user ruled that **`read_lines` is not used** (it has no error cause, no size cap and no mode check, and its taint status is not stated). That evidence is kept as a fact, not as the plan.
* **The plan:** the config arrives from the **storage carrier**, a foreign call. Bytes that arrive from a foreign call (the carrier's `(:rx, record)` cast, any BEES native-edge worker) are tainted and are
  de-tainted only by `decode((:etf), ...)` inside `sequence ... produces pure` with literal limits (the resolver edge does this today:
  `rs_text` in `bees_resolve_edge.part`, proven in trial `n1_addr`). **Yes: the app's file bytes need `decode((:etf), ...)` to become pure before they are passed to BEES.** The packer therefore writes an **ETF** term, so that `decode` produces the typed record directly; no byte of
  config is parsed by hand, which would not de-taint it (a hand rebuild is rejected, E2100, spike S8).
* The checker seeds taint only on calls **qualified with a `dangerous_*` module inside a worker's `external_danger` sequence**, and does not check the handler that receives the cast (SD-24, SD-25, memory note `silica-ffi-taint-copy-rule`): the compiler would accept an un-`decode`d forward, the specification forbids it, and BEES must not rely on the gap.
* The file-system checks (0600 mode, regular file, "does not exist", "not readable (permissions)", "readable by group or others") are done by the **packer** (Python), with the existing wording; the library checks no file.
* The app's bytes that **go into** an FFI call (the PEM or cookie string handed to C) are ordinary strings: no taint rule restricts
  arguments. SD-40 applies: bind a string to a variable before the foreign call (a string argument written as a call expression reaches C with the wrong pointer, silica-defects row SD-40).

### 2.3 Other inline-call defects

SD-44 (a tagged-tuple-returning call inline beside another argument) and SD-45 (a string-returning call inline in a cast tuple) and
SD-31 (record-returning call inline as a cast message) all say the same: **bind a computed value to a name before casting or passing it**.
The probe programs did (`c2: Cfg <- ...; cast(a, (:start, c2) ...)`) and worked. The API's examples must show that style; the library's own
code already does (`bees_resolve_edge.part`: "the address is bound before the cast").

## 3. Q3: build-time against run-time, for every value of `bees.config`

Classes: **(a)** a run-time parameter, passed in a record; **(c)** a compile-time fact in source that the app's build supplies;
**(b)** is a run-time value that needs a code-structure change in BEES (data-driven instead of generated functions), listed as (a-b).
Where the old N0b table said "c: build-time generated" the new question (source-only library) is: *which unit does the app provide?*

### 3.1 The table

| Value (bees.config today) | Class | What the app supplies / what the library does at run time |
| --- | --- | --- |
| `mode` (`beam` / `trust`) | **c, by source** | which node unit the app starts: `dangerous_bees_beam_node` or `dangerous_bees_trust_node` (the app lists the units it uses in `silica.config`; the unit is not even compiled if unused). Two modes in one binary is allowed by the rules and is the app's choice |
| `node.name` | **c** | an atom of the build (D16, D30): in the app's `bees_atoms`. At run time the config record carries the same name as a **string** and the library refuses a mismatch with `bees_atoms@from_spelling` (`(:error, ...)`, not an abort) |
| `node.creation` | a | `net.creation` |
| `beam.transport`, `beam.auth`, `epmd` (`external`/`none`), `spawn`, `spawn_allowlist` | a | small integer or atom-union in `net`; atoms of the closed sets are BEES's (in its `.atoms`); `spawn_allowlist` consumer not found by grep (N0b) *(open)* |
| `beam.cookie_file` | **a, changed meaning** | becomes `beam.cookie`: the cookie **value**; the path and the 0600 check are the example's (section 4) |
| `listen_address`, `listen_port`, `epmd`, `epmd_port`, per-link host/port/role | a | in `net` and a `links` list (one record per manifest peer, **indexed by the build's peer order**: the peer *names* and count are **c**). The address strings (`listen:any:PORT`, `host:port:ms`) are composed by the Python generator today (`listen_form`, `dial_check`, loopback rule); that logic moves to the plain `bees_cfg` unit (about 150 lines of Silica) |
| `net_ticktime_s`, `open_timeout_ms`, `redial`, `redial_initial_ms`, `redial_max_ms` | a | scalars in `net`/`redial`; today generated constants of `beam_conf`/`bees_peers` (class a per N0b 2.1) |
| `peers` (names, count, remote/local registered names, message types of `.wire`) | **c** | the app's manifest: `.wire` / `.atoms` / `.module` / `.pools` files, from which the app's build (a Python source tool BEES ships, run by the app's Makefile) writes the units `bees_atoms`, `bees_peers` (per-peer proxy code), `bees_msgs`, `bees_modules`, `bees_ids`. **Cannot be a run-time value**: a typed codec and a proxy actor per peer are code, and the atoms are the program's |
| `frame_size_max`, `args_len_max`, `term_depth_max` | **c for the decode literal; a for the `unframe` cap** | `decode((:etf), f, {max_bytes: N, ...})` requires a **record literal of literals** (E2402; probe `p5`: a limits record returned by a function is rejected). So the **built** limit is source: a one-line unit `bees_build` (see 3.2) holds `frame_max_built`. `wireframe@unframe(state, segment, max_frame)` takes the cap as a run-time argument (read: `stdlib/wireframe.silica`), so the **effective** cap is a run-time parameter bounded above by the built one; the library returns `(:error, "frame_size_max: 8000000, the program was built for 4194304 (rebuild with a larger bees_build.frame_max)")`. Same rule as N0b rule 9. **Making the decode limits run-time needs a change in Silica (N0b SR-D); no way today** |
| `trust.port`, `listen_address`, `listen_prefix`, `acceptors`, `session_slots_max`, `session.*`, timeouts, `token_*`, `suspicion_limit`, `dns_*`, `call_timeout_ms` | a | `trust` groups; pure scalars |
| `trust.tls_opts` / `client_tls_opts` (cert, key, ca) | **a, changed meaning** | PEM **bytes** (or paths, section 4) |
| `trust.whitelist` (fingerprint, spec, classical flag) | **a-b** and the name pool is **c** | a list of `{ fp, spec, classical }` in the start message. Today each entry is a generated function `perm_i` and one registered actor `bees_trust_peer_<i>`; the gate becomes data driven (a decoded/held spec), and the registered names `bees_trust_peer_0..K-1` are atoms of the build: **K is a build number the app states** (`bees_build.whitelist_slots_max`). A whitelist longer than K is `(:error, ...)` at start |
| `trust.server_pins` | **a-b**, pool **c** | same, pool M (`pinned_servers_max`) |
| `plaintext_test_only` | **c** | selects `trust_link_plain` vs `trust_link_tls` (the app puts one of the two link units in `silica.config`); a test-only mode must not be compiled into a production app by accident, so make it two units, not a boolean |
| the module/function table of `.trust` (MFA table `bees_trust_mfa`) | **c** | generated unit from the app's `.trust` manifest: "a function that was not compiled in does not exist" |
| atoms of every kind (D30; A1.2, A6.3) | **c** | `bees_atoms` unit generated by `tools/bees_config.py generate` from BEES's shipped manifests (`src/**/*.atoms`) plus the app's and the language compiler's; see 3.2 |

### 3.2 What the app's build must do, and what BEES may ship

Source-only means: no `.a`, no `.o`, no generated unit checked in as a binary-compatible interface. BEES ships **source that the app's
build assembles**:

1. **Silica units**, compiled by **one execution of the compiler** against the app's `silica.config` (the user's definition of a compilation unit, "Rulings"): that file lists, by path or through links in the app's directory, BEES's `src/inter_nodal/*`, `src/shim/*.silica`,
   `src/trust/*` that the app uses, and the Silica stdlib units BEES needs (`carrier`, `dangerous_sockets`, `dangerous_tcp_carrier`, `dangerous_store*`/`storelog` for the storage example,
   `wire_etf`, `wireframe`, `Supervisor` if used). Nothing is copied or duplicated; in use-dependency order (`tools/topo_silica_config.sh` today). The pin file's role (a source revision) is the version.
2. **One generated unit set the app owns**, produced by BEES's Python source tool from manifests the app and its compiler write:
   `bees_atoms` (+`.index`), listed **first** (section 10), and, BEAM mode, `bees_peers`/`bees_msgs`/`bees_modules`/`bees_ids`; TRUST, `bees_trust_mfa`. Today's
   `tools/bees_config.py generate -o lib MANIFEST...` does all of it already; the **change is that it no longer reads `bees.config`**.
   (A pure-Silica alternative would put the atoms in a hand-written unit; the 256-arm `case` tiering `bees_config` does makes that impractical by hand for a large program.)
3. **A tiny app-owned unit `bees_build`** (BEES ships a template, `src/api/bees_build.silica.in`) with the build facts the library
   needs as constants: `frame_max_built`, `args_len_max_built`, `term_depth_max_built`, `whitelist_slots_max`, `pinned_servers_max` and the config record's `max_bytes` (5.5).
   The decode limits in BEES's derived decoders must be **record literals of literals** (E2402; a unit's function cannot supply them), so the decode call sites that carry
   these numbers are written into a generated unit by the generator, from the app's `bees_build` numbers. This is the one place where a generated unit is unavoidable. *(read: tools/bees_config_beam.py `gen_conf`, tools/bees_trust_gen.py)*
4. **Native C**, compiled by the app's build: `native/Makefile` pieces per platform (macOS: CommonCrypto, OpenSSL; Linux; ESP32-S3 and NUCLEO with
   Mbed TLS, D40; the user's platform directories native/macos, linux, esp32s3, nucleo are chosen by the app's build); the `silica.link` archive paths in the app's tree.
5. **(Dropped)** the runtime-shim object for `read_lines`: `read_lines` is not used (ruling 3).

BEES may ship: the Python source tool, the templates, a Makefile fragment (the app's `include`: today's `tools/silica.mk`, `trial.mk`
become `bees.mk`), and a **checker** (`bees_config.py check`) that the app's build runs. All of it is source; none is a binary.
**Versioning is by source revision** (a git revision or tag of BEES, and the compiler pin); there is no ABI. The contract is the
message set of the node actors (section 5) and the record groups, versioned by `api_version` in the start message (an integer the library checks, so a mismatched checkout fails at start with `(:error, "api_version 3, the library implements 2")`).

## 4. Q4: TLS material and the cookie as bytes

### 4.1 OpenSSL (hosted: macOS, Linux)

`native/tls/silica_bees_tls.c` *(read)*: `make_ctx(role, cert, key, ca, classical)` calls `SSL_CTX_use_certificate_chain_file`,
`SSL_CTX_use_PrivateKey_file` and `SSL_CTX_load_verify_file` on paths and caches **one context per role** (built at the first
`bees_tls_open`; the spec string is three NUL-terminated paths plus an optional `"1"`, lines 202-222). To take bytes:

| Step | OpenSSL call (memory BIO) | Note |
| --- | --- | --- |
| certificate chain | `BIO_new_mem_buf(pem, len)`, `PEM_read_bio_X509` in a loop; `SSL_CTX_use_certificate` for the first, `SSL_CTX_add_extra_chain_cert` (takes ownership) for the rest | no `_chain_file` equivalent takes a buffer; this is the standard replacement |
| private key | `PEM_read_bio_PrivateKey`, `SSL_CTX_use_PrivateKey`, `SSL_CTX_check_private_key` | free the `EVP_PKEY` reference; `OPENSSL_cleanse` the temporary copy |
| CA (optional) | `PEM_read_bio_X509` loop, `X509_STORE_add_cert(SSL_CTX_get_cert_store(c), x)` | replaces `load_verify_file` |
| the fingerprint of a whitelist or pin certificate | `X509_digest(x, EVP_sha512(), md, &n)` from a PEM buffer: a new helper `bees_tls_fingerprint(pem) -> hex` | Silica has no SHA-512 (the crypto proposal is a proposal); today **Python computes it at build**. A library that takes certificates for whitelist entries needs this helper, or the app passes the hex fingerprint itself (recommended default: the whitelist record carries `fp` hex; a **helper** `bees_example_fingerprint` does the PEM-to-hex for examples) |

The wrapper `bees_tls_open(spec_ptr, spec_len)` has two FFI arguments (a pointer and its length, role from `bees_tls_set_args`). A
configure call with a certificate, a key and a CA is **six** FFI arguments (three pointer/length pairs), under the eight-register
limit (E1070). Safer in shape: one new call `bees_tls_configure(role, blob_ptr, blob_len)` whose blob is `cert_len(4) cert key_len(4) key ca_len(4) ca classical(1)`,
**two** arguments, built by a pure Silica function that concatenates the four strings. It is called once per role, from the worker that already makes the first
open, before the first `bees_tls_open`. The existing file-path route can stay as a second entry point (`spec` with a leading `p` tag) so
the compatibility path (section 6) keeps `bees.config` examples working unchanged.

FFI shape limits (read in the N0b/FFI rules and BEES's workers): one tainted cast per worker dispatch (E2101: the worker answers
with one FFI-result cast; a configure call has an integer result, nothing to taint-wrap beyond the existing `recreate` of its tag); string arguments
bound before the call (SD-40); no string longer than a worker message can carry (a few KiB PEM is fine).

### 4.2 Mbed TLS (NUCLEO-L476RG, ESP32-S3; D40)

`mbedtls_x509_crt_parse(&crt, buf, len)` takes a buffer (for PEM, `len` includes the terminating NUL; the blob above carries it), `mbedtls_pk_parse_key(&pk, key, len, NULL, 0, f_rng, ctx)`
the key, `mbedtls_ssl_conf_own_cert`, `mbedtls_ssl_conf_ca_chain`. The boards have no file system, so for them bytes are the **only** route: a configuration embedded in
flash or generated into the app's source is the example there. *(read: Mbed TLS API; not built here, not in the repo yet.)*

### 4.3 The cookie

`native/src/silica_bees_beam.c:37-65` `bees_beam_load_cookie(path)` does the open, the regular-file test, the `(mode & 077)` check, the 255-byte and printable-ASCII
rules, and stores the cookie process-wide under a lock (`bees_cookie`), zeroising its read buffer. **Taking the cookie as a value is a
smaller change than the path:** `bees_beam_set_cookie(ptr, len)` keeps the length and the printable-ASCII rule and drops the file
steps; the existing `bees_beam_digest` already works from the process-wide copy. The **0600 check, the regular-file test and the
error tags 1, 2, 4 belong to the example** (a C helper `bees_example_read_secret_file(path)` returning bytes, or the app's own).
The library's check is on the value only: printable ASCII, 1 to 255 bytes (tag 3).

### 4.4 Holding secrets

* In C: copy once into a process-wide object under a lock (as the cookie), `OPENSSL_cleanse`/`mbedtls_platform_zeroize` temporaries; OpenSSL
  owns the key in the `SSL_CTX` (freed by `SSL_CTX_free`). The existing C already does this for the cookie (`memset(buf, 0, ...)`).
* In Silica: **a string cannot be wiped and a message copy leaves copies**. There is no zeroise facility proven in the language (the crypto proposal says buffers
  "are overwritten by default" but it is a proposal, `design_documents/crypto-proposal-introduction.md:48`) *(open: not tested; I only read it)*. The honest plan:
  the secret passes through Silica **once**, in the start message to the node actor, which hands it straight to the TLS or cookie worker and does not keep it in its state; the record
  that carries it has fields named `*_secret`; no `println` of any record (the banner string never includes them, rule 11 of the config document, unchanged); the doc tells the app to
  drop its own copy at once. Guarantee level: **no logging and no retention in BEES, not memory scrubbing in Silica** until Silica provides it.
* `(:error, reason)` and banners never echo a secret: the key's length and the first error tag only.

## 5. Q5: the proposed API

### 5.1 Shape of the whole

```
app root (dangerous_<app>.silica)         BEES units (listed by path in the app's silica.config; nothing copied)
  main()                                    bees_cfg        PLAIN:  record groups, defaults, validate, banner, text rendering
   reporter start                           bees_cfg_text   PLAIN, optional: parse bees.config text (Silica), or a Python tool
   read files (example units)               dangerous_bees_beam_node   behaviours: node actor, tx, conn, lsn, nrd ... (today's .part code)
   cfg = bees_cfg@...  (pure calls)         dangerous_bees_trust_node  behaviours: node actor, tpeer, tcache, tcli ... (today's .part code)
   v = bees_cfg@validate_beam(cfg)          bees_atoms, bees_peers, bees_msgs ...    generated by the app's build (section 3.2)
   n = spawn(0, ..._node@node, ...)         dangerous_bees_*_native / tls / trust    FFI workers (unchanged)
   cast(n, (1, api_version, groups...))
```

The only functions the app **calls** are plain (`bees_cfg@...`); everything started is **spawned by reference and cast to**.

### 5.2 Config groups (plain unit `bees_cfg`; each record at most 4 fields, nested for more: SD-37 limits the derived decoder to four)

Silica has no aliases, so BEES publishes the shapes as a text file next to the unit (`bees_cfg.shapes`) and the examples spell them; the
validator's parameter lists use them verbatim. TRUST mode (the larger one):

net:      { listen_address: string, port: int64, connect_timeout_ms: int64, call_timeout_ms: int64 }
limits:   { frame_size_max: int64, args_len_max: int64, term_depth_max: int64, acceptors: int64 }
tuning:   { suspicion_limit: int64, token_bytes: int64, token_ttl_sec: int64, connect_stagger_ms: int64 }
session:  { max_inflight: int64, max_age_ms: int64, idle_ms: int64, more: { max_calls: int64, drain_ms: int64 } }
tls:      { cert_pem: string, key_pem_secret: string, ca_pem: string, classical_any: boolean }       // bytes; paths variant below
whitelist: List[{ fp: string, spec: string, classical: boolean }, mem(normal)]                      // fp: 128 lowercase hex characters (computed by the packer)
pins:      List[{ addr: string, fp: string }, mem(normal)]

BEAM mode: `net` (`name`, `creation`, `listen_address`, `listen_port`, `epmd_port`, `net_ticktime_s`, `open_timeout_ms`),
`auth` (`cookie_secret`, `transport`, `auth`), `redial` (`on`, `initial_ms`, `max_ms`), `links: List[{ peer: string, host: string, port: int64, role: int64 }]`
(one per build peer, matched by name), `limits` (`frame_size_max`), `spawn` (`mode`, allowlist).
Path variant: a field `*_path` in place of `*_pem` (the library's C reads the file; kept for the compatibility path and for the plain examples).

### 5.3 Validation

```
bees_cfg@validate_trust(net, tuning, session, tls, whitelist, pins, build)  -> (:ok, ValidCfg) | (:error, { path: string, line: int64, text: string })
bees_cfg@validate_beam(...)                                                -> (:ok, ValidCfg) | (:error, ...)
```

(`ValidCfg` is the same groups after defaults and clamps, so the caller keeps one value.) The reason is a record, not one string, so the
caller may log `text` or branch on `path`. `text` is `PATH: MESSAGE`. **As ruled (4), the byte-for-byte `bees.config:LINE: PATH: MESSAGE` is produced by the packer** (it runs the Python reader, which knows the lines); the library's check is the second, line-less one, and the example may carry the packer's line in a `line` field of the record if it has one. The oracle is `tools/bees_conf.py`
(`validate`, `proplist`, `want_int/str/bool/atom`, `parse_spec`, `beam_section` 565-750, `trust_section` 775-940: about 700 lines of rules) and the vectors of
`tools/test_bees_conf.py` (34 tests: `Document` checks the options table against `bees-config-file.md`, `Rules`, `N1`). The differential test (section 6, phase 2) runs
the same cases through both.
**What does not move into `validate`:** everything that touches the file system (does the cookie file exist, mode 0600, the whitelist file
exists, certificate readable, fingerprint of a certificate file): these were `check_file`/`cookie_check`/`fingerprint` in the oracle and become the **example's file step**,
which produces records in the library's shapes (and produces the same wording for the same cases, so the n3/n4 goldens keep their text). What validate adds: PEM sanity ("begins with `-----BEGIN`"), `fp` shape, list length against the
build's pool sizes, frame limits against the built limits.

### 5.4 Starting a node, and what the app gets back

n: actor_ref <- spawn(0, dangerous_bees_trust_node@node, stack_policy(0, :keep_last_message), state_policy(:keep_state_area));
cast(n, (:start, 2, me, net, tuning, session, tls, whitelist, pins) impl ActorMessage {})      // 2 = api_version, me = reply_to
```

**Superseded:** the first draft of this table used integer opcodes. The user ruled **no opcodes; atoms, shared** (ruling 2). The atoms below are ordinary atoms of BEES's `.atoms` manifest, registered in the unit the app lists first (section 10).

Message set:

| Message | Direction | Shape | Replaces |
| --- | --- | --- | --- |
| `:start` | app to node | `(:start, api_version, reply_to, net, tuning, session, tls, whitelist, pins)` (nine elements; a **cast** payload, not a function: E1070 does not apply) | `trust_boot` + `trust_start`, `net_start` |
| `:started` | node to `reply_to` | `(:started, lines)`: `lines` is the **boot banner and summary** as `List[string]` (today's `[trust] mode trust, ...`, `[trust] <note>`) for the app to print | `trust_notes`, the `[bees] mode=beam ...` lines |
| `:refused` | node to `reply_to` | `(:refused, path, line, text)` | `trust_boot`'s "boot refused" |
| `:call` / `:cast` | app to node | `(:call, addr, m, f, arity, args, reply_to, req)` | `trpc_call` / `trpc_cast`; the reply is the existing `{ req, what, value }` message, unchanged |
| `:reset` | app to node | `(:reset, entry_index, reply_to)`; reply `(:reset_done, ok)` | `trust_reset(i)`; **local only, still**: the node actor is the one you hold, no peer can reach it; the forbidden-name guard stays |
| `:stop` | app to node | `(:stop)` | (new; an orderly teardown) |
| raw writer messages | | `(:raw_send, ...)`, `(:raw_frame, ...)`, `(:raw_close, ...)` | `trust_raw_*`, for test programs only (kept in a test unit, not the library API) |

BEAM mode is the same family: `(:start, ...)`, replies `(:started, lines)`, `(:refused, ...)`, and `net_send_raw` etc. as test messages. The node actor
**is** the handle (an `actor_ref`); it registers nothing by atom except the name pools (3.1). The banner text and the refusal text are
produced by plain `bees_cfg` functions, so an app can also print them without a node (`bees_cfg@trust_banner(valid) -> List[string]`).
Exit status: the library never stops the process on a bad config; `(:error, ...)` or `(:refused, ...)` goes to the app, which prints it and decides.
The old behaviour (`[trust] boot refused: ...`, then `[trust] no actor was started`, `exit=1`) is the **example's** behaviour and is a few lines.

### 5.5 Where the config comes from (ruled: the storage transport and a Python packer; no Silica text parser)

**Superseded:** the earlier text of this section proposed an optional Silica parser of `bees.config` (estimated at 1200 to 1800 lines, never attempted) and a build-time `emit-silica` unit. The user chose the route below; both are dropped, and so is `read_lines`.

* **At deploy time, a small Python packer** (`tools/bees_pack.py`, new) reads `bees.config`, the whitelist file, the pin file, the certificates and the cookie file, runs **`tools/bees_conf.py` as the validator**
  (so every refusal is the existing `bees.config:LINE: PATH: MESSAGE` text, and the file-mode, "does not exist" and "not readable" wording stays here, in the packer), computes the **hex SHA-512 fingerprints** (ruling 6) and writes **one storage record**:
  the ETF encoding of the config term, a tuple of the groups of 5.2 (PEM bytes, the cookie and hex fingerprints included, or paths where the path form is used).
* **The storage record.** Silica's local storage transport is the `(:store)` carrier: `carried_on NAME: (:store) (:backing, "node.sildat", CAPACITY, :stop);` in a `dangerous_` unit of the app (path and capacity are literals of the declaration;
  capacity a multiple of 4096; a different size on disk ends the open with `(:link_down, :mismatch)`; a missing path is **created empty**, so an empty log means "no config" and must be reported by the example). The blocks are 4096 bytes with CRC-32C; a record is at most 4064 bytes
  and a larger value is segmented by `wireframe@frame(..., :storage)` and rebuilt by `unframe` in `:storage` mode (N0b 1.1, *(read)*). The packer writes that format (a Python precedent writes it: Silica's `make_backings.py`).
* **At boot, in the example**: spawn the storage carrier, `(:open, ...)`, `(:read, 0)`, collect `(:rx, record)` segments with credit until `(:rx_end, next)`, `unframe`, then
  `decode((:etf), frame, { max_bytes: N, max_depth: D, max_length: M })` inside `sequence proc[mem(normal), transport] ... produces pure` into the typed record. **`decode` is what de-taints** the foreign bytes (the rule of 2.2, as ruled). The limits are **literals** (E2402, probe `p5`),
  so `max_bytes` is a build fact in the app's `bees_build` unit, sized from the whitelist pool K (about 150 bytes per entry: 1000 entries need a limit above 150 KB) and the PEM sizes.
  A value the limits reject comes back `(:rejected, why)` (`:too_large`, `:unknown_atom`, `:bad_variant`); the example reports it as `(:error, ...)` text and does not start the node.
* **Typed result and SD-37.** The derived decoder cannot decode a record of more than **four fields** (SD-37, E1070 in the derived function); so every group of 5.2 has at most four fields (nested records, each at most four), and the whitelist is a list of three-field records.
  Whether a **tuple** of nine groups decodes is *(open; not probed)*; the fallback is one decode per group, one record per storage record, which the packer can do.
* **Then** the example calls `bees_cfg@validate_*` on the decoded groups, a second, cheap check (the packer already ran the full one) that also catches a stale or hand-edited record, and starts the node (5.4).
* **Not proved here:** the storage carrier was **not run** by this probe. It is built and trialled by Silica on Apple Silicon (`trials/transport_addition/app_transport_store_backing`, *(read)*); Linux is "in the pack source, not verified"; the boards have no `:flash_region` target yet (E2412), so on a board the example's source is a generated unit (the `(:memory)` store or embedded literals). Silica should state the taint status of the carrier's `(:rx, record)` cast (request, section 9 item 9).

### 5.6 The example set (documented, not library)

1. `examples/trust_node_storage` (hosted): the packer writes the storage record at deploy time; the app reads it through the `(:store)` carrier, `decode`s it, validates, starts the TRUST node, and prints the returned banner lines.
2. `examples/beam_node_storage`: the same for BEAM mode (the cookie value is in the record; the 0600 check ran in the packer).
3. `examples/node_embedded` (boards): the configuration written by the packer as a Silica unit of literals (`bees_pack.py --as-source`), for NUCLEO-L476RG and ESP32-S3 until a flash-region store exists.
4. `examples/node_no_config_file`: a root that builds the groups by hand (the smallest use of the library, and the first L2 trial).

## 6. Q6: impact, migration, effects on later work

### 6.1 Inventory of what changes

Counts from the tree as of 2026-11-17 *(read; `git status` shows many of these modified by other agents, so each edit must wait for that work to settle)*:

| Item | Today | Change |
| --- | --- | --- |
| `src/shim/*.part` (8 files: `beam_node_edge` 218, `bees_node_edge` 196, `bees_trust_node` 165, `bees_resolve_edge` 47, `bees_tcp_edge` 15, `bees_trust_link_tls` 20, `bees_trust_link_plain` 12, `bees_resolve_none` 9) | pasted | become behaviours in `dangerous_*` library units; the node-callable surface becomes messages. **About 700 lines of Silica move and are re-shaped** |
| `tools/bees_edge_gen.py` (103), `tools/bees_trust_gen.py` (177) | write the root unit | shrink to a root *template* (examples) and the build-fact unit; they stop being required |
| `tools/bees_config_beam.py` (247), `tools/bees_config_trust.py` (239), the `conf`/`gen_conf` outputs `beam_conf`, `bees_trust_conf`, `bees_peers` (via `tools/bees_dist_gen.py`, 379) | generate run-time constants and the boot error | the run-time constants leave; they keep `bees_peers`' per-peer *code*, pool atoms, `bees_trust_mfa`; the boot error disappears into `validate` |
| `tools/bees_conf.py` (1024), `tools/test_bees_conf.py` (555) | the one reader (build time) | stays, as the build-time extractor, the oracle, and `emit-silica`; gains a `dump` command (N0b) |
| `tools/bees_config.py` (700), `bees_wire_gen.py` (931) | atoms, modules, ids, codecs | unchanged (they never read `bees.config` except `--config`, which the library path drops) |
| `tools/trial.mk` (+ `silica.mk`) | runs `bees_config generate --config bees.config`; root generation by each leaf's Makefile | gains the second form (a leaf supplies an app root and a `cfg` unit); the first form stays during the move |
| Trials with `bees.config`: `m3_dist`, `m3_multilink`, `m3_reconnect`, `m4_demo`, `n1_addr`, `n1_frames`, `n1_limits`, `n2_dist`, `n2_live`, `n2_multilink`, `n2_reconnect`, `n2_soak`, `n3_trust`, `n4_trust_tls` (14 leaves, about 44 config files) | root generated from `.part` + role files | **unchanged in the compatibility phase**; converted one leaf at a time in the later phase (the node roots become ten-line app roots) |
| Goldens with the banner (50 `.scout` files carrying `[bees] mode`, `[trust] mode` or `BEAM mode:`), `n3_trust/boot_missing`, `boot_unreadable`, `n2_dist/loose_cookie` | banner printed by the part | **text must not change**; the example prints the `lines` the library returns. `loose_cookie`: the 0600 check moves from "at the first handshake" to the example's file step, so that golden's *timing* changes (the node is refused before it starts) |
| `native/src/silica_bees_beam.c`, `native/tls/silica_bees_tls.c`, wrappers (`.meta`, `.h`) | path-only | **add** `bees_beam_set_cookie`, `bees_tls_configure`, `bees_tls_fingerprint`; keep the path entry points |
| `contract/so-you-want-to-write-a-compiler.md` A1.2 (atoms manifest), A6.3 (D30), B1b (`bees.config` versus the manifest, "nothing is implemented"); `contract/what-is-required-to-use.md` ("BEES owns `main`"); `contract/wire-v1.md` 335-356 (caps from `bees.config`) | | A1.2/A6.3 **unchanged** (atoms still a manifest merged into `bees_atoms`); B1b and the `main` statement rewritten; wire-v1 caps text: "the caps are parameters of the start message, bounded by the built limits" |
| Docs: `development-plan/bees-config-file.md` (section 11), `N0b-boot-config-reader.md` (its file-reading parts move to the examples; its parser, validator and taint findings stay valid), `mvp.md`, `roadmap.md` (D26, D3), `README.md` | | rewrite the "boot reader" framing to "library plus examples" |
| `/Users/yenrab/to-silica/tools/node_kit/build_node.sh` *(read only)* and `APP_GAPS.md` | builds a sink-printed node in BEES's BEAM mode: copies `trials/n2_live/nodes/l/lib`, writes `bees.config` beside the unit, runs `bees_edge_gen.py` + `trial.mk`; the README says "BEES owns `main`" and the contract T9.17 has the sink print `<unit>.bees.config` | **keeps working through the whole compatibility phase unchanged.** After the move: its root becomes the app root ("the sink-printed unit is a library; `run/0`") and `bees.config` is converted by `emit-silica`; "BEES owns `main`" becomes "the root is the template's". The sink's `<unit>.bees.config` output (T9.17) stays the interchange format |

### 6.2 What survives untouched

* The mutual-TLS engine's TLS logic and its tests (`native/tls`, `dangerous_bees_tls*`, `bees_trust_frame`, the guard): only **new entry points** are added; the path entry stays.
* TRUST logic: `bees_trust_frame.silica`, `bees_trust_guard.silica`, `bees_trust_work.silica`, the `tpeer`/`tcache`/`tcli` behaviours: moved nowhere; only their startup moves.
* BEAM-mode links: `dangerous_beam_net` (1001 lines), `dangerous_bees_net` (662), `beam_dist`, `bees_dist`, `bees_wire`, the multi-link and reconnect work in flight: **not touched**; their `beam_conf@...()` reads are the class-(a) values that later become state fields (N0b phase 3).
* The wire codecs, atoms, module table, ids, the conformance kit.

### 6.3 Phased migration (the old way keeps working until the last phase)

| Phase | Work | Exit criterion (testable) | Size (agent-days) |
| --- | --- | --- | --- |
| **L0** (this document) | probes and plan | the user rules on section 9 | done |
| **L1: the plain unit and the API types** | `bees_cfg` (groups, defaults, validate, banner/refusal text) ported from `bees_conf.py` rules; `tools/bees_conf.py dump` | for every vector in `tools/test_bees_conf.py` (extracted to one file each), `validate` returns the same verdict and the same `text` as the Python reader; a trial prints both; **no change to any existing trial** | 8 to 10 (700 lines of rules; the cost of big `case` tables on the checker is the risk) |
| **L2: node actors beside the parts** | the `.part` code copied into `dangerous_bees_trust_node` and `dangerous_bees_beam_node` as behaviours with the message set of 5.4; the `.part` files stay | a new trial `l2_trust_node` and `l2_beam_node` (an app root of ten lines, no generator) passes with the **same goldens** as `n3_trust` and `n2_dist` for one scenario each; old trials untouched | 8 (TRUST), 8 (BEAM) |
| **L3: the packer and the compatibility path** | `tools/bees_pack.py` (new, Python): validates `bees.config` with `bees_conf.py` and writes the ETF config term as a storage record (the file the app's `(:store)` declaration names); `tools/trial.mk` gains a mode where a leaf supplies an app root listing BEES's units in its `silica.config`; old mode default | one leaf per mode (n3_trust, n2_dist) runs both ways from the **same `bees.config`** and the output goldens are equal; the packer's refusal text equals the Python reader's; `make integrate` passes in full with the old mode still the default | 5 |
| **L4: bytes** | `bees_beam_set_cookie`, `bees_tls_configure` (OpenSSL memory BIOs), `bees_tls_fingerprint`; the Mbed TLS equivalents written but not built (no board toolchain installs) | the n4 mutual-TLS trial passes with **bytes** (certificates and key as strings read by the example) and with paths; refusals unchanged | 4 to 5 |
| **L5: run-time scalars and the data-driven gate** | N0b phases 3 and 4: `beam_conf`/`bees_trust_conf` values come from the start message into actor state; whitelist and pins as lists consumed at start (per-entry actors from a K pool); permission gate over data | an unmodified binary starts with a changed whitelist (within K) and refuses one that is too long; SD-35 not hit (measured as in 2.1); n3/n4 goldens equal | 10 to 12 |
| **L6: examples** (as ruled: no Silica text parser) | `examples/` (5.6): the packer-and-storage example for TRUST and BEAM, the board example | the example reads the storage record, `decode`s it, validates and starts a node with **no generator for the values** and with the same output as the build-time path | 4 to 5 |
| **L7: retire the stand-in's run-time role** | old generators' run-time constants removed; `bees_trust_gen`/`bees_edge_gen` reduced to templates; node_kit updated; docs rewritten | grep: no `beam_conf@`/`bees_trust_conf@` run-time read left; `make integrate` and `make kit` pass; node_kit's three-node live run reproduces | 4 |
| Total | | | **about 35 to 55 agent-days** (the Silica text parser, 10 to 15 days, is no longer in the plan) |

### 6.4 Effects on the Linux port, N2T, N5

* **Linux (AArch64 `silica-999936-linux-aarch64`, x86_64 `silica-999944`; D29):** the library model is *easier*: the per-platform native
  directory is selected by the app's Makefile, nothing is pre-linked. New work: the cookie/TLS bytes entry points need the same OpenSSL calls (they are portable); `bees_beam_*` uses CommonCrypto
  today (macOS only), so the cookie's MD5 and random source need the Linux equivalents either way (kernel CSPRNG per D40), independent of this plan. I did not compile on Linux; compiler-version parity (the pin is 999909 on macOS, the Linux binaries are different generations) is *(open)* and affects whether probes `p1a`, `p4` hold there. `read_lines` has per-target inline emitters *(read)*.
* **N5 (windowed multiplexing, B2):** unaffected in design; but its per-connection supervisor and a worker per request add behaviours that
  today would be pasted; as library behaviours they come free with L2. It benefits from the data-driven gate (L5). The `session.*` values are class (a) and already in the groups of 5.2.
* **"N2T" (ruled 2026-11-18: BEAM-mode TLS, an `inet_tls_dist`-compatible profile, after the Linux port):** it builds on this plan, not beside it. It needs the TLS-from-bytes entry points of L4 (the same OpenSSL calls, on Linux), the BEAM node actor of L2 (a TLS link is a worker over the carrier, as TRUST's `ttls` is; the carrier choice becomes one of the two source fragments of ruling 7), and the cookie as a value (the `inet_tls_dist` handshake still uses the cookie). It is **sequenced after L7 and after the Linux port**.

## 7. What the probes proved, and could not prove

| Claim | Status | Evidence |
| --- | --- | --- |
| A `dangerous_*` library behaviour can `spawn_dangerous` a carrier and cast to it; a plain-spawned root can start it by reference | **proved** | `p1a`: `launcher` received `(:link_down, ...)` from the carrier |
| A `dangerous_*` library behaviour can `spawn_dangerous` a library **FFI worker with C** (BEES's resolver) and get its answer | **proved** | `p4`: printed `resolved localhost: 127.0.0.1` |
| A plain unit cannot `use` a `dangerous_*` unit (E4021), cannot name `dangerous_actor_ref` (E4026); the root cannot call any function of a `dangerous_*` unit (E4042) | **proved** | `p1a`, `n2`, `n1` |
| A plain unit may spawn actors, start a supervisor, `read_lines` (a fact, no longer used), be called from a `dangerous_*` root | **proved** | `p2`, `p3` |
| A 7-field record with a 1000-entry list of 128-hex fingerprints and a 4.6 KB string is a parameter, a result and a message value | **proved** | `p2` |
| A 14-field nested record, a 64 KiB and a 256 KiB string, 10000 list elements pass in a message | **proved** | `p3` |
| SD-35 costs about 100 times the CPU for a held 1000-entry list | **measured** | `p2`: 2.91 s against 0.03 s |
| `decode` limits cannot be run-time values on 999909 | **proved** | `p5` E2402 |
| Atoms in API messages hit SD-3 without a registering unit | **proved, re-proved and narrowed** (section 10: tuple-tag atoms that a receiver uses only in a type and a pattern are not registered; the pattern compares 0 and 1) | `p1a`, `at/v1` |
| `read_lines` output passes the compiler's taint pass; needs the runtime shim to link | **proved, and now unused** (ruling 3 drops `read_lines`); kept as a fact | `p3` |
| The API with atoms (no opcodes) needs the atoms registered in an earlier unit | **proved and narrowed** (section 10) | `at/v1`, `v2`, `v6`, `v10`, `v12` |
| A whole node (`net_launch` and the dial/listen/redial code, or the TRUST node) works as a behaviour in a library unit | **not proved**: the carrier and the resolver worker were; the real node code was not moved (no repo edits allowed) | L2 |
| The TLS worker (`ttls`, `trnd`) spawned from inside a library behaviour | **not proved** (the resolver, the same class, was) | L2 |
| A record state spelled across units for a spawned behaviour | **not probed** (use scalar state `0`) | design |
| OpenSSL memory-BIO loading and the Mbed TLS buffers inside BEES's FFI shapes | **not built** (no C compiled: the rule is no builds except Silica probes asked for; and no Mbed TLS source in the tree) | read only |
| A Silica parser for the `bees.config` text | **not needed** (ruling 3: a Python packer and `decode`); the estimate of 1200 to 1800 lines is kept only as the cost of the alternative | 5.5 |
| The storage carrier reads an ETF config record and `decode((:etf), ...)` yields the typed groups (limits literal, groups of at most 4 fields) | **not probed** (read: Silica design and trials); it is the first thing L1/L6 must prove | 5.5 |
| Zeroisation of secrets in Silica | **not provable**; no facility found | 4.4 |
| One 1 MiB string in a message | **not settled** (my builder was quadratic) | `p3` |
| Linux behaviour of any of this | **not tested** | |
| (dropped by the ruling) `read_lines` taint status in the specification | not needed: `read_lines` is not used | |

## 8. Recommended API, risks

**Recommendation (as ruled 2026-11-18).** (1) Build the library as plain `bees_cfg` (types, validate, banners) plus `dangerous_*` **node-actor** units; the app's root is a ten-line `dangerous_<app>`
that spawns the node by reference and casts the start message with atoms. All units are listed in the app's one `silica.config`. (2) The **first example** reads its config through the **storage carrier**: a Python packer validates `bees.config` at deploy time and writes the ETF record; the
app `decode`s it into the groups (no Silica text parser, no `read_lines`). (3) Cookie and TLS material as bytes in the start message, paths kept as a second form. (4) Config groups of at most **4** fields (SD-37 applies because the groups are decoded), the whitelist and pins consumed at start, never held in state. (5) The app's `silica.config` lists BEES's units, the atoms unit **first**, `bees_build`
and the generated per-peer/MFA units from BEES's Python tool and templates; BEES ships no binary.

**Risks**

1. **The node code has not been run as library behaviours** (section 7): the probes prove the *mechanism*, not the 1600 lines of `dangerous_beam_net`/`bees_node_edge.part`. The unproven corner is the SD-39 family
   (`dangerous_actor_ref` in state, whole-state copies): moving the start-up into a behaviour adds state fields. Mitigation: L2 is a copy beside the old path, with the n2/n3 goldens as the gate and the SD-35/39 memory measurement of the rate trials.
2. **Taint, secrets and the storage route.** Bytes from the storage carrier are tainted and only `decode` de-taints them (as ruled); the storage carrier itself was **not probed** here (read only), its Linux and board targets are unverified (`:flash_region` has no target yet, E2412), a missing backing is created empty rather than reported, and the decode limits are literals, so the whitelist's size is a **build** fact. A key held in a Silica string cannot be wiped: the promise is no retention and no logging.
3. **Atoms across units.** A receiver compiled before its sender silently compares its tuple tags against 0 and 1 (section 10: a defect, reproduced on three compilers). The mitigation is a build-order rule (BEES's atom unit first, with an expression literal for every API and protocol atom) that `bees_config check` must enforce in the app's build, because the failure appears at run time ("no case arm matched"), never at compile time. The Silica fix would remove the rule.
4. **E1070, SD-37 and no aliases** make the record shapes long and the signatures brittle; groups of at most 4 fields and a `bees_cfg.shapes` text help but every app spells them.
5. **Silica-side gaps that BEES cannot close** (N0b SR-A to SR-H, updated by the rulings): run-time decode limits (SR-D, proved E2402), a stated taint status of the storage carrier, `int_to_string`/`string_to_int`, a way to name a record shape, zeroisation, and the tuple-tag atom defect of section 10. (The `read_lines` requests are dropped.)
6. **Churn:** `dangerous_beam_net`, `dangerous_bees_net`, the generators and the trial Makefiles are being edited by other work now; L2 and later phases wait for that to land (decision 11).

## 9. Decisions, and what the user ruled (2026-11-18)

All eleven suggestions were **accepted**. Each row gives the question and the ruling; the table at the top ("Rulings") is the short form.

1. **API shape: node actors by message.** *Ruled: accepted.* One source unit, one compile, no pasting; the node actors are spawned by reference and driven by messages.
2. **Tags: integer opcodes, or atoms?** *Ruled: no integer opcodes; atoms, shared.* The messages are `(:start, ...)`, `(:started, ...)` and so on (5.4). Section 10 shows what "shared" requires today: BEES's atoms registered by an expression literal in a unit listed **before** the receivers.
3. **First example's config source.** *Ruled (changed from my suggestion): through Silica's local storage transport, not `read_lines`.* A Python packer validates `bees.config` at deploy time and writes a storage record holding an ETF-encoded config term; the app reads it through the storage carrier and `decode((:etf), ...)`s it into a typed record. No Silica text parser. `decode` de-taints.
4. **Validation messages.** *Ruled: byte for byte `bees.config:LINE: PATH: MESSAGE`;* the file-mode and "does not exist" wording lives in the packer and the examples.
5. **Cookie and key as bytes.** *Ruled: BEES guarantees no retention and no logging; scrubbing is a Silica request.*
6. **Fingerprints.** *Ruled: the whitelist carries hex fingerprints computed by the packer.*
7. **`plaintext_test_only` and the link kinds.** *Ruled: two source fragments the app chooses in `silica.config`,* not a run-time flag.
8. **Pool sizes.** *Ruled: stated by the app at build time* (`bees_build`).
9. **Silica requests.** *Ruled: draft them:* run-time decode limits, a stated taint status of the storage carrier, `int_to_string`/`string_to_int`, a way to name a record shape, zeroisation. **`read_lines` is not to be used, so its two requests are dropped.** One more defect is drafted in section 10 (tuple-tag atoms).
10. **"N2T".** *Ruled: BEAM-mode TLS (an `inet_tls_dist`-compatible profile), after the Linux port.* It is therefore a later phase of this plan, after L7: the TLS bytes entry points of L4 and the node actors of L2 are what it will build on.
11. **Sequencing.** *Ruled: as proposed:* L1 and L2 start after the multi-link/reconnect/`make integrate` work has landed and is committed.

## 10. Atoms check (2026-11-18): is the shared atom table fixed? Partly; one case is still a defect

**Question.** Silica's `APPLICATION_IS_ONE_COMPILATION_UNIT.md` says (status 2026-10-16) that atoms are fixed: one build-wide `silica.atoms` that every unit reads and extends, shapes in `silica.shapes`, and the trials `trials/modules_addition/sd3_cross_unit_atoms*.silica` pass. Probe `p1a` nevertheless hit "no case arm matched" on 999909 with a `silica.atoms` present. Which is true?

**Both, and the difference is what the receiver does with the atom.**

*How Silica's trial is built (read).* `sd3_cross_unit_atoms.silica` (`trials/modules_addition/`) lists its units in `silica.config` and compares atoms that **travel as function results**: `sd3_atom_a@mint_mango()` returns `:mango`, and `sd3_atom_b@classify(z)` matches it. Those atoms are **expression literals** (`fn mint_mango() -> atom { :mango }`), and an atom that appears as an expression literal is registered in `silica.atoms` by the unit that writes it. The trial uses `silica-compiler` (the pinned 999909) and has no actor message and no tuple tag. So the document's claim holds for that shape.

*What BEES does, and what fails (probes in `/private/tmp/claude-1331430978/-Users-yenrab-project-bees/2e742689-9b61-46cc-b8c9-af30f64162f8/scratchpad/api_probe/at/`, one compile each, `nice -n 10`, one `silica.config` in dependency order, the table deleted before each run unless stated).* The shape: a library behaviour in a `lib/` unit, **spawned by reference** from the root, receives a union of tagged tuples; the root casts `(:go, 1)`.

| Variant | Receiver unit (`rx`) | Result on 999909 | Constants the receiver's `case` compares |
| --- | --- | --- | --- |
| `v1` | union type `(:go, int64) \| (:stop, int64)` and a pattern for each; the atoms appear **nowhere else**; root first writes `:go` | **fails** ("no case arm matched") | `0` and `0`/`1` (variant positions), not atom numbers; `silica.atoms` ends `...:no_reply, :go` (no `:stop` at all) |
| `v2` | as `v1`, plus `fn a_go() -> atom { :go }` and `fn a_stop() -> atom { :stop }` **in the same unit** | works | the table's numbers, 26 and 27 |
| `v4` | **plain atoms**, not tuple tags: `msg: :go \| :stop`, patterns `:go`, `:stop`; root casts `:go` | works; `silica.atoms` holds both | table numbers |
| `v6` | as `v1`; an **earlier** unit `zz0` (not `use`d by `rx`) has the expression literals `:go`, `:stop` | works | 26 and 27 |
| `v10` | as `v6` but `zz0` holds only `:go` | works for `:go`; the `:stop` arm compares `0` | 26 and `0` |
| `v12` | as `v6` but `zz0` listed **after** `rx` | **fails** | `0` and `0` |
| `v7`, `v8` | `v1` rebuilt with a **stale `silica.atoms`** that already lists `:go` (v8: and `:stop`), no registering unit | **fails** (a stale table does **not** help) | `0` |
| `v9` | single-variant union `(:go, int64)` | **fails** | `0` |
| `v1` on 999910 and 999926 | | **fails** on both | |

**Conclusion: "works as Silica's document says when X", and X is narrower than the document.**

* *Works:* an atom that is a **plain atom**, or an **expression literal** somewhere in a unit compiled **before** the unit that matches it, gets the build-wide number in every unit (`v2`, `v4`, `v6`).
* *Still a defect:* a **tuple-tag atom that the receiving unit mentions only in a union type and a pattern** is never registered in `silica.atoms`, and the pattern is compiled against the variant's position (0, 1, ...) instead of an atom number. The sender (the root, compiled later) registers the atom as `26` and sends `26`. The receiver compares `0`. **Nothing is reported at compile time.** Order matters (`v12`); a stale table does not repair it (`v7`, `v8`); it does not depend on the stdlib carriers, on `dangerous_` units or on FFI (it fails in a plain unit, `at/v1`). The language's own carriers receive `(:open, ...)` and similar tags from other units correctly because their atoms are also expression literals in units compiled earlier (`Carrier.silica` and the like), which is why the defect was not met there.
* *Why BEES's D30 workaround works:* `bees_atoms` is listed first and writes every atom as an expression literal (`fn a_go() -> atom { :go }`), which is exactly condition X. **Under condition X the shared atoms unit is not needed as a `use`d unit**: it only has to be **listed earlier in `silica.config`** (`v6`: `rx` does not `use` `zz0`). It cannot be dropped altogether until Silica fixes the defect below.
* Consequence for the rulings: "atoms, shared" (ruling 2) holds if BEES's atom unit, with an expression literal for every API and protocol atom, is the **first** unit of the app's `silica.config`, and `bees_config check` verifies it. The app's own message atoms follow the same rule.

**Silica defect draft (for the user to file).**

> **Title.** A tuple-tag atom used only in a type and a pattern of a receiving unit is not registered in `silica.atoms`; the pattern compares the variant index, and a message cast from a later unit with the same atom is never matched (silent, run time).
>
> **Affects.** silica-999909, 999910 and 999926, macOS Apple Silicon (not tried elsewhere). `APPLICATION_IS_ONE_COMPILATION_UNIT.md` (2026-10-16) says atoms are fixed; the trials `sd3_cross_unit_atoms*` pass because they send atoms as function results written as expression literals.
>
> **Reproduction** (3 files, one `silica.config` in this order: `lib/bees_reporter.silica` (any failure reporter), `lib/rx.silica`, `main.silica`). Delete `silica.atoms` before the build.
> ```
> // lib/rx.silica
> module rx;
> export beh/2;
> fn beh(msg: (:go, int64) | (:stop, int64), st: int64) -> (:no_reply, int64) {
>     case msg of {
>         (:go, n: int64) -> { sequence proc[device_io] _: atom <- println("go received") produces pure (:no_reply, st + n) end };
>         (:stop, _m: int64) -> (:no_reply, st)
>     }
> }
> // main.silica
> use bees_reporter; use rx; module main;
> fn main() -> int64 {
>     sequence proc[concurrency, device_io]
>         _: atom <- bees_reporter@start();
>         a: actor_ref <- spawn(0, rx@beh, stack_policy(0, :keep_last_message), state_policy(:keep_state_area));
>         _: boolean <- cast(a, (:go, 1) impl ActorMessage {});
>         _: int64 <- wait_for_exit()
>     produces pure 0 end
> }
> ```
> **Observed.** `=== Silica Actor Failure === reason: :language_error: no case arm matched, #0 rx_beh`. `rx.sams` compares the first word of the message with `#0` (and `#1`); `main.sams` stores `#26`; `silica.atoms` ends `:no_reply`, `:go` and does not contain `:stop`.
> **Expected.** `go received`: the pattern atom is registered in the build-wide table, in `rx`, and `main` finds it there (as it does when `rx` also contains `fn a_go() -> atom { :go }`, or when an earlier unit does).
> **Variants.** Works with the atoms as expression literals in `rx` or in an earlier-listed unit; works with plain atoms (`msg: :go | :stop`); fails with the atoms' unit listed after `rx`; fails with a stale `silica.atoms`.
> **Impact for BEES.** Every message protocol between a library behaviour and its sender is exposed. BEES keeps D30 (the atom unit listed first) until this is fixed; a fix would let the app's `silica.config` drop that ordering rule.

The reproduction sources are kept in the scratchpad (`at/v1/lib/rx.silica`, `at/v1/main.silica`); they are not in the repository.
