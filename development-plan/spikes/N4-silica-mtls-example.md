# N4: what Silica's mutual-TLS example teaches BEES's TRUST

**Status: written 2026-11-12, before and during N4.1's first build (macOS on Apple Silicon only).** Source read (read-only): the
Silica tree's `examples/transport_pairs/ethernet_direct_mtls/` (README, `dangerous_tls.silica`, `dangerous_tls_carrier.silica`,
`net/silica_tls.c`, `net/silica_tls_wrapper.meta`, `make_cert.sh`, `run_mtls.sh`), `examples/transport_pairs/README.md`,
commit 00c787323c (the example) and commit 71009f96f8 (the carrier fixes made in answer to BEES's SD-42). The BEES side it is
compared with: [inter-nodal-modes.md](../inter-nodal-modes.md) section 3, [mvp.md](../mvp.md) N3 and N4,
[N3-trust.md](N3-trust.md), [S12-tls-engine.md](S12-tls-engine.md), roadmap D11, D27, D40, D41, and
[contract/what-is-required-to-use.md](../../contract/what-is-required-to-use.md). What was built from it is in section 5 and in
mvp.md's N4 row.

## 1. What the example does

- **Two Silica programs, one connection, mutual TLS 1.3** (Mac to Linux, or both on the Mac with `--local`). The program is
  `ethernet_direct`'s; only the carrier differs.
- **TLS sits below the carrier contract.** `dangerous_tls_carrier.silica` is the standard `(:tcp)` carrier's text with
  `dangerous_sockets@` read as `dangerous_tls@`. The wrappers (`net/silica_tls.c`) replace `silica_sockets.c`'s calls: `tcp_connect`
  and `tcp_accept` run the TLS handshake on the descriptor (`SSL_set_fd`), `send_bytes` and `recv_bytes` carry TLS records. The
  owner of the carrier speaks plain carrier messages and never sees TLS.
- **Identity**: the node's existing OpenSSH ed25519 key (`~/.ssh/id_ed25519`), read in memory; a self-signed X.509 certificate over
  it, made once by hand (`make_cert.sh`), kept in `~/.silica_mtls/own.cert.pem`.
- **Trust**: no certificate authority. A peer is accepted when the **SHA-512 of the certificate it presents equals the SHA-512 of
  one of the files in `~/.silica_mtls/peers/`** (`X509_digest(x, EVP_sha512())`, the DER) and the certificate is within its dates;
  a custom `SSL_CTX_set_cert_verify_callback` replaces chain building. Both sides demand a certificate
  (`SSL_VERIFY_PEER | SSL_VERIFY_FAIL_IF_NO_PEER_CERT`).
- **Profile**: TLS 1.3 minimum; no session tickets (`SSL_CTX_set_num_tickets(c, 0)`); `SSL_MODE_AUTO_RETRY` cleared so a readable
  socket with no application bytes answers "nothing yet". **No ALPN, no group list, no cipher-suite list, no signature list**: the
  rest is OpenSSL's defaults.
- **Refusals** never reach Silica: `accept` answers "no peer this time" (a timeout), `connect` answers an error, and the reason is
  printed by the C on stderr. In TLS 1.3 a refused client finishes its own handshake first and learns of the refusal on its first
  read.
- **SIGPIPE**: `SO_NOSIGPIPE` on macOS, the signal held around `SSL_write` on Linux (the same problem as BEES's SD-42, solved in the
  wrapper; commit 71009f96f8 then solved it in the language's own socket wrapper).
- **OpenSSL**: "OpenSSL 3" (Homebrew `openssl@3`, linked `-lssl -lcrypto` from `brew --prefix openssl@3`); checked with 3.6.2 on the
  Mac and 3.5.3 on Linux; the programmer installs it.
- **Tainted bytes**: received bytes come back through `take/1` as a string and reach the owner in the carrier's one FFI result
  cast; every scalar result is re-created (`pure_int(recreate(...))`) before it decides anything.

## 2. What it negotiates (checked on this Mac, 2026-11-12, OpenSSL 3.6.2, 127.0.0.1 only)

The example sets no group list, so its key exchange is OpenSSL's default. With `openssl s_server`/`s_client` (the same library
defaults) both at 3.6.2: **`Negotiated TLS1.3 group: X25519MLKEM768`, `TLS_AES_256_GCM_SHA384`, ed25519 signatures.** But a client
that offers only X25519 (`-groups X25519`) is **accepted** (`Peer Temp Key: X25519`). So the example gets the hybrid group between
two OpenSSL 3.5+ ends by default, and **does not refuse classical-only peers**; it cannot meet TRUST's R3 as written. BEES's
engine sets the group list to `X25519MLKEM768` alone, and its selftest shows a classical-only client refused (section 5).

## 3. What N4.1 takes from it (as is, or adapted)

| From the example | In BEES | How |
|---|---|---|
| SHA-512 of the certificate's DER (`X509_digest(EVP_sha512)`) as the peer's identity | **as is**: it is D11 | `native/tls/silica_bees_tls.c` `after_handshake`; equal to `openssl x509 -fingerprint -sha512` (selftest case 2) |
| Both sides demand a certificate; refusals never reach the program | **as is** | `SSL_VERIFY_PEER | SSL_VERIFY_FAIL_IF_NO_PEER_CERT`; a refused handshake gives the owner `(:link_down, _)` and no TRUST byte |
| No session tickets | **as is** (D27 is open; TRUST also refuses 0-RTT) | `SSL_OP_NO_TICKET`, `num_tickets 0`, `max_early_data 0`, session cache off |
| The wrapper shape: the dangerous_sockets names and answers (`{tag, value, error_code}`, tag 2 nothing yet, 3 closed; `take/1` for bytes; `set_args` for scalars before a pointer-plus-length pair) | **adapted** | `dangerous_bees_tls_native.silica`, same conventions, different calls (memory buffers, section 4) |
| `recreate` of every FFI scalar before it is used | **as is** | both TLS workers |
| TLS 1.3, failure on a peer that answers nothing within a bound | **adapted** | the engine is TLS 1.3 only (min and max); the handshake bound is `trust.client_handshake_timeout` (a timer in the link worker), not `SO_RCVTIMEO` |
| The certificate is made once and kept; peers are files the operator places | **adapted** | the whitelist's certificates and the pin file's certificates are files under `whitelist_cert_dir` (SEMP's form, already read by N3) |
| SIGPIPE handling | **taken by the language** | Silica 71009f96f8 puts `SO_NOSIGPIPE` (macOS) and `MSG_NOSIGNAL` (Linux) into the language's own socket wrapper, which BEES's carrier uses |

## 4. Where it differs from the BEES TRUST design, and what BEES does

| Topic | Example | BEES design | BEES N4.1 does | Needs the user? |
|---|---|---|---|---|
| **Where TLS sits** | In the wrapper, under the carrier: the TLS engine **owns the descriptor** (`SSL_set_fd`) | Between the carrier and TRUST's framing; the engine owns **no transport** (S12 R9) and makes no callback (R10) | **The design.** The language's `(:tcp)` carrier stays the only transport; the engine is an SSL object between two memory BIOs; a TLS link worker feeds it the carrier's ciphertext and hands the carrier the engine's | No (design followed). The example's shape is simpler (one copied carrier) but copies the carrier's text, which then "does not follow later changes to it" (its README) |
| **Identity and the CA** | No CA; trust is the SHA-512 pin alone; the node key is its ssh key | `tls_opts` with `certfile`, `keyfile`, **`cacertfile`** (all three required); "the client CA must be configured explicitly" (3.2) **and** the whitelist by SHA-512 (3.3) | Both: the chain must verify against `cacertfile` only (no system store), **then** the whitelist (server) or the pin (client) decides. The trials use a test CA | **Yes (decision N4-1):** with D11 fingerprints the CA adds little; the example shows a pin-only model works. Keep the CA (two checks), make `cacertfile` optional (pin-only when absent), or drop it? |
| **ALPN** | None | `trust/1` required; anything else closes | Client offers only `trust/1`; server selects only it (no_application_protocol alert otherwise) and both refuse a finished handshake without it | No |
| **Key exchange** | OpenSSL default: X25519MLKEM768 between 3.5+ ends, **classical X25519 accepted** | X25519MLKEM768 only on hosted nodes; classical refused (R3); boards relaxed to X25519 (D41) | Group list `X25519MLKEM768` only; classical-only refused | **Open already (D41):** whether a hosted node accepts X25519 from configured board peers. N4.1 refuses it |
| **Suites and signatures** | Defaults (any TLS 1.3 suite; ed25519 because of the key) | AES-256-GCM or ChaCha20-Poly1305; Ed25519 or ECDSA P-256 | Both lists fixed in the engine; an RSA certificate is refused | No |
| **Pins** | Every accepted peer is a file in `peers/`; any accepted peer may be dialled from anywhere | Client pins per **dialled address** (`server_pins_file`, `#{"host:port" => "server-cert.pem"}`), `server_not_pinned` | Per address, compared in constant time inside the engine after the handshake; the client then sends nothing (not even its Finished) | No (format is BEES's, N3 decision 8) |
| **Whitelist** | Accept/refuse only; no permissions | SEMP's whitelist: certificate → permission spec; suspicion, quarantine, tokens | N3's logic unchanged: the server's link hands the peer's 64-byte fingerprint up as the first plaintext, where N3 read its test-only stand-in | No |
| **Refusal reporting** | `fprintf(stderr, ...)` in the C | One audit line per refusal with the names of 3.11 (`alpn_mismatch`, `tls_verify_failed`, ...); no detail to the peer | Small integer codes from the engine; the audit line is written by the link's owner (an FFI worker may not print, E2103) | No |
| **OpenSSL version** | "OpenSSL 3" (3.6.2 / 3.5.3) | OpenSSL **4.1.0 or later** on hosted platforms (contract) | **4.1.0 is the minimum, with no exception (ruled by the user 2026-11-12):** the engine's C stops at compile time below it (`#error` on `OPENSSL_VERSION_NUMBER < 0x40100000L`), `native/Makefile` refuses to build the archive against an older OpenSSL or none, naming what it found, and the TLS link refuses at run time when the library it loaded is older (the C reports the version, Silica decides). The trials that need TLS fail with that message; nothing skips. The first N4.1 runs used Homebrew's 3.6.2 under a development allowance that has since been removed; everything was then re-run on OpenSSL 4.1.0 (23 Oct 2026, Homebrew) | No (ruled) |
| **Programmer installs OpenSSL** | Yes (Homebrew / libssl-dev); nothing fetched | Yes; BEES ships none (D40) | Yes: `OPENSSL_PREFIX`, default Homebrew's `openssl`; BEES fetches and builds nothing | No |
| **Name resolution** | IPv4 literal only (`inet_pton`) | BEES's own resolver edge (N1) | Unchanged: the TLS link dials what the carrier dials; names go through BEES's resolver before (N1) | No |
| **Tainted bytes** | One worker (the carrier) makes the one FFI result cast (received bytes to the owner); sent bytes go out through an FFI call | Conversion inside `sequence ... produces pure`; every FFI output re-created | **Two FFI workers per connection** (section 5): the language allows one tainted cast site per worker body, and a memory-BIO link has two outputs (plaintext up, ciphertext down) | No, but it is a language finding (SD-44) |

## 5. What N4.1 built from this, briefly

- `native/tls/silica_bees_tls.c` (+ header and sidecar under `native/dangerous_exposure_source/tls/`): the engine; memory BIOs,
  TRUST profile fixed, handles with a generation number, a lock per connection (two workers use it).
- `src/trust/dangerous_bees_tls_native.silica`: the bindings. `src/trust/dangerous_bees_tls.silica`: **`ttls`**, the link (carrier
  owner; handshake, read, plaintext to its owner, the one tainted cast) and **`ttlsw`**, the writer (write, pull, ciphertext to the
  carrier, one write in flight, close and free). Upward the link speaks the carrier contract, so TRUST's N3 actors are unchanged
  but for three small things: the client does not send the stand-in over TLS, a `server_not_pinned` link-down answers the call
  with that status, and the link's audit lines are written by its owner.
- `src/shim/bees_trust_link_tls.part` / `bees_trust_link_plain.part`, chosen by `tools/bees_trust_gen.py` from the node's
  generated configuration: a plaintext node needs no OpenSSL.
- `tools/bees_conf.py` and `tools/bees_config_trust.py`: mode trust without `plaintext_test_only` is now TLS (tls_opts required with
  all three keys; non-loopback addresses allowed; pins must name a readable certificate); the generated unit carries the engine's
  paths and each pinned server's fingerprint.
- `trials/n4_trust_tls`: the engine selftest (12 cases), N3's scenario set and negative suite over TLS, the node killed, a wrong
  pin (`server_not_pinned`), and ten refusals driven by `openssl s_client`.

## 5a. After the first build (2026-11-12, later): memory, rate, and the thinner C

- **Memory.** The first 2,000-call TLS run peaked at 2.1 GB on the server. Every actor and every engine connection ended
  (counted with temporary instrumentation); the memory was the listening link's: the link behaviour `ttls` has W2300 ("the
  result shape is not analysed", a whole-state copy per dispatch) and, as a node-long listener, it kept about 1 MiB per accepted
  connection (SD-35). The listener is now its own plain behaviour `ttlsl` (state: two references); the run peaks at **37.9 MiB
  (server) and 37.4 MiB (client)**. A 1 MiB `_Thread_local` read buffer in the engine was replaced by a one-record malloc'd span
  at the same time (the client dropped from 55 to 31 MiB).
- **OpenSSL 4.1.0.** The user installed OpenSSL 4.1.0 (Homebrew, `/opt/homebrew/opt/openssl`) and ruled 4.1.0 the minimum with
  no exception; the development allowance used for the first runs on 3.6.2 is removed from the C, the Makefile, the generated
  configuration and the audit lines. On 4.1.0 the engine builds without a warning, the selftest passes 12 of 12, the programs link
  `libssl.4.dylib`, and `trials/n4_trust_tls` passes with its goldens unchanged (X25519MLKEM768 and TLS_AES_256_GCM_SHA384 again); (f) on 4.1.0: 2,000 calls in 50.0 s,
  peak 37.8 MiB (server) and 37.0 MiB (client).
- **Rate.** 2,000 TLS calls take 45 to 50 s (40 to 45 per second; N3's plaintext 5.1 s). Cause: the language's carrier sleeps
  20 ms between polls while it holds no receive credit, and the link grants credit only when its owner asks (the SD-43
  mitigation), so most round trips wait for the carrier's next poll. Not changed; it is a choice for the user once SD-43 is
  settled (silica-defects.md, 2026-11-12).
- **The C is a thin shim now** (user request): the handle table, the version rule, the post-handshake judgement (ALPN, certificate,
  verify result), the group and suite names, the server's fingerprint hand-up and the client's pin moved into
  `dangerous_bees_tls@ttls`; the paths are bytes the generated configuration writes. C: 472 lines (383 code) before, 392 (304
  code) after; the link's Silica 530 (437 code) before, 587 (482 code) after, its bindings 91 before, 129 after. What stays in C and
  why: the SSL_CTX and its fixed profile, the memory BIOs, the handshake with OpenSSL's reasons turned into small codes,
  SSL_read/SSL_write, certificate verification, the SHA-512 of the DER, the ALPN callback, the per-connection lock, freeing; and the
  FFI's own conventions (the thread's answer span read by `take`, `{ tag, value, error_code }`, scalars before a
  pointer-plus-length pair). The pin is now compared in Silica as hex text, not in constant time (both values are public).
  Each step was followed by `trials/n4_trust_tls` (9 of 9 each time; the selftest golden was re-recorded once, after reading it,
  because its cases now check the reported facts rather than C-side refusals).

## 6. Linux and boards (deferred)

The engine's C is POSIX and OpenSSL only (no macOS call); it has not been built on Linux. The boards' Mbed TLS engine (D40, D41) is
not started. The example's Linux end (OpenSSL 3.5.3, SIGPIPE held around `SSL_write`) shows the Linux path BEES would take; BEES
does not need the SIGPIPE hold because its engine never touches a descriptor.
