# The BEES native edge: one C archive, libsilica_bees_native.a (gap ledger §4), built from src/ into
# dangerous_exposure_source/lib/ where Silica's sidecar link_library expects it; and the language's socket wrappers
# (Silica's compiler/stdlib/net/silica_sockets.c, the Fifi library of the hosted (:tcp) carrier, transport design 6.3),
# built here into the same lib/ as libsilica_sockets.a, the way Silica's own trials build it as a fixture. The wrappers'
# sidecar is reached through the link dangerous_exposure_source/sockets -> the Silica tree's compiler/stdlib/net.
# Common code only (src/, tls/, trust/) plus ONE platform directory, chosen by BEES_PLATFORM (tools/platform.mk: macos on
# Darwin, linux on Linux). The platform directory holds platform.mk (compiler flags,
# the list of its sources) and the implementations of bees_platform.h. See native/README.md.
THIS_DIR := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
BEES_ROOT := $(abspath $(THIS_DIR)..)
include $(BEES_ROOT)/tools/platform.mk
PLATFORM_DIR := $(THIS_DIR)$(BEES_PLATFORM)
SILICA_ROOT ?= $(abspath $(THIS_DIR)../../silica)
CC ?= clang
CFLAGS := -std=c11 -Wall -Wextra -O2 $(PLATFORM_CFLAGS) -I$(THIS_DIR) \
	-I$(THIS_DIR)dangerous_exposure_source/bees
