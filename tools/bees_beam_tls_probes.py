#!/usr/bin/env python3
"""N2T (TEST ONLY): points the programmer-installed OpenSSL's own client, `openssl s_client`, at a BEES BEAM-mode node that
listens inside TLS, once per case; each case shows one rule of the BEAM TLS profile (development-plan/spikes/N2T-beam-tls.md):
what the listener accepts at the TLS layer and what it refuses. Nothing is downloaded; 127.0.0.1 only. The mechanics are
tools/run_tls_refusals.py's (the TRUST driver), with this file's cases: the output is `case N: LABEL` followed by the lines the
node printed during the case, so the golden holds the node's audit lines case by case. A probe that is accepted at the TLS
layer sends no distribution handshake and closes, so the node logs the link going down.

    bees_beam_tls_probes.py NODE_EXE OUT READY CERTDIR HOST:PORT [--openssl PATH] [--quiet S]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run_tls_refusals as R  # noqa: E402

OK = ["-tls1_3", "-cert", "a.pem", "-key", "a-key.pem"]
# label, the s_client arguments after -connect (certificate names are files in CERTDIR)
CASES = [
    ("accepted: an Ed25519 certificate of the trial CA, TLS 1.3, the hybrid group", OK + ["-groups", "X25519MLKEM768"]),
    ("accepted: classical X25519 only (what a stock OTP 28 node offers)", OK + ["-groups", "X25519"]),
    ("accepted: an ALPN protocol is offered and none is selected (the distribution uses none)", OK + ["-alpn", "trust/1"]),
    ("accepted: an RSA 2048 certificate signed by the trial CA (N2T Q4)", ["-tls1_3", "-cert", "rsa.pem", "-key", "rsa-key.pem"]),
    ("accepted: an RSA 2048 certificate signed with RSA-PSS by an RSA authority the node trusts", ["-tls1_3", "-cert", "rsapss.pem", "-key", "rsapss-key.pem"]),
    ("refused: an RSA 1024 certificate (below 2048 bits)", ["-tls1_3", "-cipher", "DEFAULT@SECLEVEL=0", "-cert", "rsa1024.pem", "-key", "rsa1024-key.pem"]),
    ("refused: no client certificate", ["-tls1_3"]),
    ("refused: a certificate of another CA", ["-tls1_3", "-cert", "rogue.pem", "-key", "rogue-key.pem"]),
    ("refused: an expired certificate", ["-tls1_3", "-cert", "expired.pem", "-key", "expired-key.pem"]),
    ("refused: TLS 1.2 only (the default of a stock OTP 28 node without {versions, ['tlsv1.3']})", ["-tls1_2", "-cert", "a.pem", "-key", "a-key.pem"]),
    ("refused: a key exchange group outside the profile (secp256r1 only)", OK + ["-groups", "secp256r1"]),
]

if __name__ == "__main__":
    R.CASES = CASES
    sys.exit(R.main())
