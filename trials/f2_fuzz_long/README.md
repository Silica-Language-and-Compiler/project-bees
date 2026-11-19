# f2_fuzz_long: the wire fuzzer's long run

Not a trial leaf (no `Makefile`): `make integrate` and `tools/run_all_trials.sh` never run it. Everything is in `fuzz.mk`.
Spike document: [development-plan/spikes/F1-fuzzer.md](../../development-plan/spikes/F1-fuzzer.md).

```
make -f fuzz.mk nodes     SILICA_COMPILER=/path/to/silica-compiler            # once, and after a change of the BEES sources
make -f fuzz.mk fuzz-long SILICA_COMPILER=/path/to/silica-compiler SEED=20261118 DURATION=86400
make -f fuzz.mk replay    SEED=20261118 SURFACE=trust_plain CASE=1234 [BEFORE=50]
```

- `nodes/` and `resolve/` are copies of `trials/f1_fuzz_wire`'s, written by `tools/bees_fuzz.py prepare` with the ports of this
  block (`f2_fuzz_long`, 23600..23699 in `tools/trial_ports.py`; same offsets as `trials/f1_fuzz_wire/README.md`). They are
  generated: edit the sources in `trials/f1_fuzz_wire` and run `make -f fuzz.mk nodes` again.
- `runs/SEED/`: `run.log` (a progress line per slice, a `FINDING` line per finding), `summary.json` (cases per surface, the next
  index of each surface, findings by signature, cases per second, resident set at the start and end of each slice),
  `node_*.log` (everything each node printed) and `findings/SURFACE-INDEX-KIND/` with `case.json`, `input.bin` (the exact bytes
  sent), `node_output.txt` and `repro.txt` (the one-line replay command).
- `findings/`: findings worth keeping, copied from a run by hand after triage.
- One node program is alive at a time, plus the driver; the resolve surface compiles one small program per slice.
