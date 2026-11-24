//! What a node takes from the machine: the time of day, timers and random numbers. A node made with TempusNode::new
//! uses the three system sources below and nothing else: it reads the machine's clock itself, and its application
//! cannot pass the time in. TempusNode::with_sources takes the sources as values, which is how a test gives a node a
//! clock, timers and draws of its own; a node made that way listens on a loopback address only (the start is refused
//! otherwise).
use super::clock::read_system_clock;
use super::config::PeerType;
use crate::crypto::random_bytes;
use std::collections::BinaryHeap;
use std::sync::mpsc::{channel, RecvTimeoutError, Sender};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum TimerPurpose {
    /// The shuffle tick of one store.
    Tick(PeerType),
    /// The wait before the join is tried again.
    JoinRetry,
    /// The next reading of the clock.
    ClockRead,
}

pub trait ClockSource: Send + Sync {
    /// Whole seconds since 1970 UTC, or None when the clock cannot be read.
    fn seconds(&self) -> Option<i64>;
}

pub type TimerAction = Box<dyn FnOnce() + Send>;

pub trait Timers: Send + Sync {
    /// Runs `action` once, `milliseconds` from now. The node arms a timer again itself each time one has run.
    fn after(&self, milliseconds: u64, purpose: TimerPurpose, action: TimerAction);
}

pub trait RandomSource: Send + Sync {
    /// `count` non-negative integers for the choices of one tick or one answer, or None when none can be had.
    fn draws(&self, count: usize) -> Option<Vec<i64>>;
    /// 32 bytes for one challenge, or None when none can be had.
    fn nonce(&self) -> Option<Vec<u8>>;
}

#[derive(Clone)]
pub struct Sources {
    pub clock: Arc<dyn ClockSource>,
    pub timers: Arc<dyn Timers>,
    pub random: Arc<dyn RandomSource>,
}

impl Sources {
    /// The machine's clock, timers on the machine's monotonic clock, and the system's secure random source.
    pub fn system() -> Sources {
        Sources { clock: Arc::new(SystemClock), timers: Arc::new(SystemTimers::new()), random: Arc::new(SecureRandom) }
    }
}

pub struct SystemClock;

impl ClockSource for SystemClock {
    fn seconds(&self) -> Option<i64> {
        read_system_clock()
    }
}

struct Due {
    at: Instant,
    order: u64,
    action: TimerAction,
}

impl PartialEq for Due {
    fn eq(&self, other: &Due) -> bool {
        self.at == other.at && self.order == other.order
    }
}

impl Eq for Due {}

impl PartialOrd for Due {
    fn partial_cmp(&self, other: &Due) -> Option<std::cmp::Ordering> {
        Some(self.cmp(other))
    }
}

impl Ord for Due {
    // the earliest first out of a max-heap
    fn cmp(&self, other: &Due) -> std::cmp::Ordering {
        other.at.cmp(&self.at).then(other.order.cmp(&self.order))
    }
}

/// One thread that runs each action when its time has come. The thread ends when the SystemTimers value is dropped.
pub struct SystemTimers {
    tx: Mutex<Sender<Due>>,
    order: Mutex<u64>,
}

impl SystemTimers {
    pub fn new() -> SystemTimers {
        let (tx, rx) = channel::<Due>();
        std::thread::spawn(move || {
            let mut heap: BinaryHeap<Due> = BinaryHeap::new();
            loop {
                let wait = heap.peek().map(|d| d.at.saturating_duration_since(Instant::now()));
                let got = match wait {
                    Some(w) => rx.recv_timeout(w),
                    None => rx.recv().map_err(|_| RecvTimeoutError::Disconnected),
                };
                match got {
                    Ok(due) => heap.push(due),
                    Err(RecvTimeoutError::Disconnected) => return,
                    Err(RecvTimeoutError::Timeout) => {}
                }
                while heap.peek().map(|d| d.at <= Instant::now()).unwrap_or(false) {
                    if let Some(due) = heap.pop() {
                        (due.action)();
                    }
                }
            }
        });
        SystemTimers { tx: Mutex::new(tx), order: Mutex::new(0) }
    }
}

impl Default for SystemTimers {
    fn default() -> SystemTimers {
        SystemTimers::new()
    }
}

impl Timers for SystemTimers {
    fn after(&self, milliseconds: u64, _purpose: TimerPurpose, action: TimerAction) {
        let order = {
            let mut n = self.order.lock().unwrap();
            *n += 1;
            *n
        };
        let _ = self.tx.lock().unwrap().send(Due { at: Instant::now() + Duration::from_millis(milliseconds), order, action });
    }
}

/// The system's secure random source, through OpenSSL: seven bytes a draw (design 3.5), so the bias of a draw taken
/// modulo at most 256 candidates is below 2^-47.
pub struct SecureRandom;

impl RandomSource for SecureRandom {
    fn draws(&self, count: usize) -> Option<Vec<i64>> {
        let raw = random_bytes(7 * count).ok()?;
        Some(raw.chunks(7).map(|c| c.iter().fold(0i64, |acc, b| (acc << 8) | *b as i64)).collect())
    }

    fn nonce(&self) -> Option<Vec<u8>> {
        random_bytes(32).ok()
    }
}
