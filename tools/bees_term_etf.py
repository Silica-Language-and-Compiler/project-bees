#!/usr/bin/env python3
"""An independent writer and reader of the Erlang External Term Format (C1, dynamic terms).

Used only by tests and by fixture generation; nothing in a BEES node depends on it. It is written from the format's
description (erl_ext_dist), not from the Silica units, so that the two can be compared:

  encode(value) -> bytes        the bytes term_to_binary/1 writes (OTP 26 and later, no options); map pairs in the order given
  decode(frame) -> value        any term; raises EtfError(reason) with the language's rejection atom as the reason

Python model of a term:
  int                      an integer of any size
  float                    a float
  Atom(name)               an atom (name: str)
  bytes                    a binary
  BitString(data, bits)    a bit string; bits (1..7) are used in the last byte
  tuple                    a tuple
  list                     a proper list (a list of integers 0..255 is what Erlang calls a string)
  Improper(items, tail)    an improper list, [items... | tail]
  Map(pairs)               a map, an ordered list of (key, value) pairs (wire order; equality ignores the order)
  Opaque(kind, data)       a pid, reference, port or fun: kind 'pid' | 'ref' | 'port' | 'fun', data its own ETF bytes

The token form of bees_term_wire (development-plan/spikes/C1-codec-term-coverage.md section 3.2), so that a test can
predict what the Silica unit does:
  tokens_of_frame(frame) -> [(kind, n, f, s)]   as bees_term_wire@decode makes them (same limits, same refusals)
  frame_of_tokens(tokens) -> bytes              as bees_term_wire@encode writes them (b"" for a list it refuses)
  to_tokens(value), from_tokens(tokens)         between the model and tokens
  tokens_text(tokens)                           the compact line trials/c1_codec_term prints

Command line:
  bees_term_etf.py hex TERMHEX            decode and print the model
  bees_term_etf.py tokens TERMHEX         print the token line
"""
import struct
import sys

MAX_NESTING = 64
MAX_TOKENS = 65536
MAX_PAIRS = 1024
MAX_ATOM_CHARS = 255


class EtfError(Exception):
    """reason: one of the language's rejection atoms, as text"""

    def __init__(self, reason):
        Exception.__init__(self, reason)
        self.reason = reason


class Atom:
    __slots__ = ("name",)

    def __init__(self, name):
        self.name = name

    def __eq__(self, other):
        return isinstance(other, Atom) and other.name == self.name

    def __hash__(self):
        return hash(("atom", self.name))

    def __repr__(self):
        return "Atom(%r)" % self.name


class BitString:
    __slots__ = ("data", "bits")

    def __init__(self, data, bits):
        self.data, self.bits = bytes(data), bits

    def __eq__(self, other):
        return isinstance(other, BitString) and (other.data, other.bits) == (self.data, self.bits)

    def __hash__(self):
        return hash(("bits", self.data, self.bits))

    def __repr__(self):
        return "BitString(%r, %d)" % (self.data, self.bits)


class Improper:
    __slots__ = ("items", "tail")

    def __init__(self, items, tail):
        self.items, self.tail = list(items), tail

    def __eq__(self, other):
        return isinstance(other, Improper) and other.items == self.items and other.tail == self.tail

    def __repr__(self):
        return "Improper(%r, %r)" % (self.items, self.tail)


class Map:
    __slots__ = ("pairs",)

    def __init__(self, pairs):
        self.pairs = [(k, v) for k, v in pairs]

    def __eq__(self, other):
        if not isinstance(other, Map) or len(other.pairs) != len(self.pairs):
            return False
        mine = sorted(self.pairs, key=lambda kv: _exact(kv[0]))
        theirs = sorted(other.pairs, key=lambda kv: _exact(kv[0]))
        return all(_exact(a[0]) == _exact(b[0]) and a[1] == b[1] for a, b in zip(mine, theirs))

    def __repr__(self):
        return "Map(%r)" % self.pairs


