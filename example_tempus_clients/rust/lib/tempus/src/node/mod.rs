//! A TEMPUS node (development-plan/tempus-design.md sections 3 to 6 and 8 to 11): it listens, joins through its
//! sentinels, serves admitted peers and ticks its three stores. What it does, and the lines it writes, follow the BEES
//! node of src/tempus/bees_tempus_node.part.
//!
//! Who owns what. Everything that changes (the three stores, the clock state, the token, the producer key, the counts,
//! the join) is owned by one thread, the node's thread. Everything else reaches it by sending a message over one
//! channel: a timer that fell due, an accepted connection, the outcome of a dialed connection, the request of an
//! admitted peer (which carries a channel for the answer), a call of the application. Nothing else reads or writes
//! that state. A connection runs on a thread of its own with a copy of the values it needs, taken when it was dialed
//! or accepted (conn.rs). There is no async runtime.
pub mod admit;
pub mod clock;
pub mod config;
mod conn;
pub mod sources;
pub mod view;

use self::clock::{clock_turn, ClockChoices, ClockSay, ClockState};
use self::config::{dialable, identity_refusal, ConfigRefused, NodeIdentity, PeerType, TempusConfig};
use self::conn::{ConnValues, DialOutcome, NodeConn};
use self::sources::{Sources, TimerPurpose};
use self::view::{Store, TickStep, ViewEntry};
use crate::crypto::{certificate_key, hex, sha512, SigningKey};
use crate::frames::{self, read_token, Descriptor, Entry, Frame};
use crate::tls::TlsContext;
use std::collections::{HashMap, HashSet};
use std::net::{TcpListener, TcpStream};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{channel, Receiver, Sender};
use std::sync::{Arc, Mutex};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

/// What the application is told. Each event is given on the node's thread, in order with the node's own lines: the
/// function that receives it must return quickly and must not wait for the node.
#[derive(Debug, Clone)]
pub enum NodeEvent {
    /// The first reading of the clock succeeded and the node listens.
    Listening { address: String },
    /// The view of one store after a step that may have changed it.
    View { store: PeerType, entries: Vec<ViewEntry<Descriptor>> },
    /// The join through the sentinels is complete.
    Joined,
    /// The node's own token is not valid any more and ticking has stopped, until replace_token.
    OwnTokenNotValid { reason: String },
    /// A peer answered this node's advert with key_rotated, naming the kid it takes as current. `dialed` says whether
    /// this node dialed that peer. The application must get a new token.
    KeyRotated { kid: Vec<u8>, dialed: bool },
    /// The clock could not be read; the text says what that means for the node. Told once per failure.
    ClockNotRead(String),
    /// The clock went back by more than clock_back_limit_s under clock_back stop: the node has stopped for good.
    Stopped(String),
    /// An accepted peer was refused. `peer_id` is the SHA-512 of the key of its TLS certificate, never the id an
    /// advert claims; `token_verified` says whether the producer's signature on its token had verified. A node that
    /// is not a bridge keeps no score: this is for the application's own records.
    PeerRefused { event: String, peer_id: Vec<u8>, token_verified: bool },
    /// The node could not listen on its address.
    ListenFailed(String),
}

pub type Lines = Arc<dyn Fn(&str) + Send + Sync>;
pub type Events = Box<dyn Fn(NodeEvent) + Send>;

pub(crate) enum Answer {
    Reply(Vec<u8>),
    Close,
}

#[derive(Clone, Copy)]
pub(crate) enum TimerEvent {
    Tick(PeerType),
    JoinRetry(PeerType),
    ClockRead,
}

pub(crate) enum Msg {
    Start,
    Timer(TimerEvent),
    Accepted(TcpStream),
    /// An accepted connection that was counted as served has ended.
    ConnEnded,
    Dialed(usize, DialOutcome),
    /// The one request of an admitted peer on an accepted connection (None: a call or a cast).
    Request { frame: Option<Frame>, peer: Descriptor, typ: String, cid: usize, reply: Sender<Answer> },
    Report(NodeEvent),
    ReplaceToken(Vec<u8>),
    ReplaceKey(Vec<u8>, Vec<u8>),
    Peers { store: PeerType, count: i64, reply: Sender<Vec<Descriptor>> },
    Stop,
}

