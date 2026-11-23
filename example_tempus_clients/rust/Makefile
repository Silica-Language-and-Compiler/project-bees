# The Rust TEMPUS extension: build and unit tests. An example only: not for production (README.md).
# Needs cargo and rustc (any way of installing Rust that provides them) and an installed OpenSSL with X25519MLKEM768
# and Ed25519 (the one the BEES Makefiles use: native/macos/platform.mk, or OPENSSL_PREFIX=...).
# Nothing is fetched: the workspace has no dependency outside itself, and cargo is run with --offline.
#   make build   the library and every program, in target/debug/
#   make test    build, then the unit tests (cargo test; they read the recorded outputs of trials/t2_tempus_frames,
#                t0_tempus_clock, t4_tempus_admission and c4_tempus_boot and the TEST ONLY certificates of
#                trials/t5_tempus_tls/certs), the comparison of the node's stores with the Python models of tools/ and
#                with the recorded outputs of trials/t0_tempus_view and t1_tempus_store, and the check that the
#                library does not depend on the TEST ONLY crate
#   make clean   what cargo built (cargo clean)
HERE := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
BEES_ROOT := $(abspath $(HERE)/../..)
include $(BEES_ROOT)/tools/platform.mk
OPENSSL_PREFIX ?= $(firstword $(foreach p,$(PLATFORM_OPENSSL_DIRS),$(if $(wildcard $(p)/include/openssl/ssl.h),$(p))))
# cargo is looked for on PATH and then where rustup puts it
CARGO ?= $(or $(shell command -v cargo 2>/dev/null),$(wildcard $(HOME)/.cargo/bin/cargo))
BIN := $(HERE)/target/debug
RUN_CARGO := cd "$(HERE)" && OPENSSL_PREFIX="$(OPENSSL_PREFIX)" BEES_ROOT="$(BEES_ROOT)" PATH="$(dir $(CARGO)):$$PATH" "$(CARGO)"

.PHONY: build test clean
build:
	@[ -n "$(CARGO)" ] || { echo "FAIL: [rust extension] no cargo on this machine (README.md says what to install)"; exit 1; }
	@[ -n "$(OPENSSL_PREFIX)" ] || { echo "FAIL: [rust extension] no OpenSSL found (set OPENSSL_PREFIX)"; exit 1; }
	@out=$$($(RUN_CARGO) build --offline --quiet 2>&1); rc=$$?; [ "$$rc" = 0 ] || { printf '%s\n' "$$out"; echo "FAIL: [rust extension] cargo build"; exit 1; }
test: build
	@out=$$($(RUN_CARGO) test --offline --quiet -p tempus-tests 2>&1); rc=$$?; [ "$$rc" = 0 ] || { printf '%s\n' "$$out"; echo "FAIL: [rust extension] cargo test"; exit 1; }; printf '%s\n' "$$out" | awk '/^test result/ { p += $$4; f += $$6 } END { printf "rust unit tests: %d passed, %d failed\n", p, f }'
	@python3 "$(HERE)/test/model_check.py" "$(BIN)/tempus-model" "$(BEES_ROOT)"
	@python3 "$(HERE)/test/layering_check.py" "$(HERE)" "$(CARGO)"
clean:
	@[ -z "$(CARGO)" ] || { $(RUN_CARGO) clean --offline --quiet; }
