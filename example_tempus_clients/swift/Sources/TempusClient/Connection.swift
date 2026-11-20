// The transport: TCP with mutual TLS 1.3 on top, through the OpenSSL installed on the machine, and the order of a
// connection (design sections 4 and 5): the two adverts, the two challenges, the two responses, one request, one reply.
//
// TLS, exactly:
//   - TLS 1.3 only; the key exchange group X25519MLKEM768 only; the cipher suites TLS_AES_256_GCM_SHA384 and
//     TLS_CHACHA20_POLY1305_SHA256; the signature algorithm Ed25519 only; ALPN tempus/1.
//   - Both sides present a certificate, and each requires the other's. No chain is verified, because a TEMPUS
//     certificate is self-signed: OpenSSL is told to go on whatever it thinks of the chain. The handshake itself still
//     proves that the peer holds the private key of the certificate it presented (the TLS 1.3 CertificateVerify,
//     which OpenSSL always checks). After the handshake this unit reads the certificate and requires an Ed25519 key,
//     issuer equal to subject, and the certificate's signature verifying under its own key. The binding (that key is
//     the advert's pub) is the verifier's check.
//   - Certificate validity dates are not checked (ruling NQ-10: the producer token carries the validity window).
// An example only: not for production.
import COpenSSL
import Darwin

public let alpn = "tempus/1"
/// Seconds a closing side keeps reading, so that its last frame is not lost to a TCP reset.
let linger = 0.5

func monotonic() -> Double { Double(clock_gettime_nsec_np(CLOCK_UPTIME_RAW)) / 1e9 }

func tlsReason() -> String {
    let e = ERR_peek_last_error()
    ERR_clear_error()
    guard e != 0, let s = ERR_reason_error_string(e) else { return "closed during the handshake" }
    return String(cString: s)
}

/// An SSL_CTX with the tempus/1 profile and this identity's certificate and key.
final class TLSContext {
    let ctx: OpaquePointer

    init(server: Bool, identity: Identity) throws {
        guard let c = SSL_CTX_new(server ? TLS_server_method() : TLS_client_method()) else {
            throw CryptoFailure("no TLS context")
        }
        ctx = c
        guard let cert = x509(der: identity.certDER) else { throw CryptoFailure("the certificate cannot be read") }
        defer { X509_free(cert) }
        let protos = [UInt8(alpn.utf8.count)] + Array(alpn.utf8)
        // SSL_CTX_set_min_proto_version and its neighbours are C macros over SSL_CTX_ctrl; Swift calls what they expand to.
        guard SSL_CTX_ctrl(c, SSL_CTRL_SET_MIN_PROTO_VERSION, Int(TLS1_3_VERSION), nil) == 1,
              SSL_CTX_ctrl(c, SSL_CTRL_SET_MAX_PROTO_VERSION, Int(TLS1_3_VERSION), nil) == 1,
              SSL_CTX_set_ciphersuites(c, "TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256") == 1,
              ctrlString(c, SSL_CTRL_SET_GROUPS_LIST, "X25519MLKEM768"),
              ctrlString(c, SSL_CTRL_SET_SIGALGS_LIST, "ed25519"),
              ctrlString(c, SSL_CTRL_SET_CLIENT_SIGALGS_LIST, "ed25519"),
              SSL_CTX_use_certificate(c, cert) == 1,
              SSL_CTX_use_PrivateKey(c, identity.key.pkey) == 1,
              SSL_CTX_check_private_key(c) == 1 else {
            let why = tlsReason()
            SSL_CTX_free(c)
            throw CryptoFailure("the TLS context could not be set up: \(why)")
        }
        // The peer's certificate is required and its chain is not judged here (see the text at the top of this file).
        SSL_CTX_set_verify(c, SSL_VERIFY_PEER | SSL_VERIFY_FAIL_IF_NO_PEER_CERT, { _, _ in 1 })
        if server {
            // tempus/1 when the dialer offers it; otherwise no protocol is selected and the check after the handshake refuses
            SSL_CTX_set_alpn_select_cb(c, { _, out, outlen, offered, offeredLen, _ in
                guard let out, let outlen, let offered else { return SSL_TLSEXT_ERR_NOACK }
                let want = Array("tempus/1".utf8)
                var i = 0
                let n = Int(offeredLen)
                while i < n {
                    let len = Int(offered[i])
                    if i + 1 + len <= n, len == want.count, (0..<len).allSatisfy({ offered[i + 1 + $0] == want[$0] }) {
                        out.pointee = offered + i + 1
                        outlen.pointee = UInt8(len)
                        return SSL_TLSEXT_ERR_OK
                    }
                    i += 1 + len
                }
                return SSL_TLSEXT_ERR_NOACK
            }, nil)
        } else {
            guard SSL_CTX_set_alpn_protos(c, protos, UInt32(protos.count)) == 0 else {
                SSL_CTX_free(c)
                throw CryptoFailure("the ALPN protocol could not be set")
            }
        }
    }

