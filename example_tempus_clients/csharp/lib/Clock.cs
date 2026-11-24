// A usable example, to be used carefully. See README.md in the directory above.
//
// The node's clock: what one reading of the system clock does to the node's time and clock state (rulings NQ-11 and
// NQ-22; development-plan/tempus-design.md section 10). Pure, and equal to bees_tempus_node@clock_back and
// clock_turn of the Silica library, so the cases of trials/t0_tempus_clock apply to it line for line.
using System;

namespace Bees.Tempus
{
    /// <summary>The node's clock state. The numbers are the Silica node's (its `ck`).</summary>
    public static class ClockState
    {
        public const int NoReading = 0;          // no reading yet
        public const int Good = 1;               // the last reading was good
        public const int Paused = 2;             // a reading failed after a good one; the node waits (clock_fail pause)
        public const int NoReadingTold = 3;      // no reading yet, and the application was told
        public const int Stopped = 4;            // stopped after a step back above the limit (clock_back stop), for good
        public const int Holding = 5;            // the node holds a time later than the system clock's (clock_back hold)
        public const int Continuing = 6;         // a reading failed after a good one; the node goes on (clock_fail continue)

        /// <summary>A node ticks, and dials, with a good reading, while it holds its time and while it goes on after a failure.</summary>
        public static bool Ticks(int ck) => ck == Good || ck == Holding || ck == Continuing;

        /// <summary>Why an accepted connection is closed at once in this state: "clock_refused", "clock_stopped", or null.</summary>
        public static string Closes(int ck) => ck == Paused ? "clock_refused" : ck == Stopped ? "clock_stopped" : null;
    }

    /// <summary>What the node does after one reading.</summary>
    public static class ClockSay
    {
        public const int Nothing = 0;
        public const int First = 1;              // the first reading: one line, the node listens
        public const int NoneAtStart = 2;        // no time at start: one line, the application told
        public const int FailedPause = 3;        // no time after a good reading, pause: one line, the application told
        public const int FailedContinue = 4;     // no time after a good reading, continue: one line, the application told
        public const int BackFollowed = 6;       // a step back, followed: one line
        public const int BackHeld = 7;           // a step back, held from now on: one line
        public const int HoldEnded = 8;          // the system clock has reached the held time: one line
        public const int BackStop = 9;           // a step back above the limit: one line, the application told, the node stops
    }

    public static class Clock
    {
        /// <summary>
        /// Now: the node's time after the reading. Act: 0 not earlier, 1 earlier and followed, 2 earlier and held,
        /// 3 the node stops. back: "follow", "hold" or "stop"; limit: under stop, the greatest step back in seconds
        /// still followed.
        /// </summary>
        public static (long Now, int Act) Back(long last, long n, string back, long limit)
        {
            if (n >= last) return (n, 0);
            if (back == "hold") return (last, 2);
            if (back == "stop") return last - n > limit ? (last, 3) : (n, 1);
            return (n, 1);
        }

        /// <summary>
        /// One reading: n is the seconds since 1970 UTC, or null when the system gave no time. fail is "continue" or
        /// "pause". Again: the clock is read again after a pause (one line, before what Say names).
        /// </summary>
        public static (long Now, int Ck, int Say, bool Again) Turn(int ck, long last, long? n, string back, long limit, string fail)
        {
            if (ck == ClockState.Stopped) return (last, ck, ClockSay.Nothing, false);
            if (n == null || n < 0)
            {
                if (ck == ClockState.NoReading) return (last, ClockState.NoReadingTold, ClockSay.NoneAtStart, false);
                if (ck == ClockState.Good || ck == ClockState.Holding)
                    return fail == "continue" ? (last, ClockState.Continuing, ClockSay.FailedContinue, false) : (last, ClockState.Paused, ClockSay.FailedPause, false);
                return (last, ck, ClockSay.Nothing, false);
            }
            if (ck == ClockState.NoReading || ck == ClockState.NoReadingTold) return (n.Value, ClockState.Good, ClockSay.First, false);
            var b = Back(last, n.Value, back, limit);
            bool again = ck == ClockState.Paused;
            switch (b.Act)
            {
                case 0: return (b.Now, ClockState.Good, ck == ClockState.Holding ? ClockSay.HoldEnded : ClockSay.Nothing, again);
                case 1: return (b.Now, ClockState.Good, ClockSay.BackFollowed, again);
                case 2: return (b.Now, ClockState.Holding, ck == ClockState.Holding ? ClockSay.Nothing : ClockSay.BackHeld, again);
                default: return (b.Now, ClockState.Stopped, ClockSay.BackStop, again);
            }
        }

        /// <summary>The machine's clock: whole seconds since 1970 UTC, or null. A time before 1970 is no time, never a made-up one.</summary>
        public static long? SystemSeconds()
        {
            long ms;
            try { ms = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(); } catch (Exception) { return null; }
            return ms < 0 ? (long?)null : ms / 1000;
        }
    }
}
