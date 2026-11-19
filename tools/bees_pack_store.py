#!/usr/bin/env python3
"""The on-medium form of Silica's hosted (:store) carrier, written and read in Python (D46; spikes/N0d-store-config.md).

The configuration packer (tools/bees_pack.py) writes an application's configuration as the records the carrier would hold
for `encode((:etf), value)`: the contract is the ETF wire contract of the (:etf) format as storage carries it. This module
is the layout and nothing else; it knows no option of bees.config.

The layout is Silica's, not BEES's (transport_serialization_design.md 6.8.3, 6.8.4, 6.8.9; compiler/stdlib/storelog.silica,
wireframe.silica; Silica's own independent writer is trials/transport_addition/app_transport_store_backing/make_backings.py).
All integers are big-endian.

    backing      CAPACITY bytes (a multiple of BLOCK), zero-filled where nothing was written
    block        BLOCK = 4096 bytes: a 16-byte header, then records back to back
    block header first_seq (8), state (4: 1 in use), CRC-32C of those 12 bytes (4)
    record       length (4), seq (8), CRC-32C over length, seq and payload (4), payload; never spans two blocks, so a
                 payload is at most MTU = 4064 bytes; a block that cannot take the next record is left (zeros follow) and
                 the record opens the next block, whose header carries its seq
    payload      wireframe's :storage segment: frame_seq (2, always 0), index (2, bit 15 set on the last segment of a
                 frame), then at most MTU - 4 bytes of the stored frame
    stored frame wireframe@record: format id (1: (:etf) is 1), schema version (2), then the encoded value
    value        term_to_binary form (131, ...), the (:etf) binding of design 4.7

A layout change in Silica is caught by trials/d1_store_layout (a Silica program reads a store this module wrote, and a
store a Silica program wrote is compared byte for byte with this module's).

Run as a script it prints a backing's records: bees_pack_store.py dump FILE
"""
import struct
import sys

BLOCK = 4096
WRITE_UNIT = 512
HEADER = 16
ENVELOPE = 16
MTU = BLOCK - HEADER - ENVELOPE          # 4064, Carrier@mtu of the (:store) kind
SEGMENT = MTU - 4                        # 4060 bytes of a stored frame in one record
MAX_SEGMENTS = 32768                     # the 15-bit segment index
FORMAT_ETF = 1


class StoreError(ValueError):
    pass


# ---- CRC-32C (Castagnoli), reflected, as storelog@crc32c ----
def _table():
    t = []
    for i in range(256):
        c = i
        for _ in range(8):
            c = (c >> 1) ^ 0x82F63B78 if c & 1 else c >> 1
        t.append(c)
    return t


_CRC = _table()


def crc32c(data):
    c = 0xFFFFFFFF
    for b in data:
        c = _CRC[(c ^ b) & 0xFF] ^ (c >> 8)
    return c ^ 0xFFFFFFFF


# ---- ETF, the (:etf) binding (design 4.7): what Silica's encode writes for the types a configuration uses ----
class Atom(str):
    """An Erlang atom (a Silica atom, or a record's field name)."""
    __slots__ = ()

    def __repr__(self):
        return ":" + str(self)


def _atom(name):
    b = name.encode("utf-8")
    if len(b) <= 255:
        return bytes([119, len(b)]) + b
    return bytes([118]) + struct.pack(">H", len(b)) + b


