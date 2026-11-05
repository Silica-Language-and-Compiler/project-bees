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

/* ---- M2: TCP on 127.0.0.1 only (src/silica_bees_tcp.c). One link per slot (0..7), chosen by the
 * caller; descriptors never leave the C side. Payload crosses as big-endian 8-byte words.
 * Status codes returned by every entry:
 *   0 ok    1 end of stream between words    2 reset or error (including a cut word)
 *   3 timeout (poll)    4 closed (by bees_tcp_close, or the link already ended: a read, write or timeout
 *     that ends the link marks it closed, so later calls report 4)    5 bad slot, or slot already in use
 *  10 address refused (host is not the literal 127.0.0.1)    11 address text malformed
 *  12 endpoint creation, bind, listen, accept or connect failed
 * timeout_ms is clamped to [0, 60000]. */

/* open_text(addr): "listen:127.0.0.1:PORT" binds, accepts ONE peer (up to timeout_ms) and closes the listener;
 * "connect:127.0.0.1:PORT" connects, retrying every 25 ms until timeout_ms. Any other host text,
 * "0.0.0.0", "localhost" and "127.0.0.2" included, is refused with 10 before an endpoint is made. */
int64_t bees_tcp_open_prepare(int64_t slot, int64_t timeout_ms);
int64_t bees_tcp_open_text(const uint8_t *addr_ptr, uint64_t addr_len);
/* An open is these two calls in this order on one thread: the compiler accepts a pointer-plus-length
 * pair only as a foreign function's whole parameter list (SD-30). A second open_text without a new
 * prepare returns 5. */

/* Read exactly one word (waiting at most timeout_ms for each chunk); on 0 the word is in
 * bees_tcp_last_word(slot). */
int64_t bees_tcp_read_word(int64_t slot, int64_t timeout_ms);
int64_t bees_tcp_last_word(int64_t slot);

/* Write one word, waiting at most timeout_ms for the transport to take it. */
int64_t bees_tcp_write_word(int64_t slot, int64_t timeout_ms, int64_t word);

/* Close the link (wakes a blocked reader, which then reports 4). Always 0 for a valid slot. */
int64_t bees_tcp_close(int64_t slot);
