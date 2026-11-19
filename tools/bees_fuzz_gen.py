#!/usr/bin/env python3
"""F1 (fuzzer): the case generators and the oracle models of every wire surface. Pure functions; no clock, no network.

A case is a JSON-able dict: {"surface", "index", "kind", "steps": [...], ...}. `steps` is a small script the driver
(tools/bees_fuzz.py) plays against a node; bytes are hex text. case(seed, surface, index) is the same dict on every machine.

Surfaces (SURFACES below says which are live):
  beam_accept   the driver dials a listening BEAM-mode node as a hostile peer: the handshake and distribution frames
  beam_dial     a dialing BEAM-mode node asks the driver's EPMD and dials the driver's listener: hostile EPMD replies, a hostile
                acceptor handshake, hostile frames
  epmd_register a listening node registers with the driver's EPMD at boot: hostile ALIVE2 replies
  trust_plain   the driver dials a TRUST server over plaintext test mode: fingerprint stand-in, token step, request frames
  trust_tls     the same frames inside mutual TLS 1.3, and raw bytes at the TLS listener
  trust_client  a TRUST client (plaintext test mode) dials the driver: hostile token_issue and result frames
  resolve       resolver answers through the one filter (bees_addr), as generated vectors compiled into a trial program
  tempus        NOT LIVE: a documented hook (development-plan/spikes/F1-fuzzer.md)

The models say what a correct receiver may do with the exact bytes of a case; the driver compares what the node did:
  beam_model(stream)   the frames a receiver reads from the bytes sent after the handshake, each "valid", "maybe" or "invalid"
  trust_model(...)     whether the request of a connection may be executed, and with which arguments
Only a certain verdict is ever a finding: a delivery or an execution the model calls impossible ("invalid").
"""
import hashlib
import struct

import bees_fuzz_etf as E

FLAGS = bytes([0, 0, 0, 4, 3, 7, 15, 157])           # BEES's BEAM-mode flags 0x4_0307_0F9D (N2 ruling 2)
COOKIE = b"f1-fuzz-cookie"                           # the trial's fixed test cookie (trials/f1_fuzz_wire/nodes/cookie)
PEER = "stock@localhost"                             # the node name the driver plays
FRAME_CAP = 4096                                     # frame_size_max of every node under test
HELD = ["hello", "reply", "inc", "probe"]            # op atoms the BEAM nodes under test hold (node.atoms)
SOME_ATOMS = HELD + ["op", "n", "inbox", "outbox", "", "ok", "true", "false", "undefined", "nonode@nohost", PEER]

SURFACES = {
    "beam_accept": True, "beam_dial": True, "epmd_register": True, "trust_plain": True, "trust_tls": True, "trust_client": True, "resolve": True,
    "tempus": False,
}
TEMPUS_REASON = "TEMPUS has no live wire surface yet (frames exist in memory only, no node listens or dials; src/tempus is in flux)"


def hx(b):
    return bytes(b).hex()


def f2(b):
    return struct.pack(">H", len(b) & 0xFFFF) + b


def f4(b):
    return struct.pack(">I", len(b)) + b


def digest(challenge, cookie=COOKIE):
    return hashlib.md5(cookie + str(challenge).encode()).digest()


# ---- BEAM mode: messages ----
def name_msg(name=PEER, flags=FLAGS, creation=1, challenge=None):
    nb = name.encode() if isinstance(name, str) else name
    mid = b"" if challenge is None else struct.pack(">I", challenge)
    return b"N" + flags + mid + struct.pack(">I", creation) + struct.pack(">H", len(nb)) + nb


def my_pid(ident=77):
    return E.pid(PEER, ident, 0, 1)


def reg_send(target, from_pid=None):
    return E.term(E.tup([E.integer(6), from_pid or my_pid(), E.atom(""), E.atom(target)]))


def payload(op, n):
    return E.term(E.emap([(E.atom("n"), E.integer(n)), (E.atom("op"), E.atom(op))]))


def dist_frame(ctl, pay):
    return f4(b"p" + ctl + pay)


def good_frame(target, op, n):
    return dist_frame(reg_send(target), payload(op, n))


def judge_payload(b):
    """("valid" | "maybe" | "invalid", op, n) for the payload bytes of a frame whose type is { op: atom, n: int64 }"""
    try:
        v = E.read_term(b)
    except E.Bad:
        return ("invalid", None, None)
    if not (isinstance(v, tuple) and v[0] == "map"):
        return ("invalid", None, None)
    keys = [k for k, _ in v[1]]
    if sorted(map(repr, keys)) != sorted(map(repr, [("atom", "op"), ("atom", "n")])):
        return ("invalid", None, None)               # a missing, extra, repeated or non-atom key
    d = {k[1]: x for k, x in v[1]}
    op, n = d["op"], d["n"]
    if not (isinstance(op, tuple) and op[0] == "atom") or isinstance(n, bool) or not isinstance(n, int):
        return ("invalid", None, None)
    if not -(1 << 63) <= n < (1 << 63) or op[1].startswith(E.UNKNOWN_PREFIX):
        return ("invalid", None, None)
    if op[1] in HELD and b == payload(op[1], n):
        return ("valid", op[1], n)
    return ("maybe", op[1], n)


DELIVERING_OPS = (2, 6, 12, 16, 22, 33)              # SEND, REG_SEND, their trace-token forms, SEND_SENDER, ALIAS_SEND


def judge_body(body, target):
    """one frame body (after its 4-byte length): ("tick",) or (verdict, op, n)"""
    if len(body) == 0:
        return ("tick",)
    if body[0] != 112 or len(body) < 3 or body[1] != 131:
        return ("invalid", None, None)
    try:
        ctl, pos = E.read(body, 2)
    except E.Bad:
        return ("invalid", None, None)
    if not (isinstance(ctl, tuple) and ctl[0] == "tuple" and ctl[1] and isinstance(ctl[1][0], int) and not isinstance(ctl[1][0], bool)
            and ctl[1][0] in DELIVERING_OPS):
        return ("invalid", None, None)
    v, op, n = judge_payload(body[pos:])
    if v == "valid" and body[:pos] != b"p" + reg_send(target):
        v = "maybe"
    return (v, op, n)


