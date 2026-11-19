# N5: windowed multiplexing for TRUST (B2) over plaintext loopback (mvp.md section 5, N5; development-plan/spikes/N5-multiplexing.md).
# TEST ONLY as N3: plaintext_test_only, the peer identity a test-supplied stand-in for the certificate fingerprint (R5). Each
# scenario runs one server program and one client program as two OS processes on 127.0.0.1 (tools/run_trust_pair.py), each
# built from its own bees.config. Every bees.config here writes trust.session (or leaves it out on purpose: nodes b and d).
#   interleave   several requests at once on ONE connection, answers out of order, each caller gets its own; telemetry; metrics
#   window       max_calls: one goaway limit_reached, the last call still answered, close, the next call on a new session;
#                idle_ms; max_age_ms; session_slots_max
#   pause        max_inflight with read-pause backpressure: megabytes of requests wait unread while two slow calls hold the
#                limit; the server's resident set is sampled at the pause and one second later (flat: no queue); resume
#   deny         goaway deny (forbidden MFA, permission denied); suspicion per request; a failed request does not end the
#                session; quarantine in the middle of a session
#   protocol     goaway protocol (a malformed frame and an oversize frame in the middle of a session); an invalid token; a
#                duplicate req_id
#   shutdown     goaway shutdown: the call in work finishes and is answered, new connections are refused
#   cancel       cancel by close (trpc_close, and a raw peer that closes): results dropped, no suspicion
#   b1client     a B1 client (node d, no trust.session, N3's scenario role) against the multiplexing server
#   b1server     the session client against a B1 server (node e, no trust.session)
#   compat_scenario, compat_negative   N3's two suites on nodes built with trust.session 1 and 1: the outputs equal N3's
#                goldens (trials/n3_trust) once the port numbers are replaced (checked by `integrate`, and by the goldens here)
#   hostile_b1, hostile_session   F1-3: a hostile server (hostile_server.py, on node s's address) answers the token step with
#                answers a correct client refuses, followed by more bytes; a B1 client (node d, tcli) and a session client (node c,
#                mcli) give one outcome per call, accept the right answers after them, and report no actor failure
# Wall-clock values in telemetry and metrics lines (age_ms, duration_ms, paused_ms, the _ms_sum metrics) are replaced with N.
# `make measure` (not part of integrate: its numbers vary) is the soak: calls per second and resident set growth per call on
# sessions, to be read against N3's one connection per call (trials/n3_trust/measure.txt).
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)
HERE := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
include $(BEES_ROOT)/tools/silica.mk
NODES := s c w b d k kc
# --settle: the server is given its quiet time after the client has ended, so a session's end is always in its output
PAIR := $(BEES_ROOT)/tools/run_trust_pair.py --settle
READY := listening on 127.0.0.1
PORT := python3 "$(BEES_ROOT)/tools/trial_ports.py" port
# scenario|server exe|client exe|client done text ('_' stands for a space)
SCENARIOS := \
 interleave|s/dangerous_s_main|c/dangerous_c_interleave|interleave_done \
 window|w/dangerous_s_main|c/dangerous_c_window|window_done \
 pause|s/dangerous_s_main|c/dangerous_c_pause|pause_done \
 deny|s/dangerous_s_main|c/dangerous_c_deny|deny_done \
 protocol|s/dangerous_s_main|c/dangerous_c_protocol|protocol_done \
 shutdown|s/dangerous_s_main|c/dangerous_c_shutdown|shutdown_done \
 cancel|s/dangerous_s_main|c/dangerous_c_cancel|cancel_done \
 b1client|s/dangerous_s_main|d/dangerous_d_scenario|scenario_done \
 b1server|b/dangerous_s_main|c/dangerous_c_b1server|b1server_done \
 compat_scenario|k/dangerous_s_main|kc/dangerous_kc_scenario|scenario_done \
 compat_negative|k/dangerous_s_negative|kc/dangerous_kc_negative|negative_suite_done \
 hostile_b1|../hostile_server.py|d/dangerous_d_hostile|hostile_done \
 hostile_session|../hostile_server.py|c/dangerous_c_hostile|hostile_done
