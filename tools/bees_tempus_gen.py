#!/usr/bin/env python3
"""bees_tempus_gen: write the dangerous_ root unit of a program that speaks tempus/1.

    bees_tempus_gen.py edge NAME OUT_FILE [--use UNIT]... [--part PART]... ROLE_FILE...
    bees_tempus_gen.py unit IN_FILE OUT_FILE      a library unit written with the $NAME$ type names (*.silica.in)
    bees_tempus_gen.py bridge NAME OUT_FILE TRUST_ROOT [--use UNIT]... [--part PART]... ROLE_FILE...
                                                  a bridge's root unit (T6): TRUST_ROOT is the root unit
                                                  tools/bees_trust_gen.py edge wrote for NAME (carrier edge, TRUST link and
                                                  node edge); the TEMPUS link edge, the parts and the roles follow it
    bees_tempus_gen.py spec SPEC_FILE OUT_FILE    the unit bees_tempus_spec (T6): a bridge's per-type permission specs

The unit is: the `use` lines; `module NAME;`; src/shim/bees_tcp_edge.part (carrier_new); src/tempus/bees_tempus_link.part
(the TEMPUS link edge); any further parts named with --part (a file name of src/tempus, or a path from the BEES root,
as example_tempus_clients/silica/bees_tempus_client.part); then the role files, the
program's own code, in order. As tools/bees_edge_gen.py does for BEAM mode and tools/bees_trust_gen.py for TRUST.

Silica has no type names, so the parts and roles may write the long record types of the TEMPUS units as $NAME$; they are
replaced here (TYPES below; the same texts as in src/tempus/dangerous_bees_tempus_conn.silica). A role file may add names
of its own with lines `//$ NAME = text`.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "src")
D = "{ addr: string, id: string, pub: string, token: string }"
L = "List[{ id: string, d: string, age: int64 }, mem(normal)]"
CFG = ("{ node: actor_ref, sig: actor_ref, edge: dangerous_actor_ref, rnd: dangerous_actor_ref, mine: string, mtok: string, "
       "kid: string, ppub: string, wl: string, now: int64, skew: int64, count: int64, ms: uint64, ext: boolean }")
NM = ("(:link_up, string) | (:accepted, dangerous_actor_ref, string) | (:rx, string) | (:tx_credit, int64) | "
      "(:tx_failed, atom) | (:link_down, atom) | (:bees, int64, string, string, int64, int64, actor_ref)")
# the node (T3): src/tempus/bees_tempus_node.silica.in and src/tempus/bees_tempus_node.part say what each is
E = "{ id: string, d: string, age: int64 }"
DL = "List[int64, mem(normal)]"
M = "{ op: int64, id: string, d: string, n: int64, entries: $L$, draws: $DL$ }"
ML = "List[$M$, mem(normal)]"
A = ("{ node: actor_ref, st: actor_ref, up: boolean, typ: int64, "
     "id: string, d: string, own: boolean, cap: int64, count: int64, drv: boolean, skew: int64, lit: $DL$, j: int64, q: $ML$ }")
AZ = ("{ typ: int64, id: string, d: string, own: boolean, cap: int64, count: int64, drv: boolean, skew: int64, "
      "lit: string }")
P = "{ k: int64, cid: int64, st: int64, x: int64, who: actor_ref, s: string }"
PL = "List[$P$, mem(normal)]"
T5 = "(:bees, int64, string, string, int64)"
NC = ("{ app: actor_ref, sig: actor_ref, edge: dangerous_actor_ref, rnd: dangerous_actor_ref, wl: string, sents: string, "
      "listen: string, spec: string, mst: string, id: string, pub: string, addr: string, draws: string, typ: int64, skew: int64, max: int64, "
      "back: int64, blim: int64, fail: int64, "
      "k1: int64, c1: int64, k2: int64, c2: int64, k3: int64, c3: int64, ms: uint64, t1: uint64, t2: uint64, t3: uint64, "
      "j0: uint64, j1: uint64, driven: boolean, ext: actor_ref }")
NV = ("{ up: boolean, rc: actor_ref, a1: actor_ref, a2: actor_ref, a3: actor_ref, now: int64, ck: int64, mtok: string, kid: string, "
      "ppub: string, live: int64, na: int64, nd: int64, stop: boolean, jst: int64, jd: uint64, q: $PL$ }")
NS = "{ c: $NC$, v: $NV$ }"
NB = "{ op: int64, s1: string, s2: string, n: int64, m: int64, who: actor_ref }"
RQ = "{ body: string, pd: string, cid: int64, m: int64, who: actor_ref }"
NI = "{ id: string, pub: string, seed: string, addr: string, token: string, typ: int64 }"
NN = ("{ listen: string, spec: string, sents: string, wl: string, kid: string, ppub: string, ms: uint64, mst: string, "
      "max: int64, skew: int64, j0: uint64, j1: uint64, back: int64, blim: int64, fail: int64, every: uint64 }")
NZ = "{ k1: int64, c1: int64, t1: uint64, k2: int64, c2: int64, t2: uint64, k3: int64, c3: int64, t3: uint64 }"
NT = "{ driven: boolean, ext: actor_ref, draws: string }"
# the client (C2): example_tempus_clients/silica/bees_tempus_client.part says what each is
CI = ("{ id: string, pub: string, seed: string, seed2: string, addr: string, token: string, listen: string, spec: string, "
      "wl: string, kid: string, ppub: string, now: int64, skew: int64, count: int64, ms: uint64, mst: string }")
CS = "{ app: actor_ref, sig: actor_ref, sig2: actor_ref, edge: dangerous_actor_ref, rnd: dangerous_actor_ref, na: int64, c: $CI$ }"
# the bridge (T6): src/tempus/bees_tempus_bridge.silica says what each is
BL = "{ slim: int64, size: int64, rate: int64, ivl: int64, pin: int64, tin: int64, cms: int64 }"
BTL = "List[{ id: string, exp: int64, sc: int64, w0: int64, wn: int64, inf: int64 }, mem(normal)]"
TYPES = {"$BL$": BL, "$BTL$": BTL, "$CI$": CI, "$CS$": CS, "$D$": D, "$L$": L, "$CFG$": CFG, "$NM$": NM, "$E$": E, "$DL$": DL, "$M$": M, "$ML$": ML, "$A$": A, "$AZ$": AZ,
         "$P$": P, "$PL$": PL, "$T5$": T5, "$NC$": NC, "$NV$": NV, "$NS$": NS, "$NB$": NB, "$RQ$": RQ,
         "$NI$": NI, "$NN$": NN, "$NZ$": NZ, "$NT$": NT}
USES = ["bees_reporter", "bees_atoms", "carrier", "wireframe", "wire_etf", "dangerous_sockets", "dangerous_tcp_carrier",
        "bees_trust_frame", "bees_tempus_view", "bees_tempus_frame", "bees_tempus_admit", "dangerous_bees_tempus_native",
        "dangerous_bees_tempus_edge", "dangerous_bees_trust_native", "dangerous_bees_trust_edge",
        "dangerous_bees_tls_native", "dangerous_bees_tempus_tls", "dangerous_bees_tempus_conn"]


def local_types(text):
    """a role file may name record types of its own: a line `//$ NAME = { ... }` makes $NAME$ stand for the text"""
    out = {}
    for line in text.splitlines():
        if line.startswith("//$ ") and " = " in line:
            name, body = line[4:].split(" = ", 1)
            out["$" + name.strip() + "$"] = body.strip()
    return out


def expand(text, where, more=None):
    types = dict(TYPES)
    types.update(more or {})
    text = "".join(l for l in text.splitlines(True) if not l.startswith("//$ "))
    for _ in range(4):          # a type may name another
        for k, v in types.items():
            text = text.replace(k, v)
    if "$" in text:
        i = text.index("$")
        raise SystemExit("%s: an unknown $NAME$ near %r" % (where, text[max(0, i - 20):i + 20]))
    return text


def part_path(name):
    """a part of src/tempus by its file name; any other part by its path from the BEES root (the example clients' part
    is example_tempus_clients/silica/bees_tempus_client.part)"""
    return os.path.join(HERE, "..", name) if "/" in name else os.path.join(SRC, "tempus", name)


def edge(argv):
    name, out, rest = argv[0], argv[1], argv[2:]
    uses, parts, roles = [], [], []
    while rest:
        if rest[0] == "--use" and len(rest) > 1:
            uses.append(rest[1])
            rest = rest[2:]
        elif rest[0] == "--part" and len(rest) > 1:
            parts.append(part_path(rest[1]))
            rest = rest[2:]
        else:
            roles.append(rest[0])
            rest = rest[1:]
    if not roles or not name.startswith("dangerous_"):
        print("error: NAME must be dangerous_* (the carrier is an FFI wrapper) and at least one role file is needed")
        return 1
    files = [os.path.join(SRC, "shim", "bees_tcp_edge.part"), os.path.join(SRC, "tempus", "bees_tempus_link.part")] + parts
    text = "// Generated by tools/bees_tempus_gen.py from %s. Do not edit.\n" % ", ".join(os.path.basename(f) for f in files + roles)
    text += "".join("use %s;\n" % u for u in USES + [u for u in uses if u not in USES])
    text += "module %s;\n\n" % name
    more = {}
    for f in roles:
        more.update(local_types(open(f).read()))
    for f in files + roles:
        text += expand(open(f).read(), f, more) + "\n"
    with open(out, "w") as f:
        f.write(text)
    return 0


def bridge(argv):
    """a bridge: the TRUST root unit as tools/bees_trust_gen.py wrote it (its own use lines, module line, carrier edge,
    TRUST link and node edge, untouched), the TEMPUS units' use lines added before its module line, then the TEMPUS link
    edge, the parts and the roles. The carrier edge is not pasted twice."""
    name, out, troot, rest = argv[0], argv[1], argv[2], argv[3:]
    uses, parts, roles = [], [], []
    while rest:
        if rest[0] == "--use" and len(rest) > 1:
            uses.append(rest[1])
            rest = rest[2:]
        elif rest[0] == "--part" and len(rest) > 1:
            parts.append(part_path(rest[1]))
            rest = rest[2:]
        else:
            roles.append(rest[0])
            rest = rest[1:]
    t = open(troot).read()
    mod = "module %s;\n" % name
    if not roles or not name.startswith("dangerous_") or t.count(mod) != 1:
        print("error: NAME must be dangerous_*, the TRUST root unit must be the one written for NAME, and a role file is needed")
        return 1
    head, body = t.split(mod, 1)
    have = set(l[4:-1] for l in head.splitlines() if l.startswith("use ") and l.endswith(";"))
    # bees_reporter only when asked (--use): a bridge program is near the unit count at which SD-59 was seen
    more_uses = [u for u in [x for x in USES if x != "bees_reporter"] + uses if u not in have]
    files = [os.path.join(SRC, "tempus", "bees_tempus_link.part")] + parts
    text = "// Generated by tools/bees_tempus_gen.py (bridge) from %s and %s. Do not edit.\n" % (
        os.path.basename(troot), ", ".join(os.path.basename(f) for f in files + roles))
    text += "".join(l + "\n" for l in head.splitlines() if not l.startswith("//"))
    text += "".join("use %s;\n" % u for u in dict.fromkeys(more_uses))
    text += mod + body + "\n"
    more = {}
    for f in roles:
        more.update(local_types(open(f).read()))
    for f in files + roles:
        text += expand(open(f).read(), f, more) + "\n"
    if not os.path.exists(out) or open(out).read() != text:
        with open(out, "w") as f:
            f.write(text)
    return 0


SPEC_LINE = re.compile(r"^(type|entry)\s+(\S+)\s+(.+)$")
TYPE_CODE = {"tempus_edge": 1, "tempus_bridge": 2, "tempus_sentinel": 3}


def spec_value(v, where):
    """none | any | [{Module, any} | {Module, [{Function, Arity}, ...]}, ...]: the forms of a TRUST whitelist entry's
    permission spec (inter-nodal-modes 3.3); returns a Silica boolean expression over ms, fs, a"""
    v = v.strip()
    if v == "none":
        return "false"
    if v == "any":
        return "true"
    if not (v.startswith("[") and v.endswith("]")):
        raise SystemExit("%s: a spec is none, any or a list: %r" % (where, v))
    alts = []
    for m, body in re.findall(r"\{\s*([a-z][A-Za-z0-9_]*)\s*,\s*(any|\[[^\]]*\])\s*\}", v):
        if body == "any":
            alts.append('ms == "%s"' % m)
            continue
        for f, a in re.findall(r"\{\s*([a-z][A-Za-z0-9_]*)\s*,\s*([0-9]+)\s*\}", body):
            alts.append('(ms == "%s" and fs == "%s" and a == %s)' % (m, f, a))
    return " or ".join(alts) if alts else "false"


def spec(src, out):
    """the unit bees_tempus_spec: permitted(wm, m, f, a), wm = 4 * (whitelist index + 1) + the peer's type as the node
    gives it. A peer in the tempus whitelist with an `entry` line is judged by that line (ruling NQ-4: the whitelist
    entry's spec replaces the per-type spec); any other by its type's line; a type with no line permits nothing (17.4:
    none by default). SPEC_FILE lines: `type tempus_edge SPEC`, `entry N SPEC`, `#` comments."""
    types, entries = {}, {}
    for n, raw in enumerate(open(src), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        mt = SPEC_LINE.match(line)
        if not mt:
            raise SystemExit("%s:%d: not a spec line" % (src, n))
        where = "%s:%d" % (src, n)
        if mt.group(1) == "type":
            if mt.group(2) not in TYPE_CODE:
                raise SystemExit("%s: no such peer type %r" % (where, mt.group(2)))
            types[TYPE_CODE[mt.group(2)]] = spec_value(mt.group(3), where)
        else:
            entries[int(mt.group(2))] = spec_value(mt.group(3), where)
    text = "// Generated by tools/bees_tempus_gen.py spec from %s. Do not edit.\n" % os.path.basename(src)
    text += "module bees_tempus_spec;\nuse bees_atoms;\n\nexport permitted/4;\n\n"
    text += "fn by_type(t: int64, ms: string, fs: string, a: int64) -> boolean {\n    case t of {\n"
    for t in (1, 2, 3):
        text += "        %d -> %s;\n" % (t, types.get(t, "false"))
    text += "        _: int64 -> false\n    }\n}\n"
    text += "fn by_entry(w: int64, t: int64, ms: string, fs: string, a: int64) -> boolean {\n    case w of {\n"
    for w in sorted(entries):
        text += "        %d -> %s;\n" % (w, entries[w])
    text += "        _: int64 -> by_type(t, ms, fs, a)\n    }\n}\n"
    text += ("fn permitted(wm: int64, m: atom, f: atom, a: int64) -> boolean {\n"
             "    by_entry(wm / 4 - 1, wm % 4, bees_atoms@spelling(m), bees_atoms@spelling(f), a)\n}\n")
    if not os.path.exists(out) or open(out).read() != text:
        with open(out, "w") as f:
            f.write(text)
    return 0


def unit(src, out):
    """a library unit written with the $NAME$ type names: OUT is the unit a program compiles"""
    text = "// Generated by tools/bees_tempus_gen.py from %s. Do not edit.\n" % os.path.basename(src)
    text += expand(open(src).read(), src)
    if not os.path.exists(out) or open(out).read() != text:
        with open(out, "w") as f:
            f.write(text)
    return 0


def main(argv):
    if len(argv) >= 5 and argv[1] == "edge":
        return edge(argv[2:])
    if len(argv) >= 6 and argv[1] == "bridge":
        return bridge(argv[2:])
    if len(argv) == 4 and argv[1] == "spec":
        return spec(argv[2], argv[3])
    if len(argv) == 4 and argv[1] == "unit":
        return unit(argv[2], argv[3])
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
