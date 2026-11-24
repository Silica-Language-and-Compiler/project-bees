"""The Python TEMPUS extension: one tempus/1 connection (development-plan/tempus-design.md sections 4, 5 and 8).

TCP, mutual TLS 1.3 with the tempus/1 profile, frames, and admission in both positions. dial() connects, is admitted,
sends ONE request and reads and checks its one reply. Listener accepts, is admitted, reads one request and answers what
a handler chooses. The node (bees_tempus_node.py) is built on the same parts.

TLS, exactly, with Python's ssl module:
  - TLS 1.3 only, ALPN tempus/1, this peer's own certificate (self-signed over its Ed25519 identity key), and the
    peer's certificate required in both positions.
  - The key exchange group must be X25519MLKEM768. Python's ssl has no call to choose groups before Python 3.15
    (SSLContext.set_groups) and none to ask which group a connection negotiated, so this module reads the group out of
    the ServerHello message with the context's message callback and refuses, after the handshake, any connection that
    did not negotiate X25519MLKEM768 (code point 4588). Where set_groups exists it is also called, so that no other
    group is offered. Without either, no connection is made.
  - The cipher suite must be TLS_AES_256_GCM_SHA384 or TLS_CHACHA20_POLY1305_SHA256. Python's ssl cannot take the
    third TLS 1.3 suite out of its offer; a connection that negotiated it is refused after the handshake.
  - Dialing: the context does no chain verification. The handshake itself proves that the peer holds the private key of
    the certificate it presented. This module then requires an Ed25519 key, issuer equal to subject and the
    certificate's signature verifying under its own key.
  - Accepting: Python's ssl gives a server the client's certificate only when it verifies it against trust anchors, and
    has no verification callback. A TEMPUS node must accept a certificate it has never seen (an edge is not known in
    advance). So each accepted connection gets a context of its own, and when the client's Certificate message is read
    (the same message callback) that certificate is loaded into that context as its only trust anchor, with the check
    of validity dates turned off (ruling NQ-10). OpenSSL then checks the handshake signature against it, and this
    module makes the same checks as when dialing. The message callback is `SSLContext._msg_callback`, which Python
    provides for debugging and does not document as stable: see README.md, "Using it carefully".
Certificate validity dates are not checked (ruling NQ-10: the producer's token carries the validity window).

No private key is logged or sent. The key file is read by the TLS library and once by this module, which keeps the key
as an object of the `cryptography` package and never as bytes.
"""
import os
import socket
import ssl
import struct
import threading
import time

from bees_tempus_admission import certificate_key, fingerprint
from bees_tempus_codec import (Atom, ENTRIES_MAX, FRAME_MAX, Refused, advert, challenge, descriptor, frame, key_rotated,
                               kind_of, peer_id, read_any, read_body, response)

ALPN = "tempus/1"
GROUP_ID = 0x11EC                      # X25519MLKEM768
GROUP_NAME = "X25519MLKEM768"
SUITES = ("TLS_AES_256_GCM_SHA384", "TLS_CHACHA20_POLY1305_SHA256")
OUTCOMES = ("reply", "served", "key_rotated", "refused", "closed", "timeout", "tls_failed", "unreachable")
LINGER = 0.5              # seconds a closing side keeps reading, so that its last frame is not lost to a TCP reset
_NO_CHECK_TIME = 0x200000  # OpenSSL's X509_V_FLAG_NO_CHECK_TIME; Python's ssl has no name for it


def _ed25519():
    from cryptography.hazmat.primitives.asymmetric import ed25519
    return ed25519


def _raw_public(key):
    from cryptography.hazmat.primitives import serialization
    return key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


