#!/usr/bin/env python3
"""bees_conf: THE reader of `bees.config` (milestone N0.2; development-plan/bees-config-file.md). One reader for both modes: the
grammar, every option of `mode`, `node`, `beam` and `trust`, the precedence over the manifest, the validation rules of section 4,
the defaults table of section 5 and the `bees.config:LINE: PATH: MESSAGE` verdict. It replaces the two halves N2 and N3 wrote
(tools/bees_config_beam.py and tools/bees_config_trust.py are now only the generators of their modes' units and call this reader).

    bees_conf.py check    BEES_CONFIG [MANIFEST.wire...]   validate; print the notes and `ok`, or the one error line (exit 1)
    bees_conf.py defaults                                  print the defaults table (path, default, bounds, when it is read)

BUILD-TIME STAND-IN (stated plainly, as everywhere this reader is used). The design (D26, bees-config-file.md section 1) is a reader
written in Silica that reads the file at BOOT, before any actor starts. Silica cannot read a file at boot (specification 22.6:
read_file is not implemented), so this Python reader runs WHEN THE PROGRAM IS BUILT and the generators compile its verdict into
the program: the effective values as constants, or the one-line error. A changed `bees.config` (or whitelist, pin file or
certificate) therefore needs a rebuild until a boot-time reader exists (proposal: bees-config-file.md section 11). Two delivery
forms exist today, both before any actor starts:
  * TRUST mode (bees_trust_conf): the verdict is compiled in and the node's startup prints it and exits 1 at boot (R2's trial).
  * BEAM mode (beam_conf) and the M3 auth-none node (bees_peers): the build stops with the line and exit status 1.
Every option carries WHEN (see OPTIONS): `boot` means a boot-time reader could read it with no change to generated code; `build`
means today's Silica fixes it in generated code whatever reads the file (the reason is given).

What a value must be is decided only here; nothing is clamped, rounded or defaulted around a bad value.
"""
import hashlib
import os
import re
import stat
import sys

MAX_FILE = 65536
BEAM_FRAME_MAX = 4294967295      # BEAM's packet limit (4-byte length), R1; section 5.4
TOP_KEYS = ("mode", "node", "beam", "trust")


class ConfError(Exception):
    def __init__(self, line, path, msg, fname="bees.config"):
        self.text = f"{fname}:{line}: {path}: {msg}"
        super().__init__(self.text)


# ---------------------------------------------------------------- the grammar (section 4)
class Atom(str):
    pass


class Node:
    """a parsed term and the line it starts on; kind is atom, int, str, list, tuple or map"""
    def __init__(self, kind, value, line):
        self.kind, self.value, self.line = kind, value, line

    def __repr__(self):
        return f"{self.kind}:{self.value!r}"


INT_RE = re.compile(r"-?[0-9](_?[0-9])*")
ATOM_RE = re.compile(r"[a-z][A-Za-z0-9_@]*")


class Reader:
    def __init__(self, text, fname):
        self.s, self.i, self.line, self.fname = text, 0, 1, fname

    def err(self, msg, line=None):
        raise ConfError(line or self.line, "(syntax)", msg, self.fname)

    def ws(self):
        while self.i < len(self.s):
            c = self.s[self.i]
            if c == "%":
                while self.i < len(self.s) and self.s[self.i] != "\n":
                    self.i += 1
            elif c == "\n":
                self.line += 1
                self.i += 1
            elif c in " \t\r":
                self.i += 1
            else:
                break

    def peek(self):
        self.ws()
        return self.s[self.i] if self.i < len(self.s) else ""

    def expect(self, ch):
        if self.peek() != ch:
            self.err(f"expected '{ch}'")
        self.i += 1

    def seq(self, close, kind, line):
        items = []
        if self.peek() == close:
            self.i += 1
            return Node(kind, items, line)
        while True:
            items.append(self.term())
            if self.peek() == ",":
                self.i += 1
                continue
            self.expect(close)
            return Node(kind, items, line)

    def term(self):
        c = self.peek()
        line = self.line
        if c == "[":
            self.i += 1
            return self.seq("]", "list", line)
        if c == "{":
            self.i += 1
            return self.seq("}", "tuple", line)
        if c == "#":
            self.i += 1
            self.expect("{")
            pairs = []
            if self.peek() == "}":
                self.i += 1
                return Node("map", pairs, line)
            while True:
                k = self.term()
                self.ws()
                if self.s[self.i:self.i + 2] != "=>":
                    self.err("expected '=>' in a map")
                self.i += 2
                pairs.append((k, self.term()))
                if self.peek() == ",":
                    self.i += 1
                    continue
                self.expect("}")
                return Node("map", pairs, line)
        if c == '"':
            self.i += 1
            out = []
            while True:
                if self.i >= len(self.s):
                    self.err("unterminated string", line)
                ch = self.s[self.i]
                if ch == '"':
                    self.i += 1
                    return Node("str", "".join(out), line)
                if ch == "\\":
                    nxt = self.s[self.i + 1:self.i + 2]
                    esc = {"n": "\n", "t": "\t", "\\": "\\", '"': '"'}
                    if nxt not in esc:
                        self.err("only the escapes \\n \\t \\\\ \\\" are accepted in a string")
                    out.append(esc[nxt])
                    self.i += 2
                    continue
                if ch == "\n":
                    self.line += 1
                if not (32 <= ord(ch) <= 126):
                    self.err("a string holds ASCII 32 to 126 only")
                out.append(ch)
                self.i += 1
        if c == "'":
            self.i += 1
            j = self.s.find("'", self.i)
            if j < 0:
                self.err("unterminated quoted atom")
            v = self.s[self.i:j]
            self.i = j + 1
            return Node("atom", Atom(v), line)
        if c.isdigit() or c == "-":
            m = INT_RE.match(self.s, self.i)
            if m:
                self.i = m.end()
                if self.i < len(self.s) and self.s[self.i] in ".eE" and self.s[self.i + 1:self.i + 2].isdigit():
                    self.err("floats are not accepted")
                return Node("int", int(m.group(0).replace("_", "")), line)
        m = ATOM_RE.match(self.s, self.i)
        if m:
            self.i = m.end()
            return Node("atom", Atom(m.group(0)), line)
        if c == "":
            self.err("unexpected end of file")
        self.err(f"unexpected character '{c}' (floats, binaries, funs, variables, macros and records are not accepted)")

    def whole(self):
        t = self.term()
        self.expect(".")
        if self.peek() != "":
            self.err("a second term or trailing text after the full stop (a file is one term)")
        return t


