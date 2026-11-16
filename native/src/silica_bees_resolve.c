/* BEES native edge, N1: host-name resolution; see dangerous_exposure_source/bees/silica_bees_resolve_wrapper.h. */
#include "silica_bees_resolve_wrapper.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
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

bees_resolve_bytes bees_resolve_etf(const uint8_t *host_ptr, uint64_t host_len) {
    char host[256];
    char text[320];
    struct addrinfo hints, *res = 0, *p;
    if (host_ptr == 0 || host_len == 0 || host_len > 253) return etf_text("dns_error bad_name");
    memcpy(host, host_ptr, (size_t)host_len);
    host[host_len] = 0;
    memset(&hints, 0, sizeof hints);
    hints.ai_family = AF_UNSPEC;
    hints.ai_socktype = SOCK_STREAM;
    int rc = getaddrinfo(host, 0, &hints, &res);
    if (rc != 0) {
        snprintf(text, sizeof text, "dns_error %s", gai_strerror(rc));
        return etf_text(text);
    }
    char first[INET_ADDRSTRLEN] = "";
    int n4 = 0, n6 = 0;
    for (p = res; p != 0; p = p->ai_next) {
        if (p->ai_family == AF_INET) {
            if (n4 == 0) inet_ntop(AF_INET, &((struct sockaddr_in *)p->ai_addr)->sin_addr, first, sizeof first);
            n4++;
        } else if (p->ai_family == AF_INET6) {
            n6++;
        }
    }
    freeaddrinfo(res);
    if (n4 == 0) snprintf(text, sizeof text, "dns_error no_ipv4 %d", n6);
    else snprintf(text, sizeof text, "ok %s %d %d", first, n4, n6);
    return etf_text(text);
}
