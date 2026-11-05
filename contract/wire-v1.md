# BEES wire format, version 1

> **Superseded 2026-11-04 and replaced in code 2026-11-05 (milestone M1b).** The underlying protocol now matches the BEAM and
> Erlang: the Erlang distribution protocol and the External Term Format, and the reference implementation now encodes typed
> messages as ETF (`term_to_binary/1` bytes, checked against the installed `erl`; see
> [development-plan/spikes/M1b-etf-codec.md](../development-plan/spikes/M1b-etf-codec.md)). This document describes the typed,
> tag-free encoding built in the first codec milestone and **no code produces it any more**. Its limits (frame 4096 bytes, depth 16,
> 256 list elements, atom 255 bytes, string 1024 bytes) still apply to the ETF encoding; its ASCII-only text rule now covers all of
> ASCII (0 to 127); its frame layout, kind ids, schema digest, hello frame and term encoding are gone. It stays until the Erlang
> profile document (milestone M5) replaces it.

**Status:** as verified by the reference implementation (`src/inter_nodal/bees_wire.silica` with the units that
`tools/bees_config.py wire` generates) and by the trials `m1_wire_types`, `m1_wire_reject`, `m1_wire_words`,
`m1_wire_vectors` and `m1_wire_memory`. It describes frames in memory only. How frames travel between programs is not
part of this version of the document.

This is the format of one **frame**: the unit one program sends to another. A second implementation, in any language,
that follows this document produces frames the reference implementation accepts, and accepts the frames it produces.
Words in capitals (MUST, MUST NOT) are requirements on an implementation.

## 1. Conventions

- All multi-byte integers are **big-endian**. `u8`, `u16`, `u32` are unsigned; `i8` to `i64` are two's complement.
- A **byte** is 0 to 255.
- **Text** is ASCII from this set only: `0x09` (tab), `0x0A` (newline), `0x0D` (carriage return) and `0x20` to `0x7E`.
  Version 1 carries no other byte in a string, an atom spelling or a char. (This is narrower than UTF-8 on purpose; see
  section 9.)
- A **message type** is built from the types in section 5. Both programs know it from their schema (section 7); no
  field name, type tag or separator appears on the wire.

## 2. Frame

```
+----------------+---------+------+------+
| u32 length     | u8      | u8   | body |
| (big-endian)   | version | kind |      |
+----------------+---------+------+------+
```

- `length` is the number of bytes that follow the length field: `2 + len(body)`.
- `version` is `1`. A frame with any other version MUST be rejected (`bad_version`).
- `kind` is the frame kind (section 3). Any value other than 0 or 1 MUST be rejected (`bad_frame_kind`).
- The whole frame, `4 + length` bytes, MUST NOT exceed **4096** bytes. A `length` above 4092 MUST be rejected
  (`too_large`) before any further byte is read.
- A frame is exactly its declared length. Fewer bytes than declared is `truncated`; more is `trailing`.

A frame held in memory is a byte buffer of at least 4096 bytes and the number of bytes it holds. The receiver is handed
whole frames; splitting a byte stream into frames (reading the first four bytes, then `length` more) is the transport's
job. For transports that move 8 bytes at a time, section 8 defines a packing.

## 3. Frame kinds

| kind | name | body |
| --- | --- | --- |
| 0 | hello | the sender's node name as an **atom spelling** (section 5), then an **8-byte schema digest** (section 7) |
| 1 | send | a `u16` **message kind id**, then the **value** of that message's type |

The body of a frame MUST be consumed exactly: bytes left over after the last field are `trailing`, and a body that ends
inside a field is `truncated`.

A **send** frame whose message kind id is not one the receiver's schema defines MUST be rejected (`unknown_kind`).

The **hello** body is checked by the receiver against its peer table and its own schema digest (section 10). The digest
is the `u64` of section 7 written as 8 bytes, most significant first.

## 4. Limits

| limit | value | rejection |
| --- | --- | --- |
| frame, length field included | 4096 bytes | `too_large` |
| nesting depth (tuples, records and lists) | 16 | `too_deep` |
| elements in a list | 256 | `too_long` |
| atom spelling | 255 bytes | `too_long` (an encoder refuses a longer spelling) |
| string | 1024 bytes | `too_long` |
| message kinds in a schema | 65536 | build error |

