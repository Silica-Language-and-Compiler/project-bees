# The driver application of the Silica example TEMPUS client. EXAMPLE ONLY, not for production (../../README.md).
# One program per instance, because a Silica program here reads no command line: its values are compiled in.
#   dangerous_gs  the sentinel (identity sentinel, port 24800)
#   dangerous_g1  an edge (identity node, port 24801)      dangerous_g2  an edge (identity other, port 24802)
#   dangerous_g3  an edge (identity x1, port 24803)
# Each is the thin application peer.role with the instance's own role file, over the client library of ../lib:
# bees_tempus_peer.part (the member of the network: stores, timers, join) and bees_tempus_client.part (single
# connections: the application asks its own peer for samples). No unit of the test unit is listed: the programs hold no
# tick and no clock frame.
#   make build    the four programs
#   make gossip   build, then run them together as one network on this machine (../../gossip/gossip_run.py run silica)
#   make clean
# The programs are started and stopped by the runner; none runs alone. Their output depends on timing and on random
# draws, so this leaf has no goldens of its own: the runner's check is compared (trials/c7_tempus_gossip).
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../../..)
LEAF_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
T := $(BEES_ROOT)/tools
GEN := $(T)/bees_tempus_gen.py
SRC_T := $(BEES_ROOT)/src/tempus
LIB_C := $(BEES_ROOT)/example_tempus_clients/silica/lib
RUNNER := $(BEES_ROOT)/example_tempus_clients/gossip/gossip_run.py
INSTANCES := gs g1 g2 g3
USES := --use tempus_ids --use gossip_tokens --use bees_tempus_store --use bees_tempus_store_actor --use bees_tempus_node --use dangerous_bees_tempus_draws --use bees_tempus_client
PARTS := --part bees_tempus_node.part --part example_tempus_clients/silica/lib/bees_tempus_peer.part --part example_tempus_clients/silica/lib/bees_tempus_client.part
# the generated units are made by the rule of .gen.mk, an included makefile (make 3.81 lists a directory once)
-include $(LEAF_DIR)/.gen.mk
$(LEAF_DIR)/.gen.mk: $(wildcard $(LEAF_DIR)/*.role) $(GEN) $(T)/bees_tempus_ids.py $(RUNNER) $(SRC_T)/bees_tempus_node.silica.in $(SRC_T)/bees_tempus_node.part $(SRC_T)/bees_tempus_link.part $(LIB_C)/bees_tempus_peer.part $(LIB_C)/bees_tempus_client.part $(BEES_ROOT)/src/shim/bees_tcp_edge.part
	@cd "$(LEAF_DIR)" && python3 "$(T)/bees_tempus_ids.py" write lib/tempus_ids.silica ../../../trials/t5_tempus_tls/certs/ && \
	python3 "$(RUNNER)" tokens-unit write lib/gossip_tokens.silica && \
	python3 "$(GEN)" unit "$(SRC_T)/bees_tempus_node.silica.in" lib/bees_tempus_node.silica && \
	for n in $(INSTANCES); do python3 "$(GEN)" edge dangerous_$$n dangerous_$$n.silica $(USES) $(PARTS) $$n.role peer.role || exit 1; done && \
	echo "# written by the rule of this file in the Makefile: the generated units are current" > .gen.mk
include $(BEES_ROOT)/tools/trial.mk
PAIRED := $(ENTRIES)

.PHONY: natives gossip clean-generated
build: natives
natives:
	@out=$$($(MAKE) --no-print-directory -C "$(BEES_ROOT)/native" tls tempus 2>&1); rc=$$?; \
	[ -z "$$out" ] || printf '%s\n' "$$out" | grep -v '^ar \|^cc \|^mkdir ' ; \
	if [ "$$rc" != 0 ]; then echo "FAIL: [silica driver] needs the TEMPUS native edge and the TLS engine (make -C native tls tempus; OpenSSL 4.1.0 or later)"; exit 1; fi
gossip: build
	@python3 "$(RUNNER)" run silica
clean: clean-generated
clean-generated:
	@cd "$(LEAF_DIR)" && rm -f $(INSTANCES:%=dangerous_%.silica) .gen.mk lib/tempus_ids.silica lib/gossip_tokens.silica lib/bees_tempus_node.silica
