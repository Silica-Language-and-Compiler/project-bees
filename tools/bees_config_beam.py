#!/usr/bin/env python3
"""bees_config_beam: the BEAM-mode half of the bees.config reader (development-plan/bees-config-file.md), and the generator of
the two BEAM-mode units a node program needs (milestone N2).

    bees_config_beam.py check    --config FILE MANIFEST.wire...                       validate only
    bees_config_beam.py generate --config FILE [--beam FILE.beam] -o OUT_DIR MANIFEST.wire...

STATUS (N2, 2026-11-10). The N0.2 reader (`bees_conf`, read at boot) does not exist yet. This file is the beam half of it, written
so that it can be merged with the trust half (built by N3 in parallel) into one reader:

  * The GRAMMAR of section 4 is parsed in full (lists, tuples, atoms, quoted atoms, integers with `_`, strings with the four
    escapes, maps, `%` comments, one term and a full stop, 64 KiB, ASCII only).
  * The top level (`mode`, `node`, `beam`, `trust`), the `node` section and the `beam` section are validated by the rules of
    section 4 (unknown key, duplicate key, type, bounds with no clamping, cross-field rules, required values, files, "not built
    yet", the node name against the manifest). The `trust` section is the trust half's: here it is only required to be a list.
  * It runs at BUILD time, not at boot: the values are written into the generated unit `beam_conf` as constants. That is a
    deviation from section 1 ("values at boot that change no generated code") until the boot-time reader exists; the cookie
    file itself is NOT built in: its path is, and the native edge reads the file at each handshake (checking that it is a
    regular file, not readable by group or others, 1 to 255 bytes of ASCII 32..126).
  * Messages have the form `bees.config:LINE: PATH: MESSAGE`; the exit status is 1 on any violation.

Generated (generate):

  beam_conf.silica   the effective BEAM-mode values: auth_cookie, cookie_path (absolute), creation, epmd_external,
                     epmd_address, io_ms, tick_ms, link_dials, link_peer, link_address, link_by_epmd, link_host,
                     link_peer_short, register_epmd, node_short, frame_max, summary (the sanitized boot summary, rule 11).
  beam_peers.silica  the BEAM-mode proxies (one per `remote` line, registered under the name, encoding with bees_msgs and
                     writing REG_SEND with this node's creation), the reaper, and the table of pids this node hands out.

The `.beam` manifest (build time: it changes generated code, so it is not a bees.config option) has one kind of line:

    pid <remote name> deliver <local name>

The proxy of <remote name> HANDS OUT its pid: its payload on the wire is the tuple {Pid, Value} (Pid a NEW_PID_EXT of this
node: id = the proxy's number, serial 0, this node's creation), so the receiving Erlang process can answer `Pid ! Reply`, link
to it, unlink and monitor it. A SEND (control message 2) to that pid is decoded with <local name>'s declared type and delivered
to <local name>; a LINK to it is accepted and counted. A pid without a `pid` line is not handed out: a SEND to it is dropped and
counted, a LINK to it is answered EXIT noproc.
"""
import os
import re
import stat
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bees_dist_gen as D  # noqa: E402
import bees_wire_gen as W  # noqa: E402

BUILT_FRAME_MAX = 4096          # what the build implements until N1 lifts the codec (section 5.4)
BEAM_FRAME_MAX = 4294967295


class ConfigError(Exception):
    pass


class Atom(str):
    pass


