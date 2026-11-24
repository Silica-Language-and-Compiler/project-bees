// Ed25519 against RFC 8032 and against the vectors the Python extension made (native/tempus/selftest/vectors.h), the
// certificates of tools/bees_tempus_certs.py byte for byte, the client's verifier, and admission as the node judges
// it against every case of trials/t4_tempus_admission. Keys and tokens are TEST ONLY, from fixed seeds.
use std::collections::BTreeMap;
use std::sync::Arc;
use tempus::admission::Verifier;
use tempus::crypto::*;
use tempus::frames::Descriptor;
use tempus::node::admit;
use tempus::node::config::PeerType;
use tempus_testing::{fixture_identity, fixture_key, make_test_token, test_certificate};
use tempus_tests::{goldens, read};

const ADDR: &str = "127.0.0.1:22801";

#[test]
fn ed25519_is_rfc_8032_test_1() {
    let k = SigningKey::from_seed(&unhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60").unwrap()).unwrap();
    assert_eq!(hex(k.public()), "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a");
    assert_eq!(hex(&k.sign(&[]).unwrap()),
               "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b");
    assert!(ed25519_verify(k.public(), &[], &k.sign(&[]).unwrap()));
    assert!(!ed25519_verify(k.public(), &[1], &k.sign(&[]).unwrap()));
    assert!(SigningKey::from_seed(&[1, 2, 3]).is_err());
    assert_eq!(random_bytes(32).unwrap().len(), 32);
    assert_ne!(random_bytes(32).unwrap(), random_bytes(32).unwrap());
}

fn vector(name: &str) -> Vec<u8> {
    let text = read("native/tempus/selftest/vectors.h");
    let a = text.find(&format!(" {}[", name)).unwrap_or_else(|| panic!("no vector {}", name));
    let open = a + text[a..].find('{').unwrap();
    let close = open + text[open..].find('}').unwrap();
    text[open + 1..close].split(',').filter_map(|s| s.trim().parse().ok()).collect()
}

fn verifier(now: i64, skew: i64, kid: &str, producer: &SigningKey) -> Verifier {
    Verifier::new(producer.public().to_vec(), kid.as_bytes().to_vec(), Arc::new(move || now), skew, None)
}

#[test]
fn the_vectors_of_the_python_extension_and_the_verifier() {
    let (producer, node) = (fixture_key(0), fixture_key(32));
    assert_eq!(vector("token").len(), 162);
    assert_eq!(producer.public(), vector("producer_pub"));
    assert_eq!(node.public(), vector("node_pub"));
    assert_eq!(peer_id(node.public()), vector("node_id"));
    let t = make_test_token(&producer, "k1", node.public(), "tempus_edge", 1000, 2000).unwrap();
    assert_eq!(t, vector("token"), "a token with the TEST ONLY keys is the Python extension's, byte for byte");
    let me = fixture_identity(32, "tempus_edge", 1000, 2000, Some(ADDR), "k1", None, None).unwrap();
    assert_eq!(me.prove(&vector("nonce")).unwrap(), vector("pop_sig"), "the proof of possession signs nonce || token");

    let v = |now, skew| verifier(now, skew, "k1", &producer);
    let why = |v: &Verifier, d: &Descriptor, cert: Option<&[u8]>| v.check_descriptor(d, cert).err().map(|e| e.0);
    let d = me.descriptor(None).unwrap();
    assert_eq!(why(&v(1500, 0), &d, None), None);
    for (now, skew, ok) in [(999, 0, false), (999, 1, true), (2000, 0, false), (2000, 1, true), (2001, 1, false)] {
        assert_eq!(why(&v(now, skew), &d, None).is_none(), ok, "the window at {} with skew {}", now, skew);
    }
    assert_eq!(why(&v(989, 10), &d, None).unwrap(), "the token is not valid yet");
    assert_eq!(why(&v(2010, 10), &d, None).unwrap(), "the token has expired");
    assert_eq!(why(&verifier(1500, 0, "k2", &producer), &d, None).unwrap(), "key_rotated");
    assert_eq!(why(&verifier(5000, 0, "k2", &node), &d, None).unwrap(), "key_rotated", "another kid comes before every other fault");
    assert_eq!(why(&verifier(1500, 0, "k1", &node), &d, None).unwrap(), "the signature does not verify");
    let mut flipped = d.clone();
    flipped.token[70] ^= 1;
    assert!(why(&v(1500, 0), &flipped, None).is_some(), "a changed payload");
    let mut other_id = d.clone();
    other_id.id = peer_id(producer.public());
    assert_eq!(why(&v(1500, 0), &other_id, None).unwrap(), "id is not the SHA-512 of pub");
    let third = fixture_identity(128, "tempus_edge", 1000, 2000, Some(ADDR), "k1", None, None).unwrap();
    let mut other_sub = d.clone();
    other_sub.token = third.token.clone();
    assert_eq!(why(&v(1500, 0), &other_sub, None).unwrap(), "sub is not the peer's key");
    let mut only_bridges = v(1500, 0);
    only_bridges.types = vec!["tempus_bridge".into(), "tempus_sentinel".into()];
    assert_eq!(why(&only_bridges, &d, None).unwrap(), "typ is not allowed");
    let mut cut = d.clone();
    cut.token.pop();
    assert_eq!(why(&v(1500, 0), &cut, None).unwrap(), "truncated");
    // the channel binding: every field of the descriptor verifies, and the certificate is another key's
    assert_eq!(why(&v(1500, 0), &d, Some(&me.cert_der)), None);
    assert_eq!(why(&v(1500, 0), &d, Some(&third.cert_der)).unwrap(), "the certificate's key is not the advert's pub");
    // the whitelist rule for a peer whose token says bridge or sentinel
    let sentinel = fixture_identity(64, "tempus_sentinel", 1000, 2000, Some(ADDR), "k1", None, None).unwrap();
    let sd = sentinel.descriptor(None).unwrap();
    let mut listed = v(1500, 0);
    listed.whitelist = Some(vec![sha512(&third.cert_der)]);
    assert_eq!(why(&listed, &sd, Some(&sentinel.cert_der)).unwrap(), "the certificate of a tempus_sentinel is not in the whitelist");
    listed.whitelist = Some(vec![sha512(&sentinel.cert_der)]);
    assert_eq!(why(&listed, &sd, Some(&sentinel.cert_der)), None);
    assert_eq!(why(&listed, &fixture_identity(64, "tempus_edge", 1000, 2000, Some(ADDR), "k1", None, None).unwrap().descriptor(None).unwrap(), Some(&sentinel.cert_der)).unwrap(),
               "a certificate of the whitelist with a token whose typ is tempus_edge", "the rule holds the other way too");
    // the binding is judged first: another key's certificate, and a token that has expired too
    assert_eq!(why(&v(5000, 0), &d, Some(&third.cert_der)).unwrap(), "the certificate's key is not the advert's pub");
    listed.whitelist = Some(vec![]);
    assert_eq!(why(&listed, &d, Some(&me.cert_der)), None, "an edge needs no entry in the whitelist");
    // the proof of possession
    let nonce = vec![b'N'; 32];
    let proof = me.prove(&nonce).unwrap();
    assert!(v(1500, 0).check_proof(me.public_key(), &nonce, &t, &proof).is_ok());
    assert_eq!(v(1500, 0).check_proof(me.public_key(), &[b'M'; 32], &t, &proof).unwrap_err().0, "the proof of possession does not verify");
    let mut message = nonce.clone();
    message.extend_from_slice(&t);
    assert!(v(1500, 0).check_proof(me.public_key(), &nonce, &t, &third.key.sign(&message).unwrap()).is_err());
    // entries
    assert!(v(1500, 0).check_entry(&me.entry(3).unwrap(), "tempus_edge").is_ok());
    assert_eq!(v(1500, 0).check_entry(&me.entry(3).unwrap(), "tempus_bridge").unwrap_err().0, "the entry's typ is not the store's");
}

#[test]
fn the_certificates_of_the_tool_byte_for_byte() {
    let seeds = [("bridge", 160u8), ("node", 32), ("other", 64), ("sentinel", 128), ("x1", 176), ("x2", 192), ("x3", 208), ("x4", 224)];
    for (i, (name, first)) in seeds.iter().enumerate() {
        let pem = read(&format!("trials/t5_tempus_tls/certs/{}.pem", name));
        let der = certificate_der(&pem).expect("the file holds a certificate");
        let key = fixture_key(*first);
        let made = test_certificate(&key, &format!("bees tempus test {}", name), i as i64 + 1).unwrap();
        assert_eq!(hex(&made), hex(&der), "the certificate of {} is the tool's, byte for byte", name);
        assert_eq!(certificate_pem(&made), pem, "the PEM of {}", name);
        assert_eq!(certificate_key(&der).unwrap(), key.public());
    }
    let p256 = certificate_der(&read("trials/t5_tempus_tls/certs/p256.pem")).unwrap();
    assert_eq!(certificate_key(&p256).unwrap_err().0, "the certificate's key is not Ed25519");
    assert_eq!(certificate_key(&[1, 2, 3]).unwrap_err().0, "the certificate cannot be read");
    // a certificate whose issuer signed with another key is not self-signed: the signature is changed in its last byte
    let mut forged = certificate_der(&read("trials/t5_tempus_tls/certs/node.pem")).unwrap();
    let last = forged.len() - 1;
    forged[last] ^= 1;
    assert_eq!(certificate_key(&forged).unwrap_err().0, "the certificate is not self-signed");
    // a fingerprint names a certificate, not a key: a new certificate over the same key is another entry
    let key = fixture_key(32);
    assert_ne!(sha512(&test_certificate(&key, "a", 1).unwrap()), sha512(&test_certificate(&key, "a", 2).unwrap()));
}

#[test]
fn every_case_of_the_admission_trial_with_the_silica_reason() {
    let (producer, other, node) = (fixture_key(0), fixture_key(96), fixture_key(32));
    let desc = |token: Vec<u8>, id: Option<Vec<u8>>| Descriptor { id: id.unwrap_or_else(|| sha512(node.public())), public_key: node.public().to_vec(),
                                                                 addr: b"127.0.0.1:1".to_vec(), token };
    let tok = |typ: &str, nbf: i64, exp: i64, kid: &str, by: &SigningKey, sub: &[u8]| make_test_token(by, kid, sub, typ, nbf, exp).unwrap();
    let edge = |nbf, exp| tok("tempus_edge", nbf, exp, "k1", &producer, node.public());
    // the node's verdict in the words of the trial: "admitted" or "refused: WHY"
    let verdict = |d: &Descriptor, want: PeerType| {
        let why = admit::entry(d, b"k1", producer.public(), 1500, 10, Some(want));
        if why.is_empty() { "admitted".to_string() } else { format!("refused: {}", why) }
    };
    let e = PeerType::Edge;
    let mut got: Vec<(&str, String)> = vec![
        ("a good edge token", verdict(&desc(edge(1000, 2000), None), e)),
        ("expired", verdict(&desc(edge(1000, 1400), None), e)),
        ("not valid yet", verdict(&desc(edge(1800, 2000), None), e)),
        ("expired, inside the skew", verdict(&desc(edge(1000, 1495), None), e)),
        ("not valid yet, inside the skew", verdict(&desc(edge(1505, 2000), None), e)),
        ("expired at exactly exp plus skew", verdict(&desc(edge(1000, 1490), None), e)),
        ("under another kid", verdict(&desc(tok("tempus_edge", 1000, 2000, "k0", &other, node.public()), None), e)),
        ("under another kid and expired too", verdict(&desc(tok("tempus_edge", 1000, 1400, "k0", &other, node.public()), None), e)),
        ("signed by a key that is not the producer's", verdict(&desc(tok("tempus_edge", 1000, 2000, "k1", &other, node.public()), None), e)),
        ("sub is another key", verdict(&desc(tok("tempus_edge", 1000, 2000, "k1", &producer, other.public()), None), e)),
        ("a bridge token where an edge is wanted", verdict(&desc(tok("tempus_bridge", 1000, 2000, "k1", &producer, node.public()), None), e)),
        ("a bridge token where a bridge is wanted", verdict(&desc(tok("tempus_bridge", 1000, 2000, "k1", &producer, node.public()), None), PeerType::Bridge)),
        ("id is not the hash of pub", verdict(&desc(edge(1000, 2000), Some(sha512(other.public()))), e)),
    ];
    // nbf 1000 becomes 1001 after the signature was made: the atom nbf, the tag 98 and four bytes
    let mut changed = edge(1000, 2000);
    let at = changed.windows(3).position(|w| w == b"nbf").unwrap();
    changed[at + 7] ^= 1;
    got.push(("payload changed after signing", verdict(&desc(changed, None), e)));
    let mut cut = edge(1000, 2000);
    cut.truncate(cut.len() - 3);
    got.push(("token cut short", verdict(&desc(cut, None), e)));
    let (good, nonce) = (edge(1000, 2000), vec![7u8; 32]);
    let sign = |k: &SigningKey, nonce: &[u8], token: &[u8]| {
        let mut m = nonce.to_vec();
        m.extend_from_slice(token);
        k.sign(&m).unwrap()
    };
    let proof = sign(&node, &nonce, &good);
    let pop = |ok: bool| if ok { "admitted".to_string() } else { "refused: the signature does not verify".to_string() };
    got.push(("proof of possession", pop(admit::proof(node.public(), &nonce, &good, &proof))));
    got.push(("proof for another nonce", pop(admit::proof(node.public(), &[8u8; 32], &good, &proof))));
    got.push(("proof by another key", pop(admit::proof(node.public(), &nonce, &good, &sign(&other, &nonce, &good)))));
    got.push(("proof over another token", pop(admit::proof(node.public(), &nonce, &edge(1000, 2500), &proof))));
    for (name, text) in goldens("t4_tempus_admission", "dangerous_admit") {
        let want: BTreeMap<&str, &str> = text.lines().filter_map(|l| l.split_once(": ")).collect();
        assert_eq!(want.len(), 20, "{}: the admission trial's recorded output has 20 cases", name);
        for (label, verdict) in &got {
            assert_eq!(Some(&verdict.as_str()), want.get(label), "{}: admission, {}", name, label);
        }
        // the twentieth case compares a signature with a fixture of that trial: the same signature is the vector above
        assert_eq!(got.len(), 19);
    }
}

#[test]
fn the_order_of_an_adverts_checks_and_the_whitelist_rule() {
    let (producer, other, node) = (fixture_key(0), fixture_key(96), fixture_key(32));
    // a token under another kid that is also expired, for another key, with a wrong id: key_rotated comes first
    let t = make_test_token(&other, "k0", other.public(), "tempus_edge", 1000, 1400).unwrap();
    let d = Descriptor { id: vec![0; 64], public_key: node.public().to_vec(), addr: b"127.0.0.1:1".to_vec(), token: t };
    assert_eq!(admit::pre(&d, b"k1", 1500, 10, None).why, "key_rotated");
    // expired and for another key: the time comes before sub
    let t = make_test_token(&producer, "k1", other.public(), "tempus_edge", 1000, 1400).unwrap();
    let d = Descriptor { id: vec![0; 64], public_key: node.public().to_vec(), addr: b"127.0.0.1:1".to_vec(), token: t };
    assert_eq!(admit::pre(&d, b"k1", 1500, 10, None).why, "the token has expired");
    // for another key and a wrong id: sub comes before the id
    let t = make_test_token(&producer, "k1", other.public(), "tempus_edge", 1000, 2000).unwrap();
    let d = Descriptor { id: vec![0; 64], public_key: node.public().to_vec(), addr: b"127.0.0.1:1".to_vec(), token: t };
    assert_eq!(admit::pre(&d, b"k1", 1500, 10, None).why, "sub is not the peer's key");
    // a wrong id and a signature that does not verify: the id comes first
    let t = make_test_token(&other, "k1", node.public(), "tempus_edge", 1000, 2000).unwrap();
    let d = Descriptor { id: vec![0; 64], public_key: node.public().to_vec(), addr: b"127.0.0.1:1".to_vec(), token: t };
    let p = admit::pre(&d, b"k1", 1500, 10, None);
    assert_eq!(p.why, "");
    assert_eq!(admit::keys(&d, &p.payload, &p.sig, producer.public()), "id is not the SHA-512 of pub");
    let short = Descriptor { id: vec![0; 63], ..d.clone() };
    assert_eq!(admit::pre(&short, b"k1", 1500, 10, None).why, "a field of the descriptor has a wrong length");
    // the whitelist rule, both sides (rulings OQ-3, NQ-4), with the connection actor's texts
    assert_eq!(admit::whitelist("tempus_edge", false), "");
    assert_eq!(admit::whitelist("tempus_sentinel", true), "");
    assert_eq!(admit::whitelist("tempus_bridge", false), "a tempus_bridge or tempus_sentinel token under a certificate that is not in the tempus whitelist");
    assert_eq!(admit::whitelist("tempus_edge", true), "a certificate of the tempus whitelist with a token whose typ is not tempus_bridge or tempus_sentinel");
}
