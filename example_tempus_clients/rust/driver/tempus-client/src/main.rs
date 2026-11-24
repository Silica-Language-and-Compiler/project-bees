// The command line of the Rust TEMPUS extension. A usable example, to be used carefully (README.md).
//
//   tempus-client gossip OPTIONS
//       Be a member of a TEMPUS network: a node of the library (tempus::node), whose role is the type its token
//       carries. It listens, joins through the sentinels, shuffles the three stores on their timers and answers the
//       peers that dial. Prints the node's own lines (with its audit lines) and, for every peer it comes to know,
//       `learned STORE ID16 HOST:PORT`. Runs until it is interrupted or ended, or for --run-ms; then prints, per store,
//       `known STORE: ID16 ...` (every peer it ever learned of, sorted). What a node requires and these options do not
//       carry (the bound on accepted connections and the clock choices) is stated in GOSSIP_* below.
//       OPTIONS, all required unless marked:
//         --cert FILE --key FILE         this peer's certificate (PEM, self-signed over its Ed25519 key) and its private
//                                        key (PEM, PKCS#8, not encrypted)
//         --token FILE                   its token from the producer, as hex digits in a file
//         --addr HOST:PORT               the address it advertises and listens on (HOST an IPv4 literal)
//         --producer-pub HEX --kid KID   the producer's current public key and its identifier
//         --skew SECONDS                 the clock difference this peer allows
//         --timeout-ms MS                the time bound of a whole connection
//         --store-edge CAP:LEN:TICK_MS --store-bridge CAP:LEN:TICK_MS --store-sentinel CAP:LEN:TICK_MS
//                                        capacity, shuffle length and tick of each store
//         --join-retry-ms FIRST:MAX      the join's first and greatest retry delay
//         --sentinel HOST:PORT           may be repeated (1 to 16); none for a first sentinel
//         --whitelist-cert PEM_FILE      optional, may be repeated: a bridge or sentinel this peer accepts (a sentinel
//                                        is admitted only when its certificate is one of these)
//         --now SECONDS                  optional: one fixed reading in place of the machine's clock (the node
//                                        accepts that on a loopback address only)
//         --run-ms MS                    optional: stop after that long
//       The gossip command uses the library alone, nothing of the TEST ONLY crate.
//
// The commands below were written for the trials of the client half. They take the key as a seed and can make TEST
// ONLY tokens and entries (testing/tempus-testing):
//
//   tempus-client read-hex HEX SHUFFLE_LENGTH
//   tempus-client test-token --seed HEX --kid KID TYP NBF EXP
//   tempus-client dial HOST:PORT IDENTITY CHECKS [--nonce HEX] REQUEST
//       REQUEST: sample STORE N | shuffle STORE | call MODULE FUNCTION [INTEGER...] | cast MODULE FUNCTION [INTEGER...]
//                | raw HEX
//       (`shuffle STORE` sends this client's own entry at age 0; `call` and `cast` use the request id "1".)
//   tempus-client listen HOST:PORT IDENTITY CHECKS [--test-entry STORE=AGE:FIRST:TYP:NBF:EXP:HOST:PORT ...]
//       Answers a sample or a shuffle for STORE with the entries given for it, and anything else with a close.
//       Prints "listening HOST:PORT", then one line per connection, in accept order. Ends when its standard input ends.
//   IDENTITY: --seed HEX --addr HOST:PORT (--token HEX | --test-token TYP:NBF:EXP) [--cert PEM_FILE]
//   CHECKS:   --producer-pub HEX --kid KID (--now SECONDS | --system-clock) --skew SECONDS --timeout SECONDS
//             --shuffle-length N [--whitelist-cert PEM_FILE ...] [--no-entry-check]
// --test-token and --test-entry sign with the TEST producer seed 00..1f under --kid: TEST ONLY.
// Every dial prints its outcome as one line and exits 0; a fault of the command line exits 2.
use std::collections::{BTreeSet, HashMap};
use std::io::{BufRead, Write};
use std::os::raw::c_int;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use tempus::admission::{frame_line, Identity, Verifier};
use tempus::client::{dial, DialOptions};
use tempus::crypto::{certificate_der, ed25519_seed_from_pkcs8_pem, hex, sha512, unhex, SigningKey};
use tempus::frames::{self, read_body, read_token, Entry};
use tempus::listener::{standard_answer, ListenOptions, Listener};
use tempus::node::clock::{ClockBack, ClockFail};
use tempus::node::config::{NodeIdentity, PeerType, Sentinel, StoreConfig, TempusConfig};
use tempus::node::sources::{ClockSource, SecureRandom, Sources, SystemTimers};
use tempus::node::{NodeEvent, TempusNode};
use tempus_testing::{fixture_identity, fixture_key, make_test_token, test_certificate};

