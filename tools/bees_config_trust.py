#!/usr/bin/env python3
"""bees_config_trust: the TRUST-mode half of the `bees.config` reader (N3), written so that it can be merged with the BEAM-mode
half (N2) into the one reader of N0.2 (development-plan/bees-config-file.md). It owns the top-level `mode` check and every
`trust.*` option; the `beam` section is left to the BEAM half (its keys are not read here, see `BEAM_SECTION`).

    bees_config_trust.py conf -o OUT_DIR BEES_CONFIG     write OUT_DIR/bees_trust_conf.silica and OUT_DIR/bees_trust_conf.atoms
    bees_config_trust.py check BEES_CONFIG               validate only; print the verdict line (exit 1 on a boot error)

WHEN THE FILE IS READ (a stand-in, stated plainly). The design (D26) is a reader written in Silica that reads `bees.config` at boot.
Silica has no file reading yet (specification 22.6: read_file is not implemented) and N0.2 is not built, so this tool reads the
file, the whitelist, the pin file and the certificates **when the program is built**, and compiles the verdict into the generated
unit `bees_trust_conf`: either the effective values, or the one-line boot error `bees.config:LINE: PATH: MESSAGE`. The node's
startup (src/shim/bees_trust_node.part) asks `bees_trust_conf@boot_error()` FIRST and, when it is not empty, prints it and exits
with status 1 before any actor starts (validation rule 8, R2: never a silent standalone run). A change to any of these files
therefore needs a rebuild until the Silica reader exists. A generation error of the tool itself (a file it cannot write) fails
the build; everything the file says is a boot verdict, never a build failure, so trials can show the boot refusing.

What is checked (bees-config-file.md sections 3, 4 and 5.3): the grammar subset of section 4 (one term and a full stop; lists,
tuples, atoms, integers with `_`, strings, maps, `%` comments; at most 64 KiB); `mode` is `beam` or `trust` (default trust; the
list form is reserved and refused); unknown and duplicate keys at every level of the trust section; every type and bound of the
table in section 5.3, never clamped; `session.idle_ms =< session.max_age_ms`; `args_len_max =< frame_size_max`;
`dns_ns_timeout_ms =< dns_total_timeout_ms`; `listen_address` required in the trust section (R6, no default) when mode is trust;
`plaintext_test_only` only with a loopback listen address; mode trust without `plaintext_test_only` is "TRUST's TLS is not built"
(rule 9, until N4); a `frame_size_max` or `args_len_max` above what the build implements (4096 bytes until N1) is "not built yet";
`tls_opts` keys are `certfile`, `keyfile`, `cacertfile` only, all three required unless `plaintext_test_only` (with it, any
named file must exist; `certfile` names the test identity, below); every configured file exists and is readable
(`whitelist_file`, `server_pins_file`, the tls files), else a boot error naming the file and the cause (R2); the whitelist and the
pin file parse with the same reader. Paths are relative to the directory of `bees.config`.

The whitelist file is SEMP's: a map `#{"client-cert.pem" => Spec}` (or the list `[{"client-cert.pem", Spec}]`), certificates found
in `whitelist_cert_dir`; Spec is `none`, `any`, the code's list `[{Module, any} | {Module, [{Fun, Arity}]}]` or the README's map
`#{Module => all | any | [{Fun, Arity}]}`. A certificate an entry names that is missing is logged at boot and skipped, as SEMP does;
two entries with one fingerprint give a boot warning. **The fingerprint is the SHA-512 of the certificate's full DER (D11)**: for
a PEM file the DER inside it, for any other file its bytes. Under `plaintext_test_only` there is no TLS, so the peer presents a
**test-only stand-in**: the 64 bytes of a fingerprint, sent first on the connection (R5, accepted until TLS exists).

The pin file (BEES's, new relative to SEMP; its format is BEES's choice and open) is a map `#{"host:port" => "server-cert.pem"}`.
In N3 a trpc call to an address the file does not list returns `server_not_pinned`; the server's own fingerprint is not checked
(there is no server certificate without TLS; N4 does it). Each pinned server gets one client token cache (inter-nodal-modes 3.5).
"""
import hashlib
import os
import re
import sys