class Identity:
    """One peer's TEMPUS identity: its Ed25519 key, its certificate, its token and the address it listens on.

      certfile, keyfile   paths of the certificate (PEM, self-signed over the identity key) and of its private key
                          (PEM, PKCS8, not encrypted). The TLS library reads both files itself.
      token               the producer's token for this key, as the producer gave it
      addr                the listen address this peer advertises, "host:port"

    The key file is read once here, to sign proofs of possession. Nothing is refused silently: a key that is not
    Ed25519, or a certificate over another key, raises ValueError."""

    def __init__(self, certfile, keyfile, token, addr):
        from cryptography import x509
        from cryptography.hazmat.primitives import serialization
        with open(keyfile, "rb") as f:
            key = serialization.load_pem_private_key(f.read(), password=None)
        if not isinstance(key, _ed25519().Ed25519PrivateKey):
            raise ValueError("the identity key is not an Ed25519 key")
        with open(certfile, "rb") as f:
            cert = x509.load_pem_x509_certificate(f.read())
        self.cert_der = cert.public_bytes(serialization.Encoding.DER)
        self.certfile, self.keyfile = certfile, keyfile
        self.key = key
        self.pub = _raw_public(key)
        if certificate_key(self.cert_der) != self.pub:
            raise ValueError("the identity certificate is not over the identity key")
        self.peer_id = peer_id(self.pub)
        self.token = bytes(token)
        self.addr = addr

    def descriptor(self, addr=None):
        addr = self.addr if addr is None else addr
        if addr is None:
            raise ValueError("this identity has no listen address (design OQ-15: every peer has one)")
        return descriptor(self.peer_id, self.pub, addr, self.token)

    def advert(self, addr=None):
        return advert(self.descriptor(addr))

    def entry(self, age=0, addr=None):
        return (age, self.descriptor(addr))

    def prove(self, nonce):
        """The proof of possession: this key's signature over nonce || this peer's own token."""
        return self.key.sign(bytes(nonce) + self.token)


# ---------------------------------------------------------------- outcomes (plain values)
def _show(v):
    if isinstance(v, (bytes, bytearray)):
        return bytes(v).hex()
    if isinstance(v, dict):                                   # a descriptor, or a map of a frame this side does not know
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
                           went back
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


def result_value(out):
    """the value of a TRUST result an Outcome carries, or None when the reply is no result"""
    return out.fields.get("value") if out.kind == "result" else None


# ---------------------------------------------------------------- TLS
class TlsRefused(Exception):
    """No tempus/1 TLS connection. `event` and `what` are the node's audit event and text for it."""

    def __init__(self, event, what):
        Exception.__init__(self, what)
        self.event, self.what = event, what


_TLS_TEXT = {
    "tls_handshake_failed": "the TLS 1.3 handshake failed (alert, version, group, suite or signature outside the tempus/1 profile)",
    "tls_verify_failed": "the peer certificate did not pass the engine's check",
    "no_certificate": "the peer presented no certificate",
    "alpn_mismatch": "the peer did not agree on ALPN tempus/1",
    "tls_group_refused": "the connection did not negotiate X25519MLKEM768, the only key exchange of the tempus/1 profile",
    "tempus_cert_key": "the peer certificate's key is not Ed25519",
}


class _Watch:
    """What the TLS library's message callback shows of one handshake: the key exchange group the ServerHello names
    and, for a server, the client's certificate, which is made the connection's own trust anchor as it is read."""

    def __init__(self, server):
        self.server, self.group = server, None

    def __call__(self, conn, direction, version, content_type, msg_type, data):
        try:
            if int(content_type) != 22:                       # handshake messages only
                return
            kind = int(msg_type)
            if kind == 2:
                self.group = _server_hello_group(bytes(data))
            elif kind == 11 and self.server and direction == "read":
                der = _first_certificate(bytes(data))
                if der:
                    conn.context.load_verify_locations(cadata=der)
        except Exception:                                     # a message this reader cannot follow: the handshake's
            pass                                              # own checks and the checks after it decide


def _server_hello_group(msg):
    """the group of a ServerHello's key_share extension, or None"""
    if len(msg) < 39 or msg[0] != 2:
        return None
    p = 4 + 2 + 32
    p += 1 + msg[p]                       # the session id
    p += 2 + 1                            # the cipher suite and the compression method
    if p + 2 > len(msg):
        return None
    end = p + 2 + struct.unpack(">H", msg[p:p + 2])[0]
    p += 2
    while p + 4 <= min(end, len(msg)):
        ext, size = struct.unpack(">HH", msg[p:p + 4])
        if ext == 51 and size >= 2:
            return struct.unpack(">H", msg[p + 4:p + 6])[0]
        p += 4 + size
    return None


