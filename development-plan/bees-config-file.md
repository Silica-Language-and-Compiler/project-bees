# The BEES configuration file: `bees.config`

**Status: DESIGN, 2026-11-06 (roadmap D37), revised the same day for six user rulings (R1 to R6, listed in section 10). Update 2026-11-10 (N0.2, N1): ONE reader implements this document, `tools/bees_conf.py` (the beam half of N2 and the trust half of N3 merged; `tools/bees_config_beam.py` and `tools/bees_config_trust.py` are now only generators that call it). It is a BUILD-TIME STAND-IN: Silica cannot read a file at boot, so the file (and the whitelist, pin file, certificates and the cookie file's checks) is read when the program is built and the verdict is compiled in; the design's boot-time reading is NOT built. Section 11 says which options a boot-time reader could read with no change to generated code, which ones today's Silica fixes at build time whatever reads the file, and proposes a native-edge file reader. What was the 4096-byte "build limit until N1" is gone: frame caps up to BEAM's 4294967295 are accepted and become the generated limits (section 5.4, mvp.md N1).** Milestone N0 ([mvp.md](mvp.md) section 5) builds it. Before 2026-11-10 what existed was only the build-time
manifest (`node`, `creation`, `timing`, `peer`, `remote`, `local`, `message` lines; compiler guide B1a, N1) and the M3 to M5
node layer, which takes its timing and peer from that manifest. Companion documents: [roadmap.md](roadmap.md) (D26, D36,
D37, D38), [inter-nodal-modes.md](inter-nodal-modes.md) (the two modes), [mvp.md](mvp.md) (milestones N0 to N5),
[gap-ledger.md](gap-ledger.md), the compiler guide ([../contract/so-you-want-to-write-a-compiler.md](../contract/so-you-want-to-write-a-compiler.md), section B1b).

## 1. What it is, and what it replaces

`bees.config` is a **BEES file**: BEES's own configuration, for every program that uses BEES's inter-node layer, whatever
language compiled the program (D26, D37). It chooses the **mode** of the node (BEAM mode or TRUST/SEMP mode, which are two
separate implementations, D36) and carries every option of both.

- **SEMP has no command-line options.** Its options are keys of its application environment, written in a `sys.config`
  (BEAM_SEMP README, "Example TRUST configuration"; the multiplexing design, "System Configurations" and "Config Validation
  & Bounds"; defaults in `include/semp.hrl` and in the `application:get_env` calls of `src/trust/*.erl` and
  `src/semp_whitelist.erl`). BEES likewise has **no command-line options**: the program's startup (which a compiler writes,
  compiler guide N2.2) passes at most one path, the default being `bees.config` in the working directory.
- **`bees.config` replaces `sys.config` as the place for BEES and TRUST options.** An earlier version of
  [inter-nodal-modes.md](inter-nodal-modes.md) section 1.3 and decision D26 said "`sys.config`". They are corrected: BEES reads
  no `sys.config`, no application environment and no `kernel` entries. Section 7 is the rule for moving a SEMP `sys.config`
  over.
- **Format.** Erlang term text, as D26 decided: one term followed by a full stop, read by **BEES's own small reader**
  (written in Silica, so configuration is available before any compiled program code runs and depends on no converted OTP
  code). The reader accepts a deliberately small subset (section 4).
- **Targets without a file system** (the ESP32-S3, D26, D29): the language compiler compiles `bees.config` and every file it
  names (certificates, keys, whitelist, pins, cookie) into the application as a generated Silica module, and the reader
  reads that module through the same interface it uses for files. The interface is "text of a logical file name"; the
  hosted source is the file system and the embedded source is the generated module. Its exact shape (a contract item,
  D26) is not designed yet; the module's provisional name is `bees_conf_embedded`. N0 builds the file source and the
  interface; the embedded source is specified here and built when a target needs it.

## 2. The file, the manifest and the build

The manifest (the `<unit>.wire` lines, compiler guide B1a N1) **stays the build-time schema**. It decides what code is
generated: which atoms exist (D16: a node name must be an atom the program holds), which message types cross, which names are
`remote` and `local`. `bees.config` decides **values at boot** that change no generated code.

| Manifest line (build time) | What stays there | What `bees.config` may do at boot |
| --- | --- | --- |
| `node <name>` | The name (it puts the atom into `bees_atoms`). | `node.name` may repeat it; any other value is a **boot error** (the atom would not exist, D16). |
| `creation <n>` | The compiled default (1 if absent). | `node.creation` overrides it; in BEAM mode `epmd` takes the creation EPMD assigns, as OTP does. |
| `timing <open_ms> <io_ms> <tick_ms>` | The compiled defaults (10000, 60000, 15000). | `beam.net_ticktime_s` and `beam.open_timeout_ms` override them (section 5.2). The `tick_ms 0` test setting is manifest-only. |
| `peer <name> <host> <port> <listen\|dial>` | Which peer **names** exist. **Every peer line is a link (N2b, BEAM mode):** a `dial` peer is dialed, and all `listen` peers share the node's one listener (`beam.listen_port`, else the first listen peer's port) and start when their handshake names them. (The auth-none M3 node, `dangerous_bees_net`, still uses the first line only.) | `beam.peers` may give each listed name its address and role. A name not in the manifest is a **boot error**. |
| `remote <name> @ <peer> cast <type>`, `local <name> cast <type>` | All of it: names and types. | Nothing. They exist only for BEAM mode (the names are `REG_SEND` targets); a manifest that has them and a `bees.config` with `mode trust` is a **boot error**. |
| `message <name> <type>` | All of it. | Nothing. |

**Precedence, for any value both can express: `bees.config` over the manifest over BEES's built-in default.** A missing
file is allowed only when the manifest declares no `remote`, `local` or `peer` line and the built-in defaults are wanted
(mode `trust`, standalone, section 3.1); otherwise the node refuses to start and says which line needs a file.

**Where a compiler author puts what.** Names, types and atoms: manifest. Anything an operator would change between a test
rig and a deployment (mode, addresses, ports, cookie file, certificates, whitelist, limits, timeouts): `bees.config`. The
compiler never needs to edit `bees.config`; it only has to ship it, or embed it where there is no file system.

## 3. Structure

```erlang
[
  {mode, trust},                 %% beam | trust (one mode per node, section 3.1)
  {node, [ ... ]},               %% section 5.1
  {beam, [ ... ]},               %% section 5.2, validated always, used when mode is beam
  {trust, [ ... ]}               %% section 5.3, validated always, used when mode is trust
]
```

Every top-level key is optional except as noted in the tables. Both the `beam` and the `trust` section are **validated whichever
mode is selected** (syntax, types, bounds, unknown keys), so that a file written for one mode cannot hide a mistake until
the other is chosen; only the selected section is acted on.

### 3.1 The `mode` choice

- **One mode per node, for now.** BEAM mode and TRUST mode are two separate implementations (D36) and a node runs exactly
  one. `{mode, beam}` or `{mode, trust}`; any other value, including the list form `[beam, trust]`, is a boot error. The
  list form is **reserved**: running both on one node (two listeners, separate guards, one module table) is possible in
  principle and is deliberately **not** designed until N5 is closed and a use for it exists (D37). This amends D7, which
  said both may run at once.
