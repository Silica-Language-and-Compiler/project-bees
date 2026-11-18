#!/usr/bin/env python3
"""The Python TEMPUS client (development-plan/tempus-design.md section 16.5): pure Python, nothing of the Silica library.

Milestone C1: the codec. This module writes and reads every tempus/1 frame body of design section 5 with its own ETF
writer and reader (the subset the frames use: maps with atom keys, atoms, binaries, integers, lists), checks every bound of
section 8, and builds and reads tokens (section 4). It was written from the design document, not from the Silica units, so
that the two agreeing byte for byte (tools/test_bees_tempus_client.py) is evidence about the wire and not one mistake made
twice. The connection part (TCP, mutual TLS 1.3, admission, the operations of section 16.2) is milestone C2.

Ed25519 comes from the `cryptography` package and SHA-512 from hashlib; nothing else is needed and nothing is fetched.

    bees_tempus_client.py frame-hex KIND ...      (see main)
"""
import hashlib
import struct
import sys

KINDS = ("advert", "pop_challenge", "pop_response", "key_rotated", "shuffle", "shuffle_reply", "sample", "sample_reply",
         "tick", "clock", "done")
TYPES = ("tempus_edge", "tempus_bridge", "tempus_sentinel")
AGE_MAX = 65535
ENTRIES_MAX = 64          # the literal ceiling of entries in one frame
FRAME_MAX = 131072
CLOCK_MAX = 2 ** 53


class Refused(Exception):
    """A body or a token this client does not accept; the text says why."""


class Atom(str):
    """An Erlang atom (a str subclass, so a frame can tell atoms from binaries)."""
    __slots__ = ()

    def __repr__(self):
        return "Atom(%s)" % str.__repr__(self)


