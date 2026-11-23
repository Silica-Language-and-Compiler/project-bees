# N5 over mutual TLS 1.3: windowed multiplexing for TRUST (B2) on the TLS link of N4.1 (development-plan/spikes/N5-multiplexing.md).
# The session actors are the ones trials/n5_trust_mux runs over plaintext, unchanged; between them and the language's (:tcp)
# carrier sits BEES's TLS link (src/trust/dangerous_bees_tls.silica) over the TLS engine (native/tls, the programmer-installed
# OpenSSL, D40). The peer identity is the SHA-512 of its certificate (D11); the certificates are trials/n4_trust_tls/certs
# (TEST ONLY). The roles are trials/n5_trust_mux/roles; every scenario is described there and in that trial's Makefile.
#   interleave   several requests at once on one TLS connection, answers out of order; telemetry; metrics
#   deny         goaway deny, suspicion per request, a failed request does not end the session, quarantine mid-session
#   protocol     goaway protocol (malformed and oversize frames mid-session), an invalid token, a duplicate req_id
#   cancel       cancel by close (trpc_close, and a raw TLS peer that closes)
#   b1client     a B1 client (node d, no trust.session, N4's scenario role) against the multiplexing server
#   b1server     the session client against a B1 server (node e, no trust.session)
# `make measure` (not part of integrate) is the soak over TLS, to be read against N4's one TLS connection per call.
# The trial needs the TLS engine (make -C native tls: OpenSSL 4.1.0 or later). Without it the leaf FAILS; it never skips.
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)
HERE := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
include $(BEES_ROOT)/tools/silica.mk
NODES := s c b d
# --settle: the server is given its quiet time after the client has ended, so a session's end is always in its output
PAIR := $(BEES_ROOT)/tools/run_trust_pair.py --settle
READY := listening on 127.0.0.1
# scenario|server exe|client exe|client done text ('_' stands for a space)
SCENARIOS := \
 interleave|s/dangerous_s_main|c/dangerous_c_interleave|interleave_done \
 deny|s/dangerous_s_main|c/dangerous_c_deny|deny_done \
 protocol|s/dangerous_s_main|c/dangerous_c_protocol|protocol_done \
 cancel|s/dangerous_s_main|c/dangerous_c_cancel|cancel_done \
 b1client|s/dangerous_s_main|d/dangerous_d_scenario|scenario_done \
 b1server|b/dangerous_s_main|c/dangerous_c_b1server|b1server_done
ONLY ?=
SCEN_QUOTED := $(foreach s,$(if $(ONLY),$(filter $(ONLY)|%,$(SCENARIOS)),$(SCENARIOS)),'$(s)')
# as trials/n5_trust_mux: addresses, the runtime's root-actor lines, wall-clock values
CLEAN_OUT = clean_out() { $(SED_I) -E -e 's/0x[0-9a-f]{6,}/0xADDR/g' -e 's/(age_ms|duration_ms|paused_ms)=[0-9]+/\1=N/g' -e 's/^(\[trust metrics\] trust_[a-z_]*_ms_sum) [0-9]+/\1 N/' "$$@" && $(STRIP_ROOT_EXIT) "$$@" && $(STRIP_CARRIER_LINK_LOST) "$$@"; }; clean_out
.PHONY: build run integrate record-golden clean measure tls
# the engine, or the leaf fails here with native/Makefile's refusal (the OpenSSL found, and the 4.1.0 minimum)
tls:
	@out=$$($(MAKE) --no-print-directory -C "$(BEES_ROOT)/native" tls); rc=$$?; \
	[ -z "$$out" ] || printf '%s\n' "$$out" | grep -v '^ar \|^cc ' ; \
	if [ "$$rc" != 0 ] || ! grep -q '^ok ' "$(BEES_ROOT)/native/build/tls.status" 2>/dev/null; then \
		echo "FAIL: [n5_trust_mux_tls] needs the TLS engine, which needs OpenSSL 4.1.0 or later: $$(cat "$(BEES_ROOT)/native/build/tls.status" 2>/dev/null)"; exit 1; fi