def read_file(path, fname=None):
    """the whole file as one term (section 4: one term and a full stop, at most 64 KiB, ASCII only)"""
    fname = fname or os.path.basename(path)
    with open(path, "rb") as fh:
        raw = fh.read()
    if len(raw) > MAX_FILE:
        raise ConfError(1, "(file)", f"larger than {MAX_FILE} bytes (64 KiB)", fname)
    if any(b > 127 for b in raw):
        raise ConfError(1, "(file)", "a byte outside ASCII (non-ASCII bytes are not accepted)", fname)
    return Reader(raw.decode("ascii"), fname).whole()


# ---------------------------------------------------------------- the options (section 5): ONE table for both modes
class Opt:
    """kind: int, str, bool, atom, path, tls, spec, session, peers, allowlist, creation, name.
    default: the built-in default (None: unset or required, see `required`); `manifest` names the manifest value used instead.
    when: 'boot' (a boot-time reader could read it with no change to generated code) or 'build' (fixed in generated code
    under today's Silica; `why` says why)."""
    def __init__(self, kind, default=None, lo=None, hi=None, choices=None, required=None, manifest=None, when="boot", why=""):
        self.kind, self.default, self.lo, self.hi, self.choices = kind, default, lo, hi, choices
        self.required, self.manifest, self.when, self.why = required, manifest, when, why


DECODE_WHY = ("the language's decode takes its limits as a record literal of literals, baked into the derived decoder "
              "(transport design 4.1, E2402); wireframe@unframe's cap is a run-time argument")
NODE_OPTS = {
    "name": Opt("name", manifest="node", when="build", why="the node name is an atom the program must hold (D16)"),
    "creation": Opt("creation", default=1, lo=0, hi=4294967295, manifest="creation"),
}
BEAM_OPTS = {
    "transport": Opt("atom", "tls", choices=("tcp", "tls")),
    "auth": Opt("atom", "cookie", choices=("cookie", "none")),
    "cookie_file": Opt("path", required="when auth is cookie"),
    "listen_address": Opt("str", required="in the selected mode's section (R6)"),
    "listen_port": Opt("int", 0, 0, 65535),
    "epmd": Opt("atom", "external", choices=("external", "none")),
    "epmd_port": Opt("int", 4369, 1, 65535),
    "net_ticktime_s": Opt("int", 60, 4, 3600),
    "open_timeout_ms": Opt("int", 10000, 1, 60000, manifest="open_ms"),
    "peers": Opt("peers", manifest="peer", when="build", why="peer names are atoms of the manifest (D16); their host, port and "
                 "role are boot values"),
    "spawn": Opt("atom", "none", choices=("none", "allowlist", "any")),
    "spawn_allowlist": Opt("allowlist", [], 0, 1024),
    "frame_size_max": Opt("int", BEAM_FRAME_MAX, 512, BEAM_FRAME_MAX, when="build", why=DECODE_WHY),
}
TRUST_OPTS = {
    "port": Opt("int", 6469, 1, 65535),
    "listen_address": Opt("str", required="in the selected mode's section (R6)"),
    "tls_opts": Opt("tls", required="unless plaintext_test_only"),
    "client_tls_opts": Opt("tls"),
    "whitelist_file": Opt("path", when="build", why="the stand-in compiles the whitelist into the permission gate and one "
                          "registered name per entry (atoms, D16); a boot reader needs a data-driven gate and a name pool"),
    "whitelist_cert_dir": Opt("str", "certs", when="build", why="read with the whitelist"),
    "whitelist_default_spec": Opt("spec", "none"),
    "whitelist_autoload": Opt("bool", False),
    "classical_allowed_certs": Opt("strlist", [], when="build", why="D44: the marker is compiled into the generated peer table with the whitelist"),
    "server_pins_file": Opt("path", when="build", why="one registered client cache per pinned server (atoms)"),
    "call_timeout_ms": Opt("int", 5000, 1, 600000),
    "suspicion_limit": Opt("int", 3, 0, 1000),
    "token_bytes": Opt("int", 48, 32, 64),
    "token_ttl_sec": Opt("int", 300, 10, 3600),
    "dns_ns_timeout_ms": Opt("int", 2000, 100, 30000),
    "dns_total_timeout_ms": Opt("int", 5000, 100, 60000),
    "connect_timeout_ms": Opt("int", 3000, 100, 60000),
    "connect_stagger_ms": Opt("int", 250, 0, 5000),
    "client_handshake_timeout": Opt("int", 5000, 1000, 30000),
    "first_frame_timeout_ms": Opt("int", 2000, 100, 10000),
    "frame_size_max": Opt("int", BEAM_FRAME_MAX, 512, BEAM_FRAME_MAX, when="build", why=DECODE_WHY),
    "args_len_max": Opt("int", None, 0, BEAM_FRAME_MAX, when="build", why=DECODE_WHY),   # default: frame_size_max
    "term_depth_max": Opt("int", 32, 1, 128, when="build", why=DECODE_WHY),
    "session": Opt("session"),
    "acceptors": Opt("int", None, 1, 1024),
    "session_slots_max": Opt("int", None, 1, 1000000),
    "plaintext_test_only": Opt("bool", False),
}
SESSION_OPTS = {
    "max_inflight": ((1, 64), 8), "max_age_ms": ((1000, 3600000), 60000), "idle_ms": ((100, 600000), 5000),
    "max_calls": ((1, 100000), 100), "drain_ms": ((0, 60000), 1000),
}
TLS_KEYS = ("certfile", "keyfile", "cacertfile")
TLS_REQUIRED = ("certfile", "keyfile")   # D43: cacertfile is optional; without it peer trust is the pin and the whitelist alone
SEMP_RENAMED = {"token_ttl_ms": "token_ttl_sec (seconds; bees-config-file.md section 7)",
                "rpc_api": "nothing: the module table is built at build time", "host_app": "nothing: paths are relative to bees.config",
                "unsafe": "nothing", "unsafe_cookie": "nothing", "alpn": "nothing: the ALPN is fixed at trust/1",
                "enabled": "the top-level mode (section 5.2)", "sname": "node.name (section 5.2)"}