/// What every thread of a node may read: nothing in it changes after the node was made.
pub(crate) struct Shared {
    pub(crate) config: TempusConfig,
    pub(crate) sources: Sources,
    pub(crate) key: SigningKey,
    pub(crate) server_context: TlsContext,
    pub(crate) client_context: TlsContext,
    /// The SHA-512 of each whitelisted certificate's DER, in the order given.
    pub(crate) whitelist: Vec<Vec<u8>>,
    lines: Lines,
    line_lock: Mutex<()>,
    ended: AtomicBool,
}

impl Shared {
    /// One line of the node, its own or an audit line: one at a time, from any thread.
    pub(crate) fn say(&self, line: &str) {
        let _guard = self.line_lock.lock().unwrap();
        (self.lines)(line);
    }
}

/// The handle an application holds. The node itself lives on its own thread.
pub struct TempusNode {
    tx: Sender<Msg>,
    shared: Arc<Shared>,
    thread: Mutex<Option<JoinHandle<()>>>,
    peer_id: Vec<u8>,
    public_key: Vec<u8>,
}

impl TempusNode {
    /// A node that reads the machine's clock, runs its own timers and draws from the system's secure random source.
    /// `lines` is given every line the node writes (its own and the audit lines), one call per line, from any thread,
    /// one at a time. `events` is given what the application is told. Returns ConfigRefused, after writing the line
    /// `tempus: boot refused: WHY`, when the configuration or the identity refuses the start. Nothing runs before start().
    pub fn new(config: TempusConfig, identity: NodeIdentity, lines: Lines, events: Events) -> Result<TempusNode, ConfigRefused> {
        TempusNode::make(config, identity, None, lines, events)
    }

    /// A node whose clock, timers and random numbers are the caller's: for tests. It is refused on a listen address
    /// that is not loopback.
    pub fn with_sources(config: TempusConfig, identity: NodeIdentity, sources: Sources, lines: Lines, events: Events) -> Result<TempusNode, ConfigRefused> {
        TempusNode::make(config, identity, Some(sources), lines, events)
    }

    fn make(config: TempusConfig, identity: NodeIdentity, given: Option<Sources>, lines: Lines, events: Events) -> Result<TempusNode, ConfigRefused> {
        let refuse = |why: &str| -> ConfigRefused {
            lines(&format!("tempus: boot refused: {}", why));
            ConfigRefused(why.to_string())
        };
        if given.is_some() && !config.listens_on_loopback() {
            return Err(refuse("an externally driven node on a listen address that is not loopback"));
        }
        if let Some(why) = config.refusal() {
            return Err(refuse(&why));
        }
        let key = match SigningKey::from_seed(&identity.seed) {
            Ok(k) => k,
            Err(_) => return Err(refuse("the identity is not a 32-byte seed")),
        };
        if let Some(why) = identity_refusal(config.role, key.public(), &identity.token) {
            return Err(refuse(&why));
        }
        if certificate_key(&identity.certificate_der).ok().as_deref() != Some(key.public()) {
            return Err(refuse("the identity certificate is not a certificate self-signed over the identity key"));
        }
        if !dialable(identity.address.as_bytes()) {
            return Err(refuse("the node's address is not a dotted quad, a colon and a port"));
        }
        if config.whitelist.iter().any(|der| certificate_key(der).is_err()) {
            return Err(refuse("a certificate of the tempus whitelist is not a certificate self-signed over an Ed25519 key"));
        }
        // a node also lets a P-256 certificate through the handshake, to refuse it afterwards as a Silica node does
        let both = "ed25519:ecdsa_secp256r1_sha256";
        let contexts = TlsContext::new(true, &key, &identity.certificate_der, both, true, true)
            .and_then(|s| TlsContext::new(false, &key, &identity.certificate_der, both, true, false).map(|c| (s, c)));
        let (server_context, client_context) = match contexts {
            Ok(x) => x,
            Err(_) => return Err(refuse("this node's TEMPUS certificate or key could not be loaded")),
        };
        let public_key = key.public().to_vec();
        let peer_id = sha512(&public_key);
        let whitelist = config.whitelist.iter().map(|der| sha512(der)).collect();
        let shared = Arc::new(Shared { config: config.clone(), sources: given.unwrap_or_else(Sources::system), key, server_context,
                                       client_context, whitelist, lines, line_lock: Mutex::new(()), ended: AtomicBool::new(false) });
        let d = Descriptor { id: peer_id.clone(), public_key: public_key.clone(), addr: identity.address.as_bytes().to_vec(), token: identity.token.clone() };
        let stores = PeerType::ALL.map(|t| {
            let s = config.store(t);
            Store::new(peer_id.clone(), d.clone(), t == config.role, s.capacity, s.shuffle_length)
        });
        let (tx, rx) = channel();
        let core = Core { shared: shared.clone(), tx: tx.clone(), events, peer_id: peer_id.clone(), public_key: public_key.clone(),
                          address: identity.address.clone(), skew: config.clock_skew_ms / 1000, token: identity.token, kid: config.producer_kid.clone(),
                          producer_key: config.producer_key.clone(), stores, now: 0, ck: ClockState::None, live: 0, accepted: 0, dialed_count: 0,
                          own_token_told: false, join: Join::NotBegun, join_delay: config.join_retry_initial_ms, join_pending: HashSet::new(),
                          dials: HashMap::new() };
        let thread = thread::spawn(move || core.run(rx));
        Ok(TempusNode { tx, shared, thread: Mutex::new(Some(thread)), peer_id, public_key })
    }

