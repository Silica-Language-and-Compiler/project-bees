#!/usr/bin/env python3
"""bees_interchange: the driver of the two-machine interchange trials (trials/x1_interchange_beam, trials/x2_interchange_trust).
A BEES node on THIS machine ("here": the machine the driver runs on, the Mac) and a BEES node, or a stock erl, on the REMOTE
machine of .bees_build_hosts ("there": the Linux box) talk to each other over the network. Python 3, standard library only, plus
ssh and rsync. See development-plan/spikes/X1-mac-linux-interchange.md and tools/README.md.

    tools/bees_interchange.py [--only TRIAL[,TRIAL]] [--scenario NAME[,NAME]] [--record] [--rebuild] [--no-probe]
                              [--hosts-file FILE] [--here-address IPV4] [--list]

    (no hosts file)   prints "interchange: skipped: no remote (...)" and exits 0: the trials need two machines
    --record          write the goldens from this run's outputs (only after reading them: NAME.sout beside the goldens)
    --rebuild         build every node again (otherwise a node whose inputs did not change since its last build is not rebuilt)
    --here-address A  THIS machine's IPv4 address as the remote machine can dial it (also BEES_INTERCHANGE_HERE_ADDRESS). Without
                      it (the default) the remote reaches this machine through ssh -R forwards. With it, ONLY the four scenarios
                      in which a BEES node there dials a BEES node here are run, DIRECTLY over the network, under the names
                      NAME_direct (there_dials_direct, there_calls_direct, there_wrong_pin_direct, there_unlisted_direct): the
                      listeners here bind every IPv4 interface, the nodes there dial A, no forward is opened, and a probe from
                      the remote to A is made and printed first. They have their own goldens (the listen address is part of the
                      output); the first run on a network that allows it shows MISSING until the NAME_direct.SIDE.sout files
                      are read and recorded with --record. The nodes are rebuilt for the other addresses when the option is
                      added or dropped
    --list            print the scenarios, their nodes, ports and network paths, and stop

The compiler: here, SILICA_COMPILER of the environment (handed to make as an argument, as tools/run_all_trials.py does); there, the
SILICA_COMPILER, SILICA_ROOT and OPENSSL_PREFIX of the hosts line. These trials are NOT part of `make integrate` or of
tools/run_all_trials.sh (their directories hold no leaf Makefile); `make interchange` at the root runs this script.

What it does: (1) one ssh master session to the remote machine (key-based, batch mode); everything else, the port forwards
included, travels in it; (2) a reachability probe of the ports that are dialed directly; (3) a random cookie for the run, written
mode 600 here; (4) rsync of the tree (the runner's exclude list); (5) on each machine, `make -C native` and the nodes that run on
that machine; (6) each scenario: forwards, the listening side, the dialing side, the outputs normalised and compared with
NAME.here.<platform id of this machine>.scout and NAME.there.<platform id of the remote>.scout; (7) the cookie removed on both
machines, the forwards cancelled, the session closed, a check that no process of the trials is left on the remote.

Network paths (the remote machine has a public address; this machine is behind address translation, so the remote cannot dial it):
    direct    a node here dials the remote machine's public address; the listener there binds every IPv4 interface (the language's
              carrier binds 127.0.0.1 or every interface, nothing between) for the seconds the scenario runs
    -R        a node there dials 127.0.0.1:PORT on its own machine, which sshd forwards through the driver's ssh session to
              127.0.0.1:PORT here, where the listener binds 127.0.0.1 only
    -L        a node here dials 127.0.0.1:PORT, which ssh forwards to 127.0.0.1:PORT there
Every scenario with a stock erl node keeps erl and its EPMD on 127.0.0.1 and uses forwards only: a stock node is a remote shell
for whoever passes the cookie handshake, so it is never bound to a public address.
"""
import hashlib
import os
import re
import secrets
import shlex
import socket
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import n2_live as LIVE  # noqa: E402  (norm_bees, norm_stock: the normalisation of trials/n2_live, reused for the erl scenarios)
import platform_id as P  # noqa: E402
import run_all_trials as R  # noqa: E402
import trial_ports as T  # noqa: E402

X1 = "x1_interchange_beam"
X2 = "x2_interchange_trust"
TRIALS = (X1, X2)
NODE_TOOL = "tools/bees_interchange_node.py"
STAMP = ".interchange_stamp"
SAFE_PATH = re.compile(r"^[A-Za-z0-9._/~-]+$")

# the nodes each machine builds: trial -> side -> node directory -> its executables
NODES = {
    X1: {"here": {"hd": ["dangerous_hd"], "hl": ["dangerous_hl"], "el": ["dangerous_el"], "ed": ["dangerous_ed"]},
         "there": {"tl": ["dangerous_tl"], "td": ["dangerous_td"], "el": ["dangerous_el"], "ed": ["dangerous_ed"]}},
    X2: {"here": {"here": ["dangerous_here_serve", "dangerous_here_call"], "p": ["dangerous_p_pin"], "u": ["dangerous_u_unlisted"]},
         "there": {"there": ["dangerous_there_serve", "dangerous_there_call"], "p": ["dangerous_p_pin"], "u": ["dangerous_u_unlisted"]}},
}


def port(trial, offset):
    return T.port(trial, offset)


def other(side):
    return "there" if side == "here" else "here"


