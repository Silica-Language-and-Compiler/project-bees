#!/usr/bin/env python3
"""bees_pack: the configuration packer (D46; development-plan/bees-config-file.md section 12; spikes/N0d-store-config.md).

Run at deploy time. It reads `bees.config` and what that file names (the whitelist, the pin file, the certificates, the
key, the cookie), validates everything with THE reader (tools/bees_conf.py, so a refusal is the same one line
`bees.config:LINE: PATH: MESSAGE`), and writes the configuration as ETF records in the on-medium form of Silica's hosted
(:store) carrier (tools/bees_pack_store.py). The application declares that store, replays it and decodes each record with
`decode((:etf), ...)`; no C code reads a file.

    bees_pack.py pack --config bees.config --capacity BYTES -o node.sildat [MANIFEST.wire ...]
    bees_pack.py show node.sildat          the records of a packed store, secrets shown as their length only
    bees_pack.py shapes                    the record set (kind, schema number, fields), as text

--capacity is the capacity literal of the application's `carried_on` declaration (a multiple of 4096): a backing of
another size is refused by the carrier with (:link_down, :mismatch). It has no default.

THE RECORD SET (version 1). One stored frame per record; the frame's schema number says which record it is. Every record
is a Silica record of at most four fields (nested for more: the derived decoder of the pinned compiler takes four, SD-37),
written as an ETF map with atom keys. Values are integers, byte strings and booleans only, so a decode needs no atom beyond
the field names and true/false. The first record is the index: it names the format, its version, the mode and how many
frames follow, so a reader can refuse a store that lost its first block or its tail.

Addresses are written twice where a carrier needs them: Silica has no integer-to-text conversion, so the packer writes the
carrier's address form ("listen:PORT", "HOST:PORT") beside the numbers.

SECRETS. The cookie and the private key pass through the store like the rest (D46). The packer writes the backing with
mode 0600, never prints a secret (`show` prints lengths), and keeps no copy.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bees_conf                    # noqa: E402
import bees_pack_store as store     # noqa: E402
from bees_pack_store import Atom    # noqa: E402

FORMAT_KIND = "bees.config"
FORMAT_VERSION = 1
CEILING = 4294967295                # D47: the most BEES ever decodes, and the most a configuration may ask for
MS = 2147483647
PORT = 65535

# ---- the record set: one table for the packer, the generated Silica readers (tools/bees_pack_gen.py) and the document ----
# field: (name, kind, lo, hi[, sub]) with kind int | str | secret | bool | rec | list. For int, lo..hi bound the value; for
# str and secret, the length in bytes; rec and list carry their fields in sub (a list is a list of records).


def I(name, lo, hi):
    return (name, "int", lo, hi)


def S(name, lo, hi):
    return (name, "str", lo, hi)


def B(name):
    return (name, "bool", 0, 1)


INDEX = ("index", 1, "once", [I("frames", 1, 65535), S("kind", 1, 32), S("mode", 1, 8), I("version", 1, 1)])
NODE = ("node", 2, "once", [I("creation", 0, CEILING), S("name", 1, 255)])

BEAM = [
    ("net", 10, "once", [("epmd", "rec", 0, 0, [S("mode", 1, 16), I("port", 0, PORT)]),
                         S("listen_address", 0, 255), I("listen_port", 0, PORT), S("listener", 0, 280)]),
    ("time", 11, "once", [I("frame_max", 1, CEILING), I("io_ms", 0, MS), I("open_ms", 0, MS), I("tick_ms", 0, MS)]),
    ("auth", 12, "once", [S("auth", 1, 16), ("cookie", "secret", 0, 255),
                          ("redial", "rec", 0, 0, [I("initial_ms", 0, MS), I("max_ms", 0, MS), B("on")]), S("transport", 1, 16)]),
    ("link", 13, "many", [S("address", 0, 280), S("host", 0, 255),
                          ("how", "rec", 0, 0, [B("by_epmd"), B("dials"), I("port", 0, PORT), B("resolve")]), S("name", 1, 255)]),
]

TRUST = [
    ("net", 20, "once", [S("listen_address", 0, 255), S("listener", 0, 280), B("plaintext_test_only"), I("port", 0, PORT)]),
    ("limits", 21, "once", [I("args_len_max", 1, CEILING), I("frame_size_max", 1, CEILING), I("suspicion_limit", 0, MS),
                            I("term_depth_max", 1, 65535)]),
    ("time", 22, "once", [I("call_timeout_ms", 0, MS), I("connect_stagger_ms", 0, MS), I("connect_timeout_ms", 0, MS),
                          ("more", "rec", 0, 0, [I("client_handshake_timeout", 0, MS), I("dns_ns_timeout_ms", 0, MS),
                                                 I("dns_total_timeout_ms", 0, MS), I("first_frame_timeout_ms", 0, MS)])]),
    ("token", 23, "once", [I("token_bytes", 0, 65535), I("token_ttl_sec", 0, MS), B("whitelist_autoload"),
                           S("whitelist_default_spec", 1, 16)]),
    ("session", 24, "once", [I("idle_ms", 0, MS), I("max_age_ms", 0, MS), I("max_inflight", 0, MS),
                             ("more", "rec", 0, 0, [I("drain_ms", 0, MS), I("max_calls", 0, MS)])]),
    ("tls", 25, "once", [S("ca_pem", 0, 65536), S("cert_pem", 0, 65536), ("key_pem", "secret", 0, 65536), S("self_fp", 0, 128)]),
    ("peer", 26, "many", [S("cert", 0, 255), B("classical"), S("fp", 128, 128),
                          ("spec", "rec", 0, 0, [S("all", 1, 8), ("perms", "list", 0, 4096, [I("a", -1, 255), S("f", 0, 255), S("m", 1, 255)])])]),
    ("pin", 27, "many", [S("addr", 3, 280), S("fp", 0, 128)]),
]

# cross-field rules the Silica reader repeats (bees-config-file.md section 4 rule 6): (mode, group, lower field, upper field)
CROSS = [("trust", "limits", "args_len_max", "frame_size_max"), ("trust", "session", "idle_ms", "max_age_ms")]

GROUPS = {"beam": [INDEX, NODE] + BEAM, "trust": [INDEX, NODE] + TRUST}


def by_schema(mode):
    return {g[1]: g for g in GROUPS[mode]}


class PackError(Exception):
    pass


def _check(path, fields, value):
    """The value has exactly the table's fields, in bounds. The Silica reader makes the same checks after decode."""
    if not isinstance(value, dict) or set(value) != {f[0] for f in fields}:
        raise PackError(f"{path}: fields {sorted(value)} are not {sorted(f[0] for f in fields)}")
    for f in fields:
        name, kind, lo, hi = f[:4]
        v, p = value[name], f"{path}.{name}"
        if kind == "int":
            if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
                raise PackError(f"{p}: outside {lo}..{hi}")
        elif kind in ("str", "secret"):
            if isinstance(v, str):
                v = v.encode("utf-8")
            if not isinstance(v, bytes) or not lo <= len(v) <= hi:
                raise PackError(f"{p}: length outside {lo}..{hi}")
        elif kind == "bool":
            if not isinstance(v, bool):
                raise PackError(f"{p}: not a boolean")
        elif kind == "rec":
            _check(p, f[4], v)
        elif kind == "list":
            if not isinstance(v, list) or len(v) > hi:
                raise PackError(f"{p}: more than {hi} entries")
            for x in v:
                _check(p, f[4], x)


