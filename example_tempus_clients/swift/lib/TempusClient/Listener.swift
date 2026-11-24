// The listening position (design 16.1; writing-a-tempus-client.md section 9): a node that learned of this client
// through gossip dials the address the client advertises. The same admission runs, then ONE request is read and answered.
// A usable example, to be used with care (README.md says what care means).
import COpenSSL
import Darwin
import Foundation

/// What a Listener's handler is given: the request as read, its bytes, the admitted peer's descriptor and token type,
/// and the number of the connection (0 for the first accepted).
public struct Request {
    public let frame: Frame
    public let body: Bytes
    public let advert: Descriptor
    public let typ: String
    public let index: Int
}

/// What a handler answers: a reply body, or a close with no reply.
public enum Answer {
    case reply(Bytes)
    case close
}

/// The answer of writing-a-tempus-client.md section 9: a shuffle with a shuffle_reply for the same store, a sample
/// with a sample_reply for the same store (at most the `n` asked for), anything else with a close and no reply.
/// `entries` gives what this client holds for a store.
public func standardAnswer(_ request: Request, entries: (String) -> [Entry]) -> Answer {
    switch request.frame {
    case .shuffle(let store, _):
        return (try? shuffleReply(store: store, entries: entries(store))).map(Answer.reply) ?? .close
    case .sample(let store, let n):
        return (try? sampleReply(store: store, entries: Array(entries(store).prefix(Int(n))))).map(Answer.reply) ?? .close
    default:
        return .close
    }
}

/// A thread accepts connections on host:port (port 0: the system picks one; `address` says which), and each
/// connection, in its own thread, is admitted, has ONE request read, and is answered by `handler`. Every connection
/// ends as one Outcome, kept in accept order: outcomes(count:) waits for them, and `onOutcome` is called with each, in
/// accept order.
///
/// Unlike the Python example's listener, this one needs no list of the certificates expected to dial it: any
/// self-signed Ed25519 certificate passes the handshake, and admission decides.
public final class Listener {
    public let identity: Identity
    public let verifier: Verifier
    public let handler: (Request) -> Answer
    public let timeout: Double
    public let shuffleLength: Int
    public let verifyEntries: Bool
    public let port: Int
    public let address: String
    public var onOutcome: ((Int, Outcome) -> Void)?
    /// A fixed challenge nonce per connection number, for a test; nil takes each from the secure random source.
    public var nonce: ((Int) -> Bytes)?

    private let fd: Int32
    private let context: TLSContext
    private let changed = NSCondition()
    private var done: [Int: Outcome] = [:]
    private var reported = 0
    private var stopping = false
    private var running = 0
    private var accepting = false