def scenarios(here_addr=None):
    """The scenarios, in running order. `forwards`: (kind, port) with kind L (here 127.0.0.1:port -> there 127.0.0.1:port) or
    R (there 127.0.0.1:port -> here 127.0.0.1:port); `direct`: the port on the remote machine that is dialed over the network;
    `direct_back`: the port on THIS machine that the remote dials over the network (only with here_addr, --here-address: the
    BEES-with-BEES scenarios of that direction then run without a forward, under the name NAME_direct)."""
    back = bool(here_addr)
    sfx = "_direct" if back else ""
    b0, b1, b10, b11, b90 = (port(X1, o) for o in (0, 1, 10, 11, 90))
    t0, t1 = port(X2, 0), port(X2, 1)
    out = [
        # ---- BEAM mode, BEES with BEES: the cookie handshake, a request answered each way over the one link
        dict(trial=X1, name="here_dials", kind="beam_pair", listener=("there", "tl", "dangerous_tl"), dialer=("here", "hd", "dangerous_hd"),
             direct=b0, forwards=[], path=f"direct: hd (here) dials THERE_HOST:{b0} by name; tl (there) listens on 0.0.0.0:{b0}"),
        dict(trial=X1, name="there_dials" + sfx, kind="beam_pair", listener=("here", "hl", "dangerous_hl"), dialer=("there", "td", "dangerous_td"),
             direct=None, direct_back=b1 if back else None, forwards=[] if back else [("R", b1)],
             path=(f"direct: td (there) dials HERE_IPV4:{b1}; hl (here) listens on 0.0.0.0:{b1}" if back else
                   f"ssh -R forward: td (there) dials 127.0.0.1:{b1} on its machine, carried to hl (here), which listens on 127.0.0.1:{b1}")),
        # ---- BEAM mode, BEES against a stock erl on the other machine (trials/n2_live's stock_dials and bees_dials)
        dict(trial=X1, name="erl_there_dials", kind="erl", fn="stock_dials", bees=("here", "el", "dangerous_el"), stock="there", direct=None,
             forwards=[("L", b90), ("R", b10)],
             path=f"ssh forwards: el (here) registers with the EPMD there through -L {b90}; the stock erl (there) dials 127.0.0.1:{b10} "
                  f"on its machine, carried by -R to el (here), which listens on 127.0.0.1:{b10}"),
        dict(trial=X1, name="erl_there_listens", kind="erl", fn="bees_dials", bees=("here", "ed", "dangerous_ed"), stock="there", direct=None,
             forwards=[("L", b90), ("L", b11)],
             path=f"ssh forwards: ed (here) asks the EPMD there through -L {b90} and dials localhost:{b11} here, carried by -L to the "
                  f"stock erl's listener on 127.0.0.1:{b11} there"),
        dict(trial=X1, name="erl_here_dials", kind="erl", fn="stock_dials", bees=("there", "el", "dangerous_el"), stock="here", direct=None,
             forwards=[("R", b90), ("L", b10)],
             path=f"ssh forwards: el (there) registers with the EPMD here through -R {b90}; the stock erl (here) dials 127.0.0.1:{b10} "
                  f"here, carried by -L to el (there), which listens on 127.0.0.1:{b10}"),
        dict(trial=X1, name="erl_here_listens", kind="erl", fn="bees_dials", bees=("there", "ed", "dangerous_ed"), stock="here", direct=None,
             forwards=[("R", b90), ("R", b11)],
             path=f"ssh forwards: ed (there) asks the EPMD here through -R {b90} and dials localhost:{b11} there, carried by -R to the "
                  f"stock erl's listener on 127.0.0.1:{b11} here"),
    ]
    direct_t = f"direct: the client (here) dials THERE_IPV4:{t0}; node there listens on 0.0.0.0:{t0}"
    fwd_t = (f"direct: the client (there) dials HERE_IPV4:{t1}; node here listens on 0.0.0.0:{t1}" if back else
             f"ssh -R forward: the client (there) dials 127.0.0.1:{t1} on its machine, carried to node here, which listens on 127.0.0.1:{t1}")
    for name, node, exe, done in (("calls", None, None, "scenario done"), ("wrong_pin", "p", "dangerous_p_pin", "pin done"),
                                  ("unlisted", "u", "dangerous_u_unlisted", "unlisted done")):
        # ---- TRUST over mutual TLS 1.3: a call set each way, a wrong pin each way, a certificate no whitelist lists each way
        out.append(dict(trial=X2, name=f"here_{name}", kind="trust_pair", server=("there", "there", "dangerous_there_serve"),
                        client=("here", node or "here", exe or "dangerous_here_call"), done=done, direct=t0, forwards=[], path=direct_t))
        out.append(dict(trial=X2, name=f"there_{name}{sfx}", kind="trust_pair", server=("here", "here", "dangerous_here_serve"),
                        client=("there", node or "there", exe or "dangerous_there_call"), done=done, direct=None,
                        direct_back=t1 if back else None, forwards=[] if back else [("R", t1)], path=fwd_t))
    if back:
        # the other scenarios are the ordinary run's (and node here's client entry would print another listen address in this mode)
        out = [s for s in out if s.get("direct_back")]
    return out


# ---------------------------------------------------------------- normalisation (pure)
ROOT_EXIT = "[silica] root actor exited (no supervisor)\n"
# the audit block of a link going down and the reaper's line: where they land against the other lines follows when each program
# is stopped (trials/n2_multilink drops the same ones)
RACY = re.compile(r"link down, proxies ended|frames delivered|frames dropped|control messages counted|net ticks seen|^proxy ended")


