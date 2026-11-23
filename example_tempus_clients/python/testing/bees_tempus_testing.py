"""TEST SUPPORT for the Python TEMPUS extension. Nothing here is part of the extension, and an application must not
import this module.

The trials drive TEMPUS nodes through every behaviour a node has, including every refusal, and they need things no
application may have. All of them are here, and only here:

  - the two TEST-ONLY frames, tick and clock, that a test program's node understands (src/tempus_test/ on the Silica
    side); a production node refuses both as frames of no kind, and so does the extension's node;
  - token making: a token is made by the producer. The trials have a test producer whose key is a fixed seed;
  - keys from fixed seeds, and certificates made for them: keys that belong to nobody and that anyone can reproduce;
  - fixed nonces, so that a trial's bytes are the same on every run;
  - peers that misbehave on purpose (rows 12, 17, 18, 19 and 26 of design section 16.2): a wrong advert, a wrong or
    missing proof, a close or silence at any step, a wrong, oversize or raw frame, TLS 1.2, another ALPN name, no
    certificate, a certificate whose key is not Ed25519;
  - a dial() and a Listener that can do all of that and that report whatever the peer sent, checked or not, because a
    trial wants to see what a node really answers. (The extension's own dial and Listener, in bees_tempus_peer.py,
    refuse a reply that does not match its request and verify every entry.)
  - a Listener that takes the certificates of the peers expected to dial it as trust anchors (`trusted`), as the
    trials were written before the extension could accept a certificate it had never seen;
  - for the node (bees_tempus_node.py): a clock, a timer source and a random source that a test steps by hand.

It is built on the extension's own codec, admission checks and connection (bees_tempus_codec.py,
bees_tempus_admission.py, bees_tempus_peer.py). The trial tools import it under its old name, bees_tempus_client.
"""
import datetime
import os
import socket
import ssl
import struct
import tempfile
import threading
import time

import bees_tempus_codec as _codec
from bees_tempus_admission import Verifier as _Verifier, certificate_key, fingerprint  # noqa: F401
from bees_tempus_codec import (AGE_MAX, ENTRIES_MAX, FRAME_MAX, TYPES, Atom, Refused, _bin, _check_keys, _entries,  # noqa: F401
                               _typ, advert, call_frame, challenge, check_descriptor, descriptor, done, etf_decode,
                               etf_encode, frame, key_rotated, peer_id, read_token, response, sample, sample_reply,
                               shuffle, shuffle_reply)
from bees_tempus_peer import (ALPN, LINGER, OUTCOMES, Outcome, Wire as _Conn, _ed25519, _raw_public, _show,  # noqa: F401
                              _ssl_reason, result_value)

KINDS = _codec.KINDS[:-1] + ("tick", "clock", "done")
CLOCK_MAX = 2 ** 53
NO_TIME = -1             # a clock frame's ms or later: the clock could not be read
CLOCK_WAIT_MAX = 60000


# ---------------------------------------------------------------- tokens (the producer's work; TEST ONLY here)
def token_payload(kid, sub, typ, nbf, exp):
    """The bytes a producer signs: the ETF map of the five fields, times in seconds."""
    return etf_encode({Atom("kid"): kid.encode() if isinstance(kid, str) else kid, Atom("sub"): bytes(sub),
                       Atom("typ"): Atom(typ), Atom("nbf"): nbf, Atom("exp"): exp})


def make_token(signing_key, kid, sub, typ, nbf, exp):
    """A token signed with an Ed25519 private key object of the `cryptography` package."""
    payload = token_payload(kid, sub, typ, nbf, exp)
    return signing_key.sign(payload) + payload


def verify_token(token, producer_public_key, kid, now, skew=0):
    """Structure, the current kid, the producer's signature over the payload as received, and the time window."""
    fields, payload, sig = read_token(token)
    if fields["kid"] != (kid.encode() if isinstance(kid, str) else kid):
        raise Refused("key_rotated")
    try:
        producer_public_key.verify(sig, payload)
    except Exception:
        raise Refused("the signature is not the producer's")
    if not fields["nbf"] - skew <= now < fields["exp"] + skew:
        raise Refused("the token is not valid at this time")
    return fields


