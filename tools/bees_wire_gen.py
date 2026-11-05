#!/usr/bin/env python3
"""bees_wire_gen: the wire-codec half of tools/bees_config.py (MVP milestone M1b: typed messages as ETF).

Not run directly; `bees_config.py wire -o DIR MANIFEST...` and `bees_config.py generate` call it.

A `<unit>.wire` manifest is line oriented, `#` starts a comment:

    message <name> <silica type>

`<name>` is an identifier unique program-wide. A message is addressed by its NAME: the target of an Erlang
REG_SEND is a registered name (an atom), and the generated unit finds the message type from it (`index_of`). The
type is the text of Silica's own type syntax, restricted to:

    int8 int16 int32 int64 uint8 uint16 uint32 uint64 float32 float64 boolean char atom string
    (T, T, ...)                     tuple, two or more components
    { f: T, g: T, ... }             record, one or more fields
    List[T]  or  List[T, mem(normal)]

Everything else is a build error that names the message, the field path and the type: actor_ref,
supervisor_ref, regions and references (region, ref, ref?), buf, function types, sum types (`|`),
atom literal types (tagged tuples), unit, standard data structures, any unknown name.

The encoding is ETF, as `term_to_binary/1` of OTP 26+ writes it (a frame is `131` and one term):

    integers   SMALL_INTEGER_EXT / INTEGER_EXT / SMALL_BIG_EXT (the smallest, as erl chooses); chars as integers
    floats     NEW_FLOAT_EXT (a float32 as the float64 of the same value)
    boolean    the atoms true and false          atom     SMALL_ATOM_UTF8_EXT      string   BINARY_EXT
    tuple      SMALL_TUPLE_EXT / LARGE_TUPLE_EXT record   MAP_EXT with atom keys, in name order
    List[T]    LIST_EXT, elements, NIL_EXT; the empty list is NIL_EXT; a list whose elements are all 0..255
               (integers or chars) is STRING_EXT, as erl writes it

and the decoder accepts every valid encoding of the same value (see development-plan/spikes/M1b-etf-codec.md): the
other atom tags, STRING_EXT for byte lists, SMALL_BIG_EXT for any integer that fits, map keys in any order.

Generated, into OUT_DIR, deterministically and with no BEAM atom literal:

  bees_wire_tables.silica  constant lookup tables: byte <-> every integer width, and the ASCII text tables (no type
                           conversion exists in Silica, so every conversion is a lookup).
  bees_wire_ints.silica    constant: enc_<int type>, dec_<int type>, dec_byte_<int type>, put_byte_<int type> and
                           is_byte_<int type> for the eight integer widths, over the core's integer header.
  bees_wire_msgs.silica    per message: enc_<name>, dec_<name>, msg_index_<name>; and msg_count, index_of (the
                           message type of a target name), validate, validate_named (the dispatcher by index,
                           tiered at 256 arms), plus one helper group per distinct type.
"""
import os
import re
import sys

# ---- limits: the one place the build knows them. bees_wire.silica holds the run-time copy
# (max_frame, max_depth, ...); tools/test_bees_wire_gen.py checks the two agree. ----
MAX_FRAME = 4096
MAX_DEPTH = 16
MAX_LIST = 256
MAX_ATOM = 255
MAX_STRING = 1024
MAX_KINDS = 65536

TIER = 256
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

INT_TYPES = {
    # name: (bytes, signed)
    "int8": (1, True), "int16": (2, True), "int32": (4, True), "int64": (8, True),
    "uint8": (1, False), "uint16": (2, False), "uint32": (4, False), "uint64": (8, False),
}
PRIMS = set(INT_TYPES) | {"float32", "float64", "boolean", "char", "atom", "string"}
# the smallest ETF encoding of a primitive, in bytes (used to bound a list count by the bytes left)
PRIM_MIN = {"int8": 2, "int16": 2, "int32": 2, "int64": 2, "uint8": 2, "uint16": 2, "uint32": 2,
            "uint64": 2, "float32": 9, "float64": 9, "boolean": 6, "char": 2, "atom": 2, "string": 5}
# the name each non-integer primitive has in the core (bees_wire@enc_<n>, bees_wire@dec_<n>)
PRIM_CORE = {"float32": "f32", "float64": "f64", "boolean": "bool", "char": "char", "atom": "atom", "string": "string"}
# a list of these can be written as STRING_EXT (every element 0..255) and read from one
BYTE_CAPABLE = set(INT_TYPES) | {"char"}

KEYWORDS = set("""actor actor_ref atom atomic boolean buf case call_supervisor cast char concurrency core_id
core_set dangerous_actor_ref device_actor_ref device_io device_window effect efficiency_cores else end enum
export false float16 float32 float64 fn for from hot_swap if impl import int8 int16 int32 int64 lifetime
mailbox mem module network_io normal not of performance_cores proc produces provided pub pure recv ref
region register_rwr required return sequence spawn spawn_dangerous spawn_device spawn_device_registered
spawn_registered spawn_registered_supervisor string struct supervisor_ref trait true type uint8 uint16 uint32
uint64 underscore unit use where foreign explicit update""".split())

UNSUPPORTED = {
    "actor_ref": "actor references are not portable between nodes",
    "supervisor_ref": "supervisor references are not portable between nodes",
    "dangerous_actor_ref": "actor references are not portable between nodes",
    "device_actor_ref": "actor references are not portable between nodes",
    "region": "regions cannot cross the wire",
    "ref": "references cannot cross the wire",
    "ref?": "optional references cannot cross the wire",
    "buf": "buffers are not supported on the wire yet",
    "fn": "function types cannot cross the wire",
    "float16": "float16 is not supported (no exact conversion exists without type conversion)",
    "unit": "the unit type cannot be written in a Silica signature (E2006), so no message can have it",
    "lifetime": "lifetimes cannot cross the wire",
    "timer_ref": "timer references cannot cross the wire",
    "Map": "standard data structures are not supported on the wire yet",
    "Set": "standard data structures are not supported on the wire yet",
    "Tree": "standard data structures are not supported on the wire yet",
    "Heap": "standard data structures are not supported on the wire yet",
    "Queue": "standard data structures are not supported on the wire yet",
    "PriorityQueue": "standard data structures are not supported on the wire yet",
}

