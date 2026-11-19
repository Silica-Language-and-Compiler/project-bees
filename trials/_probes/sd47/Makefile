# SD-47 diagnostic (not a trial: run_all_trials does not enter trials/_probes, and there is no golden).
# `make build SILICA_COMPILER=...`, then run each entry by hand: ./a_ticker_first, ./b_busy_first, ./c_two_busy, ./d_migrate.
# Each entry: a ticker actor prints a monotonic timestamp every 50 ms (send_after to itself); at tick 4 it casts a busy actor,
# whose one dispatch runs a pure arithmetic loop (no I/O) of about 1-2 s. If the ticker stops printing for the busy period, a
# busy actor holds other actors. Every actor prints its own lines (println); there is no shared reporter actor.
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../../..)
include $(BEES_ROOT)/tools/trial.mk
