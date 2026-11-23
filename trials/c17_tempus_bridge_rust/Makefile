# C17: the client half of the Rust TEMPUS extension (example_tempus_clients/rust, command line tempus-client) against
# real bridge nodes on 127.0.0.1, and the rows of the behaviour list (design 16.2) that trials/c14_tempus_rust does not
# show for it. COVERAGE.md beside this file says which row is shown by which step of which Rust trial. The network is
# that of trials/c17_tempus_bridge_rust, each program built in its own directory under nodes/:
#   nodes/t   node T, a plain TRUST node over mutual TLS 1.3, whitelisting the two bridges' TRUST certificates
#   nodes/b1  bridge B1, nodes/b2 bridge B2: the TRUST node as built (a TRUST client of T) and a TEMPUS node of role
#             bridge in one program (src/tempus/bees_tempus_bridge.part); test programs (externally driven, with the
#             test unit of src/tempus_test; their clock is the trial's 1500). B2 joins through the Rust client, which
#             listens as its sentinel
# walk.py beside this file starts the processes, runs the Rust command line for each step, checks each step's line,
# and stops everything. The Rust client sends no test-only frame: the ticks and clock readings that drive the bridges
# are sent by walk.py with the Python test support. Outputs, each compared with its golden: t, b1, b2 (the nodes) and
# rust (every step and the line the Rust client printed for it).
# Rust is installed on the Mac only. This trial never skips: without a Rust toolchain or OpenSSL it fails and says so. The
# runner does not run it on a platform it is not declared for (the file `platforms` of this directory: N/A there), and
# its goldens are Mac goldens with no Linux twin.
# Post-processing: tools/bees_tempus_reports.py (the runtime's reports of actors that ended normally land anywhere), and
# addresses printed by the runtime become 0xADDR.
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)
HERE := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
include $(BEES_ROOT)/tools/silica.mk
RUST_DIR := $(BEES_ROOT)/example_tempus_clients/rust
CARGO ?= $(or $(shell command -v cargo 2>/dev/null),$(wildcard $(HOME)/.cargo/bin/cargo))
NODES := t b1 b2
OUTS := t b1 b2 rust
.DEFAULT_GOAL := build
.PHONY: build run integrate record-golden clean tools natives rust-client
# this trial never skips: a machine without Rust or without OpenSSL fails here and says what is missing
tools:
	@[ -n "$(CARGO)" ] || { echo "FAIL: [c17_tempus_bridge_rust] no Rust toolchain (cargo) is installed, on PATH or under ~/.cargo/bin; this trial needs one (example_tempus_clients/rust/README.md says what to install)"; exit 1; }
	@[ -n "$(firstword $(foreach p,$(PLATFORM_OPENSSL_DIRS),$(wildcard $(p)/include/openssl/ssl.h)))$(OPENSSL_PREFIX)" ] || { echo "FAIL: [c17_tempus_bridge_rust] no OpenSSL found; this trial needs OpenSSL 4.1.0 or later (example_tempus_clients/rust/README.md says what to install)"; exit 1; }
natives:
	@out=$$($(MAKE) --no-print-directory -C "$(BEES_ROOT)/native" tempus tls 2>&1); rc=$$?; \
	[ -z "$$out" ] || printf '%s\n' "$$out" | grep -v '^ar \|^cc \|^mkdir ' ; \
	if [ "$$rc" != 0 ]; then echo "FAIL: [c17_tempus_bridge_rust] needs the TEMPUS native edge and the TLS engine (make -C native tempus tls; OpenSSL 4.1.0 or later)"; exit 1; fi
# the Rust client and its unit tests (they compare its bytes with the goldens of trials/t2_tempus_frames)
rust-client: tools
	@$(MAKE) --no-print-directory -C "$(RUST_DIR)" test
build: tools natives rust-client
	@python3 "$(BEES_ROOT)/tools/bees_tempus_certs.py" check > /dev/null || { echo "FAIL: [c17_tempus_bridge_rust] the TEMPUS certificates are not what tools/bees_tempus_certs.py writes"; exit 1; }
	@for n in $(NODES); do $(MAKE) --no-print-directory -C "$(HERE)/nodes/$$n" build SILICA_COMPILER="$(SILICA_COMPILER)" || exit 1; done
run: build
	@cd "$(HERE)" && python3 walk.py . "$(RUST_DIR)/target/debug/tempus-client" || exit 1; \
	for n in $(NODES); do cp "nodes/$$n/dangerous_$$n.sout" "$$n.sout"; done; \
	python3 "$(BEES_ROOT)/tools/bees_tempus_reports.py" t.sout b1.sout b2.sout; \
	$(SED_I) -E -e 's/0x[0-9a-f]{6,}/0xADDR/g' t.sout b1.sout b2.sout
integrate: run
	@cd "$(HERE)" && ok=0; ko=0; for o in $(OUTS); do g="$$o$(GOLD_SUFFIX).scout"; \
		if [ ! -f "$$g" ]; then echo "MISSING golden for $(BEES_PLATFORM_ID) (record one on this platform with make record-golden): [c17_tempus_bridge_rust] $$g"; ko=$$((ko+1)); \
		elif diff -q "$$o.sout" "$$g" > /dev/null; then ok=$$((ok+1)); \
		else echo "DIFF: [c17_tempus_bridge_rust] $$o"; diff "$$g" "$$o.sout" || true; ko=$$((ko+1)); fi; done; \
	printf '%d %d\n' "$$ok" "$$ko" > .integrate_counts; echo "[c17_tempus_bridge_rust] $$ok passed, $$ko failed"; [ "$$ko" -eq 0 ]
record-golden: run
	@cd "$(HERE)" && for o in $(OUTS); do cp "$$o.sout" "$$o$(GOLD_SUFFIX).scout"; done; echo "[c17_tempus_bridge_rust] goldens recorded"
clean:
	@for n in $(NODES); do $(MAKE) --no-print-directory -C "$(HERE)/nodes/$$n" clean; done; cd "$(HERE)" && rm -f t.sout b1.sout b2.sout rust.sout .integrate_counts
