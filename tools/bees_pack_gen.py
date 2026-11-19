#!/usr/bin/env python3
"""bees_pack_gen: writes the Silica side of the configuration store (D46, D47; spikes/N0d-store-config.md) from the record
table of tools/bees_pack.py, so the packer and the reader cannot drift apart.

    bees_pack_gen.py write [DIR]     write the units into DIR (default: src/config)
    bees_pack_gen.py check [DIR]     exit 1 when a unit in DIR is not what this generator writes
    bees_pack_gen.py root TEMPLATE MODE OUT   an application root from a template: @MODE@, @CFG@ (the configuration type)
                                     and @ERR@ (the reason type) are replaced; OUT is left alone when already current

For each mode (beam, trust) it writes, into src/config/:

    bees_cfg_MODE.silica                  PLAIN unit. fresh/0, take/3, finish/1, show/1: decode each record with
                                          decode((:etf), ...) under the literal ceiling of D47, check every field's bounds
                                          again (a stale or hand-made store), collect the groups, and answer
                                          (:ok, cfg) | (:error, reason). show/1 prints the sanitized summary (no secret).
    dangerous_bees_cfg_MODE_store.silica  the reader actor: owns the application's (:store) carrier for the replay
                                          (:open, :log, :read, :rx under one-at-a-time credit, :close) and sends the
                                          application (:ok, cfg) or (:error, reason). dangerous_ because it holds the
                                          carrier's dangerous_actor_ref (E4026).
    bees_cfg_MODE.shapes                  the types an application must spell (Silica has no type alias).

The units are source an application lists in its silica.config (through links in its directory); nothing is compiled
ahead. Every decode carries the one literal ceiling 4294967295 (D47); the frame cap is a run-time argument of
wireframe@unframe, and every string's length is checked against the table after decode.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bees_pack as P      # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FRAME_CAP = 1048576      # the most one configuration frame may be (run-time cap of wireframe@unframe; BEES's bound)
ERR = "{ record: int64, schema: int64, text: string }"
RX = "{ mode: atom, expected: int64, pending: string }"


def ty(fields):
    parts = []
    for f in fields:
        k = f[1]
        t = {"int": "int64", "str": "string", "secret": "string", "bool": "boolean"}.get(k)
        if k == "rec":
            t = ty(f[4])
        elif k == "list":
            t = f"List[{ty(f[4])}, mem(normal)]"
        parts.append(f"{f[0]}: {t}")
    return "{ " + ", ".join(parts) + " }"


def depth(fields):
    d = 1
    for f in fields:
        if f[1] == "rec":
            d = max(d, depth(f[4]))
        elif f[1] == "list":
            d = max(d, 1 + depth(f[4]))
    return 1 + d


class Unit:
    def __init__(self, mode):
        self.mode = mode
        self.groups = P.GROUPS[mode]
        self.body = [g for g in self.groups if g[0] != "index"]
        self.once = [g for g in self.body if g[2] == "once"]
        self.many = [g for g in self.body if g[2] == "many"]
        self.out = []
        self.lists = {}         # element type text -> helper suffix (one empty/reverse/check family per list element type)

    # the configuration value: one field per group, a list for a repeated group
    def cfg_fields(self):
        fs = []
        for name, _, many, fields in self.body:
            fs.append((name + "s", "list", 0, 0, fields) if many == "many" else (name, "rec", 0, 0, fields))
        return sorted(fs, key=lambda f: f[0])

    def cfg(self):
        return ty(self.cfg_fields())

    def acc(self):
        return f"{{ cfg: {self.cfg()}, err: {ERR}, got: int64, seen: int64, want: int64 }}"

    def w(self, text=""):
        self.out.append(text)

    # ---- blank values (a list field is bound in a sequence, since an empty list is made by empty[T, S]()) ----
    def blank_expr(self, fields, binds):
        parts = []
        for f in fields:
            k = f[1]
            if k == "int":
                v = "0"
            elif k in ("str", "secret"):
                v = '""'
            elif k == "bool":
                v = "false"
            elif k == "rec":
                v = self.blank_expr(f[4], binds)
            else:
                v = f"l{len(binds)}"
                binds.append((v, ty(f[4])))
            parts.append(f"{f[0]}: {v}")
        return "{ " + ", ".join(parts) + " }"

    def blank_fn(self, name, fields):
        binds = []
        expr = self.blank_expr(fields, binds)
        self.w(f"fn {name}() -> {ty(fields)} {{")
        if binds:
            self.w("    sequence proc[mem(normal)]")
            for i, (v, t) in enumerate(binds):
                self.w(f"        {v}: List[{t}, mem(normal)] <- empty[{t}, mem(normal)](){';' if i < len(binds) - 1 else ''}")
            self.w(f"    produces pure {expr} end")
        else:
            self.w(f"    {expr}")
        self.w("}")

    # ---- bounds: "" or PATH: MESSAGE ----
    def why_chain(self, path, var, fields, checks):
        for f in fields:
            name, k, lo, hi = f[:4]
            p, v = f"{path}.{name}", f"{var}.{name}"
            if k == "int":
                lo_text = f"0 - {-lo}" if lo < 0 else str(lo)
                checks.append((f"{v} < {lo_text} or {v} > {hi}", f"{p}: outside {lo}..{hi}"))
            elif k in ("str", "secret"):
                cond = f"length_bytes({v}) > {hi}" if lo == 0 else f"length_bytes({v}) < {lo} or length_bytes({v}) > {hi}"
                checks.append((cond, f"{p}: length outside {lo}..{hi}"))
            elif k == "rec":
                self.why_chain(p, v, f[4], checks)
            elif k == "list":
                helper = self.list_why(p, f)
                checks.append((f"length_bytes({helper}({v}, 0)) > 0", None, f"{helper}({v}, 0)"))

    def list_why(self, path, f):
        """a function over a list field: the first complaint of its elements, or the length complaint"""
        t = ty(f[4])
        name = "why_" + path.replace(".", "_").replace("[]", "")
        checks = []
        self.why_chain(path + "[]", "h", f[4], checks)
        self.w(f"fn {name}(xs: List[{t}, mem(normal)], n: int64) -> string {{")
        self.w("    case xs of {")
        self.w(f"        []: List[{t}, mem(normal)] -> \"\";")
        self.w(f"        [h: {t}, rest: List[{t}, mem(normal)]] -> case n >= {f[3]} of {{")
        self.w(f"            true -> \"{path}: more than {f[3]} entries\";")
        self.w(f"            false -> case length_bytes({name}_one(h)) > 0 of {{ true -> {name}_one(h); false -> {name}(rest, n + 1) }}")
        self.w("        }")
        self.w("    }")
        self.w("}")
        self.w(f"fn {name}_one(h: {t}) -> string {{")
        self.w("    " + self.nest(checks))
        self.w("}")
        return name

    @staticmethod
    def nest(checks):
        text, tail = "", ""
        for c in checks:
            answer = f'"{c[1]}"' if c[1] is not None else c[2]
            text += f"case {c[0]} of {{ true -> {answer}; false -> "
            tail += " }"
        return text + '""' + tail

    def group_fns(self, g):
        name, schema, many, fields = g
        t = ty(fields)
        self.w(f"// ---- {name} (schema {schema}, {many}) ----")
        self.blank_fn(f"blank_{name}", fields)
        self.w(f"fn got_{name}(r: (:ok, {t}) | (:rejected, atom)) -> {{ ok: boolean, v: {t} }} {{")
        self.w("    case r of {")
        self.w(f"        (:ok, v: {t}) -> {{ ok: true, v: v }};")
        self.w(f"        (:rejected, _w: atom) -> {{ ok: false, v: blank_{name}() }}")
        self.w("    }")
        self.w("}")
        self.w(f"fn dec_{name}(e: string) -> {{ ok: boolean, v: {t} }} {{")
        self.w("    sequence proc[mem(normal), transport]")
        self.w(f"        r: (:ok, {t}) | (:rejected, atom) <- decode((:etf), e, {{ max_bytes: {P.CEILING}, max_depth: {depth(fields)}, max_length: {P.CEILING} }})")
        self.w(f"    produces pure got_{name}(r) end")
        self.w("}")
        checks = []
        self.why_chain(f"{self.mode}.{name}" if name not in ("index", "node") else name, "v", fields, checks)
        for m, group, low, high in P.CROSS:
            if m == self.mode and group == name:
                checks.append((f"v.{low} > v.{high}", f"{self.mode}.{name}.{low}: above {high}"))
        self.w(f"fn why_{name}(v: {t}) -> string {{")
        self.w("    " + self.nest(checks))
        self.w("}")

    def cfg_with(self, name, value):
        return "{ " + ", ".join(f"{f[0]}: {value if f[0] == name else 'a.cfg.' + f[0]}" for f in self.cfg_fields()) + " }"

    def plain(self):
        mode, acc, cfg = self.mode, self.acc(), self.cfg()
        self.w(f"// GENERATED by tools/bees_pack_gen.py from the record table of tools/bees_pack.py. Do not edit: edit the table.")
        self.w(f"//")
        self.w(f"// The {mode}-mode configuration as the application reads it from its (:store) carrier (D46). A PLAIN unit: no actor,")
        self.w(f"// no foreign call. The reader actor (dangerous_bees_cfg_{mode}_store) feeds take/3 one stored frame at a time and")
        self.w(f"// sends finish/1's answer to the application; an application that gets its frames another way may call these itself.")
        self.w(f"//")
        self.w(f"//   fresh()                  the empty collection")
        self.w(f"//   take(acc, schema, etf)   one stored frame: its schema number (wireframe@unrecord) and its (:etf) bytes")
        self.w(f"//   finish(acc)              (:ok, cfg) | (:error, {{ record, schema, text }}): text is PATH: MESSAGE, record the")
        self.w(f"//                            frame's number in the store (0 is the index), schema its record kind")
        self.w(f"//   show(cfg)                prints the sanitized summary, one `path = value` line per value; a secret is never")
        self.w(f"//                            printed (its line says so)")
        self.w(f"//   frame_cap()              the most one configuration frame may be: the run-time cap the reader gives")
        self.w(f"//                            wireframe@unframe (D47: every decode below carries the one literal ceiling")
        self.w(f"//                            {P.CEILING}; the cap and the per-field bounds are what limit a frame)")
        self.w(f"//")
        self.w(f"// Every decode re-creates its value from untrusted bytes (transport design 6.8.3); every field is then checked")
        self.w(f"// against the bounds of the table again. The record shapes are in bees_cfg_{mode}.shapes. Secrets (marked in the")
        self.w(f"// table) are carried in the value and nowhere else: this unit keeps nothing and prints none.")
        self.w("use wire_etf;")
        self.w()
        self.w("export fresh/0;")
        self.w("export take/3;")
        self.w("export finish/1;")
        self.w("export show/1;")
        self.w("export frame_cap/0;")
        self.w()
        self.w(f"fn frame_cap() -> int64 {{ {CONFIG_FRAME_CAP} }}")
        self.w()
        for g in self.groups:
            self.group_fns(g)
            self.w()
        # the list helpers of the repeated groups
        for name, _, _, fields in self.many:
            t = ty(fields)
            self.w(f"fn push_{name}(x: {t}, xs: List[{t}, mem(normal)]) -> List[{t}, mem(normal)] {{")
            self.w("    sequence proc[mem(normal)]")
            self.w(f"        out: List[{t}, mem(normal)] <- prepend[{t}, mem(normal)](x, xs)")
            self.w("    produces pure out end")
            self.w("}")
            self.w(f"fn none_{name}() -> List[{t}, mem(normal)] {{")
            self.w("    sequence proc[mem(normal)]")
            self.w(f"        out: List[{t}, mem(normal)] <- empty[{t}, mem(normal)]()")
            self.w("    produces pure out end")
            self.w("}")
            self.w(f"fn rev_{name}(xs: List[{t}, mem(normal)], acc: List[{t}, mem(normal)]) -> List[{t}, mem(normal)] {{")
            self.w("    case xs of {")
            self.w(f"        []: List[{t}, mem(normal)] -> acc;")
            self.w(f"        [h: {t}, rest: List[{t}, mem(normal)]] -> rev_{name}(rest, push_{name}(h, acc))")
            self.w("    }")
            self.w("}")
        self.w()
        blank_cfg = "{ " + ", ".join(f"{f[0]}: " + (f"none_{f[0][:-1]}()" if f[1] == "list" else f"blank_{f[0]}()") for f in self.cfg_fields()) + " }"
        self.w(f"fn fresh() -> {acc} {{")
        self.w(f"    {{ cfg: {blank_cfg}, err: {{ record: 0, schema: 0, text: \"\" }}, got: 0, seen: 0, want: 0 }}")
        self.w("}")
        self.w(f"fn failed(a: {acc}, schema: int64, text: string) -> {acc} {{")
        self.w("    { cfg: a.cfg, err: { record: a.seen, schema: schema, text: text }, got: a.got, seen: a.seen, want: a.want }")
        self.w("}")
        self.w("fn has(got: int64, bit: int64) -> boolean { (got / bit) % 2 == 1 }")
        self.w()
        # the index
        it = ty(P.INDEX[3])
        self.w(f"fn take_index(a: {acc}, schema: int64, d: {{ ok: boolean, v: {it} }}) -> {acc} {{")
        self.w("    case schema == 1 and d.ok of {")
        self.w("        false -> failed(a, schema, \"index: the first record is not the index of a bees.config store\");")
        self.w("        true -> case length_bytes(why_index(d.v)) > 0 of {")
        self.w("            true -> failed(a, 1, why_index(d.v));")
        self.w(f"            false -> case d.v.kind == \"{P.FORMAT_KIND}\" of {{")
        self.w("                false -> failed(a, 1, \"index.kind: not a bees.config store\");")
        self.w(f"                true -> case d.v.mode == \"{mode}\" of {{")
        self.w(f"                    false -> failed(a, 1, \"index.mode: the store is not for a {mode}-mode node\");")
        self.w("                    true -> { cfg: a.cfg, err: a.err, got: a.got, seen: 1, want: d.v.frames }")
        self.w("                }")
        self.w("            }")
        self.w("        }")
        self.w("    }")
        self.w("}")
        bit = 1
        self.bits = {}
        for name, schema, many, fields in self.body:
            t = ty(fields)
            path = name if name == "node" else f"{mode}.{name}"
            self.w(f"fn take_{name}(a: {acc}, d: {{ ok: boolean, v: {t} }}) -> {acc} {{")
            self.w("    case d.ok of {")
            self.w(f"        false -> failed(a, {schema}, \"{path}: the record does not decode as its kind\");")
            self.w(f"        true -> case length_bytes(why_{name}(d.v)) > 0 of {{")
            self.w(f"            true -> failed(a, {schema}, why_{name}(d.v));")
            if many == "once":
                self.bits[name] = bit
                self.w(f"            false -> case has(a.got, {bit}) of {{")
                self.w(f"                true -> failed(a, {schema}, \"{path}: given twice\");")
                self.w(f"                false -> {{ cfg: {self.cfg_with(name, 'd.v')}, err: a.err, got: a.got + {bit}, seen: a.seen + 1, want: a.want }}")
                self.w("            }")
                bit *= 2
            else:
                self.w(f"            false -> {{ cfg: {self.cfg_with(name + 's', f'push_{name}(d.v, a.cfg.{name}s)')}, err: a.err, got: a.got, seen: a.seen + 1, want: a.want }}")
            self.w("        }")
            self.w("    }")
            self.w("}")
        self.w()
        self.w(f"fn take(a: {acc}, schema: int64, e: string) -> {acc} {{")
        self.w("    case length_bytes(a.err.text) > 0 of {")
        self.w("        true -> a;")
        self.w("        false -> case a.seen == 0 of {")
        self.w("            true -> take_index(a, schema, dec_index(e));")
        self.w("            false -> case schema of {")
        for name, schema, _, _ in self.body:
            self.w(f"                {schema} -> take_{name}(a, dec_{name}(e));")
        self.w(f"                _: int64 -> failed(a, schema, \"a record kind that is not one of a {mode}-mode store\")")
        self.w("            }")
        self.w("        }")
        self.w("    }")
        self.w("}")
        self.w()
        missing = []
        for name, _, _, _ in self.once:
            path = name if name == "node" else f"{mode}.{name}"
            missing.append((f"has(a.got, {self.bits[name]})", f"{path}: missing"))
        chain, tail = "", ""
        for cond, text in missing:
            chain += f"case {cond} of {{ false -> \"{text}\"; true -> "
            tail += " }"
        self.w(f"fn lacks(a: {acc}) -> string {{")
        self.w("    case a.seen == 0 of {")
        self.w("        true -> \"(store): no configuration (the store holds no readable record: it is empty, or damaged at its start)\";")
        self.w("        false -> case a.seen != a.want of {")
        self.w("            true -> \"(store): fewer records than the index states (a truncated or damaged store)\";")
        self.w(f"            false -> {chain}\"\"{tail}")
        self.w("        }")
        self.w("    }")
        self.w("}")
        ordered = "{ " + ", ".join(f"{f[0]}: " + (f"rev_{f[0][:-1]}(a.cfg.{f[0]}, none_{f[0][:-1]}())" if f[1] == "list" else f"a.cfg.{f[0]}") for f in self.cfg_fields()) + " }"
        self.w(f"fn finish(a: {acc}) -> (:ok, {cfg}) | (:error, {ERR}) {{")
        self.w("    case length_bytes(a.err.text) > 0 of {")
        self.w("        true -> (:error, a.err);")
        self.w("        false -> case length_bytes(lacks(a)) > 0 of {")
        self.w("            true -> (:error, { record: a.seen, schema: 0, text: lacks(a) });")
        self.w(f"            false -> (:ok, {ordered})")
        self.w("        }")
        self.w("    }")
        self.w("}")
        self.w()
        self.show_fns()
        return "\n".join(self.out) + "\n"

    # ---- the sanitized summary ----
    def show_lines(self, path, var, fields, lines):
        for f in fields:
            name, k = f[0], f[1]
            p, v = f"{path}.{name}", f"{var}.{name}"
            if k == "int":
                lines.append(f'_: atom <- say_n("{p} = ", {v})')
            elif k == "str":
                if f[3] > 512:
                    lines.append(f'_: atom <- say_len("{p} = ", {v})')
                else:
                    lines.append(f'_: atom <- say_s("{p} = ", {v})')
            elif k == "secret":
                lines.append(f'_: atom <- say_secret("{p} = ", {v})')
            elif k == "bool":
                lines.append(f'_: atom <- say_b("{p} = ", {v})')
            elif k == "rec":
                self.show_lines(p, v, f[4], lines)
            else:
                helper = "show_" + p.replace(".", "_").replace("[]", "")
                self.show_list(helper, p, f)
                lines.append(f"_: atom <- {helper}({v})")

    def show_list(self, helper, path, f):
        t = ty(f[4])
        lines = []
        self.show_lines(path + "[]", "h", f[4], lines)
        self.pending.append((helper, t, lines))

    def emit_seq(self, lines):
        self.w("    sequence proc[device_io]")
        for ln in lines:
            self.w(f"        {ln};")
        self.w("        o: atom <- print(\"\")")
        self.w("    produces pure o end")

    def show_fns(self):
        self.w("// ---- the sanitized summary (bees-config-file.md section 4 rule 11): every value except the secrets ----")
        for fn, body in (("say_n(label: string, n: int64)", ["_: atom <- print(label)", "_: atom <- print_int64(n)"]),
                         ("say_s(label: string, s: string)", ["_: atom <- print(label)", '_: atom <- print("\\"")', "_: atom <- print(s)", '_: atom <- print("\\"")']),
                         ("say_len(label: string, s: string)", ["_: atom <- print(label)", '_: atom <- print("(")', "_: atom <- print_int64(length_bytes(s))", '_: atom <- print(" bytes)")']),
                         ("say_secret(label: string, s: string)", ["_: atom <- print(label)", '_: atom <- print(case length_bytes(s) > 0 of { true -> "(secret, not shown)"; false -> "(none)" })']),
                         ("say_b(label: string, b: boolean)", ["_: atom <- print(label)", '_: atom <- print(case b of { true -> "true"; false -> "false" })'])):
            self.w(f"fn {fn} -> atom {{")
            self.w("    sequence proc[device_io]")
            for ln in body:
                self.w(f"        {ln};")
            self.w('        o: atom <- println("")')
            self.w("    produces pure o end")
            self.w("}")
        self.pending = []
        top = []
        for f in self.cfg_fields():
            name = f[0]
            if f[1] == "list":
                group = name[:-1]
                helper = f"show_{group}s"
                lines = []
                self.show_lines(f"{self.mode}.{group}[]", "h", f[4], lines)
                self.pending.append((helper, ty(f[4]), lines))
                top.append(f"_: atom <- {helper}(c.{name})")
            else:
                path = name if name == "node" else f"{self.mode}.{name}"
                lines = []
                self.show_lines(path, "v", f[4], lines)
                self.w(f"fn show_{name}(v: {ty(f[4])}) -> atom {{")
                self.emit_seq(lines)
                self.w("}")
                top.append(f"_: atom <- show_{name}(c.{name})")
        while self.pending:
            helper, t, lines = self.pending.pop(0)
            self.w(f"fn {helper}_one(h: {t}) -> atom {{")
            self.emit_seq(lines)
            self.w("}")
            self.w(f"fn {helper}(xs: List[{t}, mem(normal)]) -> atom {{")
            self.w("    case xs of {")
            self.w(f"        []: List[{t}, mem(normal)] -> :ok;")
            self.w(f"        [h: {t}, rest: List[{t}, mem(normal)]] -> {{ _: atom <- {helper}_one(h); {helper}(rest) }}")
            self.w("    }")
            self.w("}")
        self.w(f"fn show(c: {self.cfg()}) -> atom {{")
        self.emit_seq(top)
        self.w("}")

    # ---- the reader actor ----
    def reader(self):
        mode, acc, cfg = self.mode, self.acc(), self.cfg()
        st = f"{{ acc: {acc}, car: dangerous_actor_ref, rx: {RX}, to: actor_ref, why: string }}"
        msg = ("(:link_up, string) | (:log, int64, int64, int64) | (:tx_credit, int64) | (:synced, int64) | (:rx, string) | (:rx_end, int64) | "
               "(:tx_failed, atom) | (:read_failed, atom) | (:link_down, atom)")
        o = []

        def w(text=""):
            o.append(text)
        w(f"// GENERATED by tools/bees_pack_gen.py from the record table of tools/bees_pack.py. Do not edit: edit the table.")
        w(f"//")
        w(f"// The reader of a {mode}-mode node's configuration store (D46). The application declares the store in its own root unit")
        w(f"//     carried_on config: (:store) (:backing, \"<path>.sildat\", <capacity>, :stop);")
        w(f"// (path and capacity are its literals), starts the carrier and this actor, and opens the carrier with this actor as owner:")
        w(f"//     car: dangerous_actor_ref <- spawn_dangerous_carrier(config, stack_policy(0, :keep_last_message), state_policy(:keep_state_area));")
        w(f"//     rd: actor_ref <- spawn({{ acc: bees_cfg_{mode}@fresh(), car: car, rx: wireframe@fresh(:storage), to: me, why: \"\" }},")
        w(f"//                            dangerous_bees_cfg_{mode}_store@reader, stack_policy(0, :keep_last_message), state_policy(:keep_state_area));")
        w(f"//     _: boolean <- cast(car, (:open, rd, \"\") impl ActorMessage {{}})")
        w(f"// The actor replays the log from record 0 with one receive credit at a time, gives every stored frame to")
        w(f"// bees_cfg_{mode}@take, closes the carrier, and sends `to` exactly one message when the carrier has reported")
        w(f"// (:link_down, :closed): (:ok, cfg) or (:error, {{ record, schema, text }}). It never starts a node and never ends the")
        w(f"// program: the application decides. What the carrier can answer, and what the application is told:")
        w(f"//   a missing backing is created empty by the carrier   (:error, text \"(store): no configuration ...\")")
        w(f"//   a backing of another size, (:link_down, :mismatch)   (:error, text \"(store): the backing is not the declared capacity\")")
        w(f"//   a backing another owner holds, :in_use; a medium failure, :medium                    (:error, ...)")
        w(f"//   a record that fails its check, (:read_failed, :corrupt)                               (:error, ...)")
        w(f"//   a log that does not start at record 0 (a damaged first block: the carrier drops the block without a report)  (:error, ...)")
        w(f"// After its one message the actor holds the empty collection again: no configuration value, and so no secret, stays in it.")
        w("use carrier;")
        w("use wireframe;")
        w(f"use bees_cfg_{mode};")
        w(f"module dangerous_bees_cfg_{mode}_store;")
        w()
        w("export reader/2;")
        w()
        w("fn ask(car: dangerous_actor_ref, what: int64, n: int64) -> boolean {")
        w("    sequence proc[concurrency]")
        w("        r: boolean <- case what of {")
        w("            1 -> cast(car, (:read, n) impl ActorMessage {});")
        w("            2 -> cast(car, (:credit, n) impl ActorMessage {});")
        w("            _: int64 -> cast(car, :close impl ActorMessage {})")
        w("        }")
        w("    produces pure r end")
        w("}")
        w(f"fn told(to: actor_ref, r: (:ok, {cfg}) | (:error, {ERR})) -> boolean {{")
        w("    sequence proc[concurrency]")
        w("        ok: boolean <- cast(to, r impl ActorMessage {})")
        w("    produces pure ok end")
        w("}")
        w(f"fn problem(why: string) -> (:ok, {cfg}) | (:error, {ERR}) {{")
        w("    (:error, { record: 0, schema: 0, text: why })")
        w("}")
        w(f"fn with_why(st: {st}, why: string) -> {st} {{")
        w("    { acc: st.acc, car: st.car, rx: st.rx, to: st.to, why: case length_bytes(st.why) > 0 of { true -> st.why; false -> why } }")
        w("}")
        w("fn down_text(why: atom) -> string {")
        w("    case why == :mismatch of {")
        w("        true -> \"(store): the backing is not the declared capacity (:mismatch)\";")
        w("        false -> case why == :in_use of {")
        w("            true -> \"(store): the backing is held by another owner (:in_use)\";")
        w("            false -> case why == :medium of {")
        w("                true -> \"(store): the backing could not be opened or read (:medium)\";")
        w("                false -> \"(store): the carrier ended before the configuration was read\"")
        w("            }")
        w("        }")
        w("    }")
        w("}")
        w("fn read_text(why: atom) -> string {")
        w("    case why == :corrupt of {")
        w("        true -> \"(store): a record failed its check (:corrupt)\";")
        w("        false -> \"(store): the replay failed\"")
        w("    }")
        w("}")
        w(f"fn on_log(oldest: int64, st: {st}) -> (:no_reply, {st}) {{")
        w("    case oldest == 0 of {")
        w("        true -> { _: boolean <- ask(st.car, 1, 0); _: boolean <- ask(st.car, 2, 1); (:no_reply, st) };")
        w("        false -> { _: boolean <- ask(st.car, 3, 0); (:no_reply, with_why(st, \"(store): the log does not start at record 0 (a damaged first block)\")) }")
        w("    }")
        w("}")
        w(f"fn on_frame(f: string, rx: {RX}, st: {st}) -> {st} {{")
        w("    u: (:ok, atom, int64, string) | (:rejected, atom) <- wireframe@unrecord(f);")
        w("    case u of {")
        w("        (:ok, fmt: atom, schema: int64, e: string) -> case fmt == :etf of {")
        w(f"            true -> {{ acc: bees_cfg_{mode}@take(st.acc, schema, e), car: st.car, rx: rx, to: st.to, why: st.why }};")
        w("            false -> with_why({ acc: st.acc, car: st.car, rx: rx, to: st.to, why: st.why }, \"(store): a record that is not (:etf)\")")
        w("        };")
        w("        (:rejected, _w: atom) -> with_why({ acc: st.acc, car: st.car, rx: rx, to: st.to, why: st.why }, \"(store): a record without a format header\")")
        w("    }")
        w("}")
        w(f"fn on_rx(s: string, st: {st}) -> (:no_reply, {st}) {{")
        w("    _: boolean <- ask(st.car, 2, 1);")
        w(f"    u: (:more, {RX}) | (:frame, string, {RX}) | (:rejected, atom) <- wireframe@unframe(st.rx, s, bees_cfg_{mode}@frame_cap());")
        w("    case u of {")
        w(f"        (:more, rx: {RX}) -> (:no_reply, {{ acc: st.acc, car: st.car, rx: rx, to: st.to, why: st.why }});")
        w(f"        (:frame, f: string, rx: {RX}) -> (:no_reply, on_frame(f, rx, st));")
        w("        (:rejected, _w: atom) -> (:no_reply, with_why({ acc: st.acc, car: st.car, rx: wireframe@fresh(:storage), to: st.to, why: st.why }, \"(store): a frame above the configuration frame cap, or a record too short\"))")
        w("    }")
        w("}")
        w(f"fn answer(st: {st}) -> (:ok, {cfg}) | (:error, {ERR}) {{")
        w("    case length_bytes(st.why) > 0 of {")
        w("        true -> problem(st.why);")
        w(f"        false -> bees_cfg_{mode}@finish(st.acc)")
        w("    }")
        w("}")
        w(f"fn on_down(why: atom, st: {st}) -> (:no_reply, {st}) {{")
        w("    case why == :closed of {")
        w("        true -> {")
        w("            _: boolean <- told(st.to, answer(st));")
        w(f"            (:no_reply, {{ acc: bees_cfg_{mode}@fresh(), car: st.car, rx: wireframe@fresh(:storage), to: st.to, why: \"\" }})")
        w("        };")
        w("        false -> { _: boolean <- ask(st.car, 3, 0); (:no_reply, with_why(st, down_text(why))) }")
        w("    }")
        w("}")
        w(f"fn reader(msg: {msg}, st: {st}) -> (:no_reply, {st}) {{")
        w("    case msg of {")
        w("        (:link_up, _i: string) -> (:no_reply, st);")
        w("        (:log, oldest: int64, _n: int64, _c: int64) -> on_log(oldest, st);")
        w("        (:tx_credit, _n: int64) -> (:no_reply, st);")
        w("        (:synced, _n: int64) -> (:no_reply, st);")
        w("        (:rx, s: string) -> on_rx(s, st);")
        w("        (:rx_end, _n: int64) -> { _: boolean <- ask(st.car, 3, 0); (:no_reply, st) };")
        w("        (:tx_failed, _w: atom) -> (:no_reply, st);")
        w("        (:read_failed, why: atom) -> { _: boolean <- ask(st.car, 3, 0); (:no_reply, with_why(st, read_text(why))) };")
        w("        (:link_down, why: atom) -> on_down(why, st)")
        w("    }")
        w("}")
        return "\n".join(o) + "\n"

    def shapes(self):
        o = [f"The types of a {self.mode}-mode configuration (GENERATED by tools/bees_pack_gen.py; Silica has no type alias, so an", "application spells them).", "",
             "cfg (the value of (:ok, cfg)):", self.cfg(), "", "reason (the value of (:error, reason)):", ERR, "",
             "the reader actor's message to the application:", f"(:ok, {self.cfg()}) | (:error, {ERR})", "", "groups:"]
        for name, schema, many, fields in self.groups:
            o.append(f"{name} (schema {schema}, {many}): {ty(fields)}")
        return "\n".join(o) + "\n"


def files():
    out = {}
    for mode in ("beam", "trust"):
        u = Unit(mode)
        out[f"bees_cfg_{mode}.silica"] = u.plain()
        out[f"dangerous_bees_cfg_{mode}_store.silica"] = Unit(mode).reader()
        out[f"bees_cfg_{mode}.shapes"] = Unit(mode).shapes()
    return out


def main(argv):
    cmd = argv[1] if len(argv) > 1 else ""
    d = argv[2] if len(argv) > 2 else os.path.join(ROOT, "src", "config")
    if cmd == "write":
        os.makedirs(d, exist_ok=True)
        for name, text in files().items():
            with open(os.path.join(d, name), "w", encoding="utf-8") as f:
                f.write(text)
            print(f"wrote {os.path.join(d, name)}")
        return 0
    if cmd == "root" and len(argv) == 5:
        # an application root from a template: @MODE@, @CFG@ and @ERR@ are replaced (the types an application must spell)
        template, mode, out = argv[2], argv[3], argv[4]
        with open(template, encoding="utf-8") as f:
            text = f.read().replace("@MODE@", mode).replace("@CFG@", Unit(mode).cfg()).replace("@ERR@", ERR)
        try:
            with open(out, encoding="utf-8") as f:
                if f.read() == text:
                    return 0
        except OSError:
            pass
        with open(out, "w", encoding="utf-8") as f:
            f.write(text)
        return 0
    if cmd == "check":
        bad = 0
        for name, text in files().items():
            try:
                with open(os.path.join(d, name), encoding="utf-8") as f:
                    same = f.read() == text
            except OSError:
                same = False
            if not same:
                print(f"{os.path.join(d, name)}: not what tools/bees_pack_gen.py writes (run: tools/bees_pack_gen.py write)")
                bad = 1
        return bad
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
