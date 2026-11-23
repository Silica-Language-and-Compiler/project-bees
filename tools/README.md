# tools/

Build and verification tools of BEES. This file documents the platform, golden-name, port and parallel-runner machinery
(2026-11-17); each script's header documents the rest.

## Platform and goldens

`tools/platform.mk` (make) and `tools/platform_id.py` (Python) say which platform a build is for:

| | macOS Apple Silicon | Linux x86_64 | Linux aarch64 (Raspberry Pi 5) |
|---|---|---|---|
| `BEES_PLATFORM` (the `native/` directory) | `macos` | `linux` | `linux` (the same directory) |
| `BEES_PLATFORM_ID` (golden name, same spelling as Silica) | `macos_applesilicon` | `linux_x86_64` | `linux_aarch64` |

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
goldens, leaving the others alone, so the Linux goldens (`NAME.linux_x86_64.scout`, recorded 2026-11-18) sit beside the Mac ones.
Makefiles use `$(GOLD_SUFFIX)` (`.macos_applesilicon`, `.linux_x86_64`, `.linux_aarch64`), Python uses `platform_id.golden_name("main.scout")`. Where
the outputs of the two platforms differ, and why, is listed in `native/linux/README.md` ("Goldens").

What a Makefile or a tool needs that differs between the platforms comes from `native/$(BEES_PLATFORM)/platform.mk` (`native/README.md`
lists the variables): in-place `sed` (`$(SED_I)`), the link flags, the OpenSSL rpath, this machine's non-loopback address
(`PLATFORM_LOCAL_IPV4`, `trials/n1_addr`).

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
linux_x86_64 manager@aalang.org /opt/bees /opt/openssl 2 SILICA_COMPILER=/opt/silica/binaries/silica-compiler-linux_x86_64 SILICA_ROOT=/opt/silica
```

`-` for no OpenSSL prefix or for this machine's `-j`. NOTES is free text; the tokens `SILICA_COMPILER`, `SILICA_ROOT`, `BEES_COMPILE_JOBS`,
`SILICA_COMPILE_TIMEOUT` are passed to the remote run; `BEES_PATH_PREFIX=DIR[:DIR]` puts directories before the remote's `PATH` (a programmer's Erlang/OTP in the home directory: `BEES_PATH_PREFIX=/home/u/opt/erlang/bin`). `tools/silica.mk` takes `SILICA_COMPILER` from the make command line only, so the
runner hands the one in its environment (here, or on the remote from the notes) to every make it starts as an argument
(`make ... SILICA_COMPILER=...`); a remote line must name a compiler of that machine's platform, because the default
`binaries/silica-compiler` of a checkout copied from a Mac is the macOS one. The file holds no keys, passwords or tokens (the reader refuses a line that mentions one);
ssh is key-based in batch mode only: check a machine with `ssh -o BatchMode=yes user@host true`. The remote needs a Silica checkout (the tree's
`../silica`, or `SILICA_ROOT`), a compiler for its platform, python3, rsync, make and clang.

The runner reads the file when it exists (`--remote` insists on it, `--no-remote`/`--local-only` ignores it). For each line whose platform builds:
(1) `ssh true` check; (2) `rsync -a --delete` of the tree with an exclude list modelled on silica's `sync_excludes.sh` (objects, archives,
`.sams`, `.iface`, `.sout`, built trial executables, `silica.*` products, `native/build`, `native/dangerous_exposure_source/lib`, `.git`,
`trial_runs`, the hosts file itself), build products excluded so nothing built on one machine crosses to another; (3) over ssh, the same script with
`--local-only`; (4) the remote logs and `results.json` and that platform's goldens (`*.PLATFORM_ID.scout|golden_fail`, `rsync --update`) come
back; (5) its rows join the table. `--list` and `--dry-run` print these commands and run none.

**Platform switch.** `tools/platform_id.py` holds one build switch per platform (the last field of its `PLATFORMS` rows).
`linux_x86_64` is True since 2026-11-18 (`native/linux/` and the Linux goldens exist), `linux_aarch64` since 2026-11-21 (the same `native/linux/`), so a
line of the hosts file for either is run and a Linux machine running the script runs its own platform. `esp32s3` and `nucleo` are False: their lines are listed and reported `SKIPPED` with the
reason. `test_platform_and_ports.py` pins the switches (`test_build_switches`), checks that a platform that builds has its `platform.mk` and
sources and that every Mac golden has its Linux x86-64 and Linux aarch64 counterparts (the aarch64 twin rule: see "Goldens of a third platform" in `native/linux/README.md`); `test_run_all_trials.py` checks the compiler hand-over.

### Trials for specific platforms: `trials/LEAF/platforms`

A trial that needs something only some platforms have (Swift, Kotlin and a JDK 27 exist on the Mac only) says so in a file
`trials/LEAF/platforms`: platform identifiers, whitespace separated, `#` starts a comment (put the reason there). The runner does not run
that trial on any other platform: it prints and records the row as `N/A` with `declared only for ... (trials/LEAF/platforms)`, counts it
neither as a pass nor as a failure (totals read `N of M trials passed; K N/A`), and the exit status ignores it. A trial without the file
is for every platform that builds, and one that is missing a toolchain there still FAILS loudly (the project's rule: a trial never
skips by itself). `test_platform_and_ports.py` asks no golden of a platform a trial is not declared for (and fails when one exists), and
checks the file's ids. Declared today: `c5_tempus_swift`, `c6_tempus_kotlin`, `c7_tempus_gossip` (macOS Apple Silicon only). A make run
of such a leaf by hand does what its Makefile says (all three fail loudly when their toolchain is missing).

