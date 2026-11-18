/* Linux: the kernel's random source, getrandom(2) with flags 0: it blocks until the pool has been seeded once and never
 * after, so no byte is returned before seeding. There is no /dev/urandom fallback (that file can be read before seeding).
 * A call interrupted by a signal (EINTR) is repeated; a short count (possible for requests over 256 bytes) continues where
 * it stopped. Any other error is returned as its errno. */
#include "../bees_platform.h"
#include <errno.h>
#include <sys/random.h>
#include <sys/types.h>

int bees_platform_random(uint8_t *out, size_t n) {
    size_t done = 0;
    while (done < n) {
        ssize_t r = getrandom(out + done, n - done, 0);
        if (r < 0) {
            if (errno == EINTR) continue;
            return errno ? errno : -1;
        }
        done += (size_t)r;
    }
    return 0;
}
