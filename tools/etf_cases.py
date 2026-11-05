#!/usr/bin/env python3
"""The ETF test cases of milestone M1b, as data: one registry from which

  - the Erlang oracle (`erl`, `term_to_binary/1`) produces the golden vectors in tools/etf_oracle/*.vectors,
  - the typed trial leaves (trials/m1_wire_types*) get their main.silica, .wire and .atoms,
  - tools/test_bees_wire_gen.py compares the trials' recorded output with the oracle byte for byte.

    python3 tools/etf_cases.py vectors     rewrite tools/etf_oracle/*.vectors from the installed `erl`
    python3 tools/etf_cases.py trials      rewrite the generated trial sources (no Silica compile is run)
    python3 tools/etf_cases.py check       compare the checked-in vectors with a live `erl` run (exit 1 on a difference)

A typed leaf lists messages (name, Silica type text) and entries:
  ('enc', msg, value)                       encode `value`; the bytes must equal the oracle's; decoding them and
                                            re-encoding must give the same bytes
  ('dec', msg, source, expect, ref)         decode another encoding: source is ('raw', [bytes]) or
                                            ('term', erlang_expr, erlang_options); expect is 'ok' (it must decode, and
                                            re-encode to the canonical bytes of the value `ref`, which must also be an
                                            'enc' entry) or a rejection reason (the language's atom)
A value is a Python int, float, bool, str (an atom for an `atom` field, text for `string`, one character for `char`),
tuple, dict (record) or list; `Rep(s, n)` is the text s repeated n times.
"""
import math
import os
import re
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import bees_wire_gen as W  # noqa: E402

ORACLE_DIR = os.path.join(HERE, "etf_oracle")
TYPED_VECTORS = os.path.join(ORACLE_DIR, "typed.vectors")


class Rep:
    def __init__(self, s, n):
        self.s, self.n = s, n

    def text(self):
        return self.s * self.n


class Const(list):
    """A list of n copies of v (built by a recursive Silica helper, so a long list is short source)."""

    def __init__(self, v, n):
        super().__init__([v] * n)
        self.v, self.n = v, n


NEG0 = -0.0


def f32(x):
    return struct.unpack(">f", struct.pack(">f", x))[0]


# ------------------------------------------------------------------ the typed leaves

LEAVES = {}


def leaf(name, msgs, cases, atoms=()):
    LEAVES[name] = {"msgs": msgs, "cases": cases, "atoms": list(atoms)}


def e(msg, v):
    return ("enc", msg, v)


def raw(*bs):
    return ("raw", list(bs))


def d(msg, source, expect, ref=None):
    return ("dec", msg, source, expect, ref)


def int4(v):
    return raw(131, 98, *(v % 2 ** 32).to_bytes(4, "big"))


def big(v, extra_zero=0):
    mag, digits = abs(v), []
    while mag:
        digits.append(mag & 255)
        mag >>= 8
    digits = digits or [0]
    return raw(131, 110, len(digits) + extra_zero, 1 if v < 0 else 0, *digits, *([0] * extra_zero))


def term(expr, opts=""):
    return ("term", expr, opts)


# unsigned widths
leaf("m1_wire_types",
     [("t_uint8", "uint8"), ("t_uint16", "uint16"), ("t_uint32", "uint32")],
     [e("t_uint8", v) for v in (0, 1, 127, 128, 255)]
     + [e("t_uint16", v) for v in (0, 255, 256, 32767, 32768, 65535)]
     + [e("t_uint32", v) for v in (0, 255, 256, 65535, 65536, 2147483647, 2147483648, 4294967295)]
     + [d("t_uint8", int4(255), "ok", ("t_uint8", 255)),
        d("t_uint8", big(255), "ok", ("t_uint8", 255)),
        d("t_uint16", int4(256), "ok", ("t_uint16", 256)),
        d("t_uint16", big(65535), "ok", ("t_uint16", 65535)),
        d("t_uint32", big(2147483648), "ok", ("t_uint32", 2147483648)),
        d("t_uint32", big(0), "ok", ("t_uint32", 0)),
        d("t_uint32", big(4294967295, 1), "ok", ("t_uint32", 4294967295)),
        d("t_uint8", term("256"), "out_of_range"),
        d("t_uint8", term("-1"), "out_of_range"),
        d("t_uint16", term("65536"), "out_of_range"),
        d("t_uint32", term("4294967296"), "out_of_range"),
        d("t_uint32", term("-1"), "out_of_range"),
        d("t_uint8", term("1.0"), "bad_tag"),
        d("t_uint8", term("a"), "bad_tag"),
        d("t_uint8", raw(131, 111, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0), "unsupported"),
        d("t_uint8", raw(131, 110, 9, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0), "out_of_range"),
        d("t_uint8", raw(131, 110, 1, 2, 5), "bad_tag")])
