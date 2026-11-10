#!/usr/bin/env python3
"""bees_dist_gen: the distribution half of tools/bees_config.py (MVP milestone M3; ported to the language's transport, N0.0/N1).

Not run directly; `bees_config.py generate` calls it when a `.wire` manifest has any node, peer, remote or local line. The same manifest
carries the message types (tools/bees_wire_gen.py reads the `remote` and `local` lines as messages and checks the typed subset); the
lines read here are:

    node     <name>                                  this node's name, e.g. b@127.0.0.1 (ASCII, at most 255 bytes)
    creation <n>                                     optional, 0 .. 2^32-1, default 1 (the creation of the handshake)
    timing   <open_ms> <io_ms> <tick_ms>             optional; defaults 10000 60000 15000. io_ms is the longest the peer may be
                                                     silent (a peer silent for that long is lost: dangerous_bees_net's idle check), tick_ms
                                                     the interval of the idle check that sends a net tick; tick_ms 0 sends no
                                                     ticks (a test setting: the peer will drop this node after its io_ms).
                                                     open_ms is kept for the manifest's shape; the language's (:tcp) carrier
                                                     connects or fails at once and has no accept timeout (N1 note)
    peer     <name> <host> <port> <listen|dial>      a node this program may talk to; host is 127.0.0.1 (the MVP)
    remote   <name> @ <peer name> cast <type>        a registered name on that peer: a proxy is registered here
    local    <name> cast <type>                      a registered name here that a peer may send to: a deliverer

The first `peer` line gives the program's one link (M3: one live link per node): `dial` connects to it ("host:port", the
language's carrier address), `listen` binds its port on 127.0.0.1 ("listen:port") and the first accepted connection becomes the
link; it must name a node of the table. Every other `peer` line is a table entry (a node that may dial in).

Generated, with no BEAM atom literal (the registered names come from bees_atoms, D30; the language's transport tags are
Silica-level atoms, allowed by `bees_config check`):

    bees_msgs.silica    per message type: enc_<name>(value) -> string (the language's encode((:etf), value)),
                        dec_<name>(frame) -> (:ok, T) | (:rejected, atom) (the language's decode((:etf), frame, { limits })),
                        and validate_named(frame, name) -> atom (:ok or the rejection reason) for the connection actor.
                        Both calls run in the sequence of a `sequence proc[mem(normal), transport] ... produces pure` block (user ruling
                        2026-11-06). Limits (max_bytes, max_depth, max_length) are the module constants below until bees.config
                        carries them (N1, D39 R1).
    bees_peers.silica   node_name, node_creation, open_ms, io_ms, tick_ms, link_address, link_dials, link_peer, peer_count,
                        peer_index, peer_name, local_index (a registered name -> its index, -1 when no peer may send to it),
                        start_deliverer (a short-lived actor that decodes a payload with bees_msgs@dec_<name> and delivers it with
                        cast_registered, then ends), start_proxies (one proxy per remote name, registered under it, and a reaper
                        that ends them: kill_abnormal), the proxies and the deliverers themselves. A proxy encodes with
                        bees_msgs@enc_<name>, builds the REG_SEND body (bees_dist@reg_send_body), frames it (bees_dist@frame4)
                        and casts the segment to the writer as (:bees, 0, segment).
"""
import os
import re
import sys

import bees_wire_gen as W

NAME_RE = re.compile(r"[a-z][a-z0-9_]*")
NODE_RE = re.compile(r"[A-Za-z0-9_.@\-]+")

# The decode limits handed to the language's decode for every message type (transport design 4.1). M3's frame cap and the
# typed codec's depth and element limits; the string limit is the larger of M1b's list (256) and binary (1024) limits because
# the language has one max_length for both. bees.config will carry them (N1).
MAX_BYTES = 4096
MAX_DEPTH = 16
MAX_LENGTH = 1024


class DistError(Exception):
    pass


