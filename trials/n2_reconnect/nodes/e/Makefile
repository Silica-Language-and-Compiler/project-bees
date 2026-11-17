# N2c reconnect, node e: one manifest (node.wire), bees.config (the beam half: tools/bees_config_beam.py writes lib/beam_conf.silica and
# lib/beam_peers.silica), and the entries below (root units generated at parse time from the carrier edge, the BEAM-mode node edge and roles).
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../../../..)
LEAF_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
ROLES := $(BEES_ROOT)/trials/n2_reconnect/roles
EDGE_GEN := $(BEES_ROOT)/tools/bees_edge_gen.py
PART := $(BEES_ROOT)/src/shim/beam_node_edge.part
USES := --use bees_msgs --use bees_dist --use bees_ingress --use bees_peers --use beam_dist --use beam_conf --use beam_peers --use dangerous_beam_auth --use dangerous_beam_net
_ := $(shell $(MAKE) -s -C "$(BEES_ROOT)/trials/n2_reconnect" cookies >/dev/null && cd "$(LEAF_DIR)" && \
	"$(BEES_ROOT)/tools/bees_config_beam.py" generate --config bees.config -o lib node.wire 1>&2 && \
	"$(EDGE_GEN)" dangerous_e1 dangerous_e1.silica $(USES) $(PART) $(ROLES)/node.role $(ROLES)/cookie_conf.role $(ROLES)/timing_slow.role $(ROLES)/edge_e1.role && \
	"$(EDGE_GEN)" dangerous_e2 dangerous_e2.silica $(USES) $(PART) $(ROLES)/node.role $(ROLES)/cookie_conf.role $(ROLES)/timing_slow.role $(ROLES)/edge_e2.role)
include $(BEES_ROOT)/tools/trial.mk

clean: clean-generated
.PHONY: clean-generated
clean-generated:
	@cd "$(LEAF_DIR)" && rm -f dangerous_*.silica lib/beam_conf.silica lib/beam_peers.silica
