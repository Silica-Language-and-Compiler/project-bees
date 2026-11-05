BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)
# 64 arms per case, so 120 entries cross the tier boundary (the compiler cannot take 260 in one process, SD-29)
export BEES_TIER := 64
include $(BEES_ROOT)/tools/trial.mk
