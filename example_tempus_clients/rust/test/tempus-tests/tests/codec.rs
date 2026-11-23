// The codec against the Silica frame unit and on its own. trials/t2_tempus_frames prints, for every frame and token it
// writes or mutates, a line `NAME hex HEX` and a line `NAME read: ...`. These tests build the same frames and tokens
// from the same inputs and require the same bytes, and read every HEX of every recorded golden and require the
// library's verdict. The test-only tick and clock frames are no part of the extension: it builds none, and must
// refuse each as a frame of no kind.
use std::collections::BTreeMap;
use tempus::crypto::{hex, unhex};
use tempus::etf::{etf_decode, etf_encode, Term, FRAME_MAX};
use tempus::frames::*;
use tempus::node::admit::body_kind;
use tempus_tests::goldens;

const ADDR: &str = "127.0.0.1:22801"; // a value in the frames only: nothing listens there

fn rep(ch: u8, n: usize) -> Vec<u8> {
    vec![ch; n]
}

fn tok(kid: &str, sub: &[u8], typ: &str, nbf: i64, exp: i64) -> Vec<u8> {
    let mut t = rep(b'S', 64);
    t.extend(token_payload(kid.as_bytes(), sub, typ, nbf, exp).unwrap());
    t
}

fn token() -> Vec<u8> {
    tok("k1", &rep(b'p', 32), "tempus_edge", 1000, 2000)
}

fn desc(id: Vec<u8>, public_key: Vec<u8>, addr: &str, token: Vec<u8>) -> Descriptor {
    Descriptor { id, public_key, addr: addr.as_bytes().to_vec(), token }
}

fn plain(id: Vec<u8>) -> Descriptor {
    desc(id, rep(b'p', 32), ADDR, token())
}

fn peer(ch: u8, age: i64) -> Entry {
    Entry { age, d: plain(rep(ch, 64)) }
}

fn built() -> BTreeMap<&'static str, Vec<u8>> {
    let three = vec![peer(b'A', 0), peer(b'B', 7), peer(b'C', 65535)];
    let mut four = vec![peer(b'D', 1)];
    four.extend(three.clone());
    let one = |d: Descriptor| shuffle("tempus_edge", &[Entry { age: 0, d }]).unwrap();
    let p = rep(b'p', 32);
    let mut m = BTreeMap::new();
    m.insert("advert", advert(&plain(rep(b'A', 64))).unwrap());
    m.insert("pop_challenge", challenge(&rep(b'N', 32)).unwrap());
    m.insert("pop_response", response(&rep(b'G', 64)).unwrap());
    m.insert("key_rotated", key_rotated(b"k2").unwrap());
    m.insert("shuffle", shuffle("tempus_edge", &three).unwrap());
    m.insert("shuffle_reply", shuffle_reply("tempus_bridge", &[]).unwrap());
    m.insert("sample", sample("tempus_sentinel", 2).unwrap());
    m.insert("sample_reply", sample_reply("tempus_sentinel", &[peer(b'B', 7)]).unwrap());
    m.insert("done", done().unwrap());
    m.insert("token", token());
    m.insert("token of a bridge", tok("producer-key-2026", &rep(b'q', 32), "tempus_bridge", 0, 1763424300));
    m.insert("token whose exp is not after nbf", tok("k1", &p, "tempus_edge", 2000, 2000));
    m.insert("token with a 31-byte sub", tok("k1", &rep(b'p', 31), "tempus_edge", 1000, 2000));
    m.insert("token with an empty kid", tok("", &p, "tempus_edge", 1000, 2000));
    m.insert("token with a 65-byte kid", tok(&"k".repeat(65), &p, "tempus_edge", 1000, 2000));
    m.insert("shuffle of four entries, shuffle length three", shuffle("tempus_edge", &four).unwrap());
    m.insert("entry of age 65536", shuffle("tempus_edge", &[peer(b'A', 65536)]).unwrap());
    m.insert("entry with a 63-byte id", one(plain(rep(b'A', 63))));
    m.insert("entry with a 31-byte pub", one(desc(rep(b'A', 64), rep(b'p', 31), ADDR, token())));
    m.insert("entry with a 2-byte addr", one(desc(rep(b'A', 64), p.clone(), "a:", token())));
    m.insert("entry with a 262-byte addr", one(desc(rep(b'A', 64), p.clone(), &"a".repeat(262), token())));
    m.insert("entry with a 64-byte token", one(desc(rep(b'A', 64), p.clone(), ADDR, rep(b'S', 64))));
    m.insert("advert with a 65-byte id", advert(&plain(rep(b'A', 65))).unwrap());
    m.insert("sample of 0", sample("tempus_edge", 0).unwrap());
    m.insert("sample of 4, shuffle length three", sample("tempus_edge", 4).unwrap());
    m.insert("nonce of 31 bytes", challenge(&rep(b'N', 31)).unwrap());
    m.insert("sig of 65 bytes", response(&rep(b'G', 65)).unwrap());
    m.insert("kid of no bytes", key_rotated(b"").unwrap());
    m
}

