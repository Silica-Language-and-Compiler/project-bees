//! The listening position (design 16.1; writing-a-tempus-client.md section 9): a node that learned of this client
//! through gossip dials the address the client advertises. The same admission runs, then ONE request is read and
//! answered.
use crate::admission::{Identity, Outcome, Verifier};
use crate::client::{admit, check_entries, end, end_read, tls_checks, State};
use crate::frames::{self, frame, read_any, Descriptor, Entry, Frame};
use crate::tls::{Conn, ReadResult, TlsContext};
use crate::Fault;
use std::collections::BTreeMap;
use std::net::{TcpListener, TcpStream};
use std::sync::{Arc, Condvar, Mutex};
use std::thread;
use std::time::{Duration, Instant};

/// What a Listener's handler is given: the request as read, its bytes, the admitted peer's descriptor and token type,
/// and the number of the connection (0 for the first accepted).
pub struct Request {
    pub frame: Frame,
    pub body: Vec<u8>,
    pub advert: Descriptor,
    pub typ: String,
    pub index: usize,
}

/// What a handler answers: a reply body, or a close with no reply.
pub enum Answer {
    Reply(Vec<u8>),
    Close,
}

/// The answer of writing-a-tempus-client.md section 9: a shuffle with a shuffle_reply for the same store, a sample
/// with a sample_reply for the same store (at most the `n` asked for), anything else with a close and no reply.
/// `entries` gives what this client holds for a store.
pub fn standard_answer(request: &Request, entries: &dyn Fn(&str) -> Vec<Entry>) -> Answer {
    let body = match &request.frame {
        Frame::Shuffle { store, .. } => frames::shuffle_reply(store, &entries(store)),
        Frame::Sample { store, n } => {
            let held = entries(store);
            frames::sample_reply(store, &held[..held.len().min(*n as usize)])
        }
        _ => return Answer::Close,
    };
    body.map(Answer::Reply).unwrap_or(Answer::Close)
}

pub type Handler = dyn Fn(&Request) -> Answer + Send + Sync;
pub type OnOutcome = dyn Fn(usize, &Outcome) + Send + Sync;

/// What a Listener takes beside the identity and the verifier. Nothing has a default.
pub struct ListenOptions {
    pub host: String,
    /// 0: the system picks a port, and `address()` says which.
    pub port: u16,
    /// One bound for each whole connection.
    pub timeout: Duration,
    pub shuffle_length: usize,
    pub verify_entries: bool,
    /// A fixed challenge nonce per connection number, for a test; None takes each from the secure random source.
    pub nonce: Option<Box<dyn Fn(usize) -> Vec<u8> + Send + Sync>>,
    /// Called with each connection's outcome, in accept order.
    pub on_outcome: Option<Box<OnOutcome>>,
}

struct Shared {
    done: BTreeMap<usize, Outcome>,
    reported: usize,
    stopping: bool,
    running: usize,
    accepting: bool,
}

struct Inner {
    identity: Identity,
    verifier: Verifier,
    handler: Box<Handler>,
    options: ListenOptions,
    context: TlsContext,
    address: String,
    shared: Mutex<Shared>,
    changed: Condvar,
}

/// A thread accepts connections, and each connection, in its own thread, is admitted, has ONE request read, and is
/// answered by the handler. Every connection ends as one Outcome, kept in accept order. Any self-signed Ed25519
/// certificate passes the handshake, and admission decides.
pub struct Listener {
    inner: Arc<Inner>,
    socket: Option<TcpListener>,
}

impl Listener {
    pub fn new(identity: Identity, verifier: Verifier, options: ListenOptions, handler: Box<Handler>) -> Result<Listener, Fault> {
        let context = TlsContext::new(true, &identity.key, &identity.cert_der, "ed25519", true, false)?;
        let socket = TcpListener::bind((options.host.as_str(), options.port))
            .map_err(|e| Fault(format!("cannot listen on {}:{} ({})", options.host, options.port, e)))?;
        let port = socket.local_addr().map(|a| a.port()).unwrap_or(options.port);
        let address = format!("{}:{}", options.host, port);
        socket.set_nonblocking(true).map_err(|_| Fault::new("the listener could not be set up"))?;
        let shared = Shared { done: BTreeMap::new(), reported: 0, stopping: false, running: 0, accepting: false };
        Ok(Listener { inner: Arc::new(Inner { identity, verifier, handler, options, context, address, shared: Mutex::new(shared),
                                              changed: Condvar::new() }), socket: Some(socket) })
    }

    /// The address listened on, "host:port".
    pub fn address(&self) -> &str {
        &self.inner.address
    }

