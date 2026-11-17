/* macOS: the system CSPRNG (CommonCrypto's CCRandomGenerateBytes, in libSystem; the same source arc4random_buf draws on). */
#include "../bees_platform.h"
#include <CommonCrypto/CommonRandom.h>

int bees_platform_random(uint8_t *out, size_t n) {
    CCRNGStatus s = CCRandomGenerateBytes(out, n);
    return s == kCCSuccess ? 0 : (int)s;
}
