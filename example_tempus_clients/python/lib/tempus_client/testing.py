"""EXAMPLE ONLY, not for production. See ../../README.md.

TEST ONLY. What the trials need of the example client and a program that uses the library does not: the frames of
the test unit (tick, clock, done), tokens signed with the test producer's fixed seed (a client never makes or signs a
token), identities from fixed seeds, certificates a tempus/1 peer must refuse, and every deliberate misbehaviour (rows
12, 17, 18, 19 and 26 of design 16.2), each as a named function.
"""
import struct

from .codec import FRAME_MAX, Atom, etf_encode
from .connection import STAGES, Identity, Misbehaviour, _ed25519, _key_pem, _raw_public, certificate_pem, raw_frame
from .frames import _typ


# ---------------------------------------------------------------- tokens, as the test producer makes them
def token_payload(kid, sub, typ, nbf, exp):
    """The bytes a producer signs: the ETF map of the five fields, times in seconds."""
    return etf_encode({Atom("kid"): kid.encode() if isinstance(kid, str) else kid, Atom("sub"): bytes(sub),
                       Atom("typ"): Atom(typ), Atom("nbf"): nbf, Atom("exp"): exp})


def make_token(signing_key, kid, sub, typ, nbf, exp):
    """A token signed with an Ed25519 private key object of the `cryptography` package."""
    payload = token_payload(kid, sub, typ, nbf, exp)
    return signing_key.sign(payload) + payload



# ---------------------------------------------------------------- the frames of the test unit
def tick(store):
    """TEST ONLY: a frame of the test unit (src/tempus_test/bees_tempus_test.silica), which only a test program lists
    in its build; a node without it refuses the frame as any frame that is not a request."""
    return etf_encode({Atom("t"): Atom("tick"), Atom("store"): _typ(store)})


def clock(ms, wait=None, later=None):
    """TEST ONLY, as tick: a clock reading for the node, ms milliseconds since 1970, or NO_TIME (-1): the clock could
    not be read. With wait and later: wait milliseconds after that reading is taken the node is given a second one,
    later (the same range as ms). The reading that ends a node's wait for its clock cannot arrive in a frame, because
    the waiting node closes every connection (clock_fail pause)."""
    if wait is None and later is None:
        return etf_encode({Atom("t"): Atom("clock"), Atom("ms"): ms})
    return etf_encode({Atom("t"): Atom("clock"), Atom("ms"): ms, Atom("wait"): wait, Atom("later"): later})


def done():
    return etf_encode({Atom("t"): Atom("done")})


# ---------------------------------------------------------------- certificates a tempus/1 peer must refuse
def p256_certificate(private_value=0x42454553, common_name="bees tempus test p256"):
    """(cert_pem, key_pem) of a self-signed ECDSA P-256 certificate, for row 26 (a tempus/1 peer must present an Ed25519
    one). TEST ONLY: the key is a fixed number."""
    from cryptography.hazmat.primitives.asymmetric import ec
    key = ec.derive_private_key(private_value, ec.SECP256R1())
    return certificate_pem(key, common_name), _key_pem(key)


def rsa_certificate(common_name="bees tempus test rsa"):
    """(cert_pem, key_pem) of a self-signed RSA certificate, for row 26 (the engine's BEAM-distribution profile accepts
    RSA; a tempus/1 peer must not). TEST ONLY: the key's primes are the Mersenne primes 2^1279 - 1 and 2^2203 - 1, fixed
    numbers that are nobody's key."""
    from cryptography.hazmat.primitives.asymmetric import rsa
    p, q, e = 2 ** 1279 - 1, 2 ** 2203 - 1, 65537
    d = pow(e, -1, (p - 1) * (q - 1))
    numbers = rsa.RSAPrivateNumbers(p, q, d, d % (p - 1), d % (q - 1), pow(q, -1, p), rsa.RSAPublicNumbers(e, p * q))
    key = numbers.private_key()
    return certificate_pem(key, common_name), _key_pem(key)



