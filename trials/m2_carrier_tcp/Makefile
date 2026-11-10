# M2 (ported, N1): the language's (:tcp) carrier between two BEES programs. Each program's dangerous_ root unit is generated
# from src/shim/bees_tcp_edge.part (carrier_new: the stdlib's dangerous_tcp_carrier) plus its role files, at parse time so
# trial.mk's wildcards see the units. The listener and connector run as a pair (carrier_pair.pair, tools/run_pair.py: the
# listener is started first, because the language's carrier connects or fails at once). The refusal program of the native
# edge is gone with it: the language's listener binds 127.0.0.1 only, and the manifest reader refuses other hosts.
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)
LEAF_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
EDGE_GEN := $(BEES_ROOT)/tools/bees_edge_gen.py
EDGE_DEPS := $(BEES_ROOT)/src/shim/bees_tcp_edge.part $(EDGE_GEN)
GENERATED := dangerous_m2_listener.silica dangerous_m2_connector.silica
_ := $(shell cd "$(LEAF_DIR)" && \
	"$(EDGE_GEN)" dangerous_m2_listener dangerous_m2_listener.silica listener.role peer.role && \
	"$(EDGE_GEN)" dangerous_m2_connector dangerous_m2_connector.silica connector.role peer.role)
include $(BEES_ROOT)/tools/trial.mk

clean: clean-generated
.PHONY: clean-generated
clean-generated:
	@cd "$(LEAF_DIR)" && rm -f $(GENERATED)