    public init(identity: Identity, verifier: Verifier, host: String = "127.0.0.1", port: Int = 0, timeout: Double,
                shuffleLength: Int = entriesMax, verifyEntries: Bool = true,
                handler: @escaping (Request) -> Answer) throws {
        self.identity = identity
        self.verifier = verifier
        self.handler = handler
        self.timeout = timeout
        self.shuffleLength = shuffleLength
        self.verifyEntries = verifyEntries
        context = try TLSContext(server: true, identity: identity)
        var hints = addrinfo()
        hints.ai_socktype = SOCK_STREAM
        hints.ai_flags = AI_PASSIVE | AI_NUMERICHOST
        var list: UnsafeMutablePointer<addrinfo>?
        guard getaddrinfo(host, String(port), &hints, &list) == 0, let first = list else {
            throw CryptoFailure("the listen address \(host) cannot be used")
        }
        defer { freeaddrinfo(list) }
        let fd = socket(first.pointee.ai_family, SOCK_STREAM, 0)
        self.fd = fd
        var one: Int32 = 1
        setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &one, socklen_t(MemoryLayout<Int32>.size))
        guard fd >= 0, bind(fd, first.pointee.ai_addr, first.pointee.ai_addrlen) == 0, listen(fd, 64) == 0 else {
            let e = errno
            if fd >= 0 { close(fd) }
            throw CryptoFailure("cannot listen on \(host):\(port) (errno \(e))")
        }
        var bound = sockaddr_storage()
        var len = socklen_t(MemoryLayout<sockaddr_storage>.size)
        let got = withUnsafeMutablePointer(to: &bound) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { getsockname(fd, $0, &len) }
        }
        var p = port
        if got == 0 {
            if bound.ss_family == sa_family_t(AF_INET) {
                p = withUnsafePointer(to: &bound) {
                    $0.withMemoryRebound(to: sockaddr_in.self, capacity: 1) { Int(UInt16(bigEndian: $0.pointee.sin_port)) }
                }
            } else {
                p = withUnsafePointer(to: &bound) {
                    $0.withMemoryRebound(to: sockaddr_in6.self, capacity: 1) { Int(UInt16(bigEndian: $0.pointee.sin6_port)) }
                }
            }
        }
        self.port = p
        address = "\(host):\(p)"
    }

    @discardableResult
    public func start() -> Listener {
        changed.lock()
        accepting = true
        changed.unlock()
        Thread.detachNewThread { [self] in accept() }
        return self
    }

    /// Stops accepting and waits for the connections in hand to end (each is bounded by `timeout`).
    public func stop() {
        changed.lock()
        stopping = true
        while accepting || running > 0 { changed.wait() }
        changed.unlock()
        close(fd)
    }

    /// The Outcomes of the first `count` connections in accept order, waiting up to `wait` seconds for them (fewer
    /// when they did not all end in time).
    public func outcomes(count: Int, wait: Double = 10.0) -> [Outcome] {
        let until = Date().addingTimeInterval(wait)
        changed.lock()
        defer { changed.unlock() }
        while !(0..<count).allSatisfy({ done[$0] != nil }) {
            if !changed.wait(until: until) { break }
        }
        return (0..<count).compactMap { done[$0] }
    }

    private func accept() {
        var index = 0
        while true {
            changed.lock()
            let stop = stopping
            changed.unlock()
            if stop { break }
            var p = pollfd(fd: fd, events: Int16(POLLIN), revents: 0)
            guard poll(&p, 1, 50) > 0 else { continue }
            let peer = Darwin.accept(fd, nil, nil)
            guard peer >= 0 else { continue }
            let i = index
            index += 1
            changed.lock()
            running += 1
            changed.unlock()
            Thread.detachNewThread { [self] in
                let out = serve(peer, i)
                changed.lock()
                done[i] = out
                running -= 1
                var ready: [(Int, Outcome)] = []
                while let next = done[reported] {
                    ready.append((reported, next))
                    reported += 1
                }
                // called with the lock held, so that the lines of two connections cannot change places
                for (n, o) in ready { onOutcome?(n, o) }
                changed.broadcast()
                changed.unlock()
            }
        }
        changed.lock()
        accepting = false
        changed.broadcast()
        changed.unlock()
    }

    private func serve(_ peer: Int32, _ index: Int) -> Outcome {
        let deadline = monotonic() + timeout
        let state = State()
        setNonBlocking(peer)
        guard let ssl = SSL_new(context.ctx) else {
            close(peer)
            return Outcome("tls_failed", "tls", reason: "no TLS object")
        }
        SSL_set_fd(ssl, peer)
        SSL_set_accept_state(ssl)
        let conn = Conn(ssl: ssl, fd: peer, deadline: deadline)
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
        if let out = admit(conn, me: identity, addr: identity.addr ?? address, verifier: verifier, nonce: nonce?(index),
                           certDER: certDER, state: state, shuffleLength: shuffleLength) {
            return out
        }
        let result = conn.read()
        guard case .frame(let body) = result else { return end(conn, result, "request", state) }
        let f: Frame
        do {
            f = try readAny(body, shuffleLength: shuffleLength)
            if verifyEntries { try checkEntries(f, verifier) }
        } catch {
            var out = end(conn, "refused", "request", state, "\(error)")
            out.body = body
            return out
        }
        let sent: String
        switch handler(Request(frame: f, body: body, advert: state.advert!, typ: state.typ, index: index)) {
        case .reply(let reply):
            conn.send(be32(reply.count) + reply)
            sent = "reply"
        case .close:
            sent = "close"
        }
        var out = end(conn, "served", "done", state)
        out.frame = f
        out.body = body
        out.sent = sent
        return out
    }
}
