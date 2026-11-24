# The gossip examples of the example TEMPUS clients: several instances of the driver applications on this machine, as
# one TEMPUS network, discovering each other. EXAMPLE ONLY, not for production (README.md beside this file).
#
#   make python | kotlin | swift | silica | csharp | rust
#                                            build that language's driver, then run one sentinel and three edges of it
#   make mixed                               build all six, then run a Silica sentinel and one edge of each language
#   make trio                                the mixed network without the Silica driver: a Swift sentinel and one edge
#                                            each of Python, Kotlin, Swift, C# and Rust
#   make start                               all eight networks, one after the other
#   make build                               the six drivers, nothing run
#   make integrate                           all eight, each check compared with its recorded one (NAME.check.PLATFORM.scout)
#   make record-golden                       all eight, the checks recorded for this platform; ONLY=name records one
#   make clean                               what the runs wrote (.run/); the drivers are cleaned in their own directories
#
# What must be installed is what each driver needs (the READMEs of ../python, ../kotlin, ../swift, ../silica,
# ../csharp, ../rust): python3 with the `cryptography` package; kotlinc and a JDK 27; Apple's Command Line Tools and
# OpenSSL 4.1.0 or later; the Silica compiler BEES is pinned to; the .NET SDK 11; cargo and rustc. A network whose
# driver cannot be built FAILS and says what is missing; nothing is skipped. KOTLINC, JAVA, DOTNET and SILICA_COMPILER
# may be given on the command line.
#
# One network runs at a time: all eight use the same ports (tools/trial_ports.py c7_tempus_gossip).
HERE := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
BEES_ROOT := $(abspath $(HERE)/../..)
include $(BEES_ROOT)/tools/silica.mk
CLIENTS := $(BEES_ROOT)/example_tempus_clients
KOTLINC ?= kotlinc
JAVA ?= java
DOTNET ?= dotnet
RUNNER := python3 "$(HERE)/gossip_run.py"
NETWORKS := python kotlin swift silica csharp rust mixed trio
# record-golden records these (all of them unless ONLY names some)
ONLY ?= $(NETWORKS)
OUT := $(HERE)/.run

.DEFAULT_GOAL := build
.PHONY: build build-python build-kotlin build-swift build-silica build-csharp build-rust $(NETWORKS) start run integrate record-golden clean
# what record-golden must build: every driver, unless ONLY leaves the Silica networks out
RECORD_BUILD := build-python build-kotlin build-swift build-csharp build-rust $(if $(filter silica mixed,$(ONLY)),build-silica)

build-python:
	@python3 -c "import cryptography" 2> /dev/null || { echo "FAIL: [gossip] the Python driver needs python3 with the cryptography package"; exit 1; }
build-kotlin:
	@$(MAKE) --no-print-directory -C "$(CLIENTS)/kotlin" build KOTLINC="$(KOTLINC)" JAVA="$(JAVA)" > /dev/null || { echo "FAIL: [gossip] the Kotlin driver did not build (make -C example_tempus_clients/kotlin build; its README says what to install)"; exit 1; }
build-swift:
	@$(MAKE) --no-print-directory -C "$(CLIENTS)/swift" build || { echo "FAIL: [gossip] the Swift driver did not build (make -C example_tempus_clients/swift build; its README says what to install)"; exit 1; }
build-silica:
	@$(MAKE) --no-print-directory -C "$(CLIENTS)/silica/driver" build SILICA_COMPILER="$(SILICA_COMPILER)" > "$(HERE)/.silica_build.log" 2>&1 || { tail -30 "$(HERE)/.silica_build.log"; echo "FAIL: [gossip] the Silica driver did not build (make -C example_tempus_clients/silica/driver build)"; exit 1; }
build-csharp:
	@out=$$($(MAKE) --no-print-directory -C "$(CLIENTS)/csharp" build DOTNET="$(DOTNET)" 2>&1) || { printf '%s\n' "$$out" | tail -30; echo "FAIL: [gossip] the C# driver did not build (make -C example_tempus_clients/csharp build; its README says what to install)"; exit 1; }
build-rust:
	@$(MAKE) --no-print-directory -C "$(CLIENTS)/rust" build || { echo "FAIL: [gossip] the Rust driver did not build (make -C example_tempus_clients/rust build; its README says what to install)"; exit 1; }
build: build-python build-kotlin build-swift build-silica build-csharp build-rust
	@echo "[gossip] built: the six drivers"

python: build-python
	@$(RUNNER) run python --out "$(OUT)"
kotlin: build-python build-kotlin
	@JAVA="$(JAVA)" $(RUNNER) run kotlin --out "$(OUT)"
swift: build-python build-swift
	@$(RUNNER) run swift --out "$(OUT)"
silica: build-python build-silica
	@$(RUNNER) run silica --out "$(OUT)"
csharp: build-python build-csharp
	@DOTNET="$(DOTNET)" $(RUNNER) run csharp --out "$(OUT)"
rust: build-python build-rust
	@$(RUNNER) run rust --out "$(OUT)"
mixed: build
	@JAVA="$(JAVA)" DOTNET="$(DOTNET)" $(RUNNER) run mixed --out "$(OUT)"
trio: build-python build-kotlin build-swift build-csharp build-rust
	@JAVA="$(JAVA)" DOTNET="$(DOTNET)" $(RUNNER) run trio --out "$(OUT)"

start run: build
	@rc=0; for n in $(NETWORKS); do JAVA="$(JAVA)" DOTNET="$(DOTNET)" $(RUNNER) run $$n --out "$(OUT)" || rc=1; echo; done; exit $$rc

integrate: build
	@cd "$(HERE)" && ok=0; ko=0; for n in $(NETWORKS); do g="$$n.check$(GOLD_SUFFIX).scout"; \
		JAVA="$(JAVA)" DOTNET="$(DOTNET)" $(RUNNER) run $$n --out "$(OUT)" > /dev/null; \
		if [ ! -f "$$g" ]; then echo "MISSING golden for $(BEES_PLATFORM_ID) (record one on this platform with make record-golden): [gossip] $$g"; ko=$$((ko+1)); \
		elif diff -q "$(OUT)/$$n.check" "$$g" > /dev/null; then ok=$$((ok+1)); \
		else echo "DIFF: [gossip] $$n"; diff "$$g" "$(OUT)/$$n.check" || true; ko=$$((ko+1)); fi; done; \
	printf '%d %d\n' "$$ok" "$$ko" > .integrate_counts; echo "[gossip] $$ok passed, $$ko failed"; [ "$$ko" -eq 0 ]

record-golden: $(RECORD_BUILD)
	@cd "$(HERE)" && for n in $(ONLY); do JAVA="$(JAVA)" DOTNET="$(DOTNET)" $(RUNNER) run $$n --out "$(OUT)" > /dev/null || { cat "$(OUT)/$$n.check"; echo "FAIL: [gossip] $$n: its check does not say yes throughout, so nothing is recorded"; exit 1; }; \
		cp "$(OUT)/$$n.check" "$$n.check$(GOLD_SUFFIX).scout"; done; echo "[gossip] goldens recorded"

clean:
	@rm -rf "$(OUT)" "$(HERE)/.integrate_counts" "$(HERE)/.silica_build.log"
