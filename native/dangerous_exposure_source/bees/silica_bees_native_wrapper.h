/* BEES native edge, hosted build (gap ledger §4). Every entry is a C-ABI wrapper with fixed-width
 * scalars only; byte payloads wait on S-21. Spike S4 entries: the monotonic clock and a bounded
 * poll wait. */
#include <stdint.h>

/* Nanoseconds on the monotonic clock. */
int64_t bees_clock_monotonic_ns(void);

/* System (wall) clock in nanoseconds since the Unix epoch. */
int64_t bees_clock_system_ns(void);

/* Block the calling (worker) thread for at most ms milliseconds (poll with no descriptors), and
 * return the nanoseconds actually elapsed. ms is clamped to [0, 60000]. */
int64_t bees_poll_wait_ms(int64_t ms);

/* Test fixture for milestone M0 (re-creation of bytes read from outside): word idx of a fixed
 * 24-byte frame, as a big-endian int64. Words 0..2: 42, the bytes "hello!!\n", 0x00FF000000000001.
 * Out-of-range idx returns -1. Stands in for a network read until the transport entries exist. */
int64_t bees_fixture_word(int64_t idx);

/* The TCP entries of M2 and M3 (bees_tcp_*) are gone: the transport is the language's (:tcp) carrier over its own
 * socket wrappers (Silica's compiler/stdlib/net, sidecar under dangerous_exposure_source/sockets). */

/* Host-name resolution, interim (spikes/S14 section 3, roadmap D42): the system resolver, IPv4 only. To be replaced by a
 * Silica implementation (S14 section 9). bees_dns_resolve answers tag 0 with the number of addresses (then bees_dns_take
 * gives them as dotted quads separated by ','), or tag 1 with one of the reasons below in error_code. */
typedef struct bees_dns_tagged {
    int64_t tag;
    int64_t value;
    int64_t error_code;
} bees_dns_tagged;

typedef struct bees_dns_bytes {
    int64_t tag;
    const uint8_t *text_ptr;
    uint64_t text_len;
    int64_t error_code;
} bees_dns_bytes;

#define BEES_DNS_NXDOMAIN 1   /* the name does not exist */
#define BEES_DNS_NO_ADDRESS 2 /* the name exists but has no IPv4 address */
#define BEES_DNS_TEMPORARY 3  /* the resolver could not answer now (EAI_AGAIN) */
#define BEES_DNS_BAD_NAME 4   /* empty, too long (255 bytes or more), or holding a NUL */
#define BEES_DNS_FAILED 5     /* any other failure */

bees_dns_tagged bees_dns_resolve(const uint8_t *host_ptr, uint64_t host_len);
bees_dns_bytes bees_dns_take(int64_t unused);
