#!/usr/bin/env python3
"""bees_config: build-time generator for a BEES program (roadmap §4.8, R0.1).

Commands

    bees_config.py generate -o OUT_DIR MANIFEST...   everything below, from one manifest list
    bees_config.py wire     -o OUT_DIR MANIFEST...   only the wire codecs (.wire manifests; bees_wire_gen.py)
    bees_config.py atoms    -o OUT_DIR MANIFEST...   only bees_atoms (D30)
    bees_config.py check    UNIT...                  atom-literal lint

A compiler writes manifests next to its units. Three kinds, told apart by extension:

  <unit>.atoms     one atom spelling per line (`#` comments allowed): every symbol the unit uses.
  <unit>.module    the module table entries of one module (formats below).
  <name>.pools     requests for pools of child ids (formats below).
  <unit>.wire      message types that cross between nodes (format in tools/bees_wire_gen.py):
                   `message <name> <silica type>`; one kind id per message in manifest order.

`generate` writes, into OUT_DIR, each unit only when its manifests exist:

  bees_atoms.silica (+ bees_atoms.index)   always. The union of the atoms of every `.atoms` file
                   plus every atom the other manifests imply (module names, function names, pool
                   ids, and the atoms the generated units themselves use: undef, badfun,
                   id_pool_exhausted). Tiered: no `case` has more than 256 arms.
  bees_modules.silica    when a `.module` file exists: dispatch by module, function and arity
                   (apply/3 style) and by fun id.
  bees_ids.silica        when a `.pools` file exists: child-id pools.
  bees_wire_tables.silica, bees_wire_msgs.silica
                   when a `.wire` file exists: the byte tables and the per-message encoders, decoders,
                   kind ids, schema digest and dispatcher (hand-written core: src/inter_nodal/bees_wire.silica).
                   A message type with a field the wire does not carry is a build error (exit 1).

Everything generated is sorted, so the same manifests give byte-identical units, and none of it
contains a BEAM atom literal outside bees_atoms (every other unit reaches atoms through
`bees_atoms@a_<name>()`).

bees_atoms (D30)
    Each `.atoms` manifest is one atom spelling per line. The union, in canonical (sorted) order,
    becomes the unit `bees_atoms.silica`, the only unit that may write a BEAM atom literal:

        fn a_<name>() -> atom            one accessor per atom, returning the literal
        fn spelling(a: atom) -> string   the atom's spelling ("?" for an atom not in the program)
        fn index(a: atom) -> int64       canonical index (-1 for an atom not in the program)
        fn from_spelling(s: string) -> { found: boolean, value: atom }
        fn count() -> int64

    The index table is also written as `bees_atoms.index` (index TAB spelling).

Module table: `<unit>.module`, one module per file, line oriented, `#` starts a comment
    module <name>                   the module's name (an atom spelling). Required, first.
    unit <silica_unit>              the Silica unit that holds the functions. Optional; default is
                                    the manifest's own base name.
    entry <name> <arity> <fn>       an exported function <name>/<arity>, implemented by the Silica
                                    function <fn> of the unit. 0 <= arity <= 255.
    fun <id> <fn>                   a fun body with module-local id <id> (0 <= id < 2^31),
                                    implemented by the Silica function <fn>.
  Calling convention (one fixed convention, so the table is a plain `case`):
    entry: fn <fn>(ap: APPLY, h: HEAP, args: TERM) -> TERM        args: a list term of <arity> terms
    fun:   fn <fn>(ap: APPLY, h: HEAP, env: TERM, args: TERM) -> TERM   env: the fun's captured list
    HEAP = { r: region(L, normal) }; TERM = the bees_term cell reference, as in bees_term.silica;
    APPLY = fn(HEAP, TERM, TERM) -> TERM, the generated `dispatch` passed as a value (see below).
  Generated bees_modules:
    dispatch(h, target: TERM, args: TERM) -> TERM      target is a fun term (call it) or a 2-tuple
                                                        term {Module, Function} (apply(M, F, Args))
    apply(h, m: atom, f: atom, args: TERM) -> TERM     apply(M, F, Args)
    apply_fun(h, fv: TERM, args: TERM) -> TERM         call a fun term made by fun_of
  An unknown module, function or arity, a non-fun, or an unknown fun id gives the empty reference
  (`:none`, test it with bees_term@is_none). The table cannot fail the actor itself: Silica admits
  `fail_self` only directly in a behaviour function (E2091 elsewhere). The caller fails with
  `fail_self(bees_atoms@a_undef())` (apply/3) or `fail_self(bees_atoms@a_badfun())` (a fun or
  tuple target); bees_config puts both atoms in bees_atoms whenever a module manifest exists.
    fun_of(h, m: atom, id: int64, env: TERM) -> TERM   build the fun term for fun <id> of module m
    is_exported(m: atom, f: atom, arity: int64) -> boolean
    has_module(m: atom) -> boolean
    module_index(m: atom) -> int64                     index in sorted module order, -1 if absent
    module_count() -> int64
  Silica forbids cyclic `use`, so no module in the table can `use` bees_modules. The table passes
  `dispatch` to every entry and fun body as the value `ap`; a module that applies dynamically takes
  `ap` as a parameter and calls it: ap(h, target, args). The program's top unit (main) is the only
  unit that names bees_modules. Statically known calls between modules stay ordinary calls.

Child-id pools: `<name>.pools`, line oriented
    pool <name> <count>             <count> ids (1 <= count <= 65536): atoms <name>_0 .. <name>_<count-1>
    tree <name> <fanout> <size>     a two-level supervisor tree: pool <name>_top of <fanout> ids
                                    (the ids of the leaf supervisors under the top supervisor) and
                                    <fanout> leaf pools <name>_n0 .. <name>_n<fanout-1> of <size> ids
  Pool names are identifiers and unique program-wide. Every pool owns its atoms: Silica registers a
  child under its id in one program-wide namespace, so two supervisors must never share an id.
  Generated bees_ids:
    pool_<name>() -> int64          the pool's number
    leaf_<tree>(j: int64) -> int64  pool number of leaf pool j of a tree
    pool_count() -> int64
    pool_size(pool: int64) -> int64
    id_of(pool: int64, i: int64) -> atom   the i-th id of the pool; for i outside 0..size-1 (or an unknown
                                            pool) it returns the atom id_pool_exhausted, which no pool
                                            uses, and the caller fails with fail_self (E2091: not here)

Supervisor position map: nothing is generated. Silica numbers positions at run time (spec 15.1.4
implementation status), so there is no build-time numbering to generate from; see the compiler
guide (A4) for what a program keeps at run time.

`bees_config.py check UNIT...` reports every BEAM atom literal written outside bees_atoms:
any `:name` literal that is not one of the runtime's fixed atoms (which every unit numbers
identically) and not inside a comment or string. It is a lint, not a parser: type unions such as
`:reply | :no_reply` and `child_spec` fields are Silica-level atoms the compiler resolves, so
they are on the fixed list below as well.
"""
import os
import re
import sys