def beam_model(stream, target, cap=FRAME_CAP):
    """what a correct receiver reads from the bytes sent after a completed handshake: {"frames": [(verdict, op, n)...],
    "violation": bool (a length above the cap: the link must close and nothing after it is read), "partial": bool}"""
    out, pos, violation, partial = [], 0, False, False
    while pos < len(stream):
        if pos + 4 > len(stream):
            partial = True
            break
        n = struct.unpack(">I", stream[pos:pos + 4])[0]
        if n > cap:
            violation = True
            break
        if pos + 4 + n > len(stream):
            partial = True
            break
        j = judge_body(stream[pos + 4:pos + 4 + n], target)
        if j[0] != "tick":
            out.append(j)
        pos += 4 + n
    return {"frames": out, "violation": violation, "partial": partial}


# ---- BEAM mode: hostile material ----
def hostile_payload(rng, canary):
    """payload bytes for a frame with a good control message"""
    k = rng.below(14)
    good = payload(rng.pick(HELD), canary)
    if k <= 2:
        return "mutated", E.mutate(rng, good)
    if k == 3:
        return "random_term", E.term(E.any_term(rng, SOME_ATOMS))
    if k == 4:
        return "raw_bytes", rng.bytes(rng.between(0, 40))
    if k == 5:
        return "bad_version", bytes([rng.pick([130, 0, 132, 80, 68])]) + good[1:]
    if k == 6:
        return "unknown_atom_op", E.term(E.emap([(E.atom("n"), E.integer(canary)), (E.atom("op"), E.unknown_atom(rng))]))
    if k == 7:
        extra = [(E.atom(rng.pick(["x", "op2", "n ", E.UNKNOWN_PREFIX + "k"])), E.any_term(rng, SOME_ATOMS, 0))]
        pairs = [(E.atom("n"), E.integer(canary)), (E.atom("op"), E.atom("inc"))]
        pairs.insert(rng.below(3), extra[0])
        return "extra_key", E.term(E.emap(pairs))
    if k == 8:
        return "missing_key", E.term(E.emap([rng.pick([(E.atom("n"), E.integer(canary)), (E.atom("op"), E.atom("inc"))])]))
    if k == 9:
        return "repeated_key", E.term(E.emap([(E.atom("n"), E.integer(canary)), (E.atom("op"), E.atom("inc")), (E.atom("n"), E.integer(canary))]))
    if k == 10:
        return "wrong_type_n", E.term(E.emap([(E.atom("n"), rng.pick([E.new_float(1.5), E.binary(b"7"), E.atom("inc"), E.lst([E.integer(1)]), E.any_int(rng), E.big(1 << 63), E.big(-(1 << 63) - 1), E.big(1 << 200)])),
                                              (E.atom("op"), E.atom("inc"))]))
    if k == 11:
        return "wrong_type_op", E.term(E.emap([(E.atom("n"), E.integer(canary)), (E.atom("op"), rng.pick([E.integer(1), E.binary(b"inc"), E.lst([]), E.tup([E.atom("inc")]), my_pid()]))]))
    if k == 12:
        return "atom_encodings", E.term(E.emap([(E.atom("n", rng.pick([119, 118, 100, 115])), rng.pick([E.integer(canary), E.big(canary), E.big(canary, 111)])),
                                                (E.atom("op", rng.pick([119, 118, 100, 115])), E.atom(rng.pick(HELD), rng.pick([119, 118, 100, 115])))]))
    return "deep", E.term(E.nested(rng, rng.pick(E.NEST_DEPTHS), E.emap([(E.atom("n"), E.integer(canary)), (E.atom("op"), E.atom("inc"))])))


def hostile_control(rng, target):
    k = rng.below(10)
    if k <= 1:
        return "mutated", E.mutate(rng, reg_send(target))
    if k == 2:
        return "random_term", E.term(E.any_term(rng, SOME_ATOMS))
    if k == 3:                                       # every control operation, with a plausible or a wrong arity
        op = rng.below(41)
        items = [E.integer(op)] + [rng.pick([my_pid(), E.atom(""), E.atom(target), E.integer(rng.below(1 << 20)), E.pid("bl@localhost", rng.below(4), 0, 1),
                                             E.any_term(rng, SOME_ATOMS, 0)]) for _ in range(rng.below(6))]
        return "op_%d" % op, E.term(E.tup(items))
    if k == 4:
        return "foreign_pid", E.term(E.tup([E.integer(6), E.pid(rng.pick(["x@127.0.0.1", "bl@localhost", E.UNKNOWN_PREFIX + "n@h"]), rng.below(99), 0, rng.below(3)), E.atom(""), E.atom(target)]))
    if k == 5:
        return "unknown_name", E.term(E.tup([E.integer(6), my_pid(), E.atom(""), rng.pick([E.unknown_atom(rng), E.atom("net_kernel"), E.atom("rex"), E.atom("outbox"), E.atom("")])]))
    if k == 6:                                       # SEND to a pid: the handed-out one (id 0), ones never handed out, other nodes'
        return "send_pid", E.term(E.tup([E.integer(2), E.atom(""), E.pid(rng.pick(["bl@localhost", "bd@localhost", PEER]), rng.pick([0, 0, 1, 2, 99, 1 << 31]), rng.below(3), rng.pick([1, 1, 0, 2]))]))
    if k == 7:
        return "deep", E.term(E.nested(rng, rng.pick(E.NEST_DEPTHS), E.tup([E.integer(6), my_pid(), E.atom(""), E.atom(target)])))
    if k == 8:                                       # net_kernel's is_auth call, well-formed and damaged
        call = E.tup([E.atom("$gen_call"), E.tup([my_pid(), rng.pick([E.lst([E.atom("alias")], bytes([90, 0, 1]) + E.atom(PEER) + bytes(8)), E.any_term(rng, SOME_ATOMS, 0)])]),
                      E.tup([E.atom("is_auth"), E.atom(PEER)])])
        ctl = E.term(E.tup([E.integer(6), my_pid(), E.atom(""), E.atom("net_kernel")]))
        return "is_auth", ctl + (E.term(call) if rng.chance(1, 2) else E.mutate(rng, E.term(call)))
    return "large_tuple", E.term(E.tup([E.integer(6), my_pid(), E.atom(""), E.atom(target)], large=True))