MAX_FILE = 65536
BUILD_FRAME_MAX = 4096          # what the build implements until N1 (bees-config-file.md 5.4)
BEAM_FRAME_MAX = 4294967295
BEAM_SECTION = "beam"           # read and validated by the BEAM-mode half (N2), not here
TOP_KEYS = ("mode", "node", "beam", "trust")


class ConfError(Exception):
    def __init__(self, line, path, msg, fname="bees.config"):
        super().__init__(f"{fname}:{line}: {path}: {msg}")
        self.text = f"{fname}:{line}: {path}: {msg}"


# ---------------------------------------------------------------- the reader (section 4's grammar)
class Atom(str):
    pass


class Node:
    """a parsed term with the line it starts on"""
    def __init__(self, kind, value, line):
        self.kind, self.value, self.line = kind, value, line   # kind: atom int str list tuple map

    def __repr__(self):
        return f"{self.kind}:{self.value!r}"


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

    def term(self):
        c = self.peek()
        line = self.line
        if c == "[":
            self.i += 1
            items = []
            if self.peek() == "]":
                self.i += 1
                return Node("list", items, line)
            while True:
                items.append(self.term())
                if self.peek() == ",":
                    self.i += 1
                    continue
                self.expect("]")
                return Node("list", items, line)
        if c == "{":
            self.i += 1
            items = []
            if self.peek() == "}":
                self.i += 1
                return Node("tuple", items, line)
            while True:
                items.append(self.term())
                if self.peek() == ",":
                    self.i += 1
                    continue
                self.expect("}")
                return Node("tuple", items, line)
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
                    m = {"n": "\n", "t": "\t", "\\": "\\", '"': '"'}
                    if nxt not in m:
                        self.err("unsupported escape in a string")
                    out.append(m[nxt])
                    self.i += 2
                    continue
                if not (32 <= ord(ch) <= 126):
                    self.err("a string may hold ASCII 32 to 126 only")
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
        m = re.compile(r"-?[0-9](_?[0-9])*").match(self.s, self.i)
        if m and (c.isdigit() or c == "-"):
            self.i = m.end()
            if self.i < len(self.s) and self.s[self.i] in ".eE" and self.s[self.i + 1:self.i + 2].isdigit():
                self.err("floats are not accepted")
            return Node("int", int(m.group(0).replace("_", "")), line)
        m = re.compile(r"[a-z][A-Za-z0-9_@]*").match(self.s, self.i)
        if m:
            self.i = m.end()
            return Node("atom", Atom(m.group(0)), line)
        if c == "":
            self.err("unexpected end of file")
        self.err(f"unexpected character '{c}' (variables, binaries, funs, macros and records are not accepted)")

    def whole(self):
        if len(self.s.encode()) > MAX_FILE:
            raise ConfError(1, "(file)", f"larger than {MAX_FILE} bytes", self.fname)
        if any(ord(ch) > 127 for ch in self.s):
            raise ConfError(1, "(file)", "non-ASCII bytes are not accepted", self.fname)
        t = self.term()
        self.expect(".")
        if self.peek() != "":
            self.err("text after the term's full stop (a file is one term)")
        return t


def read_file(path, fname):
    with open(path, "r", encoding="latin-1") as fh:
        return Reader(fh.read(), fname).whole()


# ---------------------------------------------------------------- the trust options (section 5.3)
def opt_int(lo, hi):
    return ("int", lo, hi)


