//! The transport: TCP with mutual TLS 1.3 on top, through the OpenSSL installed on the machine.
//!
//! TLS, exactly:
//!   - TLS 1.3 only; the key exchange group X25519MLKEM768 only; the cipher suites TLS_AES_256_GCM_SHA384 and
//!     TLS_CHACHA20_POLY1305_SHA256; ALPN tempus/1; the signature algorithm Ed25519 only for a client (a node also
//!     lets a P-256 certificate through the handshake, to refuse it afterwards as a Silica node does).
//!   - Both sides present a certificate, and each requires the other's. No chain is verified, because a TEMPUS
//!     certificate is self-signed: OpenSSL is told to go on whatever it thinks of the chain. The handshake itself still
//!     proves that the peer holds the private key of the certificate it presented (the TLS 1.3 CertificateVerify,
//!     which OpenSSL always checks). What is required of the certificate is checked after the handshake, by the caller.
//!   - Certificate validity dates are not checked (ruling NQ-10: the producer token carries the validity window).
//!
//! The TCP connection is a `std::net::TcpStream` in blocking mode. One deadline bounds a whole connection: before each
//! TLS operation the stream's read and write timeouts are set to what is left of it, and an operation that ran into
//! the timeout is tried again only while time is left. No call of the operating system is declared here.
//!
//! Every `unsafe` block is a call of a function declared in `ffi`. `TlsContext` owns its SSL_CTX and `Conn` its SSL;
//! each frees it when dropped.
use crate::crypto::{clear_errors, Certificate, SigningKey};
use crate::etf::FRAME_MAX;
use crate::ffi;
use crate::Fault;
use std::ffi::{CStr, CString};
use std::io::Read;
use std::net::{Shutdown, TcpStream};
use std::os::fd::AsRawFd;
use std::os::raw::{c_char, c_int, c_uchar, c_uint, c_void};
use std::ptr;
use std::time::{Duration, Instant};

pub(crate) const ALPN: &str = "tempus/1";
/// How long a closing side keeps reading, so that its last frame is not lost to a TCP reset.
const LINGER: Duration = Duration::from_millis(500);

fn text(p: *const c_char) -> Option<String> {
    if p.is_null() {
        return None;
    }
    // SAFETY: OpenSSL returns a zero-terminated string that lives at least as long as the object it describes.
    Some(unsafe { CStr::from_ptr(p) }.to_string_lossy().into_owned())
}

/// OpenSSL's text for the last error of this thread, and the queue cleared.
pub(crate) fn tls_reason() -> String {
    // SAFETY: reads this thread's error queue; the string returned is static.
    let why = unsafe {
        let e = ffi::ERR_peek_last_error();
        if e == 0 { None } else { text(ffi::ERR_reason_error_string(e)) }
    };
    clear_errors();
    why.unwrap_or_else(|| "closed during the handshake".to_string())
}

extern "C" fn accept_any_chain(_ok: c_int, _store: *mut ffi::X509_STORE_CTX) -> c_int {
    1
}

/// Selects tempus/1 when the dialer offers it. Otherwise: with `strict` not null the handshake ends with a fatal
/// alert, as a Silica node's does; with null no protocol is selected and the check after the handshake refuses.
extern "C" fn select_alpn(_ssl: *mut ffi::SSL, out: *mut *const c_uchar, outlen: *mut c_uchar, offered: *const c_uchar,
                          offered_len: c_uint, strict: *mut c_void) -> c_int {
    let refuse = if strict.is_null() { ffi::SSL_TLSEXT_ERR_NOACK } else { ffi::SSL_TLSEXT_ERR_ALERT_FATAL };
    if out.is_null() || outlen.is_null() || offered.is_null() {
        return refuse;
    }
    // SAFETY: OpenSSL gives `offered_len` readable bytes at `offered`, live for the handshake.
    let list = unsafe { std::slice::from_raw_parts(offered, offered_len as usize) };
    let want = ALPN.as_bytes();
    let mut i = 0;
    while i < list.len() {
        let len = list[i] as usize;
        if i + 1 + len <= list.len() && &list[i + 1..i + 1 + len] == want {
            // SAFETY: `out` and `outlen` are OpenSSL's own output slots; the pointer stored stays inside `offered`.
            unsafe {
                *out = list[i + 1..].as_ptr();
                *outlen = len as c_uchar;
            }
            return ffi::SSL_TLSEXT_ERR_OK;
        }
        i += 1 + len;
    }
    refuse
}

