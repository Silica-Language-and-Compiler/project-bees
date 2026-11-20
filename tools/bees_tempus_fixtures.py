#!/usr/bin/env python3
"""TEST-ONLY fixtures for the TEMPUS admission trial (T4): keys, tokens, descriptors and proofs, as a Silica unit.

    bees_tempus_fixtures.py write   writes trials/t4_tempus_admission/lib/tempus_fixtures.silica
    bees_tempus_fixtures.py check   fails when that file is not what this tool writes now

Everything is made with example_tempus_clients/python/bees_tempus_client.py and the `cryptography` package from fixed seeds (00..1f the producer,
20..3f the node, 40..5f another key, 60..7f the producer's old key): keys that belong to nobody. Ed25519 is deterministic,
so the file is the same on every run. cases() also says what a correct verifier must answer for each case, computed here
with the Python client's own checks: tools/test_bees_tempus_admission.py compares that with what the Silica node answered.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "example_tempus_clients", "python"))  # the example Python client
import bees_tempus_client as c  # noqa: E402
from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

OUT = os.path.join(ROOT, "trials", "t4_tempus_admission", "lib", "tempus_fixtures.silica")
RAW = serialization.Encoding.Raw, serialization.PublicFormat.Raw
KID, NOW, SKEW = "k1", 1500, 10
ADDR = "127.0.0.1:22801"
STORE = {"tempus_edge": 1, "tempus_bridge": 2, "tempus_sentinel": 3}


def key(first):
    seed = bytes(range(first, first + 32))
    k = Ed25519PrivateKey.from_private_bytes(seed)
    return seed, k, k.public_key().public_bytes(*RAW)


PRODUCER_SEED, PRODUCER, PRODUCER_PUB = key(0)
NODE_SEED, NODE, NODE_PUB = key(32)
OTHER_SEED, OTHER, OTHER_PUB = key(64)
OLD_SEED, OLD, OLD_PUB = key(96)
NONCE = bytes(range(128, 160))


def cases():
    """A list of dicts: name, kind (1 descriptor, 2 proof, 3 sign), the bytes, want, and `expect` ("" admitted, else why)."""
    out = []

    def desc(name, token, want="tempus_edge", pub=NODE_PUB, pid=None):
        pid = c.peer_id(pub) if pid is None else pid
        out.append({"name": name, "kind": 1, "id": pid, "pub": pub, "token": token, "want": STORE[want], "nonce": b"", "sig": b"",
                    "expect": expect_descriptor(pid, pub, token, want)})

    def tok(signer=PRODUCER, kid=KID, sub=NODE_PUB, typ="tempus_edge", nbf=1000, exp=2000):
        return c.make_token(signer, kid, sub, typ, nbf, exp)

    good = tok()
    desc("a good edge token", good)
    desc("expired", tok(exp=1400))
    desc("not valid yet", tok(nbf=1600))
    desc("expired, inside the skew", tok(exp=1495))
    desc("not valid yet, inside the skew", tok(nbf=1505))
    desc("expired at exactly exp plus skew", tok(exp=1490))
    desc("under another kid", tok(signer=OLD, kid="k0"))
    desc("under another kid and expired too", tok(signer=OLD, kid="k0", exp=1400))
    desc("signed by a key that is not the producer's", tok(signer=OTHER))
    desc("sub is another key", tok(sub=OTHER_PUB))
    desc("a bridge token where an edge is wanted", tok(typ="tempus_bridge"))
    desc("a bridge token where a bridge is wanted", tok(typ="tempus_bridge"), want="tempus_bridge")
    desc("id is not the hash of pub", good, pid=c.peer_id(OTHER_PUB))
    # the payload changed after signing: sub (and the descriptor's pub and id with it) is another key, the signature is the old one
    changed = good.replace(NODE_PUB, OTHER_PUB)
    desc("payload changed after signing", changed, pub=OTHER_PUB)
    desc("token cut short", good[:-1])

    def proof(name, pub, sig, nonce, token, ok):
        out.append({"name": name, "kind": 2, "id": b"", "pub": pub, "token": token, "want": 0, "nonce": nonce, "sig": sig,
                    "expect": "" if ok else "the signature does not verify"})

    pop = NODE.sign(NONCE + good)
    proof("proof of possession", NODE_PUB, pop, NONCE, good, True)
    proof("proof for another nonce", NODE_PUB, pop, bytes(32), good, False)
    proof("proof by another key", NODE_PUB, OTHER.sign(NONCE + good), NONCE, good, False)
    proof("proof over another token", NODE_PUB, pop, NONCE, tok(exp=1400), False)
    out.append({"name": "the node signs nonce and token", "kind": 3, "id": b"", "pub": NODE_SEED, "token": good, "want": 0,
                "nonce": NONCE, "sig": pop, "expect": ""})
    return out


def expect_descriptor(pid, pub, token, want):
    """What a correct verifier answers, by the Python client's own checks, in the order design section 4 gives."""
    d = c.descriptor(pid, pub, ADDR, token)
    try:
        c.check_descriptor(d)
        fields, payload, sig = c.read_token(token)
    except c.Refused as why:
        return str(why)
    if fields["kid"] != KID.encode():
        return "key_rotated"
    if NOW < fields["nbf"] - SKEW:
        return "the token is not valid yet"
    if NOW >= fields["exp"] + SKEW:
        return "the token has expired"
    if fields["sub"] != pub:
        return "sub is not the peer's key"
    if fields["typ"] != want:
        return "typ is not the store's type"
    if c.peer_id(pub) != pid:
        return "id is not the SHA-512 of pub"
    try:
        PRODUCER.public_key().verify(sig, payload)
    except Exception:
        return "the signature does not verify"
    return ""