def _atoms(fields, value):
    out = {}
    for f in fields:
        name, kind = f[0], f[1]
        v = value[name]
        if kind == "rec":
            v = _atoms(f[4], v)
        elif kind == "list":
            v = [_atoms(f[4], x) for x in v]
        out[Atom(name)] = v
    return out


def _read(path, what):
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError as e:
        raise PackError(f"{what} {path}: cannot be read: {e.strerror}")


def _spec(spec):
    if isinstance(spec, str):
        return {"all": spec, "perms": []}
    perms = []
    for module, funs in spec.items():
        if funs == "any":
            perms.append({"m": str(module), "f": "", "a": -1})          # every function of the module
        else:
            perms.extend({"m": str(module), "f": str(f), "a": int(a)} for f, a in funs)
    return {"all": "list", "perms": perms}


def beam_records(conf):
    b, node = conf["beam"], conf["node"]
    cookie = b""
    if b["auth"] == "cookie":
        cookie = _read(b["cookie_path"], "cookie file").strip()
    recs = [(2, {"name": node["name"], "creation": node["creation"]}),
            (10, {"listen_address": b["listen_address"] or "", "listen_port": b["link_port"] if b["listens"] else 0,
                  "listener": b["listener_address"] if b["listens"] else "",
                  "epmd": {"mode": b["epmd"], "port": b["epmd_port"]}}),
            (11, {"frame_max": b["frame_max"], "io_ms": b["io_ms"], "open_ms": b["open_ms"], "tick_ms": b["tick_ms"]}),
            (12, {"auth": b["auth"], "transport": b["transport"], "cookie": cookie,
                  "redial": {"on": bool(b["redial"]), "initial_ms": b["redial_initial_ms"], "max_ms": b["redial_max_ms"]}})]
    for link in b["links"]:
        recs.append((13, {"name": link["name"], "host": link["host"] or "", "address": link["address"] or "",
                          "how": {"dials": bool(link["dials"]), "by_epmd": bool(link["by_epmd"]), "port": link["port"] or 0,
                                  "resolve": bool(link["resolve"])}}))
    return recs


