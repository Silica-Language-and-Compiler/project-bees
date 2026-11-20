#!/usr/bin/env python3
"""bees_tempus_conf: the `tempus` part of `bees.config` (T7; development-plan/tempus-design.md section 11), written so
that the one reader, tools/bees_conf.py, can call it. It uses that reader's grammar and checks (Reader, proplist, want_*,
parse_spec, listen_form, is_loopback, ConfError) and changes nothing there.

    bees_tempus_conf.py check BEES_CONFIG     prints the effective TEMPUS values, or the refusal line and exit 1

What it decides:
  mode         {mode, trust} TRUST only (the default); {mode, tempus} TEMPUS only; {mode, tempus-trust} both (with role
               bridge, a bridge); {mode, beam} BEAM mode (owner's ruling on NQ-3). `tempus-trust` is accepted as the owner
               wrote it, bare (which is no Erlang atom: Erlang reads tempus - trust), as the value of mode and nowhere else,
               and quoted, 'tempus-trust'. Until tools/bees_conf.py's own reader takes the bare spelling, read() quotes it
               before handing the text to that reader (one place, the value of mode only).
  tempus       required under tempus and tempus-trust, refused under trust and beam; role bridge needs tempus-trust.
  the options  section 11's table: every bound is a literal here, nothing is clamped, nothing has a default except
               the three specs (none).
  control_test_only   NOT a key any more (owner's ruling of 2026-11-20 on OQ-20): the test-only tick and clock frames
               are in a unit only a test program lists in its build (src/tempus_test/bees_tempus_test.silica), so no
               configuration can turn them on. The key is refused with either value, with a line that says so.
  the clock    ruling NQ-22 of 2026-11-20: clock_back (follow, hold or stop: what a reading of the system clock earlier
               than the node's time does), clock_fail (continue or pause: what a reading that fails after a good one
               does) and clock_read_ms (how often the system clock is read) are required, no default.
               clock_back_limit_s (the greatest step back in seconds that stop still follows) is required under stop and
               refused under follow and hold, where it would mean nothing.
Not here (they need D46's store reader and packer, development-plan/spikes/N0d-store-config.md): turning these values into
the store's records and the node's arguments; file contents as bytes (N0c). The trust section of a tempus-trust file is
validated by tools/bees_conf.py itself, given the file with mode trust and without the tempus section (until that reader
knows the two new modes).
"""
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bees_conf as C  # noqa: E402

MODES = ("beam", "trust", "tempus", "tempus-trust")
ROLES = ("edge", "bridge", "sentinel")
STORE = {"capacity": (1, 256), "shuffle_length": (1, 64), "tick_ms": (100, 3600000)}
INTS = {"port": (1, 65535), "shuffle_timeout_ms": (100, 60000), "inflight_max": (1, 64), "clock_skew_ms": (0, 300000),
        "join_retry_initial_ms": (100, 3600000), "join_retry_max_ms": (100, 3600000), "clock_read_ms": (100, 60000)}
CLOCK_BACK = ("follow", "hold", "stop")     # the node is passed 1, 2, 3 (src/tempus/bees_tempus_node.part, net.back)
CLOCK_FAIL = ("continue", "pause")          # the node is passed 1, 2 (net.fail)
CLOCK_BACK_LIMIT_S = (0, 86400)
REQUIRED = ("role", "listen_address", "port", "edge", "bridge", "sentinel", "producer_key", "identity_keyfile",
            "identity_certfile", "shuffle_timeout_ms", "inflight_max", "clock_skew_ms", "join_retry_initial_ms",
            "join_retry_max_ms", "clock_back", "clock_fail", "clock_read_ms")
KEYS = REQUIRED + ("clock_back_limit_s", "sentinels", "whitelist_file", "whitelist_cert_dir", "edge_spec", "bridge_spec", "sentinel_spec")
# a key of earlier builds, refused by name so that the refusal says where the test frames went
REMOVED = {"control_test_only": "no such key any more: the test-only tick and clock frames are not in the library; a test "
           "program lists the test unit (src/tempus_test/bees_tempus_test.silica) in its build, and no configuration turns "
           "them on (ruling of 2026-11-20 on OQ-20)"}
BARE = re.compile(r"(\{\s*mode\s*,\s*)tempus-trust(\s*\})")


