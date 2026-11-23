"""EXAMPLE ONLY, not for production. See ../../README.md.

The active part of the library: an ordinary TEMPUS peer over TCP and mutual TLS 1.3 (ALPN tempus/1), in both
positions. dial() connects, is admitted and sends ONE request; Listener accepts, is admitted, reads one request and
answers what a callback chooses. Admission on a connection, the same at both ends: each side sends its advert at once;
checks the peer's advert (Verifier) and that the key of the peer's TLS certificate is the advert's `pub` (the channel
binding of design section 4); sends a 32-byte challenge; answers the peer's challenge with its Ed25519 signature over
nonce || its own token; verifies the peer's answer. What happened is an Outcome, a plain value; expected peer behaviour
never raises.

TLS, exactly (Python's ssl has no verification callback, so the two positions differ):
  - dialing: the context does no chain verification (CERT_NONE). The handshake itself still proves that the peer holds
    the private key of the certificate it presented (the TLS 1.3 CertificateVerify, which OpenSSL always checks). This
    module then reads the certificate (getpeercert(binary_form=True)) and requires: an Ed25519 key, issuer equal to
    subject, and the certificate's signature verifying under its own key. Then the binding: that key == the advert's pub.
    Any TEMPUS node can be dialed; nothing about it has to be known in advance.
  - listening: Python's ssl only hands a server the client's certificate when it asks for one (CERT_REQUIRED), and then
    OpenSSL refuses every certificate that does not chain to a loaded trust anchor. So a Listener is given the
    certificates of the peers expected to dial it (`trusted`), loaded as trust anchors; a peer with any other certificate
    fails the handshake (tls_failed) and no frame is read. For an anchored certificate OpenSSL checks the handshake
    signature and the validity dates; this module then makes the same Ed25519, self-signed and binding checks as above.
    A Listener cannot accept a peer whose certificate it was not given. That is a limit of Python's ssl, not of tempus/1.
Certificate validity dates are not checked (ruling NQ-10: the producer token carries the validity window).

Ed25519 comes from the `cryptography` package and SHA-512 from hashlib; nothing else is needed and nothing is fetched.

The `misbehaviour` argument of dial() and Listener, and the instructions a Listener's handler may return in place of a
reply, are how the trials reach a node's refusals. The class that carries them is here because the connection code
consults it; the named ways to misbehave are in testing.py. A program that is not a trial passes none.
"""
import datetime
import hashlib
import os
import socket
import ssl
import struct
import tempfile
import threading
import time

from .codec import FRAME_MAX, Atom, Refused, etf_decode, etf_encode
from .frames import (ENTRIES_MAX, KINDS, TYPES, advert, challenge, check_descriptor, descriptor, frame, key_rotated, peer_id,
                     read_body, read_token)

ALPN = "tempus/1"
STAGES = ("advert", "challenge", "response", "request")     # the frames one side sends, in order (a listener: no request)
OUTCOMES = ("reply", "served", "key_rotated", "refused", "closed", "timeout", "tls_failed", "unreachable")
CERT_NOT_BEFORE = datetime.datetime(2026, 1, 1)             # as tools/bees_tempus_certs.py
CERT_NOT_AFTER = datetime.datetime(2046, 1, 1)
LINGER = 0.5              # seconds a closing side keeps reading, so that its last frame is not lost to a TCP reset
ON_PURPOSE = "closed by this side on purpose"


def _ed25519():
    from cryptography.hazmat.primitives.asymmetric import ed25519
    return ed25519


def _raw_public(key):
    from cryptography.hazmat.primitives import serialization
    return key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


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


def certificate_fingerprint(pem):
    """The SHA-512 of a certificate's DER, as lower-case hex: how a tempus whitelist names a certificate."""
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization
    cert = x509.load_pem_x509_certificate(pem if isinstance(pem, bytes) else pem.encode())
    return hashlib.sha512(cert.public_bytes(serialization.Encoding.DER)).hexdigest()