def parse(paths):
    """-> dict with node, creation, timing, peers [(name, host, port, mode)], remotes [(name, peer, where)], locals."""
    d = {"node": None, "creation": 1, "timing": (10000, 60000, 15000), "peers": [], "remotes": [], "locals": []}
    for path in paths:
        with open(path) as fh:
            for n, line in enumerate(fh, 1):
                line = line.split("#", 1)[0].strip()
                if not line:
                    continue
                where = f"{path}:{n}"
                t = line.split()
                k = t[0]
                if k == "node":
                    if len(t) != 2 or not NODE_RE.fullmatch(t[1]) or len(t[1]) > 255:
                        raise DistError(f"{where}: expected: node <name> (ASCII letters, digits, _ . @ -)")
                    if d["node"] is not None:
                        raise DistError(f"{where}: a second node line (the first is this program's name)")
                    d["node"] = t[1]
                elif k == "creation":
                    if len(t) != 2 or not t[1].isdigit() or int(t[1]) >= 2 ** 32:
                        raise DistError(f"{where}: expected: creation <0 .. 4294967295>")
                    d["creation"] = int(t[1])
                elif k == "timing":
                    if len(t) != 4 or not all(x.isdigit() for x in t[1:]):
                        raise DistError(f"{where}: expected: timing <open_ms> <io_ms> <tick_ms>")
                    o, i, tk = (int(x) for x in t[1:])
                    if not (1 <= o <= 60000 and 1 <= i <= 60000 and 0 <= tk <= 60000):
                        raise DistError(f"{where}: timing values are 1..60000 ms (tick_ms may be 0)")
                    d["timing"] = (o, i, tk)
                elif k == "peer":
                    if len(t) != 5 or not NODE_RE.fullmatch(t[1]) or t[4] not in ("listen", "dial") or not t[3].isdigit():
                        raise DistError(f"{where}: expected: peer <name> <host> <port> <listen|dial>")
                    if t[2] != "127.0.0.1":
                        raise DistError(f"{where}: host {t[2]} is refused: the MVP transport is 127.0.0.1 only")
                    if not (1 <= int(t[3]) <= 65535):
                        raise DistError(f"{where}: port {t[3]} is not 1..65535")
                    if any(p[0] == t[1] for p in d["peers"]):
                        raise DistError(f"{where}: peer {t[1]} is listed twice")
                    d["peers"].append((t[1], t[2], int(t[3]), t[4]))
                elif k == "remote":
                    if len(t) < 6 or t[2] != "@" or t[4] != "cast":
                        raise DistError(f"{where}: expected: remote <name> @ <peer> cast <type>")
                    d["remotes"].append((t[1], t[3], where))
                elif k == "local":
                    if len(t) < 4 or t[2] != "cast":
                        raise DistError(f"{where}: expected: local <name> cast <type>")
                    d["locals"].append((t[1], where))
    return d


def check(d, msgs):
    if d["node"] is None:
        raise DistError("no node line")
    if not d["peers"]:
        raise DistError("no peer line: a node with no peer has nothing to connect to")
    names = {p[0] for p in d["peers"]}
    if d["node"] in names:
        raise DistError(f"peer {d['node']} is this node itself")
    seen = {}
    for name, peer, where in d["remotes"]:
        if not NAME_RE.fullmatch(name):
            raise DistError(f"{where}: '{name}' is not a usable registered name")
        if peer not in names:
            raise DistError(f"{where}: remote {name} names {peer}, which is not a peer line")
        if name in seen:
            raise DistError(f"{where}: {name} is already declared at {seen[name]} (a name cannot be remote and local, "
                            "or declared twice: its proxy or its holder would clash)")
        seen[name] = where
    for name, where in d["locals"]:
        if not NAME_RE.fullmatch(name):
            raise DistError(f"{where}: '{name}' is not a usable registered name")
        if name in seen:
            raise DistError(f"{where}: {name} is already declared at {seen[name]} (a name cannot be remote and local, "
                            "or declared twice: its proxy or its holder would clash)")
        seen[name] = where
    if len(d["remotes"]) > 16 or len(d["locals"]) > 16:
        raise DistError("at most 16 remote and 16 local names in the MVP")
    return dict(msgs)


STATE = "{ tx: actor_ref, id: int64 }"
POL = "stack_policy(0, :keep_last_message), state_policy(:keep_state_area)"


def lit(s):
    return '"' + s + '"'


def chain(items, expr_of, default):
    e = default
    for i in reversed(range(len(items))):
        e = expr_of(i, items[i], e)
    return e


def variable_sized(ty):
    """A type with a string or a list needs decode limits (transport design 4.1); a fixed-size type needs none."""
    kind = ty[0]
    if kind == "prim":
        return ty[1] == "string"
    if kind in ("tuple",):
        return any(variable_sized(t) for t in ty[1])
    if kind == "record":
        return any(variable_sized(t) for _, t in ty[1])
    return True


