//! The configuration of a node: the keys of the `tempus` section of bees.config (design section 11) as one value the
//! application builds, with the bounds and the refusal texts of tools/bees_tempus_conf.py and the boot refusals of
//! bees_tempus_node@boot_why. Nothing has a default and nothing is clamped: a value outside its bounds refuses the
//! start. Every field must be given: the struct has no Default, so leaving one out does not compile.
use super::clock::{ClockBack, ClockFail};
use crate::frames::read_token;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum PeerType {
    Edge,
    Bridge,
    Sentinel,
}

impl PeerType {
    pub const ALL: [PeerType; 3] = [PeerType::Edge, PeerType::Bridge, PeerType::Sentinel];

    /// The atom of the type on the wire: tempus_edge, tempus_bridge, tempus_sentinel.
    pub fn name(self) -> &'static str {
        match self {
            PeerType::Edge => "tempus_edge",
            PeerType::Bridge => "tempus_bridge",
            PeerType::Sentinel => "tempus_sentinel",
        }
    }

    /// The name of the role in the configuration: edge, bridge, sentinel.
    pub fn role(self) -> &'static str {
        &self.name()[7..]
    }

    pub fn from_name(s: &str) -> Option<PeerType> {
        PeerType::ALL.into_iter().find(|t| t.name() == s)
    }

    pub fn index(self) -> usize {
        match self {
            PeerType::Edge => 0,
            PeerType::Bridge => 1,
            PeerType::Sentinel => 2,
        }
    }
}

/// capacity, shuffle_length and tick_ms of one store.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct StoreConfig {
    pub capacity: i64,
    pub shuffle_length: i64,
    pub tick_ms: i64,
}

/// A sentinel the node joins through: an IPv4 literal and a port. Its TEMPUS certificate must be in the whitelist.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Sentinel {
    pub host: String,
    pub port: i64,
}

/// A configuration, or an identity, that the node refuses to start with. The text is what an operator reads.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ConfigRefused(pub String);

impl std::fmt::Display for ConfigRefused {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for ConfigRefused {}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TempusConfig {
    /// The node's own type, and the `typ` its token must carry. `Bridge` is refused: see refusal().
    pub role: PeerType,
    /// An IPv4 literal, or "localhost". "0.0.0.0" listens on every IPv4 interface.
    pub listen_address: String,
    pub port: i64,
    /// Required unless the node is the first sentinel (role sentinel): 1 to 16.
    pub sentinels: Vec<Sentinel>,
    pub edge: StoreConfig,
    pub bridge: StoreConfig,
    pub sentinel: StoreConfig,
    /// The one current producer key: its kid (1 to 64 bytes) and the 32-byte Ed25519 public key.
    pub producer_kid: Vec<u8>,
    pub producer_key: Vec<u8>,
    /// The `tempus` whitelist: the TEMPUS certificates (DER) of the bridges and sentinels this node accepts.
    pub whitelist: Vec<Vec<u8>>,
    pub shuffle_timeout_ms: i64,
    pub inflight_max: i64,
    pub clock_skew_ms: i64,
    pub clock_back: ClockBack,
    /// Required when clock_back is Stop; refused under Follow and Hold.
    pub clock_back_limit_s: Option<i64>,
    pub clock_fail: ClockFail,
    pub clock_read_ms: i64,
    pub join_retry_initial_ms: i64,
    pub join_retry_max_ms: i64,
}

fn bound(key: &str, v: i64, lo: i64, hi: i64) -> Option<String> {
    if v < lo {
        return Some(format!("tempus.{}: {} is below {} (bounds {} to {}; never clamped)", key, v, lo, lo, hi));
    }
    if v > hi {
        return Some(format!("tempus.{}: {} is above {} (bounds {} to {}; never clamped)", key, v, hi, lo, hi));
    }
    None
}

impl TempusConfig {
    pub fn store(&self, t: PeerType) -> StoreConfig {
        match t {
            PeerType::Edge => self.edge,
            PeerType::Bridge => self.bridge,
            PeerType::Sentinel => self.sentinel,
        }
    }

    /// True when the listen address is a loopback address.
    pub fn listens_on_loopback(&self) -> bool {
        self.listen_address == "localhost" || (is_ipv4(&self.listen_address) && self.listen_address.starts_with("127."))
    }

