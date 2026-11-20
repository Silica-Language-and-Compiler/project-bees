# C1 codec trial against stock Erlang, node beesl (BEAM mode): one manifest (node.wire), bees.config (tools/bees_config_beam.py
# writes lib/beam_conf.silica and lib/beam_peers.silica), the .beam manifest (no pid line), and one entry, whose root unit is
# generated at parse time from the carrier edge, the BEAM-mode node edge and roles: the node's startup of trials/n2_dist, the
# printers and the sender of trials/c1_codec_nodes (show.role, send.role, unchanged), and this trial's live.role. The cookie
# file is written first (git keeps no modes). dangerous_beesl.atoms lists the atom literals the roles write.
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../../../..)
LEAF_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
ROLES := $(BEES_ROOT)/trials/n2_dist/roles
CROLES := $(BEES_ROOT)/trials/c1_codec_nodes/roles
LROLES := $(BEES_ROOT)/trials/c1_codec_live/roles
EDGE_GEN := $(BEES_ROOT)/tools/bees_edge_gen.py
PART := $(BEES_ROOT)/src/shim/beam_node_edge.part
USES := --use bees_msgs --use bees_dist --use bees_ingress --use bees_peers --use beam_dist --use beam_conf --use beam_peers --use dangerous_beam_auth --use dangerous_beam_net --use bees_term_wire --use bees_codec_kinds
_ := $(shell $(MAKE) -s -C "$(BEES_ROOT)/trials/c1_codec_live" cookies >/dev/null && cd "$(LEAF_DIR)" && \
	"$(BEES_ROOT)/tools/bees_config_beam.py" generate --config bees.config --beam node.beam -o lib node.wire 1>&2 && \
	"$(EDGE_GEN)" dangerous_beesl dangerous_beesl.silica $(USES) $(PART) $(ROLES)/node.role $(ROLES)/cookie_conf.role $(ROLES)/timing_conf.role $(CROLES)/show.role $(CROLES)/send.role $(LROLES)/live.role)
include $(BEES_ROOT)/tools/trial.mk

clean: clean-generated
.PHONY: clean-generated
clean-generated:
	@cd "$(LEAF_DIR)" && rm -f dangerous_beesl.silica lib/beam_conf.silica lib/beam_peers.silica
