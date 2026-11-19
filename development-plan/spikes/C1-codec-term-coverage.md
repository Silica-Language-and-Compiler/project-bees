# C1: term coverage of the wire codec (sum types, optional references, maps, sets, buf, dynamic terms)

Status: design note written 2026-11-18 before building; built 2026-11-18 and 2026-11-19 (section 6, with what is left
undone in 6.6).
Closes the two rows of [mvp.md](../mvp.md) section 7: "Sum types, optional references, maps and sets, `buf`" and
"Dynamic terms (`bees_term`) as a message type".

Compiler: every fact below marked "observed" was run on the pin `silica-999909-macos-applesilicon` in a scratch directory
(one small program per question, the language's `wire_etf` from the Silica tree as the trials link it). "999906" means the
same program was also run on `silica-999906-macos-applesilicon` to learn whether a limit goes away; nothing recorded as a
golden depends on 999906. Erlang facts were taken from the local `erl` (OTP 28, `/usr/local/erlang/bin/erl`) with
`term_to_binary/1` and `binary_to_term/1`.

## 1. Where conversion happens (unchanged rule, and what is added to it)

The node path converts typed values with the language's derived `encode((:etf), v)` and `decode((:etf), frame, { limits })`
inside `sequence proc[mem(normal), transport] ... produces pure` (ruling 2026-11-06, D35). That stays the only way a
scalar, string, atom, tuple, record, list, sum or recursive tuple becomes bytes or comes back from bytes.

Three kinds have no derived form (maps with non-atom keys, sets, `buf`: sections 2.3 to 2.5) and one has no static type
(dynamic terms, section 3). For those BEES adds a position scanner, `bees_etf_scan`: hand-written Silica that reads only
tags and lengths and returns positions (where a term ends, how many pairs a map has, the text of an atom). It builds no
value. Every value still comes from the language: a leaf or a whole plain subtree is cut out with `byte_slice`, prefixed
with the version byte 131 and handed to the derived `decode`; outbound, the derived `encode` output loses its first byte
and is placed after a header BEES writes with `bytes_of`. `bees_dist` already reads control messages this way (positions
by hand, `byte_at`). Ruled 2026-11-18 (Q2).

## 2. Typed kinds: the facts

| Kind | Derived encode/decode on the pin | ETF tag Erlang uses; what OTP 28 emits | BEES adds |
| --- | --- | --- | --- |
| Sum of atom literals, tagged tuples, one record | Works (observed). `(:a, int64) \| (:b, string) \| :none` gives `83 68 02 77 01 61 61 07`, `83 68 02 77 01 62 6d 00000002 6869`, `83 77 04 6e6f6e65`, byte for byte what erl writes for `{a,7}`, `{b,<<"hi">>}`, `none`. A record variant is a map. Nesting works: a tagged variant holding a record with a sum field, a list of a sum (observed). Tags cross unit boundaries intact (observed: a value built in the program unit, encoded and decoded in a library unit; the build-wide `silica.atoms`). An atom that appears only in types and patterns decodes (observed on the pin and 999906). | SMALL_TUPLE_EXT 104 with a first SMALL_ATOM_UTF8_EXT 119; a bare atom 119; MAP_EXT 116 | Generator: accept the grammar, check the variants, put the tag atoms in `bees_atoms`. No unit. |
| Sum with two variants of one tag and different arity | Not accepted: E2404 "variants of (:pt,int64) cannot be told apart on the wire" (observed on the pin and on 999906; the transport design 4.2 says "by tag or arity"). Repro: `v: (:pt, int64, int64) \| (:pt, int64) \| :none <- (:pt, 1); frame: string <- encode((:etf), v)`. | | Generator refuses it with the same reason. |
| Sum with a primitive, list or untagged tuple variant | Not usable: `v: :none \| int64 \| string <- 7;` is E1040 and `fn f(v: int64 \| string \| float64 \| boolean)` is E1069 (observed, pin and 999906); a `case` arm that binds a list variant (`l: List[int64, mem(normal)] -> ...`) is E1069. | | Generator refuses; a program tags the variant: `(:i, int64) \| (:s, string)`. |
| Rejections in a sum | Observed: another known atom, an unknown atom, a tuple with a wrong tag, a float: `:bad_variant`; a known tag with a wrong arity: `:bad_tag`; a cut frame: `:truncated`. | | Nothing. |
| Optional reference `ref?(L, normal, rec)` in a tuple | Works (observed): `(atom, int64, ref?(L, normal, rec))` crosses as nested tuples with the atom `none` in an empty slot, `83 68 03 77 02 6f6b 61 05 68 03 77 02 6f6b 61 03 68 03 77 02 6f6b 61 04 77 04 6e6f6e65`, which is erl's `{ok,5,{ok,3,{ok,4,none}}}`. `decode` takes the caller's region as a fourth argument. `max_depth` bounds the chain (`:too_deep`), an atom other than `none` in the slot is `:bad_variant`. The recursive tuple may sit inside a tagged tuple and a record (observed: `(:chain, { id: int64, head: (int64, string, ref?(L, normal, rec)) })`). | 104 and the atom `none` | Generator: the slot in the grammar, a region in the message, a depth literal. No unit. |
| Map with atom keys known at compile time | This is a record; already covered. | MAP_EXT 116 | Nothing. |
| Map with keys that are values (`#{1 => a}`, `#{<<"k">> => 2}`) | No derived form: Silica's maps are library trees in a region (`wbt_map`, recursive tuples), which the derived walk would write as nested tuples, not as an Erlang map. | MAP_EXT 116, pair count as 4 bytes, then key, value, ... `#{3=>c,1=>a,2=>b}` is `83 74 00000003 61 01 77 01 61 61 02 77 01 62 61 03 77 01 63`. Key order is erl's internal order: sorted for small integer keys, by atom index for atom keys (`#{b=>1,a=>2}` printed b first in one run and a first in another), hash order above 32 keys. It is not canonical, so a decoder must take any order and bytes can only be compared after sorting. `binary_to_term` refuses a duplicate key (badarg) and accepts unsorted keys. | Generator kind `Map[K, V]` over the scanner; value on the Silica side `List[(K, V), mem(normal)]`. |
| Set | No derived form (as maps). | Erlang has no set term. `sets:from_list/1` on OTP 28 is a map whose values are `[]`: `sets:from_list([3,1,2])` is `83 74 00000003 61 01 6a 61 02 6a 61 03 6a`. `ordsets` is a sorted list (`[1,2,3]` is STRING_EXT `83 6b 0003 010203`), `gb_sets` a tuple tree. | Generator kind `Set[T]`; value `List[T, mem(normal)]`; the `sets` map form (Q4). |
| `buf(L, normal, uint8, N)` | Refused by design: E2401 "component buf(L,normal,uint8,4) ... is not transportable (design 4.2)" (observed). The design says a buffer's bytes cross as a `string` built by the program. | BINARY_EXT 109: `<<1,2,3>>` is `83 6d 00000003 010203` | Generator kind: the bytes in use cross as BINARY_EXT; the message carries its region (standing ruling). |
| Record of more than four fields | SD-37 on the pin (the derived decoder has more than 8 parameters); a six-field record encodes and decodes on 999906 (observed). | MAP_EXT | The scanner path can decode such a record field by field; switched by one constant so that it can be removed (section 2.6). |
| Integers | Covered already; re-observed: `uint64` max `83 6e 08 00 ff..ff`, `int64` min `83 6e 08 01 00..80`, both as erl writes them; 2^64 and any LARGE_BIG_EXT or SMALL_BIG_EXT over 8 digits is `:unsupported`; a value outside the width is `:out_of_range`; a small value sent as SMALL_BIG_EXT is accepted and re-encoded in the smallest form. Wider integers exist only in dynamic terms (section 3). | 97, 98, 110, 111 | Nothing. |
| Floats | Covered already; re-observed: NEW_FLOAT_EXT only (`:unsupported` for FLOAT_EXT 99, `:bad_tag` for an integer). Silica carries more than Erlang (D32): NaN and the infinities encode and decode (`83 46 7ff8...`, `83 46 7ff0...`); `binary_to_term` of either is badarg on a stock node, so an Erlang peer drops such a message. -0.0 round-trips. | 70 | Nothing; said in the contract. |
| Binaries and strings | Covered: `string` is BINARY_EXT. Decode also takes STRING_EXT and NIL into a `string` (observed), so a charlist of bytes arrives as bytes. BIT_BINARY_EXT is `:bad_tag` for a `string`. | 109; `"abc"` (a list) is STRING_EXT `83 6b 0003 616263` | Nothing. |
| Lists of small integers | A difference from erl that exists today and stays (existing bytes must not change): the derived encoder writes `[1,2,3]` as LIST_EXT `83 6c 00000003 61 01 61 02 61 03 6a`; erl writes STRING_EXT `83 6b 0003 010203`. Both decode on both sides (observed: `binary_to_term` of the LIST_EXT form is `[1,2]`; the derived decoder takes 107 into `List[int64]`). The old hand codec `bees_wire` (m1 trials) writes 107. | 107 or 108 | Nothing; said in the contract. |
| Improper lists | Not a Silica list: `:bad_tag` for `List[int64]` (observed). Only a dynamic term holds one. | LIST_EXT with a non-NIL tail: `[1\|2]` is `83 6c 00000001 61 01 61 02` | Dynamic terms only. |
| Trailing bytes | `decode` refuses (`:trailing_bytes`); `binary_to_term` ignores them. BEES is stricter. | | Nothing. |

### 2.1 Grammar added to the `.wire` manifest (`tools/bees_wire_gen.py`)

```
:name                         an atom literal type (only as a tuple's first component or as a sum variant)
(:tag, T, ...)                a tagged tuple, one or more components after the tag (the tag alone, (:tag), is refused:
                              the derived codec fails on it, SD-57)
A | B | ...                   a sum: each variant an atom literal, a tagged tuple whose tag no other variant has,
                              or (at most one) a record; a sum with a tagged tuple variant must not start with an
                              atom literal (write a tagged tuple first: SD-50)
ref?(L, normal, rec)          an optional reference to the enclosing tuple (a recursive tuple); only as a tuple component
Map[K, V]                     an Erlang map; on the Silica side List[(K, V), mem(normal)]
Set[T]                        an Erlang set (the sets module's map form); on the Silica side List[T, mem(normal)]
buf(L, normal, uint8, N)      N bytes of buffer, N 1..65536; on the Silica side { b: buf(L, normal, uint8, N), n: int64 },
                              n bytes in use; only below tuples and records (not in a list, map, set or sum)
term                          a dynamic term (section 3); only as the whole message type
```

Every atom written in a type is added to `bees_atoms` (the manifest is the compile-time statement that the node needs
it), and the generated units get an `.atoms` file beside them so that `bees_config check` allows the literals in their
types. The hand codec of the m1 trials (`bees_wire_msgs`, a manifest with no node line) does not learn the new kinds: it
refuses them with a build error that says so (D35: the typed codec is the language's; `bees_wire` is kept for the m1 trials
and the oracle).

### 2.2 Messages that hold memory: the region travels with the value

A message type that contains an optional reference or a `buf` has the Silica message type
`{ r: region(L, normal), v: T }`: the region the references and buffers live in, moved by the cast with the value
(standing ruling for `buf`; the same shape `bees_term` v0 uses). The sender builds it; the deliverer allocates a fresh
region, decodes into it (the fourth argument of `decode`, `alloc_buf` for a buffer) and casts the record to the local name.
`bees_wire_gen.silica(ty)` returns that message type, so every generator that asks it for the type of a message
(`bees_dist_gen`, `bees_config_beam`) gets it without a change.

### 2.3 Maps

`Map[K, V]` crosses as MAP_EXT. Encode: header `116` and the count, then for each pair of the list, in the list's order,
the derived encoding of the key and of the value. Decode: the scanner gives the count and each key's and value's extent;
each is decoded by the derived decoder of its type; the pairs are returned in wire order. Refused: a count above the
limit (`:too_long`), a duplicate key (`:duplicate_field`; keys are compared by their canonical re-encoding, which the
derived encoder guarantees is equal for equal values), any tag other than 116 (`:bad_tag`). On the way out a list with a
duplicate key or more pairs than the limit is not sent (the proxy drops it, as it drops a frame over the cap): erl would
refuse the bytes. The duplicate check is quadratic, so the pair limit is a literal, 1024 (Q5).
A key, and a set's element (2.4), holds no `Map`, `Set`, `buf` or optional reference (the generator refuses it): keys are
compared by their encoding, and a map inside a key would be written in its list's order, so two keys with the same pairs
in another order would not be found equal. This is a BEES choice; a dynamic term's keys are compared with the pairs of
inner maps put in one order (3.4), so there such keys are duplicates, as in erl.

### 2.4 Sets

`Set[T]` crosses as the map `#{E => []}` that `sets:from_list/1` builds (OTP 24 and later with version 2; the default
since OTP 28). Decode refuses a value that is not NIL (`:bad_tag`), a duplicate element (`:duplicate_field`), and more
than 1024 elements (`:too_long`). Order is free in both directions (a map has none), so "unsorted" is not an error in this
form; it would be in the `ordsets` form (Q4).
The map form is what `sets:from_list/1` returns by default only from OTP 28. On OTP 27 and earlier the default is the
version 1 record (`{set, ...}`, a 9-tuple), which BEES refuses (`:bad_tag`, observed in `c1_codec_live` phase 2); an OTP 27
sender builds the set with `sets:from_list(L, [{version, 2}])`. The ruled wire form is not changed for it.

### 2.5 buf

The bytes in use (`n` of the record) cross as BINARY_EXT. Decode refuses a binary longer than N (`:too_long`, the derived
`max_length: N` of the string decode). Encode refuses `n` outside 0..N by not sending. The conversion buffer to string
and back is generated per N (the length is part of the type), a `read_buf`/`write_buf` loop. The encoder takes the region
too: the compiler refuses a signature with a `buf(L, ...)` and no `region(L, S)` (E2323).

### 2.6 How a type is split between the derived codec and the scanner

A type is plain when it holds no `Map`, `Set` or `buf` (and, while `SD37_SPLIT` is set in the generator, no record of more
than four fields). A plain type, however deep, is one derived `encode` and one derived `decode`, exactly as today: existing
manifests generate the same text. Otherwise the generator emits one function pair per node of the path down to the
special kinds (tuples, tagged tuples, records, lists): the scanner finds each part, each plain part is one derived call.
A sum with a non-plain variant is refused (the variant choice would have to be re-implemented by hand). Also refused: a
type with both an optional reference and a Map, Set, buf or wide record; a tuple or record on the split path with more
than 7 parts, or 6 when it holds a buf (a function has at most eight parameters on this target).
Removing the SD-37 workaround is deleting the constant.
Which of these limits are the compiler's and which are BEES's own choices: section 6.5.

### 2.7 Bounds on decoded typed values

`max_bytes` and `max_length`: the frame cap, as today (D47: a literal ceiling; `wireframe@unframe` enforces the configured
cap first). `max_depth`: the type's nesting plus one; for a recursive type the nesting plus 64 (Q6). Maps and sets: 1024
entries. buf: N. Scanner: positions never pass the end of the frame; nesting is bounded by 64 levels; a count is checked
against the bytes that remain before anything is read.

## 3. Dynamic terms

### 3.1 What exists and what was ruled

`src/shim/bees_term.silica` (v0, generated) is the in-memory value of compiled BEAM code: cells in a region, atoms as
Silica atoms. On 2026-11-05 the owner ruled that an any-shape codec is the transpiler's job and M1b's `bees_etf` was
deleted; mvp.md section 7 and this task ask for the decoder now. This note treats the task as the newer instruction and
recorded the point as Q1, ruled 2026-11-18: BEES owns the conversion from ETF to tokens and nothing above it. What is built keeps the earlier ruling's line as far as it can: BEES owns the bytes (bounded,
safe conversion between ETF and a flat Silica value); building the compiler's own cells from that value stays with the
compiler.