# ---------------------------------------------------------------- the grammar (section 4)
class Parser:
    def __init__(self, text, path):
        self.s, self.i, self.path = text, 0, path

    def line(self, i=None):
        return self.s.count("\n", 0, self.i if i is None else i) + 1

    def err(self, msg, i=None):
        raise ConfigError(f"{os.path.basename(self.path)}:{self.line(i)}: (syntax): {msg}")

    def ws(self):
        while self.i < len(self.s):
            c = self.s[self.i]
            if c in " \t\r\n":
                self.i += 1
            elif c == "%":
                while self.i < len(self.s) and self.s[self.i] != "\n":
                    self.i += 1
            else:
                break

    def peek(self):
        self.ws()
        return self.s[self.i] if self.i < len(self.s) else ""

    def expect(self, c):
        if self.peek() != c:
            self.err(f"expected '{c}'")
        self.i += 1

    def term(self):
        """-> (value, line)"""
        c = self.peek()
        ln = self.line()
        if c == "[":
            self.i += 1
            items = []
            if self.peek() == "]":
                self.i += 1
                return items, ln
            while True:
                items.append(self.term())
                if self.peek() == ",":
                    self.i += 1
                    continue
                self.expect("]")
                return items, ln
        if c == "{":
            self.i += 1
            items = []
            if self.peek() == "}":
                self.i += 1
                return tuple(items), ln
            while True:
                items.append(self.term())
                if self.peek() == ",":
                    self.i += 1
                    continue
                self.expect("}")
                return tuple(items), ln
        if c == "#":
            self.i += 1
            self.expect("{")
            m = []
            if self.peek() == "}":
                self.i += 1
                return ("#map", m), ln
            while True:
                k = self.term()
                self.ws()
                if self.s[self.i:self.i + 2] != "=>":
                    self.err("expected '=>'")
                self.i += 2
                m.append((k, self.term()))
                if self.peek() == ",":
                    self.i += 1
                    continue
                self.expect("}")
                return ("#map", m), ln
        if c == '"':
            self.i += 1
            out = []
            while True:
                if self.i >= len(self.s):
                    self.err("unterminated string")
                ch = self.s[self.i]
                if ch == '"':
                    self.i += 1
                    return "".join(out), ln
                if ch == "\\":
                    nx = self.s[self.i + 1:self.i + 2]
                    if nx not in ('n', 't', '\\', '"'):
                        self.err("only the escapes \\n \\t \\\\ \\\" are accepted")
                    out.append({"n": "\n", "t": "\t", "\\": "\\", '"': '"'}[nx])
                    self.i += 2
                    continue
                if not (32 <= ord(ch) <= 126):
                    self.err("a string holds ASCII 32 to 126 only")
                out.append(ch)
                self.i += 1
        if c == "'":
            self.i += 1
            j = self.s.find("'", self.i)
            if j < 0:
                self.err("unterminated quoted atom")
            a = self.s[self.i:j]
            self.i = j + 1
            return Atom(a), ln
        m = re.compile(r"-?[0-9](?:_?[0-9])*").match(self.s, self.i)
        if m:
            self.i = m.end()
            if self.s[self.i:self.i + 1] in (".",) and self.s[self.i + 1:self.i + 2].isdigit():
                self.err("floats are not accepted")
            return int(m.group(0).replace("_", "")), ln
        m = re.compile(r"[a-z][A-Za-z0-9_@]*").match(self.s, self.i)
        if m:
            self.i = m.end()
            return Atom(m.group(0)), ln
        self.err("not a term (floats, binaries, funs, variables, macros, records are not accepted)" if c else "unexpected end of file")


def parse_file(path):
    with open(path, "rb") as fh:
        raw = fh.read()
    if len(raw) > 65536:
        raise ConfigError(f"{os.path.basename(path)}:1: (file): larger than 64 KiB")
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError:
        raise ConfigError(f"{os.path.basename(path)}:1: (file): a byte outside ASCII")
    p = Parser(text, path)
    v = p.term()
    p.expect(".")
    if p.peek():
        p.err("a second term or trailing text after the full stop")
    return v


# ---------------------------------------------------------------- validation (section 4 rules, sections 5.1, 5.2)
def proplist(v, path, fname, keys):
    """A list of {atom, value} pairs -> {key: (value, line)}; unknown and duplicate keys are errors."""
    val, ln = v
    if not isinstance(val, list):
        raise ConfigError(f"{fname}:{ln}: {path}: expected a list of {{key, value}}")
    out = {}
    for item, iln in val:
        if not (isinstance(item, tuple) and len(item) == 2 and isinstance(item[0][0], Atom)):
            raise ConfigError(f"{fname}:{iln}: {path}: expected {{key, value}}")
        k = str(item[0][0])
        where = f"{path}.{k}" if path else k
        if k not in keys:
            raise ConfigError(f"{fname}:{iln}: {where}: unknown key")
        if k in out:
            raise ConfigError(f"{fname}:{iln}: {where}: duplicate key (first at line {out[k][1]})")
        out[k] = item[1]
    return out


