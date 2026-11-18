# N4.1: TRUST over mutual TLS 1.3 between BEES nodes on this Mac (127.0.0.1), with the real certificate fingerprint (SHA-512
# of the DER, D11) in place of N3's test-only stand-in. The TRUST logic is N3's, unchanged; between it and the language's (:tcp)
# carrier sits BEES's TLS link (src/trust/dangerous_bees_tls.silica) over the TLS engine (native/tls, a thin C shim over the
# programmer-installed OpenSSL; BEES ships none, D40). Node a (nodes/s) serves; node b (nodes/c), node m (nodes/m) and node q (nodes/q) are
# clients; each is built from its own bees.config. The certificates in certs/ are TEST ONLY (tools/bees_test_certs.sh made them
# once; a test CA, keys that belong to nobody).
#   selftest   spike S12's in-memory checks of the engine (native/tls/selftest): mutual TLS 1.3 with X25519MLKEM768, the facts
#              it reports, the fingerprints equal to openssl's, P-256, and every refusal OpenSSL makes (other CA, expired, RSA,
#              X25519-only, TLS 1.2, ALPN h2, no certificate)
#   scenario   N3's scenario set over TLS: hello and token_issue, the token fast path, a cast, a binary argument (both sides)
#   negative   N3's negative suite over TLS, steps 2 to 16 (step 1, an unlisted stand-in, is the refusals case of u.pem)
#   kill       node a is SIGKILLed while a TLS connection is open; node b sees the close (node b's side compared)
#   pin        node m pins node a's address to another certificate: {error, server_not_pinned}, and node a sees the client
#              leave inside the handshake (both sides)
#   noca       node q has a SELF-SIGNED certificate (w.pem) and no cacertfile, node a has none either (D43): a call is answered; node a
#              trusts q by the whitelist's pin of w.pem, node q trusts a by the pin of a.pem (both sides)
#   refusals   openssl s_client against node a (no cacertfile; p.pem marked classical-allowed, D44), one broken rule per case;
#              node a's audit lines per case (node a's side). A certificate of another CA or an expired one is now refused by the
#              whitelist, not by a chain; a classical-only (X25519) peer is refused by the TLS link unless its entry is marked
# `make measure` (not part of integrate) runs (f): 2,000 calls, one TLS connection each, both programs under /usr/bin/time -l.
#
# The trial needs the TLS engine (make -C native tls), which needs OpenSSL 4.1.0 or later, with no exception. Without it the
# leaf FAILS with native/Makefile's refusal, which names the OpenSSL it found and the minimum; it never skips.
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)
HERE := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
include $(BEES_ROOT)/tools/silica.mk
NODES := s c m q
PAIR := $(BEES_ROOT)/tools/run_trust_pair.py
REFUSALS := $(BEES_ROOT)/tools/run_tls_refusals.py
READY := listening on 127.0.0.1
# the server's port, from the one table of the trials' ports (tools/trial_ports.py; the nodes' bees.config files hold the same numbers)
PORT_S := $(shell python3 "$(BEES_ROOT)/tools/trial_ports.py" port n4_trust_tls 0)
# scenario|server exe|client exe|client done text|kill text (blank: none)|server golden compared (1/0); '_' stands for a space
SCENARIOS := \
 scenario|s/dangerous_s_main|c/dangerous_c_scenario|scenario_done||1 \
 negative|s/dangerous_s_negative|c/dangerous_c_negative|negative_suite_done||1 \
 kill|s/dangerous_s_main|c/dangerous_c_kill|server_closed_the|the_server_answered_hello|0 \
 pin|s/dangerous_s_main|m/dangerous_m_pin|pin_done||1 \
 noca|s/dangerous_s_main|q/dangerous_q_noca|noca_done||1
SCEN_QUOTED := $(foreach s,$(SCENARIOS),'$(s)')
# an output is cleaned of addresses and the runtime's root-actor lines
CLEAN_OUT = clean_out() { $(SED_I) -E -e 's/0x[0-9a-f]{6,}/0xADDR/g' "$$@" && $(STRIP_ROOT_EXIT) "$$@"; }; clean_out
.PHONY: build run integrate record-golden clean measure tls
# the engine, or the leaf fails here with native/Makefile's refusal (the OpenSSL found, and the 4.1.0 minimum)
tls:
	@out=$$($(MAKE) --no-print-directory -C "$(BEES_ROOT)/native" tls); rc=$$?; \
	[ -z "$$out" ] || printf '%s\n' "$$out" | grep -v '^ar \|^cc ' ; \
	if [ "$$rc" != 0 ] || ! grep -q '^ok ' "$(BEES_ROOT)/native/build/tls.status" 2>/dev/null; then \
		echo "FAIL: [n4_trust_tls] needs the TLS engine, which needs OpenSSL 4.1.0 or later: $$(cat "$(BEES_ROOT)/native/build/tls.status" 2>/dev/null)"; exit 1; fi
