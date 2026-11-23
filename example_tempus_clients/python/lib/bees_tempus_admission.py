"""The Python TEMPUS extension: admission (development-plan/tempus-design.md section 4).

What one peer checks of another, in the order the BEES TEMPUS node checks it (src/tempus/dangerous_bees_tempus_conn.
silica and bees_tempus_admit.silica), with the node's audit events and reason texts:

  an advert   the channel binding first: the advert's `pub` is the key of the certificate the peer presented in the
              TLS handshake (binding_refused). Then the token: its structure; its `kid` is the current one
              (key_rotated: the one refusal a peer is told); the time, nbf - skew <= now < exp + skew; its `sub` is
              the advert's `pub` (admission_refused). Then the tempus whitelist rule, both ways: a token that says
              tempus_bridge or tempus_sentinel needs a certificate of the whitelist, and a certificate of the
              whitelist needs such a token (whitelist_reject). Then the two key operations: the advert's `id` is the
              SHA-512 of its `pub`, and the producer's signature on the token verifies (admission_refused).
  an entry    of a shuffle, a shuffle reply or a sample reply: the same token rules with the type of the store the
              frame names, the identity hash and the producer's signature. No connection is needed.
  a proof     the peer's Ed25519 signature over the nonce this side sent followed by the peer's own token bytes.

The tempus whitelist is a list of certificate fingerprints. A fingerprint is the SHA-512 of the certificate's DER
bytes, 64 bytes. It names a certificate, not a key: a new certificate over the same key is another entry.

Nothing here reads a clock: the caller gives the time in whole seconds since 1970 UTC. Ed25519 is the `cryptography`
package's; SHA-512 is hashlib's.
"""
import hashlib

from bees_tempus_codec import Atom, Refused, TYPES, check_descriptor, peer_id, read_token

ROTATED = "key_rotated"


def _ed25519():
    from cryptography.hazmat.primitives.asymmetric import ed25519
    return ed25519


def fingerprint(der):
    """How the tempus whitelist names a certificate: the SHA-512 of its DER bytes."""
    return hashlib.sha512(der).digest()


def certificate_der(pem_or_der):
    """the DER bytes of a certificate given as PEM or DER"""
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization
    data = bytes(pem_or_der)
    try:
        cert = x509.load_pem_x509_certificate(data) if data.lstrip().startswith(b"-----") else x509.load_der_x509_certificate(data)
    except Exception:
        raise Refused("the certificate cannot be read")
    return cert.public_bytes(serialization.Encoding.DER)


def certificate_key(der):
    """The raw 32-byte Ed25519 key of a certificate (DER), after checking what tempus/1 requires of it: an Ed25519
    key, issuer equal to subject, and the signature verifying under its own key. Refused(reason) otherwise. The
    validity dates are not looked at (ruling NQ-10: the producer's token carries the validity window)."""
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization
    try:
        cert = x509.load_der_x509_certificate(der)
        key = cert.public_key()
    except Exception:
        raise Refused("the certificate cannot be read", "tls_verify_failed")
    if not isinstance(key, _ed25519().Ed25519PublicKey):
        raise Refused("the certificate's key is not Ed25519", "tempus_cert_key")
    try:
        if cert.issuer != cert.subject:
            raise ValueError
        key.verify(cert.signature, cert.tbs_certificate_bytes)
    except Exception:
        raise Refused("the certificate is not self-signed", "tls_verify_failed")
    return key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def token_rules(d, kid, now, skew, want=None):
    """The token rules that need no key operation, in the node's order (bees_tempus_admit@pre): the token's structure;
    the kid (judged first: a token under another key is answered key_rotated whatever else is wrong with it); the
    time; sub; and, when `want` names a store, the token's typ. Returns (fields, payload, signature)."""
    fields, payload, sig = read_token(d[Atom("token")])
    if fields["kid"] != kid:
        raise Refused(ROTATED, ROTATED)
    if now < fields["nbf"] - skew:
        raise Refused("the token is not valid yet", "admission_refused")
    if now >= fields["exp"] + skew:
        raise Refused("the token has expired", "admission_refused")
    if fields["sub"] != d[Atom("pub")]:
        raise Refused("sub is not the peer's key", "admission_refused")
    if want is not None and fields["typ"] != want:
        raise Refused("typ is not the store's type", "admission_refused")
    return fields, payload, sig


