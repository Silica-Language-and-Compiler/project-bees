# Shared Silica toolchain settings for every BEES Makefile.
#
# Include after setting BEES_ROOT (absolute path of the repository root, no trailing slash).
#
# The compiler is the newest macOS fixed-point selfhost in the sibling Silica checkout,
# reached through its binaries/silica-compiler link. Override on the command line:
#   make SILICA_COMPILER=/path/to/silica-compiler
# The generation BEES was last verified against is pinned in tools/silica.generation, one
# line per platform (macos-applesilicon, linux-x86_64, linux-aarch64), and checked by
# `make check-compiler` (roadmap §4.9), which compares the compiler in use with the line
# of its own platform.

SILICA_ROOT ?= $(abspath $(BEES_ROOT)/../silica)
ifeq ($(filter command line,$(origin SILICA_COMPILER)),)
SILICA_COMPILER := $(SILICA_ROOT)/binaries/silica-compiler
endif

SILICA_STDLIB := $(SILICA_ROOT)/compiler/stdlib

# The platform (tools/platform.mk): BEES_PLATFORM (native/ directory) and BEES_PLATFORM_ID (the golden-name infix). Everything
# the build needs that exists on one platform only (assembler/linker flags, the clang to prefer, BSD sed, where OpenSSL is)
# comes from native/$(BEES_PLATFORM)/platform.mk.
include $(BEES_ROOT)/tools/platform.mk

# Assembler and linker. The entry symbol is `main` (no C runtime, no leading underscore): the platform's flags say so.
CLANG ?= $(or $(PLATFORM_CLANG),clang)
ASFLAGS := $(PLATFORM_ASFLAGS)
LDFLAGS := $(PLATFORM_LDFLAGS)

# A golden is NAME.$(BEES_PLATFORM_ID).scout / .golden_fail: a run compares only against its own platform's golden (tools/platform_id.py).
# GOLD(name, ext) -> NAME.ID.EXT for shell or make text.
GOLD_SUFFIX := .$(BEES_PLATFORM_ID)
# in-place sed (BSD and GNU differ; native/$(BEES_PLATFORM)/platform.mk)
SED_I := $(PLATFORM_SED_INPLACE)

# Process-per-unit reclaim loop: exit 75 means "restart me for the next unit" (Silica's
# trials/silica_compiler.mk). Exit 142 is the per-unit alarm.
SILICA_COMPILE_TIMEOUT ?= 300
# Under tools/run_all_trials.sh the compiler runs inside a slot (tools/with_slot.py): at most BEES_COMPILE_SLOTS compiles at a time.
WITH_SLOT := python3 "$(BEES_ROOT)/tools/with_slot.py"
define RUN_SILICA_COMPILER
	while true; do \
		$(WITH_SLOT) perl -e 'alarm shift @ARGV; exec @ARGV' $(SILICA_COMPILE_TIMEOUT) "$(SILICA_COMPILER)"; \
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
	$(SED_I) -E 's/0x[0-9a-f]{6,}/0xADDR/g' "$(2)"
endef

# TRUST over TLS (N4.1): a program whose silica.link names the TLS engine's archive (libsilica_bees_tls.a) is linked with the
# programmer-installed OpenSSL (D40; BEES ships none). OPENSSL_PREFIX as in native/Makefile.
OPENSSL_PREFIX ?= $(firstword $(foreach p,$(PLATFORM_OPENSSL_DIRS),$(if $(wildcard $(p)/include/openssl/ssl.h),$(p))))
OPENSSL_LIBDIR_FLAGS := $(if $(OPENSSL_PREFIX),-L$(OPENSSL_PREFIX)/lib $(if $(PLATFORM_RPATH_FLAG),$(PLATFORM_RPATH_FLAG)$(OPENSSL_PREFIX)/lib))
OPENSSL_LDFLAGS := $(OPENSSL_LIBDIR_FLAGS) -lssl -lcrypto
# A platform whose bees_platform.h functions call OpenSSL (Linux: MD5 for the Erlang cookie scheme) links libcrypto into every
# program that names the native archive (libsilica_bees_native.a); empty elsewhere.
NATIVE_CRYPTO_LDFLAGS := $(if $(PLATFORM_NATIVE_NEEDS_CRYPTO),$(OPENSSL_LIBDIR_FLAGS) -lcrypto)

