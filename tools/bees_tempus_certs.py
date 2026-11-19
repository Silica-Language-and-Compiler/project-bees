#!/usr/bin/env python3
"""TEST-ONLY TEMPUS identities for the TLS trials (T5): Ed25519 keys and certificates self-signed over them.

    bees_tempus_certs.py write   writes trials/t5_tempus_tls/certs/<name>.pem and <name>-key.pem
    bees_tempus_certs.py check   fails when those files are not what this tool writes now

A TEMPUS node's certificate is self-signed over its identity key (development-plan/tempus-design.md section 4, ruling
OQ-2). The keys come from the fixed seeds of tools/bees_tempus_fixtures.py (node 20..3f, other 40..5f) and from 80..9f
(sentinel) and a0..bf (bridge): keys that belong to nobody. Serial numbers and dates are fixed and Ed25519 signatures are
deterministic, so the files are the same on every run. Made with the `cryptography` package; nothing is fetched.
"""
import datetime
import os
import sys

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.x509.oid import NameOID

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "trials", "t5_tempus_tls", "certs")
# name -> first byte of its 32-byte seed. x1 to x4 (C2) are further peers for the clients' trials; their names sort after
# the first four, so the serial numbers (and with them the certificates) of the first four are what they were.
SEEDS = {"node": 32, "other": 64, "sentinel": 128, "bridge": 160, "x1": 176, "x2": 192, "x3": 208, "x4": 224}
NOT_BEFORE = datetime.datetime(2026, 1, 1)
NOT_AFTER = datetime.datetime(2046, 1, 1)


def key_of(name):
    first = SEEDS[name]
    return Ed25519PrivateKey.from_private_bytes(bytes(range(first, first + 32)))


def public_bytes(name):
    return key_of(name).public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def files():
    """file name -> bytes"""
    out = {}
    for serial, name in enumerate(sorted(SEEDS), start=1):
        key = key_of(name)
        who = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "bees tempus test " + name)])
        cert = (x509.CertificateBuilder().subject_name(who).issuer_name(who).public_key(key.public_key())
                .serial_number(serial).not_valid_before(NOT_BEFORE).not_valid_after(NOT_AFTER).sign(key, None))
        out[name + ".pem"] = cert.public_bytes(serialization.Encoding.PEM)
        out[name + "-key.pem"] = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                   serialization.NoEncryption())
    return out


def main(argv):
    if len(argv) == 2 and argv[1] == "write":
        os.makedirs(OUT, exist_ok=True)
        for name, data in files().items():
            with open(os.path.join(OUT, name), "wb") as f:
                f.write(data)
        return 0
    if len(argv) == 2 and argv[1] == "check":
        for name, data in files().items():
            path = os.path.join(OUT, name)
            if not os.path.exists(path) or open(path, "rb").read() != data:
                print("%s is not what the tool writes: run `write`" % path)
                return 1
        print("certificates are current")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
