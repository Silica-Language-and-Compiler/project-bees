# C6: the Kotlin example TEMPUS client (example_tempus_clients/kotlin) against real nodes on 127.0.0.1.
#   tests        the client's own tests (example_tempus_clients/kotlin/test): its codec against the frames golden of
#                trials/t2_tempus_frames, the TEST ONLY identities and tokens of tools/bees_tempus_ids.py byte for byte,
#                the admission cases of trials/t4_tempus_admission, and the client against itself over mutual TLS 1.3
#   dangerous_k  node K, a test program (externally driven, with the test unit of src/tempus_test). It joins through the
#                Kotlin client, which listens as a sentinel; the client then samples, shuffles, is dialed and is refused
#   dangerous_q  node Q, not a test program: it reads the machine's clock, and so does the Kotlin client there
#   kotlin       the walk's transcript (Walk.kt): one line per step, each step checked by the Kotlin program
# walk.py starts the node processes, sends node K the test-only tick frame with the Python example client (the Kotlin
# client holds no test frame), and plays the peers that misbehave, also with the Python example client. The outputs are
# tests.sout, dangerous_k.sout, dangerous_q.sout and kotlin.sout, each compared with its golden.
# Needs kotlinc and a Java runtime whose TLS offers the key exchange group X25519MLKEM768 (OpenJDK 27 does; OpenJDK 25
# does not). This trial never skips: without them it fails and says so. KOTLINC and JAVA may be given on the command
# line. The nodes are built by nodes.mk beside this file, the way trials/c2_tempus_clients builds its nodes.
# Post-processing of the nodes' outputs: tools/bees_tempus_reports.py.
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)
HERE := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
include $(BEES_ROOT)/tools/silica.mk
KOTLINC ?= kotlinc
JAVA ?= java
CLIENT := $(BEES_ROOT)/example_tempus_clients/kotlin
CLIENT_JAR := $(CLIENT)/build/bees-tempus-client.jar
TEST_JAR := $(CLIENT)/build/bees-tempus-client-test.jar
WALK_JAR := $(HERE)/build/walk.jar
OUTS := tests dangerous_k dangerous_q kotlin
.DEFAULT_GOAL := build
.PHONY: build run integrate record-golden clean tools natives fixtures nodes kotlin
tools:
	@command -v "$(KOTLINC)" > /dev/null || { echo "FAIL: [c6_tempus_kotlin] the Kotlin compiler (kotlinc) is not installed or not on PATH; this trial needs it (example_tempus_clients/kotlin/README.md says what to install)"; exit 1; }
	@command -v "$(JAVA)" > /dev/null && "$(JAVA)" -version > /dev/null 2>&1 || { echo "FAIL: [c6_tempus_kotlin] no Java runtime (java) is installed or on PATH; this trial needs one (example_tempus_clients/kotlin/README.md says what to install)"; exit 1; }
natives:
	@out=$$($(MAKE) --no-print-directory -C "$(BEES_ROOT)/native" tempus tls 2>&1); rc=$$?; \
	[ -z "$$out" ] || printf '%s\n' "$$out" | grep -v '^ar \|^cc \|^mkdir ' ; \
	if [ "$$rc" != 0 ]; then echo "FAIL: [c6_tempus_kotlin] needs the TEMPUS native edge and the TLS engine (make -C native tempus tls; OpenSSL 4.1.0 or later)"; exit 1; fi
fixtures:
	@python3 "$(BEES_ROOT)/tools/bees_tempus_certs.py" check > /dev/null && python3 "$(BEES_ROOT)/tools/bees_tempus_ids.py" check "$(HERE)/lib/tempus_ids.silica" ../t5_tempus_tls/certs/ > /dev/null || { echo "FAIL: [c6_tempus_kotlin] the certificates or lib/tempus_ids.silica are not what the tools write"; exit 1; }
nodes: tools natives fixtures
	@$(MAKE) --no-print-directory -C "$(HERE)" -f nodes.mk build SILICA_COMPILER="$(SILICA_COMPILER)"
kotlin: tools
	@$(MAKE) --no-print-directory -C "$(CLIENT)" build test-build KOTLINC="$(KOTLINC)" JAVA="$(JAVA)" > /dev/null || { echo "FAIL: [c6_tempus_kotlin] the Kotlin client did not compile (make -C example_tempus_clients/kotlin build test-build)"; exit 1; }
	@mkdir -p "$(HERE)/build" && cd "$(HERE)" && if [ ! -f "$(WALK_JAR)" ] || [ Walk.kt -nt "$(WALK_JAR)" ] || [ "$(CLIENT_JAR)" -nt "$(WALK_JAR)" ] || [ "$(CLIENT)/test/Fixtures.kt" -nt "$(WALK_JAR)" ]; then \
		"$(KOTLINC)" -nowarn -include-runtime -d "$(WALK_JAR)" "$(CLIENT)"/lib/*.kt "$(CLIENT)/test/Fixtures.kt" Walk.kt || { echo "FAIL: [c6_tempus_kotlin] Walk.kt did not compile"; exit 1; }; fi
	@echo "[c6_tempus_kotlin] built: the Kotlin client, its tests and the walk"
build: tools nodes kotlin
run: build
	@cd "$(HERE)" && for o in $(OUTS); do : > "$$o.sout"; done; \
	( cd "$(BEES_ROOT)" && "$(JAVA)" -cp "$(TEST_JAR)" bees.tempus.test.TestMainKt "$(BEES_ROOT)" ) > tests.sout 2>&1; rc=$$?; printf 'exit=%s\n' "$$rc" >> tests.sout; \
	if [ "$$rc" != 0 ]; then grep '^FAIL' tests.sout; echo "FAIL: [c6_tempus_kotlin] the Kotlin client's own tests failed (tests.sout)"; exit 1; fi; \
	python3 walk.py . "$(JAVA)" "$(WALK_JAR)" "$(CLIENT_JAR)" || exit 1; \
	python3 "$(BEES_ROOT)/tools/bees_tempus_reports.py" dangerous_k.sout dangerous_q.sout
integrate: run
	@cd "$(HERE)" && ok=0; ko=0; for o in $(OUTS); do g="$$o$(GOLD_SUFFIX).scout"; \
		if [ ! -f "$$g" ]; then echo "MISSING golden for $(BEES_PLATFORM_ID) (record one on this platform with make record-golden): [c6_tempus_kotlin] $$g"; ko=$$((ko+1)); \
		elif diff -q "$$o.sout" "$$g" > /dev/null; then ok=$$((ok+1)); \
		else echo "DIFF: [c6_tempus_kotlin] $$o"; diff "$$g" "$$o.sout" || true; ko=$$((ko+1)); fi; done; \
	printf '%d %d\n' "$$ok" "$$ko" > .integrate_counts; echo "[c6_tempus_kotlin] $$ok passed, $$ko failed"; [ "$$ko" -eq 0 ]
record-golden: run
	@cd "$(HERE)" && for o in $(OUTS); do cp "$$o.sout" "$$o$(GOLD_SUFFIX).scout"; done; echo "[c6_tempus_kotlin] goldens recorded"
clean:
	@$(MAKE) --no-print-directory -C "$(HERE)" -f nodes.mk clean
	@$(MAKE) --no-print-directory -C "$(CLIENT)" clean
	@cd "$(HERE)" && rm -f build/walk.jar tests.sout kotlin.sout .integrate_counts