leaf("m1_wire_types_u64",
     [("t_uint64", "uint64"), ("t_char", "char")],
     [e("t_uint64", v) for v in (0, 2 ** 31 - 1, 2 ** 31, 2 ** 32 - 1, 2 ** 32, 2 ** 56, 2 ** 63 - 1, 2 ** 63, 2 ** 64 - 1)]
     + [e("t_char", c) for c in ("a", "\x00", "\x7f", "~", " ", "\n")]
     + [d("t_uint64", big(2 ** 64 - 1), "ok", ("t_uint64", 2 ** 64 - 1)),
        d("t_uint64", big(2 ** 63), "ok", ("t_uint64", 2 ** 63)),
        d("t_uint64", int4(2 ** 31 - 1), "ok", ("t_uint64", 2 ** 31 - 1)),
        d("t_uint64", big(0), "ok", ("t_uint64", 0)),
        d("t_uint64", term("18446744073709551616"), "out_of_range"),
        d("t_uint64", term("-1"), "out_of_range"),
        d("t_char", term("128"), "out_of_range"),
        d("t_char", term("-1"), "out_of_range"),
        d("t_char", term("1114111"), "out_of_range"),
        d("t_char", raw(131, 98, 0, 0, 0, 97), "ok", ("t_char", "a")),
        d("t_char", raw(131, 110, 1, 0, 97), "ok", ("t_char", "a")),
        d("t_char", term("a"), "bad_tag")])
leaf("m1_wire_types_signed_a",
     [("t_int8", "int8"), ("t_int16", "int16")],
     [e("t_int8", v) for v in (-128, -1, 0, 1, 127)]
     + [e("t_int16", v) for v in (-32768, -129, -128, -1, 0, 255, 256, 32767)]
     + [d("t_int8", int4(-128), "ok", ("t_int8", -128)),
        d("t_int8", big(-128), "ok", ("t_int8", -128)),
        d("t_int8", big(127), "ok", ("t_int8", 127)),
        d("t_int8", int4(1), "ok", ("t_int8", 1)),
        d("t_int16", int4(-32768), "ok", ("t_int16", -32768)),
        d("t_int16", big(-32768), "ok", ("t_int16", -32768)),
        d("t_int16", big(256), "ok", ("t_int16", 256)),
        d("t_int8", term("128"), "out_of_range"),
        d("t_int8", term("-129"), "out_of_range"),
        d("t_int16", term("32768"), "out_of_range"),
        d("t_int16", term("-32769"), "out_of_range"),
        d("t_int16", term("1000000000000"), "out_of_range")])
leaf("m1_wire_types_signed_b",
     [("t_int32", "int32"), ("t_int64", "int64")],
     [e("t_int32", v) for v in (-2147483648, -1, 0, 255, 256, 2147483647)]
     + [e("t_int64", v) for v in (-2 ** 63, -2 ** 56, -2 ** 31 - 1, -2 ** 31, 2 ** 31 - 1, 2 ** 31, 2 ** 32, 2 ** 56, 2 ** 63 - 1)]
     + [d("t_int32", big(-2147483648), "ok", ("t_int32", -2147483648)),
        d("t_int32", big(2147483647), "ok", ("t_int32", 2147483647)),
        d("t_int64", int4(-2147483648), "ok", ("t_int64", -2 ** 31)),
        d("t_int64", big(-2 ** 63), "ok", ("t_int64", -2 ** 63)),
        d("t_int64", big(2 ** 63 - 1), "ok", ("t_int64", 2 ** 63 - 1)),
        d("t_int64", big(-2 ** 31), "ok", ("t_int64", -2 ** 31)),
        d("t_int32", term("2147483648"), "out_of_range"),
        d("t_int32", term("-2147483649"), "out_of_range"),
        d("t_int64", term("9223372036854775808"), "out_of_range"),
        d("t_int64", term("-9223372036854775809"), "out_of_range"),
        d("t_int64", term("123456789012345678901234567890"), "out_of_range")])

F64 = [0.0, NEG0, 1.0, -2.5, 0.1, 3.14159, 1e300, 1.7976931348623157e308, 5e-324, 2.2250738585072014e-308,
       -1e-310, 123456789.125, -1.7976931348623157e308]
leaf("m1_wire_types_float64", [("t_float64", "float64")],
     [e("t_float64", v) for v in F64]
     + [d("t_float64", term("1.5", "[{minor_version,0}, deterministic]"), "unsupported"),
        d("t_float64", raw(131, 70, 127, 240, 0, 0, 0, 0, 0, 0), "out_of_range"),
        d("t_float64", raw(131, 70, 127, 248, 0, 0, 0, 0, 0, 1), "out_of_range"),
        d("t_float64", raw(131, 70, 255, 240, 0, 0, 0, 0, 0, 0), "out_of_range"),
        d("t_float64", term("1"), "bad_tag"),
        d("t_float64", term("a"), "bad_tag")])
F32 = [0.0, NEG0, 1.0, -2.5, 0.1, 3.4028234663852886e38, 1.401298464324817e-45, 1.1754943508222875e-38, 8.5e-39,
       -3.4028234663852886e38, 16777216.0, 0.15625]
