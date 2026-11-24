# C14: the client half of the Rust TEMPUS extension (example_tempus_clients/rust, command line tempus-client) against real nodes on this machine, and against the
# Python test support. example_tempus_clients/rust/README.md says what the steps show; the steps themselves are in
# client_walk.py and, with each result, in the golden of `rust`.
#   dangerous_n  node N, a test program (externally driven, with the test unit of src/tempus_test; its clock is the
#                trial's 1500): it joins through the Rust client's sentinel listener and is then dialed by the Rust client
#   dangerous_p  node P, not a test program: it reads the system clock; it joins through a second Rust listener
#   rust        the Rust client's own lines: every command the trial tool ran and the outcome line it printed
# client_walk.py starts the processes, runs the Rust command line for each step, checks each step's
# line, and stops everything. The Rust client sends no test-only frame: the ticks that make node N shuffle are sent by
# the trial tool through the Python test support. What a client cannot see (a node's view, the reason of a refusal) is
# in the nodes' goldens (ruling NQ-1).
# Rust is installed on the Mac only. Without a Rust toolchain the leaf fails and says so; the runner does not run it on a platform it is not
# declared for (the file `platforms` of this directory: N/A there), and its goldens are Mac goldens with no Linux twin.
# Post-processing: tools/bees_tempus_reports.py (the runtime's reports of actors that ended normally land anywhere).
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)
LEAF_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
GEN := $(BEES_ROOT)/tools/bees_tempus_gen.py
SRC_T := $(BEES_ROOT)/src/tempus
RUST_DIR := $(BEES_ROOT)/example_tempus_clients/rust
CARGO ?= $(or $(shell command -v cargo 2>/dev/null),$(wildcard $(HOME)/.cargo/bin/cargo))
NODE_USES := --use tempus_ids --use bees_tempus_store --use bees_tempus_store_actor --use bees_tempus_node --use dangerous_bees_tempus_draws
OUTS := dangerous_n dangerous_p rust
HAVE_RUST := $(if $(CARGO),yes)
# the generated units are made by the rule of .gen.mk, an included makefile (make 3.81 lists a directory once)
-include $(LEAF_DIR)/.gen.mk
$(LEAF_DIR)/.gen.mk: $(wildcard $(LEAF_DIR)/*.role) $(GEN) $(SRC_T)/bees_tempus_node.silica.in $(SRC_T)/bees_tempus_node.part $(SRC_T)/bees_tempus_link.part $(BEES_ROOT)/src/shim/bees_tcp_edge.part
	@cd "$(LEAF_DIR)" && python3 "$(GEN)" unit "$(SRC_T)/bees_tempus_node.silica.in" lib/bees_tempus_node.silica && \
	python3 "$(GEN)" edge dangerous_n dangerous_n.silica $(NODE_USES) --use bees_tempus_test --part bees_tempus_node.part n.role node.role && \
	python3 "$(GEN)" edge dangerous_p dangerous_p.silica $(NODE_USES) --part bees_tempus_node.part p.role node.role && \
	echo "# written by the rule of this file in the Makefile: the generated units are current" > .gen.mk
include $(BEES_ROOT)/tools/trial.mk
# the processes run together, started and stopped by the trial tool: none runs alone
PAIRED := $(ENTRIES)

.PHONY: natives fixtures rust-client together clean-generated
ifeq ($(HAVE_RUST),yes)
build: natives fixtures rust-client
natives:
	@out=$$($(MAKE) --no-print-directory -C "$(BEES_ROOT)/native" tempus tls 2>&1); rc=$$?; \
	[ -z "$$out" ] || printf '%s\n' "$$out" | grep -v '^ar \|^cc \|^mkdir ' ; \
	if [ "$$rc" != 0 ]; then echo "FAIL: [c14_tempus_rust] needs the TEMPUS native edge and the TLS engine (make -C native tempus tls; OpenSSL 4.1.0 or later)"; exit 1; fi
fixtures:
	@python3 "$(BEES_ROOT)/tools/bees_tempus_certs.py" check > /dev/null && python3 "$(BEES_ROOT)/tools/bees_tempus_ids.py" check "$(LEAF_DIR)/lib/tempus_ids.silica" ../t5_tempus_tls/certs/ > /dev/null || { echo "FAIL: [c14_tempus_rust] the certificates or lib/tempus_ids.silica are not what the tools write"; exit 1; }
# the Rust client and its unit tests (they compare its bytes with the goldens of trials/t2_tempus_frames)
rust-client:
	@$(MAKE) --no-print-directory -C "$(RUST_DIR)" test
together: run
	@cd "$(LEAF_DIR)" && { grep -q ':link_up' silica.atoms && grep -q ':accepted' silica.atoms || { echo "FAIL: [c14_tempus_rust] this build's silica.atoms lacks the carrier's atoms (a compiler fault seen once, see trials/c2_tempus_clients/Makefile): make clean and build again"; exit 1; }; } && \
	python3 client_walk.py . "$(RUST_DIR)/target/debug/tempus-client" && \
	python3 "$(BEES_ROOT)/tools/bees_tempus_reports.py" dangerous_n.sout dangerous_p.sout
integrate: together
	@cd "$(LEAF_DIR)" && ok=0; ko=0; for o in $(OUTS); do g="$$o$(GOLD_SUFFIX).scout"; \
		if [ ! -f "$$g" ]; then echo "MISSING golden for $(BEES_PLATFORM_ID) (record one on this platform with make record-golden): [c14_tempus_rust] $$g"; ko=$$((ko+1)); \
		elif diff -q "$$o.sout" "$$g" > /dev/null; then ok=$$((ok+1)); \
		else echo "DIFF: [c14_tempus_rust] $$o"; diff "$$g" "$$o.sout" || true; ko=$$((ko+1)); fi; done; \
	printf '%d %d\n' "$$ok" "$$ko" > .integrate_counts; echo "[c14_tempus_rust] $$ok passed, $$ko failed"; [ "$$ko" -eq 0 ]
record-golden: together
	@cd "$(LEAF_DIR)" && for o in $(OUTS); do cp "$$o.sout" "$$o$(GOLD_SUFFIX).scout"; done; echo "[c14_tempus_rust] goldens recorded"
else
# no Rust toolchain on this machine: the leaf FAILS and says so (a trial never skips by itself). tools/run_all_trials.py does not run it
# on a platform it is not declared for (trials/c14_tempus_rust/platforms), where it is reported N/A.
build run integrate record-golden:
	@echo "FAIL: [c14_tempus_rust] no Rust toolchain (cargo) is installed, on PATH or under ~/.cargo/bin; this trial needs it (example_tempus_clients/rust/README.md)"; exit 1
endif
clean: clean-generated
clean-generated:
	@cd "$(LEAF_DIR)" && rm -f dangerous_n.silica dangerous_p.silica lib/bees_tempus_node.silica .gen.mk rust.sout