def read(path):
    """the file's top-level term, with the bare `{mode, tempus-trust}` quoted first (the one place it is accepted)"""
    fname = os.path.basename(path)
    with open(path, "rb") as fh:
        raw = fh.read()
    if len(raw) > C.MAX_FILE:
        raise C.ConfError(1, "(file)", "larger than %d bytes (64 KiB)" % C.MAX_FILE, fname)
    if any(b > 127 for b in raw):
        raise C.ConfError(1, "(file)", "a byte outside ASCII (non-ASCII bytes are not accepted)", fname)
    text = BARE.sub(r"\1'tempus-trust'\2", raw.decode("ascii"))
    return C.Reader(text, fname).whole(), text


def mode_of(top, fname):
    if "mode" not in top:
        return "trust", 1
    node, line = top["mode"]
    if node.kind != "atom" or str(node.value) not in MODES:
        raise C.ConfError(line, "mode", "expected beam, trust, tempus or tempus-trust", fname)
    return str(node.value), line


def store(node, path, fname):
    t = C.proplist(node, path, tuple(STORE))
    out = {}
    for k, (lo, hi) in STORE.items():
        if k not in t:
            raise C.ConfError(node.line, "%s.%s" % (path, k), "required (no default)", fname)
        out[k] = C.want_int(t[k][0], "%s.%s" % (path, k), lo, hi)
    if out["shuffle_length"] > out["capacity"]:
        raise C.ConfError(t["shuffle_length"][1], path + ".shuffle_length", "%d is above the capacity %d" %
                          (out["shuffle_length"], out["capacity"]), fname)
    return out


def producer(node, path, fname):
    if node.kind != "tuple" or len(node.value) != 2 or node.value[0].kind != "str" or node.value[1].kind != "str":
        raise C.ConfError(node.line, path, "expected {Kid, PublicKeyHex}: two strings", fname)
    kid, key = node.value[0].value, node.value[1].value
    if not 1 <= len(kid) <= 64:
        raise C.ConfError(node.line, path, "the kid is not 1 to 64 bytes", fname)
    if not re.fullmatch(r"[0-9a-fA-F]{64}", key):
        raise C.ConfError(node.line, path, "the public key is not 32 bytes as 64 hex digits", fname)
    return {"kid": kid, "key": bytes.fromhex(key)}


def sentinels(node, path, fname):
    if node.kind != "list" or not 1 <= len(node.value) <= 16:
        raise C.ConfError(node.line, path, "expected a list of 1 to 16 {Host, Port, CertName}", fname)
    out = []
    for it in node.value:
        if it.kind != "tuple" or len(it.value) != 3 or it.value[0].kind != "str" or it.value[2].kind != "str":
            raise C.ConfError(it.line, path, "a sentinel is {Host, Port, CertName}", fname)
        host = it.value[0].value
        if C.addr_kind(host) not in ("ipv4", "name"):
            raise C.ConfError(it.line, path, '"%s" is not an IPv4 literal or a host name' % host, fname)
        out.append((host, C.want_int(it.value[1], path, 1, 65535), it.value[2].value))
    return out