/// An SSL_CTX with the tempus/1 profile and one identity's certificate and key.
pub(crate) struct TlsContext {
    ctx: *mut ffi::SSL_CTX,
}

// SAFETY: an SSL_CTX is made once and then only read; OpenSSL allows SSL objects to be made from it on any thread.
unsafe impl Send for TlsContext {}
unsafe impl Sync for TlsContext {}

impl TlsContext {
    /// `peer_signatures` names the signature algorithms accepted from the peer. `require_certificate` false lets a
    /// peer with no certificate through the handshake. `strict_alpn` true makes a listener end the handshake with a
    /// fatal alert when the dialer offers protocols and tempus/1 is not among them.
    pub(crate) fn new(server: bool, key: &SigningKey, cert_der: &[u8], peer_signatures: &str, require_certificate: bool,
                      strict_alpn: bool) -> Result<TlsContext, Fault> {
        let cert = Certificate::from_der(cert_der).ok_or_else(|| Fault::new("the certificate cannot be read"))?;
        let suites = CString::new("TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256").map_err(|_| Fault::new("suites"))?;
        let group = CString::new("X25519MLKEM768").map_err(|_| Fault::new("group"))?;
        let sigs = CString::new(peer_signatures).map_err(|_| Fault::new("signature algorithms"))?;
        // SAFETY: SSL_CTX_new returns a new context or null.
        let ctx = unsafe { ffi::SSL_CTX_new(if server { ffi::TLS_server_method() } else { ffi::TLS_client_method() }) };
        if ctx.is_null() {
            return Err(Fault::new("no TLS context"));
        }
        let made = TlsContext { ctx };
        // SSL_CTX_set_min_proto_version and its neighbours are C macros over SSL_CTX_ctrl; this calls what they expand to.
        // SAFETY: `ctx`, the certificate and the key are live; the strings end in a zero byte and are copied by
        // OpenSSL; SSL_CTX_use_certificate and SSL_CTX_use_PrivateKey take their own references.
        let ok = unsafe {
            ffi::SSL_CTX_ctrl(ctx, ffi::SSL_CTRL_SET_MIN_PROTO_VERSION, ffi::TLS1_3_VERSION, ptr::null_mut()) == 1
                && ffi::SSL_CTX_ctrl(ctx, ffi::SSL_CTRL_SET_MAX_PROTO_VERSION, ffi::TLS1_3_VERSION, ptr::null_mut()) == 1
                && ffi::SSL_CTX_set_ciphersuites(ctx, suites.as_ptr()) == 1
                && ffi::SSL_CTX_ctrl(ctx, ffi::SSL_CTRL_SET_GROUPS_LIST, 0, group.as_ptr() as *mut c_void) == 1
                && ffi::SSL_CTX_ctrl(ctx, ffi::SSL_CTRL_SET_SIGALGS_LIST, 0, sigs.as_ptr() as *mut c_void) == 1
                && ffi::SSL_CTX_ctrl(ctx, ffi::SSL_CTRL_SET_CLIENT_SIGALGS_LIST, 0, sigs.as_ptr() as *mut c_void) == 1
                && ffi::SSL_CTX_use_certificate(ctx, cert.raw()) == 1
                && ffi::SSL_CTX_use_PrivateKey(ctx, key.raw()) == 1
                && ffi::SSL_CTX_check_private_key(ctx) == 1
        };
        if !ok {
            return Err(Fault(format!("the TLS context could not be set up: {}", tls_reason())));
        }
        let mode = if require_certificate { ffi::SSL_VERIFY_PEER | ffi::SSL_VERIFY_FAIL_IF_NO_PEER_CERT } else { ffi::SSL_VERIFY_PEER };
        // The peer's certificate is required and its chain is not judged here (see the text at the top of this file).
        // SAFETY: `ctx` is live; the callbacks are functions of this file with the signatures OpenSSL calls.
        unsafe {
            ffi::SSL_CTX_set_verify(ctx, mode, Some(accept_any_chain));
            if server {
                let strict = if strict_alpn { ptr::NonNull::<c_void>::dangling().as_ptr() } else { ptr::null_mut() };
                ffi::SSL_CTX_set_alpn_select_cb(ctx, Some(select_alpn), strict);
            }
        }
        if !server {
            let mut protos = vec![ALPN.len() as u8];
            protos.extend_from_slice(ALPN.as_bytes());
            // SAFETY: `protos` is live for the call and OpenSSL copies it. This function answers 0 for success.
            if unsafe { ffi::SSL_CTX_set_alpn_protos(ctx, protos.as_ptr(), protos.len() as c_uint) } != 0 {
                return Err(Fault::new("the ALPN protocol could not be set"));
            }
        }
        Ok(made)
    }
}

