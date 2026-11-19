"""The cases of examples/store_node (tools/bees_pack_trial.py; run from trials/d3_store_node): the same executable started on
three stores. The frame cap and the listener's address come from the store, so two caps need no rebuild."""
import os
import socket
import struct
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "tools"))
import bees_pack as P               # noqa: E402
import trial_ports                  # noqa: E402

PORT = trial_ports.port("d3_store_node", 0)


def packed(cap):
    def prepare(d):
        with open(os.path.join(HERE, "bees.config"), encoding="utf-8") as f:
            text = f.read()
        assert "{frame_size_max, 4096}" in text and str(PORT) in text
        with open(os.path.join(d, "bees.config"), "w", encoding="utf-8") as f:
            f.write(text.replace("{frame_size_max, 4096}", "{frame_size_max, %d}" % cap))
        rc = P.main(["bees_pack.py", "pack", "--config", os.path.join(d, "bees.config"), "--capacity", "65536",
                     "-o", os.path.join(d, "node.sildat"), os.path.join(HERE, "manifest", "node.wire")])
        assert rc == 0
    return prepare


def peer(first, second):
    """A peer that sends a frame of `first` bytes, reads the answer, then announces a frame of `second` bytes."""
    def during(d, proc):
        s = None
        for _ in range(100):
            try:
                s = socket.create_connection(("127.0.0.1", PORT), timeout=1.0)
                break
            except OSError:
                time.sleep(0.1)
        if s is None:
            return ["peer: could not connect"]
        out = []
        s.settimeout(10.0)
        try:
            s.sendall(struct.pack(">I", first) + b"x" * first)
            head = s.recv(4, socket.MSG_WAITALL)
            n = struct.unpack(">I", head)[0]
            out.append(f"peer: sent a frame of {first} bytes; the answer is the node's name: {s.recv(n, socket.MSG_WAITALL).decode()}")
            s.sendall(struct.pack(">I", second) + b"y" * 16)
            rest = s.recv(64)
            out.append(f"peer: announced a frame of {second} bytes; the node " + ("closed the link" if rest == b"" else "answered"))
        except OSError as e:
            out.append(f"peer: {type(e).__name__}")
        finally:
            s.close()
        return out
    return during


CASES = [
    {"name": "node_cap_4096", "exe": "dangerous_store_node", "prepare": packed(4096), "during": peer(10, 5000)},
    {"name": "node_cap_512", "exe": "dangerous_store_node", "prepare": packed(512), "during": peer(500, 600)},
    {"name": "node_no_store", "exe": "dangerous_store_node"},
]
