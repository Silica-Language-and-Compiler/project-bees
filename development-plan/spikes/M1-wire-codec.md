# M1: the wire codec, in memory

> **Superseded by [M1b-etf-codec.md](M1b-etf-codec.md) (2026-11-05).** The typed tag-free encoding described here was replaced by ETF; the
> generator, `bees_wire` and the trials were retargeted, kind ids, the digest and the hello frame are gone, and the reasons were
> renamed to the language's atoms. What follows is the record of M1 as it was.

**Status:** run 2026-11-04 on `silica-999939-macos-applesilicon`. **Done.** Every supported type round-trips, hostile
frames are refused without a fault, and 200,000 frames cost 1.9 MB. Nothing here touches a socket, the network or a
foreign call. The format is in [`contract/wire-v1.md`](../../contract/wire-v1.md); the plan is
[`mvp.md`](../mvp.md) section 3.4 and milestone M1.
**Trials:** `trials/m1_wire_types`, `m1_wire_reject`, `m1_wire_words`, `m1_wire_vectors`, `m1_wire_memory`, and
`tools/test_bees_wire_gen.py` (17 tests; run by `make kit`).

## 1. What was built

| Piece | Where |
| --- | --- |
| Hand-written core: byte, integer, float, boolean, char, string and atom readers and writers, the frame header, limits, word packing | `src/inter_nodal/bees_wire.silica` (+ `bees_wire.atoms`, the rejection-reason atoms) |
| Generator | `tools/bees_config.py wire -o DIR MANIFEST...` (and `generate`, which also reads `.wire` files); the work is in `tools/bees_wire_gen.py` |
| Generated units | `bees_wire_tables` (byte lookup tables, 4,900 lines, constant) and `bees_wire_msgs` (per message: `enc_<name>`, `dec_<name>`, `kind_id_<name>`; `kind_count`, `schema_digest`, `kind_of`, `validate`) |
| Manifest | `<unit>.wire`: `message <name> <silica type>`; kind ids in manifest order; digest FNV-1a 64 over the canonical schema text, emitted as the signed reading of the unsigned value |
| Trial harness | `tools/trial.mk` reads `.wire` manifests and cleans the generated units |

The M3 `bees_ingress` is not a separate unit yet. The checks (size, depth, counts, text, kind, atom held) have to run
**inside** the decoder, before anything is allocated, so they live in `bees_wire`; M3's `bees_ingress` adds the audit
entry and the delivery policy and calls them rather than repeating them.

## 2. The five design questions, answered against the compiler