# The language's rejection reasons, in the code order bees_wire.silica uses (1..16); the atoms are declared in
# src/inter_nodal/bees_wire.atoms.
REASONS = ["bad_version", "truncated", "trailing_bytes", "bad_tag", "too_large", "too_deep", "too_long",
           "out_of_range", "bad_utf8", "unknown_atom", "bad_variant", "missing_field", "duplicate_field",
           "unknown_field", "foreign_actor", "unsupported"]
WIRE_ATOMS = REASONS


class WireError(Exception):
    pass



# ---------------------------------------------------------------- manifest and type grammar

TOKEN = re.compile(r"\s*(->|[A-Za-z_][A-Za-z0-9_]*\??|[0-9]+|[(){}\[\],:|<>=.@*&?-])")


def tokenize(text, where):
    toks, i, text = [], 0, text.rstrip()
    while i < len(text):
        m = TOKEN.match(text, i)
        if not m:
            raise WireError(f"{where}: cannot read the type at '{text[i:].strip()[:20]}'")
        toks.append(m.group(1))
        i = m.end()
    return toks


class Parser:
    def __init__(self, toks, where, msg):
        self.t, self.i, self.where, self.msg = toks, 0, where, msg

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else None

    def take(self, want=None):
        tok = self.peek()
        if tok is None or (want is not None and tok != want):
            raise WireError(f"{self.where}: message {self.msg}: expected '{want or 'a type'}' but found "
                            f"'{tok if tok is not None else 'end of line'}'")
        self.i += 1
        return tok

    def fail(self, path, ty, why):
        raise WireError(f"{self.where}: message {self.msg}: field '{path}' has type '{ty}', which is not "
                        f"supported on the wire: {why}")

    def parse_type(self, path):
        """-> ('prim', name) | ('tuple', [t]) | ('record', [(f, t)]) | ('list', t)"""
        tok = self.take()
        if tok in PRIMS:
            ty = ("prim", tok)
        elif tok == "(":
            comps = []
            while True:
                comps.append(self.parse_type(f"{path}.{len(comps)}" if path != "<value>" else str(len(comps))))
                if self.peek() == ",":
                    self.take(",")
                    continue
                break
            self.take(")")
            if len(comps) < 2:
                self.fail(path, "(" + canon(comps[0]) + ")", "a tuple has two or more components")
            ty = ("tuple", comps)
        elif tok == "{":
            fields = []
            while True:
                f = self.take()
                if not IDENT.fullmatch(f):
                    raise WireError(f"{self.where}: message {self.msg}: '{f}' is not a field name")
                if f in KEYWORDS:
                    raise WireError(f"{self.where}: message {self.msg}: field '{f}' is a Silica keyword and "
                                    f"cannot name a record field")
                if any(f == g for g, _ in fields):
                    raise WireError(f"{self.where}: message {self.msg}: field '{f}' is listed twice")
                self.take(":")
                fields.append((f, self.parse_type(f if path == "<value>" else f"{path}.{f}")))
                if self.peek() == ",":
                    self.take(",")
                    continue
                break
            self.take("}")
            ty = ("record", fields)
        elif tok == "List":
            self.take("[")
            elem = self.parse_type(path + "[]")
            if self.peek() == ",":
                self.take(",")
                for want in ("mem", "(", "normal", ")"):
                    if self.peek() != want:
                        self.fail(path, "List[...]", "the only list form is List[T] or List[T, mem(normal)]")
                    self.take()
            self.take("]")
            ty = ("list", elem)
        elif tok.startswith(":"):
            self.fail(path, ":" + (self.peek() or ""), "atom literal types (tagged tuples) are not supported; "
                      "use `atom`")
        elif tok in UNSUPPORTED:
            self.fail(path, tok, UNSUPPORTED[tok])
        elif IDENT.fullmatch(tok):
            self.fail(path, tok, "unknown type name")
        else:
            self.fail(path, tok, "not a type")
        if self.peek() == "|":
            self.fail(path, canon(ty) + " | ...", "sum types are not supported")
        return ty


def canon(ty):
    kind = ty[0]
    if kind == "prim":
        return ty[1]
    if kind == "tuple":
        return "(" + ",".join(canon(t) for t in ty[1]) + ")"
    if kind == "record":
        return "{" + ",".join(f"{f}:{canon(t)}" for f, t in ty[1]) + "}"
    return "List[" + canon(ty[1]) + "]"


def silica(ty):
    kind = ty[0]
    if kind == "prim":
        return ty[1]
    if kind == "tuple":
        return "(" + ", ".join(silica(t) for t in ty[1]) + ")"
    if kind == "record":
        return "{ " + ", ".join(f"{f}: {silica(t)}" for f, t in ty[1]) + " }"
    return "List[" + silica(ty[1]) + ", mem(normal)]"


def depth_of(ty):
    """Nesting of composites (a primitive is 0)."""
    kind = ty[0]
    if kind == "prim":
        return 0
    if kind == "list":
        return 1 + depth_of(ty[1])
    parts = [t for t in ty[1]] if kind == "tuple" else [t for _, t in ty[1]]
    return 1 + max(depth_of(t) for t in parts)


def min_size(ty):
    """The smallest ETF encoding of a value of this type, in bytes (the 131 version byte excluded)."""
    kind = ty[0]
    if kind == "prim":
        return PRIM_MIN[ty[1]]
    if kind == "list":
        return 1
    if kind == "tuple":
        return (2 if len(ty[1]) <= 255 else 5) + sum(min_size(t) for t in ty[1])
    return 5 + sum(2 + len(f) + min_size(t) for f, t in ty[1])



def parse_wire(path):
    """-> list of (name, type, canonical text); warnings go to stderr."""
    msgs = []
    with open(path) as fh:
        for n, line in enumerate(fh, 1):
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            where = f"{path}:{n}"
            parts = line.split(None, 2)
            if parts[0] != "message" or len(parts) != 3:
                raise WireError(f"{where}: cannot read '{line}' (expected: message <name> <type>)")
            name, text = parts[1], parts[2]
            if not IDENT.fullmatch(name) or name in KEYWORDS:
                raise WireError(f"{where}: '{name}' is not a usable message name")
            toks = tokenize(text, where)
            p = Parser(toks, where, name)
            ty = p.parse_type("<value>")
            if p.peek() is not None:
                raise WireError(f"{where}: message {name}: unexpected '{p.peek()}' after the type")
            msgs.append((name, ty, where))
    return msgs


