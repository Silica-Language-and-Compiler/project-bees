// A usable example, to be used carefully. See README.md beside the lib directory.
//
// The node's clock: what one reading of the system clock does to the node's time and clock state (rulings NQ-11 and
// NQ-22; development-plan/tempus-design.md section 10). Pure, and equal to bees_tempus_node@clock_back and
// clock_turn of the Silica library, so the cases of trials/t0_tempus_clock apply to it line for line.
package bees.tempus

/** The node's clock state. The numbers are the Silica node's (its `ck`). */
object ClockState {
    const val NO_READING = 0          // no reading yet
    const val GOOD = 1                // the last reading was good
    const val PAUSED = 2              // a reading failed after a good one; the node waits (clock_fail pause)
    const val NO_READING_TOLD = 3     // no reading yet, and the application was told
    const val STOPPED = 4             // stopped after a step back above the limit (clock_back stop), for good
    const val HOLDING = 5             // the node holds a time later than the system clock's (clock_back hold)
    const val CONTINUING = 6          // a reading failed after a good one; the node goes on (clock_fail continue)

    /** A node ticks, and dials, with a good reading, while it holds its time and while it goes on after a failure. */
    fun ticks(ck: Int): Boolean = ck == GOOD || ck == HOLDING || ck == CONTINUING

    /** Why an accepted connection is closed at once in this state: "clock_refused", "clock_stopped", or null. */
    fun closes(ck: Int): String? = when (ck) { PAUSED -> "clock_refused"; STOPPED -> "clock_stopped"; else -> null }
}

/** What the node does after one reading. */
object ClockSay {
    const val NOTHING = 0
    const val FIRST = 1               // the first reading: one line, the node listens
    const val NONE_AT_START = 2       // no time at start: one line, the application told
    const val FAILED_PAUSE = 3        // no time after a good reading, pause: one line, the application told
    const val FAILED_CONTINUE = 4     // no time after a good reading, continue: one line, the application told
    const val BACK_FOLLOWED = 6       // a step back, followed: one line
    const val BACK_HELD = 7           // a step back, held from now on: one line
    const val HOLD_ENDED = 8          // the system clock has reached the held time: one line
    const val BACK_STOP = 9           // a step back above the limit: one line, the application told, the node stops
}

/** now: the node's time after the reading. act: 0 not earlier, 1 earlier and followed, 2 earlier and held, 3 the node stops. */
class ClockBack(val now: Long, val act: Int)

/** again: the clock is read again after a pause (one line, before what `say` names). */
class ClockTurn(val now: Long, val ck: Int, val say: Int, val again: Boolean)

/** back: "follow", "hold" or "stop"; limit: under stop, the greatest step back in seconds still followed. */
fun clockBack(last: Long, n: Long, back: String, limit: Long): ClockBack = when {
    n >= last -> ClockBack(n, 0)
    back == "hold" -> ClockBack(last, 2)
    back == "stop" -> if (last - n > limit) ClockBack(last, 3) else ClockBack(n, 1)
    else -> ClockBack(n, 1)
}

/**
 * One reading: n is the seconds since 1970 UTC, or null when the system gave no time. fail is "continue" or "pause".
 */
fun clockTurn(ck: Int, last: Long, n: Long?, back: String, limit: Long, fail: String): ClockTurn {
    if (ck == ClockState.STOPPED) return ClockTurn(last, ck, ClockSay.NOTHING, false)
    if (n == null || n < 0) {
        return when (ck) {
            ClockState.NO_READING -> ClockTurn(last, ClockState.NO_READING_TOLD, ClockSay.NONE_AT_START, false)
            ClockState.GOOD, ClockState.HOLDING ->
                if (fail == "continue") ClockTurn(last, ClockState.CONTINUING, ClockSay.FAILED_CONTINUE, false)
                else ClockTurn(last, ClockState.PAUSED, ClockSay.FAILED_PAUSE, false)
            else -> ClockTurn(last, ck, ClockSay.NOTHING, false)
        }
    }
    if (ck == ClockState.NO_READING || ck == ClockState.NO_READING_TOLD) return ClockTurn(n, ClockState.GOOD, ClockSay.FIRST, false)
    val b = clockBack(last, n, back, limit)
    val again = ck == ClockState.PAUSED
    return when (b.act) {
        0 -> ClockTurn(b.now, ClockState.GOOD, if (ck == ClockState.HOLDING) ClockSay.HOLD_ENDED else ClockSay.NOTHING, again)
        1 -> ClockTurn(b.now, ClockState.GOOD, ClockSay.BACK_FOLLOWED, again)
        2 -> ClockTurn(b.now, ClockState.HOLDING, if (ck == ClockState.HOLDING) ClockSay.NOTHING else ClockSay.BACK_HELD, again)
        else -> ClockTurn(b.now, ClockState.STOPPED, ClockSay.BACK_STOP, again)
    }
}

/** Where a node reads the time of day: whole seconds since 1970 UTC, or null when the system gave none. */
fun interface WallClock {
    fun seconds(): Long?
}

/** The machine's clock. A time before 1970 is no time, never a made-up one. */
object SystemWallClock : WallClock {
    override fun seconds(): Long? {
        val ms = try { System.currentTimeMillis() } catch (e: Exception) { return null }
        return if (ms < 0) null else ms / 1000
    }
}
