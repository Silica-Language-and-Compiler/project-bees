// The node half, at unit level: the clock against trials/t0_tempus_clock, the configuration against the cases of
// tools/test_bees_tempus_conf.py, the boot refusals (those of trials/c4_tempus_boot where the texts are the node's
// own), and a node in this process whose clock, timers and draws the test sets, dialed by the extension's client.
use std::sync::mpsc::{channel, Receiver};
use std::sync::{Arc, Mutex};
use std::time::Duration;
use tempus::admission::Verifier;
use tempus::client::{dial, DialOptions};
use tempus::frames::{self, Frame};
use tempus::node::clock::*;
use tempus::node::config::*;
use tempus::node::sources::{Sources, TimerPurpose};
use tempus::node::{NodeEvent, TempusNode};
use tempus_testing::sources::{ListRandom, ManualClock, ManualTimers};
use tempus_testing::{fixture_identity, fixture_key, fixture_seed, make_test_token, test_certificate};
use tempus_tests::goldens;

// ---------------------------------------------------------------- the clock, against trials/t0_tempus_clock
fn choices(text: &str) -> Option<ClockChoices> {
    // "follow" | "hold" | "stop limit N", then optionally ", clock_fail X"
    let (back, fail) = match text.split_once(", clock_fail ") {
        Some((b, f)) => (b, ClockFail::from_name(f)?),
        None => (text, ClockFail::Pause),
    };
    let words: Vec<&str> = back.split(' ').collect();
    Some(ClockChoices { back: ClockBack::from_name(words[0])?, limit: if words.len() == 3 { words[2].parse().ok()? } else { 0 }, fail })
}

fn state_text(ck: ClockState) -> &'static str {
    match ck {
        ClockState::None => "no reading yet",
        ClockState::NoneTold => "no reading yet, application told",
        ClockState::Good => "good",
        ClockState::Paused => "paused, waits for the clock",
        ClockState::Continuing => "goes on with its last reading",
        ClockState::Holding => "holds its time",
        ClockState::Stopped => "stopped",
    }
}

fn say_text(s: ClockSay) -> &'static str {
    match s {
        ClockSay::Nothing => "nothing",
        ClockSay::First => "first reading: one line, listen",
        ClockSay::NoTimeAtStart => "no time at start: one line, application told",
        ClockSay::NoTimePause => "no time, pause: one line, application told",
        ClockSay::NoTimeContinue => "no time, continue: one line, application told",
        ClockSay::Followed => "step back followed: one line",
        ClockSay::HoldBegins => "step back, hold begins: one line",
        ClockSay::HoldEnds => "the held time is reached: one line",
        ClockSay::Stop => "step back above the limit: one line, application told, stop",
    }
}

#[test]
fn every_line_of_the_clock_trial() {
    for (name, text) in goldens("t0_tempus_clock", "clock") {
        let (mut z, mut ck, mut now, mut lines) = (None, ClockState::None, 0i64, 0);
        for line in text.lines() {
            if line.starts_with("part ") || line.starts_with("exit=") || line.is_empty() {
                continue;
            }
            if let Some(rest) = line.strip_prefix("clock_back ") {
                z = choices(rest);
                ck = ClockState::None;
                now = 0;
                assert!(z.is_some(), "{}: the choices of: {}", name, line);
            } else if let Some(rest) = line.strip_prefix("  reading ") {
                let reading = rest.split(" -> ").next().unwrap();
                let t = clock_turn(ck, now, reading.parse().ok(), z.expect("choices come first"));
                now = t.now;
                ck = t.ck;
                let accepts = match ck {
                    ClockState::None | ClockState::NoneTold => "does not listen yet",
                    ClockState::Paused => "closes accepted connections (role 4, clock_refused)",
                    ClockState::Stopped => "closes accepted connections (role 5, clock_stopped)",
                    _ => "accepts",
                };
                let got = format!("  reading {} -> time {}; {}; {}; {}; does: {}{}", reading, now, state_text(ck), if ck.ticks() { "ticks" } else { "no ticks" },
                                  accepts, if t.again { "read again: one line; then " } else { "" }, say_text(t.say));
                assert_eq!(got, line, "{}: clock_turn", name);
                assert_eq!(ck.closes_with().is_none(), !accepts.starts_with("closes"), "{}: closes_with of {:?}", name, ck);
                lines += 1;
            } else if let Some((head, rest)) = line.split_once(": time ") {
                let z1 = choices(head).unwrap_or_else(|| panic!("{}: a line this test does not read: {}", name, line));
                let nums: Vec<&str> = rest.split(" -> ").next().unwrap().split(", reading ").collect();
                let (t, act) = clock_back(nums[0].parse().unwrap(), nums[1].parse().unwrap(), z1);
                let what = ["not earlier", "earlier, followed", "earlier, held", "earlier, the node stops"][act as usize];
                assert_eq!(format!("{}: time {}, reading {} -> time {}, {}", head, nums[0], nums[1], t, what), line, "{}: clock_back", name);
                lines += 1;
            } else {
                panic!("{}: a line of the clock trial this test does not read: {}", name, line);
            }
        }
        assert_eq!(lines, 71, "{}: the clock trial's recorded output has 71 case lines", name);
    }
}

