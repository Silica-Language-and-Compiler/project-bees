/* Self-test of the TLS engine's three additions for TEMPUS (native/tls/silica_bees_tls.c; development-plan/tempus-design.md
 * 17.6): a second profile with ALPN tempus/1, contexts per (profile, role) so one process holds two credentials, and
 * bees_tls_peer_key. In memory, no transport: two engine connections pump each other's ciphertext. TEST ONLY.
 *
 *   bees_tempus_tls_selftest <trials/t5_tempus_tls/certs> <trials/n4_trust_tls/certs>
 *
 * Built with -DBEES_TLS_SELFTEST together with native/tls/silica_bees_tls.c (trials/t5_tempus_tls/Makefile). TRUST's own
 * self-test (native/tls/selftest) is unchanged and still covers TRUST's profile.
 */
#include "silica_bees_tls_wrapper.h"
#include "tls_vectors.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

void bees_tls_selftest_reset(void);

static int failures = 0;
static const char *tempus_dir, *trust_dir;

static void check(const char *name, int good) {
    printf("%s %s\n", good ? "PASS" : "FAIL", name);
    if (!good) failures++;
}

/* role 1 client, 2 server; profile 0 TRUST, 1 TEMPUS; no CA (pins only, D43). Answers the handle, or -100 - error_code */
static int64_t open_as(int role, int profile, const char *dir, const char *who) {
    char spec[2200];
    size_t n = (size_t)snprintf(spec, sizeof spec, "%s/%s.pem%c%s/%s-key.pem%c%c", dir, who, 0, dir, who, 0, 0);
    bees_tls_set_args(role, profile);
    bees_tls_tagged r = bees_tls_open((const uint8_t *)spec, n);
    return r.tag == 0 ? r.value : -100 - r.error_code;
}

static bees_tls_tagged pump(int64_t from, int64_t to) {
    bees_tls_pull(from);
    bees_tls_bytes b = bees_tls_take(from);
    bees_tls_set_args(to, 0);
    bees_tls_tagged r = bees_tls_feed(b.text_ptr ? b.text_ptr : (const uint8_t *)"", b.text_len);
    free((void *)b.text_ptr);
    return r;
}

/* drives the handshake of client cl and server sv; 0 when both finished, else the first error code (1000 + code: seen
   by the server) */
static int64_t handshake(int64_t cl, int64_t sv) {
    bees_tls_tagged r;
    for (int i = 0; i < 8; i++) {
        r = pump(cl, sv); if (r.tag) return 1000 + r.error_code;
        r = pump(sv, cl); if (r.tag) return r.error_code;
    }
    r = pump(cl, sv); if (r.tag) return 1000 + r.error_code;
    return (bees_tls_facts(cl).tag == 0 && bees_tls_facts(sv).tag == 0) ? 0 : 99;
}

/* 1 when the peer key of handle h is the 32 bytes `want`; 0 when it is other bytes; -code when the call is refused */
static int64_t peer_key_is(int64_t h, const uint8_t *want) {
    bees_tls_tagged r = bees_tls_peer_key(h);
    if (r.tag != 0) return -r.error_code;
    bees_tls_bytes b = bees_tls_take(h);
    int same = r.value == 32 && b.text_len == 32 && memcmp(b.text_ptr, want, 32) == 0;
    free((void *)b.text_ptr);
    return same;
}

static void free_pair(int64_t cl, int64_t sv) {
    if (cl > 0) bees_tls_free(cl);
    if (sv > 0) bees_tls_free(sv);
}