SECTIONS = (("node", NODE_OPTS), ("beam", BEAM_OPTS), ("trust", TRUST_OPTS))


def defaults_rows():
    """[(path, default text, bounds text, when, why)] for every option: the reader's own defaults table"""
    rows = []
    for sec, opts in SECTIONS:
        for k, o in opts.items():
            if o.manifest:
                d = f"manifest {o.manifest}" + (f", else {o.default}" if o.default is not None else "")
            elif o.required:
                d = "required " + o.required
            elif o.default is None:
                d = "equal to frame_size_max" if k == "args_len_max" else "unset"
            else:
                d = str(o.default).lower() if isinstance(o.default, bool) else str(o.default)
            b = f"{o.lo} to {o.hi}" if o.lo is not None and o.kind == "int" or o.kind == "creation" else \
                (", ".join(o.choices) if o.choices else "")
            if k == "args_len_max":
                b = "0 to frame_size_max"
            rows.append((f"{sec}.{k}", d, b, o.when, o.why))
    for k, ((lo, hi), d) in SESSION_OPTS.items():
        rows.append((f"trust.session.{k}", str(d), f"{lo} to {hi}", "boot", ""))
    return rows


# ---------------------------------------------------------------- the checks
def proplist(node, path, allowed):
    """a list of {atom, value} pairs -> {key: (value node, line)}; unknown (rule 2) and duplicate (rule 3) keys refused"""
    if node.kind != "list":
        raise ConfError(node.line, path or "(top)", "expected a list of {key, value} pairs")
    out = {}
    for item in node.value:
        if item.kind != "tuple" or len(item.value) != 2 or item.value[0].kind != "atom":
            raise ConfError(item.line, path or "(top)", "expected a {key, value} pair with an atom key")
        k = str(item.value[0].value)
        where = f"{path}.{k}" if path else k
        if k not in allowed:
            hint = f" (SEMP's {k} is {SEMP_RENAMED[k]})" if k in SEMP_RENAMED else ""
            raise ConfError(item.line, where, "unknown key" + hint)
        if k in out:
            raise ConfError(item.line, where, f"duplicate key (first at line {out[k][1]})")
        out[k] = (item.value[1], item.line)
    return out


def want_int(node, path, lo, hi):
    if node.kind != "int":
        raise ConfError(node.line, path, "expected an integer")
    if node.value < lo:
        raise ConfError(node.line, path, f"{node.value} is below {lo} (bounds {lo} to {hi}; never clamped)")
    if node.value > hi:
        raise ConfError(node.line, path, f"{node.value} is above {hi} (bounds {lo} to {hi}; never clamped)")
    return node.value


def want_str(node, path):
    if node.kind != "str":
        raise ConfError(node.line, path, "expected a string")
    return node.value


def want_bool(node, path):
    if node.kind != "atom" or node.value not in ("true", "false"):
        raise ConfError(node.line, path, "expected true or false")
    return node.value == "true"


def want_atom(node, path, choices):
    if node.kind != "atom" or str(node.value) not in choices:
        raise ConfError(node.line, path, f"expected one of {', '.join(choices)}")
    return str(node.value)


def parse_spec(node, path):
    """a whitelist spec -> 'none' | 'any' | {module: 'any' | [(f, a)]}; SEMP's list form and the README's map form"""
    if node.kind == "atom" and node.value in ("none", "any"):
        return str(node.value)
    out = {}
    if node.kind == "list":
        entries = []
        for it in node.value:
            if it.kind != "tuple" or len(it.value) != 2 or it.value[0].kind != "atom":
                raise ConfError(it.line, path, "a spec entry is {Module, any} or {Module, [{Fun, Arity}]}")
            entries.append((it.value[0], it.value[1]))
    elif node.kind == "map":
        entries = list(node.value)
        for k, _ in entries:
            if k.kind != "atom":
                raise ConfError(k.line, path, "a spec map's keys are module atoms")
    else:
        raise ConfError(node.line, path, "a spec is none, any, a list [{Module, any | [{Fun, Arity}]}] or a map #{Module => all | [{Fun, Arity}]}")
    for k, v in entries:
        mod = str(k.value)
        if mod in out:
            raise ConfError(k.line, path, f"module {mod} named twice")
        if v.kind == "atom" and v.value in ("any", "all"):
            out[mod] = "any"
        elif v.kind == "list":
            fas = []
            for fa in v.value:
                if fa.kind != "tuple" or len(fa.value) != 2 or fa.value[0].kind != "atom" or fa.value[1].kind != "int" \
                        or not 0 <= fa.value[1].value <= 255:
                    raise ConfError(fa.line, path, "a function entry is {Fun, Arity} with 0 =< Arity =< 255")
                fas.append((str(fa.value[0].value), fa.value[1].value))
            out[mod] = fas
        else:
            raise ConfError(v.line, path, "a module's value is any, all or a list of {Fun, Arity}")
    return out


def check_file(base, rel, line, path, what):
    """rule 8: a configured file exists, is a file and is readable; a missing or unreadable one is a loud error (R2)"""
    full = rel if os.path.isabs(rel) else os.path.normpath(os.path.join(base, rel))
    rest = "(relative to the directory of bees.config)"
    if not os.path.exists(full):
        raise ConfError(line, path, f'{what} "{rel}" does not exist {rest}')
    if not os.path.isfile(full):
        raise ConfError(line, path, f'{what} "{rel}" is not a file {rest}')
    if not os.access(full, os.R_OK):
        raise ConfError(line, path, f'{what} "{rel}" is not readable (permissions) {rest}')
    try:
        with open(full, "rb") as fh:
            fh.read(1)
    except OSError as e:
        raise ConfError(line, path, f'{what} "{rel}" cannot be read: {e.strerror} {rest}')
    return full


