# C1 codec trial, two nodes, node b (prints each kind and echoes it): one manifest (node.wire), its bees.config and the entry below,
# generated at parse time from the carrier edge and the roles (M3's auth-none node, trials/m3_dist/roles/node.role).
# dangerous_b_echo.atoms lists the atom literals the roles write (all are message-type atoms of node.wire).
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../../../..)
LEAF_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
EDGE_GEN := $(BEES_ROOT)/tools/bees_edge_gen.py
ROLES := $(BEES_ROOT)/trials/c1_codec_nodes/roles
USES := --use bees_msgs --use bees_dist --use dangerous_bees_net --use bees_peers --use bees_term_wire --use bees_codec_kinds
_ := $(shell cd "$(LEAF_DIR)" && \
	"$(EDGE_GEN)" dangerous_b_echo dangerous_b_echo.silica $(USES) $(BEES_ROOT)/trials/m3_dist/roles/node.role $(ROLES)/timing.role $(ROLES)/show.role $(ROLES)/echo.role)
include $(BEES_ROOT)/tools/trial.mk

clean: clean-generated
.PHONY: clean-generated
clean-generated:
	@cd "$(LEAF_DIR)" && rm -f dangerous_*.silica lib/bees_peers.silica
