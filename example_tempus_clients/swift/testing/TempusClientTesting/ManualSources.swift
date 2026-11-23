// TEST ONLY: a clock, timers and draws that a test sets by hand, for a node made with
// TempusNode(config:identity:sources:lines:events:). No application links this target.
import Foundation
import TempusClient
import TempusNode

/// TEST ONLY: a clock whose reading is whatever the test last set; nil says that the clock cannot be read.
public final class ManualClock: NodeClockSource, @unchecked Sendable {
    private let lock = NSLock()
    private var value: Int64?

    public init(_ value: Int64?) { self.value = value }

    public func set(_ v: Int64?) {
        lock.lock()
        value = v
        lock.unlock()
    }

    public func seconds() -> Int64? {
        lock.lock()
        defer { lock.unlock() }
        return value
    }
}

/// TEST ONLY: timers that never run by themselves. The node's last timer of each purpose is kept, and fire(_:) runs it.
public final class ManualTimers: NodeTimers, @unchecked Sendable {
    private let lock = NSLock()
    private var armed: [TimerPurpose: @Sendable () -> Void] = [:]

    public init() {}

    public func after(milliseconds: Int, for purpose: TimerPurpose, _ action: @escaping @Sendable () -> Void) {
        lock.lock()
        armed[purpose] = action
        lock.unlock()
    }

    /// Runs the timer armed for this purpose, as if its time had passed. False when none is armed.
    @discardableResult
    public func fire(_ purpose: TimerPurpose) -> Bool {
        lock.lock()
        let action = armed.removeValue(forKey: purpose)
        lock.unlock()
        action?()
        return action != nil
    }
}

/// TEST ONLY: draws from a literal list, turned by one place per request, and a fixed nonce per request number, so
/// that a trial's output is the same on every run. `empty` true gives no draws at all.
public final class ListRandom: NodeRandom, @unchecked Sendable {
    private let lock = NSLock()
    private let list: [Int]
    private var turns = 0
    private var nonces = 0

    public init(_ list: [Int]) { self.list = list }

    public func draws(_ count: Int) -> [Int]? {
        lock.lock()
        defer { lock.unlock() }
        guard !list.isEmpty else { return nil }
        let k = turns % list.count
        turns += 1
        return Array(list[k...] + list[..<k])
    }

    public func nonce() -> Bytes? {
        lock.lock()
        defer { lock.unlock() }
        nonces += 1
        return (0..<32).map { UInt8(truncatingIfNeeded: nonces &+ $0) }
    }
}
