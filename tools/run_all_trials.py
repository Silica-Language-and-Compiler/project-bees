#!/usr/bin/env python3
"""Run every BEES trial in parallel on this machine, and on the remote machines of .bees_build_hosts. See tools/README.md.

    tools/run_all_trials.sh [-j N] [--compile-jobs N] [--only a,b] [--log-dir DIR] [--local-only | --remote | --no-remote]
                            [--hosts-file FILE] [--skip-native] [--no-kit] [--leaf-timeout SEC] [--list] [--dry-run]

Local: `make -C native` once, then `make -C trials/LEAF integrate` for every leaf, at most N at a time (default: cores minus one;
BEES_JOBS). The Silica compiler inside those runs is limited separately to --compile-jobs concurrent compiles (default 2,
BEES_COMPILE_JOBS) through tools/with_slot.py, because compiling a big unit is what takes memory. Each leaf's output is its own log
LOG_DIR/PLATFORM_ID/LEAF.log. Remote: for each line of .bees_build_hosts whose platform's build is supported (tools/platform_id.py),
the tree is synced, the remote runs this script with --local-only, and its logs and that platform's goldens come back. A platform
whose build is not supported yet is reported SKIPPED with the reason. One summary table is printed; the exit status is 0 only when
every trial that ran passed (a SKIPPED platform does not fail the run; a trial that could not run, or a remote that could not be
reached, does).
"""
import concurrent.futures
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import platform_id as P  # noqa: E402

HOSTS_FILE = ".bees_build_hosts"
# the NAME=VALUE tokens of a hosts line's notes that are passed to the remote run's environment
ENV_ALLOWED = ("SILICA_COMPILER", "SILICA_ROOT", "BEES_COMPILE_JOBS", "SILICA_COMPILE_TIMEOUT", "BEES_PATH_PREFIX")
SECRET_WORDS = re.compile(r"password|passwd|passphrase|BEGIN [A-Z ]*PRIVATE KEY|secret|token", re.I)
CONN = re.compile(r"^[A-Za-z0-9._-]+@[A-Za-z0-9._-]+$")

# What is not copied to a remote machine (modelled on silica's programmer_tools/sync_excludes.sh): built artifacts, a run's
# transient files, this machine's build directories, the checkout's own state. Sources, goldens, Makefiles, manifests, certificates
# travel. Built trial executables (no extension) are covered by "trials/*/*" anchored patterns written by exe_excludes().
SYNC_EXCLUDES = [
    "*.o", "*.a", "*.so", "*.dylib", "*.sams", "*.iface", "*.sout", "*.cur_fail", "*.checked", ".integrate*", ".integrate_counts",
    "__pycache__", "silica.config", "silica.link", "silica.atoms", "silica.shapes", "silica.needs_runtime", "silica.compile.*",
    "__silica_runtime.*", ".fail/", "*.tmp", "*.silica.derived", ".DS_Store", "*.raw", "*.rusage",
    "/native/build/", "/native/dangerous_exposure_source/lib/", "/native/dangerous_exposure_source/sockets",
    "/trial_runs/", "/.git/", "/.claude/", "/.bees_build_hosts", "/erl_crash.dump",
    # written mode 000 by trials/n3_trust on each machine (a whitelist that cannot be read): rsync cannot open it and would end with 23
    "unreadable_whitelist.config",
]


def sh(cmd):
    return " ".join(shlex.quote(c) for c in cmd)


class Host:
    def __init__(self, platform, conn, path, openssl, jobs, notes, line_no):
        self.platform, self.conn, self.path, self.openssl, self.jobs, self.notes, self.line_no = platform, conn, path, openssl, jobs, notes, line_no

    def env(self):
        out = {}
        for tok in self.notes.split():
            if "=" in tok and tok.split("=", 1)[0] in ENV_ALLOWED:
                k, v = tok.split("=", 1)
                out[k] = v
        if self.openssl != "-":
            out["OPENSSL_PREFIX"] = self.openssl
        return out