    deinit { SSL_CTX_free(ctx) }
}

private func ctrlString(_ c: OpaquePointer, _ cmd: Int32, _ text: String) -> Bool {
    var chars = Array(text.utf8CString)
    return chars.withUnsafeMutableBytes { SSL_CTX_ctrl(c, cmd, 0, $0.baseAddress) } == 1
}

enum ReadResult {
    case frame(Bytes)
    case oversize
    case closed(String)
    case timeout
    case tlsFailed(String)
}

/// A TLS connection with one deadline for all of it; reads and writes answer with values, not errors.
final class Conn {
    private let ssl: OpaquePointer
    private let fd: Int32
    private let deadline: Double
    private var framesRead = 0
    private var open = true

    init(ssl: OpaquePointer, fd: Int32, deadline: Double) {
        self.ssl = ssl
        self.fd = fd
        self.deadline = deadline
    }

    deinit { close() }

    private enum Wait { case ready, timeout }

    private func wait(events: Int16, until: Double) -> Wait {
        while true {
            let left = until - monotonic()
            if left <= 0 { return .timeout }
            var p = pollfd(fd: fd, events: events, revents: 0)
            let r = poll(&p, 1, Int32(max(1, min(left * 1000, 1_000_000))))
            if r > 0 { return .ready }
            if r < 0 && errno != EINTR { return .ready }      // the next TLS call says what happened
        }
    }

    /// Runs one TLS operation to its end: its result when positive, else why it stopped.
    private func run(_ op: () -> Int32) -> (Int32, ReadResult?) {
        while true {
            ERR_clear_error()
            let r = op()
            if r > 0 { return (r, nil) }
            switch SSL_get_error(ssl, r) {
            case SSL_ERROR_WANT_READ:
                if wait(events: Int16(POLLIN), until: deadline) == .timeout { return (r, .timeout) }
            case SSL_ERROR_WANT_WRITE:
                if wait(events: Int16(POLLOUT), until: deadline) == .timeout { return (r, .timeout) }
            case SSL_ERROR_ZERO_RETURN, SSL_ERROR_SYSCALL:
                ERR_clear_error()
                return (r, .closed(""))
            default:
                let why = tlsReason()
                // an end of the stream without close_notify is a close, as a TCP reset is
                if why == "unexpected eof while reading" { return (r, .closed("")) }
                return (r, framesRead == 0 ? .tlsFailed(why) : .closed(why))
            }
        }
    }

    /// The handshake. nil when it succeeded.
    func handshake() -> ReadResult? {
        run { SSL_do_handshake(self.ssl) }.1
    }

    /// True when the bytes were handed to the transport. A failure is not reported here: the next read says what happened.
    @discardableResult
    func send(_ data: Bytes) -> Bool {
        var sent = 0
        while sent < data.count {
            let (n, stop) = data.withUnsafeBufferPointer { buf in
                run { SSL_write(self.ssl, buf.baseAddress! + sent, Int32(buf.count - sent)) }
            }
            if stop != nil { return false }
            sent += Int(n)
        }
        return true
    }

