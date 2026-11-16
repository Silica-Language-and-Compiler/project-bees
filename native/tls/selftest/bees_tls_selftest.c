/* TEST ONLY: spike S12's in-memory check of the BEES TLS engine (native/tls/silica_bees_tls.c), run by
   `make -C native tls-selftest`. The engine is a thin shim: it refuses what OpenSSL refuses during the handshake (a version, group,
   suite, signature, CA, date, missing certificate or ALPN offer outside the profile) and only REPORTS what a finished handshake
   shows (bees_tls_facts, bees_tls_peer_fp); the judgement of those facts (ALPN agreed, the pin) is BEES's Silica
   (dangerous_bees_tls@ttls) and is checked end to end by trials/n4_trust_tls. The cases below check the facts it reports. A client and a server engine in one process; the bytes between them are pumped through
   memory only (R9), and for the refusals a stock OpenSSL client or server is built here with one rule broken. Prints one
   line per case; exit 0 when every case gives what the TRUST profile requires.
     usage: bees_tls_selftest CERTDIR   (the directory tools/bees_test_certs.sh made) */
#include "silica_bees_tls_wrapper.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <openssl/ssl.h>
#include <openssl/err.h>
#include <openssl/evp.h>
#include <openssl/pem.h>
#include <openssl/x509.h>

void bees_tls_selftest_reset(void);
static const char *D;
static int failures = 0;
static int g_no_ca = 0;       /* D43: open the engines with an empty cacertfile (pins only) */
static int g_classical = 0;   /* D44: open the engines with the classical-allowed flag */

static void path(char *out, const char *name) { snprintf(out, 1024, "%s/%s", D, name); }

static void fp_hex(const char *cert, char out[129]) {
    char p[1024]; path(p, cert);
    FILE *f = fopen(p, "r"); X509 *x = f ? PEM_read_X509(f, 0, 0, 0) : 0; if (f) fclose(f);
    unsigned char md[64]; unsigned int n = 0;
    out[0] = 0;
    if (x && X509_digest(x, EVP_sha512(), md, &n) == 1) for (int i = 0; i < 64; i++) sprintf(out + 2 * i, "%02x", md[i]);
    X509_free(x);
}

static int64_t open_engine(int role, const char *who, const char *pin_cert) {
    char spec[4200], c[1024], k[1024], ca[1024], pin[129] = "";
    char cn[64], kn[64];
    snprintf(cn, sizeof cn, "%s.pem", who); snprintf(kn, sizeof kn, "%s-key.pem", who);
    path(c, cn); path(k, kn); path(ca, "ca.pem");
    if (pin_cert) fp_hex(pin_cert, pin);
    /* certfile, keyfile, cacertfile, each ended by a NUL (the pin is BEES's Silica's business, not the engine's) */
    size_t n = (size_t)snprintf(spec, sizeof spec, "%s%c%s%c%s%c", c, 0, k, 0, g_no_ca ? "" : ca, 0);
    if (g_classical) { spec[n++] = '1'; spec[n++] = 0; }
    (void)pin;
    bees_tls_set_args(role, 0);
    bees_tls_tagged r = bees_tls_open((const uint8_t *)spec, n);
    return r.tag == 0 ? r.value : -100 - r.error_code;
}

/* moves pending ciphertext of handle `from` into handle `to`; answers the feed's result */
static bees_tls_tagged pump(int64_t from, int64_t to) {
    bees_tls_tagged p = bees_tls_pull(from);
    bees_tls_bytes b = bees_tls_take(from);
    bees_tls_set_args(to, 0);
    bees_tls_tagged r = bees_tls_feed(b.text_ptr ? b.text_ptr : (const uint8_t *)"", b.text_len);
    free((void *)b.text_ptr);
    (void)p;
    return r;
}

static void check(const char *name, int good, const char *detail) {
    printf("%s %s%s%s\n", good ? "PASS" : "FAIL", name, detail[0] ? ": " : "", detail);
    if (!good) failures++;
}