build: tls
	@chmod 600 "$(BEES_ROOT)"/trials/n4_trust_tls/certs/*-key.pem; for n in $(NODES); do $(MAKE) -C "$(HERE)/nodes/$$n" units > /dev/null && $(MAKE) -C "$(HERE)/nodes/$$n" build || exit 1; done

# `make run ONLY=name` runs one scenario and NOBUILD=1 runs them all, without building (the programs must be built)
NOBUILD ?=
run: $(if $(ONLY)$(NOBUILD),,build)
	@cd "$(HERE)" && for s in $(SCEN_QUOTED); do \
		sc=$$(echo "$$s" | cut -d'|' -f1); es=$$(echo "$$s" | cut -d'|' -f2); ec=$$(echo "$$s" | cut -d'|' -f3); \
		dn=$$(echo "$$s" | cut -d'|' -f4 | tr '_' ' '); \
		$(PAIR) "nodes/$$es" "$$sc.a.sout" "$(READY)" "nodes/$$ec" "$$sc.b.sout" "$$dn" || echo "pair $$sc: a run failed"; \
		$(CLEAN_OUT) "$$sc.a.sout" "$$sc.b.sout"; \
	done

integrate: run
	@cd "$(HERE)" && ok=0; ko=0; \
	check() { if [ ! -f "$$2" ]; then echo "MISSING golden for $(BEES_PLATFORM_ID) (record one on this platform with make record-golden): [n5_trust_mux_tls] $$2"; ko=$$((ko+1)); \
		elif diff -Bw -q "$$1" "$$2" > /dev/null; then ok=$$((ok+1)); \
		else echo "DIFF: [n5_trust_mux_tls] $$1"; diff -Bw "$$2" "$$1" || true; ko=$$((ko+1)); fi; }; \
	for s in $(SCEN_QUOTED); do name=$$(echo "$$s" | cut -d'|' -f1); \
		check "$$name.b.sout" "$$name.b$(GOLD_SUFFIX).scout"; check "$$name.a.sout" "$$name.a$(GOLD_SUFFIX).scout"; done; \
	printf '%d %d\n' "$$ok" "$$ko" > .integrate_counts; echo "[n5_trust_mux_tls] $$ok passed, $$ko failed"; [ "$$ko" -eq 0 ]

record-golden: run
	@cd "$(HERE)" && for s in $(SCEN_QUOTED); do name=$$(echo "$$s" | cut -d'|' -f1); \
		cp "$$name.b.sout" "$$name.b$(GOLD_SUFFIX).scout"; cp "$$name.a.sout" "$$name.a$(GOLD_SUFFIX).scout"; done; echo "[n5_trust_mux_tls] goldens recorded"

# the soak over TLS: as trials/n5_trust_mux's (sessions on node r against one TLS connection per call on node e)
CALLS_LIST ?= 2000 6000
MEASURE_PAIRS := sessions_seq|r/dangerous_s_main|rc/dangerous_rc_seq sessions_win4|r/dangerous_s_main|rc/dangerous_rc_win4 sessions_win|r/dangerous_s_main|rc/dangerous_rc_win \
	baseline_seq|b/dangerous_s_main|rc/dangerous_rc_base_seq baseline_win|b/dangerous_s_main|rc/dangerous_rc_base_win
measure: tls
	@for n in r b; do $(MAKE) -C "$(HERE)/nodes/$$n" units > /dev/null && $(MAKE) -C "$(HERE)/nodes/$$n" build > /dev/null 2>&1 || exit 1; done
	@cd "$(HERE)" && : > measure.txt && for n in $(CALLS_LIST); do \
		$(MAKE) -C "$(HERE)/nodes/rc" units CALLS=$$n > /dev/null && $(MAKE) -C "$(HERE)/nodes/rc" build CALLS=$$n > /dev/null 2>&1 || exit 1; \
		for p in $(foreach p,$(MEASURE_PAIRS),'$(p)'); do w=$$(echo "$$p" | cut -d'|' -f1); es=$$(echo "$$p" | cut -d'|' -f2); ec=$$(echo "$$p" | cut -d'|' -f3); \
			$(PAIR) "nodes/$$es" rate.a.out "$(READY)" "nodes/$$ec" rate.b.out "ok answers of" --time --cap 1500 && \
			{ echo "== $$n calls, $$w"; grep '^rate:' rate.b.out; for f in rate.a.out rate.b.out; do printf '%s peak resident set (bytes): ' "$$f"; awk '/maximum resident set size/ { print $$1 }' "$$f.rusage"; done; } | tee -a measure.txt; \
		done; \
	done

OUTPUTS =$(wildcard $(HERE)/*.sout) $(wildcard $(HERE)/rate.*.out*) $(HERE)/.integrate_counts $(HERE)/measure.txt
clean:
	@for n in $(NODES); do $(MAKE) -C "$(HERE)/nodes/$$n" clean; done; $(RM) $(OUTPUTS)
