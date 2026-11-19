# C2: both TEMPUS clients drive the behaviour list of development-plan/tempus-design.md section 16.2 (COVERAGE.md beside
# this file says which row is driven by which client, where its result is seen, and by which step).
#   dangerous_n  node N, a test node (control_test_only): driven by the pure-Python client (tools/bees_tempus_client.py)
#   dangerous_m  node M, the same node on another port: driven by the Silica client
#   dangerous_o  node O, not a test node: both clients send it a tick (row 37)
#   dangerous_cs the Silica client as a sentinel (M joins through it); dangerous_ce the Silica client as an edge
# The Silica client is the library of src/tempus_client (bees_tempus_client.silica, bees_tempus_client.part) under the thin
# application client.role; each role's scenario is compiled in (cs.role, ce.role; ruling OQ-21).
# tools/bees_tempus_trial.py c2 starts the processes, walks the Python client's steps against N and O, waits for the
# Silica clients' `done`, and stops everything. What a client cannot see (a node's view, the reason of a refusal) is in
# the nodes' goldens (ruling NQ-1).
# Post-processing: tools/bees_tempus_reports.py (the runtime's reports of actors that ended normally land anywhere).
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)
LEAF_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
GEN := $(BEES_ROOT)/tools/bees_tempus_gen.py
SRC_T := $(BEES_ROOT)/src/tempus
SRC_C := $(BEES_ROOT)/src/tempus_client
NODE_USES := --use tempus_ids --use bees_tempus_store --use bees_tempus_store_actor --use bees_tempus_node --use dangerous_bees_tempus_draws
# the generated units are made by the rule of .gen.mk, an included makefile (make 3.81 lists a directory once)
-include $(LEAF_DIR)/.gen.mk
$(LEAF_DIR)/.gen.mk: $(wildcard $(LEAF_DIR)/*.role) $(GEN) $(SRC_T)/bees_tempus_node.silica.in $(SRC_T)/bees_tempus_node.part $(SRC_T)/bees_tempus_link.part $(SRC_C)/bees_tempus_client.part $(BEES_ROOT)/src/shim/bees_tcp_edge.part
	@cd "$(LEAF_DIR)" && python3 "$(GEN)" unit "$(SRC_T)/bees_tempus_node.silica.in" lib/bees_tempus_node.silica && \
	for n in n m o; do python3 "$(GEN)" edge dangerous_$$n dangerous_$$n.silica $(NODE_USES) --part bees_tempus_node.part $$n.role node.role || exit 1; done && \
	for n in cs ce; do python3 "$(GEN)" edge dangerous_$$n dangerous_$$n.silica --use tempus_ids --use bees_tempus_client --part tempus_client/bees_tempus_client.part $$n.role client.role || exit 1; done && \
	echo "# written by the rule of this file in the Makefile: the generated units are current" > .gen.mk
include $(BEES_ROOT)/tools/trial.mk
# the processes run together, started and stopped by the trial tool: none runs alone
PAIRED := $(ENTRIES)

.PHONY: natives fixtures together clean-generated
build: natives fixtures
natives:
	@out=$$($(MAKE) --no-print-directory -C "$(BEES_ROOT)/native" tempus tls 2>&1); rc=$$?; \
	[ -z "$$out" ] || printf '%s\n' "$$out" | grep -v '^ar \|^cc \|^mkdir ' ; \
	if [ "$$rc" != 0 ]; then echo "FAIL: [c2_tempus_clients] needs the TEMPUS native edge and the TLS engine (make -C native tempus tls; OpenSSL 4.1.0 or later)"; exit 1; fi
fixtures:
	@python3 "$(BEES_ROOT)/tools/bees_tempus_certs.py" check > /dev/null && python3 "$(BEES_ROOT)/tools/bees_tempus_ids.py" check "$(LEAF_DIR)/lib/tempus_ids.silica" ../t5_tempus_tls/certs/ > /dev/null || { echo "FAIL: [c2_tempus_clients] the certificates or lib/tempus_ids.silica are not what the tools write"; exit 1; }
# Seen once on 2026-11-18 (silica-999909, a loaded machine): a build whose silica.atoms lacked every atom of the stdlib
# carrier unit (:link_up, :accepted, ...); each program's listening link then ended at start with `no case arm matched`.
# The next build of the same sources was whole. The check says so instead of letting the trial time out.
together: run
	@cd "$(LEAF_DIR)" && { grep -q ':link_up' silica.atoms && grep -q ':accepted' silica.atoms || { echo "FAIL: [c2_tempus_clients] this build's silica.atoms lacks the carrier's atoms (a compiler fault seen once): make clean and build again"; exit 1; }; } && python3 "$(BEES_ROOT)/tools/bees_tempus_trial.py" c2 . && \
	python3 "$(BEES_ROOT)/tools/bees_tempus_reports.py" dangerous_n.sout dangerous_m.sout dangerous_o.sout dangerous_cs.sout dangerous_ce.sout
integrate: together
record-golden: together
clean: clean-generated
clean-generated:
	@cd "$(LEAF_DIR)" && rm -f dangerous_n.silica dangerous_m.silica dangerous_o.silica dangerous_cs.silica dangerous_ce.silica lib/bees_tempus_node.silica .gen.mk
