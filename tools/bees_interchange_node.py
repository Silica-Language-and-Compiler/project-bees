#!/usr/bin/env python3
"""bees_interchange_node: run ONE program of an interchange trial on the machine this script is started on, under the control of
tools/bees_interchange.py, which starts it locally or over its ssh session on the remote machine. Python 3, standard library only.

    bees_interchange_node.py [--cwd DIR] [--env NAME=VALUE]... [--cap SEC] [--pipe] -- CMD [ARG...]

The program's stdout and stderr go to a pty (the way tools/run_trial.py runs a trial program), or to a pipe with --pipe (erl,
epmd); every byte is copied to this script's stdout at once, so the driver sees the lines as they are printed. This script's
stdin is the control channel, one line each:

    @kill      SIGKILL the program (a node stopped while a link is up)
    anything else is written to the program's stdin with its newline ("exit" ends a program waiting in wait_for_exit())

When the control channel ends (the driver is gone, the ssh session dropped) the program's whole process group is killed, and
after --cap seconds (default 300) too: nothing this script started outlives it, on either machine. The last line it prints is
`@exit=CODE` (CODE is `killed (SIGKILL)` after @kill, or `killed after cap`).
"""
import os
import pty
import select
import signal
import subprocess
import sys
import time


def main(argv):
    args = argv[1:]
    cwd, env, cap, pipe = None, dict(os.environ), 300.0, False
    while args and args[0] != "--":
        if args[0] == "--cwd":
            cwd, args = args[1], args[2:]
        elif args[0] == "--env":
            k, v = args[1].split("=", 1)
            env[k] = v
            args = args[2:]
        elif args[0] == "--cap":
            cap, args = float(args[1]), args[2:]
        elif args[0] == "--pipe":
            pipe, args = True, args[1:]
        else:
            print(__doc__)
            return 2
    cmd = args[1:]
    if not cmd:
        print(__doc__)
        return 2
    out = sys.stdout.buffer
    if pipe:
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=cwd, env=env, start_new_session=True)
        fd = p.stdout.fileno()
    else:
        master, slave = pty.openpty()
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=slave, stderr=slave, cwd=cwd, env=env, close_fds=True, start_new_session=True)
        os.close(slave)
        fd = master

    def kill_group():
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass

    verdict, control_open, ctl_buf, start = None, True, b"", time.monotonic()
    ctl = sys.stdin.fileno()
    while True:
        watch = [fd] + ([ctl] if control_open else [])
        try:
            r, _, _ = select.select(watch, [], [], 0.1)
        except (OSError, ValueError):
            r = []
        if fd in r:
            try:
                data = os.read(fd, 65536)
            except OSError:
                data = b""
            if data:
                out.write(data.replace(b"\r\n", b"\n"))
                out.flush()
            elif p.poll() is not None:
                break
        if control_open and ctl in r:
            data = os.read(ctl, 4096)
            if not data:
                control_open = False
                if p.poll() is None:
                    verdict = "killed (control channel closed)"
                    kill_group()
            ctl_buf += data
            while b"\n" in ctl_buf:
                line, ctl_buf = ctl_buf.split(b"\n", 1)
                if line.strip() == b"@kill":
                    verdict = "killed (SIGKILL)"
                    kill_group()
                else:
                    try:
                        p.stdin.write(line + b"\n")
                        p.stdin.flush()
                    except (BrokenPipeError, OSError):
                        pass
        if p.poll() is not None and fd not in r:
            break
        if time.monotonic() - start > cap and p.poll() is None:
            verdict = "killed after cap"
            kill_group()
    rc = p.wait()
    kill_group()   # anything the program left in its group (erl's helpers)
    out.write(f"\n@exit={verdict or rc}\n".encode())
    out.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