# The runtime prints "[silica] root actor exited (no supervisor)" on stderr when an unsupervised actor ends. Since Silica
# commit 71009f96f8 the language's carriers end with their link, so a pair trial prints it once per carrier, and stderr can
# land in the middle of a stdout line ("client: answer seq [silica] root actor exited (no supervisor)\n1"). The pair trials
# remove it with its newline wherever it lands (a whole line, or inside one, which rejoins the stdout line).
STRIP_ROOT_EXIT = perl -0pi -e 's/\[silica\] root actor exited \(no supervisor\)\n//g'
# A program without its own failure reporter gets the runtime's report of every actor end on stderr, so since 71009f96f8 also
# the carrier's own `:normal` end; its place among the stdout lines varies. STRIP_CARRIER_END removes exactly that report (reason
# :normal, call stack in dangerous_tcp_carrier_carrier) and the root-actor line; any other report stays in the output.
STRIP_CARRIER_END = perl -0pi -e 's/\[silica\] root actor exited \(no supervisor\)\n//g; s/\n?=== Silica Actor Failure ===\n(?:(?!=== End).)*?reason:\s+:normal\n(?:(?!=== End).)*?dangerous_tcp_carrier_carrier\n(?:(?!=== End).)*?=== End Silica Actor Failure ===\n\n?//gs'

# TRUST negative suite (trials/n3_trust, trials/n4_trust_tls), the server's output: the call demo:slow times out, which (1) makes the
# connection actor report the late result when the abandoned worker's answer arrives and (2) makes the fingerprint's actor print
# `suspicion ... raised by timeout` and `quarantined ... above suspicion_limit`. On a machine with many cores (2) is printed at the
# timeout and (1) when the worker ends, a quarter of a second later. On a two-core machine the fingerprint's actor does not run
# until the busy worker ends (measured on the Linux box: 1.1 s after the timeout, in the same millisecond as the late result), so
# two actors print at once and the three lines come in any order (2 of 5 runs differed). The late-result line is moved after the
# quarantine line when it lands directly before it or before the suspicion line; all three lines stay in the output and are compared.
TRUST_LATE_RESULT_LAST = perl -0pi -e 's/^(\[trust audit\] late_result_dropped [^\n]*\n)((?:\[trust audit\] suspicion [^\n]*raised by timeout[^\n]*\n)?\[trust audit\] quarantined [^\n]*above suspicion_limit[^\n]*\n)/$$2$$1/mg'

.PHONY: check-compiler
check-compiler:
	@if [ ! -x "$(SILICA_COMPILER)" ]; then echo "FAIL: no silica-compiler at $(SILICA_COMPILER)"; exit 1; fi
	@gen=$$(basename "$$(readlink "$(SILICA_COMPILER)" || echo "$(SILICA_COMPILER)")"); \
	platform=$$(printf '%s\n' "$$gen" | sed -n 's/^silica-[0-9]*-//p'); \
	pinned=$$(grep -x "silica-[0-9]*-$$platform" "$(BEES_ROOT)/tools/silica.generation" 2>/dev/null | head -1); \
	if [ -z "$$platform" ] || [ -z "$$pinned" ]; then \
		echo "NOTE: compiler generation is $$gen; tools/silica.generation has no pin for its platform"; \
	elif [ "$$gen" != "$$pinned" ]; then \
		echo "NOTE: compiler generation is $$gen; BEES was last verified with $$pinned"; \
	else echo "compiler generation $$gen (verified)"; fi
