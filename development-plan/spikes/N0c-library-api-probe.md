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

## 0. Findings in one page

1. **The `.part` pasting is not forced by E4026/E4042, but the shape of the API is.** Three rules decide it, all proven by probes:
   a unit that holds `dangerous_actor_ref` or calls `spawn_dangerous` must be named `dangerous_*` (E4026, probe `n2`); every unit that
   `use`s a `dangerous_*` unit must itself be `dangerous_*` (E4021, probe `p1a`), so the app's root is `dangerous_<app>`; and the app
   (or any unit) may not **call** any function of a `dangerous_*` unit outside an FFI worker (E4042, probe `n1`: even a function that does
   `x + 1`). What a root **can** do is *spawn a `dangerous_*` unit's behaviour by reference and cast to it*. A behaviour of a
   `dangerous_*` library unit can itself call `spawn_dangerous` (carrier: probe `p1a`; BEES's own native-edge FFI worker
   `dangerous_bees_dns@resolver` with its C: probe `p4`) and cast to what it spawned. So BEES's start-up code can live in the library as
   **node actors** that the app starts by reference and talks to by message. Today's root-unit functions (`net_launch`, `trust_start`,
   `trpc_call`, `trust_reset`) become messages; their return values become reply messages.
2. **A typed config record travels** as a function parameter, a function result, and an actor message value, including a list of 1000
   records with 128-hex-character fingerprints and a spec each (probe `p2`; a wide, nested record: probe `p3`). Holding that list in an
   actor's **state** costs about 100 times the CPU per dispatch (SD-35, measured: 2.9 s against 0.03 s for 30000 messages), so the
   list is consumed at the message, not kept in state.
3. **No pre-compiled anything is needed, and the compile-time facts become source the app owns.** The genuinely build-time items are
   the atom table (D30; probe `p1a` re-proved SD-3: a tuple atom sent across units without the shared atoms unit hits "no case arm
   matched"), the module table, the per-peer/per-link code of BEAM mode, the decode limits (E2402 proven by probe `p5`: a non-literal limits record is a
   compile error), and the pool sizes of registered names. Everything else in `bees.config` can be a run-time value (section 3).
4. **Bytes instead of paths is a small C change** in both engines (OpenSSL memory BIOs, Mbed TLS buffer parsers; the cookie as a value), inside the existing FFI shapes (section 4). Nothing was built; the cost is a plan, not a measurement.
5. **A new fact found while probing: `read_lines` links only with the runtime shim.** A program that uses the intrinsic `read_lines`
   compiles (no taint complaint, from a plain unit, `proc[device_io]`) but does not link under BEES's `trial.mk` link line:
   `Undefined symbols: _silica_read_file_path`. Linking `compiler/src/silica_rt_shim.s` assembled to an object fixed it, and the
   program then read the file (probe `p3`). The app's build must add that object (a Silica packaging gap to report, not a BEES defect).
6. The old SD-17 row ("FFI workers cannot live in a library unit") is **stale for this layout**: `dangerous_bees_dns@resolver`
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
* **Atoms in the API messages need D30** (probe `p1a`: the same program fails with "no case arm matched" until a `probe_atoms` unit,
  `use`d by both sides, holds the atoms). Either the API messages carry **integer opcodes** (no atom crosses the boundary; recommended, section 5) or the app's `bees_atoms` contains the
  API atoms, which BEES ships as a manifest (`bees_api.atoms`).

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

### 2.2 Taint: what the app's file bytes are

* The taint checker seeds taint only on calls **qualified with a `dangerous_*` module inside a worker's `external_danger` sequence**
  (silica-defects SD-24, SD-25, memory note `silica-ffi-taint-copy-rule`). A value returned by the **intrinsic `read_lines`** is not
  such a call: probe `p3` read a file in a plain unit under `proc[device_io]`, kept it as a `string`, took `substring`, passed it to
  `println` and into message casts, and the FFI-taint pass did not object. So **the app's file read with `read_lines` needs no
  `decode`**: the string is an ordinary pure string and can be passed to the validator and the parser (both pure). That is evidence
  that it is *not tainted by the compiler's model*; the spec's own wording on the intrinsic's trust status I did not find *(open: ask Silica to state it, N0b SR-C)*.
* Bytes that arrive from a **foreign call** (the storage carrier `(:rx, record)`, any BEES native-edge worker) are tainted and are
  de-tainted only by `decode((:etf), ...)` inside `sequence ... produces pure` with literal limits (the resolver edge does this today:
  `rs_text` in `bees_resolve_edge.part`, proven in trial `n1_addr`). **For an app that reads its file through a carrier or a C helper, `decode((:etf), frame, {literal limits})` is the way back to a pure value**; an app that reads by `read_lines`
  skips it. The example documents both.