def fingerprint(path):
    """SHA-512 of the certificate's full DER (D11): the DER inside a PEM file, else the file's bytes"""
    import base64
    with open(path, "rb") as fh:
        data = fh.read()
    m = re.search(rb"-----BEGIN CERTIFICATE-----(.*?)-----END CERTIFICATE-----", data, re.S)
    if m:
        data = base64.b64decode(b"".join(m.group(1).split()))
    return hashlib.sha512(data).hexdigest()


# ---------------------------------------------------------------- addresses (N1: what the language's carrier can do)
IPV4_RE = re.compile(r"(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])(\.(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])){3}")
NAME_RE = re.compile(r"(?=.{1,253}$)[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*")


def addr_kind(a):
    """ipv4 | ipv6 | name | bad"""
    if IPV4_RE.fullmatch(a):
        return "ipv4"
    if ":" in a and re.fullmatch(r"[0-9A-Fa-f:.]+", a):
        return "ipv6"
    if NAME_RE.fullmatch(a) and not re.fullmatch(r"[0-9.]+", a):
        return "name"
    return "bad"


def is_loopback(a):
    return a == "localhost" or a == "::1" or (addr_kind(a) == "ipv4" and a.startswith("127."))


CARRIER_LISTEN = ('the language\'s (:tcp) carrier binds only 127.0.0.1 ("listen:PORT") or every IPv4 interface ("listen:any:PORT", '
                  'written "0.0.0.0" here); binding one other address, an IPv6 address or a name needs interface binding in '
                  'the carrier (a request to Silica, silica-defects.md SR-1)')
CARRIER_DIAL_V6 = ("the language's (:tcp) carrier dials IPv4 literals only (inet_pton AF_INET, and its \"host:port\" address "
                   "splits at the first ':'); IPv6 needs the carrier (a request to Silica, silica-defects.md SR-2)")


def listen_form(a, line, path):
    """the carrier address prefix a listen_address maps to: 'listen:' (127.0.0.1) or 'listen:any:' (0.0.0.0)"""
    kind = addr_kind(a)
    if kind == "bad":
        raise ConfError(line, path, f'"{a}" is not an IPv4 or IPv6 literal or a host name')
    if a in ("127.0.0.1", "localhost"):
        return "listen:"
    if a == "0.0.0.0":
        return "listen:any:"
    raise ConfError(line, path, f"{a} is not built yet: {CARRIER_LISTEN}")


def dial_check(a, line, path):
    """a dial host: an IPv4 literal (any address), or a host name resolved at boot by the BEES resolver edge (A records)"""
    kind = addr_kind(a)
    if kind == "bad":
        raise ConfError(line, path, f'"{a}" is not an IPv4 or IPv6 literal or a host name')
    if kind == "ipv6":
        raise ConfError(line, path, f"{a} is not built yet: {CARRIER_DIAL_V6}")
    if a == "0.0.0.0":
        raise ConfError(line, path, "0.0.0.0 is a listen wildcard, not an address to dial")
    return kind


def test_setting_rule(addr, line, path, setting):
    """N1 (3): auth none and plaintext_test_only are loopback-only TEST settings: no authentication and no encryption, so a
    non-loopback listen or dial is refused"""
    if not is_loopback(addr):
        raise ConfError(line, path, f"{addr} is not a loopback address, and {setting} is a loopback-only test setting (no "
                        "authentication, no encryption; a non-loopback address needs TLS or authentication)")


# ---------------------------------------------------------------- the validation (section 4), both modes
def validate(cfg_path, manifest=None):
    """manifest: tools/bees_dist_gen.parse() of the program's .wire files, or None (a TRUST program has none).
    -> Conf (a dict): mode, node, beam (effective), trust (effective), notes, lines. Raises ConfError (the boot verdict)."""
    fname = os.path.basename(cfg_path)
    base = os.path.dirname(os.path.abspath(cfg_path))
    if not os.path.exists(cfg_path):
        raise ConfError(1, "(file)", f"{fname} not found ({cfg_path})", fname)
    try:
        top_node = read_file(cfg_path, fname)
    except OSError as e:
        raise ConfError(1, "(file)", f"cannot be read: {e.strerror}", fname)

    def E(line, path, msg):
        return ConfError(line, path, msg, fname)

    top = proplist_r(top_node, "", TOP_KEYS, E)
    notes = []
    # ---- mode (section 3.1): default trust (R3); the list form is reserved
    mode, mln = "trust", 1
    if "mode" in top:
        mnode, mln = top["mode"]
        if mnode.kind == "list":
            raise E(mln, "mode", "the list form is reserved (one mode per node, section 3.1)")
        if mnode.kind != "atom" or mnode.value not in ("beam", "trust"):
            raise E(mln, "mode", "expected beam or trust")
        mode = str(mnode.value)
    if manifest and (manifest["remotes"] or manifest["locals"]) and mode == "trust":
        if "mode" not in top:
            raise E(1, "mode", "absent, so the mode is trust (R3); a BEAM-mode node must write {mode, beam} "
                    "(the manifest has remote/local lines)")
        raise E(mln, "mode", "trust, but the manifest has remote/local lines, which exist only for BEAM mode")
    sec_line = {k: top[k][1] for k in top}
    conf = {"mode": mode, "notes": notes, "file": os.path.abspath(cfg_path)}
    conf["node"] = node_section(top, manifest, E)
    conf["beam"] = beam_section(top, mode, manifest, base, E, sec_line)
    conf["trust"] = trust_section(top, mode, base, E, sec_line, notes, fname)
    return conf


def _path_of(e):
    return e.text.split(": ", 2)[1]


def _msg_of(e):
    return e.text.split(": ", 2)[2]


def _line_of(e):
    return int(e.text.split(": ", 1)[0].rsplit(":", 1)[1])


def sec(top, k):
    return top[k][0] if k in top else Node("list", [], 1)


