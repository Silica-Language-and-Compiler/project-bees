/* BEES TRUST mode (N4.1): the TLS engine over the programmer-installed OpenSSL (D40), hosted targets (macOS on Apple
   Silicon built and run; Linux not built). See dangerous_exposure_source/tls/silica_bees_tls_wrapper.h for the interface.

   Shape (spike S12): the engine owns no transport. A connection is an SSL object between two memory BIOs: ciphertext the
   language's (:tcp) carrier delivered is written into the read BIO (bees_tls_feed), ciphertext for the peer is drained
   from the write BIO (bees_tls_pull) and handed to the carrier by the Silica worker. This is where BEES differs from
   Silica's examples/transport_pairs/ethernet_direct_mtls, whose wrapper replaces the socket calls and so owns the
   descriptor (SSL_set_fd); BEES keeps the language's carrier as the only transport and puts TLS between the carrier and
   TRUST's framing (inter-nodal-modes 3.6, mvp.md N4).

   A THIN SHIM (2026-11-12): only what needs C or OpenSSL is here. BEES's Silica (src/trust/dangerous_bees_tls.silica) holds and
   decides everything else: which connections exist (a handle is the connection's address, held only by the link and its writer;
   there is no table here), the OpenSSL minimum-version rule (bees_tls_version reports, the link decides), what a finished
   handshake must show (bees_tls_facts reports ALPN, the certificate, the verify result, the suite and the group; the link
   judges and names them), the client's pin (bees_tls_peer_fp gives the server's SHA-512; the link compares it with
   server_pins_file's) and when a server hands the peer's fingerprint up as its first plaintext, and the paths (the generated
   configuration writes certfile, keyfile and cacertfile, each ended by a NUL).

   Kept here: the SSL_CTX with the fixed TRUST profile (inter-nodal-modes 3.2: TLS 1.3 only; X25519MLKEM768 only, so a
   classical-only peer is refused at the handshake, unless the spec's flag says some whitelist entry is classical-allowed (D44,
   boards, D41): then X25519 is also offered and BEES's Silica refuses a classical connection of any other peer; TLS_AES_256_GCM_SHA384 or TLS_CHACHA20_POLY1305_SHA256;
   Ed25519 or ECDSA P-256 signatures; both certificates, verified against cacertfile only, no system store, within their dates, or, with no
   cacertfile (D43), not chain-verified at all: the pin and the whitelist decide;
   ALPN trust/1 offered by the client and the only one the server selects; no tickets, resumption, 0-RTT, renegotiation or
   compression), the memory BIOs, the handshake with OpenSSL's reasons mapped to small codes, SSL_read and SSL_write, the SHA-512
   of the peer certificate's DER (D11), the ALPN callback, the per-connection lock (two workers use a connection), and freeing.
   The thread's answer span and the { tag, value, error_code } results are the FFI's own conventions (a pointer-plus-length pair
   only as a binding's sole parameters; bytes only through a struct result), so they stay too. */
#include "silica_bees_tls_wrapper.h"
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

#include <openssl/crypto.h>
#include <openssl/err.h>
#include <openssl/evp.h>
#include <openssl/opensslv.h>
#include <openssl/ssl.h>
#include <openssl/x509.h>

#if OPENSSL_VERSION_NUMBER < 0x40100000L
#error "BEES TRUST needs OpenSSL 4.1.0 or later (contract/what-is-required-to-use.md); install it and point OPENSSL_PREFIX at it"
#endif

#define BEES_TLS_MAX_FEED (64u * 1024u * 1024u)
#define BEES_TLS_READ_CAP 16384u   /* one TLS record of plaintext */

static const unsigned char ALPN_TRUST[] = { 7, 't', 'r', 'u', 's', 't', '/', '1' };
/* TEMPUS (development-plan/tempus-design.md 17.6): a second profile beside TRUST's, with its own ALPN and its own contexts,
   so one process (a bridge) holds two credentials. Profile 0 is TRUST and is what every call that does not say otherwise
   gets: bees_tls_set_args(role, 0) before bees_tls_open, as before. Profile 1 is TEMPUS: bees_tls_set_args(role, 1). */
