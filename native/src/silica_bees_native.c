#include "silica_bees_native_wrapper.h"
#include <poll.h>
#include <time.h>

int64_t bees_clock_monotonic_ns(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (int64_t)ts.tv_sec * 1000000000LL + (int64_t)ts.tv_nsec;
}

int64_t bees_clock_system_ns(void) {
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    return (int64_t)ts.tv_sec * 1000000000LL + (int64_t)ts.tv_nsec;
}

int64_t bees_poll_wait_ms(int64_t ms) {
    if (ms < 0) ms = 0;
    if (ms > 60000) ms = 60000;
    int64_t start = bees_clock_monotonic_ns();
    (void)poll((struct pollfd *)0, 0, (int)ms);
    return bees_clock_monotonic_ns() - start;
}

int64_t bees_fixture_word(int64_t idx) {
    static const unsigned char frame[24] = {
        0, 0, 0, 0, 0, 0, 0, 42,
        'h', 'e', 'l', 'l', 'o', '!', '!', '\n',
        0x00, 0xFF, 0, 0, 0, 0, 0, 1
    };
    if (idx < 0 || idx > 2) return -1;
    int64_t w = 0;
    for (int i = 0; i < 8; i++) w = (w << 8) | frame[idx * 8 + i];
    return w;
}