def node_section(top, manifest, E):
    node = proplist_r(sec(top, "node"), "node", NODE_OPTS, E)
    out = {"name": manifest["node"] if manifest else None, "creation": manifest["creation"] if manifest else 1}
    if "name" in node:
        nv, nl = node["name"]
        name = want_r(want_str, E, nv, "node.name")
        if not re.fullmatch(r"[A-Za-z0-9_.@\-]{1,255}", name):
            raise E(nl, "node.name", "ASCII letters, digits, _ . @ - only, 1 to 255 bytes")
        if manifest and name != manifest["node"]:
            raise E(nl, "node.name", f"\"{name}\" differs from the manifest's node {manifest['node']} (rule 10; D16)")
        out["name"] = name
    if "creation" in node:
        cv, cl = node["creation"]
        if cv.kind == "atom":
            if cv.value == "epmd":
                raise E(cl, "node.creation", "epmd is not built yet (N2 keeps a fixed creation; the one EPMD assigns is audited)")
            raise E(cl, "node.creation", "expected an integer or epmd")
        out["creation"] = want_r(want_int, E, cv, "node.creation", 0, 4294967295)
    return out


def proplist_r(node, path, opts, E):
    try:
        return proplist(node, path, opts)
    except ConfError as e:
        raise E(_line_of(e), _path_of(e), _msg_of(e))


def want_r(fn, E, node, path, *a):
    try:
        return fn(node, path, *a)
    except ConfError as e:
        raise E(_line_of(e), _path_of(e), _msg_of(e))


def beam_section(top, mode, manifest, base, E, sec_line):
    """section 5.2, validated whatever the mode (section 3); the required values and the link only when mode is beam"""
    b = proplist_r(sec(top, "beam"), "beam", BEAM_OPTS, E)
    bl = lambda k: b[k][1]  # noqa: E731
    sl = sec_line.get("beam", 1)
    active = mode == "beam"
    v = {}
    for k, o in BEAM_OPTS.items():
        if k not in b:
            continue
        node, line = b[k]
        p = f"beam.{k}"
        if o.kind == "int":
            v[k] = want_r(want_int, E, node, p, o.lo, o.hi)
        elif o.kind == "atom":
            v[k] = want_r(want_atom, E, node, p, o.choices)
        elif o.kind in ("str", "path"):
            v[k] = want_r(want_str, E, node, p)
    transport = v.get("transport", "tls")
    auth = v.get("auth", "cookie")
    eff = {"mode": mode, "auth": auth, "transport": transport, "cookie_path": ""}
    # spawn_allowlist (validated now, takes effect at L3)
    if "spawn_allowlist" in b:
        sv, sln = b["spawn_allowlist"]
        if sv.kind != "list" or len(sv.value) > 1024:
            raise E(sln, "beam.spawn_allowlist", "expected a list of at most 1024 {Module, Function, Arity}")
        for e in sv.value:
            if not (e.kind == "tuple" and len(e.value) == 3 and e.value[0].kind == "atom" and e.value[1].kind == "atom"
                    and e.value[2].kind == "int" and 0 <= e.value[2].value <= 255):
                raise E(e.line, "beam.spawn_allowlist", "expected {Module, Function, Arity}")
    # peers: the manifest's names only (D16); each may give host, port (N or epmd) and role
    names = [p[0] for p in manifest["peers"]] if manifest else []
    over = {}
    if "peers" in b:
        pv, pln = b["peers"]
        if pv.kind != "list":
            raise E(pln, "beam.peers", "expected a list")
        for e in pv.value:
            if not (e.kind == "tuple" and len(e.value) == 2 and e.value[0].kind == "str"):
                raise E(e.line, "beam.peers", "expected {\"name@host\", [options]}")
            pname = e.value[0].value
            if manifest and pname not in names:
                raise E(e.line, "beam.peers", f"{pname} is not a peer of the manifest (D16)")
            if pname in over:
                raise E(e.line, "beam.peers", f"{pname} is listed twice")
            opts = proplist_r(e.value[1], f"beam.peers.{pname}", ("host", "port", "role"), E)
            d = {}
            if "host" in opts:
                d["host"] = want_r(want_str, E, opts["host"][0], f"beam.peers.{pname}.host")
                d["host_line"] = opts["host"][1]
                if addr_kind(d["host"]) == "bad":
                    raise E(opts["host"][1], f"beam.peers.{pname}.host", f'"{d["host"]}" is not an IPv4 or IPv6 literal or a host name')
            if "port" in opts:
                pn, pl = opts["port"]
                if pn.kind == "atom":
                    if pn.value != "epmd":
                        raise E(pl, f"beam.peers.{pname}.port", "expected 1..65535 or epmd")
                    d["port"] = "epmd"
                else:
                    d["port"] = want_r(want_int, E, pn, f"beam.peers.{pname}.port", 1, 65535)
            if "role" in opts:
                d["role"] = want_r(want_atom, E, opts["role"][0], f"beam.peers.{pname}.role", ("dial", "listen"))
            over[pname] = (d, e.line)
    # cross-field rules (rule 6)
    lport = v.get("listen_port")
    epmd = v.get("epmd", "external")
    if lport == 0 and epmd != "external":
        raise E(bl("listen_port"), "beam.listen_port", "0 needs epmd external")
    if epmd == "none":
        if lport is None or lport == 0:
            raise E(bl("epmd"), "beam.epmd", "none needs a non-zero listen_port")
        for pname, (d, eln) in over.items():
            if d.get("port") == "epmd":
                raise E(eln, f"beam.peers.{pname}.port", "epmd, but beam.epmd is none")
    if "listen_address" in v and addr_kind(v["listen_address"]) == "bad":
        raise E(bl("listen_address"), "beam.listen_address", f'"{v["listen_address"]}" is not an IPv4 or IPv6 literal or a host name')
    if not active:
        eff["active"] = False
        return eff
    # ---- required values and "not built yet" (rules 7 and 9), mode beam
    eff["active"] = True
    if transport == "tls":
        raise E(bl("transport") if "transport" in b else sl, "beam.transport",
                "tls (the default, D25) is not built yet; write {transport, tcp}")
    if auth == "cookie" and "cookie_file" not in b:
        raise E(bl("auth") if "auth" in b else sl, "beam.cookie_file", "required when auth is cookie")
    if "cookie_file" in b:
        eff["cookie_path"] = cookie_check(base, v["cookie_file"], bl("cookie_file"), E)
    if "listen_address" not in v:
        raise E(sl, "beam.listen_address", "required, no built-in default (R6)")
    la = v["listen_address"]
    if auth == "none":
        test_setting_rule(la, bl("listen_address"), "beam.listen_address", "auth none")
    la_form = listen_form(la, bl("listen_address"), "beam.listen_address")
    if v.get("spawn", "none") != "none":
        raise E(bl("spawn"), "beam.spawn", f"{v['spawn']} is not built yet (remote spawn, B4)")
    if not manifest:
        # a program without a .wire manifest (a TRUST program's generator reading a mode-beam file): the link is the
        # manifest's business, so only the values above are checked here
        eff["listen_address"] = la
        return eff
    o_ms, io_ms, tick_ms = manifest["timing"]
    if "net_ticktime_s" in v:
        io_ms, tick_ms = v["net_ticktime_s"] * 1000, v["net_ticktime_s"] * 1000 // 4
    if "open_timeout_ms" in v:
        o_ms = v["open_timeout_ms"]
    # the links (N2b): one per manifest peer line, in manifest order (the index is bees_peers@peer_index), with bees.config over
    # the manifest (section 2). A dial-role peer is dialed; every listen-role peer is listened for on the node's ONE listener
    # (beam.listen_port, else the first listen-role peer's manifest port), and a peer's link starts when its handshake names it.
    for pname, (pd, pl) in over.items():
        if "host" in pd and auth == "none":
            test_setting_rule(pd["host"], pd["host_line"], f"beam.peers.{pname}.host", "auth none")
    links = []
    listen_first = None
    for peer in manifest["peers"]:
        d, dln = over.get(peer[0], ({}, sl))
        role = d.get("role", peer[3])
        host = d.get("host", peer[1])
        hline = d.get("host_line", dln)
        port = d.get("port", peer[2])
        if role == "dial" and port == "epmd" and epmd == "none":
            raise E(dln, f"beam.peers.{peer[0]}.port", "epmd, but beam.epmd is none")
        if role == "dial":
            hk = dial_check(host, hline, f"beam.peers.{peer[0]}.host")
            if auth == "none":
                test_setting_rule(host, hline, f"beam.peers.{peer[0]}.host", "auth none")
            address = f"{host}:{port}" if port != "epmd" else ""
            link_port = port if port != "epmd" else 0
        else:
            hk = "ipv4"
            if listen_first is None:
                listen_first = peer
            address, link_port = None, None      # the listener's: set below
        links.append({"name": peer[0], "dials": role == "dial", "by_epmd": role == "dial" and port == "epmd", "host": host,
                      "host_kind": hk, "port": link_port, "address": address, "resolve": role == "dial" and hk == "name"})
    lp = 0
    listen_address = ""
    if listen_first is not None:
        lp = lport if lport is not None else listen_first[2]
        if lp == 0 and epmd != "external":
            raise E(sl, "beam.listen_port", "0 (ephemeral) needs epmd external")
        listen_address = f"{la_form}{lp}"
        for lk in links:
            if not lk["dials"]:
                lk["address"], lk["port"] = listen_address, lp
    first = links[0]
    eff.update({
        "creation": None, "epmd": epmd, "epmd_port": v.get("epmd_port", 4369), "open_ms": o_ms, "io_ms": io_ms,
        "tick_ms": tick_ms, "frame_max": v.get("frame_size_max", BEAM_FRAME_MAX), "listen_address": la,
        "links": links, "listens": listen_first is not None, "listener_address": listen_address,
        # the first link, as scalars (M3's node and the roles of the one-link trials read these)
        "link_dials": first["dials"], "link_peer": 0 if first["dials"] else -1, "link_address": first["address"],
        "link_port": first["port"], "link_by_epmd": first["by_epmd"], "link_host": first["host"],
        "link_host_kind": first["host_kind"], "link_peer_name": first["name"],
        "register_epmd": listen_first is not None and epmd == "external", "node": manifest["node"],
    })
    return eff