#[test]
fn the_system_clock_is_whole_seconds_and_present() {
    let a = read_system_clock().expect("the machine has a clock");
    assert!(a > 1_700_000_000);
}

// ---------------------------------------------------------------- configuration
fn good_config() -> TempusConfig {
    let s = StoreConfig { capacity: 4, shuffle_length: 2, tick_ms: 1000 };
    TempusConfig { role: PeerType::Edge, listen_address: "127.0.0.1".into(), port: 25790, sentinels: vec![Sentinel { host: "127.0.0.1".into(), port: 25791 }],
                   edge: StoreConfig { capacity: 4, shuffle_length: 3, tick_ms: 1000 }, bridge: s, sentinel: s, producer_kid: b"k1".to_vec(),
                   producer_key: fixture_key(0).public().to_vec(), whitelist: vec![], shuffle_timeout_ms: 2000, inflight_max: 4, clock_skew_ms: 10000,
                   clock_back: ClockBack::Follow, clock_back_limit_s: None, clock_fail: ClockFail::Pause, clock_read_ms: 1000,
                   join_retry_initial_ms: 200, join_retry_max_ms: 800 }
}

fn refused(what: &str, part: &str, change: impl Fn(&mut TempusConfig)) {
    let mut c = good_config();
    change(&mut c);
    let why = c.refusal().unwrap_or_else(|| "(accepted)".into());
    assert!(why.contains(part), "{}: wanted a refusal with \"{}\", got: {}", what, part, why);
}

#[test]
fn the_refusals_of_the_silica_configuration_in_the_same_words() {
    assert_eq!(good_config().refusal(), None);
    // the cases of tools/test_bees_tempus_conf.py that concern values (the file's syntax and the mode are not this extension's)
    refused("role bridge", "bridge needs mode tempus-trust", |c| c.role = PeerType::Bridge);
    refused("capacity 257", "tempus.edge.capacity: 257 is above 256 (bounds 1 to 256; never clamped)", |c| c.edge.capacity = 257);
    refused("shuffle length 5 of capacity 4", "tempus.edge.shuffle_length: 5 is above the capacity 4", |c| c.edge.shuffle_length = 5);
    refused("a key of 31 bytes", "32 bytes", |c| c.producer_key = vec![0; 31]);
    refused("join maximum below the initial", "tempus.join_retry_max_ms: below join_retry_initial_ms", |c| c.join_retry_max_ms = 150);
    refused("no sentinels, an edge", "tempus.sentinels: required unless the node is the first sentinel", |c| c.sentinels.clear());
    let mut first = good_config();
    first.role = PeerType::Sentinel;
    first.sentinels.clear();
    assert_eq!(first.refusal(), None, "a first sentinel needs no sentinels");
    refused("stop with no limit", "tempus.clock_back_limit_s: required when clock_back is stop", |c| c.clock_back = ClockBack::Stop);
    for back in [ClockBack::Follow, ClockBack::Hold] {
        refused("a limit under follow or hold", "remove clock_back_limit_s", |c| {
            c.clock_back = back;
            c.clock_back_limit_s = Some(30);
        });
        for fail in [ClockFail::Continue, ClockFail::Pause] {
            let mut c = good_config();
            c.clock_back = back;
            c.clock_fail = fail;
            assert_eq!(c.refusal(), None);
        }
    }
    for limit in [0, 86400] {
        let mut c = good_config();
        c.clock_back = ClockBack::Stop;
        c.clock_back_limit_s = Some(limit);
        assert_eq!(c.refusal(), None, "stop with the limit {}", limit);
    }
    let stop = |limit: i64| move |c: &mut TempusConfig| {
        c.clock_back = ClockBack::Stop;
        c.clock_back_limit_s = Some(limit);
    };
    refused("a limit of -1", "tempus.clock_back_limit_s: -1 is below 0", stop(-1));
    refused("a limit of 86401", "tempus.clock_back_limit_s: 86401 is above 86400", stop(86401));
    for ms in [100, 60000] {
        let mut c = good_config();
        c.clock_read_ms = ms;
        assert_eq!(c.refusal(), None);
    }
    refused("clock_read_ms 99", "tempus.clock_read_ms: 99 is below 100", |c| c.clock_read_ms = 99);
    refused("clock_read_ms 60001", "tempus.clock_read_ms: 60001 is above 60000", |c| c.clock_read_ms = 60001);
}

