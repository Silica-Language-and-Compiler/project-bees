# N3: TRUST logic over plaintext loopback (mvp.md section 5, N3). Node a (nodes/s, the server) and node b (nodes/c, a client)
# are two separate OS processes on 127.0.0.1, each built from its own bees.config (TEST ONLY: plaintext_test_only, and the
# peer identity is a test-supplied stand-in for the certificate fingerprint, R5). tools/run_trust_pair.py starts the server,
# starts the client once the server listens, and stops both when the client is done.
#   scenario   (a) a permitted CALL (hello: a token is issued), a CALL on the token fast path, a CAST, a CALL with a binary
#   negative   the negative-path suite and trials (b), (c), (d): unlisted fingerprint, invalid token, a request before the token
#              step, wrong ver, a malformed map, a frame above frame_size_max, first-frame timeout, forbidden MFA (twice: one is
#              the local-only reset), permission denied, user-code failure, call timeout, quarantine at the suspicion limit,
#              operator reset (local) and recovery; a permitted CALL lowers suspicion
#   kill       (e) node a is killed (SIGKILL) while a connection is open; the peer sees the close (node a's side not compared)
#   boot_missing, boot_unreadable   (g) a configured whitelist file that is missing / unreadable (mode 000): the boot is
#              refused with a message naming the file, and no actor starts (R2)
# `make measure` (not part of integrate: its numbers vary) runs (f): 2,000 calls one per connection, each program under
# /usr/bin/time -l; the result is written to measure.txt (recorded in development-plan/spikes/N3-trust.md).
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)
HERE := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
include $(BEES_ROOT)/tools/silica.mk
NODES := s c g1 g2
PAIR := $(BEES_ROOT)/tools/run_trust_pair.py
READY := listening on 127.0.0.1
# scenario|server exe|client exe|client done text|kill text (blank: none)|server golden compared (1/0); '_' stands for a space
SCENARIOS := \
 scenario|s/dangerous_s_main|c/dangerous_c_scenario|scenario_done||1 \
 negative|s/dangerous_s_negative|c/dangerous_c_negative|negative_suite_done||1 \
 kill|s/dangerous_s_main|c/dangerous_c_kill|server_closed_the|the_server_answered_hello|0
BOOTS := boot_missing|g1 boot_unreadable|g2

SCEN_QUOTED := $(foreach s,$(SCENARIOS),'$(s)')
BOOT_QUOTED := $(foreach s,$(BOOTS),'$(s)')
CLEAN_OUT = sed -i '' -E -e 's/0x[0-9a-f]{6,}/0xADDR/g' -e '/^\[silica\] root actor exited/d'
.PHONY: build run integrate record-golden clean measure
# a node leaf is built twice the first time: its root units are generated at parse time, after make has listed the entries
build:
	@for n in $(NODES); do ($(MAKE) -C "$(HERE)/nodes/$$n" build || $(MAKE) -C "$(HERE)/nodes/$$n" build) || exit 1; $(MAKE) -C "$(HERE)/nodes/$$n" build > /dev/null || exit 1; done

run: build
	@cd "$(HERE)" && for s in $(SCEN_QUOTED); do \
		sc=$$(echo "$$s" | cut -d'|' -f1); es=$$(echo "$$s" | cut -d'|' -f2); ec=$$(echo "$$s" | cut -d'|' -f3); \
		dn=$$(echo "$$s" | cut -d'|' -f4 | tr '_' ' '); kt=$$(echo "$$s" | cut -d'|' -f5 | tr '_' ' '); \
		if [ -n "$$kt" ]; then "$(PAIR)" "nodes/$$es" "$$sc.a.sout" "$(READY)" "nodes/$$ec" "$$sc.b.sout" "$$dn" --kill "$$kt" || echo "pair $$sc: a run failed"; \
		else "$(PAIR)" "nodes/$$es" "$$sc.a.sout" "$(READY)" "nodes/$$ec" "$$sc.b.sout" "$$dn" || echo "pair $$sc: a run failed"; fi; \
		$(CLEAN_OUT) "$$sc.a.sout" "$$sc.b.sout"; \
	done
	@cd "$(HERE)" && for s in $(BOOT_QUOTED); do sc=$${s%%|*}; n=$${s##*|}; \
		perl -e 'alarm shift @ARGV; exec @ARGV' 30 "nodes/$$n/dangerous_g_boot" < /dev/null > "$$sc.sout" 2>&1; printf 'exit=%s\n' "$$?" >> "$$sc.sout"; \
		$(CLEAN_OUT) "$$sc.sout"; done

integrate: run
	@cd "$(HERE)" && ok=0; ko=0; \
	check() { if [ ! -f "$$2" ]; then echo "MISSING golden: [n3_trust] $$2"; ko=$$((ko+1)); \
		elif diff -Bw -q "$$1" "$$2" > /dev/null; then ok=$$((ok+1)); \
		else echo "DIFF: [n3_trust] $$1"; diff -Bw "$$2" "$$1" || true; ko=$$((ko+1)); fi; }; \
	for s in $(SCEN_QUOTED); do name=$$(echo "$$s" | cut -d'|' -f1); ag=$$(echo "$$s" | cut -d'|' -f6); \
		check "$$name.b.sout" "$$name.b.scout"; if [ "$$ag" = 1 ]; then check "$$name.a.sout" "$$name.a.scout"; fi; done; \
	for s in $(BOOT_QUOTED); do sc=$${s%%|*}; check "$$sc.sout" "$$sc.scout"; done; \
	printf '%d %d\n' "$$ok" "$$ko" > .integrate_counts; echo "[n3_trust] $$ok passed, $$ko failed"; [ "$$ko" -eq 0 ]

record-golden: run
	@cd "$(HERE)" && for s in $(SCEN_QUOTED); do name=$$(echo "$$s" | cut -d'|' -f1); ag=$$(echo "$$s" | cut -d'|' -f6); \
		cp "$$name.b.sout" "$$name.b.scout"; if [ "$$ag" = 1 ]; then cp "$$name.a.sout" "$$name.a.scout"; fi; done; \
	for s in $(BOOT_QUOTED); do sc=$${s%%|*}; cp "$$sc.sout" "$$sc.scout"; done; echo "[n3_trust] goldens recorded"

# (f) the rate and memory run: one run, this machine, each program under /usr/bin/time -l (peak resident set size)
measure: build
	@cd "$(HERE)" && "$(PAIR)" nodes/s/dangerous_s_main rate.a.out "$(READY)" nodes/c/dangerous_c_rate rate.b.out "ok answers of" --time --cap 600 && \
		{ grep '^rate:' rate.b.out; for f in rate.a.out rate.b.out; do printf '%s peak resident set (bytes): ' "$$f"; awk '/maximum resident set size/ { print $$1 }' "$$f.rusage"; done; } | tee measure.txt

clean:
	@for n in $(NODES); do $(MAKE) -C "$(HERE)/nodes/$$n" clean; done; cd "$(HERE)" && rm -f *.sout .integrate_counts rate.*.out* measure.txt
