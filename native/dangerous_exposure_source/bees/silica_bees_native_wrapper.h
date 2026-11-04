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
 * Out-of-range idx returns -1. Stands in for a network read until the socket entries exist. */
int64_t bees_fixture_word(int64_t idx);