def read_hosts(path):
    """The lines of a hosts file: PLATFORM_ID USER@HOST REMOTE_PATH OPENSSL_PREFIX JOBS [NOTES...]; '-' for no OpenSSL prefix or no limit.
    Raises ValueError, naming the line, for anything wrong, and for anything that looks like a key or a password."""
    hosts = []
    with open(path) as f:
        for n, raw in enumerate(f, 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if SECRET_WORDS.search(line):
                raise ValueError(f"{path}:{n}: the file must hold no keys, passwords or tokens (ssh is key-based, batch mode only)")
            f_ = line.split(None, 5)
            if len(f_) < 5:
                raise ValueError(f"{path}:{n}: expected PLATFORM_ID USER@HOST REMOTE_PATH OPENSSL_PREFIX JOBS [NOTES]")
            plat, conn, rpath, ossl, jobs = f_[:5]
            notes = f_[5] if len(f_) > 5 else ""
            if plat not in P.PLATFORMS:
                raise ValueError(f"{path}:{n}: unknown platform id {plat} (known: {', '.join(P.PLATFORMS)})")
            if not CONN.match(conn):
                raise ValueError(f"{path}:{n}: {conn!r} is not user@host")
            if not rpath.startswith(("/", "~")):
                raise ValueError(f"{path}:{n}: the remote path must be absolute or start with ~")
            if jobs != "-" and not jobs.isdigit():
                raise ValueError(f"{path}:{n}: jobs must be a number or -")
            hosts.append(Host(plat, conn, rpath, ossl, jobs, notes, n))
    return hosts


def leaves(root=ROOT, only=None):
    out = sorted(d for d in os.listdir(os.path.join(root, "trials")) if os.path.isfile(os.path.join(root, "trials", d, "Makefile")))
    if only:
        bad = [o for o in only if o not in out]
        if bad:
            raise SystemExit(f"run_all_trials: no such trial: {', '.join(bad)}")
        out = [o for o in out if o in only]
    return out


def leaf_platforms(leaf, root=ROOT):
    """The platforms a trial is declared for: the ids in trials/LEAF/platforms (whitespace separated, # comments), or None when the
    trial has no such file and so is for every platform that builds. A declared platform list is the one way a trial says it cannot
    run on a platform (a missing toolchain, say); a trial run on a platform it is not declared for is reported N/A, by name and with
    the reason (the file's comments), never as a pass and never skipped silently. An unknown id in the file is an error."""
    f = os.path.join(root, "trials", leaf, "platforms")
    if not os.path.isfile(f):
        return None
    with open(f) as fh:
        text = fh.read()
    ids = " ".join(line.split("#", 1)[0] for line in text.splitlines()).split()
    bad = [i for i in ids if i not in P.PLATFORMS]
    if bad or not ids:
        raise SystemExit(f"run_all_trials: {f}: {'unknown platform id ' + ', '.join(bad) if bad else 'no platform id'} (known: {', '.join(P.PLATFORMS)})")
    return ids


def not_applicable_reason(leaf, pid, root=ROOT):
    """None when the trial runs on pid, else the sentence the table prints."""
    ids = leaf_platforms(leaf, root)
    if ids is None or pid in ids:
        return None
    return f"declared only for {', '.join(ids)} (trials/{leaf}/platforms)"


def unsupported_reason(pid):
    return f"the {pid} build is not supported yet (tools/platform_id.py PLATFORMS)"


class Row:
    def __init__(self, platform, trial, status, passed="-", failed="-", secs=None, log="", note=""):
        self.platform, self.trial, self.status, self.passed, self.failed, self.secs, self.log, self.note = platform, trial, status, passed, failed, secs, log, note

    def as_dict(self):
        return dict(self.__dict__)


def make_vars(env):
    """Variables a make run takes on its COMMAND LINE. tools/silica.mk honours SILICA_COMPILER only from there (an exported
    SILICA_COMPILER of the shell, set for work in the Silica tree, must not choose BEES's compiler by accident), so the one given to
    this runner, in its environment or through a hosts line's notes, is handed on as a make argument; sub-makes inherit it."""
    c = env.get("SILICA_COMPILER")
    return [f"SILICA_COMPILER={c}"] if c else []


def run_leaf(pid, leaf, log_dir, env, timeout):
    log = os.path.join(log_dir, f"{leaf}.log")
    leaf_dir = os.path.join(ROOT, "trials", leaf)
    counts = os.path.join(leaf_dir, ".integrate_counts")
    if os.path.exists(counts):
        os.remove(counts)
    t0 = time.monotonic()
    with open(log, "w") as lf:
        lf.write(f"$ make -C trials/{leaf} integrate {' '.join(make_vars(env))}  (platform {pid})\n")
        lf.flush()
        p = subprocess.Popen(["make", "-C", leaf_dir, "integrate"] + make_vars(env), stdout=lf, stderr=subprocess.STDOUT, env=env, start_new_session=True)
        try:
            rc = p.wait(timeout=timeout)
            note = ""
        except subprocess.TimeoutExpired:
            os.killpg(p.pid, signal.SIGKILL)
            p.wait()
            rc, note = -9, f"killed after {timeout}s"
            lf.write(f"\n[run_all_trials] killed after {timeout}s\n")
    secs = time.monotonic() - t0
    passed = failed = "-"
    if os.path.exists(counts):
        try:
            a, b = open(counts).read().split()
            passed, failed = a, b
        except ValueError:
            pass
    status = "PASS" if rc == 0 and failed in ("0", "-") else "FAIL"
    if rc != 0 and passed == "-":
        note = note or "did not finish (build failed or no result)"
    return Row(pid, leaf, status, passed, failed, secs, log, note)


def run_step(cmd, log, cwd=ROOT, env=None):
    with open(log, "a") as lf:
        lf.write(f"$ {sh(cmd) if isinstance(cmd, list) else cmd}\n")
        lf.flush()
        return subprocess.call(cmd, cwd=cwd, stdout=lf, stderr=subprocess.STDOUT, env=env, shell=isinstance(cmd, str))


def local_run(args, pid, log_dir, rows, lock):
    """Everything this machine runs: native once, the leaves in parallel, the kit."""
    os.makedirs(log_dir, exist_ok=True)
    env = dict(os.environ)
    env["BEES_COMPILE_SLOTS"] = str(args.compile_jobs)
    env["BEES_SLOT_DIR"] = os.path.join(log_dir, ".slots")
    env["BEES_PLATFORM_ID"] = pid
    boot = os.path.join(log_dir, "_setup.log")
    open(boot, "w").close()
    steps = []
    if not args.skip_native:
        steps.append(("native", ["make", "-C", os.path.join(ROOT, "native")]))
    steps.append(("check-compiler", ["make", "-s", "-C", ROOT, "check-compiler"] + make_vars(env)))
    for name, cmd in steps:
        if args.dry_run:
            print(f"  [dry-run] {sh(cmd)}")
            continue
        if run_step(cmd, boot, env=env) != 0:
            with lock:
                rows.append(Row(pid, f"({name})", "FAIL", log=boot, note=f"{name} failed; see the log"))
            return
    names = leaves(only=args.only)
    times_file = os.path.join(ROOT, "trial_runs", "timings.json")   # the last run's seconds per trial: longest first next time
    try:
        with open(times_file) as tf:
            times = json.load(tf)
    except (OSError, ValueError):
        times = {}
    for n in [n for n in names if not_applicable_reason(n, pid)]:
        names.remove(n)
        if not args.dry_run:
            with lock:
                rows.append(Row(pid, n, "N/A", note=not_applicable_reason(n, pid)))
            print(f"[{pid}] N/A  {n:28} {not_applicable_reason(n, pid)}", flush=True)
        else:
            print(f"  [dry-run] trials/{n}: N/A on {pid}: {not_applicable_reason(n, pid)}")
    names.sort(key=lambda n: -times.get(pid + "/" + n, 0))   # the slowest first: the short ones fill the gaps at the end
    if args.dry_run:
        for n in names:
            print(f"  [dry-run] make -C trials/{n} integrate {' '.join(make_vars(env))}  > {os.path.join(log_dir, n + '.log')}   (at most {args.jobs} at a time)")
        if not args.no_kit:
            print("  [dry-run] make kit")
        return
    print(f"[{pid}] {len(names)} trials, {args.jobs} at a time, {args.compile_jobs} compiles at a time, logs in {log_dir}", flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as ex:
        futs = {ex.submit(run_leaf, pid, n, log_dir, env, args.leaf_timeout): n for n in names}
        for fu in concurrent.futures.as_completed(futs):
            r = fu.result()
            with lock:
                rows.append(r)
            print(f"[{pid}] {r.status:4} {r.trial:28} {r.passed}/{r.failed} {r.secs:6.1f}s", flush=True)
            times[pid + "/" + r.trial] = r.secs
    try:
        os.makedirs(os.path.dirname(times_file), exist_ok=True)
        with open(times_file, "w") as tf:
            json.dump(times, tf)
    except OSError:
        pass
    if not args.no_kit:
        klog = os.path.join(log_dir, "kit.log")
        open(klog, "w").close()
        t0 = time.monotonic()
        rc = run_step(["make", "-C", ROOT, "kit"], klog, env=env)
        with lock:
            rows.append(Row(pid, "kit", "PASS" if rc == 0 else "FAIL", secs=time.monotonic() - t0, log=klog))


def remote_run(args, h, log_dir, rows, lock, stamp):
    """Sync, run there with --local-only, pull logs and goldens back; every step a command (printed, not run, with --dry-run)."""
    pid = h.platform
    os.makedirs(log_dir, exist_ok=True)
    log = os.path.join(log_dir, "_remote.log")
    open(log, "w").close()
    rpath = h.path
    remote_logs = f"trial_runs/{stamp}"
    ssh = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", h.conn]
    excl = [x for e in SYNC_EXCLUDES for x in ("--exclude", e)] + [x for e in exe_excludes() for x in ("--exclude", e)]
    jobs = h.jobs if h.jobs != "-" else str(args.jobs)
    renv = h.env()
    prefix = renv.pop("BEES_PATH_PREFIX", "")   # directories put before the remote's PATH (a programmer's Erlang/OTP under the home directory)
    envs = " ".join(f"{k}={shlex.quote(v)}" for k, v in renv.items()) + (f' PATH={shlex.quote(prefix)}:"$PATH"' if prefix else "")
    inner = (f"cd {rpath} && {envs} tools/run_all_trials.sh --local-only -j {jobs} --log-dir {remote_logs}"
             + (f" --only {','.join(args.only)}" if args.only else "") + (" --no-kit" if args.no_kit else ""))
    gold = ["rsync", "-a", "--update", "-e", "ssh -o BatchMode=yes", "--include", "*/", "--include", f"*.{pid}.scout", "--include", f"*.{pid}.golden_fail",
            "--exclude", "*", f"{h.conn}:{rpath}/trials/", os.path.join(ROOT, "trials") + "/"]
    cmds = [
        ("ssh check", ssh + ["true"]),
        ("sync", ["rsync", "-a", "--delete", "-e", "ssh -o BatchMode=yes"] + excl + [ROOT + "/", f"{h.conn}:{rpath}/"]),
        ("run", ssh + [inner]),
        ("pull logs", ["rsync", "-a", "-e", "ssh -o BatchMode=yes", f"{h.conn}:{rpath}/{remote_logs}/{pid}/", log_dir + "/"]),
        ("pull goldens", gold),
    ]
    if args.dry_run or args.list:
        for name, c in cmds:
            print(f"  [dry-run] {pid} {name}: {sh(c)}")
        return
    print(f"[{pid}] remote {h.conn}:{rpath}", flush=True)
    for name, c in cmds:
        rc = run_step(c, log)
        if name == "run":
            run_rc = rc
            continue   # a failing trial is a result, read from results.json below
        if rc != 0:
            with lock:
                rows.append(Row(pid, f"({name})", "FAIL", log=log, note=f"{name} failed on {h.conn} (exit {rc}); see {log}"))
            return
    try:
        res = json.load(open(os.path.join(log_dir, "results.json")))
        for d in res["rows"]:
            d["log"] = os.path.join(log_dir, os.path.basename(d.get("log", "")))
            with lock:
                rows.append(Row(**d))
    except (OSError, ValueError, KeyError, TypeError):
        with lock:
            rows.append(Row(pid, "(run)", "FAIL", log=log, note=f"no results.json came back from {h.conn} (run exit {run_rc})"))


def exe_excludes():
    """Anchored excludes for built trial executables (an executable file whose name has no dot, under trials/)."""
    out = []
    base = os.path.join(ROOT, "trials")
    for dp, dn, fn in os.walk(base):
        for f in fn:
            if "." not in f and os.access(os.path.join(dp, f), os.X_OK) and not os.path.islink(os.path.join(dp, f)):
                out.append("/" + os.path.relpath(os.path.join(dp, f), ROOT))
    return [re.sub(r"([\[\]*?\\])", r"\\\1", x) for x in out]


def table(rows, skipped):
    head = ("PLATFORM", "TRIAL", "STATUS", "PASSED", "FAILED", "SECONDS", "LOG / NOTE")
    data = [head]
    for r in sorted(rows, key=lambda r: (r.platform, r.status in ("PASS", "N/A"), r.trial)):
        data.append((r.platform, r.trial, r.status, str(r.passed), str(r.failed), "-" if r.secs is None else f"{r.secs:.1f}",
                     (r.note + " " if r.note else "") + os.path.relpath(r.log, ROOT) if r.log else r.note))
    for pid, why in skipped:
        data.append((pid, "(all)", "SKIPPED", "-", "-", "-", why))
    w = [max(len(row[i]) for row in data) for i in range(6)]
    lines = ["  ".join(c.ljust(w[i]) for i, c in enumerate(row[:6])) + "  " + row[6] for row in data]
    return "\n".join(lines)


def totals(rows, skipped):
    out = []
    plats = sorted({r.platform for r in rows} | {p for p, _ in skipped})
    for pid in plats:
        rs = [r for r in rows if r.platform == pid]
        if not rs:
            out.append(f"{pid:20} SKIPPED")
            continue
        na = sum(1 for r in rs if r.status == "N/A")
        rs = [r for r in rs if r.status != "N/A"]
        ok = sum(1 for r in rs if r.status == "PASS")
        out.append(f"{pid:20} {ok} of {len(rs)} trials passed" + ("" if ok == len(rs) else f", {len(rs) - ok} FAILED") + (f"; {na} N/A (declared for other platforms)" if na else ""))
    return "\n".join(out)


def parse(argv):
    import argparse
    ap = argparse.ArgumentParser(prog="run_all_trials.sh", description=__doc__.split("\n\n")[0])
    cores = os.cpu_count() or 2
    ap.add_argument("-j", "--jobs", type=int, default=int(os.environ.get("BEES_JOBS", max(1, cores - 1))), help="trials at a time on a machine (default cores-1, BEES_JOBS)")
    ap.add_argument("--compile-jobs", type=int, default=int(os.environ.get("BEES_COMPILE_JOBS", 2)), help="Silica compiles at a time on a machine (default 2, BEES_COMPILE_JOBS)")
    ap.add_argument("--only", type=lambda s: [x for x in s.split(",") if x], default=[], help="comma-separated trial names")
    ap.add_argument("--log-dir", default=None)
    ap.add_argument("--hosts-file", default=os.environ.get("BEES_BUILD_HOSTS", os.path.join(ROOT, HOSTS_FILE)))
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--remote", action="store_true", help="also run the machines of the hosts file (the default when the file exists)")
    g.add_argument("--no-remote", "--local-only", dest="no_remote", action="store_true", help="this machine only")
    ap.add_argument("--skip-native", action="store_true", help="do not run make -C native first")
    ap.add_argument("--no-kit", action="store_true", help="do not run make kit after the trials")
    ap.add_argument("--leaf-timeout", type=int, default=int(os.environ.get("BEES_LEAF_TIMEOUT", 3600)))
    ap.add_argument("--list", action="store_true", help="print what would run and stop")
    ap.add_argument("--dry-run", action="store_true", help="print every command instead of running it")
    a = ap.parse_args(argv)
    if a.jobs < 1 or a.compile_jobs < 1:
        ap.error("-j and --compile-jobs must be at least 1")
    return a


def main(argv):
    args = parse(argv[1:])
    here = P.current_id()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    root_logs = os.path.join(ROOT, "trial_runs")
    log_root = args.log_dir or os.path.join(root_logs, stamp)
    if not os.path.isabs(log_root):
        log_root = os.path.join(ROOT, log_root)
    hosts = []
    if not args.no_remote and (args.remote or os.path.exists(args.hosts_file)):
        if not os.path.exists(args.hosts_file):
            print(f"run_all_trials: --remote but {args.hosts_file} does not exist (copy .bees_build_hosts.example)", file=sys.stderr)
            return 2
        try:
            hosts = read_hosts(args.hosts_file)
        except ValueError as e:
            print("run_all_trials:", e, file=sys.stderr)
            return 2
    skipped = []
    local_ok = P.build_supported(here)
    if not local_ok:
        skipped.append((here, unsupported_reason(here)))
    remote_ok = []
    for h in hosts:
        if P.build_supported(h.platform):
            remote_ok.append(h)
        else:
            skipped.append((h.platform, f"{h.conn}: " + unsupported_reason(h.platform)))
    names = leaves(only=args.only)
    print(f"this machine : {here}  ({'builds' if local_ok else 'SKIPPED: no build'})")
    print(f"trials       : {len(names)} in trials/  (-j {args.jobs}, {args.compile_jobs} compiles at a time)")
    for h in hosts:
        print(f"remote       : {h.platform:18} {h.conn}:{h.path}  " + ("will run" if P.build_supported(h.platform) else "SKIPPED (build unsupported)"))
    print(f"logs         : {log_root}")
    if args.list:
        for n in names:
            print(f"  trial {n}")
        for h in remote_ok:
            remote_run(args, h, os.path.join(log_root, h.platform), [], threading.Lock(), stamp)
        return 0
    rows, lock = [], threading.Lock()
    threads = []
    if args.dry_run:
        if local_ok:
            local_run(args, here, os.path.join(log_root, here), rows, lock)
        for h in remote_ok:
            remote_run(args, h, os.path.join(log_root, h.platform), rows, lock, stamp)
        for pid, why in skipped:
            print(f"  SKIPPED {pid}: {why}")
        return 0
    t0 = time.monotonic()
    for h in remote_ok:
        t = threading.Thread(target=remote_run, args=(args, h, os.path.join(log_root, h.platform), rows, lock, stamp))
        t.start()
        threads.append(t)
    if local_ok:
        local_run(args, here, os.path.join(log_root, here), rows, lock)
    for t in threads:
        t.join()
    wall = time.monotonic() - t0
    local_rows = [r for r in rows if r.platform == here]
    os.makedirs(os.path.join(log_root, here), exist_ok=True)
    with open(os.path.join(log_root, here, "results.json"), "w") as f:
        json.dump({"platform": here, "rows": [r.as_dict() for r in local_rows]}, f, indent=1)
    print()
    print(table(rows, skipped))
    print()
    print(totals(rows, skipped))
    bad = [r for r in rows if r.status not in ("PASS", "N/A")]
    print(f"wall time {wall:.0f}s; " + ("ALL PASSED" if not bad else f"{len(bad)} FAILED") + (f"; {len(skipped)} platform(s) SKIPPED" if skipped else ""))
    return 1 if bad or (not rows and not skipped) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