def norm_text(lines, there_host, there_ip, here_ip=""):
    """What every output gets: the runtime's root-actor line removed wherever it lands (tools/silica.mk STRIP_ROOT_EXIT), runtime
    addresses to 0xADDR, the remote machine's name and address to THERE_HOST and THERE_IPV4 (a golden names no machine)."""
    text = "\n".join(lines) + "\n"
    text = text.replace(ROOT_EXIT, "")
    text = re.sub(r"0x[0-9a-f]{6,}", "0xADDR", text)
    if there_ip:
        text = text.replace(there_ip, "THERE_IPV4")
    if here_ip:
        text = text.replace(here_ip, "HERE_IPV4")
    if there_host:
        text = text.replace(there_host, "THERE_HOST")
    return [l for l in text.split("\n")]


def norm_beam_pair(lines, rc, marker, there_host="", there_ip="", here_ip=""):
    """A BEES node of a BEAM-mode pair: the racy link-down lines dropped, nothing kept after the marker line (what follows is the
    other node leaving, which races this program's own exit), the exit code kept."""
    out = []
    for l in norm_text(lines, there_host, there_ip, here_ip):
        if RACY.search(l):
            continue
        out.append(l)
        if marker in l:
            break
    while out and out[-1] == "":
        out.pop()
    return out + [f"exit={rc}"]


def norm_trust(lines, rc, there_host="", there_ip="", here_ip=""):
    out = norm_text(lines, there_host, there_ip, here_ip)
    while out and out[-1] == "":
        out.pop()
    return out + [f"exit={rc}"]


def norm_erl_bees(lines, rc, there_host="", there_ip=""):
    return LIVE.norm_bees([l for l in norm_text(lines, there_host, there_ip) if l != ""], rc)


def golden_path(trial, name, side, pid):
    return os.path.join(ROOT, "trials", trial, f"{name}.{side}.{pid}.scout")


# ---------------------------------------------------------------- processes
class Node:
    """A program started through tools/bees_interchange_node.py, here or over the ssh session; its lines are collected as they come."""

    def __init__(self, argv, label):
        self.label, self.lines, self.lock, self.rc, self.last = label, [], threading.Lock(), None, time.monotonic()
        self.p = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.t = threading.Thread(target=self._read, daemon=True)
        self.t.start()

    def _read(self):
        for raw in self.p.stdout:
            line = raw.decode("utf-8", "replace").rstrip("\n").rstrip("\r")
            with self.lock:
                if line.startswith("@exit="):
                    self.rc = line[len("@exit="):]
                else:
                    self.lines.append(line)
                    if line.strip() and ROOT_EXIT.strip() not in line:
                        self.last = time.monotonic()

    def has(self, text):
        with self.lock:
            return any(text in l for l in self.lines)

    def wait_for(self, text, timeout):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if self.has(text):
                return True
            if self.p.poll() is not None:
                self.t.join(2)
                return self.has(text)
            time.sleep(0.05)
        return False

    def wait_quiet(self, idle, timeout=30):
        end = time.monotonic() + timeout
        while time.monotonic() < end and self.p.poll() is None:
            with self.lock:
                if time.monotonic() - self.last >= idle:
                    return
            time.sleep(0.05)

    def send(self, line):
        try:
            self.p.stdin.write(line.encode() + b"\n")
            self.p.stdin.flush()
        except (BrokenPipeError, OSError):
            pass

    def quit(self, timeout=20):
        self.send("exit")
        return self.wait(timeout)

    def kill(self):
        self.send("@kill")
        return self.wait(20)

    def wait(self, timeout):
        try:
            self.p.wait(timeout)
        except subprocess.TimeoutExpired:
            self.send("@kill")
            try:
                self.p.wait(10)
            except subprocess.TimeoutExpired:
                self.p.kill()
            self.t.join(2)
            return "timeout"
        self.t.join(5)
        return self.rc if self.rc is not None else "lost"

    def stop(self):
        """for cleanup: end it whatever its state"""
        if self.p.poll() is None:
            self.send("@kill")
            try:
                self.p.wait(10)
            except subprocess.TimeoutExpired:
                self.p.kill()

    def text(self):
        self.t.join(2)
        with self.lock:
            out = list(self.lines)
        while out and out[-1] == "":
            out.pop()
        return out


class Machine:
    def __init__(self, side, pid, root, make_vars, ssh=None):
        self.side, self.pid, self.root, self.make_vars, self.ssh = side, pid, root, make_vars, ssh

    def argv(self, shell):
        """the argv that runs a shell command line in the tree's root on this machine"""
        if self.ssh:
            return self.ssh + [f"cd {self.root} && {shell}"]
        return ["bash", "-c", f"cd {shlex.quote(self.root)} && {shell}"]

    def run(self, shell, log=None, timeout=3600):
        r = subprocess.run(self.argv(shell), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=timeout)
        if log:
            with open(log, "a") as f:
                f.write(f"$ [{self.side}] {shell}\n{r.stdout}\n")
        return r.returncode, r.stdout

    def start(self, cwd, cmd, env=None, pipe=False, cap=300, label=""):
        parts = ["python3", NODE_TOOL, "--cwd", cwd, "--cap", str(cap)] + (["--pipe"] if pipe else [])
        for k, v in (env or {}).items():
            parts += ["--env", f"{k}={v}"]
        parts += ["--"] + cmd
        return Node(self.argv("exec " + " ".join(shlex.quote(x) for x in parts)), label or f"{self.side}:{cmd[0]}")


