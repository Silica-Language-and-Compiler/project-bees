#!/usr/bin/env python3
"""Run two trial executables at the same time, as two separate operating-system processes, each the
way tools/run_trial.py runs one (pty, marker, "exit" on stdin once the output is quiet). The first
is started, the second follows after STAGGER seconds; both must finish. Each one's output goes to its
own OUT file with its exit code appended.

    run_pair.py EXE_A OUT_A MARKER_A EXE_B OUT_B MARKER_B [STAGGER_SEC] [CAP_SEC]
"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))


def main(argv):
    exe_a, out_a, mark_a, exe_b, out_b, mark_b = argv[1:7]
    stagger = float(argv[7]) if len(argv) > 7 else 0.5
    cap = argv[8] if len(argv) > 8 else "60"
    runner = os.path.join(HERE, "run_trial.py")
    pa = subprocess.Popen([sys.executable, runner, exe_a, out_a, mark_a, "0.5", cap])
    time.sleep(stagger)
    pb = subprocess.Popen([sys.executable, runner, exe_b, out_b, mark_b, "0.5", cap])
    ra, rb = pa.wait(), pb.wait()
    return 0 if ra == 0 and rb == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
