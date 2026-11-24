//! TEST ONLY: a clock, timers and draws that a test sets by hand, for a node made with TempusNode::with_sources.
//! No application links this crate.
use std::collections::HashMap;
use std::sync::Mutex;
use tempus::node::sources::{ClockSource, RandomSource, TimerAction, TimerPurpose, Timers};

/// TEST ONLY: a clock whose reading is whatever the test last set; None says that the clock cannot be read.
pub struct ManualClock(Mutex<Option<i64>>);

impl ManualClock {
    pub fn new(value: Option<i64>) -> ManualClock {
        ManualClock(Mutex::new(value))
    }

    pub fn set(&self, value: Option<i64>) {
        *self.0.lock().unwrap() = value;
    }
}

impl ClockSource for ManualClock {
    fn seconds(&self) -> Option<i64> {
        *self.0.lock().unwrap()
    }
}

/// TEST ONLY: timers that never run by themselves. The node's last timer of each purpose is kept, and fire runs it.
#[derive(Default)]
pub struct ManualTimers(Mutex<HashMap<TimerPurpose, TimerAction>>);

impl ManualTimers {
    pub fn new() -> ManualTimers {
        ManualTimers::default()
    }

    /// Runs the timer armed for this purpose, as if its time had passed. False when none is armed.
    pub fn fire(&self, purpose: TimerPurpose) -> bool {
        let action = self.0.lock().unwrap().remove(&purpose);
        match action {
            Some(a) => {
                a();
                true
            }
            None => false,
        }
    }
}

impl Timers for ManualTimers {
    fn after(&self, _milliseconds: u64, purpose: TimerPurpose, action: TimerAction) {
        self.0.lock().unwrap().insert(purpose, action);
    }
}

/// TEST ONLY: draws from a literal list, turned by one place per request, and a fixed nonce per request number, so
/// that a trial's output is the same on every run. An empty list gives no draws at all.
pub struct ListRandom {
    list: Vec<i64>,
    turns: Mutex<(usize, usize)>,
}

impl ListRandom {
    pub fn new(list: Vec<i64>) -> ListRandom {
        ListRandom { list, turns: Mutex::new((0, 0)) }
    }
}

impl RandomSource for ListRandom {
    fn draws(&self, _count: usize) -> Option<Vec<i64>> {
        if self.list.is_empty() {
            return None;
        }
        let mut t = self.turns.lock().unwrap();
        let k = t.0 % self.list.len();
        t.0 += 1;
        let mut out = self.list[k..].to_vec();
        out.extend_from_slice(&self.list[..k]);
        Some(out)
    }

    fn nonce(&self) -> Option<Vec<u8>> {
        let mut t = self.turns.lock().unwrap();
        t.1 += 1;
        Some((0..32usize).map(|i| (t.1 + i) as u8).collect())
    }
}
