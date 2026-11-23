# The three Silica node programs of the C13 trial, built the way trials/c2_tempus_clients builds its nodes. The trial's own
# Makefile runs this file with `make -f nodes.mk build`; nothing here runs a program.
#   dangerous_s  node S, a sentinel, a test program (externally driven, with the test unit of src/tempus_test)
#   dangerous_a  node A, an edge, a test program
#   dangerous_q  node Q, an edge, not a test program (its root unit does not use the test unit)
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)
LEAF_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
GEN := $(BEES_ROOT)/tools/bees_tempus_gen.py
SRC_T := $(BEES_ROOT)/src/tempus
NODE_USES := --use tempus_ids --use bees_tempus_store --use bees_tempus_store_actor --use bees_tempus_node --use dangerous_bees_tempus_draws
# the generated units are made by the rule of .gen.mk, an included makefile (make 3.81 lists a directory once)
-include $(LEAF_DIR)/.gen.mk
$(LEAF_DIR)/.gen.mk: $(wildcard $(LEAF_DIR)/*.role) $(GEN) $(SRC_T)/bees_tempus_node.silica.in $(SRC_T)/bees_tempus_node.part $(SRC_T)/bees_tempus_link.part $(BEES_ROOT)/src/shim/bees_tcp_edge.part
	@cd "$(LEAF_DIR)" && python3 "$(GEN)" unit "$(SRC_T)/bees_tempus_node.silica.in" lib/bees_tempus_node.silica && \
	python3 "$(GEN)" edge dangerous_s dangerous_s.silica $(NODE_USES) --use bees_tempus_test --part bees_tempus_node.part s.role node.role && \
	python3 "$(GEN)" edge dangerous_a dangerous_a.silica $(NODE_USES) --use bees_tempus_test --part bees_tempus_node.part a.role node.role && \
	python3 "$(GEN)" edge dangerous_q dangerous_q.silica $(NODE_USES) --part bees_tempus_node.part q.role node.role && \
	echo "# written by the rule of this file in nodes.mk: the generated units are current" > .gen.mk
include $(BEES_ROOT)/tools/trial.mk
.PHONY: clean-generated
clean: clean-generated
clean-generated:
	@cd "$(LEAF_DIR)" && rm -f dangerous_s.silica dangerous_a.silica dangerous_q.silica lib/bees_tempus_node.silica .gen.mk