- **The default is `trust`. Ruled by the user, 2026-11-06 (R3: "Default to trust"); not merely chosen.** Reasons: it is the secure-by-default mode (D7; parallel-tracks "Opting down to
  BEAM-equivalent security"); BEAM mode is a downgrade that must be written down explicitly; with no `bees.config` a node is
  then a TRUST **standalone** node (no whitelist, so it accepts no inbound connection, and it can still act as a client), which exposes nothing. A
  program that needs BEAM mode (every M3 to M5 demo does) needs a file that says `{mode, beam}`.
- BEAM mode prints a downgrade banner at boot and periodically, and tags log lines `mode=beam` (inter-nodal-modes section 2).
- **Since N4.1 (2026-11-12)** a `trust` node without `{plaintext_test_only, true}` speaks TRUST over mutual TLS 1.3 (the engine over
  the programmer-installed OpenSSL, D40) and needs `tls_opts` with `certfile` and `keyfile` (**`cacertfile` is optional since D43**: see section 5.3 `tls_opts`); every pinned server's
  certificate must be readable (it is the pin). With `{plaintext_test_only, true}` it binds loopback only and prints the test-only
  banner, as before. (Until 2026-11-12 a `trust` node without it failed at boot with "TRUST's TLS is not built".)

## 4. The reader and the validation rules

**Grammar (the whole of it).** A file is one term and a full stop. Terms: lists, tuples, atoms (lowercase start, letters,
digits, `_`, `@`; or single-quoted), integers (decimal, with `_` between digits allowed, as in `600_000`), double-quoted strings
(ASCII 32 to 126 plus the escapes `\n`, `\t`, `\\`, `\"`), maps `#{K => V, ...}` (SEMP's `session` is a map and its whitelist
file is a map, so maps are needed). Comments run from `%` to the end of the line. **Not accepted:** floats, binaries, funs,
variables, macros, records, includes, non-ASCII bytes, a second term. File size at most 64 KiB (BEES's bound). The
whitelist and the pin file use the same reader.

**Validation, at boot, before any actor starts, fail-fast, no clamping** (the multiplexing design, "Validation Algorithm";
inter-nodal-modes section 1.3). Any violation aborts the boot with a non-zero exit and one line
`bees.config:LINE: PATH: MESSAGE` (for example `bees.config:41: trust.session.idle_ms: 70000 is above max_age_ms 60000`). Nothing is
repaired, rounded or defaulted around a bad value. The rules:

1. **Syntax.** The grammar above; a second term or trailing text is an error.
2. **Unknown key** at any level is an error. A SEMP key that BEES renamed or dropped gets a hint (section 7).
3. **Duplicate key** at one level is an error.
4. **Type** of every value as in the tables (integer, string, atom from a closed set, list, map).
5. **Bounds** of every integer as in the tables; an out-of-range value is an error, never clamped. A bound marked **B** is
   BEES's own (SEMP states none); a bound marked **S** is SEMP's.
6. **Cross-field rules:** `session.idle_ms =< session.max_age_ms`; `args_len_max =< frame_size_max`; `dns_ns_timeout_ms =<
   dns_total_timeout_ms`; `trust.port` differs from `beam.listen_port` when both are non-zero; `listen_port 0` needs `epmd
   external`; `beam.epmd none` needs every peer to carry a port and `listen_port` non-zero; `frame_size_max` and `args_len_max` are checked against BEAM's limits and against what the build implements (section 5.4).
7. **Required values by mode:** both modes: **`listen_address` in the section of the selected mode** (R6: BEES's code and the
   reader have **no built-in default** for it; a missing one is a validation error, in `beam` and in `trust` alike; in the section
   of the mode that is not selected it is validated if present and not required, since nothing will listen on it; a node with
   **no file at all** is the client-only TRUST standalone node of section 2, which listens on nothing); `beam`: `cookie_file`
   when `auth` is `cookie`; `trust`: `tls_opts` with all three keys unless
   `plaintext_test_only`; `server_pins_file` is never required (without it a client dials nobody, section 5.3).
8. **Files** named by the file exist and are readable at boot (certificate, key, CA, whitelist, pins, cookie). **Whitelist, ruled 2026-11-06 (R2: "SEMP is not to run silently if there is not a whitelist file"): in `trust` mode a
   `whitelist_file` that is configured and missing, unreadable (permissions) or unparseable is always a loud failure: a boot
   error with a one-line message that names the file and the cause, never a silent standalone run.** (SEMP's reference
   silently continues as standalone; BEES does not; section 8.) An **unset** `whitelist_file` is the explicit standalone node:
   no inbound connection, client only, and it is **not silent either**: boot prints a banner "TRUST standalone: no whitelist
   file configured, no inbound connections accepted". The same rule covers `whitelist_cert_dir`, `server_pins_file` and every
   other configured file (rule 8 applies to all of them). A certificate that a *whitelist entry* names and that is missing is logged and skipped, as SEMP does. Key
   and cookie files that are readable by group or others are an error on hosted targets (OTP refuses a loose
   `.erlang.cookie` for the same reason).
9. **Not built yet** is an error, not a downgrade: `transport tls` before the TLS engine exists; a `plaintext_test_only`
   value on a non-loopback address; (`trust` without plaintext before N4: built since N4.1, 2026-11-12); an address the language's carrier cannot bind or dial
   (N1: it binds 127.0.0.1 or every IPv4 interface, written `"0.0.0.0"`, and dials IPv4 literals; a dial host that is a name is
   resolved on every dial by BEES's ONE resolver edge (D42, spikes/S14; the answer is screened: reserved, this-network, broadcast
   and multicast addresses are never dialled, and a loopback-only setting refuses a name that resolves outside `127.0.0.0/8`); IPv6 literals in
   `listen_address` or a peer's `host` are refused here as "not built yet" with the SR-2 reason, and binding one specific address is a request to Silica,
   silica-defects.md SR-1 and SR-2). **Stated goal (D42): resolution is to move fully to Silica**, replacing the system resolver once the
   language offers IPv6 literal dialing (SR-2) and a resolver-capable transport. **Changed 2026-11-16 (N2b):** a peer whose host is a name and whose port is `epmd` is built: the name is resolved first
   by the same resolver edge, then the peer host's EPMD is dialed at the IPv4 literal (trial n2_live, bees_dials). **Changed 2026-11-10 (N1):** a `frame_size_max` or `args_len_max` above 4096 is no longer "not built yet";
   every value up to BEAM's 4294967295 is built (section 5.4). Nothing is ever clamped.
   **Test settings (N1):** `beam.auth none` and `trust.plaintext_test_only` give no authentication and no encryption, so a
   node with either listens and dials loopback addresses only (`127.0.0.0/8`, `::1`, `localhost`); any other address is refused
   at build (the stand-in's boot) with `... is not a loopback address, and auth none is a loopback-only test setting ...`. A
   node built from the manifest alone (no `bees.config`, M3's node) is auth none and follows the same rule.
10. **The node name** equals the manifest's `node` line (section 2).
11. On success BEES logs a **sanitized summary** of the effective configuration (every value except file contents, cookies,
    tokens and key paths' contents). Secrets are never printed.
12. **No live reload.** Changes apply at restart; connections that exist keep the values they were created with.

## 5. The options

Column "source" cites SEMP: **R** README (`/Users/yenrab/BEAM_SEMP/README.md`), **M** the multiplexing and backpressure design
doc, **H** `include/semp.hrl`, or a file and line of `src/`. "BEES" means SEMP has nothing of the kind and BEES adds it.

### 5.1 `node`

| Option | Mode | Type | Default | Bounds | Source |
| --- | --- | --- | --- | --- | --- |
| `name` | both | string, ASCII letters, digits, `_ . @ -`, at most 255 bytes | the manifest's `node` | equals the manifest's `node` | manifest (compiler guide N1); SEMP has none (an Erlang node name) |
| `creation` | both | integer, or the atom `epmd` (`beam` only) | the manifest's `creation`, else 1 | 0 to 4294967295 (S: wire field) | manifest; OTP assigns it through EPMD |

### 5.2 `beam` (BEAM mode, the OTP distribution protocol; D36)

These are the `bees_dist` options of the earlier inter-nodal-modes section 1.3, plus what the cookie handshake, EPMD, ticks
and the transport addresses need. The cookie and EPMD parts are built (N2); non-loopback addresses are built as far as the
language's carrier allows (N1: rule 9). The values are read by `tools/bees_conf.py` at build time (section 11).

| Option | Type | Default | Bounds | Notes |
| --- | --- | --- | --- | --- |
| `transport` | `tcp` or `tls` | `tls` (D25) | closed set | `tls` is the `inet_tls_dist`-compatible profile (inter-nodal-modes 4.5) and does not exist until the TLS engine does (N4, user approval), so **until then a beam node must write `{transport, tcp}`**, and gets the downgrade banner. |
| `auth` | `cookie` or `none` | `cookie` | closed set | `none` is the M3 to M5 behaviour (no digest): **a loopback-only TEST setting** (banner), kept now so the M3 to M5 trials keep their goldens when they move to a file. **Ruled 2026-11-06 (R4):** when cookies exist (N2) those trials move to `cookie`; `none` then stays only for tests that need it. Erlang's cookie digest (MD5, random challenge) is N2. |
| `cookie_file` | string (path) | none; **required** when `auth` is `cookie` | file, 1 to 255 bytes of content, not group/world readable | never read from `~/.erlang.cookie` implicitly (inter-nodal-modes 4.3); never logged. |
| `listen_address` | string: IPv4 or IPv6 literal, or a host name | **none: required** (R6) | an IPv4 literal, or `localhost`/a name the reader accepts for the carrier's two listen forms (the boot-time match against an interface address is not built); an IPv6 literal is refused as "not built yet" with the SR-2 reason (D42) | BEES. **No built-in default, in code or reader** (ruled 2026-11-06): a missing one fails validation. The trials write `"127.0.0.1"` in their configs. |
| `listen_port` | integer | 0 | 0 to 65535 (B) | 0 = ephemeral, registered with EPMD (as OTP does). |
| `epmd` | `external` or `none` | `external` | closed set | `external`: register (ALIVE2) with and look peers up (PORT_PLEASE2) in an EPMD; `none`: fixed ports, as M3 to M5. A BEES EPMD server for hosts with no Erlang (inter-nodal-modes 4.3) is B3, not N2. |
| `epmd_port` | integer | 4369 (OTP's) | 1 to 65535 (B) | the port of the EPMD on this host and on peers. |
| `net_ticktime_s` | integer | 60 (OTP's `net_ticktime`) | 4 to 3600 (B) | BEES sends a tick when idle for `net_ticktime_s / 4` and treats `net_ticktime_s` of silence as a lost peer; the manifest's `timing` 15000/60000 is the same pair. |
| `open_timeout_ms` | integer | the manifest's `open_ms` (10000) | 1 to 60000 (manifest rule) | bounds listening, accepting, connecting, the handshake. |
| `peers` | list of `{"name@host", [{host, S}, {port, N or epmd}, {role, dial or listen}]}` | the manifest's `peer` lines | each name is listed in the manifest (D16); `port` 1 to 65535 or `epmd` | `epmd` as a port means look it up. Host is an IPv4 literal or a name resolved through the system resolver on every dial, including each redial, by the one resolver edge (D42, spikes/S14: several addresses are tried one per dial attempt); an IPv6 literal is refused with the SR-2 reason. **Stated goal (D42): the system resolver is to be replaced by a Silica implementation.** |
| `spawn` | `none`, `allowlist`, `any` | `none` | closed set | remote spawn, inter-nodal-modes 4.5; takes effect at L3 (B4, after 1.0); validated now. |
| `spawn_allowlist` | list of `{Module, Function, Arity}` atoms and integer | `[]` | at most 1024 entries (B) | only with `spawn allowlist`. |
| `frame_size_max` | integer (bytes) | 4294967295, BEAM's packet limit (E; R1) | 512 to 4294967295 (E) | Ruled 2026-11-06 (R1): the frame cap is **the same as BEAM's**. The cap is on the whole distribution packet (the `112` byte, the control message and the payload). **Built 2026-11-10 (N1):** every value up to 4294967295 is built; it is the `wireframe@unframe` cap and the send cap of the proxies (run time) and the `max_bytes` and `max_length` of the generated `decode` calls (build time, section 11); nothing is allocated for the cap itself. Trials that need N2's old cap write `{frame_size_max, 4096}`. |
| `redial` | `true` or `false` | **none: required** on a node with a dial-role peer | boolean | **N2c (2026-11-17), user ruling 2026-11-17: "The dialer is not to have a default. It has to be explicitly stated as on or off."** A missing value is a boot error naming the option (write `{redial, true}` or `{redial, false}`); a non-boolean is an error. `true`: a dial-role peer whose link goes down (refused, dropped, lost, or never connected) is dialed again with a NEW carrier, writer, connection actor and proxies; every attempt is an audit line (`link lost; redial scheduled, delay in ms` and `redial attempt`). `false`: a lost link stays down, silently. A node with **no** dial-role peer (listen only) **refuses** the option and the two below as meaningless (the stricter rule: a stray option on a listening node is more likely a copied file or a peer meant to dial than a wish, and the message says to remove it). A host name that cannot be resolved at all is not retried (no carrier is opened, so no link is lost). The manifest-only M3 node (no bees.config) states it as a manifest line, `redial off` or `redial <initial_ms> <max_ms>`; a program with a bees.config takes it from the file only (a manifest line is then refused). |
| `redial_initial_ms` | integer (ms) | **none: required when `redial` is true** | 10 to 60000 | the delay before the first redial after a link was lost; it doubles after each failed attempt, at most `redial_max_ms`. Refused when `redial` is false (no delay to set), as the user dislikes silent defaults here. |
| `redial_max_ms` | integer (ms) | **none: required when `redial` is true** | 10 to 600000, at least `redial_initial_ms` | the largest delay between two attempts. A link that stays up for `redial_max_ms` counts as stable: the next loss starts again at `redial_initial_ms`. Refused when `redial` is false. |

There is **no `args_len_max` in `beam`**: BEAM has no separate argument cap, a message is bounded by the packet.

**From the earlier text:** `{enabled, ...}` is gone (the top-level `mode` replaces it); `{sname, "orders"}` is `node.name`;
`cookie_file`, `transport`, `spawn`, `spawn_allowlist` are unchanged.

### 5.3 `trust` (TRUST/SEMP mode; D36)

Every SEMP option appears here with SEMP's name unless the sources disagree on the name (then the code's name is kept and
the others are listed in section 7). **Defaults and bounds carry a source (E: BEAM's own limit, section 5.4; S: SEMP; B: BEES);** where SEMP has no bound the bound is BEES's (B)
and comes from inter-nodal-modes 3.8 where that table already has one.

| Option | Type | Default | Bounds | SEMP source and notes |
| --- | --- | --- | --- | --- |
| `port` | integer | 6469 | 1 to 65535 (B) | R example `6464`; H `DEFAULT_PORT 6469`; `trust_listener.erl:96` reads it and **errors if unset**. Sources disagree (section 8). |
| `listen_address` | string | **none: required** (R6) | literal or name (IPv4 only: an IPv6 literal is refused, SR-2; D42; stated goal: resolution moves to Silica) | BEES. **No built-in default** (ruled 2026-11-06). SEMP's `ssl:listen` binds every interface and needs no address; BEES requires an explicit one. The trial configs write `"127.0.0.1"`. |
| `tls_opts` | list of `{certfile, S}`, `{keyfile, S}` and optionally `{cacertfile, S}` | none | those three keys only; `certfile` and `keyfile` required unless `plaintext_test_only`, `cacertfile` **optional (D43)** | R example; `trust_listener.erl:148`. SEMP passes **any** `ssl` option through; BEES accepts only these three (the profile fixes everything else). **D43 (2026-11-16): peer trust is the SHA-512 pin of the peer certificate's DER (D11) plus the whitelist.** With **no `cacertfile`** (the default) no chain is verified against any CA: a self-signed or any-issuer certificate (and one outside its dates) is accepted by the handshake and the pin or the whitelist decides; it must still be presented and be Ed25519 or ECDSA P-256. **With a `cacertfile`** the chain is also verified against it, and the pin or whitelist still applies (the CA path of N4.1, kept). The boot summary says which. |
| `client_tls_opts` | same | the value of `tls_opts` | same keys | `trpc.erl:480` (SEMP default `[]`; BEES defaults to the node's own pair so one node can be both). |
| `whitelist_file` | string (path) | unset (explicit, bannered standalone) | readable, parseable file; **configured and missing or unreadable is a boot error** (R2) | R; `semp_whitelist.erl:275`. SEMP resolves it inside the host app's `priv/` and **silently** runs standalone when it is missing; BEES resolves it relative to the directory of `bees.config` and never runs silently without it (validation rule 8). |
| `whitelist_cert_dir` | string (path) | `"certs"` | existing directory | BEES. SEMP reads certificates from `priv/certs/` of the host app (`semp_whitelist.erl:425`). |
| `whitelist_default_spec` | `none`, `any`, or a list `[{Module, any}` or `{Module, [{Fun, Arity}]}]` | `none` | closed forms | R example `none`; `semp_whitelist.erl:193` default `[]` (which normalizes to "nothing permitted", the same effect); `beam_semp.app.src` `[]`. |
| `classical_allowed_certs` | list of strings (certificate names) | `[]` | each names a whitelist entry whose certificate is readable; needs `whitelist_file` and TLS (a boot error otherwise) | BEES, **D44 (2026-11-16)**. SEMP's whitelist file is unchanged; the marker is here. Only a peer whose certificate is one of these entries may negotiate classical X25519 (as a NUCLEO-L476RG or ESP32-S3 peer must, D41); every other peer must negotiate X25519MLKEM768. When the list is empty the engine offers X25519MLKEM768 only and a classical-only peer is refused inside the handshake; when it is not, the engine also offers X25519 and the TLS link refuses, right after the handshake and before any TRUST byte is read, a classical connection whose peer is not marked (audit `tls_group_refused`). The check applies in both roles: a node dialing a server must have that server's certificate in its whitelist, marked, to accept a classical server. |
| `whitelist_autoload` | boolean | `false` | closed set | `semp_whitelist.erl:190` reads it from the `semp` environment with default `false`; `beam_semp.app.src` sets `true`. Sources disagree (section 8). BEES takes the safe value. |
| `server_pins_file` | string (path) | unset | readable file | BEES (inter-nodal-modes 3.3; new relative to SEMP). Unset = no server is pinned = every `trpc` call returns `server_not_pinned`; a node that only serves needs none. |
| `call_timeout_ms` | integer | 5000 | 1 to 600000 (B, inter-nodal-modes 3.8) | R; `trust_conn.erl:244`. |
| `suspicion_limit` | integer | 3 | 0 to 1000 (B) | H; `trust_suspicion.erl:180` (read from `semp`, not `trust`). A fingerprint is quarantined when its count **exceeds** the limit. |
| `token_bytes` | integer | 48 | 32 to 64 (S: comment in `trust_token.erl:56`) | `trust_token.erl:56`. |
| `token_ttl_sec` | integer | 300 | 10 to 3600 (B, inter-nodal-modes 3.8) | `trust_token.erl:79` (default 120), H `1200`, R example `token_ttl_ms 300000` (not read by the code). Unified to 300 (inter-nodal-modes 3.12 item 5). |
| `dns_ns_timeout_ms` | integer | 2000 | 100 to 30000 (B) | R "2s per NS"; not configurable in SEMP's code (`semp_dns.erl` uses `inet:getaddrs` defaults). |
| `dns_total_timeout_ms` | integer | 5000 | 100 to 60000 (B) | R "total budget ~5s"; same. |
| `connect_timeout_ms` | integer | 3000 | 100 to 60000 (B) | R "3s per endpoint"; the code uses the call's timeout (`trpc.erl:227`) and no stagger. |
| `connect_stagger_ms` | integer | 250 | 0 to 5000 (B) | R "~250ms stagger"; not in the code. |
| `client_handshake_timeout` | integer (ms) | 5000 | 1000 to 30000 (B, inter-nodal-modes 3.8) | `trust_conn.erl:50`. The name says "client" but the code applies it to the **server's** `ssl:handshake`; BEES applies it to both ends. |
| `first_frame_timeout_ms` | integer | 2000 | 100 to 10000 (B, inter-nodal-modes 3.8) | R "First frame after TLS: 2s"; `trust_conn.erl:166`. |
| `frame_size_max` | integer (bytes) | 4294967295, BEAM's packet limit (E; R1) | 512 to 4294967295 (E) | **Ruled 2026-11-06 (R1): "The frame and argument caps are to be the same as BEAM."** Not SEMP's 8 MiB (R and `semp_util.erl:recv_frame`), not M's 1 MiB default and 64 KiB lower bound. Built up to 4294967295 (N1, as `beam.frame_size_max`): the `unframe` cap at run time, and with `args_len_max` and `term_depth_max` the generated `decode` limits of the MFA table (`tools/bees_trust_gen.py mfa --config`). A smaller value is the operator's choice, never a default. |
| `args_len_max` | integer (bytes) | equal to `frame_size_max` (E; R1) | 0 to `frame_size_max` | **Ruled (R1).** BEAM has no separate argument cap (a term is bounded by the packet), so the default is the frame cap. SEMP: M 64 KiB, R 4 MiB. Same transitional rule. **Open: under discussion with the user:** how TRUST's `args` (and the result `value`), which SEMP carries as any-type terms, are handled; this option bounds their encoded size either way. |
| `term_depth_max` | integer | 32 | 1 to 128 (B, inter-nodal-modes 3.8) | BEES (`bees_ingress` limit). **BEAM has no nesting limit** (section 5.4); the R1 ruling names the frame and argument caps, so this stays BEES's own guard. Whether it should also follow BEAM is a question for the user. |
| `session` | map of five keys | all five defaults below | below | M "Session Map Keys"; sys.config example in M. Effective from N5; before it the node serves one request per connection and prints a notice when the values differ from `max_inflight 1, max_calls 1`. |
| `session.max_inflight` | integer | 8 | 1 to 64 (S: M) | |
| `session.max_age_ms` | integer | 60000 | 1000 to 3600000 (S: M) | |
| `session.idle_ms` | integer | 5000 | 100 to 600000, and `=< max_age_ms` (S: M) | |
| `session.max_calls` | integer | 100 | 1 to 100000 (S: M) | |
| `session.drain_ms` | integer | 1000 | 0 to 60000 (S: M); effective drain is `min(drain_ms, idle_ms)` | M names it `drain_ms` (renamed from `drain_ms_default`, decision-log item 9). **The "drain" option the user's ruling mentions means `session.drain_ms`** (confirmed by the parent, 2026-11-06); no other drain key exists in SEMP. |
| `acceptors` | integer | `2 * carrier threads` of the program | 1 to 1024 (B) | M "Optional Listener/Global Controls" (`2 * schedulers_online()`). The reference listener has one accept loop; the pool exists only in the design doc. |
| `session_slots_max` | integer | unset | 1 to 1000000 (B) | M; "if set, a global admission gate". |
| `plaintext_test_only` | boolean | `false` | `true` only with a loopback `listen_address` | BEES, for N3 (TRUST logic before the TLS engine). It also enables the **test-only stand-in for the peer's certificate fingerprint**: a 64-byte value the test supplies when it connects, accepted by the user on 2026-11-06 (R5) **until TLS exists**. It is marked test-only in code comments, in these documents and in a boot banner (`TEST ONLY: plaintext transport, peer identity is a test-supplied stand-in for the certificate fingerprint`). After N4 the option stays, for tests only. |

**SEMP options BEES does not carry, and why:** `rpc_api` (`trpc_loader.erl:27`: modules to load at boot; nothing loads at run
time, the module table is built at build time); `host_app` (`semp_whitelist.erl:574`: where `priv/` is; paths are relative to
`bees.config`); `unsafe`, `unsafe_cookie`, `alpn` (fields of the `cfg` record in `semp.hrl`, read by no code; the ALPN is
fixed at `trust/1`); `token_ttl_ms` (renamed); `kernel` entries `dist_auto_connect` and `logger_level` (BEES has no `kernel`
application; logging options are not designed yet, open).

### 5.4 BEAM's limits, and where BEES stands (ruling R1, 2026-11-06)

**Ruling (R1): "The frame and argument caps are to be the same as BEAM."** In both modes the configurable caps default to, and are
bounded by, what BEAM/Erlang distribution allows. This table was established on 2026-11-06 against the `erl` found at
`/usr/local/erlang/bin/erl`. **Caveat on the version:** `erlang:system_info(otp_release)` answers `"28"`, but the installed `lib/`
directories are `erts-15.0`, `kernel-10.0`, `stdlib-6.0` and `system_info(version)` is `"15.0"`, which are the numbers OTP 27.0 shipped
(a Homebrew OTP 27.3.3 is also installed and was not used). So the figures are those of this binary, called "OTP 28" by itself; they
were not compared with a second build. **There are no `doc/` files in the installation**; "docs" below means source and runs.
Verification marks: **[run]** a small `erl -noshell -eval` experiment on 2026-11-06; **[src]** read in the installed `kernel-10.0/src`;
**argued, not checked** means from the ETF specification or knowledge of the emulator and not confirmed here.

| Limit | BEAM's | How verified | BEES (updated 2026-11-10 for N1; was: 4096, depth 16, 256 elements, 1024-byte binaries) |
| --- | --- | --- | --- |
| Distribution packet (frame): length prefix | **4 bytes, up to 4294967295** (4 GiB minus 1), no fragmentation needed; BEES offers neither fragments nor the distribution header | the `{packet, 4}` option of the connection after the handshake: **[src]** `inet_tcp_dist.erl` lines 112 and 118 (the handshake itself uses `{packet, 2}`, lines 141 and 493, so a handshake message is at most 65535 bytes). The 4 GiB figure is the width of a 4-byte prefix: **argued, not checked** (no 4 GiB packet was sent) | **configurable up to 4294967295** (`frame_size_max`); 64 KiB, 1 MiB and 8 MiB frames round-trip between two processes (`trials/n1_frames`); the cap is checked from the 4-byte length before a byte of the frame is stored (`trials/n1_limits`). Memory: a frame is held whole while it is assembled, about 75 times its size at the peak for 8 MiB (SD-35; mvp.md N1) |
| Send-side buffering | 1,048,576 bytes busy limit (`dist_buf_busy_limit`), back-pressure on the sender, **not a message-size cap** | **[run]** `erlang:system_info(dist_buf_busy_limit)` | none |
| Atom length | **255 characters** (a UTF-8 atom may take up to 1020 bytes; the length byte of SMALL_ATOM_UTF8 is at most 255 bytes) | **[run]** `list_to_atom` of 255 characters works, of 256 raises; `ATOM_UTF8_EXT` of 255 two-byte characters (510 bytes) accepted, of 256 characters refused; `ATOM_EXT` of 256 refused | 255 **bytes**, ASCII only: equal to BEAM's for ASCII text, below it for non-ASCII |
| Tuple arity | **16777215** (2^24 minus 1) | **[run]** `make_tuple(16777215, 0)` works and round-trips through `term_to_binary`/`binary_to_term`; arity 16777216 raises `system_limit`/`badarg`, also as a `LARGE_TUPLE_EXT` | a typed message's tuples have their declared arity (the language's decode; the M1b codec's 256 for a skipped tuple no longer applies to node programs) |
| List length | no fixed limit below memory; the ETF count is 32 bits (up to 4294967295) | **[run]** a 10,000,000-element list round-trips; a LIST_EXT count of 4294967295 with no elements behind it is refused. The 32-bit width: **argued, not checked** | N1: `max_length` of the generated decode is the frame cap, so a list is bounded only by the frame (a list longer than its frame cannot exist) |
| Map size | no fixed limit below memory; 32-bit arity in ETF | **[run]** a 1,000,000-key map round-trips; larger and the width: **argued, not checked** | maps only as records of declared keys: below |
| Binary size | up to the packet: a binary in a term is at most 4294967295 bytes (32-bit length) | **[run]** a 1 GiB binary encodes (1,073,741,830 bytes); above that **argued, not checked** | N1: up to the frame cap (`max_length` = `frame_size_max`); a string of exactly the cap minus its 14 bytes of framing decodes, one byte more is `too_large` (`trials/n1_limits`) |
| Nesting depth | **no limit** other than memory | **[run]** 5,000,000 nested one-tuples round-trip | N1: BEAM mode: the declared type's own nesting plus one (a typed decode cannot go deeper than its type; BEAM has none); TRUST: `term_depth_max` (default 32), BEES's own guard, now also the generated `max_depth` of `args` |
| Big integer | **4,194,239 bits** in this build (2^4194239 minus 1 encodes, one more bit raises `system_limit`); in ETF `SMALL_BIG_EXT` carries up to 255 digit bytes and `LARGE_BIG_EXT` has a 32-bit count, which the VM limit overrides | **[run]** binary search with `term_to_binary`; `LARGE_BIG_EXT` of 16,777,216 digit bytes refused. The documented figure of the OTP reference: **not available locally, not checked** | 64 bits: below, by the type (`int64` max round-trips, 2^63 is `out_of_range`: `trials/n1_limits`) |
| Atom table | 1,048,576 atoms by default | **[run]** `system_info(atom_limit)` | BEES creates no atoms from the wire (D16) |
| Fragments, distribution header, atom cache | optional features of the distribution | BEES sets neither flag (wire-v1 section 7) | not offered, by design |

**Consequences for the options.** (1) `beam.frame_size_max` and `trust.frame_size_max` default to 4294967295 and are bounded by
it; `trust.args_len_max` defaults to the frame cap. (2) **Updated 2026-11-10 (N1): the build implements every cap up to 4294967295.** The receive path is the language's
`wireframe@unframe` (the cap is a run-time argument, checked against the 4-byte length before the body is stored) and `decode`
(its `max_bytes` and `max_length` are the cap, written into the generated decoder at build time because the language takes the
limits as literals). What remains below BEAM is memory and time, not a fixed number: a frame is held whole while it is assembled
and the per-frame assembler's state copy (SD-35) makes the peak about 75 times the frame (8 MiB frame: 626 MiB on the receiver,
`trials/n1_frames`); a 4 GiB frame is not practical. A cap above available memory is the operator's responsibility (3). (3) A cap above available memory is the operator's responsibility; a refusal still happens
before anything is allocated for what the cap guards. (4) SEMP's 8 MiB (README, `semp_util:recv_frame`) and 4 MiB args, and the
multiplexing design's 1 MiB and 64 KiB, are **not** BEES's defaults or bounds; an operator may choose them as values.
(5) Any-type terms are not BEES's job (ruled 2026-11-05), so these limits apply to typed terms and to the opaque span of TRUST's
`args`; how that span is handled is the open point of section 9.

## 6. A full worked example

```erlang
%% bees.config: a TRUST node that serves one peer and calls others.
%% Every key is shown with its default except where noted; listen_address has no default.
[
  {mode, trust},

  {node, [
    {name, "orders@10.0.0.7"},                %% must equal the manifest's node line
    {creation, 1}
  ]},

  {trust, [
    {port, 6464},                             %% default 6469
    {listen_address, "10.0.0.7"},             %% required, no default (a trial config writes "127.0.0.1")
    {tls_opts, [{certfile,   "certs/node.pem"},
                {keyfile,    "certs/node-key.pem"},
                {cacertfile, "certs/ca.pem"}]},        %% optional (D43): omit it and peers are trusted by pin and whitelist only
    {whitelist_file, "trust_whitelist.config"},
    {whitelist_cert_dir, "certs"},
    {whitelist_default_spec, none},
    {whitelist_autoload, false},
    {server_pins_file, "trust_servers.config"},

    {call_timeout_ms, 5000},
    {suspicion_limit, 3},
    {token_bytes, 48},
    {token_ttl_sec, 300},

    {dns_ns_timeout_ms, 2000},
    {dns_total_timeout_ms, 5000},
    {connect_timeout_ms, 3000},
    {connect_stagger_ms, 250},
    {client_handshake_timeout, 5000},
    {first_frame_timeout_ms, 2000},

    {frame_size_max, 4_294_967_295},          %% BEAM's limit (built since N1)
    {args_len_max, 4_294_967_295},            %% default: equal to frame_size_max
    {term_depth_max, 32},

    {session, #{max_inflight => 8, max_age_ms => 60_000, idle_ms => 5_000,
                max_calls => 100, drain_ms => 1_000}},
    {acceptors, 8},
    {session_slots_max, 1_000}
  ]},

  {beam, [                                    %% validated, not used while mode is trust
    {transport, tcp},                         %% tls does not exist yet
    {auth, cookie},
    {cookie_file, "secrets/erlang.cookie"},
    {listen_address, "10.0.0.7"},
    {listen_port, 0},
    {epmd, external},
    {epmd_port, 4369},
    {net_ticktime_s, 60},
    {open_timeout_ms, 10_000},
    {peers, [{"billing@10.0.0.8", [{host, "10.0.0.8"}, {port, epmd}, {role, dial}]}]},
    {spawn, none},
    {spawn_allowlist, []},
    {frame_size_max, 4_294_967_295}           %% BEAM's limit (built since N1)
  ]}
].
```

A BEAM-mode node to test against a stock `erl -sname` node (N2) needs only:

```erlang
[ {mode, beam},
  {node, [{name, "bees@myhost"}]},                      %% a short name, as the stock node's
  {beam, [{transport, tcp}, {cookie_file, "cookie"}, {listen_address, "127.0.0.1"},
          {peers, [{"stock@myhost", [{host, "myhost"}, {port, epmd}, {role, dial}]}]}]} ].
```

## 7. Moving a SEMP `sys.config` over

1. **One section.** Everything SEMP spreads over the application environments `trust`, `semp`, `beam_semp` and `beam_trust`
   (the README uses `trust`; `suspicion_limit` and `whitelist_autoload` are read from `semp`; the multiplexing doc writes
   `beam_semp` and `beam_trust`; `host_app` is `beam_semp`) goes into the one `trust` section of `bees.config`, with
   `{mode, trust}`.
2. **Names are kept** (copy and paste) except: `token_ttl_ms` becomes `token_ttl_sec` (divide by 1000; a value that is not a whole
   number of seconds is an error); the multiplexing doc's `session` map is kept as written.
3. **Dropped:** `kernel` (`dist_auto_connect`, `logger_level`), `rpc_api`, `host_app`, `unsafe`, `unsafe_cookie`, `alpn`.
4. **Paths** lose their `priv/` prefix and are relative to the directory of `bees.config`.
5. **`tls_opts` and `client_tls_opts`** keep only `certfile`, `keyfile` and the optional `cacertfile` (D43); any other `ssl` option is an error
   (the profile fixes version, ALPN, verification and key exchange).
6. **The whitelist file** keeps SEMP's form (`#{"client-cert.pem" => Spec}`); certificate names resolve against
   `whitelist_cert_dir`. Specs are accepted as the list form the code reads or the map form the README writes (section 8).
7. **The earlier BEES text** (`{trust, [...]}` and `{bees_dist, [...]}` in two application entries of a `sys.config`): the
   `trust` entry moves as above; the `bees_dist` entry becomes the `beam` section (section 5.2: `enabled` becomes `mode`,
   `sname` becomes `node.name`).

BEES offers no translation tool; the rule is meant to be applied by hand and every mistake in it is caught by rule 2 of the
validation.

## 8. Where SEMP's sources disagree about options

(These extend inter-nodal-modes 3.12.) Each is settled above as stated.

| Option | Disagreement | BEES |
| --- | --- | --- |
| `port` | R `6464`; H `6469`; code: required | default 6469, range-checked |
| Token TTL | R `token_ttl_ms 300000`; code key `token_ttl_sec` default 120; H 1200 s | `token_ttl_sec` 300 |
| Frame cap | R 8 MiB (also hard-coded in `semp_util:recv_frame`); M default 1 MiB | **ruled (R1, 2026-11-06): the same as BEAM**: default and ceiling 4294967295 bytes (section 5.4); neither SEMP's 8 MiB nor M's 1 MiB. Built since N1 (2026-11-10) |
| Args cap | R 4 MiB; M 64 KiB | **ruled (R1): the same as BEAM**: default equal to `frame_size_max`, ceiling `frame_size_max` |
| Listen address | SEMP's `ssl:listen` binds every interface; no option | **ruled (R6): no built-in default**; required in the selected mode's section; trials write `127.0.0.1` |
| Application name | `trust`, `semp`, `beam_semp`, `beam_trust` | one `trust` section |
| `whitelist_autoload` | code default `false` (read from `semp`); `beam_semp.app.src` `true` | `false`; note that `list_cert_files` is applied to `whitelist_path`, which is the whitelist **file**, so autoload appears to scan nothing |
| `whitelist_default_spec` | `none` (R) vs `[]` (code, `app.src`) | `none`; `[]` normalizes to the same "nothing permitted" |
| Spec form | R writes a map `#{Module => all \| [{F,A}]}`; `normalize_value` accepts only `any`, `none` or a list of `{Mod, any \| [{F,A}]}` | both forms accepted, one internal form |
| Missing whitelist file | code: `{ok, standalone, hibernate}` (no inbound, **silently**) | **ruled (R2, 2026-11-06): never silent.** Configured and missing, unreadable or unparseable: boot error with a clear message; unset: standalone with a boot banner |
| Connect timing | R "3s per endpoint, ~250 ms stagger"; code connects in turn with the call's timeout | both are options |
| `drain` | the ruling lists `drain`; M has `drain_ms` only | `session.drain_ms` |
| `req_id` | R and code: 12 random bytes; inter-nodal-modes 3.6: at most 16 bytes; M: a small integer | a binary of 1 to 16 bytes; a client picks (open at N5, question in the report) |

## 9. What this document does not decide

- Logging options (a replacement for `kernel`'s `logger_level`): not designed.
- The exact shape of the generated module for targets without a file system (D26 says the contract fixes it).
- Whether a node may later run both modes (reserved, section 3.1).
- **Open: under discussion with the user (2026-11-06): how TRUST's `args` and result `value`, which SEMP carries as terms of
  any shape, are handled.** The text of this file (an opaque ETF span bounded by `args_len_max`, checked structurally) is the
  current text, not a decision; N3 depends on it (mvp.md N3). Nothing else is said here until the user rules.
- How typed Silica messages (the `remote` and `local` lines) relate to TRUST's CALL and CAST of an MFA: in `trust` mode those lines are
  refused; a mapping is a question for the user.

## 10. The user rulings of 2026-11-06 that shaped this revision

| Ruling | The user's words | Where it is written |
| --- | --- | --- |
| R1 | "The frame and argument caps are to be the same as BEAM." | section 5.4; the `frame_size_max` and `args_len_max` rows; section 8 |
| R2 | "SEMP is not to run silently if there is not a whitelist file even though BEES treats it as a boot error." | validation rule 8; `whitelist_file`; section 8 |
| R3 | "1) Default to trust." | section 3.1 |
| R4 | "2) eventually move to cookies when they become available and create similar trials for TRUST." | `beam.auth`; mvp.md N2, N3, N4 |
| R5 | "5) yes." (the test-only stand-in for the peer's certificate fingerprint) | `plaintext_test_only` |
| R6 | "for trials, yes. no default in the code." (listen address) | both `listen_address` rows; validation rule 7; section 6; section 8 |
| (drain) | the option the user called "drain" | `session.drain_ms` |

## 11. When the file is read: the build-time stand-in, and a boot-time reader (added 2026-11-10, N0.2)

**What is built.** `tools/bees_conf.py` is the one reader of this document: the grammar of section 4, every option of section 5 in
one table (`OPTIONS`; `bees_conf.py defaults` prints it, and `tools/test_bees_conf.py` compares the defaults and bounds of the
tables in section 5 with it), the precedence over the manifest (section 2), every validation rule and the one-line verdict
`bees.config:LINE: PATH: MESSAGE`. **It runs when the program is built, not at boot** (a stand-in, marked as such in its header,
in the generators and in every generated unit), because Silica cannot read a file at boot: specification 22.6 says `read_file` is
not implemented, and a Silica program has no other way to get bytes from the file system. The verdict reaches the program in one
of two forms, both before any actor starts: in TRUST mode it is compiled into `bees_trust_conf` and the node's startup prints it
and exits 1 (`trials/n3_trust` (g)); in BEAM mode and for M3's auth-none node the build stops with the same line and exit 1.
Consequences of the stand-in that the design does not have: a changed file needs a rebuild; "configured but missing at boot"
is checked when the program is built, not when it starts (a whitelist deleted after the build is not noticed: R2 is met at build
time only); a whitelist's counters are compiled in, not seeded at boot.

**Options that today's Silica fixes at build time, whatever reads the file** (a boot-time reader could not change them without
regenerating code):

| Option | Why it is build-time |
| --- | --- |
| `node.name` | the node name is an atom the program must hold (D16) |
| `beam.peers` | peer names are atoms of the manifest (D16); their host, port and role are boot values |
| `beam.frame_size_max` | the language's decode takes its limits as a record literal of literals, baked into the derived decoder (transport design 4.1, E2402); wireframe@unframe's cap is a run-time argument |
| `trust.whitelist_file` | the stand-in compiles the whitelist into the permission gate and one registered name per entry (atoms, D16); a boot reader needs a data-driven gate and a name pool |
| `trust.whitelist_cert_dir` | read with the whitelist |
| `trust.server_pins_file` | one registered client cache per pinned server (atoms) |
| `trust.frame_size_max` | the language's decode takes its limits as a record literal of literals, baked into the derived decoder (transport design 4.1, E2402); wireframe@unframe's cap is a run-time argument |
| `trust.args_len_max` | the language's decode takes its limits as a record literal of literals, baked into the derived decoder (transport design 4.1, E2402); wireframe@unframe's cap is a run-time argument |
| `trust.term_depth_max` | the language's decode takes its limits as a record literal of literals, baked into the derived decoder (transport design 4.1, E2402); wireframe@unframe's cap is a run-time argument |

**Options a boot-time reader could read with no change to generated code** (they are run-time values in the generated units today, compiled in as constants by the stand-in): `node.creation`, `beam.transport`, `beam.auth`, `beam.cookie_file`, `beam.listen_address`, `beam.listen_port`, `beam.epmd`, `beam.epmd_port`, `beam.net_ticktime_s`, `beam.open_timeout_ms`, `beam.spawn`, `beam.spawn_allowlist`, `trust.port`, `trust.listen_address`, `trust.tls_opts`, `trust.client_tls_opts`, `trust.whitelist_default_spec`, `trust.whitelist_autoload`, `trust.call_timeout_ms`, `trust.suspicion_limit`, `trust.token_bytes`, `trust.token_ttl_sec`, `trust.dns_ns_timeout_ms`, `trust.dns_total_timeout_ms`, `trust.connect_timeout_ms`, `trust.connect_stagger_ms`, `trust.client_handshake_timeout`, `trust.first_frame_timeout_ms`, `trust.session`, `trust.acceptors`, `trust.session_slots_max`, `trust.plaintext_test_only`, `trust.session.max_inflight`, `trust.session.max_age_ms`, `trust.session.idle_ms`, `trust.session.max_calls`, `trust.session.drain_ms`.

Note on `frame_size_max`: its run-time half (the `unframe` cap and the send cap) is a boot value; only its use as the `decode`
literal is build-time. A boot-time reader would keep the generated decode limits at the build's value and refuse at boot a file
whose cap is above it (rule 9), the "not built yet" form of section 4.

**Proposal: a native-edge file reader (not built; reported to the user as a decision).** What it would take, within BEES's rules
(macOS system libraries only, no download, the FFI's taint rules):

1. **The edge.** One C function in the BEES native archive, `bees_conf_read_etf(path)`: `open`, `fstat` (regular file, size at
   most 64 KiB, for key and cookie files the mode check of rule 8), `read`, `close`; it answers ONE ETF binary term holding the
   bytes, or `{error, Reason}` text with `errno`'s name, the same shape as the resolver edge (`native/src/silica_bees_resolve.c`).
   About 60 lines; `getaddrinfo`'s edge is the precedent. A Silica face `dangerous_bees_conf_native` and a worker
   `dangerous_bees_conf@read` (one request, one tainted cast to the requester, as `dangerous_bees_resolve@rslv`).
2. **The conversion.** The requester decodes the term with the language's `decode((:etf), ...)` inside a `sequence ... produces
   pure` block (mvp.md section 4), so the file's bytes become a pure string; the taint caveat SD-25 is the same as for every
   other edge.
3. **The reader in Silica.** The grammar of section 4 and the validation of section 4 written in Silica (`src/shim/bees_conf.silica`,
   D26), producing the same verdict text. This is most of the work: a recursive-descent parser over a string (bounded depth,
   64 KiB), a table of options, the cross-field rules. It must run before any actor of the node starts, so the node's startup
   becomes: spawn the reader worker, wait for the verdict, then start or exit 1.
4. **Which files.** `bees.config`; `trust.whitelist_file` and `trust.server_pins_file` (the same grammar); the certificates they
   name (only their SHA-512 fingerprint is needed: a second edge call `bees_conf_sha512_der(path)` with CommonCrypto, the DER
   inside a PEM file); `beam.cookie_file` is already read by the cookie edge at each handshake (N2) and needs only the mode check
   moved to boot.
5. **What stays build-time** (the table above): the decode literals, the atoms (node names, the registered names of whitelist
   entries and pinned servers: a boot reader needs a fixed pool of such names, sized at build time, and a data-driven
   permission gate instead of compiled `perm_i` functions).
6. **Targets without a file system** (section 1): the same reader over the generated module `bees_conf_embedded`.

**Not built, by the user's instruction (2026-11-10): the native-edge file reader is another agent's responsibility;** this
section is the proposal only. It is also not small (step 3 is a parser and validator in Silica, and steps 4 and 5 change the
TRUST units). The stand-in stays and is marked as such everywhere.

## 12. Run-time configuration source and decode limits (rulings of 2026-11-18, roadmap D46 and D47)

Status: decided, not built. This section replaces the native-edge file reader proposed in section 11.

### 12.1 The source is the storage carrier (D46)

BEES is a source library; the application reads its configuration and passes the values to BEES. The application reads it
through the local persistent storage of transport, the `(:store)` carrier (Silica transport design 6.8). No C code reads a
file. Silica's reply to request B2 (2026-11-17) rejected changes to the carrier and proposed a native file read; the user
ruled the native read out.

- The application's own unit declares the store: `carried_on config: (:store) (:backing, "<path>.sildat", <capacity>, :stop);`.
  The path and the capacity are literals of that declaration, so they are fixed when the application is built, and the name
  ends in `.sildat`. On a board the link is the board's region (`(:flash_region, n, :stop)`), when Silica provides it.
- The contract for the configuration is the ETF wire contract of the `(:etf)` format as storage carries it. The packer
  (run at deploy time) turns `bees.config`, the whitelist, the pins and the certificates into ETF terms and writes them as
  the records the store would hold for `encode((:etf), value)`; it is allowed to write the store's file directly.
- The application opens the store, waits for `:log`, replays from `oldest` and passes every record through
  `decode((:etf), ...)`. The bytes are untrusted until decode has re-created the value (design 6.8.3).
- What the carrier does that the application must handle: a missing backing is created empty (the log has no records:
  the application reports that there is no configuration); a backing of another size ends the open with
  `(:link_down, :mismatch)`; a record that fails its check ends the replay with `(:read_failed, :corrupt)`; one owner at
  a time (`:in_use`).
- Secrets (the cookie, private keys) pass through the store like the rest; BEES keeps no copy and logs none.

Open until probed: the block size and record size of the hosted backing (a value larger than one record is segmented by
`wireframe` in `:storage` mode), and a trial that a packer-written store is read back by a Silica program.

### 12.2 Decode limits: one literal ceiling, as a maximum (D47)

Silica keeps the limits of `decode` compile-time literals (reply to request B1). BEES therefore writes one fixed literal
in every generated `decode`: `max_bytes` and `max_length` of 4294967295, BEAM's packet maximum (section 5.4), with
`max_depth` from the type as today. That literal is a maximum: BEES never decodes more, and a configuration that asks for
a larger `frame_size_max` or `trust.args_len_max` is refused when it is validated.

The configured caps are enforced at run time, before decode: `wireframe@unframe` takes the frame cap as a run-time value
and refuses a longer frame, and the proxies apply the same cap on send. A term cannot be larger than its frame, so the
configured cap bounds every decode even though the literal is the ceiling. There are no limit tiers.

The three hand-written decodes with small fixed limits (the TRUST frame header fields and the resolver result) keep their
own literals.

To watch: Silica plans a per-target ceiling for decode limits; if it refuses 4294967295 on a board, the ceiling literal
becomes a per-platform value (a smaller maximum on that platform).
