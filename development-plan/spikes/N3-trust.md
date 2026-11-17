# N3: TRUST logic over plaintext loopback

**Status: built and run 2026-11-10 on `silica-999926-macos-applesilicon` (macOS, Apple Silicon only). Re-run 2026-11-12 on
`silica-999925` with the carrier fixes of Silica 71009f96f8 and without the `remove_actor` workaround (section 3, item 5); the same
logic now also runs over mutual TLS 1.3 (N4.1, [N4-silica-mtls-example.md](N4-silica-mtls-example.md), `trials/n4_trust_tls`).** TRUST mode is its own
implementation (D36): nothing in it uses BEAM mode's distribution layer (`dangerous_bees_net`, `bees_dist`, `bees_peers`). **TEST
ONLY:** there is no TLS (N4), the transport is plaintext on `127.0.0.1` (`plaintext_test_only`), and the peer's identity is a
**test-supplied stand-in for the certificate fingerprint**: the first 64 bytes a client sends (R5, accepted by the user until TLS
exists; said in the code, here, and in the boot banner). Plan: [mvp.md](../mvp.md) section 5, N3; design:
[inter-nodal-modes.md](../inter-nodal-modes.md) section 3; options: [bees-config-file.md](../bees-config-file.md) section 5.3.
Compiler findings: [silica-defects.md](../silica-defects.md), the N3 section (SD-44, SD-45 and notes).

## 1. What was built