fn fail(text: &str) -> ! {
    eprintln!("tempus-client: {}", text);
    std::process::exit(2)
}

fn say(line: &str) {
    let out = std::io::stdout();
    let mut out = out.lock();
    let _ = writeln!(out, "{}", line);
    let _ = out.flush();
}

struct Options {
    values: HashMap<String, Vec<String>>,
    rest: Vec<String>,
}

impl Options {
    fn new(argv: &[String]) -> Options {
        let flags = ["--system-clock", "--no-entry-check"];
        let mut o = Options { values: HashMap::new(), rest: Vec::new() };
        let mut i = 0;
        while i < argv.len() {
            let a = &argv[i];
            if a.starts_with("--") {
                if flags.contains(&a.as_str()) {
                    o.values.entry(a.clone()).or_default().push(String::new());
                } else {
                    if i + 1 >= argv.len() {
                        fail(&format!("{} needs a value", a));
                    }
                    o.values.entry(a.clone()).or_default().push(argv[i + 1].clone());
                    i += 1;
                }
            } else {
                o.rest.push(a.clone());
            }
            i += 1;
        }
        o
    }

    fn one(&self, name: &str) -> Option<&str> {
        self.values.get(name).and_then(|v| v.last()).map(|s| s.as_str())
    }

    fn need(&self, name: &str) -> &str {
        self.one(name).unwrap_or_else(|| fail(&format!("{} is required", name)))
    }

    fn need_hex(&self, name: &str, count: Option<usize>) -> Vec<u8> {
        match unhex(self.need(name)) {
            Some(b) if count.map(|n| n == b.len()).unwrap_or(true) => b,
            _ => fail(&format!("{} is not the hex it should be", name)),
        }
    }

    fn need_int(&self, name: &str) -> i64 {
        self.need(name).parse().unwrap_or_else(|_| fail(&format!("{} is not a whole number", name)))
    }
}

fn pem_der(path: &str) -> Vec<u8> {
    std::fs::read_to_string(path).ok().and_then(|t| certificate_der(&t))
        .unwrap_or_else(|| fail(&format!("no certificate could be read from {}", path)))
}

fn test_token(spec: &str, kid: &str, sub: &[u8]) -> Vec<u8> {
    let p: Vec<&str> = spec.split(':').collect();
    let made = if p.len() == 3 {
        match (p[1].parse::<i64>(), p[2].parse::<i64>()) {
            (Ok(nbf), Ok(exp)) => make_test_token(&fixture_key(0), kid, sub, p[0], nbf, exp).ok(),
            _ => None,
        }
    } else {
        None
    };
    made.unwrap_or_else(|| fail("a test token is TYP:NBF:EXP"))
}

fn identity(o: &Options) -> Identity {
    let seed = o.need_hex("--seed", Some(32));
    let key = SigningKey::from_seed(&seed).unwrap_or_else(|_| fail("--seed is not an Ed25519 seed"));
    if o.one("--token").is_some() == o.one("--test-token").is_some() {
        fail("give exactly one of --token and --test-token");
    }
    let token = if o.one("--token").is_some() { o.need_hex("--token", None) } else { test_token(o.need("--test-token"), o.need("--kid"), key.public()) };
    let cert = match o.one("--cert") {
        Some(path) => pem_der(path),
        None => test_certificate(&key, "bees tempus example client", 1).unwrap_or_else(|e| fail(&e.0)),
    };
    Identity::new(Arc::new(key), token, Some(o.need("--addr").to_string()), cert)
}

fn verifier(o: &Options) -> Verifier {
    if o.one("--now").is_some() == o.one("--system-clock").is_some() {
        fail("give exactly one of --now and --system-clock");
    }
    let clock: Arc<dyn Fn() -> i64 + Send + Sync> = if o.one("--now").is_some() {
        let now = o.need_int("--now");
        Arc::new(move || now)
    } else {
        Arc::new(|| SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs() as i64).unwrap_or(0))
    };
    let listed = o.values.get("--whitelist-cert").map(|v| v.iter().map(|p| sha512(&pem_der(p))).collect());
    Verifier::new(o.need_hex("--producer-pub", Some(32)), o.need("--kid").as_bytes().to_vec(), clock, o.need_int("--skew"), listed)
}