def _first_certificate(msg):
    """the DER bytes of the first certificate of a TLS 1.3 Certificate message, or b"" """
    if len(msg) < 8 or msg[0] != 11:
        return b""
    p = 4
    p += 1 + msg[p]                       # the certificate request context
    p += 3                                # the length of the list
    if p + 3 > len(msg):
        return b""
    size = int.from_bytes(msg[p:p + 3], "big")
    return msg[p + 3:p + 3 + size]


def tls_available():
    """"" when this Python can make tempus/1 connections in both positions, else what is missing."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    if not hasattr(ctx, "_msg_callback"):
        return "this Python's ssl module has no message callback (SSLContext._msg_callback)"
    if not ssl.HAS_TLSv1_3 or not ssl.HAS_ALPN:
        return "this Python's ssl module has no TLS 1.3 or no ALPN"
    return ""


def _context(server, identity, watch):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER if server else ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    ctx.maximum_version = ssl.TLSVersion.TLSv1_3
    ctx.set_alpn_protocols([ALPN])
    if hasattr(ctx, "set_groups"):                            # Python 3.15 and later: offer and accept no other group
        ctx.set_groups(GROUP_NAME)
    ctx.load_cert_chain(identity.certfile, identity.keyfile)
    ctx._msg_callback = watch
    if server:
        ctx.verify_mode = ssl.CERT_REQUIRED                   # the only way Python's ssl gives a server the client's certificate
        ctx.verify_flags = ssl.VerifyFlags(int(ctx.verify_flags) | _NO_CHECK_TIME)
    else:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE                       # the certificate is checked by certificate_key() and the binding
    return ctx


class Link:
    """An open tempus/1 TLS connection after every check of the profile: the TLS object, the peer certificate's
    Ed25519 key and fingerprint, and the suite."""
    __slots__ = ("tls", "cert_pub", "cert_fp", "suite", "server")

    def __init__(self, tls, cert_pub, cert_fp, suite, server):
        self.tls, self.cert_pub, self.cert_fp, self.suite, self.server = tls, cert_pub, cert_fp, suite, server

    def established(self):
        """the text of the node's tls_established audit line"""
        return "TLSv1.3 %s %s alpn tempus/1, mutual, as %s" % (GROUP_NAME, self.suite, "server" if self.server else "client")


def tls_open(sock, identity, server, deadline):
    """The TLS handshake of a tempus/1 connection on a connected TCP socket, and the checks a finished handshake must
    pass, in the node's order: ALPN tempus/1, a peer certificate, the group X25519MLKEM768, a suite of the profile, an
    Ed25519 certificate key. Returns a Link; raises TlsRefused (the socket is then closed)."""
    watch = _Watch(server)
    side = "server" if server else "client"

    def refused(event, text=None):
        try:
            sock.close()
        except OSError:
            pass
        return TlsRefused("tls_verify_failed" if event == "no_certificate" else event,
                          "%s, as %s" % (text or _TLS_TEXT[event], side))
    try:
        ctx = _context(server, identity, watch)
        sock.settimeout(max(0.001, deadline - time.monotonic()))
        tls = ctx.wrap_socket(sock, server_side=server)
    except socket.timeout:
        raise refused("timeout", "stage tls_handshake")
    except ssl.SSLError as exc:
        reason = getattr(exc, "reason", "") or ""
        if "PEER_DID_NOT_RETURN_A_CERTIFICATE" in reason:
            raise refused("no_certificate")
        if isinstance(exc, ssl.SSLCertVerificationError) or "CERTIFICATE_VERIFY_FAILED" in reason:
            raise refused("tls_verify_failed")
        if isinstance(exc, (ssl.SSLZeroReturnError, ssl.SSLEOFError)):
            raise refused("closed_by_peer", "stage tls_handshake")
        raise refused("tls_handshake_failed")
    except OSError:
        raise refused("closed_by_peer", "stage tls_handshake")

    def late(event):
        try:
            tls.close()
        except OSError:
            pass
        return TlsRefused("tls_verify_failed" if event == "no_certificate" else event, "%s, as %s" % (_TLS_TEXT[event], side))
    if tls.selected_alpn_protocol() != ALPN:
        raise late("alpn_mismatch")
    der = tls.getpeercert(binary_form=True)
    if not der:
        raise late("no_certificate")
    suite = (tls.cipher() or ("",))[0]
    if watch.group != GROUP_ID or suite not in SUITES:
        raise late("tls_group_refused" if watch.group != GROUP_ID else "tls_handshake_failed")
    try:
        cert_pub = certificate_key(der)
    except Refused as why:
        raise late(why.event or "tls_verify_failed")
    return Link(tls, cert_pub, fingerprint(der), suite, server)


