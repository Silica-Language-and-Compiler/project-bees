#!/usr/bin/env python3
"""bees_trust_gen: build-time generators for a TRUST-mode node program (N3).

    bees_trust_gen.py mfa  -o OUT_DIR [--config BEES_CONFIG] MANIFEST.trust...   write OUT_DIR/bees_trust_mfa.silica (the MFA table)
    bees_trust_gen.py edge NAME OUT_FILE ROLE_FILE...       write a TRUST node's dangerous_ root unit

The MFA table (inter-nodal-modes 1.1, 3.4: a function that was not compiled into the program does not exist). A `.trust`
manifest lists the functions a TRUST peer may name, one per line (`#` comments):

    export <module> <function> <arity> <unit>@<fn> args <ElemType> result <ResultType>

`<module>`, `<function>` are the names a peer sends (`m`, `f`); `<unit>@<fn>` is the Silica function that implements it, of type
`fn(args: List[<ElemType>, mem(normal)]) -> (:ok, <ResultType>) | (:error, atom)`; `(:error, Reason)` is the user code failing
(the worker then fails with Reason, D2; nothing is sent to the peer, 3.4). THIS IS THE PROVISIONAL ANSWER TO THE OPEN QUESTION of
mvp.md N3 ("args and value, any-type terms in SEMP, typed per MFA by a manifest line still to be defined"): SEMP's `args` is a
list of any terms; BEES decodes it with the language's decode((:etf), ...) as `List[<ElemType>]` (one element type; an inline sum
of atoms and tagged tuples is allowed by the language, a sum of plain types is not, E2401), with the arity checked first, and the
result value is the language's encode((:etf), value) of `<ResultType>`. Generated:

    slot_of(m: atom, f: atom, a: int64) -> int64        the table slot, -1 when the program has no such function
    check_args(slot, args_span) -> atom                  :ok, or the language's rejection atom (the receive actor's check)
    run(slot, args_span) -> { code, why, value }         decode, call, encode (the per-request worker): code 0 ok (value is the
                                                         result's ETF span), 1 the user code failed (why), 2 args refused (why)

The decode limits of `args` come from bees.config (N1, D39 R1), read by the one reader tools/bees_conf.py (a build-time stand-in):
max_bytes = trust.args_len_max + 1 (the version byte BEES puts before the span), max_length = trust.args_len_max, max_depth =
trust.term_depth_max. They are literals in the generated decoder because the language bakes decode limits into the derived
decoder (transport design 4.1, E2402). Without --config, or when the file is refused (the boot then refuses it too), the reader's
defaults are used (R1: 4294967295, depth 32).

The root unit: the BEES carrier edge (src/shim/bees_tcp_edge.part: carrier_new) and the TRUST node edge
(src/shim/bees_trust_node.part: boot check, start, trpc, test helpers), then the role files; the same shape as
tools/bees_edge_gen.py writes for BEAM mode, kept separate (D36).
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TCP_PART = os.path.join(HERE, "..", "src", "shim", "bees_tcp_edge.part")
NODE_PART = os.path.join(HERE, "..", "src", "shim", "bees_trust_node.part")
LINK_PLAIN = os.path.join(HERE, "..", "src", "shim", "bees_trust_link_plain.part")
LINK_TLS = os.path.join(HERE, "..", "src", "shim", "bees_trust_link_tls.part")
MUX_PART = os.path.join(HERE, "..", "src", "shim", "bees_trust_mux.part")
TLS_USES = ["dangerous_bees_tls_native", "dangerous_bees_tls"]
# N5 (sessions): the units a multiplexing node's root unit uses, and the functions of bees_trust_node.part that
# bees_trust_mux.part replaces (the originals stay in the root unit under the name with _b1)
MUX_USES = ["bees_trust_mux_frame", "bees_trust_slots", "dangerous_bees_trust_mux"]
MUX_RENAMES = ("trust_start", "trust_listen", "trpc_request")
HEADER_USES = ["bees_atoms", "carrier", "wireframe", "wire_etf", "dangerous_sockets", "dangerous_tcp_carrier", "bees_trust_frame",
               "bees_trust_conf", "bees_trust_mfa", "dangerous_bees_trust_edge", "dangerous_bees_trust"]
LINE = re.compile(r"export\s+([a-z][A-Za-z0-9_]*)\s+([a-z][A-Za-z0-9_]*)\s+([0-9]+)\s+([a-z][A-Za-z0-9_]*)@([a-z][A-Za-z0-9_]*)\s+args\s+(.+?)\s+result\s+(.+)$")


def parse(paths):
    out = []
    for p in paths:
        for n, raw in enumerate(open(p), 1):
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            m = LINE.fullmatch(line)
            if not m:
                raise SystemExit(f"{p}:{n}: cannot read '{line}'")
            mod, fn, ar, unit, impl, elem, res = m.groups()
            if int(ar) > 255:
                raise SystemExit(f"{p}:{n}: arity above 255")
            if any((e[0], e[1], e[2]) == (mod, fn, int(ar)) for e in out):
                raise SystemExit(f"{p}:{n}: {mod}:{fn}/{ar} listed twice")
            out.append((mod, fn, int(ar), unit, impl, elem, res))
    return out


def limits(cfg):
    sys.path.insert(0, HERE)
    import bees_conf as C
    args, depth = C.BEAM_FRAME_MAX, C.TRUST_OPTS["term_depth_max"].default
    if cfg:
        try:
            t = C.validate(cfg, None)["trust"]
            args, depth = t["args_eff"], t["term_depth_max"]
        except C.ConfError:
            pass        # the boot verdict is bees_trust_conf's (tools/bees_config_trust.py); the node will not start
    return "{ max_bytes: %d, max_depth: %d, max_length: %d }" % (args + 1, depth, args)


def gen_mfa(out_dir, entries, lim="{ max_bytes: 4294967296, max_depth: 32, max_length: 4294967295 }"):
    units = sorted({e[3] for e in entries})
    L = ["// Generated by tools/bees_trust_gen.py from the program's .trust manifests. Do not edit. The TRUST MFA table: which",
         "// functions a peer may name (after the forbidden guard and the permission gate), the declared types its args are decoded",
         "// with (the language's decode, in the sequence of each produces-pure block), and the call of the implementing function.",
         "module bees_trust_mfa;", "use bees_atoms;", "use wire_etf;"] + [f"use {u};" for u in units] + [""]
    L += ["export slot_of/3;", "export check_args/2;", "export run/2;", ""]
    L.append("fn term(sp: string) -> string {")
    L.append("    sequence proc[mem(normal), transport]")
    L.append("        xs: List[int64, mem(normal)] <- [131];")
    L.append("        h: string <- bytes_of(xs);")
    L.append("        parts: List[string, mem(normal)] <- [h, sp];")
    L.append("        s: string <- join_bytes(parts)")
    L.append("    produces pure s end")
    L.append("}")
    e = "0 - 1"
    for i, (mod, fn, ar, *_r) in reversed(list(enumerate(entries))):
        e = f'case ms == "{mod}" and fs == "{fn}" and a == {ar} of {{ true -> {i}; false -> {e} }}'
    L.append(f"fn slot_in(ms: string, fs: string, a: int64) -> int64 {{ {e} }}")
    L.append("fn slot_of(m: atom, f: atom, a: int64) -> int64 { slot_in(bees_atoms@spelling(m), bees_atoms@spelling(f), a) }")
    R = "{ code: int64, why: atom, value: string }"
    for i, (mod, fn, ar, unit, impl, elem, res) in enumerate(entries):
        lt = f"List[{elem}, mem(normal)]"
        L.append(f"// {i}: {mod}:{fn}/{ar} -> {unit}@{impl}")
        L.append(f"fn chk_{i}(sp: string) -> atom {{")
        L.append("    sequence proc[mem(normal), transport]")
        L.append(f"        r: (:ok, {lt}) | (:rejected, atom) <- decode((:etf), term(sp), {lim})")
        L.append(f"    produces pure case r of {{ (:ok, _xs: {lt}) -> :ok; (:rejected, w: atom) -> w }} end")
        L.append("}")
        L.append(f"fn enc_{i}(v: {res}) -> string {{")
        L.append("    sequence proc[mem(normal), transport]")
        L.append("        s: string <- encode((:etf), v);")
        L.append("        out: string <- byte_slice(s, 1, length_bytes(s))")
        L.append("    produces pure out end")
        L.append("}")
        L.append(f"fn out_{i}(r: (:ok, {res}) | (:error, atom)) -> {R} {{")
        L.append(f"    case r of {{ (:ok, v: {res}) -> {{ code: 0, why: :ok, value: enc_{i}(v) }}; (:error, w: atom) -> {{ code: 1, why: w, value: \"\" }} }}")
        L.append("}")
        L.append(f"fn run_{i}(sp: string) -> {R} {{")
        L.append("    sequence proc[mem(normal), transport]")
        L.append(f"        r: (:ok, {lt}) | (:rejected, atom) <- decode((:etf), term(sp), {lim})")
        L.append(f"    produces pure case r of {{ (:ok, xs: {lt}) -> out_{i}({unit}@{impl}(xs)); (:rejected, w: atom) -> {{ code: 2, why: w, value: \"\" }} }} end")
        L.append("}")
    L.append("fn check_args(slot: int64, sp: string) -> atom {")
    L.append("    case slot of {")
    for i in range(len(entries)):
        L.append(f"        {i} -> chk_{i}(sp);")
    L.append("        _: int64 -> bees_atoms@a_unsupported()")
    L += ["    }", "}"]
    L.append(f"fn run(slot: int64, sp: string) -> {R} {{")
    L.append("    case slot of {")
    for i in range(len(entries)):
        L.append(f"        {i} -> run_{i}(sp);")
    L.append('        _: int64 -> { code: 2, why: bees_atoms@a_unsupported(), value: "" }')
    L += ["    }", "}", ""]
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "bees_trust_mfa.silica"), "w") as fh:
        fh.write("\n".join(L))


def mux_units(out_dir, cfg):
    """N5: a node whose bees.config multiplexes gets its session units beside the MFA table (tools/bees_trust_mux_gen.py); a node
    that does not has none of them (stale ones are removed, so a changed config cannot leave a unit behind)"""
    sys.path.insert(0, HERE)
    import bees_conf as C
    import bees_trust_mux_gen as M
    t = None
    if cfg:
        try:
            t = C.validate(cfg, None)["trust"]
        except C.ConfError:
            t = None
    if t and t.get("active") and t.get("session_set"):
        M.generate(out_dir, t["session"]["max_inflight"])
    else:
        M.remove(out_dir)


def gen_edge(name, out, roles):
    if not name.startswith("dangerous_"):
        raise SystemExit("the root unit of a TRUST node must be named dangerous_* (it installs FFI workers)")
    # N4.1: the link part follows the node's generated configuration (lib/bees_trust_conf.silica beside the root unit, written
    # first by tools/bees_config_trust.py): over TLS the TLS worker and its engine are used; under plaintext_test_only neither is,
    # so a plaintext node needs no OpenSSL
    conf = os.path.join(os.path.dirname(os.path.abspath(out)), "lib", "bees_trust_conf.silica")
    conf_text = open(conf).read() if os.path.isfile(conf) else ""
    tls = "fn tls() -> boolean { true }" in conf_text
    # N5: a node that multiplexes (bees_trust_conf@mux) also gets bees_trust_mux.part, whose trust_start, trust_listen and
    # trpc_request replace the node part's (renamed here, in the generated text only; a node that does not multiplex gets
    # exactly the text it got before N5)
    mux = "fn mux() -> boolean { true }" in conf_text
    link = LINK_TLS if tls else LINK_PLAIN
    text = "// Generated by tools/bees_trust_gen.py from src/shim/bees_tcp_edge.part, src/shim/bees_trust_node.part, %s%s and %s. Do not edit.\n" \
        % (os.path.basename(link), ", bees_trust_mux.part" if mux else "", " ".join(os.path.basename(r) for r in roles))
    text += "".join(f"use {u};\n" for u in HEADER_USES + (TLS_USES if tls else []) + (MUX_USES if mux else []))
    text += f"module {name};\n\n"
    node = open(NODE_PART).read()
    if mux:
        for fn in MUX_RENAMES:
            if node.count(f"\nfn {fn}(") != 1:
                raise SystemExit(f"bees_trust_gen: bees_trust_node.part no longer defines {fn} exactly once")
            node = node.replace(f"\nfn {fn}(", f"\nfn {fn}_b1(")
        node += "\n" + open(MUX_PART).read()
    text += open(TCP_PART).read() + "\n" + open(link).read() + "\n" + node
    for r in roles:
        text += "\n" + open(r).read()
    with open(out, "w") as fh:
        fh.write(text)


def main(argv):
    if len(argv) >= 4 and argv[1] == "mfa" and argv[2] == "-o":
        rest, cfg = argv[4:], None
        if len(rest) >= 2 and rest[0] == "--config":
            cfg, rest = rest[1], rest[2:]
        gen_mfa(argv[3], parse(rest), limits(cfg))
        mux_units(argv[3], cfg)
        return 0
    if len(argv) >= 5 and argv[1] == "edge":
        gen_edge(argv[2], argv[3], argv[4:])
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