# ---------------------------------------------------------------- the two TEST-ONLY frames
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


def read_body(body, shuffle_length):
    """A body as (kind, fields): the extension's reader, and the two test-only frames beside it."""
    try:
        m = etf_decode(body)
    except Refused:
        return _codec.read_body(body, shuffle_length)
    t = m.get(Atom("t")) if isinstance(m, dict) else None
    kind = str(t) if isinstance(t, Atom) else ""
    if kind == "tick":
        _check_keys(m, ("t", "store"), kind)
        store = m[Atom("store")]
        if not isinstance(store, Atom) or store not in TYPES:
            raise Refused("store is not a peer type")
        return kind, {"store": str(store)}
    if kind == "clock":
        two = Atom("wait") in m
        _check_keys(m, ("t", "ms", "wait", "later") if two else ("t", "ms"), kind)
        ms = m[Atom("ms")]
        if not isinstance(ms, int) or not NO_TIME <= ms <= CLOCK_MAX:
            raise Refused("ms is not -1 (no time) or 0 to 2^53")
        if not two:
            return kind, {"ms": ms}
        wait, later = m[Atom("wait")], m[Atom("later")]
        if not isinstance(later, int) or not NO_TIME <= later <= CLOCK_MAX:
            raise Refused("later is not -1 (no time) or 0 to 2^53")
        if not isinstance(wait, int) or not 1 <= wait <= CLOCK_WAIT_MAX:
            raise Refused("wait is not 1 to 60000")
        return kind, {"ms": ms, "wait": wait, "later": later}
    return _codec.read_body(body, shuffle_length)


# ---------------------------------------------------------------- identities (TEST ONLY: keys from fixed seeds)
STAGES = ("advert", "challenge", "response", "request")     # the frames one side sends, in order (a listener: no request)
CERT_NOT_BEFORE = datetime.datetime(2026, 1, 1)             # as tools/bees_tempus_certs.py
CERT_NOT_AFTER = datetime.datetime(2046, 1, 1)
ON_PURPOSE = "closed by this side on purpose"



def _key_pem(key):
    from cryptography.hazmat.primitives import serialization
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())


def certificate_pem(key, common_name, serial=1, issuer_key=None, issuer_name=None):
    """A certificate over `key`, self-signed unless issuer_key is given; built exactly as tools/bees_tempus_certs.py
    builds its files (fixed dates and serial, so an Ed25519 certificate is the same bytes on every run). TEST ONLY."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.x509.oid import NameOID
    who = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    by = who if issuer_name is None else x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, issuer_name)])
    signer = key if issuer_key is None else issuer_key
    builder = (x509.CertificateBuilder().subject_name(who).issuer_name(by).public_key(key.public_key())
               .serial_number(serial).not_valid_before(CERT_NOT_BEFORE).not_valid_after(CERT_NOT_AFTER))
    if isinstance(signer, _ed25519().Ed25519PrivateKey):
        cert = builder.sign(signer, None)
    else:
        try:
            cert = builder.sign(signer, hashes.SHA256(), ecdsa_deterministic=True)
        except Exception:                                    # an older package or engine: a random ECDSA nonce
            cert = builder.sign(signer, hashes.SHA256())
    return cert.public_bytes(serialization.Encoding.PEM)


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



class Identity:
    """One TEST peer: an Ed25519 key from a seed given as bytes, pub, peer_id = SHA-512(pub), a self-signed certificate
    and its key as PEM, the token bytes and the listen address text "host:port" (None: a Listener advertises the
    address it bound). The extension's own Identity (bees_tempus_peer.py) takes key and certificate files and never a
    seed."""

    def __init__(self, seed, token, addr=None, cert_pem=None, common_name="bees tempus test client", serial=1):
        if len(seed) != 32:
            raise ValueError("an Ed25519 seed is 32 bytes")
        self.seed = bytes(seed)
        self.key = _ed25519().Ed25519PrivateKey.from_private_bytes(self.seed)
        self.pub = _raw_public(self.key)
        self.peer_id = peer_id(self.pub)
        self.token = bytes(token)
        self.addr = addr
        self.cert_pem = cert_pem if cert_pem is not None else certificate_pem(self.key, common_name, serial)
        self.key_pem = _key_pem(self.key)

    def descriptor(self, addr=None):
        addr = self.addr if addr is None else addr
        if addr is None:
            raise ValueError("this identity has no listen address (design OQ-15: every node has one)")
        return descriptor(self.peer_id, self.pub, addr, self.token)

    def advert(self, addr=None):
        return advert(self.descriptor(addr))

    def entry(self, age=0, addr=None):
        return (age, self.descriptor(addr))

    def prove(self, nonce, token=None):
        """The proof of possession: this key's signature over nonce || token."""
        return self.key.sign(bytes(nonce) + (self.token if token is None else token))

    def with_token(self, token):
        return Identity(self.seed, token, self.addr, self.cert_pem)

    def with_addr(self, addr):
        return Identity(self.seed, self.token, addr, self.cert_pem)

    def write_pem(self, directory):
        """Writes cert.pem and key.pem into `directory` (a tempfile directory, never the tree); returns the two paths."""
        return _write_pem(directory, self.cert_pem, self.key_pem)