    private func exact(_ n: Int) -> (Bytes, ReadResult?) {
        var data = Bytes(repeating: 0, count: n)
        var got = 0
        while got < n {
            let (r, stop) = data.withUnsafeMutableBufferPointer { buf in
                run { SSL_read(self.ssl, buf.baseAddress! + got, Int32(n - got)) }
            }
            if let stop { return ([], stop) }
            got += Int(r)
        }
        return (data, nil)
    }

    /// The next frame's body. A frame above the ceiling is refused from its length, before its body is read.
    func read() -> ReadResult {
        let (head, stop) = exact(4)
        if let stop { return stop }
        let size = head.reduce(0) { ($0 << 8) | Int($1) }
        if size > frameMax { return .oversize }
        let (body, stop2) = exact(size)
        if let stop2 { return stop2 }
        framesRead += 1
        return .frame(body)
    }

    var selectedALPN: String? {
        var p: UnsafePointer<UInt8>?
        var n: UInt32 = 0
        SSL_get0_alpn_selected(ssl, &p, &n)
        guard let p, n > 0 else { return nil }
        return String(decoding: UnsafeBufferPointer(start: p, count: Int(n)), as: UTF8.self)
    }

    var version: String { String(cString: SSL_get_version(ssl)) }

    /// The certificate the peer presented, as DER.
    var peerCertificate: Bytes? {
        guard let x = SSL_get1_peer_certificate(ssl) else { return nil }
        defer { X509_free(x) }
        return derOf(x)
    }

    /// Close so that what was last written arrives: TLS close_notify, TCP end of writing, then read to the peer's end
    /// (at most `linger` seconds). Closing with unread bytes would send a TCP reset, which can destroy a frame (a
    /// key_rotated, a request) the peer has not yet read.
    func close() {
        guard open else { return }
        open = false
        ERR_clear_error()
        _ = SSL_shutdown(ssl)                      // writes close_notify; does not wait for the peer's
        ERR_clear_error()
        shutdown(fd, SHUT_WR)
        let until = monotonic() + linger
        var buf = Bytes(repeating: 0, count: 65536)
        while wait(events: Int16(POLLIN), until: until) == .ready {
            let n = recv(fd, &buf, buf.count, 0)
            if n == 0 || (n < 0 && errno != EINTR && errno != EAGAIN) { break }
        }
        SSL_free(ssl)
        Darwin.close(fd)
    }
}

func setNonBlocking(_ fd: Int32) {
    _ = fcntl(fd, F_SETFL, fcntl(fd, F_GETFL) | O_NONBLOCK)
    var one: Int32 = 1
    setsockopt(fd, SOL_SOCKET, SO_NOSIGPIPE, &one, socklen_t(MemoryLayout<Int32>.size))
}

func splitAddress(_ text: String) -> (host: String, port: String)? {
    guard let i = text.lastIndex(of: ":") else { return nil }
    let host = String(text[..<i]), port = String(text[text.index(after: i)...])
    guard !host.isEmpty, let n = Int(port), n >= 0, n <= 65535 else { return nil }
    return (host, port)
}

// ---------------------------------------------------------------- the order of a connection
final class State {
    var advert: Descriptor?
    var typ = ""
}

func end(_ conn: Conn, _ what: String, _ stage: String, _ state: State, _ reason: String = "") -> Outcome {
    conn.close()
    var out = Outcome(what, stage, reason: reason)
    out.advert = state.advert
    out.typ = state.typ
    return out
}

func end(_ conn: Conn, _ result: ReadResult, _ stage: String, _ state: State) -> Outcome {
    switch result {
    case .oversize: return end(conn, "refused", stage, state, "a frame above the ceiling")
    case .closed(let why): return end(conn, "closed", stage, state, why)
    case .timeout: return end(conn, "timeout", stage, state)
    case .tlsFailed(let why): return end(conn, "tls_failed", stage, state, why)
    case .frame: return end(conn, "closed", stage, state)
    }
}

