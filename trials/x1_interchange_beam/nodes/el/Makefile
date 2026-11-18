# x1_interchange_beam node el (BEES listening and registered with the stock node's EPMD; the stock erl node on the OTHER machine dials it; trials/n2_live's node l with this trial's ports). Built and run by tools/bees_interchange.py, on the machine that runs this node
# only; never by `make integrate` (the trial has no leaf Makefile). bees.config is written from bees.config.in: @THERE_HOST@ is
# the remote machine's name (X_THERE_HOST, from .bees_build_hosts), so no tracked file names a machine. The cookie file
# (../../cookie) is a random one the driver writes on both machines for each run. Roles: trials/n2_dist/roles (the node's
# startup, the cookie and timing of bees.config) and trials/n2_live/roles.
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../../../..)
LEAF_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
ROLES := $(BEES_ROOT)/trials/n2_dist/roles
EDGE_GEN := $(BEES_ROOT)/tools/bees_edge_gen.py
PART := $(BEES_ROOT)/src/shim/beam_node_edge.part
USES := --use bees_msgs --use bees_dist --use bees_ingress --use bees_peers --use beam_dist --use beam_conf --use beam_peers --use dangerous_beam_auth --use dangerous_beam_net
X_THERE_HOST ?= there.invalid
# this machine as the remote dials it, and what the listeners here bind: 127.0.0.1 (an ssh -R forward, the default), or this
# machine's reachable address and 0.0.0.0 (the driver's --here-address: the remote dials this machine directly)
X_HERE_HOST ?= 127.0.0.1
X_HERE_LISTEN ?= 127.0.0.1
_ := $(shell cd "$(LEAF_DIR)" && { [ -f ../../cookie ] || echo "x1_interchange_beam: no cookie file; tools/bees_interchange.py writes one for each run" 1>&2; } && \
	sed -e "s/@THERE_HOST@/$(X_THERE_HOST)/g" -e "s/@HERE_HOST@/$(X_HERE_HOST)/g" -e "s/@HERE_LISTEN@/$(X_HERE_LISTEN)/g" bees.config.in > bees.config && \
	"$(BEES_ROOT)/tools/bees_config_beam.py" generate --config bees.config --beam node.beam -o lib node.wire 1>&2 && \
	"$(EDGE_GEN)" dangerous_el dangerous_el.silica $(USES) $(PART) $(ROLES)/node.role $(ROLES)/cookie_conf.role $(ROLES)/timing_conf.role $(BEES_ROOT)/trials/n2_live/roles/live_svc.role)
include $(BEES_ROOT)/tools/trial.mk

clean: clean-generated
.PHONY: clean-generated
clean-generated:
	@cd "$(LEAF_DIR)" && rm -f dangerous_*.silica lib/beam_conf.silica lib/beam_peers.silica bees.config .interchange_stamp
