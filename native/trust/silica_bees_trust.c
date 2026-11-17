/* BEES native edge for TRUST mode (N3); see dangerous_exposure_source/trust/silica_bees_trust_wrapper.h. */
#include "silica_bees_trust_wrapper.h"
#include "../bees_platform.h"
#include <stdlib.h>
#include <string.h>
#include <errno.h>

bees_trust_bytes bees_trust_random_etf(int64_t n) {
    bees_trust_bytes r;
    r.tag = 0; r.text_ptr = 0; r.text_len = 0; r.error_code = 0;
    if (n < 1 || n > 64) { r.tag = 1; r.error_code = EINVAL; return r; }
    uint8_t *out = (uint8_t *)malloc((size_t)n + 6);
    if (out == 0) { r.tag = 1; r.error_code = ENOMEM; return r; }
    out[0] = 131; out[1] = 109;
    out[2] = 0; out[3] = 0; out[4] = 0; out[5] = (uint8_t)n;
    int rc = bees_platform_random(out + 6, (size_t)n);
    if (rc != 0) { free(out); r.tag = 1; r.error_code = rc; return r; }
    r.text_ptr = out;
    r.text_len = (uint64_t)n + 6;
    return r;
}

static _Thread_local uint8_t ct_a[64];
static _Thread_local uint64_t ct_a_len = 0;

bees_trust_tagged bees_trust_ct_set(const uint8_t *ptr, uint64_t len) {
    bees_trust_tagged r = {0, 0, 0};
    if (len > sizeof ct_a) { ct_a_len = 0; r.tag = 1; r.error_code = EINVAL; return r; }
    memcpy(ct_a, ptr, (size_t)len);
    ct_a_len = len;
    return r;
}

bees_trust_tagged bees_trust_ct_equal(const uint8_t *ptr, uint64_t len) {
    bees_trust_tagged r = {0, 0, 0};
    volatile uint8_t diff = 0;
    uint64_t n = len < ct_a_len ? len : ct_a_len;
    for (uint64_t i = 0; i < sizeof ct_a; i++) {
        uint8_t a = i < ct_a_len ? ct_a[i] : 0;
        uint8_t b = i < n ? ptr[i] : 0;
        diff |= (uint8_t)(a ^ b);
    }
    r.value = (diff == 0 && len == ct_a_len && len > 0) ? 1 : 0;
    memset(ct_a, 0, sizeof ct_a);
    ct_a_len = 0;
    return r;
}
