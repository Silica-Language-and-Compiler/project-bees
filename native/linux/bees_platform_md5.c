/* Linux: MD5 from OpenSSL's EVP interface (libcrypto of the programmer-installed OpenSSL, OPENSSL_PREFIX; the same
 * installation the TLS engine uses). MD5 is not a secure hash; it is what Erlang's cookie scheme is defined with.
 * EVP_Digest fetches the digest from the default provider, where MD5 lives (it is not one of the legacy provider's). */
#include "../bees_platform.h"
#include <openssl/evp.h>
#include <stdio.h>
#include <stdlib.h>

void bees_platform_md5(const void *data, size_t n, uint8_t out[16]) {
    unsigned char md[EVP_MAX_MD_SIZE];
    unsigned int len = 0;
    if (EVP_Digest(data, n, md, &len, EVP_md5(), NULL) != 1 || len != 16) {
        /* The contract says "never fails": an OpenSSL whose configuration has no MD5 (a FIPS-only provider set) cannot run
         * BEAM mode at all. A digest of made-up bytes would only turn that into a cookie mismatch nobody can explain. */
        fputs("bees_platform_md5: this OpenSSL provides no MD5 (EVP_Digest failed); BEAM mode's cookie scheme needs it\n", stderr);
        abort();
    }
    for (int i = 0; i < 16; i++) out[i] = md[i];
}