def _write_pem(directory, cert_pem, key_pem):
    paths = os.path.join(directory, "cert.pem"), os.path.join(directory, "key.pem")
    for path, data in zip(paths, (cert_pem, key_pem)):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
    return paths


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


# ---------------------------------------------------------------- the verifier, as the trials construct it
class Verifier(_Verifier):
    """The extension's Verifier with the arguments the trials give it: the clock is a number or a function (never read
    from the machine here), the skew defaults to 0, `types` are the token types admitted, and the tempus whitelist
    rule is not applied unless a whitelist is given. Two reasons keep the wording the trials' recorded outputs have."""

    def __init__(self, producer_pub, kid, now, skew=0, types=TYPES, whitelist=None):
        _Verifier.__init__(self, producer_pub, kid, now, skew, whitelist)
        self.types = tuple(types)

    def check_descriptor(self, d, cert_pub=None, cert_fp=None):
        """The token's fields when the descriptor verifies; Refused(reason) otherwise, reason "key_rotated" for a token
        under another kid. cert_pub, when given, is the key of the peer's TLS certificate: the channel binding, checked
        first, as a node checks it."""
        check_descriptor(d)
        try:
            fields, _index = self.check_advert(d, d[Atom("pub")] if cert_pub is None else cert_pub, cert_fp)
        except Refused as why:
            if why.event == "binding_refused":
                raise Refused("the certificate's key is not the advert's pub", why.event)
            raise
        if fields["typ"] not in self.types:
            raise Refused("typ is not allowed")
        return fields


def read_any(body, shuffle_length=ENTRIES_MAX):
    """(kind, fields) of any body: a tempus/1 frame by read_body; a map whose `t` is no tempus/1 kind (TRUST's result,
    call, cast) with its fields as decoded, unchecked; else ("undecoded", {"why": reason}). PROVISIONAL for TRUST's
    frames: this reader has no tuples or floats, so a TRUST frame carrying them is "undecoded" (its bytes are still in
    the outcome's `body`); C3 decides what the client reads of them."""
    try:
        return read_body(body, shuffle_length)
    except Refused as why:
        first = str(why)
    try:
        m = etf_decode(body)
    except Refused:
        return "undecoded", {"why": first}
    t = m.get(Atom("t")) if isinstance(m, dict) else None
    if isinstance(t, Atom) and t not in KINDS:
        return str(t), {str(k): v for k, v in m.items() if k != "t"}
    return "undecoded", {"why": first}