    /// Begins accepting. Call it once.
    pub fn start(&mut self) {
        let socket = match self.socket.take() {
            Some(s) => s,
            None => return,
        };
        self.inner.shared.lock().unwrap().accepting = true;
        let inner = self.inner.clone();
        thread::spawn(move || accept_loop(inner, socket));
    }

    /// Stops accepting and waits for the connections in hand to end (each is bounded by the timeout).
    pub fn stop(&self) {
        let mut s = self.inner.shared.lock().unwrap();
        s.stopping = true;
        while s.accepting || s.running > 0 {
            s = self.inner.changed.wait(s).unwrap();
        }
    }

    /// The Outcomes of the first `count` connections in accept order, waiting up to `wait` for them (fewer when they
    /// did not all end in time).
    pub fn outcomes(&self, count: usize, wait: Duration) -> Vec<Outcome> {
        let until = Instant::now() + wait;
        let mut s = self.inner.shared.lock().unwrap();
        while !(0..count).all(|i| s.done.contains_key(&i)) {
            let left = until.saturating_duration_since(Instant::now());
            if left.is_zero() {
                break;
            }
            s = self.inner.changed.wait_timeout(s, left).unwrap().0;
        }
        (0..count).filter_map(|i| s.done.get(&i).cloned()).collect()
    }
}

fn accept_loop(inner: Arc<Inner>, socket: TcpListener) {
    let mut index = 0;
    loop {
        if inner.shared.lock().unwrap().stopping {
            break;
        }
        let stream = match socket.accept() {
            Ok((stream, _)) => stream,
            Err(_) => {
                thread::sleep(Duration::from_millis(20));
                continue;
            }
        };
        let i = index;
        index += 1;
        inner.shared.lock().unwrap().running += 1;
        let conn_inner = inner.clone();
        thread::spawn(move || {
            let out = serve(&conn_inner, stream, i);
            let mut s = conn_inner.shared.lock().unwrap();
            s.done.insert(i, out);
            s.running -= 1;
            // called with the lock held, so that the lines of two connections cannot change places
            while let Some(next) = s.done.get(&s.reported) {
                if let Some(f) = &conn_inner.options.on_outcome {
                    f(s.reported, next);
                }
                s.reported += 1;
            }
            conn_inner.changed.notify_all();
        });
    }
    drop(socket);
    let mut s = inner.shared.lock().unwrap();
    s.accepting = false;
    inner.changed.notify_all();
}

fn serve(inner: &Inner, stream: TcpStream, index: usize) -> Outcome {
    let deadline = Instant::now() + inner.options.timeout;
    let mut state = State::default();
    let mut conn = match Conn::new(&inner.context, stream, true, deadline) {
        Ok(c) => c,
        Err(e) => return Outcome::new("tls_failed", "tls", &e.0),
    };
    if let Some(failed) = conn.handshake() {
        conn.close();
        return match failed {
            ReadResult::Timeout => Outcome::new("timeout", "tls", ""),
            ReadResult::TlsFailed(why) => Outcome::new("tls_failed", "tls", &why),
            _ => Outcome::new("tls_failed", "tls", "closed during the handshake"),
        };
    }
    let cert_der = match tls_checks(&conn) {
        Ok(der) => der,
        Err(why) => return end(&mut conn, "refused", "tls", &state, &why.0),
    };
    let addr = inner.identity.addr.clone().unwrap_or_else(|| inner.address.clone());
    let nonce = inner.options.nonce.as_ref().map(|f| f(index));
    if let Err(out) = admit(&mut conn, &inner.identity, Some(&addr), &inner.verifier, nonce, &cert_der, &mut state,
                            inner.options.shuffle_length) {
        return out;
    }
    let body = match conn.read() {
        ReadResult::Frame(body) => body,
        other => return end_read(&mut conn, other, "request", &state),
    };
    let judged = read_any(&body, inner.options.shuffle_length).and_then(|f| {
        if inner.options.verify_entries {
            check_entries(&f, &inner.verifier)?;
        }
        Ok(f)
    });
    let f = match judged {
        Ok(f) => f,
        Err(why) => {
            let mut out = end(&mut conn, "refused", "request", &state, &why.0);
            out.body = body;
            return out;
        }
    };
    let advert = match state.advert.clone() {
        Some(d) => d,
        None => return end(&mut conn, "closed", "request", &state, "internal error"),
    };
    let request = Request { frame: f, body, advert, typ: state.typ.clone(), index };
    let sent = match (inner.handler)(&request) {
        Answer::Reply(reply) => {
            if let Ok(b) = frame(&reply) {
                conn.send(&b);
            }
            "reply"
        }
        Answer::Close => "close",
    };
    let mut out = end(&mut conn, "served", "done", &state, "");
    out.frame = Some(request.frame);
    out.body = request.body;
    out.sent = sent.to_string();
    out
}