def limits_arg(ty):
    return f", {{ max_bytes: {MAX_BYTES}, max_depth: {MAX_DEPTH}, max_length: {MAX_LENGTH} }}" if variable_sized(ty) else ""


def result_type(st):
    return f"(:ok, {st}) | (:rejected, atom)"


def generate_msgs(out_dir, msgs):
    """bees_msgs.silica: the two-function shape per message over the language's derived encode and decode."""
    ln = ["// Generated by tools/bees_dist_gen.py (bees_config generate). Do not edit. The message codecs of this program's manifest:",
          "// the language's derived encode((:etf), value) and decode((:etf), frame, { limits }) behind enc_<name> / dec_<name>",
          "// (transport design 4.1, 4.3), each in the sequence of a `sequence proc[mem(normal), transport] ... produces pure` block, so that",
          "// what leaves is a pure typed value or a pure string. validate_named(frame, name) is the connection actor's check of a",
          "// payload against its target name's declared type: :ok, or the language's rejection atom.",
          "module bees_msgs;", "use wire_etf;", "use bees_atoms;", ""]
    ex = ["validate_named/2"]
    for name, _ in msgs:
        ex += [f"enc_{name}/1", f"dec_{name}/1"]
    ln += [f"export {e};" for e in ex] + [""]
    for name, ty in msgs:
        st = W.silica(ty)
        rt = result_type(st)
        ln += [f"fn enc_{name}(msg: {st}) -> string {{",
               "    sequence proc[mem(normal), transport]",
               "        s: string <- encode((:etf), msg)",
               "    produces pure s end", "}", "",
               f"fn dec_{name}(frame: string) -> {rt} {{",
               "    sequence proc[mem(normal), transport]",
               f"        r: {rt} <- decode((:etf), frame{limits_arg(ty)})",
               "    produces pure r end", "}", "",
               f"fn check_{name}(frame: string) -> atom {{",
               "    sequence",
               f"        r: {rt} <- dec_{name}(frame);",
               f"        why: atom <- case r of {{ (:ok, _v: {st}) -> :ok; (:rejected, w: atom) -> w }}",
               "    produces pure why end", "}", ""]
    names = [n for n, _ in msgs]
    ln += ["fn validate_named(frame: string, name: atom) -> atom { " +
           chain(names, lambda k, n, e: f"case name == bees_atoms@a_{n}() of {{ true -> check_{n}(frame); false -> {e} }}",
                 "bees_atoms@a_unknown_atom()") + " }", ""]
    with open(os.path.join(out_dir, "bees_msgs.silica"), "w") as out:
        out.write("\n".join(ln))


