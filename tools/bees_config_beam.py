#!/usr/bin/env python3
"""bees_config_beam: the generator of the two BEAM-mode units a node program needs (milestone N2). It READS NOTHING ITSELF: every
value comes from the one bees.config reader, tools/bees_conf.py (N0.2), which merged the beam half that used to live here with
N3's trust half.

    bees_config_beam.py check    --config FILE MANIFEST.wire...                       validate only
    bees_config_beam.py generate --config FILE [--beam FILE.beam] -o OUT_DIR MANIFEST.wire...

BUILD-TIME STAND-IN (bees_conf.py's header): the file is read when the program is built, not at boot, because Silica cannot read a
file at boot yet. In BEAM mode a violation stops the build with the reader's one line `bees.config:LINE: PATH: MESSAGE` and exit
status 1 (so no actor ever starts); the values are written into the generated unit `beam_conf` as constants. The cookie file itself
is NOT built in: its path is, and the native edge reads the file at each handshake (checking that it is a regular file, not readable
by group or others, 1 to 255 bytes of ASCII 32..126).

Generated (generate):

  beam_conf.silica   the effective BEAM-mode values: auth_cookie, cookie_path (absolute), creation, epmd_external,
                     epmd_address (this host's EPMD, for ALIVE2), epmd_lookup_address (the peer host's EPMD, for PORT_PLEASE2),
                     io_ms, tick_ms, link_dials, link_peer, link_address, link_by_epmd, link_host, link_resolve (the link's host
                     is a name the resolver edge turns into an IPv4 literal at boot, N1), link_port, link_peer_short,
                     register_epmd, node_short, frame_max, summary (the sanitized boot summary, rule 11) and banner.
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
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bees_conf as C  # noqa: E402
import bees_dist_gen as D  # noqa: E402
import bees_wire_gen as W  # noqa: E402

BEAM_FRAME_MAX = C.BEAM_FRAME_MAX
ConfigError = C.ConfError


class BeamManifestError(Exception):
    """an error in the .beam manifest (build time, not a bees.config verdict)"""


def validate(cfg_path, manifest):
    """the one reader (tools/bees_conf.py) in the context of the manifest -> the effective BEAM-mode values"""
    conf = C.validate(cfg_path, manifest)
    if conf["mode"] != "beam":
        raise C.ConfError(1, "mode", "trust, but this program is built with the BEAM-mode node (tools/bees_config_beam.py)",
                          os.path.basename(cfg_path))
    eff = dict(conf["beam"])
    eff["creation"] = conf["node"]["creation"]
    return eff


# ---------------------------------------------------------------- generation
def lit(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def link_summary(eff):
    """`link=NAME role=ROLE[ via epmd]` for a one-link node (unchanged since N2); `links=N NAME:ROLE[:epmd],...` for more"""
    links = eff["links"]
    if len(links) == 1:
        return f"link={eff['link_peer_name']} role={'dial' if eff['link_dials'] else 'listen'}{' via epmd' if eff['link_by_epmd'] else ''}"
    return f"links={len(links)} " + ",".join(f"{k['name']}:{'dial' if k['dials'] else 'listen'}{':epmd' if k['by_epmd'] else ''}" for k in links)


def case_fn(name, ty, values, default):
    """fn NAME(i: int64) -> TY { case i of { 0 -> v0; ...; _: int64 -> default } }"""
    arms = "".join(f"        {k} -> {v};\n" for k, v in enumerate(values))
    return f"fn {name}(i: int64) -> {ty} {{\n    case i of {{\n{arms}        _: int64 -> {default}\n    }}\n}}"


def spec_fn(name, _unused, raw):
    """fn NAME() -> string: the bytes `raw` (bytes_of over a list literal: a string literal cannot hold a NUL byte), or "" """
    if not raw:
        return f'fn {name}() -> string {{ "" }}'
    return "\n".join([f"fn {name}() -> string {{", "    sequence proc[mem(normal), transport]",
                      f"        xs: List[int64, mem(normal)] <- [{', '.join(str(x) for x in raw)}];", "        s: string <- bytes_of(xs)",
                      "    produces pure s end", "}"])


def gen_conf(out_dir, eff, cfg_path):
    b = lambda v: "true" if v else "false"  # noqa: E731
    where = eff["listen_address"]
    banner = ("[bees] BEAM mode: Erlang cookie authentication, no encryption (transport tcp, %s); a downgrade from TRUST" % where
              if eff["auth"] == "cookie" else
              "[bees] BEAM mode with auth none: TEST ONLY, no authentication, no encryption (%s)" % where)
    tls = bool(eff.get("tls"))
    if tls:
        # N2T (spikes/N2T-beam-tls.md): the link is the Erlang distribution protocol inside TLS; the profile is fixed (ruled 2026-11-18)
        banner = ("[bees] BEAM mode: Erlang cookie authentication inside TLS 1.3 (transport tls, %s against cacertfile, %s); "
                  "key exchange X25519MLKEM768 or classical X25519; certificates Ed25519, ECDSA P-256 or RSA (PSS, 2048 bits or more); a downgrade from TRUST"
                  % (eff["tls_verify"], where))
    summary = (f"[bees] mode=beam node={eff['node']} transport={'tls tls_verify=' + eff['tls_verify'] if tls else 'tcp'} auth={eff['auth']} creation={eff['creation']} "
               f"epmd={eff['epmd']} epmd_port={eff['epmd_port']} net_tick io_ms={eff['io_ms']} tick_ms={eff['tick_ms']} "
               f"{link_summary(eff)} frame_size_max={eff['frame_max']}")
    ln = ["// Generated by tools/bees_config_beam.py from " + os.path.basename(cfg_path) + " and the manifest. Do not edit.",
          "// The effective BEAM-mode values (bees-config-file.md 5.1, 5.2), read at build time until the boot-time reader exists",
          "// (N0.2: tools/bees_conf.py is a build-time stand-in). The cookie is not here: only its file's path, which the native edge reads at each handshake.",
          "module beam_conf;", ""]
    fns = [
        ("auth_cookie", "boolean", b(eff["auth"] == "cookie")),
        ("cookie_path", "string", lit(eff["cookie_path"])),
        ("creation", "int64", str(eff["creation"])),
        ("epmd_external", "boolean", b(eff["epmd"] == "external")),
        ("epmd_address", "string", lit(f"127.0.0.1:{eff['epmd_port']}:{eff['open_ms']}")),
        ("open_text", "string", lit(str(eff["open_ms"]))),
        ("open_ms", "int64", str(eff["open_ms"])),
        ("epmd_port", "int64", str(eff["epmd_port"])),
        ("epmd_lookup_address", "string", lit(f"{eff['link_host']}:{eff['epmd_port']}:{eff['open_ms']}")),
        ("io_ms", "uint64", str(eff["io_ms"])),
        ("tick_ms", "uint64", str(eff["tick_ms"])),
        ("link_dials", "boolean", b(eff["link_dials"])),
        ("link_peer", "int64", str(eff["link_peer"])),
        ("link_address", "string", lit(eff["link_address"] + (f":{eff['open_ms']}" if eff["link_dials"] and eff["link_address"] else ""))),
        ("link_by_epmd", "boolean", b(eff["link_by_epmd"])),
        ("link_host", "string", lit(eff["link_host"])),
        ("link_resolve", "boolean", b(eff["link_dials"] and eff["link_host_kind"] == "name")),
        ("link_port", "int64", str(eff["link_port"])),
        ("link_peer_short", "string", lit(eff["link_peer_name"].split("@", 1)[0])),
        ("register_epmd", "boolean", b(eff["register_epmd"])),
        ("node_short", "string", lit(eff["node"].split("@", 1)[0])),
        ("frame_max", "int64", str(eff["frame_max"])),
        ("summary", "string", lit(summary)),
        ("banner", "string", lit(banner)),
        ("redial", "boolean", b(eff["redial"])),
        ("redial_initial_ms", "int64", str(eff["redial_initial_ms"])),
        ("redial_max_ms", "int64", str(eff["redial_max_ms"])),
        ("listens", "boolean", b(eff["listens"])),
        ("listener_address", "string", lit(eff["listener_address"])),
        ("tls", "boolean", b(tls)),
    ]
    # N2b: one entry per manifest peer line, indexed like bees_peers@peer_index (the scalars above are the first link's)
    links = eff["links"]
    host_of = lambda k: k["host"]  # noqa: E731
    indexed = [
        ("link_dials_of", "boolean", [b(k["dials"]) for k in links], "false"),
        ("link_by_epmd_of", "boolean", [b(k["by_epmd"]) for k in links], "false"),
        ("link_resolve_of", "boolean", [b(k["resolve"]) for k in links], "false"),
        ("link_host_of", "string", [lit(host_of(k)) for k in links], '""'),
        ("link_port_of", "int64", [str(k["port"]) for k in links], "0"),
        ("link_address_of", "string", [lit(k["address"] + (f":{eff['open_ms']}" if k["dials"] and k["address"] else "")) for k in links], '""'),
        ("epmd_lookup_address_of", "string", [lit(f"{k['host']}:{eff['epmd_port']}:{eff['open_ms']}") for k in links], '""'),
        ("peer_short", "string", [lit(k["name"].split("@", 1)[0]) for k in links], '""'),
    ]
    # N2T: what the TLS engine (native/tls, profile 16) is given at a connection's open: this node's certfile, keyfile and cacertfile
    # (absolute paths), a flag field the BEAM profile does not use ("0") and, for a dialed peer, the host part of the peer's node name,
    # which is sent as SNI and checked against the server's certificate (as a stock Erlang node does); each field is ended by a NUL
    # byte, so the value is written as bytes (a string literal cannot hold NUL). A plaintext node gets empty strings.
    paths = eff.get("tls_paths", {})
    own = b"".join(paths[kk].encode() + b"\0" for kk in ("certfile", "keyfile", "cacertfile")) + b"0\0" if tls else b""
    spec_fns = [spec_fn("tls_server_spec", "", own)]
    spec_fns += [spec_fn(f"tls_client_spec_{i}", "", own + k["name"].split("@", 1)[-1].encode() + b"\0" if tls and k["dials"] else b"")
                 for i, k in enumerate(links)]
    spec_fns.append(case_fn("tls_client_spec_of", "string", [f"tls_client_spec_{i}()" for i in range(len(links))], '""'))
    ln += [f"export {n}/0;" for n, _, _ in fns] + [f"export {n}/1;" for n, _, _, _ in indexed]
    ln += ["export tls_server_spec/0;", "export tls_client_spec_of/1;", ""]
    ln += [f"fn {n}() -> {t} {{ {v} }}" for n, t, v in fns]
    ln += [""] + [case_fn(n, t, vs, d) for n, t, vs, d in indexed] + spec_fns
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
                raise BeamManifestError(f"{where}: expected: pid <remote name> deliver <local name>")
            if t[1] not in rem:
                raise BeamManifestError(f"{where}: {t[1]} is not a remote name of the manifest")
            if t[3] not in loc:
                raise BeamManifestError(f"{where}: {t[3]} is not a local name of the manifest")
            if t[1] in pids:
                raise BeamManifestError(f"{where}: {t[1]} already hands out its pid")
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
    ex = ["start_proxies/3", "pid_local/1", "local_atom/1", "handed_count/0"]
    ln += [f"export {e};" for e in ex] + [""]
    for k, n in enumerate(rems):
        st = W.silica(msgs[n])
        wrap = (f"        p2: string <- beam_dist@with_pid(beam_dist@pid_bytes(bees_peers@node_name(), st.id, beam_conf@creation()), payload);"
                if n in pids else "        p2: string <- payload;")
        ln += [f"fn proxy_{n}(msg: {st}, st: {STATE}) -> (:no_reply, {STATE}) {{",
               "    sequence proc[concurrency]",
               f"        payload: string <- bees_msgs@enc_{n}(msg);",
               wrap,
               f"        body: string <- bees_dist@reg_send_body_max(p2, st.id, bees_peers@node_name(), beam_conf@creation(), bees_atoms@spelling(bees_atoms@a_{n}()), beam_conf@frame_max());",
               "        seg: string <- bees_dist@frame4(body);",
               "        _: boolean <- case length_bytes(body) > 0 of { true -> cast(st.tx, (:bees, 0, seg) impl ActorMessage {}); false -> true }",
               "    produces pure (:no_reply, st) end", "}", ""]
    # N2b/N2c: one reaper and one start_proxies_p<i> per peer (only the remotes declared @ that peer; a registered name is unique,
    # SD-33), shared with bees_peers (tools/bees_dist_gen.py per_peer_proxies); start_proxies(peer, tx, mgr) picks by the peer's index.
    # Every remote name of every peer is in bees_atoms from the manifest at compile time, so a listening node that learns its peer at
    # the handshake creates no atom at run time (user ruling 2026-11-16).
    ln += D.per_peer_proxies([p[0] for p in d["peers"]], [(n, pe) for n, pe, _ in d["remotes"]])
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
        eff = validate(cfg, d)
        pids = parse_beam(beam, d)
    except (ConfigError, BeamManifestError, D.DistError) as e:
        print(str(e), file=sys.stderr)
        return 1
    if cmd == "generate":
        os.makedirs(out, exist_ok=True)
        gen_conf(out, eff, cfg)
        gen_peers(out, d, msgs, pids)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
