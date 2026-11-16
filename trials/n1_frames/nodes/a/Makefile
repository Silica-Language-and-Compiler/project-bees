# N1 big frames, node a: one manifest (node.wire), its bees.config (frame_size_max; the one reader tools/bees_conf.py, a
# build-time stand-in) and the entry below, generated at parse time from the carrier edge and roles (M3's auth-none node).
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../../../..)
LEAF_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
EDGE_GEN := $(BEES_ROOT)/tools/bees_edge_gen.py
USES := --use bees_msgs --use bees_dist --use dangerous_bees_net --use bees_peers
_ := $(shell cd "$(LEAF_DIR)" && \
	"$(EDGE_GEN)" dangerous_a_echo dangerous_a_echo.silica $(USES) $(BEES_ROOT)/trials/m3_dist/roles/node.role $(BEES_ROOT)/trials/n1_frames/roles/timing_big.role $(BEES_ROOT)/trials/n1_frames/roles/echo.role)
include $(BEES_ROOT)/tools/trial.mk

clean: clean-generated
.PHONY: clean-generated
clean-generated:
	@cd "$(LEAF_DIR)" && rm -f dangerous_*.silica lib/bees_peers.silica
