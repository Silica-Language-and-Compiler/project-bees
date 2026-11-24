//! Ed25519, SHA-512, random bytes and certificates, through the OpenSSL installed on the machine.
//! Every `unsafe` block here is one call, or one short run of calls, of the functions declared in `ffi`, inside a type
//! that owns the pointer and frees it when it is dropped.
use crate::ffi;
use crate::{Fault, Refused};
use std::ffi::CString;
use std::os::raw::{c_int, c_long, c_uint, c_void};
use std::ptr;

/// The SHA-512 of some bytes: 64 bytes.
pub fn sha512(data: &[u8]) -> Vec<u8> {
    let mut out = vec![0u8; 64];
    let mut n: c_uint = 0;
    // SAFETY: `data` and `out` are live for the call; `out` has the 64 bytes SHA-512 writes.
    let ok = unsafe { ffi::EVP_Digest(data.as_ptr() as *const c_void, data.len(), out.as_mut_ptr(), &mut n, ffi::EVP_sha512(), ptr::null_mut()) };
    assert!(ok == 1 && n == 64, "SHA-512 failed");
    out
}

/// The identity of a public key: its SHA-512 (design section 4).
pub fn peer_id(public_key: &[u8]) -> Vec<u8> {
    sha512(public_key)
}

/// Bytes from the system's secure random source (through OpenSSL).
pub fn random_bytes(n: usize) -> Result<Vec<u8>, Fault> {
    let mut out = vec![0u8; n];
    // SAFETY: `out` has `n` bytes.
    if unsafe { ffi::RAND_bytes(out.as_mut_ptr(), n as c_int) } != 1 {
        return Err(Fault::new("no random bytes"));
    }
    Ok(out)
}

pub(crate) fn clear_errors() {
    // SAFETY: clears this thread's OpenSSL error queue; no pointer is involved.
    unsafe { ffi::ERR_clear_error() }
}

/// A digest context, freed when dropped.
struct MdCtx(*mut ffi::EVP_MD_CTX);

impl MdCtx {
    fn new() -> Option<MdCtx> {
        // SAFETY: returns a new context or null.
        let p = unsafe { ffi::EVP_MD_CTX_new() };
        if p.is_null() { None } else { Some(MdCtx(p)) }
    }
}

impl Drop for MdCtx {
    fn drop(&mut self) {
        // SAFETY: the pointer came from EVP_MD_CTX_new and is freed once.
        unsafe { ffi::EVP_MD_CTX_free(self.0) }
    }
}

/// An Ed25519 private key, made from its 32-byte seed. The seed is not kept, and the key is never written or sent.
pub struct SigningKey {
    pkey: *mut ffi::EVP_PKEY,
    public: Vec<u8>,
}

// SAFETY: an EVP_PKEY is reference counted and is only read after it is made; OpenSSL allows its use from several
// threads, each with a digest context of its own, which is how `sign` uses it.
unsafe impl Send for SigningKey {}
unsafe impl Sync for SigningKey {}

impl SigningKey {
    pub fn from_seed(seed: &[u8]) -> Result<SigningKey, Fault> {
        if seed.len() != 32 {
            return Err(Fault::new("an Ed25519 seed is 32 bytes"));
        }
        // SAFETY: `seed` has 32 bytes; the result is owned by the SigningKey made below, or is null.
        let pkey = unsafe { ffi::EVP_PKEY_new_raw_private_key(ffi::EVP_PKEY_ED25519, ptr::null_mut(), seed.as_ptr(), 32) };
        if pkey.is_null() {
            clear_errors();
            return Err(Fault::new("the Ed25519 key could not be made"));
        }
        let mut key = SigningKey { pkey, public: Vec::new() };
        match raw_public(pkey) {
            Some(p) => key.public = p,
            None => return Err(Fault::new("the Ed25519 public key could not be read")),
        }
        Ok(key)
    }

    /// The 32-byte public key.
    pub fn public(&self) -> &[u8] {
        &self.public
    }

    /// The Ed25519 signature of a message: 64 bytes, the same bytes on every call (RFC 8032).
    pub fn sign(&self, message: &[u8]) -> Result<Vec<u8>, Fault> {
        let ctx = MdCtx::new().ok_or_else(|| Fault::new("no digest context"))?;
        let mut sig = vec![0u8; 64];
        let mut n: usize = 64;
        // SAFETY: the context and the key are live; `sig` has the 64 bytes an Ed25519 signature takes.
        let ok = unsafe {
            ffi::EVP_DigestSignInit(ctx.0, ptr::null_mut(), ptr::null(), ptr::null_mut(), self.pkey) == 1
                && ffi::EVP_DigestSign(ctx.0, sig.as_mut_ptr(), &mut n, message.as_ptr(), message.len()) == 1
        };
        if !ok || n != 64 {
            clear_errors();
            return Err(Fault::new("the signature could not be made"));
        }
        Ok(sig)
    }