/// The next frame, which must be one of the kinds `want`; otherwise the Outcome that ended the connection (this side
/// then closes without a reply, design section 5).
func readFrame(_ conn: Conn, _ stage: String, _ state: State, want: [String], _ shuffleLength: Int) -> (Frame?, Outcome?) {
    let result = conn.read()
    guard case .frame(let body) = result else { return (nil, end(conn, result, stage, state)) }
    do {
        let f = try readBody(body, shuffleLength: shuffleLength)
        guard want.contains(f.kind) else {
            return (nil, end(conn, "refused", stage, state, "\(f.kind) where \(want.joined(separator: " or ")) was due"))
        }
        return (f, nil)
    } catch {
        return (nil, end(conn, "refused", stage, state, "\(error)"))
    }
}

/// After the handshake: the version, the ALPN protocol and the peer's certificate (DER), with what tempus/1 requires
/// of it.
func tlsChecks(_ conn: Conn) throws -> Bytes {
    guard conn.version == "TLSv1.3" else { throw Refused("the TLS version is not 1.3") }
    guard conn.selectedALPN == alpn else { throw Refused("the ALPN protocol is not tempus/1") }
    guard let der = conn.peerCertificate else { throw Refused("the peer presented no certificate") }
    _ = try certificateKey(der: der)
    return der
}

/// Admission, the same at both ends (design sections 4 and 5). nil when both directions passed, else the Outcome.
func admit(_ conn: Conn, me: Identity, addr: String?, verifier: Verifier, nonce: Bytes?, certDER: Bytes, state: State,
           shuffleLength: Int) -> Outcome? {
    do {
        let nonce = try nonce ?? randomBytes(32)
        conn.send(try frame(try me.advert(addr: addr)))
        var (f, out) = readFrame(conn, "advert", state, want: ["advert"], shuffleLength)
        guard case .advert(let theirs)? = f else { return out }
        state.advert = theirs
        do {
            state.typ = try verifier.checkDescriptor(theirs, certDER: certDER).typ
        } catch let why as Refused {
            if why.reason == "key_rotated" {       // the one exception to silence (ruling OQ-10): one frame, then close
                conn.send(try frame(try keyRotated(kid: verifier.kid)))
            }
            return end(conn, "refused", "advert", state, why.reason)
        }
        conn.send(try frame(try challenge(nonce: nonce)))
        (f, out) = readFrame(conn, "challenge", state, want: ["pop_challenge", "key_rotated"], shuffleLength)
        guard let due = f else { return out }
        if case .keyRotated(let kid) = due {
            var o = end(conn, "key_rotated", "challenge", state)
            o.kid = kid
            return o
        }
        guard case .popChallenge(let theirNonce) = due else { return end(conn, "refused", "challenge", state) }
        conn.send(try frame(try response(sig: try me.prove(nonce: theirNonce))))
        (f, out) = readFrame(conn, "response", state, want: ["pop_response"], shuffleLength)
        guard case .popResponse(let sig)? = f else { return out }
        do {
            try verifier.checkProof(pub: theirs.pub, nonce: nonce, token: theirs.token, sig: sig)
        } catch let why as Refused {
            return end(conn, "refused", "response", state, why.reason)
        }
        return nil
    } catch {
        return end(conn, "closed", "advert", state, "internal error: \(error)")
    }
}

/// Every entry of a shuffle or sample frame must verify before any of them is used; one that does not refuses the frame.
func checkEntries(_ f: Frame, _ verifier: Verifier) throws {
    guard let store = f.store, let entries = f.entries else { return }
    for e in entries {
        do {
            try verifier.checkEntry(e, store: store)
        } catch let why as Refused {
            throw Refused("an entry does not verify: \(why.reason)")
        }
    }
}

