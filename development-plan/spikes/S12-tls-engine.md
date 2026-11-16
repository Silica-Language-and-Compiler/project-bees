# Spike S12: The TLS Engine

**Update 2026-11-10 (D40, user decision): the engines are OpenSSL (Apple platforms, Linux) and Mbed TLS (NUCLEO-L476RG and ESP32-S3), so this spike's rustls track is superseded: rerun its questions against OpenSSL and Mbed TLS, X25519MLKEM768 first. Fetching or building either still needs the user's explicit approval.**
**Status 2026-11-12: the hosted half is built and run on macOS (Apple Silicon) against OpenSSL 4.1.0 (23 Oct 2026, installed
by the user with Homebrew; BEES downloads and builds no TLS library). 4.1.0 is the minimum, with no exception: the C stops at
compile time below it, `native/Makefile` refuses an older OpenSSL by name, and the TLS link refuses an older library at run time.**
(The first runs, the same day, used Homebrew's 3.6.2 under a development allowance that the user then had removed.) The engine is `native/tls/silica_bees_tls.c` (memory BIOs: no transport, no callback, small integer
status codes, flat byte outputs); its in-memory test is `native/tls/selftest` (`make -C native tls-selftest`, golden
`trials/n4_trust_tls/selftest.scout`). Passed: R1 (a TLS 1.2-only client refused), R2 (no client certificate refused; a certificate
from another CA refused; an expired one refused), R3 (X25519MLKEM768 negotiated; an X25519-only client refused), R4 (the
configuration allows only AES-256-GCM and ChaCha20-Poly1305; AES-256-GCM negotiated), R5 (Ed25519 and ECDSA P-256 certificates
complete; RSA refused), R6 (configuration: TLS 1.3 only, no tickets, no early data, no renegotiation, no compression), R7 (ALPN
`trust/1` enforced; another ALPN and none refused), R8 (the peer's SHA-512 equals `openssl x509 -fingerprint -sha512`; client pins),
R9, R10, R11, R15. Not run: R12 (Linux, boards), R13, R14 (boards), R16 (the BEAM-mode profile), the measurements of section 6. The C interface differs from section 3's sketch in its calls (Fifi's rules: a pointer-plus-length pair only as a
binding's sole parameters, scalars passed first) but keeps its rules. See [N4-silica-mtls-example.md](N4-silica-mtls-example.md).
Text of 2026-11-06: planned, not run. This document specifies the spike. Nothing has been built yet.
**Update 2026-11-06 (roadmap D36, D38).** (1) **Running this spike needs the user's explicit approval** (milestone N4.0): the no-downloads rule blocks fetching or building any TLS engine, and the choice of engine is a user decision that runs in parallel with N2 and N3. (2) TRUST's TLS carries **TRUST's own frames** (a 4-byte length and one ETF map each); it is not wrapped around the Erlang distribution stream, which is how earlier text read. (3) BEAM mode's cookie authentication (N2) needs no TLS; its optional `inet_tls_dist`-compatible profile (D25) is a later use of the same engine. (4) Whatever the engine returns (plaintext, random bytes, digests) follows the conversion rule: handled in the `sequence` of a `sequence ... produces pure` block (mvp.md section 4).
**Decision it confirms:** D40 (2026-11-10), which supersedes D6 (rustls, struck below): earlier, D6, revised 2026-09-17: rustls on the hosted targets, the board's Mbed TLS on the ESP32-S3, behind one C
interface ([roadmap §6](../roadmap.md#6-decisions)).
**What it settles first:** which C TLS library the ESP32-S3 uses. The board's Mbed TLS if it offers X25519MLKEM768, which
TRUST's profile requires; otherwise a different C library that does (wolfSSL is the first candidate to check).

---

## 1. Purpose

TRUST can't run without TLS, so the TLS engine is on the critical path for B1. BEAM mode's default transport is TLS
too (D25), so the same engine is on the path for B3. D6 chose rustls on the hosted targets and the board's own Mbed TLS on the
ESP32-S3 (D29). This spike checks that choice before B1 and B3 depend on it. It answers five questions:

1. Can OpenSSL on the hosted targets, and Mbed TLS on the boards (D40),
   interface? On the ESP32-S3 the first check is X25519MLKEM768 (R3).
2. Does it fit BEES's I/O model: no transports of its own, no callbacks into Silica, and every output re-created?
3. What does it cost in code size and RAM, especially on the ESP32-S3?
4. Which C TLS library on the ESP32-S3 meets the TRUST profile, X25519MLKEM768 included?
5. Can the same interface also offer the BEAM-mode compatibility profile (inter-nodal-modes §4.5), so that stock OTP
   `inet_tls_dist` connects?

## 2. Requirements

These come from the TRUST profile (inter-nodal-modes §3.2), the BEAM-mode compatibility profile (§4.5), D11, D17
and the native-edge rules (gap ledger §4).

| # | Requirement | How the spike checks it |
| --- | --- | --- |
| R1 | TLS 1.3 only; TLS 1.2 refused | A client that offers only TLS 1.2 fails the handshake |
| R2 | Both sides present certificates (mTLS); the server requires a client certificate | A client with no certificate is refused; a client certificate from another CA is refused |
| R3 | Key exchange **X25519MLKEM768** only; classical-only peers refused. **Relaxed 2026-11-10 (D41) on the NUCLEO-L476RG and ESP32-S3: classical X25519.** | The negotiated group is reported as `0x11EC`; a client offering only X25519 is refused |
| R4 | Ciphers AES-256-GCM or ChaCha20-Poly1305 only | The negotiated suite is reported; the configuration allows no others |
| R5 | Certificates Ed25519 or ECDSA P-256 | Both kinds of certificate complete the handshake |
| R6 | No 0-RTT, renegotiation or compression | Configuration review (TLS 1.3 only; OpenSSL and Mbed TLS option settings) |
| R7 | ALPN `trust/1`, enforced | A peer offering another ALPN is refused; a peer offering none is refused by the interface's check after the handshake |
| R8 | The peer's certificate DER and its SHA-512 are available (D11), and so are the client-side pins | The interface returns both, and the fingerprint matches one computed separately |
| R9 | No transports of its own; ciphertext in, ciphertext and plaintext out | The test harness pumps bytes between two endpoints through memory buffers only |
| R10 | No callbacks into Silica (Fifi only calls outward) | Interface review: every function is called by Silica and returns |
| R11 | Every output can be re-created (S-5) | Outputs are flat byte buffers with explicit lengths, plus scalars |
| R12 | Builds for all four 1.0 targets (D29) | Per-target build (§5) |
| R13 | Fits the ESP32-S3 (about 512 KB SRAM) | Code size, and peak RAM during a handshake and a 1 MiB transfer |
| R14 | A secure random source and a clock on the ESP32-S3 | These come from the board's hardware RNG and clock through the native edge (D17). Certificate validity also needs wall-clock time, which the board has only after SNTP or a set-time call; the spike records what the edge does before then |
| R15 | Apache-2.0-compatible license | OpenSSL 3.x and later is Apache-2.0; Mbed TLS and ESP-IDF are Apache-2.0 |
| R16 | The BEAM-mode compatibility profile (TLS 1.3, X25519, ECDSA or RSA certificates, no ALPN requirement), selected per configuration, on the hosted targets | A stock OTP node of the release named in D14 connects with `inet_tls_dist` in both directions; the TRUST profile stays unchanged when the compatibility profile is not selected |

## 3. The C interface (`dangerous_bees_native` TLS entries)

The interface owns no transports and makes no callbacks. Silica reads and writes the network through its own TCP/IP
(S-22) on the hosted targets, and through the board's lwIP behind the edge on the ESP32-S3 (D29). It hands incoming ciphertext to the engine, takes outgoing ciphertext back, and re-creates everything the
engine returns (S-5) before the data is used or written to a transport.

```c
/* Configuration: PEM inputs and a profile. Each profile is fixed inside the engine:
 *   BEES_TLS_PROFILE_TRUST      TLS 1.3, X25519MLKEM768, the two AEADs, ALPN "trust/1", mTLS required.
 *   BEES_TLS_PROFILE_BEAM_DIST  TLS 1.3, X25519, ECDSA or RSA certificates, no ALPN: what inet_tls_dist speaks. */
bees_tls_config *bees_tls_server_config_new(int profile,
                                            const uint8_t *cert_pem, size_t cert_len,
                                            const uint8_t *key_pem,  size_t key_len,
                                            const uint8_t *ca_pem,   size_t ca_len);   /* client CA */
bees_tls_config *bees_tls_client_config_new(int profile,
                                            const uint8_t *cert_pem, size_t cert_len,
                                            const uint8_t *key_pem,  size_t key_len,
                                            const uint8_t *ca_pem,   size_t ca_len);   /* server CA */
void             bees_tls_config_free(bees_tls_config *);

/* Connections. */
bees_tls_conn *bees_tls_server_new(const bees_tls_config *);
bees_tls_conn *bees_tls_client_new(const bees_tls_config *, const uint8_t *server_name, size_t len);
void           bees_tls_conn_free(bees_tls_conn *);

/* Ciphertext in and out: no transports. */
int bees_tls_feed(bees_tls_conn *, const uint8_t *in, size_t len, size_t *consumed);  /* ciphertext from the peer */
int bees_tls_pull(bees_tls_conn *, uint8_t *out, size_t cap, size_t *written);        /* ciphertext for the peer */

/* Plaintext. */
int bees_tls_write(bees_tls_conn *, const uint8_t *in, size_t len, size_t *accepted);
int bees_tls_read (bees_tls_conn *, uint8_t *out, size_t cap, size_t *written);

/* State and peer information, available once the handshake completes. */
int bees_tls_handshake_done(const bees_tls_conn *);
int bees_tls_peer_cert_der(const bees_tls_conn *, uint8_t *out, size_t cap, size_t *written);
int bees_tls_peer_fingerprint_sha512(const bees_tls_conn *, uint8_t out[64]);
int bees_tls_alpn(const bees_tls_conn *, uint8_t *out, size_t cap, size_t *written);  /* must equal "trust/1" */
int bees_tls_kx_group(const bees_tls_conn *);        /* IANA group id; 0x11EC = X25519MLKEM768 */
int bees_tls_cipher_suite(const bees_tls_conn *);    /* IANA suite id */
```

Rules for the interface:
- Every function enforces hard size limits on its inputs.
- Status codes are small integers, never strings, and carry no peer-supplied detail.
- A handle (`bees_tls_conn *`) stays inside the one `spawn_dangerous` worker that owns the connection. It is never
  sent to another actor, following the native-edge rules in gap ledger §4.
- Once the byte-buffers-across-FFI item (S-21) lands, `buf(uint8)` crosses the boundary. Until then, bytes are
  packed in records of `uint64` words.

These spike-only hooks (a classical-only client, a client with no certificate, a client that offers TLS 1.2 only)
are built only in the test harness. They are never part of the edge's release build.

## 4. Engine per target

| Target | Engine | Notes |
| --- | --- | --- |
| Apple Silicon (macOS), Linux | **OpenSSL (D40, 2026-11-10; the programmer installs it, BEES ships none), at least 4.1.0** | Supersedes the rustls row. TLS 1.3 only, key-exchange group X25519MLKEM768 only, the cipher suites of R4. Random source: the platform's CSPRNG. Check with `openssl list -kem-algorithms`. See [contract/what-is-required-to-use.md](../../contract/what-is-required-to-use.md). |
| Linux AArch64 | As above | Needs a Linux AArch64 machine, or a cross sysroot for `aws-lc-sys`. |
| Linux x86_64 | As above | Needs a Linux x86_64 machine. The Silica side waits on S-32, but the edge can be built and tested on its own. |
| ESP32-S3 and NUCLEO-L476RG (bare metal) | **Mbed TLS (D40), latest release (4.2.0 on 2026-11-10); X25519MLKEM768 is not supported, so R3 is relaxed to classical X25519 on these boards (D41)** | No Rust toolchain. The C interface in §3 is implemented over OpenSSL (hosted) and Mbed TLS (boards), and the same harness runs against both. Random source: the STM32L476RG hardware RNG on the NUCLEO; the hardware RNG with its physical entropy source enabled on the ESP32-S3. wolfSSL supports the group but was not adopted (memory fit unmeasured). |

**The ESP32-S3's key exchange is the main risk.** TRUST's profile requires X25519MLKEM768 (R3). **Relaxed for the two boards 2026-11-10 (D41):** they use classical X25519 with Mbed TLS.
The spike checks the Mbed TLS version ESP-IDF ships and whether it negotiates that group. If it does not, the spike
tries the candidates in order and reports the first that passes R1–R15 and fits (R13): a newer Mbed TLS built into
the edge, then wolfSSL, which has an ESP32 port and ML-KEM hybrid groups. D6 names the library the spike settles on.

## 5. How to run it (for whoever runs the spike)

| Target | Where | Installs needed (not done yet) |
| --- | --- | --- |
| macOS AArch64 | This Mac | OpenSSL 4.1.0 or later, installed by the programmer (not fetched by BEES). `clang` is already present. rustls, `aws-lc-rs`, `rcgen` and `cmake` are no longer needed (D40). |
| Linux AArch64 | A Linux AArch64 host, such as the one used for Silica's Linux port | The Rust crates |
| Linux x86_64 | A Linux x86_64 host | The Rust crates |
| ESP32-S3 | This Mac plus an ESP32-S3 board | ESP-IDF, already under `~/.espressif`, with its Mbed TLS component; wolfSSL's ESP-IDF component if Mbed TLS fails R3. No Rust toolchain. |

The functional test pumps bytes between a client and a server entirely in memory (R9). It runs the positive case
and each negative case in §2. It then records the negotiated group and suite, the ALPN, and the peer fingerprint.

## 6. Measurements to record

- Handshake time and bytes exchanged. The hybrid group adds about 2 KB to the handshake, compared with X25519 alone.
- Throughput for a 1 MiB transfer in each direction.
- Size of the static library and of a minimal linked program, per target.
- Peak RAM during the handshake and the transfer, on the ESP32-S3.

## 7. Exit criteria and decision rule

- **D6 is confirmed** if R1–R15 pass on all four targets, R16 passes on the hosted targets, and the ESP32-S3 has
  room left for BEES.
- **If the ESP32-S3's Mbed TLS fails R3** (no X25519MLKEM768), the spike moves down the list in §4 and D6 names the
  library that passes.
- **If the hosted targets fail**, D6 is reopened.

## 8. What is known before running

Taken from crates.io metadata on 2026-09-15. Nothing has been built.

- The latest stable rustls is **0.23.45**, licensed Apache-2.0, ISC or MIT. Its default features include `aws_lc_rs`
  and `prefer-post-quantum`, and it has a `ring` alternative and a `custom-provider` feature. A `0.24.0-dev`
  pre-release also exists.
- rustls without `std` and the pure-Rust providers (`rustls-rustcrypto` at `0.0.2-alpha`) are no longer needed,
  since the ESP32-S3 uses a C TLS library (D6, D29). Which Mbed TLS version ESP-IDF ships, whether it offers
  X25519MLKEM768, and whether wolfSSL's ESP32 port does, have not been checked.