class Session:
    """The one ssh master session to the remote machine; every command, sync and forward of the run travels in it."""

    def __init__(self, conn):
        self.conn = conn
        self.dir = tempfile.mkdtemp(prefix="bees_x_")
        self.ctl = os.path.join(self.dir, "c")
        self.forwards = []

    def base(self):
        return ["ssh", "-S", self.ctl, "-o", "BatchMode=yes", self.conn]

    def open(self):
        r = subprocess.run(["ssh", "-M", "-S", self.ctl, "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", "-o", "ServerAliveInterval=15",
                            "-o", "ControlPersist=no", "-f", "-N", self.conn], capture_output=True, text=True)
        return r.returncode == 0, (r.stdout + r.stderr).strip()

    def _spec(self, kind, p):
        return [f"-{kind}", f"127.0.0.1:{p}:127.0.0.1:{p}"]

    def forward(self, kind, p):
        r = subprocess.run(["ssh", "-S", self.ctl, "-O", "forward"] + self._spec(kind, p) + [self.conn], capture_output=True, text=True)
        if r.returncode == 0:
            self.forwards.append((kind, p))
        return r.returncode == 0, (r.stdout + r.stderr).strip()

    def cancel_all(self):
        for kind, p in self.forwards:
            subprocess.run(["ssh", "-S", self.ctl, "-O", "cancel"] + self._spec(kind, p) + [self.conn], capture_output=True, text=True)
        self.forwards = []

    def close(self):
        subprocess.run(["ssh", "-S", self.ctl, "-O", "exit", self.conn], capture_output=True, text=True)
        try:
            os.rmdir(self.dir)
        except OSError:
            pass


# ---------------------------------------------------------------- build
def tree_hash(paths):
    h = hashlib.sha256()
    for top in paths:
        full = os.path.join(ROOT, top)
        files = []
        if os.path.isfile(full):
            files = [full]
        else:
            for dp, dn, fn in os.walk(full):
                dn[:] = sorted(d for d in dn if d not in ("__pycache__", "build", "lib") or dp != os.path.join(ROOT, "native"))
                files += [os.path.join(dp, f) for f in sorted(fn) if not f.endswith((".o", ".a", ".pyc", ".sout", ".raw", ".scout"))]
        for f in files:
            h.update(os.path.relpath(f, ROOT).encode() + b"\0")
            try:
                with open(f, "rb") as fh:
                    h.update(fh.read())
            except OSError:
                pass
            h.update(b"\0")
    return h.hexdigest()


NODE_INPUTS = re.compile(r"^(Makefile|.*\.in|node\..*|.*\.trust|trust_whitelist\.config)$")


def node_stamp(trial, node, machine, compiler_id):
    """What a node's build depends on: BEES's sources and generators, the roles, the node's own tracked files, the certificates,
    the make variables and the compiler of the machine that builds it."""
    common = ["src/inter_nodal", "src/shim", "src/trust", "native/src", "native/tls", "native/trust", "native/macos", "native/linux", "native/Makefile", "native/bees_platform.h",
              "tools/silica.mk", "tools/trial.mk", "tools/platform.mk", "tools/topo_silica_config.sh", "tools/bees_conf.py", "tools/bees_config.py",
              "tools/bees_config_beam.py", "tools/bees_config_trust.py", "tools/bees_edge_gen.py", "tools/bees_trust_gen.py", "tools/bees_dist_gen.py",
              "trials/n2_dist/roles", "trials/n2_live/roles", "trials/n4_trust_tls/roles", f"trials/{trial}/roles"]
    if trial == X2:
        common.append(f"trials/{trial}/certs")
    h = hashlib.sha256(tree_hash(common).encode())
    nd = os.path.join(ROOT, "trials", trial, "nodes", node)
    for f in sorted(os.listdir(nd)):
        if NODE_INPUTS.match(f) or (f == "bees.config" and not os.path.exists(os.path.join(nd, "bees.config.in"))):
            h.update(f.encode() + b"\0" + open(os.path.join(nd, f), "rb").read() + b"\0")
    h.update(" ".join(machine.make_vars).encode() + b"\0" + compiler_id.encode())
    return h.hexdigest()


def build_machine(machine, trials, compiler_id, rebuild, log, problems):
    vars_ = " ".join(shlex.quote(v) for v in machine.make_vars)
    steps = [f"make -C native {vars_}"]
    if X2 in trials:
        steps.append(f"make -C native tls {vars_} && grep -q '^ok ' native/build/tls.status")
    for s in steps:
        rc, _ = machine.run(s, log)
        if rc != 0:
            problems.append(f"[{machine.side}] `{s}` failed; see {log}")
            return
    for trial in trials:
        for node, exes in NODES[trial][machine.side].items():
            d = f"trials/{trial}/nodes/{node}"
            stamp = node_stamp(trial, node, machine, compiler_id)
            have = " && ".join(f"[ -x {d}/{e} ]" for e in exes)
            if not rebuild:
                rc, _ = machine.run(f'{have} && [ "$(cat {d}/{STAMP} 2>/dev/null)" = {stamp} ]')
                if rc == 0:
                    print(f"[{machine.side}] {trial}/{node}: up to date", flush=True)
                    continue
            t0 = time.monotonic()
            # `units` first: the node's Makefile writes bees.config and the root units while make reads it, and a make that has
            # already listed the directory does not see them (the reason the other node trials build twice); one retry for the
            # compiler's known transient crash
            rc, _ = machine.run(f"rm -f {d}/{STAMP}; make -C {d} units {vars_} >/dev/null 2>&1; "
                                f"(make -C {d} build {vars_} || make -C {d} build {vars_}) && {have} && echo {stamp} > {d}/{STAMP}", log)
            print(f"[{machine.side}] {trial}/{node}: {'built' if rc == 0 else 'BUILD FAILED'} in {time.monotonic() - t0:.0f}s", flush=True)
            if rc != 0:
                problems.append(f"[{machine.side}] {trial}/{node} did not build; see {log}")
                return