def hostile_stream(rng, target, canary):
    """(kind, bytes sent after the handshake, same_link_probe): one hostile frame or framing game, between good frames"""
    k = rng.weighted([(30, "payload"), (22, "control"), (10, "length"), (6, "body"), (6, "batch"), (4, "ticks")])
    if k == "payload":
        kind, pay = hostile_payload(rng, canary)
        return "payload/" + kind, dist_frame(reg_send(target), pay), True
    if k == "control":
        kind, ctl = hostile_control(rng, target)
        if kind == "is_auth":
            return "control/" + kind, f4(b"p" + ctl), True
        return "control/" + kind, dist_frame(ctl, payload("inc", canary)), True
    if k == "body":                                  # the pass-through byte and what follows it
        good = b"p" + reg_send(target) + payload("inc", canary)
        j = rng.below(5)
        if j == 0:
            return "body/type_byte", f4(bytes([rng.pick([68, 131, 0, 113, 255])]) + good[1:]), True
        if j == 1:
            return "body/one_byte", f4(bytes([rng.below(256)])), True
        if j == 2:
            return "body/no_payload", f4(b"p" + reg_send(target)), True
        if j == 3:
            return "body/random", f4(rng.bytes(rng.between(1, 300))), True
        return "body/mutated", f4(E.mutate(rng, good)), True
    if k == "length":
        good = b"p" + reg_send(target) + payload("inc", canary)
        j = rng.below(7)
        if j == 0:
            return "length/over_cap", struct.pack(">I", rng.pick([4097, 4098, 65536, 1 << 24, 0x7FFFFFFF, 0x80000000, 0xFFFFFFFF])) + good, False
        if j == 1:
            return "length/at_cap", f4(b"p" + reg_send(target) + payload("inc", canary) + rng.bytes(0))[:4] and f4((b"p" + reg_send(target) + E.term(E.binary(rng.bytes(4096))))[:rng.pick([4095, 4096])]), True
        if j == 2:
            return "length/overstated", struct.pack(">I", len(good) + rng.between(1, 60)) + good, False
        if j == 3:
            return "length/understated", struct.pack(">I", max(0, len(good) - rng.between(1, len(good)))) + good, False
        if j == 4:
            return "length/partial_prefix", rng.bytes(rng.between(1, 3)), False
        if j == 5:
            return "length/partial_frame", f4(good)[:rng.between(4, len(good) + 3)], False
        return "length/random_prefix", rng.bytes(4) + good, False
    if k == "batch":                                 # good and bad frames in one write
        parts, n = [], rng.between(2, 6)
        for i in range(n):
            if rng.chance(1, 2):
                parts.append(good_frame(target, rng.pick(HELD), canary + 1 + i))
            else:
                parts.append(dist_frame(reg_send(target), hostile_payload(rng, canary + 1 + i)[1]))
        return "batch/mixed", b"".join(parts), True
    return "ticks/flood", bytes(4 * rng.pick([1, 10, 500, 3000])), True


# ---- surface: beam_accept ----
def case_beam_accept(rng, index):
    canary = 1000 * (index + 1)
    c = {"target": "inbox", "canary": canary}
    k = rng.weighted([(60, "frames"), (10, "pre"), (12, "name"), (12, "auth"), (6, "slow")])
    if k == "frames":
        kind, stream, same = hostile_stream(rng, "inbox", canary)
        lead = good_frame("inbox", "hello", canary + 900) if rng.chance(1, 5) else b""
        c.update(kind="frames/" + kind, steps=[["hs", "good"], ["post", hx(lead + stream)]], auth="yes", same_link_probe=same)
    elif k == "slow":                                # a good frame and a hostile one written in small pieces
        kind, stream, same = hostile_stream(rng, "inbox", canary)
        c.update(kind="slow/" + kind, steps=[["hs", "good"], ["post_chunks", hx(good_frame("inbox", "inc", canary + 900) + stream), rng.pick([1, 2, 3, 7])]], auth="yes", same_link_probe=same)
    elif k == "pre":                                 # bytes instead of a handshake
        j = rng.below(6)
        raw = [rng.bytes(rng.between(1, 64)), bytes(rng.between(1, 8)), struct.pack(">H", rng.pick([0, 1, 65535])) + rng.bytes(rng.below(40)),
               good_frame("inbox", "inc", canary), f2(b"N") + good_frame("inbox", "inc", canary), b"\x16\x03\x01\x02\x00\x01\x00\x01\xfc\x03\x03" + rng.bytes(40)][j]
        c.update(kind="pre/%d" % j, steps=[["raw", hx(raw)], ["drain"]], auth="no", same_link_probe=False)
    elif k == "name":                                # the initiator's name message, damaged; then the rest of a handshake as far as it goes
        j = rng.below(9)
        good = name_msg()
        if j == 0:
            msg, auth = E.mutate(rng, good), "maybe"
        elif j == 1:
            msg, auth = name_msg(rng.pick(["intruder@localhost", "stock@127.0.0.1", "bl@localhost", "stock", "@", "stock@localhost ", "STOCK@LOCALHOST"])), "no"
        elif j == 2:
            msg, auth = name_msg(flags=rng.pick([bytes(8), b"\xff" * 8, rng.bytes(8), bytes([0, 0, 0, 0, 3, 7, 15, 157]), bytes([0, 0, 0, 4, 3, 7, 15, 156])])), "maybe"
        elif j == 3:
            msg, auth = name_msg("a" * rng.pick([0, 255, 256, 300, 4000]) + "@localhost"), "no"
        elif j == 4:
            msg, auth = good[:-rng.between(1, len(good) - 1)], "no"
        elif j == 5:
            msg, auth = b"n" + struct.pack(">H", 5) + FLAGS[4:] + PEER.encode(), "maybe"      # the old (version 5) name message
        elif j == 6:
            msg, auth = bytes([rng.below(256)]) + good[1:], "maybe"
        elif j == 7:
            msg, auth = good + rng.bytes(rng.between(1, 30)), "maybe"
        else:
            msg, auth = good[:13] + struct.pack(">H", rng.pick([0, 1, 14, 16, 200, 65535])) + PEER.encode(), "maybe"
        c.update(kind="name/%d" % j, steps=[["raw", hx(f2(msg))], ["hs_rest", "good"], ["post", hx(good_frame("inbox", "inc", canary))]], auth=auth, same_link_probe=False)
    else:                                            # the challenge reply
        mode = rng.pick(["bad_digest", "no_reply", "truncated_reply", "wrong_tag", "long_reply", "zero_digest"])
        c.update(kind="auth/" + mode, steps=[["hs", mode], ["post", hx(good_frame("inbox", "inc", canary) + good_frame("inbox", "hello", canary + 1))]],
                 auth="no", same_link_probe=False)
    return c


# ---- surface: beam_dial (EPMD replies and the acceptor's side of the handshake) ----
def port2_resp(port, name="stock"):
    nb = name.encode()
    return bytes([119, 0]) + struct.pack(">H", port) + bytes([77, 0]) + struct.pack(">HH", 6, 6) + struct.pack(">H", len(nb)) + nb + b"\x00\x00"


