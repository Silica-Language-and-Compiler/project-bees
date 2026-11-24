#!/usr/bin/env python3
"""A plain name for the Python TEMPUS test support, the name every trial tool imports (`import bees_tempus_client as
c`: tools/bees_tempus_trial.py, bees_tempus_fixtures.py, bees_tempus_ids.py, test_bees_tempus_admission.py,
bees_tempus_swift_trial.py, the walks of the client, node and bridge trials of every language, directly or through
bees_tempus_trial.py, and test_bees_tempus_client.py beside this file). It holds no code of its own.

The Python code is in two parts that must not be confused:

  the extension    lib/bees_tempus_codec.py, bees_tempus_admission.py, bees_tempus_peer.py, bees_tempus_view.py,
                   bees_tempus_store.py, bees_tempus_config.py, bees_tempus_node.py: what an application imports to be
                   a TEMPUS peer or a TEMPUS node. It holds nothing that is for tests only.
  test support     testing/bees_tempus_testing.py: the test-only tick and clock frames, token making, keys from fixed
                   seeds, fixed nonces, peers that misbehave on purpose. Only tests and trials import it.

This module is the test support under that name: every name of bees_tempus_testing.py, which itself passes on the
names of the extension the trials use. An application imports the extension's modules by their own names, never this.
The command line is the test support's too (it signs tokens with the TEST producer seed and sends the test-only
frames); the driver application's command line is driver/tempus_peer.py.

    bees_tempus_client.py read-hex HEX [SHUFFLE_LENGTH]
    bees_tempus_client.py dial HOST:PORT --seed HEX --addr HOST:PORT --producer-pub HEX --kid KID --now SECONDS
                               (--token HEX | --test-token TYP:NBF:EXP) [--skew S] [--timeout S] [--nonce HEX]
                               [--shuffle-length N] REQUEST
        REQUEST: sample STORE N | tick STORE | clock MS | shuffle STORE | raw HEX
        (`shuffle STORE` sends this client's own entry at age 0; `raw` is any body, for example TRUST's call or cast.)
        --test-token signs with the TEST producer seed 00..1f. Prints the outcome as one line. TEST ONLY.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
for _dir in ("testing", "lib"):
    if os.path.join(_HERE, _dir) not in sys.path:
        sys.path.insert(0, os.path.join(_HERE, _dir))

import bees_tempus_testing as _testing  # noqa: E402

globals().update({_k: _v for _k, _v in vars(_testing).items() if not _k.startswith("__")})


def main(argv):
    code = _testing.main(argv)
    if code == 2:
        print(__doc__)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
