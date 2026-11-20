# T6 and C3: TEMPUS bridge nodes (development-plan/tempus-design.md section 17) driven by both TEMPUS clients (rows 24, 25,
# 29 to 35 of 16.2; COVERAGE.md beside this file says which row is driven by which client, where its result is seen, and
# by which step). Each program is built in its own directory under nodes/ (each has its own bees.config or roles):
#   nodes/t   node T, a plain TRUST node over mutual TLS 1.3 (port +0), whitelisting the two bridges' TRUST certificates
#   nodes/b1  bridge B1, nodes/b2 bridge B2: the TRUST node as built (a TRUST client of T, pinned to a.pem) and a TEMPUS
#             node of role bridge (tempus/1 on +1 and +2) in one program (src/tempus/bees_tempus_bridge.part)
#   nodes/c   the Silica client (example_tempus_clients/silica) under the thin application roles/client.role with the scenario c.role
# tools/bees_tempus_trial.py c3 starts T, B1 and B2, walks the Python client's first part, waits for the Silica client's
# `done`, walks the Python client's second part (it stops B2 for row 33 and has T quarantine B1 at the end), and stops
# everything. Each program's output is copied here as t.sout, b1.sout, b2.sout, c.sout and compared with its golden.
# Post-processing: tools/bees_tempus_reports.py (the runtime's reports of actors that ended normally land anywhere), and
# addresses printed by the runtime become 0xADDR.
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)
HERE := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
include $(BEES_ROOT)/tools/silica.mk
NODES := t b1 b2 c
OUTS := t b1 b2 c
.PHONY: build run integrate record-golden clean natives
natives:
	@out=$$($(MAKE) --no-print-directory -C "$(BEES_ROOT)/native" tempus tls 2>&1); rc=$$?; \
	[ -z "$$out" ] || printf '%s\n' "$$out" | grep -v '^ar \|^cc \|^mkdir ' ; \
	if [ "$$rc" != 0 ]; then echo "FAIL: [c3_tempus_bridge] needs the TEMPUS native edge and the TLS engine (make -C native tempus tls; OpenSSL 4.1.0 or later)"; exit 1; fi
build: natives
	@python3 "$(BEES_ROOT)/tools/bees_tempus_certs.py" check > /dev/null || { echo "FAIL: [c3_tempus_bridge] the TEMPUS certificates are not what tools/bees_tempus_certs.py writes"; exit 1; }
	@for n in $(NODES); do $(MAKE) --no-print-directory -C "$(HERE)/nodes/$$n" build SILICA_COMPILER="$(SILICA_COMPILER)" || exit 1; done
run: build
	@cd "$(HERE)" && python3 "$(BEES_ROOT)/tools/bees_tempus_trial.py" c3 . ; \
	cp nodes/t/dangerous_t.sout t.sout; cp nodes/b1/dangerous_b1.sout b1.sout; cp nodes/b2/dangerous_b2.sout b2.sout; cp nodes/c/dangerous_c.sout c.sout; \
	python3 "$(BEES_ROOT)/tools/bees_tempus_reports.py" t.sout b1.sout b2.sout c.sout; \
	$(SED_I) -E -e 's/0x[0-9a-f]{6,}/0xADDR/g' t.sout b1.sout b2.sout c.sout
integrate: run
	@cd "$(HERE)" && ok=0; ko=0; for o in $(OUTS); do g="$$o$(GOLD_SUFFIX).scout"; \
		if [ ! -f "$$g" ]; then echo "MISSING golden for $(BEES_PLATFORM_ID) (record one on this platform with make record-golden): [c3_tempus_bridge] $$g"; ko=$$((ko+1)); \
		elif diff -q "$$o.sout" "$$g" > /dev/null; then ok=$$((ok+1)); \
		else echo "DIFF: [c3_tempus_bridge] $$o"; diff "$$g" "$$o.sout" || true; ko=$$((ko+1)); fi; done; \
	printf '%d %d\n' "$$ok" "$$ko" > .integrate_counts; echo "[c3_tempus_bridge] $$ok passed, $$ko failed"; [ "$$ko" -eq 0 ]
record-golden: run
	@cd "$(HERE)" && for o in $(OUTS); do cp "$$o.sout" "$$o$(GOLD_SUFFIX).scout"; done; echo "[c3_tempus_bridge] goldens recorded"
clean:
	@for n in $(NODES); do $(MAKE) --no-print-directory -C "$(HERE)/nodes/$$n" clean; done; cd "$(HERE)" && rm -f t.sout b1.sout b2.sout c.sout .integrate_counts
