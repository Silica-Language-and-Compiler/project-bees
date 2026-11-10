# N2 node b: one manifest (node.wire), bees.config (the beam half: tools/bees_config_beam.py writes lib/beam_conf.silica and
# lib/beam_peers.silica), and the entries below. Each entry's root unit is generated at parse time from the carrier edge, the
# BEAM-mode node edge (src/shim/beam_node_edge.part) and roles. The cookie files are written first (git keeps no modes).
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../../../..)
LEAF_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
ROLES := $(BEES_ROOT)/trials/n2_dist/roles
EDGE_GEN := $(BEES_ROOT)/tools/bees_edge_gen.py
PART := $(BEES_ROOT)/src/shim/beam_node_edge.part
USES := --use bees_msgs --use bees_dist --use bees_ingress --use bees_peers --use beam_dist --use beam_conf --use beam_peers --use dangerous_beam_auth --use dangerous_beam_net
_ := $(shell $(MAKE) -s -C "$(BEES_ROOT)/trials/n2_dist" cookies >/dev/null && cd "$(LEAF_DIR)" && \
	"$(BEES_ROOT)/tools/bees_config_beam.py" generate --config bees.config -o lib node.wire 1>&2 && \
	"$(EDGE_GEN)" dangerous_b_slow dangerous_b_slow.silica $(USES) $(PART) $(ROLES)/node.role $(ROLES)/cookie_conf.role $(ROLES)/timing_slow.role $(ROLES)/delay_short.role $(ROLES)/client.role && \
	"$(EDGE_GEN)" dangerous_b_idle dangerous_b_idle.silica $(USES) $(PART) $(ROLES)/node.role $(ROLES)/cookie_conf.role $(ROLES)/timing_fast.role $(ROLES)/delay_long.role $(ROLES)/client.role && \
	"$(EDGE_GEN)" dangerous_b_silent dangerous_b_silent.silica $(USES) $(PART) $(ROLES)/node.role $(ROLES)/cookie_conf.role $(ROLES)/timing_silent.role $(ROLES)/idle.role && \
	"$(EDGE_GEN)" dangerous_b_raw dangerous_b_raw.silica $(USES) $(PART) $(ROLES)/node.role $(ROLES)/cookie_conf.role $(ROLES)/timing_slow.role $(ROLES)/raw.role && \
	"$(EDGE_GEN)" dangerous_b_wrong dangerous_b_wrong.silica $(USES) $(PART) $(ROLES)/node.role $(ROLES)/cookie_wrong.role $(ROLES)/timing_slow.role $(ROLES)/delay_short.role $(ROLES)/client.role && \
	"$(EDGE_GEN)" dangerous_b_loose dangerous_b_loose.silica $(USES) $(PART) $(ROLES)/node.role $(ROLES)/cookie_loose.role $(ROLES)/timing_slow.role $(ROLES)/delay_short.role $(ROLES)/client.role)
include $(BEES_ROOT)/tools/trial.mk

clean: clean-generated
.PHONY: clean-generated
clean-generated:
	@cd "$(LEAF_DIR)" && rm -f dangerous_*.silica lib/beam_conf.silica lib/beam_peers.silica