def need_atom(v, where, fname, choices):
    val, ln = v
    if not isinstance(val, Atom) or str(val) not in choices:
        raise ConfigError(f"{fname}:{ln}: {where}: expected one of {', '.join(choices)}")
    return str(val)


def need_int(v, where, fname, lo, hi):
    val, ln = v
    if isinstance(val, bool) or not isinstance(val, int):
        raise ConfigError(f"{fname}:{ln}: {where}: expected an integer")
    if val < lo:
        raise ConfigError(f"{fname}:{ln}: {where}: {val} is below {lo}")
    if val > hi:
        raise ConfigError(f"{fname}:{ln}: {where}: {val} is above {hi}")
    return val


def need_str(v, where, fname):
    val, ln = v
    if not isinstance(val, str) or isinstance(val, Atom):
        raise ConfigError(f"{fname}:{ln}: {where}: expected a string")
    return val


BEAM_KEYS = ["transport", "auth", "cookie_file", "listen_address", "listen_port", "epmd", "epmd_port", "net_ticktime_s",
             "open_timeout_ms", "peers", "spawn", "spawn_allowlist", "frame_size_max"]


def validate(cfg_path, manifest):
    """manifest: bees_dist_gen.parse() of the .wire files. -> dict of effective values."""
    fname = os.path.basename(cfg_path)
    base = os.path.dirname(os.path.abspath(cfg_path))
    top = proplist(parse_file(cfg_path), "", fname, ["mode", "node", "beam", "trust"])
    if "mode" not in top:
        raise ConfigError(f"{fname}:1: mode: absent, so the mode is trust (R3); a BEAM-mode node must write {{mode, beam}}")
    mval, mln = top["mode"]
    if isinstance(mval, list):
        raise ConfigError(f"{fname}:{mln}: mode: the list form is reserved (one mode per node, section 3.1)")
    mode = need_atom(top["mode"], "mode", fname, ["beam", "trust"])
    if "trust" in top and not isinstance(top["trust"][0], list):
        raise ConfigError(f"{fname}:{top['trust'][1]}: trust: expected a list of {{key, value}}")
    if manifest["remotes"] or manifest["locals"]:
        if mode == "trust":
            raise ConfigError(f"{fname}:{mln}: mode: trust, but the manifest has remote/local lines, which exist only for BEAM mode")
    eff = {"mode": mode}
    node = proplist(top.get("node", ([], 1)), "node", fname, ["name", "creation"])
    eff["creation"] = manifest["creation"]
    if "name" in node:
        name = need_str(node["name"], "node.name", fname)
        if name != manifest["node"]:
            raise ConfigError(f"{fname}:{node['name'][1]}: node.name: \"{name}\" differs from the manifest's node {manifest['node']}")
    if "creation" in node:
        cv, cln = node["creation"]
        if isinstance(cv, Atom):
            if cv == "epmd":
                raise ConfigError(f"{fname}:{cln}: node.creation: epmd is not built yet (N2 keeps a fixed creation; the one EPMD assigns is audited)")
            raise ConfigError(f"{fname}:{cln}: node.creation: expected an integer or epmd")
        eff["creation"] = need_int(node["creation"], "node.creation", fname, 0, 4294967295)
    b = proplist(top.get("beam", ([], 1)), "beam", fname, BEAM_KEYS)
    bl = lambda k: b[k][1]  # noqa: E731
    transport = need_atom(b["transport"], "beam.transport", fname, ["tcp", "tls"]) if "transport" in b else "tls"
    if transport == "tls":
        ln = bl("transport") if "transport" in b else 1
        raise ConfigError(f"{fname}:{ln}: beam.transport: tls (the default, D25) is not built yet; write {{transport, tcp}}")
    auth = need_atom(b["auth"], "beam.auth", fname, ["cookie", "none"]) if "auth" in b else "cookie"
    eff["auth"] = auth
    eff["cookie_path"] = ""
    if auth == "cookie":
        if "cookie_file" not in b:
            raise ConfigError(f"{fname}:{bl('auth') if 'auth' in b else 1}: beam.cookie_file: required when auth is cookie")
    if "cookie_file" in b:
        cf = need_str(b["cookie_file"], "beam.cookie_file", fname)
        full = cf if os.path.isabs(cf) else os.path.normpath(os.path.join(base, cf))
        ln = bl("cookie_file")
        if not os.path.exists(full):
            raise ConfigError(f"{fname}:{ln}: beam.cookie_file: {cf} does not exist")
        st = os.stat(full)
        if not stat.S_ISREG(st.st_mode):
            raise ConfigError(f"{fname}:{ln}: beam.cookie_file: {cf} is not a regular file")
        if st.st_mode & 0o077:
            raise ConfigError(f"{fname}:{ln}: beam.cookie_file: {cf} is readable or writable by group or others (mode {st.st_mode & 0o777:o})")
        try:
            content = open(full, "rb").read()
        except OSError as e:
            raise ConfigError(f"{fname}:{ln}: beam.cookie_file: {cf} cannot be read ({e.strerror})")
        if content.endswith(b"\n"):
            content = content[:-1]
        if content.endswith(b"\r"):
            content = content[:-1]
        if not (1 <= len(content) <= 255) or any(c < 32 or c > 126 for c in content):
            raise ConfigError(f"{fname}:{ln}: beam.cookie_file: {cf} must hold 1 to 255 bytes of ASCII 32..126")
        eff["cookie_path"] = full
    if "listen_address" not in b:
        raise ConfigError(f"{fname}:{top['beam'][1] if 'beam' in top else 1}: beam.listen_address: required, no built-in default (R6)")
    la = need_str(b["listen_address"], "beam.listen_address", fname)
    if la != "127.0.0.1":
        raise ConfigError(f"{fname}:{bl('listen_address')}: beam.listen_address: {la} is not built yet (the language's carrier listens on 127.0.0.1; N1)")
    lport = need_int(b["listen_port"], "beam.listen_port", fname, 0, 65535) if "listen_port" in b else None
    epmd = need_atom(b["epmd"], "beam.epmd", fname, ["external", "none"]) if "epmd" in b else "external"
    eport = need_int(b["epmd_port"], "beam.epmd_port", fname, 1, 65535) if "epmd_port" in b else 4369
    o, io_ms, tick_ms = manifest["timing"]
    if "net_ticktime_s" in b:
        t = need_int(b["net_ticktime_s"], "beam.net_ticktime_s", fname, 4, 3600)
        io_ms, tick_ms = t * 1000, t * 1000 // 4
    if "open_timeout_ms" in b:
        need_int(b["open_timeout_ms"], "beam.open_timeout_ms", fname, 1, 60000)
    spawn = need_atom(b["spawn"], "beam.spawn", fname, ["none", "allowlist", "any"]) if "spawn" in b else "none"
    if spawn != "none":
        raise ConfigError(f"{fname}:{bl('spawn')}: beam.spawn: {spawn} is not built yet (remote spawn, B4)")
    if "spawn_allowlist" in b:
        sv, sln = b["spawn_allowlist"]
        if not isinstance(sv, list) or len(sv) > 1024:
            raise ConfigError(f"{fname}:{sln}: beam.spawn_allowlist: expected a list of at most 1024 {{Module, Function, Arity}}")
        for (e, eln) in sv:
            if not (isinstance(e, tuple) and len(e) == 3 and isinstance(e[0][0], Atom) and isinstance(e[1][0], Atom)
                    and isinstance(e[2][0], int) and 0 <= e[2][0] <= 255):
                raise ConfigError(f"{fname}:{eln}: beam.spawn_allowlist: expected {{Module, Function, Arity}}")
    fmax = BUILT_FRAME_MAX
    if "frame_size_max" in b:
        fmax = need_int(b["frame_size_max"], "beam.frame_size_max", fname, 512, BEAM_FRAME_MAX)
        if fmax > BUILT_FRAME_MAX:
            raise ConfigError(f"{fname}:{bl('frame_size_max')}: beam.frame_size_max: {fmax} is not built yet (the build implements {BUILT_FRAME_MAX} until N1; never clamped)")
    # peers: the manifest's names only (D16); each may give host, port (N or epmd) and role
    names = [p[0] for p in manifest["peers"]]
    over = {}
    if "peers" in b:
        pv, pln = b["peers"]
        if not isinstance(pv, list):
            raise ConfigError(f"{fname}:{pln}: beam.peers: expected a list")
        for (e, eln) in pv:
            if not (isinstance(e, tuple) and len(e) == 2 and isinstance(e[0][0], str) and not isinstance(e[0][0], Atom)):
                raise ConfigError(f"{fname}:{eln}: beam.peers: expected {{\"name@host\", [options]}}")
            pname = e[0][0]
            if pname not in names:
                raise ConfigError(f"{fname}:{eln}: beam.peers: {pname} is not a peer of the manifest (D16)")
            if pname in over:
                raise ConfigError(f"{fname}:{eln}: beam.peers: {pname} is listed twice")
            opts = proplist(e[1], f"beam.peers.{pname}", fname, ["host", "port", "role"])
            d = {}
            if "host" in opts:
                h = need_str(opts["host"], f"beam.peers.{pname}.host", fname)
                if h != "127.0.0.1":
                    raise ConfigError(f"{fname}:{opts['host'][1]}: beam.peers.{pname}.host: {h} is not built yet (127.0.0.1 only until N1)")
                d["host"] = h
            if "port" in opts:
                pv2, pl2 = opts["port"]
                if isinstance(pv2, Atom):
                    if pv2 != "epmd":
                        raise ConfigError(f"{fname}:{pl2}: beam.peers.{pname}.port: expected 1..65535 or epmd")
                    d["port"] = "epmd"
                else:
                    d["port"] = need_int(opts["port"], f"beam.peers.{pname}.port", fname, 1, 65535)
            if "role" in opts:
                d["role"] = need_atom(opts["role"], f"beam.peers.{pname}.role", fname, ["dial", "listen"])
            over[pname] = (d, eln)
    # cross-field rules (rule 6)
    if lport == 0 and epmd != "external":
        raise ConfigError(f"{fname}:{bl('listen_port')}: beam.listen_port: 0 needs epmd external")
    if epmd == "none":
        if lport is None or lport == 0:
            raise ConfigError(f"{fname}:{bl('epmd')}: beam.epmd: none needs a non-zero listen_port")
        for pname, (d, eln) in over.items():
            if d.get("port") == "epmd":
                raise ConfigError(f"{fname}:{eln}: beam.peers.{pname}.port: epmd, but beam.epmd is none")
    # the link: the manifest's first peer (M3: one live link per node)
    first = manifest["peers"][0]
    d = over.get(first[0], ({}, 0))[0]
    role = d.get("role", first[3])
    host = d.get("host", first[1])
    port = d.get("port", first[2] if first[3] == "dial" or role == "dial" else None)
    if role == "dial" and port == "epmd" and epmd == "none":
        raise ConfigError(f"{fname}:1: beam.peers.{first[0]}.port: epmd, but beam.epmd is none")
    if role == "listen":
        lp = lport if lport is not None else (first[2] if first[3] == "listen" else 0)
        if lp == 0 and epmd != "external":
            raise ConfigError(f"{fname}:1: beam.listen_port: 0 (ephemeral) needs epmd external")
        address = f"listen:{lp}"
    else:
        address = f"{host}:{port}" if port != "epmd" else ""
    eff.update({
        "epmd": epmd, "epmd_port": eport, "io_ms": io_ms, "tick_ms": tick_ms, "frame_max": fmax,
        "link_dials": role == "dial", "link_peer": 0 if role == "dial" else -1, "link_address": address,
        "link_by_epmd": role == "dial" and port == "epmd", "link_host": host, "link_peer_name": first[0],
        "register_epmd": role == "listen" and epmd == "external", "node": manifest["node"],
    })
    return eff