def silica():
    cs = cases()

    def table(fn, field, kind):
        lines = ["fn %s(k: int64) -> %s {" % (fn, kind), "    case k of {"]
        for i, case in enumerate(cs):
            v = case[field]
            text = str(v) if kind == "int64" else '"%s"' % (v.hex() if isinstance(v, bytes) else v)
            lines.append("        %d -> %s;" % (i, text))
        lines.append("        _: int64 -> %s" % ("0" if kind == "int64" else '""'))
        lines += ["    }", "}"]
        return "\n".join(lines)

    head = '''// GENERATED by tools/bees_tempus_fixtures.py (`write`); do not edit. TEST ONLY: keys, tokens and proofs for
// trials/t4_tempus_admission, made from fixed seeds (keys that belong to nobody). Byte strings are written as hex and
// read with unhex/1. Case kinds: 1 a descriptor to admit (id, pub, token, the store type wanted), 2 a proof of possession
// (pub, sig, nonce, token), 3 a signature the node makes itself (pub holds the node's private seed; sig is what it must equal).
module tempus_fixtures;

export count/0;
export name/1;
export kind/1;
export id_hex/1;
export pub_hex/1;
export token_hex/1;
export nonce_hex/1;
export sig_hex/1;
export want/1;
export producer_pub_hex/0;
export kid/0;
export now/0;
export skew/0;
export addr/0;
export unhex/1;

fn count() -> int64 { %d }
fn producer_pub_hex() -> string { "%s" }
fn kid() -> string { "%s" }
fn now() -> int64 { %d }
fn skew() -> int64 { %d }
fn addr() -> string { "%s" }

fn at(s: string, i: int64) -> int64 {
    sequence proc[transport]
        b: int64 <- byte_at(s, i)
    produces pure b end
}
fn nibble(b: int64) -> int64 { case b >= 97 of { true -> b - 87; false -> b - 48 } }
fn pairs(s: string, i: int64, acc: List[int64, mem(normal)]) -> List[int64, mem(normal)] {
    case i < 0 of {
        true -> acc;
        false -> {
            v: int64 <- nibble(at(s, i)) * 16 + nibble(at(s, i + 1));
            j: int64 <- i - 2;
            sequence proc[mem(normal)]
                nxt: List[int64, mem(normal)] <- prepend[int64, mem(normal)](v, acc)
            produces pure pairs(s, j, nxt) end
        }
    }
}
// the bytes a string of lower-case hex digits spells
fn unhex(s: string) -> string {
    sequence proc[mem(normal), transport]
        e: List[int64, mem(normal)] <- empty[int64, mem(normal)]();
        xs: List[int64, mem(normal)] <- pairs(s, length_bytes(s) - 2, e);
        out: string <- bytes_of(xs)
    produces pure out end
}
''' % (len(cs), PRODUCER_PUB.hex(), KID, NOW, SKEW, ADDR)
    parts = [head, table("name", "name", "string"), table("kind", "kind", "int64"), table("id_hex", "id", "string"),
             table("pub_hex", "pub", "string"), table("token_hex", "token", "string"), table("nonce_hex", "nonce", "string"),
             table("sig_hex", "sig", "string"), table("want", "want", "int64")]
    return "\n".join(parts) + "\n"


def main(argv):
    if len(argv) == 2 and argv[1] == "write":
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        with open(OUT, "w") as f:
            f.write(silica())
        return 0
    if len(argv) == 2 and argv[1] == "check":
        with open(OUT) as f:
            same = f.read() == silica()
        print("fixtures are current" if same else "fixtures differ from what the tool writes: run `write`")
        return 0 if same else 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
