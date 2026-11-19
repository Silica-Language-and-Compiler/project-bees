# Diagnostic for the Linux fault in c1_codec_term part 6 (not a trial: run_all_trials does not enter this directory, and
# there is no golden). `make run SILICA_COMPILER=...` then read main.sout; run ./main under `/usr/bin/time -v` for peak memory.
#   scale: a list of n one-tuples (n = 1000 .. 30000) built, decoded, encoded, scanned, each step printed before the next.
#   tco:   10,000,000 self calls in the two shapes bees_term_wire's loops use; constant memory means they are tail calls.
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../../../..)
include $(BEES_ROOT)/tools/trial.mk
