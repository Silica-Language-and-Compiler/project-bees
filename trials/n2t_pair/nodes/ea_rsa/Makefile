# N2T node leaf ea_rsa (BEAM mode inside TLS): one manifest (node.wire), bees.config (tools/bees_config_beam.py writes lib/beam_conf.silica and
# lib/beam_peers.silica) and its entry programs, whose root units are generated at parse time from the carrier edge, the BEAM-mode node
# edge and roles; `--use dangerous_beam_tls` makes tools/bees_edge_gen.py wrap every link carrier in the BEAM TLS link.
# The cookie and the test certificates' key modes are set first (git keeps no modes).
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../../../..)
LEAF_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
EDGE_GEN := $(BEES_ROOT)/tools/bees_edge_gen.py
PART := $(BEES_ROOT)/src/shim/beam_node_edge.part
USES := --use bees_msgs --use bees_dist --use bees_ingress --use bees_peers --use beam_dist --use beam_conf --use beam_peers --use dangerous_beam_auth --use dangerous_beam_net --use dangerous_beam_tls
_ := $(shell $(MAKE) -s -C "$(BEES_ROOT)/trials/n2t_pair" cookies >/dev/null && cd "$(LEAF_DIR)" && \
	"$(BEES_ROOT)/tools/bees_config_beam.py" generate --config bees.config -o lib node.wire 1>&2 && \
	"$(EDGE_GEN)" dangerous_ea_rsa dangerous_ea_rsa.silica $(USES) $(PART) $(BEES_ROOT)/trials/n2_multilink/roles/node.role $(BEES_ROOT)/trials/n2_multilink/roles/cookie_conf.role $(BEES_ROOT)/trials/n2_multilink/roles/timing_slow.role $(BEES_ROOT)/trials/n2_multilink/roles/edge_a.role)
include $(BEES_ROOT)/tools/trial.mk

clean: clean-generated
.PHONY: clean-generated
clean-generated:
	@cd "$(LEAF_DIR)" && rm -f dangerous_*.silica lib/beam_conf.silica lib/beam_peers.silica
