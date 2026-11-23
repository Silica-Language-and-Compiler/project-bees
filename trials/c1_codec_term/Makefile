# C1: the dynamic term codec (bees_term_wire) and the position scanner (bees_etf_scan), in one process, against the bytes
# stock Erlang wrote (tools/bees_term_fixtures.erl); tools/test_bees_term_etf.py predicts every line with an independent
# Python reader and writer.
# Part 6 builds terms of 60,000 tokens on the main thread, one stack frame per token (SD-59: a tail call that is a real call):
# more than Linux's default 8 MiB main-thread stack. The macOS link gives every program 256 MiB; on Linux the entry is run
# under the same limit (NEEDS_MAIN_STACK, tools/silica.mk).
NEEDS_MAIN_STACK := 1
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)
include $(BEES_ROOT)/tools/trial.mk
