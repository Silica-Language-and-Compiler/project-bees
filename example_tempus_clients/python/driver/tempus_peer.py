#!/usr/bin/env python3
"""tempus_peer.py: the driver application of the Python example TEMPUS client. EXAMPLE ONLY, not for production.

A thin program over the library in ../lib/tempus_client. It reads its values from the command line and from the files
the command line names, hands them to the library, and prints what the library reports, one line each.

  gossip OPTIONS                      be a member of a TEMPUS network: listen, join through the sentinels, shuffle the
                                      three stores on their timers, answer the peers that dial. Prints the peer's own
                                      lines and, for every peer it comes to know, `learned STORE ID16 HOST:PORT`.
                                      Runs until it is interrupted or ended, or for --run-ms; then prints, per store,
                                      `known STORE: ID16 ...` (every peer it ever learned of, sorted).
  dial HOST:PORT OPTIONS REQUEST      connect, be admitted, send one request, print the outcome as one line
      REQUEST: sample STORE N
               shuffle STORE          offers this client's own entry at age 0
  read-hex HEX SHUFFLE_LENGTH         read one frame body given as hex digits and print what it is

  OPTIONS, all required unless marked:
      --cert FILE              this peer's certificate, PEM, self-signed over its Ed25519 key
      --key FILE               its private key, PEM (PKCS#8, not encrypted)
      --token FILE             its token from the producer, as hex digits in a file
      --addr HOST:PORT         the address this peer advertises (gossip: it also listens there)
      --producer-pub HEX       the producer's current public key, 64 hex digits
      --kid TEXT               the identifier of that key
      --skew SECONDS           the clock difference this peer allows
      --timeout-ms MS          the time bound of a whole connection
      --whitelist-cert FILE    optional, may be repeated: the certificate (PEM) of a bridge or sentinel this peer accepts
      --now SECONDS            optional: the time for token checks, in seconds since 1970 UTC, in place of the system clock
    dial only:
      --shuffle-length N       the shuffle length of the network
    gossip only:
      --store-edge CAP:LEN:TICK_MS      capacity, shuffle length and tick of the edge store
      --store-bridge CAP:LEN:TICK_MS    the same of the bridge store
      --store-sentinel CAP:LEN:TICK_MS  the same of the sentinel store
      --join-retry-ms FIRST:MAX         the join's first and greatest retry delay
      --sentinel HOST:PORT     may be repeated; none for a first sentinel
      --trusted-cert FILE      may be repeated: the certificate (PEM) of a peer that may dial this one. Python's ssl
                               accepts a client's certificate only when it was given beforehand (../README.md)
      --run-ms MS              optional: stop after that long
  STORE is tempus_edge, tempus_bridge or tempus_sentinel.
"""
import argparse
import os
import signal
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import tempus_client as tc  # noqa: E402


def _read(path):
    with open(path, "rb") as f:
        return f.read()


def _common(ap, gossip):
    for name in ("--cert", "--key", "--token", "--addr", "--producer-pub", "--kid"):
        ap.add_argument(name, required=True)
    ap.add_argument("--skew", required=True, type=int)
    ap.add_argument("--timeout-ms", required=True, type=int)
    ap.add_argument("--whitelist-cert", action="append", default=[])
    ap.add_argument("--now", type=int)
    if gossip:
        for name in ("--store-edge", "--store-bridge", "--store-sentinel", "--join-retry-ms"):
            ap.add_argument(name, required=True)
        ap.add_argument("--sentinel", action="append", default=[])
        ap.add_argument("--trusted-cert", action="append", default=[])
        ap.add_argument("--run-ms", type=int)
    else:
        ap.add_argument("--shuffle-length", required=True, type=int)


def _setup(o, whitelist):
    """the identity and the verifier; whitelist False: the whitelist rule is not applied (a single dial, to any peer)"""
    me = tc.Identity.from_pem(_read(o.cert), _read(o.key), bytes.fromhex(_read(o.token).decode("ascii").strip()), o.addr)
    now = (lambda: o.now) if o.now is not None else (lambda: int(time.time()))
    listed = {tc.certificate_fingerprint(_read(p)) for p in o.whitelist_cert}
    verifier = tc.Verifier(bytes.fromhex(o.producer_pub), o.kid, now, o.skew, whitelist=listed if whitelist or listed else None)
    return me, verifier


def _say(line):
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def _dial(argv):
    ap = argparse.ArgumentParser(prog="tempus_peer.py dial")
    ap.add_argument("peer")
    _common(ap, False)
    ap.add_argument("request", nargs="+")
    o = ap.parse_args(argv)
    me, verifier = _setup(o, False)
    r = o.request
    if r[0] == "sample" and len(r) == 3:
        body = tc.sample(r[1], int(r[2]))
    elif r[0] == "shuffle" and len(r) == 2:
        body = tc.shuffle(r[1], [me.entry(0)])
    else:
        ap.error("the request is: sample STORE N | shuffle STORE")
    _say(tc.dial(o.peer, me, verifier, body, timeout=o.timeout_ms / 1000.0, shuffle_length=o.shuffle_length).line())
    return 0


def _store(text):
    capacity, length, tick_ms = (int(x) for x in text.split(":"))
    return tc.StoreSettings(capacity, length, tick_ms)


def _gossip(argv):
    ap = argparse.ArgumentParser(prog="tempus_peer.py gossip")
    _common(ap, True)
    o = ap.parse_args(argv)
    me, verifier = _setup(o, True)
    first, most = (int(x) for x in o.join_retry_ms.split(":"))
    settings = tc.PeerSettings({"tempus_edge": _store(o.store_edge), "tempus_bridge": _store(o.store_bridge),
                                "tempus_sentinel": _store(o.store_sentinel)}, o.timeout_ms, o.sentinel, first, most)
    known = {t: set() for t in tc.TYPES}
    lock = threading.Lock()

    def learned(store, d):
        pid = d[tc.Atom("id")][:8].hex()
        with lock:
            new = pid not in known[store]
            known[store].add(pid)
        if new:
            _say("learned %s %s %s" % (store, pid, d[tc.Atom("addr")].decode("utf-8", "replace")))

    host, _, port = o.addr.rpartition(":")
    peer = tc.Peer(me, verifier, settings, host=host, port=int(port), trusted=[_read(p) for p in o.trusted_cert],
                   on_line=_say, on_learned=learned)
    ended = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: ended.set())
    peer.start()
    ended.wait(None if o.run_ms is None else o.run_ms / 1000.0)
    peer.stop()
    with lock:
        for t in tc.TYPES:
            _say("known %s: %s" % (t, " ".join(sorted(known[t])) or "(none)"))
    return 0


def main(argv):
    if len(argv) >= 2 and argv[1] == "gossip":
        return _gossip(argv[2:])
    if len(argv) >= 2 and argv[1] == "dial":
        return _dial(argv[2:])
    if len(argv) == 4 and argv[1] == "read-hex":
        try:
            kind, fields = tc.read_body(bytes.fromhex(argv[2]), int(argv[3]))
            _say("%s %s" % (kind, {k: (v if not isinstance(v, bytes) else v.hex()) for k, v in fields.items()}))
        except tc.Refused as why:
            _say("refused: %s" % why)
        return 0
    sys.stdout.write(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
