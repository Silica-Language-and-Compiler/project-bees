#!/usr/bin/env python3
"""Run three trial executables at the same time, as three separate operating-system processes, each the way tools/run_trial.py
runs one (pty, marker, "exit" on stdin once the output is quiet). The first is started; when it has printed its first byte (it
is loaded and runs: tools/run_pair.py says why that is waited for) the second follows after STAGGER seconds, and the third
after the second's first byte and another STAGGER; all must finish. Each one's output goes to its own OUT file with its exit code appended.

    run_trio.py EXE_1 OUT_1 MARKER_1 EXE_2 OUT_2 MARKER_2 EXE_3 OUT_3 MARKER_3 [STAGGER_SEC] [CAP_SEC]
"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from run_pair import forget, start_and_wait  # noqa: E402


def main(argv):
    triples = [argv[1 + 3 * i: 4 + 3 * i] for i in range(3)]
    stagger = float(argv[10]) if len(argv) > 10 else 0.5
    cap = argv[11] if len(argv) > 11 else "60"
    runner = os.path.join(HERE, "run_trial.py")
    procs = []
    for k, (exe, out, mark) in enumerate(triples):
        if k:
            time.sleep(stagger)
        if k < 2:
            procs.append(start_and_wait(runner, exe, out, mark, cap))
        else:
            procs.append(subprocess.Popen([sys.executable, runner, exe, out, mark, "0.5", cap]))
    codes = [p.wait() for p in procs]
    for _exe, out, _mark in triples[:2]:
        forget(out)
    return 0 if all(c == 0 for c in codes) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