def generate(out_dir, paths):
    d = parse(paths)
    msgs = check(d, W.collect(paths, warn=False))
    generate_msgs(out_dir, [(n, msgs[n]) for n in sorted(msgs)])
    ln = ["// Generated by tools/bees_dist_gen.py (bees_config generate). Do not edit. The peer table, the proxies and the deliverers",
          "// of this program's manifest (M3, over the language's transport). No BEAM atom literal: every registered name comes from",
          "// bees_atoms (D30); the :bees tag is dangerous_bees_net's actor-protocol tag.",
          "module bees_peers;", "use bees_atoms;", "use bees_msgs;", "use bees_dist;", ""]
    ex = ["node_name/0", "node_creation/0", "open_ms/0", "io_ms/0", "tick_ms/0", "link_address/0", "link_dials/0",
          "link_peer/0", "peer_count/0", "peer_index/1", "peer_name/1", "local_index/1", "start_deliverer/1", "start_proxies/1"]
    ln += [f"export {e};" for e in ex] + [""]
    peers = d["peers"]
    o, i, t = d["timing"]
    ln += [f"fn node_name() -> string {{ {lit(d['node'])} }}",
           f"fn node_creation() -> int64 {{ {d['creation']} }}",
           f"fn open_ms() -> int64 {{ {o} }}", f"fn io_ms() -> uint64 {{ {i} }}", f"fn tick_ms() -> uint64 {{ {t} }}"]
    first = peers[0]
    # the language's carrier addresses (transport design 6.2, 6.3): "host:port" connects, "listen:port" listens on 127.0.0.1
    address = f"listen:{first[2]}" if first[3] == "listen" else f"{first[1]}:{first[2]}"
    ln += [f"fn link_address() -> string {{ {lit(address)} }}",
           f"fn link_dials() -> boolean {{ {'true' if first[3] == 'dial' else 'false'} }}",
           f"fn link_peer() -> int64 {{ {0 if first[3] == 'dial' else -1} }}",
           f"fn peer_count() -> int64 {{ {len(peers)} }}"]
    arms = "".join(f"        {lit(p[0])} -> {k};\n" for k, p in enumerate(peers))
    ln += ["fn peer_index(name: string) -> int64 {", "    case name of {", arms + "        _: string -> -1", "    }", "}"]
    arms = "".join(f"        {k} -> {lit(p[0])};\n" for k, p in enumerate(peers))
    ln += ["fn peer_name(i: int64) -> string {", "    case i of {", arms + '        _: int64 -> ""', "    }", "}", ""]
    locs = [n for n, _ in d["locals"]]
    rems = [(n, p) for n, p, _ in d["remotes"]]
    ln += [f"fn local_index(name: atom) -> int64 {{ " +
           chain(locs, lambda k, n, e: f"case name == bees_atoms@a_{n}() of {{ true -> {k}; false -> {e} }}", "-1") + " }", ""]
    # deliverers: one short-lived actor per delivery (cast_registered to a name nobody holds fails the caller, so the
    # failure must not be the connection actor's). The decode is the language's, inside the sequence of a produces-pure block.
    for n in locs:
        st = W.silica(msgs[n])
        rt = result_type(st)
        ln += [f"fn dlv_{n}(msg: string, st: int64) -> (:no_reply, int64) {{",
               "    sequence proc[concurrency]",
               f"        r: {rt} <- bees_msgs@dec_{n}(msg);",
               f"        _: boolean <- case r of {{ (:ok, v: {st}) -> cast_registered(bees_atoms@a_{n}(), v impl ActorMessage {{}}); (:rejected, _w: atom) -> true }};",
               "        _: atom <- stop_self(:normal)",
               "    produces pure (:no_reply, st) end", "}", "",
               f"fn start_dlv_{n}() -> actor_ref {{",
               "    sequence proc[concurrency]",
               f"        a: actor_ref <- spawn(0, dlv_{n}, {POL})",
               "    produces pure a end", "}", ""]
    if locs:
        e = f"start_dlv_{locs[-1]}()"
        for k in reversed(range(len(locs) - 1)):
            e = f"case idx == {k} of {{ true -> start_dlv_{locs[k]}(); false -> {e} }}"
        ln += [f"fn start_deliverer(idx: int64) -> actor_ref {{ {e} }}", ""]
    else:
        ln += ["fn start_deliverer(idx: int64) -> actor_ref {", "    sequence proc[concurrency]", "        me: actor_ref <- self()",
               "    produces pure me end", "}", ""]
    # proxies: encode (the language's), the REG_SEND body, the 4-byte framing, one segment to the writer
    for k, (n, _) in enumerate(rems):
        st = W.silica(msgs[n])
        ln += [f"fn proxy_{n}(msg: {st}, st: {STATE}) -> (:no_reply, {STATE}) {{",
               "    sequence proc[concurrency]",
               f"        payload: string <- bees_msgs@enc_{n}(msg);",
               f"        body: string <- bees_dist@reg_send_body(payload, st.id, node_name(), node_creation(), bees_atoms@spelling(bees_atoms@a_{n}()));",
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
    sp = [f"        p{k}: actor_ref <- spawn_registered({{ tx: tx, id: {k} }}, proxy_{n}, bees_atoms@a_{n}(), {POL});" for k, (n, _) in enumerate(rems)]
    init = ", ".join(["n: " + str(len(rems))] + [f"p{k}: p{k}" for k in range(len(rems))])
    ln += ["// the reaper ends every proxy of the link (kill_abnormal) when the link is lost; it is the one value start_proxies returns",
           "fn start_proxies(tx: actor_ref) -> actor_ref {", "    sequence proc[concurrency]"] + sp + \
          [f"        r: actor_ref <- spawn({{ {init} }}, reaper, {POL})", "    produces pure r end", "}", ""]
    with open(os.path.join(out_dir, "bees_peers.silica"), "w") as out:
        out.write("\n".join(ln))
    return d


def has_dist(paths):
    for p in paths:
        with open(p) as fh:
            for line in fh:
                if line.split("#", 1)[0].split()[:1] in (["node"], ["peer"], ["remote"], ["local"], ["creation"], ["timing"]):
                    return True
    return False


if __name__ == "__main__":
    print(__doc__)