fn timeout(o: &Options) -> Duration {
    match o.need("--timeout").parse::<f64>() {
        Ok(t) if t > 0.0 => Duration::from_secs_f64(t),
        _ => fail("--timeout is a number of seconds"),
    }
}

fn request(r: &[String], me: &Identity) -> Vec<u8> {
    let usage = "the request is: sample STORE N | shuffle STORE | call M F [INTEGER...] | cast M F [INTEGER...] | raw HEX";
    let made = match r.first().map(|s| s.as_str()) {
        Some("sample") if r.len() == 3 => match r[2].parse::<i64>() {
            Ok(n) => frames::sample(&r[1], n),
            Err(_) => fail(usage),
        },
        Some("shuffle") if r.len() == 2 => me.entry(0).and_then(|e| frames::shuffle(&r[1], &[e])),
        Some("call") | Some("cast") if r.len() >= 3 => {
            let args: Vec<i64> = r[3..].iter().map(|a| a.parse().unwrap_or_else(|_| fail("the arguments of a call or cast are whole numbers"))).collect();
            frames::call_frame(&r[0], b"1", &r[1], &r[2], &args)
        }
        Some("raw") if r.len() == 2 => return unhex(&r[1]).unwrap_or_else(|| fail(usage)),
        _ => fail(usage),
    };
    made.unwrap_or_else(|e| fail(&e.0))
}

fn test_entries(o: &Options) -> HashMap<String, Vec<Entry>> {
    let mut held: HashMap<String, Vec<Entry>> = HashMap::new();
    for spec in o.values.get("--test-entry").cloned().unwrap_or_default() {
        let bad = || -> ! { fail("a test entry is STORE=AGE:FIRST:TYP:NBF:EXP:HOST:PORT") };
        let (store, rest) = spec.split_once('=').unwrap_or_else(|| bad());
        let p: Vec<&str> = rest.splitn(6, ':').collect();
        if p.len() != 6 {
            bad();
        }
        let entry = match (p[0].parse::<i64>(), p[1].parse::<u8>(), p[3].parse::<i64>(), p[4].parse::<i64>()) {
            (Ok(age), Ok(first), Ok(nbf), Ok(exp)) => fixture_identity(first, p[2], nbf, exp, Some(p[5]), o.need("--kid"), None, None)
                .and_then(|who| who.entry(age)).unwrap_or_else(|_| bad()),
            _ => bad(),
        };
        held.entry(store.to_string()).or_default().push(entry);
    }
    held
}

// ---------------------------------------------------------------- gossip
fn read_text(path: &str) -> String {
    std::fs::read_to_string(path).unwrap_or_else(|_| fail(&format!("{} cannot be read", path)))
}

fn store_config(o: &Options, name: &str) -> StoreConfig {
    let p: Vec<i64> = o.need(name).split(':').map(|n| n.parse().unwrap_or_else(|_| fail(&format!("{} is CAP:LEN:TICK_MS", name)))).collect();
    if p.len() != 3 {
        fail(&format!("{} is CAP:LEN:TICK_MS", name));
    }
    StoreConfig { capacity: p[0], shuffle_length: p[1], tick_ms: p[2] }
}

fn host_port(text: &str, name: &str) -> (String, i64) {
    match text.rsplit_once(':').and_then(|(h, p)| p.parse::<i64>().ok().map(|p| (h.to_string(), p))) {
        Some(x) => x,
        None => fail(&format!("{} is HOST:PORT", name)),
    }
}

// The values a node requires and the `gossip` command line does not carry. The library has no default for any of
// them; these are this driver's choices for the gossip example, stated here and nowhere else, and not
// recommendations: an application decides each of them for its own network (README.md, "The configuration").
const GOSSIP_INFLIGHT_MAX: i64 = 16;                       // accepted connections at once
const GOSSIP_CLOCK_BACK: ClockBack = ClockBack::Follow;    // a clock that steps back is followed
const GOSSIP_CLOCK_BACK_LIMIT_S: Option<i64> = None;       // only Stop takes a limit
const GOSSIP_CLOCK_FAIL: ClockFail = ClockFail::Continue;  // a reading that fails after a good one: go on with the last reading
const GOSSIP_CLOCK_READ_MS: i64 = 1000;                    // how often the clock is read

/// The clock of `--now SECONDS`: one fixed reading. The node accepts a clock of its caller's on a loopback listen
/// address only.
struct FixedClock(i64);