# ---------------------------------------------------------------- C2: deliberate misbehaviour (rows 12, 17, 18, 19 of 16.2)
class Misbehaviour:
    """What one side does wrong on purpose during a connection. Stages are the frames a side sends, in order: "advert",
    "challenge", "response", and for a dialer "request".
      replace  stage -> bytes written INSTEAD of that stage's frame (already framed; the protocol then goes on)
      skip     stages at which nothing is sent (the protocol goes on, so the next frame arrives where this one was due)
      stop     (stage, None): close when that stage's frame is due; (stage, seconds): stay silent that long, then close
      proof    a function (identity, nonce) -> the 64 signature bytes sent as the proof of possession
    Build one with the functions below; several combine with `+`."""

    def __init__(self, replace=None, skip=(), stop=None, proof=None):
        self.replace, self.skip, self.stop, self.proof = dict(replace or {}), frozenset(skip), stop, proof

    def __add__(self, other):
        merged = dict(self.replace)
        merged.update(other.replace)
        return Misbehaviour(merged, self.skip | other.skip, other.stop or self.stop, other.proof or self.proof)


def _stage(stage):
    if stage not in STAGES:
        raise ValueError("a stage is one of %s" % (STAGES,))
    return stage


def raw_frame(body):
    """Any bytes with a 4-byte length in front, with no ceiling (frame() refuses a body above it)."""
    return struct.pack(">I", len(body)) + bytes(body)


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
CLOSE = ("close",)


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


# ---------------------------------------------------------------- C2: the connection
def _context(server, identity, tls_version, alpn, tls_cert, trusted):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER if server else ssl.PROTOCOL_TLS_CLIENT)
    version = {"1.3": ssl.TLSVersion.TLSv1_3, "1.2": ssl.TLSVersion.TLSv1_2}[tls_version]
    ctx.minimum_version = version
    ctx.maximum_version = version
    if alpn is not None:
        ctx.set_alpn_protocols([alpn])
    if tls_cert is not None:
        cert_pem, key_pem = (identity.cert_pem, identity.key_pem) if tls_cert == "own" else tls_cert
        with tempfile.TemporaryDirectory(prefix="bees_tempus_") as tmp:      # ssl loads from files only
            ctx.load_cert_chain(*_write_pem(tmp, cert_pem, key_pem))
    if server:
        ctx.verify_mode = ssl.CERT_REQUIRED          # the only way Python's ssl gives a server the client's certificate
        for pem in trusted:
            ctx.load_verify_locations(cadata=pem.decode() if isinstance(pem, bytes) else pem)
    else:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE              # the certificate is checked by certificate_key() and the binding
    return ctx



def _end(conn, what, stage, state, reason=""):
    conn.close()
    return Outcome(what, stage, reason, advert=state.get("advert"), typ=state.get("typ", ""))


def _read(conn, stage, state, want, shuffle_length):
    """The next frame, which must be one of the kinds `want`: (fields, None, kind), or (None, Outcome, "") when the
    connection ended or the frame was not acceptable (this side then closes without a reply, design section 5)."""
    what, value = conn.read()
    if what == "oversize":
        return None, _end(conn, "refused", stage, state, "a frame above the ceiling"), ""
    if what != "frame":
        return None, _end(conn, what, stage, state, value), ""
    try:
        kind, fields = read_body(value, shuffle_length)
    except Refused as why:
        return None, _end(conn, "refused", stage, state, str(why)), ""
    if kind not in want:
        return None, _end(conn, "refused", stage, state, "%s where %s was due" % (kind, " or ".join(want))), ""
    return fields, None, kind


def _emit(conn, mis, stage, state, body):
    """Sends the stage's frame, or does what the misbehaviour says for it. An Outcome when that ended the connection."""
    if mis is not None:
        if mis.stop is not None and mis.stop[0] == stage:
            if mis.stop[1] is None:
                return _end(conn, "closed", stage, state, ON_PURPOSE)
            seen = conn.watch(mis.stop[1])
            return _end(conn, seen, stage, state, "silent on purpose")
        if stage in mis.skip:
            return None
        if stage in mis.replace:
            conn.send(mis.replace[stage])
            return None
    conn.send(frame(body))
    return None


def _tls_checks(tls, state, alpn_wanted=ALPN):
    """After the handshake: the ALPN protocol and the peer's certificate. The certificate's raw key, or Refused."""
    if tls.selected_alpn_protocol() != alpn_wanted:
        raise Refused("the ALPN protocol is not tempus/1")
    der = tls.getpeercert(binary_form=True)
    if not der:
        raise Refused("the peer presented no certificate")
    return certificate_key(der)


