/* BEES TRUST mode (N4.1): the TLS engine's Fifi wrappers (native/tls/silica_bees_tls.c), hosted targets, over the
   programmer-installed OpenSSL (D40; BEES ships no TLS library, contract/what-is-required-to-use.md).

   The engine owns NO transport (spike S12, R9): ciphertext comes in from the language's (:tcp) carrier through
   bees_tls_feed and goes back out through bees_tls_pull, both through memory buffers; plaintext goes in with
   bees_tls_write and comes out with bees_tls_read. It makes no callback into Silica (R10). A connection is named by a
   small integer handle that stays inside the one TLS worker that owns it (dangerous_bees_tls@ttls).

   Results: { tag, value, error_code } with tag 0 ok, 1 error, 2 nothing yet, 3 closed by the peer (the conventions of the
   language's silica_sockets.c); bytes land in a span private to the calling thread and bees_tls_take answers them as
   { tag, text_ptr, text_len, error_code } (a malloc'd span the compiler's string-out helper copies and frees). The FFI
   carries a pointer-plus-length pair only as a binding's sole parameters, so the scalars go first (bees_tls_set_args). */
#ifndef SILICA_BEES_TLS_WRAPPER_H
#define SILICA_BEES_TLS_WRAPPER_H
#include <stdint.h>

typedef struct bees_tls_tagged {
    int64_t tag;
    int64_t value;
    int64_t error_code;
} bees_tls_tagged;

typedef struct bees_tls_bytes {
    int64_t tag;
    const uint8_t *text_ptr;
    uint64_t text_len;
    int64_t error_code;
} bees_tls_bytes;

bees_tls_tagged bees_tls_set_args(int64_t a, int64_t b);   /* b: for bees_tls_open the profile, 0 TRUST (trust/1), 1 TEMPUS (tempus/1), 16 BEAM distribution (no ALPN; N2T; not 2: see silica_bees_tls.c) */
bees_tls_tagged bees_tls_version(int64_t unused);                           /* OpenSSL_version_num() */
bees_tls_tagged bees_tls_open(const uint8_t *spec_ptr, uint64_t spec_len);   /* a: role 1 client, 2 server */
bees_tls_tagged bees_tls_feed(const uint8_t *data_ptr, uint64_t data_len);   /* a: handle */
bees_tls_tagged bees_tls_write(const uint8_t *data_ptr, uint64_t data_len);  /* a: handle */
bees_tls_tagged bees_tls_pull(int64_t handle);
bees_tls_tagged bees_tls_read(int64_t handle, int64_t max);
bees_tls_tagged bees_tls_facts(int64_t handle);     /* what a finished handshake shows, packed (silica_bees_tls.c) */
bees_tls_tagged bees_tls_peer_fp(int64_t handle);   /* the SHA-512 of the peer certificate's DER into the span */
bees_tls_tagged bees_tls_peer_key(int64_t handle);  /* TEMPUS: the peer certificate's raw Ed25519 public key (32) into the span */
bees_tls_tagged bees_tls_discard(int64_t handle);   /* drop the ciphertext not yet pulled */
bees_tls_tagged bees_tls_close(int64_t handle);
bees_tls_tagged bees_tls_free(int64_t handle);
bees_tls_bytes bees_tls_take(int64_t handle);

/* error codes (error_code of a tag-1 answer); small integers, never peer-supplied text (S12 section 3) */
#define BEES_TLS_E_HANDSHAKE   1   /* the handshake failed: an alert, a protocol or version mismatch, a refused group */
#define BEES_TLS_E_CERT        2   /* the peer's certificate did not verify against cacertfile (wrong CA, expired, bad) */
#define BEES_TLS_E_NO_CERT     3   /* the peer presented no certificate */
#define BEES_TLS_E_ALPN        4   /* no ALPN, or not trust/1 */
#define BEES_TLS_E_NOT_PINNED  5   /* client: the server's fingerprint is not the one pinned for the address */
#define BEES_TLS_E_IDENTITY    6   /* this node's key, certificate or CA could not be loaded, or the engine is refused */
#define BEES_TLS_E_TABLE       7   /* the connection table is full */
#define BEES_TLS_E_STATE       8   /* a call on a handle that is not open, or out of order */
/* 9: the OpenSSL found at run time is older than 4.1.0, the minimum (decided by BEES's Silica on bees_tls_version, not here) */
#endif
