/* BEES native edge for TEMPUS (milestone T4, development-plan/tempus-design.md section 4): Ed25519 and SHA-512; and the
 * system clock of a node that is not a test node (ruling NQ-11).
 *
 * Hosted platforms only: the functions call the programmer-installed OpenSSL (D40; libcrypto), the library TRUST's TLS
 * link already uses. The boards' Mbed TLS has no Ed25519 (design NQ-6), so this file is not built for them.
 *
 * Shapes follow native/trust: every function takes ONE byte string (pointer and length; a foreign function that mixes
 * scalars with a pointer-and-length pair cannot be called from Silica, SD-30), so several inputs travel concatenated, each
 * of a fixed length except the last. A result that is bytes comes back as one whole ETF binary term (131 109 len bytes),
 * which the receiving Silica actor passes through the language's decode: that is where an FFI-derived value becomes a
 * pure one. The caller frees nothing: a returned buffer is malloc'd and handed to Silica as the wrapper metadata says.
 *
 * NOT YET WIRED: no existing makefile builds this file and no sidecar (dangerous_exposure_source/tempus/) exists yet; see
 * development-plan/tempus-design.md section 15. native/tempus/selftest checks the functions by themselves.
 */
#ifndef SILICA_BEES_TEMPUS_H
#define SILICA_BEES_TEMPUS_H

#include <stdint.h>

typedef struct { int64_t tag; const uint8_t *text_ptr; uint64_t text_len; int64_t error_code; } bees_tempus_bytes;
typedef struct { int64_t tag; int64_t value; int64_t error_code; } bees_tempus_tagged;

/* input: public key (32) || signature (64) || message (1 to 4096). value 1 when the signature is that key's over the
 * message, 0 when it is not; tag 1 (error_code EINVAL) when the input is not of that form. */
bees_tempus_tagged bees_tempus_ed25519_verify(const uint8_t *ptr, uint64_t len);

/* input: private key seed (32) || message (1 to 4096). The 64-byte signature as an ETF binary. */
bees_tempus_bytes bees_tempus_ed25519_sign(const uint8_t *ptr, uint64_t len);

/* input: private key seed (32). The 32-byte public key as an ETF binary. */
bees_tempus_bytes bees_tempus_ed25519_public(const uint8_t *ptr, uint64_t len);

/* input: 1 to 4096 bytes. Their SHA-512 (64 bytes) as an ETF binary: a peer's identity from its public key. */
bees_tempus_bytes bees_tempus_sha512(const uint8_t *ptr, uint64_t len);

/* The system (wall) clock, for a node that is not a test node (ruling NQ-11): the whole seconds since 1970-01-01 00:00:00
 * UTC as 8 bytes, most significant first, as an ETF binary. The input is not read (one byte string, as every function
 * here). tag 1 when the operating system does not answer, or answers a time before 1970: no time is made up. */
bees_tempus_bytes bees_tempus_wall_clock(const uint8_t *ptr, uint64_t len);

#endif