build: tls
	@for n in $(NODES); do ($(MAKE) -C "$(HERE)/nodes/$$n" build || $(MAKE) -C "$(HERE)/nodes/$$n" build) || exit 1; $(MAKE) -C "$(HERE)/nodes/$$n" build > /dev/null || exit 1; done

run: build
	@cd "$(HERE)" && \
		$(MAKE) --no-print-directory -s -C "$(BEES_ROOT)/native" tls-selftest > selftest.sout 2>&1; printf 'exit=%s\n' "$$?" >> selftest.sout; \
		$(SED_I) -E -e '/^OpenSSL /d' selftest.sout; \
		for s in $(SCEN_QUOTED); do \
			sc=$$(echo "$$s" | cut -d'|' -f1); es=$$(echo "$$s" | cut -d'|' -f2); ec=$$(echo "$$s" | cut -d'|' -f3); \
			dn=$$(echo "$$s" | cut -d'|' -f4 | tr '_' ' '); kt=$$(echo "$$s" | cut -d'|' -f5 | tr '_' ' '); \
			if [ -n "$$kt" ]; then "$(PAIR)" "nodes/$$es" "$$sc.a.sout" "$(READY)" "nodes/$$ec" "$$sc.b.sout" "$$dn" --kill "$$kt" || echo "pair $$sc: a run failed"; \
			else "$(PAIR)" "nodes/$$es" "$$sc.a.sout" "$(READY)" "nodes/$$ec" "$$sc.b.sout" "$$dn" || echo "pair $$sc: a run failed"; fi; \
			$(CLEAN_OUT) "$$sc.a.sout" "$$sc.b.sout"; $(TRUST_LATE_RESULT_LAST) "$$sc.a.sout"; \
		done; \
		"$(REFUSALS)" nodes/s/dangerous_s_main refusals.a.sout "$(READY)" certs 127.0.0.1:$(PORT_S) --openssl "$(OPENSSL_PREFIX)/bin/openssl" || echo "refusals: the run failed"; \
		$(CLEAN_OUT) refusals.a.sout

integrate: run
	@cd "$(HERE)" && ok=0; ko=0; \
	check() { if [ ! -f "$$2" ]; then echo "MISSING golden for $(BEES_PLATFORM_ID) (record one on this platform with make record-golden): [n4_trust_tls] $$2"; ko=$$((ko+1)); \
		elif diff -Bw -q "$$1" "$$2" > /dev/null; then ok=$$((ok+1)); \
		else echo "DIFF: [n4_trust_tls] $$1"; diff -Bw "$$2" "$$1" || true; ko=$$((ko+1)); fi; }; \
	check selftest.sout selftest$(GOLD_SUFFIX).scout; \
	for s in $(SCEN_QUOTED); do name=$$(echo "$$s" | cut -d'|' -f1); ag=$$(echo "$$s" | cut -d'|' -f6); \
		check "$$name.b.sout" "$$name.b$(GOLD_SUFFIX).scout"; if [ "$$ag" = 1 ]; then check "$$name.a.sout" "$$name.a$(GOLD_SUFFIX).scout"; fi; done; \
	check refusals.a.sout refusals.a$(GOLD_SUFFIX).scout; \
	printf '%d %d\n' "$$ok" "$$ko" > .integrate_counts; echo "[n4_trust_tls] $$ok passed, $$ko failed"; [ "$$ko" -eq 0 ]

record-golden: run
	@cd "$(HERE)" && cp selftest.sout selftest$(GOLD_SUFFIX).scout; cp refusals.a.sout refusals.a$(GOLD_SUFFIX).scout; \
	for s in $(SCEN_QUOTED); do name=$$(echo "$$s" | cut -d'|' -f1); ag=$$(echo "$$s" | cut -d'|' -f6); \
		cp "$$name.b.sout" "$$name.b$(GOLD_SUFFIX).scout"; if [ "$$ag" = 1 ]; then cp "$$name.a.sout" "$$name.a$(GOLD_SUFFIX).scout"; fi; done; \
	echo "[n4_trust_tls] goldens recorded"

# (f) the rate and memory run over TLS: one run, this machine, each program under /usr/bin/time -l (peak resident set size)
measure: build
	@cd "$(HERE)" && "$(PAIR)" nodes/s/dangerous_s_main rate.a.out "$(READY)" nodes/c/dangerous_c_rate rate.b.out "ok answers of" --time --cap 900 && \
		{ grep '^rate:' rate.b.out; for f in rate.a.out rate.b.out; do printf '%s peak resident set (bytes): ' "$$f"; awk '/maximum resident set size/ { print $$1 }' "$$f.rusage"; done; } | tee measure.txt

clean:
	@for n in $(NODES); do $(MAKE) -C "$(HERE)/nodes/$$n" clean; done; cd "$(HERE)" && rm -f *.sout .integrate_counts rate.*.out* measure.txt