impl ClockSource for FixedClock {
    fn seconds(&self) -> Option<i64> {
        Some(self.0)
    }
}

static INTERRUPTED: AtomicBool = AtomicBool::new(false);

extern "C" fn on_signal(_: c_int) {
    INTERRUPTED.store(true, Ordering::SeqCst);
}

extern "C" {
    // the C library's signal(2); the result, the previous handler, is not used
    fn signal(signum: c_int, handler: extern "C" fn(c_int)) -> usize;
}

/// SIGINT and SIGTERM end the run, so that the `known` lines are printed. The standard library has no call for this.
fn end_on_signals() {
    const SIGINT: c_int = 2;
    const SIGTERM: c_int = 15;
    // SAFETY: the handler only stores into an atomic, which is safe in a signal handler; the numbers are those of
    // macOS and Linux.
    unsafe {
        signal(SIGINT, on_signal);
        signal(SIGTERM, on_signal);
    }
}

fn gossip(o: &Options) {
    if !o.rest.is_empty() {
        fail("gossip OPTIONS");
    }
    let seed = ed25519_seed_from_pkcs8_pem(&read_text(o.need("--key"))).unwrap_or_else(|| fail("--key is not an unencrypted PKCS#8 Ed25519 key in PEM"));
    let token = unhex(read_text(o.need("--token")).trim()).unwrap_or_else(|| fail("--token does not hold hex digits"));
    // the node's role is the type its token carries
    let role = read_token(&token).ok().and_then(|t| PeerType::from_name(&t.fields.typ)).unwrap_or_else(|| fail("--token does not hold a token"));
    let retry: Vec<i64> = o.need("--join-retry-ms").split(':').filter_map(|n| n.parse().ok()).collect();
    if retry.len() != 2 {
        fail("--join-retry-ms is FIRST:MAX");
    }
    let (host, port) = host_port(o.need("--addr"), "--addr");
    let many = |name: &str| o.values.get(name).cloned().unwrap_or_default();
    // a member of a network always applies the whitelist rule: with no --whitelist-cert it accepts no bridge and no
    // sentinel on a connection. The library's whitelist is a list of certificates and a sentinel names none of them.
    let config = TempusConfig {
        role, listen_address: host, port,
        sentinels: many("--sentinel").iter().map(|s| { let (host, port) = host_port(s, "--sentinel"); Sentinel { host, port } }).collect(),
        edge: store_config(o, "--store-edge"), bridge: store_config(o, "--store-bridge"), sentinel: store_config(o, "--store-sentinel"),
        producer_kid: o.need("--kid").as_bytes().to_vec(), producer_key: o.need_hex("--producer-pub", Some(32)),
        whitelist: many("--whitelist-cert").iter().map(|p| pem_der(p)).collect(),
        shuffle_timeout_ms: o.need_int("--timeout-ms"), inflight_max: GOSSIP_INFLIGHT_MAX,
        clock_skew_ms: o.need_int("--skew") * 1000,
        clock_back: GOSSIP_CLOCK_BACK, clock_back_limit_s: GOSSIP_CLOCK_BACK_LIMIT_S,
        clock_fail: GOSSIP_CLOCK_FAIL, clock_read_ms: GOSSIP_CLOCK_READ_MS,
        join_retry_initial_ms: retry[0], join_retry_max_ms: retry[1],
    };
    let identity = NodeIdentity { seed, certificate_der: pem_der(o.need("--cert")), token, address: o.need("--addr").to_string() };
    // every peer this instance ever held in a store, from the views the node reports
    let known: Arc<Mutex<HashMap<&'static str, BTreeSet<String>>>> = Arc::new(Mutex::new(HashMap::new()));
    let seen = known.clone();
    let events = Box::new(move |event: NodeEvent| match event {
        NodeEvent::View { store, entries } => {
            let mut seen = seen.lock().unwrap();
            for e in entries {
                let id16 = hex(&e.id[..8.min(e.id.len())]);
                if seen.entry(store.name()).or_default().insert(id16.clone()) {
                    say(&format!("learned {} {} {}", store.name(), id16, String::from_utf8_lossy(&e.d.addr)));
                }
            }
        }
        NodeEvent::OwnTokenNotValid { reason } => say(&format!("told: the node's own token is not valid any more: {}", reason)),
        NodeEvent::KeyRotated { kid, .. } => say(&format!("told: a peer answered key_rotated, its current kid is {}", String::from_utf8_lossy(&kid))),
        NodeEvent::ClockNotRead(text) | NodeEvent::Stopped(text) => say(&format!("told: {}", text)),
        NodeEvent::ListenFailed(text) => say(&format!("told: the node does not listen: {}", text)),
        NodeEvent::Listening { .. } | NodeEvent::Joined | NodeEvent::PeerRefused { .. } => {}
    });
    let lines: tempus::node::Lines = Arc::new(|line: &str| say(line));
    let made = match o.one("--now") {
        Some(_) => {
            let sources = Sources { clock: Arc::new(FixedClock(o.need_int("--now"))), timers: Arc::new(SystemTimers::new()), random: Arc::new(SecureRandom) };
            TempusNode::with_sources(config, identity, sources, lines, events)
        }
        None => TempusNode::new(config, identity, lines, events),
    };
    let node = made.unwrap_or_else(|_| std::process::exit(1)); // the node has written the line that says why
    end_on_signals();
    node.start();
    let until = o.one("--run-ms").map(|_| Instant::now() + Duration::from_millis(o.need_int("--run-ms").max(0) as u64));
    while !INTERRUPTED.load(Ordering::SeqCst) && until.map(|t| Instant::now() < t).unwrap_or(true) {
        std::thread::sleep(Duration::from_millis(50));
    }
    node.stop();
    let known = known.lock().unwrap();
    for t in PeerType::ALL {
        let all: Vec<String> = known.get(t.name()).map(|s| s.iter().cloned().collect()).unwrap_or_default();
        say(&format!("known {}: {}", t.name(), if all.is_empty() { "(none)".to_string() } else { all.join(" ") }));
    }
}

