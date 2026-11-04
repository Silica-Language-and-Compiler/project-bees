#!/usr/bin/env python3
"""bees_wire_gen: the wire-codec half of tools/bees_config.py (MVP milestone M1).

Not run directly; `bees_config.py wire -o DIR MANIFEST...` and `bees_config.py generate` call it.

A `<unit>.wire` manifest is line oriented, `#` starts a comment:

    message <name> <silica type>

`<name>` is an identifier unique program-wide. Each message gets a numeric kind id (u16) in manifest
order across the manifests, files taken in the order given, starting at 0. The type is the text of
Silica's own type syntax, restricted to:

    int8 int16 int32 int64 uint8 uint16 uint32 uint64 float32 float64 boolean char atom string
    (T, T, ...)                     tuple, two or more components
    { f: T, g: T, ... }             record, one or more fields
    List[T]  or  List[T, mem(normal)]

Everything else is a build error that names the message, the field path and the type: actor_ref,
supervisor_ref, regions and references (region, ref, ref?), buf, function types, sum types (`|`),
atom literal types (tagged tuples), unit, standard data structures, any unknown name.

Generated, into OUT_DIR, deterministically and with no BEAM atom literal:

  bees_wire_tables.silica  constant lookup tables: byte <-> every integer width, and the ASCII text
                           tables (no type conversion exists in Silica, so every conversion is a lookup).
  bees_wire_msgs.silica    per message: enc_<name>, dec_<name>, kind_id_<name>; and kind_count,
                           schema_digest, kind_of, validate (the dispatcher by kind id, tiered at
                           256 arms), plus one helper pair per distinct type.
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
WIRE_VERSION = 1
MAX_KINDS = 65536

TIER = 256
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

INT_TYPES = {
    # name: (bytes, signed)
    "int8": (1, True), "int16": (2, True), "int32": (4, True), "int64": (8, True),
    "uint8": (1, False), "uint16": (2, False), "uint32": (4, False), "uint64": (8, False),
}
PRIMS = set(INT_TYPES) | {"float32", "float64", "boolean", "char", "atom", "string"}
# minimum encoded size of a primitive, in bytes (used to bound a list count by the bytes left)
PRIM_MIN = {"int8": 1, "int16": 2, "int32": 4, "int64": 8, "uint8": 1, "uint16": 2, "uint32": 4,
            "uint64": 8, "float32": 4, "float64": 8, "boolean": 1, "char": 4, "atom": 1, "string": 4}
# the name each primitive has in the core (bees_wire@enc_<n>, bees_wire@dec_<n>)
PRIM_CORE = {"int8": "i8", "int16": "i16", "int32": "i32", "int64": "i64", "uint8": "u8", "uint16": "u16",
             "uint32": "u32", "uint64": "u64", "float32": "f32", "float64": "f64", "boolean": "bool",
             "char": "char", "atom": "atom", "string": "string"}

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
    "unit": "the unit type carries no value",
    "lifetime": "lifetimes cannot cross the wire",
    "timer_ref": "timer references cannot cross the wire",
    "Map": "standard data structures are not supported on the wire yet",
    "Set": "standard data structures are not supported on the wire yet",
    "Tree": "standard data structures are not supported on the wire yet",
    "Heap": "standard data structures are not supported on the wire yet",
    "Queue": "standard data structures are not supported on the wire yet",
    "PriorityQueue": "standard data structures are not supported on the wire yet",
}

# the atoms the wire layer needs in bees_atoms (rejection reasons); see src/inter_nodal/bees_wire.atoms
REASONS = ["rejected", "truncated", "too_large", "too_deep", "too_long", "bad_text", "unknown_atom",
           "unknown_kind", "bad_float", "bad_boolean", "bad_version", "bad_frame_kind", "trailing"]
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
    kind = ty[0]
    if kind == "prim":
        return PRIM_MIN[ty[1]]
    if kind == "list":
        return 4
    parts = ty[1] if kind == "tuple" else [t for _, t in ty[1]]
    return sum(min_size(t) for t in parts)


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
        raise WireError(f"{len(msgs)} messages: a kind id is a u16 ({MAX_KINDS} at most)")
    for name, ty, where in msgs:
        if warn and depth_of(ty) > MAX_DEPTH:
            print(f"bees_config: {where}: warning: message {name} nests {depth_of(ty)} levels, above the wire "
                  f"limit of {MAX_DEPTH}; every frame of it will be rejected as too_deep", file=sys.stderr)
        # the value must fit in a frame: smallest encoding is checked, the largest is a run-time matter
        if min_size(ty) + 8 > MAX_FRAME:
            raise WireError(f"{where}: message {name}: even its smallest encoding does not fit in a "
                            f"{MAX_FRAME}-byte frame")
    return [(n, t) for n, t, _ in msgs]


# ---------------------------------------------------------------- schema digest

def schema_text(msgs):
    lines = [f"bees-wire {WIRE_VERSION}",
             f"limits frame={MAX_FRAME} depth={MAX_DEPTH} list={MAX_LIST} atom={MAX_ATOM} string={MAX_STRING}"]
    for i, (name, ty) in enumerate(msgs):
        lines.append(f"message {i} {name} {canon(ty)}")
    return "\n".join(lines) + "\n"


def fnv1a64(data):
    h = 0xCBF29CE484222325
    for byte in data:
        h ^= byte
        h = (h * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return h


def digest(msgs):
    """The schema digest: FNV-1a (64 bit) of the canonical schema text, as an unsigned 64-bit value."""
    return fnv1a64(schema_text(msgs).encode("ascii"))


def signed64(u):
    """The same 64 bits read as a two's complement int64, the form Silica holds and the generator emits."""
    return u - (1 << 64) if u >= (1 << 63) else u


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