| Piece | Where | What it does |
| --- | --- | --- |
| frame codec | `src/trust/bees_trust_frame.silica` | SEMP's wire: a 4-byte length and one ETF map per frame. `check` walks the map structurally and bounds-checked **before any value is decoded**: the 131 byte, a map on top, at most 16 keys, atom keys, no key twice, only TRUST's ETF subset (integers, floats, atoms, binaries, lists, tuples, maps; pids, references, ports, funs, bit binaries, compressed terms are `unsupported`), depth at most `term_depth_max`, every atom one the program holds (D16, `unknown_atom`), the `args` value at most `args_len_max` bytes (`too_large`), no trailing bytes. Each value is then decoded with the **language's `decode((:etf), ...)`** in a `sequence ... produces pure` block (`t`, `ver`, `req_id`, `m`, `f`, `a`, `token`); `args` and a result's `value` stay ETF spans. Frames BEES writes: each value made by the language's `encode`, the map written around them in key name order. |
| forbidden guard | `src/trust/bees_trust_guard.silica` | SEMP's default deny map (`semp_policy:default_map/0`, whole modules and `erlang` functions of every arity) and prefixes, plus BEES's: `bees_*` (the shim, the generated units, the local-only reset), `trpc`, `trust_`, `semp_`, `tempus_`. |
| permission gate, whitelist, config | `tools/bees_config_trust.py` → generated `bees_trust_conf` | The TRUST half of the `bees.config` reader (the BEAM half is N2's; to be merged into N0.2's reader). Reads `bees.config`, the whitelist (SEMP's file: `#{"cert" => Spec}` or the list form; specs `none`, `any`, per-module list or map), the pin file and the certificates **when the program is built** (Silica cannot read files yet; see section 4), and compiles in the values, the per-fingerprint permission functions and either "no error" or the boot error line. |
| MFA table | `tools/bees_trust_gen.py mfa` → generated `bees_trust_mfa` | From a `.trust` manifest (`export <m> <f> <a> <unit>@<fn> args <ElemType> result <Type>`): the slot of an MFA (a function not compiled in does not exist), the type check of `args` (the language's `decode` as `List[ElemType]`) and the call (decode, call, the language's `encode` of the result). **The provisional answer to the open question of how `args` and `value` are typed** (mvp.md N3): per MFA, by this manifest line. |
| connection actors | `src/trust/dangerous_bees_trust.silica` | `tlsn` (listener: a send actor and a receive actor per accepted connection), `tconn` (the receive actor and per-connection state machine, a plain behaviour with a phase field, S-17), `ttx` (the send actor: encodes and frames typed values), `tasm` (per-frame assembler, SD-35), `tpeer` (one per whitelisted fingerprint: suspicion, quarantine, token), `tcache` (one per pinned server: the client's token cache), `tcli` (the client side of one `trpc` call or cast). |
| per-request worker | `src/trust/bees_trust_work.silica` | Runs the MFA in its own actor; `(:error, Reason)` from the user code makes it `fail_self(Reason)` (D2) after telling the connection, which sends nothing to the peer. |
| native edge | `native/trust/silica_bees_trust.c`, sidecar `native/dangerous_exposure_source/trust/`, `src/trust/dangerous_bees_trust_native.silica`, worker `src/trust/dangerous_bees_trust_edge.silica` | Random bytes from `arc4random_buf` (libSystem; nothing downloaded), returned as one ETF binary that the receiving connection decodes with the language's `decode`, and the constant-time comparison (every byte visited, lengths public). Its own archive `libsilica_bees_trust.a` (D36: no code shared with BEAM mode's edge). |
| node edge | `src/shim/bees_trust_node.part` (pasted by `tools/bees_trust_gen.py edge`) | `trust_boot` (first in `main`: prints the boot error and starts nothing, or the TEST ONLY banner, the sanitized summary and the boot notes), `trust_start`, `trpc_call`, `trpc_cast`, `trust_reset` (the operator's local reset), raw helpers for hostile test peers. |

**One connection, server side (phases of `tconn`):** 1 read the 64-byte stand-in fingerprint (`client_handshake_timeout`); not in
the whitelist: `whitelist_reject`, closed. 2 ask the fingerprint's actor whether it is quarantined: `quarantined`, closed. 3 the first
frame (`first_frame_timeout_ms`): `hello` → 4 ask the edge for `token_bytes` random bytes, store them with the fingerprint (expiry
`token_ttl_sec`, one per fingerprint, the new one replaces the old), send `token_issue`; `token_present` → 5 the fingerprint's actor
checks expiry and quarantine and asks the edge's constant-time compare; anything else: `protocol_error` ("request before the token
step"), closed. 6 the request frame: structure, `ver` 1, `req_id` 1 to 16 bytes, `m`/`f` atoms, `a` the length of `args`, `opts` a
map; then the forbidden guard, the permission gate, the MFA table, the type check of `args`; admitted: a worker runs it. 7 a call
waits for the worker (`call_timeout_ms`) and sends `result`; 8 a cast closes at once and waits for the worker. Every refusal
closes with **no error body**, writes one audit line (`[trust audit] event fp=<128 hex digits> what <connection id>`; arguments and
tokens are never logged) and, for a whitelisted fingerprint, raises its suspicion by one; a permitted request that succeeds lowers it
(floor 0); above `suspicion_limit` the fingerprint is quarantined, its token revoked and every connection refused until
`trust_reset` (D10). A connection actor never ends while an answer it asked for is on its way (a cast to an ended actor fails the
sender), and is reaped 500 ms after its close.

**Client (`trpc_call`/`trpc_cast`, `tcli`):** an address the pin file does not list is `server_not_pinned`; a host that is not an
IPv4 literal is `dns_error` (DNS is not built: N1); connect (`connect_timeout_ms`; one address, so no stagger); ask the server's
cache; send the stand-in fingerprint, `token_present` (cached) or `hello`, and the request, **pipelined** (the server takes them in
order, holding each next frame until it is ready); read `token_issue` (cached) and `result`; answer the caller once with
`{ req, what, value }`: `ok` with the result's ETF span, `cast`, or `closed`, `timeout`, `protocol_error`, `connect_failed`,
`dns_error`, `server_not_pinned`. A connection that ends without its answer makes the client forget the cached token (the server
may have revoked it), so the next call starts with `hello`.

## 2. Trials

| Leaf | What | Result |
| --- | --- | --- |
| `trials/n3_trust_frames` | in memory: every frame BEES writes passes `check` and decodes back; 13 hostile frames refused with the language's reason (bad version, not a map, truncated, trailing byte, key twice, unknown atom, pid, too deep, 17 keys, integer key, a list count beyond the frame, args above `args_len_max`); the forbidden guard; the parsers; **200,000 refused frames** (half an oversize length refused by `wireframe@unframe` when the length is read, half structural) | golden recorded; **peak resident set 1.7 MB** (`/usr/bin/time -l`, peak footprint 1.0 MB), as flat as `m1_wire_memory`'s 1.9 MB |
| `trials/n3_trust` scenario | (a) two processes: `demo:add([1,2])` by `hello` → `{ok, 3}` and `token_issued`; `demo:add([40,2])` → `{ok, 42}` with `token_accepted` (fast path, no `token_issue`); `cast demo:note([7])` → `{ok, cast}`, the server prints `note got 7`; `demo:echo([<<"hi">>])` → `{ok, <<"hi">>}` | goldens, both sides |
| `trials/n3_trust` negative | 16 steps, each refusal with no error body (a raw peer counts 0 bytes, or only the `token_issue` frame it asked for; a trpc call sees `closed`), an audit line and the suspicion change: (b) unlisted fingerprint; invalid token; (c) a call frame before the token step; (d) `hello` with `ver` 2, a malformed map, a length above `frame_size_max` (refused before decoding); first-frame timeout; `erlang:apply/3` forbidden; a permitted call (suspicion 7 → 6) and a permitted cast (6 → 5); `bees_trust_admin:reset/1` forbidden (the reset is local only); `demo:secret/0` not in the spec (`permission_denied`); `demo:crash/1` (`user_code_error`, the worker fails); `demo:slow` above `call_timeout_ms` (timeout, suspicion 9 > 8: quarantined, token revoked); a call while quarantined (refused at the gate); the operator's local `trust_reset` at 9 s; a call after it → `{ok, 3}` | goldens, both sides |
| `trials/n3_trust` kill | (e) a raw peer sends its fingerprint and `hello`, gets `token_issue`; node a is SIGKILLed; the peer sees the close | golden (node b; node a's side is cut by the kill and not compared) |
| `trials/n3_trust` boot_missing, boot_unreadable | (g) a configured `whitelist_file` that does not exist / exists with mode 000: `[trust] boot refused: bees.config:8: trust.whitelist_file: whitelist file "…" does not exist` / `is not readable (permissions)`, `no actor was started`, exit 1 (R2) | goldens |
| `tools/test_bees_config_trust.py` | 13 tests: every `trust` and `mode` validation rule rejects with `bees.config:LINE: PATH: MESSAGE`; the defaults of section 5.3 read back; both spec forms; SHA-512 of the DER inside a PEM; the generated unit; and live `erl`'s `binary_to_term(.., [safe])` reads BEES's hello, call and result frames as maps with the expected keys | pass |

**Stability:** the goldens were recorded after reading each output, then `make -C trials/n3_trust integrate` passed 7 of 7 on two
further runs, the last with the machine's load average above 80 (the timing margins: steps 150 ms apart, the slow call's worker
ending well inside the 2 s before the next step, the operator reset at 9 s against steps 15 and 16 at about 5 s and 11 s).

The node programs are built from `bees.config` files in `trials/n3_trust/nodes/*/` (node a: whitelist `b.cert` with
`demo:add/2, echo/1, slow/1, crash/1, note/1`, `n.cert` with `none`, and `z.cert`, which is missing and logged as skipped; node b:
standalone, pins `127.0.0.1:47501`). The stand-in certificates in `trials/n3_trust/certs/` are text files, not X.509.

**(f) Rate and memory** (`make -C trials/n3_trust measure`; one run each, this machine, under heavy load from other work, not a
benchmark): 2,000 calls one after another, each on its own connection (B1), the first by `hello`, the rest on the token fast path:
**5.55 s and 5.75 s (about 350 requests per second)**, a third run 9.57 s with the load average near 40; **peak resident set 34 to
38 MiB per node**. **2026-11-12, without the workaround (carriers end with their link): 5.12 s, 8.6 and 8.4 MiB; 6,000 calls 15.2 s,
11.9 and 10.9 MiB.** Before the closed carriers were removed (section 3, item 5) the same run peaked at **232 MiB per node**.
The same run with 6,000 calls: **15.8 s (380 requests per second), peak 37.8 and 35.8 MiB**: memory does not grow with the
number of connections once closed carriers are removed (2,000 calls peaked at 34 to 38 MiB).

## 3. Decisions taken in the code (each open to the user)

1. **The config is read at build time** (section 4). The boot refusal of R2 is real (no actor starts, exit 1), but the file is
   read when the program is built, so a change needs a rebuild until Silica can read files and N0.2's reader exists.
2. **`args` typed per MFA by a manifest line** (`.trust`, `List[ElemType]`, one element type; the language refuses a sum of plain
   types in a list, E2401, so a heterogeneous argument list needs a sum of tagged tuples or atoms). The result `value` is the
   language's `encode` of the declared result type. Provisional until the user rules on any-type terms.
3. **Token words.** A token is held as ten seven-byte words in the fingerprint's actor, because a string in an actor's state that
   is replaced takes SD-35's whole-state copy at every dispatch; the compiler proves `tpeer`, `tcache`, `tconn` and `tcli` (the only
   W2300 left is `tasm`, as in BEAM mode).
4. **The client pipelines** the fingerprint, the token step and the request. The server holds each next frame (the next assembler
   is started with the bytes that followed and drained only when the connection is ready), so the order is SEMP's.
5. **Closed carriers are removed** with `remove_actor` by the connection actor when it is reaped: the language's carrier never ends
   after `:close`, and each one left behind kept about 100 KiB (232 MiB after 2,000 connections). `remove_actor` takes the
   `dangerous_actor_ref` (it compiles and runs). **Removed 2026-11-12:** since Silica commit 71009f96f8 the carrier ends with its
   link (after `:link_down`, on `:close` and on a peer close), so the workaround is gone; in its place, nothing casts to a carrier
   after its `:link_down` (the send actor's kind 10 ends it without touching the carrier), because a cast to an ended carrier ends
   the sender (SD-43). 2,000 calls then peak at 8.6 and 8.4 MiB per node (5.12 s), 6,000 calls at 11.9 and 10.9 MiB (15.2 s).
6. **The client forgets a cached token** when a connection ends without its answer (a quarantine revokes the server's copy; a
   server restart forgets it).
7. **Audit lines** end with the connection id; the token is never logged; `token_issued` and `token_accepted` are logged by the
   connection (not by the fingerprint's actor), so their order with `admitted` is fixed.
8. **The pin file's format** is BEES's (`#{"host:port" => "server-cert"}`); in N3 only the address is checked (no server
   certificate without TLS; N4). Each pinned server gets one token cache.
9. **An atom the server does not hold** (for example `apply` in a program that never mentions it) is refused by the atom policy
   (`protocol_error ... unknown_atom`) before the forbidden guard; node a holds the forbidden names its trial sends so that the
   guard is what refuses them.
10. **The soft increment for timeouts** is +1, like the others (inter-nodal-modes 3.7 says "soft" without a size).
11. **`opts.deadline_ms`** is accepted (`opts` must be a map) and not used: a timer's delay is `uint64` and Silica has no int64 to
    uint64 conversion (M3 note), so the server bounds a call by its own `call_timeout_ms`.
12. **`listen_address`** must be `127.0.0.1`: the language's carrier listens on 127.0.0.1 for `listen:PORT` (and on every interface
    for `listen:any:PORT`, added to the Silica tree during this work, not used).

## 4. Not covered, and why

- **TLS, ALPN, certificates, server pins** (N4); the stand-in fingerprint is test-only.
- **Reading `bees.config` at boot.** Silica has no file reading (specification 22.6: `read_file` is not implemented); the reader is
  Python at build time. The `beam` section is not read here (N2's half).
- **Multiplexing** (N5); `session`, `acceptors`, `session_slots_max` are validated, not used (one request per connection).
- **DNS, IPv6, more than one address per name, connect stagger** (N1: the language's carrier takes an IPv4 literal).
- **A hard fault of the user code** (not `(:error, _)`) is seen only as the call timeout: no monitor (D20).
- **Taint:** the random bytes are decoded by the language's `decode` in the receiving connection actor (the FFI result handler);
  the checker raises nothing, with SD-25's caveat (that handler is not checked), as for N0.1.
- **Interoperation with the Erlang reference** is not promised (inter-nodal-modes 3.13); `erl` reads BEES's frames, and BEES's key
  order is the language's (name order), not `term_to_binary`'s.


## 2026-11-17: the per-connection growth, measured to 20,000 calls (N2c, user: "for a long-lived TRUST node that is a leak")

`make measure` in trials/n3_trust now runs 2,000, 6,000 and 20,000 calls (CALLS_LIST; one connection per call; not part of integrate). Peak resident set:
server 8.49, 12.24, 24.08 MiB; client 8.29, 11.34, 19.78 MiB; so 0.85 KiB per call on the server and 0.59 KiB on the client between 6,000 and 20,000. Every
connection actor of TRUST ends (tconn at phase 10, ttx at kind 3 or 10, tasm per frame, twork by stop_self), so the growth is not an idle actor. A
reproduction without any BEES actor (trials/n2_carrier_leak) shows 0.52 KiB per ended (:tcp) carrier: that is SD-46, Silica's, and it accounts for almost all
of the client's growth and 60 percent of the server's. About 0.3 KiB per call on the server is not attributed (candidate: the edge worker's FFI dispatches
for the constant-time token check; not isolated). Nothing in BEES's TRUST units could be removed.
