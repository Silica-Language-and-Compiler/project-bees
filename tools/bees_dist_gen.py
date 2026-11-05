#!/usr/bin/env python3
"""bees_dist_gen: the distribution half of tools/bees_config.py (MVP milestone M3).

Not run directly; `bees_config.py generate` calls it when a `.wire` manifest has any node, peer, remote or local line. The same manifest
carries the message types (tools/bees_wire_gen.py reads the `remote` and `local` lines as messages); the lines read
here are:

    node     <name>                                  this node's name, e.g. b@127.0.0.1 (ASCII, at most 255 bytes)
    creation <n>                                     optional, 0 .. 2^32-1, default 1 (the creation of the handshake)
    timing   <open_ms> <io_ms> <tick_ms>             optional; defaults 10000 60000 15000. open_ms bounds listen/accept
                                                     and connect, io_ms is the longest a read may see nothing (a peer
                                                     silent for that long is lost), tick_ms the interval of the idle
                                                     check that sends a net tick; tick_ms 0 sends no ticks (a test
                                                     setting: the peer will drop this node after its io_ms)
    peer     <name> <host> <port> <listen|dial>      a node this program may talk to; host is 127.0.0.1 (the MVP)
    remote   <name> @ <peer name> cast <type>        a registered name on that peer: a proxy is registered here
    local    <name> cast <type>                      a registered name here that a peer may send to: a deliverer

The first `peer` line gives the program's one link (M3: one live link per node, as the M2 transport holds one peer
per listener): `dial` connects to it, `listen` binds its port and accepts one connection, which must name a node of
the table. Every other `peer` line is a table entry (a node that may dial in).

Generated: bees_peers.silica, with no BEAM atom literal (the registered names come from bees_atoms, D30):

    node_name, node_creation, open_ms, io_ms, tick_ms, link_address, link_dials, link_peer, peer_count, peer_index,
    peer_name, local_index (a registered name -> its index, -1 when no peer may send to it), start_deliverer (a
    short-lived actor that decodes a validated payload and delivers it with cast_registered, then ends), start_proxies
    (one proxy per remote name, registered under it, and a reaper that ends them: kill_abnormal), the proxies and
    the deliverers themselves.
"""
import os
import re
import sys

import bees_wire_gen as W

NAME_RE = re.compile(r"[a-z][a-z0-9_]*")
NODE_RE = re.compile(r"[A-Za-z0-9_.@\-]+")


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
TXMSG = "{ kind: int64, rg: region(L, normal), b: buf(L, normal, uint8, 4096), len: int64, who: actor_ref }"
DMSG = "{ rg: region(L, normal), b: buf(L, normal, uint8, 4096), len: int64 }"
POL = "stack_policy(0, :keep_last_message), state_policy(:keep_state_area)"


def lit(s):
    return '"' + s + '"'


def chain(items, expr_of, default):
    e = default
    for i in reversed(range(len(items))):
        e = expr_of(i, items[i], e)
    return e


def generate(out_dir, paths):
    d = parse(paths)
    msgs = check(d, W.collect(paths, warn=False))
    ln = ["// Generated by tools/bees_dist_gen.py (bees_config generate). Do not edit. The peer table, the proxies and the deliverers",
          "// of this program's manifest (M3). No BEAM atom literal: every registered name comes from bees_atoms (D30).",
          "module bees_peers;", "use bees_atoms;", "use bees_wire;", "use bees_wire_msgs;", "use bees_dist;", ""]
    ex = ["node_name/0", "node_creation/0", "open_ms/0", "io_ms/0", "tick_ms/0", "link_address/0", "link_dials/0",
          "link_peer/0", "peer_count/0", "peer_index/1", "peer_name/1", "local_index/1", "start_deliverer/1", "start_proxies/1"]
    ln += [f"export {e};" for e in ex] + [""]
    peers = d["peers"]
    o, i, t = d["timing"]
    ln += [f"fn node_name() -> string {{ {lit(d['node'])} }}",
           f"fn node_creation() -> int64 {{ {d['creation']} }}",
           f"fn open_ms() -> int64 {{ {o} }}", f"fn io_ms() -> int64 {{ {i} }}", f"fn tick_ms() -> uint64 {{ {t} }}"]
    first = peers[0]
    mode = "listen" if first[3] == "listen" else "connect"
    ln += [f"fn link_address() -> string {{ {lit(mode + ':' + first[1] + ':' + str(first[2]))} }}",
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
    # failure must not be the connection actor's)
    for n in locs:
        st = W.silica(msgs[n])
        ln += [f"fn dlv_{n}(msg: {DMSG}, st: int64) -> (:no_reply, int64) {{",
               "    sequence proc[concurrency]",
               f"        r: {{ code: int64, v: {st} }} <- bees_wire_msgs@dec_{n}(msg.rg, msg.b, msg.len);",
               f"        _: boolean <- case r.code == 0 of {{ true -> cast_registered(bees_atoms@a_{n}(), r.v impl ActorMessage {{}}); false -> true }};",
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
    # proxies
    ln += [f"fn tx_msg(kind: int64, rg: region(L, normal), b: buf(L, normal, uint8, 4096), len: int64, who: actor_ref) -> {TXMSG} {{",
           "    { kind: kind, rg: rg, b: b, len: len, who: who }", "}", ""]
    for k, (n, _) in enumerate(rems):
        st = W.silica(msgs[n])
        ln += [f"fn proxy_{n}(msg: {st}, st: {STATE}) -> (:no_reply, {STATE}) {{",
               "    sequence proc[concurrency, mem(normal)]",
               "        L: lifetime <- fresh_lifetime();",
               "        rg: region(L, normal) <- alloc_region(normal);",
               "        pb: buf(L, normal, uint8, 4096) <- alloc_buf(rg, 4096);",
               "        ob: buf(L, normal, uint8, 4096) <- alloc_buf(rg, 4096);",
               f"        plen: int64 <- bees_wire_msgs@enc_{n}(rg, pb, msg);",
               f"        flen: int64 <- bees_dist@reg_send_frame(rg, ob, pb, plen, st.id, node_name(), node_creation(), bees_atoms@spelling(bees_atoms@a_{n}()));",
               "        me: actor_ref <- self();",
               "        m: " + TXMSG + " <- tx_msg(0, rg, ob, flen, me);",
               "        _: boolean <- case flen > 0 of { true -> cast(st.tx, m impl ActorMessage {}); false -> true }",
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