# ---------------------------------------------------------------- frames on a connection
class Wire:
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
        """("frame", body) | ("oversize", "") | ("closed", why) | ("timeout", "") | ("tls_failed", why). A frame above
        the ceiling is refused from its length alone: no byte of its body is read."""
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

    def drain(self):
        """Read and drop what the peer still sends, until it closes or the connection's bound passes (after a
        key_rotated frame: closing with the peer's bytes unread could reset the connection and destroy the frame)."""
        return self.watch(max(0.0, self.deadline - time.monotonic()))

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


# ---------------------------------------------------------------- admission on a connection
class Ended(Exception):
    """A connection ended before the peer was admitted, or a frame was refused. event and what are the node's audit
    event and text; phase is where ("advert", "challenge", "response", "request", "reply"); peer is the peer's
    descriptor once its advert was read; kid is the kid a key_rotated frame of the PEER named (event
    "key_rotated_received"); proved says whether the peer's token had been verified when it ended."""

    def __init__(self, event, what, phase, peer=None, kid=None, proved=False):
        Exception.__init__(self, what)
        self.event, self.what, self.phase, self.peer, self.kid, self.proved = event, what, phase, peer, kid, proved


ROTATED_TEXT = "the peer's token is under another kid; it was told the current one"


class Admitted:
    """An admitted peer: its descriptor, the fields of its token, and its certificate's index in the whitelist (-1)."""
    __slots__ = ("d", "fields", "index")

    def __init__(self, d, fields, index):
        self.d, self.fields, self.index = d, fields, index

    @property
    def typ(self):
        return self.fields["typ"]


def read_frame(wire, phase, peer=None, proved=False):
    """the next frame's body, or Ended: a frame above the ceiling (protocol_error), a close (closed_by_peer), the
    connection's bound (timeout)"""
    what, value = wire.read()
    if what == "frame":
        return value
    if what == "oversize":
        raise Ended("protocol_error", "frame refused before decoding: too_large", phase, peer, proved=proved)
    if what == "timeout":
        raise Ended("timeout", "stage " + phase, phase, peer, proved=proved)
    raise Ended("closed_by_peer", "stage " + phase, phase, peer, proved=proved)


def _decoded(body, want, count, wrong, event, phase, peer, proved=False):
    """the fields of a body that must be of kind `want`"""
    try:
        kind, fields = read_body(body, count)
    except Refused as why:
        text = str(why) if kind_of(body) == want else wrong
        raise Ended(event, text, phase, peer, proved=proved)
    if kind != want:
        raise Ended(event, wrong, phase, peer, proved=proved)
    return fields