# bytes that may appear in a string, an atom spelling or a char: tab, newline, carriage return, space..~
TEXT_BYTES = [9, 10, 13] + list(range(32, 127))


def char_literal(c):
    return {39: "'\\''", 34: "'\\\"'", 92: "'\\\\'", 10: "'\\n'", 9: "'\\t'", 13: "'\\r'", 32: "'\\x20'"}.get(c, "'" + chr(c) + "'")


def string_literal(c):
    return {34: '"\\""', 92: '"\\\\"', 10: '"\\n"', 9: '"\\t"', 13: '"\\r"'}.get(c, '"' + chr(c) + '"')


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
    # text
    exports.append("tab_is_text/1")
    L.append("fn tab_is_text(b: uint8) -> boolean {")
    L.append("    case b of {")
    for c in TEXT_BYTES:
        L.append(f"        {c} -> true;")
    L.append("        _: uint8 -> false")
    L.append("    }")
    L.append("}")
    L.append("")
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

    def enc_call(self, ty, p, v, depth):
        if ty[0] == "prim":
            return f"bees_wire@enc_{PRIM_CORE[ty[1]]}(b, {p}, {v})"
        return f"enc_t{self.names[canon(ty)]}(b, {p}, {v}, {depth})"

    def dec_call(self, ty, p, depth):
        if ty[0] == "prim":
            return f"bees_wire@dec_{PRIM_CORE[ty[1]]}(b, len, {p})"
        return f"dec_t{self.names[canon(ty)]}(b, len, {p}, {depth})"

    def helper(self, lines, idx, ty):
        B = "buf(L, normal, uint8, 4096)"
        st = silica(ty)
        kind = ty[0]
        if kind in ("tuple", "record"):
            if kind == "tuple":
                parts = [(str(i), t) for i, t in enumerate(ty[1])]
            else:
                parts = ty[1]
            # encoder: one nested expression, the position threaded through the calls
            e = "bees_wire@enter(pos, depth)"
            for i, (f, t) in enumerate(parts):
                access = f"v.{f}" if kind == "record" else f"x{i}"
                e = self.enc_call(t, e, access, "depth + 1")
            lines.append(f"fn enc_t{idx}(b: {B}, pos: int64, v: {st}, depth: int64) -> int64 {{")
            if kind == "tuple":
                pat = ", ".join(f"x{i}" for i in range(len(parts)))
                lines += ["    sequence", f"        ({pat}): {st} <- v;", f"        r: int64 <- {e}",
                          "    produces pure r end", "}", ""]
            else:
                lines += ["    " + e, "}", ""]
            # decoder
            lines.append(f"fn dec_t{idx}(b: {B}, len: int64, pos: int64, depth: int64) -> {{ v: {st}, pos: int64 }} {{")
            lines.append("    sequence")
            lines.append("        p0: int64 <- bees_wire@enter(pos, depth);")
            prev = "p0"
            names = []
            for i, (f, t) in enumerate(parts):
                lines.append(f"        f{i}: {{ v: {silica(t)}, pos: int64 }} <- {self.dec_call(t, prev, 'depth + 1')};")
                prev = f"f{i}.pos"
                names.append(f"f{i}.v")
            if kind == "tuple":
                val = "(" + ", ".join(names) + ")"
            else:
                val = "{ " + ", ".join(f"{f}: {n}" for (f, _), n in zip(parts, names)) + " }"
            lines.append(f"        out: {{ v: {st}, pos: int64 }} <- {{ v: {val}, pos: {prev} }}")
            lines += ["    produces pure out end", "}", ""]
        else:  # list
            et = ty[1]
            es = silica(et)
            lines += [f"fn enc_items_{idx}(b: {B}, pos: int64, v: {st}, i: int64, n: int64, depth: int64) -> int64 {{",
                      "    case pos < 0 or i >= n of {",
                      "        true -> pos;",
                      "        false -> {",
                      "            sequence proc[mem(normal)]",
                      f"                e: {es} <- list_at[{es}, mem(normal)](v, i);",
                      f"                r: int64 <- enc_items_{idx}(b, {self.enc_call(et, 'pos', 'e', 'depth')}, v, i + 1, n, depth)",
                      "            produces pure r end",
                      "        }",
                      "    }", "}", ""]
            lines += [f"fn enc_t{idx}(b: {B}, pos: int64, v: {st}, depth: int64) -> int64 {{",
                      "    sequence proc[mem(normal)]",
                      f"        n: int64 <- length[{es}, mem(normal)](v);",
                      "        p: int64 <- bees_wire@enc_count(b, bees_wire@enter(pos, depth), n);",
                      f"        r: int64 <- enc_items_{idx}(b, p, v, 0, n, depth + 1)",
                      "    produces pure r end", "}", ""]
            ms = min_size(et)
            lines += [f"fn dec_items_{idx}(b: {B}, len: int64, pos: int64, n: int64, depth: int64) -> {{ v: {st}, pos: int64 }} {{",
                      "    sequence proc[mem(normal)]",
                      f"        nil: {st} <- empty[{es}, mem(normal)]();",
                      f"        out: {{ v: {st}, pos: int64 }} <- case pos < 0 or n == 0 of {{",
                      "            true -> { v: nil, pos: pos };",
                      "            false -> {",
                      "                sequence proc[mem(normal)]",
                      f"                    e: {{ v: {es}, pos: int64 }} <- {self.dec_call(et, 'pos', 'depth')};",
                      f"                    rest: {{ v: {st}, pos: int64 }} <- dec_items_{idx}(b, len, e.pos, n - 1, depth);",
                      # the element is bound first: a float64 passed as a field access straight into prepend is
                      # stored as zero (silica-defects SD-26)
                      f"                    x: {es} <- e.v;",
                      f"                    cell: {st} <- prepend[{es}, mem(normal)](x, rest.v);",
                      f"                    r: {{ v: {st}, pos: int64 }} <- case rest.pos < 0 of {{ true -> {{ v: nil, pos: rest.pos }}; false -> {{ v: cell, pos: rest.pos }} }}",
                      "                produces pure r end",
                      "            }",
                      "        }",
                      "    produces pure out end", "}", ""]
            lines += [f"fn dec_t{idx}(b: {B}, len: int64, pos: int64, depth: int64) -> {{ v: {st}, pos: int64 }} {{",
                      "    sequence",
                      "        p0: int64 <- bees_wire@enter(pos, depth);",
                      f"        c: {{ v: int64, pos: int64 }} <- bees_wire@dec_count(b, len, p0, {ms});",
                      f"        out: {{ v: {st}, pos: int64 }} <- dec_items_{idx}(b, len, c.pos, c.v, depth + 1)",
                      "    produces pure out end", "}", ""]