    /// The node's peer id, the SHA-512 of its public key.
    pub fn peer_id(&self) -> &[u8] {
        &self.peer_id
    }

    pub fn public_key(&self) -> &[u8] {
        &self.public_key
    }

    /// Begins: the clock is read, and at the first reading the node listens and joins. Call it once.
    pub fn start(&self) {
        let _ = self.tx.send(Msg::Start);
    }

    /// Ends the node: it stops listening, its timers do nothing more, and connections in hand end by themselves
    /// within shuffle_timeout_ms. A node that has ended is not started again: make a new one.
    pub fn stop(&self) {
        self.shared.ended.store(true, Ordering::SeqCst);
        let _ = self.tx.send(Msg::Stop);
        if let Some(t) = self.thread.lock().unwrap().take() {
            let _ = t.join();
        }
    }

    /// A new token from the producer (design section 6): the node's own entry carries it from the next shuffle on,
    /// and a node that had stopped ticking for its expired token ticks again.
    pub fn replace_token(&self, token: Vec<u8>) {
        let _ = self.tx.send(Msg::ReplaceToken(token));
    }

    /// A new current producer key (ruling NQ-5).
    pub fn replace_producer_key(&self, kid: Vec<u8>, public_key: Vec<u8>) {
        let _ = self.tx.send(Msg::ReplaceKey(kid, public_key));
    }

    /// Up to `count` peers of one store, drawn at random (how an application finds a bridge, design 17.3). Empty when
    /// the store is empty, no random numbers can be had, or the node has ended. It waits for the node's thread: do
    /// not call it from the function that receives the node's events.
    pub fn peers(&self, store: PeerType, count: i64) -> Vec<Descriptor> {
        let (reply, answer) = channel();
        if self.tx.send(Msg::Peers { store, count, reply }).is_err() {
            return Vec::new();
        }
        answer.recv().unwrap_or_default()
    }
}