    pub(crate) fn raw(&self) -> *mut ffi::EVP_PKEY {
        self.pkey
    }
}

impl Drop for SigningKey {
    fn drop(&mut self) {
        // SAFETY: the pointer came from EVP_PKEY_new_raw_private_key and is freed once.
        unsafe { ffi::EVP_PKEY_free(self.pkey) }
    }
}

fn raw_public(pkey: *const ffi::EVP_PKEY) -> Option<Vec<u8>> {
    let mut raw = vec![0u8; 32];
    let mut n: usize = 32;
    // SAFETY: `pkey` is a live key; `raw` has 32 bytes and `n` says so.
    let ok = unsafe { ffi::EVP_PKEY_get_raw_public_key(pkey, raw.as_mut_ptr(), &mut n) };
    if ok == 1 && n == 32 { Some(raw) } else { clear_errors(); None }
}

/// True when `sig` is the Ed25519 signature of `message` under the raw 32-byte public key `public_key`.
pub fn ed25519_verify(public_key: &[u8], message: &[u8], sig: &[u8]) -> bool {
    if public_key.len() != 32 || sig.len() != 64 {
        return false;
    }
    // SAFETY: `public_key` has 32 bytes; the key is freed below.
    let k = unsafe { ffi::EVP_PKEY_new_raw_public_key(ffi::EVP_PKEY_ED25519, ptr::null_mut(), public_key.as_ptr(), 32) };
    if k.is_null() {
        clear_errors();
        return false;
    }
    let ok = match MdCtx::new() {
        // SAFETY: the context and the key are live; the lengths are those of the slices.
        Some(ctx) => unsafe {
            ffi::EVP_DigestVerifyInit(ctx.0, ptr::null_mut(), ptr::null(), ptr::null_mut(), k) == 1
                && ffi::EVP_DigestVerify(ctx.0, sig.as_ptr(), sig.len(), message.as_ptr(), message.len()) == 1
        },
        None => false,
    };
    // SAFETY: `k` came from EVP_PKEY_new_raw_public_key and is freed once.
    unsafe { ffi::EVP_PKEY_free(k) };
    clear_errors();
    ok
}

// ---------------------------------------------------------------- certificates
/// An X.509 certificate held by OpenSSL, freed when dropped.
pub(crate) struct Certificate(*mut ffi::X509);

impl Certificate {
    /// The certificate of exactly these DER bytes; None when they do not parse or bytes follow the certificate.
    pub(crate) fn from_der(der: &[u8]) -> Option<Certificate> {
        let mut p = der.as_ptr();
        // SAFETY: `p` points at `der.len()` readable bytes; d2i_X509 moves `p` past what it read.
        let x = unsafe { ffi::d2i_X509(ptr::null_mut(), &mut p, der.len() as c_long) };
        if x.is_null() {
            clear_errors();
            return None;
        }
        let cert = Certificate(x);
        if p as usize != der.as_ptr() as usize + der.len() {
            return None;
        }
        Some(cert)
    }

    /// Takes a pointer that the caller owns (one reference).
    pub(crate) fn from_owned(x: *mut ffi::X509) -> Option<Certificate> {
        if x.is_null() { None } else { Some(Certificate(x)) }
    }

    pub(crate) fn raw(&self) -> *mut ffi::X509 {
        self.0
    }

    pub(crate) fn der(&self) -> Option<Vec<u8>> {
        // SAFETY: with a null output pointer i2d_X509 only returns the length.
        let n = unsafe { ffi::i2d_X509(self.0, ptr::null_mut()) };
        if n <= 0 {
            return None;
        }
        let mut out = vec![0u8; n as usize];
        let mut p = out.as_mut_ptr();
        // SAFETY: `out` has the `n` bytes i2d_X509 said it writes.
        let written = unsafe { ffi::i2d_X509(self.0, &mut p) };
        if written == n { Some(out) } else { None }
    }

    /// The raw Ed25519 public key of the certificate; None when its key is of another kind.
    pub(crate) fn ed25519_key(&self) -> Option<Vec<u8>> {
        // SAFETY: the certificate is live; the key pointer belongs to it and is not freed here.
        let k = unsafe { ffi::X509_get0_pubkey(self.0) };
        if k.is_null() {
            clear_errors();
            return None;
        }
        // SAFETY: `k` is live as long as the certificate.
        if unsafe { ffi::EVP_PKEY_get_base_id(k) } != ffi::EVP_PKEY_ED25519 {
            return None;
        }
        raw_public(k)
    }