/// Connect to the TEMPUS peer at "host:port", be admitted, send ONE request body and read one reply.
///
/// `request` is a body from shuffle(), sample() or callFrame(). `timeout` is one bound, in seconds, for the whole
/// connection. `identity.addr` is the listen address this peer advertises. `nonce` is the 32-byte challenge; nil
/// takes it from the system's secure random source, which is what a client does (a fixed nonce is for a test).
/// `shuffleLength` is the value of the network. `verifyEntries` false leaves the entries of a reply unjudged, as the
/// Python example does; the caller must then check each with Verifier.checkEntry before using it.
/// When `request` is a cast, no reply comes: the outcome is "closed" at stage "reply".
public func dial(_ addr: String, identity: Identity, verifier: Verifier, request: Bytes, timeout: Double,
                 nonce: Bytes? = nil, shuffleLength: Int = entriesMax, verifyEntries: Bool = true) -> Outcome {
    let deadline = monotonic() + timeout
    let state = State()
    guard let (host, port) = splitAddress(addr), let advertised = identity.addr, splitAddress(advertised) != nil,
          request.count <= frameMax, let context = try? TLSContext(server: false, identity: identity) else {
        return Outcome("unreachable", "tls", reason: "the address, the identity or the request cannot be used")
    }
    var hints = addrinfo()
    hints.ai_socktype = SOCK_STREAM
    var list: UnsafeMutablePointer<addrinfo>?
    guard getaddrinfo(host, port, &hints, &list) == 0, let first = list else { return Outcome("unreachable", "tls") }
    defer { freeaddrinfo(list) }
    let fd = socket(first.pointee.ai_family, SOCK_STREAM, 0)
    guard fd >= 0 else { return Outcome("unreachable", "tls") }
    setNonBlocking(fd)
    if connect(fd, first.pointee.ai_addr, first.pointee.ai_addrlen) != 0 {
        guard errno == EINPROGRESS else {
            close(fd)
            return Outcome("unreachable", "tls")
        }
        var p = pollfd(fd: fd, events: Int16(POLLOUT), revents: 0)
        var ready: Int32 = 0
        repeat {
            let left = deadline - monotonic()
            ready = left <= 0 ? 0 : poll(&p, 1, Int32(max(1, left * 1000)))
        } while ready < 0 && errno == EINTR
        var err: Int32 = 0
        var len = socklen_t(MemoryLayout<Int32>.size)
        getsockopt(fd, SOL_SOCKET, SO_ERROR, &err, &len)
        if ready <= 0 || err != 0 {
            close(fd)
            return Outcome(ready == 0 ? "timeout" : "unreachable", "tls")
        }
    }
    guard let ssl = SSL_new(context.ctx) else {
        close(fd)
        return Outcome("tls_failed", "tls", reason: "no TLS object")
    }
    SSL_set_fd(ssl, fd)
    SSL_set_connect_state(ssl)
    let conn = Conn(ssl: ssl, fd: fd, deadline: deadline)
    if let failed = conn.handshake() {
        conn.close()
        switch failed {
        case .timeout: return Outcome("timeout", "tls")
        case .tlsFailed(let why): return Outcome("tls_failed", "tls", reason: why)
        default: return Outcome("tls_failed", "tls", reason: "closed during the handshake")
        }
    }
    let certDER: Bytes
    do {
        certDER = try tlsChecks(conn)
    } catch {
        return end(conn, "refused", "tls", state, "\(error)")
    }
    // In TLS 1.3 a dialer's handshake ends before the listener has judged the dialer's certificate: a listener's TLS
    // refusal shows as an alert on the first read, reported as tls_failed at "advert".
    if let out = admit(conn, me: identity, addr: nil, verifier: verifier, nonce: nonce, certDER: certDER, state: state,
                       shuffleLength: shuffleLength) {
        return out
    }
    guard let framed = try? frame(request) else { return end(conn, "closed", "request", state, "internal error") }
    conn.send(framed)
    let result = conn.read()
    guard case .frame(let body) = result else { return end(conn, result, "reply", state) }
    var out: Outcome
    do {
        let f = try readAny(body, shuffleLength: shuffleLength)
        if verifyEntries { try checkEntries(f, verifier) }
        out = end(conn, "reply", "done", state)
        out.frame = f
    } catch {
        out = end(conn, "refused", "reply", state, "\(error)")
    }
    out.body = body
    return out
}