leaf("m1_wire_types_float32", [("t_float32", "float32")],
     [e("t_float32", f32(v)) for v in F32]
     + [d("t_float32", term("0.1"), "out_of_range"),
        d("t_float32", term("1.0e39"), "out_of_range"),
        d("t_float32", term("1.0e-46"), "out_of_range"),
        d("t_float32", term("1.1754943508222875e-38"), "ok", ("t_float32", f32(1.1754943508222875e-38))),
        d("t_float32", term("16777217.0"), "out_of_range"),
        d("t_float32", term("1.5", "[{minor_version,0}, deterministic]"), "unsupported"),
        d("t_float32", raw(131, 70, 127, 240, 0, 0, 0, 0, 0, 0), "out_of_range"),
        d("t_float32", term("2"), "bad_tag")])

leaf("m1_wire_types_text",
     [("t_boolean", "boolean"), ("t_atom", "atom"), ("t_string", "string")],
     [e("t_boolean", True), e("t_boolean", False)]
     + [e("t_atom", a) for a in ("alpha", "beta_gamma", "z", "x" * 255)]
     + [e("t_string", s) for s in ("", "a", "hello world", "tab\tnl\n", Rep("k", 1023), Rep("k", 1024), "\x00\x01\x7f")]
     + [d("t_boolean", raw(131, 118, 0, 4, 116, 114, 117, 101), "ok", ("t_boolean", True)),
        d("t_boolean", raw(131, 100, 0, 5, 102, 97, 108, 115, 101), "ok", ("t_boolean", False)),
        d("t_boolean", raw(131, 115, 4, 116, 114, 117, 101), "ok", ("t_boolean", True)),
        d("t_boolean", term("'maybe'"), "bad_variant"),
        d("t_boolean", term("1"), "bad_tag"),
        d("t_atom", raw(131, 118, 0, 5, 97, 108, 112, 104, 97), "ok", ("t_atom", "alpha")),
        d("t_atom", raw(131, 100, 0, 5, 97, 108, 112, 104, 97), "ok", ("t_atom", "alpha")),
        d("t_atom", raw(131, 115, 5, 97, 108, 112, 104, 97), "ok", ("t_atom", "alpha")),
        d("t_atom", term("nope"), "unknown_atom"),
        d("t_atom", raw(131, 119, 0), "unknown_atom"),
        d("t_atom", raw(131, 118, 1, 0), "too_long"),
        d("t_atom", raw(131, 119, 2, 195, 169), "unsupported"),
        d("t_atom", raw(131, 119, 2, 195, 40), "bad_utf8"),
        d("t_atom", raw(131, 82, 0), "unsupported"),
        d("t_string", raw(131, 109, 0, 0, 0, 2, 195, 169), "unsupported"),
        d("t_string", raw(131, 109, 0, 0, 0, 1, 255), "bad_utf8"),
        d("t_string", raw(131, 109, 0, 0, 0, 3, 237, 160, 128), "bad_utf8"),
        d("t_string", raw(131, 107, 0, 1, 104), "bad_tag"),
        d("t_string", raw(131, 109, 0, 0, 4, 1), "too_long"),
        d("t_string", term("a"), "bad_tag")],
     atoms=["alpha", "beta_gamma", "z", "x" * 255])

NESTED = ("{ id: uint32, tags: List[string], pos: (float64, float64), items: List[{ k: atom, v: int16, ok: boolean }], "
          "ch: char, big: uint64, f: float32, s: string, grid: List[List[uint8]] }")
REC = "{ a: int64, b: float64, c: boolean, d: atom }"
LST = ("t_list_i32", [1, 2, 3])
RECV = ("t_record", {"d": "alpha", "c": True, "b": -1.0, "a": -300})
# composites are split over several leaves: one compiler process cannot type-check many wide types (SD-29)
leaf("m1_wire_types_lists",
     [("t_list_i32", "List[int32]"), ("t_list_str", "List[string]"), ("t_list_f64", "List[float64]"),
      ("t_list_u8", "List[uint8]"), ("t_list_ch", "List[char]"), ("t_list_tuple", "List[(int64, string)]")],
     [e("t_list_i32", []), e("t_list_i32", [1]), e("t_list_i32", [1, 2, 3]), e("t_list_i32", [255, 256, -1]),
      e("t_list_i32", Const(7, 256)), e("t_list_i32", Const(300, 256)),
      e("t_list_str", ["a", "", "bc"]),
      e("t_list_f64", [1.5, -0.25, 3.0]),
      e("t_list_u8", []), e("t_list_u8", [0, 1, 255]),
      e("t_list_ch", ["h", "i"]),
      e("t_list_tuple", [(1, "one"), (2, "two")]),
      # other valid encodings of the same values
      d("t_list_i32", raw(131, 108, 0, 0, 0, 3, 97, 1, 97, 2, 97, 3, 106), "ok", LST),
      d("t_list_i32", raw(131, 107, 0, 3, 1, 2, 3), "ok", LST),
      d("t_list_i32", raw(131, 108, 0, 0, 0, 3, 98, 0, 0, 0, 1, 110, 1, 0, 2, 97, 3, 106), "ok", LST),
      d("t_list_u8", raw(131, 108, 0, 0, 0, 3, 97, 0, 97, 1, 97, 255, 106), "ok", ("t_list_u8", [0, 1, 255])),
      d("t_list_ch", raw(131, 108, 0, 0, 0, 2, 97, 104, 97, 105, 106), "ok", ("t_list_ch", ["h", "i"])),
      d("t_list_i32", raw(131, 106), "ok", ("t_list_i32", [])),
      # rejections
      d("t_list_i32", raw(131, 108, 0, 0, 0, 1, 97, 1, 97, 2), "bad_tag"),
      d("t_list_i32", raw(131, 107, 0, 3, 1, 2), "truncated"),
      d("t_list_i32", term("[1 | 2]"), "bad_tag"),
      d("t_list_u8", term("[256]"), "out_of_range"),
      d("t_list_u8", raw(131, 108, 0, 0, 0, 1, 98, 0, 0, 1, 0, 106), "out_of_range"),
      d("t_list_ch", raw(131, 107, 0, 1, 200), "out_of_range"),
      d("t_list_i32", raw(131, 108, 0, 0, 1, 1, 106), "too_long"),
      d("t_list_i32", raw(131, 108, 0, 0, 0, 200, 97, 1, 106), "truncated"),
      d("t_list_i32", raw(131, 107, 1, 1, 5), "too_long")])
