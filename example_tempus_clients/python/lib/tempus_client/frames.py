"""EXAMPLE ONLY, not for production. See ../../README.md.

The frames of tempus/1 (development-plan/tempus-design.md sections 4, 5 and 8): descriptors, the structure and the
checks of a token, every frame body a peer writes, and read_body, which reads a body and checks every bound.

The reader also knows the three frames of the test unit (tick, clock, done), because the trials' listeners read them;
the functions that WRITE them are in testing.py, with everything else that is for the trials only.
"""
import hashlib
import struct

from .codec import FRAME_MAX, Atom, Refused, etf_decode, etf_encode

KINDS = ("advert", "pop_challenge", "pop_response", "key_rotated", "shuffle", "shuffle_reply", "sample", "sample_reply",
         "tick", "clock", "done")
TYPES = ("tempus_edge", "tempus_bridge", "tempus_sentinel")
AGE_MAX = 65535
ENTRIES_MAX = 64          # the literal ceiling of entries in one frame
CLOCK_MAX = 2 ** 53
NO_TIME = -1             # a clock frame's ms or later: the clock could not be read
CLOCK_WAIT_MAX = 60000


# ---------------------------------------------------------------- identities, descriptors, tokens
def peer_id(pub):
    """The identity of a public key: its SHA-512 (design section 4)."""
    return hashlib.sha512(pub).digest()


def descriptor(pid, pub, addr, token):
    return {Atom("id"): bytes(pid), Atom("pub"): bytes(pub), Atom("addr"): addr.encode() if isinstance(addr, str) else bytes(addr),
            Atom("token"): bytes(token)}


def _check_keys(m, keys, what):
    if not isinstance(m, dict):
        raise Refused("%s is not a map" % what)
    have = set(m)
    want = {Atom(k) for k in keys}
    if have - want:
        raise Refused("unknown_field")
    if want - have:
        raise Refused("missing_field")


def _bin(m, key, lo, hi, text):
    v = m[Atom(key)]
    if not isinstance(v, bytes) or not lo <= len(v) <= hi:
        raise Refused(text)
    return v


def check_descriptor(d):
    _check_keys(d, ("id", "pub", "addr", "token"), "descriptor")
    _bin(d, "id", 64, 64, "id is not 64 bytes")
    _bin(d, "pub", 32, 32, "pub is not 32 bytes")
    _bin(d, "addr", 3, 261, "addr is not 3 to 261 bytes")
    _bin(d, "token", 65, 1024, "token is not 65 to 1024 bytes")
    return d


def read_token(token):
    """The structure and bounds of a token: (fields, payload, signature). The signature is NOT verified here."""
    if not 65 <= len(token) <= 1024:
        raise Refused("token is not 65 to 1024 bytes")
    sig, payload = token[:64], token[64:]
    m = etf_decode(payload, depth_max=2)
    if not isinstance(m, dict) or len(m) != 5:
        raise Refused("the token is not a map of five keys")
    _check_keys(m, ("kid", "sub", "typ", "nbf", "exp"), "token")
    kid = _bin(m, "kid", 1, 64, "kid is not 1 to 64 bytes")
    sub = _bin(m, "sub", 32, 32, "sub is not 32 bytes")
    typ, nbf, exp = m[Atom("typ")], m[Atom("nbf")], m[Atom("exp")]
    if not isinstance(typ, Atom) or typ not in TYPES:
        raise Refused("typ is not a peer type")
    if not isinstance(nbf, int) or not isinstance(exp, int) or isinstance(nbf, Atom) or nbf < 0 or exp < 0:
        raise Refused("nbf or exp is not a time")
    if exp <= nbf:
        raise Refused("exp is not after nbf")
    return {"kid": kid, "sub": sub, "typ": str(typ), "nbf": nbf, "exp": exp}, payload, sig


def verify_token(token, producer_public_key, kid, now, skew=0):
    """Structure, the current kid, the producer's signature over the payload as received, and the time window."""
    fields, payload, sig = read_token(token)
    if fields["kid"] != (kid.encode() if isinstance(kid, str) else kid):
        raise Refused("key_rotated")
    try:
        producer_public_key.verify(sig, payload)
    except Exception:
        raise Refused("the signature is not the producer's")
    if not fields["nbf"] - skew <= now < fields["exp"] + skew:
        raise Refused("the token is not valid at this time")
    return fields


# ---------------------------------------------------------------- frame bodies
def _typ(store):
    if store not in TYPES:
        raise ValueError("store is one of %s" % (TYPES,))
    return Atom(store)


def advert(d):
    return etf_encode({Atom("t"): Atom("advert"), Atom("ver"): 1, Atom("d"): d})


def challenge(nonce):
    return etf_encode({Atom("t"): Atom("pop_challenge"), Atom("nonce"): bytes(nonce)})


def response(sig):
    return etf_encode({Atom("t"): Atom("pop_response"), Atom("sig"): bytes(sig)})


def key_rotated(kid):
    return etf_encode({Atom("t"): Atom("key_rotated"), Atom("kid"): kid.encode() if isinstance(kid, str) else kid})


def _entries(kind, store, entries):
    return etf_encode({Atom("t"): Atom(kind), Atom("store"): _typ(store),
                       Atom("entries"): [{Atom("age"): age, Atom("d"): d} for (age, d) in entries]})