def case_beam_dial(rng, index):
    canary = 1000 * (index + 1)
    c = {"target": "outbox", "canary": canary, "epmd": "good", "same_link_probe": False}
    k = rng.weighted([(10, "epmd"), (30, "acceptor"), (60, "frames")])
    if k == "epmd":
        j = rng.below(10)
        good = port2_resp(0)                         # the driver writes its listener's port into bytes 2..3 of a "port" reply
        reply = [rng.bytes(rng.between(1, 40)), bytes([119, rng.between(1, 255)]), bytes([119]), bytes([119, 0]), bytes([119, 0, 0]),
                 b"", bytes([rng.pick([118, 121, 110, 0, 255])]) + rng.bytes(8), good + rng.bytes(rng.pick([1, 100, 60000])),
                 E.mutate(rng, good), bytes([119, 0, 0, 0]) + rng.bytes(8)][j]
        names = ["random", "not_found", "one_byte", "no_port", "half_port", "empty_close", "other_reply", "long", "mutated", "port_zero"]
        c.update(kind="epmd/" + names[j], epmd={"reply": hx(reply), "own_port": j in (7,), "hold": rng.chance(1, 6)}, steps=[["accept_any"]], auth="maybe" if j in (7, 8) else "no")
        if j == 5 and rng.chance(1, 2):
            c["epmd"] = {"reply": "", "silent": True, "hold": True}
            c["kind"] = "epmd/silent"
    elif k == "acceptor":
        j = rng.below(12)
        mode = ["status_nok", "status_not_allowed", "status_alive", "status_random", "status_long", "challenge_mutated", "challenge_other_name",
                "challenge_truncated", "ack_bad_digest", "ack_missing", "ack_wrong_tag", "status_named"][j]
        auth = "no" if mode in ("challenge_other_name", "ack_bad_digest", "ack_missing", "ack_wrong_tag", "status_nok", "status_not_allowed") else "maybe"
        c.update(kind="acceptor/" + mode, steps=[["acc", mode, hx(rng.bytes(64))], ["post", hx(good_frame("outbox", "inc", canary) + good_frame("outbox", "probe", canary + 1))]], auth=auth)
    else:
        kind, stream, same = hostile_stream(rng, "outbox", canary)
        c.update(kind="frames/" + kind, steps=[["acc", "good", ""], ["post", hx(stream)]], auth="yes", same_link_probe=same)
    return c


# ---- surface: epmd_register (the reply to ALIVE2_REQ at the node's boot) ----
def case_epmd_register(rng, index):
    j = rng.below(10)
    reply = [rng.bytes(rng.between(1, 40)), bytes([118, rng.between(1, 255), 0, 0, 0, 1]), bytes([118]), bytes([118, 0, 0]), bytes([121, 0, 0, 1]), bytes([121, 1, 0, 0]),
             b"", bytes([118, 0]) + rng.bytes(4) + rng.bytes(rng.pick([1, 200, 60000])), bytes([rng.below(256)]) + rng.bytes(5), bytes([118, 0, 255, 255, 255, 255])][j]
    names = ["random", "refused", "one_byte", "half", "old_ok", "old_refused", "empty_close", "long", "other_tag", "creation_max"]
    return {"kind": "alive2/" + names[j], "epmd": {"reply": hx(reply), "hold": rng.chance(1, 2)}, "steps": [], "canary": 1000 * (index + 1), "target": "inbox", "auth": "yes"}


# ---- TRUST: frames and the model ----
T_ATOMS = ["demo", "add", "echo", "crash", "note", "secret", "badarith", "apply", "erlang", "bees_trust_admin", "reset", "t", "ver", "req_id", "m", "f", "a", "args", "opts", "value",
           "token", "hello", "token_present", "token_issue", "result", "call", "cast", "ok", "error"]
PERMITTED = {("demo", "add", 2): "int", ("demo", "echo", 1): "bin", ("demo", "crash", 1): "int", ("demo", "note", 1): "int"}
ARGS_CAP = 1024
DEPTH_CAP = 32


def t_hello(ver=1):
    return E.term(E.emap([(E.atom("t"), E.atom("hello")), (E.atom("ver"), E.integer(ver))]))


def t_token_present(tok):
    return E.term(E.emap([(E.atom("t"), E.atom("token_present")), (E.atom("token"), E.binary(tok)), (E.atom("ver"), E.integer(1))]))


def t_request(kind, m, f, args, rid=b"r1", arity=None, opts=None, ver=1, extra=()):
    pairs = [(E.atom("a"), E.integer(len(args) if arity is None else arity)), (E.atom("args"), E.lst(args)), (E.atom("f"), E.atom(f)), (E.atom("m"), E.atom(m)),
             (E.atom("opts"), E.emap([]) if opts is None else opts), (E.atom("req_id"), E.binary(rid)), (E.atom("t"), E.atom(kind)), (E.atom("ver"), E.integer(ver))]
    return E.term(E.emap(pairs + list(extra)))


def _span_of_args(body):
    """the byte length of the args value in a frame the lenient reader accepts (the map's values are walked again)"""
    pos = 6
    n = struct.unpack(">I", body[2:6])[0]
    for _ in range(n):
        k, kp = E.read(body, pos)
        _, vp = E.read(body, kp)
        if k == ("atom", "args"):
            return vp - kp
        pos = vp
    return 0