leaf("m1_wire_types_records",
     [("t_tuple", "(int8, uint16, string, boolean)"), ("t_record", REC), ("t_nested", NESTED)],
     [e("t_tuple", (-5, 300, "hi", True)),
      e("t_record", {"a": 7, "b": 2.5, "c": False, "d": "alpha"}),
      e("t_record", RECV[1]),
      e("t_nested", {"id": 4000000000, "tags": ["x", "yy"], "pos": (1.5, -2.5),
                     "items": [{"k": "alpha", "v": -300, "ok": True}, {"k": "z", "v": 5, "ok": False}],
                     "ch": "q", "big": 2 ** 64 - 1, "f": 0.5, "s": "end", "grid": [[1, 2], [], [255]]}),
      # other valid encodings of the same values: keys in another order, other atom tags, a large tuple
      d("t_record", raw(131, 116, 0, 0, 0, 4, 119, 1, 100, 119, 5, 97, 108, 112, 104, 97, 119, 1, 99, 119, 4, 116, 114, 117, 101,
                        119, 1, 98, 70, 191, 240, 0, 0, 0, 0, 0, 0, 119, 1, 97, 98, 255, 255, 254, 212), "ok", RECV),
      d("t_record", raw(131, 116, 0, 0, 0, 4, 100, 0, 1, 100, 119, 5, 97, 108, 112, 104, 97, 115, 1, 99, 119, 4, 116, 114, 117, 101,
                        118, 0, 1, 98, 70, 191, 240, 0, 0, 0, 0, 0, 0, 119, 1, 97, 98, 255, 255, 254, 212), "ok", RECV),
      d("t_tuple", raw(131, 105, 0, 0, 0, 4, 98, 255, 255, 255, 251, 98, 0, 0, 1, 44, 109, 0, 0, 0, 2, 104, 105, 119, 4, 116, 114, 117, 101),
        "ok", ("t_tuple", (-5, 300, "hi", True))),
      # rejections
      d("t_tuple", term("{1, 2, 3}"), "missing_field"),
      d("t_tuple", term("{1, 2, 3, 4, 5}"), "unknown_field"),
      d("t_tuple", term("[1,2,3,4]"), "bad_tag"),
      d("t_record", term("#{a => 1, b => 2.5, c => true}"), "missing_field"),
      d("t_record", term("#{a => 1, b => 2.5, c => true, d => alpha, e => 1}"), "unknown_field"),
      d("t_record", raw(131, 116, 0, 0, 0, 4, 119, 1, 97, 97, 1, 119, 1, 97, 97, 2, 119, 1, 98, 70, 0, 0, 0, 0, 0, 0, 0, 0, 119, 1, 99, 119, 4, 116, 114, 117, 101),
        "duplicate_field"),
      d("t_record", raw(131, 116, 0, 0, 0, 4, 119, 1, 97, 97, 1, 119, 1, 98, 70, 0, 0, 0, 0, 0, 0, 0, 0, 119, 1, 99, 119, 4, 116, 114, 117, 101, 119, 1, 122, 97, 1),
        "unknown_field"),
      d("t_record", raw(131, 116, 0, 0, 0, 4, 97, 1, 97, 1, 97, 1, 97, 1), "bad_tag"),
      d("t_record", term("#{}"), "missing_field"),
      d("t_record", term("#{a => 1, b => 2.5, c => true, d => 'nope'}"), "unknown_atom"),
      d("t_record", term("#{a => 1, b => 2.5, c => true, d => 5}"), "bad_tag"),
      d("t_nested", term("#{id => 1}"), "missing_field")],
     atoms=["alpha", "z"])


