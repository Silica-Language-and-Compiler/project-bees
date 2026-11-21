#!/usr/bin/env python3
"""EXAMPLE ONLY, not for production. See README.md beside this file.

The Python example TEMPUS client as the TRIALS use it: one module name, `bees_tempus_client`, that holds the library
(lib/tempus_client: codec, frames, connection, gossip) and, beside it, everything that is for the trials only
(lib/tempus_client/testing.py: the frames of the test unit, tokens made with the test producer's fixed seed, identities
from fixed seeds, deliberate misbehaviour). The tools of the trials import this module (`import bees_tempus_client as
c`) and its tests are test_bees_tempus_client.py.

A program that is a TEMPUS client does not import this file. It imports the library, `tempus_client`, from lib/, as
the driver application driver/tempus_peer.py does.

The command line below is the trials' own (it signs tokens with the TEST producer seed and sends the test unit's
frames); the driver application's command line is driver/tempus_peer.py.

    bees_tempus_client.py read-hex HEX [SHUFFLE_LENGTH]
    bees_tempus_client.py dial HOST:PORT --seed HEX --addr HOST:PORT --producer-pub HEX --kid KID --now SECONDS
                               (--token HEX | --test-token TYP:NBF:EXP) [--skew S] [--timeout S] [--nonce HEX]
                               [--shuffle-length N] REQUEST
        REQUEST: sample STORE N | tick STORE | clock MS | shuffle STORE | raw HEX
        (`shuffle STORE` sends this client's own entry at age 0; `raw` is any body, for example TRUST's call or cast.)
        --test-token signs with the TEST producer seed 00..1f. Prints the outcome as one line.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
from tempus_client import *  # noqa: E402,F401,F403  the library
from tempus_client.codec import _Reader, _enc  # noqa: E402,F401
from tempus_client.frames import CLOCK_MAX, CLOCK_WAIT_MAX, NO_TIME, _bin, _check_keys, _entries, _typ  # noqa: E402,F401
from tempus_client.connection import (CERT_NOT_AFTER, CERT_NOT_BEFORE, LINGER, ON_PURPOSE, Misbehaviour, _addr, _admit,  # noqa: E402,F401
                                      _Conn, _context, _ed25519, _emit, _end, _key_pem, _raw_public, _read, _show, _ssl_reason,
                                      _tls_checks, _write_pem, raw_frame)
from tempus_client.testing import *  # noqa: E402,F401,F403  TEST ONLY
from tempus_client.testing import _stage  # noqa: E402,F401


# ---------------------------------------------------------------- the command line
def _dial_command(argv):
    import argparse
    ap = argparse.ArgumentParser(prog="bees_tempus_client.py dial")
    ap.add_argument("peer", help="HOST:PORT of the node")
    ap.add_argument("--seed", required=True, help="this client's Ed25519 seed, 64 hex digits (TEST ONLY keys)")
    ap.add_argument("--addr", required=True, help="the listen address this client advertises, HOST:PORT")
    ap.add_argument("--producer-pub", required=True, help="the current producer key, 64 hex digits")
    ap.add_argument("--kid", required=True)
    ap.add_argument("--now", required=True, type=int, help="the clock for token checks, whole seconds")
    ap.add_argument("--skew", type=int, default=0)
    ap.add_argument("--token", help="this client's token, hex")
    ap.add_argument("--test-token", help="TYP:NBF:EXP, signed with the TEST producer seed 00..1f under --kid")
    ap.add_argument("--timeout", type=float, default=5.0)
    ap.add_argument("--nonce", help="the challenge nonce, 64 hex digits (default: the system's random source)")
    ap.add_argument("--shuffle-length", type=int, default=ENTRIES_MAX)
    ap.add_argument("request", nargs="+", help="sample STORE N | tick STORE | clock MS | shuffle STORE | raw HEX")
    o = ap.parse_args(argv)
    seed = bytes.fromhex(o.seed)
    if (o.token is None) == (o.test_token is None):
        ap.error("give exactly one of --token and --test-token")
    if o.token is not None:
        token = bytes.fromhex(o.token)
    else:
        typ, nbf, exp = o.test_token.split(":")
        pub = _raw_public(_ed25519().Ed25519PrivateKey.from_private_bytes(seed))
        token = make_token(fixture_key(0), o.kid, pub, typ, int(nbf), int(exp))
    me = Identity(seed, token, o.addr)
    r = o.request
    if r[0] == "sample" and len(r) == 3:
        body = sample(r[1], int(r[2]))
    elif r[0] == "tick" and len(r) == 2:
        body = tick(r[1])
    elif r[0] == "clock" and len(r) == 2:
        body = clock(int(r[1]))
    elif r[0] == "shuffle" and len(r) == 2:
        body = shuffle(r[1], [me.entry(0)])
    elif r[0] == "raw" and len(r) == 2:
        body = bytes.fromhex(r[1])
    else:
        ap.error("the request is: sample STORE N | tick STORE | clock MS | shuffle STORE | raw HEX")
    verifier = Verifier(bytes.fromhex(o.producer_pub), o.kid, o.now, o.skew)
    out = dial(o.peer, me, verifier, body, timeout=o.timeout, nonce=bytes.fromhex(o.nonce) if o.nonce else None,
               shuffle_length=o.shuffle_length)
    print(out.line())
    return 0


def main(argv):
    if len(argv) >= 2 and argv[1] == "dial":
        return _dial_command(argv[2:])
    if len(argv) >= 3 and argv[1] == "read-hex":
        try:
            kind, fields = read_body(bytes.fromhex(argv[2]), int(argv[3]) if len(argv) > 3 else ENTRIES_MAX)
            print(kind, {k: (v if not isinstance(v, bytes) else v.hex()) for k, v in fields.items()})
        except Refused as why:
            print("refused:", why)
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))

