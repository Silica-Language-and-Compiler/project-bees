/* BEES native edge, M2: TCP on 127.0.0.1 only, one link per slot. The Silica side chooses a slot
 * number (a literal it owns); every descriptor stays in this table, so no descriptor is ever
 * returned to Silica (a returned value is tainted and could not be handed back to a worker).
 * Payload crosses as big-endian 8-byte words. Every entry returns a status code (see the header).
 * Nothing here allocates per call and nothing is decoded: a word is eight bytes, as sent. */
#include "silica_bees_native_wrapper.h"

#include <arpa/inet.h>
#include <errno.h>
#include <netinet/in.h>
#include <poll.h>
#include <pthread.h>
#include <stdint.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

#define SLOTS 8
enum { S_FREE = 0, S_OPENING = 1, S_OPEN = 2, S_CLOSED = 3 };

typedef struct {
    int state;
    int fd;
    int64_t last_word;
} slot_t;

static slot_t g_slots[SLOTS] = {{0, -1, 0}, {0, -1, 0}, {0, -1, 0}, {0, -1, 0},
                                {0, -1, 0}, {0, -1, 0}, {0, -1, 0}, {0, -1, 0}};
static pthread_mutex_t g_mu = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t g_cv = PTHREAD_COND_INITIALIZER;

static int64_t now_ms(void) { return bees_clock_monotonic_ns() / 1000000; }

static void nap_ms(int ms) { (void)poll((struct pollfd *)0, 0, ms); }

/* Parse "listen:127.0.0.1:PORT" or "connect:127.0.0.1:PORT". Returns 0 and fills mode (0 listen,
 * 1 connect) and port; 10 for any host other than the literal 127.0.0.1; 11 for bad text. */
static int parse_address(const uint8_t *p, uint64_t n, int *mode, int *port) {
    static const char host[] = "127.0.0.1:";
    uint64_t i = 0;
    if (n > 64) return 11;
    if (n >= 7 && memcmp(p, "listen:", 7) == 0) { *mode = 0; i = 7; }
    else if (n >= 8 && memcmp(p, "connect:", 8) == 0) { *mode = 1; i = 8; }
    else return 11;
    /* A host that does not start with the exact local text is a refused (non-local) address;
     * a text that is not host:port at all is a bad address. */
    int colon = 0;
    for (uint64_t k = i; k < n; k++) if (p[k] == ':') colon = 1;
    if (!colon) return 11;
    if (n - i < sizeof(host) - 1 || memcmp(p + i, host, sizeof(host) - 1) != 0) return 10;
    i += sizeof(host) - 1;
    if (i >= n || n - i > 5) return 11;
    int v = 0;
    for (; i < n; i++) {
        if (p[i] < '0' || p[i] > '9') return 11;
        v = v * 10 + (p[i] - '0');
    }
    if (v < 1 || v > 65535) return 11;
    *port = v;
    return 0;
}

static void set_nosigpipe(int fd) {
#ifdef SO_NOSIGPIPE
    int one = 1;
    (void)setsockopt(fd, SOL_SOCKET, SO_NOSIGPIPE, &one, sizeof one);
#else
    (void)fd;
#endif
}

static int finish_open(int64_t slot, int fd, int status) {
    pthread_mutex_lock(&g_mu);
    if (status == 0) {
        g_slots[slot].fd = fd;
        g_slots[slot].state = S_OPEN;
    } else {
        g_slots[slot].state = S_CLOSED;
    }
    pthread_cond_broadcast(&g_cv);
    pthread_mutex_unlock(&g_mu);
    return status;
}

/* silica-999936 accepts a pointer-plus-length parameter pair only as a foreign function's WHOLE
 * parameter list (type_checker_expressions_user_call_helpers: params_inner_is_ptr_len_pair), so the
 * slot and the timeout travel in a separate call made first, on the same worker thread (SD-30). */
static _Thread_local int64_t t_slot = -1;
static _Thread_local int64_t t_timeout_ms = 0;

int64_t bees_tcp_open_prepare(int64_t slot, int64_t timeout_ms) {
    t_slot = slot;
    t_timeout_ms = timeout_ms;
    return 0;
}