# The atoms the runtime numbers identically in every unit (atom_0..atom_22 in every .sams), plus
# the atoms the compiler itself interprets in behaviour returns, child specs, supervisor messages
# and trait protocols. Any of these may be written as a literal in any unit.
FIXED_ATOMS = {
    "efficiency", "performance", "ok", "normal", "language_error", "memory_fault", "explicit",
    "unknown", "noproc", "permanent", "transient", "temporary", "one_for_one", "one_for_all",
    "rest_for_one", "insert", "lookup", "delete", "found", "not_found", "unknown_op", "plain",
    "dangerous",
    # compiler-interpreted protocol atoms
    "reply", "no_reply", "none", "worker", "supervisor", "child_started", "children", "count",
    "child_info", "error", "add_child", "count_children", "get_child", "remove_child",
    "restart_child", "terminate_child", "which_children", "less", "equal", "greater",
    # stack and state policies (spawn arguments, chunk 1 and chunk 15) and report-sink protocol
    "release_on_return", "keep_last_message", "track_recent_peak", "release_when_idle",
    "keep_high_water", "keep_state_area", "shrink_after_compaction", "compact_on_request",
    "set_report_sink", "sink_set", "terminate_actor",
}

TIER = 256

ATOM_RE = re.compile(r"(?<![A-Za-z0-9_'\"]):([A-Za-z_][A-Za-z0-9_]*)")


IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
MODULE_ATOMS = ["undef", "badfun"]       # used by the generated bees_modules
POOL_ATOMS = ["id_pool_exhausted"]       # used by the generated bees_ids
MAX_ATOMS = (1 << 20) - 2                # the entry key packs an atom index into 20 bits
T = "ref?(L, normal, (int64, int64, float64, atom, actor_ref, ref?(L, normal, rec), ref?(L, normal, rec)))"
H = "{ r: region(L, normal) }"