impl Drop for TlsContext {
    fn drop(&mut self) {
        // SAFETY: the pointer came from SSL_CTX_new and is freed once.
        unsafe { ffi::SSL_CTX_free(self.ctx) }
    }
}

pub(crate) enum ReadResult {
    Frame(Vec<u8>),
    Oversize,
    Closed(String),
    Timeout,
    TlsFailed(String),
}

/// A TLS connection with one deadline for all of it; reads and writes answer with values, not errors.
pub(crate) struct Conn {
    ssl: *mut ffi::SSL,
    stream: Option<TcpStream>,
    deadline: Instant,
    frames_read: usize,
}

impl Conn {
    /// A connection over `stream`, which is put in blocking mode. `server` says which side of the handshake this is.
    pub(crate) fn new(context: &TlsContext, stream: TcpStream, server: bool, deadline: Instant) -> Result<Conn, Fault> {
        stream.set_nonblocking(false).map_err(|_| Fault::new("the connection could not be set up"))?;
        let _ = stream.set_nodelay(true);
        // SAFETY: the context is live; SSL_new returns a new object or null.
        let ssl = unsafe { ffi::SSL_new(context.ctx) };
        if ssl.is_null() {
            return Err(Fault::new("no TLS object"));
        }
        // SAFETY: `ssl` is live. SSL_set_fd does not take the descriptor over (it is not closed by SSL_free): the
        // TcpStream owns it and outlives the SSL object, which `close` frees first.
        unsafe {
            ffi::SSL_set_fd(ssl, stream.as_raw_fd());
            if server { ffi::SSL_set_accept_state(ssl) } else { ffi::SSL_set_connect_state(ssl) }
        }
        Ok(Conn { ssl, stream: Some(stream), deadline, frames_read: 0 })
    }

    fn arm(&self, until: Instant) -> bool {
        let left = until.saturating_duration_since(Instant::now());
        if left.is_zero() {
            return false;
        }
        let left = left.max(Duration::from_millis(1));
        if let Some(s) = &self.stream {
            let _ = s.set_read_timeout(Some(left));
            let _ = s.set_write_timeout(Some(left));
        }
        true
    }

    /// Runs one TLS operation to its end: its result when positive, else why it stopped.
    fn run(&mut self, op: &mut dyn FnMut(*mut ffi::SSL) -> c_int) -> Result<c_int, ReadResult> {
        loop {
            if !self.arm(self.deadline) {
                return Err(ReadResult::Timeout);
            }
            clear_errors();
            let r = op(self.ssl);
            if r > 0 {
                return Ok(r);
            }
            // SAFETY: `ssl` is live and `r` is the value the operation just returned on this thread.
            match unsafe { ffi::SSL_get_error(self.ssl, r) } {
                ffi::SSL_ERROR_WANT_READ | ffi::SSL_ERROR_WANT_WRITE => continue,
                ffi::SSL_ERROR_ZERO_RETURN | ffi::SSL_ERROR_SYSCALL => {
                    clear_errors();
                    return Err(ReadResult::Closed(String::new()));
                }
                _ => {
                    let why = tls_reason();
                    // an end of the stream without close_notify is a close, as a TCP reset is
                    if why == "unexpected eof while reading" {
                        return Err(ReadResult::Closed(String::new()));
                    }
                    return Err(if self.frames_read == 0 { ReadResult::TlsFailed(why) } else { ReadResult::Closed(why) });
                }
            }
        }
    }

    /// The handshake. None when it succeeded.
    pub(crate) fn handshake(&mut self) -> Option<ReadResult> {
        // SAFETY: the pointer the closure is given is this connection's live SSL object.
        self.run(&mut |ssl| unsafe { ffi::SSL_do_handshake(ssl) }).err()
    }

    /// True when the bytes were handed to the transport. A failure is not reported here: the next read says what happened.
    pub(crate) fn send(&mut self, data: &[u8]) -> bool {
        let mut sent = 0;
        while sent < data.len() {
            let rest = &data[sent..];
            // SAFETY: `rest` is live for the call and its length is given.
            match self.run(&mut |ssl| unsafe { ffi::SSL_write(ssl, rest.as_ptr() as *const c_void, rest.len() as c_int) }) {
                Ok(n) => sent += n as usize,
                Err(_) => return false,
            }
        }
        true
    }

