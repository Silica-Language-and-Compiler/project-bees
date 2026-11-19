# f1_fuzz_wire: the wire fuzzer's nodes and its smoke case

Spike document: [development-plan/spikes/F1-fuzzer.md](../../development-plan/spikes/F1-fuzzer.md). Driver: `tools/bees_fuzz.py`
(generators and oracle models: `tools/bees_fuzz_gen.py`, `tools/bees_fuzz_etf.py`; unit tests: `tools/test_bees_fuzz.py`).

`make integrate` here builds the four node programs, runs a fixed, small number of generated cases (seed 1) and compares
`smoke.sout` with `smoke.<platform>.scout`. The long run is `trials/f2_fuzz_long` and is never part of integrate.

## Nodes under test

| Directory | Program | What it is | Fuzzed as |
| --- | --- | --- | --- |
| `nodes/bl` | `dangerous_bl` | BEAM-mode node `bl@localhost`, listens, registers with EPMD, serves `inbox`, hands out one pid | `beam_accept`, `epmd_register` |
| `nodes/bd` | `dangerous_bd` | BEAM-mode node `bd@localhost`, asks EPMD for `stock` and dials it, redial on, serves `outbox` | `beam_dial` |
| `nodes/ts` | `dangerous_ts` | TRUST server, plaintext test mode (TEST ONLY), stand-in certificates of `trials/n3_trust/certs` | `trust_plain` |
| `nodes/tt` | `dangerous_tt` | TRUST server, mutual TLS 1.3, TEST-ONLY certificates of `trials/n4_trust_tls/certs` | `trust_tls` |
| `nodes/tc` | `dangerous_tc` | TRUST client, plaintext test mode: calls `demo:add` on its pinned server (the driver) for ever, one call per connection | `trust_client` (long run only) |
| `resolve/` | `fz_resolve` (generated) | a batch of resolver answers through `bees_addr` | `resolve` |

The driver plays the node `stock@localhost`, its EPMD, and the TRUST peers `b.cert` / `p.pem` (permitted), `n.cert` / `n.pem`
(whitelisted, permitted nothing) and an identity no whitelist lists. Each node prints what it delivers or executes with the value
in decimal on one line (`inbox got op=.. n=..`, `outbox got ..`, `[demo] note got ..`): that line is the oracle's canary.
Every actor failure report except a normal end is printed whole behind the line `[fuzz actor failure report]`.

`nodes/cookie` is written by the node Makefiles: the fixed value `f1-fuzz-cookie`, mode 600. It authenticates nothing outside
this trial.

## Ports (block `f1_fuzz_wire`, 23500..23599 in `tools/trial_ports.py`)

| Offset | Port | Who listens |
| --- | --- | --- |
| +0 | 23500 | node `bl` (BEAM-mode listener) |
| +1 | 23501 | the driver, as the node `stock@localhost` that `bd` dials |
| +2 | 23502 | the driver's EPMD (`bl` registers with it, `bd` asks it) |
| +3 | 23503 | the driver, as the TRUST server that `tc` has pinned |
| +10 | 23510 | node `ts` (TRUST, plaintext test mode) |
| +11 | 23511 | node `tt` (TRUST, mutual TLS 1.3) |
| +12 | 23512 | node `tc`'s own `trust.port` (required by the reader; `tc` has no whitelist and never listens) |

`trials/f2_fuzz_long` uses the same offsets in its own block (23600..23699); `tools/bees_fuzz.py prepare` rewrites them.

## Reading smoke.sout

```
case beam_accept 000003 auth/truncated_reply id=476fc4059322 ok
FINDING beam_dial case 0 epmd/half_port (no_redial): after this EPMD answer the dialing node ...
cases 140 findings 3
```

`id` is the SHA-256 (12 hex digits) of the generated case, so a change of the generator shows as a golden difference. A
`FINDING` line in the golden is a defect that is known and reported in the spike document; when it is fixed the line turns into
an `ok` line and the golden is recorded again. Replay one case: `python3 tools/bees_fuzz.py replay --seed 1 --surface beam_dial --case 0`.