def gen_msgs(out_dir, msgs):
    g = Gen(msgs)
    B = "buf(L, normal, uint8, 4096)"
    d = signed64(digest(msgs))
    lines = ["// Generated by tools/bees_config.py (wire). Do not edit. The message codecs of this program's schema.",
             "// Decode results are { code, v }: code 0 is accepted, any other code is a rejection reason",
             "// (bees_wire@reason_atom). Encoders return the frame length in bytes, or the negated reason.",
             "module bees_wire_msgs;", "use bees_wire;", ""]
    ex = ["kind_count/0", "schema_digest/0", "kind_of/2", "validate/2"]
    for name, _ in msgs:
        ex += [f"enc_{name}/2", f"dec_{name}/2", f"kind_id_{name}/0"]
    lines += [f"export {e};" for e in ex] + [""]
    lines += [f"fn kind_count() -> int64 {{ {len(msgs)} }}",
              "// FNV-1a (64 bit) of the canonical schema text, as the signed reading of the unsigned value.",
              f"fn schema_digest() -> int64 {{ {d} }}", ""]
    for name, _ in msgs:
        pass
    for i, (name, _) in enumerate(msgs):
        lines.append(f"fn kind_id_{name}() -> int64 {{ {i} }}")
    lines.append("")
    for idx, ty in g.order:
        g.helper(lines, idx, ty)
    for i, (name, ty) in enumerate(msgs):
        st = silica(ty)
        lines += [f"fn enc_{name}(b: {B}, msg: {st}) -> int64 {{",
                  f"    bees_wire@finish(b, {g.enc_call(ty, f'bees_wire@enc_u16(b, bees_wire@put_prefix(b, 1), {i})', 'msg', '0')})",
                  "}", ""]
        lines += [f"fn dec_{name}(b: {B}, len: int64) -> {{ code: int64, v: {st} }} {{",
                  "    sequence",
                  f"        p0: int64 <- bees_wire@open_send(b, len, {i});",
                  f"        f: {{ v: {st}, pos: int64 }} <- {g.dec_call(ty, 'p0', '0')};",
                  "        p1: int64 <- bees_wire@close(f.pos, len);",
                  f"        out: {{ code: int64, v: {st} }} <- {{ code: bees_wire@code_of(p1), v: f.v }}",
                  "    produces pure out end", "}", ""]
    lines += [f"fn kind_of(b: {B}, len: int64) -> int64 {{ bees_wire@kind_of(b, len, kind_count()) }}", ""]
    emit_switch(lines, "validate_slot", [("b", B), ("len", "int64"), ("kind", "int64")], "kind", "int64",
                [(i, f"dec_{n}(b, len).code") for i, (n, _) in enumerate(msgs)], "bees_wire@reason_unknown_kind()")
    lines += [f"fn validate(b: {B}, len: int64) -> int64 {{",
              "    case kind_of(b, len) < 0 of {",
              "        true -> 0 - kind_of(b, len);",
              "        false -> validate_slot(b, len, kind_of(b, len))",
              "    }", "}", ""]
    with open(os.path.join(out_dir, "bees_wire_msgs.silica"), "w") as out:
        out.write("\n".join(lines))


def generate_wire(out_dir, paths):
    """paths: the .wire manifests. Writes bees_wire_tables.silica and bees_wire_msgs.silica."""
    msgs = collect(paths)
    os.makedirs(out_dir, exist_ok=True)
    gen_tables(out_dir)
    gen_msgs(out_dir, msgs)
    return msgs