static int64_t last_facts = 0;
static char client_saw[129];
/* engine client WHO against engine server a; answers the first error code seen, 0 for success; bits: the server's facts;
   fp_seen: the server's view of the client's fingerprint; client_saw: the client's view of the server's */
static int64_t engine_pair(const char *who, const char *pin, int64_t *bits, char *fp_seen) {
    bees_tls_selftest_reset();
    int64_t cl = open_engine(1, who, pin), sv = open_engine(2, "a", 0);
    if (cl < 0) return -cl - 100;
    if (sv < 0) return -sv - 100;
    bees_tls_tagged r = {0, 0, 0};
    for (int i = 0; i < 8; i++) {
        r = pump(cl, sv); if (r.tag) { bees_tls_free(cl); bees_tls_free(sv); return 1000 + r.error_code; }
        r = pump(sv, cl); if (r.tag) { bees_tls_free(cl); bees_tls_free(sv); return r.error_code; }
    }
    /* the client's last flight reaches the server */
    r = pump(cl, sv); if (r.tag) { bees_tls_free(cl); bees_tls_free(sv); return 1000 + r.error_code; }
    if (r.value % 4 == 0) { bees_tls_free(cl); bees_tls_free(sv); return 99; }
    *bits = bees_tls_facts(sv).value;
    last_facts = bees_tls_facts(cl).value;
    /* each side's view of the other's certificate fingerprint; then a frame */
    bees_tls_peer_fp(sv);
    bees_tls_bytes b = bees_tls_take(sv);
    for (uint64_t i = 0; i < b.text_len && i < 64; i++) sprintf(fp_seen + 2 * i, "%02x", b.text_ptr[i]);
    free((void *)b.text_ptr);
    bees_tls_peer_fp(cl);
    b = bees_tls_take(cl);
    for (uint64_t i = 0; i < b.text_len && i < 64; i++) sprintf(client_saw + 2 * i, "%02x", b.text_ptr[i]);
    free((void *)b.text_ptr);
    (void)pin;
    bees_tls_set_args(cl, 0);
    bees_tls_write((const uint8_t *)"ping", 4);
    pump(cl, sv);
    bees_tls_read(sv, 0);
    b = bees_tls_take(sv);
    int pong = b.text_len == 4 && memcmp(b.text_ptr, "ping", 4) == 0;
    free((void *)b.text_ptr);
    bees_tls_close(cl); bees_tls_take(cl);
    bees_tls_free(sv);
    return pong ? 0 : 98;
}

/* a stock OpenSSL client against engine server a, with one rule broken; answers the server's error code or 0 */
static int64_t stock_client(const char *who, const char *groups, int tls12, const char *alpn) {
    bees_tls_selftest_reset();
    int64_t sv = open_engine(2, "a", 0);
    SSL_CTX *c = SSL_CTX_new(TLS_client_method());
    char p[1024], k[1024];
    if (tls12) { SSL_CTX_set_max_proto_version(c, TLS1_2_VERSION); }
    if (groups) SSL_CTX_set1_groups_list(c, groups);
    if (who) {
        char cn[64], kn[64]; snprintf(cn, sizeof cn, "%s.pem", who); snprintf(kn, sizeof kn, "%s-key.pem", who);
        path(p, cn); path(k, kn);
        SSL_CTX_use_certificate_file(c, p, SSL_FILETYPE_PEM); SSL_CTX_use_PrivateKey_file(c, k, SSL_FILETYPE_PEM);
    }
    if (alpn) { unsigned char a[64]; size_t n = strlen(alpn); a[0] = (unsigned char)n; memcpy(a + 1, alpn, n); SSL_CTX_set_alpn_protos(c, a, (unsigned)n + 1); }
    SSL *s = SSL_new(c);
    BIO *rb = BIO_new(BIO_s_mem()), *wb = BIO_new(BIO_s_mem());
    BIO_set_mem_eof_return(rb, -1);
    SSL_set_bio(s, rb, wb); SSL_set_connect_state(s);
    int64_t err = 0;
    for (int i = 0; i < 8 && err == 0; i++) {
        SSL_do_handshake(s);
        char buf[65536]; int n;
        while ((n = BIO_read(wb, buf, sizeof buf)) > 0) {
            bees_tls_set_args(sv, 0);
            bees_tls_tagged r = bees_tls_feed((uint8_t *)buf, (uint64_t)n);
            if (r.tag) { err = r.error_code; break; }
        }
        bees_tls_pull(sv);
        bees_tls_bytes b = bees_tls_take(sv);
        if (b.text_len) BIO_write(rb, b.text_ptr, (int)b.text_len);
        free((void *)b.text_ptr);
    }
    ERR_clear_error();
    if (err == 0) last_facts = bees_tls_facts(sv).value;
    SSL_free(s); SSL_CTX_free(c); bees_tls_free(sv);
    return err;
}

