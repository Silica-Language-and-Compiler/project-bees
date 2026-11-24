// An application that is a TEMPUS node, using the Rust TEMPUS extension: the smallest complete one. It depends on the
// crate `tempus` and on nothing of the tests. It reads the machine's clock, runs its own timers and draws from the
// system's secure random source; nothing here can set its time.
//
//   tempus-node-example KEY=VALUE ...      every key is required unless marked optional; nothing has a default
//     role=edge|sentinel  listen_address=A.B.C.D  port=N  address=A.B.C.D:PORT (what other nodes dial)
//     seed_file=PATH (the 32 bytes of the Ed25519 private seed)  cert_file=PATH (PEM)  token_file=PATH (the token's bytes)
//     producer_kid=TEXT  producer_key=HEX  sentinels=A.B.C.D:PORT,... (optional for a first sentinel)
//     whitelist=PEM_FILE,... (optional)  edge=CAPACITY/SHUFFLE_LENGTH/TICK_MS  bridge=...  sentinel=...
//     shuffle_timeout_ms=N  inflight_max=N  clock_skew_ms=N  clock_back=follow|hold|stop  clock_back_limit_s=N (with stop)
//     clock_fail=continue|pause  clock_read_ms=N  join_retry_initial_ms=N  join_retry_max_ms=N
// It prints the node's lines and what the application is told, and ends when its standard input says `exit` or ends.
use std::collections::HashMap;
use std::io::{BufRead, Write};
use std::sync::Arc;
use tempus::crypto::{certificate_der, unhex};
use tempus::node::clock::{ClockBack, ClockFail};
use tempus::node::config::{NodeIdentity, PeerType, Sentinel, StoreConfig, TempusConfig};
use tempus::node::{NodeEvent, TempusNode};

fn fail(text: &str) -> ! {
    eprintln!("tempus-node-example: {}", text);
    std::process::exit(2)
}

fn say(line: &str) {
    let out = std::io::stdout();
    let mut out = out.lock();
    let _ = writeln!(out, "{}", line);
    let _ = out.flush();
}

fn file(path: &str) -> Vec<u8> {
    std::fs::read(path).unwrap_or_else(|_| fail(&format!("cannot read {}", path)))
}

fn certificate(path: &str) -> Vec<u8> {
    certificate_der(&String::from_utf8_lossy(&file(path))).unwrap_or_else(|| fail(&format!("{} holds no certificate", path)))
}

fn main() {
    let mut given: HashMap<String, String> = HashMap::new();
    for a in std::env::args().skip(1) {
        match a.split_once('=') {
            Some((k, v)) => given.insert(k.to_string(), v.to_string()),
            None => fail(&format!("not KEY=VALUE: {}", a)),
        };
    }
    let need = |key: &str| -> String { given.get(key).cloned().unwrap_or_else(|| fail(&format!("{} is required (no default)", key))) };
    let number = |key: &str| -> i64 { need(key).parse().unwrap_or_else(|_| fail(&format!("{} is not a number", key))) };
    let store = |key: &str| -> StoreConfig {
        let p: Vec<i64> = need(key).split('/').filter_map(|n| n.parse().ok()).collect();
        if p.len() != 3 {
            fail(&format!("{} is not CAPACITY/SHUFFLE_LENGTH/TICK_MS", key));
        }
        StoreConfig { capacity: p[0], shuffle_length: p[1], tick_ms: p[2] }
    };
    let list = |key: &str| -> Vec<String> { given.get(key).map(|v| v.split(',').filter(|s| !s.is_empty()).map(|s| s.to_string()).collect()).unwrap_or_default() };
    let role = PeerType::from_name(&format!("tempus_{}", need("role"))).unwrap_or_else(|| fail("role is not edge, bridge or sentinel"));
    let back = ClockBack::from_name(&need("clock_back")).unwrap_or_else(|| fail("clock_back is not follow, hold or stop"));
    let clock_fail = ClockFail::from_name(&need("clock_fail")).unwrap_or_else(|| fail("clock_fail is not continue or pause"));
    let sentinels = list("sentinels").iter().map(|text| match text.rsplit_once(':').and_then(|(h, p)| p.parse().ok().map(|p| (h, p))) {
        Some((host, port)) => Sentinel { host: host.to_string(), port },
        None => fail("a sentinel is A.B.C.D:PORT"),
    }).collect();
    let config = TempusConfig {
        role, listen_address: need("listen_address"), port: number("port"), sentinels,
        edge: store("edge"), bridge: store("bridge"), sentinel: store("sentinel"),
        producer_kid: need("producer_kid").into_bytes(), producer_key: unhex(&need("producer_key")).unwrap_or_else(|| fail("producer_key is not hex")),
        whitelist: list("whitelist").iter().map(|p| certificate(p)).collect(),
        shuffle_timeout_ms: number("shuffle_timeout_ms"), inflight_max: number("inflight_max"), clock_skew_ms: number("clock_skew_ms"),
        clock_back: back, clock_back_limit_s: given.get("clock_back_limit_s").map(|_| number("clock_back_limit_s")),
        clock_fail, clock_read_ms: number("clock_read_ms"),
        join_retry_initial_ms: number("join_retry_initial_ms"), join_retry_max_ms: number("join_retry_max_ms"),
    };
    let identity = NodeIdentity { seed: file(&need("seed_file")), certificate_der: certificate(&need("cert_file")), token: file(&need("token_file")),
                                  address: need("address") };
    // what the application is told; an application acts on these (a new token, a new node), this one prints them
    let events = Box::new(|event: NodeEvent| match event {
        NodeEvent::OwnTokenNotValid { reason } => say(&format!("application: told that the node's own token is not valid any more: {}", reason)),
        NodeEvent::KeyRotated { kid, .. } => say(&format!("application: told that a peer answered key_rotated, its current kid is {}", String::from_utf8_lossy(&kid))),
        NodeEvent::ClockNotRead(text) | NodeEvent::Stopped(text) => say(&format!("application: told that {}", text)),
        NodeEvent::ListenFailed(text) => say(&format!("application: told that the node does not listen: {}", text)),
        NodeEvent::Listening { .. } | NodeEvent::View { .. } | NodeEvent::Joined | NodeEvent::PeerRefused { .. } => {}
    });
    let node = match TempusNode::new(config, identity, Arc::new(|line: &str| say(line)), events) {
        Ok(n) => n,
        Err(_) => std::process::exit(1), // the node has written the line that says why
    };
    node.start();
    let stdin = std::io::stdin();
    for line in stdin.lock().lines() {
        match line {
            Ok(l) if l != "exit" => {}
            _ => break,
        }
    }
    node.stop();
}
