#!/usr/bin/env python3
"""Run one build command of the C# TEMPUS extension while no other one runs.

    build_lock.py LOCK_FILE CMD [ARG...]

Several trials build the extension, and every project that references it builds it again, into the same directory
(build/). `dotnet build` does not expect a second build of the same project at the same time. This tool holds an
flock(2) on LOCK_FILE for as long as CMD runs, so such builds run one after another, whichever trial starts them. A
lock whose holder was killed is free again at once. The exit status is the command's.
"""
import fcntl
import os
import subprocess
import sys


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 2
    os.makedirs(os.path.dirname(os.path.abspath(argv[1])), exist_ok=True)
    with open(argv[1], "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return subprocess.call(argv[2:])


if __name__ == "__main__":
    sys.exit(main(sys.argv))