def _term(v):
    if isinstance(v, bool):
        return _atom("true" if v else "false")
    if isinstance(v, Atom):
        return _atom(str(v))
    if isinstance(v, int):
        if 0 <= v <= 255:
            return bytes([97, v])
        if -(1 << 31) <= v < (1 << 31):
            return bytes([98]) + struct.pack(">i", v)
        mag = abs(v)
        digits = mag.to_bytes((mag.bit_length() + 7) // 8, "little")
        if len(digits) > 8:
            raise StoreError(f"integer {v} needs more than 8 bytes (not transportable)")
        return bytes([110, len(digits), 1 if v < 0 else 0]) + digits
    if isinstance(v, str):
        v = v.encode("utf-8")
    if isinstance(v, (bytes, bytearray)):
        return bytes([109]) + struct.pack(">I", len(v)) + bytes(v)
    if isinstance(v, tuple):
        head = bytes([104, len(v)]) if len(v) <= 255 else bytes([105]) + struct.pack(">I", len(v))
        return head + b"".join(_term(x) for x in v)
    if isinstance(v, list):
        if not v:
            return bytes([106])
        return bytes([108]) + struct.pack(">I", len(v)) + b"".join(_term(x) for x in v) + bytes([106])
    if isinstance(v, dict):
        # a Silica record: a map with atom keys, written in the order of the field names (bytewise), as Silica's encode does
        keys = sorted(v, key=lambda k: str(k).encode("utf-8"))
        return bytes([116]) + struct.pack(">I", len(keys)) + b"".join(_atom(str(k)) + _term(v[k]) for k in keys)
    raise StoreError(f"no ETF form for {type(v).__name__}")


def etf(value):
    """term_to_binary(value): str and bytes are binaries (Silica's string), dict is a record (a map with atom keys)."""
    return bytes([131]) + _term(value)


# ---- wireframe: record (the stored frame) and the :storage segments ----
def stored_frame(schema, encoded, format_id=FORMAT_ETF):
    if not 0 <= schema <= 65535:
        raise StoreError(f"schema version {schema} outside 0..65535")
    return bytes([format_id, schema >> 8, schema & 255]) + encoded


def segments(frame):
    """wireframe@frame(frame, MTU, :storage): the record payloads of one stored frame, in order."""
    n = len(frame)
    if n == 0:
        raise StoreError("an empty frame cannot be stored")
    count = (n + SEGMENT - 1) // SEGMENT
    if count > MAX_SEGMENTS:
        raise StoreError(f"a frame of {n} bytes needs {count} records, above the {MAX_SEGMENTS} one frame may span")
    out = []
    for i in range(count):
        last = i == count - 1
        out.append(struct.pack(">HH", 0, i | (0x8000 if last else 0)) + frame[i * SEGMENT:(i + 1) * SEGMENT])
    return out


def block_header(first_seq, state=1):
    body = struct.pack(">QI", first_seq, state)
    return body + struct.pack(">I", crc32c(body))


def envelope(seq, payload):
    head = struct.pack(">IQ", len(payload), seq)
    return head + struct.pack(">I", crc32c(head + payload)) + payload


class Image:
    """A backing being written: records appended from sequence number 0, as one drain of the carrier writes them."""

    def __init__(self, capacity):
        if capacity <= 0 or capacity % BLOCK:
            raise StoreError(f"capacity {capacity} is not a positive multiple of {BLOCK}")
        self.capacity = capacity
        self.data = bytearray(capacity)
        self.block = -1          # the block being filled
        self.at = BLOCK          # the write position inside it
        self.next = 0            # the next sequence number
        self.frames = 0

    def append(self, payload):
        """One record. Raises StoreError when the region is full (a :stop region refuses with :full)."""
        n = len(payload)
        if n == 0:
            raise StoreError("a record of no bytes is refused by the carrier (:empty)")
        if n > MTU:
            raise StoreError(f"a record of {n} bytes is longer than the mtu {MTU} (:too_long)")
        if self.at + ENVELOPE + n > BLOCK:
            self.block += 1
            if (self.block + 1) * BLOCK > self.capacity:
                raise StoreError(f"the store is full: capacity {self.capacity} bytes cannot take record {self.next} (:full)")
            base = self.block * BLOCK
            self.data[base:base + HEADER] = block_header(self.next)
            self.at = HEADER
        base = self.block * BLOCK + self.at
        rec = envelope(self.next, payload)
        self.data[base:base + len(rec)] = rec
        self.at += len(rec)
        self.next += 1

    def append_value(self, schema, value):
        """One value as one stored frame: encode((:etf), value), wireframe@record, wireframe@frame(..., :storage)."""
        for seg in segments(stored_frame(schema, etf(value))):
            self.append(seg)
        self.frames += 1

    def bytes(self):
        return bytes(self.data)


# ---- reading (the carrier's scan, for the tests and for `dump`) ----
def _good(blk, p, want):
    if p + ENVELOPE > BLOCK:
        return None
    n, seq, crc = struct.unpack(">IQI", blk[p:p + ENVELOPE])
    if n == 0 or p + ENVELOPE + n > BLOCK or seq != want:
        return None
    payload = blk[p + ENVELOPE:p + ENVELOPE + n]
    if crc32c(blk[p:p + 12] + payload) != crc:
        return None
    return payload


def records(data):
    """The records of a backing whose log starts at 0, in order: [(seq, payload)]. Stops where the carrier's scan stops."""
    if len(data) % BLOCK:
        raise StoreError(f"a backing of {len(data)} bytes is not a multiple of {BLOCK}")
    out, want = [], 0
    for b in range(len(data) // BLOCK):
        blk = data[b * BLOCK:(b + 1) * BLOCK]
        first, state, crc = struct.unpack(">QII", blk[:HEADER])
        if crc32c(blk[:12]) != crc or state != 1 or first != want:
            break
        p = HEADER
        while True:
            payload = _good(blk, p, want)
            if payload is None and p % WRITE_UNIT:
                p = (p + WRITE_UNIT - 1) // WRITE_UNIT * WRITE_UNIT      # the record after a sync lies at the next write unit
                payload = _good(blk, p, want)
            if payload is None:
                break
            out.append((want, payload))
            want += 1
            p += ENVELOPE + len(payload)
    return out


def frames(data):
    """The stored frames of a backing: [(format_id, schema, encoded)], reassembled as wireframe@unframe does in :storage mode."""
    out, expected, pending = [], 0, b""
    for _, payload in records(data):
        if len(payload) < 4:
            raise StoreError("a record shorter than the segment header")
        index = struct.unpack(">H", payload[2:4])[0]
        last, idx = index >= 0x8000, index & 0x7FFF
        if idx == 0:
            pending = payload[4:]
        elif expected and idx == expected:
            pending += payload[4:]
        else:
            expected, pending = 0, b""
            continue
        if last:
            if len(pending) < 3:
                raise StoreError("a stored frame shorter than its header")
            out.append((pending[0], pending[1] * 256 + pending[2], pending[3:]))
            expected, pending = 0, b""
        else:
            expected = idx + 1
    return out


def main(argv):
    if len(argv) == 3 and argv[1] == "dump":
        with open(argv[2], "rb") as f:
            data = f.read()
        recs = records(data)
        print(f"capacity {len(data)} records {len(recs)}")
        for fmt, schema, enc in frames(data):
            print(f"frame format {fmt} schema {schema} bytes {len(enc)}")      # sizes only: a store may hold secrets
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