1. **The buffer.** `buf(L, normal, uint8, 4096)`, one buffer for the largest frame, allocated in a `sequence proc[mem(normal)]`
   with `alloc_buf(r, 4096)`. The frame length (bytes held) travels beside it as an `int64`. Reads and writes go through
   `read_buf` / `write_buf` inside one-expression helpers (`rb`, `put_u8`); an out-of-range index would end the actor, so every
   read is preceded by `have(len, pos, n)` and every write checks the 4096 capacity. A position is an `int64` cursor; a
   **negative position is a rejection** (`-pos` is the reason code) and every reader and writer returns it unchanged, so a
   codec threads the position through its fields and checks once at the end. **Words:** `get_word(b, len, i)` reads 8
   bytes big-endian as an `int64` (two's complement; bytes past `len` read as zero even over a buffer full of 255),
   `put_word(b, i, w)` writes them, `word_count(len)` and `frame_total_from_word0(w)` size a frame from its first word.
   Verified: five frames from 12 to 4096 bytes copied word by word are byte-identical, zero-padded and valid, with
   negative words (`m1_wire_words`).
2. **Strings and atoms: ASCII only.** Silica has no bytes-to-string conversion. A byte becomes text through a 256-arm
   `case` over `uint8` returning a one-character literal (`"\x00"` through `"\n"` all work), and text becomes a byte
   through a `case` over the one-character `substring`. `substring`, `length_bytes`, `length_chars` and string
   `case`/`==` behave as the specification says for ASCII. The MVP accepts tab, newline, carriage return and `0x20`-`0x7E`
   and the decoder **rejects every other byte, including NUL, 0x7F and any UTF-8 sequence** (`bad_text`); the encoder
   refuses a string whose `length_chars` differs from `length_bytes` or that holds a byte outside the set. Strings are
   built by halves (`concat` of two halves) so a 1 KiB string is O(n log n) and 10 frames deep. **Cost (measured):**
   encode of a 1,020-byte string 0.94 ms, decode 0.22 ms; a short atom a few microseconds. `char` is a `u32` code point
   in the same set.
3. **Integer widths and floats.** All eight integer widths and `float32` and `float64` work, with lookups and same-type
   arithmetic only. Decode: a byte becomes a typed integer through `uint8`-keyed tables (`tab_u8_<type>`, and
   `tab_s8_<type>` mapping 128..255 to -128..-1 for the signed top byte), multiplied by literal powers of 256 in the
   result's own type. Encode: a negative value is moved by `+ 2^(bits-2) + 2^(bits-2)` into the non-negative range (two
   steps that never overflow), the top byte gets +128, and each byte is `lb_<type>(m / 256^k)`. Floats are spike S5's
   technique: decode builds the mantissa from per-bit powers of two and scales by `2^k` composed from literals; encode
   finds the exponent by a **binary search** (11 steps) over `2^e` comparisons and peels the mantissa bits. `float32` is the
   same algorithm with its own constants and works exactly: all 78 integer and float frames in `m1_wire_types` match
   Python's `struct.pack` byte for byte, including -0.0 (sign of a zero found by `1/v < 0`), the largest and smallest
   normal and subnormal values of both widths. **Infinity and NaN are refused** (`bad_float`) on encode and decode.
   **Excluded:** `float16` (build error). Costs: `float64` encode 21 us, decode 3.7 us; `float32` encode 17 us;
   `int64` encode and decode about 1 us.
4. **`List[T]`.** The list type in a signature must be `List[T, mem(normal)]` (`List[T]` is a parse error there), and every
   list operation takes `[T, mem(normal)]` and needs `mem(normal)` declared. Decode builds the list **recursively**:
   decode element, recurse for the rest, `prepend` on the way back, which gives the right order with no `reverse`; the
   recursion is at most 256 deep. Encode uses `list_at` and `length`. The count is checked against 256 **and against the
   bytes left divided by the smallest element size** before the first element is built, so a hostile count allocates
   nothing. A failure part-way returns the empty list. Verified at 0, 1, 255, 256 elements (and 257 refused), lists of
   strings, floats, tuples and lists of lists.
5. **The type grammar.** The generator parses: the primitives, tuples `(T, T, ...)` (two or more), records
   `{ f: T, g: T }`, and `List[T]` / `List[T, mem(normal)]`, nested to any depth (a type deeper than 16 builds with a
   warning and every frame of it is rejected `too_deep`). **Tagged tuples (atom-literal types) are not supported**: a
   decoder would have to write the tag as a BEAM atom literal, which a generated unit may not contain (use `(atom, T)` or
   an `atom` field). Every other construct is a build error naming the message, the field path and the type
   (`message ping: field 'to' has type 'actor_ref', which is not supported on the wire: ...`): `actor_ref` and the other
   actor references, `region`, `ref`, `ref?`, `buf`, `fn`, sum types, atom literals, `float16`, unit, `Map`, `Set` and other
   standard data structures, any unknown name, record fields that are Silica keywords, duplicate names.

## 3. Results