# ---------------------------------------------------------------- ETF, the subset tempus/1 uses
def _enc(term, out):
    if isinstance(term, Atom):
        name = term.encode("utf-8")
        if len(name) > 255:
            raise ValueError("atom too long for tempus/1")
        out += b"\x77" + bytes([len(name)]) + name
    elif isinstance(term, bool):
        raise ValueError("tempus/1 carries no booleans")
    elif isinstance(term, int):
        if 0 <= term <= 255:
            out += b"\x61" + bytes([term])
        elif -2 ** 31 <= term < 2 ** 31:
            out += b"\x62" + struct.pack(">i", term)
        else:
            mag = abs(term)
            digits = mag.to_bytes((mag.bit_length() + 7) // 8, "little")
            if len(digits) > 8:
                raise ValueError("integer beyond 64 bits")
            out += b"\x6e" + bytes([len(digits), 1 if term < 0 else 0]) + digits
    elif isinstance(term, (bytes, bytearray)):
        out += b"\x6d" + struct.pack(">I", len(term)) + bytes(term)
    elif isinstance(term, list):
        if term:
            out += b"\x6c" + struct.pack(">I", len(term))
            for x in term:
                _enc(x, out)
        out += b"\x6a"
    elif isinstance(term, dict):
        out += b"\x74" + struct.pack(">I", len(term))
        for key in sorted(term, key=lambda k: k.encode("utf-8")):   # keys in name order: one byte form
            if not isinstance(key, Atom):
                raise ValueError("a map key must be an atom")
            _enc(key, out)
            _enc(term[key], out)
    else:
        raise ValueError("no tempus/1 form for %r" % type(term))


def etf_encode(term):
    out = bytearray(b"\x83")
    _enc(term, out)
    return bytes(out)


class _Reader:
    def __init__(self, data, depth_max):
        self.data, self.pos, self.depth_max = data, 0, depth_max

    def take(self, n):
        if n < 0 or self.pos + n > len(self.data):
            raise Refused("truncated")
        chunk = self.data[self.pos:self.pos + n]
        self.pos += n
        return chunk

    def term(self, depth):
        if depth > self.depth_max:
            raise Refused("too_deep")
        tag = self.take(1)[0]
        if tag == 0x77:
            return Atom(self.take(self.take(1)[0]).decode("utf-8"))
        if tag == 0x76:
            return Atom(self.take(struct.unpack(">H", self.take(2))[0]).decode("utf-8"))
        if tag == 0x61:
            return self.take(1)[0]
        if tag == 0x62:
            return struct.unpack(">i", self.take(4))[0]
        if tag == 0x6e:
            n, sign = self.take(1)[0], self.take(1)[0]
            if n > 8:
                raise Refused("unsupported")
            v = int.from_bytes(self.take(n), "little")
            return -v if sign else v
        if tag == 0x6d:
            return self.take(struct.unpack(">I", self.take(4))[0])
        if tag == 0x6a:
            return []
        if tag == 0x6c:
            n = struct.unpack(">I", self.take(4))[0]
            if n > len(self.data):
                raise Refused("truncated")
            items = [self.term(depth + 1) for _ in range(n)]
            if self.take(1) != b"\x6a":
                raise Refused("bad_tag")
            return items
        if tag == 0x74:
            n = struct.unpack(">I", self.take(4))[0]
            if n > len(self.data):
                raise Refused("truncated")
            m = {}
            for _ in range(n):
                key = self.term(depth + 1)
                if not isinstance(key, Atom):
                    raise Refused("bad_tag")
                if key in m:
                    raise Refused("duplicate_field")
                m[key] = self.term(depth + 1)
            return m
        raise Refused("bad_tag" if tag in (0x68, 0x69, 0x6b, 0x46) else "unsupported")


def etf_decode(data, depth_max=6, size_max=FRAME_MAX):
    if len(data) > size_max:
        raise Refused("too_large")
    if len(data) < 1:
        raise Refused("truncated")
    if data[0] != 0x83:
        raise Refused("bad_version")
    r = _Reader(data, depth_max)
    r.pos = 1
    term = r.term(1)
    if r.pos != len(data):
        raise Refused("trailing_bytes")
    return term


# ---------------------------------------------------------------- identities, descriptors, tokens
def peer_id(pub):
    """The identity of a public key: its SHA-512 (design section 4)."""
    return hashlib.sha512(pub).digest()


def descriptor(pid, pub, addr, token):
    return {Atom("id"): bytes(pid), Atom("pub"): bytes(pub), Atom("addr"): addr.encode() if isinstance(addr, str) else bytes(addr),
            Atom("token"): bytes(token)}


def _check_keys(m, keys, what):
    if not isinstance(m, dict):
        raise Refused("%s is not a map" % what)
    have = set(m)
    want = {Atom(k) for k in keys}
    if have - want:
        raise Refused("unknown_field")
    if want - have:
        raise Refused("missing_field")


def _bin(m, key, lo, hi, text):
    v = m[Atom(key)]
    if not isinstance(v, bytes) or not lo <= len(v) <= hi:
        raise Refused(text)
    return v


def check_descriptor(d):
    _check_keys(d, ("id", "pub", "addr", "token"), "descriptor")
    _bin(d, "id", 64, 64, "id is not 64 bytes")
    _bin(d, "pub", 32, 32, "pub is not 32 bytes")
    _bin(d, "addr", 3, 261, "addr is not 3 to 261 bytes")
    _bin(d, "token", 65, 1024, "token is not 65 to 1024 bytes")
    return d


def token_payload(kid, sub, typ, nbf, exp):
    """The bytes a producer signs: the ETF map of the five fields, times in seconds."""
    return etf_encode({Atom("kid"): kid.encode() if isinstance(kid, str) else kid, Atom("sub"): bytes(sub),
                       Atom("typ"): Atom(typ), Atom("nbf"): nbf, Atom("exp"): exp})


def make_token(signing_key, kid, sub, typ, nbf, exp):
    """A token signed with an Ed25519 private key object of the `cryptography` package."""
    payload = token_payload(kid, sub, typ, nbf, exp)
    return signing_key.sign(payload) + payload


def read_token(token):
    """The structure and bounds of a token: (fields, payload, signature). The signature is NOT verified here."""
    if not 65 <= len(token) <= 1024:
        raise Refused("token is not 65 to 1024 bytes")
    sig, payload = token[:64], token[64:]
    m = etf_decode(payload, depth_max=2)
    if not isinstance(m, dict) or len(m) != 5:
        raise Refused("the token is not a map of five keys")
    _check_keys(m, ("kid", "sub", "typ", "nbf", "exp"), "token")
    kid = _bin(m, "kid", 1, 64, "kid is not 1 to 64 bytes")
    sub = _bin(m, "sub", 32, 32, "sub is not 32 bytes")
    typ, nbf, exp = m[Atom("typ")], m[Atom("nbf")], m[Atom("exp")]
    if not isinstance(typ, Atom) or typ not in TYPES:
        raise Refused("typ is not a peer type")
    if not isinstance(nbf, int) or not isinstance(exp, int) or isinstance(nbf, Atom) or nbf < 0 or exp < 0:
        raise Refused("nbf or exp is not a time")
    if exp <= nbf:
        raise Refused("exp is not after nbf")
    return {"kid": kid, "sub": sub, "typ": str(typ), "nbf": nbf, "exp": exp}, payload, sig


def verify_token(token, producer_public_key, kid, now, skew=0):
    """Structure, the current kid, the producer's signature over the payload as received, and the time window."""
    fields, payload, sig = read_token(token)
    if fields["kid"] != (kid.encode() if isinstance(kid, str) else kid):
        raise Refused("key_rotated")
    try:
        producer_public_key.verify(sig, payload)
    except Exception:
        raise Refused("the signature is not the producer's")
    if not fields["nbf"] - skew <= now < fields["exp"] + skew:
        raise Refused("the token is not valid at this time")
    return fields


# ---------------------------------------------------------------- frame bodies
def _typ(store):
    if store not in TYPES:
        raise ValueError("store is one of %s" % (TYPES,))
    return Atom(store)


def advert(d):
    return etf_encode({Atom("t"): Atom("advert"), Atom("ver"): 1, Atom("d"): d})


def challenge(nonce):
    return etf_encode({Atom("t"): Atom("pop_challenge"), Atom("nonce"): bytes(nonce)})


def response(sig):
    return etf_encode({Atom("t"): Atom("pop_response"), Atom("sig"): bytes(sig)})


def key_rotated(kid):
    return etf_encode({Atom("t"): Atom("key_rotated"), Atom("kid"): kid.encode() if isinstance(kid, str) else kid})


def _entries(kind, store, entries):
    return etf_encode({Atom("t"): Atom(kind), Atom("store"): _typ(store),
                       Atom("entries"): [{Atom("age"): age, Atom("d"): d} for (age, d) in entries]})


def shuffle(store, entries):
    """entries: a list of (age, descriptor)."""
    return _entries("shuffle", store, entries)


def shuffle_reply(store, entries):
    return _entries("shuffle_reply", store, entries)


def sample_reply(store, entries):
    return _entries("sample_reply", store, entries)


def sample(store, n):
    return etf_encode({Atom("t"): Atom("sample"), Atom("store"): _typ(store), Atom("n"): n})


def tick(store):
    """TEST ONLY: accepted by a node started with control_test_only."""
    return etf_encode({Atom("t"): Atom("tick"), Atom("store"): _typ(store)})


def clock(ms):
    """TEST ONLY."""
    return etf_encode({Atom("t"): Atom("clock"), Atom("ms"): ms})


def done():
    return etf_encode({Atom("t"): Atom("done")})


def read_body(body, shuffle_length):
    """A body as (kind, fields), every bound of design section 8 checked; Refused(reason) otherwise."""
    m = etf_decode(body)
    if not isinstance(m, dict):
        raise Refused("bad_tag")
    t = m.get(Atom("t"))
    if not isinstance(t, Atom) or t not in KINDS:
        raise Refused("unknown kind")
    kind = str(t)
    if kind == "advert":
        _check_keys(m, ("t", "ver", "d"), kind)
        if m[Atom("ver")] != 1:
            raise Refused("ver is not 1")
        return kind, {"d": check_descriptor(m[Atom("d")])}
    if kind == "pop_challenge":
        _check_keys(m, ("t", "nonce"), kind)
        return kind, {"nonce": _bin(m, "nonce", 32, 32, "nonce is not 32 bytes")}
    if kind == "pop_response":
        _check_keys(m, ("t", "sig"), kind)
        return kind, {"sig": _bin(m, "sig", 64, 64, "sig is not 64 bytes")}
    if kind == "key_rotated":
        _check_keys(m, ("t", "kid"), kind)
        return kind, {"kid": _bin(m, "kid", 1, 64, "kid is not 1 to 64 bytes")}
    if kind in ("shuffle", "shuffle_reply", "sample_reply"):
        _check_keys(m, ("t", "store", "entries"), kind)
        store, entries = m[Atom("store")], m[Atom("entries")]
        if not isinstance(store, Atom) or store not in TYPES:
            raise Refused("store is not a peer type")
        if not isinstance(entries, list):
            raise Refused("entries is not a list")
        if len(entries) > ENTRIES_MAX or len(entries) > shuffle_length:
            raise Refused("more entries than the shuffle length")
        out = []
        for e in entries:
            _check_keys(e, ("age", "d"), "entry")
            age = e[Atom("age")]
            if not isinstance(age, int) or isinstance(age, Atom) or not 0 <= age <= AGE_MAX:
                raise Refused("age is not 0 to 65535")
            out.append((age, check_descriptor(e[Atom("d")])))
        return kind, {"store": str(store), "entries": out}
    if kind == "sample":
        _check_keys(m, ("t", "store", "n"), kind)
        store, n = m[Atom("store")], m[Atom("n")]
        if not isinstance(store, Atom) or store not in TYPES:
            raise Refused("store is not a peer type")
        if not isinstance(n, int) or not 1 <= n <= shuffle_length:
            raise Refused("n is not 1 to the shuffle length")
        return kind, {"store": str(store), "n": n}
    if kind == "tick":
        _check_keys(m, ("t", "store"), kind)
        store = m[Atom("store")]
        if not isinstance(store, Atom) or store not in TYPES:
            raise Refused("store is not a peer type")
        return kind, {"store": str(store)}
    if kind == "clock":
        _check_keys(m, ("t", "ms"), kind)
        ms = m[Atom("ms")]
        if not isinstance(ms, int) or not 0 <= ms <= CLOCK_MAX:
            raise Refused("ms is not 0 to 2^53")
        return kind, {"ms": ms}
    _check_keys(m, ("t",), kind)
    return kind, {}


def frame(body):
    """The body with its 4-byte big-endian length, as it travels."""
    if len(body) > FRAME_MAX:
        raise ValueError("body above the frame ceiling")
    return struct.pack(">I", len(body)) + body


def main(argv):
    if len(argv) >= 2 and argv[1] == "read-hex":
        try:
            kind, fields = read_body(bytes.fromhex(argv[2]), int(argv[3]) if len(argv) > 3 else ENTRIES_MAX)
            print(kind, {k: (v if not isinstance(v, bytes) else v.hex()) for k, v in fields.items()})
        except Refused as why:
            print("refused:", why)
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