/// name -> (the bytes, the Silica reader's text) from one output of the trial
fn parse(text: &str) -> BTreeMap<String, (Vec<u8>, String)> {
    let (mut hexes, mut reads) = (BTreeMap::new(), BTreeMap::new());
    for line in text.lines() {
        if let Some((name, h)) = line.split_once(" hex ") {
            hexes.insert(name.to_string(), unhex(h).unwrap_or_default());
        } else if let Some(name) = line.strip_suffix(" hex") {
            hexes.insert(name.to_string(), Vec::new());
        } else if let Some((name, r)) = line.split_once(" read: ") {
            reads.insert(name.to_string(), r.to_string());
        }
    }
    hexes.into_iter().map(|(name, data)| {
        let r = reads.get(&name).cloned().unwrap_or_default();
        (name, (data, r))
    }).collect()
}

fn verdict(what: &str, data: &[u8]) -> Option<String> {
    if what.starts_with("token") { read_token(data).err().map(|e| e.0) } else { read_body(data, 3).err().map(|e| e.0) }
}

#[test]
fn the_frames_of_the_silica_frame_unit() {
    let test_only = "the library refuses it (unknown kind)";
    for (name, text) in goldens("t2_tempus_frames", "frames") {
        let seen = parse(&text);
        assert!(seen.len() >= 44, "{}: {} frames and tokens", name, seen.len());
        // the same bytes from the same inputs
        for (what, data) in built() {
            let theirs = seen.get(what).unwrap_or_else(|| panic!("{}: no line for {}", name, what));
            assert_eq!(hex(&theirs.0), hex(&data), "{}: same bytes: {}", name, what);
        }
        // the same verdict on every frame
        let mut test_only_seen = 0;
        for (what, (data, said)) in &seen {
            let why = verdict(what, data);
            if said.starts_with(test_only) {
                test_only_seen += 1;
                assert_eq!(why.as_deref(), Some("unknown kind"), "{}: the test-only frame `{}` is a frame of no kind", name, what);
                // and a node that holds no test atom says so before it looks at the kind
                assert_eq!(body_kind(data), Err("unknown_atom".to_string()), "{}: {}", name, what);
            } else {
                assert_eq!(why.is_none(), !said.contains("refused"), "{}: same verdict: {}: Silica says \"{}\", Rust says {:?}", name, what, said, why);
            }
        }
        assert!(test_only_seen >= 6, "{}: the golden holds the test-only frames the extension must refuse: {}", name, test_only_seen);
        // the same fields read
        match read_body(&seen["shuffle"].0, 3) {
            Ok(Frame::Shuffle { store, entries }) => {
                assert_eq!(store, "tempus_edge");
                let shown: Vec<String> = entries.iter().map(|e| format!("{}/{}:{}", String::from_utf8_lossy(&e.d.id[..4]), e.d.id.len(), e.age)).collect();
                assert_eq!(shown.join(" "), "AAAA/64:0 BBBB/64:7 CCCC/64:65535");
                assert!(seen["shuffle"].1.contains("AAAA/64:0 BBBB/64:7 CCCC/64:65535"), "{}: Silica read the same entries", name);
            }
            other => panic!("{}: the shuffle is read: {:?}", name, other),
        }
        let t = read_token(&seen["token"].0).expect("the token is read");
        assert_eq!((t.fields.kid.as_slice(), t.fields.typ.as_str(), t.fields.nbf, t.fields.exp, t.payload.len()), (&b"k1"[..], "tempus_edge", 1000, 2000, 98));
        assert!(seen["token"].1.contains("kid k1 sub pppp/32 typ 1 nbf 1000 exp 2000 payload of 98 bytes"), "{}: Silica read the same token", name);
    }
}