    /// True when the issuer is the subject and the certificate's signature verifies under its own key.
    fn self_signed(&self) -> bool {
        // SAFETY: the certificate is live; the name and key pointers belong to it.
        let ok = unsafe {
            let k = ffi::X509_get0_pubkey(self.0);
            !k.is_null()
                && ffi::X509_NAME_cmp(ffi::X509_get_issuer_name(self.0), ffi::X509_get_subject_name(self.0)) == 0
                && ffi::X509_verify(self.0, k) == 1
        };
        clear_errors();
        ok
    }
}

impl Drop for Certificate {
    fn drop(&mut self) {
        // SAFETY: the pointer is one owned reference, freed once.
        unsafe { ffi::X509_free(self.0) }
    }
}

const B64: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

fn base64_encode(data: &[u8]) -> String {
    let mut out = String::new();
    for chunk in data.chunks(3) {
        let a = chunk[0];
        let b = *chunk.get(1).unwrap_or(&0);
        let c = *chunk.get(2).unwrap_or(&0);
        out.push(B64[(a >> 2) as usize] as char);
        out.push(B64[(((a & 3) << 4) | (b >> 4)) as usize] as char);
        out.push(if chunk.len() > 1 { B64[(((b & 15) << 2) | (c >> 6)) as usize] as char } else { '=' });
        out.push(if chunk.len() > 2 { B64[(c & 63) as usize] as char } else { '=' });
    }
    out
}

fn base64_decode(text: &str) -> Option<Vec<u8>> {
    let mut out = Vec::new();
    let (mut acc, mut bits) = (0u32, 0u32);
    for ch in text.bytes() {
        if ch == b'=' {
            continue;
        }
        let v = B64.iter().position(|&x| x == ch)? as u32;
        acc = (acc << 6) | v;
        bits += 6;
        if bits >= 8 {
            bits -= 8;
            out.push(((acc >> bits) & 0xFF) as u8);
        }
    }
    Some(out)
}

/// The bytes of the first PEM block with this label ("CERTIFICATE", "PRIVATE KEY") in a text.
fn pem_block(pem: &str, label: &str) -> Option<Vec<u8>> {
    let (begin, end) = (format!("-----BEGIN {}-----", label), format!("-----END {}-----", label));
    let lines: Vec<&str> = pem.lines().map(|l| l.trim_end_matches('\r')).collect();
    let a = lines.iter().position(|l| *l == begin)?;
    let b = a + lines[a..].iter().position(|l| *l == end)?;
    base64_decode(&lines[a + 1..b].concat())
}

/// The certificate of a PEM text (the first one in it), as DER.
pub fn certificate_der(pem: &str) -> Option<Vec<u8>> {
    pem_block(pem, "CERTIFICATE")
}

/// The 32-byte seed of the Ed25519 private key in an unencrypted PKCS#8 PEM text ("-----BEGIN PRIVATE KEY-----"),
/// as OpenSSL reads it; None when the text holds no such key, the key is of another kind, or bytes follow it. The
/// seed is what SigningKey::from_seed and a node's identity take.
pub fn ed25519_seed_from_pkcs8_pem(pem: &str) -> Option<Vec<u8>> {
    let der = pem_block(pem, "PRIVATE KEY")?;
    let mut p = der.as_ptr();
    // SAFETY: `p` points at `der.len()` readable bytes; d2i_AutoPrivateKey moves `p` past what it read and returns a
    // new key, owned here and freed below, or null.
    let pkey = unsafe { ffi::d2i_AutoPrivateKey(ptr::null_mut(), &mut p, der.len() as c_long) };
    if pkey.is_null() {
        clear_errors();
        return None;
    }
    let whole = p as usize == der.as_ptr() as usize + der.len();
    let mut seed = vec![0u8; 32];
    let mut n: usize = 32;
    // SAFETY: `pkey` is live until it is freed, once, at the end of the block; `seed` has 32 bytes and `n` says so.
    let ok = unsafe {
        let ok = ffi::EVP_PKEY_get_base_id(pkey) == ffi::EVP_PKEY_ED25519
            && ffi::EVP_PKEY_get_raw_private_key(pkey, seed.as_mut_ptr(), &mut n) == 1;
        ffi::EVP_PKEY_free(pkey);
        ok
    };
    clear_errors();
    if ok && whole && n == 32 { Some(seed) } else { None }
}

pub fn certificate_pem(der: &[u8]) -> String {
    let b64 = base64_encode(der);
    let mut out = String::from("-----BEGIN CERTIFICATE-----\n");
    for chunk in b64.as_bytes().chunks(64) {
        out.push_str(std::str::from_utf8(chunk).unwrap_or(""));
        out.push('\n');
    }
    out + "-----END CERTIFICATE-----\n"
}