def shuffle(store, entries):
    """entries: a list of (age, descriptor)."""
    return _entries("shuffle", store, entries)


def shuffle_reply(store, entries):
    return _entries("shuffle_reply", store, entries)


def sample_reply(store, entries):
    return _entries("sample_reply", store, entries)


def sample(store, n):
    return etf_encode({Atom("t"): Atom("sample"), Atom("store"): _typ(store), Atom("n"): n})


def call_frame(req_id, m, f, args, kind="call", arity=None):
    """C3: TRUST's request frame as a bridge reads it (design 17.4; the form of src/trust/bees_trust_frame.silica
    enc_request, written here independently): #{t => call | cast, ver => 1, req_id => <<bytes>>, m => M, f => F,
    a => length(args), args => [integers], opts => #{}}. args is a list of integers (what the trial's functions take)."""
    rid = req_id.encode() if isinstance(req_id, str) else bytes(req_id)
    return etf_encode({Atom("t"): Atom(kind), Atom("ver"): 1, Atom("req_id"): rid, Atom("m"): Atom(m), Atom("f"): Atom(f),
                       Atom("a"): len(args) if arity is None else arity, Atom("args"): list(args), Atom("opts"): {}})


def result_value(out):
    """the value of a TRUST result an Outcome carries (read_any's fields), or None when the reply is no result"""
    return out.fields.get("value") if out.kind == "result" else None


def read_body(body, shuffle_length):
    """A body as (kind, fields), every bound of design section 8 checked; Refused(reason) otherwise."""
    m = etf_decode(body)
    if not isinstance(m, dict):
        raise Refused("bad_tag")
    t = m.get(Atom("t"))
    if not isinstance(t, Atom) or t not in KINDS:
        raise Refused("unknown kind")
    kind = str(t)
    if kind == "advert":
        _check_keys(m, ("t", "ver", "d"), kind)
        if m[Atom("ver")] != 1:
            raise Refused("ver is not 1")
        return kind, {"d": check_descriptor(m[Atom("d")])}
    if kind == "pop_challenge":
        _check_keys(m, ("t", "nonce"), kind)
        return kind, {"nonce": _bin(m, "nonce", 32, 32, "nonce is not 32 bytes")}
    if kind == "pop_response":
        _check_keys(m, ("t", "sig"), kind)
        return kind, {"sig": _bin(m, "sig", 64, 64, "sig is not 64 bytes")}
    if kind == "key_rotated":
        _check_keys(m, ("t", "kid"), kind)
        return kind, {"kid": _bin(m, "kid", 1, 64, "kid is not 1 to 64 bytes")}
    if kind in ("shuffle", "shuffle_reply", "sample_reply"):
        _check_keys(m, ("t", "store", "entries"), kind)
        store, entries = m[Atom("store")], m[Atom("entries")]
        if not isinstance(store, Atom) or store not in TYPES:
            raise Refused("store is not a peer type")
        if not isinstance(entries, list):
            raise Refused("entries is not a list")
        if len(entries) > ENTRIES_MAX or len(entries) > shuffle_length:
            raise Refused("more entries than the shuffle length")
        out = []
        for e in entries:
            _check_keys(e, ("age", "d"), "entry")
            age = e[Atom("age")]
            if not isinstance(age, int) or isinstance(age, Atom) or not 0 <= age <= AGE_MAX:
                raise Refused("age is not 0 to 65535")
            out.append((age, check_descriptor(e[Atom("d")])))
        return kind, {"store": str(store), "entries": out}
    if kind == "sample":
        _check_keys(m, ("t", "store", "n"), kind)
        store, n = m[Atom("store")], m[Atom("n")]
        if not isinstance(store, Atom) or store not in TYPES:
            raise Refused("store is not a peer type")
        if not isinstance(n, int) or not 1 <= n <= shuffle_length:
            raise Refused("n is not 1 to the shuffle length")
        return kind, {"store": str(store), "n": n}
    if kind == "tick":
        _check_keys(m, ("t", "store"), kind)
        store = m[Atom("store")]
        if not isinstance(store, Atom) or store not in TYPES:
            raise Refused("store is not a peer type")
        return kind, {"store": str(store)}
    if kind == "clock":
        two = Atom("wait") in m
        _check_keys(m, ("t", "ms", "wait", "later") if two else ("t", "ms"), kind)
        ms = m[Atom("ms")]
        if not isinstance(ms, int) or not NO_TIME <= ms <= CLOCK_MAX:
            raise Refused("ms is not -1 (no time) or 0 to 2^53")
        if not two:
            return kind, {"ms": ms}
        wait, later = m[Atom("wait")], m[Atom("later")]
        if not isinstance(later, int) or not NO_TIME <= later <= CLOCK_MAX:
            raise Refused("later is not -1 (no time) or 0 to 2^53")
        if not isinstance(wait, int) or not 1 <= wait <= CLOCK_WAIT_MAX:
            raise Refused("wait is not 1 to 60000")
        return kind, {"ms": ms, "wait": wait, "later": later}
    _check_keys(m, ("t",), kind)
    return kind, {}


def frame(body):
    """The body with its 4-byte big-endian length, as it travels."""
    if len(body) > FRAME_MAX:
        raise ValueError("body above the frame ceiling")
    return struct.pack(">I", len(body)) + body


