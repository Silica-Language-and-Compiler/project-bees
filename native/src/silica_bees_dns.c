/* BEES host-name resolution, interim (spikes/S14 section 3, roadmap D42): the system resolver. To be replaced by a Silica
 * implementation (S14 section 9); nothing else in BEES may call these entries.
 *
 * Two entries, in the shape of the language's socket wrappers (one pointer-plus-length pair as a wrapper's sole parameters,
 * the bytes handed back by a second call), kept per thread: a dangerous actor is its own thread.
 *
 *   bees_dns_resolve(host)  getaddrinfo(host, AF_INET, SOCK_STREAM, AI_ADDRCONFIG). tag 0: value is the number of IPv4
 *                           addresses kept, and their dotted quads, separated by ',', in the order the system returned them,
 *                           wait for bees_dns_take. tag 1: error_code is the reason (BEES_DNS_* below).
 *   bees_dns_take()         the text of the last successful bees_dns_resolve on this thread.
 *
 * The output is untrusted all the same: the Silica side parses and checks every address (bees_addr). */
#include "silica_bees_native_wrapper.h"
#include <arpa/inet.h>
#include <netdb.h>
#include <netinet/in.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>

#define BEES_DNS_TEXT 1024 /* at most 64 addresses of 15 bytes and a separator */
#define BEES_DNS_MAX_ADDRS 64

static __thread char bees_dns_text[BEES_DNS_TEXT];
static __thread uint64_t bees_dns_text_len = 0;

static bees_dns_tagged dns_ok(int64_t v) { bees_dns_tagged r = {0, v, 0}; return r; }
static bees_dns_tagged dns_err(int64_t why) { bees_dns_tagged r = {1, 0, why}; return r; }

static int64_t reason_of(int gai) {
    switch (gai) {
    case EAI_NONAME: return BEES_DNS_NXDOMAIN;
#ifdef EAI_NODATA
#if EAI_NODATA != EAI_NONAME
    case EAI_NODATA: return BEES_DNS_NO_ADDRESS;
#endif
#endif
#ifdef EAI_ADDRFAMILY
    case EAI_ADDRFAMILY: return BEES_DNS_NO_ADDRESS;
#endif
    case EAI_AGAIN: return BEES_DNS_TEMPORARY;
    default: return BEES_DNS_FAILED;
    }
}

bees_dns_tagged bees_dns_resolve(const uint8_t *host_ptr, uint64_t host_len) {
    char host[256];
    bees_dns_text_len = 0;
    if (host_ptr == 0 || host_len == 0 || host_len >= sizeof host) return dns_err(BEES_DNS_BAD_NAME);
    memcpy(host, host_ptr, (size_t)host_len);
    host[host_len] = 0;
    if (strlen(host) != (size_t)host_len) return dns_err(BEES_DNS_BAD_NAME); /* an embedded NUL */

    struct addrinfo hints;
    memset(&hints, 0, sizeof hints);
    hints.ai_family = AF_INET;
    hints.ai_socktype = SOCK_STREAM;
    hints.ai_flags = AI_ADDRCONFIG;
    struct addrinfo *res = 0;
    int gai = getaddrinfo(host, 0, &hints, &res);
    if (gai != 0) return dns_err(reason_of(gai));

    int64_t n = 0;
    for (struct addrinfo *p = res; p != 0 && n < BEES_DNS_MAX_ADDRS; p = p->ai_next) {
        if (p->ai_family != AF_INET || p->ai_addr == 0) continue;
        char quad[INET_ADDRSTRLEN];
        const struct sockaddr_in *sin = (const struct sockaddr_in *)p->ai_addr;
        if (inet_ntop(AF_INET, &sin->sin_addr, quad, sizeof quad) == 0) continue;
        size_t ql = strlen(quad);
        if (bees_dns_text_len + ql + 1 > BEES_DNS_TEXT) break;
        if (n > 0) bees_dns_text[bees_dns_text_len++] = ',';
        memcpy(bees_dns_text + bees_dns_text_len, quad, ql);
        bees_dns_text_len += ql;
        n++;
    }
    freeaddrinfo(res);
    if (n == 0) return dns_err(BEES_DNS_NO_ADDRESS);
    return dns_ok(n);
}

bees_dns_bytes bees_dns_take(int64_t unused) {
    bees_dns_bytes r = {0, 0, 0, 0};
    (void)unused;
    if (bees_dns_text_len > 0) {
        uint8_t *span = (uint8_t *)malloc(bees_dns_text_len);
        if (span == 0) { r.tag = 1; r.error_code = BEES_DNS_FAILED; return r; }
        memcpy(span, bees_dns_text, bees_dns_text_len);
        r.text_ptr = span;
        r.text_len = bees_dns_text_len;
    }
    return r;
}