/// The dates of a certificate made by `self_signed_certificate`: UTCTime texts, "YYMMDDHHMMSSZ".
pub struct Validity<'a> {
    pub not_before: &'a str,
    pub not_after: &'a str,
}

/// A certificate self-signed over `key`, as DER: version 3, no extensions, the subject and issuer one common name.
/// The token carries a peer's validity period, not the certificate (ruling NQ-10), so the dates are the caller's choice
/// and no node reads them. With the names, serial numbers and dates of tools/bees_tempus_certs.py the bytes are those
/// that tool writes, because an Ed25519 signature is the same on every run.
pub fn self_signed_certificate(key: &SigningKey, common_name: &str, serial: i64, validity: &Validity) -> Result<Vec<u8>, Fault> {
    let failed = || Fault::new("the certificate could not be made");
    let cn = common_name.as_bytes();
    let field = CString::new("CN").map_err(|_| failed())?;
    let before = CString::new(validity.not_before).map_err(|_| failed())?;
    let after = CString::new(validity.not_after).map_err(|_| failed())?;
    // SAFETY: X509_new returns a new certificate or null; it is owned by `cert`.
    let cert = Certificate::from_owned(unsafe { ffi::X509_new() }).ok_or_else(failed)?;
    // SAFETY: X509_NAME_new returns a new name or null; it is freed below on every path.
    let name = unsafe { ffi::X509_NAME_new() };
    if name.is_null() {
        return Err(failed());
    }
    let x = cert.raw();
    // SAFETY: `x`, `name` and the key are live; the C strings end in a zero byte; `cn` is given with its length.
    // X509_set_subject_name and X509_set_issuer_name copy the name, and X509_set_pubkey takes its own reference.
    let ok = unsafe {
        ffi::X509_set_version(x, 2) == 1
            && ffi::ASN1_INTEGER_set(ffi::X509_get_serialNumber(x), serial as c_long) == 1
            && ffi::X509_NAME_add_entry_by_txt(name, field.as_ptr(), ffi::MBSTRING_UTF8, cn.as_ptr(), cn.len() as c_int, -1, 0) == 1
            && ffi::X509_set_subject_name(x, name) == 1
            && ffi::X509_set_issuer_name(x, name) == 1
            && ffi::ASN1_TIME_set_string(ffi::X509_getm_notBefore(x), before.as_ptr()) == 1
            && ffi::ASN1_TIME_set_string(ffi::X509_getm_notAfter(x), after.as_ptr()) == 1
            && ffi::X509_set_pubkey(x, key.raw()) == 1
            && ffi::X509_sign(x, key.raw(), ptr::null()) > 0
    };
    // SAFETY: `name` came from X509_NAME_new and is freed once.
    unsafe { ffi::X509_NAME_free(name) };
    if !ok {
        clear_errors();
        return Err(failed());
    }
    cert.der().ok_or_else(failed)
}

/// The raw 32-byte Ed25519 key of a certificate (DER), after checking what tempus/1 requires of it: an Ed25519 key,
/// issuer equal to subject, and the signature verifying under its own key. The validity dates are not checked
/// (ruling NQ-10: the producer token carries the validity window).
pub fn certificate_key(der: &[u8]) -> Result<Vec<u8>, Refused> {
    let cert = Certificate::from_der(der).ok_or_else(|| Refused::new("the certificate cannot be read"))?;
    let key = cert.ed25519_key().ok_or_else(|| Refused::new("the certificate's key is not Ed25519"))?;
    if !cert.self_signed() {
        return Err(Refused::new("the certificate is not self-signed"));
    }
    Ok(key)
}

pub fn hex(b: &[u8]) -> String {
    const DIGITS: &[u8; 16] = b"0123456789abcdef";
    let mut s = String::with_capacity(b.len() * 2);
    for x in b {
        s.push(DIGITS[(x >> 4) as usize] as char);
        s.push(DIGITS[(x & 15) as usize] as char);
    }
    s
}

pub fn unhex(s: &str) -> Option<Vec<u8>> {
    let u = s.as_bytes();
    if u.len() % 2 != 0 {
        return None;
    }
    let v = |c: u8| -> Option<u8> {
        match c {
            b'0'..=b'9' => Some(c - b'0'),
            b'a'..=b'f' => Some(c - b'a' + 10),
            b'A'..=b'F' => Some(c - b'A' + 10),
            _ => None,
        }
    };
    let mut out = Vec::with_capacity(u.len() / 2);
    for pair in u.chunks(2) {
        out.push((v(pair[0])? << 4) | v(pair[1])?);
    }
    Some(out)
}
