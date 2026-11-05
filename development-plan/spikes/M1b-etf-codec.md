# M1b: the typed message codec on ETF

> **Ruling 2026-11-05, after the first run:** an any-type term is not supported by Silica; handling it is the language transpiler's job, not BEES's and not Silica's. The term codec this note first described has been deleted; where it is mentioned below it is history. Decision 2 (remote pid as a tuple inside a term) is moot.

**Status:** run 2026-11-05 on `silica-999936-macos-applesilicon` with Erlang/OTP 28 (erts-15.0) as the byte oracle. **Done, with the
limits in section 8.** Nothing here touches a socket, the network or a foreign call. Plan: [`mvp.md`](../mvp.md) section 3.4 and
milestone M1b; the design it follows: [`silica-transport-alignment.md`](../silica-transport-alignment.md) (D35). It supersedes
[M1-wire-codec.md](M1-wire-codec.md) and the layout in [`contract/wire-v1.md`](../../contract/wire-v1.md).

## 1. What was built

| Piece | Where |
| --- | --- |
| Hand-written core: ETF readers and writers (integer header and emitter, floats, atoms, binaries, tuple, map and list headers, a structural skipper), the frame check, limits, the 16 rejection atoms, word packing | `src/inter_nodal/bees_wire.silica`, `bees_wire.atoms` |
| Generator | `tools/bees_config.py wire` (and `generate`); the work is in `tools/bees_wire_gen.py` |
| Generated units | `bees_wire_tables` (constant byte tables, ASCII 0 to 127), `bees_wire_ints` (constant: the eight integer widths over the core's header), `bees_wire_msgs` (per message `enc_<name>(rg, b, msg)`, `dec_<name>(rg, b, len)`, `msg_index_<name>`; `msg_count`, `index_of`, `validate`, `validate_named`) |
| Oracle and trial generator | `tools/etf_cases.py` (one registry of cases: it asks `erl` for the vectors, and writes the trial sources); vectors in `tools/etf_oracle/typed.vectors` (232), headed by the OTP version |
| Tests | `tools/test_bees_wire_gen.py` (20 tests, run by `make kit`): generator errors and shape, the vectors against a live `erl`, every trial golden against the vectors byte for byte, an independent Python writer of the scalar layouts against the vectors |
| Trials | `m1_wire_types*` (15 leaves, generated), `m1_wire_reject`, `m1_wire_words`, `m1_wire_memory` (hand-written). `m1_wire_vectors` is gone (the worked example of the old document; the oracle replaces it) |

## 2. The mapping

| Silica type | Written as | Read |
| --- | --- | --- |
| `int8`..`int64`, `uint8`..`uint64` | the smallest of SMALL_INTEGER_EXT (97, 0..255), INTEGER_EXT (98, 32-bit signed), SMALL_BIG_EXT (110, at most 8 digit bytes, fewest digits), as erl chooses | 97, 98, 110 with at most 8 digits (a 9th digit is `:out_of_range`), any valid encoding of a value in range (a SMALL_BIG for 5 is accepted); range-checked against the declared width |
| `char` | as an integer, 0 to 127 | the same, range-checked |
| `float64` | NEW_FLOAT_EXT (70) | 70 only (the old FLOAT_EXT text 99, which `minor_version` 0 writes, is `:unsupported`); infinity and NaN are `:out_of_range` |
| `float32` | NEW_FLOAT_EXT of the same value as a float64 (exact widening, subnormals included) | 70; a float64 that a float32 cannot hold exactly is `:out_of_range` |
| `boolean` | the atoms `true` and `false`, SMALL_ATOM_UTF8_EXT | any of the four atom tags; another atom is `:bad_variant` |
| `atom` | SMALL_ATOM_UTF8_EXT (119); the 118 form is never needed (a spelling is at most 255 bytes, the Erlang maximum) | 119, 118, 115, 100; a spelling the program does not hold is `:unknown_atom` (D16) |
| `string` | BINARY_EXT (109), at most 1024 bytes | 109 only |
| tuple | SMALL_TUPLE_EXT (104), LARGE_TUPLE_EXT (105) above 255 | both; fewer components than declared is `:missing_field`, more is `:unknown_field` |
| record | MAP_EXT (116) with atom keys **in name order** | keys **in any order**: one pass finds where each value starts (a skipper), then each field is decoded in declared order; a repeated key is `:duplicate_field`, an unknown key `:unknown_field`, a missing one `:missing_field` |
| `List[T]` | LIST_EXT (108), elements, NIL_EXT (106); the empty list is NIL_EXT; a list whose elements are all 0..255 (integers, or chars) is STRING_EXT (107), as erl writes it | all three; an improper tail is `:bad_tag`; STRING_EXT for any integer or char element type |
| whole frame | 131, then one term, ending at the last byte | 131 (else `:bad_version`); bytes left over are `:trailing_bytes` |

Records and the oracle: erl writes the keys of a flat map (up to 32 keys) in key order only with `[deterministic]` (section 5); a
record of more than 32 fields is written in name order too and decodes in any order, but erl uses hash order above 32 keys and no vector
covers it.

### Dispatch by target name

A message is found by its **name**: the target of an Erlang REG_SEND is a registered name, an atom the control message has already
decoded. `bees_config generate` adds every message name to `bees_atoms`, and the generated `bees_wire_msgs` exposes
`index_of(name: atom) -> int64` (the message's position in the manifest, or -1), `validate(rg, b, len, idx)` and
`validate_named(rg, b, len, name)` (0 or the rejection code; `:unknown_atom` for a name that is no message), and the typed
`dec_<name>`. The lookup is a chain of `name == bees_atoms@a_<m>()` in helpers of 64 (the compiler offers no switch on atoms
without writing atom literals, which D30 forbids in generated units), the dispatcher by index is tiered at 256 arms as before.
The numeric kind id, the schema digest and the hello frame of M1 are removed: the handshake is the Erlang one (M3).

## 3. Rejection reasons: M1 onto the language's atoms

The core now uses exactly Silica's sixteen atoms (`bees_wire.atoms`, codes 1 to 16 in this order).

| M1 reason | Now | Where |
| --- | --- | --- |
| `bad_version` | `:bad_version` | first byte not 131 |
| `truncated` | `:truncated` | a read past the end, a count larger than the bytes left |
| `trailing` | `:trailing_bytes` | bytes after the term |
| `bad_frame_kind` | removed | there is no frame kind |
| `unknown_kind` | `:unknown_atom` | a target name that is no message (`validate_named`, `index_of` is -1) |
| `too_large` | `:too_large` | a frame over 4096 bytes held, or a write past the buffer |
| `too_deep` | `:too_deep` | the 17th level of tuple, map or list (a STRING_EXT counts as a level) |
| `too_long` | `:too_long` | a list or tuple over 256, a binary over 1024, an atom over 255 bytes |
| `bad_text` | `:bad_utf8` for bytes that are not UTF-8, `:unsupported` for valid UTF-8 beyond ASCII | text is ASCII; Silica has no byte-to-character conversion for more |
| `unknown_atom` | `:unknown_atom` | an atom the program does not hold (and the empty atom) |
| `bad_float` | `:out_of_range` | infinity, NaN, a float64 a float32 cannot hold |
| `bad_boolean` | `:bad_variant` | an atom other than `true` and `false` |
| (new) | `:bad_tag` | a tag the type does not take (a float where an integer is declared), an improper list tail, a sign byte above 1 |
| (new) | `:out_of_range` | an integer outside the declared width, a 9-digit big |
| (new) | `:missing_field`, `:duplicate_field`, `:unknown_field` | maps, and tuples of the wrong arity |
| (new) | `:unsupported` | tags BEES does not implement: compressed (80), atom cache reference (82), bit binary (77), references, ports, funs, LARGE_BIG, the old float text, a pid where a typed value is declared; and, for terms, MAP_EXT |
| (new) | `:foreign_actor` | declared, never produced (Silica's `actor_ref` is not used for foreign pids) |

## 4. Terms of any shape: removed

The first run of M1b also built a codec between `bees_term` and ETF (`bees_etf`, `bees_etf_term`, 87 vectors, the `NEW_PID_EXT` form inside a term). **Ruled 2026-11-05: an any-type term is not supported by Silica, and handling it is the language transpiler's job, not BEES's and not Silica's. The code, its trials (`m1_etf_*`) and `terms.vectors` were deleted in the commit that follows this note** (see git history before it for the work). Foreign pids stay BEES's own for the distribution layer (M3), as typed values, not as a term shape.

## 5. The oracle

`tools/etf_cases.py vectors` runs `erl -noshell -eval` once over every entry and writes `<id> <hex>`. Four kinds of entry:

1. **encode**: the value is built in Silica and encoded; the frame must equal `term_to_binary(Value)`, and decoding it and encoding the
   result must give the same bytes.
2. **other valid encodings**: the frame is decoded and re-encoded and must equal the canonical frame of the referenced value
   (SMALL_BIG and INTEGER_EXT forms of integers, the other atom tags, STRING_EXT against LIST_EXT lists, keys in another order,
   LARGE_TUPLE_EXT for a small tuple, PID_EXT). Hand-built frames are first checked by erl: `binary_to_term(Frame) =:= Value`.
3. **hostile frames**: the expected reason is fixed in the registry (truncated, trailing bytes, oversized, too deep, too long, bad UTF-8,
   unknown atom, bad tag, unsupported tags such as compressed `131 80` and atom cache references, out of range, missing, duplicate and unknown
   fields).
4. **`minor_version` 0**: the float form (tag 99) is refused `:unsupported`, as decided.

**A surprise worth keeping:** erl's default `term_to_binary` writes the keys of a small map in *atom-table order*, not name order (`#{a=>1,b=>2,c=>3}`
came out as c, a, b). That order is not reproducible by any other implementation and differs between runs for maps built from `term(...)`
expressions. The vectors for terms that hold a map therefore use `[deterministic]` (keys in term order, atoms by name); every other
vector is plain `term_to_binary/1`. `make_ref()`, `self()` and funs are different on every run, so hostile frames for those tags are written
by hand (and checked by the unsupported-tag rule, not by erl).

## 6. Results

| Check | Result |
| --- | --- |
| Typed entries: 232 (116 encode, 116 decode-only) in 15 leaves (every width at its limits, floats incl. -0.0, subnormals and the largest values of both widths, booleans, chars, atoms of 255 bytes, strings to 1024 bytes, a 256-element list of bytes and of non-bytes, records in two key orders, a nested value using every type) | all pass: the encoded frames equal erl's byte for byte and round-trip; every alternative decodes to the canonical value; every hostile frame is refused with the expected reason |
| `m1_wire_reject`: truncation at every length of a 56-byte message frame (validate, `dec_small`: 56 of 56) and of a 2075-byte frame as a message (2075 of 2075); len 4097, 0; exactly 4096 accepted and 4097 refused at encode; 16 levels accepted and 17 refused (encode, and a hand-built frame); lists of 256 and 257, counts of 2^32-1 and 200 with 3 elements; strings of 1024 and 1025, counts of 2^32-1 and 1000 with 3 bytes; atom counts; text cases; booleans; infinities and NaN; a name nobody registered; a valid frame afterwards | each returns the expected reason and the program carries on |
| Memory (`m1_wire_memory`) | one actor: 100,000 hostile frames (list of 257, byte 200 in a string, unknown atom, truncated; 25,000 each) in one dispatch, then 100,000 valid frames (encode and decode a record holding a string, a list and an atom) one per dispatch: **peak resident set 1.9 MB** (`/usr/bin/time -l`), the same as M1; wall time 6.3 s for the 200,000 frames |
| Rates (one actor, 20,000 round trips in one dispatch, whole-process wall time with start-up; one run, an Apple silicon laptop, not a benchmark) | typed `{ a: uint16, s: string(23), l: List[uint8], at: atom, ok: boolean }` encode + decode: 1.19 s, about **17,000 round trips/s**; typed `{ a: int64, b: float64, c: boolean, d: atom }`: 0.71 s, about **28,000/s**; a term (`{int, atom, [1, 300]}`) encode, validate, decode, encode: 0.61 s, about **33,000/s**. Peak resident set 7.9 MB, 4.4 MB and 32.5 MB: a decode's allocation lives until the handler returns (the M1 finding), the term case also holding 20,000 terms in one heap region |
| Generator | deterministic; no BEAM atom literal; no `case` above 256 arms (601 messages split over three dispatch helpers and ten name-lookup helpers); the limits equal in the generator and the core |
| Build errors | the 15 unsupported shapes of M1 still exit non-zero naming message, field path and type; `unit` is now explained as not spellable |

## 7. Surprises and compiler facts (for the next milestone)

- **A region name is a name.** `bees_term`'s signatures name every region `L`, so the heap and the frame buffer must be allocated under the
  same lifetime (`L: lifetime`, both `alloc_region(normal)` calls). Using another name for the heap is a type error (E2003). The codec
  functions that take both are written with `L` for both.
- **`build` is a reserved function name** (as `bytes`, `end` and `use` already were); the term builder is `mk_term`.
- **A float taken from a record field and passed on loses its value in two places** (the SD-26 family, now seen outside `prepend`).
  `x: float64 <- r.v` followed by `bees_term@mk_float(h, x)` in one sequence stores 0.0 in the cell; the same float returned by a
  float64-returning function and bound from the call works. And `put_wide_f32(rg, b, pos, neg: boolean, a: float32)` with the float as the
  last argument after a boolean lost the mantissa; the version that passes the float32 alone and recomputes `abs` inside works. Both are
  worked around in the code (comments say where); neither is minimised into a `silica_defects` repro yet.
- **A qualified call cannot take an arithmetic argument** (`bees_wire@have(len, pos + 5, n)` is E2005, as already noted for `v / 256`),
  nor a field of its result (`bees_wire@dec_f64(...).pos`): both need a local wrapper function, which is why the codec has `bi`, `u32`,
  `have`, `enter_at`, `atom_from`, `i64_at`, `f64_at`.
- **`unit` cannot be a message type**: Silica has the value `()` but no type name for it (E2006 on `-> unit`, E2001 on `-> ()`), so the plan's
  `unit -> {}` has nothing to attach to.
- Two `case` expressions as consecutive arguments of one call are misread (`rng(rg, b, i + 1, stop, case ... { }, case ... { })` reports
  an argument count mismatch, E2005); helper functions (`lo3`, `hi3`) carry the choices. A function takes at most 8 parameters (E1070):
  the record scanner's helpers were reshaped for it.
- **A stale `silica.compile.crashed`** record made two builds report a crash (and a leaf with `Error 76`, the SD-29 out-of-memory exit,
  needed one re-run) that did not happen; every leaf of this milestone built on the second try at most.
- STRING_EXT must count as a list level for the depth limit (the typed codec always did, the term check did not at first): a nest of 17
  lists whose innermost is `[1]` is 17 levels.
- Text is now ASCII 0 to 127, control characters included (`"\x00"` through `"\x7f"` work as literals and in `case`).
  The 256-arm `case` tables of M1 are 128 arms now.

## 8. Not done, and what it would take

- **Tagged tuples** (`(:ok, int64)` as a message type) are still a build error: a generated unit may not contain a BEAM atom literal (D30)
  and the type is written with one. `(atom, T)` and an `atom` field are the supported form. The manifest could grow a `tag(name)` pseudo-type
  that checks the atom against `bees_atoms@a_name()` and is typed `atom`; not built.
- **`unit` / `{}`**: not spellable (section 7).
- **Text beyond ASCII**: valid UTF-8 beyond ASCII is `:unsupported`. It needs a byte-to-character path Silica does not have.
- **ATOM_UTF8_EXT on encode** is never written (an atom spelling is at most 255 bytes, the Erlang maximum); only the decoder reads 118.
- **Records over 32 fields**: written in name order, decoded in any order, byte-compared with erl for no case (erl switches to hash order).
- **Not run:** a stock Erlang node was not connected (there is no handshake yet, M3); the pid vectors are erl's own bytes, not a live exchange.
- The `.wire`/generator/`bees_wire` pieces are interim by D35: when Silica's `Transportable` lands they go, and `enc_<name>`/`dec_<name>` become
  its `encode`/`decode((:etf), ...)`. The 16 limits and the oracle stay.

## 9. Decisions to review

1. **Depth**: tuple, map, list and STRING_EXT each count as one level; a scalar does not. 16 levels are accepted, the 17th is `:too_deep`.
2. ~~The remote pid inside a term is a tuple with a marker atom.~~ Withdrawn with the term codec.
3. **`:unsupported` versus `:bad_tag`**: a tag of the format that BEES does not implement is `:unsupported`; any other tag that the
   reader did not expect is `:bad_tag`. A float where an integer is declared is `:bad_tag`.
4. **Valid UTF-8 beyond ASCII** is `:unsupported`, invalid UTF-8 `:bad_utf8`; control characters and NUL are accepted (M1 refused them).
5. **Canonical map order** is name order, matching erl's `[deterministic]`; erl's default order is not reproducible.
6. **An unknown target name is `:unknown_atom`** (there is no `unknown_kind` in the language's list).
7. **`float32` accepts only a float64 it can hold exactly**, rejecting the rest as `:out_of_range`, as the plan proposed (mvp.md section 9, point 7).
8. **Message names are atoms**: `bees_config generate` adds them to `bees_atoms` without being asked, so a message name can never clash
   with a Silica keyword the way a record field can (the parser already refuses those).
