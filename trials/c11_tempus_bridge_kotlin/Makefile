# C11: the client half of the Kotlin extension (example_tempus_clients/kotlin) against real bridge nodes on 127.0.0.1.
# The network is that of trials/c3_tempus_bridge, on this trial's own ports (the node directories and roles are copies of
# that trial's, with the ports changed and nothing else):
#   nodes/t   node T, a plain TRUST node over mutual TLS 1.3 (port +0), whitelisting the two bridges' TRUST certificates
#   nodes/b1  bridge B1, nodes/b2 bridge B2: a TRUST client of T and a TEMPUS node of role bridge (tempus/1 on +1 and +2)
#             in one program; test programs (externally driven, with the test unit of src/tempus_test)
#   kotlin    the walk's transcript (Bridge.kt): one line per step, each step checked by the Kotlin program
# walk.py starts and stops the node processes and sends the bridges the test-only tick and clock frames with the Python
# test support (the Kotlin extension holds no test frame). COVERAGE.md says which row of the design's section 16.2 each
# step reaches, for this trial, trials/c6_tempus_kotlin and trials/c9_tempus_node_kotlin together.
# Needs kotlinc and a Java runtime of release 27 or later (its TLS offers the key exchange group X25519MLKEM768; OpenJDK
# 25 does not). This trial never skips: without them it fails and says so. KOTLINC and JAVA may be given on the command
# line. Post-processing of the nodes' outputs: tools/bees_tempus_reports.py; addresses the runtime prints become 0xADDR.
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)
HERE := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
include $(BEES_ROOT)/tools/silica.mk
KOTLINC ?= kotlinc
JAVA ?= java
EXT := $(BEES_ROOT)/example_tempus_clients/kotlin
JAR := $(HERE)/build/bridge.jar
NODES := t b1 b2
OUTS := t b1 b2 kotlin
N := c11_tempus_bridge_kotlin
.DEFAULT_GOAL := build
.PHONY: build run integrate record-golden clean tools natives nodes kotlin
tools:
	@command -v "$(KOTLINC)" > /dev/null || { echo "FAIL: [$(N)] the Kotlin compiler (kotlinc) is not installed or not on PATH; this trial needs it (example_tempus_clients/kotlin/README.md says what to install)"; exit 1; }
	@command -v "$(JAVA)" > /dev/null && "$(JAVA)" -version > /dev/null 2>&1 || { echo "FAIL: [$(N)] no Java runtime (java) is installed or on PATH; this trial needs one of release 27 or later (example_tempus_clients/kotlin/README.md says what to install)"; exit 1; }
	@v=$$("$(JAVA)" -XshowSettings:properties -version 2>&1 | sed -n 's/^ *java.specification.version = //p'); case "$$v" in ''|*[!0-9]*) v=0;; esac; \
	[ "$$v" -ge 27 ] || { echo "FAIL: [$(N)] the Java runtime ($(JAVA)) is release $$v; this trial needs release 27 or later, whose TLS offers X25519MLKEM768 (example_tempus_clients/kotlin/README.md says what to install)"; exit 1; }
natives:
	@out=$$($(MAKE) --no-print-directory -C "$(BEES_ROOT)/native" tempus tls 2>&1); rc=$$?; \
	[ -z "$$out" ] || printf '%s\n' "$$out" | grep -v '^ar \|^cc \|^mkdir ' ; \
	if [ "$$rc" != 0 ]; then echo "FAIL: [$(N)] needs the TEMPUS native edge and the TLS engine (make -C native tempus tls; OpenSSL 4.1.0 or later)"; exit 1; fi
nodes: tools natives
	@python3 "$(BEES_ROOT)/tools/bees_tempus_certs.py" check > /dev/null || { echo "FAIL: [$(N)] the TEMPUS certificates are not what tools/bees_tempus_certs.py writes"; exit 1; }
	@for n in $(NODES); do $(MAKE) --no-print-directory -C "$(HERE)/nodes/$$n" build SILICA_COMPILER="$(SILICA_COMPILER)" || exit 1; done
kotlin: tools
	@mkdir -p "$(HERE)/build" && cd "$(HERE)" && if [ ! -f "$(JAR)" ] || [ Bridge.kt -nt "$(JAR)" ] || [ -n "$$(find "$(EXT)/lib" "$(EXT)/test/Fixtures.kt" -newer "$(JAR)" 2>/dev/null)" ]; then \
		"$(KOTLINC)" -nowarn -include-runtime -d "$(JAR)" "$(EXT)"/lib/*.kt "$(EXT)/test/Fixtures.kt" Bridge.kt || { echo "FAIL: [$(N)] the Kotlin extension or Bridge.kt did not compile"; exit 1; }; fi
	@echo "[$(N)] built: the Kotlin extension and the walk"
build: tools nodes kotlin
run: build
	@cd "$(HERE)" && for o in $(OUTS); do : > "$$o.sout"; done; \
	python3 walk.py . "$(JAVA)" "$(JAR)"; rc=$$?; \
	for n in $(NODES); do [ ! -f nodes/$$n/dangerous_$$n.sout ] || cp nodes/$$n/dangerous_$$n.sout $$n.sout; done; \
	python3 "$(BEES_ROOT)/tools/bees_tempus_reports.py" t.sout b1.sout b2.sout; \
	$(SED_I) -E -e 's/0x[0-9a-f]{6,}/0xADDR/g' t.sout b1.sout b2.sout; exit $$rc
integrate: run
	@cd "$(HERE)" && ok=0; ko=0; for o in $(OUTS); do g="$$o$(GOLD_SUFFIX).scout"; \
		if [ ! -f "$$g" ]; then echo "MISSING golden for $(BEES_PLATFORM_ID) (record one on this platform with make record-golden): [$(N)] $$g"; ko=$$((ko+1)); \
		elif diff -q "$$o.sout" "$$g" > /dev/null; then ok=$$((ok+1)); \
		else echo "DIFF: [$(N)] $$o"; diff "$$g" "$$o.sout" || true; ko=$$((ko+1)); fi; done; \
	printf '%d %d\n' "$$ok" "$$ko" > .integrate_counts; echo "[$(N)] $$ok passed, $$ko failed"; [ "$$ko" -eq 0 ]
record-golden: run
	@cd "$(HERE)" && for o in $(OUTS); do cp "$$o.sout" "$$o$(GOLD_SUFFIX).scout"; done; echo "[$(N)] goldens recorded"
clean:
	@for n in $(NODES); do $(MAKE) --no-print-directory -C "$(HERE)/nodes/$$n" clean; done; cd "$(HERE)" && rm -f build/bridge.jar t.sout b1.sout b2.sout kotlin.sout .integrate_counts
