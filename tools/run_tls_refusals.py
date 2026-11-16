#!/usr/bin/env python3
"""N4.1 (TEST ONLY): runs a TRUST server over mutual TLS 1.3 and points the programmer-installed OpenSSL's own client,
`openssl s_client`, at it once per case, each case breaking one rule of the TRUST profile (inter-nodal-modes 3.2) or of the
whitelist (3.3). Nothing is downloaded; 127.0.0.1 only. The server runs under a pty (tools/run_trust_pair.py's Proc); after each
case the driver waits until the server has been quiet for QUIET seconds and writes `case N: LABEL` followed by the lines the
server printed during the case, so the golden holds the server's audit lines case by case. The client's own output is not
compared (OpenSSL's wording is not BEES's); a case only has to end within its time limit.

    run_tls_refusals.py SERVER_EXE OUT READY CERTDIR HOST:PORT [--openssl PATH] [--quiet S]
"""
import argparse
import os
import select
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_trust_pair import Proc  # noqa: E402

# label, the s_client arguments after -connect (certificate names are files in CERTDIR)
CASES = [
    ("no client certificate", ["-tls1_3", "-alpn", "trust/1", "-groups", "X25519MLKEM768"]),
    ("TLS 1.2 only", ["-tls1_2", "-alpn", "trust/1", "-cert", "b.pem", "-key", "b-key.pem"]),
    ("classical key exchange only (X25519), b.pem not marked classical-allowed (D44)", ["-tls1_3", "-alpn", "trust/1", "-groups", "X25519", "-cert", "b.pem", "-key", "b-key.pem"]),
    ("ALPN h2 instead of trust/1", ["-tls1_3", "-alpn", "h2", "-cert", "b.pem", "-key", "b-key.pem"]),
    ("no ALPN", ["-tls1_3", "-cert", "b.pem", "-key", "b-key.pem"]),
    ("a certificate from another CA (r.pem): no cacertfile (D43), so the whitelist refuses it", ["-tls1_3", "-alpn", "trust/1", "-cert", "r.pem", "-key", "r-key.pem"]),
    ("an expired certificate (x.pem): not checked without a cacertfile (D43), the whitelist refuses it", ["-tls1_3", "-alpn", "trust/1", "-cert", "x.pem", "-key", "x-key.pem"]),
    ("an RSA certificate (z.pem; the profile signs with Ed25519 or ECDSA P-256)", ["-tls1_3", "-alpn", "trust/1", "-cert", "z.pem", "-key", "z-key.pem"]),
    ("a certificate in no whitelist entry, so unpinned (u.pem)", ["-tls1_3", "-alpn", "trust/1", "-cert", "u.pem", "-key", "u-key.pem"]),
    ("a whitelisted ECDSA P-256 certificate (p.pem) that sends no TRUST frame", ["-tls1_3", "-alpn", "trust/1", "-cert", "p.pem", "-key", "p-key.pem"]),
    ("classical key exchange only (X25519), p.pem marked classical-allowed (D44), sends no TRUST frame", ["-tls1_3", "-alpn", "trust/1", "-groups", "X25519", "-cert", "p.pem", "-key", "p-key.pem"]),
    ("classical key exchange only (X25519), u.pem in no whitelist entry (D44)", ["-tls1_3", "-alpn", "trust/1", "-groups", "X25519", "-cert", "u.pem", "-key", "u-key.pem"]),
    ("hybrid offered first, classical second, b.pem not marked: the hybrid is chosen and the peer is admitted (D44)", ["-tls1_3", "-alpn", "trust/1", "-groups", "X25519MLKEM768:X25519", "-cert", "b.pem", "-key", "b-key.pem"]),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("server")
    ap.add_argument("out")
    ap.add_argument("ready")
    ap.add_argument("certdir")
    ap.add_argument("addr")
    ap.add_argument("--openssl", default="openssl")
    ap.add_argument("--quiet", type=float, default=0.8)
    ap.add_argument("--cap", type=float, default=120.0)
    o = ap.parse_args()
    t0 = time.monotonic()
    s = Proc(o.server, o.out, False)

    def pump_until(cond, limit):
        end = time.monotonic() + limit
        while time.monotonic() < end and not s.closed:
            r, _, _ = select.select([s.master], [], [], 0.05)
            if s.master in r:
                s.pump()
            if cond():
                return True
        return cond()

    if not pump_until(lambda: o.ready in s.text(), 30):
        s.kill()
        s.finish()
        print("run_tls_refusals: the server did not print its ready line", file=sys.stderr)
        return 1
    pump_until(lambda: time.monotonic() - s.last >= o.quiet, 5)
    report = [s.text().replace("\r\n", "\n").rstrip("\n")]
    mark = len(s.buf)
    ca = os.path.join(o.certdir, "ca.pem")
    for i, (label, args) in enumerate(CASES, 1):
        argv = [o.openssl, "s_client", "-connect", o.addr, "-CAfile", ca, "-quiet", "-verify_return_error"]
        argv += [os.path.join(o.certdir, a) if a.endswith(".pem") else a for a in args]
        try:
            subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=8)
        except subprocess.TimeoutExpired:
            pass
        pump_until(lambda: False, 0.2)
        pump_until(lambda: time.monotonic() - s.last >= o.quiet, 6)
        lines = s.buf[mark:].decode("utf-8", "replace").replace("\r\n", "\n").rstrip("\n")
        mark = len(s.buf)
        report.append(f"case {i}: {label}")
        if lines:
            report.append(lines)
        if time.monotonic() - t0 > o.cap:
            break
    s.tell_exit()
    pump_until(lambda: s.p.poll() is not None, 10)
    if s.p.poll() is None:
        s.kill()
    rc = s.p.wait()
    with open(o.out, "w") as f:
        f.write("\n".join(report) + "\n")
        f.write(f"exit={rc}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