TRUST_OPTS = {
    "port": (opt_int(1, 65535), 6469),
    "listen_address": (("str",), None),
    "tls_opts": (("tls",), None),
    "client_tls_opts": (("tls",), None),
    "whitelist_file": (("str",), None),
    "whitelist_cert_dir": (("str",), "certs"),
    "whitelist_default_spec": (("spec",), "none"),
    "whitelist_autoload": (("bool",), False),
    "server_pins_file": (("str",), None),
    "call_timeout_ms": (opt_int(1, 600000), 5000),
    "suspicion_limit": (opt_int(0, 1000), 3),
    "token_bytes": (opt_int(32, 64), 48),
    "token_ttl_sec": (opt_int(10, 3600), 300),
    "dns_ns_timeout_ms": (opt_int(100, 30000), 2000),
    "dns_total_timeout_ms": (opt_int(100, 60000), 5000),
    "connect_timeout_ms": (opt_int(100, 60000), 3000),
    "connect_stagger_ms": (opt_int(0, 5000), 250),
    "client_handshake_timeout": (opt_int(1000, 30000), 5000),
    "first_frame_timeout_ms": (opt_int(100, 10000), 2000),
    "frame_size_max": (opt_int(512, BEAM_FRAME_MAX), BEAM_FRAME_MAX),
    "args_len_max": (opt_int(0, BEAM_FRAME_MAX), None),          # default: frame_size_max
    "term_depth_max": (opt_int(1, 128), 32),
    "session": (("session",), None),
    "acceptors": (opt_int(1, 1024), None),
    "session_slots_max": (opt_int(1, 1000000), None),
    "plaintext_test_only": (("bool",), False),
}
SESSION_OPTS = {
    "max_inflight": ((1, 64), 8), "max_age_ms": ((1000, 3600000), 60000), "idle_ms": ((100, 600000), 5000),
    "max_calls": ((1, 100000), 100), "drain_ms": ((0, 60000), 1000),
}
TLS_KEYS = ("certfile", "keyfile", "cacertfile")
SEMP_RENAMED = {"token_ttl_ms": "token_ttl_sec (seconds; bees-config-file.md section 7)",
                "rpc_api": "nothing: the module table is built at build time", "host_app": "nothing: paths are relative to bees.config",
                "unsafe": "nothing", "unsafe_cookie": "nothing", "alpn": "nothing: the ALPN is fixed at trust/1"}


def proplist(node, path, allowed=None):
    """a list of {atom, value} pairs -> dict key -> (value node, line); unknown and duplicate keys refused"""
    if node.kind != "list":
        raise ConfError(node.line, path, "expected a list of {key, value} pairs")
    out = {}
    for item in node.value:
        if item.kind != "tuple" or len(item.value) != 2 or item.value[0].kind != "atom":
            raise ConfError(item.line, path, "expected a {key, value} pair with an atom key")
        k = str(item.value[0].value)
        if allowed is not None and k not in allowed:
            hint = f" (SEMP's {k} is {SEMP_RENAMED[k]})" if k in SEMP_RENAMED else ""
            raise ConfError(item.line, f"{path}.{k}", "unknown key" + hint)
        if k in out:
            raise ConfError(item.line, f"{path}.{k}", "duplicate key")
        out[k] = (item.value[1], item.line)
    return out


def want_int(node, path, lo, hi):
    if node.kind != "int":
        raise ConfError(node.line, path, "expected an integer")
    if not lo <= node.value <= hi:
        raise ConfError(node.line, path, f"{node.value} is outside {lo} to {hi}")
    return node.value


def want_str(node, path):
    if node.kind != "str":
        raise ConfError(node.line, path, "expected a string")
    return node.value


def want_bool(node, path):
    if node.kind != "atom" or node.value not in ("true", "false"):
        raise ConfError(node.line, path, "expected true or false")
    return node.value == "true"


def parse_spec(node, path):
    """-> 'none' | 'any' | {module: 'any' | [(f, a)]}"""
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


def check_file(base, rel, line, path, notes, what):
    full = os.path.normpath(os.path.join(base, rel))
    if not os.path.exists(full):
        raise ConfError(line, path, f'{what} "{rel}" does not exist (relative to the directory of bees.config)')
    if not os.path.isfile(full):
        raise ConfError(line, path, f'{what} "{rel}" is not a file (relative to the directory of bees.config)')
    if not os.access(full, os.R_OK):
        raise ConfError(line, path, f'{what} "{rel}" is not readable (permissions) (relative to the directory of bees.config)')
    try:
        with open(full, "rb") as fh:
            fh.read(1)
    except OSError as e:
        raise ConfError(line, path, f'{what} "{rel}" cannot be read: {e.strerror} (relative to the directory of bees.config)')
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