def cookie_check(base, cf, ln, E):
    full = cf if os.path.isabs(cf) else os.path.normpath(os.path.join(base, cf))
    if not os.path.exists(full):
        raise E(ln, "beam.cookie_file", f"{cf} does not exist")
    st = os.stat(full)
    if not stat.S_ISREG(st.st_mode):
        raise E(ln, "beam.cookie_file", f"{cf} is not a regular file")
    if st.st_mode & 0o077:
        raise E(ln, "beam.cookie_file", f"{cf} is readable or writable by group or others (mode {st.st_mode & 0o777:o})")
    try:
        with open(full, "rb") as fh:
            content = fh.read()
    except OSError as e:
        raise E(ln, "beam.cookie_file", f"{cf} cannot be read ({e.strerror})")
    if content.endswith(b"\n"):
        content = content[:-1]
    if content.endswith(b"\r"):
        content = content[:-1]
    if not (1 <= len(content) <= 255) or any(c < 32 or c > 126 for c in content):
        raise E(ln, "beam.cookie_file", f"{cf} must hold 1 to 255 bytes of ASCII 32..126")
    return full


def trust_section(top, mode, base, E, sec_line, notes, fname):
    """section 5.3, validated whatever the mode; the required values, files and the whitelist only when mode is trust"""
    tr = proplist_r(sec(top, "trust"), "trust", TRUST_OPTS, E)
    sl = sec_line.get("trust", 1)
    v = {"mode": mode}
    for k, o in TRUST_OPTS.items():
        if k not in tr:
            v[k] = o.default
            continue
        node, line = tr[k]
        p = f"trust.{k}"
        if o.kind == "int":
            v[k] = want_r(want_int, E, node, p, o.lo, o.hi)
        elif o.kind in ("str", "path"):
            v[k] = want_r(want_str, E, node, p)
        elif o.kind == "bool":
            v[k] = want_r(want_bool, E, node, p)
        elif o.kind == "spec":
            v[k] = want_r(parse_spec, E, node, p)
        elif o.kind == "strlist":
            if node.kind != "list":
                raise E(line, p, "expected a list of certificate names, for example [\"board.pem\"]")
            names = [want_r(want_str, E, it, p) for it in node.value]
            if len(set(names)) != len(names):
                raise E(line, p, "a certificate is named twice")
            v[k] = names
        elif o.kind == "tls":
            d = proplist_r(node, p, TLS_KEYS, E)
            v[k] = {kk: (want_r(want_str, E, vv, f"{p}.{kk}"), ln) for kk, (vv, ln) in d.items()}
        elif o.kind == "session":
            if node.kind != "map":
                raise E(line, p, "expected a map of max_inflight, max_age_ms, idle_ms, max_calls, drain_ms")
            sess = {}
            for kn, vn in node.value:
                if kn.kind != "atom" or str(kn.value) not in SESSION_OPTS:
                    raise E(kn.line, f"{p}.{kn.value}", "unknown key")
                if str(kn.value) in sess:
                    raise E(kn.line, f"{p}.{kn.value}", "duplicate key")
                lo, hi = SESSION_OPTS[str(kn.value)][0]
                sess[str(kn.value)] = want_r(want_int, E, vn, f"{p}.{kn.value}", lo, hi)
            v[k] = sess
    lines = {k: tr[k][1] for k in tr}
    v["lines"] = lines
    sess = {k: d for k, (_, d) in SESSION_OPTS.items()}
    sess.update(v["session"] or {})
    v["session"] = sess
    if sess["idle_ms"] > sess["max_age_ms"]:
        raise E(lines.get("session", sl), "trust.session.idle_ms", f"{sess['idle_ms']} is above max_age_ms {sess['max_age_ms']}")
    if v["args_len_max"] is None:
        v["args_len_max"] = v["frame_size_max"]
    if v["args_len_max"] > v["frame_size_max"]:
        raise E(lines.get("args_len_max", sl), "trust.args_len_max", f"{v['args_len_max']} is above frame_size_max {v['frame_size_max']}")
    if v["dns_ns_timeout_ms"] > v["dns_total_timeout_ms"]:
        raise E(lines.get("dns_ns_timeout_ms", sl), "trust.dns_ns_timeout_ms",
                f"{v['dns_ns_timeout_ms']} is above dns_total_timeout_ms {v['dns_total_timeout_ms']}")
    v["frame_eff"] = v["frame_size_max"]
    v["args_eff"] = v["args_len_max"]
    if v["listen_address"] is not None and addr_kind(v["listen_address"]) == "bad":
        raise E(lines["listen_address"], "trust.listen_address", f'"{v["listen_address"]}" is not an IPv4 or IPv6 literal or a host name')
    if mode != "trust":
        v["active"] = False
        return v
    v["active"] = True
    if v["listen_address"] is None:
        raise E(sl, "trust.listen_address", "required in mode trust; there is no default (R6)")
    # N4.1: without plaintext_test_only the node speaks TRUST over mutual TLS 1.3 (the engine over the programmer's OpenSSL,
    # native/tls; the profile is fixed, inter-nodal-modes 3.2); tls_opts is then required with all three keys
    v["tls"] = not v["plaintext_test_only"]
    if v["plaintext_test_only"] and not is_loopback(v["listen_address"]):
        raise E(lines["listen_address"], "trust.listen_address",
                f"plaintext_test_only binds a loopback address only ({v['listen_address']} is not loopback; no "
                "authentication, no encryption)")
    if v["tls"]:
        if v["tls_opts"] is None:
            raise E(sl, "trust.tls_opts", "required in mode trust unless plaintext_test_only (certfile and keyfile; cacertfile is optional, D43)")
        for k in ("tls_opts", "client_tls_opts"):
            if v[k] is not None:
                missing = [kk for kk in TLS_REQUIRED if kk not in v[k]]
                if missing:
                    raise E(lines.get(k, sl), f"trust.{k}", f"needs certfile and keyfile ({', '.join(missing)} missing); cacertfile is optional")
    v["listen_prefix"] = listen_form(v["listen_address"], lines["listen_address"], "trust.listen_address")
    v["tls_paths"] = {}
    for k in ("tls_opts", "client_tls_opts"):
        if v[k] is not None:
            for kk, (rel, ln) in v[k].items():
                full = check_file(base, rel, ln, f"trust.{k}.{kk}", "file")
                if kk == "keyfile" and os.stat(full).st_mode & 0o077:
                    raise E(ln, f"trust.{k}.{kk}", f'key file "{rel}" is readable or writable by group or others (mode '
                            f'{os.stat(full).st_mode & 0o777:o}; rule 8)')
                v["tls_paths"][(k, kk)] = os.path.abspath(full)
    certdir = os.path.join(base, v["whitelist_cert_dir"])
    own = (v["client_tls_opts"] or v["tls_opts"] or {}).get("certfile")
    # the TEST-ONLY stand-in identity (R5) exists only under plaintext_test_only; over TLS the identity is the certificate
    v["self_fp"] = fingerprint(os.path.join(base, own[0])) if (own and not v["tls"]) else ""
    v["peers"] = []
    if v["whitelist_file"] is not None:
        wl_full = check_file(base, v["whitelist_file"], lines["whitelist_file"], "trust.whitelist_file", "whitelist file")
        try:
            wl = read_file(wl_full, v["whitelist_file"])
        except ConfError as e:
            raise E(lines["whitelist_file"], "trust.whitelist_file", f'whitelist file "{v["whitelist_file"]}" does not parse: {e.text}')
        if wl.kind == "map":
            entries = list(wl.value)
        elif wl.kind == "list":
            entries = []
            for it in wl.value:
                if it.kind != "tuple" or len(it.value) != 2:
                    raise ConfError(it.line, "(whitelist)", "an entry is {\"cert.pem\", Spec}", v["whitelist_file"])
                entries.append((it.value[0], it.value[1]))
        else:
            raise ConfError(wl.line, "(whitelist)", "the whitelist is a map #{\"cert.pem\" => Spec} or a list", v["whitelist_file"])
        seen = {}
        for kn, sn in entries:
            cert = want_str(kn, f"{v['whitelist_file']}: certificate name")
            spec = parse_spec(sn, f"{v['whitelist_file']}: {cert}")
            cpath = os.path.join(certdir, cert)
            if not (os.path.isfile(cpath) and os.access(cpath, os.R_OK)):
                notes.append(f"whitelist: certificate {cert} is missing or unreadable, entry skipped (as SEMP does)")
                continue
            fp = fingerprint(cpath)
            if fp in seen:
                notes.append(f"whitelist: {cert} has the same fingerprint as {seen[fp]} (one certificate per node, 3.3)")
                continue
            seen[fp] = cert
            v["peers"].append((cert, fp, spec))
        names = [c for c, _, _ in v["peers"]]
        for c in v["classical_allowed_certs"]:
            if c not in names:
                raise E(lines["classical_allowed_certs"], "trust.classical_allowed_certs",
                        f'"{c}" names no whitelist entry with a readable certificate (the marker is per whitelist entry, D44)')
    else:
        if v["classical_allowed_certs"]:
            raise E(lines["classical_allowed_certs"], "trust.classical_allowed_certs", "needs a whitelist_file to mark entries of (D44)")
        notes.append("TRUST standalone: no whitelist file configured, no inbound connections accepted")
    if v["classical_allowed_certs"] and not v["tls"]:
        raise E(lines["classical_allowed_certs"], "trust.classical_allowed_certs", "has no meaning under plaintext_test_only (no TLS)")
    v["peer_classical"] = [c in v["classical_allowed_certs"] for c, _, _ in v["peers"]]
    v["servers"] = []
    if v["server_pins_file"] is not None:
        pf = check_file(base, v["server_pins_file"], lines["server_pins_file"], "trust.server_pins_file", "pin file")
        try:
            pins = read_file(pf, v["server_pins_file"])
        except ConfError as e:
            raise E(lines["server_pins_file"], "trust.server_pins_file", f'pin file "{v["server_pins_file"]}" does not parse: {e.text}')
        if pins.kind != "map":
            raise ConfError(pins.line, "(pins)", "the pin file is a map #{\"host:port\" => \"server-cert.pem\"}", v["server_pins_file"])
        for kn, cn in pins.value:
            addr = want_str(kn, f"{v['server_pins_file']}: address")
            if not re.fullmatch(r"[^:]+:[0-9]{1,5}", addr):
                raise ConfError(kn.line, "(pins)", f"{addr} is not host:port", v["server_pins_file"])
            host = addr.rsplit(":", 1)[0]
            dial_check(host, kn.line, f"{v['server_pins_file']}: {addr}")
            if not is_loopback(host) and not v["tls"]:
                raise ConfError(kn.line, "(pins)", f"{addr}: {host} is not a loopback address, and plaintext_test_only is a "
                                "loopback-only test setting (no authentication, no encryption)", v["server_pins_file"])
            cert = want_str(cn, f"{v['server_pins_file']}: {addr}")
            cpath = os.path.join(certdir, cert)
            fp = fingerprint(cpath) if os.path.isfile(cpath) else ""
            if v["tls"] and not fp:
                # over TLS a pin is the server's identity: a pin without its certificate could never match (rule 8)
                raise ConfError(cn.line, "(pins)", f'{addr}: pinned certificate "{cert}" is missing or unreadable '
                                f'(in {v["whitelist_cert_dir"]})', v["server_pins_file"])
            v["servers"].append((addr, fp))
    return v