## Two machines: `bees_interchange.py`

```
make interchange [SILICA_COMPILER=...]            # or: tools/bees_interchange.py [--only TRIAL] [--scenario NAME] [--record] [--rebuild] [--list]
```

Runs the interchange trials, `trials/x1_interchange_beam` (BEAM mode: BEES with BEES, and BEES against a stock erl) and
`trials/x2_interchange_trust` (TRUST over mutual TLS 1.3: calls, a wrong pin, a certificate no whitelist lists), with one node on
this machine ("here") and the other on the first machine of another platform in `.bees_build_hosts` ("there"), each scenario in
both directions. They need both machines, so they are **not** trial leaves (their directories hold `interchange.mk`, no
`Makefile`): `make integrate` and `run_all_trials.sh` never run them, and without the hosts file the driver prints
`interchange: skipped: no remote (...)` and exits 0. Here the compiler is `SILICA_COMPILER` of the environment (or of the make
command line); there, the hosts line's `SILICA_COMPILER`, `SILICA_ROOT` and OpenSSL prefix.

- One ssh master session carries every remote command, the rsync (the runner's exclude list) and the port forwards. The driver
  probes the directly dialed ports first and prints what it finds; a node here dials the remote directly, and a node there
  reaches this machine through an `ssh -R` forward (this machine is behind address translation). Each scenario's line in the
  output says which path its bytes took; `--list` prints them all. A stock erl and its private EPMD always stay on 127.0.0.1 and
  are reached through forwards only.
- `--here-address IPV4` (or `BEES_INTERCHANGE_HERE_ADDRESS`): on a network where the remote can dial this machine, runs the four
  BEES-with-BEES scenarios of that direction directly, with no forward, as `NAME_direct` (own goldens, to be recorded on such a
  network; the spike document's Limits section).
- The BEAM-mode cookie is random per run, mode 600 on both machines, removed at the end. `x2`'s certificates are test fixtures
  (`tools/bees_test_certs.sh`).
- Goldens carry the side and the platform of the machine the node ran on: `NAME.here.macos_applesilicon.scout`,
  `NAME.there.linux_x86_64.scout`; the remote machine's name and address are written `THERE_HOST` and `THERE_IPV4`.
  `test_platform_and_ports.py` checks that every scenario has one golden per side, of different platforms (instead of the
  Mac-golden-has-a-Linux-twin rule). `--record` writes them; read `NAME.SIDE.sout` first.
- A node is built on the machine that runs it and rebuilt only when its inputs changed (`.interchange_stamp`). Logs:
  `trial_runs/interchange-STAMP/`. At the end the driver checks that no process of the trials is left on the remote.
- Ports: the two blocks of `trial_ports.py`. What was measured and the limits: `development-plan/spikes/X1-mac-linux-interchange.md`.

## Other tools

`trial.mk` / `silica.mk` (the leaf Makefiles' machinery), `run_trial.py` / `run_pair.py` / `run_trio.py` (run executables on a pty), `bees_conf.py`,
`bees_config*.py` (the `bees.config` and manifest readers and generators), `conformance.py`, the `test_*.py` unit tests, `n2_live.py`, `soak.py`, `bees_interchange.py` / `bees_interchange_node.py` (above).

## Configuration through the store carrier: `bees_pack*.py`

`bees_pack.py pack --config bees.config --capacity BYTES -o node.sildat [MANIFEST.wire ...]` validates a configuration with
`bees_conf.py` and writes it as ETF records in the on-medium layout of Silica's hosted `(:store)` carrier (D46); `show FILE`
prints a packed store without its secrets. `bees_pack_store.py` is the layout (Silica's; guarded by `trials/d1_store_layout`),
`bees_pack_gen.py write` regenerates the reader units of `src/config/` from the packer's record table (`check` and
`test_bees_pack.py` fail when they are stale), and `bees_pack_trial.mk` / `bees_pack_trial.py` run the leaves whose programs open
a backing (`cases.py` in the leaf: one program on several prepared backings). The example application is `examples/store_node`.
Design, probe results and the migration plan: `development-plan/spikes/N0d-store-config.md`.

## TRUST sessions (N5, windowed multiplexing)

Design and results: `development-plan/spikes/N5-multiplexing.md`.

- `bees_trust_mux_gen.py OUT_DIR BEES_CONFIG` writes a session node's units into its `lib/`: `bees_trust_slots.silica` (the
  per-connection supervisor's table, the client's pending table and the metrics actor, sized by `trust.session.max_inflight`),
  `dangerous_bees_trust_mux.silica` (the expansion of `src/trust/dangerous_bees_trust_mux.silica.in`, whose record macros are
  described in the tool's header), and links to `bees_trust_mux_frame.silica` and `bees_trust_mux.atoms`. A leaf does not call
  it: `bees_trust_gen.py mfa ... --config bees.config` does, when the config multiplexes, and removes those files when it does
  not. `bees_trust_gen.py edge` then pastes `src/shim/bees_trust_mux.part` into the root unit (`trust_start`, `trpc_call`,
  `trpc_cast` keep their names; `trpc_close`, `trust_shutdown`, `trust_metrics_dump` are added). A node that does not multiplex
  gets the root unit it got before.
- When a node multiplexes: `bees_config_trust.py` writes `mux()`, `session_single()` and the `session_*` values into
  `bees_trust_conf`. A node multiplexes when its `bees.config` writes `trust.session`. `SESSION_DEFAULT_ON` in `bees_conf.py` is
  the one switch for a node that does not write it: `False` today (one request per connection, as before N5); `True` is the
  ruled target (the defaults 8 and 100), to be flipped together with the re-recording of the existing TRUST goldens (the list
  is in section 12 of the spike note). `{session, #{max_inflight => 1, max_calls => 1}}` keeps a node at one request per
  connection either way.
- `run_trust_pair.py` has two more options, both off unless given: `--settle` (the server is told to exit only QUIET seconds
  after the client has ended, so what it prints about the client's close is always in its output) and
  `--rss TEXT:SECONDS:FILE` (the server's resident set, from `ps`, when TEXT first appears in its output and SECONDS later;
  the read-pause scenario of `trials/n5_trust_mux` uses it).
- `test_bees_trust_mux.py`: the macros, the generated tables, the switch, the root unit of a node with and without sessions.
- In `trials/n5_trust_mux` and `trials/n5_trust_mux_tls`: `make run ONLY=name` runs one scenario and `make integrate NOBUILD=1`
  runs them all, both without building; `make measure` is the soak (not part of `integrate`).
