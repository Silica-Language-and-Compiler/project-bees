#!/usr/bin/env python3
"""Run two trial executables at the same time, as two separate operating-system processes, each the
way tools/run_trial.py runs one (pty, marker, "exit" on stdin once the output is quiet). The first
is started; when it has printed its first byte (it is loaded and runs) the second follows after STAGGER
seconds; both must finish. Each one's output goes to its own OUT file with its exit code appended.

The wait for the first byte is there because STAGGER alone measured from the START of the first program, and a program
that was just built takes about two seconds to be loaded the first time it is run on a Mac (measured 2026-11-20: 1.98 s,
then 0.01 s): a dialer started 0.5 s after such a listener found nobody listening.

    run_pair.py EXE_A OUT_A MARKER_A EXE_B OUT_B MARKER_B [STAGGER_SEC] [CAP_SEC]
"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
READY_CAP = 5.0


def start_and_wait(runner, exe, out, mark, cap):
    """Starts one program under run_trial.py and waits until it has printed its first byte (it is loaded and runs), at
    most READY_CAP seconds: a program that says nothing before its peer arrives is not waited for longer. The caller
    removes started_flag(out) when the program has ended (a silent program writes it late)."""
    flag = started_flag(out)
    if os.path.exists(flag):
        os.unlink(flag)
    p = subprocess.Popen([sys.executable, runner, exe, out, mark, "0.5", cap], env=dict(os.environ, BEES_RUN_STARTED=flag))
    until = time.monotonic() + READY_CAP
    while not os.path.exists(flag) and p.poll() is None and time.monotonic() < until:
        time.sleep(0.02)
    return p


def started_flag(out):
    return out + ".started"


def forget(out):
    if os.path.exists(started_flag(out)):
        os.unlink(started_flag(out))


def main(argv):
    exe_a, out_a, mark_a, exe_b, out_b, mark_b = argv[1:7]
    stagger = float(argv[7]) if len(argv) > 7 else 0.5
    cap = argv[8] if len(argv) > 8 else "60"
    runner = os.path.join(HERE, "run_trial.py")
    pa = start_and_wait(runner, exe_a, out_a, mark_a, cap)
    time.sleep(stagger)
    pb = subprocess.Popen([sys.executable, runner, exe_b, out_b, mark_b, "0.5", cap])
    ra, rb = pa.wait(), pb.wait()
    forget(out_a)
    return 0 if ra == 0 and rb == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