**Depth** counts composite levels: the outermost tuple, record or list is level 1, a composite inside it level 2, and so
on. A decoder entering level 17 MUST reject. A schema whose type nests deeper than 16 can never be decoded; the reference
generator warns.

A decoder MUST check each limit **before it allocates for what the limit guards**: a list count is checked against 256
and against the bytes remaining in the frame (each element takes at least as many bytes as the smallest value of its
type) before the first element is built; a string or atom length is checked against its limit and against the bytes
remaining before any text is copied. Rejecting a frame MUST NOT cost more memory than accepting a full 4096-byte frame.

## 5. Values

A value is encoded from its type, depth first, with no tags.

| type | encoding | rejection on decode |
| --- | --- | --- |
| `uint8`, `uint16`, `uint32`, `uint64` | 1, 2, 4, 8 bytes | `truncated` |
| `int8`, `int16`, `int32`, `int64` | 1, 2, 4, 8 bytes, two's complement | `truncated` |
| `float32` | IEEE 754 binary32, 4 bytes | `bad_float` if the exponent field is all ones (infinity, NaN); `truncated` |
| `float64` | IEEE 754 binary64, 8 bytes | `bad_float` likewise |
| `boolean` | 1 byte: `0` false, `1` true | `bad_boolean` for any other byte |
| `char` | the code point as `u32`; only the text set (section 1) | `bad_text` for any other code point |
| `atom` | `u8` byte count `n`, then `n` bytes of text: the atom's **spelling** | `unknown_atom` if the receiver's program holds no atom with that spelling (including `n = 0`); `bad_text` |
| `string` | `u32` byte count `n` (at most 1024), then `n` bytes of text | `too_long`; `truncated`; `bad_text` |
| tuple `(T1, ..., Tn)`, `n >= 2` | the components in order, nothing between them | those of the components |
| record `{ f1: T1, ..., fn: Tn }`, `n >= 1` | the fields in **declared order**, nothing between them | those of the fields |
| `List[T]` | `u32` element count `n` (at most 256), then the `n` elements in order | `too_long`; `truncated`; those of the elements |

- **Floats.** An encoder MUST NOT encode infinity or NaN (it reports `bad_float`). Negative zero (`80 00 ...`) and
  subnormal values are valid and MUST round-trip exactly.
- **Atoms** are not numbers: two programs number their atoms differently, so an atom travels as the bytes of its name.
  The receiver turns the spelling back into one of its own atoms by lookup and MUST refuse a spelling it does not hold.
  An atom is never created from a received spelling.
- **Strings and spellings** are checked byte by byte against the text set. A string with a NUL byte, a byte of 0x7F or
  above, or a UTF-8 multi-byte sequence is `bad_text`.
- **Unsigned 32-bit counts** that exceed their limit (for example `0xFFFFFFFF`) are rejected by the limit, not by
  attempting to read that many bytes.

## 6. Order of checks

A decoder checks in this order and reports the first failure:

1. Bytes held more than 4096: `too_large`. Fewer than 4: `truncated`.
2. Declared length above 4092: `too_large`. `4 + length` above the bytes held: `truncated`; below: `trailing`;
   `length` below 2: `truncated`.
3. Version: `bad_version`.
4. Frame kind: `bad_frame_kind` if it is not the kind expected.
5. For a send frame, the message kind id: fewer than 2 bytes `truncated`; not defined `unknown_kind`.
6. The value, field by field in order; the first rejection wins. Entering a composite at level 17 is `too_deep`.
7. Bytes left over: `trailing`.

The reference implementation reports the rejection as a reason code and never faults, whatever bytes it is given.

## 7. Schema, kind ids and digest

A program declares the messages that may cross in a **schema**: a list of `(name, type)` in a fixed order. The position
in that order, starting at 0, is the message's **kind id** (a `u16`). Both programs MUST hold the same schema.

The **canonical schema text** is these lines, each ending in a line feed (`0x0A`), in ASCII:

```
bees-wire 1
limits frame=4096 depth=16 list=256 atom=255 string=1024
message <id> <name> <type>        (one line per message, in order)
```

where `<type>` is the canonical type text: primitive names as written (`int8` ... `uint64`, `float32`, `float64`,
`boolean`, `char`, `atom`, `string`), tuples as `(T,T)`, records as `{f:T,g:T}` in declared order, lists as `List[T]`,
with no spaces anywhere.

