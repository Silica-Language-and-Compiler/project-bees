// The node's clock: what one reading of the system clock does to the node (design section 10; rulings NQ-11 and
// NQ-22). clockTurn is pure and is the rule of bees_tempus_node@clock_turn in src/tempus/bees_tempus_node.silica.in;
// the tests compute every line of trials/t0_tempus_clock's recorded output with it.
import Darwin

public enum ClockBack: String, Sendable, CaseIterable { case follow, hold, stop }
public enum ClockFail: String, Sendable, CaseIterable { case `continue`, pause }

/// The node's clock state.
public enum ClockState: Sendable, Equatable {
    /// No reading yet.
    case none
    /// No reading yet, and the application was told.
    case noneTold
    /// The last reading was good.
    case good
    /// A reading failed after a good one and the node waits for the next good one (clock_fail pause).
    case paused
    /// A reading failed after a good one and the node goes on with its last reading (clock_fail continue).
    case continuing
    /// The node holds a time later than the system clock's (clock_back hold).
    case holding
    /// Stopped after a step back above the limit (clock_back stop), for good.
    case stopped

    /// A node ticks, and dials, in these states only.
    public var ticks: Bool { self == .good || self == .holding || self == .continuing }
    /// The audit event with which an accepted connection is closed at once in this state, if it is.
    public var closesWith: String? { self == .paused ? "clock_refused" : self == .stopped ? "clock_stopped" : nil }
}

/// What the node does after a reading.
public enum ClockSay: Sendable, Equatable {
    case nothing
    case first              // the first reading: one line, the node listens
    case noTimeAtStart      // one line, the application told; the node has not started
    case noTimePause        // one line, the application told
    case noTimeContinue     // one line, the application told
    case followed           // a step back, followed: one line
    case holdBegins         // a step back, held from now on: one line
    case holdEnds           // the system clock has reached the held time: one line
    case stop               // a step back above the limit: one line, the application told, the node stops
}

public struct ClockChoices: Sendable {
    public var back: ClockBack
    /// Read under `stop` only.
    public var limit: Int64
    public var fail: ClockFail

    public init(back: ClockBack, limit: Int64, fail: ClockFail) {
        self.back = back
        self.limit = limit
        self.fail = fail
    }
}

/// One good reading `n` after the node's time `last`: the node's time afterwards and what happened
/// (0 not earlier, 1 earlier and followed, 2 earlier and held, 3 earlier by more than the limit: the node stops).
public func clockBack(last: Int64, reading n: Int64, _ z: ClockChoices) -> (now: Int64, act: Int) {
    if n >= last { return (n, 0) }
    switch z.back {
    case .hold: return (last, 2)
    case .stop: return last - n > z.limit ? (last, 3) : (n, 1)
    case .follow: return (n, 1)
    }
}

/// One reading: `n` is the seconds since 1970, or nil when the operating system gave no time. `again` says that the
/// clock is read again after a pause (one line, before what `say` names).
public func clockTurn(_ ck: ClockState, last: Int64, reading n: Int64?, _ z: ClockChoices)
    -> (now: Int64, ck: ClockState, say: ClockSay, again: Bool) {
    if ck == .stopped { return (last, .stopped, .nothing, false) }
    guard let n, n >= 0 else {
        switch ck {
        case .none: return (last, .noneTold, .noTimeAtStart, false)
        case .good, .holding:
            return z.fail == .continue ? (last, .continuing, .noTimeContinue, false) : (last, .paused, .noTimePause, false)
        default: return (last, ck, .nothing, false)
        }
    }
    if ck == .none || ck == .noneTold { return (n, .good, .first, false) }
    let b = clockBack(last: last, reading: n, z)
    let again = ck == .paused
    switch b.act {
    case 0: return (b.now, .good, ck == .holding ? .holdEnds : .nothing, again)
    case 1: return (b.now, .good, .followed, again)
    case 2: return (b.now, .holding, ck == .holding ? .nothing : .holdBegins, again)
    default: return (b.now, .stopped, .stop, again)
    }
}

/// The machine's clock in whole seconds since 1970 UTC, or nil when the operating system gives no time or a time
/// before 1970: an error is an error and never a made-up time.
public func readSystemClock() -> Int64? {
    var ts = timespec()
    guard clock_gettime(CLOCK_REALTIME, &ts) == 0, ts.tv_sec >= 0 else { return nil }
    return Int64(ts.tv_sec)
}
