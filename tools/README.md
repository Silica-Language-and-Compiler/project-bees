# tools/

Build and verification tools of BEES. This file documents the platform, golden-name, port and parallel-runner machinery
(2026-11-17); each script's header documents the rest.

## Platform and goldens

`tools/platform.mk` (make) and `tools/platform_id.py` (Python) say which platform a build is for:

| | macOS Apple Silicon | Linux x86_64 |
|---|---|---|
| `BEES_PLATFORM` (the `native/` directory) | `macos` | `linux` (placeholder; no build yet) |
| `BEES_PLATFORM_ID` (golden name, same spelling as Silica) | `macos_applesilicon` | `linux_x86_64` |

Both default from `uname -s` / `uname -m` and can be set on the command line or in the environment.

A golden is the recorded expected output of a trial entry: `NAME.scout` (stdout, stderr and the exit code) and `NAME.golden_fail` (a
compile-fail trial's diagnostics). The platform identifier goes right before the extension, as in Silica's own trials
(`test.macos_applesilicon.sout`):

```
scenario.a.scout      -> scenario.a.macos_applesilicon.scout
hub.scout             -> hub.macos_applesilicon.scout
redial.check.scout    -> redial.check.macos_applesilicon.scout
x.golden_fail         -> x.macos_applesilicon.golden_fail
```

Not goldens, and unchanged: the run outputs `NAME.sout` and `NAME.cur_fail`, `NAME.wait_for_exit`, `.pair`, manifests, `*.txt`
measurements, the Erlang oracle vectors (`tools/etf_oracle/`, platform-free).

`make integrate` compares a run only with `NAME.$(BEES_PLATFORM_ID).scout`. With none the leaf fails loudly: `MISSING golden for
linux_x86_64 (record one on this platform with make record-golden): [leaf] file`. `make record-golden` writes the current platform's
goldens, leaving the others alone, so Linux goldens will sit beside the Mac ones. Makefiles use `$(GOLD_SUFFIX)` (`.macos_applesilicon`),
Python uses `platform_id.golden_name("main.scout")`. Where outputs differ between platforms, that is for the port.

## Ports

`tools/trial_ports.py` is the one table: trial name to a base port; each trial owns 100 ports from its base (`21000 + 100*k`, below the
Linux and macOS ephemeral ranges). Offsets within a trial are listed in the table. Files keep the numbers as literals (a manifest, a
`bees.config`, a role file and a golden must say what they say); `trial_ports.py check` (and `test_platform_and_ports.py`, run by
`python3 -m unittest discover -s tools -p 'test_*.py'`) fails when a trial's files name a port of another trial's block, when blocks
overlap, or when a trial that listens is missing from the table. Makefile recipes and tools that need a port ask it (`trial_ports.py port
n4_trust_tls 0`; `n2_live.py` takes its private EPMD port from it; `trials/m4_demo/roles/gen_types.py` its manifests'). To add a trial that
listens: take `NEXT_BASE`, add the entry, put its ports in that block, bump `NEXT_BASE`. Never renumber an existing entry: a changed port
changes the goldens that print it. The spike documents keep the ports of their day.

## run_all_trials.sh

```
tools/run_all_trials.sh [-j N] [--compile-jobs N] [--only a,b] [--log-dir DIR] [--local-only | --remote | --no-remote]
                        [--hosts-file FILE] [--skip-native] [--no-kit] [--leaf-timeout SEC] [--list] [--dry-run]
```

- Local: `make -C native` once, `make check-compiler`, then `make -C trials/LEAF integrate` for each leaf, at most `-j` at a time (default
  cores minus one; env `BEES_JOBS`), the slowest first (seconds of the last run are kept in `trial_runs/timings.json`), then `make kit`.
- Compile cap: the Silica compiler runs inside `tools/with_slot.py`, so at most `--compile-jobs` (default 2, env `BEES_COMPILE_JOBS`) compile at
  once across all trials; runs are not limited by it.
- Logs: `trial_runs/STAMP/PLATFORM_ID/LEAF.log` (and `_setup.log`, `kit.log`, `results.json`); `trial_runs/` is ignored by git.
- Summary: one table (platform, trial, status, passed, failed, seconds, log), one total per platform, wall time. Exit status 0 only when every
  trial that ran passed; SKIPPED platforms do not fail the run; a trial that could not run, or a remote that cannot be reached, does.
- `make integrate` is the serial path and is unchanged. `make integrate-parallel` calls the runner for this machine only.
- Safety under parallel runs: each leaf builds in its own directory (node leaves in `nodes/*`), cookies and certificates are per leaf, ports are
  per trial, `native/` (archives in `native/dangerous_exposure_source/lib`, objects in `native/build`) is built once before any leaf and is only
  read after (`n4_trust_tls` calls `make -C native tls`, a no-op when current). There is no shared lock file.

### Remote machines: `.bees_build_hosts`

Untracked (in `.gitignore`); copy `.bees_build_hosts.example`. One line per machine, whitespace separated, `#` comments:

```
PLATFORM_ID  USER@HOST  REMOTE_PATH  OPENSSL_PREFIX  JOBS  [NOTES]
linux_x86_64 manager@aalang.org /opt/bees /opt/openssl 3 SILICA_COMPILER=/opt/silica/binaries/silica-compiler
```

`-` for no OpenSSL prefix or for this machine's `-j`. NOTES is free text; the tokens `SILICA_COMPILER`, `SILICA_ROOT`, `BEES_COMPILE_JOBS`,
`SILICA_COMPILE_TIMEOUT` are passed to the remote run. The file holds no keys, passwords or tokens (the reader refuses a line that mentions one);
ssh is key-based in batch mode only: check a machine with `ssh -o BatchMode=yes user@host true`. The remote needs a Silica checkout (the tree's
`../silica`, or `SILICA_ROOT`), a compiler for its platform, python3, rsync, make and clang.

The runner reads the file when it exists (`--remote` insists on it, `--no-remote`/`--local-only` ignores it). For each line whose platform builds:
(1) `ssh true` check; (2) `rsync -a --delete` of the tree with an exclude list modelled on silica's `sync_excludes.sh` (objects, archives,
`.sams`, `.iface`, `.sout`, built trial executables, `silica.*` products, `native/build`, `native/dangerous_exposure_source/lib`, `.git`,
`trial_runs`, the hosts file itself), build products excluded so nothing built on one machine crosses to another; (3) over ssh, the same script with
`--local-only`; (4) the remote logs and `results.json` and that platform's goldens (`*.PLATFORM_ID.scout|golden_fail`, `rsync --update`) come
back; (5) its rows join the table. `--list` and `--dry-run` print these commands and run none.

**Linux switch.** The Linux port is not done: `tools/platform_id.py` has `("linux", "Linux", "x86_64", False)` for `linux_x86_64`. While the last field
is False every `linux_x86_64` line is listed and reported `SKIPPED` with the reason, and a Linux machine running the script skips its own platform. When
`native/linux/` and the Linux trials build, set it to True (and update `test_platform_and_ports.py`, whose `test_linux_build_switch` pins it).

## Other tools

`trial.mk` / `silica.mk` (the leaf Makefiles' machinery), `run_trial.py` / `run_pair.py` / `run_trio.py` (run executables on a pty), `bees_conf.py`,
`bees_config*.py` (the `bees.config` and manifest readers and generators), `conformance.py`, the `test_*.py` unit tests, `n2_live.py`, `soak.py`.