def tempus_section(top, mode, fname):
    """the effective tempus values, or None for a node that runs no TEMPUS; ConfError on any refusal"""
    has = "tempus" in top
    runs = mode in ("tempus", "tempus-trust")
    # owner's ruling 2026-11-20: BEAM configured together with TEMPUS is refused, whatever the mode says
    if "beam" in top and (has or runs):
        raise C.ConfError(top["beam"][1], "beam", "a beam section in a file that configures TEMPUS: a node is BEAM or "
                          "TEMPUS, never both (the mode is %s)" % mode, fname)
    if has and not runs:
        raise C.ConfError(top["tempus"][1], "tempus", "a tempus section in a %s node (mode tempus or tempus-trust runs TEMPUS)" % mode, fname)
    if runs and not has:
        raise C.ConfError(top["mode"][1] if "mode" in top else 1, "tempus", "required under mode %s (no default)" % mode, fname)
    if not runs:
        return None
    node, line = top["tempus"]
    t = C.proplist(node, "tempus", KEYS + tuple(REMOVED))
    for k, why in REMOVED.items():
        if k in t:
            raise C.ConfError(t[k][1], "tempus." + k, why, fname)
    for k in REQUIRED:
        if k not in t:
            raise C.ConfError(line, "tempus." + k, "required (no default)", fname)
    v = {"role": C.want_atom(t["role"][0], "tempus.role", ROLES)}
    if v["role"] == "bridge" and mode != "tempus-trust":
        raise C.ConfError(t["role"][1], "tempus.role", "bridge needs mode tempus-trust (a bridge runs TRUST and TEMPUS)", fname)
    v["listen_address"] = C.want_str(t["listen_address"][0], "tempus.listen_address")
    try:
        form = C.listen_form(v["listen_address"], t["listen_address"][1], "tempus.listen_address")
    except C.ConfError as e:
        raise C.ConfError(t["listen_address"][1], "tempus.listen_address", e.text.split(": ", 2)[-1], fname)
    for k, (lo, hi) in INTS.items():
        v[k] = C.want_int(t[k][0], "tempus." + k, lo, hi)
    v["listener"] = "%s%d" % (form, v["port"])
    if v["join_retry_max_ms"] < v["join_retry_initial_ms"]:
        raise C.ConfError(t["join_retry_max_ms"][1], "tempus.join_retry_max_ms", "below join_retry_initial_ms", fname)
    v["clock_back"] = C.want_atom(t["clock_back"][0], "tempus.clock_back", CLOCK_BACK)
    v["clock_fail"] = C.want_atom(t["clock_fail"][0], "tempus.clock_fail", CLOCK_FAIL)
    if v["clock_back"] == "stop":
        if "clock_back_limit_s" not in t:
            raise C.ConfError(t["clock_back"][1], "tempus.clock_back_limit_s", "required when clock_back is stop (no default)", fname)
        v["clock_back_limit_s"] = C.want_int(t["clock_back_limit_s"][0], "tempus.clock_back_limit_s", *CLOCK_BACK_LIMIT_S)
    elif "clock_back_limit_s" in t:
        raise C.ConfError(t["clock_back_limit_s"][1], "tempus.clock_back_limit_s", "clock_back is %s, so no step back stops "
                          "the node: remove clock_back_limit_s (it is for clock_back stop only)" % v["clock_back"], fname)
    for s in ("edge", "bridge", "sentinel"):
        v[s] = store(t[s][0], "tempus." + s, fname)
    v["producer_key"] = producer(t["producer_key"][0], "tempus.producer_key", fname)
    for k in ("identity_keyfile", "identity_certfile", "whitelist_file", "whitelist_cert_dir"):
        if k in t:
            v[k] = C.want_str(t[k][0], "tempus." + k)
    if "sentinels" in t:
        v["sentinels"] = sentinels(t["sentinels"][0], "tempus.sentinels", fname)
    elif v["role"] != "sentinel":
        raise C.ConfError(line, "tempus.sentinels", "required unless the node is the first sentinel (role sentinel)", fname)
    else:
        v["sentinels"] = []
    for k in ("edge_spec", "bridge_spec", "sentinel_spec"):
        v[k] = C.parse_spec(t[k][0], "tempus." + k) if k in t else "none"
    return v


def without_tempus(text, mode_line):
    """the file's text for tools/bees_conf.py: mode trust, no tempus section (the reader does not know them yet)"""
    out = re.sub(r"\{\s*mode\s*,\s*'tempus-trust'\s*\}", "{mode, trust}", text)
    i = re.search(r"\{\s*tempus\s*,", out)
    if not i:
        return out
    depth, j = 0, i.start()
    while j < len(out):
        if out[j] in "{[":
            depth += 1
        elif out[j] in "}]":
            depth -= 1
            if depth == 0:
                break
        j += 1
    head, tail = out[:i.start()].rstrip(), out[j + 1:]
    if head.endswith(","):
        head = head[:-1]
    elif tail.lstrip().startswith(","):
        tail = tail.lstrip()[1:]
    return head + tail


def validate(path):
    """-> {mode, tempus (or None), trust (tools/bees_conf.py's effective trust values, or None)}"""
    fname = os.path.basename(path)
    node, text = read(path)
    top = C.proplist(node, "", C.TOP_KEYS + ("tempus",))
    mode, mline = mode_of(top, fname)
    tempus = tempus_section(top, mode, fname)
    trust = None
    if mode in ("trust", "tempus-trust", "beam"):
        base = os.path.dirname(os.path.abspath(path))
        with tempfile.NamedTemporaryFile("w", suffix=".config", dir=base if os.access(base, os.W_OK) else None, delete=False) as fh:
            fh.write(without_tempus(text, mline))
            tmp = fh.name
        try:
            conf = C.validate(tmp)
        except C.ConfError as e:
            raise C.ConfError(0, "(trust or beam part)", e.text.split(": ", 1)[-1], fname)
        finally:
            os.unlink(tmp)
        trust = conf["trust"] if mode != "beam" else None
    return {"mode": mode, "tempus": tempus, "trust": trust}


def main(argv):
    if len(argv) == 3 and argv[1] == "check":
        try:
            v = validate(argv[2])
        except C.ConfError as e:
            print("refused: " + e.text)
            return 1
        print("mode %s" % v["mode"])
        for k, val in sorted((v["tempus"] or {}).items()):
            print("tempus.%s %r" % (k, val))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