def admit(wire, link, identity, verifier, nonce, rotated=None):
    """Admission, the same at both ends (design sections 4 and 5), in the node's order: this side's advert at once; the
    peer's advert, checked (a token under another kid is answered with the one key_rotated frame, and what the peer
    still sends is then read and dropped until it closes); this side's challenge; the peer's challenge (or its
    key_rotated), answered with this side's proof; the peer's response, verified. Returns Admitted or raises Ended.
    nonce: 32 bytes from a secure random source, fresh for this connection. rotated, when given, is called with the
    peer's descriptor when the key_rotated frame has been sent, before the wait for the peer's close."""
    if len(nonce) != 32:
        raise ValueError("a nonce is 32 bytes")
    wire.send(frame(identity.advert()))
    body = read_frame(wire, "advert")
    theirs = _decoded(body, "advert", ENTRIES_MAX, "the first frame is not an advert", "protocol_error", "advert", None)["d"]
    try:
        fields, index = verifier.check_advert(theirs, link.cert_pub, link.cert_fp)
    except Refused as why:
        if why.event == "key_rotated":
            wire.send(frame(key_rotated(verifier.kid)))
            if rotated is not None:
                rotated(theirs)
            wire.drain()
            raise Ended("key_rotated", ROTATED_TEXT, "advert", theirs)
        raise Ended(why.event or "admission_refused", str(why), "advert", theirs)
    wire.send(frame(challenge(nonce)))
    body = read_frame(wire, "challenge", theirs, True)
    if kind_of(body) == "key_rotated":
        kid = _decoded(body, "key_rotated", ENTRIES_MAX, "a challenge was expected", "protocol_error", "challenge", theirs, True)["kid"]
        raise Ended("key_rotated_received", "the peer says this node's token is under another kid than its current one",
                    "challenge", theirs, kid, True)
    theirs_nonce = _decoded(body, "pop_challenge", ENTRIES_MAX, "a challenge was expected", "protocol_error", "challenge", theirs, True)["nonce"]
    wire.send(frame(response(identity.prove(theirs_nonce))))
    body = read_frame(wire, "response", theirs, True)
    sig = _decoded(body, "pop_response", ENTRIES_MAX, "a response was expected", "pop_failed", "response", theirs, True)["sig"]
    try:
        verifier.check_proof(theirs[Atom("pub")], nonce, theirs[Atom("token")], sig)
    except Refused as why:
        raise Ended("pop_failed", str(why), "response", theirs, proved=True)
    return Admitted(theirs, fields, index)


def check_reply(verifier, request, body, count):
    """The reply to a request this side sent: (kind, fields), or Refused. A reply must be the reply of its request:
      a shuffle        a shuffle_reply for the same store, at most `count` entries (the shuffle length)
      a sample of n    a sample_reply for the same store, at most n entries
      a call           a result with the same req_id (a cast has no reply at all)
    and every entry of it must verify (Verifier.check_entries) before any is used. `request` is the body sent."""
    try:
        asked, afields = read_any(request, ENTRIES_MAX)
    except Refused:
        asked, afields = "undecoded", {}
    kind, fields = read_any(body, ENTRIES_MAX)
    if kind == "undecoded":
        raise Refused(fields["why"], "protocol_error")
    want = {"shuffle": "shuffle_reply", "sample": "sample_reply", "call": "result"}.get(asked)
    if want is None or kind != want:
        raise Refused("the reply is not the reply of the request" if want else "the request has no reply", "protocol_error")
    if kind == "result":
        if fields.get("req_id") != afields.get("req_id"):
            raise Refused("the result is for another req_id", "protocol_error")
        return kind, fields
    if fields["store"] != afields["store"]:
        raise Refused("the reply is for another store", "protocol_error")
    most = min(count, afields["n"]) if asked == "sample" else count
    if len(fields["entries"]) > most:
        raise Refused("more entries than were asked for" if asked == "sample" and len(fields["entries"]) <= count
                      else "more entries than the shuffle length", "protocol_error")
    verifier.check_entries(fields["store"], fields["entries"])
    return kind, fields


def _addr(text):
    host, _, port = text.rpartition(":")
    return host, int(port)


def _outcome(what, stage, reason="", peer=None, typ=""):
    return Outcome(what, stage, reason, advert=peer, typ=typ)


def _ended(why):
    """an Ended as an Outcome of this module's callers"""
    if why.event == "key_rotated_received":
        out = _outcome("key_rotated", why.phase, peer=why.peer)
        out.kid = why.kid
        return out
    if why.event == "timeout":
        return _outcome("timeout", why.phase, peer=why.peer)
    if why.event == "closed_by_peer":
        return _outcome("closed", why.phase, peer=why.peer)
    return _outcome("refused", why.phase, "key_rotated" if why.event == "key_rotated" else why.what, why.peer)


