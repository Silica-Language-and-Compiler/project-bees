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
 * decode((:etf), ...) (mvp.md section 4). The text is one of:
 *   "ok <a.b.c.d> <n4> <n6>"            the first IPv4 address (an A record or /etc/hosts), and how many IPv4 and IPv6
 *                                      addresses the name has (the carrier can dial only the IPv4 ones)
 *   "dns_error no_ipv4 <n6>"            the name has only IPv6 addresses (AAAA), which the carrier cannot dial
 *   "dns_error <reason>"               getaddrinfo failed: gai_strerror's text, spaces kept (EAI_NONAME: "nodename nor
 *                                      servname provided, or not known")
 * getaddrinfo blocks the calling thread (a dangerous worker is its own thread); no timeout is applied (trust.dns_* are not
 * used here, a gap noted in spikes/N1-addresses-and-limits.md). */
bees_resolve_bytes bees_resolve_etf(const uint8_t *host_ptr, uint64_t host_len);