def _admit(conn, me, addr, verifier, nonce, mis, cert_pub, state, shuffle_length):
    """Admission, the same at both ends (design sections 4 and 5). None when both directions passed, else the Outcome."""
    nonce = os.urandom(32) if nonce is None else bytes(nonce)
    out = _emit(conn, mis, "advert", state, me.advert(addr))
    if out:
        return out
    fields, out, _ = _read(conn, "advert", state, ("advert",), shuffle_length)
    if out:
        return out
    theirs = fields["d"]
    state["advert"] = theirs
    try:
        state["typ"] = verifier.check_descriptor(theirs, cert_pub)["typ"]
    except Refused as why:
        if str(why) == "key_rotated":                # the one exception to silence (ruling OQ-10): one frame, then close
            conn.send(frame(key_rotated(verifier.kid)))
        return _end(conn, "refused", "advert", state, str(why))
    out = _emit(conn, mis, "challenge", state, challenge(nonce))
    if out:
        return out
    fields, out, kind = _read(conn, "challenge", state, ("pop_challenge", "key_rotated"), shuffle_length)
    if out:
        return out
    if kind == "key_rotated":
        out = _end(conn, "key_rotated", "challenge", state)
        out.kid = fields["kid"]
        return out
    sig = mis.proof(me, fields["nonce"]) if mis is not None and mis.proof else me.prove(fields["nonce"])
    out = _emit(conn, mis, "response", state, etf_encode({Atom("t"): Atom("pop_response"), Atom("sig"): bytes(sig)}))
    if out:
        return out
    fields, out, _ = _read(conn, "response", state, ("pop_response",), shuffle_length)
    if out:
        return out
    try:
        verifier.check_proof(theirs[Atom("pub")], nonce, theirs[Atom("token")], fields["sig"])
    except Refused as why:
        return _end(conn, "refused", "response", state, str(why))
    return None


def _addr(text):
    host, _, port = text.rpartition(":")
    return host, int(port)


def dial(addr, identity, verifier, request, *, timeout=5.0, nonce=None, misbehaviour=None, shuffle_length=ENTRIES_MAX,
         tls_version="1.3", alpn=ALPN, tls_cert="own"):
    """Connect to the TEMPUS peer at "host:port", be admitted, send ONE request body (bytes: shuffle(), sample(), tick(),
    clock(), or TRUST's call or cast as bytes) and read one reply. Returns an Outcome; `timeout` is for the whole
    connection. identity.addr is the listen address this peer advertises. tls_version, alpn and tls_cert ("own", None for
    no certificate, or (cert_pem, key_pem)) are the row-26 switches."""
    ctx = _context(False, identity, tls_version, alpn, tls_cert, ())
    deadline = time.monotonic() + timeout
    state = {}
    try:
        sock = socket.create_connection(_addr(addr), timeout=timeout)
    except socket.timeout:
        return Outcome("timeout", "tls")
    except OSError:
        return Outcome("unreachable", "tls")
    try:
        sock.settimeout(max(0.001, deadline - time.monotonic()))
        tls = ctx.wrap_socket(sock)
    except socket.timeout:
        sock.close()
        return Outcome("timeout", "tls")
    except ssl.SSLError as exc:
        sock.close()
        return Outcome("tls_failed", "tls", _ssl_reason(exc))
    except OSError:
        sock.close()
        return Outcome("tls_failed", "tls", "closed during the handshake")
    conn = _Conn(tls, deadline)
    try:
        # a dialer that offers another ALPN on purpose goes on, to see what the peer does about it
        cert_pub = _tls_checks(tls, state, ALPN if alpn == ALPN else tls.selected_alpn_protocol())
    except Refused as why:
        return _end(conn, "refused", "tls", state, str(why))
    # In TLS 1.3 a dialer's handshake ends before the listener has judged the dialer's certificate: a listener's TLS
    # refusal (no certificate, an unknown one) shows as an alert on the first read, reported as tls_failed at "advert".
    out = _admit(conn, identity, None, verifier, nonce, misbehaviour, cert_pub, state, shuffle_length)
    if out:
        return out
    out = _emit(conn, misbehaviour, "request", state, request)
    if out:
        return out
    what, value = conn.read()
    if what == "oversize":
        return _end(conn, "refused", "reply", state, "a frame above the ceiling")
    if what != "frame":
        return _end(conn, what, "reply", state, value)
    kind, fields = read_any(value, shuffle_length)
    if kind == "undecoded":
        out = _end(conn, "refused", "reply", state, fields["why"])
    else:
        out = _end(conn, "reply", "done", state)
        out.kind, out.fields = kind, fields
    out.body = value
    return out