def dial(addr, identity, verifier, request, *, timeout, shuffle_length, random=os.urandom):
    """Connect to the TEMPUS peer at "host:port", be admitted, send ONE request body (shuffle(), sample(), or TRUST's
    call or cast for a bridge) and read its one reply, which is checked against the request and whose entries are
    verified (check_reply). Returns an Outcome. `timeout` (seconds) is one bound for the whole connection and
    `shuffle_length` the most entries a frame may hold in the network joined; neither has a default. A cast has no
    reply: its outcome is "closed" at stage "reply" when the bridge closes, which says nothing of what the bridge did.
    random(n) gives n secure random bytes."""
    deadline = time.monotonic() + timeout
    try:
        sock = socket.create_connection(_addr(addr), timeout=timeout)
    except socket.timeout:
        return Outcome("timeout", "tls")
    except OSError:
        return Outcome("unreachable", "tls")
    try:
        link = tls_open(sock, identity, False, deadline)
    except TlsRefused as why:
        return Outcome("timeout" if why.event == "timeout" else "tls_failed", "tls", why.what)
    wire = Wire(link.tls, deadline)
    try:
        peer = admit(wire, link, identity, verifier, random(32))
        wire.send(frame(request))
        body = read_frame(wire, "reply", peer.d, True)
    except Ended as why:
        wire.close()
        return _ended(why)
    wire.close()
    try:
        kind, fields = check_reply(verifier, request, body, shuffle_length)
    except Refused as why:
        out = Outcome("refused", "reply", str(why), advert=peer.d, typ=peer.typ)
        out.body = body
        return out
    return Outcome("reply", "done", kind=kind, fields=fields, body=body, advert=peer.d, typ=peer.typ)


class Request:
    """What a Listener's handler is given: the request's kind and fields (a shuffle's entries are verified), its bytes,
    the admitted peer's descriptor and token type, and the number of the connection (0 for the first accepted)."""
    __slots__ = ("kind", "fields", "body", "advert", "typ", "index")

    def __init__(self, kind, fields, body, advert, typ, index):
        self.kind, self.fields, self.body, self.advert, self.typ, self.index = kind, fields, body, advert, typ, index


class Listener:
    """The listening position for a program that is a TEMPUS peer but not a node: a thread accepts connections on
    host:port, and each connection, in its own thread, is admitted, has ONE request read (a shuffle or a sample; the
    entries of a shuffle are verified; anything else is refused with no reply) and is answered by handler(Request),
    which returns the reply body (bytes) or None (close with no reply). Every connection ends as one Outcome, kept in
    accept order: outcomes(count) waits for them. timeout (seconds, one bound per connection) and shuffle_length have
    no default. A peer with any self-signed Ed25519 certificate can connect; admission decides."""

    def __init__(self, identity, verifier, handler, *, host, port, timeout, shuffle_length, random=os.urandom):
        missing = tls_available()
        if missing:
            raise RuntimeError(missing)
        self.identity, self.verifier, self.handler, self.timeout = identity, verifier, handler, timeout
        self.shuffle_length, self.random = shuffle_length, random
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
        except Exception as exc:                     # a fault of this module or of the handler, never the peer's doing
            out = Outcome("closed", "tls", "internal error: %s: %s" % (type(exc).__name__, exc))
            try:
                sock.close()
            except OSError:
                pass
        with self._changed:
            self._done[index] = out
            self._changed.notify_all()

    def _serve(self, sock, index):
        deadline = time.monotonic() + self.timeout
        try:
            link = tls_open(sock, self.identity, True, deadline)
        except TlsRefused as why:
            return Outcome("timeout" if why.event == "timeout" else "tls_failed", "tls", why.what)
        wire = Wire(link.tls, deadline)
        try:
            peer = admit(wire, link, self.identity, self.verifier, self.random(32))
            body = read_frame(wire, "request", peer.d, True)
            try:
                kind, fields = read_body(body, self.shuffle_length)
                if kind not in ("shuffle", "sample"):
                    raise Refused("not a request: %s" % kind)
                if kind == "shuffle":
                    self.verifier.check_entries(fields["store"], fields["entries"])
            except Refused as why:
                raise Ended(why.event or "protocol_error", str(why), "request", peer.d, proved=True)
        except Ended as why:
            wire.close()
            return _ended(why)
        answer = self.handler(Request(kind, fields, body, peer.d, peer.typ, index))
        if answer is not None:
            wire.send(frame(bytes(answer)))
        wire.close()
        return Outcome("served", "done", kind=kind, fields=fields, body=body, advert=peer.d, typ=peer.typ,
                       sent="reply" if answer is not None else "nothing")