#[test]
fn round_trips_key_order_and_integers() {
    for (what, data) in built() {
        if !what.starts_with("token") {
            assert_eq!(etf_encode(&etf_decode(&data).unwrap()).unwrap(), data, "round trip: {}", what);
        }
    }
    let body = sample("tempus_edge", 1).unwrap();
    let at = |needle: &[u8]| body.windows(needle.len()).position(|w| w == needle).expect("the key is there");
    let (n, s, t) = (at(b"\x77\x01n"), at(b"\x77\x05store"), at(b"\x77\x01t"));
    assert!(n < s && s < t, "keys are written in name order: {} {} {}", n, s, t);
    assert_eq!(&frame(&done().unwrap()).unwrap()[..4], &[0, 0, 0, 15]);
    // integers, against bytes the Python extension wrote
    for (n, want) in [(0i64, "836100"), (255, "8361ff"), (256, "836200000100"), (-1, "8362ffffffff"), (2147483647, "83627fffffff"),
                      (-2147483648, "836280000000"), (2147483648, "836e040000000080"), (-2147483649, "836e040101000080"),
                      (9007199254740992, "836e070000000000000020"), (1763424000000, "836e060000d842949a01")] {
        assert_eq!(hex(&etf_encode(&Term::Int(n)).unwrap()), want, "the integer {}", n);
        assert_eq!(etf_decode(&unhex(want).unwrap()).unwrap(), Term::Int(n), "the integer {} read back", n);
    }
}

#[test]
fn trusts_frames_are_the_bytes_the_python_extension_writes() {
    assert_eq!(hex(&call_frame("call", b"1", "bees_c3", "add", &[2, 40]).unwrap()),
               "83740000000877016161027704617267736c00000002610261286a770166770361646477016d7707626565735f633377046f707473740000000077067265715f69646d0000000131770174770463616c6c77037665726101");
    assert_eq!(hex(&call_frame("cast", b"r9", "m", "f", &[]).unwrap()),
               "83740000000877016161007704617267736a77016677016677016d77016d77046f707473740000000077067265715f69646d00000002723977017477046361737477037665726101");
    let result = unhex("83740000000477067265715f69646d00000001317701747706726573756c74770576616c7565612a77037665726101").unwrap();
    let f = read_any(&result, ENTRIES_MAX).unwrap();
    assert_eq!(f.kind(), "result");
    assert_eq!(result_value(&f, b"1"), Ok(&Term::Int(42)));
    assert_eq!(result_value(&f, b"2").unwrap_err().0, "the result is not for this call's req_id");
    assert_eq!(result_value(&Frame::Done, b"1").unwrap_err().0, "done where result was due");
    assert_eq!(read_body(&result, 3).unwrap_err().0, "unknown kind", "a result is no tempus/1 kind for the strict reader");
    assert!(call_frame("call", &rep(b'r', 17), "m", "f", &[]).is_err(), "a request id above 16 bytes is not written");
    assert!(call_frame("call", b"", "m", "f", &[]).is_err());
    assert!(call_frame("tick", b"1", "m", "f", &[]).is_err());
}