    fn exact(&mut self, n: usize) -> Result<Vec<u8>, ReadResult> {
        let mut data = vec![0u8; n];
        let mut got = 0;
        while got < n {
            let rest = &mut data[got..];
            // SAFETY: `rest` is live for the call and its length is given.
            let r = self.run(&mut |ssl| unsafe { ffi::SSL_read(ssl, rest.as_mut_ptr() as *mut c_void, rest.len() as c_int) })?;
            got += r as usize;
        }
        Ok(data)
    }

    /// The next frame's body. A frame above the ceiling is refused from its length, before its body is read.
    pub(crate) fn read(&mut self) -> ReadResult {
        let head = match self.exact(4) {
            Ok(h) => h,
            Err(stop) => return stop,
        };
        let size = u32::from_be_bytes([head[0], head[1], head[2], head[3]]) as usize;
        if size > FRAME_MAX {
            return ReadResult::Oversize;
        }
        match self.exact(size) {
            Ok(body) => {
                self.frames_read += 1;
                ReadResult::Frame(body)
            }
            Err(stop) => stop,
        }
    }

    pub(crate) fn selected_alpn(&self) -> Option<String> {
        let mut p: *const c_uchar = ptr::null();
        let mut n: c_uint = 0;
        // SAFETY: `ssl` is live; OpenSSL stores a pointer into its own memory and a length.
        unsafe { ffi::SSL_get0_alpn_selected(self.ssl, &mut p, &mut n) };
        if p.is_null() || n == 0 {
            return None;
        }
        // SAFETY: OpenSSL said `n` bytes are readable at `p`, and they live as long as `ssl`.
        Some(String::from_utf8_lossy(unsafe { std::slice::from_raw_parts(p, n as usize) }).into_owned())
    }

    pub(crate) fn version(&self) -> String {
        // SAFETY: `ssl` is live; the string is static.
        text(unsafe { ffi::SSL_get_version(self.ssl) }).unwrap_or_default()
    }

    /// The name of the key exchange group the handshake chose.
    pub(crate) fn group(&self) -> String {
        // SAFETY: `ssl` is live; the string belongs to OpenSSL.
        text(unsafe { ffi::SSL_get0_group_name(self.ssl) }).unwrap_or_default()
    }

    pub(crate) fn cipher(&self) -> Option<String> {
        // SAFETY: `ssl` is live; the cipher and its name belong to OpenSSL.
        unsafe {
            let c = ffi::SSL_get_current_cipher(self.ssl);
            if c.is_null() { None } else { text(ffi::SSL_CIPHER_get_name(c)) }
        }
    }

    /// The certificate the peer presented.
    pub(crate) fn peer_certificate(&self) -> Option<Certificate> {
        // SAFETY: `ssl` is live; SSL_get1_peer_certificate gives one owned reference, or null.
        Certificate::from_owned(unsafe { ffi::SSL_get1_peer_certificate(self.ssl) })
    }

    /// Close so that what was last written arrives: TLS close_notify, TCP end of writing, then read to the peer's end
    /// (at most LINGER). Closing with unread bytes would send a TCP reset, which can destroy a frame (a key_rotated,
    /// a request) the peer has not yet read.
    pub(crate) fn close(&mut self) {
        let stream = match self.stream.take() {
            Some(s) => s,
            None => return,
        };
        let until = Instant::now() + LINGER;
        let _ = stream.set_write_timeout(Some(LINGER));
        clear_errors();
        // SAFETY: `ssl` is live; SSL_shutdown writes close_notify and does not wait for the peer's.
        unsafe { ffi::SSL_shutdown(self.ssl) };
        clear_errors();
        let _ = stream.shutdown(Shutdown::Write);
        let mut buf = [0u8; 4096];
        loop {
            let left = until.saturating_duration_since(Instant::now());
            if left.is_zero() {
                break;
            }
            let _ = stream.set_read_timeout(Some(left.max(Duration::from_millis(1))));
            match (&stream).read(&mut buf) {
                Ok(0) => break,
                Ok(_) => continue,
                Err(e) if e.kind() == std::io::ErrorKind::Interrupted => continue,
                Err(_) => break,
            }
        }
        // SAFETY: the pointer came from SSL_new and is freed once: `stream` is None from here on, and Drop frees
        // only when it finds the stream still there.
        unsafe { ffi::SSL_free(self.ssl) };
        self.ssl = ptr::null_mut();
        drop(stream);
    }
}

impl Drop for Conn {
    fn drop(&mut self) {
        self.close();
    }
}
