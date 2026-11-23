// One tempus/1 connection of a node (design sections 4, 5, 8 and 10), dialed or accepted: the same until the request.
// The order, the checks, the audit events and their texts are those of src/tempus/dangerous_bees_tempus_conn.silica and
// of the TLS link under it (src/tempus/dangerous_bees_tempus_tls.silica). Any violation closes with no reply (the one
// exception is key_rotated) and writes one audit line. It runs on a thread of its own, with the values of ConnValues,
// and blocks only on its own connection, which has ONE time bound from the dial or the accept to the close (ruling
// NQ-14).
import COpenSSL
import Darwin
import TempusClient

/// What a connection works with: copied from the node when the connection was dialed or accepted.
struct ConnValues: Sendable {
    let cid: Int
    let dialed: Bool
    let advert: Bytes
    let token: Bytes
    let kid: Bytes
    let producerKey: Bytes
    let now: Int64
    let skew: Int64
    /// The most entries a frame may hold: the store's shuffle length when dialed, the greatest of the three when accepted.
    let count: Int
    /// The value of the monotonic clock at which shuffle_timeout_ms has passed.
    let deadline: Double
}

enum DialOutcome: Sendable {
    /// The reply (nil for a reply frame that is not of tempus/1's own kinds), the admitted peer and its token's type.
    case reply(Frame?, peer: Descriptor, typ: String)
    /// The audit event that ended it, or connect_failed.
    case failed(String)
    case keyRotated(kid: Bytes)
}

final class NodeConnection {
    let node: TempusNode
    let v: ConnValues
    private var conn: Conn?
    private var peer: Descriptor?
    private var certKey: Bytes = []
    private var listed: Int?
    private var tokenVerified = false
    private var onClose: (() -> Void)?

    init(node: TempusNode, v: ConnValues) {
        self.node = node
        self.v = v
    }

    private var tag: String { (v.dialed ? "d" : "a") + String(v.cid) }
    private var side: String { v.dialed ? "client" : "server" }

    private func audit(_ event: String, _ what: String) {
        let p = peer.map { hex(Array($0.id.prefix(8))) } ?? "-"
        node.say("[tempus audit] \(event) peer=\(p) \(what) \(tag)")
    }

    private func finish() {
        onClose?()
        onClose = nil
        conn?.close()
        conn = nil
    }

    /// A refusal that is the peer's doing: one audit line, the close, and for an accepted peer whose certificate key
    /// is known the node is told (ruling NQ-19).
    private func refuse(_ event: String, _ what: String) -> DialOutcome {
        audit(event, what)
        finish()
        if !v.dialed && certKey.count == 32 {
            node.report(.peerRefused(event: event, peerId: sha512(certKey), tokenVerified: tokenVerified))
        }
        return .failed(event)
    }

    private enum Next { case body(Bytes), ended(DialOutcome) }

    /// The next frame's body, or how the connection ended while it was waited for.
    private func next(_ stage: String) -> Next {
        switch conn!.read() {
        case .frame(let body): return .body(body)
        case .oversize: return .ended(refuse("protocol_error", "frame refused before decoding: too_large"))
        case .timeout: return .ended(refuse("timeout", "stage " + stage))
        case .closed, .tlsFailed:
            audit("closed_by_peer", "stage " + stage)
            finish()
            return .ended(.failed("closed_by_peer"))
        }
    }

    private func send(_ body: Bytes) { conn?.send(be32(body.count) + body) }

    // ---------------------------------------------------------------- TLS
    /// The handshake and what tempus/1 requires of it. False when the connection was refused (the line is written).
    private func handshake(_ ssl: OpaquePointer, _ fd: Int32) -> Bool {
        let c = Conn(ssl: ssl, fd: fd, deadline: v.deadline)
        conn = c
        func failed(_ event: String, _ what: String) -> Bool {
            audit(event, what + ", as " + side)
            finish()
            return false
        }
        if let stop = c.handshake() {
            switch stop {
            case .timeout: return failed("timeout", "stage tls_handshake")
            case .tlsFailed(let why):
                // the listener's own refusal of the dialer's protocols (TLSContext, strictALPN)
                if why.contains("no application protocol") || why.contains("callback failed") {
                    return failed("alpn_mismatch", "the peer did not agree on ALPN tempus/1")
                }
                if why.contains("peer did not return a certificate") {
                    return failed("tls_verify_failed", "the peer presented no certificate")
                }
                return failed("tls_handshake_failed", "the TLS 1.3 handshake failed (alert, version, group, suite or signature outside the tempus/1 profile)")
            default: return failed("closed_by_peer", "stage tls_handshake")
            }
        }
        guard c.selectedALPN == alpn else { return failed("alpn_mismatch", "the peer did not agree on ALPN tempus/1") }
        guard let x = SSL_get1_peer_certificate(ssl) else { return failed("tls_verify_failed", "the peer presented no certificate") }
        defer { X509_free(x) }
        let group = SSL_get0_group_name(ssl).map { String(cString: $0) } ?? ""
        guard group.uppercased() == "X25519MLKEM768" else {
            return failed("tls_group_refused", "the connection did not negotiate X25519MLKEM768, the only key exchange of the tempus/1 profile")
        }
        var raw = Bytes(repeating: 0, count: 32)
        var n = 32
        guard let k = X509_get0_pubkey(x), EVP_PKEY_get_base_id(k) == EVP_PKEY_ED25519,
              EVP_PKEY_get_raw_public_key(k, &raw, &n) == 1, n == 32, let der = derOf(x) else {
            return failed("tempus_cert_key", "the peer certificate's key is not Ed25519")
        }
        certKey = raw
        listed = node.whitelist.firstIndex(of: sha512(der))
        let suite = SSL_get_current_cipher(ssl).flatMap { SSL_CIPHER_get_name($0) }.map { String(cString: $0) } ?? "other-suite"
        audit("tls_established", "\(c.version) X25519MLKEM768 \(suite) alpn tempus/1, mutual, as \(side)")
        return true
    }