class Request:
    """What a Listener's handler is given: the request's kind and decoded fields (read_any), its bytes, the admitted
    peer's descriptor and token type, and the number of the connection (0 for the first accepted)."""
    __slots__ = ("kind", "fields", "body", "advert", "typ", "index")

    def __init__(self, kind, fields, body, advert, typ, index):
        self.kind, self.fields, self.body, self.advert, self.typ, self.index = kind, fields, body, advert, typ, index


class Listener:
    """The listening position of design 16.1: a thread accepts connections on host:port (port 0: the system picks one;
    .address says which), and each connection, in its own thread, is admitted, has ONE request read, and is answered by
    handler(Request), which returns the reply body (bytes), or None (nothing, close), or CLOSE, stay_silent(seconds),
    send_raw(bytes). Every connection ends as one Outcome, kept in accept order: outcomes(count) waits for them.

    trusted: the PEM certificates of the peers expected to dial (see the module text: Python's ssl gives a server no
    other way to receive a self-signed client certificate). nonce and misbehaviour may each be a value for every
    connection or a function of the connection's number."""

    def __init__(self, identity, verifier, handler, trusted, *, host="127.0.0.1", port=0, timeout=5.0, nonce=None,
                 misbehaviour=None, shuffle_length=ENTRIES_MAX, tls_version="1.3", alpn=ALPN, tls_cert="own"):
        self.identity, self.verifier, self.handler, self.timeout = identity, verifier, handler, timeout
        self.nonce, self.misbehaviour, self.shuffle_length = nonce, misbehaviour, shuffle_length
        self._ctx = _context(True, identity, tls_version, alpn, tls_cert, trusted)
        self._sock = socket.socket(socket.AF_INET6 if ":" in host else socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((host, port))
        self._sock.listen(64)
        self._sock.settimeout(0.05)
        self.port = self._sock.getsockname()[1]
        self.address = "%s:%d" % (host, self.port)
        self._done = {}
        self._changed = threading.Condition()
        self._stop = False
        self._threads = []
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self._accept, daemon=True)
        self._thread.start()
        return self

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.close()

    def close(self):
        """Stops accepting and waits for the connections in hand to end (each is bounded by `timeout`)."""
        self._stop = True
        if self._thread is not None:
            self._thread.join()
        for t in self._threads:
            t.join()
        self._sock.close()

    def outcomes(self, count=None, wait=10.0):
        """The Outcomes of the first `count` connections in accept order, waiting up to `wait` seconds for them (fewer
        when they did not all end in time); with no count, those ended so far."""
        until = time.monotonic() + wait
        with self._changed:
            while count is not None and not all(i in self._done for i in range(count)):
                left = until - time.monotonic()
                if left <= 0:
                    break
                self._changed.wait(left)
            return [self._done[i] for i in sorted(self._done) if count is None or i < count]

    def _accept(self):
        index = 0
        while not self._stop:
            try:
                sock, _ = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            t = threading.Thread(target=self._one, args=(sock, index), daemon=True)
            self._threads.append(t)
            t.start()
            index += 1

    def _one(self, sock, index):
        try:
            out = self._serve(sock, index)
        except Exception as exc:                     # a fault of this tool or of the handler, never the peer's doing: say so
            out = Outcome("closed", "tls", "internal error: %s: %s" % (type(exc).__name__, exc))
            try:
                sock.close()
            except OSError:
                pass
        with self._changed:
            self._done[index] = out
            self._changed.notify_all()

    def _per(self, value, index):
        return value(index) if callable(value) else value

    def _serve(self, sock, index):
        deadline = time.monotonic() + self.timeout
        state = {}
        try:
            sock.settimeout(self.timeout)
            tls = self._ctx.wrap_socket(sock, server_side=True)
        except socket.timeout:
            sock.close()
            return Outcome("timeout", "tls")
        except ssl.SSLError as exc:
            sock.close()
            return Outcome("tls_failed", "tls", _ssl_reason(exc))
        except OSError:
            sock.close()
            return Outcome("tls_failed", "tls", "closed during the handshake")
        conn = _Conn(tls, deadline)
        try:
            cert_pub = _tls_checks(tls, state)
        except Refused as why:
            return _end(conn, "refused", "tls", state, str(why))
        addr = self.identity.addr or self.address
        out = _admit(conn, self.identity, addr, self.verifier, self._per(self.nonce, index),
                     self._per(self.misbehaviour, index), cert_pub, state, self.shuffle_length)
        if out:
            return out
        what, value = conn.read()
        if what == "oversize":
            return _end(conn, "refused", "request", state, "a frame above the ceiling")
        if what != "frame":
            return _end(conn, what, "request", state, value)
        kind, fields = read_any(value, self.shuffle_length)
        if kind == "undecoded":
            out = _end(conn, "refused", "request", state, fields["why"])
            out.body = value
            return out
        answer = self.handler(Request(kind, fields, value, state["advert"], state["typ"], index))
        if answer is None:
            sent = "nothing"
        elif isinstance(answer, (bytes, bytearray)):
            conn.send(raw_frame(answer))
            sent = "reply"
        elif answer[0] == "close":
            sent = "close"
        elif answer[0] == "silent":
            conn.watch(answer[1])
            sent = "silent"
        elif answer[0] == "raw":
            conn.send(answer[1])
            sent = "raw"
        else:
            raise ValueError("the handler returned %r" % (answer,))
        out = _end(conn, "served", "done", state)
        out.kind, out.fields, out.body, out.sent = kind, fields, value, sent
        return out