int main(int argc, char **argv) {
    if (argc < 3) { fprintf(stderr, "usage: %s TEMPUS_CERTS TRUST_CERTS\n", argv[0]); return 2; }
    tempus_dir = argv[1]; trust_dir = argv[2];
    int64_t cl, sv, rc;

    /* 1. a TEMPUS pair: ALPN tempus/1, each side reads the other's Ed25519 key from its certificate */
    bees_tls_selftest_reset();
    cl = open_as(1, 1, tempus_dir, "node"); sv = open_as(2, 1, tempus_dir, "sentinel");
    check("tempus: both ends open with profile 1", cl > 0 && sv > 0);
    rc = handshake(cl, sv);
    check("tempus: the handshake completes", rc == 0);
    check("tempus: the server's facts say the profile's ALPN was selected", (bees_tls_facts(sv).value & 1) == 1);
    check("tempus: the client's facts say the profile's ALPN was selected", (bees_tls_facts(cl).value & 1) == 1);
    check("tempus: the server reads the client's public key (the node's)", peer_key_is(sv, node_pub) == 1);
    check("tempus: the client reads the server's public key (the sentinel's)", peer_key_is(cl, sentinel_pub) == 1);
    check("tempus: the key read is not some other identity's", peer_key_is(sv, other_pub) == 0);
    free_pair(cl, sv);

    /* 2. the wrong ALPN is refused, both ways round */
    bees_tls_selftest_reset();
    cl = open_as(1, 0, tempus_dir, "node"); sv = open_as(2, 1, tempus_dir, "sentinel");
    rc = handshake(cl, sv);
    check("a trust/1 client is refused by a tempus/1 server (no common ALPN)", rc == 1000 + BEES_TLS_E_ALPN);
    free_pair(cl, sv);
    bees_tls_selftest_reset();
    cl = open_as(1, 1, tempus_dir, "node"); sv = open_as(2, 0, tempus_dir, "sentinel");
    rc = handshake(cl, sv);
    check("a tempus/1 client is refused by a trust/1 server (no common ALPN)", rc == 1000 + BEES_TLS_E_ALPN);
    free_pair(cl, sv);

    /* 3. two credentials in one process: a TRUST pair (TRUST's test certificates a and b) and a TEMPUS pair, open at the
       same time, no reset in between; each connection shows its own profile's certificate */
    bees_tls_selftest_reset();
    int64_t tcl = open_as(1, 0, trust_dir, "b"), tsv = open_as(2, 0, trust_dir, "a");
    cl = open_as(1, 1, tempus_dir, "node"); sv = open_as(2, 1, tempus_dir, "bridge");
    check("two credentials: all four ends open", tcl > 0 && tsv > 0 && cl > 0 && sv > 0);
    int64_t rc_trust = handshake(tcl, tsv), rc_tempus = handshake(cl, sv);
    check("two credentials: the TRUST handshake completes", rc_trust == 0);
    check("two credentials: the TEMPUS handshake completes", rc_tempus == 0);
    check("two credentials: the TEMPUS client sees the bridge's TEMPUS key", peer_key_is(cl, bridge_pub) == 1);
    check("two credentials: the TEMPUS server sees the node's key", peer_key_is(sv, node_pub) == 1);
    check("two credentials: the TRUST client does not see a TEMPUS key", peer_key_is(tcl, bridge_pub) == 0);
    check("two credentials: the TRUST connection's ALPN bit is set (trust/1)", (bees_tls_facts(tsv).value & 1) == 1);
    /* a second TEMPUS connection reuses the TEMPUS context, a second TRUST one the TRUST context */
    int64_t cl2 = open_as(1, 1, tempus_dir, "other"), sv2 = open_as(2, 1, tempus_dir, "other");
    rc = handshake(cl2, sv2);
    check("two credentials: a later TEMPUS open keeps the first TEMPUS credential (the node's, the bridge's)",
          rc == 0 && peer_key_is(sv2, node_pub) == 1 && peer_key_is(cl2, bridge_pub) == 1);
    free_pair(cl2, sv2); free_pair(cl, sv); free_pair(tcl, tsv);

    /* 4. a peer whose certificate key is not Ed25519: the handshake may complete (ECDSA P-256 is an allowed signature), the
       key call is refused */
    bees_tls_selftest_reset();
    cl = open_as(1, 1, tempus_dir, "p256"); sv = open_as(2, 1, tempus_dir, "sentinel");
    rc = handshake(cl, sv);
    check("a P-256 peer: the handshake completes", rc == 0);
    check("a P-256 peer: its key is refused (not Ed25519)", peer_key_is(sv, node_pub) == -BEES_TLS_E_CERT);
    free_pair(cl, sv);

    /* 5. calls that are not in order */
    bees_tls_selftest_reset();
    check("a profile that does not exist is refused", open_as(1, 2, tempus_dir, "node") == -100 - BEES_TLS_E_STATE);
    check("a negative profile is refused", open_as(1, -1, tempus_dir, "node") == -100 - BEES_TLS_E_STATE);
    cl = open_as(1, 1, tempus_dir, "node");
    check("the key of a connection with no peer certificate yet is refused", peer_key_is(cl, node_pub) == -BEES_TLS_E_NO_CERT);
    free_pair(cl, 0);
    check("the key of a handle that is not a connection is refused", bees_tls_peer_key(0).tag == 1);

    printf("%s\n", failures == 0 ? "all passed" : "FAILURES");
    return failures == 0 ? 0 : 1;
}
