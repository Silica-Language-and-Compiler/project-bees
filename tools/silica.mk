# Shared Silica toolchain settings for every BEES Makefile.
#
# Include after setting BEES_ROOT (absolute path of the repository root, no trailing slash).
#
# The compiler is the newest macOS fixed-point selfhost in the sibling Silica checkout,
# reached through its binaries/silica-compiler link. Override on the command line:
#   make SILICA_COMPILER=/path/to/silica-compiler
# The generation BEES was last verified against is pinned in tools/silica.generation and
# checked by `make check-compiler` (roadmap §4.9).

SILICA_ROOT ?= $(abspath $(BEES_ROOT)/../silica)
ifeq ($(filter command line,$(origin SILICA_COMPILER)),)
SILICA_COMPILER := $(SILICA_ROOT)/binaries/silica-compiler
endif

SILICA_STDLIB := $(SILICA_ROOT)/compiler/stdlib

# Assembler and linker. Homebrew LLVM's clang is preferred when present, as in Silica's own
# project Makefiles. The entry symbol is `main` (no C runtime, no leading underscore).
CLANG ?= $(or $(shell test -x /opt/homebrew/opt/llvm/bin/clang && echo /opt/homebrew/opt/llvm/bin/clang),clang)
MACOS_MIN_VERSION ?= 26.0
ASFLAGS := -mmacosx-version-min=$(MACOS_MIN_VERSION)
LDFLAGS := -Wl,-e,main -Wl,-macos_version_min,$(MACOS_MIN_VERSION) -Wl,-stack_size,0x10000000

# Process-per-unit reclaim loop: exit 75 means "restart me for the next unit" (Silica's
# trials/silica_compiler.mk). Exit 142 is the per-unit alarm.
SILICA_COMPILE_TIMEOUT ?= 300
define RUN_SILICA_COMPILER
	while true; do \
		perl -e 'alarm shift @ARGV; exec @ARGV' $(SILICA_COMPILE_TIMEOUT) "$(SILICA_COMPILER)"; \
		ec=$$?; \
		if [ $$ec -eq 0 ]; then break; fi; \
		if [ $$ec -eq 75 ]; then continue; fi; \
		if [ $$ec -eq 142 ]; then echo "FAIL: compiler timed out after $(SILICA_COMPILE_TIMEOUT)s"; fi; \
		exit $$ec; \
	done
endef

# Run one trial executable with a wall-clock limit, capture stdout+stderr and the exit code.
# Addresses printed by the runtime (actor_id: 0x...) vary between runs and are normalised.
SILICA_RUN_TIMEOUT ?= 120
# A trial whose main ends in wait_for_exit() has a NAME.wait_for_exit file holding the marker line
# after which "exit" is fed to it (tools/run_trial.py); every other trial runs with stdin closed.
define RUN_TRIAL
	if [ -f "$(1).wait_for_exit" ]; then \
		"$(BEES_ROOT)/tools/run_trial.py" "$(1)" "$(2)" "$$(cat "$(1).wait_for_exit")"; \
	else \
		perl -e 'alarm shift @ARGV; exec @ARGV' $(SILICA_RUN_TIMEOUT) "$(1)" < /dev/null > "$(2)" 2>&1; rc=$$?; \
		printf 'exit=%s\n' "$$rc" >> "$(2)"; \
	fi; \
	sed -i '' -E 's/0x[0-9a-f]{6,}/0xADDR/g' "$(2)"
endef

# TRUST over TLS (N4.1): a program whose silica.link names the TLS engine's archive (libsilica_bees_tls.a) is linked with the
# programmer-installed OpenSSL (D40; BEES ships none). OPENSSL_PREFIX as in native/Makefile.
OPENSSL_PREFIX ?= $(firstword $(foreach p,/opt/homebrew/opt/openssl /opt/homebrew/opt/openssl@3,$(if $(wildcard $(p)/include/openssl/ssl.h),$(p))))
OPENSSL_LDFLAGS := $(if $(OPENSSL_PREFIX),-L$(OPENSSL_PREFIX)/lib) -lssl -lcrypto

# The runtime prints "[silica] root actor exited (no supervisor)" on stderr when an unsupervised actor ends. Since Silica
# commit 71009f96f8 the language's carriers end with their link, so a pair trial prints it once per carrier, and stderr can
# land in the middle of a stdout line ("client: answer seq [silica] root actor exited (no supervisor)\n1"). The pair trials
# remove it with its newline wherever it lands (a whole line, or inside one, which rejoins the stdout line).
STRIP_ROOT_EXIT = perl -0pi -e 's/\[silica\] root actor exited \(no supervisor\)\n//g'
# A program without its own failure reporter gets the runtime's report of every actor end on stderr, so since 71009f96f8 also
# the carrier's own `:normal` end; its place among the stdout lines varies. STRIP_CARRIER_END removes exactly that report (reason
# :normal, call stack in dangerous_tcp_carrier_carrier) and the root-actor line; any other report stays in the output.
STRIP_CARRIER_END = perl -0pi -e 's/\[silica\] root actor exited \(no supervisor\)\n//g; s/\n?=== Silica Actor Failure ===\n(?:(?!=== End).)*?reason:\s+:normal\n(?:(?!=== End).)*?dangerous_tcp_carrier_carrier\n(?:(?!=== End).)*?=== End Silica Actor Failure ===\n\n?//gs'

.PHONY: check-compiler
check-compiler:
	@if [ ! -x "$(SILICA_COMPILER)" ]; then echo "FAIL: no silica-compiler at $(SILICA_COMPILER)"; exit 1; fi
	@gen=$$(basename "$$(readlink "$(SILICA_COMPILER)" || echo "$(SILICA_COMPILER)")"); \
	pinned=$$(cat "$(BEES_ROOT)/tools/silica.generation" 2>/dev/null); \
	if [ "$$gen" != "$$pinned" ]; then \
		echo "NOTE: compiler generation is $$gen; BEES was last verified with $${pinned:-<none>}"; \
	else echo "compiler generation $$gen (verified)"; fi