def certificate_key(der):
    """The raw 32-byte Ed25519 key of a certificate (DER), after checking what tempus/1 requires of it: an Ed25519 key,
    issuer equal to subject, and the signature verifying under its own key. Refused(reason) otherwise."""
    from cryptography import x509
    try:
        cert = x509.load_der_x509_certificate(der)
        key = cert.public_key()
    except Exception:
        raise Refused("the certificate cannot be read")
    if not isinstance(key, _ed25519().Ed25519PublicKey):
        raise Refused("the certificate's key is not Ed25519")
    try:
        if cert.issuer != cert.subject:
            raise ValueError
        key.verify(cert.signature, cert.tbs_certificate_bytes)
    except Exception:
        raise Refused("the certificate is not self-signed")
    from cryptography.hazmat.primitives import serialization
    return key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


class Identity:
    """One peer: Ed25519 seed and key, pub, peer_id = SHA-512(pub), a self-signed certificate and its key as PEM, the
    token bytes and the listen address text "host:port" (None: a Listener advertises the address it bound)."""

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

    @classmethod
    def from_pem(cls, cert_pem, key_pem, token, addr=None):
        """An identity from the PEM bytes of its certificate and of its private key (PKCS#8, not encrypted)."""
        from cryptography.hazmat.primitives import serialization
        key = serialization.load_pem_private_key(key_pem, None)
        seed = key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
        return cls(seed, token, addr, cert_pem)

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



# ---------------------------------------------------------------- C2: the verifier (design section 4)
class Verifier:
    """What this peer needs to check another: the current producer key (32 raw bytes) and its kid, the clock in whole
    seconds (a number, or a function of no arguments returning one: never read from the machine here), the skew, the
    token types it admits, and the tempus whitelist: the fingerprints (certificate_fingerprint) of the certificates of the
    bridges and sentinels this peer accepts. With whitelist None the whitelist rule is not applied at all (the trials'
    clients, which meet nodes of every type on purpose); a peer that takes part in a network passes a set, which may be
    empty: it then accepts no bridge and no sentinel on a connection."""

    def __init__(self, producer_pub, kid, now, skew=0, types=TYPES, whitelist=None):
        self.whitelist = None if whitelist is None else frozenset(whitelist)
        self.producer_pub = bytes(producer_pub)
        self.producer = _ed25519().Ed25519PublicKey.from_public_bytes(self.producer_pub)
        self.kid = kid.encode() if isinstance(kid, str) else bytes(kid)
        self.now, self.skew, self.types = now, skew, tuple(types)

    def clock(self):
        return self.now() if callable(self.now) else self.now

    def check_descriptor(self, d, cert_pub=None, cert_fp=None, store=None):
        """The token's fields when the descriptor verifies; Refused(reason) otherwise, reason "key_rotated" for a token
        under another kid (checked before the rest of the token: a signature under a key this verifier does not hold
        cannot be judged).
        cert_pub, when given, is the key of the peer's TLS certificate: the channel binding. It is judged first, before
        anything of the token, as a node does: a peer whose advert is not bound to its certificate is told nothing
        about the token it presented, not even that its kid is old. cert_fp, when given with
        a whitelist, is that certificate's fingerprint: a token that says bridge or sentinel needs a certificate of the
        whitelist, and a certificate of the whitelist needs such a token. store, when given, is the store an entry was
        received for: the token's type must be that store's type."""
        check_descriptor(d)
        pid, pub, token = d[Atom("id")], d[Atom("pub")], d[Atom("token")]
        if cert_pub is not None and cert_pub != pub:
            raise Refused("the certificate's key is not the advert's pub")
        fields, payload, sig = read_token(token)
        now = self.clock()
        if fields["kid"] != self.kid:
            raise Refused("key_rotated")
        if now < fields["nbf"] - self.skew:
            raise Refused("the token is not valid yet")
        if now >= fields["exp"] + self.skew:
            raise Refused("the token has expired")
        if fields["sub"] != pub:
            raise Refused("sub is not the peer's key")
        if fields["typ"] not in self.types:
            raise Refused("typ is not allowed")
        if store is not None and fields["typ"] != store:
            raise Refused("typ is not the store's type")
        if self.whitelist is not None and cert_fp is not None:
            listed = cert_fp in self.whitelist
            special = fields["typ"] in ("tempus_bridge", "tempus_sentinel")
            if special and not listed:
                raise Refused("a %s whose certificate is not in the tempus whitelist" % fields["typ"])
            if listed and not special:
                raise Refused("a certificate of the tempus whitelist with a %s token" % fields["typ"])
        if peer_id(pub) != pid:
            raise Refused("id is not the SHA-512 of pub")
        try:
            self.producer.verify(sig, payload)
        except Exception:
            raise Refused("the signature does not verify")
        return fields

    def check_entry(self, d, store):
        """An entry received in a shuffle or sample frame of the named store: verified without contact."""
        return self.check_descriptor(d, store=store)

    def check_proof(self, pub, nonce, token, sig):
        try:
            _ed25519().Ed25519PublicKey.from_public_bytes(pub).verify(sig, bytes(nonce) + token)
        except Exception:
            raise Refused("the proof of possession does not verify")


