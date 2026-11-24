# The Swift TEMPUS extension: build and unit tests. A usable example, to be used with care (README.md).
# Needs Apple's Command Line Tools (swiftc and the Swift Package Manager; Xcode is not needed) and an installed OpenSSL
# with X25519MLKEM768 and Ed25519 (the one the BEES Makefiles use: native/macos/platform.mk, or OPENSSL_PREFIX=...).
# Nothing is fetched: the package has no remote dependency.
#   make build   the two libraries and every program (Package.swift lists them), in .build/
#   make test    build, then the unit tests of the client part and of the node part (they read the recorded outputs of
#                trials/t2_tempus_frames, t0_tempus_clock and t4_tempus_admission and the TEST ONLY certificates of
#                trials/t5_tempus_tls/certs), the comparison of the node's stores with the Python models of tools/, and
#                the check that no library depends on the TEST ONLY target
#   make gossip  build, then four instances of the driver (tempus-client gossip, a node each) as one TEMPUS network on this machine
#                (../gossip/gossip_run.py run swift; it needs python3 with the `cryptography` package for the test tokens)
#   make clean   remove .build/
HERE := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
BEES_ROOT := $(abspath $(HERE)/../..)
include $(BEES_ROOT)/tools/platform.mk
OPENSSL_PREFIX ?= $(firstword $(foreach p,$(PLATFORM_OPENSSL_DIRS),$(if $(wildcard $(p)/include/openssl/ssl.h),$(p))))
SWIFT ?= swift
BIN := $(HERE)/.build/debug
# --disable-sandbox: the package manager's own sandbox cannot start inside another sandbox, and this package has no
# plugin and no dependency for it to guard
SWIFT_BUILD := $(SWIFT) build --package-path "$(HERE)" --disable-sandbox -Xcc -I$(OPENSSL_PREFIX)/include -Xlinker -L$(OPENSSL_PREFIX)/lib

.PHONY: build test gossip clean
build:
	@command -v $(SWIFT) > /dev/null || { echo "FAIL: [swift client] no swift on this machine"; exit 1; }
	@[ -n "$(OPENSSL_PREFIX)" ] || { echo "FAIL: [swift client] no OpenSSL found (set OPENSSL_PREFIX)"; exit 1; }
	@out=$$($(SWIFT_BUILD) 2>&1); rc=$$?; [ "$$rc" = 0 ] || { printf '%s\n' "$$out"; echo "FAIL: [swift client] swift build"; exit 1; }
test: build
	@"$(BIN)/tempus-client-tests" "$(BEES_ROOT)"
	@"$(BIN)/tempus-node-tests" "$(BEES_ROOT)"
	@python3 "$(HERE)/test/model_check.py" "$(BIN)/tempus-node-tests"
	@python3 "$(HERE)/test/layering_check.py" "$(HERE)"
gossip: build
	@python3 "$(HERE)/../gossip/gossip_run.py" run swift
clean:
	@rm -rf "$(HERE)/.build"