def judge_request(body):
    """("valid" | "maybe" | "invalid", {"m","f","args"} or None) for a request frame's body"""
    try:
        v = E.read_term(body)
    except E.Bad:
        return ("invalid", None)
    if not (isinstance(v, tuple) and v[0] == "map") or len(v[1]) > 16:
        return ("invalid", None)
    if any(not (isinstance(k, tuple) and k[0] == "atom") for k, _ in v[1]):
        return ("invalid", None)
    names = [k[1] for k, _ in v[1]]
    if len(set(names)) != len(names) or E.has_other(v) or E.depth_of(v) > DEPTH_CAP + 2:
        return ("invalid", None)
    if any(a.startswith(E.UNKNOWN_PREFIX) for a in E.atoms_of(v)):
        return ("invalid", None)
    d = dict(zip(names, [x for _, x in v[1]]))
    # opts may be absent: BEES reads a missing opts as the empty map (bees_trust_frame@parse_req refuses it only when it is
    # there and no map); whether SEMP requires the key is an owner question of the spike document
    if any(k not in d for k in ("t", "ver", "req_id", "m", "f", "a", "args")):
        return ("invalid", None)
    if d["ver"] != 1 or isinstance(d["ver"], bool) or d["t"] not in (("atom", "call"), ("atom", "cast")):
        return ("invalid", None)
    rid = d["req_id"]
    if not (isinstance(rid, tuple) and rid[0] == "bin" and 1 <= len(rid[1]) <= 16):
        return ("invalid", None)
    if not all(isinstance(d[k], tuple) and d[k][0] == "atom" for k in ("m", "f")) or isinstance(d["a"], bool) or not isinstance(d["a"], int):
        return ("invalid", None)
    kind = PERMITTED.get((d["m"][1], d["f"][1], d["a"]))
    args = d["args"]
    if kind is None or not (isinstance(args, tuple) and args[0] == "list" and args[2] is None) or len(args[1]) != d["a"]:
        return ("invalid", None)
    if "opts" in d and not (isinstance(d["opts"], tuple) and d["opts"][0] == "map"):
        return ("invalid", None)
    for x in args[1]:
        if kind == "int" and (isinstance(x, bool) or not isinstance(x, int) or not -(1 << 63) <= x < (1 << 63)):
            return ("invalid", None)
        if kind == "bin" and not (isinstance(x, tuple) and x[0] == "bin"):
            return ("invalid", None)
    if _span_of_args(body) > ARGS_CAP:
        return ("invalid", None)
    what = {"m": d["m"][1], "f": d["f"][1], "args": [x if isinstance(x, int) else x[1].hex() for x in args[1]], "t": d["t"][1]}
    canonical = t_request(d["t"][1], d["m"][1], d["f"][1], [E.integer(x) if isinstance(x, int) else E.binary(x[1]) for x in args[1]], rid[1])
    return ("valid" if body == canonical and "opts" in d else "maybe", what)


def judge_first(body):
    """the first frame: "hello", "token_present", "maybe" (a decoder might take it for one of them) or "invalid\""""
    try:
        v = E.read_term(body)
    except E.Bad:
        return "invalid"
    if not (isinstance(v, tuple) and v[0] == "map") or len(v[1]) > 16 or any(not (isinstance(k, tuple) and k[0] == "atom") for k, _ in v[1]):
        return "invalid"
    names = [k[1] for k, _ in v[1]]
    d = dict(zip(names, [x for _, x in v[1]]))
    if len(set(names)) != len(names) or E.has_other(v) or d.get("ver") != 1 or any(a.startswith(E.UNKNOWN_PREFIX) for a in E.atoms_of(v)):
        return "invalid"
    if d.get("t") == ("atom", "hello"):
        return "hello" if body == t_hello() else "maybe"
    if d.get("t") == ("atom", "token_present"):
        return "token_present"
    return "invalid"


def trust_model(stream, live_token=False, cap=FRAME_CAP):
    """stream: the bytes sent after the peer identity was established (after the 64-byte stand-in on plaintext). Returns
    {"may_execute": bool, "request": what or None, "verdict": ...}: whether a correct server may run the request."""
    frames, pos = [], 0
    while pos + 4 <= len(stream) and len(frames) < 2:
        n = struct.unpack(">I", stream[pos:pos + 4])[0]
        if n > cap or pos + 4 + n > len(stream):
            break
        frames.append(stream[pos + 4:pos + 4 + n])
        pos += 4 + n
    no = {"may_execute": False, "request": None, "verdict": "invalid"}
    if len(frames) < 2:
        return no
    first = judge_first(frames[0])
    if first == "invalid" or (first == "token_present" and not live_token):
        return no
    v, what = judge_request(frames[1])
    if v == "invalid":
        return no
    return {"may_execute": True, "request": what, "verdict": v if first in ("hello", "token_present") else "maybe"}


def hostile_request(rng, canary):
    """(kind, request frame body)"""
    note = [E.integer(canary)]
    good = t_request("cast" if rng.chance(1, 2) else "call", "demo", "note", note)
    k = rng.below(24)
    if k <= 2:
        return "mutated", E.mutate(rng, good)
    if k == 3:
        return "random_term", E.term(E.any_term(rng, T_ATOMS))
    if k == 4:
        return "random_map", E.term(E.emap([(E.atom(rng.pick(T_ATOMS)), E.any_term(rng, T_ATOMS, 2)) for _ in range(rng.between(0, 18))]))
    if k == 5:
        return "ver", t_request("call", "demo", "note", note, ver=rng.pick([0, 2, 255, 256, -1, 1 << 40]))
    if k == 6:
        return "req_id_len", t_request("call", "demo", "note", note, rid=rng.bytes(rng.pick([0, 17, 18, 64, 300])))
    if k == 7:
        return "forbidden_mfa", t_request(rng.pick(["call", "cast"]), *rng.pick([("erlang", "apply"), ("bees_trust_admin", "reset"), ("demo", "secret"), ("erlang", "note"), ("demo", "apply")]), note)
    if k == 8:
        return "unknown_atom", t_request("call", "demo", "note", note).replace(E.atom(rng.pick(["demo", "note", "call"])), E.unknown_atom(rng), 1)
    if k == 9:
        return "arity", t_request("call", "demo", rng.pick(["note", "add"]), note, arity=rng.pick([0, 2, 3, 255, -1, 1 << 33]))
    if k == 10:
        return "args_count", t_request("call", "demo", "note", [E.integer(canary)] * rng.pick([0, 2, 3, 50]), arity=1)
    if k == 11:
        return "args_type", t_request("call", "demo", rng.pick(["note", "add", "echo"]), [rng.pick([E.binary(b"x"), E.atom("demo"), E.new_float(2.0), E.big(1 << 64), E.lst([E.integer(canary)]), E.tup([]), E.integer(canary)]) for _ in range(rng.between(1, 2))])
    if k == 12:
        return "args_large", t_request("call", "demo", "echo", [E.binary(rng.bytes(rng.pick([1000, 1015, 1016, 1017, 1024, 1030, 3000, 4000, 4090])))])
    if k == 13:
        return "opts", t_request("call", "demo", "note", note, opts=rng.pick([E.integer(0), E.lst([]), E.atom("ok"), E.emap([(E.atom("ok"), E.any_term(rng, T_ATOMS, 2))]), E.emap([(E.integer(1), E.integer(2))])]))
    if k == 14:
        return "t", t_request(rng.pick(["hello", "result", "token_issue", "token_present", "ok", "demo"]), "demo", "note", note)
    if k == 15:
        n = rng.pick([1, 8, 9, 10])
        return "extra_keys_%d" % (8 + n), t_request("cast", "demo", "note", note, extra=[(E.atom("x%d" % i if rng.chance(1, 2) else E.UNKNOWN_PREFIX + "%d" % i), E.integer(i)) for i in range(n)])
    if k == 16:
        return "repeated_key", t_request("cast", "demo", "note", note, extra=[(E.atom(rng.pick(["t", "ver", "args", "m"])), E.integer(1))])
    if k == 17:
        key = rng.pick(["t", "ver", "req_id", "m", "f", "a", "args", "opts"])
        v = E.read_term(good)
        return "missing_" + key, E.term(E.emap([p for p in _pairs(good) if p[0] != E.atom(key)]))
    if k == 18:
        return "deep_args", t_request("call", "demo", "note", [E.nested(rng, rng.pick([29, 30, 31, 32, 33, 34, 64, 199, 400]), E.integer(canary))])
    if k == 19:
        return "deep_opts", t_request("cast", "demo", "note", note, opts=E.emap([(E.atom("ok"), E.nested(rng, rng.pick([29, 30, 31, 32, 33, 64, 400]), E.integer(1)))]))
    if k == 20:
        return "unsupported_term", t_request("cast", "demo", "note", note, opts=E.emap([(E.atom("ok"), rng.pick([my_pid(), bytes([90, 0, 1]) + E.atom("ok") + bytes(8), bytes([77, 0, 0, 0, 1, 3, 0xA0]), bytes([113]) + E.atom("erlang") + E.atom("apply") + E.integer(3), bytes([80, 0, 0, 0, 9]) + rng.bytes(12)]))]))
    if k == 21:
        return "bad_version", bytes([rng.pick([130, 0, 132, 80])]) + good[1:]
    if k == 22:
        return "key_not_atom", E.term(E.emap([(rng.pick([E.binary(b"t"), E.integer(1), E.lst([])]), E.atom("call"))] + _pairs(good)[:7]))
    return "string_args", good.replace(E.lst(note), bytes([107, 0, 1, canary & 255]), 1)