class ManifestError(Exception):
    pass


def manifest_lines(path):
    with open(path) as fh:
        for n, line in enumerate(fh, 1):
            line = line.split("#", 1)[0].strip()
            if line:
                yield n, line.split()


def parse_module(path):
    """-> dict(module, unit, entries=[(name, arity, fn)], funs=[(id, fn)])"""
    base = os.path.basename(path)
    m = {"module": None, "unit": base[:-len(".module")], "entries": [], "funs": [], "path": path}
    for n, w in manifest_lines(path):
        where = f"{path}:{n}"
        if w[0] == "module" and len(w) == 2 and IDENT.fullmatch(w[1]):
            m["module"] = w[1]
        elif w[0] == "unit" and len(w) == 2 and IDENT.fullmatch(w[1]):
            m["unit"] = w[1]
        elif w[0] == "entry" and len(w) == 4 and IDENT.fullmatch(w[1]) and w[2].isdigit() and IDENT.fullmatch(w[3]):
            if int(w[2]) > 255:
                raise ManifestError(f"{where}: arity {w[2]} is above 255")
            m["entries"].append((w[1], int(w[2]), w[3]))
        elif w[0] == "fun" and len(w) == 3 and w[1].isdigit() and IDENT.fullmatch(w[2]):
            if int(w[1]) >= 1 << 31:
                raise ManifestError(f"{where}: fun id {w[1]} is not below 2^31")
            m["funs"].append((int(w[1]), w[2]))
        else:
            raise ManifestError(f"{where}: cannot read '{' '.join(w)}'")
    if m["module"] is None:
        raise ManifestError(f"{path}: no `module <name>` line")
    seen = set()
    for name, arity, _ in m["entries"]:
        if (name, arity) in seen:
            raise ManifestError(f"{path}: entry {name}/{arity} listed twice")
        seen.add((name, arity))
    ids = [i for i, _ in m["funs"]]
    if len(ids) != len(set(ids)):
        raise ManifestError(f"{path}: a fun id is listed twice")
    return m


def parse_pools(path):
    """-> list of (pool name, count); a `tree` line expands to its pools."""
    pools = []
    for n, w in manifest_lines(path):
        where = f"{path}:{n}"
        if w[0] == "pool" and len(w) == 3 and IDENT.fullmatch(w[1]) and w[2].isdigit() and 1 <= int(w[2]) <= 65536:
            pools.append((w[1], int(w[2]), None))
        elif w[0] == "tree" and len(w) == 4 and IDENT.fullmatch(w[1]) and w[2].isdigit() and w[3].isdigit() \
                and 1 <= int(w[2]) <= 4096 and 1 <= int(w[3]) <= 65536:
            fan = int(w[2])
            pools.append((w[1] + "_top", fan, None))
            for j in range(fan):
                pools.append((f"{w[1]}_n{j}", int(w[3]), (w[1], j)))
        else:
            raise ManifestError(f"{where}: cannot read '{' '.join(w)}'")
    return pools


def split_manifests(paths):
    atoms_f = [p for p in paths if p.endswith(".atoms")]
    mod_f = [p for p in paths if p.endswith(".module")]
    pool_f = [p for p in paths if p.endswith(".pools")]
    other = [p for p in paths if p not in atoms_f + mod_f + pool_f and not p.endswith(".wire")]
    if other:
        raise ManifestError("unknown manifest kind: " + ", ".join(other))
    return atoms_f, mod_f, pool_f


def collect(paths):
    """Parse every manifest. -> (sorted atoms, modules, pools); pools are sorted by name."""
    atoms_f, mod_f, pool_f = split_manifests(paths)
    atoms = set()
    for p in atoms_f:
        for _, w in manifest_lines(p):
            atoms.add(w[0])
    modules = sorted((parse_module(p) for p in mod_f), key=lambda m: m["module"])
    names = [m["module"] for m in modules]
    for a in set(names):
        if names.count(a) > 1:
            raise ManifestError(f"module {a} is described by more than one manifest")
    pools = {}
    for p in pool_f:
        for name, count, leaf in parse_pools(p):
            if name in pools:
                raise ManifestError(f"{p}: pool {name} is requested twice")
            pools[name] = (count, leaf)
    pools = sorted((n, c, l) for n, (c, l) in pools.items())
    if modules:
        atoms.update(MODULE_ATOMS)
    for m in modules:
        atoms.add(m["module"])
        atoms.update(n for n, _, _ in m["entries"])
    if pools:
        atoms.update(POOL_ATOMS)
    for name, count, _ in pools:
        atoms.update(f"{name}_{i}" for i in range(count))
    if len(atoms) > MAX_ATOMS:
        raise ManifestError(f"{len(atoms)} atoms: more than the module table's key can hold ({MAX_ATOMS})")
    return sorted(atoms), modules, pools