def trust_records(conf):
    t, node = conf["trust"], conf["node"]
    s = t["session"]
    tls = {"cert_pem": b"", "key_pem": b"", "ca_pem": b"", "self_fp": t.get("self_fp") or ""}
    if t["tls"]:
        for (opt, key), path in t["tls_paths"].items():
            if opt != "tls_opts":
                continue
            field = {"certfile": "cert_pem", "keyfile": "key_pem", "cacertfile": "ca_pem"}.get(key)
            if field:
                tls[field] = _read(path, f"trust.tls_opts.{key}")
    recs = [(2, {"name": node["name"], "creation": node["creation"]}),
            (20, {"listen_address": t["listen_address"] or "", "port": t["port"],
                  "listener": f'{t["listen_prefix"]}{t["port"]}' if t["listen_address"] else "",
                  "plaintext_test_only": bool(t["plaintext_test_only"])}),
            (21, {"frame_size_max": t["frame_eff"], "args_len_max": t["args_eff"], "term_depth_max": t["term_depth_max"],
                  "suspicion_limit": t["suspicion_limit"]}),
            (22, {"call_timeout_ms": t["call_timeout_ms"], "connect_timeout_ms": t["connect_timeout_ms"],
                  "connect_stagger_ms": t["connect_stagger_ms"],
                  "more": {"client_handshake_timeout": t["client_handshake_timeout"], "first_frame_timeout_ms": t["first_frame_timeout_ms"],
                           "dns_ns_timeout_ms": t["dns_ns_timeout_ms"], "dns_total_timeout_ms": t["dns_total_timeout_ms"]}}),
            (23, {"token_bytes": t["token_bytes"], "token_ttl_sec": t["token_ttl_sec"],
                  "whitelist_default_spec": t["whitelist_default_spec"], "whitelist_autoload": bool(t["whitelist_autoload"])}),
            (24, {"max_inflight": s["max_inflight"], "max_age_ms": s["max_age_ms"], "idle_ms": s["idle_ms"],
                  "more": {"max_calls": s["max_calls"], "drain_ms": s["drain_ms"]}}),
            (25, tls)]
    classical = t.get("peer_classical") or []
    for i, (cert, fp, spec) in enumerate(t.get("peers") or []):
        recs.append((26, {"cert": cert, "fp": fp, "classical": bool(classical[i]) if i < len(classical) else False, "spec": _spec(spec)}))
    for addr, fp in t.get("servers") or []:
        recs.append((27, {"addr": addr, "fp": fp}))
    return recs


def records(conf):
    """The whole store for a validated Conf: [(schema, value)], the index first."""
    mode = conf["mode"]
    body = beam_records(conf) if mode == "beam" else trust_records(conf)
    table = by_schema(mode)
    for schema, value in body:
        name, _, _, fields = table[schema]
        _check(f"{mode}.{name}", fields, value)
    for m, group, low, high in CROSS:
        for schema, value in body:
            if m == mode and table[schema][0] == group and value[low] > value[high]:
                raise PackError(f"{mode}.{group}.{low}: above {high}")
    index = {"kind": FORMAT_KIND, "version": FORMAT_VERSION, "mode": mode, "frames": len(body) + 1}
    _check("index", INDEX[3], index)
    return [(1, index)] + body


def image(recs, mode, capacity):
    table = by_schema(mode)
    img = store.Image(capacity)
    for schema, value in recs:
        img.append_value(schema, _atoms(table[schema][3], value))
    return img


def pack(config, manifests, capacity, out):
    manifest = None
    if manifests:
        import bees_dist_gen
        manifest = bees_dist_gen.parse(manifests)
    conf = bees_conf.validate(config, manifest)
    recs = records(conf)
    data = image(recs, conf["mode"], capacity).bytes()
    tmp = out + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    os.chmod(tmp, 0o600)
    os.replace(tmp, out)
    return conf, recs