    /// None when a node may start with this configuration; else why not, as `tempus.KEY: text`, in the order and with
    /// the texts of tools/bees_tempus_conf.py.
    pub fn refusal(&self) -> Option<String> {
        if self.role == PeerType::Bridge {
            return Some("tempus.role: bridge needs mode tempus-trust (a bridge runs TRUST and TEMPUS); this extension has no TRUST side and cannot be a bridge".into());
        }
        if self.listen_address != "localhost" && !is_ipv4(&self.listen_address) {
            return Some(format!("tempus.listen_address: \"{}\" is not an IPv4 literal or localhost (this extension listens on IPv4 only)", self.listen_address));
        }
        for (key, v, lo, hi) in [("port", self.port, 1, 65535), ("shuffle_timeout_ms", self.shuffle_timeout_ms, 100, 60000),
                                 ("inflight_max", self.inflight_max, 1, 64), ("clock_skew_ms", self.clock_skew_ms, 0, 300000),
                                 ("join_retry_initial_ms", self.join_retry_initial_ms, 100, 3600000),
                                 ("join_retry_max_ms", self.join_retry_max_ms, 100, 3600000), ("clock_read_ms", self.clock_read_ms, 100, 60000)] {
            if let Some(why) = bound(key, v, lo, hi) {
                return Some(why);
            }
        }
        if self.join_retry_max_ms < self.join_retry_initial_ms {
            return Some("tempus.join_retry_max_ms: below join_retry_initial_ms".into());
        }
        match (self.clock_back, self.clock_back_limit_s) {
            (ClockBack::Stop, None) => return Some("tempus.clock_back_limit_s: required when clock_back is stop (no default)".into()),
            (ClockBack::Stop, Some(limit)) => {
                if let Some(why) = bound("clock_back_limit_s", limit, 0, 86400) {
                    return Some(why);
                }
            }
            (back, Some(_)) => {
                return Some(format!("tempus.clock_back_limit_s: clock_back is {}, so no step back stops the node: remove clock_back_limit_s (it is for clock_back stop only)", back.name()));
            }
            _ => {}
        }
        for t in PeerType::ALL {
            let (s, path) = (self.store(t), t.role());
            let why = bound(&format!("{}.capacity", path), s.capacity, 1, 256)
                .or_else(|| bound(&format!("{}.shuffle_length", path), s.shuffle_length, 1, 64))
                .or_else(|| bound(&format!("{}.tick_ms", path), s.tick_ms, 100, 3600000));
            if why.is_some() {
                return why;
            }
            if s.shuffle_length > s.capacity {
                return Some(format!("tempus.{}.shuffle_length: {} is above the capacity {}", path, s.shuffle_length, s.capacity));
            }
        }
        if self.producer_kid.is_empty() || self.producer_kid.len() > 64 {
            return Some("tempus.producer_key: the kid is not 1 to 64 bytes".into());
        }
        if self.producer_key.len() != 32 {
            return Some("tempus.producer_key: the public key is not 32 bytes".into());
        }
        if self.sentinels.is_empty() {
            if self.role != PeerType::Sentinel {
                return Some("tempus.sentinels: required unless the node is the first sentinel (role sentinel)".into());
            }
        } else if self.sentinels.len() > 16 {
            return Some("tempus.sentinels: expected a list of 1 to 16 {Host, Port}".into());
        }
        for s in &self.sentinels {
            if !is_ipv4(&s.host) {
                return Some(format!("tempus.sentinels: \"{}\" is not an IPv4 literal (this extension resolves no host name)", s.host));
            }
            if let Some(why) = bound("sentinels", s.port, 1, 65535) {
                return Some(why);
            }
        }
        None
    }
}

/// The node's TEMPUS identity, passed by the application as bytes: the 32-byte Ed25519 private seed, the certificate
/// self-signed over that key (DER), the producer's token, and the address other nodes dial ("a.b.c.d:port").
/// The node makes its key from the seed when it is created and keeps no copy of the seed.
#[derive(Clone)]
pub struct NodeIdentity {
    pub seed: Vec<u8>,
    pub certificate_der: Vec<u8>,
    pub token: Vec<u8>,
    pub address: String,
}

pub(crate) fn is_ipv4(s: &str) -> bool {
    let parts: Vec<&str> = s.split('.').collect();
    parts.len() == 4 && parts.iter().all(|p| !p.is_empty() && p.len() <= 3 && p.bytes().all(|c| c.is_ascii_digit()) && p.parse::<u32>().map(|n| n <= 255).unwrap_or(false))
}

/// An address this node dials: a dotted quad, a colon, a port of 1 to 65535 in decimal. A name is not resolved.
pub(crate) fn dialable(addr: &[u8]) -> bool {
    let text = match std::str::from_utf8(addr) {
        Ok(t) => t,
        Err(_) => return false,
    };
    let (host, port) = match text.split_once(':') {
        Some(x) => x,
        None => return false,
    };
    let quads: Vec<&str> = host.split('.').collect();
    if quads.len() != 4 || !quads.iter().all(|q| !q.is_empty() && q.len() <= 3 && q.bytes().all(|c| c.is_ascii_digit())) {
        return false;
    }
    if port.is_empty() || port.len() > 5 || !port.bytes().all(|c| c.is_ascii_digit()) {
        return false;
    }
    port.parse::<u32>().map(|p| (1..=65535).contains(&p)).unwrap_or(false)
}

/// What refuses a node's start from its identity (bees_tempus_node@boot_why, with its texts): None when it may start.
pub fn identity_refusal(role: PeerType, public_key: &[u8], token: &[u8]) -> Option<String> {
    let fields = match read_token(token) {
        Ok(t) => t.fields,
        Err(why) => return Some(format!("the node's token does not read: {}", why)),
    };
    if fields.typ != role.name() {
        return Some("the node's token is for another peer type than the node's".into());
    }
    if fields.sub != public_key {
        return Some("the node's token names another key".into());
    }
    None
}