| Check | Result |
| --- | --- |
| Round trips (`m1_wire_types`): 107 value cases, every width at min, max, 0, -1 and mid values; floats incl. -0.0, subnormals, largest normals; booleans; chars; atoms incl. one of 255 bytes; strings empty / 1 / 1023 / 1024; tuple, record, lists (0, 1, 255, 256 elements), a nested value using every type | each decodes and re-encodes to the same bytes; the 78 primitive frames equal Python `struct.pack`; 257 elements and a 256-byte atom are refused at encode |
| Rejections (`m1_wire_reject`) | truncated at **every** length of a 32-byte valid frame (validate and `dec_small`: 32 of 32) and of a 21-byte hello; len 4097; declared length 70000 and 4093; encode of ~5 KiB; frame of exactly 4096 accepted, 4097 refused; 16 levels accepted, 17 refused (decode and encode); lists of 257, count 2^32-1, count 200 with 3 bytes; strings of 1025, count 2^32-1, count 1000 with 3 bytes; atom count 255 with 3 bytes; unknown atom; empty atom; unknown kind 11 and 65535; bytes 128, 127, 0, UTF-8 `C3 A9` in a string, byte 200 in an atom, chars 233 and 0x1F600; boolean 2; version 2; frame kind 2 and 0 where a send is expected, a send where a hello is expected; +/- infinity and NaN in both float widths and at encode; one byte too many. **Each returns the expected reason; the program carries on and decodes a valid frame afterwards.** |
| Build error (`tools/test_bees_wire_gen.py`) | 15 unsupported shapes exit non-zero naming message, field path and type; nothing is written |
| Generator | deterministic (two runs byte-identical); no BEAM atom literal (`bees_config check`); no `case` above 256 arms (600 messages split into three dispatcher helpers); limits equal in the generator and the core; digest FNV vectors and the signed reading checked |
| Memory (`m1_wire_memory`) | one actor: 100,000 hostile frames (list of 257, byte 200 in a string, unknown atom, truncated; 25,000 each) in one dispatch, then 100,000 valid frames one per dispatch. **Peak RSS 1.9 MB** (`/usr/bin/time -l`), the same as the rejection loop alone (1.8 MB). |
| Stability | each new leaf run three times: identical |

## 4. Limitations and surprises (for the people who read the next milestone)

- **Allocation made by a decode lives until the receiving handler returns.** 100,000 valid frames decoded in a *single*
  dispatch grew RSS from 1.8 to 22.7 MB (~0.2 KB per frame, a record holding a string, a list and an atom); the same frames,
  one per dispatch, stay at 1.9 MB. The connection actor must decode **one frame per dispatch** (it will: one frame per
  message). Rejected frames allocate nothing that grows, even 100,000 in one dispatch, because the checks come before the
  allocations.
- **A `float64` passed straight into `prepend` as a call result or a field access is stored as 0.0** (new,
  `silica-defects.md` SD-26, trial `silica_defects/sd26_float_prepend_argument`). The generated decoder binds each list
  element first. Float arguments to ordinary functions, record fields and tuple components, and float list elements read
  with `list_at`, were fine.
- Silica quirks met while writing the codec, all with workarounds in the code: `bytes`, `build`, `end` and `use`
  cannot be function or parameter names; a `case` over `n % 256` infers its scrutinee only for `int64` (other
  widths need a one-line helper); an argument such as `v / 256` cannot be passed to a *qualified* call (E2005), so the core
  wraps every table in a local function; a function has at most 8 parameters (E1070); a char pattern `' '` is rejected
  (E2005), `'\x20'` works; a `sequence` whose only calls are to user functions must not declare `device_io` or
  `mem(normal)` (E3010), and a record literal does not count as using `mem(normal)`; a bare record literal is fine as a
  `case` arm but not as a function body.
- **String encode is the slow path** (0.94 ms per KiB): each character is a `substring` plus a chain of up to 98 string
  comparisons. Acceptable for 4 KiB frames; a faster table (binary search over a `starts_with`, or a jump table when Silica
  has one) is a later optimisation.
- A `uint8` count limits an atom spelling to 255, so a 256-byte atom cannot be *expressed* in a frame; the 256-byte case is
  tested at the encoder, which refuses it (`too_long`). The decoder's `too_long` for atoms therefore cannot occur from the
  length byte alone.
- The depth limit is a run-time check but also a property of the type (the wire has no recursive types), so a type deeper
  than 16 is a build **warning**, not an error, so that the depth rejection can be tested through generated code.
- The generated tables unit is 4,900 lines and compiles in a few seconds; each leaf that uses the codec recompiles it.
- Tagged tuples, non-ASCII text and `float16` are excluded (section 2). Not yet written: the `local` / `remote` / `peer`
  manifest lines (M3), the proxies and deliverers (M3), and the real `bees_ingress` unit.