static const unsigned char ALPN_TEMPUS[] = { 8, 't', 'e', 'm', 'p', 'u', 's', '/', '1' };
/* BEAM distribution (N2T, development-plan/spikes/N2T-beam-tls.md): a third profile, for BEAM-mode links to stock Erlang
   nodes started with -proto_dist inet_tls and between BEES nodes. bees_tls_set_args(role, 16): the number is NOT the next one,
   on purpose. Before this profile every number but 0 and 1 was refused by bees_tls_open, and that stays so for every number but
   16 (TEMPUS's self-test, native/tempus/selftest, opens profile 2 to show that a profile that does not exist is refused; its
   golden is unchanged). The contexts are kept by slot (profile_slot), not by the number. It differs from TRUST's in what
   stock Erlang needs and ONLY for this profile (profiles 0 and 1 are untouched): no ALPN (inet_tls_dist uses none; the
   "protocol" of the profile is the empty one, so bees_tls_facts bit 0 says that none was selected); X25519MLKEM768 preferred
   and classical X25519 accepted from any verified peer (stock OTP 28 has no hybrid group; ruled 2026-11-18); a cacertfile is
   REQUIRED (verify_peer against a CA; no pins-only mode here); RSA certificates are accepted beside Ed25519 and ECDSA P-256
   (BEES_TLS_BEAM_RSA_SIGALGS, the one place); and a client checks the server's certificate against a name (the host part of
   the peer's node name, an optional fifth spec field), which it also sends as SNI, as a stock Erlang node does. */
static const unsigned char ALPN_NONE[] = { 0 };
#define BEES_TLS_PROFILE_BEAM 16
/* THE ONE PLACE where BEAM-mode TLS accepts RSA (ruled 2026-11-18, N2T Q4, for interoperation with existing Erlang clusters):
   RSA-PSS signatures only, in the handshake and on certificates (rsa_pss_rsae_*: an ordinary RSA key; rsa_pss_pss_*: an
   RSA-PSS key). PKCS#1 v1.5 (rsa_pkcs1_*) is not in the list, and keys below 2048 bits are refused by security level 2, set
   explicitly for this profile. Remove this list from BEES_TLS_BEAM_SIGALGS to refuse RSA again. */
#define BEES_TLS_BEAM_RSA_SIGALGS ":rsa_pss_rsae_sha256:rsa_pss_rsae_sha384:rsa_pss_rsae_sha512:rsa_pss_pss_sha256:rsa_pss_pss_sha384:rsa_pss_pss_sha512"
#define BEES_TLS_BEAM_SIGALGS "ed25519:ecdsa_secp256r1_sha256" BEES_TLS_BEAM_RSA_SIGALGS
#define BEES_TLS_PROFILES 3   /* slots of the context table: TRUST, TEMPUS, BEAM */
/* the context slot of a profile number, or -1 for a number that names no profile (refused by bees_tls_open) */
static int profile_slot(int64_t profile) { return profile == 0 ? 0 : profile == 1 ? 1 : profile == BEES_TLS_PROFILE_BEAM ? 2 : -1; }
static const unsigned char *alpn_of(int profile) { return profile == BEES_TLS_PROFILE_BEAM ? ALPN_NONE : profile == 1 ? ALPN_TEMPUS : ALPN_TRUST; }

/* ---- the thread's answer span (taken by bees_tls_take in the same dispatch) ------------------------------------------ */
static _Thread_local int64_t arg_a = 0;
static _Thread_local int64_t arg_b = 0;   /* bees_tls_open: the profile (0 TRUST, 1 TEMPUS); unused by the other calls */
static _Thread_local uint8_t *span = 0;
static _Thread_local uint64_t span_len = 0;

static bees_tls_tagged ok(int64_t v) { bees_tls_tagged r = {0, v, 0}; return r; }
static bees_tls_tagged fail(int64_t code) { bees_tls_tagged r = {1, 0, code}; return r; }
static bees_tls_tagged nothing(void) { bees_tls_tagged r = {2, 0, 0}; return r; }
static bees_tls_tagged closed(void) { bees_tls_tagged r = {3, 0, 0}; return r; }