* `read_lines` has no error cause and no size cap and no mode check (N0b 1.2), so the **0600 check on a key/cookie file and the typed
  errors ("does not exist", "not readable (permissions)", "readable by group or others") cannot be had from it**. An example that wants those
  uses a C helper (the shape of `bees_beam_load_cookie`: `open(O_NOFOLLOW)`, `fstat`, mode test) returning bytes to an app unit through
  an ETF binary and `decode`. The library itself checks no file.
* The app's bytes that **go into** an FFI call (the PEM or cookie string handed to C) are ordinary strings: no taint rule restricts
  arguments. SD-40 applies: bind a string to a variable before the foreign call (string argument written as a call expression reaches C with the wrong pointer, N0b/silica-defects row SD-40).

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

1. **Silica units**, compiled by the app's compiler run: `lib/` symlinks (or copies) of BEES's `src/inter_nodal/*`, `src/shim/*.silica`,
   `src/trust/*` that the app uses, and the Silica stdlib units BEES needs (`carrier`, `dangerous_sockets`, `dangerous_tcp_carrier`,
   `wire_etf`, `wireframe`, `Supervisor` if used). Exactly as `trials/*/lib` does today; the pin file's role (a source revision) is the version.
2. **One generated unit set the app owns**, produced by BEES's Python source tool from manifests the app and its compiler write:
   `bees_atoms` (+`.index`), and, BEAM mode, `bees_peers`/`bees_msgs`/`bees_modules`/`bees_ids`; TRUST, `bees_trust_mfa`. Today's
   `tools/bees_config.py generate -o lib MANIFEST...` does all of it already; the **change is that it no longer reads `bees.config`**.
   (A pure-Silica alternative would put the atoms in a hand-written unit; the 256-arm `case` tiering `bees_config` does makes that impractical by hand for a large program.)
3. **A tiny app-owned unit `bees_build`** (BEES ships a template, `src/api/bees_build.silica.in`) with the build facts the library
   needs as constants: `frame_max_built`, `args_len_max_built`, `term_depth_max_built`, `whitelist_slots_max`, `pinned_servers_max`.
   The decode limits in BEES's derived decoders `use` these. Hand-written, five lines; no generator needed. (Whether
   a unit's literal limits can come from another unit's function: **no**, E2402 wants literals; so the decode call sites that carry
   the built limits are themselves generated from the template, or the template **is** the unit that contains those `decode` calls. This is the one place where a generated unit is unavoidable: **the generator writes it from the app's `bees_build` numbers.** *(read: tools/bees_config_beam.py `gen_conf`, tools/bees_trust_gen.py)*)
4. **Native C**, compiled by the app's build: `native/Makefile` pieces per platform (macOS: CommonCrypto, OpenSSL; Linux; ESP32-S3 and NUCLEO with
   Mbed TLS, D40); the `silica.link` archive paths in the app's tree (`dangerous_exposure_source/...`).