def read_manifests(paths):
    return collect(paths)[0]


def accessor_name(spelling):
    """a_<spelling> when the spelling is an identifier; otherwise hex-escape the odd characters."""
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", spelling):
        return "a_" + spelling
    return "a_x" + "".join(c if re.fullmatch(r"[A-Za-z0-9]", c) else "_%02x" % ord(c) for c in spelling)


def silica_string(spelling):
    return '"' + spelling.replace("\\", "\\\\").replace('"', '\\"') + '"'


def gen_atoms(out_dir, manifests):
    atoms = read_manifests(manifests)
    return write_atoms(out_dir, atoms)


def write_atoms(out_dir, atoms):
    bad = [a for a in atoms if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", a)]
    if bad:
        # Silica's atom literal syntax is :identifier; quoted atoms need a spelling table entry
        # only, which is not generated yet (contract item 1 will say how such atoms are written).
        print("bees_config: atoms that are not identifiers are not supported yet: " + ", ".join(bad), file=sys.stderr)
        return 1
    lines = ["// Generated by tools/bees_config.py (D30). Do not edit; do not write BEAM atom literals elsewhere.",
             "module bees_atoms;", ""]
    for a in atoms:
        lines.append(f"export {accessor_name(a)}/0;")
    lines += ["export spelling/1;", "export index/1;", "export from_spelling/1;", "export count/0;", ""]
    for a in atoms:
        lines += [f"fn {accessor_name(a)}() -> atom {{ :{a} }}"]
    lines.append("")
    # Silica's parser rejects a case with 512 or more literal arms (E1069, ROADMAP compile-defect
    # trial case_512_literal_arms), so above TIER atoms each lookup is split into helper functions
    # of TIER arms that are tried in turn. At or below TIER the output is one flat case.
    chunks = [list(enumerate(atoms))[i:i + TIER] for i in range(0, max(len(atoms), 1), TIER)]
    if len(chunks) <= 1:
        lines.append("fn spelling(a: atom) -> string {")
        lines.append("    case a of {")
        for a in atoms:
            lines.append(f"        :{a} -> {silica_string(a)};")
        lines.append('        _: atom -> "?"')
        lines.append("    }")
        lines.append("}")
        lines.append("")
        lines.append("fn index(a: atom) -> int64 {")
        lines.append("    case a of {")
        for i, a in enumerate(atoms):
            lines.append(f"        :{a} -> {i};")
        lines.append("        _: atom -> -1")
        lines.append("    }")
        lines.append("}")
        lines.append("")
    else:
        for k, ch in enumerate(chunks):
            lines.append(f"fn spelling_{k}(a: atom) -> string {{")
            lines.append("    case a of {")
            for i, a in ch:
                lines.append(f"        :{a} -> {silica_string(a)};")
            lines.append('        _: atom -> "?"')
            lines.append("    }")
            lines.append("}")
            lines.append("")
            lines.append(f"fn index_{k}(a: atom) -> int64 {{")
            lines.append("    case a of {")
            for i, a in ch:
                lines.append(f"        :{a} -> {i};")
            lines.append("        _: atom -> -1")
            lines.append("    }")
            lines.append("}")
            lines.append("")
        for name, ret, miss, test in (("spelling", "string", '"?"', 's == "?"'), ("index", "int64", "-1", "r < 0")):
            lines.append(f"fn {name}(a: atom) -> {ret} {{")
            expr = f"{name}_{len(chunks) - 1}(a)"
            for k in range(len(chunks) - 2, -1, -1):
                expr = f"case ({name}_{k}(a)) == {miss} of {{ true -> {expr}; false -> {name}_{k}(a) }}"
            lines.append("    " + expr)
            lines.append("}")
            lines.append("")
    # from_spelling: a chain of string comparisons (no jump table for strings), split into helpers of
    # FROM_TIER comparisons each so no function nests thousands of cases.
    FROM_TIER = 64
    rec = "{ found: boolean, value: atom }"
    miss = "{ found: false, value: :unknown }"
    groups = [atoms[i:i + FROM_TIER] for i in range(0, max(len(atoms), 1), FROM_TIER)]
    for k, g in enumerate(groups):
        body = miss
        for a in reversed(g):
            body = f"case s == {silica_string(a)} of {{ true -> {{ found: true, value: :{a} }}; false -> {body} }}"
        lines.append(f"fn from_spelling_{k}(s: string) -> {rec} {{")
        lines.append("    " + body)
        lines.append("}")
        lines.append("")
    lines.append(f"fn from_spelling(s: string) -> {rec} {{")
    expr = f"from_spelling_{len(groups) - 1}(s)"
    for k in range(len(groups) - 2, -1, -1):
        expr = f"case from_spelling_{k}(s).found of {{ true -> from_spelling_{k}(s); false -> {expr} }}"
    lines.append("    " + expr)
    lines.append("}")
    lines.append("")
    lines.append(f"fn count() -> int64 {{ {len(atoms)} }}")
    lines.append("")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "bees_atoms.silica"), "w") as out:
        out.write("\n".join(lines))
    with open(os.path.join(out_dir, "bees_atoms.index"), "w") as out:
        for i, a in enumerate(atoms):
            out.write(f"{i}\t{a}\n")
    return 0