#[test]
fn every_bound_of_the_design_on_both_sides() {
    refused("port 0", "tempus.port: 0 is below 1", |c| c.port = 0);
    refused("port 65536", "tempus.port: 65536 is above 65535", |c| c.port = 65536);
    refused("shuffle_timeout_ms 99", "tempus.shuffle_timeout_ms: 99 is below 100", |c| c.shuffle_timeout_ms = 99);
    refused("shuffle_timeout_ms 60001", "tempus.shuffle_timeout_ms: 60001 is above 60000", |c| c.shuffle_timeout_ms = 60001);
    refused("inflight_max 0", "tempus.inflight_max: 0 is below 1", |c| c.inflight_max = 0);
    refused("inflight_max 65", "tempus.inflight_max: 65 is above 64", |c| c.inflight_max = 65);
    refused("clock_skew_ms 300001", "tempus.clock_skew_ms: 300001 is above 300000", |c| c.clock_skew_ms = 300001);
    refused("clock_skew_ms -1", "tempus.clock_skew_ms: -1 is below 0", |c| c.clock_skew_ms = -1);
    refused("join_retry_initial_ms 99", "tempus.join_retry_initial_ms: 99 is below 100", |c| c.join_retry_initial_ms = 99);
    refused("join_retry_max_ms 3600001", "tempus.join_retry_max_ms: 3600001 is above 3600000", |c| c.join_retry_max_ms = 3600001);
    refused("tick_ms 99", "tempus.bridge.tick_ms: 99 is below 100", |c| c.bridge.tick_ms = 99);
    refused("tick_ms 3600001", "tempus.sentinel.tick_ms: 3600001 is above 3600000", |c| c.sentinel.tick_ms = 3600001);
    refused("shuffle_length 65", "tempus.edge.shuffle_length: 65 is above 64", |c| {
        c.edge.capacity = 256;
        c.edge.shuffle_length = 65;
    });
    refused("shuffle_length 0", "tempus.bridge.shuffle_length: 0 is below 1", |c| c.bridge.shuffle_length = 0);
    refused("capacity 0", "tempus.sentinel.capacity: 0 is below 1", |c| c.sentinel.capacity = 0);
    refused("an empty kid", "tempus.producer_key: the kid is not 1 to 64 bytes", |c| c.producer_kid.clear());
    refused("a kid of 65 bytes", "tempus.producer_key: the kid is not 1 to 64 bytes", |c| c.producer_kid = vec![b'k'; 65]);
    refused("17 sentinels", "1 to 16", |c| c.sentinels = vec![Sentinel { host: "127.0.0.1".into(), port: 1 }; 17]);
    refused("a sentinel by name", "is not an IPv4 literal", |c| c.sentinels = vec![Sentinel { host: "s.example".into(), port: 1 }]);
    refused("a sentinel's port 0", "tempus.sentinels: 0 is below 1", |c| c.sentinels = vec![Sentinel { host: "127.0.0.1".into(), port: 0 }]);
    refused("an IPv6 listen address", "tempus.listen_address", |c| c.listen_address = "::1".into());
}