    // ---------------------------------------------------------------- admission, the same at both ends
    /// nil when the peer is admitted; else how the connection ended.
    private func admit() -> DialOutcome? {
        send(v.advert)
        let first: Bytes
        switch next("advert") {
        case .body(let b): first = b
        case .ended(let how): return how
        }
        guard bodyKind(first).kind == "advert" else { return refuse("protocol_error", "the first frame is not an advert") }
        guard case .advert(let d)? = readFrame(first, count: v.count).frame else {
            return refuse("protocol_error", readFrame(first, count: v.count).why)
        }
        peer = d
        // the channel binding: without it a node in the middle with its own certificate could relay an advert and its proof
        guard d.pub == certKey else { return refuse("binding_refused", "the advert's pub is not the key of the peer's TLS certificate") }
        let p = Admission.pre(d, kid: v.kid, now: v.now, skew: v.skew, want: nil)
        if p.why == Admission.rotated {
            // the one exception to silence (ruling OQ-10). What the peer still sends is read and dropped until it closes or
            // the bound passes: closing with its bytes unread would reset the connection and could destroy the frame
            if let body = try? keyRotated(kid: v.kid) { send(body) }
            audit("key_rotated", "the peer's token is under another kid; it was told the current one")
            while case .frame = conn!.read() {}
            finish()
            return .failed("key_rotated_sent")
        }
        if !p.why.isEmpty { return refuse("admission_refused", p.why) }
        let wl = Admission.whitelist(typ: p.fields!.typ, listed: listed != nil)
        if !wl.isEmpty { return refuse("whitelist_reject", wl) }
        let keys = Admission.keys(d, payload: p.payload, sig: p.sig, producerKey: v.producerKey)
        if !keys.isEmpty { return refuse("admission_refused", keys) }
        tokenVerified = true
        guard let nonce = node.sources.random.nonce(), nonce.count == 32, let ch = try? challenge(nonce: nonce) else {
            audit("internal_error", "random bytes refused")
            finish()
            return .failed("internal_error")
        }
        send(ch)
        let second: Bytes
        switch next("challenge") {
        case .body(let b): second = b
        case .ended(let how): return how
        }
        switch bodyKind(second).kind {
        case "key_rotated":
            guard case .keyRotated(let named)? = readFrame(second, count: v.count).frame else {
                return refuse("protocol_error", readFrame(second, count: v.count).why)
            }
            audit("key_rotated", "the peer says this node's token is under another kid than its current one")
            finish()
            if !v.dialed { node.report(.keyRotated(kid: named, dialed: false)) }
            return .keyRotated(kid: named)
        case "pop_challenge":
            guard case .popChallenge(let theirs)? = readFrame(second, count: v.count).frame else {
                return refuse("protocol_error", readFrame(second, count: v.count).why)
            }
            guard let sig = try? node.key.sign(theirs + v.token), let body = try? response(sig: sig) else {
                audit("internal_error", "the signature could not be made")
                finish()
                return .failed("internal_error")
            }
            send(body)
        default:
            return refuse("protocol_error", "a challenge was expected")
        }
        let third: Bytes
        switch next("response") {
        case .body(let b): third = b
        case .ended(let how): return how
        }
        guard bodyKind(third).kind == "pop_response" else { return refuse("pop_failed", "a response was expected") }
        guard case .popResponse(let sig)? = readFrame(third, count: v.count).frame else {
            return refuse("pop_failed", readFrame(third, count: v.count).why)
        }
        guard Admission.proof(pub: d.pub, nonce: nonce, token: d.token, sig: sig) else {
            return refuse("pop_failed", "the proof of possession does not verify")
        }
        audit("admitted", p.fields!.typ + (listed.map { ", tempus whitelist entry \($0)" } ?? ", token and proof of possession"))
        return nil
    }

