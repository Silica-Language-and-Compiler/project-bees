#!/usr/bin/env python3
"""Run a command while holding one of N slots, so that at most N such commands run at the same time on this machine, whichever
trial or process starts them.

    with_slot.py CMD [ARG...]

N comes from BEES_COMPILE_SLOTS and the slot files live in BEES_SLOT_DIR (both set by tools/run_all_trials.sh). With either
unset the command simply runs (a serial `make integrate` needs no limit). A slot is an flock(2) on a file, so one that its holder
leaves behind (killed, crashed) is free again at once. The compile of a big unit (bees_modules) takes several hundred MB of
resident memory, and the trial runs themselves are cheap: the compiler is what the slots limit (tools/silica.mk, tools/trial.mk).
The exit status is the command's.
"""
import fcntl
import os
import sys
import time


def main(argv):
    cmd = argv[1:]
    if not cmd:
        print(__doc__)
        return 2
    n = int(os.environ.get("BEES_COMPILE_SLOTS", "0") or "0")
    d = os.environ.get("BEES_SLOT_DIR", "")
    if n <= 0 or not d:
        os.execvp(cmd[0], cmd)
    os.makedirs(d, exist_ok=True)
    fds = [os.open(os.path.join(d, f"slot{i}"), os.O_CREAT | os.O_RDWR, 0o600) for i in range(n)]
    held = None
    while held is None:
        for fd in fds:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                held = fd
                break
            except OSError:
                continue
        else:
            time.sleep(0.2)
    # the lock is inherited by the child (flock is per open file description) and ends with the last holder
    import subprocess
    return subprocess.call(cmd, pass_fds=(held,))


if __name__ == "__main__":
    sys.exit(main(sys.argv))
