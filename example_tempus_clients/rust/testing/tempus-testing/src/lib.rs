//! TEST ONLY: keys, tokens and identities from fixed seeds that are written in this repository. Anyone can reproduce
//! them. They exist so that the unit tests and the trials can be repeated; an extension never makes or signs a token
//! (the producer does), and never takes its key from a fixed seed.
use std::sync::Arc;
use tempus::admission::Identity;
use tempus::crypto::{self_signed_certificate, SigningKey, Validity};
use tempus::frames::token_payload;
use tempus::Fault;

pub mod sources;

/// TEST ONLY: the dates tools/bees_tempus_certs.py gives its certificates.
pub const TEST_VALIDITY: Validity<'static> = Validity { not_before: "260101000000Z", not_after: "460101000000Z" };

/// TEST ONLY: the 32 bytes first, first+1, ... (a seed that belongs to nobody).
pub fn fixture_seed(first: u8) -> Vec<u8> {
    (0..32u8).map(|i| first.wrapping_add(i)).collect()
}

/// TEST ONLY: the key of fixture_seed(first).
pub fn fixture_key(first: u8) -> SigningKey {
    SigningKey::from_seed(&fixture_seed(first)).expect("a 32-byte seed makes a key")
}

/// TEST ONLY: a token signed with a producer's private key. The producer's signature is over the payload bytes.
pub fn make_test_token(producer: &SigningKey, kid: &str, sub: &[u8], typ: &str, nbf: i64, exp: i64) -> Result<Vec<u8>, Fault> {
    let payload = token_payload(kid.as_bytes(), sub, typ, nbf, exp)?;
    let mut token = producer.sign(&payload)?;
    token.extend_from_slice(&payload);
    Ok(token)
}

/// TEST ONLY: a certificate self-signed over the key, with the dates of the test certificates.
pub fn test_certificate(key: &SigningKey, common_name: &str, serial: i64) -> Result<Vec<u8>, Fault> {
    self_signed_certificate(key, common_name, serial, &TEST_VALIDITY)
}

/// TEST ONLY: the identity of seed first..first+31 with a token signed by `producer`, or by the test producer (seed
/// 00..1f, the one of tools/bees_tempus_fixtures.py) when None; `cert_der` None makes a certificate.
pub fn fixture_identity(first: u8, typ: &str, nbf: i64, exp: i64, addr: Option<&str>, kid: &str, producer: Option<&SigningKey>,
                        cert_der: Option<Vec<u8>>) -> Result<Identity, Fault> {
    let key = fixture_key(first);
    let own;
    let producer = match producer {
        Some(p) => p,
        None => {
            own = fixture_key(0);
            &own
        }
    };
    let token = make_test_token(producer, kid, key.public(), typ, nbf, exp)?;
    let cert = match cert_der {
        Some(c) => c,
        None => test_certificate(&key, "bees tempus example client", 1)?,
    };
    Ok(Identity::new(Arc::new(key), token, addr.map(|s| s.to_string()), cert))
}
