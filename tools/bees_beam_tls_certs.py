#!/usr/bin/env python3
"""TEST-ONLY certificates for the BEAM-mode TLS trials (N2T: trials/n2t_pair, trials/n2t_live). Never real keys.

    bees_beam_tls_certs.py write [DIR]   writes <name>.pem and <name>-key.pem (default DIR: trials/n2t_pair/certs)
    bees_beam_tls_certs.py check [DIR]   fails when those files are not what this tool writes now

Everything is made from fixed inputs: each Ed25519 key is the 32 bytes first..first+31 of its seed (keys that belong to nobody),
the RSA keys are the fixed test keys of tools/bees_beam_tls_rsa_keys.py, serial numbers and dates are fixed, and the signatures
are deterministic (Ed25519; RSA-PSS with an empty salt for the one certificate an RSA authority signs), so the files are the same
on every run and on every machine. Made with the `cryptography` package; nothing is fetched.

    ca          the trial's certificate authority (self-signed, CA:TRUE): every node's cacertfile
    rogue_ca    another authority, which no node trusts
    h a b l d   BEES nodes, signed by ca, subjectAltName DNS:localhost and IP:127.0.0.1 (a dialing Erlang or BEES node checks
                the host part of the node name it dials, localhost, against the certificate)
    stock       the stock Erlang node of trials/n2t_live, signed by ca, the same names
    rogue       signed by rogue_ca (the "wrong CA" refusals), the same names
    expired     signed by ca, valid 2020-01-01 to 2021-01-01 only
    otherhost   signed by ca, subjectAltName DNS:otherhost only (the host name refusal of a dialing node)
    rsa         an RSA 2048 key, signed by ca (N2T Q4: RSA certificates are accepted in BEAM mode)
    stock_rsa   an RSA 2048 key for the stock Erlang node, signed by ca
    rsa1024     an RSA 1024 key, signed by ca: refused (below 2048 bits)
    rsa_ca      an RSA 2048 authority; rsapss, an RSA 2048 key, is signed by it with RSA-PSS (SHA-256)
    ca_both     (certificate only) ca followed by rsa_ca: a cacertfile that trusts both authorities
"""
import datetime
import ipaddress
import os
import sys

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.x509.oid import NameOID

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from bees_beam_tls_rsa_keys import KEYS as RSA_KEYS  # noqa: E402
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "trials", "n2t_pair", "certs")
NOT_BEFORE = datetime.datetime(2026, 1, 1)
NOT_AFTER = datetime.datetime(2046, 1, 1)
OLD_BEFORE = datetime.datetime(2020, 1, 1)
OLD_AFTER = datetime.datetime(2021, 1, 1)
LOCAL = [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
# name -> (first byte of its 32-byte seed, issuer, serial, subjectAltName, expired)
CERTS = {
    "ca": (0x10, "ca", 1, None, False),
    "rogue_ca": (0x30, "rogue_ca", 2, None, False),
    "h": (0x50, "ca", 10, LOCAL, False),
    "a": (0x51, "ca", 11, LOCAL, False),
    "b": (0x52, "ca", 12, LOCAL, False),
    "l": (0x53, "ca", 13, LOCAL, False),
    "d": (0x54, "ca", 14, LOCAL, False),
    "stock": (0x55, "ca", 15, LOCAL, False),
    "rogue": (0x56, "rogue_ca", 16, LOCAL, False),
    "expired": (0x57, "ca", 17, LOCAL, True),
    "otherhost": (0x58, "ca", 18, [x509.DNSName("otherhost")], False),
    # RSA keys (first byte unused: the key is RSA_KEYS[name])
    "rsa": (0, "ca", 19, LOCAL, False),
    "stock_rsa": (0, "ca", 20, LOCAL, False),
    "rsa1024": (0, "ca", 21, LOCAL, False),
    "rsa_ca": (0, "rsa_ca", 3, None, False),
    "rsapss": (0, "rsa_ca", 22, LOCAL, False),
}


def key_of(name):
    if name in RSA_KEYS:
        return serialization.load_pem_private_key(RSA_KEYS[name].encode(), None)
    first = CERTS[name][0]
    return Ed25519PrivateKey.from_private_bytes(bytes((first + i) % 256 for i in range(32)))


def subject(name):
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "bees-n2t-test-" + name)])


def cert_of(name):
    _first, issuer, serial, san, old = CERTS[name]
    is_ca = san is None
    pub = key_of(name).public_key()
    ipub = key_of(issuer).public_key()
    b = (x509.CertificateBuilder().subject_name(subject(name)).issuer_name(subject(issuer)).public_key(pub)
         .serial_number(serial).not_valid_before(OLD_BEFORE if old else NOT_BEFORE).not_valid_after(OLD_AFTER if old else NOT_AFTER)
         .add_extension(x509.BasicConstraints(ca=is_ca, path_length=None), critical=True)
         .add_extension(x509.SubjectKeyIdentifier.from_public_key(pub), critical=False)
         .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ipub), critical=False))
    if is_ca:
        b = b.add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False, key_encipherment=False,
                                          data_encipherment=False, key_agreement=False, key_cert_sign=True, crl_sign=True,
                                          encipher_only=False, decipher_only=False), critical=True)
    else:
        b = b.add_extension(x509.SubjectAlternativeName(san), critical=False)
    if issuer in RSA_KEYS:
        # RSA-PSS with SHA-256 and an EMPTY salt: deterministic, so the file is the same on every run
        return b.sign(key_of(issuer), hashes.SHA256(), rsa_padding=padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=0))
    return b.sign(key_of(issuer), None)


def files():
    """file name -> bytes"""
    out = {}
    for name in CERTS:
        out[name + ".pem"] = cert_of(name).public_bytes(serialization.Encoding.PEM)
        out[name + "-key.pem"] = key_of(name).private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                             serialization.NoEncryption())
    out["ca_both.pem"] = out["ca.pem"] + out["rsa_ca.pem"]
    return out


def main(argv):
    if len(argv) < 2 or argv[1] not in ("write", "check"):
        print(__doc__, file=sys.stderr)
        return 2
    out = argv[2] if len(argv) > 2 else OUT
    want = files()
    if argv[1] == "write":
        os.makedirs(out, exist_ok=True)
        for name, data in want.items():
            path = os.path.join(out, name)
            if name.endswith("-key.pem") and os.path.exists(path):
                os.chmod(path, 0o600)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600 if name.endswith("-key.pem") else 0o644)
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            if name.endswith("-key.pem"):
                os.chmod(path, 0o600)
        print(f"bees_beam_tls_certs: wrote {len(want)} files to {out}")
        return 0
    bad = []
    for name, data in want.items():
        path = os.path.join(out, name)
        try:
            with open(path, "rb") as fh:
                if fh.read() != data:
                    bad.append(name + " differs")
        except OSError:
            bad.append(name + " missing")
    if bad:
        print("bees_beam_tls_certs: " + ", ".join(bad), file=sys.stderr)
        return 1
    print(f"bees_beam_tls_certs: ok, {len(want)} files")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
