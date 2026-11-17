# m3_mesh node c: one manifest (node.wire), bees.config and the entries below (root units generated at parse time from the carrier edge, the node edge and roles).
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../../../..)
LEAF_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
ROLES := $(BEES_ROOT)/trials/m3_mesh/roles
EDGE_GEN := $(BEES_ROOT)/tools/bees_edge_gen.py
USES := --use bees_msgs --use bees_dist --use dangerous_bees_net --use bees_peers
_ := $(shell cd "$(LEAF_DIR)" && \
	"$(EDGE_GEN)" dangerous_cm dangerous_cm.silica $(USES) $(ROLES)/node.role $(ROLES)/timing_slow.role $(ROLES)/c.role $(ROLES)/mesh_c.role && \
	"$(EDGE_GEN)" dangerous_c1 dangerous_c1.silica $(USES) $(ROLES)/node.role $(ROLES)/timing_slow.role $(ROLES)/c.role $(ROLES)/redial_c1.role && \
	"$(EDGE_GEN)" dangerous_c2 dangerous_c2.silica $(USES) $(ROLES)/node.role $(ROLES)/timing_slow.role $(ROLES)/c.role $(ROLES)/redial_c2.role)
include $(BEES_ROOT)/tools/trial.mk

clean: clean-generated
.PHONY: clean-generated
clean-generated:
	@cd "$(LEAF_DIR)" && rm -f dangerous_*.silica lib/bees_peers.silica