impl Drop for TempusNode {
    fn drop(&mut self) {
        self.stop();
    }
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum Join {
    NotBegun,
    /// The store being asked for.
    Asking(PeerType),
    Done,
    /// The request for this store waits until the clock is read again.
    Waiting(PeerType),
}

enum Dial {
    Shuffle(PeerType),
    Join(PeerType, usize),
}

/// The node's state. Owned by the node's thread.
struct Core {
    shared: Arc<Shared>,
    tx: Sender<Msg>,
    events: Events,
    peer_id: Vec<u8>,
    public_key: Vec<u8>,
    address: String,
    skew: i64,
    token: Vec<u8>,
    kid: Vec<u8>,
    producer_key: Vec<u8>,
    stores: [Store<Descriptor>; 3],
    now: i64,
    ck: ClockState,
    live: i64,
    accepted: usize,
    dialed_count: usize,
    own_token_told: bool,
    join: Join,
    join_delay: i64,
    join_pending: HashSet<PeerType>,
    dials: HashMap<usize, Dial>,
}

fn id8(id: &[u8]) -> String {
    hex(&id[..id.len().min(4)])
}

fn to_view(entries: &[Entry]) -> Vec<ViewEntry<Descriptor>> {
    entries.iter().map(|e| ViewEntry { id: e.d.id.clone(), d: e.d.clone(), age: e.age }).collect()
}

fn to_entries(view: &[ViewEntry<Descriptor>]) -> Vec<Entry> {
    view.iter().map(|e| Entry { age: e.age, d: e.d.clone() }).collect()
}

impl Core {
    fn run(mut self, rx: Receiver<Msg>) {
        while let Ok(msg) = rx.recv() {
            match msg {
                Msg::Start => {
                    for t in PeerType::ALL {
                        self.arm(t);
                    }
                    self.read_clock();
                }
                Msg::Timer(TimerEvent::Tick(st)) => {
                    self.arm(st);
                    self.tick(st);
                }
                Msg::Timer(TimerEvent::JoinRetry(st)) => {
                    if self.ck != ClockState::Stopped {
                        self.join(st, 1);
                    }
                }
                Msg::Timer(TimerEvent::ClockRead) => self.read_clock(),
                Msg::Accepted(stream) => self.accepted_connection(stream),
                Msg::ConnEnded => self.live -= 1,
                Msg::Dialed(cid, out) => self.dialed(cid, out),
                Msg::Request { frame, peer, typ, cid, reply } => {
                    let answer = self.request(frame, &peer, &typ, cid);
                    let _ = reply.send(answer);
                }
                Msg::Report(e) => self.tell(e),
                Msg::ReplaceToken(token) => {
                    self.token = token;
                    self.own_token_told = false;
                    self.say("own token replaced");
                    let d = self.own_descriptor();
                    for s in self.stores.iter_mut() {
                        s.me.d = d.clone();
                    }
                }
                Msg::ReplaceKey(kid, key) => {
                    self.say(&format!("producer key replaced, kid {}", String::from_utf8_lossy(&kid)));
                    self.kid = kid;
                    self.producer_key = key;
                }
                Msg::Peers { store, count, reply } => {
                    let draws = self.draws(store);
                    let got = self.stores[store.index()].sample(count, draws.as_deref()).unwrap_or_default();
                    let _ = reply.send(got.into_iter().map(|e| e.d).collect());
                }
                Msg::Stop => break,
            }
        }
    }

    // ---------------------------------------------------------------- lines and events
    fn say(&self, line: &str) {
        self.shared.say(line);
    }

    fn tell(&self, e: NodeEvent) {
        (self.events)(e);
    }

    fn own_descriptor(&self) -> Descriptor {
        Descriptor { id: self.peer_id.clone(), public_key: self.public_key.clone(), addr: self.address.as_bytes().to_vec(), token: self.token.clone() }
    }

    fn count(&self, t: PeerType) -> i64 {
        self.shared.config.store(t).shuffle_length
    }

    fn max_count(&self) -> i64 {
        PeerType::ALL.iter().map(|t| self.count(*t)).max().unwrap_or(0)
    }

    /// One set of draws for one tick or one answer: one more than the shuffle length (design 3.5).
    fn draws(&self, t: PeerType) -> Option<Vec<i64>> {
        self.shared.sources.random.draws(self.count(t) as usize + 1)
    }

    fn show_view(&self, t: PeerType) {
        self.tell(NodeEvent::View { store: t, entries: self.stores[t.index()].view.clone() });
    }

