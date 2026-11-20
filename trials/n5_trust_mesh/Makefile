# N5 mesh: the example application examples/trust_mesh, built and run as a trial. Five TRUST-mode nodes on this machine
# (127.0.0.1), each a TRUST server and a TRUST client of the other four, over mutual TLS 1.3 with sessions (N5): a complete
# mesh of 20 directed pairs, each used once per lap by a baton that goes round twice (40 calls on 20 TLS connections).
# The sources, the configuration of the five nodes, the TEST ONLY certificates, the runner (mesh_run.py) and the goldens
# (mesh.n1 ... mesh.n5, mesh.check) live in the example's directory; its README.md says what the check shows.
# Ports: tools/trial_ports.py n5_trust_mesh +1 to +5. The trial needs the TLS engine (make -C native tls: OpenSSL 4.1.0 or
# later). Without it the leaf FAILS; it never skips.
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)
THIS_LEAF := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
MESH := $(BEES_ROOT)/examples/trust_mesh

.DEFAULT_GOAL := build
.PHONY: build run integrate record-golden clean

build run record-golden:
	@$(MAKE) --no-print-directory -C "$(MESH)" $@

integrate:
	@rm -f "$(MESH)/.integrate_counts"; $(MAKE) --no-print-directory -C "$(MESH)" integrate; rc=$$?; \
	if [ -f "$(MESH)/.integrate_counts" ]; then cp "$(MESH)/.integrate_counts" "$(THIS_LEAF)/.integrate_counts"; fi; exit $$rc

clean:
	@$(MAKE) --no-print-directory -C "$(MESH)" clean; rm -f "$(THIS_LEAF)/.integrate_counts"
