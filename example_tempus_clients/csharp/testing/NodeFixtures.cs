// TEST ONLY. What a test gives a node in place of the machine's clock, real timers and random draws, through the
// node's ordinary construction interface (NodeEnvironment). Nothing in this file is part of the extension, and no
// frame a peer can send reaches any of it.
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;
using System.Threading;

namespace Bees.Tempus.Testing
{
    /// <summary>TEST ONLY: a clock whose reading the test sets. null: the clock could not be read.</summary>
    public sealed class TestClock
    {
        long? reading;
        readonly object gate = new object();
        public TestClock(long? reading) { this.reading = reading; }
        public long? Reading { get { lock (gate) return reading; } set { lock (gate) reading = value; } }
        public long? Seconds() => Reading;
    }

    /// <summary>
    /// TEST ONLY: timers that never run by themselves. The node arms them as it would arm real ones; the test runs one
    /// by its name ("clock", "tick tempus_edge", "join tempus_edge") when the scenario says that its time has come.
    /// </summary>
    public sealed class ManualTimers : INodeTimers
    {
        readonly Dictionary<string, Queue<Action>> pending = new Dictionary<string, Queue<Action>>();

        public void After(long ms, string name, Action action)
        {
            lock (pending)
            {
                if (!pending.TryGetValue(name, out var q)) pending[name] = q = new Queue<Action>();
                q.Enqueue(action);
            }
        }

        public bool Armed(string name) { lock (pending) return pending.TryGetValue(name, out var q) && q.Count > 0; }

        /// <summary>Runs the oldest armed timer of that name. False when none is armed.</summary>
        public bool Fire(string name)
        {
            Action action;
            lock (pending)
            {
                if (!pending.TryGetValue(name, out var q) || q.Count == 0) return false;
                action = q.Dequeue();
            }
            action();
            return true;
        }
    }

    /// <summary>
    /// TEST ONLY: draws from a literal list, as an externally driven Silica node takes them (design 3.5): each answer
    /// is the whole list turned left by one more place, counted per store.
    /// </summary>
    public sealed class LiteralDraws : IDrawSource
    {
        readonly List<long> literal;
        readonly Dictionary<string, int> turns = new Dictionary<string, int>();
        public LiteralDraws(IEnumerable<long> literal) { this.literal = literal.ToList(); }

        public IReadOnlyList<long> Draws(string store, int count)
        {
            lock (turns)
            {
                turns.TryGetValue(store, out int j);
                turns[store] = j + 1;
                if (literal.Count == 0) return new List<long>();
                int k = j % literal.Count;
                return literal.Skip(k).Concat(literal.Take(k)).ToList();
            }
        }
    }

    /// <summary>TEST ONLY: the lines of a node, kept in order; a test waits for one.</summary>
    public sealed class Lines
    {
        readonly List<string> all = new List<string>();
        int seen;

        public void Add(string line) { lock (all) { all.Add(line); Monitor.PulseAll(all); } }

        public List<string> Snapshot() { lock (all) return new List<string>(all); }

        /// <summary>The first line after the last one matched that the pattern finds; null when none came in time.</summary>
        public string Await(string pattern, long waitMs = 20000)
        {
            var rx = new Regex(pattern);
            long until = Tls.NowMs() + waitMs;
            lock (all)
            {
                while (true)
                {
                    for (int i = seen; i < all.Count; i++) if (rx.IsMatch(all[i])) { seen = i + 1; return all[i]; }
                    long left = until - Tls.NowMs();
                    if (left <= 0) return null;
                    Monitor.Wait(all, (int)Math.Min(left, 200));
                }
            }
        }
    }

    public static class TestEnvironment
    {
        /// <summary>TEST ONLY: the environment of a test node. The nonces are real random bytes.</summary>
        public static NodeEnvironment Of(TestClock clock, ManualTimers timers, IEnumerable<long> draws, Lines lines) =>
            new NodeEnvironment(clock.Seconds, timers, new LiteralDraws(draws), () => Crypto.RandomBytes(32), lines.Add);
    }
}
