# C9: nodes of the Kotlin extension (example_tempus_clients/kotlin) in one network with Silica nodes, on 127.0.0.1.
#   tests        the extension's node tests (example_tempus_clients/kotlin/test/NodeTestMain.kt): the view and the store
#                against the two Python models and the goldens of trials/t0_tempus_view and trials/t1_tempus_store, the
#                clock against the golden of trials/t0_tempus_clock, the configuration's refusals, the entry check on the
#                cases of trials/t4_tempus_admission, and a sentinel and two edges of the extension in one process
#   dangerous_s  node S, a Silica sentinel, a test program; the Kotlin nodes KE and KH join through it
#   dangerous_a  node A, a Silica edge, a test program; it joins through the Kotlin sentinel KS
#   dangerous_q  node Q, a Silica edge, not a test program; it joins through the Kotlin sentinel KP by the machine's clock
#   ke ks kh kc ks2   the lines of the Kotlin test nodes (their clock, timers and draws are the trial's, given through
#                the extension's construction interface): KE an edge, KS and KS2 sentinels, KH and KC edges whose clock
#                the trial sets (hold and continue; stop with a limit and pause)
#   kp           the lines of the Kotlin node that is not a test node: the machine's clock, its own timers
#   kotlin       the transcript (Net.kt): one line per step, each step checked by the Kotlin program
# walk.py starts the Silica node processes, sends the Silica test nodes the test-only tick frame and plays the peers
# that misbehave, with the Python example client's test support.
# Needs kotlinc and a Java runtime of release 27 or later (its TLS offers the key exchange group X25519MLKEM768; OpenJDK
# 25 does not). This trial never skips: without them it fails and says so. KOTLINC and JAVA may be given on the command
# line. The Silica nodes are built by nodes.mk beside this file. Post-processing of the Silica nodes' outputs:
# tools/bees_tempus_reports.py.
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)
HERE := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
include $(BEES_ROOT)/tools/silica.mk
KOTLINC ?= kotlinc
JAVA ?= java
EXT := $(BEES_ROOT)/example_tempus_clients/kotlin
TEST_JAR := $(EXT)/build/bees-tempus-client-test.jar
CASES := $(EXT)/build/model_cases.txt
NET_JAR := $(HERE)/build/net.jar
SILICA_OUTS := dangerous_s dangerous_a dangerous_q
KOTLIN_OUTS := ke ks kh kc ks2 kp
OUTS := tests $(SILICA_OUTS) $(KOTLIN_OUTS) kotlin
N := c9_tempus_node_kotlin
.DEFAULT_GOAL := build
.PHONY: build run integrate record-golden clean tools natives fixtures nodes kotlin
tools:
	@command -v "$(KOTLINC)" > /dev/null || { echo "FAIL: [$(N)] the Kotlin compiler (kotlinc) is not installed or not on PATH; this trial needs it (example_tempus_clients/kotlin/README.md says what to install)"; exit 1; }
	@command -v "$(JAVA)" > /dev/null && "$(JAVA)" -version > /dev/null 2>&1 || { echo "FAIL: [$(N)] no Java runtime (java) is installed or on PATH; this trial needs one of release 27 or later (example_tempus_clients/kotlin/README.md says what to install)"; exit 1; }
	@v=$$("$(JAVA)" -XshowSettings:properties -version 2>&1 | sed -n 's/^ *java.specification.version = //p'); case "$$v" in ''|*[!0-9]*) v=0;; esac; \
	[ "$$v" -ge 27 ] || { echo "FAIL: [$(N)] the Java runtime ($(JAVA)) is release $$v; this trial needs release 27 or later, whose TLS offers X25519MLKEM768 (example_tempus_clients/kotlin/README.md says what to install)"; exit 1; }
natives:
	@out=$$($(MAKE) --no-print-directory -C "$(BEES_ROOT)/native" tempus tls 2>&1); rc=$$?; \
	[ -z "$$out" ] || printf '%s\n' "$$out" | grep -v '^ar \|^cc \|^mkdir ' ; \
	if [ "$$rc" != 0 ]; then echo "FAIL: [$(N)] needs the TEMPUS native edge and the TLS engine (make -C native tempus tls; OpenSSL 4.1.0 or later)"; exit 1; fi
