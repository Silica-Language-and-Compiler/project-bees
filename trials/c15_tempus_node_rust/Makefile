# C15: the Rust TEMPUS extension as a node (example_tempus_clients/rust, crate lib/tempus) in a mixed network on
# 127.0.0.1 with Silica nodes. walk.py beside this file starts every process, walks the steps and checks each one; its
# head says what the steps show. Each Silica program is built in its own directory under nodes/, so that each has its
# own list of units (lib/), as in trials/t6_tempus_clock:
#   nodes/s  node S, a Silica sentinel, a test program (externally driven, with the test unit of src/tempus_test; its
#            clock is the trial's 1500). The Silica node E and the Rust node A join through it
#   nodes/e  node E, a Silica edge, a test program. It shuffles with A in both directions, and every refusal of A is
#            compared with E's refusal of the same peer
#   nodes/p  node P, a Silica edge shaped like a production program: its lib/ lists neither the test unit nor its
#            atoms. It reads the machine's clock. It joins through R
# The Rust nodes are programs of the Rust package:
#   a        node A, an edge whose clock, timers and draws the trial sets (clock_back hold, clock_fail continue)
#   t        node T, an edge with clock_back stop, limit 60, and clock_fail pause, and no sentinel that answers
#   u        node U, a sentinel whose clock cannot be read at its start
#   r        node R, a sentinel that is not a test node at all: the program tempus-node-example, which links nothing
#            of the tests, reads the machine's clock and runs its own timers
# Outputs, each compared with its golden: s, e and p (the Silica nodes), a, t, u and r (the Rust nodes), walk (the
# steps, what each one saw on the wire, and the comparison of each refusal), and client: the lines of the Rust CLIENT
# (the command line tempus-client), which after node A has stopped is run against S and E for the rows of the behaviour
# list that trials/c14_tempus_rust does not show (trials/c17_tempus_bridge_rust/COVERAGE.md).
# What a peer cannot see (a node's view, the reason of a refusal) is in the nodes' own outputs (ruling NQ-1).
# Rust is installed on the Mac only. This trial never skips: without a Rust toolchain or OpenSSL it fails and says so. The
# runner does not run it on a platform it is not declared for (the file `platforms` of this directory: N/A there), and
# its goldens are Mac goldens with no Linux twin.
# Post-processing: tools/bees_tempus_reports.py (the runtime's reports of actors that ended normally land anywhere;
# the stage at which a peer's close is noticed is written `(any)`).
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)
HERE := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
include $(BEES_ROOT)/tools/silica.mk
RUST_DIR := $(BEES_ROOT)/example_tempus_clients/rust
CARGO ?= $(or $(shell command -v cargo 2>/dev/null),$(wildcard $(HOME)/.cargo/bin/cargo))
NODES := s e p
OUTS := s e p a t u r walk client
.DEFAULT_GOAL := build
.PHONY: build run integrate record-golden clean tools natives rust-node
# this trial never skips: a machine without Rust or without OpenSSL fails here and says what is missing
tools:
	@[ -n "$(CARGO)" ] || { echo "FAIL: [c15_tempus_node_rust] no Rust toolchain (cargo) is installed, on PATH or under ~/.cargo/bin; this trial needs one (example_tempus_clients/rust/README.md says what to install)"; exit 1; }
	@[ -n "$(firstword $(foreach p,$(PLATFORM_OPENSSL_DIRS),$(wildcard $(p)/include/openssl/ssl.h)))$(OPENSSL_PREFIX)" ] || { echo "FAIL: [c15_tempus_node_rust] no OpenSSL found; this trial needs OpenSSL 4.1.0 or later (example_tempus_clients/rust/README.md says what to install)"; exit 1; }
natives:
	@out=$$($(MAKE) --no-print-directory -C "$(BEES_ROOT)/native" tempus tls 2>&1); rc=$$?; \
	[ -z "$$out" ] || printf '%s\n' "$$out" | grep -v '^ar \|^cc \|^mkdir ' ; \
	if [ "$$rc" != 0 ]; then echo "FAIL: [c15_tempus_node_rust] needs the TEMPUS native edge and the TLS engine (make -C native tempus tls; OpenSSL 4.1.0 or later)"; exit 1; fi
# the Rust extension, its unit tests (the frames against trials/t2_tempus_frames; the clock, the configuration and
# admission against the recorded outputs of the BEES trials) and the comparison of its stores with the Python models
rust-node: tools
	@$(MAKE) --no-print-directory -C "$(RUST_DIR)" test
build: tools natives rust-node
	@python3 "$(BEES_ROOT)/tools/bees_tempus_certs.py" check > /dev/null || { echo "FAIL: [c15_tempus_node_rust] the TEMPUS certificates are not what tools/bees_tempus_certs.py writes"; exit 1; }
	@for n in $(NODES); do $(MAKE) --no-print-directory -C "$(HERE)/nodes/$$n" build SILICA_COMPILER="$(SILICA_COMPILER)" || exit 1; done
run: build
	@cd "$(HERE)" && python3 walk.py . "$(RUST_DIR)/target/debug" || exit 1; \
	for n in $(NODES); do cp "nodes/$$n/dangerous_$$n.sout" "$$n.sout"; done; \
	python3 "$(BEES_ROOT)/tools/bees_tempus_reports.py" s.sout e.sout p.sout a.sout t.sout u.sout r.sout
integrate: run
	@cd "$(HERE)" && ok=0; ko=0; for o in $(OUTS); do g="$$o$(GOLD_SUFFIX).scout"; \
		if [ ! -f "$$g" ]; then echo "MISSING golden for $(BEES_PLATFORM_ID) (record one on this platform with make record-golden): [c15_tempus_node_rust] $$g"; ko=$$((ko+1)); \
		elif diff -q "$$o.sout" "$$g" > /dev/null; then ok=$$((ok+1)); \
		else echo "DIFF: [c15_tempus_node_rust] $$o"; diff "$$g" "$$o.sout" || true; ko=$$((ko+1)); fi; done; \
	printf '%d %d\n' "$$ok" "$$ko" > .integrate_counts; echo "[c15_tempus_node_rust] $$ok passed, $$ko failed"; [ "$$ko" -eq 0 ]
record-golden: run
	@cd "$(HERE)" && for o in $(OUTS); do cp "$$o.sout" "$$o$(GOLD_SUFFIX).scout"; done; echo "[c15_tempus_node_rust] goldens recorded"
clean:
	@for n in $(NODES); do $(MAKE) --no-print-directory -C "$(HERE)/nodes/$$n" clean; done; cd "$(HERE)" && rm -f s.sout e.sout p.sout a.sout t.sout u.sout r.sout walk.sout client.sout r.seed r.token .integrate_counts
