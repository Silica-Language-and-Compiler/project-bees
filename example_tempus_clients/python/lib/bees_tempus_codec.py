"""The Python TEMPUS extension: the tempus/1 codec (development-plan/tempus-design.md sections 4, 5 and 8).

This module writes and reads every tempus/1 frame body with its own ETF writer and reader (the subset the frames use:
maps with atom keys, atoms, binaries, integers, lists), checks every bound of design section 8, and reads tokens. It
was written from the design document, not from the Silica units, so that the two agreeing byte for byte
(test_bees_tempus_client.py against the golden of trials/t2_tempus_frames) is evidence about the wire.

It holds nothing that is for tests only. The two test-only frames, tick and clock, are not here: to this module they
are frames of no kind, as they are to a production node (owner's ruling of 2026-11-20). Token making is not here
either: a token is made by the producer, never by a peer. Both are in bees_tempus_testing.py, which only tests and
trials import.

Nothing here opens a connection, holds a key or reads a clock.
"""
import hashlib
import struct

KINDS = ("advert", "pop_challenge", "pop_response", "key_rotated", "shuffle", "shuffle_reply", "sample", "sample_reply",
         "done")
TYPES = ("tempus_edge", "tempus_bridge", "tempus_sentinel")
AGE_MAX = 65535
ENTRIES_MAX = 64          # the literal ceiling of entries in one frame
FRAME_MAX = 131072


class Refused(Exception):
    """A body, a token or a peer this side does not accept; the text says why. `event` is the audit event a node
    writes for it (design section 5 and the Silica node's audit lines), "" where the caller decides."""

    def __init__(self, why, event=""):
        Exception.__init__(self, why)
        self.event = event


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

    def atom(self, name):
        """An atom's name must be UTF-8 (tags 119 and 118 say so); bytes that are not are refused, never raised."""
        try:
            return Atom(name.decode("utf-8"))
        except UnicodeDecodeError:
            raise Refused("bad_atom")

    def term(self, depth):
        if depth > self.depth_max:
            raise Refused("too_deep")
        tag = self.take(1)[0]
        if tag == 0x77:
            return self.atom(self.take(self.take(1)[0]))
        if tag == 0x76:
            return self.atom(self.take(struct.unpack(">H", self.take(2))[0]))
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
    _check_keys(m, ("t",), kind)
    return kind, {}


def frame(body):
    """The body with its 4-byte big-endian length, as it travels."""
    if len(body) > FRAME_MAX:
        raise ValueError("body above the frame ceiling")
    return struct.pack(">I", len(body)) + body



def call_frame(req_id, m, f, args, kind="call", arity=None):
    """C3: TRUST's request frame as a bridge reads it (design 17.4; the form of src/trust/bees_trust_frame.silica
    enc_request, written here independently): #{t => call | cast, ver => 1, req_id => <<bytes>>, m => M, f => F,
    a => length(args), args => [integers], opts => #{}}. args is a list of integers (what the trial's functions take)."""
    rid = req_id.encode() if isinstance(req_id, str) else bytes(req_id)
    return etf_encode({Atom("t"): Atom(kind), Atom("ver"): 1, Atom("req_id"): rid, Atom("m"): Atom(m), Atom("f"): Atom(f),
                       Atom("a"): len(args) if arity is None else arity, Atom("args"): list(args), Atom("opts"): {}})



def read_any(body, shuffle_length=ENTRIES_MAX):
    """(kind, fields) of any body: a tempus/1 frame by read_body; a map whose `t` is no tempus/1 kind (TRUST's result,
    call, cast) with its fields as decoded, unchecked; else ("undecoded", {"why": reason}). PROVISIONAL for TRUST's
    frames: this reader has no tuples or floats, so a TRUST frame carrying them is "undecoded" (its bytes are still in
    the outcome's `body`); C3 decides what the client reads of them."""
    try:
        return read_body(body, shuffle_length)
    except Refused as why:
        first = str(why)
    try:
        m = etf_decode(body)
    except Refused:
        return "undecoded", {"why": first}
    t = m.get(Atom("t")) if isinstance(m, dict) else None
    if isinstance(t, Atom) and t not in KINDS:
        return str(t), {str(k): v for k, v in m.items() if k != "t"}
    return "undecoded", {"why": first}



# ---------------------------------------------------------------- the structure check of a node
# The atoms a production BEES TEMPUS node holds (the atom table of a node built from src/tempus and src/trust without
# the test unit: trials/t6_tempus_clock, node P). A node refuses a frame that names any other atom, with the reason
# unknown_atom, before it looks at the frame's kind. `tick`, `clock`, `ms`, `wait` and `later` are not among them.
NODE_ATOMS = frozenset((
    "a", "addr", "advert", "age", "args", "bad_tag", "bad_variant", "bad_version", "call", "cast", "closed",
    "connect_failed", "d", "deadline_ms", "dns_error", "done", "duplicate_field", "entries", "erlang", "error", "exp",
    "f", "goaway", "hello", "id", "key_rotated", "kid", "m", "missing_field", "n", "nbf", "nonce", "ok", "opts",
    "out_of_range", "pop_challenge", "pop_response", "protocol_error", "pub", "req_id", "result", "sample",
    "sample_reply", "server_not_pinned", "shuffle", "shuffle_reply", "sig", "store", "sub", "t", "tempus_bridge",
    "tempus_edge", "tempus_sentinel", "timeout", "token", "token_issue", "token_present", "too_deep", "too_large",
    "too_long", "trailing_bytes", "truncated", "typ", "unknown_atom", "unknown_field", "unsupported", "value", "ver"))