/// A port of 127.0.0.1 that the system says is free now. The tests of several trials may run at the same time, so no
/// test listens on a fixed port.
fn free_port() -> i64 {
    std::net::TcpListener::bind("127.0.0.1:0").and_then(|l| l.local_addr()).expect("the system assigns a port").port() as i64
}

// ---------------------------------------------------------------- the start, and a node in this process
struct Made {
    node: Result<TempusNode, ConfigRefused>,
    lines: Arc<Mutex<Vec<String>>>,
    events: Receiver<NodeEvent>,
    clock: Arc<ManualClock>,
    timers: Arc<ManualTimers>,
}

/// A node with the identity of seed 32.. and the given token, on the configuration `change` makes of the good one.
fn make(token: Vec<u8>, manual: bool, draws: Vec<i64>, change: impl Fn(&mut TempusConfig)) -> Made {
    let mut c = good_config();
    change(&mut c);
    let key = fixture_key(32);
    let identity = NodeIdentity { seed: fixture_seed(32), certificate_der: test_certificate(&key, "bees tempus test node", 2).unwrap(), token,
                                  address: format!("127.0.0.1:{}", c.port) };
    let lines = Arc::new(Mutex::new(Vec::new()));
    let sink = lines.clone();
    let say: tempus::node::Lines = Arc::new(move |l: &str| sink.lock().unwrap().push(l.to_string()));
    let (tx, events) = channel();
    let tell: tempus::node::Events = Box::new(move |e| {
        let _ = tx.send(e);
    });
    let (clock, timers) = (Arc::new(ManualClock::new(Some(1500))), Arc::new(ManualTimers::new()));
    let node = if manual {
        TempusNode::with_sources(c, identity, Sources { clock: clock.clone(), timers: timers.clone(), random: Arc::new(ListRandom::new(draws)) }, say, tell)
    } else {
        TempusNode::new(c, identity, say, tell)
    };
    Made { node, lines, events, clock, timers }
}

fn token_of(first: u8, typ: &str, nbf: i64, exp: i64) -> Vec<u8> {
    make_test_token(&fixture_key(0), "k1", fixture_key(first).public(), typ, nbf, exp).unwrap()
}

fn boot(what: &str, want: &str, token: Vec<u8>, manual: bool, change: impl Fn(&mut TempusConfig)) {
    let m = make(token, manual, vec![0], change);
    match &m.node {
        Ok(_) => assert_eq!(want, "", "{}: the node was made, wanted the refusal: {}", what, want),
        Err(e) => {
            assert_eq!(e.0, want, "{}", what);
            assert_eq!(m.lines.lock().unwrap().join("|"), format!("tempus: boot refused: {}", want), "{}, the line", what);
        }
    }
}

#[test]
fn the_boot_refusals() {
    let good = || token_of(32, "tempus_edge", 1000, 2000);
    boot("a good start", "", good(), false, |_| {});
    boot("capacity", "tempus.edge.capacity: 0 is below 1 (bounds 1 to 256; never clamped)", good(), false, |c| c.edge.capacity = 0);
    boot("producer", "tempus.producer_key: the public key is not 32 bytes", good(), false, |c| c.producer_key = vec![1, 2, 3]);
    boot("token of another type", "the node's token is for another peer type than the node's", token_of(32, "tempus_sentinel", 1000, 2000), false, |_| {});
    boot("token of another key", "the node's token names another key", token_of(64, "tempus_edge", 1000, 2000), false, |_| {});
    let mut cut = good();
    cut.truncate(100);
    boot("a token that does not read", "the node's token does not read: truncated", cut, false, |_| {});
    boot("a test node on loopback", "", good(), true, |_| {});
    boot("a test node off loopback", "an externally driven node on a listen address that is not loopback", good(), true, |c| c.listen_address = "0.0.0.0".into());
    boot("a bridge", "tempus.role: bridge needs mode tempus-trust (a bridge runs TRUST and TEMPUS); this extension has no TRUST side and cannot be a bridge",
         token_of(32, "tempus_bridge", 1000, 2000), false, |c| c.role = PeerType::Bridge);
    // the texts that are the Silica node's own are those trials/c4_tempus_boot recorded
    let recorded: Vec<String> = goldens("c4_tempus_boot", "dangerous_token").into_iter().chain(goldens("c4_tempus_boot", "dangerous_any"))
        .flat_map(|(_, t)| t.lines().map(|l| l.to_string()).collect::<Vec<_>>()).collect();
    for text in ["the node's token is for another peer type than the node's", "an externally driven node on a listen address that is not loopback"] {
        assert!(recorded.contains(&format!("tempus: boot refused: {}", text)), "trials/c4_tempus_boot recorded: {}", text);
    }
}