static void span_drop(void) { free(span); span = 0; span_len = 0; }
static int span_set(const uint8_t *p, uint64_t n) {
    span_drop();
    if (n == 0) return 1;
    span = (uint8_t *)malloc((size_t)n);
    if (span == 0) return 0;
    memcpy(span, p, (size_t)n);
    span_len = n;
    return 1;
}

/* ---- contexts: one per profile and role, built once from the paths the first open of that profile and role names ----- */
static pthread_mutex_t ctx_lock = PTHREAD_MUTEX_INITIALIZER;
static SSL_CTX *ctxs[BEES_TLS_PROFILES][3] = {{0, 0, 0}, {0, 0, 0}, {0, 0, 0}};

/* D43: with no cacertfile the chain is not verified against any CA: a self-signed or any-issuer certificate, within or past its
   dates, is accepted by the handshake and BEES's Silica judges the peer by the SHA-512 of its DER (D11) and the whitelist.
   The certificate must still be presented (SSL_VERIFY_FAIL_IF_NO_PEER_CERT) and sign with Ed25519 or ECDSA P-256 (sigalgs). */
static int accept_any_chain_cb(X509_STORE_CTX *store_ctx, void *arg) {
    (void)store_ctx; (void)arg;
    return 1;   /* the X509 verify result stays X509_V_OK: bees_tls_facts reports 0, as for a verified chain */
}


static int alpn_select(SSL *ssl, const unsigned char **out, unsigned char *outlen, const unsigned char *in,
                       unsigned int inlen, void *arg) {
    (void)ssl;
    const unsigned char *want = (const unsigned char *)arg;   /* the context's one protocol, length first */
    unsigned int i = 0;
    while (i < inlen) {
        unsigned int n = in[i];
        if (i + 1 + n > inlen) break;
        if (n == want[0] && memcmp(in + i + 1, want + 1, n) == 0) {
            *out = in + i + 1;
            *outlen = (unsigned char)n;
            return SSL_TLSEXT_ERR_OK;
        }
        i += 1 + n;
    }
    return SSL_TLSEXT_ERR_ALERT_FATAL;   /* no_application_protocol */
}

static SSL_CTX *make_ctx(int role, const char *cert, const char *key, const char *ca, int classical, int profile) {
    const unsigned char *alpn = alpn_of(profile);
    int beam = profile == BEES_TLS_PROFILE_BEAM;   /* N2T: see ALPN_NONE above; every other profile takes the paths it took before */
    if (beam) classical = 1;                       /* X25519 beside the hybrid, from any verified peer (ruled 2026-11-18, Q2) */
    if (beam && ca[0] == 0) return 0;              /* BEAM mode verifies against a CA; there is no pins-only mode */
    SSL_CTX *c = SSL_CTX_new(TLS_method());
    if (c == 0) return 0;
    if (beam) SSL_CTX_set_security_level(c, 2);    /* RSA and DH keys of at least 2048 bits, no SHA-1 or MD5 signatures */
    int good = SSL_CTX_set_min_proto_version(c, TLS1_3_VERSION) == 1
        && SSL_CTX_set_max_proto_version(c, TLS1_3_VERSION) == 1
        && SSL_CTX_set_ciphersuites(c, "TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256") == 1
        /* D44: X25519MLKEM768 only, unless some whitelist entry is marked classical-allowed: then X25519 is also offered, and
           BEES's Silica refuses, after the handshake, a classical connection whose peer is not such an entry */
        && SSL_CTX_set1_groups_list(c, classical ? "X25519MLKEM768:X25519" : "X25519MLKEM768") == 1
        && SSL_CTX_set1_sigalgs_list(c, beam ? BEES_TLS_BEAM_SIGALGS : "ed25519:ecdsa_secp256r1_sha256") == 1
        && SSL_CTX_use_certificate_chain_file(c, cert) == 1
        && SSL_CTX_use_PrivateKey_file(c, key, SSL_FILETYPE_PEM) == 1
        && SSL_CTX_check_private_key(c) == 1
        && (ca[0] == 0 || SSL_CTX_load_verify_file(c, ca) == 1);   /* the configured CA only: no default paths, no system store */
    if (!good) { ERR_clear_error(); SSL_CTX_free(c); return 0; }
    SSL_CTX_set_options(c, SSL_OP_NO_COMPRESSION | SSL_OP_NO_RENEGOTIATION | SSL_OP_NO_TICKET);
    SSL_CTX_set_num_tickets(c, 0);
    SSL_CTX_set_max_early_data(c, 0);
    SSL_CTX_set_session_cache_mode(c, SSL_SESS_CACHE_OFF);
    if (classical) SSL_CTX_set_options(c, SSL_OP_CIPHER_SERVER_PREFERENCE);   /* a server picks the hybrid group whenever the peer offers it */
    SSL_CTX_set_verify(c, SSL_VERIFY_PEER | SSL_VERIFY_FAIL_IF_NO_PEER_CERT, 0);
    if (ca[0] == 0) SSL_CTX_set_cert_verify_callback(c, accept_any_chain_cb, 0);
    SSL_CTX_set_verify_depth(c, 4);
    if (beam) {
        /* no ALPN: a client offers none, and a server selects none whatever the client offers */
    } else if (role == 1) {
        if (SSL_CTX_set_alpn_protos(c, alpn, (unsigned int)alpn[0] + 1) != 0) { SSL_CTX_free(c); return 0; }
    } else {
        SSL_CTX_set_alpn_select_cb(c, alpn_select, (void *)alpn);
    }
    return c;
}

