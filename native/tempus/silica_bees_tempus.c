/* BEES native edge for TEMPUS (T4); see silica_bees_tempus.h. OpenSSL's EVP interface only. */
#include "silica_bees_tempus.h"
#include <errno.h>
#include <stdlib.h>
#include <string.h>
#include <openssl/evp.h>

#define MSG_MAX 4096

static bees_tempus_bytes bytes_error(int code) {
    bees_tempus_bytes r = {1, 0, 0, code};
    return r;
}

/* n bytes (n <= 255) as one ETF binary term in a malloc'd buffer */
static bees_tempus_bytes etf_binary(const uint8_t *data, size_t n) {
    uint8_t *out = (uint8_t *)malloc(n + 6);
    if (out == 0) return bytes_error(ENOMEM);
    out[0] = 131; out[1] = 109; out[2] = 0; out[3] = 0; out[4] = 0; out[5] = (uint8_t)n;
    memcpy(out + 6, data, n);
    bees_tempus_bytes r = {0, out, (uint64_t)n + 6, 0};
    return r;
}

bees_tempus_tagged bees_tempus_ed25519_verify(const uint8_t *ptr, uint64_t len) {
    bees_tempus_tagged r = {0, 0, 0};
    if (ptr == 0 || len < 32 + 64 + 1 || len > 32 + 64 + MSG_MAX) { r.tag = 1; r.error_code = EINVAL; return r; }
    EVP_PKEY *key = EVP_PKEY_new_raw_public_key(EVP_PKEY_ED25519, 0, ptr, 32);
    if (key == 0) return r;                       /* not a usable key: the signature is not valid */
    EVP_MD_CTX *ctx = EVP_MD_CTX_new();
    if (ctx == 0) { EVP_PKEY_free(key); r.tag = 1; r.error_code = ENOMEM; return r; }
    if (EVP_DigestVerifyInit(ctx, 0, 0, 0, key) == 1 &&
        EVP_DigestVerify(ctx, ptr + 32, 64, ptr + 96, (size_t)(len - 96)) == 1)
        r.value = 1;
    EVP_MD_CTX_free(ctx);
    EVP_PKEY_free(key);
    return r;
}

bees_tempus_bytes bees_tempus_ed25519_sign(const uint8_t *ptr, uint64_t len) {
    if (ptr == 0 || len < 32 + 1 || len > 32 + MSG_MAX) return bytes_error(EINVAL);
    EVP_PKEY *key = EVP_PKEY_new_raw_private_key(EVP_PKEY_ED25519, 0, ptr, 32);
    if (key == 0) return bytes_error(EINVAL);
    EVP_MD_CTX *ctx = EVP_MD_CTX_new();
    if (ctx == 0) { EVP_PKEY_free(key); return bytes_error(ENOMEM); }
    uint8_t sig[64];
    size_t n = sizeof sig;
    int ok = EVP_DigestSignInit(ctx, 0, 0, 0, key) == 1 && EVP_DigestSign(ctx, sig, &n, ptr + 32, (size_t)(len - 32)) == 1 && n == 64;
    EVP_MD_CTX_free(ctx);
    EVP_PKEY_free(key);
    if (!ok) return bytes_error(EIO);
    bees_tempus_bytes r = etf_binary(sig, 64);
    memset(sig, 0, sizeof sig);
    return r;
}

bees_tempus_bytes bees_tempus_ed25519_public(const uint8_t *ptr, uint64_t len) {
    if (ptr == 0 || len != 32) return bytes_error(EINVAL);
    EVP_PKEY *key = EVP_PKEY_new_raw_private_key(EVP_PKEY_ED25519, 0, ptr, 32);
    if (key == 0) return bytes_error(EINVAL);
    uint8_t pub[32];
    size_t n = sizeof pub;
    int ok = EVP_PKEY_get_raw_public_key(key, pub, &n) == 1 && n == 32;
    EVP_PKEY_free(key);
    if (!ok) return bytes_error(EIO);
    return etf_binary(pub, 32);
}

bees_tempus_bytes bees_tempus_sha512(const uint8_t *ptr, uint64_t len) {
    if (ptr == 0 || len < 1 || len > MSG_MAX) return bytes_error(EINVAL);
    uint8_t md[64];
    unsigned int n = 0;
    if (EVP_Digest(ptr, (size_t)len, md, &n, EVP_sha512(), 0) != 1 || n != 64) return bytes_error(EIO);
    return etf_binary(md, 64);
}