def _pairs(body):
    """the (key bytes, value bytes) pairs of a well-formed frame's top map"""
    out, pos = [], 6
    for _ in range(struct.unpack(">I", body[2:6])[0]):
        _, kp = E.read(body, pos)
        _, vp = E.read(body, kp)
        out.append((body[pos:kp], body[kp:vp]))
        pos = vp
    return out


def trust_steps(rng, index, tls):
    """the steps of one TRUST case after the peer identity; returns (kind, steps, identity)"""
    canary = 1000 * (index + 1)
    good_req = f4(t_request("cast", "demo", "note", [E.integer(canary)]))
    k = rng.weighted([(52, "request"), (12, "first"), (10, "length"), (8, "identity"), (6, "token"), (6, "order"), (6, "slow")])
    ident = "good"
    if k == "request":
        kind, body = hostile_request(rng, canary)
        if rng.chance(1, 4):                         # on the token fast path: the driver puts the live token of its last probe first
            steps = [["send_live", hx(f4(body))]]
            kind = "request_token/" + kind
        else:
            steps = [["send", hx(f4(t_hello()) + f4(body))]]
            kind = "request/" + kind
    elif k == "slow":
        kind, body = hostile_request(rng, canary)
        steps = [["send_chunks", hx(f4(t_hello()) + f4(body)), rng.pick([1, 2, 5])]]
        kind = "slow/" + kind
    elif k == "first":
        j = rng.below(6)
        first = [E.mutate(rng, t_hello()), t_hello(rng.pick([0, 2, 255, 1 << 40])), E.term(E.any_term(rng, T_ATOMS)), t_request("cast", "demo", "note", [E.integer(canary)]),
                 E.term(E.emap([(E.atom("t"), E.atom(rng.pick(["token_issue", "result", "call", "ok"]))), (E.atom("ver"), E.integer(1))])), rng.bytes(rng.between(0, 30))][j]
        steps = [["send", hx(f4(first) + good_req)]]
        kind = "first/%d" % j
    elif k == "length":
        j = rng.below(6)
        body = t_request("cast", "demo", "note", [E.integer(canary)])
        s = [struct.pack(">I", rng.pick([4097, 65536, 1 << 24, 0x7FFFFFFF, 0x80000000, 0xFFFFFFFF])) + t_hello() + good_req,
             f4(t_hello()) + struct.pack(">I", rng.pick([4097, 1 << 20, 0xFFFFFFFF])) + body,
             f4(t_hello()) + struct.pack(">I", len(body) + rng.between(1, 40)) + body,
             f4(t_hello()) + struct.pack(">I", len(body) - rng.between(1, len(body))) + body,
             f4(t_hello()) + f4(body)[:rng.between(1, len(body) + 3)],
             bytes(4) + f4(t_hello()) + good_req][j]
        steps = [["send", hx(s)]]
        kind = "length/" + ["first_over_cap", "request_over_cap", "overstated", "understated", "partial", "zero_first"][j]
    elif k == "identity":
        j = rng.below(4)
        ident = ["unlisted", "none", "garbage", "short"][j]
        steps = [["send", hx(f4(t_hello()) + good_req)]]
        kind = "identity/" + ident
    elif k == "token":
        j = rng.below(4)
        tok = [rng.bytes(48), bytes(48), rng.bytes(rng.pick([0, 1, 47, 49, 300])), b""][j]
        first = t_token_present(tok) if j < 3 else E.term(E.emap([(E.atom("t"), E.atom("token_present")), (E.atom("token"), E.any_term(rng, T_ATOMS, 0)), (E.atom("ver"), E.integer(1))]))
        steps = [["send", hx(f4(first) + good_req)]]
        kind = "token/" + ["random", "zero", "wrong_length", "not_binary"][j]
    else:                                            # a request before the token step; a second request after the first
        if rng.chance(1, 2):
            steps = [["send", hx(good_req + f4(t_hello()))]]
            kind = "order/request_first"
        else:
            steps = [["send", hx(f4(t_hello()) + good_req + f4(t_request("cast", "demo", "note", [E.integer(canary + 1)])) + f4(t_hello()))]]
            kind = "order/second_request"
    return kind, steps, ident, canary


def case_trust(rng, index, tls):
    kind, steps, ident, canary = trust_steps(rng, index, tls)
    c = {"kind": kind, "steps": steps, "identity": ident, "canary": canary}
    if tls and rng.chance(1, 8):                     # raw bytes at the TLS listener, no TLS handshake at all
        j = rng.below(5)
        raw = [rng.bytes(rng.between(1, 200)), b"\x16\x03\x01" + struct.pack(">H", rng.pick([0, 5, 512, 16384, 65535])) + rng.bytes(rng.between(0, 300)),
               bytes([rng.pick([20, 21, 22, 23, 24, 255]), 3, rng.below(5)]) + struct.pack(">H", rng.below(70000) & 0xFFFF) + rng.bytes(rng.between(0, 64)),
               f4(t_hello()) + f4(t_request("cast", "demo", "note", [E.integer(canary)])), b"GET / HTTP/1.1\r\nHost: x\r\n\r\n"][j]
        c = {"kind": "tls_raw/%d" % j, "steps": [["send", hx(raw)]], "identity": "raw", "canary": canary}
    return c


