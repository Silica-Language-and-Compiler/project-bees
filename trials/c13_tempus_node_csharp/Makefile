# C13: nodes of the C# extension (example_tempus_clients/csharp) in one network with Silica nodes, on 127.0.0.1.
#   tests        the extension's node tests (example_tempus_clients/csharp/test/NodeTests.cs): the view and the store
#                against the two Python models and the goldens of trials/t0_tempus_view and trials/t1_tempus_store, the
#                clock against the golden of trials/t0_tempus_clock, the configuration's refusals, the entry check on the
#                cases of trials/t4_tempus_admission
#   dangerous_s  node S, a Silica sentinel, a test program; the C# nodes CE and CH join through it
#   dangerous_a  node A, a Silica edge, a test program; it joins through the C# sentinel CS
#   dangerous_q  node Q, a Silica edge, not a test program; it joins through the C# sentinel CP by the machine's clock
#   ce cs ch cc cs2   the lines of the C# test nodes (their clock, timers and draws are the trial's, given through the
#                extension's construction interface): CE an edge, CS and CS2 sentinels, CH and CC edges whose clock the
#                trial sets (hold and continue; stop with a limit and pause)
#   cp           the lines of the C# node that is not a test node: the machine's clock, its own timers
#   csharp       the transcript (Net.cs): one line per step, each step checked by the C# program
# walk.py starts the Silica node processes, sends the Silica test nodes the test-only tick frame and plays the peers
# that misbehave, with the Python test support.
# Needs the .NET SDK 11 (dotnet) and OpenSSL 4.1.0 or later, which the extension calls for TLS and Ed25519. This trial
# never skips: without them it fails and says so. DOTNET may be given on the command line. Nothing is fetched: see the
# Makefile of the extension. The Silica nodes are built by nodes.mk beside this file. Post-processing of the Silica
# nodes' outputs: tools/bees_tempus_reports.py.
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)
HERE := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
include $(BEES_ROOT)/tools/silica.mk
DOTNET ?= dotnet
EXT := $(BEES_ROOT)/example_tempus_clients/csharp
export DOTNET_CLI_TELEMETRY_OPTOUT := 1
export DOTNET_NOLOGO := 1
export DOTNET_SKIP_FIRST_TIME_EXPERIENCE := 1
export DOTNET_GENERATE_ASPNET_CERTIFICATE := false
export DOTNET_CLI_WORKLOAD_UPDATE_NOTIFY_DISABLE := 1
export DOTNET_CLI_HOME := $(EXT)/build/home
export NUGET_PACKAGES := $(EXT)/build/home/packages
export NUGET_HTTP_CACHE_PATH := $(EXT)/build/home/http-cache
DRIVER_DLL := $(EXT)/build/bin/BeesTempusDriver/bees-tempus.dll
TEST_DLL := $(EXT)/build/bin/BeesTempusTests/bees-tempus-tests.dll
NET_DLL := $(HERE)/build/bin/Net/net.dll
CASES := $(EXT)/build/model_cases.txt
SILICA_OUTS := dangerous_s dangerous_a dangerous_q
CSHARP_OUTS := ce cs ch cc cs2 cp
OUTS := tests $(SILICA_OUTS) $(CSHARP_OUTS) csharp
N := c13_tempus_node_csharp
.DEFAULT_GOAL := build
.PHONY: build run integrate record-golden clean tools natives fixtures nodes csharp
tools:
	@command -v "$(DOTNET)" > /dev/null && "$(DOTNET)" --version > /dev/null 2>&1 || { echo "FAIL: [$(N)] the .NET SDK (dotnet) is not installed or not on PATH; this trial needs it (example_tempus_clients/csharp/README.md says what to install)"; exit 1; }
natives:
	@out=$$($(MAKE) --no-print-directory -C "$(BEES_ROOT)/native" tempus tls 2>&1); rc=$$?; \
	[ -z "$$out" ] || printf '%s\n' "$$out" | grep -v '^ar \|^cc \|^mkdir ' ; \
	if [ "$$rc" != 0 ]; then echo "FAIL: [$(N)] needs the TEMPUS native edge and the TLS engine (make -C native tempus tls; OpenSSL 4.1.0 or later)"; exit 1; fi
fixtures:
	@python3 "$(BEES_ROOT)/tools/bees_tempus_certs.py" check > /dev/null && python3 "$(BEES_ROOT)/tools/bees_tempus_ids.py" check "$(HERE)/lib/tempus_ids.silica" ../t5_tempus_tls/certs/ > /dev/null || { echo "FAIL: [$(N)] the certificates or lib/tempus_ids.silica are not what the tools write"; exit 1; }
nodes: tools natives fixtures
	@$(MAKE) --no-print-directory -C "$(HERE)" -f nodes.mk build SILICA_COMPILER="$(SILICA_COMPILER)"
csharp: tools
	@$(MAKE) --no-print-directory -C "$(EXT)" build test-build "$(CASES)" DOTNET="$(DOTNET)" > /dev/null || { $(MAKE) --no-print-directory -C "$(EXT)" build test-build "$(CASES)" DOTNET="$(DOTNET)" 2>&1 | grep -E 'FAIL|error' | head -20; echo "FAIL: [$(N)] the C# extension did not compile (make -C example_tempus_clients/csharp build test-build)"; exit 1; }
	@python3 "$(EXT)/build_lock.py" "$(EXT)/build/.build.lock" "$(DOTNET)" build --nologo -v quiet '-clp:ErrorsOnly;NoSummary' --configfile "$(EXT)/nuget.config" "$(HERE)/Net.csproj" > /dev/null || { python3 "$(EXT)/build_lock.py" "$(EXT)/build/.build.lock" "$(DOTNET)" build --nologo -v quiet '-clp:ErrorsOnly;NoSummary' --configfile "$(EXT)/nuget.config" "$(HERE)/Net.csproj" | head -20; echo "FAIL: [$(N)] Net.cs did not compile"; exit 1; }
	@"$(DOTNET)" "$(TEST_DLL)" openssl > /dev/null 2>&1 || { "$(DOTNET)" "$(TEST_DLL)" openssl 2>&1 | head -3; echo "FAIL: [$(N)] OpenSSL 4.1.0 or later is not installed where the C# extension looks for it; this trial needs it (example_tempus_clients/csharp/README.md says what to install)"; exit 1; }
	@echo "[$(N)] built: the C# extension, its node tests and the network program"
build: tools nodes csharp
run: build
	@cd "$(HERE)" && for o in $(OUTS); do : > "$$o.sout"; done; \
	( cd "$(BEES_ROOT)" && "$(DOTNET)" "$(TEST_DLL)" node "$(BEES_ROOT)" "$(CASES)" ) > tests.sout 2>&1; rc=$$?; printf 'exit=%s\n' "$$rc" >> tests.sout; \
	if [ "$$rc" != 0 ]; then grep '^FAIL' tests.sout; echo "FAIL: [$(N)] the C# extension's node tests failed (tests.sout)"; exit 1; fi; \
	python3 walk.py . "$(DOTNET)" "$(NET_DLL)" || exit 1; \
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
	@cd "$(HERE)" && rm -rf build && rm -f tests.sout csharp.sout $(addsuffix .sout,$(CSHARP_OUTS)) .integrate_counts
