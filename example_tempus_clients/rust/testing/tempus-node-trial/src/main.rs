// TEST ONLY: a node of the Rust TEMPUS extension as the trial trials/c15_tempus_node_rust runs it. Its identity and
// token come from fixed seeds (tempus-testing), and its clock, timers and draws are set by hand: the trial tool
// writes commands to its standard input. None of this is in the extension: the node is made with the constructor
// that takes its sources, and is refused on an address that is not loopback.
//
//   tempus-node-trial KEY=VALUE ...
//     role=edge|sentinel  port=N  seed=FIRST_BYTE  token=TYP:NBF:EXP  cert=PEM_FILE (optional: else one is made)
//     sentinels=127.0.0.1:PORT,...  whitelist=PEM_FILE,...  stores=CAP/LEN,CAP/LEN,CAP/LEN (edge, bridge, sentinel)
//     inflight_max=N  shuffle_timeout_ms=N  clock_back=...  clock_back_limit_s=N  clock_fail=...  draws=3,0,7
//     join_retry=INITIAL/MAX  now=SECONDS (optional: the first reading; without it the clock cannot be read at start)
//   Commands, one per line:
//     clock SECONDS | clock fail      the next reading of the node's clock, taken at once
//     tick STORE                      the tick timer of that store runs now
//     retry                           the join's retry timer runs now
//     token TYP:NBF:EXP               the application passes a new token
//     exit
// It prints the node's lines, one line `view STORE: ID@AGE ...` for each view the node tells its application, and one
// line `application: ...` for everything else it is told.
use std::collections::HashMap;
use std::io::{BufRead, Write};
use std::sync::Arc;
use tempus::crypto::{certificate_der, hex};
use tempus::node::clock::{ClockBack, ClockFail};
use tempus::node::config::{NodeIdentity, PeerType, Sentinel, StoreConfig, TempusConfig};
use tempus::node::sources::{Sources, TimerPurpose};
use tempus::node::{NodeEvent, TempusNode};
use tempus_testing::sources::{ListRandom, ManualClock, ManualTimers};
use tempus_testing::{fixture_key, fixture_seed, make_test_token, test_certificate};

fn fail(text: &str) -> ! {
    eprintln!("tempus-node-trial: {}", text);
    std::process::exit(2)
}

fn say(line: &str) {
    let out = std::io::stdout();
    let mut out = out.lock();
    let _ = writeln!(out, "{}", line);
    let _ = out.flush();
}

fn certificate(path: &str) -> Vec<u8> {
    std::fs::read_to_string(path).ok().and_then(|t| certificate_der(&t)).unwrap_or_else(|| fail(&format!("no certificate in {}", path)))
}

fn test_token(text: &str, sub: &[u8]) -> Vec<u8> {
    let p: Vec<&str> = text.split(':').collect();
    if p.len() != 3 {
        fail("a token is TYP:NBF:EXP");
    }
    match (p[1].parse(), p[2].parse()) {
        (Ok(nbf), Ok(exp)) => make_test_token(&fixture_key(0), "k1", sub, p[0], nbf, exp).unwrap_or_else(|_| fail("a token is TYP:NBF:EXP")),
        _ => fail("a token is TYP:NBF:EXP"),
    }
}