def collect(paths, warn=True):
    msgs = []
    for p in paths:
        msgs += parse_wire(p)
    seen = {}
    for name, _, where in msgs:
        if name in seen:
            raise WireError(f"{where}: message {name} is already declared at {seen[name]}")
        seen[name] = where
    if len(msgs) > MAX_KINDS:
        raise WireError(f"{len(msgs)} messages ({MAX_KINDS} at most)")
    for name, ty, where in msgs:
        if warn and depth_of(ty) > MAX_DEPTH:
            print(f"bees_config: {where}: warning: message {name} nests {depth_of(ty)} levels, above the wire "
                  f"limit of {MAX_DEPTH}; every frame of it will be rejected as too_deep", file=sys.stderr)
        # the value must fit in a frame: smallest encoding is checked, the largest is a run-time matter
        if min_size(ty) + 1 > MAX_FRAME:
            raise WireError(f"{where}: message {name}: even its smallest encoding does not fit in a "
                            f"{MAX_FRAME}-byte frame")
    return [(n, t) for n, t, _ in msgs]


# ---------------------------------------------------------------- tables

def emit_switch(lines, name, params, sel, ret, arms, default):
    """`fn name(params) -> ret` as a `case sel of` with at most TIER arms per case: above that the arms go
    to helpers name_0, name_1, ... and `name` picks one by `sel < boundary` tests. arms: [(int key, expr)]."""
    arms = sorted(arms)
    sig = ", ".join(f"{n}: {t}" for n, t in params)
    call_args = ", ".join(n for n, _ in params)
    chunks = [arms[i:i + TIER] for i in range(0, len(arms), TIER)]

    def body(ch):
        out = ["    case " + sel + " of {"]
        for k, e in ch:
            out.append(f"        {k} -> {e};")
        out.append(f"        _: int64 -> {default}")
        out.append("    }")
        return out

    if len(chunks) <= 1:
        lines.append(f"fn {name}({sig}) -> {ret} {{")
        lines += body(chunks[0] if chunks else [])
        lines += ["}", ""]
        return
    for k, ch in enumerate(chunks):
        lines.append(f"fn {name}_{k}({sig}) -> {ret} {{")
        lines += body(ch)
        lines += ["}", ""]

    def tree(lo, hi):
        if lo == hi:
            return f"{name}_{lo}({call_args})"
        mid = (lo + hi + 1) // 2
        return f"case {sel} < {chunks[mid][0][0]} of {{ true -> {tree(lo, mid - 1)}; false -> {tree(mid, hi)} }}"

    lines += [f"fn {name}({sig}) -> {ret} {{", "    " + tree(0, len(chunks) - 1), "}", ""]

# the text bytes: ASCII, 0..127 (valid UTF-8 beyond ASCII is :unsupported, anything else :bad_utf8)
TEXT_BYTES = list(range(128))


def char_literal(c):
    if c in (39, 92):
        return "'\\" + chr(c) + "'"
    if 32 < c < 127:
        return "'" + chr(c) + "'"
    return {10: "'\\n'", 9: "'\\t'", 13: "'\\r'"}.get(c, "'\\x%02x'" % c)


def string_literal(c):
    if c in (34, 92):
        return '"\\' + chr(c) + '"'
    if 32 <= c < 127:
        return '"' + chr(c) + '"'
    return {10: '"\\n"', 9: '"\\t"', 13: '"\\r"'}.get(c, '"\\x%02x"' % c)


def gen_tables(out_dir):
    L = ["// Generated by tools/bees_config.py (wire). Do not edit. Constant lookup tables for bees_wire:",
         "// Silica has no type conversion, so a byte becomes a typed integer, and back, only through a lookup.",
         "// Every case has at most 256 arms. Signed top bytes (tab_s8_*) map 128..255 to -128..-1.",
         "module bees_wire_tables;", ""]
    exports = []

    def table(name, ptype, ret, arms, default):
        exports.append(f"{name}/1")
        L.append(f"fn {name}(b: {ptype}) -> {ret} {{")
        L.append("    case b of {")
        for k, v in arms:
            L.append(f"        {k} -> {v};")
        L.append(f"        _: {ptype} -> {default}")
        L.append("    }")
        L.append("}")
        L.append("")

    byte = list(range(256))
    for ty in ("int64", "int32", "int16", "uint16", "uint32", "uint64"):
        table("tab_u8_" + ty, "uint8", ty, [(i, i) for i in byte[:255]], 255)
    for ty in ("int8", "int16", "int32", "int64"):
        table("tab_s8_" + ty, "uint8", ty, [(i, i if i < 128 else i - 256) for i in byte[:255]], -1)
    # low byte of a non-negative value of each width: n % 256 chosen by case. A `case n % 256` over a
    # width other than int64 cannot infer its scrutinee, so a one-line helper holds the remainder.
    for ty in ("int16", "int32", "uint16", "uint32", "uint64"):
        L.append(f"fn rem_{ty}(n: {ty}) -> {ty} {{ n % 256 }}")
        L.append("")
    for ty in ("int64", "int32", "int16", "uint16", "uint32", "uint64"):
        exports.append(f"lb_{ty}/1")
        L.append(f"fn lb_{ty}(n: {ty}) -> uint8 {{")
        L.append("    case " + ("n % 256" if ty == "int64" else f"rem_{ty}(n)") + " of {")
        for i in byte[:255]:
            L.append(f"        {i} -> {i};")
        L.append(f"        _: {ty} -> 255")
        L.append("    }")
        L.append("}")
        L.append("")
    exports.append("lb_int8/1")
    L.append("fn lb_int8(n: int8) -> uint8 {")
    L.append("    case n of {")
    for i in range(-128, 127):
        L.append(f"        {i} -> {i % 256};")
    L.append("        _: int8 -> 127")
    L.append("    }")
    L.append("}")
    L.append("")
    # text: the byte <-> one-character string and char tables, ASCII 0..127
    exports.append("tab_text_str/1")
    L.append("fn tab_text_str(b: uint8) -> string {")
    L.append("    case b of {")
    for c in TEXT_BYTES[:-1]:
        L.append(f"        {c} -> {string_literal(c)};")
    L.append(f"        _: uint8 -> {string_literal(TEXT_BYTES[-1])}")
    L.append("    }")
    L.append("}")
    L.append("")
    exports.append("tab_text_char/1")
    L.append("fn tab_text_char(b: uint8) -> char {")
    L.append("    case b of {")
    for c in TEXT_BYTES[:-1]:
        L.append(f"        {c} -> {char_literal(c)};")
    L.append(f"        _: uint8 -> {char_literal(TEXT_BYTES[-1])}")
    L.append("    }")
    L.append("}")
    L.append("")
    exports.append("tab_str_byte/1")
    L.append("fn tab_str_byte(c: string) -> int64 {")
    L.append("    case c of {")
    for c in TEXT_BYTES:
        L.append(f"        {string_literal(c)} -> {c};")
    L.append("        _: string -> -1")
    L.append("    }")
    L.append("}")
    L.append("")
    exports.append("tab_char_byte/1")
    L.append("fn tab_char_byte(c: char) -> int64 {")
    L.append("    case c of {")
    for c in TEXT_BYTES:
        L.append(f"        {char_literal(c)} -> {c};")
    L.append("        _: char -> -1")
    L.append("    }")
    L.append("}")
    L.append("")
    head = L[:4]
    body = L[4:]
    text = head + [f"export {e};" for e in exports] + [""] + body
    with open(os.path.join(out_dir, "bees_wire_tables.silica"), "w") as out:
        out.write("\n".join(text))