    fn after(&self, ms: i64, purpose: TimerPurpose, event: TimerEvent) {
        let (tx, shared) = (self.tx.clone(), self.shared.clone());
        self.shared.sources.timers.after(ms.max(0) as u64, purpose, Box::new(move || {
            if !shared.ended.load(Ordering::SeqCst) {
                let _ = tx.send(Msg::Timer(event));
            }
        }));
    }

    /// The values a connection works with: a copy, taken now.
    fn snapshot(&self, cid: usize, dialed: bool, count: i64) -> ConnValues {
        ConnValues { cid, dialed, advert: frames::advert(&self.own_descriptor()).unwrap_or_default(), token: self.token.clone(),
                     kid: self.kid.clone(), producer_key: self.producer_key.clone(), now: self.now, skew: self.skew, count: count.max(0) as usize,
                     deadline: Instant::now() + Duration::from_millis(self.shared.config.shuffle_timeout_ms.max(0) as u64) }
    }

    // ---------------------------------------------------------------- the clock (design section 10)
    fn read_clock(&mut self) {
        let n = self.shared.sources.clock.seconds();
        self.reading(n);
        self.after(self.shared.config.clock_read_ms, TimerPurpose::ClockRead, TimerEvent::ClockRead);
    }

    fn reading(&mut self, n: Option<i64>) {
        let config = &self.shared.config;
        let limit = config.clock_back_limit_s.unwrap_or(0);
        let t = clock_turn(self.ck, self.now, n, ClockChoices { back: config.clock_back, limit, fail: config.clock_fail });
        let back = format!("the system clock went back by {} s", self.now - n.unwrap_or(0));
        if t.again {
            self.say("clock: the system clock is read again");
        }
        let not_read = |me: &Core, text: &str| {
            me.say(&format!("clock: {}", text));
            me.tell(NodeEvent::ClockNotRead(text.to_string()));
        };
        match t.say {
            ClockSay::Nothing => {}
            ClockSay::First => self.say("clock: the system clock is read"),
            ClockSay::NoTimeAtStart => not_read(self, "the system clock could not be read: the node has not started"),
            ClockSay::NoTimePause => not_read(self, "the system clock could not be read: the node admits no connection and does not tick until it is read again"),
            ClockSay::NoTimeContinue => not_read(self, "the system clock could not be read: the node goes on with its last reading"),
            ClockSay::Followed => self.say(&format!("clock: {}; the node follows it", back)),
            ClockSay::HoldBegins => self.say(&format!("clock: {}; the node holds its time until the system clock has reached it", back)),
            ClockSay::HoldEnds => self.say("clock: the system clock has reached the held time; the node follows it again"),
            ClockSay::Stop => {
                let text = format!("{}, more than clock_back_limit_s {}: the node has stopped; it admits no connection and does not tick until its application starts it again", back, limit);
                self.say(&format!("clock: {}", text));
                self.tell(NodeEvent::Stopped(text));
            }
        }
        self.now = t.now;
        self.ck = t.ck;
        if t.say == ClockSay::First {
            self.listen();
        }
        // the join request that waited for the clock is made at once when the clock is read again (ruling 1.d)
        if t.again {
            if let Join::Waiting(st) = self.join {
                self.join = Join::Asking(st);
                self.join(st, 1);
            }
        }
    }