# ---------------------------------------------------------------- C2: outcomes
def _show(v):
    if isinstance(v, (bytes, bytearray)):
        return bytes(v).hex()
    if isinstance(v, dict):                                   # a descriptor, or a map of a frame this client does not know
        if Atom("id") in v and isinstance(v[Atom("id")], bytes):
            return v[Atom("id")][:8].hex()
        return "{" + ",".join("%s=%s" % (k, _show(v[k])) for k in sorted(v)) + "}"
    if isinstance(v, tuple) and len(v) == 2 and isinstance(v[1], dict):   # an entry: (age, descriptor)
        return "%d:%s" % (v[0], _show(v[1]))
    if isinstance(v, (list, tuple)):
        return "[" + ",".join(_show(x) for x in v) + "]"
    return str(v)


class Outcome:
    """What happened on one connection, as plain values.

    what    "reply"        dialing: a reply frame arrived (kind, fields, body)
            "served"       listening: the peer was admitted and its request read (kind, fields, body); `sent` says what
                           went back: "reply", "close", "silent", "raw" or "nothing"
            "key_rotated"  the peer answered this side's advert with key_rotated; `kid` is the kid it named
            "refused"      THIS side refused the peer or its frame; `reason` says why ("key_rotated": this side sent the frame)
            "closed"       the connection closed before the exchange was complete
            "timeout"      nothing came within the time allowed
            "tls_failed"   no tempus/1 TLS connection: the handshake failed, or a TLS alert came before any frame
            "unreachable"  dialing: no TCP connection
    stage   where it ended: "tls", "advert", "challenge", "response", "request", "reply", "done"
    advert  the peer's descriptor, once its advert was read (also when it was then refused)
    typ     the type in the peer's token, once the advert verified
    """
    __slots__ = ("what", "stage", "reason", "kind", "fields", "body", "advert", "typ", "kid", "sent")

    def __init__(self, what, stage, reason="", kind="", fields=None, body=b"", advert=None, typ="", kid=None, sent=""):
        assert what in OUTCOMES
        self.what, self.stage, self.reason, self.kind, self.fields, self.body = what, stage, reason, kind, fields, body
        self.advert, self.typ, self.kid, self.sent = advert, typ, kid, sent

    def line(self):
        """One deterministic line: nothing of the wall clock, no object addresses."""
        parts = [self.what]
        if self.what not in ("reply", "served"):
            parts.append("at=" + self.stage)
        if self.kind:
            parts.append(self.kind)
            parts += ["%s=%s" % (k, _show(self.fields[k])) for k in sorted(self.fields or {})]
        if self.sent:
            parts.append("sent=" + self.sent)
        if self.kid is not None:
            parts.append("kid=" + self.kid.hex())
        if self.advert is not None:
            parts.append("peer=" + _show(self.advert))
        if self.typ:
            parts.append("typ=" + self.typ)
        if self.reason:
            parts.append('reason="%s"' % self.reason)
        return " ".join(parts)

    __repr__ = line


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



def raw_frame(body):
    """Any bytes with a 4-byte length in front, with no ceiling (frame() refuses a body above it)."""
    return struct.pack(">I", len(body)) + bytes(body)