class Opaque:
    __slots__ = ("kind", "data")

    def __init__(self, kind, data):
        self.kind, self.data = kind, bytes(data)

    def __eq__(self, other):
        return isinstance(other, Opaque) and (other.kind, other.data) == (self.kind, self.data)

    def __repr__(self):
        return "Opaque(%r, %s)" % (self.kind, self.data.hex())


def _exact(v):
    """a sort and comparison key that keeps 1 and 1.0 apart: the term's canonical bytes with map pairs sorted"""
    if isinstance(v, Map):
        return b"M" + b"".join(sorted(_exact(k) + _exact(x) for k, x in v.pairs))
    if isinstance(v, tuple):
        return b"T" + struct.pack(">I", len(v)) + b"".join(_exact(x) for x in v)
    if isinstance(v, list):
        return b"L" + struct.pack(">I", len(v)) + b"".join(_exact(x) for x in v)
    if isinstance(v, Improper):
        return b"P" + struct.pack(">I", len(v.items)) + b"".join(_exact(x) for x in v.items) + _exact(v.tail)
    return b"V" + _term(v)


# ---------------------------------------------------------------------------------------------------------------
# writer
# ---------------------------------------------------------------------------------------------------------------
def encode(value):
    return b"\x83" + _term(value)


def _int(n):
    if 0 <= n <= 255:
        return bytes([97, n])
    if -(1 << 31) <= n < (1 << 31):
        return b"b" + struct.pack(">i", n)
    sign = 1 if n < 0 else 0
    mag = abs(n)
    digits = mag.to_bytes((mag.bit_length() + 7) // 8, "little")
    if len(digits) <= 255:
        return bytes([110, len(digits), sign]) + digits
    return b"o" + struct.pack(">I", len(digits)) + bytes([sign]) + digits


def _atom(name):
    raw = name.encode("utf-8")
    if len(name) > MAX_ATOM_CHARS:
        raise EtfError("too_long")
    if len(raw) <= 255:
        return bytes([119, len(raw)]) + raw
    return b"v" + struct.pack(">H", len(raw)) + raw


def _is_byte(x):
    return isinstance(x, int) and not isinstance(x, bool) and 0 <= x <= 255


def _term(v):
    if isinstance(v, bool):
        return _atom("true" if v else "false")
    if isinstance(v, int):
        return _int(v)
    if isinstance(v, float):
        return b"F" + struct.pack(">d", v)
    if isinstance(v, Atom):
        return _atom(v.name)
    if isinstance(v, (bytes, bytearray)):
        return b"m" + struct.pack(">I", len(v)) + bytes(v)
    if isinstance(v, BitString):
        if v.bits == 8:
            return _term(v.data)
        if not 1 <= v.bits <= 7 or not v.data:
            raise EtfError("out_of_range")
        unit = 1 << (8 - v.bits)
        data = v.data[:-1] + bytes([v.data[-1] - v.data[-1] % unit])
        return b"M" + struct.pack(">I", len(data)) + bytes([v.bits]) + data
    if isinstance(v, tuple):
        head = bytes([104, len(v)]) if len(v) <= 255 else b"i" + struct.pack(">I", len(v))
        return head + b"".join(_term(x) for x in v)
    if isinstance(v, list):
        if not v:
            return b"j"
        if len(v) <= 65535 and all(_is_byte(x) for x in v):
            return b"k" + struct.pack(">H", len(v)) + bytes(v)
        return b"l" + struct.pack(">I", len(v)) + b"".join(_term(x) for x in v) + b"j"
    if isinstance(v, Improper):
        if not v.items:
            raise EtfError("bad_tag")
        return b"l" + struct.pack(">I", len(v.items)) + b"".join(_term(x) for x in v.items) + _term(v.tail)
    if isinstance(v, Map):
        return b"t" + struct.pack(">I", len(v.pairs)) + b"".join(_term(k) + _term(x) for k, x in v.pairs)
    if isinstance(v, Opaque):
        return v.data
    raise TypeError("no ETF form for %r" % (v,))


# ---------------------------------------------------------------------------------------------------------------
# reader: bytes to tokens (the shape of bees_term_wire@decode), then tokens to the model
# ---------------------------------------------------------------------------------------------------------------
UNSUPPORTED_TAGS = (99, 82, 80, 68, 69, 117, 121)
OPAQUE_KIND = {88: 12, 103: 12, 90: 13, 114: 13, 101: 13, 120: 14, 89: 14, 102: 14, 112: 15, 113: 15}
KIND_NAME = {12: "pid", 13: "ref", 14: "port", 15: "fun"}
NAME_KIND = {v: k for k, v in KIND_NAME.items()}


def _need(frame, stop):
    if stop > len(frame):
        raise EtfError("truncated")
    return stop


def _atom_span(frame, pos):
    """(start of the name, stop) of the atom at pos"""
    _need(frame, pos + 1)
    tag = frame[pos]
    if tag in (119, 115):
        _need(frame, pos + 2)
        return pos + 2, _need(frame, pos + 2 + frame[pos + 1])
    if tag in (118, 100):
        _need(frame, pos + 3)
        return pos + 3, _need(frame, pos + 3 + struct.unpack_from(">H", frame, pos + 1)[0])
    if tag == 82:
        raise EtfError("unsupported")
    raise EtfError("bad_tag")


def _atom_name(frame, pos):
    start, stop = _atom_span(frame, pos)
    raw = frame[start:stop]
    if frame[pos] in (115, 100):
        if len(raw) > MAX_ATOM_CHARS:
            raise EtfError("too_long")
        return raw.decode("latin-1"), stop
    if len(raw) > 4 * MAX_ATOM_CHARS:
        raise EtfError("too_long")
    try:
        name = raw.decode("utf-8", "strict")
    except UnicodeDecodeError:
        raise EtfError("bad_utf8")
    if len(name) > MAX_ATOM_CHARS:
        raise EtfError("too_long")
    return name, stop


def _opaque_stop(frame, pos):
    tag = frame[pos]
    if tag == 112:
        _need(frame, pos + 5)
        size = struct.unpack_from(">I", frame, pos + 1)[0]
        if size < 4:
            raise EtfError("truncated")
        return _need(frame, pos + 1 + size)
    if tag == 113:
        _, p = _atom_span(frame, pos + 1)
        _, p = _atom_span(frame, p)
        _need(frame, p + 2)
        if frame[p] != 97:
            raise EtfError("bad_tag")
        return p + 2
    if tag in (90, 114):
        _need(frame, pos + 3)
        n = struct.unpack_from(">H", frame, pos + 1)[0]
        _, p = _atom_span(frame, pos + 3)
        return _need(frame, p + (4 if tag == 90 else 1) + 4 * n)
    _, p = _atom_span(frame, pos + 1)
    return _need(frame, p + {88: 12, 103: 9, 101: 5, 120: 12, 89: 8, 102: 5}[tag])


def _token_at(frame, pos):
    """(token, stop, kids): kids is -1 for a leaf"""
    _need(frame, pos + 1)
    tag = frame[pos]
    if tag == 97:
        _need(frame, pos + 2)
        return (1, frame[pos + 1], 0.0, b""), pos + 2, -1
    if tag == 98:
        _need(frame, pos + 5)
        return (1, struct.unpack_from(">i", frame, pos + 1)[0], 0.0, b""), pos + 5, -1
    if tag in (110, 111):
        w = 1 if tag == 110 else 4
        _need(frame, pos + 2 + w)
        n = frame[pos + 1] if w == 1 else struct.unpack_from(">I", frame, pos + 1)[0]
        sign = frame[pos + 1 + w]
        start = pos + 2 + w
        stop = _need(frame, start + n)
        if sign > 1:
            raise EtfError("out_of_range")
        mag = frame[start:stop].rstrip(b"\x00")
        value = int.from_bytes(mag, "little")
        value = -value if sign else value
        if -(1 << 63) <= value < (1 << 63):
            return (1, value, 0.0, b""), stop, -1
        return (2, sign, 0.0, mag), stop, -1
    if tag == 70:
        _need(frame, pos + 9)
        return (3, 0, struct.unpack_from(">d", frame, pos + 1)[0], b""), pos + 9, -1
    if tag in (119, 118, 115, 100):
        name, stop = _atom_name(frame, pos)
        return (4, 0, 0.0, name.encode("utf-8")), stop, -1
    if tag == 109:
        _need(frame, pos + 5)
        stop = _need(frame, pos + 5 + struct.unpack_from(">I", frame, pos + 1)[0])
        return (5, 0, 0.0, frame[pos + 5:stop]), stop, -1
    if tag == 77:
        _need(frame, pos + 6)
        n = struct.unpack_from(">I", frame, pos + 1)[0]
        bits = frame[pos + 5]
        stop = _need(frame, pos + 6 + n)
        if bits < 1 or bits > 8 or n < 1:
            raise EtfError("out_of_range")
        data = frame[pos + 6:stop]
        if bits == 8:
            return (5, 0, 0.0, data), stop, -1
        unit = 1 << (8 - bits)
        data = data[:-1] + bytes([data[-1] - data[-1] % unit])
        return (6, bits, 0.0, data), stop, -1
    if tag == 107:
        _need(frame, pos + 3)
        stop = _need(frame, pos + 3 + struct.unpack_from(">H", frame, pos + 1)[0])
        if stop == pos + 3:
            return (9, 0, 0.0, b""), stop, -1
        return (10, 0, 0.0, frame[pos + 3:stop]), stop, -1
    if tag == 106:
        return (9, 0, 0.0, b""), pos + 1, -1
    if tag in (104, 105, 108, 116):
        head = 2 if tag == 104 else 5
        _need(frame, pos + head)
        n = frame[pos + 1] if tag == 104 else struct.unpack_from(">I", frame, pos + 1)[0]
        left = len(frame) - (pos + head)
        if tag in (104, 105):
            kind, kids = 7, n
        elif tag == 108:
            if n < 1:
                raise EtfError("bad_tag")
            kind, kids = 8, n + 1
        else:
            if n > MAX_PAIRS:
                raise EtfError("too_long")
            kind, kids = 11, 2 * n
        if kids > left:
            raise EtfError("truncated")
        return (kind, n, 0.0, b""), pos + head, kids
    if tag in OPAQUE_KIND:
        stop = _opaque_stop(frame, pos)
        return (OPAQUE_KIND[tag], 0, 0.0, frame[pos:stop]), stop, -1
    if tag in UNSUPPORTED_TAGS:
        raise EtfError("unsupported")
    raise EtfError("bad_tag")


def tokens_of_frame(frame, max_depth=MAX_NESTING, max_tokens=MAX_TOKENS, bounded=True):
    """The tokens bees_term_wire@decode makes for the frame; EtfError(reason) where it refuses.
    bounded=False lifts the token limit (the model's own decode: a list of 65536 small integers is a legal term of
    65538 tokens)."""
    frame = bytes(frame)
    if len(frame) < 1:
        raise EtfError("truncated")
    if frame[0] != 131:
        raise EtfError("bad_version")
    max_depth, max_tokens = min(max_depth, MAX_NESTING), min(max_tokens, MAX_TOKENS)
    if not bounded:
        max_tokens = len(frame) + 1
    pos, stack, depth, toks = 1, [1], 0, []
    while stack:
        if stack[-1] == 0:
            stack.pop()
            depth -= 1
            continue
        if len(toks) >= max_tokens:
            raise EtfError("too_long")
        tok, stop, kids = _token_at(frame, pos)
        if kids >= 0 and depth + 1 > max_depth:
            raise EtfError("too_deep")
        if len(toks) + 1 + max(kids, 0) > max_tokens:
            raise EtfError("too_long")
        toks.append(tok)
        stack[-1] -= 1
        pos = stop
        if kids >= 0:
            stack.append(kids)
            depth += 1
    if pos != len(frame):
        raise EtfError("trailing_bytes")
    if not _maps_ok(toks):
        raise EtfError("duplicate_field")
    return toks


def _kids(tok):
    return {7: tok[1], 8: tok[1] + 1, 11: 2 * tok[1]}.get(tok[0], 0)


def term_end(toks, i):
    """the index after the term that starts at token i, -1 when there is no whole term"""
    pending = 1
    while pending:
        if i >= len(toks) or _kids(toks[i]) < 0:
            return -1
        pending += _kids(toks[i]) - 1
        i += 1
    return i


def _maps_ok(toks):
    for i, tok in enumerate(toks):
        if tok[0] == 11 and tok[1] >= 2:
            keys, p = set(), i + 1
            for _ in range(tok[1]):
                e = term_end(toks, p)
                if e < 0:
                    return False
                # the canonical form: the writer's bytes with the pairs of every map inside the key sorted
                if _write(toks[p:e], check=False) is None:
                    return False
                key = _exact(from_tokens(toks[p:e]))
                if key in keys:
                    return False
                keys.add(key)
                p = term_end(toks, e)
                if p < 0:
                    return False
    return True


def _write(toks, check=True):
    """the term bytes (no 131) of a token list that is exactly one term, or None: bees_term_wire@encode's rules"""
    out, stack, depth, i = [], [1], 0, 0
    while stack:
        if stack[-1] == 0:
            stack.pop()
            depth -= 1
            continue
        if i >= len(toks):
            return None
        kind, n, f, s = toks[i]
        i += 1
        kids = -1
        if kind == 1:
            out.append(_int(n))
        elif kind == 2:
            if n not in (0, 1) or not s or s[-1] == 0:
                return None
            v = int.from_bytes(s, "little")
            out.append(_int(-v if n else v))
        elif kind == 3:
            out.append(b"F" + struct.pack(">d", f))
        elif kind == 4:
            try:
                name = bytes(s).decode("utf-8", "strict")
            except UnicodeDecodeError:
                return None
            if len(name) > MAX_ATOM_CHARS:
                return None
            out.append(_atom(name))
        elif kind == 5:
            out.append(_term(bytes(s)))
        elif kind == 6:
            if not 1 <= n <= 8 or not s:
                return None
            out.append(_term(BitString(s, n)))
        elif kind == 7:
            if n < 0 or n > 0xFFFFFFFF:
                return None
            out.append(bytes([104, n]) if n <= 255 else b"i" + struct.pack(">I", n))
            kids = n
        elif kind == 8:
            if n < 1 or n > 0xFFFFFFFF:
                return None
            run = toks[i:i + n + 1]
            if n <= 65535 and len(run) == n + 1 and run[n][0] == 9 and all(t[0] == 1 and 0 <= t[1] <= 255 for t in run[:n]):
                out.append(b"k" + struct.pack(">H", n) + bytes(t[1] for t in run[:n]))
                i += n + 1
            else:
                out.append(b"l" + struct.pack(">I", n))
                kids = n + 1
        elif kind == 9:
            out.append(b"j")
        elif kind == 10:
            out.append(_term(list(bytes(s))))
        elif kind == 11:
            if n < 0 or n > MAX_PAIRS:
                return None
            if check and n >= 2 and not _maps_ok([toks[i - 1]] + list(toks[i:])):
                return None
            out.append(b"t" + struct.pack(">I", n))
            kids = 2 * n
        elif kind in KIND_NAME:
            s = bytes(s)
            if not s or OPAQUE_KIND.get(s[0]) != kind:
                return None
            try:
                if _opaque_stop(s, 0) != len(s):
                    return None
            except EtfError:
                return None
            out.append(s)
        else:
            return None
        stack[-1] -= 1
        if kids >= 0:
            if depth + 1 > MAX_NESTING:
                return None
            stack.append(kids)
            depth += 1
    if i != len(toks):
        return None
    return b"".join(out)


def frame_of_tokens(toks):
    """The frame bees_term_wire@encode writes; b"" for a token list it refuses."""
    body = _write(list(toks))
    return b"" if body is None else b"\x83" + body


def from_tokens(toks):
    value, i = _value(toks, 0)
    if i != len(toks):
        raise ValueError("more than one term")
    return value


def _value(toks, i):
    kind, n, f, s = toks[i]
    i += 1
    if kind == 1:
        return n, i
    if kind == 2:
        v = int.from_bytes(s, "little")
        return (-v if n else v), i
    if kind == 3:
        return f, i
    if kind == 4:
        return Atom(bytes(s).decode("utf-8")), i
    if kind == 5:
        return bytes(s), i
    if kind == 6:
        return BitString(s, n), i
    if kind == 9:
        return [], i
    if kind == 10:
        return list(bytes(s)), i
    if kind in KIND_NAME:
        return Opaque(KIND_NAME[kind], s), i
    count = _kids((kind, n, f, s))
    items = []
    for _ in range(count):
        v, i = _value(toks, i)
        items.append(v)
    if kind == 7:
        return tuple(items), i
    if kind == 8:
        tail = items.pop()
        if isinstance(tail, list):
            return items + tail, i
        if isinstance(tail, Improper):
            return Improper(items + tail.items, tail.tail), i
        return Improper(items, tail), i
    if kind == 11:
        return Map(zip(items[0::2], items[1::2])), i
    raise ValueError("unknown kind %r" % kind)


def decode(frame):
    """Any term to the model; EtfError(reason) for a frame bees_term_wire would refuse (its token limit aside)."""
    return from_tokens(tokens_of_frame(frame, bounded=False))


def to_tokens(value):
    """The tokens bees_term_wire@decode makes for the frame encode(value) writes."""
    return tokens_of_frame(encode(value))


def _clip(data, limit=24):
    data = bytes(data)
    return data.hex() if len(data) <= limit else data[:limit].hex() + "~" + str(len(data))


def token_text(tok):
    kind, n, f, s = tok
    if kind == 1:
        return "i%d" % n
    if kind == 2:
        return "I%s%s" % ("-" if n else "+", _clip(s))
    if kind == 3:
        return "f" + struct.pack(">d", f).hex()
    if kind == 4:
        return "a:" + _clip(s)
    if kind == 5:
        return "b:" + _clip(s)
    if kind == 6:
        return "B%d:%s" % (n, _clip(s))
    if kind == 7:
        return "t%d" % n
    if kind == 8:
        return "l%d" % n
    if kind == 9:
        return "n"
    if kind == 10:
        return "s:" + _clip(s)
    if kind == 11:
        return "m%d" % n
    return {12: "p:", 13: "r:", 14: "o:", 15: "u:"}[kind] + _clip(s)


def tokens_text(toks, limit=40):
    """the compact line of trials/c1_codec_term: at most `limit` tokens, then +N for the N that are not shown"""
    shown = [token_text(t) for t in toks[:limit]]
    if len(toks) > limit:
        shown.append("+%d" % (len(toks) - limit))
    return " ".join(shown)


def trial_line(label, frame):
    """the line trials/c1_codec_term/main.silica prints for one fixture"""
    frame = bytes(frame)
    try:
        toks = tokens_of_frame(frame)
    except EtfError as e:
        return "%s: rejected :%s" % (label, e.reason)
    again = frame_of_tokens(toks)
    return "%s: %s | %s" % (label, tokens_text(toks), "same" if again == frame else "differs")


def main(argv):
    if len(argv) == 3 and argv[1] == "hex":
        print(repr(decode(bytes.fromhex(argv[2]))))
        return 0
    if len(argv) == 3 and argv[1] == "tokens":
        print(trial_line("term", bytes.fromhex(argv[2])))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