fn main() {
    let mut given: HashMap<String, String> = HashMap::new();
    for a in std::env::args().skip(1) {
        match a.split_once('=') {
            Some((k, v)) => given.insert(k.to_string(), v.to_string()),
            None => fail(&format!("not KEY=VALUE: {}", a)),
        };
    }
    let need = |key: &str| -> String { given.get(key).cloned().unwrap_or_else(|| fail(&format!("{} is required", key))) };
    let number = |key: &str| -> i64 { need(key).parse().unwrap_or_else(|_| fail(&format!("{} is not a number", key))) };
    let role = PeerType::from_name(&format!("tempus_{}", need("role"))).unwrap_or_else(|| fail("role"));
    let first: u8 = need("seed").parse().unwrap_or_else(|_| fail("seed"));
    let key = fixture_key(first);
    let back = ClockBack::from_name(&need("clock_back")).unwrap_or_else(|| fail("the clock's choices"));
    let clock_fail = ClockFail::from_name(&need("clock_fail")).unwrap_or_else(|| fail("the clock's choices"));
    let sizes: Vec<Vec<i64>> = need("stores").split(',').map(|s| s.split('/').filter_map(|n| n.parse().ok()).collect()).collect();
    if sizes.len() != 3 || sizes.iter().any(|s| s.len() != 2) {
        fail("stores");
    }
    let retry: Vec<i64> = need("join_retry").split('/').filter_map(|n| n.parse().ok()).collect();
    if retry.len() != 2 {
        fail("join_retry");
    }
    let port = number("port");
    let list = |key: &str| -> Vec<String> { given.get(key).map(|v| v.split(',').filter(|s| !s.is_empty()).map(|s| s.to_string()).collect()).unwrap_or_default() };
    let sentinels = list("sentinels").iter().map(|text| {
        let (host, p) = text.split_once(':').unwrap_or_else(|| fail("sentinels"));
        Sentinel { host: host.to_string(), port: p.parse().unwrap_or(0) }
    }).collect();
    // the timers never run by themselves, so the tick and clock periods are only values that pass the bounds
    let store = |k: usize| StoreConfig { capacity: sizes[k][0], shuffle_length: sizes[k][1], tick_ms: 1000 };
    let config = TempusConfig {
        role, listen_address: "127.0.0.1".into(), port, sentinels, edge: store(0), bridge: store(1), sentinel: store(2),
        producer_kid: b"k1".to_vec(), producer_key: fixture_key(0).public().to_vec(),
        whitelist: list("whitelist").iter().map(|p| certificate(p)).collect(),
        shuffle_timeout_ms: number("shuffle_timeout_ms"), inflight_max: number("inflight_max"), clock_skew_ms: 10000,
        clock_back: back, clock_back_limit_s: given.get("clock_back_limit_s").map(|_| number("clock_back_limit_s")),
        clock_fail, clock_read_ms: 1000, join_retry_initial_ms: retry[0], join_retry_max_ms: retry[1],
    };
    let cert = match given.get("cert") {
        Some(path) => certificate(path),
        None => test_certificate(&key, "bees tempus trial node", 1).unwrap_or_else(|_| fail("the certificate")),
    };
    let identity = NodeIdentity { seed: fixture_seed(first), certificate_der: cert, token: test_token(&need("token"), key.public()),
                                  address: format!("127.0.0.1:{}", port) };
    let clock = Arc::new(ManualClock::new(given.get("now").and_then(|n| n.parse().ok())));
    let timers = Arc::new(ManualTimers::new());
    let draws = need("draws").split(',').filter_map(|n| n.parse().ok()).collect();
    let sources = Sources { clock: clock.clone(), timers: timers.clone(), random: Arc::new(ListRandom::new(draws)) };
    say("TEST ONLY: this node's clock, timers and draws are set by the trial");
    let events = Box::new(|event: NodeEvent| match event {
        NodeEvent::View { store, entries } => {
            let shown = if entries.is_empty() { " (empty)".to_string() } else { entries.iter().map(|e| format!(" {}@{}", hex(&e.id[..4]), e.age)).collect() };
            say(&format!("view {}:{}", store.name(), shown));
        }
        NodeEvent::OwnTokenNotValid { reason } => say(&format!("application: told that the node's own token is not valid any more: {}", reason)),
        NodeEvent::KeyRotated { kid, dialed } => say(&format!("application: told that a peer {} answered key_rotated, its current kid is {}",
                                                             if dialed { "this node dialed" } else { "that dialed this node" }, String::from_utf8_lossy(&kid))),
        NodeEvent::ClockNotRead(text) | NodeEvent::Stopped(text) => say(&format!("application: told that {}", text)),
        NodeEvent::ListenFailed(text) => say(&format!("application: told that the node does not listen: {}", text)),
        NodeEvent::PeerRefused { event, peer_id, token_verified } => say(&format!("application: told that a peer was refused: {} {} {}", event,
                                                                                 hex(&peer_id[..8]), if token_verified { "token verified" } else { "token not verified" })),
        NodeEvent::Listening { .. } | NodeEvent::Joined => {}
    });
    let node = match TempusNode::with_sources(config, identity, sources, Arc::new(|line: &str| say(line)), events) {
        Ok(n) => n,
        Err(_) => {
            say("boot: refused, nothing started");
            std::process::exit(1);
        }
    };
    node.start();
    let stdin = std::io::stdin();
    for line in stdin.lock().lines() {
        let line = match line {
            Ok(l) => l,
            Err(_) => break,
        };
        if line == "exit" {
            break;
        }
        let w: Vec<&str> = line.split(' ').filter(|s| !s.is_empty()).collect();
        match (w.first().copied(), w.len()) {
            (Some("clock"), 2) => {
                clock.set(w[1].parse().ok()); // `fail` is no number: the clock cannot be read
                if !timers.fire(TimerPurpose::ClockRead) {
                    say("trial: no clock timer is armed");
                }
            }
            (Some("tick"), 2) => {
                let fired = PeerType::from_name(w[1]).map(|st| timers.fire(TimerPurpose::Tick(st))).unwrap_or(false);
                if !fired {
                    say(&format!("trial: no tick timer for {}", w[1]));
                }
            }
            (Some("retry"), _) => {
                if !timers.fire(TimerPurpose::JoinRetry) {
                    say("trial: no join retry timer is armed");
                }
            }
            (Some("token"), 2) => node.replace_token(test_token(w[1], key.public())),
            _ => say(&format!("trial: unknown command: {}", line)),
        }
    }
    node.stop();
}
