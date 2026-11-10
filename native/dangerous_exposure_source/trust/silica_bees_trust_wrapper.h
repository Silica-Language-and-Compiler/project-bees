/* BEES native edge for TRUST mode (N3): secure random bytes and a constant-time comparison, from macOS system
 * facilities only (arc4random_buf of libSystem; no library is downloaded or built besides this file). TRUST only:
 * BEAM mode (N2) has its own edge entries; the two modes share no native code (D36). macOS on Apple Silicon only. */
#include <stdint.h>

typedef struct bees_trust_tagged {
    int64_t tag;        /* 0 ok, 1 error */
    int64_t value;
    int64_t error_code;
} bees_trust_tagged;

typedef struct bees_trust_bytes {
    int64_t tag;
    const uint8_t *text_ptr;
    uint64_t text_len;
    int64_t error_code;
} bees_trust_bytes;

/* n (1..64) random bytes from arc4random_buf, returned as ONE ETF term, a binary: 131 109 len(4, big-endian) bytes.
 * The caller decodes it with the language's decode((:etf), ...) as a string, so the bytes become a pure value only
 * through the language's own conversion (mvp.md section 4). n outside 1..64 gives tag 1 and no bytes. */
bees_trust_bytes bees_trust_random_etf(int64_t n);

/* The constant-time comparison (inter-nodal-modes 3.5): set the first operand (kept per calling thread), then
 * compare the second with it. value 1 when both have the same length and the same bytes, else 0. The time does not
 * depend on where the bytes differ (every byte is visited; lengths are public). Both calls must run in one dispatch
 * of one worker (the FFI carries a pointer-plus-length pair only as a binding's sole parameters, SD-30). */
bees_trust_tagged bees_trust_ct_set(const uint8_t *ptr, uint64_t len);
bees_trust_tagged bees_trust_ct_equal(const uint8_t *ptr, uint64_t len);
