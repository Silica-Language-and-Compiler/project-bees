"""The Python TEMPUS extension: a node's configuration (development-plan/tempus-design.md section 11).

The application builds a mapping (a dict) with the keys of the `tempus` section of `bees.config` and passes it to
node_config(), which answers a NodeConfig or raises ConfigRefused. The keys, their meanings and their bounds are those
of the Silica node's configuration (tools/bees_tempus_conf.py), and a refusal says the same thing in the same words:
"tempus.KEY: what is wrong". Nothing is clamped and nothing has a default. A required key that is missing is a
refusal, never a guess. This module reads no file but the certificates of the tempus whitelist.

    role                    "edge" or "sentinel". "bridge" is refused: a bridge is also a member of a TRUST network,
                            and this extension has no TRUST.
    listen_address, port    the address the node listens on: an IPv4 literal ("0.0.0.0" for every interface) or
                            "localhost"; port 1 to 65535
    sentinels               a list of (host, port, cert_name), 1 to 16, required unless the role is "sentinel";
                            host is an IPv4 literal; cert_name names a certificate file of whitelist_cert_dir
    edge, bridge, sentinel  each a mapping {capacity 1 to 256, shuffle_length 1 to 64 and at most the capacity,
                            tick_ms 100 to 3600000}: one per store
    producer_key            (kid, key): kid 1 to 64 bytes (text or bytes), key 32 bytes (bytes, or 64 hex digits)
    identity_keyfile, identity_certfile
                            paths of the node's Ed25519 identity key (PEM, PKCS8) and of its certificate, self-signed
                            over that key
    whitelist_cert_dir      optional: a directory of PEM certificates, the tempus whitelist (the TEMPUS certificates
                            of the bridges and sentinels this node accepts). Every file whose name ends in ".pem" and
                            not in "-key.pem" is one entry, named by its file name; the entries are numbered in the
                            order of their names.
    shuffle_timeout_ms      100 to 60000: ONE bound for a whole connection, from the dial or the accept to the close
    inflight_max            1 to 64: accepted connections served at once
    clock_skew_ms           0 to 300000
    clock_back              "follow", "hold" or "stop": what a reading of the clock earlier than the node's time does
    clock_back_limit_s      0 to 86400: required when clock_back is "stop", refused otherwise
    clock_fail              "continue" or "pause": what a reading that fails after a good one does
    clock_read_ms           100 to 60000: how often the clock is read
    join_retry_initial_ms, join_retry_max_ms
                            100 to 3600000; the maximum not below the initial
    edge_spec, bridge_spec, sentinel_spec
                            optional, and only "none": what an admitted peer of that type may call here. Only a bridge
                            serves calls.

Refused by name: control_test_only (no configuration turns the test frames on; they are in no part of the extension),
and whitelist_file (TRUST's file of permission specs: it says what a peer may call, which concerns a bridge only, and
this extension does not read it).
"""
import os
import re

from bees_tempus_admission import certificate_der, fingerprint
from bees_tempus_codec import Refused

ROLES = ("edge", "bridge", "sentinel")
TYPE_OF_ROLE = {"edge": "tempus_edge", "bridge": "tempus_bridge", "sentinel": "tempus_sentinel"}
STORES = ("edge", "bridge", "sentinel")
STORE = (("capacity", 1, 256), ("shuffle_length", 1, 64), ("tick_ms", 100, 3600000))
INTS = (("port", 1, 65535), ("shuffle_timeout_ms", 100, 60000), ("inflight_max", 1, 64), ("clock_skew_ms", 0, 300000),
        ("join_retry_initial_ms", 100, 3600000), ("join_retry_max_ms", 100, 3600000), ("clock_read_ms", 100, 60000))
CLOCK_BACK = ("follow", "hold", "stop")
CLOCK_FAIL = ("continue", "pause")
CLOCK_BACK_LIMIT_S = (0, 86400)
REQUIRED = ("role", "listen_address", "port", "edge", "bridge", "sentinel", "producer_key", "identity_keyfile",
            "identity_certfile", "shuffle_timeout_ms", "inflight_max", "clock_skew_ms", "join_retry_initial_ms",
            "join_retry_max_ms", "clock_back", "clock_fail", "clock_read_ms")
