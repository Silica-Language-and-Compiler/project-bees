#!/usr/bin/env python3
"""Take the runtime's actor reports out of a TEMPUS node's output (trials): bees_tempus_reports.py FILE...

A node's actors without a supervisor (assemblers, send actors, connections, links, carriers) end when a connection ends,
and the runtime reports each end from that actor's own thread: where a report lands among the program's lines varies,
and two reports can be written into each other, line by line. So the reports are recognised by their lines, not as
blocks. Removed: every line of a report (its two frame lines, actor_id, agent_type_atom, reason, reason_tag,
supervisor_acb, call_stack and the `  #N  name` lines), the runtime's root-actor notice, and empty lines.
Kept, as one line each before the exit line, in sorted order: the reason of every report that is not one of
  :normal                          an actor that ended as it should
  (:explicit, :link_lost)          the carrier's own report of a lost link (a write to a peer that had just closed)
  (:explicit, :link_unavailable)   the carrier of a dial that found nobody listening (the node's own line says connect_failed)
so any other failure of an actor still fails the comparison with the golden.
Also: the stage and peer of a closed_by_peer audit line are written `(any)` (the side whose peer closed learns of it at
whichever step it had reached), and addresses are written 0xADDR.
"""
import re
import sys

REPORT = re.compile(r"^(=== (End )?Silica Actor Failure ===|actor_id:\s+\d+|agent_type_atom:\s+\S+|reason_tag:\s+\S+|"
                    r"supervisor_acb:\s+\S+|call_stack:|  #\d+  \S+|\[silica\] root actor exited \(no supervisor\))\s*$")
REASON = re.compile(r"^reason:\s+(.*?)\s*$")
BENIGN = {":normal", "(:explicit, :link_lost)", "(:explicit, :link_unavailable)"}
CLOSED = re.compile(r"^(\[tempus audit\] closed_by_peer) peer=\S+ stage [a-z]+")


def clean(text):
    out, other, last = [], [], []
    for ln in text.split("\n"):
        if ln.startswith("exit="):
            last.append(ln)
            continue
        m = REASON.match(ln)
        if m:
            if m.group(1) not in BENIGN:
                other.append("runtime report: an actor ended with reason " + m.group(1))
            continue
        if REPORT.match(ln) or not ln.strip():
            continue
        ln = re.sub(r"0x[0-9a-f]{6,}", "0xADDR", ln)
        out.append(CLOSED.sub(r"\1 peer=(any) stage (any)", ln))
    return "\n".join(out + sorted(other) + last) + "\n"


def main(argv):
    for path in argv[1:]:
        with open(path) as f:
            text = f.read()
        with open(path, "w") as f:
            f.write(clean(text))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
