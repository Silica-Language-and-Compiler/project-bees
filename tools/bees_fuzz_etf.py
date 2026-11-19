#!/usr/bin/env python3
"""F1 (fuzzer): the deterministic random source, an ETF writer, a lenient ETF reader (the oracle's) and the hostile-term generator.

Everything here is pure: no clock, no os.urandom, no `random` module (its sequences are not promised across Python versions). A
generator draws from Rng, a splitmix64 stream seeded from the SHA-256 of the run seed, the surface name and the case index, so
case I of surface S under seed N is the same bytes on every machine and Python.

The reader is lenient on purpose: it accepts every tag of the external term format that OTP 28 writes, in every encoding, so
that "the reader refuses it" means "no decoder may accept it" (the oracle's certain-invalid verdict). Standard library only.
"""
import hashlib
import struct

MASK = (1 << 64) - 1


class Rng:
    """splitmix64; seeded from text parts."""

    def __init__(self, *parts):
        h = hashlib.sha256(":".join(str(p) for p in parts).encode()).digest()
        self.s = int.from_bytes(h[:8], "big")

    def u64(self):
        self.s = (self.s + 0x9E3779B97F4A7C15) & MASK
        z = self.s
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & MASK
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & MASK
        return z ^ (z >> 31)

    def below(self, n):
        return self.u64() % n if n > 0 else 0

    def between(self, a, b):
        return a + self.below(b - a + 1)

    def chance(self, num, den):
        return self.below(den) < num

    def pick(self, seq):
        return seq[self.below(len(seq))]

    def weighted(self, pairs):
        """pairs: [(weight, value)]"""
        total = sum(w for w, _ in pairs)
        x = self.below(total)
        for w, v in pairs:
            if x < w:
                return v
            x -= w
        return pairs[-1][1]

    def bytes(self, n):
        out = bytearray()
        while len(out) < n:
            out += self.u64().to_bytes(8, "big")
        return bytes(out[:n])


# ---- writer ----
def atom(name, tag=119):
    b = name if isinstance(name, bytes) else name.encode("utf-8")
    if tag in (119, 115):
        return bytes([tag, len(b) & 255]) + b
    return bytes([tag]) + struct.pack(">H", len(b) & 0xFFFF) + b


def integer(n):
    if 0 <= n <= 255:
        return bytes([97, n])
    if -(1 << 31) <= n < (1 << 31):
        return bytes([98]) + struct.pack(">i", n)
    return big(n)