def is_loopback(addr):
    return addr == "127.0.0.1" or addr.startswith("127.") or addr == "::1" or addr == "localhost"


def validate(cfg_path):
    """-> dict of effective values; raises ConfError for a boot error"""
    base = os.path.dirname(os.path.abspath(cfg_path))
    notes = []
    try:
        top = read_file(cfg_path, "bees.config")
    except FileNotFoundError:
        raise ConfError(0, "(file)", f"bees.config not found ({cfg_path})")
    top_d = proplist(top, "(top)", TOP_KEYS)
    mode = "trust"
    if "mode" in top_d:
        mnode, line = top_d["mode"]
        if mnode.kind == "list":
            raise ConfError(line, "mode", "the list form is reserved (one mode per node, section 3.1)")
        if mnode.kind != "atom" or mnode.value not in ("beam", "trust"):
            raise ConfError(line, "mode", "expected beam or trust")
        mode = str(mnode.value)
    tr = proplist(top_d["trust"][0], "trust", TRUST_OPTS) if "trust" in top_d else {}
    v = {"mode": mode}
    for k, (kind, default) in TRUST_OPTS.items():
        if k not in tr:
            v[k] = default
            continue
        node, line = tr[k]
        p = f"trust.{k}"
        if kind[0] == "int":
            v[k] = want_int(node, p, kind[1], kind[2])
        elif kind[0] == "str":
            v[k] = want_str(node, p)
        elif kind[0] == "bool":
            v[k] = want_bool(node, p)
        elif kind[0] == "spec":
            v[k] = parse_spec(node, p)
        elif kind[0] == "tls":
            d = proplist(node, p, TLS_KEYS)
            v[k] = {kk: (want_str(vv, f"{p}.{kk}"), ln) for kk, (vv, ln) in d.items()}
        elif kind[0] == "session":
            if node.kind != "map":
                raise ConfError(line, p, "expected a map of max_inflight, max_age_ms, idle_ms, max_calls, drain_ms")
            sess = {}
            for kn, vn in node.value:
                if kn.kind != "atom" or str(kn.value) not in SESSION_OPTS:
                    raise ConfError(kn.line, f"{p}.{kn.value}", "unknown key")
                if str(kn.value) in sess:
                    raise ConfError(kn.line, f"{p}.{kn.value}", "duplicate key")
                lo, hi = SESSION_OPTS[str(kn.value)][0]
                sess[str(kn.value)] = want_int(vn, f"{p}.{kn.value}", lo, hi)
            v[k] = sess
    lines = {k: tr[k][1] for k in tr}
    sess = {k: d for k, (_, d) in SESSION_OPTS.items()}
    sess.update(v["session"] or {})
    v["session"] = sess
    if sess["idle_ms"] > sess["max_age_ms"]:
        raise ConfError(lines.get("session", 0), "trust.session.idle_ms", f"{sess['idle_ms']} is above max_age_ms {sess['max_age_ms']}")
    if v["args_len_max"] is None:
        v["args_len_max"] = v["frame_size_max"]
    if v["args_len_max"] > v["frame_size_max"]:
        raise ConfError(lines.get("args_len_max", 0), "trust.args_len_max", f"{v['args_len_max']} is above frame_size_max {v['frame_size_max']}")
    if v["dns_ns_timeout_ms"] > v["dns_total_timeout_ms"]:
        raise ConfError(lines.get("dns_ns_timeout_ms", 0), "trust.dns_ns_timeout_ms", "is above dns_total_timeout_ms")
    for k in ("frame_size_max", "args_len_max"):
        if k in lines and v[k] > BUILD_FRAME_MAX:
            raise ConfError(lines[k], f"trust.{k}", f"{v[k]} is not built yet: this build implements {BUILD_FRAME_MAX} bytes until N1 (never clamped)")
    v["frame_eff"] = min(v["frame_size_max"], BUILD_FRAME_MAX)
    v["args_eff"] = min(v["args_len_max"], v["frame_eff"])
    if mode != "trust":
        v["active"] = False
        return v, notes
    v["active"] = True
    if v["listen_address"] is None:
        raise ConfError(top_d["trust"][1] if "trust" in top_d else 0, "trust.listen_address", "required in mode trust; there is no default (R6)")
    if not v["plaintext_test_only"]:
        raise ConfError(lines.get("plaintext_test_only", top_d["trust"][1] if "trust" in top_d else 0), "trust.plaintext_test_only",
                        "TRUST's TLS is not built (N4): mode trust needs {plaintext_test_only, true} until it is")
    if not is_loopback(v["listen_address"]):
        raise ConfError(lines["listen_address"], "trust.listen_address", "plaintext_test_only binds a loopback address only")
    if v["listen_address"] != "127.0.0.1":
        raise ConfError(lines["listen_address"], "trust.listen_address", "the language's carrier listens on 127.0.0.1 only (N1 open)")
    for k in ("tls_opts", "client_tls_opts"):
        if v[k] is not None:
            for kk, (rel, ln) in v[k].items():
                check_file(base, rel, ln, f"trust.{k}.{kk}", notes, "file")
    certdir = os.path.join(base, v["whitelist_cert_dir"])
    # the node's own test identity (the stand-in fingerprint it presents as a client): client_tls_opts, else tls_opts, certfile
    own = (v["client_tls_opts"] or v["tls_opts"] or {}).get("certfile")
    v["self_fp"] = fingerprint(os.path.join(base, own[0])) if own else ""
    # whitelist (R2: configured and missing, unreadable or unparseable is a boot error)
    v["peers"] = []
    if v["whitelist_file"] is not None:
        wl_full = check_file(base, v["whitelist_file"], lines["whitelist_file"], "trust.whitelist_file", notes, "whitelist file")
        try:
            wl = read_file(wl_full, v["whitelist_file"])
        except ConfError as e:
            raise ConfError(lines["whitelist_file"], "trust.whitelist_file", f'whitelist file "{v["whitelist_file"]}" does not parse: {e.text}')
        entries = []
        if wl.kind == "map":
            entries = list(wl.value)
        elif wl.kind == "list":
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
    else:
        notes.append("TRUST standalone: no whitelist file configured, no inbound connections accepted")
    v["servers"] = []
    if v["server_pins_file"] is not None:
        pf = check_file(base, v["server_pins_file"], lines["server_pins_file"], "trust.server_pins_file", notes, "pin file")
        try:
            pins = read_file(pf, v["server_pins_file"])
        except ConfError as e:
            raise ConfError(lines["server_pins_file"], "trust.server_pins_file", f'pin file "{v["server_pins_file"]}" does not parse: {e.text}')
        if pins.kind != "map":
            raise ConfError(pins.line, "(pins)", "the pin file is a map #{\"host:port\" => \"server-cert.pem\"}", v["server_pins_file"])
        for kn, cn in pins.value:
            addr = want_str(kn, f"{v['server_pins_file']}: address")
            if not re.fullmatch(r"[^:]+:[0-9]{1,5}", addr):
                raise ConfError(kn.line, "(pins)", f"{addr} is not host:port", v["server_pins_file"])
            cert = want_str(cn, f"{v['server_pins_file']}: {addr}")
            cpath = os.path.join(certdir, cert)
            fp = fingerprint(cpath) if os.path.isfile(cpath) else ""
            v["servers"].append((addr, fp))
    return v, notes


