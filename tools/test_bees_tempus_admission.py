#!/usr/bin/env python3
"""Tests of TEMPUS admission (T4, development-plan/tempus-design.md section 4).

trials/t4_tempus_admission runs the Silica admission rules and the native edge (Ed25519, SHA-512) over fixtures made by
tools/bees_tempus_fixtures.py, and prints one line per case. This test:
  - checks that the fixtures unit in the tree is what the tool writes now (keys and tokens are deterministic);
  - requires, for every case, the verdict the Python client's own checks give for the same bytes
    (bees_tempus_fixtures.cases(), computed with example_tempus_clients/python/bees_tempus_client.py and the `cryptography` package);
  - checks the fixtures themselves (each refusal case differs from the good one in the one thing its name says).
It reads every recorded golden (dangerous_admit.<platform>.scout) and the last run's output when there is one.

    python3 tools/test_bees_tempus_admission.py
"""
import glob
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "example_tempus_clients", "python"))  # the example Python client
import bees_tempus_client as c  # noqa: E402
import bees_tempus_fixtures as fx  # noqa: E402

LEAF = os.path.join(ROOT, "trials", "t4_tempus_admission")


def expected_lines():
    out = []
    for case in fx.cases():
        if case["kind"] == 3:
            text = "the same 64 bytes as the fixture's signature"
        else:
            text = "admitted" if case["expect"] == "" else "refused: " + case["expect"]
        out.append("%s: %s" % (case["name"], text))
    return out + ["done", "exit=0"]


def read_lines(path):
    with open(path) as f:
        return [line.rstrip("\n") for line in f if line.strip() != ""]


class Admission(unittest.TestCase):
    def test_fixtures_unit_is_current(self):
        with open(fx.OUT) as f:
            self.assertEqual(f.read(), fx.silica(), "run tools/bees_tempus_fixtures.py write")

    def test_goldens_match_the_python_verdicts(self):
        goldens = sorted(glob.glob(os.path.join(LEAF, "dangerous_admit.*.scout")))
        self.assertTrue(goldens, "no golden recorded in trials/t4_tempus_admission")
        for g in goldens:
            self.assertEqual(read_lines(g), expected_lines(), g)

    def test_last_run_matches_the_python_verdicts(self):
        sout = os.path.join(LEAF, "dangerous_admit.sout")
        if not os.path.exists(sout):
            self.skipTest("the trial has not been run in this tree")
        self.assertEqual(read_lines(sout), expected_lines())

    def test_every_refusal_reason_is_covered(self):
        reasons = {case["expect"] for case in fx.cases()}
        for want in ("", "key_rotated", "the token has expired", "the token is not valid yet", "sub is not the peer's key",
                     "typ is not the store's type", "id is not the SHA-512 of pub", "the signature does not verify", "truncated"):
            self.assertIn(want, reasons)

    def test_the_good_token_by_the_python_client(self):
        good = fx.cases()[0]
        fields = c.verify_token(good["token"], fx.PRODUCER.public_key(), fx.KID, fx.NOW, fx.SKEW)
        self.assertEqual(fields["sub"], fx.NODE_PUB)
        self.assertEqual(good["id"], c.peer_id(fx.NODE_PUB))
        # the kid is judged before the time: an expired token under another key is answered key_rotated
        both = [x for x in fx.cases() if x["name"] == "under another kid and expired too"][0]
        self.assertEqual(both["expect"], "key_rotated")
        with self.assertRaisesRegex(c.Refused, "key_rotated"):
            c.verify_token(both["token"], fx.PRODUCER.public_key(), fx.KID, fx.NOW, fx.SKEW)

    def test_proofs(self):
        by = {x["name"]: x for x in fx.cases()}
        p = by["proof of possession"]
        fx.NODE.public_key().verify(p["sig"], p["nonce"] + p["token"])
        for name in ("proof for another nonce", "proof by another key", "proof over another token"):
            q = by[name]
            with self.assertRaises(Exception):
                fx.NODE.public_key().verify(q["sig"], q["nonce"] + q["token"])


if __name__ == "__main__":
    unittest.main()