    /// Every entry of a received frame is verified without contact before the node sees the frame (ruling OQ-4): one
    /// that does not verify refuses the whole frame. nil when all verify.
    private func entries(_ body: Bytes) -> (frame: Frame?, refused: DialOutcome?) {
        let r = readFrame(body, count: v.count)
        guard let f = r.frame, let store = f.store, let list = f.entries else { return (nil, refuse("protocol_error", r.why)) }
        for (k, e) in list.enumerated() {
            let why = Admission.entry(e.d, kid: v.kid, producerKey: v.producerKey, now: v.now, skew: v.skew, want: PeerType(rawValue: store))
            if !why.isEmpty { return (nil, refuse("entry_refused", "entry \(k): \(why)")) }
        }
        return (f, nil)
    }

    // ---------------------------------------------------------------- an accepted connection
    /// `closeWith`: the audit event with which the connection is closed at once after its handshake (the node is at
    /// inflight_max, waits for its clock, or has stopped).
    func accepted(_ fd: Int32, closeWith: String?, onClose: @escaping () -> Void) {
        self.onClose = onClose
        setNonBlocking(fd)
        guard let ssl = SSL_new(node.serverContext.ctx) else {
            close(fd)
            onClose()
            return
        }
        SSL_set_fd(ssl, fd)
        SSL_set_accept_state(ssl)
        guard handshake(ssl, fd) else { return }
        if let closeWith {
            switch closeWith {
            case "inflight_refused": audit(closeWith, "more accepted connections than inflight_max: closed at once")
            case "clock_refused": audit(closeWith, "the system clock cannot be read: closed at once")
            default: audit(closeWith, "the node stopped after its system clock went back: closed at once")
            }
            finish()
            return
        }
        if admit() != nil { return }
        guard case .body(let body) = next("request"), let d = peer else { return }
        let typ = (try? readToken(d.token).fields.typ) ?? ""
        let k = bodyKind(body)
        var frame: Frame?
        switch k.kind {
        case "shuffle":
            let e = entries(body)
            if e.refused != nil { return }
            frame = e.frame
        case "sample":
            let r = readFrame(body, count: entriesMax)
            guard r.frame != nil else {
                _ = refuse("protocol_error", r.why)
                return
            }
            frame = r.frame
        case "call", "cast":
            break
        default:
            // a frame of no request kind: the test-only tick and clock frames are refused here like any other
            _ = refuse("protocol_error", "not a request: " + (k.kind == nil ? k.why : "unknown kind"))
            return
        }
        if case .reply(let reply) = node.request(frame, kind: k.kind!, peer: d, typ: typ, cid: v.cid) { send(reply) }
        finish()
    }

    // ---------------------------------------------------------------- a dialed connection
    func dial(_ addr: String, request: Bytes) -> DialOutcome {
        guard let (host, port) = splitAddress(addr), let p = UInt16(port) else { return .failed("connect_failed") }
        var sa = sockaddr_in()
        sa.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
        sa.sin_family = sa_family_t(AF_INET)
        sa.sin_port = p.bigEndian
        guard inet_pton(AF_INET, host, &sa.sin_addr) == 1 else { return .failed("connect_failed") }
        let fd = socket(AF_INET, SOCK_STREAM, 0)
        guard fd >= 0 else { return .failed("connect_failed") }
        setNonBlocking(fd)
        let rc = withUnsafePointer(to: &sa) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { connect(fd, $0, socklen_t(MemoryLayout<sockaddr_in>.size)) }
        }
        if rc != 0 {
            var ready: Int32 = 0
            if errno == EINPROGRESS {
                var pf = pollfd(fd: fd, events: Int16(POLLOUT), revents: 0)
                repeat {
                    let left = v.deadline - monotonic()
                    ready = left <= 0 ? 0 : poll(&pf, 1, Int32(max(1, left * 1000)))
                } while ready < 0 && errno == EINTR
            }
            var err: Int32 = 0
            var len = socklen_t(MemoryLayout<Int32>.size)
            getsockopt(fd, SOL_SOCKET, SO_ERROR, &err, &len)
            if ready <= 0 || err != 0 {
                close(fd)
                return .failed("connect_failed")
            }
        }
        guard let ssl = SSL_new(node.clientContext.ctx) else {
            close(fd)
            return .failed("connect_failed")
        }
        SSL_set_fd(ssl, fd)
        SSL_set_connect_state(ssl)
        guard handshake(ssl, fd) else { return .failed("connect_failed") }
        if let ended = admit() { return ended }
        guard let d = peer else { return .failed("closed") }
        let typ = (try? readToken(d.token).fields.typ) ?? ""
        send(request)
        let body: Bytes
        switch next("reply") {
        case .body(let b): body = b
        case .ended(let how): return how
        }
        switch bodyKind(body).kind {
        case "shuffle_reply", "sample_reply":
            let e = entries(body)
            if let refused = e.refused { return refused }
            finish()
            return .reply(e.frame, peer: d, typ: typ)
        case "done", "result":
            finish()
            return .reply(nil, peer: d, typ: typ)
        default:
            return refuse("protocol_error", "the reply is not a reply frame")
        }
    }
}