int64_t bees_tcp_open_text(const uint8_t *addr_ptr, uint64_t addr_len) {
    int64_t slot = t_slot, timeout_ms = t_timeout_ms;
    t_slot = -1; /* a prepare is good for one open */
    int mode = 0, port = 0;
    if (slot < 0 || slot >= SLOTS) return 5;
    if (timeout_ms < 0) timeout_ms = 0;
    if (timeout_ms > 60000) timeout_ms = 60000;
    int rc = parse_address(addr_ptr, addr_len, &mode, &port);
    if (rc != 0) return rc; /* refused before any transport endpoint exists */
    pthread_mutex_lock(&g_mu);
    if (g_slots[slot].state == S_OPENING || g_slots[slot].state == S_OPEN) {
        pthread_mutex_unlock(&g_mu);
        return 5;
    }
    if (g_slots[slot].fd >= 0) { close(g_slots[slot].fd); g_slots[slot].fd = -1; }
    g_slots[slot].state = S_OPENING;
    pthread_mutex_unlock(&g_mu);

    struct sockaddr_in sa;
    memset(&sa, 0, sizeof sa);
    sa.sin_family = AF_INET;
    sa.sin_port = htons((uint16_t)port);
    sa.sin_addr.s_addr = htonl(INADDR_LOOPBACK);

    if (mode == 0) {
        int ls = socket(AF_INET, SOCK_STREAM, 0);
        if (ls < 0) return finish_open(slot, -1, 12);
        int one = 1;
        (void)setsockopt(ls, SOL_SOCKET, SO_REUSEADDR, &one, sizeof one);
        if (bind(ls, (struct sockaddr *)&sa, sizeof sa) != 0 || listen(ls, 1) != 0) {
            close(ls);
            return finish_open(slot, -1, 12);
        }
        struct pollfd pf = {ls, POLLIN, 0};
        int pr;
        do { pr = poll(&pf, 1, (int)timeout_ms); } while (pr < 0 && errno == EINTR);
        if (pr == 0) { close(ls); return finish_open(slot, -1, 3); }
        if (pr < 0) { close(ls); return finish_open(slot, -1, 12); }
        int fd = accept(ls, (struct sockaddr *)0, (socklen_t *)0);
        close(ls); /* one peer per listener in M2 */
        if (fd < 0) return finish_open(slot, -1, 12);
        set_nosigpipe(fd);
        return finish_open(slot, fd, 0);
    }
    /* connect: retry while the listener is not up yet, until the timeout */
    int64_t deadline = now_ms() + timeout_ms;
    for (;;) {
        int fd = socket(AF_INET, SOCK_STREAM, 0);
        if (fd < 0) return finish_open(slot, -1, 12);
        if (connect(fd, (struct sockaddr *)&sa, sizeof sa) == 0) {
            set_nosigpipe(fd);
            return finish_open(slot, fd, 0);
        }
        close(fd);
        if (now_ms() >= deadline) return finish_open(slot, -1, 3);
        nap_ms(25);
    }
}

/* Wait (bounded) until the slot has left S_OPENING. Caller holds g_mu. Returns the state. */
static int wait_settled(slot_t *s, int64_t timeout_ms) {
    int64_t deadline = now_ms() + timeout_ms;
    while (s->state == S_OPENING || s->state == S_FREE) {
        int64_t left = deadline - now_ms();
        if (left <= 0) break;
        struct timespec ts;
        clock_gettime(CLOCK_REALTIME, &ts);
        ts.tv_sec += left / 1000;
        ts.tv_nsec += (left % 1000) * 1000000L;
        if (ts.tv_nsec >= 1000000000L) { ts.tv_sec++; ts.tv_nsec -= 1000000000L; }
        pthread_cond_timedwait(&g_cv, &g_mu, &ts);
    }
    return s->state;
}

static int fd_of(int64_t slot, int64_t timeout_ms, int *fd) {
    if (slot < 0 || slot >= SLOTS) return 5;
    pthread_mutex_lock(&g_mu);
    int st = wait_settled(&g_slots[slot], timeout_ms);
    *fd = g_slots[slot].fd;
    pthread_mutex_unlock(&g_mu);
    if (st == S_OPEN) return 0;
    if (st == S_CLOSED) return 4;
    return 3;
}

/* A link that has failed or timed out is over: mark it closed so the other thread's pending and
 * later calls report 4 (closed) instead of reporting the same end again. */
static int64_t end_link(int64_t slot, int64_t status) {
    pthread_mutex_lock(&g_mu);
    slot_t *s = &g_slots[slot];
    if (s->state == S_OPEN && s->fd >= 0) (void)shutdown(s->fd, SHUT_RDWR);
    if (s->state == S_OPEN) s->state = S_CLOSED;
    pthread_cond_broadcast(&g_cv);
    pthread_mutex_unlock(&g_mu);
    return status;
}

