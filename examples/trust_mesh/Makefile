# examples/trust_mesh: five TRUST-mode nodes on this machine, each a TRUST server and a TRUST client of the other four,
# over mutual TLS 1.3 (README.md). One program per node, in nodes/n1 ... nodes/n5: the same sources (roles/), each with its
# own bees.config, whitelist and pin file. The ports are the block of n5_trust_mesh in tools/trial_ports.py (+1 to +5).
#
#   make build     the TLS engine (make -C native tls: it needs OpenSSL 4.1.0 or later), then the five programs
#   make start     build, run the mesh once and print the check (mesh.check) and node 1's output
#   make integrate / record-golden / clean    as in a trial leaf; trials/n5_trust_mesh runs them from `make integrate`
#
# The compiler is the one of tools/silica.mk; to name another, write SILICA_COMPILER=... on the make command line.
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)
EXAMPLE_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
include $(BEES_ROOT)/tools/silica.mk
NODES := n1 n2 n3 n4 n5
DRIVER := python3 "$(EXAMPLE_DIR)/mesh_run.py"

.DEFAULT_GOAL := build
.PHONY: build run start integrate record-golden clean tls

# the engine, or the build fails here with native/Makefile's refusal (the OpenSSL it found, and the 4.1.0 minimum)
tls:
	@out=$$($(MAKE) --no-print-directory -C "$(BEES_ROOT)/native" tls); rc=$$?; \
	[ -z "$$out" ] || printf '%s\n' "$$out" | grep -v '^ar \|^cc ' ; \
	if [ "$$rc" != 0 ] || ! grep -q '^ok ' "$(BEES_ROOT)/native/build/tls.status" 2>/dev/null; then \
		echo "FAIL: [n5_trust_mesh] needs the TLS engine, which needs OpenSSL 4.1.0 or later: $$(cat "$(BEES_ROOT)/native/build/tls.status" 2>/dev/null)"; exit 1; fi

# (the first make of a node writes its generated units; the second sees them and builds)
build: tls
	@for n in $(NODES); do $(MAKE) --no-print-directory -C "$(EXAMPLE_DIR)/nodes/$$n" units > /dev/null && $(MAKE) --no-print-directory -C "$(EXAMPLE_DIR)/nodes/$$n" build || exit 1; done

run: build
	@$(DRIVER) run

start: run
	@cat "$(EXAMPLE_DIR)/mesh.check"; echo "-- node 1 --"; cat "$(EXAMPLE_DIR)/mesh.n1.sout"

integrate: run
	@$(DRIVER) compare

record-golden: run
	@$(DRIVER) record

clean:
	@for n in $(NODES); do $(MAKE) --no-print-directory -C "$(EXAMPLE_DIR)/nodes/$$n" clean; done; \
	cd "$(EXAMPLE_DIR)" && rm -rf mesh.*.sout mesh.*.raw mesh.check .integrate_counts __pycache__
