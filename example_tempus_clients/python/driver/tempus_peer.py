#!/usr/bin/env python3
"""tempus_peer.py: the driver application of the Python TEMPUS extension. A usable example, to be used carefully:
../README.md says what care means.

A thin program over the extension's modules in ../lib (bees_tempus_config and bees_tempus_node for `gossip`,
bees_tempus_peer for `dial`). It reads its values from the command line and from the files the command line names,
hands them to the extension, and prints what the extension reports, one line each.

  gossip OPTIONS                      be a node of a TEMPUS network (an edge or a sentinel, by the token's type):
                                      listen, join through the sentinels, shuffle the three stores on their timers,
                                      answer the peers that dial. Prints the node's own lines, its audit lines, and,
                                      for every peer it comes to know, `learned STORE ID16 HOST:PORT`.
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
      --whitelist-cert FILE    optional, may be repeated: the certificate (PEM) of a bridge or sentinel this peer accepts.
                               gossip with a --sentinel needs at least one.
      --now SECONDS            optional: the time for token checks, in seconds since 1970 UTC, in place of the system clock
    dial only:
      --shuffle-length N       the shuffle length of the network
    gossip only:
      --store-edge CAP:LEN:TICK_MS      capacity, shuffle length and tick of the edge store
      --store-bridge CAP:LEN:TICK_MS    the same of the bridge store
      --store-sentinel CAP:LEN:TICK_MS  the same of the sentinel store
      --join-retry-ms FIRST:MAX         the join's first and greatest retry delay
      --sentinel HOST:PORT     may be repeated; none for a first sentinel
      --trusted-cert FILE      optional, may be repeated, and not used: the node accepts a certificate it has never
                               seen, as TEMPUS requires. The option is still read so that older command lines work.
      --run-ms MS              optional: stop after that long
  STORE is tempus_edge, tempus_bridge or tempus_sentinel.

The node takes more values than this command line has. `gossip` states them itself, in GOSSIP_CHOICES below. They are
this driver's choices for the gossip example and nothing more: the extension has no defaults, and an application
makes each of these choices for itself.
"""
import argparse
import os
import shutil
import signal
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import bees_tempus_admission as admission  # noqa: E402
import bees_tempus_codec as codec  # noqa: E402
import bees_tempus_config  # noqa: E402
import bees_tempus_node  # noqa: E402
import bees_tempus_peer  # noqa: E402

# What a node needs and the `gossip` command line does not give. THE DRIVER'S CHOICES FOR THE GOSSIP EXAMPLE, not
# defaults of the extension and not recommendations: at most 16 accepted connections served at once; a clock that
# goes back is followed; a clock that cannot be read leaves the node going on with its last reading; the clock is
# read once a second.
GOSSIP_CHOICES = {"inflight_max": 16, "clock_back": "follow", "clock_fail": "continue", "clock_read_ms": 1000}


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


def _token(o):
    return bytes.fromhex(_read(o.token).decode("ascii").strip())


def _say(line):
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def _dial(argv):
    ap = argparse.ArgumentParser(prog="tempus_peer.py dial")
    ap.add_argument("peer")
    _common(ap, False)
    ap.add_argument("request", nargs="+")
    o = ap.parse_args(argv)
    me = bees_tempus_peer.Identity(o.cert, o.key, _token(o), o.addr)
    now = o.now if o.now is not None else (lambda: int(time.time()))
    # with no --whitelist-cert the whitelist rule is not applied: a single dial, to a peer of any type
    listed = [admission.fingerprint(admission.certificate_der(_read(p))) for p in o.whitelist_cert]
    verifier = admission.Verifier(bytes.fromhex(o.producer_pub), o.kid, now, o.skew, listed or None)
    r = o.request
    if r[0] == "sample" and len(r) == 3:
        body = codec.sample(r[1], int(r[2]))
    elif r[0] == "shuffle" and len(r) == 2:
        body = codec.shuffle(r[1], [me.entry(0)])
    else:
        ap.error("the request is: sample STORE N | shuffle STORE")
    _say(bees_tempus_peer.dial(o.peer, me, verifier, body, timeout=o.timeout_ms / 1000.0, shuffle_length=o.shuffle_length).line())
    return 0


