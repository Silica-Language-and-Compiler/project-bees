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
    redial   off | <initial_ms> <max_ms>             REQUIRED when a peer is `dial` and the program has no bees.config (no default): `off` leaves
                                                     a lost link down; the numbers dial again, the delay doubling from initial to max (a node
                                                     with a bees.config states beam.redial there instead, and this line is refused)
    peer     <name> <host> <port> <listen|dial>      a node this program may talk to; host is an IPv4 literal or a host name
                                                     (N1). Built from the manifest alone the node is auth none, a loopback-only
                                                     test setting, so only loopback hosts pass (tools/bees_conf.py manifest_only)
    remote   <name> @ <peer name> cast <type>        a registered name on that peer: a proxy is registered here
    local    <name> cast <type>                      a registered name here that a peer may send to: a deliverer

Every `peer` line is a link (N2c, as in BEAM mode): a `dial` peer is connected to ("host:port", the language's carrier address) and,
when its link is lost, dialed again (bees.config's redial options); the node has ONE listener when any peer is `listen` (the first
listen peer's port, on 127.0.0.1 as "listen:port"), and a peer's link starts when its handshake names it; a peer that connects again
replaces its old link (spikes/N2b-multi-link.md, "N2c"). With a bees.config
(tools/bees_conf.py, the one reader, a build-time stand-in) the file's values win over the manifest's (bees-config-file.md
section 2): the link's address, its role, and the frame cap `beam.frame_size_max`.

Generated, with no BEAM atom literal (the registered names come from bees_atoms, D30; the language's transport tags are
Silica-level atoms, allowed by `bees_config check`):

    bees_msgs.silica    per message type: enc_<name>(value) -> string (the language's encode((:etf), value)),
                        dec_<name>(frame) -> (:ok, T) | (:rejected, atom) (the language's decode((:etf), frame, { limits })),
                        and validate_named(frame, name) -> atom (:ok or the rejection reason) for the connection actor.
                        Both calls run in the sequence of a `sequence proc[mem(normal), transport] ... produces pure` block (user ruling
                        2026-11-06). Limits (N1, D39 R1): max_bytes and max_length are `beam.frame_size_max` (BEAM's
                        4294967295 when the file does not set it: a term is bounded by the packet, as in BEAM), max_depth is
                        the declared type's own nesting plus one (BEAM has no depth limit; a typed decode cannot go deeper
                        than its type). They are literals because the language's decode bakes its limits into the derived
                        decoder (transport design 4.1, E2402): a build-time value whatever reads the file.
                        C1 (spikes/C1-codec-term-coverage.md 2.1, 2.2, 2.7): a type may hold sums, tagged tuples and optional
                        references. A message whose type holds ref?(L, normal, rec) is { r: region(L, normal), v: T }: enc_<name>
                        encodes v, dec_<name>(frame, r) decodes into the caller's region, its max_depth is the nesting plus 64, and
                        its deliverer decodes into a fresh region and casts { r, v }. When a type writes atom literals,
                        bees_msgs.atoms, bees_peers.atoms and beam_peers.atoms list them (what `bees_config check` allows a unit).
    bees_peers.silica   node_name, node_creation, open_ms, io_ms, tick_ms, frame_max (the unframe cap and the send cap),
                        link_address, link_dials, link_peer, link_resolve, link_host, link_port (the first link's; a dial host that is a name is
                        turned into an IPv4 literal at boot by the resolver edge, N1), the same per peer (link_dials_of(i), link_resolve_of,
                        link_host_of, link_port_of, link_address_of), listens, listener_address, redial_on, redial_initial_ms,
                        redial_max_ms (N2c), peer_count,
                        peer_index, peer_name, local_index (a registered name -> its index, -1 when no peer may send to it),
                        start_deliverer (a short-lived actor that decodes a payload with bees_msgs@dec_<name> and delivers it with
                        cast_registered, then ends), start_proxies(peer, tx, mgr) (per peer: one proxy per remote name, registered under it, and a reaper
                        that ends them: kill_abnormal, and then reports to mgr), the proxies and the deliverers themselves. A proxy encodes with
                        bees_msgs@enc_<name>, builds the REG_SEND body (bees_dist@reg_send_body), frames it (bees_dist@frame4)
                        and casts the segment to the writer as (:bees, 0, segment).
"""
import os
import re
import sys

import bees_wire_gen as W

NAME_RE = re.compile(r"[a-z][a-z0-9_]*")
NODE_RE = re.compile(r"[A-Za-z0-9_.@\-]+")

# The decode limits (transport design 4.1) come from bees.config's beam.frame_size_max (N1); BEAM's packet limit when unset (R1).
BEAM_FRAME_MAX = 4294967295


class DistError(Exception):
    pass


def parse(paths):
    """-> dict with node, creation, timing, peers [(name, host, port, mode)], remotes [(name, peer, where)], locals."""
    d = {"node": None, "creation": 1, "timing": (10000, 60000, 15000), "peers": [], "remotes": [], "locals": [], "redial": None}
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
                elif k == "redial":
                    ok = (len(t) == 2 and t[1] == "off") or (len(t) == 3 and t[1].isdigit() and t[2].isdigit())
                    if not ok or d["redial"] is not None:
                        raise DistError(f"{where}: expected once: redial off | redial <initial_ms> <max_ms>")
                    if t[1] == "off":
                        d["redial"] = ("off",)
                    else:
                        i0, m0 = int(t[1]), int(t[2])
                        if not (10 <= i0 <= 60000 and 10 <= m0 <= 600000 and i0 <= m0):
                            raise DistError(f"{where}: redial: initial_ms 10..60000, max_ms 10..600000, not below the initial")
                        d["redial"] = (i0, m0)
                elif k == "peer":
                    if len(t) != 5 or not NODE_RE.fullmatch(t[1]) or t[4] not in ("listen", "dial") or not t[3].isdigit():
                        raise DistError(f"{where}: expected: peer <name> <host> <port> <listen|dial>")
                    if not re.fullmatch(r"[A-Za-z0-9.:\-]{1,253}", t[2]):
                        raise DistError(f"{where}: host {t[2]} is not an IPv4 or IPv6 literal or a host name")
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
    if kind == "atomlit":
        return False
    if kind == "sum":
        return any(variable_sized(t) for t in ty[1])
    return True  # a list; an optional reference (C1: a recursive tuple has no fixed size)


def limits_arg(ty, frame_max):
    return f", {{ max_bytes: {frame_max}, max_depth: {W.max_depth(ty)}, max_length: {frame_max} }}" if variable_sized(ty) else ""


def result_type(st):
    return f"(:ok, {st}) | (:rejected, atom)"

MSG = "(:bees, int64, int64, actor_ref, actor_ref)"


def per_peer_proxies(peers, remotes):
    """N2c: the per-peer reapers and start_proxies, shared by bees_peers (this tool) and beam_peers (bees_config_beam.py); both units
    define proxy_<name> as above. peers: [name]; remotes: [(name, peer name)] in the manifest's order (a proxy's id is its index).

    reaper_p<i>(msg, st): the one actor of peer i's link that ends its proxies (kill_abnormal) when the link is lost (the writer's
        message (:bees, 1, 0, tx, conn)), and only AFTER the last kill reports (:bees, 2, i, tx, conn) to its manager `mgr` and ends
        itself (stop_self: nothing casts to it again; N2c teardown): the slot of a
        listening node, the redial actor of a dialing one. A registered name is free when kill_abnormal has returned, so a manager
        that starts the next link's proxies on that report never clashes (SD-33).
    start_proxies_p<i>(tx, mgr) -> reaper; start_proxies(idx, tx, mgr) picks by the peer's index."""
    ln = [f"fn rp_tx(msg: {MSG}) -> actor_ref {{ case msg of {{ (:bees, _a: int64, _b: int64, t: actor_ref, _c: actor_ref) -> t }} }}",
          f"fn rp_cn(msg: {MSG}) -> actor_ref {{ case msg of {{ (:bees, _a: int64, _b: int64, _t: actor_ref, c: actor_ref) -> c }} }}", ""]
    byp = [[(k, n) for k, (n, pe) in enumerate(remotes) if pe == pn] for pn in peers]
    for pi, mine in enumerate(byp):
        fields = ", ".join(["n: int64", "mgr: actor_ref"] + [f"p{j}: actor_ref" for j in range(len(mine))])
        body = ["        t: actor_ref <- rp_tx(msg)", "        c: actor_ref <- rp_cn(msg)"] + [f"        _: atom <- kill_abnormal(st.p{j})" for j in range(len(mine))] + \
               [f"        _: boolean <- cast(st.mgr, (:bees, 2, {pi}, t, c) impl ActorMessage {{}})",
                "        _: atom <- stop_self(:normal)"]
        ln += [f"fn reaper_p{pi}(msg: {MSG}, st: {{ {fields} }}) -> (:no_reply, {{ {fields} }}) {{",
               "    sequence proc[concurrency]", ";\n".join(body),
               "    produces pure (:no_reply, st) end", "}", ""]
        sp = [f"        p{j}: actor_ref <- spawn_registered({{ tx: tx, id: {k} }}, proxy_{n}, bees_atoms@a_{n}(), {POL});" for j, (k, n) in enumerate(mine)]
        init = ", ".join(["n: " + str(len(mine)), "mgr: mgr"] + [f"p{j}: p{j}" for j in range(len(mine))])
        ln += [f"// peer {pi} ({peers[pi]}): its proxies, and the reaper that ends them when its link is lost; the reaper is the one value returned",
               f"fn start_proxies_p{pi}(tx: actor_ref, mgr: actor_ref) -> actor_ref {{", "    sequence proc[concurrency]"] + sp + \
              [f"        r: actor_ref <- spawn({{ {init} }}, reaper_p{pi}, {POL})", "    produces pure r end", "}", ""]
    e = f"start_proxies_p{len(peers) - 1}(tx, mgr)"
    for pi in reversed(range(len(peers) - 1)):
        e = f"case idx == {pi} of {{ true -> start_proxies_p{pi}(tx, mgr); false -> {e} }}"
    ln += ["// start_proxies(peer, tx, mgr): the proxies of the peer with that index (peer_index); callers pass 0 <= peer < peer_count",
           f"fn start_proxies(idx: int64, tx: actor_ref, mgr: actor_ref) -> actor_ref {{ {e} }}", ""]
    return ln


def generate_msgs(out_dir, msgs, frame_max=BEAM_FRAME_MAX):
    """bees_msgs.silica: the two-function shape per message over the language's derived encode and decode."""
    ln = ["// Generated by tools/bees_dist_gen.py (bees_config generate). Do not edit. The message codecs of this program's manifest:",
          "// the language's derived encode((:etf), value) and decode((:etf), frame, { limits }) behind enc_<name> / dec_<name>",
          "// (transport design 4.1, 4.3), each in the sequence of a `sequence proc[mem(normal), transport] ... produces pure` block, so that",
          "// what leaves is a pure typed value or a pure string. validate_named(frame, name) is the connection actor's check of a",
          "// payload against its target name's declared type: :ok, or the language's rejection atom.",
          "module bees_msgs;", "use wire_etf;", "use bees_atoms;"] + W.split_uses(msgs) + [""]
    ex = ["validate_named/2"]
    for name, ty in msgs:
        ex += [f"enc_{name}/1", f"dec_{name}/{2 if W.has_region(ty) else 1}"]
    ln += [f"export {e};" for e in ex] + [""]
    # C1 (design 2.3 to 2.6, 3.5): a dynamic term, and a type that holds a Map, a Set or a buf (or, while W.SD37_SPLIT is set, a
    # record of more than four fields) are not one derived call: W.split_msgs writes them, after the plain messages
    for name, ty in msgs:
        if not W.is_plain(ty):
            continue
        if W.has_slot(ty):
            ln += recursive_msg(name, ty, frame_max)
            continue
        st = W.silica(ty)
        rt = result_type(st)
        ln += [f"fn enc_{name}(msg: {st}) -> string {{",
               "    sequence proc[mem(normal), transport]",
               "        s: string <- encode((:etf), msg)",
               "    produces pure s end", "}", "",
               f"fn dec_{name}(frame: string) -> {rt} {{",
               "    sequence proc[mem(normal), transport]",
               f"        r: {rt} <- decode((:etf), frame{limits_arg(ty, frame_max)})",
               "    produces pure r end", "}", "",
               f"fn check_{name}(frame: string) -> atom {{",
               "    sequence",
               f"        r: {rt} <- dec_{name}(frame);",
               f"        why: atom <- case r of {{ (:ok, _v: {st}) -> :ok; (:rejected, w: atom) -> w }}",
               "    produces pure why end", "}", ""]
    ln += W.split_msgs(msgs, frame_max, limits_arg, result_type)
    names = [n for n, _ in msgs]
    ln += ["fn validate_named(frame: string, name: atom) -> atom { " +
           chain(names, lambda k, n, e: f"case name == bees_atoms@a_{n}() of {{ true -> check_{n}(frame); false -> {e} }}",
                 "bees_atoms@a_unknown_atom()") + " }", ""]
    with open(os.path.join(out_dir, "bees_msgs.silica"), "w") as out:
        out.write("\n".join(ln))
    write_type_atoms(out_dir, msgs)


def recursive_msg(name, ty, frame_max):
    """C1 (spikes/C1-codec-term-coverage.md 2.2): a message whose type holds an optional reference is the record
    { r: region(L, normal), v: T }. enc_<name> encodes v; dec_<name>(frame, r) decodes into the caller's region (the fourth argument
    of the language's decode); check_<name> validates by decoding into a scratch region of its own."""
    st, vt = W.silica(ty), W.silica_value(ty)
    rt = result_type(vt)
    return [f"fn enc_{name}(msg: {st}) -> string {{",
            "    sequence proc[mem(normal), transport]",
            f"        v: {vt} <- msg.v;",
            "        s: string <- encode((:etf), v)",
            "    produces pure s end", "}", "",
            f"fn dec_{name}(frame: string, r: {W.REGION}) -> {rt} {{",
            "    sequence proc[mem(normal), transport]",
            f"        x: {rt} <- decode((:etf), frame{limits_arg(ty, frame_max)}, r)",
            "    produces pure x end", "}", "",
            f"fn check_{name}(frame: string) -> atom {{",
            "    sequence proc[mem(normal)]",
            "        L: lifetime <- fresh_lifetime();",
            f"        r: {W.REGION} <- alloc_region(normal);",
            f"        x: {rt} <- dec_{name}(frame, r);",
            f"        why: atom <- case x of {{ (:ok, _v: {vt}) -> :ok; (:rejected, w: atom) -> w }}",
            "    produces pure why end", "}", ""]


TYPE_ATOM_UNITS = ("bees_msgs", "bees_peers", "beam_peers")
TYPE_ATOMS_HEAD = "# Generated by tools/bees_dist_gen.py (bees_config generate). Do not edit. The atom literals written in this program's"


def write_type_atoms(out_dir, msgs):
    """C1: a message type may write atom literals (tags, atom variants), and the generated units that spell the types (bees_msgs,
    bees_peers, and beam_peers in BEAM mode) then hold them as literals; `bees_config check` allows a unit the atoms of the X.atoms
    file beside it. Written only when a type has an atom literal; a file this tool wrote earlier is removed when none has."""
    atoms = W.type_atom_names(msgs)
    for unit in TYPE_ATOM_UNITS:
        path = os.path.join(out_dir, unit + ".atoms")
        if atoms:
            with open(path, "w") as out:
                out.write("\n".join([TYPE_ATOMS_HEAD, f"# message types (.wire manifest), which {unit} spells; all are in bees_atoms."] + atoms) + "\n")
        elif os.path.isfile(path):
            with open(path) as fh:
                mine = fh.readline().rstrip("\n") == TYPE_ATOMS_HEAD
            if mine:
                os.remove(path)


def generate(out_dir, paths, link=None):
    """link: tools/bees_conf.py m3_link() of the program's bees.config (None: the manifest alone, checked by the caller)"""
    d = parse(paths)
    msgs = check(d, W.collect(paths, warn=False))
    if link is None:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import bees_conf
        link = bees_conf.m3_link(None, d)
    generate_msgs(out_dir, [(n, msgs[n]) for n in sorted(msgs)], link["frame_max"])
    ln = ["// Generated by tools/bees_dist_gen.py (bees_config generate). Do not edit. The peer table, the proxies and the deliverers",
          "// of this program's manifest (M3, over the language's transport). No BEAM atom literal: every registered name comes from",
          "// bees_atoms (D30); the :bees tag is dangerous_bees_net's actor-protocol tag.",
          "module bees_peers;", "use bees_atoms;", "use bees_msgs;", "use bees_dist;", ""]
    ex = ["node_name/0", "node_creation/0", "open_ms/0", "io_ms/0", "tick_ms/0", "frame_max/0", "link_address/0", "open_text/0", "link_dials/0",
          "link_peer/0", "link_resolve/0", "link_host/0", "link_port/0", "peer_count/0", "peer_index/1", "peer_name/1", "local_index/1", "start_deliverer/1", "start_proxies/3",
          "listens/0", "listener_address/0", "link_dials_of/1", "link_resolve_of/1", "link_host_of/1", "link_port_of/1", "link_address_of/1",
          "redial_on/0", "redial_initial_ms/0", "redial_max_ms/0"]
    ln += [f"export {e};" for e in ex] + [""]
    peers = d["peers"]
    o, i, t = d["timing"]
    ln += [f"fn node_name() -> string {{ {lit(d['node'])} }}",
           f"fn node_creation() -> int64 {{ {d['creation']} }}",
           f"fn open_ms() -> int64 {{ {o} }}", f"fn io_ms() -> uint64 {{ {i} }}", f"fn tick_ms() -> uint64 {{ {t} }}",
           f"fn frame_max() -> int64 {{ {link['frame_max']} }}"]
    # the language's carrier addresses (transport design 6.2, 6.3): "host:port" connects, "listen:port" listens on 127.0.0.1,
    # "listen:any:port" on every IPv4 interface
    dials = link["link_dials"]
    # the carrier's dial form is "host:port:timeout_ms" (silica 39b6a5a50b, E8): BEES's open_ms is the budget; no default exists
    addr = link['link_address'] + (f":{o}" if dials and link['link_address'] else "")
    ln += [f"fn link_address() -> string {{ {lit(addr)} }}", f"fn open_text() -> string {{ {lit(str(o))} }}",
           f"fn link_dials() -> boolean {{ {'true' if dials else 'false'} }}",
           f"fn link_peer() -> int64 {{ {0 if dials else -1} }}",
           f"fn link_resolve() -> boolean {{ {'true' if link.get('link_resolve') else 'false'} }}",
           f"fn link_host() -> string {{ {lit(link['link_host'])} }}",
           f"fn link_port() -> int64 {{ {link.get('link_port', 0)} }}",
           f"fn peer_count() -> int64 {{ {len(peers)} }}"]
    # N2c: one entry per peer line (the first link's values above are the scalars), the node's one listener, and the redial settings
    # (tools/bees_conf.py m3_link: bees.config's beam.redial, redial_initial_ms, redial_max_ms, or the manifest's `redial` line; no default)
    links = link["links"]
    tf = lambda v: "true" if v else "false"  # noqa: E731
    ln += [f"fn listens() -> boolean {{ {tf(link['listens'])} }}", f"fn listener_address() -> string {{ {lit(link['listener_address'])} }}",
           f"fn redial_on() -> boolean {{ {tf(link['redial'])} }}", f"fn redial_initial_ms() -> int64 {{ {link['redial_initial_ms']} }}",
           f"fn redial_max_ms() -> int64 {{ {link['redial_max_ms']} }}"]
    for name, ty, vals, dflt in [
            ("link_dials_of", "boolean", [tf(k["dials"]) for k in links], "false"),
            ("link_resolve_of", "boolean", [tf(k["resolve"]) for k in links], "false"),
            ("link_host_of", "string", [lit(k["host"]) for k in links], '""'),
            ("link_port_of", "int64", [str(k["port"] or 0) for k in links], "0"),
            ("link_address_of", "string", [lit(k["address"] + (f":{o}" if k["dials"] and k["address"] else "")) for k in links], '""')]:
        arms = "".join(f"        {n} -> {v};\n" for n, v in enumerate(vals))
        ln += [f"fn {name}(i: int64) -> {ty} {{", "    case i of {", arms + f"        _: int64 -> {dflt}", "    }", "}"]
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
        if W.has_region(msgs[n]):
            # C1: a recursive message, and one that holds a buf, is decoded into a fresh region, which is cast with the value ({ r, v }, design 2.2)
            vt = W.silica_value(msgs[n])
            ln += [f"fn dlv_{n}(msg: string, st: int64) -> (:no_reply, int64) {{",
                   "    sequence proc[concurrency, mem(normal)]",
                   "        L: lifetime <- fresh_lifetime();",
                   f"        r: {W.REGION} <- alloc_region(normal);",
                   f"        x: {result_type(vt)} <- bees_msgs@dec_{n}(msg, r);",
                   f"        _: boolean <- case x of {{ (:ok, v: {vt}) -> cast_registered(bees_atoms@a_{n}(), {{ r: r, v: v }} impl ActorMessage {{}}); (:rejected, _w: atom) -> true }};",
                   "        _: atom <- stop_self(:normal)",
                   "    produces pure (:no_reply, st) end", "}", "",
                   f"fn start_dlv_{n}() -> actor_ref {{",
                   "    sequence proc[concurrency]",
                   f"        a: actor_ref <- spawn(0, dlv_{n}, {POL})",
                   "    produces pure a end", "}", ""]
            continue
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
               f"        body: string <- bees_dist@reg_send_body_max(payload, st.id, node_name(), node_creation(), bees_atoms@spelling(bees_atoms@a_{n}()), frame_max());",
               "        seg: string <- bees_dist@frame4(body);",
               "        _: boolean <- case length_bytes(body) > 0 of { true -> cast(st.tx, (:bees, 0, seg) impl ActorMessage {}); false -> true }",
               "    produces pure (:no_reply, st) end", "}", ""]
    ln += per_peer_proxies([p[0] for p in peers], rems)
    with open(os.path.join(out_dir, "bees_peers.silica"), "w") as out:
        out.write("\n".join(ln))
    return d


def has_dist(paths):
    for p in paths:
        with open(p) as fh:
            for line in fh:
                if line.split("#", 1)[0].split()[:1] in (["node"], ["peer"], ["remote"], ["local"], ["creation"], ["timing"], ["redial"]):
                    return True
    return False


if __name__ == "__main__":
    print(__doc__)
