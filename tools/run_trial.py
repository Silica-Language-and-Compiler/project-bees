#!/usr/bin/env python3
"""Run a trial executable whose main ends in wait_for_exit(): stdout and stderr on a pty, stdin on
a pipe; once MARKER has appeared and the output has been quiet for IDLE seconds, write "exit\\n"
to stdin (wait_for_exit returns on that line). Output goes to OUT with the exit code appended.
Modelled on Silica's trials/ffi_addition/run_integration_exit_after_marker.py.

    run_trial.py EXE OUT MARKER [IDLE_SEC] [CAP_SEC]

When the environment names a file in BEES_RUN_STARTED, that file is created at the program's first byte of output: the
program has been loaded and runs. tools/run_pair.py and tools/run_trio.py wait for it before they start the next
program (a program that was just built can take two seconds to be loaded the first time it is run on a Mac).
"""
import os
import pty
import select
import subprocess
import sys
import time

NOTICE = b"[silica] root actor exited (no supervisor)"


def main(argv):
    exe, out_path, marker = argv[1], argv[2], argv[3]
    idle = float(argv[4]) if len(argv) > 4 else 0.5
    cap = float(argv[5]) if len(argv) > 5 else 60.0
    master, slave = pty.openpty()
    proc = subprocess.Popen([exe], stdin=subprocess.PIPE, stdout=slave, stderr=slave, close_fds=True)
    os.close(slave)
    chunks, seen, sent = [], False, False
    started = os.environ.get("BEES_RUN_STARTED", "")
    start = time.monotonic()
    last = start
    while True:
        r, _, _ = select.select([master], [], [], 0.1)
        if r:
            try:
                data = os.read(master, 65536)
            except OSError:
                data = b""
            if not data:
                break
            chunks.append(data)
            if started:
                open(started, "w").close()
                started = ""
            # The runtime's notice for each normal stop of an unsupervised actor (one-shot timers, resolvers) is not the
            # program's output and every caller deletes it afterwards; it does not break the quiet wait, or a program whose
            # short-lived actors stop more often than every IDLE seconds is never told to exit.
            if data.replace(NOTICE, b"").strip():
                last = time.monotonic()
            # The marker counts only once its own line is complete (a newline follows it): a program stopped between the
            # marker's first bytes and the end of its line leaves a cut-off last line in the output (a02_exit_listener).
            whole = b"".join(chunks)
            i = whole.find(marker.encode())
            if i >= 0 and b"\n" in whole[i:]:
                seen = True
        if proc.poll() is not None and not r:
            break
        now = time.monotonic()
        if seen and not sent and now - last >= idle:
            try:
                proc.stdin.write(b"exit\n"); proc.stdin.flush()
            except Exception:
                pass
            sent = True
        if now - start > cap:
            proc.kill()
            chunks.append(b"\n[run_trial] killed after cap\n")
            break
    rc = proc.wait()
    with open(out_path, "wb") as f:
        f.write(b"".join(chunks).replace(b"\r\n", b"\n"))
        f.write(f"exit={rc}\n".encode())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