# ---------------------------------------------------------------- the typed integer widths

IH = "{ neg: boolean, hi: int64, lo: int64, pos: int64 }"
BUF = "rg: region(L, normal), b: buf(L, normal, uint8, 4096)"


def gen_ints(out_dir):
    """bees_wire_ints: for each integer width T, over the core's integer header (bees_wire@int_hdr: a sign and a
    magnitude in two halves hi:lo, each below 2^32):
      dec_T / dec_byte_T   range-check the halves against T and build a T from them (byte lookups and Horner steps in
                           T's own arithmetic; no type conversion exists), or reject out_of_range;
      enc_T                split a T into the halves (the value w, or -(w+1) for a negative one) and let the core write
                           the smallest of SMALL_INTEGER_EXT / INTEGER_EXT / SMALL_BIG_EXT;
      put_byte_T / is_byte_T   a value 0..255 as one byte, and the test, for STRING_EXT lists."""
    L = ["// Generated by tools/bees_config.py (wire). Do not edit. The eight integer widths over the core's ETF integer",
         "// header (bees_wire@int_hdr / emit_int); constant, the same for every schema.",
         "module bees_wire_ints;", "use bees_wire;", "use bees_wire_tables;", ""]
    ex = []
    body = []
    A = body.append
    A("fn tab_u8_int64(b: uint8) -> int64 { bees_wire_tables@tab_u8_int64(b) }")
    A("fn lb_int64(n: int64) -> uint8 { bees_wire_tables@lb_int64(n) }")
    A("fn tab_s8_int8(b: uint8) -> int8 { bees_wire_tables@tab_s8_int8(b) }")
    A("fn lb_int8(n: int8) -> uint8 { bees_wire_tables@lb_int8(n) }")
    for t in ("int16", "int32", "uint16", "uint32", "uint64"):
        A(f"fn tab_u8_{t}(b: uint8) -> {t} {{ bees_wire_tables@tab_u8_{t}(b) }}")
    for t in ("int16", "int32", "uint16", "uint32", "uint64"):
        A(f"fn lb_{t}(n: {t}) -> uint8 {{ bees_wire_tables@lb_{t}(n) }}")
    A(f"fn mk_ih(neg: boolean, hi: int64, lo: int64, pos: int64) -> {IH} {{ bees_wire@ih(neg, hi, lo, pos) }}")
    A(f"fn byte_hdr({BUF}, len: int64, pos: int64) -> {IH} {{")
    A("    case bees_wire@have(len, pos, 1) of {")
    A("        true -> mk_ih(false, 0, bees_wire@rb_i(rg, b, pos), pos + 1);")
    A("        false -> mk_ih(false, 0, 0, bees_wire@fail(pos, 2))")
    A("    }")
    A("}")
    A("fn lim(neg: boolean, m: int64) -> int64 { case neg of { true -> m + 1; false -> m } }")
    A("")
    for t, (nb, signed) in INT_TYPES.items():
        ex += [f"enc_{t}/4", f"dec_{t}/4", f"dec_byte_{t}/4", f"put_byte_{t}/4", f"is_byte_{t}/1"]
        # ---- decode
        if t == "uint8":
            fits = "neg == false and hi == 0 and lo <= 255"
        elif t == "uint16":
            fits = "neg == false and hi == 0 and lo <= 65535"
        elif t == "uint32":
            fits = "neg == false and hi == 0"
        elif t == "uint64":
            fits = "neg == false"
        elif t == "int64":
            fits = ("case neg of { true -> hi < 2147483648 or (hi == 2147483648 and lo == 0); "
                    "false -> hi < 2147483648 }")
        else:
            top = {"int8": 127, "int16": 32767, "int32": 2147483647}[t]
            fits = f"hi == 0 and lo <= lim(neg, {top})"
        A(f"fn fits_{t}(neg: boolean, hi: int64, lo: int64) -> boolean {{ {fits} }}")
        # the bytes of the magnitude, most significant first, as uint8 expressions
        if nb == 8:
            bs = [f"lb_int64(hi / {d})" for d in (16777216, 65536, 256, 1)] + \
                 [f"lb_int64(lo / {d})" for d in (16777216, 65536, 256, 1)]
        elif nb == 4:
            bs = [f"lb_int64(lo / {d})" for d in (16777216, 65536, 256, 1)]
        elif nb == 2:
            bs = [f"lb_int64(lo / {d})" for d in (256, 1)]
        else:
            bs = ["lb_int64(lo)"]
        bs = [x.replace(" / 1)", ")") for x in bs]
        if t == "uint8":
            conv = "lb_int64(lo)"
        elif t == "int8":
            conv = ("case neg of { true -> case lo == 128 of { true -> tab_s8_int8(lb_int64(lo)); "
                    "false -> 0 - tab_s8_int8(lb_int64(lo)) }; false -> tab_s8_int8(lb_int64(lo)) }")
        else:
            tab = f"tab_u8_{t}"
            pos = f"{tab}({bs[0]})"
            neg = f"(0 - {tab}({bs[0]}))"
            for x in bs[1:]:
                pos = f"({pos}) * 256 + {tab}({x})"
                neg = f"({neg}) * 256 - {tab}({x})"
            conv = f"case neg of {{ true -> {neg}; false -> {pos} }}" if signed else pos
        A(f"fn conv_{t}(neg: boolean, hi: int64, lo: int64) -> {t} {{ {conv} }}")
        A(f"fn fin_{t}(h: {IH}) -> {{ v: {t}, pos: int64 }} {{")
        A("    case h.pos < 0 of {")
        A("        true -> { v: 0, pos: h.pos };")
        A(f"        false -> case fits_{t}(h.neg, h.hi, h.lo) of {{")
        A("            false -> { v: 0, pos: 0 - 8 };")
        A(f"            true -> {{ v: conv_{t}(h.neg, h.hi, h.lo), pos: h.pos }}")
        A("        }")
        A("    }")
        A("}")
        A(f"fn dec_{t}({BUF}, len: int64, pos: int64) -> {{ v: {t}, pos: int64 }} {{ fin_{t}(bees_wire@int_hdr(rg, b, len, pos)) }}")
        A(f"fn dec_byte_{t}({BUF}, len: int64, pos: int64) -> {{ v: {t}, pos: int64 }} {{ fin_{t}(byte_hdr(rg, b, len, pos)) }}")
        # ---- encode
        if signed:
            A(f"fn neg_{t}(v: {t}) -> boolean {{ v < 0 }}")
            A(f"fn w_{t}(v: {t}) -> {t} {{ case v < 0 of {{ true -> 0 - (v + 1); false -> v }} }}")
        else:
            A(f"fn neg_{t}(v: {t}) -> boolean {{ false }}")
            A(f"fn w_{t}(v: {t}) -> {t} {{ v }}")
        lbf = {"int8": "lb_int8", "uint8": None}.get(t, f"lb_{t}")

        def byte_of(div):
            x = "w" if div == 1 else f"w / {div}"
            return f"tab_u8_int64({x})" if lbf is None else f"tab_u8_int64({lbf}({x}))"
        if nb == 8:
            lo = " + ".join(f"{byte_of(d)} * {m}" for d, m in ((1, 1), (256, 256), (65536, 65536), (16777216, 16777216)))
            hi = " + ".join(f"{byte_of(d)} * {m}" for d, m in ((4294967296, 1), (1099511627776, 256),
                                                              (281474976710656, 65536), (72057594037927936, 16777216)))
        else:
            ds = [(256 ** k, 256 ** k) for k in range(nb)]
            lo = " + ".join(f"{byte_of(d)} * {m}" if m != 1 else byte_of(d) for d, m in ds)
            hi = "0"
        lo = re.sub(r" \* 1(?!\d)", "", lo)
        A(f"fn lo_{t}(w: {t}) -> int64 {{ {lo} }}")
        A(f"fn hi_{t}(w: {t}) -> int64 {{ {hi} }}")
        A(f"fn enc_{t}({BUF}, pos: int64, v: {t}) -> int64 {{")
        A(f"    bees_wire@emit_int(rg, b, pos, neg_{t}(v), hi_{t}(w_{t}(v)), lo_{t}(w_{t}(v)))")
        A("}")
        # ---- STRING_EXT helpers
        if t == "uint8":
            pb = "v"
            isb = "true"
        else:
            pb = f"{lbf}(v)"
            isb = ("v >= 0" if t == "int8" else "v >= 0 and v <= 255") if signed else "v <= 255"
        A(f"fn put_byte_{t}({BUF}, pos: int64, v: {t}) -> int64 {{ bees_wire@put_u8(rg, b, pos, {pb}) }}")
        A(f"fn is_byte_{t}(v: {t}) -> boolean {{ {isb} }}")
        A("")
    text = L + [f"export {e};" for e in ex] + [""] + body
    with open(os.path.join(out_dir, "bees_wire_ints.silica"), "w") as out:
        out.write("\n".join(text))