# ---------------------------------------------------------------- the generated unit
def sstr(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def chain(var, items, default):
    """case var == key of { true -> val; false -> ... } over (key, val) pairs"""
    e = default
    for k, val in reversed(items):
        e = f"case {var} == {sstr(k)} of {{ true -> {val}; false -> {e} }}"
    return e


def perm_expr(spec):
    if spec == "none":
        return "false"
    if spec == "any":
        return "true"
    parts = []
    for mod, fas in sorted(spec.items()):
        if fas == "any":
            parts.append(f'ms == {sstr(mod)}')
        elif fas:
            alts = " or ".join(f'(fs == {sstr(f)} and a == {a})' for f, a in fas)
            parts.append(f'(ms == {sstr(mod)} and ({alts}))')
    return " or ".join(parts) if parts else "false"


def gen(out_dir, v, notes, err):
    L = ["// Generated by tools/bees_config_trust.py from bees.config (and its whitelist and pin files) WHEN THE PROGRAM WAS BUILT.",
         "// Do not edit. The Silica reader of N0.2 does not exist yet, so the verdict of the file is compiled in; the node's startup",
         "// asks boot_error() first and refuses to start when it is not empty (R2). TEST ONLY while plaintext_test_only is the only",
         "// transport: the peer identity is a test-supplied stand-in for the certificate fingerprint (R5).",
         "module bees_trust_conf;", "use bees_atoms;", ""]
    ex = ["boot_error/0", "note_count/0", "note/1", "summary/0", "active/0", "listens/0", "port/0", "listen_spec/0",
          "call_timeout_ms/0", "first_frame_timeout_ms/0", "handshake_timeout_ms/0", "connect_timeout_ms/0",
          "suspicion_limit/0", "token_bytes/0", "token_ttl_ns/0", "frame_size_max/0", "args_len_max/0", "term_depth_max/0",
          "peer_count/0", "peer_index/1", "peer_hex/1", "peer_name/1", "permitted/4",
          "server_count/0", "server_index/1", "server_name/1", "self_fp/0"]
    L += [f"export {e};" for e in ex] + [""]
    ok = err is None
    L.append(f"fn boot_error() -> string {{ {sstr(err or '')} }}")
    notes = notes if ok else []
    L.append(f"fn note_count() -> int64 {{ {len(notes)} }}")
    L.append("fn note(i: int64) -> string {")
    L.append("    case i of {")
    for i, n in enumerate(notes):
        L.append(f"        {i} -> {sstr(n)};")
    L.append('        _: int64 -> ""')
    L += ["    }", "}"]
    g = (lambda k, d=0: v.get(k, d)) if ok else (lambda k, d=0: d)
    peers = g("peers", [])
    servers = g("servers", [])
    summ = ""
    if ok:
        summ = (f"[trust] mode {v['mode']}, listen {v['listen_address']}:{v['port']}, whitelist {len(peers)} entries, "
                f"pinned servers {len(servers)}, frame_size_max {v['frame_eff']} (build limit {BUILD_FRAME_MAX} until N1), "
                f"args_len_max {v['args_eff']}, term_depth_max {v['term_depth_max']}, call_timeout_ms {v['call_timeout_ms']}, "
                f"first_frame_timeout_ms {v['first_frame_timeout_ms']}, suspicion_limit {v['suspicion_limit']}, "
                f"token_bytes {v['token_bytes']}, token_ttl_sec {v['token_ttl_sec']}, one request per connection (B1)")
    L.append(f"fn summary() -> string {{ {sstr(summ)} }}")
    L.append(f"fn active() -> boolean {{ {'true' if ok and v['active'] else 'false'} }}")
    L.append(f"fn listens() -> boolean {{ {'true' if ok and v['active'] and v['whitelist_file'] is not None else 'false'} }}")
    L.append(f"fn port() -> int64 {{ {g('port', 0)} }}")
    L.append(f"fn listen_spec() -> string {{ {sstr('listen:' + str(g('port', 0)))} }}")
    for name, key in (("call_timeout_ms", "call_timeout_ms"), ("first_frame_timeout_ms", "first_frame_timeout_ms"),
                      ("handshake_timeout_ms", "client_handshake_timeout"), ("connect_timeout_ms", "connect_timeout_ms")):
        L.append(f"fn {name}() -> uint64 {{ {g(key, 1000)} }}")
    L.append(f"fn suspicion_limit() -> int64 {{ {g('suspicion_limit', 0)} }}")
    L.append(f"fn token_bytes() -> int64 {{ {g('token_bytes', 48)} }}")
    L.append(f"fn token_ttl_ns() -> int64 {{ {g('token_ttl_sec', 300) * 1000000000} }}")
    L.append(f"fn frame_size_max() -> int64 {{ {g('frame_eff', 512)} }}")
    L.append(f"fn args_len_max() -> int64 {{ {g('args_eff', 0)} }}")
    L.append(f"fn term_depth_max() -> int64 {{ {g('term_depth_max', 1)} }}")
    L.append(f"fn peer_count() -> int64 {{ {len(peers)} }}")
    L.append(f"fn peer_index(h: string) -> int64 {{ {chain('h', [(fp, str(i)) for i, (_, fp, _) in enumerate(peers)], '0 - 1')} }}")
    L.append("fn peer_hex(i: int64) -> string {")
    L.append("    case i of {")
    for i, (_, fp, _) in enumerate(peers):
        L.append(f"        {i} -> {sstr(fp)};")
    L.append('        _: int64 -> "-"')
    L += ["    }", "}"]
    L.append("fn peer_name(i: int64) -> atom {")
    L.append("    case i of {")
    for i in range(len(peers)):
        L.append(f"        {i} -> bees_atoms@a_bees_trust_peer_{i}();")
    L.append("        _: int64 -> bees_atoms@a_error()")
    L += ["    }", "}"]
    L.append("// the permission gate (inter-nodal-modes 3.3): the whitelist spec of the peer's fingerprint; the forbidden guard runs first")
    for i, (cert, _, spec) in enumerate(peers):
        L.append(f"// {i}: {cert}")
        L.append(f"fn perm_{i}(ms: string, fs: string, a: int64) -> boolean {{ {perm_expr(spec)} }}")
    L.append("fn permitted(i: int64, m: atom, f: atom, a: int64) -> boolean {")
    L.append("    case i of {")
    for i in range(len(peers)):
        L.append(f"        {i} -> perm_{i}(bees_atoms@spelling(m), bees_atoms@spelling(f), a);")
    L.append("        _: int64 -> false")
    L += ["    }", "}"]
    L.append(f"fn server_count() -> int64 {{ {len(servers)} }}")
    L.append(f"fn server_index(addr: string) -> int64 {{ {chain('addr', [(a, str(i)) for i, (a, _) in enumerate(servers)], '0 - 1')} }}")
    L.append("fn server_name(i: int64) -> atom {")
    L.append("    case i of {")
    for i in range(len(servers)):
        L.append(f"        {i} -> bees_atoms@a_bees_trust_srv_{i}();")
    L.append("        _: int64 -> bees_atoms@a_error()")
    L += ["    }", "}"]
    fp = g("self_fp", "")
    if fp:
        bs = ", ".join(str(b) for b in bytes.fromhex(fp))
        L += ["// the node's own TEST-ONLY identity: the stand-in fingerprint it sends first as a client (R5)",
              "fn self_fp() -> string {", "    sequence proc[mem(normal), transport]",
              f"        xs: List[int64, mem(normal)] <- [{bs}];", "        s: string <- bytes_of(xs)", "    produces pure s end", "}"]
    else:
        L.append('fn self_fp() -> string { "" }')
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "bees_trust_conf.silica"), "w") as fh:
        fh.write("\n".join(L) + "\n")
    with open(os.path.join(out_dir, "bees_trust_conf.atoms"), "w") as fh:
        fh.write("# generated by tools/bees_config_trust.py: the registered names of the per-fingerprint and per-server actors\n")
        fh.write("error\n")
        for i in range(len(peers)):
            fh.write(f"bees_trust_peer_{i}\n")
        for i in range(len(servers)):
            fh.write(f"bees_trust_srv_{i}\n")


def run(cfg):
    try:
        v, notes = validate(cfg)
        return v, notes, None
    except ConfError as e:
        return {}, [], e.text


def main(argv):
    if len(argv) == 5 and argv[1] == "conf" and argv[2] == "-o":
        v, notes, err = run(argv[4])
        gen(argv[3], v, notes, err)
        return 0
    if len(argv) == 3 and argv[1] == "check":
        v, notes, err = run(argv[2])
        if err:
            print(err)
            return 1
        for n in notes:
            print(n)
        print("ok")
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
