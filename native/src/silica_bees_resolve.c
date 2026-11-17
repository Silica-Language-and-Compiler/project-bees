/* BEES native edge, N1: host-name resolution; see dangerous_exposure_source/bees/silica_bees_resolve_wrapper.h. */
#include "silica_bees_resolve_wrapper.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <unistd.h>
#include <sys/types.h>
#include <sys/socket.h>
#include <netdb.h>
#include <arpa/inet.h>

static bees_resolve_bytes etf_text(const char *text) {
    bees_resolve_bytes r;
    size_t n = strlen(text);
    r.tag = 0; r.text_ptr = 0; r.text_len = 0; r.error_code = 0;
    uint8_t *out = (uint8_t *)malloc(n + 6);
    if (out == 0) { r.tag = 1; r.error_code = ENOMEM; return r; }
    out[0] = 131; out[1] = 109;
    out[2] = (uint8_t)(n >> 24); out[3] = (uint8_t)(n >> 16); out[4] = (uint8_t)(n >> 8); out[5] = (uint8_t)n;
    memcpy(out + 6, text, n);
    r.text_ptr = out;
    r.text_len = (uint64_t)n + 6;
    return r;
}

#define BEES_RESOLVE_MAX_ADDRS 24   /* 24 dotted quads of at most 15 bytes and a comma stay far under the owner's decode limit */

static bees_resolve_bytes err_text(const char *reason) {
    char text[64];
    snprintf(text, sizeof text, "err %s", reason);
    return etf_text(text);
}

bees_resolve_bytes bees_resolve_etf(const uint8_t *host_ptr, uint64_t host_len) {
    char host[256];
    char text[BEES_RESOLVE_MAX_ADDRS * 16 + 32];
    struct addrinfo hints, *res = 0, *p;
    if (host_ptr == 0 || host_len == 0 || host_len > 253 || memchr(host_ptr, 0, (size_t)host_len) != 0) return err_text("bad_name");
    memcpy(host, host_ptr, (size_t)host_len);
    host[host_len] = 0;
    memset(&hints, 0, sizeof hints);
    hints.ai_family = AF_UNSPEC;
    hints.ai_socktype = SOCK_STREAM;
    int rc = getaddrinfo(host, 0, &hints, &res);
    if (rc != 0) {
        switch (rc) {
        case EAI_NONAME: return err_text("nxdomain");
#ifdef EAI_NODATA
        case EAI_NODATA: return err_text("no_address");
#endif
        case EAI_AGAIN: return err_text("temporary");
        default: return err_text("failed");
        }
    }
    size_t off = 3;
    int n4 = 0, n6 = 0;
    memcpy(text, "ok ", 3);
    for (p = res; p != 0; p = p->ai_next) {
        if (p->ai_family == AF_INET) {
            if (n4 < BEES_RESOLVE_MAX_ADDRS) {
                char quad[INET_ADDRSTRLEN];
                inet_ntop(AF_INET, &((struct sockaddr_in *)p->ai_addr)->sin_addr, quad, sizeof quad);
                if (n4 > 0) text[off++] = ',';
                size_t q = strlen(quad);
                memcpy(text + off, quad, q);
                off += q;
            }
            n4++;
        } else if (p->ai_family == AF_INET6) {
            n6++;
        }
    }
    freeaddrinfo(res);
    if (n4 == 0) return err_text("no_address");
    snprintf(text + off, sizeof text - off, " %d", n6);
    return etf_text(text);
}

/* The test stub (selected at build time by the resolver edge's --resolve-stub, which names dangerous_bees_resolve_stub as the
 * worker): fixed answers for a few names, the real resolver for any other. A name of the stub's table never reaches the system:
 *   two.stub   "ok 127.0.0.2,127.0.0.1 0"   two addresses; on macOS 127.0.0.2 is not on the loopback interface, so a dial to
 *                                          it ends with the connect budget and the next attempt takes the second address
 *   slow.stub  "ok 127.0.0.1 0" after 2 s  a slow lookup, to show that a late answer is dropped by its tag
 *   localhost  "ok 10.0.0.8,127.0.0.1 0"   a name that resolves outside loopback, for a loopback-only setting
 *   dup.stub   "ok 127.0.0.1,127.0.0.1 0"  a repeated answer */
bees_resolve_bytes bees_resolve_stub_etf(const uint8_t *host_ptr, uint64_t host_len) {
    if (host_ptr != 0 && host_len == 8 && memcmp(host_ptr, "two.stub", 8) == 0) return etf_text("ok 127.0.0.2,127.0.0.1 0");
    if (host_ptr != 0 && host_len == 8 && memcmp(host_ptr, "dup.stub", 8) == 0) return etf_text("ok 127.0.0.1,127.0.0.1 0");
    if (host_ptr != 0 && host_len == 9 && memcmp(host_ptr, "localhost", 9) == 0) return etf_text("ok 10.0.0.8,127.0.0.1 0");
    if (host_ptr != 0 && host_len == 9 && memcmp(host_ptr, "slow.stub", 9) == 0) { sleep(2); return etf_text("ok 127.0.0.1 0"); }
    return bees_resolve_etf(host_ptr, host_len);
}