# ---------------------------------------------------------------- per-message codecs

class Gen:
    def __init__(self, msgs):
        self.msgs = msgs
        self.names = {}      # canonical text -> helper index (composites only)
        self.order = []      # (index, type), dependencies first
        for _, ty in msgs:
            self.reg(ty)

    def reg(self, ty):
        if ty[0] == "prim":
            return None
        key = canon(ty)
        if key in self.names:
            return self.names[key]
        parts = ty[1] if ty[0] == "tuple" else ([t for _, t in ty[1]] if ty[0] == "record" else [ty[1]])
        for t in parts:
            self.reg(t)
        idx = len(self.names)
        self.names[key] = idx
        self.order.append((idx, ty))
        return idx

    @staticmethod
    def core(prim):
        """(module, name) of the primitive's reader and writer."""
        if prim in INT_TYPES:
            return "bees_wire_ints", prim
        return "bees_wire", PRIM_CORE[prim]

    def enc_call(self, ty, p, v, depth):
        if ty[0] == "prim":
            m, n = self.core(ty[1])
            return f"{m}@enc_{n}(rg, b, {p}, {v})"
        return f"enc_t{self.names[canon(ty)]}(rg, b, {p}, {v}, {depth})"

    def dec_call(self, ty, p, depth):
        if ty[0] == "prim":
            m, n = self.core(ty[1])
            return f"{m}@dec_{n}(rg, b, len, {p})"
        return f"dec_t{self.names[canon(ty)]}(rg, b, len, {p}, {depth})"

    def helper(self, lines, idx, ty):
        B = "buf(L, normal, uint8, 4096)"
        st = silica(ty)
        kind = ty[0]
        if kind == "tuple":
            self.tuple_helper(lines, idx, ty, st, B)
        elif kind == "record":
            self.record_helper(lines, idx, ty, st, B)
        else:
            self.list_helper(lines, idx, ty, st, B)

    # ---- tuples: SMALL_TUPLE_EXT / LARGE_TUPLE_EXT, components in order
    def tuple_helper(self, lines, idx, ty, st, B):
        n = len(ty[1])
        e = f"bees_wire@put_tuple_hdr(rg, b, bees_wire@enter(pos, depth), {n})"
        for i, t in enumerate(ty[1]):
            e = self.enc_call(t, e, f"x{i}", "depth + 1")
        pat = ", ".join(f"x{i}" for i in range(n))
        lines.append(f"fn enc_t{idx}(rg: region(L, normal), b: {B}, pos: int64, v: {st}, depth: int64) -> int64 {{")
        lines += ["    sequence", f"        ({pat}): {st} <- v;", f"        r: int64 <- {e}", "    produces pure r end", "}", ""]
        lines.append(f"fn dec_t{idx}(rg: region(L, normal), b: {B}, len: int64, pos: int64, depth: int64) -> {{ v: {st}, pos: int64 }} {{")
        lines.append("    sequence")
        lines.append(f"        p0: int64 <- bees_wire@tuple_hdr(rg, b, len, bees_wire@enter(pos, depth), {n});")
        prev = "p0"
        names = []
        for i, t in enumerate(ty[1]):
            lines.append(f"        f{i}: {{ v: {silica(t)}, pos: int64 }} <- {self.dec_call(t, prev, 'depth + 1')};")
            prev = f"f{i}.pos"
            names.append(f"f{i}.v")
        lines.append(f"        out: {{ v: {st}, pos: int64 }} <- {{ v: ({', '.join(names)}), pos: {prev} }}")
        lines += ["    produces pure out end", "}", ""]

    # ---- records: MAP_EXT with atom keys; written in name order, read in any order
    def record_helper(self, lines, idx, ty, st, B):
        fields = ty[1]
        k = len(fields)
        order = sorted(fields, key=lambda ft: ft[0].encode())
        e = f"bees_wire@put_map_hdr(rg, b, bees_wire@enter(pos, depth), {k})"
        for f, t in order:
            e = f"bees_wire@put_atom_text(rg, b, {e}, \"{f}\")"
            e = self.enc_call(t, e, f"v.{f}", "depth + 1")
        lines.append(f"fn enc_t{idx}(rg: region(L, normal), b: {B}, pos: int64, v: {st}, depth: int64) -> int64 {{")
        lines += ["    " + e, "}", ""]
        # the offsets of the values, found by one pass over the pairs (a value is skipped, not decoded)
        R = "{ " + ", ".join(f"p{i}: int64" for i in range(k)) + ", fin: int64 }"
        ps = [f"p{i}" for i in range(k)]
        lines.append(f"fn key_index_t{idx}(s: string) -> int64 {{")
        lines.append("    case s of {")
        for i, (f, _) in enumerate(fields):
            lines.append(f"        \"{f}\" -> {i};")
        lines += ["        _: string -> -1", "    }", "}", ""]

        def rec(**ov):
            return "{ " + ", ".join(f"{p}: {ov.get(p, 'a.' + p)}" for p in ps) + f", fin: {ov.get('fin', 'a.fin')} }}"
        lines.append(f"fn slot_t{idx}(a: {R}, i: int64) -> int64 {{")
        lines.append("    case i of {")
        for i in range(k - 1):
            lines.append(f"        {i} -> a.p{i};")
        lines += [f"        _: int64 -> a.p{k - 1}", "    }", "}", ""]
        lines.append(f"fn with_t{idx}(a: {R}, i: int64, v: int64) -> {R} {{")
        lines.append("    case i of {")
        for i in range(k - 1):
            lines.append(f"        {i} -> {rec(**{f'p{i}': 'v'})};")
        lines += [f"        _: int64 -> {rec(**{f'p{k - 1}': 'v'})}", "    }", "}", ""]
        sig = f"rg: region(L, normal), b: {B}, len: int64, left: int64, dv: int64, a: {R}"
        lines.append(f"fn scan_t{idx}({sig}, pos: int64) -> {R} {{")
        lines += ["    case pos < 0 or left <= 0 of {",
                  f"        true -> {rec(fin='pos')};",
                  f"        false -> scan_key_t{idx}(rg, b, len, left, dv, a, bees_wire@dec_atom_text(rg, b, len, pos))",
                  "    }", "}", ""]
        lines.append(f"fn scan_key_t{idx}({sig}, k: {{ v: string, pos: int64 }}) -> {R} {{")
        lines += ["    case k.pos < 0 of {",
                  f"        true -> {rec(fin='k.pos')};",
                  f"        false -> scan_set_t{idx}(rg, b, len, left, dv, a, k.pos, key_index_t{idx}(k.v))",
                  "    }", "}", ""]
        lines.append(f"fn scan_set_t{idx}({sig}, vpos: int64, i: int64) -> {R} {{")
        lines += ["    case i < 0 of {",
                  f"        true -> {rec(fin='(0 - 14)')};",
                  f"        false -> case slot_t{idx}(a, i) >= 0 of {{",
                  f"            true -> {rec(fin='(0 - 13)')};",
                  f"            false -> scan_next_t{idx}(rg, b, len, left, dv, with_t{idx}(a, i, vpos), bees_wire@skip(rg, b, len, vpos, dv))",
                  "        }", "    }", "}", ""]
        lines.append(f"fn scan_next_t{idx}({sig}, vend: int64) -> {R} {{")
        lines += ["    case vend < 0 of {",
                  f"        true -> {rec(fin='vend')};",
                  f"        false -> scan_t{idx}(rg, b, len, left - 1, dv, a, vend)",
                  "    }", "}", ""]
        # decode: header, scan, then each value at its offset, in declared order
        lines.append(f"fn dec_t{idx}(rg: region(L, normal), b: {B}, len: int64, pos: int64, depth: int64) -> {{ v: {st}, pos: int64 }} {{")
        lines.append("    sequence")
        lines.append(f"        m: {{ v: int64, pos: int64 }} <- bees_wire@dec_map_hdr(rg, b, len, bees_wire@enter(pos, depth), {k});")
        init = "{ " + ", ".join(f"p{i}: -1" for i in range(k)) + ", fin: 0 }"
        lines.append(f"        a: {R} <- scan_t{idx}(rg, b, len, m.v, depth + 1, {init}, m.pos);")
        miss = " or ".join(f"a.p{i} < 0" for i in range(k))
        lines.append(f"        chk: int64 <- case a.fin < 0 of {{ true -> a.fin; false -> case {miss} of {{ true -> 0 - 12; false -> a.fin }} }};")
        names = []
        fails = []
        for i, (f, t) in enumerate(fields):
            lines.append(f"        q{i}: int64 <- case chk < 0 of {{ true -> chk; false -> a.p{i} }};")
            lines.append(f"        f{i}: {{ v: {silica(t)}, pos: int64 }} <- {self.dec_call(t, f'q{i}', 'depth + 1')};")
            names.append(f"f{i}.v")
            fails.append(f"f{i}.pos")
        fe = "chk"
        for fp in reversed(fails):
            fe = f"bees_bound_{idx}({fp}, {fe})"
        val = "{ " + ", ".join(f"{f}: {n}" for (f, _), n in zip(fields, names)) + " }"
        lines.append(f"        out: {{ v: {st}, pos: int64 }} <- {{ v: {val}, pos: {fe} }}")
        lines += ["    produces pure out end", "}", ""]
        lines.append(f"fn bees_bound_{idx}(first: int64, rest: int64) -> int64 {{ case first < 0 of {{ true -> first; false -> rest }} }}")
        lines.append("")

    # ---- lists: LIST_EXT with a NIL_EXT tail; the empty list is NIL_EXT; byte lists are STRING_EXT
    def list_helper(self, lines, idx, ty, st, B):
        et = ty[1]
        es = silica(et)
        bytecap = et[0] == "prim" and et[1] in BYTE_CAPABLE
        if bytecap:
            mod, nm = self.core(et[1]) if et[1] != "char" else ("bees_wire", "char")
        lines += [f"fn enc_items_{idx}(rg: region(L, normal), b: {B}, pos: int64, v: {st}, i: int64, n: int64, depth: int64) -> int64 {{",
                  "    case pos < 0 or i >= n of {",
                  "        true -> pos;",
                  "        false -> {",
                  "            sequence proc[mem(normal)]",
                  f"                e: {es} <- list_at[{es}, mem(normal)](v, i);",
                  f"                r: int64 <- enc_items_{idx}(rg, b, {self.enc_call(et, 'pos', 'e', 'depth')}, v, i + 1, n, depth)",
                  "            produces pure r end",
                  "        }",
                  "    }", "}", ""]
        if bytecap:
            isb = "true" if et[1] == "char" else f"bees_wire_ints@is_byte_{et[1]}(e)"
            putb = f"bees_wire@put_byte_char(rg, b, pos, e)" if et[1] == "char" else f"bees_wire_ints@put_byte_{et[1]}(rg, b, pos, e)"
            lines += [f"fn all_bytes_{idx}(v: {st}, i: int64, n: int64) -> boolean {{",
                      "    case i >= n of {",
                      "        true -> true;",
                      "        false -> {",
                      "            sequence proc[mem(normal)]",
                      f"                e: {es} <- list_at[{es}, mem(normal)](v, i);",
                      f"                r: boolean <- case {isb} of {{ true -> all_bytes_{idx}(v, i + 1, n); false -> false }}",
                      "            produces pure r end",
                      "        }",
                      "    }", "}", ""]
            lines += [f"fn enc_bytes_{idx}(rg: region(L, normal), b: {B}, pos: int64, v: {st}, i: int64, n: int64) -> int64 {{",
                      "    case pos < 0 or i >= n of {",
                      "        true -> pos;",
                      "        false -> {",
                      "            sequence proc[mem(normal)]",
                      f"                e: {es} <- list_at[{es}, mem(normal)](v, i);",
                      f"                r: int64 <- enc_bytes_{idx}(rg, b, {putb}, v, i + 1, n)",
                      "            produces pure r end",
                      "        }",
                      "    }", "}", ""]
        lines += [f"fn enc_t{idx}(rg: region(L, normal), b: {B}, pos: int64, v: {st}, depth: int64) -> int64 {{",
                  "    sequence proc[mem(normal)]",
                  f"        n: int64 <- length[{es}, mem(normal)](v);",
                  "        p: int64 <- bees_wire@enter(pos, depth);"]
        gen_items = (f"bees_wire@put_nil(rg, b, enc_items_{idx}(rg, b, bees_wire@put_list_hdr(rg, b, p, n), v, 0, n, depth + 1))")
        if bytecap:
            body = ("case n == 0 of {\n"
                    "            true -> bees_wire@put_nil(rg, b, p);\n"
                    f"            false -> case all_bytes_{idx}(v, 0, n) of {{\n"
                    f"                true -> case n > 256 of {{ true -> bees_wire@fail(p, 7); false -> enc_bytes_{idx}(rg, b, bees_wire@put_string_hdr(rg, b, p, n), v, 0, n) }};\n"
                    f"                false -> {gen_items}\n"
                    "            }\n"
                    "        }")
        else:
            body = (f"case n == 0 of {{ true -> bees_wire@put_nil(rg, b, p); false -> {gen_items} }}")
        lines += [f"        r: int64 <- {body}", "    produces pure r end", "}", ""]
        ms = min_size(et)
        lines += [f"fn dec_items_{idx}(rg: region(L, normal), b: {B}, len: int64, pos: int64, n: int64, depth: int64, bsl: boolean) -> {{ v: {st}, pos: int64 }} {{",
                  "    sequence proc[mem(normal)]",
                  f"        nil: {st} <- empty[{es}, mem(normal)]();",
                  f"        out: {{ v: {st}, pos: int64 }} <- case pos < 0 or n == 0 of {{",
                  "            true -> { v: nil, pos: pos };",
                  "            false -> {",
                  "                sequence proc[mem(normal)]"]
        if bytecap:
            bcall = (f"bees_wire@dec_byte_char(rg, b, len, pos)" if et[1] == "char"
                     else f"bees_wire_ints@dec_byte_{et[1]}(rg, b, len, pos)")
            lines.append(f"                    e: {{ v: {es}, pos: int64 }} <- case bsl of {{ true -> {bcall}; false -> {self.dec_call(et, 'pos', 'depth')} }};")
        else:
            lines.append(f"                    e: {{ v: {es}, pos: int64 }} <- {self.dec_call(et, 'pos', 'depth')};")
        lines += [f"                    rest: {{ v: {st}, pos: int64 }} <- dec_items_{idx}(rg, b, len, e.pos, n - 1, depth, bsl);",
                  # the element is bound first: a float64 passed as a field access straight into prepend is
                  # stored as zero (silica-defects SD-26)
                  f"                    x: {es} <- e.v;",
                  f"                    cell: {st} <- prepend[{es}, mem(normal)](x, rest.v);",
                  f"                    r: {{ v: {st}, pos: int64 }} <- case rest.pos < 0 of {{ true -> {{ v: nil, pos: rest.pos }}; false -> {{ v: cell, pos: rest.pos }} }}",
                  "                produces pure r end",
                  "            }",
                  "        }",
                  "    produces pure out end", "}", ""]
        allow = "true" if bytecap else "false"
        lines += [f"fn dec_t{idx}(rg: region(L, normal), b: {B}, len: int64, pos: int64, depth: int64) -> {{ v: {st}, pos: int64 }} {{",
                  "    sequence",
                  "        p0: int64 <- bees_wire@enter(pos, depth);",
                  f"        h: {{ n: int64, k: int64, pos: int64 }} <- bees_wire@list_hdr(rg, b, len, p0, {ms}, {allow});",
                  f"        items: {{ v: {st}, pos: int64 }} <- dec_items_{idx}(rg, b, len, h.pos, h.n, depth + 1, h.k == 2);",
                  "        pe: int64 <- case h.k == 1 of { true -> bees_wire@expect_nil(rg, b, len, items.pos); false -> items.pos };",
                  f"        out: {{ v: {st}, pos: int64 }} <- {{ v: items.v, pos: pe }}",
                  "    produces pure out end", "}", ""]