SPECS = ("edge_spec", "bridge_spec", "sentinel_spec")
KEYS = REQUIRED + ("clock_back_limit_s", "sentinels", "whitelist_cert_dir") + SPECS
REMOVED = {
    "control_test_only": "no such key any more: the test-only tick and clock frames are not in the library; a test "
                         "program lists the test unit (src/tempus_test/bees_tempus_test.silica) in its build, and no "
                         "configuration turns them on (ruling of 2026-11-20 on OQ-20)",
    "whitelist_file": "not read by the Python extension: it gives what each whitelisted peer may call, and only a "
                      "bridge serves calls; give the certificates in whitelist_cert_dir",
}
_IPV4 = re.compile(r"(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})")


class ConfigRefused(Exception):
    """A configuration this extension does not start a node with. The text is "tempus.KEY: what is wrong"."""

    def __init__(self, key, why):
        Exception.__init__(self, "tempus%s: %s" % ("." + key if key else "", why))
        self.key, self.why = key, why


def _int(v, key, lo, hi):
    if isinstance(v, bool) or not isinstance(v, int):
        raise ConfigRefused(key, "expected an integer")
    if v < lo:
        raise ConfigRefused(key, "%d is below %d (bounds %d to %d; never clamped)" % (v, lo, lo, hi))
    if v > hi:
        raise ConfigRefused(key, "%d is above %d (bounds %d to %d; never clamped)" % (v, hi, lo, hi))
    return v


def _str(v, key):
    if not isinstance(v, str):
        raise ConfigRefused(key, "expected a string")
    return v


def _choice(v, key, choices):
    if not isinstance(v, str) or v not in choices:
        raise ConfigRefused(key, "expected one of %s" % ", ".join(choices))
    return v


def is_ipv4(text):
    m = _IPV4.fullmatch(text)
    return bool(m) and all(int(g) <= 255 for g in m.groups())


def _store(v, key):
    if not isinstance(v, dict):
        raise ConfigRefused(key, "expected a mapping of capacity, shuffle_length and tick_ms")
    for k in v:
        if k not in [name for name, _lo, _hi in STORE]:
            raise ConfigRefused("%s.%s" % (key, k), "unknown key")
    out = {}
    for name, lo, hi in STORE:
        if name not in v:
            raise ConfigRefused("%s.%s" % (key, name), "required (no default)")
        out[name] = _int(v[name], "%s.%s" % (key, name), lo, hi)
    if out["shuffle_length"] > out["capacity"]:
        raise ConfigRefused(key + ".shuffle_length", "%d is above the capacity %d" % (out["shuffle_length"], out["capacity"]))
    return out


def _producer(v):
    key = "producer_key"
    if not isinstance(v, (tuple, list)) or len(v) != 2:
        raise ConfigRefused(key, "expected (kid, public key)")
    kid, pub = v
    kid = kid.encode() if isinstance(kid, str) else kid
    if not isinstance(kid, (bytes, bytearray)) or not 1 <= len(kid) <= 64:
        raise ConfigRefused(key, "the kid is not 1 to 64 bytes")
    if isinstance(pub, str):
        if not re.fullmatch(r"[0-9a-fA-F]{64}", pub):
            raise ConfigRefused(key, "the public key is not 32 bytes as 64 hex digits")
        pub = bytes.fromhex(pub)
    if not isinstance(pub, (bytes, bytearray)) or len(pub) != 32:
        raise ConfigRefused(key, "the public key is not 32 bytes")
    return bytes(kid), bytes(pub)


def _whitelist(directory):
    """[(name, fingerprint)] in the order of the names"""
    key = "whitelist_cert_dir"
    if not os.path.isdir(directory):
        raise ConfigRefused(key, '"%s" is not a directory' % directory)
    out = []
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".pem") or name.endswith("-key.pem"):
            continue
        try:
            with open(os.path.join(directory, name), "rb") as f:
                out.append((name, fingerprint(certificate_der(f.read()))))
        except (OSError, Refused):
            raise ConfigRefused(key, '"%s" is not a certificate that can be read' % name)
    return out


