// The command line of the Rust TEMPUS extension's client half. An example only: not for production (README.md).
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
use std::collections::HashMap;
use std::io::{BufRead, Write};
use std::sync::Arc;
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use tempus::admission::{frame_line, Identity, Verifier};
use tempus::client::{dial, DialOptions};
use tempus::crypto::{certificate_der, hex, sha512, unhex, SigningKey};
use tempus::frames::{self, read_body, Entry};
use tempus::listener::{standard_answer, ListenOptions, Listener};
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

fn main() {
    let argv: Vec<String> = std::env::args().skip(1).collect();
    match argv.first().map(|s| s.as_str()) {
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
        _ => fail("usage: tempus-client read-hex | test-token | dial | listen (see the README)"),
    }
}
