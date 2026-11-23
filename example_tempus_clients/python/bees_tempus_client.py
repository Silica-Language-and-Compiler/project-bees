#!/usr/bin/env python3
"""EXAMPLE ONLY, not for production. See README.md beside this file.

The one module name the TRIALS import for the Python TEMPUS test support: `import bees_tempus_client as c`
(tools/bees_tempus_trial.py, bees_tempus_fixtures.py, bees_tempus_ids.py, test_bees_tempus_admission.py,
bees_tempus_swift_trial.py, the walks of trials c6, c8 and c9, and test_bees_tempus_client.py beside this file). It
holds no TEMPUS code of its own. An application never imports it.

There are two bodies of Python TEMPUS code in this directory, written on two lines of work and kept side by side
until the owner decides between them (README.md says what each can do). Each has its own test support, and this
module is one or the other of them under the old name:

  bees_tempus_testing     (the default) testing/bees_tempus_testing.py, built on the extension's modules
                          lib/bees_tempus_codec.py, bees_tempus_admission.py, bees_tempus_peer.py (the code the node
                          lib/bees_tempus_node.py is built on). Every name of that module is passed on, and beside
                          them the names of the library package lib/tempus_client that the other choice has and this
                          one has not (Peer, PeerSettings, Store, StoreSettings, peer8, secure_draws,
                          certificate_fingerprint, _Reader, _enc), so that an importer written for either line finds
                          every name it used.
  tempus_client.testing   lib/tempus_client (codec, frames, connection, gossip) with lib/tempus_client/testing.py:
                          chosen by setting the environment variable BEES_TEMPUS_TEST_SUPPORT=tempus_client.testing.
                          The tests of test_bees_tempus_client.py pass with either; the Makefile beside this file
                          runs them with both.

Both have the same command line (it signs tokens with the TEST producer seed and sends the test unit's frames); the
driver application's command line is driver/tempus_peer.py.

    bees_tempus_client.py read-hex HEX [SHUFFLE_LENGTH]
    bees_tempus_client.py dial HOST:PORT --seed HEX --addr HOST:PORT --producer-pub HEX --kid KID --now SECONDS
                               (--token HEX | --test-token TYP:NBF:EXP) [--skew S] [--timeout S] [--nonce HEX]
                               [--shuffle-length N] REQUEST
        REQUEST: sample STORE N | tick STORE | clock MS | shuffle STORE | raw HEX
        (`shuffle STORE` sends this client's own entry at age 0; `raw` is any body, for example TRUST's call or cast.)
        --test-token signs with the TEST producer seed 00..1f. Prints the outcome as one line. TEST ONLY.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
for _dir in ("testing", "lib"):
    if os.path.join(_HERE, _dir) not in sys.path:
        sys.path.insert(0, os.path.join(_HERE, _dir))

TEST_SUPPORT = os.environ.get("BEES_TEMPUS_TEST_SUPPORT", "bees_tempus_testing")

if TEST_SUPPORT == "bees_tempus_testing":
    import bees_tempus_testing as _testing
    import tempus_client as _library
    from tempus_client.codec import _Reader, _enc  # noqa: F401

    globals().update({_k: getattr(_library, _k) for _k in ("Peer", "PeerSettings", "Store", "StoreSettings", "peer8",
                                                           "secure_draws", "certificate_fingerprint")})
    globals().update({_k: _v for _k, _v in vars(_testing).items() if not _k.startswith("__")})

    def main(argv):
        code = _testing.main(argv)
        if code == 2:
            print(__doc__)
        return code

elif TEST_SUPPORT == "tempus_client.testing":
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

else:
    raise ImportError("BEES_TEMPUS_TEST_SUPPORT is %r: it must be bees_tempus_testing or tempus_client.testing" % TEST_SUPPORT)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