fn main() {
    let argv: Vec<String> = std::env::args().skip(1).collect();
    match argv.first().map(|s| s.as_str()) {
        Some("gossip") => gossip(&Options::new(&argv[1..])),
        Some("read-hex") if argv.len() == 3 => {
            let (body, length) = match (unhex(&argv[1]), argv[2].parse::<usize>()) {
                (Some(b), Ok(n)) => (b, n),
                _ => fail("read-hex HEX SHUFFLE_LENGTH"),
            };
            match read_body(&body, length) {
                Ok(f) => say(&frame_line(&f)),
                Err(why) => say(&format!("refused: {}", why)),
            }
        }
        Some("test-token") => {
            let o = Options::new(&argv[1..]);
            if o.rest.len() != 3 {
                fail("test-token --seed HEX --kid KID TYP NBF EXP");
            }
            let key = SigningKey::from_seed(&o.need_hex("--seed", Some(32))).unwrap_or_else(|e| fail(&e.0));
            say(&hex(&test_token(&o.rest.join(":"), o.need("--kid"), key.public())));
        }
        Some("dial") => {
            let o = Options::new(&argv[1..]);
            let peer = o.rest.first().unwrap_or_else(|| fail("dial HOST:PORT ..."));
            let me = identity(&o);
            let options = DialOptions { timeout: timeout(&o), nonce: o.one("--nonce").map(|_| o.need_hex("--nonce", Some(32))),
                                        shuffle_length: o.need_int("--shuffle-length") as usize, verify_entries: o.one("--no-entry-check").is_none() };
            let out = dial(peer, &me, &verifier(&o), &request(&o.rest[1..], &me), options);
            say(&out.line());
        }
        Some("listen") => {
            let o = Options::new(&argv[1..]);
            let (host, port) = match o.rest.first().and_then(|at| at.rsplit_once(':')).and_then(|(h, p)| p.parse::<u16>().ok().map(|p| (h.to_string(), p))) {
                Some(x) if o.rest.len() == 1 => x,
                _ => fail("listen HOST:PORT ..."),
            };
            let held = test_entries(&o);
            let options = ListenOptions { host, port, timeout: timeout(&o), shuffle_length: o.need_int("--shuffle-length") as usize,
                                          verify_entries: o.one("--no-entry-check").is_none(), nonce: None,
                                          on_outcome: Some(Box::new(|_, out| say(&out.line()))) };
            let handler = Box::new(move |rq: &tempus::listener::Request| standard_answer(rq, &|store| held.get(store).cloned().unwrap_or_default()));
            let mut listener = Listener::new(identity(&o), verifier(&o), options, handler).unwrap_or_else(|e| fail(&e.0));
            listener.start();
            say(&format!("listening {}", listener.address()));
            let stdin = std::io::stdin();
            for _ in stdin.lock().lines() {}
            listener.stop();
        }
        _ => fail("usage: tempus-client gossip | read-hex | test-token | dial | listen (see the README)"),
    }
}
