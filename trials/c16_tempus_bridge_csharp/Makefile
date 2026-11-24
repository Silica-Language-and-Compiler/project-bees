# C16: the client half of the C# TEMPUS extension (example_tempus_clients/csharp) against real bridge nodes on 127.0.0.1.
# The network is that of trials/c3_tempus_bridge, on this trial's own ports (the node directories and roles are copies
# of that trial's, with the ports changed and nothing else; that trial's Silica client and its roles are left out):
#   nodes/t   node T, a plain TRUST node over mutual TLS 1.3 (port +0), whitelisting the two bridges' TRUST certificates
#   nodes/b1  bridge B1, nodes/b2 bridge B2: a TRUST client of T and a TEMPUS node of role bridge (tempus/1 on +1 and +2)
#             in one program; test programs (externally driven, with the test unit of src/tempus_test)
#   csharp    the walk's transcript (Bridge.cs): one line per step, each step checked by the C# program
# walk.py starts and stops the node processes and sends bridge B2 the test-only tick frame with the Python test support
# (the C# extension holds no test frame). COVERAGE.md says which row of the design's section 16.2 each step reaches, for
# this trial and for trials/c12_tempus_csharp and trials/c13_tempus_node_csharp together.
# Needs the .NET SDK 11 (dotnet) and OpenSSL 4.1.0 or later, which the extension calls for TLS and Ed25519. This trial
# never skips: without them it fails and says so. DOTNET may be given on the command line. Nothing is fetched: see the
# Makefile of the extension. Post-processing of the nodes' outputs: tools/bees_tempus_reports.py; addresses the runtime
# prints become 0xADDR.
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
BRIDGE_DLL := $(HERE)/build/bin/Bridge/bridge.dll
NODES := t b1 b2
OUTS := t b1 b2 csharp
N := c16_tempus_bridge_csharp
.DEFAULT_GOAL := build
.PHONY: build run integrate record-golden clean tools natives nodes csharp
tools:
	@command -v "$(DOTNET)" > /dev/null && "$(DOTNET)" --version > /dev/null 2>&1 || { echo "FAIL: [$(N)] the .NET SDK (dotnet) is not installed or not on PATH; this trial needs it (example_tempus_clients/csharp/README.md says what to install)"; exit 1; }
natives:
	@out=$$($(MAKE) --no-print-directory -C "$(BEES_ROOT)/native" tempus tls 2>&1); rc=$$?; \
	[ -z "$$out" ] || printf '%s\n' "$$out" | grep -v '^ar \|^cc \|^mkdir ' ; \
	if [ "$$rc" != 0 ]; then echo "FAIL: [$(N)] needs the TEMPUS native edge and the TLS engine (make -C native tempus tls; OpenSSL 4.1.0 or later)"; exit 1; fi
nodes: tools natives
	@python3 "$(BEES_ROOT)/tools/bees_tempus_certs.py" check > /dev/null || { echo "FAIL: [$(N)] the TEMPUS certificates are not what tools/bees_tempus_certs.py writes"; exit 1; }
	@for n in $(NODES); do $(MAKE) --no-print-directory -C "$(HERE)/nodes/$$n" build SILICA_COMPILER="$(SILICA_COMPILER)" || exit 1; done
csharp: tools
	@$(MAKE) --no-print-directory -C "$(EXT)" build test-build DOTNET="$(DOTNET)" > /dev/null || { $(MAKE) --no-print-directory -C "$(EXT)" build test-build DOTNET="$(DOTNET)" 2>&1 | grep -E 'FAIL|error' | head -20; echo "FAIL: [$(N)] the C# extension did not compile (make -C example_tempus_clients/csharp build test-build)"; exit 1; }
	@python3 "$(EXT)/build_lock.py" "$(EXT)/build/.build.lock" "$(DOTNET)" build --nologo -v quiet '-clp:ErrorsOnly;NoSummary' --configfile "$(EXT)/nuget.config" "$(HERE)/Bridge.csproj" > /dev/null || { python3 "$(EXT)/build_lock.py" "$(EXT)/build/.build.lock" "$(DOTNET)" build --nologo -v quiet '-clp:ErrorsOnly;NoSummary' --configfile "$(EXT)/nuget.config" "$(HERE)/Bridge.csproj" | head -20; echo "FAIL: [$(N)] Bridge.cs did not compile"; exit 1; }
	@"$(DOTNET)" "$(TEST_DLL)" openssl > /dev/null 2>&1 || { "$(DOTNET)" "$(TEST_DLL)" openssl 2>&1 | head -3; echo "FAIL: [$(N)] OpenSSL 4.1.0 or later is not installed where the C# extension looks for it; this trial needs it (example_tempus_clients/csharp/README.md says what to install)"; exit 1; }
	@echo "[$(N)] built: the C# extension, its tests and the walk"
build: tools nodes csharp
run: build
	@cd "$(HERE)" && for o in $(OUTS); do : > "$$o.sout"; done; \
	python3 walk.py . "$(DOTNET)" "$(BRIDGE_DLL)"; rc=$$?; \
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
	@for n in $(NODES); do $(MAKE) --no-print-directory -C "$(HERE)/nodes/$$n" clean; done
	@cd "$(HERE)" && rm -rf build && rm -f t.sout b1.sout b2.sout csharp.sout .integrate_counts