fn wait_for(m: &Made, what: &str) {
    for _ in 0..500 {
        if m.lines.lock().unwrap().iter().any(|l| l.contains(what)) {
            return;
        }
        std::thread::sleep(Duration::from_millis(10));
    }
    panic!("the node did not write `{}`; its lines:\n{}", what, m.lines.lock().unwrap().join("\n"));
}

fn client_options() -> DialOptions {
    DialOptions { timeout: Duration::from_secs(5), nonce: None, shuffle_length: 3, verify_entries: true }
}

#[test]
fn a_node_in_this_process_served_by_hand() {
    // a first sentinel on 127.0.0.1, its clock 1500, its timers and draws the test's
    let cert = test_certificate(&fixture_key(32), "bees tempus test node", 2).unwrap();
    let (port, other_port) = (free_port(), free_port());
    let at = format!("127.0.0.1:{}", port);
    let m = make(token_of(32, "tempus_sentinel", 1000, 2000), true, vec![0, 1, 2, 3], |c| {
        c.role = PeerType::Sentinel;
        c.sentinels.clear();
        c.port = port;
        c.inflight_max = 2;
    });
    let node = m.node.as_ref().expect("the node is made");
    node.start();
    wait_for(&m, "join: no sentinel is configured");
    assert!(matches!(m.events.recv_timeout(Duration::from_secs(2)), Ok(NodeEvent::Listening { .. })));
    let verifier = Verifier::new(fixture_key(0).public().to_vec(), b"k1".to_vec(), Arc::new(|| 1500), 10, Some(vec![tempus::crypto::sha512(&cert)]));
    let edge = |first: u8| fixture_identity(first, "tempus_edge", 1000, 2000, Some("127.0.0.1:25799"), "k1", None, None).unwrap();
    // a sample: the sentinel answers with nothing and then holds the asker
    let out = dial(&at, &edge(64), &verifier, &frames::sample("tempus_edge", 3).unwrap(), client_options());
    assert_eq!(out.line(), format!("reply sample_reply entries=[] store=tempus_edge peer={} typ=tempus_sentinel", tempus::crypto::hex(&node.peer_id()[..8])));
    let out = dial(&at, &edge(96), &verifier, &frames::sample("tempus_edge", 3).unwrap(), client_options());
    match out.frame {
        Some(Frame::SampleReply { entries, .. }) => assert_eq!(entries.iter().map(|e| e.d.id.clone()).collect::<Vec<_>>(), vec![edge(64).peer_id()]),
        other => panic!("a sample reply was due: {:?}", other),
    }
    assert_eq!(node.peers(PeerType::Edge, 2).len(), 2, "the application gets peers of a store");
    assert_eq!(node.peers(PeerType::Bridge, 2).len(), 0);
    // a call: no bridge
    let out = dial(&at, &edge(64), &verifier, &frames::call_frame("call", b"1", "m", "f", &[1]).unwrap(), client_options());
    assert_eq!((out.what.as_str(), out.stage.as_str()), ("closed", "reply"));
    wait_for(&m, "request_refused peer=");
    // a raw tick frame: a frame of no kind to a node that holds no test atom
    let tick = tempus::etf::etf_encode(&tempus::etf::Term::map(vec![("t", tempus::etf::Term::atom("tick")), ("store", tempus::etf::Term::atom("tempus_edge"))])).unwrap();
    let out = dial(&at, &edge(64), &verifier, &tick, client_options());
    assert_eq!((out.what.as_str(), out.stage.as_str()), ("closed", "reply"));
    wait_for(&m, "protocol_error peer=1fae2ad7f75a0ded not a request: unknown_atom");
    // the clock cannot be read: under pause every accepted connection is closed at once
    m.clock.set(None);
    assert!(m.timers.fire(TimerPurpose::ClockRead));
    wait_for(&m, "clock: the system clock could not be read: the node admits no connection and does not tick until it is read again");
    let out = dial(&at, &edge(64), &verifier, &frames::sample("tempus_edge", 3).unwrap(), client_options());
    assert_eq!((out.what.as_str(), out.stage.as_str()), ("closed", "advert"));
    wait_for(&m, "clock_refused peer=- the system clock cannot be read: closed at once");
    m.clock.set(Some(1501));
    assert!(m.timers.fire(TimerPurpose::ClockRead));
    wait_for(&m, "clock: the system clock is read again");
    // no draws: a tick is skipped whole
    let none = make(token_of(32, "tempus_sentinel", 1000, 2000), true, vec![], |c| {
        c.role = PeerType::Sentinel;
        c.sentinels.clear();
        c.port = other_port;
    });
    let n2 = none.node.as_ref().unwrap();
    n2.start();
    wait_for(&none, "join: no sentinel is configured");
    assert!(none.timers.fire(TimerPurpose::Tick(PeerType::Edge)));
    wait_for(&none, "tick tempus_edge: skipped (no draws)");
    // a listen address in use is said
    let busy = make(token_of(32, "tempus_sentinel", 1000, 2000), true, vec![0], |c| {
        c.role = PeerType::Sentinel;
        c.sentinels.clear();
        c.port = other_port;
    });
    busy.node.as_ref().unwrap().start();
    wait_for(&busy, "the listening link has gone down");
    n2.stop();
    node.stop();
}