# A Listener's handler may return, instead of a reply body, this instruction: close with no reply.
CLOSE = ("close",)


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


class _Conn:
    """A TLS connection with one deadline for all of it; reads and writes answer with values, not exceptions."""

    def __init__(self, tls, deadline):
        self.tls, self.deadline, self.frames_read, self.open = tls, deadline, 0, True

    def _arm(self, deadline=None):
        left = (self.deadline if deadline is None else min(deadline, self.deadline)) - time.monotonic()
        if left <= 0:
            raise socket.timeout()
        self.tls.settimeout(left)

    def send(self, data):
        """True when the bytes were handed to the socket. A failure is not reported here: the next read says what happened."""
        try:
            self._arm()
            self.tls.sendall(data)
            return True
        except (OSError, ssl.SSLError):
            return False

    def _fail(self, exc):
        if isinstance(exc, socket.timeout):
            return "timeout", ""
        if isinstance(exc, (ssl.SSLZeroReturnError, ssl.SSLEOFError)) or not isinstance(exc, ssl.SSLError):
            return "closed", ""
        if self.frames_read == 0:
            return "tls_failed", _ssl_reason(exc)
        return "closed", _ssl_reason(exc)

    def _exact(self, n, deadline=None):
        data = b""
        while len(data) < n:
            self._arm(deadline)
            chunk = self.tls.recv(n - len(data))
            if not chunk:
                raise ConnectionResetError()
            data += chunk
        return data

    def read(self):
        """("frame", body) | ("oversize", "") | ("closed", why) | ("timeout", "") | ("tls_failed", why)"""
        try:
            size = struct.unpack(">I", self._exact(4))[0]
            if size > FRAME_MAX:
                return "oversize", ""
            body = self._exact(size)
        except (OSError, ssl.SSLError) as exc:
            return self._fail(exc)
        self.frames_read += 1
        return "frame", body

    def watch(self, seconds):
        """Send nothing and read for that long: "closed" when the peer closed in that time, else "timeout"."""
        until = time.monotonic() + seconds
        try:
            while True:
                self._arm(until)
                if not self.tls.recv(4096):
                    return "closed"
        except socket.timeout:
            return "timeout"
        except (OSError, ssl.SSLError):
            return "closed"

    def close(self):
        """Close so that what was last written arrives: TLS close_notify, TCP end of writing, then read to the peer's
        end (at most LINGER seconds). Closing with unread bytes would send a TCP reset, which can destroy a frame
        (a key_rotated, a reply) the peer has not yet read."""
        if not self.open:
            return
        self.open = False
        try:
            plain = socket.socket(fileno=os.dup(self.tls.fileno()))
        except OSError:
            plain = None
        try:
            self.tls.settimeout(0)
            self.tls.unwrap()                        # writes close_notify; does not wait for the peer's
        except (OSError, ssl.SSLError, ValueError):
            pass
        if plain is not None:
            try:
                plain.shutdown(socket.SHUT_WR)
                until = time.monotonic() + LINGER
                while True:
                    left = until - time.monotonic()
                    if left <= 0:
                        break
                    plain.settimeout(left)
                    if not plain.recv(65536):
                        break
            except OSError:
                pass
            plain.close()
        try:
            self.tls.close()
        except OSError:
            pass


def _ssl_reason(exc):
    return getattr(exc, "reason", None) or type(exc).__name__


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
    state["cert_fp"] = hashlib.sha512(der).hexdigest()
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
        state["typ"] = verifier.check_descriptor(theirs, cert_pub, state.get("cert_fp"))["typ"]
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
                 misbehaviour=None, shuffle_length=ENTRIES_MAX, tls_version="1.3", alpn=ALPN, tls_cert="own", keep=True):
        self.identity, self.verifier, self.handler, self.timeout = identity, verifier, handler, timeout
        self.keep = keep                             # False: no Outcome is kept (a peer that runs for a long time)
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
            if not self.keep:
                self._threads = [x for x in self._threads if x.is_alive()]
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
        if not self.keep:
            return
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

