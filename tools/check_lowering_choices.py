#!/usr/bin/env python3
"""Validate a BEES lowering-choices file (contract/conformance/lowering-choices.md).

    check_lowering_choices.py FILE...        exit 0 when every file is valid, 1 otherwise;
                                             errors go to stderr as FILE:LINE: message
    check_lowering_choices.py --template     print a valid file with every entry set to its first choice
    check_lowering_choices.py --requirements print the table of entries, their choices and keys

Importable: `check(text) -> list of (line, message)` for a generator that wants to validate its own file.
Python 3, standard library only.

Format (line oriented; `#` starts a comment; blank lines are ignored):

    lowering-choices 1                      first line, the format version
    target-contract <token>                 the contract version targeted (A1.4)
    compiler <name> <version>               who wrote the file
    <requirement id> <choice> [key=value ...] [-- note]

One entry for every requirement id in REQUIREMENTS, each exactly once, in any order. A choice must be
one of the listed ones. `other` and `not-applicable` need a note (`-- why`). Keys are listed per
requirement; a key marked required must be present, and any key not listed is an error.
"""
import re
import sys

FORMAT_VERSION = "1"
INT = "int"      # a non-negative decimal integer
RELEASE = ("release_on_return", "keep_last_message", "track_recent_peak", "release_when_idle", "keep_high_water")
RESTART = ("permanent", "transient", "temporary")
STRATEGY = ("one_for_one", "one_for_all", "rest_for_one")

# id -> (title, {choice: {key: (required, allowed values or INT)}})
REQUIREMENTS = {
    "A3.2": ("stack reserve for spawned actors", {
        "lowered": {"reserve": (True, INT), "release": (True, RELEASE)},
        "default": {"release": (True, RELEASE)},
    }),
    "A3.3": ("suspension points (code that waits in the middle of a function)", {
        "phase-field": {}, "continuation-table": {}, "not-applicable": {}, "other": {},
    }),
    "A3.4": ("yield points in long computations", {
        "back-edge": {}, "budget-counter": {"budget": (False, INT)}, "none": {}, "other": {},
    }),
    "A4.2": ("child-id scheme and supervisor tree", {
        "single-pool": {"pool-size": (True, INT)},
        "pool-tree": {"fanout": (True, INT), "leaf-size": (True, INT)},
        "other": {},
    }),
    "A4.3": ("supervisor shape", {
        "one-per-shape": {}, "uniform-shape": {}, "other": {},
    }),
    "A4.4": ("restart policy and strategy", {
        "chosen": {"restart": (True, RESTART), "strategy": (True, STRATEGY)},
    }),
    "A5.1": ("recoverable-error constructs", {
        "result-values": {}, "result-variants": {}, "mixed": {}, "rejected": {}, "not-applicable": {},
    }),
    "A5.4": ("send to a dead recipient", {
        "proxy": {}, "liveness-check": {}, "accept-sender-death": {}, "not-applicable": {}, "other": {},
    }),
    "A5.5": ("links and exit requests between actors", {
        "silica-link": {}, "supervisor-request": {}, "not-supported": {}, "other": {},
    }),
    "A6.8": ("byte-level and bit-level operations", {
        "lookup-tables": {}, "not-supported": {}, "other": {},
    }),
    "A7.1": ("calls by name and through function values", {
        "module-table": {}, "own-dispatch": {}, "not-applicable": {},
    }),
}
NEEDS_NOTE = ("other", "not-applicable")
WORD = re.compile(r"[A-Za-z0-9_.\-]+")