ONLY ?=
SCEN_QUOTED := $(foreach s,$(if $(ONLY),$(filter $(ONLY)|%,$(SCENARIOS)),$(SCENARIOS)),'$(s)')
# addresses, the runtime's root-actor lines, wall-clock values
CLEAN_OUT = clean_out() { $(SED_I) -E -e 's/0x[0-9a-f]{6,}/0xADDR/g' -e 's/(age_ms|duration_ms|paused_ms)=[0-9]+/\1=N/g' -e 's/^(\[trust metrics\] trust_[a-z_]*_ms_sum) [0-9]+/\1 N/' "$$@" && $(STRIP_ROOT_EXIT) "$$@"; }; clean_out
.PHONY: build run integrate record-golden clean measure
# a node leaf's root units are generated when its Makefile is parsed, after make has listed the entries: `units` parses it once
# (so the units exist), then one build sees them all
build:
	@for n in $(NODES); do $(MAKE) -C "$(HERE)/nodes/$$n" units > /dev/null && $(MAKE) -C "$(HERE)/nodes/$$n" build || exit 1; done

# `make run ONLY=name` runs one scenario and NOBUILD=1 runs them all, without building (the programs must be built)
NOBUILD ?=
run: $(if $(ONLY)$(NOBUILD),,build)
	@cd "$(HERE)" && for s in $(SCEN_QUOTED); do \
		sc=$$(echo "$$s" | cut -d'|' -f1); es=$$(echo "$$s" | cut -d'|' -f2); ec=$$(echo "$$s" | cut -d'|' -f3); \
		dn=$$(echo "$$s" | cut -d'|' -f4 | tr '_' ' '); \
		if [ "$$sc" = pause ]; then $(PAIR) "nodes/$$es" "$$sc.a.sout" "$(READY)" "nodes/$$ec" "$$sc.b.sout" "$$dn" --rss "telemetry] pause:1.0:pause.rss" || echo "pair $$sc: a run failed"; \
		else $(PAIR) "nodes/$$es" "$$sc.a.sout" "$(READY)" "nodes/$$ec" "$$sc.b.sout" "$$dn" || echo "pair $$sc: a run failed"; fi; \
		$(CLEAN_OUT) "$$sc.a.sout" "$$sc.b.sout"; $(TRUST_LATE_RESULT_LAST) "$$sc.a.sout"; \
		if [ "$$sc" = pause ]; then a=$$(awk '/^at_text/ { print $$2 }' pause.rss); l=$$(awk '/^later/ { print $$2 }' pause.rss); \
			if [ -n "$$a" ] && [ -n "$$l" ] && [ $$((l - a)) -lt 1024 ]; then echo "[pause] the server's resident set one second into the pause: within 1024 KiB of its size when it paused (megabytes of requests unread)" >> pause.a.sout; \
			else echo "[pause] the server's resident set GREW while paused, or was not sampled: at the pause $$a KiB, one second later $$l KiB" >> pause.a.sout; fi; fi; \
	done

# compat: N3's own goldens, with N3's port numbers replaced by this trial's, must equal what the session actors printed
N3 := $(BEES_ROOT)/trials/n3_trust
compat_same = sed -e "s/$$($(PORT) n3_trust 0)/$$($(PORT) n5_trust_mux 2)/g" -e "s/$$($(PORT) n3_trust 1)/$$($(PORT) n5_trust_mux 6)/g" "$(N3)/$(1)$(GOLD_SUFFIX).scout" | diff -Bw - "compat_$(1).sout" > /dev/null

