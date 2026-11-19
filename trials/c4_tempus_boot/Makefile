# C4 (T7's checks that need no configuration reader; design 16.2 row 28): a TEMPUS node refuses to start on values its
# application passes that break a rule, one entry per rule, each the thin application boot.role with its own role file:
#   dangerous_any       control_test_only on a listen address that is not loopback (ruling OQ-20)
#   dangerous_shuffle   a shuffle length above the store's capacity      dangerous_capacity  a capacity above 256
#   dangerous_token     an edge node with a tempus_bridge token          dangerous_producer  a producer key of 31 bytes
# Each prints the boot's one refusal line and ends with 1; nothing listens (port 24300 is a value only).
# The bridge's own refusals of its limits (bees_tempus_bridge@lim_why) are not here: they need a bridge program.
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)
LEAF_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
GEN := $(BEES_ROOT)/tools/bees_tempus_gen.py
SRC_T := $(BEES_ROOT)/src/tempus
ENTRY_ROLES := any shuffle capacity token producer
USES := --use tempus_ids --use bees_tempus_store --use bees_tempus_store_actor --use bees_tempus_node --use dangerous_bees_tempus_draws
-include $(LEAF_DIR)/.gen.mk
$(LEAF_DIR)/.gen.mk: $(wildcard $(LEAF_DIR)/*.role) $(GEN) $(SRC_T)/bees_tempus_node.silica.in $(SRC_T)/bees_tempus_node.part $(SRC_T)/bees_tempus_link.part $(BEES_ROOT)/src/shim/bees_tcp_edge.part
	@cd "$(LEAF_DIR)" && python3 "$(BEES_ROOT)/tools/bees_tempus_ids.py" write lib/tempus_ids.silica ../t5_tempus_tls/certs/ && \
	python3 "$(GEN)" unit "$(SRC_T)/bees_tempus_node.silica.in" lib/bees_tempus_node.silica && \
	for n in $(ENTRY_ROLES); do python3 "$(GEN)" edge dangerous_$$n dangerous_$$n.silica $(USES) --part bees_tempus_node.part $$n.role boot.role || exit 1; done && \
	echo "# written by the rule of this file in the Makefile: the generated units are current" > .gen.mk
include $(BEES_ROOT)/tools/trial.mk
clean: clean-generated
.PHONY: clean-generated
clean-generated:
	@cd "$(LEAF_DIR)" && rm -f $(foreach n,$(ENTRY_ROLES),dangerous_$(n).silica) lib/bees_tempus_node.silica lib/tempus_ids.silica .gen.mk
