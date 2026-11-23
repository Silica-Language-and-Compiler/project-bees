// What a node takes from the machine: the time of day, timers and random numbers. A node made with
// TempusNode(config:identity:lines:events:) uses the three system sources below and nothing else: it reads the
// machine's clock itself, and its application cannot pass the time in. The second initializer takes the sources as
// values, which is how a test gives a node a clock, timers and draws of its own; a node made that way listens on a
// loopback address only (the start is refused otherwise).
import COpenSSL
import Foundation
import TempusClient

public enum TimerPurpose: Sendable, Hashable {
    /// The shuffle tick of one store.
    case tick(PeerType)
    /// The wait before the join is tried again.
    case joinRetry
    /// The next reading of the clock.
    case clockRead
}

public protocol NodeClockSource: Sendable {
    /// Whole seconds since 1970 UTC, or nil when the clock cannot be read.
    func seconds() -> Int64?
}

public protocol NodeTimers: Sendable {
    /// Runs `action` once, `milliseconds` from now. The node arms a timer again itself each time one has run.
    func after(milliseconds: Int, for purpose: TimerPurpose, _ action: @escaping @Sendable () -> Void)
}

public protocol NodeRandom: Sendable {
    /// `count` non-negative integers for the choices of one tick or one answer, or nil when none can be had.
    func draws(_ count: Int) -> [Int]?
    /// 32 bytes for one challenge, or nil when none can be had.
    func nonce() -> Bytes?
}

public struct NodeSources: Sendable {
    public var clock: any NodeClockSource
    public var timers: any NodeTimers
    public var random: any NodeRandom

    public init(clock: any NodeClockSource, timers: any NodeTimers, random: any NodeRandom) {
        self.clock = clock
        self.timers = timers
        self.random = random
    }

    /// The machine's clock, the system's timers and the system's secure random source.
    public static var system: NodeSources { NodeSources(clock: SystemClock(), timers: SystemTimers(), random: SecureRandom()) }
}

public struct SystemClock: NodeClockSource {
    public init() {}
    public func seconds() -> Int64? { readSystemClock() }
}

public struct SystemTimers: NodeTimers {
    public init() {}
    public func after(milliseconds: Int, for purpose: TimerPurpose, _ action: @escaping @Sendable () -> Void) {
        DispatchQueue.global().asyncAfter(deadline: .now() + .milliseconds(milliseconds), execute: action)
    }
}

/// The system's secure random source, through OpenSSL: seven bytes a draw (design 3.5), so the bias of a draw taken
/// modulo at most 256 candidates is below 2^-47.
public struct SecureRandom: NodeRandom {
    public init() {}

    public func draws(_ count: Int) -> [Int]? {
        guard let raw = try? randomBytes(7 * count) else { return nil }
        return (0..<count).map { i in raw[(7 * i)..<(7 * i + 7)].reduce(0) { ($0 << 8) | Int($1) } }
    }

    public func nonce() -> Bytes? { try? randomBytes(32) }
}