static SSL_CTX *ctx_for(int role, const char *cert, const char *key, const char *ca, int classical, int profile) {
    SSL_CTX *c;
    pthread_mutex_lock(&ctx_lock);
    int slot = profile_slot(profile);   /* bees_tls_open has refused a number that names no profile */
    if (ctxs[slot][role] == 0) ctxs[slot][role] = make_ctx(role, cert, key, ca, classical, profile);   /* a failure is retried at the next open */
    c = ctxs[slot][role];
    pthread_mutex_unlock(&ctx_lock);
    return c;
}

#ifdef BEES_TLS_SELFTEST
/* TEST ONLY (native/tls/selftest): forget both contexts so the next open loads another identity. Never in a node. */
void bees_tls_selftest_reset(void) {
    pthread_mutex_lock(&ctx_lock);
    for (int p = 0; p < BEES_TLS_PROFILES; p++) for (int i = 0; i < 3; i++) { SSL_CTX_free(ctxs[p][i]); ctxs[p][i] = 0; }
    pthread_mutex_unlock(&ctx_lock);
}
#endif

/* ---- connections --------------------------------------------------------------------------------------------------- */
typedef struct conn {
    uint64_t magic;
    pthread_mutex_t lock;   /* two workers use a connection (the link worker feeds and reads, the writer writes and pulls) */
    SSL *ssl;
    BIO *rbio, *wbio;
    int done;            /* the handshake finished (what it shows is judged by BEES's Silica: bees_tls_facts) */
    const unsigned char *alpn;   /* the protocol of the connection's profile, length first (trust/1 or tempus/1) */
} conn;

/* No table: a handle is the connection's address, held only by the two BEES workers that use the connection (the link and its
   writer, src/trust/dangerous_bees_tls.silica), which hand it to no one and stop using it before the writer frees it. A magic
   word refuses a handle that is not a live connection. A connection is used with its lock held (conn_get ... conn_put_back). */
#define BEES_TLS_MAGIC 0x42454553544c5331ULL   /* "BEESTLS1" */

static conn *conn_get(int64_t h) {
    conn *c = (conn *)(intptr_t)h;
    if (c == 0 || c->magic != BEES_TLS_MAGIC) return 0;
    pthread_mutex_lock(&c->lock);
    return c;
}

static void conn_put_back(conn *c) { if (c != 0) pthread_mutex_unlock(&c->lock); }

static int64_t conn_add(conn *c) {
    c->magic = BEES_TLS_MAGIC;
    return (int64_t)(intptr_t)c;
}

/* answers the connection locked and no longer live, or 0 */
static conn *conn_remove(int64_t h) {
    conn *c = conn_get(h);
    if (c != 0) c->magic = 0;
    return c;
}