# ---------------------------------------------------------------- identities from fixed seeds
def fixture_key(first):
    """TEST ONLY: the Ed25519 key whose seed is the 32 bytes first, first+1, ... (a key that belongs to nobody)."""
    return _ed25519().Ed25519PrivateKey.from_private_bytes(bytes(range(first, first + 32)))


def fixture_identity(first, typ, nbf, exp, addr=None, kid="k1", producer=None, sub=None):
    """TEST ONLY: the identity of seed first..first+31 with a token signed by `producer` (default: fixture_key(0), the
    test producer of tools/bees_tempus_fixtures.py). `sub` (default the identity's own key) makes a token for another key."""
    seed = bytes(range(first, first + 32))
    pub = _raw_public(_ed25519().Ed25519PrivateKey.from_private_bytes(seed))
    token = make_token(fixture_key(0) if producer is None else producer, kid, pub if sub is None else sub, typ, nbf, exp)
    return Identity(seed, token, addr)



# ---------------------------------------------------------------- deliberate misbehaviour (rows 12, 17, 18, 19 of 16.2)
def _stage(stage):
    if stage not in STAGES:
        raise ValueError("a stage is one of %s" % (STAGES,))
    return stage


def wrong_advert(body):
    """Row 12: this advert body is sent instead of the identity's own (build it with advert(descriptor(...)), or
    another identity's .advert() for the channel-binding case)."""
    return Misbehaviour(replace={"advert": raw_frame(body)})


def wrong_proof_other_nonce():
    """Row 12, wrong proof: a real signature by the right key over another nonce."""
    return Misbehaviour(proof=lambda me, nonce: me.prove(bytes(b ^ 0xFF for b in nonce)))


def wrong_proof_other_key(key):
    """Row 12, wrong proof: a signature over the right bytes by another Ed25519 key."""
    return Misbehaviour(proof=lambda me, nonce: key.sign(bytes(nonce) + me.token))


def wrong_proof_bytes(sig=bytes(64)):
    """Row 12, wrong proof: these bytes as the signature (64 of them, or another length for row 19)."""
    return Misbehaviour(proof=lambda me, nonce: sig)


def no_proof():
    """Row 12, no proof: the response is left out; the next frame (a dialer's request) arrives where it was due."""
    return Misbehaviour(skip=("response",))


def close_at(stage):
    """Row 18, closes early: close where this stage's frame was due. close_at("challenge") is closing after the advert."""
    return Misbehaviour(stop=(_stage(stage), None))


def close_after_advert():
    return close_at("challenge")


def silent_at(stage, seconds):
    """Row 18, silence: send nothing where this stage's frame was due, for that long, then close."""
    return Misbehaviour(stop=(_stage(stage), float(seconds)))


def wrong_frame_at(stage, body):
    """Rows 18 and 19: this body, properly framed, instead of the stage's frame."""
    return Misbehaviour(replace={_stage(stage): raw_frame(body)})


def oversize_frame_at(stage, size=FRAME_MAX + 1):
    """Row 19: a frame whose length prefix says `size` (above the ceiling), followed by that many zero bytes."""
    return Misbehaviour(replace={_stage(stage): struct.pack(">I", size) + bytes(size)})


def raw_bytes_at(stage, data):
    """Rows 18 and 19: these bytes as they are (no length prefix added) instead of the stage's frame."""
    return Misbehaviour(replace={_stage(stage): bytes(data)})


# A Listener's handler may return, instead of a reply body, one of these instructions (rows 17 and 18):
def stay_silent(seconds):
    return ("silent", float(seconds))


def send_raw(data):
    """These bytes as they are (frame them with raw_frame() or frame() when a frame is meant)."""
    return ("raw", bytes(data))


# Row 26, the TLS refusals: keyword arguments for dial() (or Listener), as  dial(..., **tls12_only()).
def tls12_only():
    return {"tls_version": "1.2"}


def other_alpn(name="h2"):
    """Another ALPN protocol; None offers no ALPN at all."""
    return {"alpn": name}


def no_certificate():
    return {"tls_cert": None}


def p256_cert():
    return {"tls_cert": p256_certificate()}


def rsa_cert():
    return {"tls_cert": rsa_certificate()}


