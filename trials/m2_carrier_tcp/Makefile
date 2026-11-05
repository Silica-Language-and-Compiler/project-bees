# M2: the TCP carrier actor of the native edge. Each program's dangerous_ root unit is generated
# from src/shim/bees_tcp_edge.part plus its role files (SD-17: the worker and its spawn site must
# share a unit), at parse time so trial.mk's wildcards see the units. The listener and connector run
# as a pair (carrier_pair.pair, tools/run_pair.py); the refusal program runs alone.
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)
LEAF_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
EDGE_GEN := $(BEES_ROOT)/tools/bees_edge_gen.py
EDGE_DEPS := $(BEES_ROOT)/src/shim/bees_tcp_edge.part $(EDGE_GEN)
GENERATED := dangerous_m2_listener.silica dangerous_m2_connector.silica dangerous_m2_refuse.silica
_ := $(shell cd "$(LEAF_DIR)" && \
	"$(EDGE_GEN)" dangerous_m2_listener dangerous_m2_listener.silica listener.role peer.role && \
	"$(EDGE_GEN)" dangerous_m2_connector dangerous_m2_connector.silica connector.role peer.role && \
	"$(EDGE_GEN)" dangerous_m2_refuse dangerous_m2_refuse.silica refuse.role)
include $(BEES_ROOT)/tools/trial.mk

clean: clean-generated
.PHONY: clean-generated
clean-generated:
	@cd "$(LEAF_DIR)" && rm -f $(GENERATED)