static void conn_destroy(conn *c) {
    SSL_free(c->ssl);
    pthread_mutex_unlock(&c->lock);
    pthread_mutex_destroy(&c->lock);
    OPENSSL_cleanse(c, sizeof *c);
    free(c);
}

/* the installed OpenSSL's version number (0xMNNFFPPS); BEES decides whether it may run */
bees_tls_tagged bees_tls_version(int64_t unused) { (void)unused; return ok((int64_t)OpenSSL_version_num()); }

bees_tls_tagged bees_tls_set_args(int64_t a, int64_t b) { arg_a = a; arg_b = b; return ok(0); }

/* Opens a connection in role a (1 client, 2 server). spec: certfile, keyfile and cacertfile (empty: no CA, D43 pins only) and an
   optional flag "1" (D44), each ended by a NUL byte (made by BEES's generated configuration). A client's ClientHello is ready to pull at once. value: the handle. */
bees_tls_tagged bees_tls_open(const uint8_t *spec_ptr, uint64_t spec_len) {
    const char *f[3];
    int classical = 0;
    uint64_t at = 0;
    int role = (int)arg_a;
    int profile = (int)arg_b;   /* 0 TRUST (every caller before TEMPUS passes 0), 1 TEMPUS, 16 BEAM distribution (N2T) */
    if ((role != 1 && role != 2) || spec_ptr == 0) return fail(BEES_TLS_E_STATE);
    if (profile_slot(arg_b) < 0) return fail(BEES_TLS_E_STATE);   /* 0, 1 and 16 (BEAM) exist; every other number is refused, as before */
    for (int i = 0; i < 3; i++) {
        const uint8_t *z = at < spec_len ? memchr(spec_ptr + at, 0, (size_t)(spec_len - at)) : 0;
        if (z == 0) return fail(BEES_TLS_E_IDENTITY);
        f[i] = (const char *)spec_ptr + at;
        at = (uint64_t)(z - spec_ptr) + 1;
    }
    /* an optional fourth field (D44): "1" offers X25519 beside X25519MLKEM768; absent or anything else, the hybrid only */
    if (at < spec_len) {
        const uint8_t *z = memchr(spec_ptr + at, 0, (size_t)(spec_len - at));
        if (z == 0) return fail(BEES_TLS_E_IDENTITY);
        classical = (z - (spec_ptr + at)) == 1 && spec_ptr[at] == '1';
        at = (uint64_t)(z - spec_ptr) + 1;
    }
    /* BEAM profile only (N2T): an optional fifth field, the name a client checks the server's certificate against */
    const char *host = 0;
    if (profile == BEES_TLS_PROFILE_BEAM && role == 1 && at < spec_len) {
        const uint8_t *z = memchr(spec_ptr + at, 0, (size_t)(spec_len - at));
        if (z == 0) return fail(BEES_TLS_E_IDENTITY);
        if (z > spec_ptr + at) host = (const char *)spec_ptr + at;
    }
    SSL_CTX *ctx = ctx_for(role, f[0], f[1], f[2], classical, profile);
    if (ctx == 0) return fail(BEES_TLS_E_IDENTITY);
    conn *c = (conn *)calloc(1, sizeof *c);
    if (c == 0) return fail(BEES_TLS_E_TABLE);
    pthread_mutex_init(&c->lock, 0);
    c->alpn = alpn_of(profile);
    c->ssl = SSL_new(ctx);
    c->rbio = BIO_new(BIO_s_mem());
    c->wbio = BIO_new(BIO_s_mem());
    if (c->ssl == 0 || c->rbio == 0 || c->wbio == 0) {
        if (c->ssl) SSL_free(c->ssl);
        BIO_free(c->rbio); BIO_free(c->wbio);
        pthread_mutex_destroy(&c->lock);
        free(c);
        return fail(BEES_TLS_E_TABLE);
    }
    if (host != 0) {
        /* the name is checked against the certificate (a DNS name or an IP address literal); SNI carries DNS names only */
        int is_ip = strchr(host, ':') != 0 || strspn(host, "0123456789.") == strlen(host);
        if ((is_ip ? SSL_set1_ipaddr(c->ssl, host) : SSL_set1_dnsname(c->ssl, host)) != 1
            || (!is_ip && SSL_set_tlsext_host_name(c->ssl, host) != 1)) {
            ERR_clear_error();
            SSL_free(c->ssl); BIO_free(c->rbio); BIO_free(c->wbio);
            pthread_mutex_destroy(&c->lock);
            free(c);
            return fail(BEES_TLS_E_IDENTITY);
        }
    }
    BIO_set_mem_eof_return(c->rbio, -1);   /* an empty read BIO means "more ciphertext needed", not EOF */
    SSL_set_bio(c->ssl, c->rbio, c->wbio);
    if (role == 1) SSL_set_connect_state(c->ssl); else SSL_set_accept_state(c->ssl);
    if (role == 1) { (void)SSL_do_handshake(c->ssl); ERR_clear_error(); }   /* the ClientHello, ready to pull */
    int64_t h = conn_add(c);
    if (h < 0) { SSL_free(c->ssl); pthread_mutex_destroy(&c->lock); free(c); return fail(BEES_TLS_E_TABLE); }
    return ok(h);
}

