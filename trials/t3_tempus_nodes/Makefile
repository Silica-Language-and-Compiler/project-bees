# T3: TEMPUS nodes over real TLS on 127.0.0.1 (development-plan/tempus-design.md sections 3 to 6, 8 to 10, 16.3): three node
# test programs (externally driven nodes with the test unit of src/tempus_test), the sentinel S (dangerous_s), the edges A and B (dangerous_a, dangerous_b), and the
# Python client (example_tempus_clients/python/bees_tempus_client.py) as the peer that sends the tick and clock frames, shuffles, listens and
# misbehaves. tools/bees_tempus_trial.py t3 starts the nodes one after another, walks the steps (each waits for its reply
# and for the node lines that end it, so the nodes' outputs are in one order), checks what the client can see, and stops
# the nodes. What the client cannot see (a node's view after a step) is in the nodes' goldens.
# Each node's root unit is generated (tools/bees_tempus_gen.py) from the carrier edge, the TEMPUS link edge, the node part
# and its role files; lib/bees_tempus_node.silica is generated from src/tempus/bees_tempus_node.silica.in.
# Post-processing: tools/bees_tempus_reports.py (the runtime's reports of actors that ended normally, which land anywhere
# and can be written into each other; any other reason is kept). Nothing is reordered: every step ends before the next
# begins, and the step that holds three connections open at once opens and closes them half a second apart.
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)
LEAF_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
GEN := $(BEES_ROOT)/tools/bees_tempus_gen.py
# The generated units are made by the rule of .gen.mk, an included makefile: when it is remade, make starts again and reads
# the directory afresh (make 3.81 lists a directory once, so units generated while the makefiles are read are not seen
# by the wildcards of tools/trial.mk in the same run).
SRC_T := $(BEES_ROOT)/src/tempus
-include $(LEAF_DIR)/.gen.mk
$(LEAF_DIR)/.gen.mk: $(LEAF_DIR)/s.role $(LEAF_DIR)/a.role $(LEAF_DIR)/b.role $(LEAF_DIR)/node.role $(GEN) $(SRC_T)/bees_tempus_node.silica.in $(SRC_T)/bees_tempus_node.part $(SRC_T)/bees_tempus_link.part $(BEES_ROOT)/src/shim/bees_tcp_edge.part
	@cd "$(LEAF_DIR)" && python3 "$(GEN)" unit "$(SRC_T)/bees_tempus_node.silica.in" lib/bees_tempus_node.silica && \
	for n in s a b; do python3 "$(GEN)" edge dangerous_$$n dangerous_$$n.silica --use tempus_ids --use bees_tempus_store --use bees_tempus_store_actor --use bees_tempus_node --use dangerous_bees_tempus_draws --use bees_tempus_test --part bees_tempus_node.part $$n.role node.role || exit 1; done && \
	echo "# written by the rule of this file in the Makefile: the generated units are current" > .gen.mk
include $(BEES_ROOT)/tools/trial.mk
# the nodes run together, started and stopped by the trial tool: none runs alone
PAIRED := $(ENTRIES)

.PHONY: natives fixtures together clean-generated
build: natives fixtures
natives:
	@out=$$($(MAKE) --no-print-directory -C "$(BEES_ROOT)/native" tempus tls 2>&1); rc=$$?; \
	[ -z "$$out" ] || printf '%s\n' "$$out" | grep -v '^ar \|^cc \|^mkdir ' ; \
	if [ "$$rc" != 0 ]; then echo "FAIL: [t3_tempus_nodes] needs the TEMPUS native edge and the TLS engine (make -C native tempus tls; OpenSSL 4.1.0 or later)"; exit 1; fi
fixtures:
	@python3 "$(BEES_ROOT)/tools/bees_tempus_certs.py" check > /dev/null && python3 "$(BEES_ROOT)/tools/bees_tempus_ids.py" check "$(LEAF_DIR)/lib/tempus_ids.silica" ../t5_tempus_tls/certs/ > /dev/null || { echo "FAIL: [t3_tempus_nodes] the certificates or lib/tempus_ids.silica are not what the tools write"; exit 1; }
together: run
	@cd "$(LEAF_DIR)" && python3 "$(BEES_ROOT)/tools/bees_tempus_trial.py" t3 . && \
	python3 "$(BEES_ROOT)/tools/bees_tempus_reports.py" dangerous_s.sout dangerous_a.sout dangerous_b.sout
integrate: together
record-golden: together
clean: clean-generated
clean-generated:
	@cd "$(LEAF_DIR)" && rm -f dangerous_[sab].silica lib/bees_tempus_node.silica .gen.mk
