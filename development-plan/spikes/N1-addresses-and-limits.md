# N1 (rest) and N0.2: addresses, frame limits from `bees.config`, the one reader

**Date:** 2026-11-10. **Compiler:** `silica-999926-macos-applesilicon` (the pin in `tools/silica.generation`, passed explicitly as
`SILICA_COMPILER`; the tree's `binaries/silica-compiler` link points at `silica-999925` since 10:04 that day and was not used).
**macOS / Apple Silicon only. Nothing in `/Users/yenrab/silica` was changed.** Companion: [mvp.md](../mvp.md) N0 and N1 rows,
[bees-config-file.md](../bees-config-file.md) sections 4, 5.4 and 11, [silica-defects.md](../silica-defects.md) (2026-11-10, N0.2/N1).

## 1. What the language's carrier supports (read in the Silica tree, read-only)

Read: `compiler/stdlib/dangerous_tcp_carrier.silica`, `compiler/stdlib/dangerous_sockets.silica`, `compiler/stdlib/net/silica_sockets.c`
(the tree at commit `3b0d647930`, 2026-11-10 13:48; the `listen:any` form arrived in `76ae8e92e1` that afternoon, during this work),
and the transport design 6.2 and 6.3.

| Question | Answer | Where |
| --- | --- | --- |
| Dial a non-loopback address | **Yes, any IPv4 literal.** `"host:port"`: the host is the text before the first `:`, the port the digits after it; `silica_sockets_tcp_connect` does `inet_pton(AF_INET, host)` and `connect`. | `host_of`, `port_of`; `silica_sockets.c` `silica_sockets_tcp_connect` |
| Dial an IPv6 literal | **No.** `AF_INET` only, and `"::1:4369"` splits at the first `:` (host `""`). | same |
| Dial a DNS name (A or AAAA) | **No, by design: name resolution is BEES's (user ruling 2026-11-12), not the language's.** The carrier dials literals; a name given to it fails `inet_pton` (EINVAL) and answers `(:link_down, :fault)`. BEES resolves names before dialing (below). | same |
| Listen on a non-loopback address | **Only on every IPv4 interface:** `"listen:PORT"` binds `127.0.0.1` (`INADDR_LOOPBACK`), `"listen:any:PORT"` binds `0.0.0.0` (`INADDR_ANY`). No form binds one specific address, an IPv6 address or a name ("until interface binding exists", transport design 6.3). | `tcp_listen_on`, `silica_sockets_tcp_listen_any` |
| The accepted peer's address | Not reported (`(:link_up, "peer:accepted")`). | carrier `link_up` text |
| Writing to a peer that closed | **Since Silica commit 71009f96f8 (2026-11-12): a failed write.** The carrier reports the link down and ends (`SO_NOSIGPIPE` on macOS, `send(MSG_NOSIGNAL)` on Linux). Until then the process died of SIGPIPE (found by `trials/n1_frames`, SD-42, now resolved). | `silica_sockets_send`, `write_no_sigpipe` |

**What BEES does with it.** Everything the carrier does is used: `listen_address "127.0.0.1"` (or `"localhost"`) becomes
`listen:PORT`, `"0.0.0.0"` becomes `listen:any:PORT`, a dial host that is an IPv4 literal is dialed as it is. Where the carrier
does not reach:

- **DNS names: a BEES native-edge part, kept small.** `native/src/silica_bees_resolve.c` (getaddrinfo of libSystem, about 50 lines,
  no download) answers one ETF binary: `ok <first IPv4> <n4> <n6>` or `dns_error <reason>` (a name with only AAAA records is
  `dns_error no_ipv4 <n6>`, because the carrier cannot dial IPv6). The worker `src/shim/dangerous_bees_resolve.silica` makes the
  one tainted cast; `src/shim/bees_resolve_edge.part` (pasted by `tools/bees_edge_gen.py --resolve`) decodes the answer with the
  language's `decode((:etf), ...)` in a produces-pure block and opens the carrier with the IPv4 literal. Wired into the dialers of
  M3's node (`bees_node_edge.part`) and BEAM mode's node (`beam_node_edge.part`); a node built without `--resolve` gets
  `bees_resolve_none.part`, which refuses a name loudly. Not wired: TRUST's `trpc` (its pins must be loopback literals while it is
  plaintext-only), and an EPMD lookup by name (refused by the reader: `is a name and the port is epmd`). getaddrinfo blocks the
  worker's thread and has no timeout; `trust.dns_*` are not applied (gap).