/* Ciphertext from the peer (handle: set_args a); while the handshake runs it is driven. value: 1 the handshake finished in
   this call, 2 it had finished before, 0 it goes on; plus 4 when there is ciphertext to pull. Errors (OpenSSL's reason as a
   small code): 1 the handshake failed, 2 the peer's certificate did not verify, 3 the peer sent none, 4 no common ALPN.
   What a finished handshake shows is judged by BEES's Silica (bees_tls_facts, bees_tls_peer_fp). */
static bees_tls_tagged feed_locked(conn *c, const uint8_t *data_ptr, uint64_t data_len);
bees_tls_tagged bees_tls_feed(const uint8_t *data_ptr, uint64_t data_len) {
    conn *c = conn_get(arg_a);
    if (c == 0) return fail(BEES_TLS_E_STATE);
    bees_tls_tagged r = feed_locked(c, data_ptr, data_len);
    conn_put_back(c);
    return r;
}
static int64_t pending(conn *c) { return BIO_ctrl_pending(c->wbio) > 0 ? 4 : 0; }
static bees_tls_tagged feed_locked(conn *c, const uint8_t *data_ptr, uint64_t data_len) {
    if (data_len > BEES_TLS_MAX_FEED) return fail(BEES_TLS_E_HANDSHAKE);
    if (data_len > 0 && BIO_write(c->rbio, data_ptr, (int)data_len) != (int)data_len) return fail(BEES_TLS_E_STATE);
    if (c->done) return ok(2 + pending(c));
    int r = SSL_do_handshake(c->ssl);
    if (r == 1) { ERR_clear_error(); c->done = 1; return ok(1 + pending(c)); }
    int e = SSL_get_error(c->ssl, r);
    if (e == SSL_ERROR_WANT_READ || e == SSL_ERROR_WANT_WRITE) { ERR_clear_error(); return ok(pending(c)); }
    long v = SSL_get_verify_result(c->ssl);
    unsigned long reason = ERR_peek_last_error();
    ERR_clear_error();
    if (v != X509_V_OK) return fail(BEES_TLS_E_CERT);
    if (ERR_GET_REASON(reason) == SSL_R_PEER_DID_NOT_RETURN_A_CERTIFICATE) return fail(BEES_TLS_E_NO_CERT);
    if (ERR_GET_REASON(reason) == SSL_R_NO_APPLICATION_PROTOCOL) return fail(BEES_TLS_E_ALPN);
    return fail(BEES_TLS_E_HANDSHAKE);
}

/* What a finished handshake shows, for BEES to judge: value = alpn_is_trust_1 + 2 * peer_presented_a_certificate
   + 4 * (the chain's X509 verify result, 0 for OK, below 256) + 1024 * (the suite's IANA id, 16 bits)
   + 2^26 * (SSL_get_negotiated_group: an OpenSSL NID, or 0x1000000 + the IANA id for a group without a NID). */