5. **The runtime shim object** for `read_lines` (finding 5), if the app uses it.

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
app root (dangerous_<app>.silica)         BEES units (copied/linked into lib/)
  main()                                    bees_cfg        PLAIN:  record groups, defaults, validate, banner, text rendering
   reporter start                           bees_cfg_text   PLAIN, optional: parse bees.config text (Silica), or a Python tool
   read files (example units)               dangerous_bees_beam_node   behaviours: node actor, tx, conn, lsn, nrd ... (today's .part code)
   cfg = bees_cfg@...  (pure calls)         dangerous_bees_trust_node  behaviours: node actor, tpeer, tcache, tcli ... (today's .part code)
   v = bees_cfg@validate_beam(cfg)          bees_atoms, bees_peers, bees_msgs ...    generated by the app's build (section 3.2)
   n = spawn(0, ..._node@node, ...)         dangerous_bees_*_native / tls / trust    FFI workers (unchanged)
   cast(n, (1, api_version, groups...))
```

The only functions the app **calls** are plain (`bees_cfg@...`); everything started is **spawned by reference and cast to**.

### 5.2 Config groups (plain unit `bees_cfg`; each at most 5 fields at top level, nested for more)

Silica has no aliases, so BEES publishes the shapes as a text file next to the unit (`bees_cfg.shapes`) and the examples spell them; the
validator's parameter lists use them verbatim. TRUST mode (the larger one):

```
net:     { listen_address: string, port: int64, connect_timeout_ms: int64, call_timeout_ms: int64, acceptors: int64 }
tuning:  { suspicion_limit: int64, token_bytes: int64, token_ttl_sec: int64, connect_stagger_ms: int64, frame: { frame_size_max: int64, args_len_max: int64, term_depth_max: int64 } }
session: { max_inflight: int64, max_age_ms: int64, idle_ms: int64, max_calls: int64, drain_ms: int64 }
tls:     { cert_pem: string, key_pem_secret: string, ca_pem: string, classical_any: boolean }     // bytes; paths variant below
whitelist: List[{ fp: string, spec: string, classical: boolean }, mem(normal)]                    // fp: 128 lowercase hex characters
pins:      List[{ addr: string, fp: string }, mem(normal)]
```

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
caller may log `text` or branch on `path`. `text` is **byte-identical to the Python reader's** `bees.config:LINE: PATH: MESSAGE` when the
caller gives a line (the optional parser supplies `line`; otherwise `text` is `PATH: MESSAGE`). The oracle is `tools/bees_conf.py`
(`validate`, `proplist`, `want_int/str/bool/atom`, `parse_spec`, `beam_section` 565-750, `trust_section` 775-940: about 700 lines of rules) and the vectors of
`tools/test_bees_conf.py` (34 tests: `Document` checks the options table against `bees-config-file.md`, `Rules`, `N1`). The differential test (section 6, phase 2) runs
the same cases through both.
**What does not move into `validate`:** everything that touches the file system (does the cookie file exist, mode 0600, the whitelist file
exists, certificate readable, fingerprint of a certificate file): these were `check_file`/`cookie_check`/`fingerprint` in the oracle and become the **example's file step**,
which produces records in the library's shapes (and produces the same wording for the same cases, so the n3/n4 goldens keep their text). What validate adds: PEM sanity ("begins with `-----BEGIN`"), `fp` shape, list length against the
build's pool sizes, frame limits against the built limits.

### 5.4 Starting a node, and what the app gets back

```
n: actor_ref <- spawn(0, dangerous_bees_trust_node@node, stack_policy(0, :keep_last_message), state_policy(:keep_state_area));
cast(n, (1, 2, me, tuning_etc...) impl ActorMessage {})        // (opcode 1 = start, api_version 2, reply_to, groups)
```

Message set (integer opcodes, so no atom crosses the API; each opcode is a constant of `bees_cfg`):

| Opcode | Direction | Shape | Replaces |
| --- | --- | --- | --- |
| 1 start | app to node | `(1, api_version, reply_to, net, tuning, session, tls, whitelist, pins)` (nine elements; a **cast** payload, not a function: E1070 does not apply) | `trust_boot` + `trust_start`, `net_start` |
| 2 started | node to `reply_to` | `(2, lines)`: `lines` is the **boot banner and summary** as `List[string]` (today's `[trust] mode trust, ...`, `[trust] <note>`) for the app to print | `trust_notes`, the `[bees] mode=beam ...` lines |
| 3 refused | node to `reply_to` | `(3, path, line, text)` | `trust_boot`'s "boot refused" |
| 10 call / 11 cast | app to node | `(10, addr, m, f, arity, args, reply_to, req)` | `trpc_call` / `trpc_cast`; the reply is the existing `{ req, what, value }` message, unchanged |
| 12 reset | app to node | `(12, entry_index, reply_to)`; reply `(13, ok)` | `trust_reset(i)`; **local only, still**: the node actor is the one you hold, no peer can reach it; the forbidden-name guard stays |
| 20 stop | app to node | `(20)` | (new; an orderly teardown) |
| raw writer ops | | `(30..34, ...)` | `trust_raw_*`, for test programs only (kept in a test unit, not the library API) |

BEAM mode is the same family: `(1, ... start)`, replies `(2, lines)`, `(3, ...)`, and `net_send_raw` etc. as test ops. The node actor
**is** the handle (an `actor_ref`); it registers nothing by atom except the name pools (3.1). The banner text and the refusal text are
produced by plain `bees_cfg` functions, so an app can also print them without a node (`bees_cfg@trust_banner(valid) -> List[string]`).
Exit status: the library never stops the process on a bad config; `(:error, ...)` or opcode 3 goes to the app, which prints it and decides.
The old behaviour (`[trust] boot refused: ...`, then `[trust] no actor was started`, `exit=1`) is the **example's** behaviour and is a few lines.

### 5.5 Where the optional `bees.config` text parser lives

* The format is a single Erlang term and a full stop, with lists, tuples, atoms, integers with `_`, strings with four escapes, maps, `%` comments, ASCII only, 64 KiB
  (`bees-config-file.md` section 4; `tools/bees_conf.py` `Reader`, lines 58-183: 125 lines of Python).
* **Silica parser (optional `bees_cfg_text`, plain unit)**: tokenising and building a flat list of `{ path, line, kind, num, text }` entries (a recursive tree type is the SD-36/SD-29 risk, N0b 3.3)
  then mapping entries to the groups of 5.2. I estimate **1200 to 1800 lines** of Silica (the Python reader 125 + the option tables and rules about 700, plus Silica's lack of
  `int_to_string`/`string_to_int` (N0b SR-G; three hand-written `int_text`s exist), no loops, recursion for everything, and no records update). **Can it be written within the compiler's limits?**
  Probably, in pieces under 256 case arms and with units of a few hundred lines each (the compiler hits W2300 quadratic cost and OOM on big units, the memory note "Compiler 999936 facts"), but **I did not write
  or compile a parser**; the risk is real and unmeasured. It runs on a `read_lines` string, so the taint question does not arise (2.2); it is pure.
* **Python at build (recommended first step)**: `tools/bees_conf.py` already parses and validates. A new mode `bees_conf.py emit-silica FILE` writes a small **app-owned plain unit** `app_conf.silica` with
  `fn app_trust() -> {groups...} ...` (record literals of the validated values; the whitelist as a list literal; the PEM bytes as string literals or read at run time by the example). The example then
  calls `bees_cfg@validate_trust(app_conf@...)` as a second check (so the library's validator is exercised) and starts the node. This keeps `bees.config` as the operator's file, keeps the Python oracle as
  the build-time diagnostics ("a bad bees.config is a build failure" stays possible, N0b D-2), and needs no Silica parser. The compatibility path (section 6) is this.
* **Both are source.** The run-time (Silica) route is for an app that must read `bees.config` on the device after deployment.

### 5.6 The example set (documented, not library)

1. `examples/trust_node_build_time`: `bees.config` and the whitelist file converted by `bees_conf.py emit-silica` at build (works on every target, no file system on the device).
2. `examples/trust_node_read_at_boot` (hosted): reads `bees.config`, the whitelist, the pins, the certificates and key with `read_lines` (or a C helper for the mode check), parses with `bees_cfg_text`, validates, starts.
3. `examples/beam_node_*` likewise (cookie file with the 0600 check by the C helper).
4. A board example: configuration embedded in flash (generated unit) for NUCLEO and ESP32-S3 (Mbed TLS bytes).

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
| **L3: compatibility path** | `bees_conf.py emit-silica` writes the app-owned `app_conf` unit; `tools/trial.mk` gains a mode where a leaf supplies an app root; old mode default | one leaf per mode (n3_trust, n2_dist) builds both ways from the **same `bees.config`** and the output goldens are equal; `make integrate` passes in full with the old mode still the default | 4 |
| **L4: bytes** | `bees_beam_set_cookie`, `bees_tls_configure` (OpenSSL memory BIOs), `bees_tls_fingerprint`; the Mbed TLS equivalents written but not built (no board toolchain installs) | the n4 mutual-TLS trial passes with **bytes** (certificates and key as strings read by the example) and with paths; refusals unchanged | 4 to 5 |
| **L5: run-time scalars and the data-driven gate** | N0b phases 3 and 4: `beam_conf`/`bees_trust_conf` values come from the start message into actor state; whitelist and pins as lists consumed at start (per-entry actors from a K pool); permission gate over data | an unmodified binary starts with a changed whitelist (within K) and refuses one that is too long; SD-35 not hit (measured as in 2.1); n3/n4 goldens equal | 10 to 12 |
| **L6: examples and the optional text parser** | `examples/` (5.6), `bees_cfg_text` (Silica) **if the user wants it**; the Python route first | example 2 reads, parses, validates and starts with no generator for the values; diff of dump against the Python parser over all vectors | 3 (examples), 10 to 15 (Silica parser) |
| **L7: retire the stand-in's run-time role** | old generators' run-time constants removed; `bees_trust_gen`/`bees_edge_gen` reduced to templates; node_kit updated; docs rewritten | grep: no `beam_conf@`/`bees_trust_conf@` run-time read left; `make integrate` and `make kit` pass; node_kit's three-node live run reproduces | 4 |
| Total | | | **about 45 to 70 agent-days** (the larger figure includes the Silica text parser) |

### 6.4 Effects on the Linux port, N2T, N5

* **Linux (AArch64 `silica-999936-linux-aarch64`, x86_64 `silica-999944`; D29):** the library model is *easier*: the per-platform native
  directory is selected by the app's Makefile, nothing is pre-linked. New work: the cookie/TLS bytes entry points need the same OpenSSL calls (they are portable); `bees_beam_*` uses CommonCrypto
  today (macOS only), so the cookie's MD5 and random source need the Linux equivalents either way (kernel CSPRNG per D40), independent of this plan. I did not compile on Linux; compiler-version parity (the pin is 999909 on macOS, the Linux binaries are different generations) is *(open)* and affects whether probes `p1a`, `p4` hold there. `read_lines` has per-target inline emitters *(read)*.
* **N5 (windowed multiplexing, B2):** unaffected in design; but its per-connection supervisor and a worker per request add behaviours that
  today would be pasted; as library behaviours they come free with L2. It benefits from the data-driven gate (L5). The `session.*` values are class (a) and already in the groups of 5.2.
* **"N2T":** I found no item of that name in the plans, specs or trials of the repository or in `to-silica` (grep over both trees). If it refers to the BEAM-mode N2c/N2 line (multi-link, reconnect, the soak), the effect is: its trials keep the old mode until L7, and the `redial` values move into the `redial` group at L5. Please say which it is.

## 7. What the probes proved, and could not prove

| Claim | Status | Evidence |
| --- | --- | --- |
| A `dangerous_*` library behaviour can `spawn_dangerous` a carrier and cast to it; a plain-spawned root can start it by reference | **proved** | `p1a`: `launcher` received `(:link_down, ...)` from the carrier |
| A `dangerous_*` library behaviour can `spawn_dangerous` a library **FFI worker with C** (BEES's resolver) and get its answer | **proved** | `p4`: printed `resolved localhost: 127.0.0.1` |
| A plain unit cannot `use` a `dangerous_*` unit (E4021), cannot name `dangerous_actor_ref` (E4026); the root cannot call any function of a `dangerous_*` unit (E4042) | **proved** | `p1a`, `n2`, `n1` |
| A plain unit may spawn actors, start a supervisor, `read_lines`, be called from a `dangerous_*` root | **proved** | `p2`, `p3` |
| A 7-field record with a 1000-entry list of 128-hex fingerprints and a 4.6 KB string is a parameter, a result and a message value | **proved** | `p2` |
| A 14-field nested record, a 64 KiB and a 256 KiB string, 10000 list elements pass in a message | **proved** | `p3` |
| SD-35 costs about 100 times the CPU for a held 1000-entry list | **measured** | `p2`: 2.91 s against 0.03 s |
| `decode` limits cannot be run-time values on 999909 | **proved** | `p5` E2402 |
| Atoms in API messages need the shared atoms unit (SD-3) | **proved (re-proved)** | `p1a`, first run |
| `read_lines` output passes the compiler's taint pass; needs the runtime shim to link | **proved for the checker; link finding new** | `p3` |
| The app's own `bees_atoms` can be the only generated unit for the API | **not proved**; the API with integer opcodes avoids it | design |
| A whole node (`net_launch` and the dial/listen/redial code, or the TRUST node) works as a behaviour in a library unit | **not proved**: the carrier and the resolver worker were; the real node code was not moved (no repo edits allowed) | L2 |
| The TLS worker (`ttls`, `trnd`) spawned from inside a library behaviour | **not proved** (the resolver, the same class, was) | L2 |
| A record state spelled across units for a spawned behaviour | **not probed** (use scalar state `0`) | design |
| OpenSSL memory-BIO loading and the Mbed TLS buffers inside BEES's FFI shapes | **not built** (no C compiled: the rule is no builds except Silica probes asked for; and no Mbed TLS source in the tree) | read only |
| A Silica parser for the `bees.config` text within the compiler's limits | **not attempted**; estimate 1200 to 1800 lines | 5.5 |
| Zeroisation of secrets in Silica | **not provable**; no facility found | 4.4 |
| One 1 MiB string in a message | **not settled** (my builder was quadratic) | `p3` |
| Linux behaviour of any of this | **not tested** | |
| `read_lines` is untainted by the *specification's* wording (vs the checker) | **not found in the spec** | ask Silica |

## 8. Recommended API, risks

**Recommendation.** (1) Build the library as plain `bees_cfg` (types, validate, banners) plus `dangerous_*` **node-actor** units; the app's root is a ten-line `dangerous_<app>`
that spawns the node by reference and casts the start message with integer opcodes. (2) The **compatibility and first example** route is `bees.config` converted at build by the existing Python reader into an app-owned
plain unit (`emit-silica`), validated again by the library at start; the Silica parser comes later and only if wanted. (3) Cookie and TLS material as bytes in the start message, paths kept as a second form. (4) Config groups of at most 5
fields, the whitelist and pins consumed at start, never held in state. (5) The app's build supplies `bees_atoms`, `bees_build` and the generated per-peer/MFA units from BEES's Python source tool and templates; BEES ships no binary.

**Risks**

1. **The node code has not been run as library behaviours** (section 7): the probes prove the *mechanism*, not the 1600 lines of `dangerous_beam_net`/`bees_node_edge.part`. The unproven corner is the SD-39 family
   (`dangerous_actor_ref` in state, whole-state copies): moving the start-up into a behaviour adds state fields. Mitigation: L2 is a copy beside the old path, with the n2/n3 goldens as the gate and the SD-35/39 memory measurement of the rate trials.
2. **Taint and secrets.** `read_lines` is untainted for the checker but the spec's statement is missing; a key held in a Silica string cannot be wiped. The no-retention/no-logging promise is weaker than "zeroised".
3. **Compile-time facts leak into the app's build** (atoms, `bees_build`, the generated decode sites). The "library" is therefore not "include and call"; it is "include, run BEES's generator, call". A mismatch (a stale `bees_atoms` after an API change) shows as "no case arm matched" at **run time**, not at compile time (SD-3, reproduced). Mitigation: integer opcodes in the API, `api_version` check in the start message, and the checker (`bees_config check`) in the app's Makefile fragment.
4. **E1070 and no aliases** make the record shapes long and the signatures brittle; groups of at most 5 fields and a `bees_cfg.shapes` text help but every app spells them.
5. **The Silica parser is large and its checker cost is unmeasured** (SD-29/SD-36 class). It is optional by design.
6. **Silica-side gaps that BEES cannot close** (N0b SR-A to SR-H, updated): run-time decode limits (SR-D, proved E2402), the runtime shim for `read_lines`, `int_to_string`/`string_to_int`, file stat and typed read errors, a documented taint status of `read_lines`, zeroisation.
7. **Churn:** `dangerous_beam_net`, `dangerous_bees_net`, the generators and the trial Makefiles are being edited by other work now; L2 and later phases must wait for that to land.

## 9. Decisions needed from the user

1. **Approve "node actors by message"** as the API shape (the only shape the rules allow without pasting). Equivalent alternative: keep a one-line `.part`-style template the app pastes. I recommend messages.
2. **Integer opcodes in the API messages** (no atoms cross the boundary), or atoms via an API manifest merged into the app's `bees_atoms`?
3. **The first example reads `bees.config` at build time through the Python reader** (`emit-silica`), with the Silica run-time parser deferred. Yes, or do you want the Silica parser first (about 10 to 15 days, unmeasured risk)?
4. **Validation messages:** keep `bees.config:LINE: PATH: MESSAGE` byte for byte when a line is known, `PATH: MESSAGE` otherwise? Does the 0600 and "does not exist" wording stay in the **examples**, or must the library return them (it cannot: it sees no files)?
5. **Cookie and key as bytes:** OK that the library guarantees *no retention and no logging* but not memory scrubbing in Silica (Silica has no facility)? If scrubbing matters, it is a Silica request.
6. **Fingerprints:** the whitelist record carries the hex fingerprint (computed by the example, by Python at build, or by a C helper), because Silica has no SHA-512. Accept, or should the library take certificate PEMs for whitelist entries and fingerprint them through a C helper?
7. **`plaintext_test_only` and the two link kinds:** two units (the app chooses by `silica.config`), not a run-time boolean.
8. **Pool sizes** (`whitelist_slots_max`, `pinned_servers_max`) stated by the app in `bees_build`: OK as new build facts?
9. **Ask Silica for:** run-time decode limits (SR-D), the `read_lines` runtime shim in the default link line, a stated taint status of `read_lines`, `int_to_string`/`string_to_int`, a type alias or a way to name a record shape (the API spells every shape), zeroisation. May these be filed?
10. **"N2T":** what does it name?
11. **Sequencing:** L1 and L2 start only after the multi-link/reconnect/`make integrate` work now in the tree has landed and been committed?
