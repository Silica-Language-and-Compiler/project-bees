"""EXAMPLE ONLY, not for production. See ../../README.md.

The ETF codec of the example Python TEMPUS client library: the subset of the external term format that tempus/1
uses (maps with atom keys, atoms, binaries, integers, lists), written from the design document and not from the Silica
units.
"""
import struct

FRAME_MAX = 131072


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