# ---------------------------------------------------------------- the command line
def _dial_command(argv):
    import argparse
    ap = argparse.ArgumentParser(prog="bees_tempus_client.py dial")
    ap.add_argument("peer", help="HOST:PORT of the node")
    ap.add_argument("--seed", required=True, help="this client's Ed25519 seed, 64 hex digits (TEST ONLY keys)")
    ap.add_argument("--addr", required=True, help="the listen address this client advertises, HOST:PORT")
    ap.add_argument("--producer-pub", required=True, help="the current producer key, 64 hex digits")
    ap.add_argument("--kid", required=True)
    ap.add_argument("--now", required=True, type=int, help="the clock for token checks, whole seconds")
    ap.add_argument("--skew", type=int, default=0)
    ap.add_argument("--token", help="this client's token, hex")
    ap.add_argument("--test-token", help="TYP:NBF:EXP, signed with the TEST producer seed 00..1f under --kid")
    ap.add_argument("--timeout", type=float, default=5.0)
    ap.add_argument("--nonce", help="the challenge nonce, 64 hex digits (default: the system's random source)")
    ap.add_argument("--shuffle-length", type=int, default=ENTRIES_MAX)
    ap.add_argument("request", nargs="+", help="sample STORE N | tick STORE | clock MS | shuffle STORE | raw HEX")
    o = ap.parse_args(argv)
    seed = bytes.fromhex(o.seed)
    if (o.token is None) == (o.test_token is None):
        ap.error("give exactly one of --token and --test-token")
    if o.token is not None:
        token = bytes.fromhex(o.token)
    else:
        typ, nbf, exp = o.test_token.split(":")
        pub = _raw_public(_ed25519().Ed25519PrivateKey.from_private_bytes(seed))
        token = make_token(fixture_key(0), o.kid, pub, typ, int(nbf), int(exp))
    me = Identity(seed, token, o.addr)
    r = o.request
    if r[0] == "sample" and len(r) == 3:
        body = sample(r[1], int(r[2]))
    elif r[0] == "tick" and len(r) == 2:
        body = tick(r[1])
    elif r[0] == "clock" and len(r) == 2:
        body = clock(int(r[1]))
    elif r[0] == "shuffle" and len(r) == 2:
        body = shuffle(r[1], [me.entry(0)])
    elif r[0] == "raw" and len(r) == 2:
        body = bytes.fromhex(r[1])
    else:
        ap.error("the request is: sample STORE N | tick STORE | clock MS | shuffle STORE | raw HEX")
    verifier = Verifier(bytes.fromhex(o.producer_pub), o.kid, o.now, o.skew)
    out = dial(o.peer, me, verifier, body, timeout=o.timeout, nonce=bytes.fromhex(o.nonce) if o.nonce else None,
               shuffle_length=o.shuffle_length)
    print(out.line())
    return 0


