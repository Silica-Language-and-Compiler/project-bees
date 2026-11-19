# F1 (fuzzer) node bl: the listening BEAM-mode node under test. bees.config (tools/bees_config_beam.py writes lib/beam_conf.silica and
# lib/beam_peers.silica), the manifests (node.wire, node.atoms, node.beam) and one entry, whose root unit is generated at parse time
# from the carrier edge, the BEAM-mode node edge and roles (cookie_conf and timing_conf are trials/n2_dist's). The cookie file is
# written first (git keeps no modes); it is a fixed test value that authenticates nothing outside this trial.
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../../../..)
LEAF_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
ROLES := $(BEES_ROOT)/trials/n2_dist/roles
FROLES := $(BEES_ROOT)/trials/f1_fuzz_wire/roles
EDGE_GEN := $(BEES_ROOT)/tools/bees_edge_gen.py
PART := $(BEES_ROOT)/src/shim/beam_node_edge.part
USES := --use bees_msgs --use bees_dist --use bees_ingress --use bees_peers --use beam_dist --use beam_conf --use beam_peers --use dangerous_beam_auth --use dangerous_beam_net
_ := $(shell cd "$(LEAF_DIR)" && printf 'f1-fuzz-cookie\n' > ../cookie && chmod 600 ../cookie && \
	"$(BEES_ROOT)/tools/bees_config_beam.py" generate --config bees.config --beam node.beam -o lib node.wire 1>&2 && \
	"$(EDGE_GEN)" dangerous_bl dangerous_bl.silica $(USES) $(PART) $(FROLES)/fuzz_node.role $(ROLES)/cookie_conf.role $(ROLES)/timing_conf.role $(FROLES)/fuzz_listen.role)
include $(BEES_ROOT)/tools/trial.mk

clean: clean-generated
.PHONY: clean-generated
clean-generated:
	@cd "$(LEAF_DIR)" && rm -f dangerous_*.silica lib/beam_conf.silica lib/beam_peers.silica