# ---- show: a packed store, without its secrets ----
def _decode(data, at=0):
    """A minimal ETF reader for what the packer writes -> (value, next)."""
    import struct
    tag = data[at]
    if tag == 97:
        return data[at + 1], at + 2
    if tag == 98:
        return struct.unpack(">i", data[at + 1:at + 5])[0], at + 5
    if tag == 110:
        n, sign = data[at + 1], data[at + 2]
        v = int.from_bytes(data[at + 3:at + 3 + n], "little")
        return (-v if sign else v), at + 3 + n
    if tag == 119:
        n = data[at + 1]
        name = data[at + 2:at + 2 + n].decode()
        return (name == "true") if name in ("true", "false") else Atom(name), at + 2 + n
    if tag == 109:
        n = struct.unpack(">I", data[at + 1:at + 5])[0]
        return data[at + 5:at + 5 + n], at + 5 + n
    if tag == 106:
        return [], at + 1
    if tag == 108:
        n = struct.unpack(">I", data[at + 1:at + 5])[0]
        at += 5
        out = []
        for _ in range(n):
            v, at = _decode(data, at)
            out.append(v)
        return out, at + 1
    if tag == 116:
        n = struct.unpack(">I", data[at + 1:at + 5])[0]
        at += 5
        out = {}
        for _ in range(n):
            k, at = _decode(data, at)
            v, at = _decode(data, at)
            out[str(k)] = v
        return out, at
    raise PackError(f"tag {tag} is not one the packer writes")


def _lines(path, fields, value, out):
    for f in fields:
        name, kind = f[0], f[1]
        v, p = value[name], f"{path}.{name}"
        if kind == "secret":
            out.append(f"{p} = (secret, {len(v)} bytes)")
        elif kind == "str":
            text = v.decode("utf-8", "replace")
            out.append(f"{p} = ({len(v)} bytes)" if len(v) > 160 or "\n" in text else f'{p} = "{text}"')
        elif kind == "rec":
            _lines(p, f[4], v, out)
        elif kind == "list":
            for i, x in enumerate(v):
                _lines(f"{p}[{i}]", f[4], x, out)
        else:
            out.append(f"{p} = {str(v).lower() if isinstance(v, bool) else v}")


def show(path):
    with open(path, "rb") as f:
        data = f.read()
    frames = store.frames(data)
    if not frames:
        raise PackError(f"{path}: no record (an empty store)")
    out = [f"capacity {len(data)} records {len(store.records(data))} frames {len(frames)}"]
    mode, count = None, {}
    for fmt, schema, enc in frames:
        if fmt != store.FORMAT_ETF or enc[:1] != b"\x83":
            raise PackError(f"{path}: a frame that is not (:etf)")
        value, _ = _decode(enc, 1)
        if mode is None:
            if schema != 1 or value.get("kind") != FORMAT_KIND.encode():
                raise PackError(f"{path}: the first record is not the index of a {FORMAT_KIND} store")
            mode = value["mode"].decode()
        table = by_schema(mode)
        if schema not in table:
            raise PackError(f"{path}: schema {schema} is not a record of mode {mode}")
        name, _, many, fields = table[schema]
        i = count.get(name, 0)
        count[name] = i + 1
        _lines(f"{name}[{i}]" if many == "many" else name, fields, value, out)
    return out


def shapes():
    out = []
    for mode in ("beam", "trust"):
        out.append(f"mode {mode}")
        for name, schema, many, fields in GROUPS[mode]:
            out.append(f"  {schema:3} {name} ({many})")

            def walk(fs, ind):
                for f in fs:
                    if f[1] in ("rec", "list"):
                        out.append(f"{ind}{f[0]}: {f[1]}")
                        walk(f[4], ind + "  ")
                    else:
                        out.append(f"{ind}{f[0]}: {f[1]} {f[2]}..{f[3]}")
            walk(fields, "      ")
    return out


def main(argv):
    try:
        if len(argv) >= 2 and argv[1] == "pack":
            args, config, capacity, out, manifests = argv[2:], None, None, None, []
            while args:
                a = args.pop(0)
                if a == "--config":
                    config = args.pop(0)
                elif a == "--capacity":
                    capacity = int(args.pop(0))
                elif a == "-o":
                    out = args.pop(0)
                else:
                    manifests.append(a)
            if not config or capacity is None or not out:
                print("usage: bees_pack.py pack --config bees.config --capacity BYTES -o node.sildat [MANIFEST.wire ...]", file=sys.stderr)
                return 2
            conf, recs = pack(config, manifests, capacity, out)
            for note in conf["notes"]:
                print(f"note: {note}")
            print(f"packed {len(recs)} records, mode {conf['mode']}, capacity {capacity}: {out}")
            return 0
        if len(argv) == 3 and argv[1] == "show":
            print("\n".join(show(argv[2])))
            return 0
        if len(argv) == 2 and argv[1] == "shapes":
            print("\n".join(shapes()))
            return 0
    except bees_conf.ConfError as e:
        print(e.text, file=sys.stderr)
        return 1
    except (PackError, store.StoreError) as e:
        print(f"bees_pack: {e}", file=sys.stderr)
        return 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
