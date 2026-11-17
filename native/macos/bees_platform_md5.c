/* macOS: MD5 from CommonCrypto (libSystem). CC_MD5 is marked deprecated (MD5 is not a secure hash); it is what Erlang's
 * cookie scheme is defined with. */
#include "../bees_platform.h"
#include <CommonCrypto/CommonDigest.h>

#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wdeprecated-declarations"
void bees_platform_md5(const void *data, size_t n, uint8_t out[16]) {
    CC_MD5(data, (CC_LONG)n, out);
}
#pragma clang diagnostic pop
