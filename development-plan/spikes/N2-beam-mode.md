# N2: BEAM mode against a stock Erlang node

**Status: built and run 2026-11-10 on `silica-999926-macos-applesilicon`, macOS on Apple Silicon, against the installed
OTP 28 (`erl` 28, kernel-10.0; D14 names OTP 29, so this is a test against 28).** Everything ran on 127.0.0.1. Nothing was
downloaded, and nothing in `/Users/yenrab/silica` was changed. The user accepted four rulings on 2026-11-10, listed in
section 6.

## 1. What was built

| Piece | File | What it does |
| --- | --- | --- |
| Cookie edge (C) | `native/src/silica_bees_beam.c`, `native/dangerous_exposure_source/beam/` | Reads the cookie file and refuses it when it is not a regular file, is readable or writable by group or others, or holds anything but 1 to 255 bytes of ASCII 32..126. It makes a random 32-bit challenge (`CCRandomGenerateBytes`) and computes `MD5(cookie ++ decimal(challenge))` (`CC_MD5`, `dist_util:gen_digest/2`). Both come from CommonCrypto, which is part of libSystem. The cookie never leaves C. Built into the existing `libsilica_bees_native.a`. |
| Cookie worker | `src/inter_nodal/dangerous_beam_auth.silica`, `dangerous_beam_auth_ffi.silica` | One FFI worker per node, in the stdlib carrier's shape: the worker behaviour is in a library unit and its spawn site is in the root unit. Op 1 returns a new challenge and its digest; op 3 returns the digest of the peer's challenge. Every foreign scalar is cleaned with the language's `recreate` inside the worker, so only pure numbers leave it. Its state is the cookie file's path. |
| Layouts | `src/inter_nodal/beam_dist.silica` | BEAM-mode flags `0x4_0307_0F9D`; `N` (initiator and acceptor with a challenge); `s` statuses; `r`; `a`; EPMD's `ALIVE2_REQ`, `ALIVE2_X_RESP`/`ALIVE2_RESP`, `PORT_PLEASE2_REQ`, `PORT2_RESP`; a bounded ETF skipper (every tag OTP may put in a control message, depth 16); control-tuple spans; pid read and write; the replies EXIT `noproc`, UNLINK_ID_ACK and SEND; net_kernel's `is_auth` request and its `{Tag, yes}` reply; the `{Pid, Value}` handout payload. |
| Node | `src/inter_nodal/dangerous_beam_net.silica` | A fork of M3's `dangerous_bees_net` (left as it was for the auth-none M3 to M5 trials), with the same rules: no heap value in `conn`'s state (SD-35), no replaced `dangerous_actor_ref` (SD-39). It adds the cookie steps; `not_allowed` for an unlisted node; the EPMD client actor `epm` (register and keep the connection open, or look up then dial); and the control messages: REG_SEND to local names and to `net_kernel`, SEND to a handed-out pid, LINK, UNLINK_ID, UNLINK_ID_ACK, EXIT, EXIT2, MONITOR_P and DEMONITOR_P. Each control message is audited and counted. `tx` gained kind 6, which writes and then closes, so `not_allowed` reaches the peer before the close. |
| Startup | `src/shim/beam_node_edge.part` | Passed to `tools/bees_edge_gen.py` as the first role file, so no shared tool changed. `beam_launch(c, io_ms, tick_ms, cookie)` starts the cookie worker and a second carrier for EPMD, then dials (directly or through EPMD) or listens through `lsn`. It prints the configuration summary and the BEAM-mode banner. |
| Config, beam half | `tools/bees_config_beam.py` | The beam half of the `bees.config` reader. It parses the full grammar of section 4 and validates `mode`, `node` and `beam`: unknown key, duplicate key, type, bounds with no clamping, cross-field rules, required values, files, "not built yet", and the node name against the manifest. The `trust` section is left to the trust half (N3's `tools/bees_config_trust.py`). It generates `beam_conf.silica` (effective values) and `beam_peers.silica` (proxies, reaper, handout table). It reads the file at **build time**, not at boot (section 5). |
| `.beam` manifest | (format in the tool's docstring) | `pid <remote> deliver <local>`: that proxy hands out its pid in a `{Pid, Value}` payload, and a SEND to that pid is decoded with `<local>`'s type and delivered to it. |

## 2. Trials

| Leaf | What it checks | Result |
| --- | --- | --- |
| `trials/n2_auth` | The cookie worker's op 3 digests for challenges 3000000000, 0 and 4294967295, and op 1 against op 3 of the same challenge. | 1/1. `tools/test_beam_dist.py` compares the three digests with `erlang:md5`: equal. |
| `trials/n2_frames` | Every BEAM-mode message BEES writes, as hex. OTP 28 control messages captured from `erl` (LINK, MONITOR_P, UNLINK_ID with a big id, EXIT2 with a nested reason, the `net_kernel` gen_call with an `[alias\|Ref]` tag) are parsed back; truncated, bad-tag and too-deep input is refused. | 1/1. In `tools/test_beam_dist.py`, the flags equal kernel's `dist.hrl` (mandatory set, PUBLISHED, DIST_MONITOR). `N`, `s`, `r` and `a` equal an independent writer of `dist_util.erl`'s layouts. `ALIVE2_REQ` and `PORT_PLEASE2_REQ` equal `erl_epmd.erl`'s packets. EXIT, UNLINK_ID_ACK, SEND, the is_auth reply and the handout payload equal `term_to_binary` in `erl`. |
| `trials/n2_dist` | M3's five scenarios with cookies (R4), BEES to BEES on fixed ports (`epmd none`), plus `wrong_cookie_dial`, `wrong_cookie_listen` and `loose_cookie`. | 16/16, stable over three runs. Each side differs from M3's golden only in the handshake: the banner and summary, `cookie digest accepted from ...`, `not_allowed sent` / `refused by the peer: not_allowed` in place of M3's bare close, and the new `control messages counted` line. A wrong cookie in either direction is refused by the acceptor (`challenge reply refused (bad cookie)`). A loose cookie file is refused by the edge (`cookie unavailable`). Nothing crashes. |
| `trials/n2_live` | **The live test** against `erl -sname ...@localhost` (driver `tools/n2_live.py`, stock side `trials/n2_live/stock_driver.erl`, private EPMD on 127.0.0.1:4399, `net_ticktime` 8 on both sides). | 10/10, stable over three runs. See section 3. |
| `tools/test_beam_dist.py` (in `make kit`) | The reader's rejecting cases (syntax, unknown and duplicate key, type, below and above a bound, `mode` absent, list form, `trust` with remote lines, missing `listen_address`, missing, loose and empty cookie file, `tls`, non-loopback address, `frame_size_max` above 4096, `spawn`, `creation epmd`, `listen_port 0` with `epmd none`, node name differs, a peer not in the manifest, a bad `.beam` line), plus the layout and digest checks above. | 15 tests, OK. |

## 3. The live evidence (OTP 28, 2026-11-10)

Exit criteria of the N2 row, as run in `trials/n2_live` (goldens `*.scout`; raw logs `*.raw`):

1. **Handshake both ways.** In `stock_dials`, the stock node finds `beesl@localhost` in EPMD (BEES registered with ALIVE2 and
   kept the connection open), dials it, and the cookie handshake completes (`cookie digest accepted from stock@localhost`). In
   `bees_dials`, BEES asks EPMD (PORT_PLEASE2: `epmd: found, dialing stock`), dials the stock node and completes the handshake
   as initiator.
2. **`net_adm:ping` returns `pong`.** BEES answers `net_kernel`'s `{'$gen_call', {From, [alias|Ref]}, {is_auth, Node}}` with
   SEND `{[alias|Ref], yes}` to From.
3. **`{inbox, BEES} ! #{op => hello, n => 1}` is delivered** to the BEES local name: `inbox got op=hello n=1`. In
   `bees_dials`, `{outbox, BEES} ! #{op => inc, n => 42}` gives `outbox got op=inc n=42`.
4. **A BEES cast to a remote name arrives at a registered stock process.** The reply cast to `outbox` arrives as
   `{Pid, #{op => reply, n => 2}}` with `node(Pid)` equal to BEES (the handout). In `bees_dials`, the stock's `inbox` gets
   `#{op => inc, n => 41}`.
5. **Wrong cookie refused both ways, no crash.** `wrong_ping`: BEES refuses the stock node's `r` and `ping` returns `pang`.
   `wrong_listen`: the stock node refuses BEES's `r` (`** Connection attempt from node beesd@localhost rejected. Invalid
   challenge reply. **`). Both programs exit normally.
6. **`not_allowed`.** `unlisted`: `intruder@localhost` gets the status `not_allowed` and its `ping` returns `pang`. BEES
   audits `unlisted node, not_allowed sent, link closed intruder@localhost`.
7. **Ticks.** With `net_ticktime` 8 on both sides, the link stays up through 26 s of idleness (more than 3 × 8 s), and
   `nodes()` still lists BEES afterwards.
8. **nodedown.** After BEES is killed (SIGKILL), the stock node sees `nodedown` well within 8 s: 32, 22 and 25 ms in three
   runs (the kernel closes the socket).
9. **Links and monitors.** A stock process links to the handed-out pid (`LINK ... accepted, counted`), unlinks (BEES answers
   UNLINK_ID_ACK) and monitors it; the link survives and `nodes()` still lists BEES. A process that stays linked exits with
   `noconnection` when BEES dies, and the monitor fires with `noconnection`. A link to a BEES pid that BEES did not hand out
   is answered EXIT `noproc`. **Finding: OTP 28 sends no MONITOR_P or DEMONITOR_P to BEES.** The stock node's
   distribution-socket `send_cnt` does not change across `monitor/2` and `demonitor/1` towards a BEES pid, while `link/1`
   adds one frame. Between two stock nodes, `monitor/2` and `demonitor/1` each add one. `dist_util` negotiates flags with a
   plain AND and BEES offers DIST_MONITOR (0x8), so the reason is in ERTS, whose source is not installed. The stock node keeps
   the monitor locally and fires it on `noconnection`, which matches what D21's "dropped" would give. BEES's MONITOR_P and
   DEMONITOR_P paths are exercised only by `n2_frames` (OTP bytes parsed), not live.
10. **SEND to a pid.** `Pid ! #{op => viapid, n => 3}` reaches the actor behind the handed-out pid (`SEND to a handed-out pid,
    for inbox`, then `inbox got op=viapid n=3`). A SEND to a BEES pid that BEES did not hand out (id 99) is dropped and
    counted.

The stock kernel's own nodeup traffic, REG_SEND to `rex` and to `global_name_server`, is dropped and counted (`not a name this
node serves`). Those two can arrive in either order; the driver sorts a run of such lines in the normalised output.

## 4. Compiler facts met (none is a new defect)

- A function may take at most eight register arguments on AArch64 (E1070). `conn`'s fourteen-field sub-state therefore has
  no single constructor; it is built by small helpers that each write the record literal. SD-37's derived decoder hits the
  same limit.
- `end` cannot be a parameter name, and `link` cannot be a record field name; both are keywords (E1069, "no parsable body").
- A module function named `head` is ambiguous with the builtin (E2020).
- `recreate` is a transport operation: the worker's `external_danger` sequence must also declare `transport` (E3013).
- An `if`-like `case` inside an arithmetic expression does not parse; it is lifted into a helper function.
- The FFI taint check accepts the worker as written: foreign tagged results, scalars cleaned with `recreate`, a string built
  from those pure numbers and cast to the connection actor. SD-25's caveat still holds: the handler of an FFI result is not
  itself checked.
- No Silica-side interchange problem was seen. The language's `(:tcp)` carrier carried the OTP handshake, the data frames and
  EPMD's unframed answers unchanged; EPMD closes its socket after PORT2_RESP and the carrier reported `(:link_down, :closed)`
  as expected.

## 5. Deviations and limits (each is in the N2 row)

- **The config is read at build time** (`beam_conf` constants), not at boot. The boot-time reader is N0.2. The cookie is not
  built in: only its path is, and the edge reads the file at each handshake.
- **Creation is fixed** (manifest or `node.creation`; ruling 3). The creation EPMD assigns is not used; `{creation, epmd}` is
  refused as not built yet. Restarting BEES with the same creation makes old BEES pids at the stock node refer to the new
  incarnation.
- **One link per node** (M3). A dialing node does not register with EPMD. A listening node registers once its port is bound
  (`listen_port 0` works: the bound port is registered).
- **Exits are counted, not delivered**: LINK, EXIT, EXIT2 and UNLINK_ID_ACK wait for the exit hub and Silica links (A2, I1).
- **127.0.0.1 only**, through the language's carrier. `listen_address` and peer hosts other than 127.0.0.1 are refused as
  not built yet (N1).
- **Not run**: the M4 demo under cookies (R4 covers M3 to M5; M4's demo and rate under `auth cookie` were not re-run), the
  `tls` transport (D25), remote spawn, the OTP 25 digest shorthand flag.

## 6. Rulings (user, 2026-11-10)

1. The `pid <remote> deliver <local>` manifest line and the `{Pid, Value}` handout (the language encodes an `actor_ref` as
   `nonode@nohost`, so it cannot carry a usable pid).
2. BEAM-mode flags `0x4_0307_0F9D`: PUBLISHED, so the node is in `nodes()`, and DIST_MONITOR.
3. Creation fixed from the manifest or config.
4. BEES answers `net_kernel`'s `is_auth`, so `net_adm:ping` returns `pong`.