#[test]
fn a_reply_must_be_the_reply_of_its_request() {
    use tempus::client::check_reply;
    let smp = frames::sample("tempus_edge", 2).unwrap();
    let me = fixture_identity(64, "tempus_edge", 1000, 2000, Some("127.0.0.1:1"), "k1", None, None).unwrap();
    let e = me.entry(1).unwrap();
    let reply = |f: Frame| check_reply(&smp, &f).err().map(|e| e.0);
    assert_eq!(reply(Frame::SampleReply { store: "tempus_edge".into(), entries: vec![e.clone(), e.clone()] }), None);
    assert_eq!(reply(Frame::SampleReply { store: "tempus_bridge".into(), entries: vec![] }).unwrap(), "the reply is for another store than the request");
    assert_eq!(reply(Frame::SampleReply { store: "tempus_edge".into(), entries: vec![e.clone(), e.clone(), e.clone()] }).unwrap(), "more entries than the sample asked for");
    assert_eq!(reply(Frame::ShuffleReply { store: "tempus_edge".into(), entries: vec![] }).unwrap(), "shuffle_reply where sample_reply was due");
    assert_eq!(reply(Frame::Done).unwrap(), "done where sample_reply was due");
    let shf = frames::shuffle("tempus_edge", &[e.clone()]).unwrap();
    assert!(check_reply(&shf, &Frame::ShuffleReply { store: "tempus_edge".into(), entries: vec![] }).is_ok());
    assert_eq!(check_reply(&shf, &Frame::SampleReply { store: "tempus_edge".into(), entries: vec![] }).unwrap_err().0, "sample_reply where shuffle_reply was due");
    assert_eq!(check_reply(&shf, &Frame::ShuffleReply { store: "tempus_sentinel".into(), entries: vec![] }).unwrap_err().0, "the reply is for another store than the request");
    let call = frames::call_frame("call", b"7", "m", "f", &[]).unwrap();
    let result = |id: &[u8]| frames::read_any(&tempus::etf::etf_encode(&tempus::etf::Term::map(vec![("t", tempus::etf::Term::atom("result")), ("ver", tempus::etf::Term::Int(1)),
        ("req_id", tempus::etf::Term::binary(id)), ("value", tempus::etf::Term::Int(5))])).unwrap(), 3).unwrap();
    assert!(check_reply(&call, &result(b"7")).is_ok());
    assert_eq!(check_reply(&call, &result(b"8")).unwrap_err().0, "the result is not for this call's req_id");
    assert_eq!(check_reply(&call, &Frame::Done).unwrap_err().0, "done where result was due");
}