    // ---------------------------------------------------------------- listening
    fn listen(&mut self) {
        let config = self.shared.config.clone();
        // IPv4 only: the name localhost is the address 127.0.0.1 here, never an IPv6 address
        let host = if config.listen_address == "localhost" { "127.0.0.1" } else { config.listen_address.as_str() };
        let bound = TcpListener::bind((host, config.port as u16)).and_then(|l| l.set_nonblocking(true).map(|_| l));
        let listener = match bound {
            Ok(l) => l,
            Err(e) => {
                self.say("the listening link has gone down");
                self.tell(NodeEvent::ListenFailed(format!("cannot listen on {}:{} ({})", config.listen_address, config.port, e)));
                return;
            }
        };
        self.say(&format!("{} node {} listening on {}", config.role.name(), id8(&self.peer_id), self.address));
        for t in PeerType::ALL {
            self.say(&format!("store {}: capacity {}, shuffle length {}", t.name(), config.store(t).capacity, self.count(t)));
        }
        self.tell(NodeEvent::Listening { address: self.address.clone() });
        let (tx, shared) = (self.tx.clone(), self.shared.clone());
        thread::spawn(move || {
            while !shared.ended.load(Ordering::SeqCst) {
                match listener.accept() {
                    Ok((stream, _)) => {
                        if tx.send(Msg::Accepted(stream)).is_err() {
                            break;
                        }
                    }
                    Err(_) => thread::sleep(Duration::from_millis(10)),
                }
            }
        });
        if config.sentinels.is_empty() {
            self.say("join: no sentinel is configured");
            self.join = Join::Done;
        } else {
            self.join = Join::Asking(PeerType::Edge);
            self.join_delay = config.join_retry_initial_ms;
            self.join(PeerType::Edge, 1);
        }
    }

    fn accepted_connection(&mut self, stream: TcpStream) {
        self.accepted += 1;
        // an accepted connection is closed at once, after its handshake, while the clock cannot be read (clock_fail
        // pause), after the node stopped (clock_back stop), and beyond inflight_max
        let close_with = self.ck.closes_with().or(if self.live >= self.shared.config.inflight_max { Some("inflight_refused") } else { None });
        if close_with.is_none() {
            self.live += 1;
        }
        let v = self.snapshot(self.accepted, false, self.max_count());
        // the connection is made on its own thread: an OpenSSL connection object stays on the thread that made it
        let (shared, tx) = (self.shared.clone(), self.tx.clone());
        thread::spawn(move || NodeConn::new(shared, tx, v).accepted(stream, close_with));
    }

    // ---------------------------------------------------------------- the join (design section 6)
    /// `x`: twice the index of the sentinel asked, plus 1 when the request is part of the join (and not the asking
    /// again after a tick found a store empty).
    fn join(&mut self, st: PeerType, x: usize) {
        if self.ck == ClockState::Paused {
            self.say(&format!("join: the request for {} waits until the system clock is read again", st.name()));
            self.join = Join::Waiting(st);
            return;
        }
        if self.ck == ClockState::Stopped {
            return;
        }
        self.dialed_count += 1;
        let cid = self.dialed_count;
        let s = &self.shared.config.sentinels[x / 2];
        let addr = format!("{}:{}", s.host, s.port);
        self.say(&format!("join: asking the sentinel at {} for {} d{}", addr, st.name(), cid));
        self.dials.insert(cid, Dial::Join(st, x));
        self.join_pending.insert(st);
        let body = frames::sample(st.name(), self.count(st)).unwrap_or_default();
        self.dial(cid, addr, body, self.count(st));
    }

    fn join_goes_on(&mut self, st: PeerType, x: usize) {
        if x % 2 != 1 {
            return;
        }
        self.join_delay = self.shared.config.join_retry_initial_ms;
        if st.index() < 2 {
            let next = PeerType::ALL[st.index() + 1];
            self.join = Join::Asking(next);
            self.join(next, 1);
        } else {
            self.say("join: done");
            self.join = Join::Done;
            self.tell(NodeEvent::Joined);
        }
    }

    fn join_failed(&mut self, st: PeerType, x: usize) {
        if x / 2 + 1 < self.shared.config.sentinels.len() {
            self.join(st, x + 2);
        } else if x % 2 == 1 {
            self.say(&format!("join: no sentinel answered for {}; waiting to try again", st.name()));
            self.after(self.join_delay, TimerPurpose::JoinRetry, TimerEvent::JoinRetry(st));
            self.join = Join::Asking(st);
            self.join_delay = (self.join_delay * 2).min(self.shared.config.join_retry_max_ms);
        } else {
            self.say(&format!("join: no sentinel answered for {}", st.name()));
        }
    }

    // ---------------------------------------------------------------- ticks (design 3.2)
    fn arm(&self, st: PeerType) {
        self.after(self.shared.config.store(st).tick_ms, TimerPurpose::Tick(st), TimerEvent::Tick(st));
    }