/* Read exactly n bytes (1 to 8), waiting at most timeout_ms for each chunk; on 0 they are in
 * bees_tcp_last_word(slot), big-endian and right-aligned (the first byte read is the most significant of the n).
 * M3: a byte-exact stream needs parts shorter than a word (the 2- and 4-byte length headers and the last part of
 * a frame). A word is a part of 8. */
int64_t bees_tcp_read_part(int64_t slot, int64_t timeout_ms, int64_t want) {
    int fd;
    if (timeout_ms < 0) timeout_ms = 0;
    if (timeout_ms > 60000) timeout_ms = 60000;
    if (want < 1 || want > 8) return 5;
    int rc = fd_of(slot, timeout_ms, &fd);
    if (rc != 0) return rc;
    uint8_t buf[8];
    size_t got = 0, need = (size_t)want;
    while (got < need) {
        struct pollfd pf = {fd, POLLIN, 0};
        int pr = poll(&pf, 1, (int)timeout_ms);
        if (pr < 0 && errno == EINTR) continue;
        pthread_mutex_lock(&g_mu);
        int closed = g_slots[slot].state == S_CLOSED;
        pthread_mutex_unlock(&g_mu);
        if (closed) return 4;
        if (pr == 0) return end_link(slot, 3);
        if (pr < 0) return end_link(slot, 2);
        ssize_t n = recv(fd, buf + got, need - got, 0);
        if (n == 0) return end_link(slot, got == 0 ? 1 : 2); /* clean end between parts, or cut in the middle */
        if (n < 0) {
            if (errno == EINTR || errno == EAGAIN) continue;
            pthread_mutex_lock(&g_mu);
            closed = g_slots[slot].state == S_CLOSED;
            pthread_mutex_unlock(&g_mu);
            return closed ? 4 : end_link(slot, 2);
        }
        got += (size_t)n;
    }
    int64_t w = 0;
    for (size_t i = 0; i < need; i++) w = (int64_t)(((uint64_t)w << 8) | buf[i]);
    pthread_mutex_lock(&g_mu);
    g_slots[slot].last_word = w;
    pthread_mutex_unlock(&g_mu);
    return 0;
}

int64_t bees_tcp_read_word(int64_t slot, int64_t timeout_ms) { return bees_tcp_read_part(slot, timeout_ms, 8); }

int64_t bees_tcp_last_word(int64_t slot) {
    if (slot < 0 || slot >= SLOTS) return 0;
    pthread_mutex_lock(&g_mu);
    int64_t w = g_slots[slot].last_word;
    pthread_mutex_unlock(&g_mu);
    return w;
}

/* Write the low n bytes (1 to 8) of the word, most significant of the n first. */
int64_t bees_tcp_write_part(int64_t slot, int64_t timeout_ms, int64_t word, int64_t count) {
    int fd;
    if (timeout_ms < 0) timeout_ms = 0;
    if (timeout_ms > 60000) timeout_ms = 60000;
    if (count < 1 || count > 8) return 5;
    int rc = fd_of(slot, timeout_ms, &fd);
    if (rc != 0) return rc;
    uint8_t buf[8];
    size_t total = (size_t)count;
    for (size_t i = 0; i < total; i++) buf[i] = (uint8_t)((uint64_t)word >> (8 * (total - 1 - i)));
    size_t sent = 0;
    while (sent < total) {
        struct pollfd pf = {fd, POLLOUT, 0};
        int pr = poll(&pf, 1, (int)timeout_ms);
        if (pr < 0 && errno == EINTR) continue;
        if (pr == 0) return end_link(slot, 3);
        if (pr < 0) return end_link(slot, 2);
        ssize_t n = send(fd, buf + sent, total - sent, 0);
        if (n < 0) {
            if (errno == EINTR || errno == EAGAIN) continue;
            return end_link(slot, 2);
        }
        sent += (size_t)n;
    }
    return 0;
}

int64_t bees_tcp_write_word(int64_t slot, int64_t timeout_ms, int64_t word) { return bees_tcp_write_part(slot, timeout_ms, word, 8); }

int64_t bees_tcp_close(int64_t slot) {
    if (slot < 0 || slot >= SLOTS) return 5;
    pthread_mutex_lock(&g_mu);
    slot_t *s = &g_slots[slot];
    if (s->state == S_OPEN && s->fd >= 0) {
        /* shutdown wakes a reader blocked in poll. The descriptor itself is closed only when the
         * slot is opened again, never while a reader may still hold it (no descriptor reuse). */
        (void)shutdown(s->fd, SHUT_RDWR);
    }
    s->state = S_CLOSED;
    pthread_cond_broadcast(&g_cv);
    pthread_mutex_unlock(&g_mu);
    return 0;
}