fixtures:
	@python3 "$(BEES_ROOT)/tools/bees_tempus_certs.py" check > /dev/null && python3 "$(BEES_ROOT)/tools/bees_tempus_ids.py" check "$(HERE)/lib/tempus_ids.silica" ../t5_tempus_tls/certs/ > /dev/null || { echo "FAIL: [$(N)] the certificates or lib/tempus_ids.silica are not what the tools write"; exit 1; }
nodes: tools natives fixtures
	@$(MAKE) --no-print-directory -C "$(HERE)" -f nodes.mk build SILICA_COMPILER="$(SILICA_COMPILER)"
kotlin: tools
	@$(MAKE) --no-print-directory -C "$(EXT)" test-build "$(CASES)" KOTLINC="$(KOTLINC)" JAVA="$(JAVA)" > /dev/null || { echo "FAIL: [$(N)] the Kotlin extension or its tests did not compile (make -C example_tempus_clients/kotlin test-build)"; exit 1; }
	@mkdir -p "$(HERE)/build" && cd "$(HERE)" && if [ ! -f "$(NET_JAR)" ] || [ Net.kt -nt "$(NET_JAR)" ] || [ "$(TEST_JAR)" -nt "$(NET_JAR)" ]; then \
		"$(KOTLINC)" -nowarn -include-runtime -d "$(NET_JAR)" "$(EXT)"/lib/*.kt "$(EXT)/test/Fixtures.kt" "$(EXT)/test/NodeFixtures.kt" Net.kt || { echo "FAIL: [$(N)] Net.kt did not compile"; exit 1; }; fi
	@echo "[$(N)] built: the Kotlin extension, its node tests and the network program"
build: tools nodes kotlin
run: build
	@cd "$(HERE)" && for o in $(OUTS); do : > "$$o.sout"; done; \
	( cd "$(BEES_ROOT)" && "$(JAVA)" -cp "$(TEST_JAR)" bees.tempus.test.NodeTestMainKt "$(BEES_ROOT)" "$(CASES)" ) > tests.sout 2>&1; rc=$$?; printf 'exit=%s\n' "$$rc" >> tests.sout; \
	if [ "$$rc" != 0 ]; then grep '^FAIL' tests.sout; echo "FAIL: [$(N)] the Kotlin extension's node tests failed (tests.sout)"; exit 1; fi; \
	python3 walk.py . "$(JAVA)" "$(NET_JAR)" || exit 1; \
	python3 "$(BEES_ROOT)/tools/bees_tempus_reports.py" $(addsuffix .sout,$(SILICA_OUTS))
integrate: run
	@cd "$(HERE)" && ok=0; ko=0; for o in $(OUTS); do g="$$o$(GOLD_SUFFIX).scout"; \
		if [ ! -f "$$g" ]; then echo "MISSING golden for $(BEES_PLATFORM_ID) (record one on this platform with make record-golden): [$(N)] $$g"; ko=$$((ko+1)); \
		elif diff -q "$$o.sout" "$$g" > /dev/null; then ok=$$((ok+1)); \
		else echo "DIFF: [$(N)] $$o"; diff "$$g" "$$o.sout" || true; ko=$$((ko+1)); fi; done; \
	printf '%d %d\n' "$$ok" "$$ko" > .integrate_counts; echo "[$(N)] $$ok passed, $$ko failed"; [ "$$ko" -eq 0 ]
record-golden: run
	@cd "$(HERE)" && for o in $(OUTS); do cp "$$o.sout" "$$o$(GOLD_SUFFIX).scout"; done; echo "[$(N)] goldens recorded"
clean:
	@$(MAKE) --no-print-directory -C "$(HERE)" -f nodes.mk clean
	@cd "$(HERE)" && rm -f build/net.jar tests.sout kotlin.sout $(addsuffix .sout,$(KOTLIN_OUTS)) .integrate_counts
