"""The cases of D2 (tools/bees_pack_trial.py): configuration stores written by tools/bees_pack.py, read by the roots."""
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "tools"))
import bees_conf                    # noqa: E402
import bees_dist_gen                # noqa: E402
import bees_pack as P               # noqa: E402
import bees_pack_store as S         # noqa: E402

CAPACITY = 65536
# the ports are configuration VALUES: nothing in this leaf listens or dials (tools/trial_ports.py DATA_ONLY)
BEAM_CONFIG = """[ {mode, beam},
  {node, [{name, "a@localhost"}]},
  {beam, [{transport, tcp}, {frame_size_max, 4096}, {auth, cookie}, {cookie_file, "cookie"}, {listen_address, "127.0.0.1"},
          {listen_port, 23410}, {epmd, none}, {net_ticktime_s, 60}, {open_timeout_ms, 7000},
          {redial, true}, {redial_initial_ms, 500}, {redial_max_ms, 8000}]} ].
"""
BEAM_WIRE = """node   a@localhost
peer   b@localhost 127.0.0.1 23410 listen
peer   c@localhost 127.0.0.1 23411 dial
remote outbox @ b@localhost cast { op: atom, n: int64 }
local  inbox cast { op: atom, n: int64 }
"""
TRUST_CONFIG = """[
  {mode, trust},
  {node, [{name, "a@127.0.0.1"}]},
  {trust, [
    {port, 23412},
    {listen_address, "127.0.0.1"},
    {plaintext_test_only, true},
    {tls_opts, [{certfile, "certs/a.cert"}]},
    {whitelist_file, "trust_whitelist.config"},
    {whitelist_cert_dir, "certs"},
    {call_timeout_ms, 400},
    {first_frame_timeout_ms, 500},
    {suspicion_limit, 8},
    {frame_size_max, 8192},
    {args_len_max, 4096},
    {term_depth_max, 32}
  ]}
].
"""
WHITELIST = """#{
  "b.cert" => [{demo, [{add, 2}, {echo, 1}]}, {math, any}],
  "n.cert" => none
}.
"""
COOKIE = "d2-test-cookie-not-a-secret-of-anyone"      # a fixture; the trial checks that no output line shows it


def write(d, name, text, mode=0o644):
    p = os.path.join(d, name)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    os.chmod(p, mode)
    return p


def beam_records(d):
    write(d, "bees.config", BEAM_CONFIG)
    wire = write(d, "node.wire", BEAM_WIRE)
    write(d, "cookie", COOKIE + "\n", 0o600)
    conf = bees_conf.validate(os.path.join(d, "bees.config"), bees_dist_gen.parse([wire]))
    return P.records(conf)


def trust_records(d):
    write(d, "bees.config", TRUST_CONFIG)
    write(d, "trust_whitelist.config", WHITELIST)
    shutil.copytree(os.path.join(HERE, "certs"), os.path.join(d, "certs"))
    return P.records(bees_conf.validate(os.path.join(d, "bees.config")))


def put(d, mode, recs, name=None):
    table, img = P.by_schema(mode), S.Image(CAPACITY)
    for schema, value in recs:          # a kind outside the table is written as it is (a store that must be refused)
        img.append_value(schema, P._atoms(table[schema][3], value) if schema in table else {S.Atom(k): v for k, v in value.items()})
    with open(os.path.join(d, name or f"node_{mode}.sildat"), "wb") as f:
        f.write(img.bytes())


def reindex(recs):
    recs[0] = (1, dict(recs[0][1], frames=len(recs)))
    return recs


def beam_ok(d):
    # through the packer's command line, as a deployment would
    beam_records(d)
    rc = P.main(["bees_pack.py", "pack", "--config", os.path.join(d, "bees.config"), "--capacity", str(CAPACITY),
                 "-o", os.path.join(d, "node_beam.sildat"), os.path.join(d, "node.wire")])
    assert rc == 0


def edited(mode, change):
    def prepare(d):
        recs = beam_records(d) if mode == "beam" else trust_records(d)
        put(d, mode, change(recs))
    return prepare


def flipped(at):
    def prepare(d):
        data = bytearray(P.image(beam_records(d), "beam", CAPACITY).bytes())
        data[at] ^= 1
        with open(os.path.join(d, "node_beam.sildat"), "wb") as f:
            f.write(data)
    return prepare


def long_flipped(at):
    """A TRUST store of several blocks (40 more whitelist entries) with one byte wrong in its FIRST block: the carrier checks only
    the tail block when it opens, so the damage is met by the replay (a record) or drops the block (its header)."""
    def prepare(d):
        recs = trust_records(d)
        data = bytearray(P.image(reindex(recs + [recs[-1]] * 40), "trust", CAPACITY).bytes())
        assert len(S.records(bytes(data))) > 20 and data[4096:4096 + 16] != bytes(16)
        data[at] ^= 1
        with open(os.path.join(d, "node_trust.sildat"), "wb") as f:
            f.write(data)
    return prepare


def other_size(d):
    with open(os.path.join(d, "node_beam.sildat"), "wb") as f:
        f.write(P.image(beam_records(d), "beam", CAPACITY).bytes()[:32768])


def wrong_mode(d):
    put(d, "trust", trust_records(d), "node_beam.sildat")


def set_in(schema, key, value):
    def change(recs):
        return [(s, dict(v, **{key: value}) if s == schema else v) for s, v in recs]
    return change


def no_secret(d):
    """No output of this leaf may show the cookie."""
    leaked = []
    for f in sorted(os.listdir(HERE)):
        if f.endswith(".sout"):
            with open(os.path.join(HERE, f), encoding="utf-8", errors="replace") as fh:
                if COOKIE in fh.read():
                    leaked.append(f)
    return ["the cookie appears in no output" if not leaked else "THE COOKIE APPEARS IN: " + " ".join(leaked)]


def case(name, mode, prepare, after=None):
    c = {"name": name, "exe": f"dangerous_d2_{mode}", "prepare": prepare}
    if after:
        c["after"] = after
    return c


CASES = [
    case("beam_ok", "beam", beam_ok),
    case("trust_ok", "trust", edited("trust", lambda r: r)),
    case("beam_absent", "beam", None),
    case("beam_other_size", "beam", other_size),
    case("beam_flipped_record", "beam", flipped(16 + 16 + 20)),
    case("beam_flipped_header", "beam", flipped(3)),
    case("beam_trust_store", "beam", wrong_mode),
    case("beam_truncated", "beam", edited("beam", lambda r: r[:-1])),
    case("beam_node_twice", "beam", edited("beam", lambda r: reindex(r + [r[1]]))),
    case("beam_time_missing", "beam", edited("beam", lambda r: reindex([x for x in r if x[0] != 11]))),
    case("beam_unknown_kind", "beam", edited("beam", lambda r: reindex(r[:2] + [(20, {"x": 1})] + r[2:]))),
    case("beam_out_of_bounds", "beam", edited("beam", set_in(10, "listen_port", 70000))),
    case("beam_wrong_shape", "beam", edited("beam", set_in(11, "io_ms", "sixty thousand"))),
    case("beam_not_index", "beam", edited("beam", lambda r: r[1:])),
    case("trust_flipped_record", "trust", long_flipped(16 + 16 + 60 + 16 + 20)),
    case("trust_flipped_header", "trust", long_flipped(3)),
    case("trust_cross_rule", "trust", edited("trust", set_in(21, "args_len_max", 9000))),
    case("trust_long_list_ok", "trust", edited("trust", lambda r: reindex(r + [r[-1]] * 40)), no_secret),
]