bees_tls_tagged bees_tls_facts(int64_t handle) {
    conn *c = conn_get(handle);
    if (c == 0) return fail(BEES_TLS_E_STATE);
    const unsigned char *alpn = 0;
    unsigned int alpn_len = 0;
    SSL_get0_alpn_selected(c->ssl, &alpn, &alpn_len);
    /* bit 0: the selected protocol is the one of the connection's profile (trust/1 for TRUST, as before; tempus/1 for TEMPUS) */
    /* (the BEAM profile's protocol is the empty one: its bit 0 says that no ALPN was selected) */
    int64_t trust = alpn_len == c->alpn[0] && (alpn_len == 0 || memcmp(alpn, c->alpn + 1, alpn_len) == 0);
    int64_t has_cert = SSL_get0_peer_certificate(c->ssl) != 0;
    int64_t verify = SSL_get_verify_result(c->ssl) & 0xff;
    const SSL_CIPHER *suite = SSL_get_current_cipher(c->ssl);
    int64_t suite_id = suite ? SSL_CIPHER_get_protocol_id(suite) & 0xffff : 0;
    int64_t group = (int64_t)SSL_get_negotiated_group(c->ssl) & 0x1ffffff;
    int done = c->done;
    conn_put_back(c);
    return done ? ok(trust + 2 * has_cert + 4 * verify + 1024 * suite_id + (group << 26)) : fail(BEES_TLS_E_STATE);
}

/* The SHA-512 of the peer certificate's full DER (D11) into the thread's span; value 64, or an error without a certificate. */
bees_tls_tagged bees_tls_peer_fp(int64_t handle) {
    span_drop();
    conn *c = conn_get(handle);
    if (c == 0) return fail(BEES_TLS_E_STATE);
    X509 *peer = SSL_get0_peer_certificate(c->ssl);
    unsigned int n = 0;
    uint8_t md[64];
    int got = peer != 0 && X509_digest(peer, EVP_sha512(), md, &n) == 1 && n == 64;
    conn_put_back(c);
    if (!got || !span_set(md, 64)) return fail(BEES_TLS_E_NO_CERT);
    return ok(64);
}

/* TEMPUS: the raw public key of the peer certificate into the thread's span; value 32. Only an Ed25519 key is answered:
   any other key type is refused (BEES_TLS_E_CERT), as is a connection without a peer certificate (BEES_TLS_E_NO_CERT). A
   TEMPUS node compares these bytes with the `pub` of the peer's advert, which ties the TLS channel to the identity that
   then proves possession (development-plan/tempus-design.md section 4). TRUST does not call this. */
bees_tls_tagged bees_tls_peer_key(int64_t handle) {
    span_drop();
    conn *c = conn_get(handle);
    if (c == 0) return fail(BEES_TLS_E_STATE);
    X509 *peer = SSL_get0_peer_certificate(c->ssl);
    EVP_PKEY *key = peer != 0 ? X509_get0_pubkey(peer) : 0;
    uint8_t raw[32];
    size_t n = sizeof raw;
    int ed = key != 0 && EVP_PKEY_get_base_id(key) == EVP_PKEY_ED25519;
    int got = ed && EVP_PKEY_get_raw_public_key(key, raw, &n) == 1 && n == 32;
    conn_put_back(c);
    if (peer == 0) return fail(BEES_TLS_E_NO_CERT);
    if (!got || !span_set(raw, 32)) return fail(BEES_TLS_E_CERT);
    return ok(32);
}

/* Drops the ciphertext not yet pulled: a client that refuses the server does not send its Finished. */
bees_tls_tagged bees_tls_discard(int64_t handle) {
    conn *c = conn_get(handle);
    if (c == 0) return fail(BEES_TLS_E_STATE);
    (void)BIO_reset(c->wbio);
    conn_put_back(c);
    return ok(0);
}

/* Plaintext for the peer, once the handshake is done; the ciphertext is then ready to pull. */
bees_tls_tagged bees_tls_write(const uint8_t *data_ptr, uint64_t data_len) {
    conn *c = conn_get(arg_a);
    if (c == 0) return fail(BEES_TLS_E_STATE);
    if (!c->done) { conn_put_back(c); return fail(BEES_TLS_E_STATE); }
    uint64_t at = 0;
    while (at < data_len) {
        size_t piece = (size_t)(data_len - at);
        if (piece > 16384) piece = 16384;
        int w = SSL_write(c->ssl, data_ptr + at, (int)piece);
        if (w <= 0) { ERR_clear_error(); conn_put_back(c); return fail(BEES_TLS_E_STATE); }
        at += (uint64_t)w;
    }
    conn_put_back(c);
    return ok((int64_t)at);
}

