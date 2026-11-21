"""EXAMPLE ONLY, not for production. See ../../README.md.

The example Python TEMPUS client library: the files an application would take as its starting point.

  codec.py       the ETF subset tempus/1 uses
  frames.py      descriptors, tokens (read and verify), every frame body, read_body with every bound
  connection.py  Identity, Verifier, dial, Listener, Outcome: one connection, in both positions
  gossip.py      the view rules, Store, Peer: the three stores, the shuffle on a timer, the join

testing.py is beside them and is NOT part of what an application uses: the frames of the test unit, tokens made with
the test producer's fixed seed, and deliberate misbehaviour. It is imported by name (tempus_client.testing), never by
`from tempus_client import *`.
"""
from .codec import FRAME_MAX, Atom, Refused, etf_decode, etf_encode
from .frames import (AGE_MAX, ENTRIES_MAX, KINDS, TYPES, advert, call_frame, challenge, check_descriptor, descriptor, frame,
                     key_rotated, peer_id, read_body, read_token, response, result_value, sample, sample_reply, shuffle,
                     shuffle_reply, verify_token)
from .connection import (ALPN, CLOSE, OUTCOMES, STAGES, Identity, Listener, Outcome, Request, Verifier, certificate_fingerprint,
                         certificate_key, certificate_pem, dial, read_any)
from .gossip import Peer, PeerSettings, Store, StoreSettings, peer8, secure_draws

__all__ = [
    "FRAME_MAX", "Atom", "Refused", "etf_decode", "etf_encode",
    "AGE_MAX", "ENTRIES_MAX", "KINDS", "TYPES", "advert", "call_frame", "challenge", "check_descriptor", "descriptor", "frame",
    "key_rotated", "peer_id", "read_body", "read_token", "response", "result_value", "sample", "sample_reply", "shuffle",
    "shuffle_reply", "verify_token",
    "ALPN", "CLOSE", "OUTCOMES", "STAGES", "Identity", "Listener", "Outcome", "Request", "Verifier", "certificate_fingerprint",
    "certificate_key", "certificate_pem", "dial", "read_any",
    "Peer", "PeerSettings", "Store", "StoreSettings", "peer8", "secure_draws",
]
