# N2c M3 reconnect, node h: one manifest (node.wire), bees.config (mode beam, auth none: M3's node), and the entries below (root units generated at parse time from the carrier edge, the BEAM-mode node edge and roles).
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../../../..)
LEAF_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
ROLES := $(BEES_ROOT)/trials/m3_reconnect/roles
EDGE_GEN := $(BEES_ROOT)/tools/bees_edge_gen.py
USES := --use bees_msgs --use bees_dist --use dangerous_bees_net --use bees_peers
_ := $(shell cd "$(LEAF_DIR)" && \
	"$(EDGE_GEN)" dangerous_h dangerous_h.silica $(USES) $(ROLES)/node.role $(ROLES)/timing_slow.role $(ROLES)/hub.role)
include $(BEES_ROOT)/tools/trial.mk

clean: clean-generated
.PHONY: clean-generated
clean-generated:
	@cd "$(LEAF_DIR)" && rm -f dangerous_*.silica lib/bees_peers.silica
