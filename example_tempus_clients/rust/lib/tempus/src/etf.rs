//! The Erlang external term format, the subset tempus/1 uses: maps with atom keys, atoms, binaries, integers, lists.
//! Written from development-plan/tempus-design.md section 5 and example_tempus_clients/writing-a-tempus-client.md.
use crate::{Fault, Refused};
use std::collections::BTreeMap;

/// The greatest body of a frame, in bytes.
pub const FRAME_MAX: usize = 131072;

/// One term. A map's keys are atoms, held by name; a BTreeMap keeps them in the byte order of their names, which is
/// the order they are written in, so every frame has exactly one byte form.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Term {
    Atom(String),
    Int(i64),
    Binary(Vec<u8>),
    List(Vec<Term>),
    Map(BTreeMap<String, Term>),
}

impl Term {
    pub fn atom(name: &str) -> Term {
        Term::Atom(name.to_string())
    }

    pub fn binary(bytes: &[u8]) -> Term {
        Term::Binary(bytes.to_vec())
    }

    pub fn map(fields: Vec<(&str, Term)>) -> Term {
        Term::Map(fields.into_iter().map(|(k, v)| (k.to_string(), v)).collect())
    }
}

pub(crate) fn be32(n: usize) -> [u8; 4] {
    (n as u32).to_be_bytes()
}

fn encode_into(term: &Term, out: &mut Vec<u8>) -> Result<(), Fault> {
    match term {
        Term::Atom(name) => {
            let raw = name.as_bytes();
            if raw.len() > 255 {
                return Err(Fault::new("atom too long for tempus/1"));
            }
            out.push(0x77);
            out.push(raw.len() as u8);
            out.extend_from_slice(raw);
        }
        Term::Int(n) => {
            let n = *n;
            if (0..=255).contains(&n) {
                out.extend_from_slice(&[0x61, n as u8]);
            } else if (-2147483648..=2147483647).contains(&n) {
                out.push(0x62);
                out.extend_from_slice(&(n as i32).to_be_bytes());
            } else {
                let mut mag = n.unsigned_abs();
                let mut digits = Vec::new();
                while mag > 0 {
                    digits.push((mag & 0xFF) as u8);
                    mag >>= 8;
                }
                out.extend_from_slice(&[0x6e, digits.len() as u8, if n < 0 { 1 } else { 0 }]);
                out.extend_from_slice(&digits);
            }
        }
        Term::Binary(b) => {
            out.push(0x6d);
            out.extend_from_slice(&be32(b.len()));
            out.extend_from_slice(b);
        }
        Term::List(items) => {
            if !items.is_empty() {
                out.push(0x6c);
                out.extend_from_slice(&be32(items.len()));
                for x in items {
                    encode_into(x, out)?;
                }
            }
            out.push(0x6a);
        }
        Term::Map(m) => {
            out.push(0x74);
            out.extend_from_slice(&be32(m.len()));
            for (key, value) in m {
                encode_into(&Term::Atom(key.clone()), out)?;
                encode_into(value, out)?;
            }
        }
    }
    Ok(())
}

/// The bytes of a term, beginning with the version byte 131.
pub fn etf_encode(term: &Term) -> Result<Vec<u8>, Fault> {
    let mut out = vec![0x83];
    encode_into(term, &mut out)?;
    Ok(out)
}

struct Reader<'a> {
    data: &'a [u8],
    pos: usize,
    depth_max: usize,
}

fn refused<T>(text: &str) -> Result<T, Refused> {
    Err(Refused::new(text))
}

