#!/usr/bin/env python3
"""N2T: the live test of BEAM mode INSIDE TLS against a stock Erlang node started with `erl -proto_dist inet_tls`
(development-plan/spikes/N2T-beam-tls.md). The mechanics are tools/n2_live.py's (a private EPMD, which stays plaintext as for
stock Erlang; the stock side under `erl -noshell`; outputs normalised the same way), with the TLS settings of each stock node
written to an ssl_dist_optfile in LEAF/build. Everything stays on 127.0.0.1; the certificates are the TEST-ONLY ones of
trials/n2t_pair/certs (tools/bees_beam_tls_certs.py).

    bees_beam_tls_live.py LEAF_DIR SCENARIO...

The stock node's option files (what a stock node needs to talk to a BEES node: TLS 1.3; verify_peer on both halves and
fail_if_no_peer_cert on the server half for mutual TLS). Every file SAYS its versions and, for TLS 1.3, its key exchange
group, so that a scenario shows the same thing whatever the installed OTP offers by default: OTP 28's inet_tls_dist
offers TLS 1.2 only unless told and has no X25519MLKEM768; OTP 29 (ssl 11.x on OpenSSL 4.1, seen 2026-11-20) offers
TLS 1.3 and puts x25519mlkem768 first. The group named is classical x25519: these scenarios are the ones that show a
stock node on the classical exchange BEAM mode accepts (spikes/N2T-beam-tls.md, profile). The hybrid exchange is shown
between two BEES nodes by trials/n2t_pair.
    good     certificate stock (Ed25519), {versions, ['tlsv1.3']}, {supported_groups, [x25519]}
    rsa      certificate stock_rsa (RSA 2048), the same
    tls12    certificate stock, {versions, ['tlsv1.2']}: a stock node that offers TLS 1.2 only
    rogue    certificate rogue (another CA), as good
Scenarios (BEES node l listens and registers with EPMD; BEES node d dials through EPMD):
    stock_dials        n2_live's stock_dials over TLS: ping (pong), nodes(), a message each way, SEND to a handed-out pid, link,
                       unlink, monitor, 26 s idle with ticks, BEES killed: nodedown and noconnection
    bees_dials         n2_live's bees_dials over TLS: BEES finds the stock node in EPMD, dials it inside TLS (SNI and name check
                       localhost), casts to its inbox; the stock node answers to outbox
    stock_rsa_dials    a stock node with an RSA certificate dials BEES: pong, a message each way (N2T Q4)
    bees_dials_rsa     BEES dials a stock node with an RSA certificate: a message each way
    stock_tls12        a stock node that offers TLS 1.2 only pings BEES: refused at the TLS handshake, pang
    stock_plain        a stock node WITHOUT -proto_dist inet_tls pings BEES's TLS listener: refused, pang
    stock_wrong_ca     a stock node with a certificate of another CA pings BEES: refused, pang
    wrong_cookie       a stock node with good TLS and another cookie pings BEES: TLS established, the digest refused, pang
    bees_dials_tls12   BEES dials a stock node that offers TLS 1.2 only: BEES's handshake fails, no link
    bees_dials_plain   BEES dials a stock node that listens in plaintext: BEES's TLS handshake is closed, no link
    bees_redials_epmd  F1-1 (spikes/F1-fuzzer.md): BEES node r (redial on, 6 s) starts BEFORE the stock node: its EPMD lookup fails
                       (the peer is not registered), the link is failed like a refused dial and the redial is scheduled; the stock
                       node then registers, BEES's next attempt (a new EPMD lookup) finds it and dials it inside TLS, and the stock
                       node casts to BEES's outbox over the new link. The driver adds one line saying whether the stock node had
                       registered before that attempt (else the run proves nothing); the reaper's "proxy ended" line, whose order
                       against the redial actor's line is not fixed, is dropped.
"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import n2_live as N  # noqa: E402
import trial_ports  # noqa: E402

N.EPMD_PORT = str(trial_ports.port("n2t_live", 90))
GOOD = "n2t-live-cookie"
WRONG = "another-cookie"
CERTS = os.path.join(os.path.dirname(HERE), "trials", "n2t_pair", "certs")
OPTFILES = {"good": ("stock", True), "rsa": ("stock_rsa", True), "tls12": ("stock", False), "rogue": ("rogue", True)}


def write_optfiles(leaf):
    ca = os.path.join(CERTS, "ca.pem")
    for name, (cert, v13) in OPTFILES.items():
        common = f'{{certfile, "{CERTS}/{cert}.pem"}}, {{keyfile, "{CERTS}/{cert}-key.pem"}}, {{cacertfile, "{ca}"}}, {{verify, verify_peer}}'
        ver = ", {versions, ['tlsv1.3']}, {supported_groups, [x25519]}" if v13 else ", {versions, ['tlsv1.2']}"
        with open(os.path.join(leaf, "build", f"{name}.optfile"), "w") as fh:
            fh.write(f"[{{server, [{common}, {{fail_if_no_peer_cert, true}}{ver}]}},\n {{client, [{common}{ver}]}}].\n")


def stock(leaf, name, cookie, mod, fn, bees, opt):
    """a stock node; opt names its ssl_dist_optfile, or None for a plaintext node (no -proto_dist)"""
    argv = ["erl", "-sname", f"{name}@localhost", "-setcookie", cookie, "-kernel", "net_ticktime", N.TICK,
            "-kernel", "inet_dist_use_interface", "{127,0,0,1}"]
    if opt:
        argv += ["-proto_dist", "inet_tls", "-ssl_dist_optfile", os.path.join(leaf, "build", f"{opt}.optfile")]
    argv += ["-pa", os.path.join(leaf, "build"), "-noshell", "-eval", f"{mod}:{fn}('{bees}'), halt()."]
    return N.Proc(argv, env=N.env(), cwd=leaf)


# name -> (who dials, the stock node's cookie, module, function, option file)
SCENARIOS = {
    "stock_dials": ("stock_long", GOOD, "stock_driver", "stock_dials", "good"),
    "bees_dials": ("bees", GOOD, "stock_driver", "bees_dials", "good"),
    "stock_rsa_dials": ("stock", GOOD, "stock_tls", "ping_cast", "rsa"),
    "bees_dials_rsa": ("bees", GOOD, "stock_driver", "bees_dials", "rsa"),
    "stock_tls12": ("stock", GOOD, "stock_tls", "refused_ping", "tls12"),
    "stock_plain": ("stock", GOOD, "stock_tls", "refused_ping", None),
    "stock_wrong_ca": ("stock", GOOD, "stock_tls", "refused_ping", "rogue"),
    "wrong_cookie": ("stock", WRONG, "stock_tls", "refused_ping", "good"),
    "bees_dials_tls12": ("bees_refused", GOOD, "stock_tls", "waits", "tls12"),
    "bees_dials_plain": ("bees_refused", GOOD, "stock_tls", "waits", None),
    "bees_redials_epmd": ("bees_late", GOOD, "stock_tls", "late_peer", "good"),
}


def scenario(leaf, name):
    if name not in SCENARIOS:
        print(f"bees_beam_tls_live: unknown scenario {name}")
        return 1
    kind, cookie, mod, fn, opt = SCENARIOS[name]
    if kind == "stock_long":
        b = N.bees(leaf, "l", "dangerous_beesl")
        ok = b.wait_for("epmd: registered", 15)
        s = stock(leaf, "stock", cookie, mod, fn, "beesl@localhost", opt)
        if ok and s.wait_for("KILL NOW", 90):
            brc = b.kill()
            brc = "killed (SIGKILL)" if brc == -9 else brc
        else:
            brc = b.quit()
        src = s.wait(60)
    elif kind == "stock":
        b = N.bees(leaf, "l", "dangerous_beesl")
        b.wait_for("epmd: registered", 15)
        s = stock(leaf, "stock", cookie, mod, fn, "beesl@localhost", opt)
        s.wait_for("stock: done", 60)
        src = s.wait(30)
        time.sleep(1.0)
        brc = b.quit()
    elif kind == "bees_late":
        b = N.bees(leaf, "r", "dangerous_beesr")
        failed = b.wait_for("epmd: the peer is not registered", 20)
        s = stock(leaf, "stock", cookie, mod, fn, "beesr@localhost", opt)
        registered = s.wait_for("stock: registered", 30)
        before = failed and registered and not any("redial attempt" in l for l in b.text())
        s.wait_for("stock: done", 60)
        time.sleep(1.0)
        brc = b.quit()
        src = s.wait(30)
        bl, sl = b.text(), s.text()
        normed = [l for l in N.norm_bees(bl, brc) if not l.startswith("proxy ended")]
        normed.insert(len(normed) - 1, f"driver: the first EPMD lookup failed and the stock node registered before the next attempt: {'yes' if before else 'NO'}")
        N.write(leaf, name, "bees", bl, normed)
        N.write(leaf, name, "stock", sl, N.norm_stock(sl, src))
        print(f"[n2t_live] {name}: bees exit {brc}, stock exit {src}")
        return 0
    else:
        s = stock(leaf, "stock", cookie, mod, fn, "beesd@localhost", opt)
        s.wait_for("stock: waiting", 20)
        time.sleep(0.5)
        b = N.bees(leaf, "d", "dangerous_beesd")
        s.wait_for("stock: done", 60)
        time.sleep(1.0 if kind == "bees" else 0.5)
        brc = b.quit()
        src = s.wait(30)
    bl, sl = b.text(), s.text()
    N.write(leaf, name, "bees", bl, N.norm_bees(bl, brc))
    N.write(leaf, name, "stock", sl, N.norm_stock(sl, src))
    print(f"[n2t_live] {name}: bees exit {brc}, stock exit {src}")
    return 0


def main(argv):
    leaf, names = os.path.abspath(argv[1]), argv[2:]
    os.makedirs(os.path.join(leaf, "build"), exist_ok=True)
    for src in (os.path.join(os.path.dirname(HERE), "trials", "n2_live", "stock_driver.erl"), os.path.join(leaf, "stock_tls.erl")):
        r = subprocess.run(["erlc", "-o", os.path.join(leaf, "build"), src], capture_output=True, text=True)
        if r.returncode != 0:
            print(r.stdout + r.stderr)
            return 1
    write_optfiles(leaf)
    subprocess.run(["epmd", "-port", N.EPMD_PORT, "-kill"], capture_output=True, env=N.env())
    subprocess.run(["epmd", "-port", N.EPMD_PORT, "-address", "127.0.0.1", "-daemon"], env=N.env(), check=True)
    time.sleep(0.5)
    rc = 0
    try:
        for n in names:
            rc |= scenario(leaf, n)
            time.sleep(1.0)
    finally:
        subprocess.run(["epmd", "-port", N.EPMD_PORT, "-kill"], capture_output=True, env=N.env())
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv))