# ================================================================== values -> Erlang and Silica text

def parse_type(text):
    p = W.Parser(W.tokenize(text, "etf_cases"), "etf_cases", "m")
    return p.parse_type("<value>")


def erl_float(x):
    if math.copysign(1.0, x) < 0 and x == 0:
        return "-0.0"
    r = repr(x)
    if "e" in r:
        m, ex = r.split("e")
        if "." not in m:
            m += ".0"
        return f"{m}e{int(ex)}"
    return r


def erl_bin(bs):
    return "<<" + ",".join(str(b) for b in bs) + ">>"


def erl_val(ty, v):
    k = ty[0]
    if k == "prim":
        n = ty[1]
        if n in W.INT_TYPES:
            return str(v)
        if n in ("float32", "float64"):
            return erl_float(v)
        if n == "boolean":
            return "true" if v else "false"
        if n == "char":
            return str(ord(v))
        if n == "atom":
            return f"'{v}'"
        if isinstance(v, Rep):
            return f"list_to_binary(lists:duplicate({v.n}, {ord(v.s)}))" if len(v.s) == 1 else erl_bin(v.text().encode())
        return erl_bin(v.encode())
    if k == "tuple":
        return "{" + ",".join(erl_val(t, x) for t, x in zip(ty[1], v)) + "}"
    if k == "record":
        return "#{" + ",".join(f"{f} => {erl_val(t, v[f])}" for f, t in ty[1]) + "}"
    return "[" + ",".join(erl_val(ty[1], x) for x in v) + "]"


def sil_float(x, t):
    if math.copysign(1.0, x) < 0 and x == 0:
        return f"negate_{t}(0.0)"
    r = erl_float(x)
    return r


def sil_string(s):
    return "".join(W.string_literal(ord(c))[1:-1] for c in s)


class Build:
    """Silica statements that build a value of a type, and the expression that names it."""

    def __init__(self, atoms, prefix=""):
        self.steps, self.n, self.atoms, self.helpers, self.prefix = [], 0, atoms, [], prefix

    def fresh(self, base):
        self.n += 1
        return f"{base}{self.n}"

    def build(self, ty, v):
        k = ty[0]
        if k == "prim":
            n = ty[1]
            if n in W.INT_TYPES:
                return str(v)
            if n in ("float32", "float64"):
                return sil_float(v, n)
            if n == "boolean":
                return "true" if v else "false"
            if n == "char":
                return W.char_literal(ord(v))
            if n == "atom":
                self.atoms.add(v)
                return f"bees_atoms@a_{v}()"
            if isinstance(v, Rep):
                return f'rep("{sil_string(v.s)}", {v.n})'
            return f'"{sil_string(v)}"'
        if k == "tuple":
            return "(" + ", ".join(self.build(t, x) for t, x in zip(ty[1], v)) + ")"
        if k == "record":
            return "{ " + ", ".join(f"{f}: {self.build(t, v[f])}" for f, t in ty[1]) + " }"
        et = ty[1]
        es, st = W.silica(et), W.silica(ty)
        if isinstance(v, Const):
            name = self.prefix + self.fresh("constl")
            sub = Build(self.atoms, self.prefix)
            sub.n = 1000 + self.n
            ex = sub.build(et, v.v)
            self.helpers += [f"fn {name}(n: int64) -> {st} {{",
                             "    case n <= 0 of {",
                             f"        true -> {{ sequence proc[mem(normal)] e: {st} <- empty[{es}, mem(normal)]() produces pure e end }};",
                             "        false -> {",
                             "            sequence proc[mem(normal)]"]
            self.helpers += ["                " + x for x in sub.steps]
            self.helpers += [f"                rest: {st} <- {name}(n - 1);",
                             f"                x: {es} <- {ex};",
                             f"                r: {st} <- prepend[{es}, mem(normal)](x, rest)",
                             "            produces pure r end",
                             "        }", "    }", "}"]
            return f"{name}({v.n})"
        prev = self.fresh("nil")
        self.steps.append(f"{prev}: {st} <- empty[{es}, mem(normal)]();")
        for x in reversed(v):
            ex = self.build(et, x)
            el = self.fresh("el")
            self.steps.append(f"{el}: {es} <- {ex};")
            cell = self.fresh("cell")
            self.steps.append(f"{cell}: {st} <- prepend[{es}, mem(normal)]({el}, {prev});")
            prev = cell
        return prev


def sil_val_fn(name, ty, v, atoms):
    b = Build(atoms, name + '_')
    ex = b.build(ty, v)
    st = W.silica(ty)
    if not b.steps:
        return b.helpers + [f"fn {name}() -> {st} {{ {ex} }}"]
    out = b.helpers + [f"fn {name}() -> {st} {{", "    sequence proc[mem(normal)]"]
    out += ["        " + s for s in b.steps]
    out += [f"        r: {st} <- {ex}", "    produces pure r end", "}"]
    return out


def words_of(bs):
    ws = []
    for i in range(0, len(bs), 8):
        chunk = bytes(bs[i:i + 8]).ljust(8, b"\0")
        ws.append(int.from_bytes(chunk, "big", signed=True))
    return ws