The **schema digest** is the 64-bit **FNV-1a** hash of those bytes: start with `0xcbf29ce484222325`; for each byte,
XOR it into the hash, then multiply by `0x100000001b3` modulo 2^64. The result is an unsigned 64-bit value. It is
carried in a hello frame as 8 bytes, most significant first. (The reference implementation holds it as the same 64 bits
read as a signed `int64`, because that is its language's integer type; on the wire the bits are the same.)

### Worked example

Schema (`trials/m1_wire_vectors/vectors.wire`):

```
message a uint8
message b { n: int16, s: string }
message c List[boolean]
```

Canonical schema text:

```
bees-wire 1
limits frame=4096 depth=16 list=256 atom=255 string=1024
message 0 a uint8
message 1 b {n:int16,s:string}
message 2 c List[boolean]
```

Digest `0xbdfe920b6e5e1c92`. Frames (hex):

| frame | bytes |
| --- | --- |
| `a` with 255 | `00 00 00 05 01 01 00 00 ff` |
| `b` with `{ n: -2, s: "hi" }` | `00 00 00 0c 01 01 00 01 ff fe 00 00 00 02 68 69` |
| `c` with `[true, false]` | `00 00 00 0a 01 01 00 02 00 00 00 02 01 00` |
| hello from node `n1` with the digest above | `00 00 00 0d 01 00 02 6e 31 bd fe 92 0b 6e 5e 1c 92` |

Further vectors: `float64` 1.5 is `3f f8 00 00 00 00 00 00`; `float32` -0.0 is `80 00 00 00`; `int64` -2^63 is
`80 00 00 00 00 00 00 00`; an atom `alpha` is `05 61 6c 70 68 61`.

## 8. Packing a frame into 8-byte words

Where a transport moves 8 bytes at a time, a frame is a sequence of 64-bit words, each the next 8 bytes **big-endian**
(the first byte of the frame is the most significant byte of the first word). The last word is padded with zero bytes.
The number of words is `ceil(bytes / 8)`, at most 512. The frame's length is known from the first word alone: its top
four bytes are the length field, so the total is that value plus 4, to be compared with 4096 before more words are read.
The padding is not part of the frame; a receiver is told the byte length (or derives it from the length field) and MUST
ignore the padding.

## 9. What version 1 does not carry

- Strings, atom spellings and chars outside the text set (any non-ASCII text). Silica, in which the reference
  implementation is written, has no conversion from bytes to text, so a byte becomes text through a table of
  one-character literals. A later version may widen the set (UTF-8) without changing the frame.
- `float16`; infinity and NaN.
- References to actors, regions and references, buffers, function values, sum types, optional references, atom literals
  as types (tagged tuples whose first element is a fixed atom), maps, sets and other standard data structures. A message
  type that uses one is a build error in the reference generator.
- Frames above 4096 bytes.

## 10. Handshake bodies (for the layer above)

A connection begins with each side sending a **hello** frame. The receiver checks the node name (turned into an atom
by lookup, so a name the receiver's peer table does not hold is `unknown_atom`) against the peers it expects, and the
digest against its own schema digest, and closes the connection on any difference. Frames of kind send before the
handshake completes are dropped. This document defines only the bodies; the connection rules belong to the node layer.

## 11. Reference implementation

| piece | role |
| --- | --- |
| `src/inter_nodal/bees_wire.silica` | the hand-written core: byte, integer, float, boolean, char, string and atom readers and writers; header checks; limits; word packing |
| `tools/bees_config.py wire` (`tools/bees_wire_gen.py`) | generates `bees_wire_tables` (byte lookup tables) and `bees_wire_msgs` (an encoder and decoder per message, kind ids, the digest and a validating dispatcher) from `<unit>.wire` manifests: `message <name> <silica type>` |

A decoder returns `{ code, v }`; `code` 0 is accepted and any other code is a rejection reason (`truncated`,
`too_large`, `too_deep`, `too_long`, `bad_text`, `unknown_atom`, `unknown_kind`, `bad_float`, `bad_boolean`,
`bad_version`, `bad_frame_kind`, `trailing`). An encoder returns the frame length in bytes, or the negated code.
