# N2 live trial, node beesd: one manifest (node.wire), bees.config (tools/bees_config_beam.py writes lib/beam_conf.silica and
# lib/beam_peers.silica), and one entry, whose root unit is generated at parse time from the carrier edge, the BEAM-mode
# node edge and roles (shared with trials/n2_dist). The cookie file is written first (git keeps no modes).
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../../../..)
LEAF_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
ROLES := $(BEES_ROOT)/trials/n2_dist/roles
LROLES := $(BEES_ROOT)/trials/n2_live/roles
EDGE_GEN := $(BEES_ROOT)/tools/bees_edge_gen.py
PART := $(BEES_ROOT)/src/shim/beam_node_edge.part
USES := --use bees_msgs --use bees_dist --use bees_ingress --use bees_peers --use beam_dist --use beam_conf --use beam_peers --use dangerous_beam_auth --use dangerous_beam_net
_ := $(shell $(MAKE) -s -C "$(BEES_ROOT)/trials/n2_live" cookies >/dev/null && cd "$(LEAF_DIR)" && \
	"$(BEES_ROOT)/tools/bees_config_beam.py" generate --config bees.config -o lib node.wire 1>&2 && \
	"$(EDGE_GEN)" dangerous_beesd dangerous_beesd.silica $(USES) $(PART) $(ROLES)/node.role $(ROLES)/cookie_conf.role $(ROLES)/timing_conf.role $(LROLES)/live_client.role)
include $(BEES_ROOT)/tools/trial.mk

clean: clean-generated
.PHONY: clean-generated
clean-generated:
	@cd "$(LEAF_DIR)" && rm -f dangerous_*.silica lib/beam_conf.silica lib/beam_peers.silica