int main(int argc, char **argv) {
    if (argc != 2) { fprintf(stderr, "usage: bees_tls_selftest CERTDIR\n"); return 2; }
    D = argv[1];
    char want[129], seen[129] = "", line[400];
    int64_t bits = 0, e;
    fp_hex("b.pem", want);
    char want_a[129], want_u[129];
    fp_hex("a.pem", want_a); fp_hex("u.pem", want_u);
    e = engine_pair("b", "a.pem", &bits, seen);
    snprintf(line, sizeof line, "error %lld, facts: alpn %lld, certificate %lld, verify %lld, suite 0x%llx, group 0x%llx",
             (long long)e, (long long)(bits % 2), (long long)((bits / 2) % 2), (long long)((bits / 4) % 256),
             (long long)((bits / 1024) % 65536), (long long)(bits / 67108864));
    check("mutual TLS 1.3 b -> a, data both ways; facts ALPN trust/1, a verified certificate, TLS_AES_256_GCM_SHA384 (0x1302), X25519MLKEM768 (0x10011ec)",
          e == 0 && bits % 2 == 1 && (bits / 2) % 2 == 1 && (bits / 4) % 256 == 0 && (bits / 1024) % 65536 == 0x1302 && bits / 67108864 == 0x10011ec, line);
    check("the server's view of the client is the SHA-512 of b.pem's DER (as openssl x509 -fingerprint -sha512)", strcmp(want, seen) == 0, seen);
    check("the client's view of the server is a.pem's SHA-512 and not u.pem's (the pin itself is judged by BEES's Silica)",
          strcmp(client_saw, want_a) == 0 && strcmp(client_saw, want_u) != 0, client_saw);
    e = engine_pair("p", "a.pem", &bits, seen);
    snprintf(line, sizeof line, "error %lld", (long long)e);
    check("an ECDSA P-256 client certificate completes the handshake", e == 0, line);
    e = engine_pair("r", "a.pem", &bits, seen);
    snprintf(line, sizeof line, "error %lld (1002 = the server refused the certificate)", (long long)e);
    check("a client certificate from another CA is refused", e == 1000 + BEES_TLS_E_CERT, line);
    e = engine_pair("x", "a.pem", &bits, seen);
    snprintf(line, sizeof line, "error %lld (1002)", (long long)e);
    check("an expired client certificate is refused", e == 1000 + BEES_TLS_E_CERT, line);
    e = engine_pair("z", "a.pem", &bits, seen);
    snprintf(line, sizeof line, "error %lld (a handshake failure on either side)", (long long)e);
    check("an RSA client certificate (not Ed25519 or P-256) is refused", e != 0, line);
    e = stock_client("b", "X25519", 0, "trust/1");
    snprintf(line, sizeof line, "server error %lld (1 = handshake)", (long long)e);
    check("a classical-only client (X25519) is refused", e == BEES_TLS_E_HANDSHAKE, line);
    e = stock_client("b", 0, 1, "trust/1");
    snprintf(line, sizeof line, "server error %lld", (long long)e);
    check("a TLS 1.2-only client is refused", e == BEES_TLS_E_HANDSHAKE, line);
    e = stock_client("b", 0, 0, "h2");
    snprintf(line, sizeof line, "server error %lld (4 = ALPN)", (long long)e);
    check("a client offering another ALPN is refused", e == BEES_TLS_E_ALPN, line);
    last_facts = -1;
    e = stock_client("b", 0, 0, 0);
    snprintf(line, sizeof line, "server error %lld, facts alpn bit %lld (BEES's Silica refuses alpn 0)", (long long)e, (long long)(last_facts % 2));
    check("a client offering no ALPN completes the handshake with facts saying no ALPN", e == 0 && last_facts >= 0 && last_facts % 2 == 0, line);
    e = stock_client(0, 0, 0, "trust/1");
    snprintf(line, sizeof line, "server error %lld (3 = no certificate)", (long long)e);
    check("a client with no certificate is refused", e == BEES_TLS_E_NO_CERT, line);
    /* D43: no cacertfile: the chain is not verified, whatever the issuer; the pin and the whitelist (BEES's Silica) decide */
    g_no_ca = 1;
    e = engine_pair("r", "a.pem", &bits, seen);
    snprintf(line, sizeof line, "error %lld, verify %lld", (long long)e, (long long)((bits / 4) % 256));
    check("no cacertfile: a certificate from another CA completes the handshake (verify result 0)", e == 0 && (bits / 4) % 256 == 0, line);
    e = engine_pair("w", "a.pem", &bits, seen);
    snprintf(line, sizeof line, "error %lld", (long long)e);
    check("no cacertfile: a self-signed certificate (w.pem) completes the handshake", e == 0, line);
    e = engine_pair("x", "a.pem", &bits, seen);
    snprintf(line, sizeof line, "error %lld", (long long)e);
    check("no cacertfile: an expired certificate completes the handshake (the pin decides)", e == 0, line);
    e = engine_pair("z", "a.pem", &bits, seen);
    snprintf(line, sizeof line, "error %lld", (long long)e);
    check("no cacertfile: an RSA certificate is still refused (signature rule)", e != 0, line);
    e = stock_client(0, 0, 0, "trust/1");
    snprintf(line, sizeof line, "server error %lld (3 = no certificate)", (long long)e);
    check("no cacertfile: a client with no certificate is still refused", e == BEES_TLS_E_NO_CERT, line);
    e = stock_client("b", "X25519", 0, "trust/1");
    snprintf(line, sizeof line, "server error %lld (1 = handshake)", (long long)e);
    check("no cacertfile, no classical flag: a classical-only client is still refused by the engine", e == BEES_TLS_E_HANDSHAKE, line);
    g_no_ca = 0;
    /* D44: with the classical flag the engine also offers X25519; whether a peer may use it is BEES's Silica's judgement */
    g_classical = 1;
    e = stock_client("b", "X25519", 0, "trust/1");
    snprintf(line, sizeof line, "server error %lld, group 0x%llx (NID 1034 is 0x40a)", (long long)e, (long long)(last_facts / 67108864));
    check("classical flag: a classical-only client completes the handshake and the facts say X25519 (NID 1034)", e == 0 && last_facts / 67108864 == 1034, line);
    e = engine_pair("b", "a.pem", &bits, seen);
    snprintf(line, sizeof line, "error %lld, group 0x%llx", (long long)e, (long long)(bits / 67108864));
    check("classical flag: two engines still negotiate X25519MLKEM768", e == 0 && bits / 67108864 == 0x10011ec, line);
    e = stock_client("r", 0, 0, "trust/1");
    snprintf(line, sizeof line, "server error %lld (2 = certificate)", (long long)e);
    check("classical flag, CA configured: a certificate from another CA is still refused", e == BEES_TLS_E_CERT, line);
    g_classical = 0;
    printf("OpenSSL %s; %d failure(s)\n", OpenSSL_version(OPENSSL_VERSION), failures);
    return failures ? 1 : 0;
}