def main(argv):
    if len(argv) >= 2 and argv[1] == "dial":
        return _dial_command(argv[2:])
    if len(argv) >= 3 and argv[1] == "read-hex":
        try:
            kind, fields = read_body(bytes.fromhex(argv[2]), int(argv[3]) if len(argv) > 3 else ENTRIES_MAX)
            print(kind, {k: (v if not isinstance(v, bytes) else v.hex()) for k, v in fields.items()})
        except Refused as why:
            print("refused:", why)
        return 0
    return 2


# ---------------------------------------------------------------- TEST ONLY: what a test gives a node in place of the machine
class TestClock:
    """A clock a test sets by hand: `value` is the reading in whole seconds, None when "the clock cannot be read"."""

    def __init__(self, value):
        self.value = value

    def read(self):
        return self.value


class TestTimers:
    """Timers that never run by themselves: a test fires them. fire(name) runs the oldest pending timer of that name
    ("clock", "tick tempus_edge", "join retry", ...) and answers whether there was one."""

    class _Handle:
        def __init__(self, owner, item):
            self.owner, self.item = owner, item

        def cancel(self):
            with self.owner.lock:
                if self.item in self.owner.pending:
                    self.owner.pending.remove(self.item)

    def __init__(self):
        self.pending = []
        self.lock = threading.Lock()

    def call_later(self, ms, function, name):
        item = (name, ms, function)
        with self.lock:
            self.pending.append(item)
        return TestTimers._Handle(self, item)

    def names(self):
        with self.lock:
            return [name for name, _ms, _f in self.pending]

    def delay(self, name):
        """the delay, in ms, the oldest pending timer of that name was armed with"""
        with self.lock:
            return next((ms for n, ms, _f in self.pending if n == name), None)

    def fire(self, name):
        with self.lock:
            item = next((it for it in self.pending if it[0] == name), None)
            if item is not None:
                self.pending.remove(item)
        if item is None:
            return False
        item[2]()
        return True


class TestRandom:
    """A random source that is not random: the same bytes on every run. Nonces are a counter's SHA-512; the draws of
    each store are the literal list, turned left by one place per set given, which is how a Silica test node's store
    front gives its store its draws (src/tempus/bees_tempus_node.silica.in, on_draws), so that a test node of the
    extension and a Silica test node given the same list make the same choices."""

    def __init__(self, literal=(0, 1, 2, 3), fails=False):
        self.literal, self.turn, self.count, self.fails = list(literal), {}, 0, fails
        self.lock = threading.Lock()

    def bytes(self, n):
        import hashlib
        if self.fails:
            return None
        with self.lock:
            self.count += 1
            out, k = b"", 0
            while len(out) < n:
                out += hashlib.sha512(b"bees tempus test nonce %d %d" % (self.count, k)).digest()
                k += 1
            return out[:n]

    def draws(self, store, purpose, n):
        if self.fails:
            return None
        j = self.turn.get(store, 0)
        self.turn[store] = j + 1
        k = j % len(self.literal)
        return self.literal[k:] + self.literal[:k]