#[test]
fn what_the_reader_refuses() {
    let mut trailing = done().unwrap();
    trailing.push(0);
    for (bad, why) in [(vec![], "truncated"), (vec![0x82], "bad_version"), (trailing, "trailing_bytes"), (vec![0x83, 0x68, 0x00], "bad_tag"),
                       (vec![0x83, 0x74, 0, 0, 0, 1, 0x61, 1, 0x61, 1], "bad_tag")] {
        assert_eq!(read_body(&bad, 3).unwrap_err().0, why, "the reader refuses {}", hex(&bad));
    }
    let mut twice = vec![0x83, 0x74, 0, 0, 0, 2];
    for _ in 0..2 {
        twice.extend_from_slice(b"\x77\x01t\x77\x04done");
    }
    assert_eq!(read_body(&twice, 3).unwrap_err().0, "duplicate_field");
    let mut deep = vec![0x83];
    for _ in 0..8 {
        deep.extend_from_slice(&[0x6c, 0, 0, 0, 1]);
    }
    deep.extend(rep(0x6a, 9));
    assert_eq!(etf_decode(&deep).unwrap_err().0, "too_deep");
    assert_eq!(etf_decode(&rep(0x83, FRAME_MAX + 1)).unwrap_err().0, "too_large");
    assert!(frame(&rep(0, FRAME_MAX + 1)).is_err(), "a body above the ceiling is not framed");
    // what a peer can send and a reader must refuse, not fail on
    assert_eq!(etf_decode(&[0x83, 0x77, 2, 0xff, 0xfe]).unwrap_err().0, "bad_atom", "an atom that is not UTF-8");
    assert_eq!(etf_decode(&[0x83, 0x6d, 0xff, 0xff, 0xff, 0xff, 1]).unwrap_err().0, "truncated", "a length that runs past the frame");
    assert_eq!(etf_decode(&[0x83, 0x6c, 0x7f, 0xff, 0xff, 0xff]).unwrap_err().0, "truncated");
    assert_eq!(etf_decode(&[0x83, 0x46, 0, 0, 0, 0, 0, 0, 0, 0]).unwrap_err().0, "bad_tag", "a float");
    assert_eq!(etf_decode(&[0x83, 0x6e, 9, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1]).unwrap_err().0, "unsupported", "an integer above 64 bits");
}

#[test]
fn the_nodes_structure_check() {
    assert_eq!(body_kind(&sample("tempus_edge", 1).unwrap()), Ok("sample".to_string()));
    assert_eq!(body_kind(&call_frame("call", b"1", "m", "f", &[1]).unwrap()), Ok("call".to_string()));
    assert_eq!(body_kind(b"hello"), Err("bad_version".to_string()));
    assert_eq!(body_kind(&[131, 116, 0]), Err("truncated".to_string()));
    assert_eq!(body_kind(&[131, 108, 0, 0, 0, 1, 106, 106]), Err("bad_tag".to_string()));
    assert_eq!(body_kind(&[131, 116, 0, 0, 0, 17, 0, 0]), Err("too_long".to_string()));
    let tick = etf_encode(&Term::map(vec![("t", Term::atom("tick")), ("store", Term::atom("tempus_edge"))])).unwrap();
    assert_eq!(body_kind(&tick), Err("unknown_atom".to_string()), "a node holds no atom of the test frames");
    let no_kind = etf_encode(&Term::map(vec![("t", Term::atom("ok"))])).unwrap();
    assert_eq!(body_kind(&no_kind), Err("unknown kind".to_string()));
    let no_t = etf_encode(&Term::map(vec![("n", Term::Int(1))])).unwrap();
    assert_eq!(body_kind(&no_t), Err("unknown kind".to_string()));
}

#[test]
fn the_wire_atoms_are_those_of_the_two_atom_files() {
    let mut want: Vec<String> = Vec::new();
    for path in ["src/tempus/bees_tempus.atoms", "src/trust/bees_trust.atoms"] {
        for line in tempus_tests::read(path).lines() {
            let line = line.trim();
            if !line.is_empty() && !line.starts_with('#') && !want.iter().any(|w| w == line) {
                want.push(line.to_string());
            }
        }
    }
    want.sort();
    let mut have: Vec<String> = tempus::node::admit::WIRE_ATOMS.iter().map(|s| s.to_string()).collect();
    have.sort();
    assert_eq!(have, want);
    // a call that names a module the node holds no atom for is refused before its kind is looked at
    assert_eq!(body_kind(&call_frame("call", b"1", "demo", "add", &[1, 2]).unwrap()), Err("unknown_atom".to_string()));
    // an atom of the rejection list is held: such a frame is sound, and of no kind
    assert_eq!(body_kind(&etf_encode(&Term::map(vec![("t", Term::atom("truncated"))])).unwrap()), Err("unknown kind".to_string()));
}