# ---- surface: trust_client (a TRUST client dials the driver: hostile token_issue and result frames) ----
RID = b"rXXXXXX"                                     # where the driver writes the request id of the call it answers (r100000 ..)
VAL = bytes([98]) + b"VVVV"                          # where it writes the value the call expects, an INTEGER_EXT


def t_token_issue(tok):
    return E.term(E.emap([(E.atom("t"), E.atom("token_issue")), (E.atom("token"), E.binary(tok)), (E.atom("ver"), E.integer(1))]))


def t_result(rid=RID, value=VAL, ver=1, t="result", extra=()):
    return E.term(E.emap([(E.atom("req_id"), E.binary(rid)), (E.atom("t"), E.atom(t)), (E.atom("value"), value), (E.atom("ver"), E.integer(ver))] + list(extra)))


def good_reply(first_is_hello, token=bytes(range(48))):
    return (f4(t_token_issue(token)) if first_is_hello else b"") + f4(t_result())


def reply_model(stream, first_is_hello, rid, cap=FRAME_CAP):
    """may a correct client report {ok, Value} for this answer stream? ("no" is certain; "yes" means it is not excluded).
    Returns (may_ok, value or None when the value is not a plain integer)"""
    frames, pos = [], 0
    while pos + 4 <= len(stream):
        n = struct.unpack(">I", stream[pos:pos + 4])[0]
        if n > cap or pos + 4 + n > len(stream):
            break
        frames.append(stream[pos + 4:pos + 4 + n])
        pos += 4 + n
    maps = []
    for f in frames:
        try:
            v = E.read_term(f)
        except E.Bad:
            break
        if not (isinstance(v, tuple) and v[0] == "map") or any(not (isinstance(k, tuple) and k[0] == "atom") for k, _ in v[1]):
            break
        if E.has_other(v) or any(a.startswith(E.UNKNOWN_PREFIX) for a in E.atoms_of(v)) or len({k[1] for k, _ in v[1]}) != len(v[1]):
            break
        maps.append({k[1]: x for k, x in v[1]})
    if first_is_hello:
        if not maps or maps[0].get("t") != ("atom", "token_issue") or maps[0].get("ver") != 1 or not (isinstance(maps[0].get("token"), tuple) and maps[0]["token"][0] == "bin"):
            return (False, None)
        maps = maps[1:]
    if not maps:
        return (False, None)
    m = maps[0]
    if m.get("t") != ("atom", "result") or m.get("ver") != 1 or m.get("req_id") != ("bin", rid) or "value" not in m:
        return (False, None)
    v = m["value"]
    return (True, v if isinstance(v, int) and not isinstance(v, bool) else None)


def case_trust_client(rng, index):
    """the answer has two forms, one for a client that said hello and one for a client that presented a token"""
    k = rng.below(20)
    tok = bytes(range(48))
    res = t_result()

    def both(kind, hello_form, token_form=None, hold=False):
        return {"kind": kind, "reply_hello": hx(hello_form), "reply_token": hx(hello_form if token_form is None else token_form), "hold": hold, "steps": []}
    if k <= 2:
        return both("mutated_result", f4(t_token_issue(tok)) + f4(E.mutate(rng, res)), f4(E.mutate(rng, res)))
    if k == 3:
        return both("mutated_token_issue", f4(E.mutate(rng, t_token_issue(tok))) + f4(res))
    if k == 4:
        t = rng.bytes(rng.pick([0, 1, 47, 49, 64, 255, 256, 2000, 4000]))
        return both("token_size", f4(t_token_issue(t)) + f4(res))
    if k == 5:
        bad = E.term(E.emap([(E.atom("t"), E.atom("token_issue")), (E.atom("token"), E.any_term(rng, T_ATOMS, 2)), (E.atom("ver"), E.integer(1))]))
        return both("token_not_binary", f4(bad) + f4(res))
    if k == 6:
        return both("no_token_issue", f4(res), f4(t_token_issue(tok)) + f4(res))
    if k == 7:
        r = t_result(rid=rng.pick([b"r100000", b"r999999", b"", b"x", RID + b"0", rng.bytes(7), rng.bytes(300)]))
        return both("other_req_id", f4(t_token_issue(tok)) + f4(r), f4(r))
    if k == 8:
        r = t_result(ver=rng.pick([0, 2, 255, -1, 1 << 40]))
        return both("ver", f4(t_token_issue(tok)) + f4(r), f4(r))
    if k == 9:
        r = t_result(t=rng.pick(["hello", "call", "cast", "token_issue", "token_present", "ok", "error"]))
        return both("t", f4(t_token_issue(tok)) + f4(r), f4(r))
    if k == 10:
        r = E.term(E.emap([p for p in _pairs(res) if p[0] != E.atom(rng.pick(["req_id", "t", "value", "ver"]))]))
        return both("missing_key", f4(t_token_issue(tok)) + f4(r), f4(r))
    if k == 11:
        r = t_result(value=rng.pick([E.any_term(rng, T_ATOMS), E.nested(rng, rng.pick([30, 31, 32, 33, 34, 64, 199, 400]), E.integer(1)), E.binary(rng.bytes(rng.pick([0, 100, 3000, 4000]))), E.unknown_atom(rng), my_pid(), E.big(1 << 64)]))
        return both("value_term", f4(t_token_issue(tok)) + f4(r), f4(r))
    if k == 12:
        r = E.term(E.any_term(rng, T_ATOMS))
        return both("random_term", f4(t_token_issue(tok)) + f4(r), f4(r))
    if k == 13:
        j = rng.below(4)
        s = [struct.pack(">I", rng.pick([4097, 65536, 0x7FFFFFFF, 0xFFFFFFFF])) + res, struct.pack(">I", len(res) + rng.between(1, 30)) + res, f4(res)[:rng.between(1, len(res) + 3)], bytes(4) + f4(res)][j]
        return both("length_%d" % j, f4(t_token_issue(tok)) + s, s, hold=j in (1, 2) and rng.chance(1, 2))
    if k == 14:
        return both("silent", b"", hold=True)
    if k == 15:
        return both("close", b"")
    if k == 16:
        return both("garbage", rng.bytes(rng.between(1, 200)))
    if k == 17:
        r = t_result(extra=[(E.atom(rng.pick(["x1", "args", "token", E.UNKNOWN_PREFIX + "k"])), E.any_term(rng, T_ATOMS, 0)) for _ in range(rng.pick([1, 2, 12, 13, 30]))])
        return both("extra_keys", f4(t_token_issue(tok)) + f4(r), f4(r))
    if k == 18:
        return both("two_results", f4(t_token_issue(tok)) + f4(t_result(value=E.integer(7))) + f4(res), f4(t_result(value=E.integer(7))) + f4(res))
    return both("result_then_token", f4(res) + f4(t_token_issue(tok)))


