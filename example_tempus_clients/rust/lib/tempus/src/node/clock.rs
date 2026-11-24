//! The node's clock: what one reading of the system clock does to the node (design section 10; rulings NQ-11 and
//! NQ-22). clock_turn is pure and is the rule of bees_tempus_node@clock_turn in src/tempus/bees_tempus_node.silica.in;
//! the tests compute every line of trials/t0_tempus_clock's recorded output with it.
use std::time::{SystemTime, UNIX_EPOCH};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ClockBack {
    Follow,
    Hold,
    Stop,
}

impl ClockBack {
    pub fn name(self) -> &'static str {
        match self {
            ClockBack::Follow => "follow",
            ClockBack::Hold => "hold",
            ClockBack::Stop => "stop",
        }
    }

    pub fn from_name(s: &str) -> Option<ClockBack> {
        [ClockBack::Follow, ClockBack::Hold, ClockBack::Stop].into_iter().find(|b| b.name() == s)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ClockFail {
    Continue,
    Pause,
}

impl ClockFail {
    pub fn name(self) -> &'static str {
        match self {
            ClockFail::Continue => "continue",
            ClockFail::Pause => "pause",
        }
    }

    pub fn from_name(s: &str) -> Option<ClockFail> {
        [ClockFail::Continue, ClockFail::Pause].into_iter().find(|b| b.name() == s)
    }
}

/// The node's clock state.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ClockState {
    /// No reading yet.
    None,
    /// No reading yet, and the application was told.
    NoneTold,
    /// The last reading was good.
    Good,
    /// A reading failed after a good one and the node waits for the next good one (clock_fail pause).
    Paused,
    /// A reading failed after a good one and the node goes on with its last reading (clock_fail continue).
    Continuing,
    /// The node holds a time later than the system clock's (clock_back hold).
    Holding,
    /// Stopped after a step back above the limit (clock_back stop), for good.
    Stopped,
}

impl ClockState {
    /// A node ticks, and dials, in these states only.
    pub fn ticks(self) -> bool {
        matches!(self, ClockState::Good | ClockState::Holding | ClockState::Continuing)
    }

    /// The audit event with which an accepted connection is closed at once in this state, if it is.
    pub fn closes_with(self) -> Option<&'static str> {
        match self {
            ClockState::Paused => Some("clock_refused"),
            ClockState::Stopped => Some("clock_stopped"),
            _ => None,
        }
    }
}

/// What the node does after a reading.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ClockSay {
    Nothing,
    /// The first reading: one line, the node listens.
    First,
    /// One line, the application told; the node has not started.
    NoTimeAtStart,
    /// One line, the application told.
    NoTimePause,
    /// One line, the application told.
    NoTimeContinue,
    /// A step back, followed: one line.
    Followed,
    /// A step back, held from now on: one line.
    HoldBegins,
    /// The system clock has reached the held time: one line.
    HoldEnds,
    /// A step back above the limit: one line, the application told, the node stops.
    Stop,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ClockChoices {
    pub back: ClockBack,
    /// Read under `Stop` only.
    pub limit: i64,
    pub fail: ClockFail,
}

/// One good reading `n` after the node's time `last`: the node's time afterwards and what happened
/// (0 not earlier, 1 earlier and followed, 2 earlier and held, 3 earlier by more than the limit: the node stops).
pub fn clock_back(last: i64, n: i64, z: ClockChoices) -> (i64, u8) {
    if n >= last {
        return (n, 0);
    }
    match z.back {
        ClockBack::Hold => (last, 2),
        ClockBack::Stop => if last - n > z.limit { (last, 3) } else { (n, 1) },
        ClockBack::Follow => (n, 1),
    }
}

/// The outcome of one reading.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ClockTurn {
    pub now: i64,
    pub ck: ClockState,
    pub say: ClockSay,
    /// The clock is read again after a pause (one line, before what `say` names).
    pub again: bool,
}

/// One reading: `reading` is the seconds since 1970, or None when the operating system gave no time.
pub fn clock_turn(ck: ClockState, last: i64, reading: Option<i64>, z: ClockChoices) -> ClockTurn {
    let turn = |now, ck, say, again| ClockTurn { now, ck, say, again };
    if ck == ClockState::Stopped {
        return turn(last, ClockState::Stopped, ClockSay::Nothing, false);
    }
    let n = match reading {
        Some(n) if n >= 0 => n,
        _ => {
            return match ck {
                ClockState::None => turn(last, ClockState::NoneTold, ClockSay::NoTimeAtStart, false),
                ClockState::Good | ClockState::Holding => match z.fail {
                    ClockFail::Continue => turn(last, ClockState::Continuing, ClockSay::NoTimeContinue, false),
                    ClockFail::Pause => turn(last, ClockState::Paused, ClockSay::NoTimePause, false),
                },
                _ => turn(last, ck, ClockSay::Nothing, false),
            }
        }
    };
    if ck == ClockState::None || ck == ClockState::NoneTold {
        return turn(n, ClockState::Good, ClockSay::First, false);
    }
    let (now, act) = clock_back(last, n, z);
    let again = ck == ClockState::Paused;
    match act {
        0 => turn(now, ClockState::Good, if ck == ClockState::Holding { ClockSay::HoldEnds } else { ClockSay::Nothing }, again),
        1 => turn(now, ClockState::Good, ClockSay::Followed, again),
        2 => turn(now, ClockState::Holding, if ck == ClockState::Holding { ClockSay::Nothing } else { ClockSay::HoldBegins }, again),
        _ => turn(now, ClockState::Stopped, ClockSay::Stop, again),
    }
}

/// The machine's clock in whole seconds since 1970 UTC, or None when the operating system gives a time before 1970:
/// an error is an error and never a made-up time.
pub fn read_system_clock() -> Option<i64> {
    SystemTime::now().duration_since(UNIX_EPOCH).ok().map(|d| d.as_secs() as i64)
}