# ================================================================== the oracle

def entries(name):
    """-> [(global index, entry)] of a leaf, in order."""
    return list(enumerate(LEAVES[name]["cases"]))


def find_enc(lf, ref):
    msg, val = ref
    for k, c in enumerate(lf["cases"]):
        if c[0] == "enc" and c[1] == msg and c[2] == val and type(c[2]) is type(val):
            return k
    raise KeyError(f"no enc entry for {ref}")


def has_record(ty):
    if ty[0] == "record":
        return True
    if ty[0] == "tuple":
        return any(has_record(t) for t in ty[1])
    if ty[0] == "list":
        return has_record(ty[1])
    return False


def erl_program():
    """The Erlang expression that prints `<id> <hex>` for every typed entry. An 'ok' decode entry is checked against
    binary_to_term: it must be an encoding of the referenced value."""
    items = []
    for name, lf in LEAVES.items():
        tys = {m: parse_type(t) for m, t in lf["msgs"]}
        for k, c in enumerate(lf["cases"]):
            ident = f"{name}.{k}"
            if c[0] == "enc":
                # erl writes a map's keys in atom-table order, which no other implementation can reproduce; with
                # `deterministic` they are in term order (atoms by name), the canonical order BEES writes
                opt = ", [deterministic]" if has_record(tys[c[1]]) else ""
                items.append(f'{{"{ident}", fun() -> term_to_binary({erl_val(tys[c[1]], c[2])}{opt}) end}}')
            else:
                _, msg, src, expect, ref = c
                if src[0] == "term":
                    items.append(f'{{"{ident}", fun() -> term_to_binary({src[1]}, {src[2] or "[deterministic]"}) end}}')
                else:
                    body = erl_bin(src[1])
                    if expect == "ok":
                        rk = find_enc(lf, ref)
                        rv = erl_val(tys[ref[0]], ref[1])
                        items.append(f'{{"{ident}", fun() -> B = {body}, case binary_to_term(B) =:= {rv} of true -> B; false -> error({{not_the_value, "{ident}"}}) end end}}')
                    else:
                        items.append(f'{{"{ident}", fun() -> {body} end}}')
    return ("Hex = fun(B) -> lists:flatten([io_lib:format(\"~2.16.0b\", [X]) || <<X>> <= B]) end, "
            "Cases = [" + ",\n".join(items) + "], "
            "io:format(\"# OTP ~s erts-~s: term_to_binary/1 (minor version 1; [deterministic] when a map is involved or the entry is a hostile frame built from a term), one `<id> <hex>` per entry~n\", "
            "[erlang:system_info(otp_release), erlang:system_info(version)]), "
            "lists:foreach(fun({Id, F}) -> io:format(\"~s ~s~n\", [Id, Hex(F())]) end, Cases), halt().")


def run_erl(program):
    r = subprocess.run(["erl", "-noshell", "-eval", program], capture_output=True, text=True)
    if r.returncode != 0 or "error" in r.stderr.lower() or r.stderr.strip():
        raise SystemExit("erl failed:\n" + r.stdout + r.stderr)
    return r.stdout


def read_vectors(path):
    """-> (header line, {id: hex})"""
    header, vec = "", {}
    with open(path) as fh:
        for line in fh:
            line = line.rstrip("\n")
            if line.startswith("#"):
                header = header or line
            elif line:
                ident, hx = line.split(" ")
                vec[ident] = hx
    return header, vec


def cmd_vectors():
    out = run_erl(erl_program())
    os.makedirs(ORACLE_DIR, exist_ok=True)
    with open(TYPED_VECTORS, "w") as fh:
        fh.write(out)
    print(f"wrote {TYPED_VECTORS} ({len(out.splitlines()) - 1} vectors; {out.splitlines()[0]})")


def cmd_check():
    out = run_erl(erl_program())
    _, vec = read_vectors(TYPED_VECTORS)
    live = {}
    for line in out.splitlines():
        if not line.startswith("#"):
            a, b = line.split(" ")
            live[a] = b
    if live != vec:
        diff = sorted(k for k in set(live) | set(vec) if live.get(k) != vec.get(k))
        print("vectors differ from a live erl run:", diff[:10])
        return 1
    print(f"{len(vec)} typed vectors match the installed erl")
    return 0


# ================================================================== the trial sources

CHUNK = 24      # entries per trial leaf (one compiler process cannot take many: silica-defects SD-29)