# ---- surface: resolve (answers of the resolver edge through the one filter, bees_addr) ----
def resolve_answer(rng):
    """one resolver answer text, as the native edge would hand it over: `ok a.b.c.d[,...] n6` / `err reason`, well-formed or not"""
    def quad():
        k = rng.below(10)
        if k <= 4:
            return "%d.%d.%d.%d" % (rng.pick([127, 127, 10, 192, 0, 224, 240, 255, 1, 169]), rng.below(256), rng.below(256), rng.below(256))
        return rng.pick(["127.0.0.1", "0.0.0.0", "255.255.255.255", "224.0.0.1", "239.255.255.255", "240.0.0.1", "127.255.255.255", "128.0.0.1", "126.255.255.255",
                         "256.1.1.1", "1.2.3", "1.2.3.4.5", "01.2.3.4", "1..2.3", " 1.2.3.4", "1.2.3.4 ", "-1.2.3.4", "1.2.3.4a", "0x7f.0.0.1", "127.1", "::1", "", "999999999999999999999.1.1.1",
                         "127.0.0.01", "127.0.0.1.", ".127.0.0.1", "1,2", "127.0.0.+1"])
    k = rng.below(12)
    if k <= 5:
        return "ok " + ",".join(quad() for _ in range(rng.between(1, 5))) + " " + str(rng.pick([0, 0, 1, 7]))
    if k == 6:
        return "err " + rng.pick(["nxdomain", "no_address", "temporary", "bad_name", "failed", "timeout", "", "NXDOMAIN", "nxdomain ", "ok", "x" * 300])
    if k == 7:
        return rng.pick(["", "ok", "ok ", "ok  ", "err", "OK 127.0.0.1 0", "ok 127.0.0.1", "ok 127.0.0.1 ", "ok 127.0.0.1  0", "ok 127.0.0.1 0 ", "ok 127.0.0.1 -1", "ok 127.0.0.1 x", "ok ,127.0.0.1 0",
                         "ok 127.0.0.1, 0", "ok 127.0.0.1,,127.0.0.2 0", "ok 127.0.0.1 99999999999999999999"])
    if k == 8:
        return "ok " + ",".join(["127.0.0.%d" % rng.below(256)] * rng.pick([2, 3, 40])) + " 0"
    if k == 9:
        return "ok " + ",".join("127.0.%d.%d" % (i // 256, i % 256) for i in range(rng.pick([17, 64, 200]))) + " 0"
    if k == 10:
        s = "ok " + quad() + " 0"
        i = rng.below(len(s))
        return s[:i] + rng.pick([";", "%", "~", "#", "/", "ok ", ",", " "]) + s[i:]
    return "".join(rng.pick("ok er0123456789., ") for _ in range(rng.between(0, 40)))


def _quad_value(q):
    """the four numbers of a strict dotted quad or None (digits only, 1 to 3 per part, no leading zero except "0", each at most 255)"""
    parts = q.split(".")
    if len(parts) != 4:
        return None
    out = []
    for p in parts:
        if not (1 <= len(p) <= 3) or any(ch not in "0123456789" for ch in p) or (len(p) > 1 and p[0] == "0") or int(p) > 255:
            return None
        out.append(int(p))
    return out


def resolve_model(answer, loopback_only):
    """what the filter must conclude: ("ok", [usable addresses in order]) or ("err", reason) or ("maybe",) when the specification
    (S14 sections 3 and 5) does not settle the text. Only usable addresses that are strict quads outside the dropped ranges may come
    out; that is what the driver checks whatever the model says."""
    if not answer.startswith("ok "):
        return ("maybe",)
    parts = answer.split(" ")
    if len(parts) != 3 or not parts[2].isdigit():
        return ("maybe",)
    out = []
    for q in parts[1].split(","):
        v = _quad_value(q)
        if v is None:
            return ("maybe",)
        if v[0] == 0 or v[0] >= 224:
            continue
        if q not in out:
            out.append(q)
    if not out:
        return ("err", "no_usable_address")
    if loopback_only and any(not q.startswith("127.") for q in out):
        return ("err", "not_loopback")
    return ("ok", out)


def never_usable(q):
    """True when the text can never be a usable address, whatever else the filter decides"""
    v = _quad_value(q)
    return v is None or v[0] == 0 or v[0] >= 224


def case_resolve(rng, index):
    return {"kind": "answer", "answer": resolve_answer(rng), "loopback_only": rng.chance(1, 2), "steps": []}


# ---- the one entry ----
def case(seed, surface, index):
    rng = E.Rng("bees-fuzz", seed, surface, index)
    if surface == "beam_accept":
        c = case_beam_accept(rng, index)
    elif surface == "beam_dial":
        c = case_beam_dial(rng, index)
    elif surface == "epmd_register":
        c = case_epmd_register(rng, index)
    elif surface == "trust_plain":
        c = case_trust(rng, index, False)
    elif surface == "trust_tls":
        c = case_trust(rng, index, True)
    elif surface == "trust_client":
        c = case_trust_client(rng, index)
    elif surface == "resolve":
        c = case_resolve(rng, index)
    else:
        raise ValueError("no such surface (or not live): " + surface)
    c.update(surface=surface, index=index, seed=seed)
    return c


def case_bytes(c):
    """every byte the case sends, in order (what a reproducer file holds)"""
    out = b""
    for s in c.get("steps", []):
        if s[0] in ("raw", "post", "post_chunks", "send", "send_chunks", "send_live"):
            out += bytes.fromhex(s[1])
    if isinstance(c.get("epmd"), dict):
        out += bytes.fromhex(c["epmd"].get("reply", ""))
    if "answer" in c:
        out += c["answer"].encode()
    if "reply_hello" in c:
        out += bytes.fromhex(c["reply_hello"])
    return out


def case_id(c):
    """a short stable name for the generated case: the SHA-256 of its JSON form"""
    import json
    return hashlib.sha256(json.dumps(c, sort_keys=True).encode()).hexdigest()[:12]