BUILD := $(THIS_DIR)build
LIB := $(THIS_DIR)dangerous_exposure_source/lib
SRCS := $(wildcard $(THIS_DIR)src/*.c)
OBJS := $(patsubst $(THIS_DIR)src/%.c,$(BUILD)/%.o,$(SRCS)) $(patsubst %.c,$(BUILD)/plat_%.o,$(PLATFORM_NATIVE_SRCS))
ARCHIVE := $(LIB)/libsilica_bees_native.a
SOCKETS_SRC := $(SILICA_ROOT)/compiler/stdlib/net/silica_sockets.c
SOCKETS_OBJ := $(BUILD)/silica_sockets.o
SOCKETS_ARCHIVE := $(LIB)/libsilica_sockets.a
SOCKETS_LINK := $(THIS_DIR)dangerous_exposure_source/sockets

.PHONY: all clean
all: $(ARCHIVE) $(SOCKETS_ARCHIVE) $(SOCKETS_LINK)

$(BUILD)/%.o: $(THIS_DIR)src/%.c $(wildcard $(THIS_DIR)dangerous_exposure_source/bees/*.h)
	@mkdir -p $(BUILD)
	$(CC) $(CFLAGS) -c $< -o $@

# the platform's implementations of bees_platform.h
$(BUILD)/plat_%.o: $(PLATFORM_DIR)/%.c $(THIS_DIR)bees_platform.h
	@mkdir -p $(BUILD)
	$(CC) $(CFLAGS) $(PLATFORM_SRC_CFLAGS) -c $< -o $@

$(ARCHIVE): $(OBJS)
	@mkdir -p $(LIB)
	ar rcs $@ $^
	@echo "[native] $(ARCHIVE)"

$(SOCKETS_OBJ): $(SOCKETS_SRC)
	@mkdir -p $(BUILD)
	$(CC) $(CFLAGS) -c $< -o $@

$(SOCKETS_ARCHIVE): $(SOCKETS_OBJ)
	@mkdir -p $(LIB)
	ar rcs $@ $^
	@echo "[native] $(SOCKETS_ARCHIVE) (the language's socket wrappers, from $(SOCKETS_SRC))"

$(SOCKETS_LINK):
	ln -sfn "$(SILICA_ROOT)/compiler/stdlib/net" "$@"

clean:
	rm -rf $(BUILD) $(ARCHIVE) $(SOCKETS_ARCHIVE)

# TRUST mode (N3): its own archive, libsilica_bees_trust.a, from trust/ (random bytes from the platform interface and the constant-time comparison); its sidecar is dangerous_exposure_source/trust/. Kept apart from the BEAM-mode entries (D36).
TRUST_SRCS := $(wildcard $(THIS_DIR)trust/*.c)
TRUST_OBJS := $(patsubst $(THIS_DIR)trust/%.c,$(BUILD)/trust_%.o,$(TRUST_SRCS)) $(patsubst %.c,$(BUILD)/plat_%.o,$(PLATFORM_TRUST_SRCS))
TRUST_ARCHIVE := $(LIB)/libsilica_bees_trust.a
all: $(TRUST_ARCHIVE)
$(BUILD)/trust_%.o: $(THIS_DIR)trust/%.c $(wildcard $(THIS_DIR)dangerous_exposure_source/trust/*.h)
	@mkdir -p $(BUILD)
	$(CC) $(CFLAGS) -I$(THIS_DIR)dangerous_exposure_source/trust -c $< -o $@
$(TRUST_ARCHIVE): $(TRUST_OBJS)
	@mkdir -p $(LIB)
	ar rcs $@ $^
	@echo "[native] $(TRUST_ARCHIVE) (TRUST mode)"
clean: clean-trust
.PHONY: clean-trust
clean-trust:
	rm -f $(TRUST_ARCHIVE) $(TRUST_OBJS)

# TRUST over TLS (N4.1): its own archive, libsilica_bees_tls.a, from tls/ over the programmer-installed OpenSSL (D40: BEES
# ships no TLS library; contract/what-is-required-to-use.md). OPENSSL_PREFIX names the installation (default: the platform's list, PLATFORM_OPENSSL_DIRS; macOS: Homebrew's
# openssl, then openssl@4). The minimum is OpenSSL 4.1.0, with no exception: an older OpenSSL, or none, is refused with a
# message naming what was found, and nothing is built or left against it. `make -C native tls` fails then (exit 1);
# `make -C native` (all) prints the same refusal and goes on, because the BEAM-mode and plaintext TRUST programs do not need the
# engine; every trial that needs it calls `tls` itself and fails with the message. build/tls.status: "ok <version>" or
# "refused: <why>".
OPENSSL_PREFIX ?= $(firstword $(foreach p,$(PLATFORM_OPENSSL_DIRS),$(if $(wildcard $(p)/include/openssl/ssl.h),$(p))))
TLS_ARCHIVE := $(LIB)/libsilica_bees_tls.a
TLS_OBJ := $(BUILD)/tls_silica_bees_tls.o
comma := ,
OPENSSL_VERSION_TEXT := $(if $(OPENSSL_PREFIX),$(shell awk '/define OPENSSL_VERSION_(MAJOR|MINOR|PATCH)[ \t]/ { v[$$(NF-1)] = $$NF } END { printf "%d.%d.%d", v["OPENSSL_VERSION_MAJOR"], v["OPENSSL_VERSION_MINOR"], v["OPENSSL_VERSION_PATCH"] }' "$(OPENSSL_PREFIX)/include/openssl/opensslv.h" 2>/dev/null))
OPENSSL_TOO_OLD := $(if $(OPENSSL_VERSION_TEXT),$(shell echo "$(OPENSSL_VERSION_TEXT)" | awk -F. '{ exit !(($$1 * 10000 + $$2 * 100 + $$3) < 40100) }' && echo 1))
TLS_REFUSAL := $(if $(wildcard $(OPENSSL_PREFIX)/include/openssl/ssl.h),$(if $(OPENSSL_TOO_OLD),OpenSSL $(OPENSSL_VERSION_TEXT) at $(OPENSSL_PREFIX) is older than 4.1.0$(comma) the minimum (contract/what-is-required-to-use.md); install OpenSSL 4.1.0 or later and point OPENSSL_PREFIX at it),no OpenSSL headers found (OPENSSL_PREFIX: $(or $(OPENSSL_PREFIX),unset; looked at $(PLATFORM_OPENSSL_DIRS))); install OpenSSL 4.1.0 or later and set OPENSSL_PREFIX (contract/what-is-required-to-use.md))
TLS_FLAGS_FILE := $(BUILD)/tls.flags
.PHONY: tls tls-report tls-selftest tls-flags
all: tls-report
# all: the refusal is printed and the other archives go on
tls-report:
	@$(MAKE) --no-print-directory tls || echo "[native] continuing without the TLS engine: only the TRUST-over-TLS trials need it, and they fail with the message above"
# tls: the engine, or a refusal (exit 1) naming the installed version and the minimum; a refused build leaves no archive
tls: tls-flags
	@if [ -n "$(TLS_REFUSAL)" ]; then echo "[native] REFUSED to build the TLS engine: $(TLS_REFUSAL)"; \
		echo "refused: $(TLS_REFUSAL)" > "$(BUILD)/tls.status"; rm -f "$(TLS_ARCHIVE)" "$(TLS_OBJ)"; exit 1; \
	else $(MAKE) --no-print-directory "$(TLS_ARCHIVE)" && echo "ok $(OPENSSL_VERSION_TEXT)" > "$(BUILD)/tls.status"; fi
# the installation is part of the object: it is rebuilt whenever OPENSSL_PREFIX changes
tls-flags:
	@mkdir -p $(BUILD); echo "$(OPENSSL_PREFIX)" | cmp -s - "$(TLS_FLAGS_FILE)" || echo "$(OPENSSL_PREFIX)" > "$(TLS_FLAGS_FILE)"
$(TLS_OBJ): $(THIS_DIR)tls/silica_bees_tls.c $(wildcard $(THIS_DIR)dangerous_exposure_source/tls/*.h) $(TLS_FLAGS_FILE)
	@mkdir -p $(BUILD)
	$(CC) $(CFLAGS) -I$(THIS_DIR)dangerous_exposure_source/tls -I$(OPENSSL_PREFIX)/include -c $< -o $@
$(TLS_ARCHIVE): $(TLS_OBJ)
	@mkdir -p $(LIB)
	ar rcs $@ $^
	@echo "[native] $(TLS_ARCHIVE) (TRUST over TLS; OpenSSL $(OPENSSL_VERSION_TEXT) at $(OPENSSL_PREFIX))"
# spike S12's in-memory checks of the engine against the trial certificates (TEST ONLY; run by trials/n4_trust_tls)
tls-selftest: tls
	@$(CC) -std=c11 -Wall -Wextra -O2 $(PLATFORM_CFLAGS) -I$(THIS_DIR) -DBEES_TLS_SELFTEST \
		-I$(THIS_DIR)dangerous_exposure_source/tls -I$(OPENSSL_PREFIX)/include $(THIS_DIR)tls/silica_bees_tls.c $(THIS_DIR)tls/selftest/bees_tls_selftest.c \
		-L$(OPENSSL_PREFIX)/lib $(if $(PLATFORM_RPATH_FLAG),$(PLATFORM_RPATH_FLAG)$(OPENSSL_PREFIX)/lib) -lssl -lcrypto -o $(BUILD)/bees_tls_selftest
	@$(BUILD)/bees_tls_selftest $(THIS_DIR)../trials/n4_trust_tls/certs
clean: clean-tls
.PHONY: clean-tls
clean-tls:
	rm -f $(TLS_ARCHIVE) $(TLS_OBJ) $(TLS_FLAGS_FILE) $(BUILD)/bees_tls_selftest $(BUILD)/tls.status

# TEMPUS (T4): its own archive, libsilica_bees_tempus.a, from tempus/ (Ed25519 over the programmer-installed OpenSSL, the same
# installation the TLS engine uses). Built on request (`make -C native tempus`), only when OPENSSL_PREFIX names an accepted
# installation; never for the boards (Mbed TLS has no Ed25519: development-plan/tempus-design.md NQ-6). Not part of `all`.
TEMPUS_SRCS := $(wildcard $(THIS_DIR)tempus/*.c)
TEMPUS_OBJS := $(patsubst $(THIS_DIR)tempus/%.c,$(BUILD)/tempus_%.o,$(TEMPUS_SRCS))
TEMPUS_ARCHIVE := $(LIB)/libsilica_bees_tempus.a
.PHONY: tempus tempus-selftest clean-tempus
tempus:
	@if [ -n "$(TLS_REFUSAL)" ]; then echo "[native] REFUSED to build the TEMPUS edge: $(TLS_REFUSAL)"; exit 1; \
	else $(MAKE) --no-print-directory "$(TEMPUS_ARCHIVE)"; fi
$(BUILD)/tempus_%.o: $(THIS_DIR)tempus/%.c $(wildcard $(THIS_DIR)tempus/*.h) $(wildcard $(THIS_DIR)dangerous_exposure_source/tempus/*.h) $(TLS_FLAGS_FILE)
	@mkdir -p $(BUILD)
	$(CC) $(CFLAGS) -I$(THIS_DIR)tempus -I$(THIS_DIR)dangerous_exposure_source/tempus -I$(OPENSSL_PREFIX)/include -c $< -o $@
$(TEMPUS_ARCHIVE): $(TEMPUS_OBJS)
	@mkdir -p $(LIB)
	ar rcs $@ $^
	@echo "[native] $(TEMPUS_ARCHIVE) (TEMPUS; OpenSSL $(OPENSSL_VERSION_TEXT) at $(OPENSSL_PREFIX))"
# TEST ONLY: Ed25519 against vectors made by Python
tempus-selftest: tls-flags
	@if [ -n "$(TLS_REFUSAL)" ]; then echo "[native] REFUSED: $(TLS_REFUSAL)"; exit 1; fi
	$(CC) $(CFLAGS) -I$(THIS_DIR)tempus -I$(OPENSSL_PREFIX)/include $(TEMPUS_SRCS) $(THIS_DIR)tempus/selftest/bees_tempus_selftest.c \
		-L$(OPENSSL_PREFIX)/lib $(if $(PLATFORM_RPATH_FLAG),$(PLATFORM_RPATH_FLAG)$(OPENSSL_PREFIX)/lib) -lcrypto -o $(BUILD)/bees_tempus_selftest
	@$(BUILD)/bees_tempus_selftest
clean: clean-tempus
clean-tempus:
	rm -f $(TEMPUS_ARCHIVE) $(TEMPUS_OBJS) $(BUILD)/bees_tempus_selftest