HELPERS = '''use bees_atoms;
use bees_wire;
use bees_wire_msgs;

fn rep(s: string, n: int64) -> string {
    case n <= 0 of {
        true -> "";
        false -> case n == 1 of { true -> s; false -> concat(rep(s, n / 2), rep(s, n - n / 2)) }
    }
}
fn hexd(n: int64) -> string {
    case n of {
        0 -> "0"; 1 -> "1"; 2 -> "2"; 3 -> "3"; 4 -> "4"; 5 -> "5"; 6 -> "6"; 7 -> "7"; 8 -> "8"; 9 -> "9";
        10 -> "a"; 11 -> "b"; 12 -> "c"; 13 -> "d"; 14 -> "e"; _: int64 -> "f"
    }
}
fn show_hex(rg: region(L, normal), b: buf(L, normal, uint8, 4096), i: int64, n: int64) -> int64 {
    case i >= n of {
        true -> 0;
        false -> {
            sequence proc[device_io]
                print_string(hexd(bees_wire@rb_i(rg, b, i) / 16));
                print_string(hexd(bees_wire@rb_i(rg, b, i) % 16));
                r: int64 <- show_hex(rg, b, i + 1, n)
            produces pure r end
        }
    }
}
fn same_bytes(rg: region(L, normal), a: buf(L, normal, uint8, 4096), c: buf(L, normal, uint8, 4096), i: int64, n: int64) -> boolean {
    case i >= n of {
        true -> true;
        false -> case bees_wire@rb_i(rg, a, i) == bees_wire@rb_i(rg, c, i) of { true -> same_bytes(rg, a, c, i + 1, n); false -> false }
    }
}
// `<id> n=<frame bytes> hex=<every byte> `
fn show(rg: region(L, normal), id: string, b: buf(L, normal, uint8, 4096), n: int64) -> int64 {
    sequence proc[device_io]
        print_string(id);
        print_string(" n=");
        _: atom <- print_int64(n);
        print_string(" hex=");
        _: int64 <- show_hex(rg, b, 0, n);
        print_string(" ")
    produces pure 0 end
}
fn verdict(code: int64, same: boolean) -> int64 {
    sequence proc[device_io]
        _: atom <- print_atom(bees_wire@reason_atom(code));
        println(case same of { true -> " rt"; false -> " DIFFERENT" })
    produces pure 0 end
}
fn rejected(id: string, n: int64) -> int64 {
    sequence proc[device_io]
        print_string(id);
        print_string(" encode rejected ");
        _: atom <- print_atom(bees_wire@reason_atom(0 - n));
        println("")
    produces pure 0 end
}
// `<id> dec <reason> <rt | DIFFERENT | ->`
fn dverdict(id: string, code: int64, same: int64) -> int64 {
    sequence proc[device_io]
        print_string(id);
        print_string(" dec ");
        _: atom <- print_atom(bees_wire@reason_atom(code));
        println(case same of { 1 -> " rt"; 0 -> " DIFFERENT"; _: int64 -> " -" })
    produces pure 0 end
}
'''


def load_fn(name, bs):
    ws = words_of(bs)
    out = [f"fn {name}(rg: region(L, normal), b: buf(L, normal, uint8, 4096)) -> int64 {{", "    sequence"]
    for i, w in enumerate(ws):
        out.append(f"        _: int64 <- bees_wire@put_word(rg, b, {i}, {w});")
    out[-1] = out[-1].rstrip(";")
    out += [f"    produces pure {len(bs)} end", "}"]
    return out


def unhex(h):
    return [int(h[i:i + 2], 16) for i in range(0, len(h), 2)]


