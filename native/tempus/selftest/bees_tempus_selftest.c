/* Self-test of native/tempus/silica_bees_tempus.c against vectors made by an independent implementation (vectors.h).
 * TEST ONLY. Build and run by hand until the makefiles build native/tempus (design section 15):
 *
 *   cc -std=c11 -Wall -Wextra -I<openssl>/include -Inative/tempus native/tempus/silica_bees_tempus.c \
 *      native/tempus/selftest/bees_tempus_selftest.c -L<openssl>/lib -lcrypto -o /tmp/bees_tempus_selftest
 *
 * The vectors: seeds 00..1f and 20..3f; a token for the node's key signed by the producer (kid k1, tempus_edge, 1000 to
 * 2000); the node's proof of possession over nonce || token; the node's identity (SHA-512 of its public key).
 */
#include "silica_bees_tempus.h"
#include "vectors.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

static int failures = 0;
static void check(const char *what, int ok) {
    printf("%s: %s\n", what, ok ? "ok" : "FAILED");
    if (!ok) failures++;
}
static int is_etf_binary(bees_tempus_bytes r, const uint8_t *want, size_t n) {
    return r.tag == 0 && r.text_len == n + 6 && r.text_ptr[0] == 131 && r.text_ptr[1] == 109 && r.text_ptr[5] == n &&
           memcmp(r.text_ptr + 6, want, n) == 0;
}
static size_t join3(uint8_t *out, const uint8_t *a, size_t an, const uint8_t *b, size_t bn, const uint8_t *c, size_t cn) {
    memcpy(out, a, an); memcpy(out + an, b, bn); memcpy(out + an + bn, c, cn);
    return an + bn + cn;
}

int main(void) {
    uint8_t buf[8192];
    size_t n;
    size_t payload_len = sizeof token - 64;

    bees_tempus_bytes p = bees_tempus_ed25519_public(producer_seed, 32);
    check("producer public key from its seed", is_etf_binary(p, producer_pub, 32));
    p = bees_tempus_ed25519_public(node_seed, 32);
    check("node public key from its seed", is_etf_binary(p, node_pub, 32));

    p = bees_tempus_sha512(node_pub, 32);
    check("node identity is the SHA-512 of its public key", is_etf_binary(p, node_id, 64));

    /* the token: the producer's signature (first 64 bytes) over the payload (the rest) */
    n = join3(buf, producer_pub, 32, token, 64, token + 64, payload_len);
    bees_tempus_tagged v = bees_tempus_ed25519_verify(buf, n);
    check("token signature verifies under the producer key", v.tag == 0 && v.value == 1);
    n = join3(buf, node_pub, 32, token, 64, token + 64, payload_len);
    v = bees_tempus_ed25519_verify(buf, n);
    check("token signature does not verify under another key", v.tag == 0 && v.value == 0);
    n = join3(buf, producer_pub, 32, token, 64, token + 64, payload_len);
    buf[32 + 64 + 10] ^= 1;
    v = bees_tempus_ed25519_verify(buf, n);
    check("a changed payload does not verify", v.tag == 0 && v.value == 0);
    n = join3(buf, producer_pub, 32, token, 64, token + 64, payload_len);
    buf[40] ^= 1;
    v = bees_tempus_ed25519_verify(buf, n);
    check("a changed signature does not verify", v.tag == 0 && v.value == 0);

    /* proof of possession: the node's signature over nonce || token */
    uint8_t msg[4096];
    memcpy(msg, nonce, 32); memcpy(msg + 32, token, sizeof token);
    n = join3(buf, node_pub, 32, pop_sig, 64, msg, 32 + sizeof token);
    v = bees_tempus_ed25519_verify(buf, n);
    check("proof of possession verifies under the node key", v.tag == 0 && v.value == 1);
    memcpy(buf, node_seed, 32); memcpy(buf + 32, msg, 32 + sizeof token);
    bees_tempus_bytes s = bees_tempus_ed25519_sign(buf, 32 + 32 + sizeof token);
    check("signing nonce || token gives the same signature", is_etf_binary(s, pop_sig, 64));
    msg[0] ^= 1;
    n = join3(buf, node_pub, 32, pop_sig, 64, msg, 32 + sizeof token);
    v = bees_tempus_ed25519_verify(buf, n);
    check("the proof does not verify for another nonce", v.tag == 0 && v.value == 0);

    /* inputs that are not of the stated form */
    v = bees_tempus_ed25519_verify(buf, 96);
    check("verify refuses an input with no message", v.tag == 1);
    v = bees_tempus_ed25519_verify(buf, 32 + 64 + 4097);
    check("verify refuses a message above 4096 bytes", v.tag == 1);
    s = bees_tempus_ed25519_sign(buf, 32);
    check("sign refuses an input with no message", s.tag == 1);
    s = bees_tempus_ed25519_public(buf, 31);
    check("public refuses a 31-byte seed", s.tag == 1);
    s = bees_tempus_sha512(buf, 0);
    check("sha512 refuses no bytes", s.tag == 1);

    /* the system clock (ruling NQ-11): 8 bytes as an ETF binary; a time after 2026-01-01 (1767225600) and the same second
     * as, or the one after, the C library's time() read just before; two readings do not go back */
    {
        time_t before = time(0);
        bees_tempus_bytes w1 = bees_tempus_wall_clock((const uint8_t *)"", 0);
        bees_tempus_bytes w2 = bees_tempus_wall_clock(0, 0);
        int shaped = w1.tag == 0 && w1.text_len == 14 && w1.text_ptr[0] == 131 && w1.text_ptr[1] == 109 && w1.text_ptr[5] == 8
            && w2.tag == 0 && w2.text_len == 14;
        uint64_t a = 0, b = 0;
        if (shaped) for (int i = 0; i < 8; i++) { a = (a << 8) | w1.text_ptr[6 + i]; b = (b << 8) | w2.text_ptr[6 + i]; }
        check("the system clock answers 8 bytes as an ETF binary", shaped);
        check("the system clock is the C library's time, in seconds since 1970", shaped && a >= (uint64_t)before && a <= (uint64_t)before + 2 && a > 1767225600u);
        check("a second reading is not earlier", shaped && b >= a && b <= a + 2);
    }
    printf("%s\n", failures == 0 ? "all passed" : "FAILURES");
    return failures == 0 ? 0 : 1;
}