def gen_msgs(out_dir, msgs):
    g = Gen(msgs)
    B = "buf(L, normal, uint8, 4096)"
    lines = ["// Generated by tools/bees_config.py (wire). Do not edit. The message codecs of this program's schema (typed ETF).",
             "// A message is found by its target NAME (index_of); decode results are { code, v }: code 0 is accepted, any",
             "// other code is a rejection reason (bees_wire@reason_atom). Encoders return the frame length in bytes, or the",
             "// negated reason.",
             "module bees_wire_msgs;", "use bees_atoms;", "use bees_wire;", "use bees_wire_ints;", ""]
    ex = ["msg_count/0", "index_of/1", "validate/4", "validate_named/4"]
    for name, _ in msgs:
        ex += [f"enc_{name}/3", f"dec_{name}/3", f"msg_index_{name}/0"]
    lines += [f"export {e};" for e in ex] + [""]
    lines += [f"fn msg_count() -> int64 {{ {len(msgs)} }}", ""]
    for i, (name, _) in enumerate(msgs):
        lines.append(f"fn msg_index_{name}() -> int64 {{ {i} }}")
    lines.append("")
    # the message type of a target name: -1 when the name is not a message
    chunk = 64
    chunks = [msgs[i:i + chunk] for i in range(0, len(msgs), chunk)] or [[]]
    for c, ch in enumerate(chunks):
        e = "-1"
        for j in reversed(range(len(ch))):
            e = f"case name == bees_atoms@a_{ch[j][0]}() of {{ true -> {c * chunk + j}; false -> {e} }}"
        lines += [f"fn index_of_{c}(name: atom) -> int64 {{ {e} }}", ""]
    lines.append("fn first_hit(a: int64, b: int64) -> int64 { case a < 0 of { true -> b; false -> a } }")
    e = f"index_of_{len(chunks) - 1}(name)"
    for c in reversed(range(len(chunks) - 1)):
        e = f"first_hit(index_of_{c}(name), {e})"
    lines += [f"fn index_of(name: atom) -> int64 {{ {e} }}", ""]
    for idx, ty in g.order:
        g.helper(lines, idx, ty)
    for i, (name, ty) in enumerate(msgs):
        st = silica(ty)
        lines += [f"fn enc_{name}(rg: region(L, normal), b: {B}, msg: {st}) -> int64 {{",
                  f"    bees_wire@finish(rg, b, {g.enc_call(ty, 'bees_wire@put_hdr(rg, b)', 'msg', '0')})",
                  "}", ""]
        lines += [f"fn dec_{name}(rg: region(L, normal), b: {B}, len: int64) -> {{ code: int64, v: {st} }} {{",
                  "    sequence",
                  "        p0: int64 <- bees_wire@hdr(rg, b, len);",
                  f"        f: {{ v: {st}, pos: int64 }} <- {g.dec_call(ty, 'p0', '0')};",
                  "        p1: int64 <- bees_wire@close(f.pos, len);",
                  f"        out: {{ code: int64, v: {st} }} <- {{ code: bees_wire@code_of(p1), v: f.v }}",
                  "    produces pure out end", "}", ""]
    emit_switch(lines, "validate_slot", [("rg", "region(L, normal)"), ("b", B), ("len", "int64"), ("idx", "int64")], "idx", "int64",
                [(i, f"dec_{n}(rg, b, len).code") for i, (n, _) in enumerate(msgs)], "bees_wire@reason_unknown_atom()")
    lines += [f"fn validate(rg: region(L, normal), b: {B}, len: int64, idx: int64) -> int64 {{",
              "    case idx < 0 of {",
              "        true -> bees_wire@reason_unknown_atom();",
              "        false -> validate_slot(rg, b, len, idx)",
              "    }", "}", ""]
    lines += [f"fn validate_named(rg: region(L, normal), b: {B}, len: int64, name: atom) -> int64 {{",
              "    validate(rg, b, len, index_of(name))", "}", ""]
    with open(os.path.join(out_dir, "bees_wire_msgs.silica"), "w") as out:
        out.write("\n".join(lines))


def generate_wire(out_dir, paths):
    """paths: the .wire manifests. Writes bees_wire_tables.silica, bees_wire_ints.silica and bees_wire_msgs.silica."""
    msgs = collect(paths)
    os.makedirs(out_dir, exist_ok=True)
    gen_tables(out_dir)
    gen_ints(out_dir)
    gen_msgs(out_dir, msgs)
    return msgs


def message_names(paths):
    """The message names of the manifests (each is also an atom, the target name; bees_config adds them to
    bees_atoms)."""
    return [n for n, _ in collect(paths, warn=False)]
