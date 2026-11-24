// TEST ONLY. What a test gives a node in place of the machine's clock, real timers and random draws, through the
// node's ordinary construction interface (NodeEnvironment). Nothing in this file is part of the extension, and no
// frame a peer can send reaches any of it.
package bees.tempus.test

import bees.tempus.DrawSource
import bees.tempus.NodeEnvironment
import bees.tempus.NodeTimers
import bees.tempus.WallClock
import java.security.SecureRandom

/** TEST ONLY: a clock whose reading the test sets. null: the clock could not be read. */
class TestClock(@Volatile var reading: Long?) : WallClock {
    override fun seconds(): Long? = reading
}

/**
 * TEST ONLY: timers that never run by themselves. The node arms them as it would arm real ones; the test runs one by
 * its name ("clock", "tick tempus_edge", "join tempus_edge") when the scenario says that its time has come.
 */
class ManualTimers : NodeTimers {
    private val pending = HashMap<String, ArrayDeque<() -> Unit>>()

    @Synchronized override fun after(ms: Long, name: String, action: () -> Unit) {
        pending.getOrPut(name) { ArrayDeque() }.addLast(action)
    }

    @Synchronized private fun take(name: String): (() -> Unit)? = pending[name]?.removeFirstOrNull()

    @Synchronized fun armed(name: String): Boolean = !pending[name].isNullOrEmpty()

    /** Runs the oldest armed timer of that name. False when none is armed. */
    fun fire(name: String): Boolean {
        val action = take(name) ?: return false
        action()
        return true
    }
}

/**
 * TEST ONLY: draws from a literal list, as an externally driven Silica node takes them (design 3.5): each answer is
 * the whole list turned left by one more place, counted per store.
 */
class LiteralDraws(private val literal: List<Long>) : DrawSource {
    private val turns = HashMap<String, Int>()

    @Synchronized override fun draws(store: String, count: Int): List<Long>? {
        val j = turns.getOrDefault(store, 0)
        turns[store] = j + 1
        if (literal.isEmpty()) return literal
        val k = j % literal.size
        return literal.drop(k) + literal.take(k)
    }
}

/** TEST ONLY: the lines of a node, kept in order; a test waits for one. */
class Lines {
    private val all = ArrayList<String>()
    private var seen = 0

    @Synchronized fun add(line: String) { all.add(line); (this as Object).notifyAll() }

    @Synchronized fun snapshot(): List<String> = ArrayList(all)

    /** The first line after the last one matched that the pattern finds; null when none came in time. */
    @Synchronized fun await(pattern: Regex, waitMs: Long = 20000): String? {
        val until = System.nanoTime() + waitMs * 1_000_000
        while (true) {
            for (i in seen until all.size) if (pattern.containsMatchIn(all[i])) { seen = i + 1; return all[i] }
            val left = (until - System.nanoTime()) / 1_000_000
            if (left <= 0) return null
            (this as Object).wait(minOf(left, 200))
        }
    }
}

/** TEST ONLY: the environment of a test node. */
fun testEnvironment(clock: TestClock, timers: ManualTimers, draws: List<Long>, lines: Lines): NodeEnvironment =
    NodeEnvironment(clock, timers, LiteralDraws(draws), SecureRandom()) { lines.add(it) }