def emit_switch(lines, name, params, sel, ret, arms, default):
    """Emit `fn name(params) -> ret` as a `case` on the int64 parameter `sel`, never with more than
    TIER arms in one `case` (Silica rejects 512). `arms` is [(int key, expression)]; keys are
    distinct. Above TIER arms the arms go to helper functions name_0, name_1, ... (sorted keys,
    TIER each), and `name` picks the helper by a balanced tree of `sel < boundary` tests."""
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


def gen_modules(out_dir, atoms, modules):
    idx = {a: i for i, a in enumerate(atoms)}
    units = sorted({m["unit"] for m in modules})
    lines = ["// Generated by tools/bees_config.py. Do not edit. The module table: dispatch by module, function",
             "// and arity, and by fun id. Entries: fn(ap, h, args) -> term; funs: fn(ap, h, env, args) -> term.",
             "module bees_modules;", "use bees_atoms;", "use bees_term;"]
    lines += [f"use {u};" for u in units]
    lines.append("")
    for e in ("dispatch/3", "apply/4", "apply_fun/3", "fun_of/4", "is_exported/3", "has_module/1", "module_index/1", "module_count/0"):
        lines.append(f"export {e};")
    lines.append("")
    # modules
    mod_index = {m["module"]: i for i, m in enumerate(modules)}
    emit_switch(lines, "module_index", [("m", "atom")], "bees_atoms@index(m)", "int64",
                [(idx[m["module"]], str(i)) for i, m in enumerate(modules)], "-1")
    lines.append(f"fn module_count() -> int64 {{ {len(modules)} }}")
    lines.append("fn has_module(m: atom) -> boolean { module_index(m) >= 0 }")
    lines.append("")
    # named entries: key = ((module atom index * 2^20) + function atom index) * 256 + arity
    ent = []
    for m in modules:
        for name, arity, fn in m["entries"]:
            key = (idx[m["module"]] * 1048576 + idx[name]) * 256 + arity
            ent.append((key, m["unit"], fn))
    ent.sort()
    fns = [(k, f"{u}@{fn}(dispatch, h, args)") for k, u, fn in ent]
    lines.append("fn entry_key(m: atom, f: atom, arity: int64) -> int64 {")
    lines.append("    case bees_atoms@index(m) < 0 of { true -> -1; false ->")
    lines.append("    case bees_atoms@index(f) < 0 of { true -> -1; false ->")
    lines.append("    case arity > 255 of { true -> -1; false ->")
    lines.append("    (bees_atoms@index(m) * 1048576 + bees_atoms@index(f)) * 256 + arity } } }")
    lines += ["}", ""]
    emit_switch(lines, "entry_slot_of", [("key", "int64")], "key", "int64",
                [(k, str(i)) for i, (k, _) in enumerate(fns)], "-1")
    emit_switch(lines, "entry_run", [("h", H), ("slot", "int64"), ("args", T)], "slot", T,
                [(i, e) for i, (_, e) in enumerate(fns)], ":none")
    lines.append("fn entry_slot(m: atom, f: atom, arity: int64) -> int64 {")
    lines.append("    case entry_key(m, f, arity) < 0 of { true -> -1; false -> entry_slot_of(entry_key(m, f, arity)) }")
    lines += ["}", ""]
    lines.append(f"fn is_exported(m: atom, f: atom, arity: int64) -> boolean {{ entry_slot(m, f, arity) >= 0 }}")
    lines.append("")
    lines.append(f"fn apply(h: {H}, m: atom, f: atom, args: {T}) -> {T} {{")
    lines.append("    case entry_slot(m, f, bees_term@list_len(args)) < 0 of {")
    lines.append("        true -> :none;")
    lines.append("        false -> entry_run(h, entry_slot(m, f, bees_term@list_len(args)), args)")
    lines += ["    }", "}", ""]
    # funs: key = module index * 2^31 + fun id
    fun = []
    for m in modules:
        for fid, fn in m["funs"]:
            fun.append((mod_index[m["module"]] * 2147483648 + fid, m["unit"], fn))
    fun.sort()
    emit_switch(lines, "fun_slot_of", [("key", "int64")], "key", "int64",
                [(k, str(i)) for i, (k, _, _) in enumerate(fun)], "-1")
    emit_switch(lines, "fun_run", [("h", H), ("slot", "int64"), ("env", T), ("args", T)], "slot", T,
                [(i, f"{u}@{fn}(dispatch, h, env, args)") for i, (_, u, fn) in enumerate(fun)], ":none")
    lines.append(f"fn fun_key(fv: {T}) -> int64 {{")
    lines.append("    case bees_term@tag(fv) == 8 of {")
    lines.append("        true -> bees_term@int_of(fv) * 2147483648 + bees_term@int_of(bees_term@hd_of(bees_term@hd_of(fv)));")
    lines.append("        false -> -1")
    lines += ["    }", "}", ""]
    lines.append(f"fn apply_fun(h: {H}, fv: {T}, args: {T}) -> {T} {{")
    lines.append("    case fun_key(fv) < 0 of {")
    lines.append("        true -> :none;")
    lines.append("        false -> case fun_slot_of(fun_key(fv)) < 0 of {")
    lines.append("            true -> :none;")
    lines.append("            false -> fun_run(h, fun_slot_of(fun_key(fv)), bees_term@tl_of(bees_term@hd_of(fv)), args)")
    lines += ["        }", "    }", "}", ""]
    lines.append(f"fn dispatch(h: {H}, target: {T}, args: {T}) -> {T} {{")
    lines.append("    case bees_term@tag(target) of {")
    lines.append("        8 -> apply_fun(h, target, args);")
    lines.append("        6 -> case bees_term@int_of(target) == 2 of {")
    lines.append("            true -> apply(h, bees_term@atom_of(bees_term@nth(bees_term@hd_of(target), 0)), bees_term@atom_of(bees_term@nth(bees_term@hd_of(target), 1)), args);")
    lines.append("            false -> :none")
    lines.append("        };")
    lines.append("        _: int64 -> :none")
    lines += ["    }", "}", ""]
    lines.append(f"fn fun_of(h: {H}, m: atom, id: int64, env: {T}) -> {T} {{")
    lines.append("    bees_term@mk_fun(h, module_index(m), bees_term@mk_cons(h, bees_term@mk_int(h, id), env))")
    lines += ["}", ""]
    with open(os.path.join(out_dir, "bees_modules.silica"), "w") as out:
        out.write("\n".join(lines))
    return 0