def big(n, tag=110):
    mag = abs(n)
    digits = mag.to_bytes(max(1, (mag.bit_length() + 7) // 8), "little")
    head = bytes([110, len(digits) & 255]) if tag == 110 else bytes([111]) + struct.pack(">I", len(digits))
    return head + bytes([1 if n < 0 else 0]) + digits


def binary(b):
    return bytes([109]) + struct.pack(">I", len(b)) + b


def tup(items, large=False):
    head = bytes([105]) + struct.pack(">I", len(items)) if large or len(items) > 255 else bytes([104, len(items)])
    return head + b"".join(items)


def lst(items, tail=b"\x6a"):
    if not items and tail == b"\x6a":
        return b"\x6a"
    return bytes([108]) + struct.pack(">I", len(items)) + b"".join(items) + tail


def emap(pairs):
    return bytes([116]) + struct.pack(">I", len(pairs)) + b"".join(k + v for k, v in pairs)


def new_float(x):
    return bytes([70]) + struct.pack(">d", x)


def pid(node, ident, serial=0, creation=1, new=True):
    if new:
        return bytes([88]) + atom(node) + struct.pack(">III", ident, serial, creation)
    return bytes([103]) + atom(node) + struct.pack(">II", ident, serial) + bytes([creation & 255])


def term(t):
    """a whole external term: the version byte and the term"""
    return b"\x83" + t


# ---- lenient reader (the oracle) ----
class Bad(ValueError):
    pass


DEPTH_CEILING = 200          # deeper than any limit under test (16 and 32): the reader calls it malformed
UNSUPPORTED = "other"        # pids, ports, references, funs, bit binaries: read, and reported as ("other", tag)


def _need(b, pos, n):
    if pos + n > len(b):
        raise Bad("truncated")


def read(b, pos=0, depth=0):
    """(value, next position). Values: ("atom", text), int, float, ("bin", bytes), ("tuple", [..]), ("list", [..], tail),
    ("map", [(k, v)..]), ("other", tag). Raises Bad on anything malformed."""
    if depth > DEPTH_CEILING:
        raise Bad("too deep")
    _need(b, pos, 1)
    t = b[pos]
    pos += 1
    if t == 97:
        _need(b, pos, 1)
        return b[pos], pos + 1
    if t == 98:
        _need(b, pos, 4)
        return struct.unpack(">i", b[pos:pos + 4])[0], pos + 4
    if t in (110, 111):
        w = 1 if t == 110 else 4
        _need(b, pos, w)
        n = b[pos] if t == 110 else struct.unpack(">I", b[pos:pos + 4])[0]
        pos += w
        _need(b, pos, 1 + n)
        v = int.from_bytes(b[pos + 1:pos + 1 + n], "little")
        return (-v if b[pos] else v), pos + 1 + n
    if t in (119, 115, 118, 100):
        w = 1 if t in (119, 115) else 2
        _need(b, pos, w)
        n = b[pos] if w == 1 else struct.unpack(">H", b[pos:pos + 2])[0]
        pos += w
        _need(b, pos, n)
        raw = b[pos:pos + n]
        try:
            text = raw.decode("utf-8" if t in (119, 118) else "latin-1")
        except UnicodeDecodeError:
            raise Bad("atom not UTF-8")
        return ("atom", text), pos + n
    if t == 70:
        _need(b, pos, 8)
        return struct.unpack(">d", b[pos:pos + 8])[0], pos + 8
    if t == 99:
        _need(b, pos, 31)
        try:
            return float(b[pos:pos + 31].split(b"\x00")[0].decode("ascii")), pos + 31
        except (ValueError, UnicodeDecodeError):
            raise Bad("old float")
    if t == 109:
        _need(b, pos, 4)
        n = struct.unpack(">I", b[pos:pos + 4])[0]
        pos += 4
        _need(b, pos, n)
        return ("bin", b[pos:pos + n]), pos + n
    if t == 106:
        return ("list", [], None), pos
    if t == 107:
        _need(b, pos, 2)
        n = struct.unpack(">H", b[pos:pos + 2])[0]
        pos += 2
        _need(b, pos, n)
        return ("list", list(b[pos:pos + n]), None), pos + n
    if t in (104, 105):
        w = 1 if t == 104 else 4
        _need(b, pos, w)
        n = b[pos] if w == 1 else struct.unpack(">I", b[pos:pos + 4])[0]
        pos += w
        _need(b, pos, n)             # each element is at least one byte
        items = []
        for _ in range(n):
            v, pos = read(b, pos, depth + 1)
            items.append(v)
        return ("tuple", items), pos
    if t == 108:
        _need(b, pos, 4)
        n = struct.unpack(">I", b[pos:pos + 4])[0]
        pos += 4
        _need(b, pos, n + 1)
        items = []
        for _ in range(n):
            v, pos = read(b, pos, depth + 1)
            items.append(v)
        tail, pos = read(b, pos, depth + 1)
        return ("list", items, None if tail == ("list", [], None) else tail), pos
    if t == 116:
        _need(b, pos, 4)
        n = struct.unpack(">I", b[pos:pos + 4])[0]
        pos += 4
        _need(b, pos, 2 * n)
        pairs = []
        for _ in range(n):
            k, pos = read(b, pos, depth + 1)
            v, pos = read(b, pos, depth + 1)
            pairs.append((k, v))
        return ("map", pairs), pos
    if t in (88, 103):                               # NEW_PID_EXT, PID_EXT
        node, pos = read(b, pos, depth + 1)
        n = 12 if t == 88 else 9
        _need(b, pos, n)
        return (UNSUPPORTED, t, node, b[pos:pos + n]), pos + n
    if t in (89, 102, 120):                          # ports
        node, pos = read(b, pos, depth + 1)
        n = {89: 8, 102: 5, 120: 12}[t]
        _need(b, pos, n)
        return (UNSUPPORTED, t), pos + n
    if t in (90, 114):                               # NEWER_REFERENCE_EXT, NEW_REFERENCE_EXT
        _need(b, pos, 2)
        n = struct.unpack(">H", b[pos:pos + 2])[0]
        node, pos = read(b, pos + 2, depth + 1)
        k = (4 if t == 90 else 1) + 4 * n
        _need(b, pos, k)
        return (UNSUPPORTED, t), pos + k
    if t == 77:                                      # BIT_BINARY_EXT
        _need(b, pos, 5)
        n = struct.unpack(">I", b[pos:pos + 4])[0]
        _need(b, pos + 5, n)
        return (UNSUPPORTED, t), pos + 5 + n
    if t == 113:                                     # EXPORT_EXT
        for _ in range(3):
            _, pos = read(b, pos, depth + 1)
        return (UNSUPPORTED, t), pos
    if t == 112:                                     # NEW_FUN_EXT: a size field covers it
        _need(b, pos, 4)
        n = struct.unpack(">I", b[pos:pos + 4])[0]
        if n < 4:
            raise Bad("fun size")
        _need(b, pos, n)
        return (UNSUPPORTED, t), pos + n
    raise Bad(f"tag {t}")


def read_term(b):
    """the value of a whole term (131 first, no trailing byte) or raises Bad"""
    if len(b) < 2 or b[0] != 131:
        raise Bad("version")
    v, pos = read(b, 1)
    if pos != len(b):
        raise Bad("trailing")
    return v


def depth_of(v):
    if isinstance(v, tuple):
        if v[0] == "tuple":
            return 1 + max([depth_of(x) for x in v[1]] or [0])
        if v[0] == "list":
            return 1 + max([depth_of(x) for x in v[1]] + ([depth_of(v[2])] if v[2] is not None else []) or [0])
        if v[0] == "map":
            return 1 + max([max(depth_of(k), depth_of(x)) for k, x in v[1]] or [0])
    return 0


def has_other(v):
    if isinstance(v, tuple):
        if v[0] == UNSUPPORTED:
            return True
        if v[0] == "tuple":
            return any(has_other(x) for x in v[1])
        if v[0] == "list":
            return any(has_other(x) for x in v[1]) or (v[2] is not None and has_other(v[2]))
        if v[0] == "map":
            return any(has_other(k) or has_other(x) for k, x in v[1])
    return False


def atoms_of(v, out=None):
    out = [] if out is None else out
    if isinstance(v, tuple):
        if v[0] == "atom":
            out.append(v[1])
        elif v[0] == "tuple":
            for x in v[1]:
                atoms_of(x, out)
        elif v[0] == "list":
            for x in v[1]:
                atoms_of(x, out)
            if v[2] is not None:
                atoms_of(v[2], out)
        elif v[0] == "map":
            for k, x in v[1]:
                atoms_of(k, out)
                atoms_of(x, out)
        elif v[0] == UNSUPPORTED and len(v) > 2:
            atoms_of(v[2], out)
    return out


# ---- the hostile-term generator ----
UNKNOWN_PREFIX = "zz_fuzz_"          # an atom spelled with this prefix is held by no node under test
ALL_TAGS = [70, 77, 80, 82, 88, 89, 90, 97, 98, 99, 100, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111, 112, 113, 114, 115,
            116, 117, 118, 119, 120, 121]
NEST_DEPTHS = [2, 8, 15, 16, 17, 18, 30, 31, 32, 33, 34, 40, 64, 150, 199, 201, 400, 1000]


def unknown_atom(rng):
    return atom(UNKNOWN_PREFIX + "%x" % rng.below(1 << 20), rng.pick([119, 118, 100, 115]))


def any_int(rng):
    k = rng.below(8)
    if k == 0:
        return integer(rng.below(256))
    if k == 1:
        return integer(rng.between(-(1 << 31), (1 << 31) - 1))
    if k == 2:
        return big(rng.pick([(1 << 63) - 1, -(1 << 63), 1 << 63, -(1 << 63) - 1, (1 << 64) - 1, 1 << 64, 0, 1, -1]))
    if k == 3:
        return big(rng.u64() - (1 << 63), rng.pick([110, 111]))
    if k == 4:
        return big(int.from_bytes(rng.bytes(rng.between(9, 40)), "big") * rng.pick([1, -1]))
    if k == 5:                                       # a small big with no digit, or with leading zero digits
        return rng.pick([bytes([110, 0, 0]), bytes([110, 8, 0]) + bytes(8), bytes([110, 9, 1, 1]) + bytes(8), bytes([111, 0, 0, 0, 0, 0])])
    if k == 6:
        return bytes([98]) + rng.bytes(4)
    return integer(rng.pick([0, 1, 41, 42, 255, 256, -1, 65535, 65536]))


def leaf(rng, atoms):
    k = rng.below(12)
    if k <= 1:
        return atom(rng.pick(atoms), rng.pick([119, 119, 118, 100, 115]))
    if k == 2:
        return unknown_atom(rng)
    if k <= 4:
        return any_int(rng)
    if k == 5:
        return binary(rng.bytes(rng.pick([0, 1, 7, 16, 17, 64, 300])))
    if k == 6:
        return new_float(struct.unpack(">d", rng.bytes(8))[0]) if rng.chance(1, 2) else bytes([99]) + (b"%.20e" % 1.5).ljust(31, b"\x00")
    if k == 7:
        return b"\x6a" if rng.chance(1, 2) else bytes([107]) + struct.pack(">H", 3) + rng.bytes(3)
    if k == 8:
        return pid(rng.pick(["stock@localhost", "x@127.0.0.1", "bl@localhost", UNKNOWN_PREFIX + "n@h"]), rng.below(1 << 15), rng.below(8), rng.below(4), rng.chance(3, 4))
    if k == 9:                                       # port, reference, bit binary, export fun
        return rng.pick([bytes([89]) + atom("stock@localhost") + bytes(8), bytes([120]) + atom("stock@localhost") + bytes(12),
                         bytes([90, 0, 2]) + atom("stock@localhost") + bytes(12), bytes([114, 0, 1]) + atom("stock@localhost") + bytes(5),
                         bytes([77, 0, 0, 0, 1, 3, 0xA0]), bytes([113]) + atom("erlang") + atom("apply") + integer(3)])
    if k == 10:                                      # a length that claims more than can be there
        return rng.pick([bytes([109]) + struct.pack(">I", rng.pick([0xFFFFFFFF, 0x7FFFFFFF, 4097, 65536])) + rng.bytes(rng.below(6)),
                         bytes([108]) + struct.pack(">I", rng.pick([0xFFFFFFFF, 1 << 20, 5000])) + rng.bytes(rng.below(6)),
                         bytes([116]) + struct.pack(">I", rng.pick([0xFFFFFFFF, 1 << 20, 17, 5000])) + rng.bytes(rng.below(6)),
                         bytes([105]) + struct.pack(">I", rng.pick([0xFFFFFFFF, 1 << 20])) + rng.bytes(rng.below(6)),
                         bytes([104, 255]) + rng.bytes(rng.below(6)), bytes([107, 255, 255]) + rng.bytes(rng.below(6)),
                         bytes([119, 255]) + rng.bytes(rng.below(6)), bytes([118, 255, 255]) + rng.bytes(rng.below(6)),
                         bytes([110, 255, 0]) + rng.bytes(rng.below(6)), bytes([111, 255, 255, 255, 255, 0]) + rng.bytes(rng.below(6)),
                         bytes([112]) + struct.pack(">I", rng.pick([0, 3, 0xFFFFFFFF])) + rng.bytes(rng.below(6)),
                         bytes([80]) + struct.pack(">I", 0xFFFFFFFF) + rng.bytes(rng.below(12))])
    return bytes([rng.pick(ALL_TAGS) if rng.chance(2, 3) else rng.below(256)]) + rng.bytes(rng.below(12))


def nested(rng, depth, inner):
    """inner wrapped in depth levels of tuples, lists and maps"""
    t = inner
    for _ in range(depth):
        k = rng.below(4)
        if k == 0:
            t = tup([t])
        elif k == 1:
            t = lst([t])
        elif k == 2:
            t = emap([(integer(1), t)])
        else:
            t = lst([integer(1)], t)                 # an improper list: the nesting is in the tail
    return t


def any_term(rng, atoms, budget=6):
    """one term, well-formed or not, a few bytes to a few hundred"""
    k = rng.below(10)
    if k <= 3 or budget <= 0:
        return leaf(rng, atoms)
    if k == 4:
        return nested(rng, rng.pick(NEST_DEPTHS), leaf(rng, atoms))
    n = rng.below(5)
    items = [any_term(rng, atoms, budget - 2) for _ in range(n)]
    if k == 5:
        return tup(items, rng.chance(1, 5))
    if k == 6:
        return lst(items, any_term(rng, atoms, 0) if rng.chance(1, 4) else b"\x6a")
    if k == 7:
        return emap([(any_term(rng, atoms, 0), v) for v in items])
    if k == 8:
        keys = [atom(rng.pick(atoms)) for _ in items]
        return emap(list(zip(keys, items)))
    return emap([(atom("k%d" % i), integer(i)) for i in range(rng.pick([15, 16, 17, 18, 64]))])


def mutate(rng, b):
    """byte-level damage to a well-formed message"""
    b = bytearray(b)
    k = rng.below(9)
    if not b:
        return bytes(rng.bytes(rng.between(1, 8)))
    if k == 0:                                       # one bit
        i = rng.below(len(b))
        b[i] ^= 1 << rng.below(8)
    elif k == 1:                                     # one byte
        b[rng.below(len(b))] = rng.below(256)
    elif k == 2:                                     # cut short
        del b[rng.below(len(b)):]
    elif k == 3:                                     # extra bytes at the end
        b += rng.bytes(rng.between(1, 9))
    elif k == 4:                                     # a byte removed
        del b[rng.below(len(b))]
    elif k == 5:                                     # a byte inserted
        b.insert(rng.below(len(b) + 1), rng.below(256))
    elif k == 6:                                     # a run overwritten
        i = rng.below(len(b))
        n = rng.between(1, 8)
        b[i:i + n] = rng.bytes(n)
    elif k == 7:                                     # a run repeated
        i = rng.below(len(b))
        n = rng.between(1, 16)
        b[i:i] = b[i:i + n]
    else:                                            # several bits
        for _ in range(rng.between(2, 6)):
            i = rng.below(len(b))
            b[i] ^= 1 << rng.below(8)
    return bytes(b)