    fn tick(&mut self, st: PeerType) {
        // no tick before the first reading, while the node waits for its clock, or after it stopped
        if !self.ck.ticks() {
            return;
        }
        let own = admit::pre(&self.own_descriptor(), &self.kid, self.now, self.skew, None).why;
        if !own.is_empty() {
            if !self.own_token_told {
                self.say(&format!("own token: {}; ticking has stopped", own));
                self.tell(NodeEvent::OwnTokenNotValid { reason: own });
            }
            self.own_token_told = true;
            return;
        }
        // entries whose token has expired leave the view first (ruling OQ-4)
        let (now, skew) = (self.now, self.skew);
        let gone: Vec<Vec<u8>> = self.stores[st.index()].view.iter()
            .filter(|e| now >= read_token(&e.d.token).map(|t| t.fields.exp).unwrap_or(0) + skew).map(|e| e.id.clone()).collect();
        for id in &gone {
            self.stores[st.index()].drop_peer(id);
        }
        if !gone.is_empty() {
            self.say(&format!("expired in {}:{}", st.name(), gone.iter().map(|id| format!(" {}", id8(id))).collect::<String>()));
        }
        let draws = self.draws(st);
        let step = self.stores[st.index()].tick(draws.as_deref());
        self.show_view(st);
        let head = format!("tick {}: ", st.name());
        match step {
            TickStep::Skipped => self.say(&format!("{}skipped (no draws)", head)),
            TickStep::Aged => self.say(&format!("{}aged only (a shuffle is in flight)", head)),
            TickStep::Empty => {
                self.say(&format!("{}the view is empty", head));
                // an empty view: the node asks a sentinel again (design section 10)
                if self.join == Join::Done && !self.join_pending.contains(&st) && !self.shared.config.sentinels.is_empty() {
                    self.join(st, 0);
                }
            }
            TickStep::Shuffle { partner, out } => {
                let with = format!("{}shuffle with {}", head, id8(&partner.id));
                let body = frames::shuffle(st.name(), &to_entries(&out));
                match body {
                    Ok(body) if dialable(&partner.d.addr) => {
                        self.dialed_count += 1;
                        let cid = self.dialed_count;
                        let addr = String::from_utf8_lossy(&partner.d.addr).into_owned();
                        self.say(&format!("{} at {} d{}", with, addr, cid));
                        self.dials.insert(cid, Dial::Shuffle(st));
                        self.dial(cid, addr, body, self.count(st));
                    }
                    _ => {
                        self.say(&format!("{}: its address is not one this build dials", with));
                        self.shuffle_failed(st);
                    }
                }
            }
        }
    }

    fn shuffle_failed(&mut self, st: PeerType) {
        self.stores[st.index()].failed();
        self.show_view(st);
        self.say(&format!("tick {}: shuffle failed", st.name()));
    }

    // ---------------------------------------------------------------- dialed connections
    fn dial(&self, cid: usize, addr: String, request: Vec<u8>, count: i64) {
        let (shared, tx, v) = (self.shared.clone(), self.tx.clone(), self.snapshot(cid, true, count));
        thread::spawn(move || {
            let out = NodeConn::new(shared, tx.clone(), v).dial(&addr, &request);
            let _ = tx.send(Msg::Dialed(cid, out));
        });
    }