- **IPv6 (dial and listen), and binding one specific address: recorded as requests to Silica** (silica-defects.md SR-1, SR-2),
  refused by the reader as "not built yet" with the reason.

## 2. The loopback rule is now a rule of the test settings

`beam.auth none` and `trust.plaintext_test_only` (no authentication, no encryption) accept loopback addresses only (`127.0.0.0/8`,
`::1`, `localhost`) for `listen_address`, every peer host and every pinned server; anything else is refused by the reader:
`bees.config:LINE: beam.listen_address: 0.0.0.0 is not a loopback address, and auth none is a loopback-only test setting (no
authentication, no encryption; a non-loopback address needs TLS or authentication)`. A node built from the manifest alone (M3's)
is auth none and follows the same rule (`bees_conf.manifest_only`); the manifest reader no longer refuses non-`127.0.0.1` hosts by
itself. `tools/bees_edge_gen.py` refuses to build M3's node (`dangerous_bees_net`, no cookie) from a `bees.config` that says
`auth cookie`. Tests: `tools/test_bees_conf.py` (class `N1`).

## 3. Trials

**`trials/n1_addr`** (BEAM mode with cookies, N2's node and roles; ports 4745x). Goldens read and recorded; this machine's
non-loopback address is written into the configs by the leaves' Makefiles (`ipconfig getifaddr en0`), so it is in no golden.

| Scenario | Result |
| --- | --- |
| `loop_only` | a listens on 127.0.0.1 only; b dials this machine's non-loopback address: `link down, proxies ended; reason fault`, a sees nothing. |
| `name` | n dials `localhost`: `[bees] resolve localhost: ok 127.0.0.1 1 1`, the cookie handshake completes, `inbox got op=inc n=41`. |
| `dns_error` | e dials `no-such-host.invalid`: `[bees] resolve no-such-host.invalid: dns_error nodename nor servname provided, or not known`, nothing dialed, no crash, the program runs on until told to exit. |
| `any_ip` (opt-in, `make -C trials/n1_addr any_ip`, no golden) | w listens on `0.0.0.0` and v dials the non-loopback address. **Not run:** the session's sandbox refused to start a listener on every interface ("expose local services"). Running it is the user's decision. |

`::1`: the host has it (`lo0`), but the carrier cannot use it, so there is nothing to run; the reader refuses it (test).

**`trials/n1_frames`** (M3's auth-none node, loopback; node a's `frame_size_max` 9 MiB, node b's 4294967295, BEAM's): b sends
`{ seq, blob }` of 64 KiB, 1 MiB and 8 MiB; a echoes each whole; then 10 MiB, above a's cap: a writes `bad frame length, link closed
too_large 5` (refused from the 4-byte length) and b's write fails: **since Silica 71009f96f8 (2026-11-12) b sees `link down, proxies
ended; reason link_down 3` and exits 0** (before it, b was killed by SIGPIPE, exit -13, SD-42, a golden that was flaky); the golden
was re-recorded after four identical runs.
`make measure` (one run each, this machine, `/usr/bin/time -l`, not a benchmark):

| Run | Round trip (cast to answer) | Peak resident set a / b |
| --- | --- | --- |
| 64 KiB and 1 MiB only | 64 KiB: 10 ms; 1 MiB: 67 ms | 22.7 MiB / 31.7 MiB |
| 64 KiB, 1 MiB, 8 MiB, then 10 MiB refused | 9 ms; 67 ms; **8 MiB: 4.48 s** | **628 MiB / 703 MiB** |

The 8 MiB round trip completes well inside ten minutes; the memory is the finding: SD-35 (an actor state with a heap value takes
the whole-state copy at every dispatch) applied to the per-frame assembler, whose `pending` string grows by one 64 KiB segment
per dispatch, so about 128 copies of a growing string are kept. b's cap of 4294967295 costs nothing (its peak with 64 KiB and
1 MiB frames is the same as with a 16 MiB cap). **The TRUST variant (an 8 MiB frame with 4 MiB `args`) was not run**: TRUST's
receive path uses the same `unframe` and assembler shape, so the same memory is expected; not measured.

**`trials/n1_limits`** (in memory, `frame_size_max` 65536 from its `bees.config`): `unframe` of a frame of exactly the cap gives
the frame, the 4-byte length of a frame one byte above, alone, is `too_large` (no body byte exists); with the cap 4294967295 the
length 4294967295 alone gives `more, pending bytes 4` (nothing allocated for the declared length); the generated `decode` takes
`{ s }` with a string of cap - 14 bytes (frame exactly 65536) and refuses one byte more as `too_large`; int64 max round-trips and
2^63 is `out_of_range`; 200,000 refusals of a frame one byte above the cap in one dispatch: **2.0 MiB peak resident set**
(`/usr/bin/time -l`), flat.

**The limits of bees-config-file.md 5.4, as built now:** frame: configurable to 4294967295, enforced before storing (tests above);
lists and strings: `max_length` = the frame cap, so bounded by the frame only; depth: the declared type's nesting plus one in BEAM
mode, `term_depth_max` in TRUST; tuples: the declared arity; atoms: 255 bytes, held atoms only (D16, unchanged); integers: 64 bits by
type. Remaining gaps and their reasons: memory (SD-35, about 75 times the frame at the peak), no big integers or non-ASCII atoms
(language and D16), IPv6 and specific-address binding (carrier, SR-1, SR-2). (A sender killed by SIGPIPE when the peer closes
mid-frame, SD-42, was resolved by Silica 71009f96f8 on 2026-11-12.)

## 4. Where the frame caps go (replacing the generator constants 4096/16/1024)

| Cap | Run time | Build time (decode literal) |
| --- | --- | --- |
| `beam.frame_size_max` | `bees_peers@frame_max()` / `beam_conf@frame_max()`: the `wireframe@unframe` cap of `dangerous_bees_net` and `dangerous_beam_net`, and the send cap `bees_dist@reg_send_body_max` of every generated proxy | `bees_msgs`: `{ max_bytes: cap, max_depth: type depth + 1, max_length: cap }` (`tools/bees_dist_gen.py`) |
| `trust.frame_size_max` | `bees_trust_conf@frame_size_max()`: the TRUST assembler's `unframe` cap, the reply parser's | |
| `trust.args_len_max`, `trust.term_depth_max` | BEES's structural check before any value is decoded (`parse_first`, `parse_req`) | `bees_trust_mfa`: `{ max_bytes: args_len_max + 1, max_depth: term_depth_max, max_length: args_len_max }` (`tools/bees_trust_gen.py mfa --config`) |

The 4096 that remain: `bees_dist@max_body()` for the raw test peers of M3/M4 (`reg_send_body` without a cap), and
`bees_trust_frame@dec_str`'s bound on the token and `req_id` (fields of at most 64 and 16 bytes, not a frame cap).

## 5. N0.2: the one reader

`tools/bees_conf.py` replaces the two halves (`bees_config_beam.py` and `bees_config_trust.py` keep only their generators and CLIs
and call it; `bees_config.py generate --config` and `trial.mk` pass a leaf's `bees.config` to it for the node units). Unified
messages: `N is below LO (bounds LO to HI; never clamped)`, `N is above HI ...`; the top-level unknown key's PATH is the key itself.
Tests: `tools/test_bees_conf.py` (21: the document's tables against the reader's, the worked example read back, one rejecting case
per rule, no `sys.config`, N1), `tools/test_bees_config_trust.py` (13) and `tools/test_beam_dist.py` (15) updated for the unified
messages and the lifted cap. The M3/M4 trials now run from a `bees.config` (`mode beam`, `auth none`, `listen_address
"127.0.0.1"`, `frame_size_max 4096`) with unmoved goldens; **their timing stays in the roles**, because they use sub-4-second test
timings (1.5 s, 3 s, no ticks) below `beam.net_ticktime_s`'s bound and different per program of one node. N2's and N3's configs
gained `{frame_size_max, 4096}` so their behaviour is unchanged; N3's boot summary lost "(build limit 4096 until N1)" (five
goldens, that line only). Build-time stand-in and the proposal for a boot-time reader: bees-config-file.md section 11 (not built:
the user ruled it another agent's responsibility).