def leaf_source(name, lf, idxs, vec, atoms):
    tys = {m: parse_type(t) for m, t in lf["msgs"]}
    L = [f"// GENERATED by tools/etf_cases.py (entries {idxs[0]}..{idxs[-1]} of {name}); do not edit. Typed ETF codec: every",
         "// `enc` entry prints `<id> n=<frame bytes> hex=<all bytes> <reason> rt|DIFFERENT` (rt: the frame decodes and re-encodes",
         "// to the same bytes); every `dec` entry prints `<id> dec <reason> rt|DIFFERENT|-`. tools/test_bees_wire_gen.py compares",
         "// the hex with the vectors the installed erl produced (tools/etf_oracle/typed.vectors).",
         HELPERS]
    runs = []
    for k in idxs:
        c = lf["cases"][k]
        ident = f"{name}.{k}"
        msg = c[1]
        st = W.silica(tys[msg])
        if c[0] == "enc":
            L += sil_val_fn(f"val_{k}", tys[msg], c[2], atoms)
            L += [f"fn e_{k}(rg: region(L, normal), b: buf(L, normal, uint8, 4096), c: buf(L, normal, uint8, 4096), a: buf(L, normal, uint8, 4096)) -> int64 {{",
                  "    sequence",
                  f"        n: int64 <- bees_wire_msgs@enc_{msg}(rg, b, val_{k}());",
                  "        r: int64 <- case n < 0 of {",
                  f"            true -> rejected(\"{ident}\", n);",
                  "            false -> {",
                  "                sequence",
                  f"                    _: int64 <- show(rg, \"{ident}\", b, n);",
                  f"                    d: {{ code: int64, v: {st} }} <- bees_wire_msgs@dec_{msg}(rg, b, n);",
                  f"                    m2: int64 <- bees_wire_msgs@enc_{msg}(rg, c, d.v);",
                  "                    same: boolean <- case d.code == 0 of { true -> m2 == n and same_bytes(rg, b, c, 0, n); false -> false };",
                  "                    _: int64 <- verdict(d.code, same)",
                  "                produces pure 0 end",
                  "            }",
                  "        }",
                  "    produces pure r end", "}"]
        else:
            _, _, src, expect, ref = c
            frame = unhex(vec[ident])
            L += load_fn(f"load_{k}", frame)
            body = [f"fn e_{k}(rg: region(L, normal), b: buf(L, normal, uint8, 4096), c: buf(L, normal, uint8, 4096), a: buf(L, normal, uint8, 4096)) -> int64 {{",
                    "    sequence",
                    f"        na: int64 <- load_{k}(rg, a);",
                    f"        d: {{ code: int64, v: {st} }} <- bees_wire_msgs@dec_{msg}(rg, a, na);"]
            if ref is not None:
                rk = find_enc(lf, ref)
                L += load_fn(f"canon_{k}", unhex(vec[f"{name}.{rk}"]))
                body += [f"        nc: int64 <- canon_{k}(rg, c);",
                         f"        m2: int64 <- bees_wire_msgs@enc_{msg}(rg, b, d.v);",
                         "        same: int64 <- case d.code == 0 and m2 == nc and same_bytes(rg, b, c, 0, nc) of { true -> 1; false -> 0 };"]
            else:
                body += ["        same: int64 <- 2;"]
            body += [f"        r: int64 <- dverdict(\"{ident}\", d.code, same)",
                     "    produces pure r end", "}"]
            L += body
        runs.append(k)
    L += ["fn run_all(rg: region(L, normal), b: buf(L, normal, uint8, 4096), c: buf(L, normal, uint8, 4096), a: buf(L, normal, uint8, 4096)) -> int64 {",
          "    sequence"]
    for k in runs:
        L.append(f"        _: int64 <- e_{k}(rg, b, c, a);")
    L[-1] = L[-1].rstrip(";")
    L += ["    produces pure 0 end", "}",
          "fn main() -> int64 {",
          "    sequence proc[device_io, mem(normal)]",
          "        L: lifetime <- fresh_lifetime();",
          "        rg: region(L, normal) <- alloc_region(normal);",
          "        b: buf(L, normal, uint8, 4096) <- alloc_buf(rg, 4096);",
          "        c: buf(L, normal, uint8, 4096) <- alloc_buf(rg, 4096);",
          "        a: buf(L, normal, uint8, 4096) <- alloc_buf(rg, 4096);",
          "        _: int64 <- run_all(rg, b, c, a);",
          f"        println(\"{name} done\")",
          "    produces pure 0 end", "}", ""]
    return "\n".join(L)


def leaf_dirs(name):
    """[(directory name, [entry indexes])]: a leaf of many entries is split over directories of CHUNK each."""
    n = len(LEAVES[name]["cases"])
    parts = -(-n // CHUNK)
    size = -(-n // parts)
    out = []
    for j, lo in enumerate(range(0, n, size)):
        out.append((name if j == 0 else f"{name}_{chr(ord('a') + j)}", list(range(lo, min(lo + size, n)))))
    return out


MAKEFILE = ("BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)\n"
            "include $(BEES_ROOT)/tools/trial.mk\n")


def cmd_trials():
    _, vec = read_vectors(TYPED_VECTORS)
    for name, lf in LEAVES.items():
        for dname, idxs in leaf_dirs(name):
            d_ = os.path.join(ROOT, "trials", dname)
            os.makedirs(os.path.join(d_, "lib"), exist_ok=True)
            for f, tgt in (("bees_wire.silica", "../../../src/inter_nodal/bees_wire.silica"),
                           ("bees_wire.atoms", "../../../src/inter_nodal/bees_wire.atoms")):
                lp = os.path.join(d_, "lib", f)
                if not os.path.islink(lp):
                    os.symlink(tgt, lp)
            with open(os.path.join(d_, "Makefile"), "w") as fh:
                fh.write(MAKEFILE)
            atoms = set(lf["atoms"])
            src = leaf_source(name, lf, idxs, vec, atoms)
            with open(os.path.join(d_, "main.silica"), "w") as fh:
                fh.write(src)
            with open(os.path.join(d_, "types.wire"), "w") as fh:
                fh.write("# GENERATED by tools/etf_cases.py: the messages of this leaf\n")
                for m, t in lf["msgs"]:
                    fh.write(f"message {m} {t}\n")
            with open(os.path.join(d_, "types.atoms"), "w") as fh:
                fh.write("# GENERATED by tools/etf_cases.py: the atoms of this leaf's values\n")
                for a in sorted(atoms):
                    fh.write(a + "\n")
            print(f"{dname}: entries {idxs[0]}..{idxs[-1]}, {src.count(chr(10))} lines")



def main(argv):
    if len(argv) == 2 and argv[1] == "vectors":
        return cmd_vectors() or 0
    if len(argv) == 2 and argv[1] == "trials":
        return cmd_trials() or 0
    if len(argv) == 2 and argv[1] == "check":
        return cmd_check()
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
