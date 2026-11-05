# M3: two plain Silica programs (separate OS processes) over the carrier transport actor on 127.0.0.1. Each node is its own
# leaf under nodes/ (one manifest, one generated bees_peers, a set of entry programs); the scenarios below start one entry of
# one node and one of another with tools/run_pair.py (listener first) and compare each program's output with its golden.
#   handshake_cast     a (listener) and b (dialer): the handshake completes and a cast to inbox on a arrives
#   unlisted           a and x, a node a does not list: a closes the link
#   before_handshake   a and a raw peer whose first bytes are a REG_SEND data frame: dropped, link closed
#   ticks_alive        a and b idle for 4.5 s, three times the 1.5 s silence limit: ticks keep the link up, then the cast arrives
#   ticks_absent       a and b that sends no ticks: a ends the link after 1.5 s and its proxy ends
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
 ticks_absent|a/dangerous_a_fast|killed)|b/dangerous_b_silent|closed|0

SCEN_QUOTED := $(foreach s,$(SCENARIOS),'$(s)')
.PHONY: build run integrate record-golden clean
# a node leaf is built until it succeeds (once more on a transient compiler crash, SD-29 family) and then once more, because the
# root units are generated at parse time and make may list the entries before they exist on the very first build
build:
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
			if [ ! -f "$$name.$$side.scout" ]; then echo "MISSING golden: [m3_dist] $$name.$$side.scout"; ko=$$((ko+1)); \
			elif diff -Bw -q "$$name.$$side.sout" "$$name.$$side.scout" > /dev/null; then ok=$$((ok+1)); \
			else echo "DIFF: [m3_dist] $$name.$$side"; diff -Bw "$$name.$$side.scout" "$$name.$$side.sout" || true; ko=$$((ko+1)); fi; \
		done; \
	done; printf '%d %d\n' "$$ok" "$$ko" > .integrate_counts; echo "[m3_dist] $$ok passed, $$ko failed"; [ "$$ko" -eq 0 ]

record-golden: run
	@cd "$(HERE)" && for s in $(SCEN_QUOTED); do name=$${s%%|*}; cp "$$name.a.sout" "$$name.a.scout"; cp "$$name.b.sout" "$$name.b.scout"; done; echo "[m3_dist] goldens recorded"

clean:
	@for n in $(NODES); do $(MAKE) -C "$(HERE)/nodes/$$n" clean; done; cd "$(HERE)" && rm -f *.sout .integrate_counts