/* Moves every pending byte of ciphertext into the thread's span; value is the count (0: nothing to send). */
bees_tls_tagged bees_tls_pull(int64_t handle) {
    span_drop();
    conn *c = conn_get(handle);
    if (c == 0) return fail(BEES_TLS_E_STATE);
    size_t n = BIO_ctrl_pending(c->wbio);
    int got = 0;
    if (n > 0 && (span = (uint8_t *)malloc(n)) != 0) {
        got = BIO_read(c->wbio, span, (int)n);
        if (got <= 0) { span_drop(); got = 0; } else span_len = (uint64_t)got;
    }
    conn_put_back(c);
    return ok(got);
}

/* Plaintext from the peer into the thread's span, at most max bytes; value is the count. A server first answers the
   peer's 64-byte certificate fingerprint, once. Tag 2: nothing decrypted yet (feed more ciphertext); tag 3: the peer
   sent close_notify. */
bees_tls_tagged bees_tls_read(int64_t handle, int64_t max) {
    span_drop();
    conn *c = conn_get(handle);
    if (c == 0) return fail(BEES_TLS_E_STATE);
    bees_tls_tagged r;
    if (!c->done) r = fail(BEES_TLS_E_STATE);
    else {
        /* at most one TLS record's plaintext per call, straight into a malloc'd span (no per-thread buffer: a large
           _Thread_local buffer was kept for every actor thread that read, about 1 MiB per connection on a server) */
        size_t cap = (max > 0 && (uint64_t)max < BEES_TLS_READ_CAP) ? (size_t)max : BEES_TLS_READ_CAP;
        uint8_t *buf = (uint8_t *)malloc(cap);
        int got = buf ? SSL_read(c->ssl, buf, (int)cap) : -1;
        if (buf == 0) r = fail(BEES_TLS_E_TABLE);
        else if (got > 0) { span = buf; span_len = (uint64_t)got; r = ok(got); }
        else {
            int e = SSL_get_error(c->ssl, got);
            free(buf);
            ERR_clear_error();
            if (e == SSL_ERROR_WANT_READ || e == SSL_ERROR_WANT_WRITE) r = nothing();
            else if (e == SSL_ERROR_ZERO_RETURN) r = closed();
            else r = fail(BEES_TLS_E_HANDSHAKE);   /* a fatal alert (in TLS 1.3 a refused client certificate arrives here) */
        }
    }
    conn_put_back(c);
    return r;
}

/* Sends close_notify (ready to pull) and frees the connection; value is the count of ciphertext bytes in the span. */
bees_tls_tagged bees_tls_close(int64_t handle) {
    span_drop();
    conn *c = conn_remove(handle);
    if (c == 0) return ok(0);
    if (c->done) { (void)SSL_shutdown(c->ssl); ERR_clear_error(); }
    size_t n = BIO_ctrl_pending(c->wbio);
    int64_t got = 0;
    if (n > 0 && (span = (uint8_t *)malloc(n)) != 0) {
        int r = BIO_read(c->wbio, span, (int)n);
        if (r > 0) { span_len = (uint64_t)r; got = r; } else span_drop();
    }
    conn_destroy(c);
    return ok(got);
}

/* Frees a connection without a close_notify (the carrier has already gone, or the handshake was given up). */
bees_tls_tagged bees_tls_free(int64_t handle) {
    conn *c = conn_remove(handle);
    if (c != 0) conn_destroy(c);
    return ok(0);
}

bees_tls_bytes bees_tls_take(int64_t handle) {
    bees_tls_bytes r;
    (void)handle;
    r.tag = 0; r.text_ptr = 0; r.text_len = 0; r.error_code = 0;
    if (span_len > 0) {
        r.text_ptr = span;   /* ownership passes to the compiler's string-out helper, which frees it */
        r.text_len = span_len;
        span = 0;
        span_len = 0;
    }
    return r;
}
