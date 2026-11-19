"""The cases of D1 (tools/bees_pack_trial.py). The values below are the ones dangerous_d1_write.silica writes."""
import fcntl
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tools"))
import bees_pack_store as S      # noqa: E402
from bees_pack_store import Atom as A      # noqa: E402

CAPACITY = 16384
NAME = "d1.sildat"


def image():
    img = S.Image(CAPACITY)
    img.append_value(1, {A("name"): "alpha", A("n"): 42})
    img.append_value(2, bytes(10000))                       # one value in three records
    img.append_value(3, {A("flag"): True, A("items"): [{A("a"): 1, A("s"): "one"}, {A("a"): 2, A("s"): "two"}],
                         A("neg"): -70000, A("wide"): 4294967295})
    return img.bytes()


def put(d, data):
    with open(os.path.join(d, NAME), "wb") as f:
        f.write(data)


def flipped(at):
    data = bytearray(image())
    data[at] ^= 1
    return bytes(data)


def describe(d):
    """What the backing looks like after the run (no content: sizes and counts)."""
    p = os.path.join(d, NAME)
    if not os.path.exists(p):
        return ["backing: absent"]
    with open(p, "rb") as f:
        data = f.read()
    return [f"backing: {len(data)} bytes, {len(S.records(data))} records, {len(S.frames(data))} frames"]


def same_as_packer(d):
    # the writer's declaration names d1w.sildat: one build may claim a backing once (E2415)
    with open(os.path.join(d, "d1w.sildat"), "rb") as f:
        data = f.read()
    return [f"backing: {len(data)} bytes, {len(S.records(data))} records, {len(S.frames(data))} frames"] + ["backing bytes equal to the packer's image: " + ("yes" if data == image() else "NO")]


_held = []


def locked(d):
    put(d, image())
    fd = os.open(os.path.join(d, NAME), os.O_RDWR)
    fcntl.flock(fd, fcntl.LOCK_EX)          # another owner: the carrier's sidecar takes the same lock
    _held.append(fd)


def unlock(d):
    while _held:
        os.close(_held.pop())
    return describe(d)


CASES = [
    {"name": "read_packed", "exe": "dangerous_d1_read", "prepare": lambda d: put(d, image()), "after": describe},
    {"name": "write_compare", "exe": "dangerous_d1_write", "after": same_as_packer},
    {"name": "read_absent", "exe": "dangerous_d1_read", "after": describe},
    {"name": "read_other_size", "exe": "dangerous_d1_read", "prepare": lambda d: put(d, image()[:8192]), "after": describe},
    # one payload byte of record 2 (the middle record of the three-record value) wrong
    {"name": "read_flipped_record", "exe": "dangerous_d1_read", "prepare": lambda d: put(d, flipped(2 * 4096 + 16 + 16 + 100)), "after": describe},
    # one byte of the first block's header wrong: the carrier drops the block without a report
    {"name": "read_flipped_header", "exe": "dangerous_d1_read", "prepare": lambda d: put(d, flipped(3)), "after": describe},
    {"name": "read_held", "exe": "dangerous_d1_read", "prepare": locked, "after": unlock},
]
