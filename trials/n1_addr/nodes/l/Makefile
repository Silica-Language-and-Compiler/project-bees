# N1 node l (trials/n1_addr): M3's node (dangerous_bees_net, auth none) built with the resolver edge's test stub (--resolve-stub):
# the loopback-only rule applied to a resolved name. Roles: trials/m3_dist/roles and ../../roles.
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../../../..)
LEAF_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
ROLES := $(BEES_ROOT)/trials/m3_dist/roles
EDGE_GEN := $(BEES_ROOT)/tools/bees_edge_gen.py
USES := --use bees_msgs --use bees_dist --use dangerous_bees_net --use bees_peers
_ := $(shell cd "$(LEAF_DIR)" && \
	"$(EDGE_GEN)" dangerous_l_watch dangerous_l_watch.silica $(USES) --resolve-stub $(ROLES)/node.role $(ROLES)/timing_slow.role $(BEES_ROOT)/trials/n1_addr/roles/late.role $(BEES_ROOT)/trials/n1_addr/roles/m3_watch.role)
include $(BEES_ROOT)/tools/trial.mk

clean: clean-generated
.PHONY: clean-generated
clean-generated:
	@cd "$(LEAF_DIR)" && rm -f dangerous_*.silica lib/bees_peers.silica
