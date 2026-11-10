# M3 node b: one manifest (node.wire), one generated bees_peers, and the entries below. Each entry's root unit is generated
# at parse time from the carrier edge (the language's (:tcp) carrier) and roles.
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../../../..)
LEAF_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
ROLES := $(BEES_ROOT)/trials/m3_dist/roles
EDGE_GEN := $(BEES_ROOT)/tools/bees_edge_gen.py
USES := --use bees_msgs --use bees_dist --use dangerous_bees_net --use bees_peers
_ := $(shell cd "$(LEAF_DIR)" && \
	"$(EDGE_GEN)" dangerous_b_slow dangerous_b_slow.silica $(USES) $(ROLES)/node.role $(ROLES)/timing_slow.role $(ROLES)/delay_short.role $(ROLES)/client.role && \
	"$(EDGE_GEN)" dangerous_b_idle dangerous_b_idle.silica $(USES) $(ROLES)/node.role $(ROLES)/timing_fast.role $(ROLES)/delay_long.role $(ROLES)/client.role && \
	"$(EDGE_GEN)" dangerous_b_silent dangerous_b_silent.silica $(USES) $(ROLES)/node.role $(ROLES)/timing_silent.role $(ROLES)/idle.role && \
	"$(EDGE_GEN)" dangerous_b_raw dangerous_b_raw.silica $(USES) $(ROLES)/node.role $(ROLES)/timing_slow.role $(ROLES)/raw.role)
include $(BEES_ROOT)/tools/trial.mk

clean: clean-generated
.PHONY: clean-generated
clean-generated:
	@cd "$(LEAF_DIR)" && rm -f dangerous_*.silica lib/bees_peers.silica