    fn dialed(&mut self, cid: usize, out: DialOutcome) {
        let what = match self.dials.remove(&cid) {
            Some(w) => w,
            None => return,
        };
        let (reply, failure) = match out {
            DialOutcome::Reply(frame, peer, typ) => (Some((frame, peer, typ)), String::new()),
            DialOutcome::Failed(event) => (None, event),
            DialOutcome::KeyRotated(named) => {
                self.tell(NodeEvent::KeyRotated { kid: named, dialed: true });
                (None, "key_rotated".to_string())
            }
        };
        match what {
            Dial::Shuffle(st) => {
                let (frame, _, _) = match reply {
                    Some(r) => r,
                    None => {
                        self.say(&format!("tick {}: the partner did not answer, {} d{}", st.name(), failure, cid));
                        self.shuffle_failed(st);
                        return;
                    }
                };
                let merged = match frame {
                    Some(Frame::ShuffleReply { store, entries }) if store == st.name() && entries.len() as i64 <= self.count(st) =>
                        self.stores[st.index()].reply(&to_view(&entries)),
                    _ => false,
                };
                if !merged {
                    self.shuffle_failed(st);
                    return;
                }
                self.show_view(st);
                self.say(&format!("tick {}: shuffle merged", st.name()));
            }
            Dial::Join(st, x) => {
                self.join_pending.remove(&st);
                let (store, entries, peer, typ) = match reply {
                    Some((Some(Frame::SampleReply { store, entries }), peer, typ)) => (store, entries, peer, typ),
                    other => {
                        let why = if other.is_none() { failure } else { "a reply that is not a sample_reply".to_string() };
                        self.say(&format!("join: the sentinel did not answer for {}, {} d{}", st.name(), why, cid));
                        self.join_failed(st, x);
                        return;
                    }
                };
                self.say(&format!("join: the sentinel answered for {} d{}", st.name(), cid));
                if store == st.name() && entries.len() as i64 <= self.count(st) {
                    for e in to_view(&entries) {
                        self.stores[st.index()].insert(&e);
                    }
                }
                self.show_view(st);
                // the joiner keeps the sentinel it joined through (ruling NQ-12)
                if typ == PeerType::Sentinel.name() {
                    self.stores[PeerType::Sentinel.index()].insert(&ViewEntry { id: peer.id.clone(), d: peer, age: 0 });
                    self.show_view(PeerType::Sentinel);
                }
                self.join_goes_on(st, x);
            }
        }
    }

    // ---------------------------------------------------------------- what connections ask of the node
    fn audit(&self, event: &str, peer: &Descriptor, what: &str, cid: usize) {
        self.say(&format!("[tempus audit] {} peer={} {} a{}", event, hex(&peer.id[..8]), what, cid));
    }

    /// The one request of an admitted peer on an accepted connection.
    fn request(&mut self, frame: Option<Frame>, peer: &Descriptor, typ: &str, cid: usize) -> Answer {
        match frame {
            Some(Frame::Shuffle { store, entries }) => {
                let st = match PeerType::from_name(&store) {
                    Some(st) => st,
                    None => return Answer::Close,
                };
                let draws = if entries.len() as i64 <= self.count(st) { self.draws(st) } else { None };
                let out = self.stores[st.index()].request(&peer.id, &to_view(&entries), draws.as_deref());
                match out.and_then(|out| frames::shuffle_reply(&store, &to_entries(&out)).ok()) {
                    Some(body) => {
                        self.show_view(st);
                        Answer::Reply(body)
                    }
                    None => {
                        self.say(&format!("[tempus audit] shuffle_refused peer=- the store refused the frame a{}", cid));
                        Answer::Close
                    }
                }
            }
            Some(Frame::Sample { store, n }) => {
                let st = match PeerType::from_name(&store) {
                    Some(st) => st,
                    None => return Answer::Close,
                };
                if n > self.count(st) {
                    self.audit("protocol_error", peer, "n is not 1 to the shuffle length", cid);
                    return Answer::Close;
                }
                let draws = self.draws(st);
                let out = self.stores[st.index()].sample(n, draws.as_deref());
                // a sentinel inserts the peer that asks it into its store of the peer's type, after the sample was
                // taken (rulings OQ-6, NQ-13), so a joiner is never answered with itself
                if self.shared.config.role == PeerType::Sentinel {
                    if let Some(pt) = PeerType::from_name(typ) {
                        self.stores[pt.index()].insert(&ViewEntry { id: peer.id.clone(), d: peer.clone(), age: 0 });
                        self.show_view(pt);
                    }
                }
                match out.and_then(|out| frames::sample_reply(&store, &to_entries(&out)).ok()) {
                    Some(body) => Answer::Reply(body),
                    None => Answer::Close,
                }
            }
            _ => {
                self.audit("request_refused", peer, "call and cast are served by a bridge only", cid);
                Answer::Close
            }
        }
    }
}
