# T5: TLS for TEMPUS (development-plan/tempus-design.md sections 4 and 17.6).
# Built so far: the engine's three additions, checked in memory by native/tempus/selftest/bees_tempus_tls_selftest.c built
# together with native/tls/silica_bees_tls.c: the TEMPUS profile (ALPN tempus/1), two credentials in one process (a TRUST pair
# and a TEMPUS pair at once), and the peer certificate's public key (Ed25519 only). Not built yet: the TEMPUS link in Silica
# and the node trials over it (the next step of T5).
# certs/ holds TEST-ONLY identities: Ed25519 keys from fixed seeds and certificates self-signed over them, written by
# tools/bees_tempus_certs.py (`check` must pass: the build fails when they are not what the tool writes), and one P-256
# certificate made once with the openssl command (a key type the key call must refuse). Keys that belong to nobody.
# The leaf needs the OpenSSL the TLS engine needs (4.1.0 or later); without it the leaf fails, it never skips.
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)
HERE := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
include $(BEES_ROOT)/tools/silica.mk
NATIVE := $(BEES_ROOT)/native
BIN := $(HERE)/tempus_tls_selftest
GOLDEN := $(HERE)/selftest$(GOLD_SUFFIX).scout

.PHONY: build run integrate record-golden clean
build:
	@[ -n "$(OPENSSL_PREFIX)" ] || { echo "FAIL: [t5_tempus_tls] needs OpenSSL 4.1.0 or later (OPENSSL_PREFIX)"; exit 1; }
	@python3 "$(BEES_ROOT)/tools/bees_tempus_certs.py" check > /dev/null || { echo "FAIL: [t5_tempus_tls] certs/ is not what tools/bees_tempus_certs.py writes"; exit 1; }
	@$(CLANG) -std=c11 -Wall -Wextra -DBEES_TLS_SELFTEST -I$(OPENSSL_PREFIX)/include -I$(NATIVE)/dangerous_exposure_source/tls \
		-I$(NATIVE)/tempus/selftest $(NATIVE)/tls/silica_bees_tls.c $(NATIVE)/tempus/selftest/bees_tempus_tls_selftest.c \
		$(OPENSSL_LDFLAGS) -lpthread -o "$(BIN)"
	@echo "[t5_tempus_tls] built: tempus_tls_selftest"

run: build
	@cd "$(HERE)" && "$(BIN)" certs ../n4_trust_tls/certs > selftest.sout 2>&1; printf 'exit=%s\n' "$$?" >> selftest.sout

integrate: run
	@cd "$(HERE)" && ok=0; ko=0; \
	if [ ! -f "$(GOLDEN)" ]; then echo "MISSING golden for $(BEES_PLATFORM_ID) (record one on this platform with make record-golden): [t5_tempus_tls] selftest$(GOLD_SUFFIX).scout"; ko=1; \
	elif diff -Bw -q selftest.sout "$(GOLDEN)" > /dev/null; then ok=1; \
	else echo "DIFF: [t5_tempus_tls] selftest"; diff -Bw "$(GOLDEN)" selftest.sout || true; ko=1; fi; \
	printf '%d %d\n' "$$ok" "$$ko" > .integrate_counts; echo "[t5_tempus_tls] $$ok passed, $$ko failed"; [ "$$ko" -eq 0 ]

record-golden: run
	@cd "$(HERE)" && cp selftest.sout "$(GOLDEN)" && echo "[t5_tempus_tls] goldens recorded"

clean:
	@cd "$(HERE)" && rm -f tempus_tls_selftest selftest.sout .integrate_counts
