//! Declarations of the functions of the installed OpenSSL (libssl and libcrypto, version 4.1.0 on the machine this was
//! written on) that the extension calls. Declarations only: there is no C code in this crate. Every call of these
//! functions is in `crypto.rs` or `tls.rs`, inside a safe type that owns the pointer and frees it.
//!
//! Several OpenSSL settings are C macros (SSL_CTX_set_min_proto_version, SSL_CTX_set1_groups_list, ...). A macro cannot
//! be called from Rust, so the function each one expands to, `SSL_CTX_ctrl`, is called with the macro's command number.
//! The numbers below are those of include/openssl/ssl.h, tls1.h, evp.h, obj_mac.h and asn1.h of OpenSSL 4.1.0.
#![allow(non_camel_case_types, non_snake_case, dead_code)]

use std::os::raw::{c_char, c_int, c_long, c_uchar, c_uint, c_ulong, c_void};

macro_rules! opaque {
    ($($name:ident),*) => { $( #[repr(C)] pub struct $name { _private: [u8; 0] } )* };
}
opaque!(SSL_CTX, SSL, SSL_METHOD, SSL_CIPHER, X509, X509_NAME, X509_STORE_CTX, EVP_PKEY, EVP_PKEY_CTX, EVP_MD, EVP_MD_CTX,
        ENGINE, ASN1_INTEGER, ASN1_TIME);

pub const SSL_CTRL_SET_GROUPS_LIST: c_int = 92;
pub const SSL_CTRL_SET_SIGALGS_LIST: c_int = 98;
pub const SSL_CTRL_SET_CLIENT_SIGALGS_LIST: c_int = 102;
pub const SSL_CTRL_SET_MIN_PROTO_VERSION: c_int = 123;
pub const SSL_CTRL_SET_MAX_PROTO_VERSION: c_int = 124;
pub const TLS1_3_VERSION: c_long = 0x0304;
pub const SSL_VERIFY_PEER: c_int = 0x01;
pub const SSL_VERIFY_FAIL_IF_NO_PEER_CERT: c_int = 0x02;
pub const SSL_TLSEXT_ERR_OK: c_int = 0;
pub const SSL_TLSEXT_ERR_ALERT_FATAL: c_int = 2;
pub const SSL_TLSEXT_ERR_NOACK: c_int = 3;
pub const SSL_ERROR_WANT_READ: c_int = 2;
pub const SSL_ERROR_WANT_WRITE: c_int = 3;
pub const SSL_ERROR_SYSCALL: c_int = 5;
pub const SSL_ERROR_ZERO_RETURN: c_int = 6;
pub const EVP_PKEY_ED25519: c_int = 1087;
pub const MBSTRING_UTF8: c_int = 0x1000;

pub type VerifyCallback = extern "C" fn(c_int, *mut X509_STORE_CTX) -> c_int;
pub type AlpnSelectCallback =
    extern "C" fn(*mut SSL, *mut *const c_uchar, *mut c_uchar, *const c_uchar, c_uint, *mut c_void) -> c_int;

#[link(name = "ssl")]
extern "C" {
    pub fn TLS_client_method() -> *const SSL_METHOD;
    pub fn TLS_server_method() -> *const SSL_METHOD;
    pub fn SSL_CTX_new(method: *const SSL_METHOD) -> *mut SSL_CTX;
    pub fn SSL_CTX_free(ctx: *mut SSL_CTX);
    pub fn SSL_CTX_ctrl(ctx: *mut SSL_CTX, cmd: c_int, larg: c_long, parg: *mut c_void) -> c_long;
    pub fn SSL_CTX_set_ciphersuites(ctx: *mut SSL_CTX, names: *const c_char) -> c_int;
    pub fn SSL_CTX_use_certificate(ctx: *mut SSL_CTX, x: *mut X509) -> c_int;
    pub fn SSL_CTX_use_PrivateKey(ctx: *mut SSL_CTX, key: *mut EVP_PKEY) -> c_int;
    pub fn SSL_CTX_check_private_key(ctx: *const SSL_CTX) -> c_int;
    pub fn SSL_CTX_set_verify(ctx: *mut SSL_CTX, mode: c_int, callback: Option<VerifyCallback>);
    pub fn SSL_CTX_set_alpn_select_cb(ctx: *mut SSL_CTX, callback: Option<AlpnSelectCallback>, arg: *mut c_void);
    pub fn SSL_CTX_set_alpn_protos(ctx: *mut SSL_CTX, protos: *const c_uchar, len: c_uint) -> c_int;
    pub fn SSL_new(ctx: *mut SSL_CTX) -> *mut SSL;
    pub fn SSL_free(ssl: *mut SSL);
    pub fn SSL_set_fd(ssl: *mut SSL, fd: c_int) -> c_int;
    pub fn SSL_set_connect_state(ssl: *mut SSL);
    pub fn SSL_set_accept_state(ssl: *mut SSL);
    pub fn SSL_do_handshake(ssl: *mut SSL) -> c_int;
    pub fn SSL_read(ssl: *mut SSL, buf: *mut c_void, num: c_int) -> c_int;
    pub fn SSL_write(ssl: *mut SSL, buf: *const c_void, num: c_int) -> c_int;
    pub fn SSL_get_error(ssl: *const SSL, ret: c_int) -> c_int;
    pub fn SSL_shutdown(ssl: *mut SSL) -> c_int;
    pub fn SSL_get0_alpn_selected(ssl: *const SSL, data: *mut *const c_uchar, len: *mut c_uint);
    pub fn SSL_get_version(ssl: *const SSL) -> *const c_char;
    pub fn SSL_get1_peer_certificate(ssl: *const SSL) -> *mut X509;
    pub fn SSL_get0_group_name(ssl: *mut SSL) -> *const c_char;
    pub fn SSL_get_current_cipher(ssl: *const SSL) -> *const SSL_CIPHER;
    pub fn SSL_CIPHER_get_name(cipher: *const SSL_CIPHER) -> *const c_char;
}

#[link(name = "crypto")]
extern "C" {
    pub fn EVP_sha512() -> *const EVP_MD;
    pub fn EVP_Digest(data: *const c_void, count: usize, md: *mut c_uchar, size: *mut c_uint, kind: *const EVP_MD,
                      engine: *mut ENGINE) -> c_int;
    pub fn RAND_bytes(buf: *mut c_uchar, num: c_int) -> c_int;
    pub fn EVP_PKEY_new_raw_private_key(kind: c_int, engine: *mut ENGINE, key: *const c_uchar, len: usize) -> *mut EVP_PKEY;
    pub fn EVP_PKEY_new_raw_public_key(kind: c_int, engine: *mut ENGINE, key: *const c_uchar, len: usize) -> *mut EVP_PKEY;
    pub fn EVP_PKEY_get_raw_public_key(key: *const EVP_PKEY, out: *mut c_uchar, len: *mut usize) -> c_int;
    pub fn EVP_PKEY_get_base_id(key: *const EVP_PKEY) -> c_int;
    pub fn EVP_PKEY_free(key: *mut EVP_PKEY);
    pub fn EVP_MD_CTX_new() -> *mut EVP_MD_CTX;
    pub fn EVP_MD_CTX_free(ctx: *mut EVP_MD_CTX);
    pub fn EVP_DigestSignInit(ctx: *mut EVP_MD_CTX, pctx: *mut *mut EVP_PKEY_CTX, kind: *const EVP_MD, engine: *mut ENGINE,
                              key: *mut EVP_PKEY) -> c_int;
    pub fn EVP_DigestSign(ctx: *mut EVP_MD_CTX, sig: *mut c_uchar, siglen: *mut usize, tbs: *const c_uchar, tbslen: usize) -> c_int;
    pub fn EVP_DigestVerifyInit(ctx: *mut EVP_MD_CTX, pctx: *mut *mut EVP_PKEY_CTX, kind: *const EVP_MD, engine: *mut ENGINE,
                                key: *mut EVP_PKEY) -> c_int;
    pub fn EVP_DigestVerify(ctx: *mut EVP_MD_CTX, sig: *const c_uchar, siglen: usize, tbs: *const c_uchar, tbslen: usize) -> c_int;
    pub fn ERR_clear_error();
    pub fn ERR_peek_last_error() -> c_ulong;
    pub fn ERR_reason_error_string(e: c_ulong) -> *const c_char;
    pub fn X509_new() -> *mut X509;
    pub fn X509_free(x: *mut X509);
    pub fn d2i_X509(out: *mut *mut X509, input: *mut *const c_uchar, len: c_long) -> *mut X509;
    pub fn i2d_X509(x: *const X509, out: *mut *mut c_uchar) -> c_int;
    pub fn X509_set_version(x: *mut X509, version: c_long) -> c_int;
    pub fn X509_get_serialNumber(x: *mut X509) -> *mut ASN1_INTEGER;
    pub fn ASN1_INTEGER_set(a: *mut ASN1_INTEGER, v: c_long) -> c_int;
    pub fn X509_NAME_new() -> *mut X509_NAME;
    pub fn X509_NAME_free(name: *mut X509_NAME);
    pub fn X509_NAME_add_entry_by_txt(name: *mut X509_NAME, field: *const c_char, kind: c_int, bytes: *const c_uchar,
                                      len: c_int, loc: c_int, set: c_int) -> c_int;
    pub fn X509_NAME_cmp(a: *const X509_NAME, b: *const X509_NAME) -> c_int;
    pub fn X509_set_subject_name(x: *mut X509, name: *const X509_NAME) -> c_int;
    pub fn X509_set_issuer_name(x: *mut X509, name: *const X509_NAME) -> c_int;
    pub fn X509_get_subject_name(x: *const X509) -> *mut X509_NAME;
    pub fn X509_get_issuer_name(x: *const X509) -> *mut X509_NAME;
    pub fn X509_getm_notBefore(x: *mut X509) -> *mut ASN1_TIME;
    pub fn X509_getm_notAfter(x: *mut X509) -> *mut ASN1_TIME;
    pub fn ASN1_TIME_set_string(t: *mut ASN1_TIME, text: *const c_char) -> c_int;
    pub fn X509_set_pubkey(x: *mut X509, key: *mut EVP_PKEY) -> c_int;
    pub fn X509_sign(x: *mut X509, key: *mut EVP_PKEY, md: *const EVP_MD) -> c_int;
    pub fn X509_get0_pubkey(x: *const X509) -> *mut EVP_PKEY;
    pub fn X509_verify(x: *const X509, key: *mut EVP_PKEY) -> c_int;
}