integrate: run
	@cd "$(HERE)" && ok=0; ko=0; \
	check() { if [ ! -f "$$2" ]; then echo "MISSING golden for $(BEES_PLATFORM_ID) (record one on this platform with make record-golden): [n5_trust_mux] $$2"; ko=$$((ko+1)); \
		elif diff -Bw -q "$$1" "$$2" > /dev/null; then ok=$$((ok+1)); \
		else echo "DIFF: [n5_trust_mux] $$1"; diff -Bw "$$2" "$$1" || true; ko=$$((ko+1)); fi; }; \
	for s in $(SCEN_QUOTED); do name=$$(echo "$$s" | cut -d'|' -f1); \
		check "$$name.b.sout" "$$name.b$(GOLD_SUFFIX).scout"; check "$$name.a.sout" "$$name.a$(GOLD_SUFFIX).scout"; done; \
	for g in scenario.a scenario.b negative.a negative.b; do \
		if $(call compat_same,$$g); then ok=$$((ok+1)); else echo "DIFF: [n5_trust_mux] compat_$$g.sout is not N3's golden $$g with the ports replaced"; ko=$$((ko+1)); fi; done; \
	printf '%d %d\n' "$$ok" "$$ko" > .integrate_counts; echo "[n5_trust_mux] $$ok passed, $$ko failed"; [ "$$ko" -eq 0 ]

record-golden: run
	@cd "$(HERE)" && for s in $(SCEN_QUOTED); do name=$$(echo "$$s" | cut -d'|' -f1); \
		cp "$$name.b.sout" "$$name.b$(GOLD_SUFFIX).scout"; cp "$$name.a.sout" "$$name.a$(GOLD_SUFFIX).scout"; done; echo "[n5_trust_mux] goldens recorded"

# the soak: one run per call count, each program under /usr/bin/time -l (peak resident set). Five pairs per count:
#   sessions seq   the session server r (max_calls 1000, max_inflight 8), one call outstanding at a time
#   sessions win4  the same server, 4 calls outstanding at a time (below max_inflight: the server never pauses)
#   sessions win   the same server, 8 calls outstanding at a time (at max_inflight: the server pauses after every request)
#   baseline seq   the server without sessions (node e), one connection per call, one call at a time
#   baseline win   the same, 8 connections at a time
# What is read: calls per second, the latency buckets, and the growth of the peak resident set per call between the counts.
CALLS_LIST ?= 2000 6000 20000
MEASURE_PAIRS := sessions_seq|r/dangerous_s_main|rc/dangerous_rc_seq sessions_win4|r/dangerous_s_main|rc/dangerous_rc_win4 sessions_win|r/dangerous_s_main|rc/dangerous_rc_win \
	baseline_seq|b/dangerous_s_main|rc/dangerous_rc_base_seq baseline_win|b/dangerous_s_main|rc/dangerous_rc_base_win
measure:
	@for n in r b; do $(MAKE) -C "$(HERE)/nodes/$$n" units > /dev/null && $(MAKE) -C "$(HERE)/nodes/$$n" build > /dev/null 2>&1 || exit 1; done
	@cd "$(HERE)" && : > measure.txt && for n in $(CALLS_LIST); do \
		$(MAKE) -C "$(HERE)/nodes/rc" units CALLS=$$n > /dev/null && $(MAKE) -C "$(HERE)/nodes/rc" build CALLS=$$n > /dev/null 2>&1 || exit 1; \
		for p in $(foreach p,$(MEASURE_PAIRS),'$(p)'); do w=$$(echo "$$p" | cut -d'|' -f1); es=$$(echo "$$p" | cut -d'|' -f2); ec=$$(echo "$$p" | cut -d'|' -f3); \
			$(PAIR) "nodes/$$es" rate.a.out "$(READY)" "nodes/$$ec" rate.b.out "ok answers of" --time --cap 1500 && \
			{ echo "== $$n calls, $$w"; grep '^rate:' rate.b.out; for f in rate.a.out rate.b.out; do printf '%s peak resident set (bytes): ' "$$f"; awk '/maximum resident set size/ { print $$1 }' "$$f.rusage"; done; } | tee -a measure.txt; \
		done; \
	done

OUTPUTS =$(wildcard $(HERE)/*.sout) $(wildcard $(HERE)/rate.*.out*) $(HERE)/.integrate_counts $(HERE)/pause.rss $(HERE)/measure.txt
clean:
	@for n in $(NODES); do $(MAKE) -C "$(HERE)/nodes/$$n" clean; done; $(RM) $(OUTPUTS)