def _store(text):
    capacity, length, tick_ms = (int(x) for x in text.split(":"))
    return {"capacity": capacity, "shuffle_length": length, "tick_ms": tick_ms}


class _FixedClock:
    """--now: the node's clock always reads this"""

    def __init__(self, seconds):
        self.seconds = seconds

    def read(self):
        return self.seconds


def _gossip(argv):
    ap = argparse.ArgumentParser(prog="tempus_peer.py gossip")
    _common(ap, True)
    o = ap.parse_args(argv)
    if o.sentinel and not o.whitelist_cert:
        ap.error("a --sentinel needs a --whitelist-cert: a node accepts a sentinel only under a certificate of its whitelist")
    token = _token(o)
    host, _, port = o.addr.rpartition(":")
    first, most = (int(x) for x in o.join_retry_ms.split(":"))
    # The node's configuration takes its whitelist as a directory of certificates and names one of them for each
    # sentinel. This command line gives certificate files and sentinel addresses, so the driver copies the files into
    # a directory of its own for the run and names the first for every sentinel. The node uses that name only to
    # check that it is in the whitelist; which certificate a sentinel really presents is judged on each connection.
    listed = tempfile.mkdtemp(prefix="tempus-whitelist-")
    try:
        names = []
        for k, path in enumerate(o.whitelist_cert):
            names.append("%03d.pem" % k)
            shutil.copyfile(path, os.path.join(listed, names[-1]))
        values = dict(GOSSIP_CHOICES)
        values.update({
            "role": codec.read_token(token)[0]["typ"][len("tempus_"):],
            "listen_address": host, "port": int(port),
            "edge": _store(o.store_edge), "bridge": _store(o.store_bridge), "sentinel": _store(o.store_sentinel),
            "producer_key": (o.kid, o.producer_pub),
            "identity_keyfile": o.key, "identity_certfile": o.cert, "whitelist_cert_dir": listed,
            "shuffle_timeout_ms": o.timeout_ms, "clock_skew_ms": o.skew * 1000,
            "join_retry_initial_ms": first, "join_retry_max_ms": most,
        })
        if o.sentinel:
            values["sentinels"] = [(s.rpartition(":")[0], int(s.rpartition(":")[2]), names[0]) for s in o.sentinel]
        known = {t: set() for t in codec.TYPES}
        lock = threading.Lock()

        def told(event):
            if event.name != "view":
                _say("told %s%s" % (event.name, "".join(" %s=%s" % kv for kv in sorted(vars(event).items()) if kv[0] != "name")))
                return
            for (pid, d, _age) in event.entries:
                pid = pid[:8].hex()
                with lock:
                    new = pid not in known[event.store]
                    known[event.store].add(pid)
                if new:
                    _say("learned %s %s %s" % (event.store, pid, d[codec.Atom("addr")].decode("utf-8", "replace")))

        try:
            node = bees_tempus_node.Node(bees_tempus_config.node_config(values), token=token, address=o.addr, on_event=told,
                                         log=_say, clock=None if o.now is None else _FixedClock(o.now))
        except (bees_tempus_config.ConfigRefused, codec.Refused) as why:
            _say("refused: %s" % why)
            return 1
        except bees_tempus_node.BootRefused:
            return 1                                 # the node said why
        ended = threading.Event()
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: ended.set())
        node.start()
        ended.wait(None if o.run_ms is None else o.run_ms / 1000.0)
        node.stop()
        with lock:
            for t in codec.TYPES:
                _say("known %s: %s" % (t, " ".join(sorted(known[t])) or "(none)"))
        return 0
    finally:
        shutil.rmtree(listed, ignore_errors=True)


def main(argv):
    if len(argv) >= 2 and argv[1] == "gossip":
        return _gossip(argv[2:])
    if len(argv) >= 2 and argv[1] == "dial":
        return _dial(argv[2:])
    if len(argv) == 4 and argv[1] == "read-hex":
        try:
            kind, fields = codec.read_body(bytes.fromhex(argv[2]), int(argv[3]))
            _say("%s %s" % (kind, {k: (v if not isinstance(v, bytes) else v.hex()) for k, v in fields.items()}))
        except codec.Refused as why:
            _say("refused: %s" % why)
        return 0
    sys.stdout.write(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