### 3.2 The type

No static Silica type decodes "any term" through the derived decoder: a derived tuple has a fixed arity, a derived list one
element type, a recursive slot only the enclosing tuple. So a dynamic term is held flat, as its tokens in prefix order:

```
bees_term on the wire side:  List[(int64, int64, float64, string), mem(normal)]      one token: (kind, n, f, s)
```

| kind | Token | Followed by | ETF read | ETF written |
| --- | --- | --- | --- | --- |
| 1 | integer n (fits int64) | | 97, 98, 110/111 that fit | smallest of 97, 98, 110 (erl's choice) |
| 2 | big integer: n = 0 or 1 (sign), s = magnitude, little-endian, no leading zero byte | | 110, 111 beyond int64 | 110 up to 255 bytes, else 111 |
| 3 | float f | | 70 (99 is `:unsupported`) | 70 |
| 4 | atom, s = its name in UTF-8 | | 119, 118, 115, 100 (Latin-1 turned into UTF-8) | 119, or 118 above 255 bytes |
| 5 | binary s | | 109 | 109 |
| 6 | bit string: s = bytes, n = bits used in the last byte (1..7 from decode: 8 bits arrive as kind 5, and unused bits are cleared; encode takes 1..8) | | 77 | 77 |
| 7 | tuple of arity n | n terms | 104, 105 | 104, or 105 above 255 |
| 8 | list of n elements, n >= 1 | n terms and a tail term | 108 | 108; 107 when every element is an integer 0..255, the tail is nil and n <= 65535 (erl's choice) |
| 9 | nil | | 106, and 107 of length 0 | 106 |
| 10 | byte list: s = the bytes; the proper list of those integers | | 107 | 107 (108 above 65535 bytes) |
| 11 | map of n pairs | 2n terms | 116 | 116, pairs in token order |
| 12 | pid, 13 reference, 14 port, 15 fun: s = the term's own ETF bytes, tag included | | 88, 103; 90, 114, 101; 120, 89, 102; 112, 113 | s, unchanged |

It can hold every term a BEAM language sends: integers of any size, floats, atoms, binaries, bit strings, tuples, proper
and improper lists, maps. Pids, references, ports and funs are carried opaquely (their bytes, checked only for their
extent) and written back unchanged, so decoding never fails on them and a node can hand one back to the peer that made
it; they are not live values. A token list is an ordinary Silica value with no region: it can be a message, state, or an
argument, and a compiler turns it into its own cells (`bees_term` v0 or another form) in its own region.

Because a value has one token form except for byte lists (kind 10 or kind 8 with small integers) and the encoder writes
both as erl does, BEES's bytes for a term equal `term_to_binary`'s except for the key order of maps (section 2).

### 3.3 Atoms

Every atom a node needs exists at compile time; a dynamic term can name any atom. Options for an atom the program does
not hold: (a) refuse the whole term (`:unknown_atom`), as typed decode does; (b) carry its text; (c) replace it with a
marker atom, losing the name. Ruled (Q3) and built: (b), for every atom, known or not: the token holds the name, and the
consumer resolves it where it needs an atom (`bees_atoms@from_spelling`, or the language's `atom_of_name`, which answers
`:none` for a name the program does not hold). No atom is created, memory is bounded by the term's own bytes, nothing is
lost, and a term that only passes through (stored, echoed, logged) never needs the atom at all. A name is refused when
it is longer than 255 characters or is not UTF-8 (`:bad_utf8`, `:too_long`). Q3.

### 3.4 Decoding within limits

One pass over the frame with an explicit stack of pending counts (no recursion in the element direction; the stack depth
is the term's nesting). Limits, all literals in the unit (D47's form): frame bytes (the caller's frame is already under
the unframe cap; the ceiling 4294967295), nesting 64 (`:too_deep`), tokens 65536 (`:too_long`; bounds memory: measured on
the pin at about 0.4 to 0.7 KB per decoded token, so about 45 MB at the token ceiling and about 3 MB under a 4096-byte
frame cap; the first draft of this note said "a few MiB", which was wrong), map pairs 1024
per map (`:too_long`; the duplicate-key check is quadratic), atom names 255 characters. Every count is checked against
the bytes left before a token is made. Refused: no 131 (`:bad_version`), a compressed term 131 80, a distribution header,
an atom cache reference, FLOAT_EXT (`:unsupported`), an unknown tag (`:bad_tag`), a cut term (`:truncated`), bytes after
the term (`:trailing_bytes`), a duplicate map key (`:duplicate_field`, compared as token runs after integers are
normalised and the pairs of every map inside a key are put in one order, so two keys that are maps with the same pairs
are equal whatever their pair order, as in erl). Leaves are converted by the derived decoder on a slice (integers that fit, floats); strings are slices.
The values are ruled (Q7).

### 3.5 The manifest

`remote name @ peer cast term` and `local name cast term`: the proxy and the deliverer use `bees_term_wire@encode` and
`bees_term_wire@decode`. A dynamic term is a whole message; a typed message cannot have a `term` field (it would need the
scanner path for every type around it; left out, said in "left undone" if not built).

## 4. Owner questions, all RULED 2026-11-18 (owner)

These are decided, not provisional.

| | Question | Options | RULED 2026-11-18 (owner) |
| --- | --- | --- | --- |
| Q1 | The 2026-11-05 ruling says an any-shape codec is the transpiler's, not BEES's; the plan row and this task ask for it. | (a) BEES owns the ETF to token conversion and nothing above it; (b) BEES also builds `bees_term` v0 cells; (c) nothing in BEES. | (a): "BEES owns the conversion from ETF to tokens and nothing above it." No `bees_term` cells and nothing else above the token list is built in BEES. |
| Q2 | May BEES read positions by hand (tags, lengths) when every value still comes from the derived decoder on a slice? | (a) yes; (b) no: maps, sets, buf and dynamic terms wait for a Silica feature. | (a): positions are read by hand, values come from the derived decoder on a slice. |
| Q3 | An atom in a dynamic term that the program does not hold. | (a) refuse the term; (b) carry the text; (c) a marker atom. | (b): the text is carried, for every atom, held or not. |
| Q4 | The wire form of a set. | (a) the `sets` map `#{E => []}`; (b) `ordsets`, a sorted list; (c) both, chosen in the manifest. | (a): the sets-module map form. |
| Q5 | The largest map and set (the duplicate check is quadratic). | 1024; a larger literal; a sort-based check and BEAM's own bound. | 1024 entries; the sort-based check when a program needs more. |
| Q6 | The depth limit of a recursive message. | 64 above the type's own nesting; a number in the manifest. | 64 above the type's own nesting. |
| Q7 | The limits of a dynamic term. | nesting 64, 65536 tokens, 1024 pairs per map; larger literals; `bees.config` options. | Nesting 64, 65536 tokens, 1024 pairs per map; later, options in `bees.config`. |
| Q8 | `buf`: the bytes in use, or always all N bytes. | (a) `{ b, n }` with n in use; (b) exactly N. | (a): the bytes in use. |
| Q9 | A value that cannot be sent (a duplicate key, too many entries, a bad `n`). | (a) not sent, like a frame over the cap; (b) fail the sending actor. | (a): not sent, as the proxy does today; the drop is to be observable in the way a frame over the cap is. |

Q9, the known gap: the proxy gives no audit or report line today for a frame over the cap.
`bees_dist@reg_send_body_max` returns the empty string and the generated proxy then casts nothing
(`case length_bytes(body) > 0 of { true -> cast(...); false -> true }`); nothing is printed, counted or reported. A value
that cannot be sent is therefore dropped just as silently. No new mechanism is added here (ruling); when the proxy gains a
report for the over-cap drop, the unsendable-value drop goes through the same line, because both reach the proxy as an
empty body.

What a transpiler supplies above the token list (Q1): its own in-memory term (for example `bees_term` v0 cells in a region
it owns) built from the tokens and flattened back to tokens to send; the resolution of atom names to its atoms
(`bees_atoms@from_spelling` or `atom_of_name`) and what it does with a name the program does not hold; term equality,
ordering and copying; the meaning of big integers and bit strings (the tokens hold only their bytes); any use of pids,
references, ports and funs, which BEES carries only as opaque bytes; and maps as a data structure (the tokens hold the
pairs in wire order, already free of duplicate keys).

RULED 2026-11-19 (owner), Q7 revisited: option (c). The compiled ceiling stays 65,536 tokens (the maximum, D47 pattern), and the application states a run-time limit at or below it, with no default; a term with more tokens than the configured limit is refused `too_long`. The option's name follows `term_depth_max`: `term_tokens_max` (to be added to bees-config-file.md with the reader change). Not built: today only the compiled ceiling applies.

RULED 2026-11-19 (owner), Q4 confirmed after the OTP 27 finding: option (a) stays. The wire form of a set is the `sets` map form only; an OTP 27 default set (the version 1 record) is refused, and an OTP 27 sender builds its sets with `sets:from_list(L, [{version, 2}])` (section 2.4).

## 5. Trials planned (one kind at a time)

`trials/c1_codec_sum`, `c1_codec_optref`, `c1_codec_term`, `c1_codec_map`, `c1_codec_set`, `c1_codec_buf`: in one
process, each value encoded, its bytes printed and compared with the bytes erl gave (fixtures written by
`tools/bees_codec_fixtures.erl` for the typed kinds and `tools/bees_term_fixtures.erl` for dynamic terms, the latter
checked by the independent Python writer `tools/bees_term_etf.py`), decoded, and the
malformed and oversized frames refused. `c1_codec_nodes`: two BEES nodes exchange every kind. `c1_codec_live`: a BEES
node sends every kind to a stock `erl`, which echoes it and reports what it saw (modelled on `n2_live`; skipped when
`erl` is not installed).

## 6. Built

All on the pin `silica-999909-macos-applesilicon`; "observed" means seen in a trial's output that was read before its
golden was recorded. Linux goldens are still to be recorded for every trial named here.

### 6.1 Sums and optional references (2, 2.1, 2.2, 2.7)

`tools/bees_wire_gen.py` reads `:name`, `(:tag, T, ...)`, `A | B | ...` and `ref?(L, normal, rec)`; every atom written in
a type goes to `bees_atoms` (`message_names`), and `bees_msgs.atoms`, `bees_peers.atoms`, `beam_peers.atoms` are written
beside the generated units (only when a type has an atom literal). A sum is one derived `encode` and one derived `decode`,
as any plain type. A type with an optional reference has the message type `{ r: region(L, normal), v: T }`:
`enc_<name>` encodes `v`, `dec_<name>(frame, r)` decodes into the caller's region with `max_depth` = nesting + 64,
`check_<name>` validates in a scratch region, and the deliverer decodes into a fresh region and casts `{ r, v }`.
Refused by the generator because the derived codec fails (pin and 999906): `(:tag)` alone (SD-57) and a sum that starts
with an atom literal and has a tagged tuple variant (SD-50). Also refused: two variants of one tag (E2404), a primitive,
list or untagged tuple variant, and any new kind in a manifest without node lines (the m1 hand codec).
Trials `c1_codec_sum` and `c1_codec_optref` (observed): bytes equal to OTP 28's `term_to_binary` for every term without a
map, erl's bytes decoded for those with one, every malformed or oversized frame refused with the language's atom, a
66-cell chain refused `too_deep` with no cell allocated (the derived decoder allocates a cell only after its inner node
decoded; read in the derived text), chains of 60 and 65 cells decoded, peak memory flat (1.8 MB) over 400,000 refusals
and over 400,000 accepted decodes (measured out of band). `too_deep` cannot occur for a non-recursive type: a deeper frame
fails the type first. Existing output unchanged: the 20 leaves with a `.wire` manifest generate identical files with the
generators before and after. Fixtures: `tools/bees_codec_fixtures.erl`. Six more compiler defects that a program meets
when it handles these values (SD-51 to SD-55, SD-58) are worked around in the trial sources.

### 6.2 The scanner and dynamic terms (1, 3)

`src/inter_nodal/bees_etf_scan.silica`: positions only (`skip`, `skip_within`, `tag_at`, `map_count`/`map_first`,
`tuple_arity`/`tuple_first`, `list_count`/`list_first`, `atom_check`/`atom_text`/`atom_is`, `slice_term`, `body_of`,
`bytes_compare`/`bytes_less`), negative codes numbered as `bees_ingress` numbers them, nesting 64, tail-recursive over
elements. It also holds the four derived-codec leaf calls (`leaf_int`, `leaf_float`, `int_term`, `float_term`) because a
unit that exports functions named `decode` and `encode` cannot call the builtins of those names (E2020, SD-56).
`src/inter_nodal/bees_term_wire.silica`: `decode`, `decode_within`, `encode`, `term_size`, `term_end`, constructors
(`t_int` ... `t_fun`) and accessors over `List[(int64, int64, float64, string), mem(normal)]`, kinds 1..15 as in 3.2; one
pass with an explicit stack; limits 64 / 65536 tokens / 1024 pairs / 255-character atoms. Normalised on decode: a bit
string of 8 bits is a binary, unused bits are cleared, an empty STRING_EXT is nil. Stricter than erl: LIST_EXT of 0
elements (`:bad_tag`), a big-integer sign byte above 1 (`:out_of_range`), trailing bytes (`:trailing_bytes`). A map header
is checked against 1024 pairs before the bytes left, and the token limit at each container header before any child is
read. Encode returns the empty string for a token list that is not one well-formed term. Known asymmetry: a byte list of
65536 bytes or more encodes (as LIST_EXT) but its frame needs more tokens than decode allows.
Trial `c1_codec_term` (observed): 54 erl fixtures decode and re-encode to the same bytes (integers to 2048 bits, -0.0,
255-character and UTF-8 atoms, bit strings, a 300-element tuple, improper lists, nested maps, a `sets` map, pid,
reference, port, export fun and local fun); 19 forms erl reads but does not write; 32 constructor-built terms; the decode
and encode refusals; every prefix of two fixtures refused; every byte of both changed without a fault; 64 levels accepted
and 65 refused; 60,002-token terms decoded and encoded. `tools/bees_term_etf.py` (independent writer, reader and token
mirror) and `tools/test_bees_term_etf.py` predict the golden and cross-check erl in both directions, including that
`binary_to_term` refuses exactly the duplicate-key frames BEES refuses. Not measured: a worst-case key that is itself a
1024-pair map (the sort inside a key is quadratic); behaviour inside a long-lived actor. A single activation that
allocates past about 256 MiB faults (seen once, not reduced, so not numbered; silica-defects.md, 2026-11-19), far above what
these limits allow.

### 6.3 Maps, sets, buf, the `term` message type, wide records (2.3 to 2.6, 3.5)

Generated per node by `bees_wire_gen.Split` over the hand-written helpers `src/inter_nodal/bees_codec_kinds.silica` (frame
check, part cutting, tuple, record, list and map positions, the duplicate check) and `bees_etf_scan`; every key, value and
plain part is one derived call. Plain types generate the text they generated before (22 leaves with a `.wire` manifest:
identical files).

Map: `Map[K, V]` is `List[(K, V), mem(normal)]`, MAP_EXT, pairs in the list's order out and wire order in; 1024 pairs at
most and no key twice in either direction (keys compared by the derived re-encoding, so 5 as tag 97 and as tag 110 is one
key); a value that cannot be sent gives the empty string and the proxy sends nothing. Trial `c1_codec_map` (observed):
bytes equal erl's for the empty map and for ascending integer, string and tuple keys, in a record field, with list, sum
and map values, in a list; erl's bytes decode in erl's own order, a 40-key map in hash order included; 1024 accepted and
1025 refused both ways; a count of 2^32-1 is `:too_long` from the header (`:truncated` when the map is nested, because the
outer scan meets it first).

Set: `Set[T]` is `List[T, mem(normal)]`, the map `#{E => []}`. A value other than NIL is `:bad_tag` (an `ordsets` list
too), a repeated element `:duplicate_field`, more than 1024 `:too_long`. Trial `c1_codec_set`.

buf: `{ b, n }`, the n bytes in use as BINARY_EXT; the message is `{ r: region(L, normal), v: T }`. Decode is the derived
string decode with `max_length: N` (so STRING_EXT and NIL are taken as well), then `alloc_buf` in the caller's region and
a `write_buf` loop; n outside 0..N is not sent. Trial `c1_codec_buf`, with deliverers that cast `{ r, v }` to actors which
read the buffer.

term: `cast term` makes the message `bees_term_wire`'s token list; `bees_msgs` gains `use bees_term_wire;` only then.
Trial `c1_codec_termmsg`.

Wide records: while `SD37_SPLIT` is set in `tools/bees_wire_gen.py` a record of more than four fields is converted field
by field (bytes equal the derived encoder's, which does compile on the pin; only the derived decoder does not). Field
errors are found before values are decoded, so where a frame has both a bad value and a bad key the reason can differ
from the derived decoder's. Deleting the constant restores one derived call (unit-tested as text; the pin cannot compile
it). Trial `c1_codec_wide`.

Memory, out of band: 2 to 11 MB peak over 5000 repeats of refused and accepted frames in each trial.

### 6.4 Across the link: two BEES nodes, and a stock erl (2.1 to 2.7, 3.2, 3.5)

What the in-process trials infer (that the proxies and deliverers generated for the new kinds carry them) is observed here,
in BEAM mode, through the generated proxies (`bees_peers@proxy_<name>`, `beam_peers@proxy_<name>`) and deliverers.

`trials/c1_codec_nodes` (port block 24000): two Silica programs (separate processes) on the BEAM-mode node with
`{auth, none}` on 127.0.0.1 (a TEST setting). Node a casts to node b one message of each kind: a sum value of each variant
shape (four tagged tuples, a record, an atom), a three-cell recursive chain with its region, `Map[int64, string]`,
`Set[int64]`, a record holding a `buf` of 16 with its region, a six-field record (the SD-37 split path), and a dynamic term
of 14 elements (small and big integers, a float, atoms, one that no manifest of b holds, a binary, a bit string, a tuple,
a byte list, a proper and an improper list, a map). b prints each (the chain walked and the buffer read in the region that
came with the message, the term's tokens) and casts it back through its own proxies; a prints the echo, then sends the
next. For the map, set, buf and term a value the encoder refuses (a key twice, an element twice, `n` of 17 and -1 for a
buffer of 16, a token list that is not one term) is cast first: nothing arrives for it, nothing fails, and the good value
cast right behind it through the same proxy arrives next (Q9: not sent, silently; the known gap of section 4).

`trials/c1_codec_live` (port block 24100, private EPMD at +90; `tools/bees_codec_live.py`, `codec_driver.erl`): one BEES
node (BEAM mode, cookie authentication) against `erl -sname stock@localhost` (the installed erl: OTP 28 on the Mac, OTP 27 on the Linux machine). Phase 1: BEES casts each
kind as above to a registered process of the stock node (sets on the erl side are built with `[{version, 2}]`, so the
trial checks the ruled form under OTP 27 and 28), which prints the term as Erlang sees it, checks it `=:=` the term
expected (true for all 17 messages), prints `term_to_binary` where the bytes are canonical, and sends it back to a typed name of
BEES, where the deliverer decodes it. Seen from erl: the sum values are the tuples, map and atom erl writes; the chain is
`{ok,3,{ok,2,{ok,1,none}}}`; the map `#{1 => <<"a">>,...}`; the set `#{1 => [],2 => [],3 => []}`, for which
`sets:is_set/1` is true; the buf record `#{data => <<222,173,190,239>>, id => 7, note => <<"n">>}`; the six-field record a map
with six atom keys; the dynamic term the 14-element tuple, big integer `1208925819614629174706176` (2^80) and bit string `<<5:3>>`
included. Phase 2: erl sends terms that do not fit a typed name (a tag, arity or variant the sum lacks; a 66-cell chain;
an atom where the slot needs `none`; a map with a wrong key or value type; a list of pairs; a plain list, an `ordsets`
list, a version 1 `sets` record or a map whose values are not `[]` where a set is expected; 17 bytes for a buffer of 16; a record with a field missing
or added, or an atom BEES does not hold): BEES drops each with the decoder's reason in its audit (`bad_variant`, `bad_tag`,
`too_deep`, `too_long`, `missing_field`, `unknown_field`, `unknown_atom`) and the fitting term behind it arrives (a 65-cell
chain among them). Phase 3: erl sends arbitrary terms to the name whose type is `term` (`self()`, `make_ref()`, a port, an
export fun and a local fun, an atom BEES never saw, a map with a pid key and a fun key); BEES prints the tokens (kinds
12 to 15 carried as bytes) and casts the token list back; erl confirms each echo `=:=` the original, so pids, references,
ports and funs made by erl come back to it usable. A machine without `erl`, `erlc` or `epmd` reports the trial skipped.

Both trials passed five runs in a row on the pin (2026-11-19). Linux goldens are not recorded.

### 6.5 Restrictions: compiler limit or BEES choice

Each was checked with a small program in a scratch directory on the pin and on silica-999906 (same result on both unless
said). The repro text is given so that it can be re-run.

| Restriction | Kind | Evidence |
| --- | --- | --- |
| `buf` only directly inside tuples and records (not in a list, map, set or sum) | BEES choice | Silica holds a list of records that hold buffers of one region and reads them back (`xs: List[{ b: buf(L, normal, uint8, 4), n: int64 }, mem(normal)] <- [a, a]`, then `read_buf(h.b, 0)` on the head: prints 7, both compilers). What is missing is a generated conversion: the derived codec refuses `buf` by design (E2401), so a list of buffers would need a hand-generated loop with `alloc_buf` per element; it was not built. |
| A sum variant may not hold a `Map`, `Set` or `buf` | BEES choice | Silica holds them: `(:b, { b: buf(L, normal, uint8, 4), n: int64 }) \| :none` is built, passed, matched and its buffer read (prints 109); `(:m, List[(int64, string), mem(normal)]) \| (:s, List[int64, mem(normal)]) \| :none` is built and matched and even crosses the derived codec, as nested lists (prints 2 and 2). The generated decoders themselves return `(:ok, { b: buf(...), n: int64 }) \| (:rejected, atom)`. Refused because the variant choice is the derived decoder's; carrying these would mean re-implementing variant selection by hand in the generator. |
| A sum variant may not hold a record of more than four fields | Compiler limit on the pin (SD-37) | `v: (:w, { a: int64, b: int64, c: int64, d: int64, e: int64 }) \| :none`, `encode((:etf), v)`, `decode((:etf), frame)`: on the pin the derived `__tr_decm_etf_...` has nine parameters and fails ("more than 8 parameters"); on 999906 it compiles and prints 5. Goes away when the pin moves past SD-37 (delete `SD37_SPLIT`). |
| A tuple or record on the split path has at most 7 parts (6 with a buf) | BEES choice bounded by a compiler limit | The limit itself is the compiler's: `fn f(a: int64, ..., j: int64)` with nine parameters is E1070 on both compilers (the AArch64 calling convention: eight register arguments), so it is not a defect. Using one parameter per decoded part is BEES's generated shape: the same nine values pass as `fn f(p: (int64, int64, int64, int64, int64, int64, int64, int64), j: int64)` (prints 45, both). Liftable in the generator by passing the parts decoded so far as one tuple. |
| A tag-only tuple `(:tag)` | Compiler defect, SD-57 | `trials/silica_defects/sd57_bare_tag_variant_encode_faults` (encode faults at run time; first-variant form E2005), both compilers. A program writes the atom `:tag`. |
| A sum mixing a bare atom literal and a tagged tuple | Compiler defect, SD-50, only when the atom literal is the first variant | `trials/silica_defects/fail_sd50_sum_atom_first_with_tagged_tuple` (E2005 in the derived decoder), both compilers. The other order works and is used by every trial (`(:i, int64) \| ... \| :none`); the generator asks for it. |
| A map's key or a set's element holding a `Map`, `Set`, `buf` or optional reference | BEES choice | Section 2.3: keys are compared by their encoding. |
| A type with both an optional reference and a Map, Set, buf or wide record | BEES choice | The recursive tuple is one derived call; splitting it would mean a hand-written recursion over the chain. |

Silica defects of this work: SD-50 to SD-58 in development-plan/silica-defects.md (2026-11-19), each with a repro in
`trials/silica_defects`; all nine unchanged on silica-999906.

### 6.5a Stack use per element (SD-59, found on Linux 2026-11-19)

The loops written as tail calls are not all tail calls in the compiled code: a self call of a function that returns a
record, and any mutual call, is a real call (SD-59). So decode (`bees_term_wire@run`, which returns `{ code, toks }`),
encode (`enc_run`), `walk`, the key checks, the generated Map and Set loops and `bees_codec_kinds` use one stack frame per
token, pair or element. Much of what section 3.4 called memory per token (about 0.4 to 0.7 KB, about 100 MB peak for
60,002 tokens on the Mac) is this stack. On the Mac the main actor's stack hides it; on Linux `c1_codec_term` faults in
part 6 (main runs on the 8 MiB process stack; a 5,000-element list, 10,002 tokens, already faults:
`trials/_probes/c1_codec_term/scale`). Inside a node the deliverers are actors, whose stack reservation follows the
machine's memory, so the node trials pass on both machines; on a small device it would not. The language's own derived
list codec has the same property and is outside BEES.

Plan (not done): rewrite each per-element loop as a self call that returns a list or a scalar (the result code carried as
a first element or a separate pass), the generated Map/Set loops as one self-recursive function per node, and re-measure;
until then the Linux golden of `c1_codec_term` is not recorded.

RULED 2026-11-19 (owner): BEES does not rewrite its loops around SD-59; the limit is documented (contract/what-is-required-to-use.md section 7) and the fix is Silica's. The planned rewrite of `run`, `enc_run`, `walk`, `keys_of`, `canon_*`, the generated Map/Set loops, `bees_codec_kinds` and the scanner is therefore not done. The Linux golden of `c1_codec_term` stays unrecorded: its part 6 (a 30,000-element term decoded in `main`) cannot pass on Linux's 8 MiB main stack while SD-59 stands.

### 6.6 Left undone

Linux golden of `c1_codec_term` (blocked by 6.5a; the other C1 Linux goldens are recorded). A typed message with a `term` field (3.5). A report line for a value the proxy does not
send (Q9's known gap). The sort-based duplicate check for maps and sets above 1024 entries (Q5). Measuring the worst-case
dynamic-term key that is itself a 1024-pair map. The lifts named in 6.5 (buf in lists, Map/Set/buf in sum variants,
more than 7 split parts), none asked for.