impl<'a> Reader<'a> {
    fn take(&mut self, n: usize) -> Result<&'a [u8], Refused> {
        if n > self.data.len() - self.pos {
            return refused("truncated");
        }
        let s = &self.data[self.pos..self.pos + n];
        self.pos += n;
        Ok(s)
    }

    fn byte(&mut self) -> Result<u8, Refused> {
        Ok(self.take(1)?[0])
    }

    fn u32(&mut self) -> Result<usize, Refused> {
        let b = self.take(4)?;
        Ok(u32::from_be_bytes([b[0], b[1], b[2], b[3]]) as usize)
    }

    fn atom(&mut self, n: usize) -> Result<Term, Refused> {
        let raw = self.take(n)?;
        match std::str::from_utf8(raw) {
            Ok(name) => Ok(Term::Atom(name.to_string())),
            Err(_) => refused("bad_atom"),
        }
    }

    fn term(&mut self, depth: usize) -> Result<Term, Refused> {
        if depth > self.depth_max {
            return refused("too_deep");
        }
        let tag = self.byte()?;
        match tag {
            0x77 => {
                let n = self.byte()? as usize;
                self.atom(n)
            }
            0x76 => {
                let hi = self.byte()? as usize;
                let lo = self.byte()? as usize;
                self.atom((hi << 8) | lo)
            }
            0x61 => Ok(Term::Int(self.byte()? as i64)),
            0x62 => {
                let b = self.take(4)?;
                Ok(Term::Int(i32::from_be_bytes([b[0], b[1], b[2], b[3]]) as i64))
            }
            0x6e => {
                let n = self.byte()? as usize;
                let sign = self.byte()?;
                if n > 8 {
                    return refused("unsupported");
                }
                let mut mag: u64 = 0;
                for (i, b) in self.take(n)?.iter().enumerate() {
                    mag |= (*b as u64) << (8 * i);
                }
                // this extension keeps integers in 64 signed bits; every number of tempus/1 is far inside them
                if sign != 0 {
                    if mag > (i64::MAX as u64) + 1 {
                        return refused("unsupported");
                    }
                    return Ok(Term::Int((mag as i64).wrapping_neg()));
                }
                if mag > i64::MAX as u64 {
                    return refused("unsupported");
                }
                Ok(Term::Int(mag as i64))
            }
            0x6d => {
                let n = self.u32()?;
                Ok(Term::Binary(self.take(n)?.to_vec()))
            }
            0x6a => Ok(Term::List(Vec::new())),
            0x6c => {
                let n = self.u32()?;
                if n > self.data.len() {
                    return refused("truncated");
                }
                let mut items = Vec::with_capacity(n.min(64));
                for _ in 0..n {
                    items.push(self.term(depth + 1)?);
                }
                if self.byte()? != 0x6a {
                    return refused("bad_tag");
                }
                Ok(Term::List(items))
            }
            0x74 => {
                let n = self.u32()?;
                if n > self.data.len() {
                    return refused("truncated");
                }
                let mut m = BTreeMap::new();
                for _ in 0..n {
                    let key = match self.term(depth + 1)? {
                        Term::Atom(key) => key,
                        _ => return refused("bad_tag"),
                    };
                    if m.contains_key(&key) {
                        return refused("duplicate_field");
                    }
                    let value = self.term(depth + 1)?;
                    m.insert(key, value);
                }
                Ok(Term::Map(m))
            }
            0x68 | 0x69 | 0x6b | 0x46 => refused("bad_tag"),
            _ => refused("unsupported"),
        }
    }
}

/// One term from bytes that begin with the version byte 131 and hold nothing after the term. `depth_max` is the
/// deepest nesting accepted, and `size_max` the most bytes.
pub fn etf_decode_within(data: &[u8], depth_max: usize, size_max: usize) -> Result<Term, Refused> {
    if data.len() > size_max {
        return refused("too_large");
    }
    if data.is_empty() {
        return refused("truncated");
    }
    if data[0] != 0x83 {
        return refused("bad_version");
    }
    let mut r = Reader { data, pos: 1, depth_max };
    let term = r.term(1)?;
    if r.pos != data.len() {
        return refused("trailing_bytes");
    }
    Ok(term)
}

/// One term of a frame body: nested at most 6 deep (the node's structure check), at most the frame ceiling long.
pub fn etf_decode(data: &[u8]) -> Result<Term, Refused> {
    etf_decode_within(data, 6, FRAME_MAX)
}
