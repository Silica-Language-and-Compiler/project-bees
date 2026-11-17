/* BEES native edge, N1: host-name resolution for the dialers of the BEAM-mode and M3 nodes, because the language's (:tcp)
 * carrier dials IPv4 literals only (it has no resolver: silica_sockets_tcp_connect calls inet_pton(AF_INET, ...)). macOS system
 * library only (getaddrinfo of libSystem); nothing is downloaded or built besides this file. macOS on Apple Silicon only. */
#include <stdint.h>

typedef struct bees_resolve_bytes {
    int64_t tag;        /* 0: an answer (ok or dns_error) is in the bytes; 1: the call itself failed (error_code) */
    const uint8_t *text_ptr;
    uint64_t text_len;
    int64_t error_code;
} bees_resolve_bytes;

/* Resolves the host name (1 to 253 bytes) with getaddrinfo(AF_UNSPEC, SOCK_STREAM) and answers ONE ETF term, a binary
 * (131 109 len(4, big-endian) text), so that the receiving handler makes it a pure value with the language's
 * decode((:etf), ...) (mvp.md section 4). The text is one of (the resolver contract of S14 section 3, folded in 2026-11-17):
 *   "ok <a.b.c.d>[,<a.b.c.d>...] <n6>"  the IPv4 addresses in the order the system returned them (at most 24; an A record or
 *                                      /etc/hosts), and how many IPv6 addresses the name has (the carrier dials only IPv4)
 *   "err <reason>"                     reason: nxdomain (EAI_NONAME), no_address (the name exists, no A record: only AAAA, or
 *                                      EAI_NODATA), temporary (EAI_AGAIN), bad_name (empty or over 253 bytes), failed
 * The answer is FFI output and untrusted: the owner parses and filters it with bees_addr (the one answer filter). getaddrinfo
 * blocks the calling thread (a dangerous worker is its own thread) and has no timeout: the owner holds the budget and drops a
 * late answer by its tag (src/shim/bees_resolve_edge.part). */
bees_resolve_bytes bees_resolve_etf(const uint8_t *host_ptr, uint64_t host_len);

/* The test stub of the resolver (see silica_bees_resolve.c): the same shape of answer, fixed for a few names. Selected only by
 * building a program with the resolver edge's --resolve-stub. */
bees_resolve_bytes bees_resolve_stub_etf(const uint8_t *host_ptr, uint64_t host_len);