def gen_ids(out_dir, atoms, pools):
    base, total = {}, 0
    for i, (name, count, _) in enumerate(pools):
        base[name] = total
        total += count
    pool_no = {name: i for i, (name, _, _) in enumerate(pools)}
    trees = {}
    for name, _, leaf in pools:
        if leaf:
            trees.setdefault(leaf[0], []).append((leaf[1], pool_no[name]))
    lines = ["// Generated by tools/bees_config.py. Do not edit. Child-id pools: every pool owns its atoms.",
             "module bees_ids;", "use bees_atoms;", "",
             "export pool_count/0;", "export pool_size/1;", "export id_of/2;"]
    for name, _, _ in pools:
        lines.append(f"export pool_{name}/0;")
    for t in sorted(trees):
        lines.append(f"export leaf_{t}/1;")
    lines.append("")
    for name, _, _ in pools:
        lines.append(f"fn pool_{name}() -> int64 {{ {pool_no[name]} }}")
    lines.append(f"fn pool_count() -> int64 {{ {len(pools)} }}")
    lines.append("")
    for t in sorted(trees):
        emit_switch(lines, f"leaf_{t}", [("j", "int64")], "j", "int64", [(j, str(p)) for j, p in sorted(trees[t])], "-1")
    emit_switch(lines, "pool_size", [("pool", "int64")], "pool", "int64",
                [(pool_no[n], str(c)) for n, c, _ in pools], "0")
    emit_switch(lines, "pool_base", [("pool", "int64")], "pool", "int64",
                [(pool_no[n], str(base[n])) for n, _, _ in pools], "0")
    flat = [(base[n] + i, f"bees_atoms@a_{n}_{i}()") for n, c, _ in pools for i in range(c)]
    emit_switch(lines, "flat_id", [("k", "int64")], "k", "atom", flat, "bees_atoms@a_id_pool_exhausted()")
    lines.append("fn id_of(pool: int64, i: int64) -> atom {")
    lines.append("    case i < 0 of { true -> bees_atoms@a_id_pool_exhausted(); false ->")
    lines.append("    case i >= pool_size(pool) of { true -> bees_atoms@a_id_pool_exhausted(); false -> flat_id(pool_base(pool) + i) } }")
    lines += ["}", ""]
    with open(os.path.join(out_dir, "bees_ids.silica"), "w") as out:
        out.write("\n".join(lines))
    return 0