_ONCE = ("t", "ver", "req_id", "m", "f", "a", "args", "opts", "value", "token")   # keys the walk refuses twice


class _Walk(Exception):
    pass


def _skip(s, pos, depth, dmax, atoms):
    n = len(s)
    if depth > dmax:
        raise _Walk("too_deep")
    if pos >= n:
        raise _Walk("truncated")
    tag = s[pos]

    def need(end):
        if end > n:
            raise _Walk("truncated")
        return end

    def count(start, k, d):
        if k > n - start:
            raise _Walk("truncated")
        for _ in range(k):
            start = _skip(s, start, d, dmax, atoms)
        return start
    if tag == 97:
        return need(pos + 2)
    if tag == 98:
        return need(pos + 5)
    if tag == 70:
        return need(pos + 9)
    if tag == 106:
        return pos + 1
    if tag == 110:
        need(pos + 2)
        return need(pos + 3 + s[pos + 1])
    if tag in (119, 115, 118, 100):
        hdr = 2 if tag in (119, 115) else 3
        need(pos + hdr)
        size = s[pos + 1] if hdr == 2 else struct.unpack(">H", s[pos + 1:pos + 3])[0]
        end = need(pos + hdr + size)
        try:
            known = s[pos + hdr:end].decode("utf-8") in atoms
        except UnicodeDecodeError:
            known = False
        if not known:
            raise _Walk("unknown_atom")
        return end
    if tag == 109:
        need(pos + 5)
        return need(pos + 5 + struct.unpack(">I", s[pos + 1:pos + 5])[0])
    if tag == 107:
        need(pos + 3)
        return need(pos + 3 + struct.unpack(">H", s[pos + 1:pos + 3])[0])
    if tag == 108:
        need(pos + 5)
        end = count(pos + 5, struct.unpack(">I", s[pos + 1:pos + 5])[0], depth + 1)
        if end >= n:
            raise _Walk("truncated")
        if s[end] != 106:
            raise _Walk("bad_tag")
        return end + 1
    if tag == 104:
        need(pos + 2)
        return count(pos + 2, s[pos + 1], depth + 1)
    if tag == 105:
        need(pos + 5)
        return count(pos + 5, struct.unpack(">I", s[pos + 1:pos + 5])[0], depth + 1)
    if tag == 116:
        need(pos + 5)
        return count(pos + 5, 2 * struct.unpack(">I", s[pos + 1:pos + 5])[0], depth + 1)
    raise _Walk("unsupported")


def structure_reason(body, atoms=NODE_ATOMS, depth_max=6):
    """The structure check a node makes on a frame before it looks at its kind, in the node's order and with the
    node's reasons: "" when the body is one map with atom keys, of terms of the ETF subset, nested at most depth_max
    deep, naming only atoms of `atoms`, with no trailing bytes; else the reason. Written after the walk of
    src/trust/bees_trust_frame.silica (check), which the Silica node uses for the same purpose."""
    s = bytes(body)
    n = len(s)
    if n < 6:
        return "bad_version" if n >= 1 and s[0] != 131 else "truncated"
    if s[0] != 131:
        return "bad_version"
    if s[1] != 116:
        return "bad_tag"
    pairs = struct.unpack(">I", s[2:6])[0]
    if pairs > 16:
        return "too_long"
    pos, seen = 6, set()
    try:
        for _ in range(pairs):
            if pos >= n:
                return "truncated"
            if s[pos] not in (119, 115, 118, 100):
                return "bad_tag"
            end = _skip(s, pos, 1, depth_max, atoms)
            hdr = 2 if s[pos] in (119, 115) else 3
            key = s[pos + hdr:end]
            pos = _skip(s, end, 1, depth_max, atoms)
            name = key.decode("utf-8")
            if name in _ONCE:
                if name in seen:
                    return "duplicate_field"
                seen.add(name)
    except _Walk as why:
        return str(why)
    return "" if pos == n else "trailing_bytes"


def kind_of(body, atoms=NODE_ATOMS):
    """What a node takes a body to be before decoding it: the atom of its `t` when the structure check passes and `t`
    is an atom, else "" (the Silica node's kind(), which answers 0)."""
    if structure_reason(body, atoms):
        return ""
    s = bytes(body)
    pos = 6
    for _ in range(struct.unpack(">I", s[2:6])[0]):
        hdr = 2 if s[pos] in (119, 115) else 3
        end = _skip(s, pos, 1, 6, atoms)
        key = s[pos + hdr:end]
        pos = _skip(s, end, 1, 6, atoms)
        if key == b"t":
            if s[end] not in (119, 115, 118, 100):
                return ""
            vh = 2 if s[end] in (119, 115) else 3
            return s[end + vh:pos].decode("utf-8")
    return ""
