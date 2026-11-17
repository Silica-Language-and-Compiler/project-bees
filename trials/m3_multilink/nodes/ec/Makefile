# N2c M3 node ec: one manifest (node.wire), bees.config (mode beam, auth none: M3's node), tools/bees_config.py generate writes lib/bees_peers.silica,
# and the entries below. Each entry's root unit is generated at parse time from the carrier edge, the M3 node edge (src/shim/bees_node_edge.part) and roles.
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../../../..)
LEAF_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
ROLES := $(BEES_ROOT)/trials/m3_multilink/roles
EDGE_GEN := $(BEES_ROOT)/tools/bees_edge_gen.py
USES := --use bees_msgs --use bees_dist --use dangerous_bees_net --use bees_peers
_ := $(shell cd "$(LEAF_DIR)" && \
	"$(EDGE_GEN)" dangerous_ec dangerous_ec.silica $(USES) $(ROLES)/node.role $(ROLES)/timing_slow.role $(ROLES)/edge_c.role)
include $(BEES_ROOT)/tools/trial.mk

clean: clean-generated
.PHONY: clean-generated
clean-generated:
	@cd "$(LEAF_DIR)" && rm -f dangerous_*.silica lib/bees_peers.silica
