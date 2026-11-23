//! The Rust TEMPUS extension: what an application written in Rust uses to be a TEMPUS client or a TEMPUS node.
//! An example only: not for production (README.md beside the workspace says what has and has not been reviewed).
//!
//! The client half: `etf` and `frames` (the wire), `crypto` (Ed25519, SHA-512, certificates), `admission` (an identity,
//! the verifier, the outcome of a connection), `client` (dial) and `listener` (the listening position).
//! The node half, built on it: the modules under `node`.
//!
//! This crate holds no test material: no fixed key, no token making, no clock a peer could set. The standard library
//! is its only Rust dependency; TLS and the cryptography come from the OpenSSL installed on the machine, declared in
//! `ffi` and called only from `crypto` and `tls`.

mod ffi;
mod tls;

pub mod admission;
pub mod client;
pub mod crypto;
pub mod etf;
pub mod frames;
pub mod listener;
pub mod node;

/// A body, a token or a peer that this side does not accept. The text says why.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Refused(pub String);

impl Refused {
    pub fn new(text: &str) -> Refused {
        Refused(text.to_string())
    }
}

impl std::fmt::Display for Refused {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

/// A fault of the caller or of the machine: a value that has no tempus/1 form, a key that could not be made.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Fault(pub String);

impl Fault {
    pub fn new(text: &str) -> Fault {
        Fault(text.to_string())
    }
}

impl std::fmt::Display for Fault {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for Refused {}
impl std::error::Error for Fault {}
