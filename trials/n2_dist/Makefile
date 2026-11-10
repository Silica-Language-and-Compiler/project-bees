# N2: the M3 scenarios re-run in BEAM mode with Erlang's cookie authentication (R4), BEES to BEES over 127.0.0.1 with fixed
# ports (beam.epmd none; EPMD is exercised by trials/n2_live), plus the cookie's own refusals. Each node is its own leaf under
# nodes/ (one manifest, one bees.config, generated bees_peers, beam_conf and beam_peers, a set of entry programs); a scenario
# starts one entry of one node and one of another with tools/run_pair.py (listener first) and compares each program's output.
#   handshake_cast      a (listener) and b (dialer): N, s, N with a challenge, r, a; a cast to inbox on a arrives
#   unlisted            a and x, a node a does not list: a answers the status not_allowed and closes; x audits the refusal
#   before_handshake    a and a raw peer whose first bytes are a REG_SEND data frame: dropped, link closed
#   ticks_alive         a and b idle for 4.5 s, three times the 1.5 s silence limit: ticks keep the link up, then the cast arrives
#   ticks_absent        a and b that sends no ticks: a ends the link after 1.5 s and its proxy ends
#   wrong_cookie_dial   b dials with another cookie: a refuses b's challenge reply (r) and closes; b sees the link go
#   wrong_cookie_listen a listens with another cookie: a refuses the right r all the same (the digests differ) and closes
#   loose_cookie        b's cookie file is readable by others (mode 644): its cookie worker refuses it, b closes the link
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)
HERE := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
include $(BEES_ROOT)/tools/silica.mk
NODES := a b x
# scenario|a-side exe|marker (a word in the output after which the program is told to exit)|b-side exe|marker
# a trailing 1: the link ends only because the harness stops the programs (the peer's close races the exit of the process), so
# what a program prints after its marker is not stable and is dropped (the exit code line is kept)
SCENARIOS := \
 handshake_cast|a/dangerous_a_slow|got|b/dangerous_b_slow|sent|1 \
 unlisted|a/dangerous_a_slow|unlisted|x/dangerous_x_idle|closed|0 \
 before_handshake|a/dangerous_a_slow|before|b/dangerous_b_raw|down|0 \
 ticks_alive|a/dangerous_a_fast|got|b/dangerous_b_idle|sent|1 \
 ticks_absent|a/dangerous_a_fast|killed)|b/dangerous_b_silent|closed|0 \
 wrong_cookie_dial|a/dangerous_a_slow|killed)|b/dangerous_b_wrong|killed)|0 \
 wrong_cookie_listen|a/dangerous_a_wrong|killed)|b/dangerous_b_slow|killed)|0 \
 loose_cookie|a/dangerous_a_slow|killed)|b/dangerous_b_loose|killed)|0

SCEN_QUOTED := $(foreach s,$(SCENARIOS),'$(s)')
.PHONY: build run integrate record-golden clean cookies
# a node leaf is built until it succeeds (once more on a transient compiler crash, SD-29 family) and then once more, because the
# root units are generated at parse time and make may list the entries before they exist on the very first build
build: cookies
	@for n in $(NODES); do ($(MAKE) -C "$(HERE)/nodes/$$n" build || $(MAKE) -C "$(HERE)/nodes/$$n" build) || exit 1; $(MAKE) -C "$(HERE)/nodes/$$n" build > /dev/null || exit 1; done

run: build
	@cd "$(HERE)" && for s in $(SCEN_QUOTED); do \
		sc=$$(echo "$$s" | cut -d'|' -f1); ea=$$(echo "$$s" | cut -d'|' -f2); ma=$$(echo "$$s" | cut -d'|' -f3); eb=$$(echo "$$s" | cut -d'|' -f4); mb=$$(echo "$$s" | cut -d'|' -f5); tr=$$(echo "$$s" | cut -d'|' -f6); \
		"$(BEES_ROOT)/tools/run_pair.py" "nodes/$$ea" "$$sc.a.sout" "$$ma" "nodes/$$eb" "$$sc.b.sout" "$$mb" 0.5 60 || echo "pair $$sc: a run failed"; \
		sed -i '' -E -e 's/0x[0-9a-f]{6,}/0xADDR/g' -e '/^\[silica\] root actor exited/d' "$$sc.a.sout" "$$sc.b.sout"; \
		if [ "$$tr" = 1 ]; then \
			awk -v m="$$ma" 'done { if ($$0 ~ /^exit=/) print; next } { print } index($$0, m) { done = 1 }' "$$sc.a.sout" > "$$sc.a.tmp" && mv "$$sc.a.tmp" "$$sc.a.sout"; \
			awk -v m="$$mb" 'done { if ($$0 ~ /^exit=/) print; next } { print } index($$0, m) { done = 1 }' "$$sc.b.sout" > "$$sc.b.tmp" && mv "$$sc.b.tmp" "$$sc.b.sout"; \
		fi; \
	done

integrate: run
	@cd "$(HERE)" && ok=0; ko=0; for s in $(SCEN_QUOTED); do \
		name=$${s%%|*}; \
		for side in a b; do \
			if [ ! -f "$$name.$$side.scout" ]; then echo "MISSING golden: [n2_dist] $$name.$$side.scout"; ko=$$((ko+1)); \
			elif diff -Bw -q "$$name.$$side.sout" "$$name.$$side.scout" > /dev/null; then ok=$$((ok+1)); \
			else echo "DIFF: [n2_dist] $$name.$$side"; diff -Bw "$$name.$$side.scout" "$$name.$$side.sout" || true; ko=$$((ko+1)); fi; \
		done; \
	done; printf '%d %d\n' "$$ok" "$$ko" > .integrate_counts; echo "[n2_dist] $$ok passed, $$ko failed"; [ "$$ko" -eq 0 ]

record-golden: run
	@cd "$(HERE)" && for s in $(SCEN_QUOTED); do name=$${s%%|*}; cp "$$name.a.sout" "$$name.a.scout"; cp "$$name.b.sout" "$$name.b.scout"; done; echo "[n2_dist] goldens recorded"

clean:
	@for n in $(NODES); do $(MAKE) -C "$(HERE)/nodes/$$n" clean; done; cd "$(HERE)" && rm -f *.sout .integrate_counts

# the cookie files (git keeps no permissions): the shared cookie and a different one, mode 600, and the shared cookie in a file
# that group and others may read (644), which the native edge must refuse
cookies:
	@cd "$(HERE)" && printf 'n2-cookie\n' > cookie && chmod 600 cookie && printf 'n2-other\n' > cookie_wrong && chmod 600 cookie_wrong && \
		printf 'n2-cookie\n' > cookie_loose && chmod 644 cookie_loose