# ---------------------------------------------------------------- the manifest-only M3 node (auth none, no bees.config)
def manifest_only(manifest):
    """The M3 node with no bees.config: auth none, the loopback-only test setting. The manifest's peer hosts must be loopback
    (N1 (3)); the frame cap is BEAM's default (R1). -> the same shape bees_dist_gen takes from a Conf."""
    for name, host, port, role in manifest["peers"]:
        kind = addr_kind(host)
        where = f"peer {name}"
        if kind == "bad":
            raise ConfError(1, where, f'"{host}" is not an IPv4 or IPv6 literal or a host name', "(manifest)")
        if not is_loopback(host):
            raise ConfError(1, where, f"{host} is not a loopback address: a node built from the manifest alone is auth none, "
                            "a loopback-only test setting (no authentication, no encryption); write a bees.config", "(manifest)")
        if kind == "ipv6" and role == "dial":
            raise ConfError(1, where, f"{host} is not built yet: {CARRIER_DIAL_V6}", "(manifest)")
    return None


def m3_link(conf, manifest):
    """the link and the frame cap of a node's bees_peers (tools/bees_dist_gen.py) from a Conf, or from the manifest alone"""
    if conf is None:
        first = manifest["peers"][0]
        dials = first[3] == "dial"
        return {"frame_max": BEAM_FRAME_MAX, "link_dials": dials, "link_host": first[1], "link_port": first[2],
                "link_address": f"{first[1]}:{first[2]}" if dials else f"listen:{first[2]}",
                "link_resolve": dials and addr_kind(first[1]) == "name"}
    b = conf["beam"]
    return {"frame_max": b["frame_max"], "link_address": b["link_address"], "link_dials": b["link_dials"],
            "link_host": b["link_host"], "link_port": b["link_port"],
            "link_resolve": b["link_dials"] and b["link_host_kind"] == "name"}


# ---------------------------------------------------------------- command line
def main(argv):
    if len(argv) >= 3 and argv[1] == "check":
        manifest = None
        if len(argv) > 3:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import bees_dist_gen as D
            manifest = D.parse(argv[3:])
        try:
            conf = validate(argv[2], manifest)
        except ConfError as e:
            print(e.text)
            return 1
        for n in conf["notes"]:
            print(n)
        print("ok")
        return 0
    if len(argv) == 2 and argv[1] == "defaults":
        for row in defaults_rows():
            print(" | ".join(row))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
