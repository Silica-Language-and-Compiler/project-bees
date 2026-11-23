// The program test/model_check.py runs: it answers, one line each, the calls of the view functions and of one store's
// steps that the check writes to its standard input, so that the Rust store rules can be compared with the two Python
// models of the BEES tools and replayed against the recorded outputs of trials/t0_tempus_view and t1_tempus_store.
// It depends on the library only.
//
// A request is fields separated by tabs: the operation, then NAME=VALUE fields. A list of entries is ID/D/AGE joined
// by commas, `-` when empty; draws are integers joined by commas, `-` for an empty list and `none` for no draws.
// A store step carries the store's whole state (view, sent, partner) and answers the state after it.
use std::collections::HashMap;
use std::io::{BufRead, Write};
use tempus::node::view::{self, Store, TickStep, ViewEntry};

type E = ViewEntry<String>;

fn entries(text: &str) -> Vec<E> {
    if text == "-" {
        return Vec::new();
    }
    text.split(',').map(|e| {
        let p: Vec<&str> = e.splitn(3, '/').collect();
        E { id: p[0].as_bytes().to_vec(), d: p[1].to_string(), age: p[2].parse().expect("an age") }
    }).collect()
}

fn show(v: &[E]) -> String {
    if v.is_empty() { "-".to_string() } else { v.iter().map(|e| format!("{}/{}/{}", String::from_utf8_lossy(&e.id), e.d, e.age)).collect::<Vec<_>>().join(",") }
}

fn draws(text: &str) -> Option<Vec<i64>> {
    match text {
        "none" => None,
        "-" => Some(Vec::new()),
        t => Some(t.split(',').map(|n| n.parse().expect("a draw")).collect()),
    }
}

fn main() {
    let stdin = std::io::stdin();
    let out = std::io::stdout();
    let mut out = out.lock();
    for line in stdin.lock().lines() {
        let line = line.expect("a line");
        let mut parts = line.split('\t');
        let op = parts.next().unwrap_or("");
        let f: HashMap<&str, &str> = parts.filter_map(|p| p.split_once('=')).collect();
        let get = |k: &str| *f.get(k).unwrap_or(&"-");
        let num = |k: &str| get(k).parse::<i64>().unwrap_or(0);
        let ents = |k: &str| entries(get(k));
        let ds = || draws(get("draws"));
        let me = get("self").as_bytes().to_vec();
        let store = || {
            let mut s: Store<String> = Store::new(me.clone(), get("selfd").to_string(), get("own") == "1", num("cap"), num("count"));
            s.view = ents("view");
            s.sent = ents("sent");
            s.partner = ents("partner").into_iter().next();
            s
        };
        let state = |s: &Store<String>| format!("{}\t{}\t{}", show(&s.view), show(&s.sent), show(s.partner.as_slice()));
        let answer = match op {
            "age_all" => show(&view::age_all(&ents("view"))),
            "select" => match view::select(&ents("view"), num("n"), &ds().unwrap_or_default()) {
                Some(s) => format!("{}\t{}\t{}", show(&[s.partner]), show(&s.sent), show(&s.rest)),
                None => "none".to_string(),
            },
            "reply_select" => {
                let (sent, rest) = view::reply_select(&ents("view"), num("n"), get("asker").as_bytes(), &ds().unwrap_or_default());
                format!("{}\t{}", show(&sent), show(&rest))
            }
            "merge" => show(&view::merge(&ents("view"), &ents("received"), &me, num("cap"))),
            "prefer_sent" => show(&view::prefer_sent(&ents("received"), &ents("sent"))),
            "backfill" => show(&view::backfill(&ents("view"), &ents("sent"), num("cap"))),
            "insert" => show(&view::insert(&ents("view"), &ents("received")[0], &me, num("cap"))),
            "sample" => show(&view::sample(&ents("view"), num("n"), &ds().unwrap_or_default())),
            "valid" => if view::valid(&ents("view"), &me, num("cap")) { "yes".to_string() } else { "no".to_string() },
            "store.tick" => {
                let mut s = store();
                let what = match s.tick(ds().as_deref()) {
                    TickStep::Skipped => "skipped".to_string(),
                    TickStep::Aged => "aged".to_string(),
                    TickStep::Empty => "empty".to_string(),
                    TickStep::Shuffle { partner, out } => format!("shuffle\t{}\t{}", show(&[partner]), show(&out)),
                };
                format!("{}\t{}", state(&s), what)
            }
            "store.failed" => {
                let mut s = store();
                s.failed();
                state(&s)
            }
            "store.reply" => {
                let mut s = store();
                s.reply(&ents("received"));
                state(&s)
            }
            "store.request" => {
                let mut s = store();
                let got = s.request(get("asker").as_bytes(), &ents("received"), ds().as_deref());
                format!("{}\t{}", state(&s), got.map(|g| show(&g)).unwrap_or_else(|| "refused".to_string()))
            }
            "store.sample" => {
                let s = store();
                let got = s.sample(num("n"), ds().as_deref());
                format!("{}\t{}", state(&s), got.map(|g| show(&g)).unwrap_or_else(|| "refused".to_string()))
            }
            "store.insert" => {
                let mut s = store();
                s.insert(&ents("received")[0]);
                state(&s)
            }
            "store.drop" => {
                let mut s = store();
                s.drop_peer(get("id").as_bytes());
                state(&s)
            }
            _ => "unknown op".to_string(),
        };
        writeln!(out, "{}", answer).expect("the answer is written");
        out.flush().expect("the answer is written");
    }
}
