# F1 (fuzzer), the resolve surface: tools/bees_fuzz.py writes fz_resolve.silica (a batch of generated resolver answers, each put
# through the one filter, src/shim/bees_addr.silica) and builds it here with the generic leaf rules. Not a trial leaf of its own
# (trials/Makefile and tools/run_all_trials.py list only trials/*/Makefile); trials/f1_fuzz_wire/Makefile drives it.
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../../..)
include $(BEES_ROOT)/tools/trial.mk
