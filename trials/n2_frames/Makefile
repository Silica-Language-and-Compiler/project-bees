# N2: the byte layouts BEAM mode adds (beam_dist): the cookie steps, EPMD's requests and answers, control messages built and
# parsed (OTP 28 bytes from erl are embedded as hex). tools/test_beam_dist.py compares the printed bytes with erl and erl_epmd.
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)
include $(BEES_ROOT)/tools/trial.mk