def gen_wire(out_dir, manifests):
    """The wire codec units from the .wire manifests among `manifests` (none: only the tables)."""
    import bees_wire_gen
    try:
        bees_wire_gen.generate_wire(out_dir, [p for p in manifests if p.endswith(".wire")])
    except bees_wire_gen.WireError as e:
        print("bees_config: " + str(e), file=sys.stderr)
        return 1
    return 0


def generate(out_dir, manifests):
    try:
        atoms, modules, pools = collect(manifests)
    except ManifestError as e:
        print("bees_config: " + str(e), file=sys.stderr)
        return 1
    # the wire manifests are read first so that a bad message type stops the build before anything is written
    if any(p.endswith(".wire") for p in manifests):
        import bees_wire_gen
        try:
            bees_wire_gen.collect([p for p in manifests if p.endswith(".wire")], warn=False)
        except bees_wire_gen.WireError as e:
            print("bees_config: " + str(e), file=sys.stderr)
            return 1
    rc = write_atoms(out_dir, atoms)
    if rc == 0 and modules:
        rc = gen_modules(out_dir, atoms, modules)
    if rc == 0 and pools:
        rc = gen_ids(out_dir, atoms, pools)
    if rc == 0 and any(p.endswith(".wire") for p in manifests):
        rc = gen_wire(out_dir, manifests)
    return rc


def strip_comments_and_strings(src):
    src = re.sub(r"//[^\n]*", "", src)
    src = re.sub(r'"(?:\\.|[^"\\])*"', '""', src)
    src = re.sub(r"'(?:\\.|[^'\\])'", "''", src)
    return src


def check(units):
    rc = 0
    for u in units:
        if os.path.basename(u) == "bees_atoms.silica":
            continue
        with open(u) as fh:
            src = strip_comments_and_strings(fh.read())
        for lineno, line in enumerate(src.split("\n"), 1):
            for m in ATOM_RE.finditer(line):
                if m.group(1) not in FIXED_ATOMS:
                    print(f"{u}:{lineno}: BEAM atom literal :{m.group(1)} outside bees_atoms (D30)")
                    rc = 1
    return rc


def main(argv):
    if len(argv) >= 4 and argv[1] == "atoms" and argv[2] == "-o":
        try:
            return gen_atoms(argv[3], argv[4:])
        except ManifestError as e:
            print("bees_config: " + str(e), file=sys.stderr)
            return 1
    if len(argv) >= 4 and argv[1] == "generate" and argv[2] == "-o":
        os.makedirs(argv[3], exist_ok=True)
        return generate(argv[3], argv[4:])
    if len(argv) >= 4 and argv[1] == "wire" and argv[2] == "-o":
        return gen_wire(argv[3], argv[4:])
    if len(argv) >= 3 and argv[1] == "check":
        return check(argv[2:])
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