def whitelist_why(typ, index):
    """The tempus whitelist rule (rulings OQ-3 and NQ-4): "" or why the peer is refused. index: where the peer's
    certificate is in the whitelist, -1 when it is not there."""
    if typ == "tempus_edge":
        return ("a certificate of the tempus whitelist with a token whose typ is not tempus_bridge or tempus_sentinel"
                if index >= 0 else "")
    return ("a tempus_bridge or tempus_sentinel token under a certificate that is not in the tempus whitelist"
            if index < 0 else "")


class Verifier:
    """What this side needs to check another. Every value is required; none has a default.

      producer_pub  the producer's current public key, 32 raw bytes
      kid           its key identifier, 1 to 64 bytes (text is taken as its bytes)
      now           the time for token checks in whole seconds since 1970 UTC: a number, or a function of no
                    arguments that returns one
      skew          the clock difference allowed, in seconds
      whitelist     the tempus whitelist: a sequence of certificate fingerprints (fingerprint()), in the order the
                    audit lines number them. An empty one accepts no bridge and no sentinel. None means that the rule
                    is not applied at all: only for a program that never treats a peer as a bridge or a sentinel,
                    because without the rule any holder of such a token is believed.
    """

    def __init__(self, producer_pub, kid, now, skew, whitelist):
        self.producer_pub = bytes(producer_pub)
        if len(self.producer_pub) != 32:
            raise ValueError("the producer key is 32 bytes")
        self.producer = _ed25519().Ed25519PublicKey.from_public_bytes(self.producer_pub)
        self.kid = kid.encode() if isinstance(kid, str) else bytes(kid)
        if not 1 <= len(self.kid) <= 64:
            raise ValueError("the kid is 1 to 64 bytes")
        self.now, self.skew = now, skew
        self.whitelist = None if whitelist is None else [bytes(f) for f in whitelist]

    def clock(self):
        return self.now() if callable(self.now) else self.now

    def whitelist_index(self, cert_fp):
        if self.whitelist is None or cert_fp is None:
            return -1
        try:
            return self.whitelist.index(bytes(cert_fp))
        except ValueError:
            return -1

    def _keyed(self, d, payload, sig, event):
        if peer_id(d[Atom("pub")]) != d[Atom("id")]:
            raise Refused("id is not the SHA-512 of pub", event)
        try:
            self.producer.verify(sig, payload)
        except Exception:
            raise Refused("the signature does not verify", event)

    def check_advert(self, d, cert_pub, cert_fp):
        """A peer's advert on a connection: (the token's fields, the certificate's index in the whitelist or -1).
        cert_pub is the key of the certificate the peer presented in the TLS handshake and cert_fp that
        certificate's fingerprint. Refused otherwise, with the node's event and reason; the event "key_rotated" means
        the caller sends the one key_rotated frame."""
        check_descriptor(d)
        if d[Atom("pub")] != cert_pub:
            raise Refused("the advert's pub is not the key of the peer's TLS certificate", "binding_refused")
        fields, payload, sig = token_rules(d, self.kid, self.clock(), self.skew)
        index = self.whitelist_index(cert_fp)
        if self.whitelist is not None:
            why = whitelist_why(fields["typ"], index)
            if why:
                raise Refused(why, "whitelist_reject")
        self._keyed(d, payload, sig, "admission_refused")
        return fields, index

    def check_entry(self, d, store):
        """One entry of a received shuffle, shuffle reply or sample reply, for the store the frame names: the token's
        fields, or Refused (event entry_refused). A token under another kid is refused like any other here: only an
        advert is answered with key_rotated."""
        if store not in TYPES:
            raise ValueError("store is a peer type")
        try:
            check_descriptor(d)
            fields, payload, sig = token_rules(d, self.kid, self.clock(), self.skew, store)
            self._keyed(d, payload, sig, "entry_refused")
        except Refused as why:
            raise Refused(str(why), "entry_refused")
        return fields

    def check_entries(self, store, entries):
        """Every entry of a frame; one that does not verify refuses the whole frame (design section 10)."""
        for k, (_age, d) in enumerate(entries):
            try:
                self.check_entry(d, store)
            except Refused as why:
                raise Refused("entry %d: %s" % (k, why), "entry_refused")

    def check_proof(self, pub, nonce, token, sig):
        try:
            _ed25519().Ed25519PublicKey.from_public_bytes(pub).verify(sig, bytes(nonce) + token)
        except Exception:
            raise Refused("the proof of possession does not verify", "pop_failed")