def check(text):
    """-> list of (line number, message); empty when the file is valid."""
    errors = []
    seen = {}
    header = []
    for n, raw in enumerate(text.split("\n"), 1):
        body = raw.split("#", 1)[0].strip()
        if not body:
            continue
        note = None
        if " -- " in body:
            body, note = body.split(" -- ", 1)
            note = note.strip()
            body = body.strip()
        words = body.split()
        if not header:
            header.append(n)
            if words != ["lowering-choices", FORMAT_VERSION]:
                errors.append((n, f"the first line must be `lowering-choices {FORMAT_VERSION}`"))
            continue
        head = words[0]
        if head == "target-contract":
            if len(words) != 2 or not WORD.fullmatch(words[1]):
                errors.append((n, "target-contract takes one token"))
            seen["target-contract"] = n
            continue
        if head == "compiler":
            if len(words) != 3 or not all(WORD.fullmatch(w) for w in words[1:]):
                errors.append((n, "compiler takes a name and a version, each one token"))
            seen["compiler"] = n
            continue
        if head not in REQUIREMENTS:
            errors.append((n, f"unknown requirement id {head}"))
            continue
        if head in seen:
            errors.append((n, f"{head} is listed twice (first on line {seen[head]})"))
            continue
        seen[head] = n
        title, choices = REQUIREMENTS[head]
        if len(words) < 2:
            errors.append((n, f"{head} needs a choice: one of {', '.join(choices)}"))
            continue
        choice = words[1]
        if choice not in choices:
            errors.append((n, f"{head}: `{choice}` is not a choice; use one of {', '.join(choices)}"))
            continue
        if choice in NEEDS_NOTE and not note:
            errors.append((n, f"{head} {choice} needs a note (`-- why`)"))
        keys = choices[choice]
        given = {}
        for kv in words[2:]:
            if "=" not in kv:
                errors.append((n, f"{head}: `{kv}` is not key=value"))
                continue
            k, v = kv.split("=", 1)
            if k not in keys:
                errors.append((n, f"{head} {choice}: unknown key `{k}`" + (f" (allowed: {', '.join(keys)})" if keys else " (no keys allowed)")))
            elif k in given:
                errors.append((n, f"{head}: key `{k}` given twice"))
            else:
                given[k] = v
                want = keys[k][1]
                if want == INT:
                    if not v.isdigit():
                        errors.append((n, f"{head}: `{k}` must be a non-negative integer, not `{v}`"))
                elif v not in want:
                    errors.append((n, f"{head}: `{k}` must be one of {', '.join(want)}, not `{v}`"))
        for k, (required, _) in keys.items():
            if required and k not in given:
                errors.append((n, f"{head} {choice}: key `{k}` is required"))
    if not header:
        errors.append((1, "the file is empty; the first line must be `lowering-choices " + FORMAT_VERSION + "`"))
    for k in ("target-contract", "compiler"):
        if k not in seen:
            errors.append((0, f"missing `{k}` line"))
    for rid in REQUIREMENTS:
        if rid not in seen:
            errors.append((0, f"missing entry for {rid} ({REQUIREMENTS[rid][0]})"))
    return sorted(errors)


def template():
    out = ["lowering-choices " + FORMAT_VERSION, "target-contract TOKEN", "compiler NAME VERSION"]
    for rid, (title, choices) in REQUIREMENTS.items():
        choice, keys = next(iter(choices.items()))
        parts = [rid, choice]
        for k, (required, want) in keys.items():
            if required:
                parts.append(f"{k}={'0' if want == INT else want[0]}")
        line = " ".join(parts)
        if choice in NEEDS_NOTE:
            line += " -- why"
        out.append(f"{line}    # {title}")
    return "\n".join(out) + "\n"


def requirements():
    out = []
    for rid, (title, choices) in REQUIREMENTS.items():
        out.append(f"{rid}  {title}")
        for choice, keys in choices.items():
            ks = ", ".join(f"{k}{'' if req else '?'}={'int' if w == INT else '|'.join(w)}" for k, (req, w) in keys.items())
            out.append(f"    {choice}" + (f"  [{ks}]" if ks else "") + ("  (needs a note)" if choice in NEEDS_NOTE else ""))
    return "\n".join(out) + "\n"


def main(argv):
    if len(argv) == 2 and argv[1] == "--template":
        sys.stdout.write(template())
        return 0
    if len(argv) == 2 and argv[1] == "--requirements":
        sys.stdout.write(requirements())
        return 0
    if len(argv) < 2 or argv[1].startswith("-"):
        print(__doc__, file=sys.stderr)
        return 2
    rc = 0
    for path in argv[1:]:
        try:
            with open(path) as fh:
                text = fh.read()
        except OSError as e:
            print(f"{path}: {e}", file=sys.stderr)
            rc = 1
            continue
        for n, msg in check(text):
            print(f"{path}:{n}: {msg}" if n else f"{path}: {msg}", file=sys.stderr)
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv))