# ---------------------------------------------------------------- generation
def lit(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def gen_conf(out_dir, eff, cfg_path):
    b = lambda v: "true" if v else "false"  # noqa: E731
    summary = (f"[bees] mode=beam node={eff['node']} transport=tcp auth={eff['auth']} creation={eff['creation']} "
               f"epmd={eff['epmd']} epmd_port={eff['epmd_port']} net_tick io_ms={eff['io_ms']} tick_ms={eff['tick_ms']} "
               f"link={eff['link_peer_name']} role={'dial' if eff['link_dials'] else 'listen'}"
               f"{' via epmd' if eff['link_by_epmd'] else ''} frame_size_max={eff['frame_max']}")
    ln = ["// Generated by tools/bees_config_beam.py from " + os.path.basename(cfg_path) + " and the manifest. Do not edit.",
          "// The effective BEAM-mode values (bees-config-file.md 5.1, 5.2), read at build time until the boot-time reader exists",
          "// (N0.2). The cookie is not here: only its file's path, which the native edge reads at each handshake.",
          "module beam_conf;", ""]
    fns = [
        ("auth_cookie", "boolean", b(eff["auth"] == "cookie")),
        ("cookie_path", "string", lit(eff["cookie_path"])),
        ("creation", "int64", str(eff["creation"])),
        ("epmd_external", "boolean", b(eff["epmd"] == "external")),
        ("epmd_address", "string", lit(f"127.0.0.1:{eff['epmd_port']}")),
        ("io_ms", "uint64", str(eff["io_ms"])),
        ("tick_ms", "uint64", str(eff["tick_ms"])),
        ("link_dials", "boolean", b(eff["link_dials"])),
        ("link_peer", "int64", str(eff["link_peer"])),
        ("link_address", "string", lit(eff["link_address"])),
        ("link_by_epmd", "boolean", b(eff["link_by_epmd"])),
        ("link_host", "string", lit(eff["link_host"])),
        ("link_peer_short", "string", lit(eff["link_peer_name"].split("@", 1)[0])),
        ("register_epmd", "boolean", b(eff["register_epmd"])),
        ("node_short", "string", lit(eff["node"].split("@", 1)[0])),
        ("frame_max", "int64", str(eff["frame_max"])),
        ("summary", "string", lit(summary)),
    ]
    ln += [f"export {n}/0;" for n, _, _ in fns] + [""]
    ln += [f"fn {n}() -> {t} {{ {v} }}" for n, t, v in fns]
    with open(os.path.join(out_dir, "beam_conf.silica"), "w") as out:
        out.write("\n".join(ln) + "\n")


def parse_beam(path, d):
    """-> {remote name: local name} from `pid <remote> deliver <local>` lines."""
    pids = {}
    if not path:
        return pids
    rem = [r[0] for r in d["remotes"]]
    loc = [l[0] for l in d["locals"]]
    with open(path) as fh:
        for n, line in enumerate(fh, 1):
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            t = line.split()
            where = f"{os.path.basename(path)}:{n}"
            if len(t) != 4 or t[0] != "pid" or t[2] != "deliver":
                raise ConfigError(f"{where}: expected: pid <remote name> deliver <local name>")
            if t[1] not in rem:
                raise ConfigError(f"{where}: {t[1]} is not a remote name of the manifest")
            if t[3] not in loc:
                raise ConfigError(f"{where}: {t[3]} is not a local name of the manifest")
            if t[1] in pids:
                raise ConfigError(f"{where}: {t[1]} already hands out its pid")
            pids[t[1]] = t[3]
    return pids


STATE = "{ tx: actor_ref, id: int64 }"
POL = "stack_policy(0, :keep_last_message), state_policy(:keep_state_area)"


def gen_peers(out_dir, d, msgs, pids):
    rems = [r[0] for r in d["remotes"]]
    locs = [l[0] for l in d["locals"]]
    ln = ["// Generated by tools/bees_config_beam.py (BEAM mode, N2). Do not edit. The proxies of this node's remote names, the reaper,",
          "// and the pids this node hands out (the .beam manifest's pid lines). No BEAM atom literal: names come from bees_atoms (D30).",
          "module beam_peers;", "use bees_atoms;", "use bees_msgs;", "use bees_dist;", "use bees_peers;", "use beam_dist;", "use beam_conf;", ""]
    ex = ["start_proxies/1", "pid_local/1", "local_atom/1", "handed_count/0"]
    ln += [f"export {e};" for e in ex] + [""]
    for k, n in enumerate(rems):
        st = W.silica(msgs[n])
        wrap = (f"        p2: string <- beam_dist@with_pid(beam_dist@pid_bytes(bees_peers@node_name(), st.id, beam_conf@creation()), payload);"
                if n in pids else "        p2: string <- payload;")
        ln += [f"fn proxy_{n}(msg: {st}, st: {STATE}) -> (:no_reply, {STATE}) {{",
               "    sequence proc[concurrency]",
               f"        payload: string <- bees_msgs@enc_{n}(msg);",
               wrap,
               f"        body: string <- bees_dist@reg_send_body(p2, st.id, bees_peers@node_name(), beam_conf@creation(), bees_atoms@spelling(bees_atoms@a_{n}()));",
               "        seg: string <- bees_dist@frame4(body);",
               "        _: boolean <- case length_bytes(body) > 0 of { true -> cast(st.tx, (:bees, 0, seg) impl ActorMessage {}); false -> true }",
               "    produces pure (:no_reply, st) end", "}", ""]
    fields = ", ".join(["n: int64"] + [f"p{k}: actor_ref" for k in range(len(rems))])
    kills = "".join(f"        _: atom <- kill_abnormal(st.p{k});\n" for k in range(len(rems)))
    if rems:
        ln += [f"fn reaper(msg: int64, st: {{ {fields} }}) -> (:no_reply, {{ {fields} }}) {{",
               "    sequence proc[concurrency]", kills.rstrip().rstrip(";"),
               "    produces pure (:no_reply, st) end", "}", ""]
    else:
        ln += [f"fn reaper(msg: int64, st: {{ {fields} }}) -> (:no_reply, {{ {fields} }}) {{ (:no_reply, st) }}", ""]
    sp = [f"        p{k}: actor_ref <- spawn_registered({{ tx: tx, id: {k} }}, proxy_{n}, bees_atoms@a_{n}(), {POL});" for k, n in enumerate(rems)]
    init = ", ".join(["n: " + str(len(rems))] + [f"p{k}: p{k}" for k in range(len(rems))])
    ln += ["// the reaper ends every proxy of the link (kill_abnormal) when the link is lost; it is the one value start_proxies returns",
           "fn start_proxies(tx: actor_ref) -> actor_ref {", "    sequence proc[concurrency]"] + sp + \
          [f"        r: actor_ref <- spawn({{ {init} }}, reaper, {POL})", "    produces pure r end", "}", ""]
    # pid id k (the proxy's number) -> the local index its SENDs are delivered to, or -1 when the pid was not handed out
    arms = "".join(f"        {k} -> {locs.index(pids[n])};\n" for k, n in enumerate(rems) if n in pids)
    ln += ["fn pid_local(id: int64) -> int64 {", "    case id of {", arms + "        _: int64 -> -1", "    }", "}"]
    arms = "".join(f"        {k} -> bees_atoms@a_{n}();\n" for k, n in enumerate(locs))
    ln += ["fn local_atom(li: int64) -> atom {", "    case li of {", arms + "        _: int64 -> :ok", "    }", "}",
           f"fn handed_count() -> int64 {{ {len(pids)} }}", ""]
    with open(os.path.join(out_dir, "beam_peers.silica"), "w") as out:
        out.write("\n".join(ln))


def main(argv):
    args = argv[1:]
    if not args or args[0] not in ("check", "generate"):
        print(__doc__, file=sys.stderr)
        return 2
    cmd, args = args[0], args[1:]
    cfg = beam = out = None
    wires = []
    while args:
        if args[0] == "--config" and len(args) > 1:
            cfg, args = args[1], args[2:]
        elif args[0] == "--beam" and len(args) > 1:
            beam, args = args[1], args[2:]
        elif args[0] == "-o" and len(args) > 1:
            out, args = args[1], args[2:]
        else:
            wires.append(args[0])
            args = args[1:]
    if not cfg or not wires or (cmd == "generate" and not out):
        print(__doc__, file=sys.stderr)
        return 2
    try:
        d = D.parse(wires)
        msgs = D.check(d, W.collect(wires, warn=False))
        if not os.path.exists(cfg):
            raise ConfigError(f"{os.path.basename(cfg)}:1: (file): does not exist")
        eff = validate(cfg, d)
        if eff["mode"] != "beam":
            raise ConfigError(f"{os.path.basename(cfg)}:1: mode: trust; this is the BEAM-mode half (the trust half reads it)")
        pids = parse_beam(beam, d)
    except (ConfigError, D.DistError) as e:
        print(str(e), file=sys.stderr)
        return 1
    if cmd == "generate":
        os.makedirs(out, exist_ok=True)
        gen_conf(out, eff, cfg)
        gen_peers(out, d, msgs, pids)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
