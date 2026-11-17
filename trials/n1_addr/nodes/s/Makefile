# N1 node s (trials/n1_addr): bees.config is written from bees.config.in with this machine's non-loopback IPv4 address
# (ipconfig getifaddr en0, else en1), then the BEAM-mode units (tools/bees_config_beam.py, the one reader tools/bees_conf.py)
# and each entry's root unit (tools/bees_edge_gen.py; --resolve-stub pastes the resolver edge). Roles: trials/n2_dist/roles and ../../roles.
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../../../..)
LEAF_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
EDGE_GEN := $(BEES_ROOT)/tools/bees_edge_gen.py
PART := $(BEES_ROOT)/src/shim/beam_node_edge.part
USES := --use bees_msgs --use bees_dist --use bees_ingress --use bees_peers --use beam_dist --use beam_conf --use beam_peers --use dangerous_beam_auth --use dangerous_beam_net
IP := $(shell ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null)
_ := $(shell $(MAKE) -s -C "$(BEES_ROOT)/trials/n2_dist" cookies >/dev/null && cd "$(LEAF_DIR)" && \
	sed "s/@IP@/$(IP)/g" bees.config.in > bees.config && \
	"$(BEES_ROOT)/tools/bees_config_beam.py" generate --config bees.config -o lib node.wire 1>&2 && \
	"$(EDGE_GEN)" dangerous_s_watch dangerous_s_watch.silica $(USES) --resolve-stub $(PART) $(BEES_ROOT)/trials/n2_dist/roles/node.role $(BEES_ROOT)/trials/n2_dist/roles/cookie_conf.role $(BEES_ROOT)/trials/n2_dist/roles/timing_slow.role $(BEES_ROOT)/trials/n1_addr/roles/late.role $(BEES_ROOT)/trials/n1_addr/roles/watch.role)
include $(BEES_ROOT)/tools/trial.mk

clean: clean-generated
.PHONY: clean-generated
clean-generated:
	@cd "$(LEAF_DIR)" && rm -f dangerous_*.silica lib/beam_conf.silica lib/beam_peers.silica bees.config
