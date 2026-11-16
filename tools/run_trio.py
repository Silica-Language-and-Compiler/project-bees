#!/usr/bin/env python3
"""Run three trial executables at the same time, as three separate operating-system processes, each the way tools/run_trial.py
runs one (pty, marker, "exit" on stdin once the output is quiet). The first is started, the second follows after STAGGER seconds
and the third after another STAGGER; all must finish. Each one's output goes to its own OUT file with its exit code appended.

    run_trio.py EXE_1 OUT_1 MARKER_1 EXE_2 OUT_2 MARKER_2 EXE_3 OUT_3 MARKER_3 [STAGGER_SEC] [CAP_SEC]
"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))


def main(argv):
    triples = [argv[1 + 3 * i: 4 + 3 * i] for i in range(3)]
    stagger = float(argv[10]) if len(argv) > 10 else 0.5
    cap = argv[11] if len(argv) > 11 else "60"
    runner = os.path.join(HERE, "run_trial.py")
    procs = []
    for k, (exe, out, mark) in enumerate(triples):
        if k:
            time.sleep(stagger)
        procs.append(subprocess.Popen([sys.executable, runner, exe, out, mark, "0.5", cap]))
    codes = [p.wait() for p in procs]
    return 0 if all(c == 0 for c in codes) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
