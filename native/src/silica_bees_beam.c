/* BEES native edge, BEAM mode (N2): cookie file, random challenge and MD5 digest for Erlang's cookie handshake, from the
 * system's CommonCrypto (libSystem). See ../dangerous_exposure_source/beam/silica_bees_beam_wrapper.h. */
#include "../dangerous_exposure_source/beam/silica_bees_beam_wrapper.h"

#include <CommonCrypto/CommonDigest.h>
#include <CommonCrypto/CommonRandom.h>
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#define BEES_COOKIE_MAX 255

/* The cookie is process-wide (one node, one cookie), written by a load and read by every digest under the lock. */
static pthread_mutex_t bees_cookie_lock = PTHREAD_MUTEX_INITIALIZER;
static char bees_cookie[BEES_COOKIE_MAX + 1];
static size_t bees_cookie_len = 0;

/* The last digest of the calling thread (a dangerous actor is its own thread; digest and digest_word run in one dispatch). */
static __thread uint8_t bees_digest_last[16];

static bees_beam_tagged result(int64_t tag, int64_t value, int64_t code) {
    bees_beam_tagged r = {tag, value, code};
    return r;
}

static void forget_cookie(void) {
    pthread_mutex_lock(&bees_cookie_lock);
    memset(bees_cookie, 0, sizeof bees_cookie);
    bees_cookie_len = 0;
    pthread_mutex_unlock(&bees_cookie_lock);
}

bees_beam_tagged bees_beam_load_cookie(const uint8_t *path_ptr, uint64_t path_len) {
    char path[1024];
    if (path_len == 0 || path_len >= sizeof path) { forget_cookie(); return result(1, 0, ENAMETOOLONG); }
    memcpy(path, path_ptr, (size_t)path_len);
    path[path_len] = 0;
    int fd = open(path, O_RDONLY | O_NOFOLLOW);
    if (fd < 0) { int e = errno; forget_cookie(); return result(1, 0, e); }
    struct stat st;
    if (fstat(fd, &st) != 0) { int e = errno; close(fd); forget_cookie(); return result(1, 0, e); }
    if (!S_ISREG(st.st_mode)) { close(fd); forget_cookie(); return result(4, 0, 0); }
    if ((st.st_mode & 077) != 0) { close(fd); forget_cookie(); return result(2, 0, (int64_t)(st.st_mode & 0777)); }
    char buf[BEES_COOKIE_MAX + 3];
    ssize_t got = read(fd, buf, sizeof buf);
    int e = errno;
    close(fd);
    if (got < 0) { forget_cookie(); return result(1, 0, e); }
    size_t n = (size_t)got;
    if (n > 0 && buf[n - 1] == '\n') n--;
    if (n > 0 && buf[n - 1] == '\r') n--;
    if (n == 0 || n > BEES_COOKIE_MAX) { forget_cookie(); return result(3, 0, (int64_t)n); }
    for (size_t i = 0; i < n; i++) {
        unsigned char ch = (unsigned char)buf[i];
        if (ch < 32 || ch > 126) { forget_cookie(); return result(3, 0, (int64_t)i); }
    }
    pthread_mutex_lock(&bees_cookie_lock);
    memcpy(bees_cookie, buf, n);
    bees_cookie[n] = 0;
    bees_cookie_len = n;
    pthread_mutex_unlock(&bees_cookie_lock);
    memset(buf, 0, sizeof buf);
    return result(0, (int64_t)n, 0);
}

bees_beam_tagged bees_beam_challenge(int64_t unused) {
    (void)unused;
    uint8_t b[4];
    CCRNGStatus s = CCRandomGenerateBytes(b, sizeof b);
    if (s != kCCSuccess) return result(1, 0, (int64_t)s);
    uint32_t v = ((uint32_t)b[0] << 24) | ((uint32_t)b[1] << 16) | ((uint32_t)b[2] << 8) | (uint32_t)b[3];
    return result(0, (int64_t)v, 0);
}

/* CC_MD5 is marked deprecated (MD5 is not a secure hash); it is what Erlang's cookie scheme is defined with. */
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wdeprecated-declarations"
bees_beam_tagged bees_beam_digest(int64_t challenge) {
    if (challenge < 0 || challenge > 0xFFFFFFFFLL) return result(6, 0, 0);
    char text[BEES_COOKIE_MAX + 16];
    pthread_mutex_lock(&bees_cookie_lock);
    size_t n = bees_cookie_len;
    if (n > 0) memcpy(text, bees_cookie, n);
    pthread_mutex_unlock(&bees_cookie_lock);
    if (n == 0) return result(5, 0, 0);
    int k = snprintf(text + n, 16, "%llu", (unsigned long long)challenge);
    CC_MD5(text, (CC_LONG)(n + (size_t)k), bees_digest_last);
    memset(text, 0, sizeof text);
    return result(0, 0, 0);
}
#pragma clang diagnostic pop

bees_beam_tagged bees_beam_digest_word(int64_t i) {
    if (i < 0 || i > 3) return result(6, 0, 0);
    const uint8_t *p = bees_digest_last + 4 * i;
    uint32_t v = ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) | ((uint32_t)p[2] << 8) | (uint32_t)p[3];
    return result(0, (int64_t)v, 0);
}
