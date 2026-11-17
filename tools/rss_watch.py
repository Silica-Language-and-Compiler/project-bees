#!/usr/bin/env python3
"""rss_watch: run a program that prints a marker line every STEP units of work and print its resident set (ps, KiB) at each marker.

    rss_watch.py EXE UNIT STEP SAMPLES [CAP_SEC]     prints `<units> <UNIT> <rss> KiB <seconds>`; the first line is the program's "start" line

A measurement helper (trials/n2_carrier_leak), not a test. The program is killed after SAMPLES markers or CAP_SEC (default 200).
"""
import subprocess
import sys
import time


def main(argv):
    exe, unit, step, samples = argv[1], argv[2], int(argv[3]), int(argv[4])
    cap = float(argv[5]) if len(argv) > 5 else 200.0
    p = subprocess.Popen([exe], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
    t0, n = time.time(), 0
    for line in p.stdout:
        line = line.strip()
        if line.startswith("batch") or line == "start":
            rss = subprocess.run(["ps", "-o", "rss=", "-p", str(p.pid)], capture_output=True, text=True).stdout.strip()
            print(f"{n * step:7d} {unit} {rss:>8} KiB {time.time() - t0:6.1f} s", flush=True)
            n += 1
        if n > samples or time.time() - t0 > cap:
            break
    p.kill()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
