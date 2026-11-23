#!/usr/bin/env python3
"""C7: node R, an application that is a TEMPUS node through the Python extension and is NOT a test program.

It imports the extension's two modules an application needs, bees_tempus_config and bees_tempus_node, and nothing of
the test support. It gives the node no clock, no timers and no random source: the node reads the machine's clock,
runs its own timers and takes its random bytes from the operating system. Its values are its own configuration file,
r_app.json beside it, which the trial tool writes (the TEST-ONLY key, certificate and token are files the trial tool
names there; this program makes no key and no token).

The node's lines go to standard output, as the Silica node's do. What the node tells its application is printed as
one line each. A line `exit` on standard input stops the node; the last line says whether any test support was loaded.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "example_tempus_clients", "python", "lib"))
import bees_tempus_config  # noqa: E402
import bees_tempus_node  # noqa: E402


def told(event):
    if event.name == "token_invalid":
        print("application: told that the node's own token is not valid any more: " + event.why, flush=True)
    elif event.name == "key_rotated":
        print("application: told that a peer answered key_rotated, its current kid is " + event.kid.decode(), flush=True)
    elif event.name in ("clock_unreadable", "stopped", "listen_failed"):
        print("application: told (%s) that %s" % (event.name, event.text), flush=True)


def main():
    with open(os.path.join(HERE, "r_app.json")) as f:
        values = json.load(f)
    with open(values.pop("token_file")) as f:
        token = bytes.fromhex(f.read().strip())
    address = values.pop("address")
    values["producer_key"] = tuple(values["producer_key"])
    config = bees_tempus_config.node_config(values)
    node = bees_tempus_node.Node(config, token=token, address=address, on_event=told)
    node.start()
    for line in sys.stdin:
        if line.strip() == "exit":
            break
    node.stop()
    loaded = sorted(name for name in sys.modules if name in ("bees_tempus_testing", "bees_tempus_client"))
    print("application: test support loaded: %s" % (", ".join(loaded) if loaded else "none"), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