# ---------------------------------------------------------------- the run
class Run:
    def __init__(self, args, host):
        self.args, self.host = args, host
        self.there_host = host.conn.split("@", 1)[1]
        self.there_ip = ""
        self.here_addr = args.here_address or ""
        self.session = Session(host.conn)
        self.results = []      # (trial, scenario, side, platform, status, note)
        self.nodes = []        # every Node started, for cleanup
        self.cookie = None
        self.log_dir = os.path.join(ROOT, "trial_runs", "interchange-" + time.strftime("%Y%m%d-%H%M%S"))

    # ---- machines
    def machines(self):
        env = self.host.env()
        there_vars = [f"{k}={env[k]}" for k in ("SILICA_COMPILER", "SILICA_ROOT", "OPENSSL_PREFIX") if k in env]
        here_vars = R.make_vars(os.environ)
        if os.environ.get("OPENSSL_PREFIX"):
            here_vars.append("OPENSSL_PREFIX=" + os.environ["OPENSSL_PREFIX"])
        back = self.here_addr or "127.0.0.1"
        x = [f"X_THERE_HOST={self.there_host}", f"X_THERE_IP={self.there_ip}", f"X_HERE_HOST={back}",
             f"X_HERE_LISTEN={'0.0.0.0' if self.here_addr else '127.0.0.1'}"]
        self.here = Machine("here", P.current_id(), ROOT, here_vars + x + [f"X_SERVER={self.there_ip}:{port(X2, 0)}"])
        self.there = Machine("there", self.host.platform, self.host.path, there_vars + x + [f"X_SERVER={back}:{port(X2, 1)}"], self.session.base())
        self.m = {"here": self.here, "there": self.there}

    def start(self, side, cwd, cmd, **kw):
        n = self.m[side].start(cwd, cmd, **kw)
        self.nodes.append(n)
        return n

    # ---- setup
    def probe(self, ports):
        """Is PORT on the remote machine reachable from here over the network? A throwaway listener there for a few seconds, one
        connection from here. Printed; a blocked port fails the scenarios that dial it directly."""
        open_ = {}
        for p in ports:
            code = (f"import socket\ns=socket.socket();s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);s.bind(('0.0.0.0',{p}));s.listen(1);"
                    "s.settimeout(8);print('up',flush=True)\ntry:\n c,a=s.accept();print('from',a[0],flush=True)\nexcept OSError as e:\n print('none',e,flush=True)\n")
            pr = subprocess.Popen(self.session.base() + ["python3 -c " + shlex.quote(code)], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            first = pr.stdout.readline().strip()
            ok, seen = False, ""
            if first == "up":
                try:
                    socket.create_connection((self.there_ip, p), timeout=5).close()
                    ok = True
                except OSError as e:
                    seen = str(e)
                rest = pr.stdout.read().strip()
                seen = seen or rest
            else:
                seen = "the probe's listener did not start there: " + first + " " + pr.stdout.read().strip()
            pr.wait()
            open_[p] = ok
            print(f"reachability: here -> {self.there_host} ({self.there_ip}) port {p}: {'open, ' + seen.replace('from', 'seen there as coming from') if ok else 'BLOCKED (' + seen + ')'}", flush=True)
        return open_

    def probe_back(self, ports):
        """With --here-address: is PORT on THIS machine reachable from the remote at that address? A throwaway listener here on
        every IPv4 interface for a few seconds, one connection from the remote."""
        open_ = {}
        for p in ports:
            ls = socket.socket()
            ls.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            ok, seen = False, ""
            try:
                ls.bind(("0.0.0.0", p))
                ls.listen(1)
                ls.settimeout(8)
                code = f"import socket\ntry:\n socket.create_connection(({self.here_addr!r},{p}),timeout=5).close();print('connected')\nexcept OSError as e:\n print('failed:',e)\n"
                pr = subprocess.Popen(self.session.base() + ["python3 -c " + shlex.quote(code)], stdin=subprocess.DEVNULL,
                                      stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                try:
                    c, a = ls.accept()
                    c.close()
                    ok, seen = True, f"seen here as coming from {a[0]}"
                except OSError:
                    pass
                said = pr.communicate()[0].strip()
                seen = seen or f"the remote said: {said}"
            except OSError as e:
                seen = f"no listener here: {e}"
            finally:
                ls.close()
            open_[p] = ok
            print(f"reachability: there -> here ({self.here_addr}) port {p}: {'open, ' + seen if ok else 'BLOCKED (' + seen + ')'}", flush=True)
        return open_

    def write_cookie(self):
        self.cookie = secrets.token_hex(16)
        d = os.path.join(ROOT, "trials", X1)
        for name, text in (("cookie", self.cookie + "\n"), ("cookie_args", f"-setcookie {self.cookie}\n")):
            path = os.path.join(d, name)
            if os.path.exists(path):
                os.remove(path)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(text)

    def sync(self, log):
        mine = ["--include", "/trials/x[0-9]*_interchange_*/nodes/*/dangerous_exposure_source",
                "--exclude", "/trials/x[0-9]*_interchange_*/nodes/*/dangerous_*", "--exclude", "/trials/x[0-9]*_interchange_*/build/",
                "--exclude", STAMP]
        excl = [x for e in R.SYNC_EXCLUDES for x in ("--exclude", e)] + [x for e in R.exe_excludes() for x in ("--exclude", e)]
        cmd = ["rsync", "-a", "--delete", "-e", f"ssh -S {self.session.ctl} -o BatchMode=yes"] + mine + excl + [ROOT + "/", f"{self.host.conn}:{self.host.path}/"]
        return R.run_step(cmd, log)

    # ---- one scenario
    def exe(self, trial, node, exe):
        return f"trials/{trial}/nodes/{node}", [f"./{exe}"]

    def beam_pair(self, sc):
        ls, ln, le = sc["listener"]
        ds, dn, de = sc["dialer"]
        lm, dm = "lbox got op=ans n=68", "dialer: answered op=ans n=68"
        cwd, cmd = self.exe(sc["trial"], ln, le)
        lis = self.start(ls, cwd, cmd, cap=120)
        if not lis.wait_for("[bees] BEAM mode", 20):
            lis.stop()
            return {ls: (lis.text(), "no banner"), ds: ([], "not started")}, {ls: lm, ds: dm}
        time.sleep(1.0)   # the listener is bound right after the banner (the other node trials stagger by half a second)
        cwd, cmd = self.exe(sc["trial"], dn, de)
        dia = self.start(ds, cwd, cmd, cap=120)
        dia.wait_for(dm, 40)
        lis.wait_for(lm, 10)
        dia.wait_quiet(1.0)
        lis.wait_quiet(1.0)
        drc = dia.quit()
        lrc = lis.quit()
        return {ls: (lis.text(), lrc), ds: (dia.text(), drc)}, {ls: lm, ds: dm}

    def erl(self, sc):
        bs, bn, be = sc["bees"]
        ss = sc["stock"]
        trial = sc["trial"]
        epmd_port, dist = str(port(X1, 90)), str(port(X1, 11))
        tdir = f"trials/{trial}"
        rc, out = self.m[ss].run(f"mkdir -p {tdir}/build && erlc -o {tdir}/build trials/n2_live/stock_driver.erl")
        if rc != 0:
            return {bs: ([], "not started"), ss: (out.split("\n"), "erlc failed")}
        epmd = self.start(ss, tdir, ["epmd", "-port", epmd_port, "-address", "127.0.0.1"], pipe=True, cap=200, label="epmd")
        time.sleep(1.0)
        bees_name = "beesl@localhost" if sc["fn"] == "stock_dials" else "beesd@localhost"
        erl = ["erl", "-sname", "stock@localhost", "-start_epmd", "false", "-args_file", "cookie_args", "-kernel", "net_ticktime", LIVE.TICK,
               "-kernel", "inet_dist_use_interface", "{127,0,0,1}", "-kernel", "inet_dist_listen_min", dist, "-kernel", "inet_dist_listen_max", dist,
               "-pa", "build", "-noshell", "-eval", f"stock_driver:{sc['fn']}('{bees_name}'), halt()."]
        cwd, cmd = self.exe(trial, bn, be)
        if sc["fn"] == "stock_dials":
            b = self.start(bs, cwd, cmd, cap=180)
            ok = b.wait_for("epmd: registered", 20)
            s = self.start(ss, tdir, erl, env={"ERL_EPMD_PORT": epmd_port}, pipe=True, cap=180, label="erl")
            if ok and s.wait_for("KILL NOW", 90):
                brc = b.kill()
            else:
                brc = b.quit()
            src = s.wait(60)
        else:
            s = self.start(ss, tdir, erl, env={"ERL_EPMD_PORT": epmd_port}, pipe=True, cap=120, label="erl")
            s.wait_for("waiting in registered process inbox", 30)
            time.sleep(0.5)
            b = self.start(bs, cwd, cmd, cap=120)
            s.wait_for("stock: done", 60)
            src = s.wait(30)
            b.wait_quiet(1.0)
            brc = b.quit()
        epmd.stop()
        return {bs: (b.text(), brc), ss: (s.text(), src)}

    def trust_pair(self, sc):
        ss, sn, se = sc["server"]
        cs, cn, ce = sc["client"]
        cwd, cmd = self.exe(sc["trial"], sn, se)
        srv = self.start(ss, cwd, cmd, cap=120)
        if not srv.wait_for("[trust] listening on ", 20):
            rc = srv.quit() if srv.p.poll() is None else srv.wait(5)
            return {ss: (srv.text(), rc), cs: ([], "not started")}
        time.sleep(0.5)
        cwd, cmd = self.exe(sc["trial"], cn, ce)
        cli = self.start(cs, cwd, cmd, cap=120)
        cli.wait_for(sc["done"], 60)
        cli.wait_quiet(1.0)
        crc = cli.quit()
        srv.wait_quiet(1.0)
        src = srv.quit()
        return {ss: (srv.text(), src), cs: (cli.text(), crc)}

    def scenario(self, sc, direct_open):
        trial, name = sc["trial"], sc["name"]
        print(f"[{trial}] {name}: {sc['path']}", flush=True)
        if sc["direct"] and not direct_open.get(sc["direct"], True):
            for side in ("here", "there"):
                self.results.append((trial, name, side, self.m[side].pid, "FAIL", f"port {sc['direct']} on the remote machine is not reachable from here; not run"))
            return
        if sc.get("direct_back") and not direct_open.get(("back", sc["direct_back"]), True):
            for side in ("here", "there"):
                self.results.append((trial, name, side, self.m[side].pid, "FAIL", f"port {sc['direct_back']} of this machine is not reachable from the remote at "
                                     f"{self.here_addr}; not run (without --here-address this direction runs through an ssh -R forward)"))
            return
        for kind, p in sc["forwards"]:
            ok, why = self.session.forward(kind, p)
            if not ok:
                self.session.cancel_all()
                for side in ("here", "there"):
                    self.results.append((trial, name, side, self.m[side].pid, "FAIL", f"ssh -{kind} forward of port {p} refused: {why}"))
                return
        markers = {}
        try:
            if sc["kind"] == "beam_pair":
                outs, markers = self.beam_pair(sc)
            elif sc["kind"] == "erl":
                outs = self.erl(sc)
            else:
                outs = self.trust_pair(sc)
        finally:
            for n in self.nodes:
                n.stop()
            self.nodes = []
            self.session.cancel_all()
        tdir = os.path.join(ROOT, "trials", trial)
        for side in ("here", "there"):
            lines, rc = outs[side]
            if sc["kind"] == "beam_pair":
                normed = norm_beam_pair(lines, rc, markers[side], self.there_host, self.there_ip, self.here_addr)
            elif sc["kind"] == "erl":
                normed = norm_erl_bees(lines, rc, self.there_host, self.there_ip) if side == sc["bees"][0] else LIVE.norm_stock(lines, rc)
            else:
                normed = norm_trust(lines, rc, self.there_host, self.there_ip, self.here_addr)
            base = os.path.join(tdir, f"{name}.{side}")
            with open(base + ".raw", "w") as f:
                f.write("\n".join(lines) + f"\n@exit={rc}\n")
            with open(base + ".sout", "w") as f:
                f.write("\n".join(normed) + "\n")
            gold = golden_path(trial, name, side, self.m[side].pid)
            if self.args.record:
                with open(gold, "w") as f:
                    f.write("\n".join(normed) + "\n")
                self.results.append((trial, name, side, self.m[side].pid, "RECORDED", os.path.relpath(gold, ROOT)))
            elif not os.path.exists(gold):
                self.results.append((trial, name, side, self.m[side].pid, "MISSING", f"no golden {os.path.relpath(gold, ROOT)} (read {name}.{side}.sout, then --record)"))
            else:
                d = subprocess.run(["diff", "-Bw", gold, base + ".sout"], capture_output=True, text=True)
                if d.returncode == 0:
                    self.results.append((trial, name, side, self.m[side].pid, "PASS", ""))
                else:
                    print(f"DIFF: [{trial}] {name}.{side}\n{d.stdout}", flush=True)
                    self.results.append((trial, name, side, self.m[side].pid, "DIFF", f"{os.path.relpath(base, ROOT)}.sout"))
        time.sleep(1.0)   # the ports are free again before the next scenario binds them

    # ---- the whole run
    def go(self, todo):
        trials = [t for t in TRIALS if any(s["trial"] == t for s in todo)]
        os.makedirs(self.log_dir, exist_ok=True)
        log = os.path.join(self.log_dir, "setup.log")
        try:
            self.there_ip = socket.gethostbyname(self.there_host)
        except OSError as e:
            print(f"interchange: FAIL: {self.there_host} does not resolve here ({e})")
            return 1
        ok, why = self.session.open()
        if not ok:
            print(f"interchange: FAIL: no ssh session to {self.host.conn} (key-based, batch mode): {why}")
            return 1
        try:
            self.machines()
            print(f"here  : {self.here.pid}  {ROOT}")
            print(f"there : {self.there.pid}  {self.host.conn}:{self.host.path}  ({self.there_ip})")
            print(f"logs  : {self.log_dir}", flush=True)
            direct_open = {}
            if not self.args.no_probe:
                direct_open = self.probe(sorted({s["direct"] for s in todo if s["direct"]}))
            if self.here_addr:
                if not self.args.no_probe:
                    back = self.probe_back(sorted({s["direct_back"] for s in todo if s.get("direct_back")}))
                    direct_open.update({("back", p): ok for p, ok in back.items()})
            else:
                print("reachability: there -> here: not attempted directly (no --here-address: this machine is taken to be behind "
                      "address translation); ssh -R forwards of this session carry that direction", flush=True)
            if X1 in trials:
                self.write_cookie()
            if self.sync(log) != 0:
                print(f"interchange: FAIL: the sync to {self.host.conn}:{self.host.path} failed; see {log}")
                return 1
            rc, cid = self.there.run('c="$(readlink -f "' + dict(v.split("=", 1) for v in self.there.make_vars).get("SILICA_COMPILER", "../silica/binaries/silica-compiler")
                                     + '")"; stat -c "%n %s %Y" "$c"')
            there_cid = cid.strip() if rc == 0 else "unknown"
            lc = os.path.realpath(dict(v.split("=", 1) for v in self.here.make_vars).get("SILICA_COMPILER", os.path.join(ROOT, "..", "silica", "binaries", "silica-compiler")))
            here_cid = f"{lc} {os.path.getsize(lc)} {int(os.path.getmtime(lc))}" if os.path.exists(lc) else "unknown"
            problems = []
            ths = [threading.Thread(target=build_machine, args=(m, trials, c, self.args.rebuild, os.path.join(self.log_dir, f"build_{m.side}.log"), problems))
                   for m, c in ((self.here, here_cid), (self.there, there_cid))]
            for t in ths:
                t.start()
            for t in ths:
                t.join()
            if problems:
                for pr in problems:
                    print("interchange: FAIL:", pr)
                return 1
            for sc in todo:
                self.scenario(sc, direct_open)
        finally:
            for n in self.nodes:
                n.stop()
            self.session.cancel_all()
            for name in ("cookie", "cookie_args"):
                try:
                    os.remove(os.path.join(ROOT, "trials", X1, name))
                except OSError:
                    pass
            try:
                self.there.run(f"rm -f trials/{X1}/cookie trials/{X1}/cookie_args", timeout=30)
                rc, left = self.there.run("pgrep -u \"$(id -u)\" -af 'x[0-9]_interchange_|bees_interchange_node' | grep -v pgrep || true", timeout=30)
                left = left.strip()
                print("remote  : " + ("no process of the trials is left" if not left else "LEFT RUNNING:\n" + left), flush=True)
            except (subprocess.SubprocessError, OSError, AttributeError):
                pass
            self.session.close()
        return self.report()

    def report(self):
        rows = [("TRIAL", "SCENARIO", "SIDE", "PLATFORM", "STATUS", "NOTE")] + [tuple(r) for r in self.results]
        w = [max(len(r[i]) for r in rows) for i in range(5)]
        print()
        for r in rows:
            print("  ".join(c.ljust(w[i]) for i, c in enumerate(r[:5])) + "  " + r[5])
        good = sum(1 for r in self.results if r[4] in ("PASS", "RECORDED"))
        bad = len(self.results) - good
        print(f"\ninterchange: {good} passed, {bad} failed" if not self.args.record else f"\ninterchange: {good} goldens recorded, {bad} failed")
        return 0 if bad == 0 and self.results else 1


def pick_host(hosts, here):
    """the first line of the hosts file whose platform builds and is another machine's: the interchange partner"""
    for h in hosts:
        if P.build_supported(h.platform) and h.platform != here:
            return h
    return None


def parse(argv):
    import argparse
    ap = argparse.ArgumentParser(prog="bees_interchange.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("--only", type=lambda s: [x for x in s.split(",") if x], default=[], help="trial names (x1_interchange_beam, x2_interchange_trust)")
    ap.add_argument("--scenario", type=lambda s: [x for x in s.split(",") if x], default=[], help="scenario names")
    ap.add_argument("--record", action="store_true", help="write the goldens from this run's outputs")
    ap.add_argument("--rebuild", action="store_true", help="build every node again")
    ap.add_argument("--no-probe", action="store_true", help="skip the reachability probe of the directly dialed ports")
    ap.add_argument("--hosts-file", default=os.environ.get("BEES_BUILD_HOSTS", os.path.join(ROOT, R.HOSTS_FILE)))
    ap.add_argument("--here-address", default=os.environ.get("BEES_INTERCHANGE_HERE_ADDRESS") or None,
                    help="this machine's IPv4 address as the remote can dial it: the BEES-with-BEES scenarios of that direction run directly (NAME_direct)")
    ap.add_argument("--list", action="store_true", help="print the scenarios and stop")
    return ap.parse_args(argv)


def main(argv):
    args = parse(argv[1:])
    if args.here_address and not re.fullmatch(r"(?:[0-9]{1,3}\.){3}[0-9]{1,3}", args.here_address):
        print("interchange: --here-address takes an IPv4 literal (TRUST dials IPv4 literals only)", file=sys.stderr)
        return 2
    todo = [s for s in scenarios(args.here_address) if (not args.only or s["trial"] in args.only) and (not args.scenario or s["name"] in args.scenario)]
    for t in args.only:
        if t not in TRIALS:
            print(f"interchange: no such trial: {t} (known: {', '.join(TRIALS)})", file=sys.stderr)
            return 2
    if args.list:
        for s in todo:
            print(f"{s['trial']:22} {s['name']:18} {s['path']}")
        return 0
    if not todo:
        print("interchange: no scenario selected", file=sys.stderr)
        return 2
    if not os.path.exists(args.hosts_file):
        print(f"interchange: skipped: no remote ({args.hosts_file} is missing; the interchange trials need a second machine: copy "
              ".bees_build_hosts.example to .bees_build_hosts)")
        return 0
    try:
        hosts = R.read_hosts(args.hosts_file)
    except ValueError as e:
        print("interchange:", e, file=sys.stderr)
        return 2
    here = P.current_id()
    host = pick_host(hosts, here)
    if host is None:
        print(f"interchange: skipped: no remote ({args.hosts_file} names no machine of another platform whose build is supported)")
        return 0
    if not SAFE_PATH.match(host.path):
        print(f"interchange: the remote path {host.path!r} must be plain (letters, digits, . _ / ~ -)", file=sys.stderr)
        return 2
    return Run(args, host).go(todo)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