def _sentinels(v, names):
    key = "sentinels"
    if not isinstance(v, (list, tuple)) or not 1 <= len(v) <= 16:
        raise ConfigRefused(key, "expected a list of 1 to 16 {Host, Port, CertName}")
    out = []
    for it in v:
        if not isinstance(it, (list, tuple)) or len(it) != 3 or not isinstance(it[0], str) or not isinstance(it[2], str):
            raise ConfigRefused(key, "a sentinel is {Host, Port, CertName}")
        host, port, cert = it
        if not is_ipv4(host):
            raise ConfigRefused(key, '"%s" is not an IPv4 literal (the Python extension dials IPv4 literals only, as '
                                'the Silica node does)' % host)
        if cert not in names:
            raise ConfigRefused(key, '"%s" names no certificate of the tempus whitelist (whitelist_cert_dir)' % cert)
        out.append(("%s:%d" % (host, _int(port, key, 1, 65535)), cert))
    return out


class NodeConfig:
    """A checked configuration. Read its values; build one with node_config()."""

    def __init__(self, values):
        self.__dict__.update(values)

    @property
    def typ(self):
        return TYPE_OF_ROLE[self.role]


def node_config(values):
    """The checked configuration of a node, from a mapping with the keys this module's text lists."""
    if not isinstance(values, dict):
        raise ConfigRefused("", "expected a mapping of the tempus keys")
    for k in values:
        if k in REMOVED:
            raise ConfigRefused(k, REMOVED[k])
        if k not in KEYS:
            raise ConfigRefused(str(k), "unknown key")
    for k in REQUIRED:
        if k not in values:
            raise ConfigRefused(k, "required (no default)")
    v = {"role": _choice(values["role"], "role", ROLES)}
    if v["role"] == "bridge":
        raise ConfigRefused("role", "bridge needs mode tempus-trust (a bridge runs TRUST and TEMPUS), and the Python "
                            "extension has no TRUST: it runs an edge or a sentinel")
    v["listen_address"] = _str(values["listen_address"], "listen_address")
    host = "127.0.0.1" if v["listen_address"] == "localhost" else v["listen_address"]
    if not is_ipv4(host):
        raise ConfigRefused("listen_address", '"%s" is not an IPv4 literal or localhost (the Python extension listens '
                            'on IPv4 only)' % v["listen_address"])
    v["listen_host"] = host
    for name, lo, hi in INTS:
        v[name] = _int(values[name], name, lo, hi)
    if v["join_retry_max_ms"] < v["join_retry_initial_ms"]:
        raise ConfigRefused("join_retry_max_ms", "below join_retry_initial_ms")
    v["clock_back"] = _choice(values["clock_back"], "clock_back", CLOCK_BACK)
    v["clock_fail"] = _choice(values["clock_fail"], "clock_fail", CLOCK_FAIL)
    if v["clock_back"] == "stop":
        if "clock_back_limit_s" not in values:
            raise ConfigRefused("clock_back_limit_s", "required when clock_back is stop (no default)")
        v["clock_back_limit_s"] = _int(values["clock_back_limit_s"], "clock_back_limit_s", *CLOCK_BACK_LIMIT_S)
    elif "clock_back_limit_s" in values:
        raise ConfigRefused("clock_back_limit_s", "clock_back is %s, so no step back stops the node: remove "
                            "clock_back_limit_s (it is for clock_back stop only)" % v["clock_back"])
    else:
        v["clock_back_limit_s"] = None
    v["stores"] = dict(("tempus_" + s, _store(values[s], s)) for s in STORES)
    v["producer_kid"], v["producer_pub"] = _producer(values["producer_key"])
    for k in ("identity_keyfile", "identity_certfile"):
        v[k] = _str(values[k], k)
    entries = _whitelist(_str(values["whitelist_cert_dir"], "whitelist_cert_dir")) if "whitelist_cert_dir" in values else []
    v["whitelist_names"] = [name for name, _fp in entries]
    v["whitelist"] = [fp for _name, fp in entries]
    if "sentinels" in values:
        v["sentinels"] = _sentinels(values["sentinels"], v["whitelist_names"])
    elif v["role"] != "sentinel":
        raise ConfigRefused("sentinels", "required unless the node is the first sentinel (role sentinel)")
    else:
        v["sentinels"] = []
    for k in SPECS:
        if k in values and values[k] != "none":
            raise ConfigRefused(k, "only none: what a peer may call is served by a bridge only, and the Python "
                                "extension runs no bridge")
    # The node's clock is in whole seconds. How the Silica node's configuration turns clock_skew_ms into the seconds
    # its node takes is not built there yet (it waits on the store reader, NQ-21); here it is the whole seconds in it.
    v["clock_skew_s"] = v["clock_skew_ms"] // 1000
    return NodeConfig(v)
