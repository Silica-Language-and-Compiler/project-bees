# Spike S12: The TLS Engine

**Update 2026-11-10 (D40, user decision): the engines are OpenSSL (Apple platforms, Linux) and Mbed TLS (NUCLEO-L476RG and ESP32-S3), so this spike's rustls track is superseded: rerun its questions against OpenSSL and Mbed TLS, X25519MLKEM768 first. Fetching or building either still needs the user's explicit approval.**
**Status:** planned, not run. This document specifies the spike. Nothing has been built yet.
**Update 2026-11-06 (roadmap D36, D38).** (1) **Running this spike needs the user's explicit approval** (milestone N4.0): the no-downloads rule blocks fetching or building any TLS engine, and the choice of engine is a user decision that runs in parallel with N2 and N3. (2) TRUST's TLS carries **TRUST's own frames** (a 4-byte length and one ETF map each); it is not wrapped around the Erlang distribution stream, which is how earlier text read. (3) BEAM mode's cookie authentication (N2) needs no TLS; its optional `inet_tls_dist`-compatible profile (D25) is a later use of the same engine. (4) Whatever the engine returns (plaintext, random bytes, digests) follows the conversion rule: handled in the `sequence` of a `sequence ... produces pure` block (mvp.md section 4).
**Decision it confirms:** D6, revised 2026-09-17: rustls on the hosted targets, the board's Mbed TLS on the ESP32-S3, behind one C
interface ([roadmap §6](../roadmap.md#6-decisions)).
**What it settles first:** which C TLS library the ESP32-S3 uses. The board's Mbed TLS if it offers X25519MLKEM768, which
TRUST's profile requires; otherwise a different C library that does (wolfSSL is the first candidate to check).

---

## 1. Purpose

TRUST can't run without TLS, so the TLS engine is on the critical path for B1. BEAM mode's default transport is TLS
too (D25), so the same engine is on the path for B3. D6 chose rustls on the hosted targets and the board's own Mbed TLS on the
ESP32-S3 (D29). This spike checks that choice before B1 and B3 depend on it. It answers five questions:

1. Can rustls on the hosted targets, and Mbed TLS on the ESP32-S3, meet the TRUST TLS profile behind one small C
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
| R6 | No 0-RTT, renegotiation or compression | Configuration review (rustls doesn't implement renegotiation or compression) |
| R7 | ALPN `trust/1`, enforced | A peer offering another ALPN is refused; a peer offering none is refused by the interface's check after the handshake |
| R8 | The peer's certificate DER and its SHA-512 are available (D11), and so are the client-side pins | The interface returns both, and the fingerprint matches one computed separately |
| R9 | No transports of its own; ciphertext in, ciphertext and plaintext out | The test harness pumps bytes between two endpoints through memory buffers only |
| R10 | No callbacks into Silica (Fifi only calls outward) | Interface review: every function is called by Silica and returns |
| R11 | Every output can be re-created (S-5) | Outputs are flat byte buffers with explicit lengths, plus scalars |
| R12 | Builds for all four 1.0 targets (D29) | Per-target build (§5) |
| R13 | Fits the ESP32-S3 (about 512 KB SRAM) | Code size, and peak RAM during a handshake and a 1 MiB transfer |
| R14 | A secure random source and a clock on the ESP32-S3 | These come from the board's hardware RNG and clock through the native edge (D17). Certificate validity also needs wall-clock time, which the board has only after SNTP or a set-time call; the spike records what the edge does before then |
| R15 | Apache-2.0-compatible license | rustls is Apache-2.0, ISC or MIT; Mbed TLS and ESP-IDF are Apache-2.0 |
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
| Apple Silicon (macOS) | rustls 0.23 with `std`, `aws-lc-rs` provider | rustls's default features include `aws_lc_rs` and `prefer-post-quantum`. The spike turns off `tls12`, so only TLS 1.3 is built in, and narrows the key-exchange groups to X25519MLKEM768 and the cipher suites to R4. Building `aws-lc-rs` needs `cmake` and a C compiler. |
| Linux AArch64 | As above | Needs a Linux AArch64 machine, or a cross sysroot for `aws-lc-sys`. |
| Linux x86_64 | As above | Needs a Linux x86_64 machine. The Silica side waits on S-32, but the edge can be built and tested on its own. |
| ESP32-S3 | A C TLS library: the board's Mbed TLS under ESP-IDF if it offers X25519MLKEM768, otherwise one that does (D6) | No Rust toolchain. The C interface in §3 is implemented twice, once over rustls and once over the board's library, and the same harness runs against both. |

**The ESP32-S3's key exchange is the main risk.** TRUST's profile requires X25519MLKEM768 (R3). **Relaxed for the two boards 2026-11-10 (D41):** they use classical X25519 with Mbed TLS.
The spike checks the Mbed TLS version ESP-IDF ships and whether it negotiates that group. If it does not, the spike
tries the candidates in order and reports the first that passes R1–R15 and fits (R13): a newer Mbed TLS built into
the edge, then wolfSSL, which has an ESP32 port and ML-KEM hybrid groups. D6 names the library the spike settles on.

## 5. How to run it (for whoever runs the spike)

| Target | Where | Installs needed (not done yet) |
| --- | --- | --- |
| macOS AArch64 | This Mac | The Rust crates (`rustls`, `aws-lc-rs`, `rcgen` for test certificates). `cmake` and `clang` are already present. |
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
