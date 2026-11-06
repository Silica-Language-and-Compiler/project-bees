#!/usr/bin/env python3
"""Summarise one run of the M4 rate scenario (tools/run_demo.py --time --stamps): the request rate and each node's peak memory.

    m4_measure.py A_OUT B_OUT

reads A_OUT.rusage, B_OUT.rusage (BSD /usr/bin/time -l: peak resident set size in bytes on macOS) and B_OUT.stamps (the seconds since the
start at which each line of the client's output appeared). The rate is the number of requests of the run divided by the time between
the client's line `client: sending` and its line `client: all answered`; the times are those of the driver reading a pty, good to
about 0.1 s. One run on one machine, not a benchmark.
"""
import re
import sys


def rusage(path):
    out = {}
    for line in open(path):
        m = re.match(r"\s*([\d.]+)\s+real\s+([\d.]+)\s+user\s+([\d.]+)\s+sys", line)
        if m:
            out["real"], out["user"], out["sys"] = map(float, m.groups())
        m = re.match(r"\s*(\d+)\s+maximum resident set size", line)
        if m:
            out["rss"] = int(m.group(1))
        m = re.match(r"\s*(\d+)\s+peak memory footprint", line)
        if m:
            out["footprint"] = int(m.group(1))
    return out


def main(argv):
    a_out, b_out = argv[1], argv[2]
    stamps = {}
    for line in open(b_out + ".stamps"):
        t, _, text = line.strip().partition(" ")
        text = text.strip()
        if text.startswith("client: sending") and "send" not in stamps:
            stamps["send"] = float(t)
        if text.startswith("client: all answered"):
            stamps["done"] = float(t)
            m = re.search(r"all answered, (\d+) requests, payload not intact in (\d+)", text)
            stamps["n"], stamps["bad"] = int(m.group(1)), int(m.group(2))
    ra, rb = rusage(a_out + ".rusage"), rusage(b_out + ".rusage")
    dt = stamps["done"] - stamps["send"]
    print(f"requests {stamps['n']}, payload not intact in {stamps['bad']}")
    print(f"first request to last answer {dt:.2f} s: {stamps['n'] / dt:.1f} request/answer round trips per second "
          f"({2 * stamps['n'] / dt:.1f} messages per second across the link)")
    for name, r in (("a (service)", ra), ("b (client)", rb)):
        print(f"{name}: peak resident set {r['rss'] / 1048576:.1f} MiB"
              + (f", peak footprint {r['footprint'] / 1048576:.1f} MiB" if "footprint" in r else "")
              + f", user {r['user']:.2f} s, sys {r['sys']:.2f} s, real {r['real']:.2f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
