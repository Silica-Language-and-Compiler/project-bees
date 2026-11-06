# M4: the demo. A plain Silica service (node a) and client (node b), two separate OS processes over the M3 distribution layer on
# 127.0.0.1. The payload uses every type the typed ETF codec supports (roles/gen_types.py writes the manifests and the payload code).
# Scenarios (each starts one entry of node a and one of node b with tools/run_demo.py, listener first, and compares each program's
# output with its golden):
#   demo           b sends three requests, a answers each through reply_to=answers; both sides compare every payload
#   kill           the same, then a is killed (SIGKILL) and b's sender keeps casting: it sees only Silica's dead-actor failure
#   hostile        b injects five hostile frames into the live link, then a good request: each is refused and audited, the link stays
#   hostile_close  b injects a frame whose length is over the limit: refused, audited, the link is closed on both sides
# `make measure` (not part of integrate: its numbers vary) runs the rate scenario: 4000 requests, 8 in flight, each program under
# /usr/bin/time -l; the results are written to measure.txt.
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)
HERE := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
include $(BEES_ROOT)/tools/silica.mk
NODES := a b
# scenario|a exe|a marker|b exe|b marker|kill text (blank: none)|a golden (1: compared); no spaces in a field (make splits on them)
SCENARIOS := \
 demo|a/dangerous_a_demo|seq=3|b/dangerous_b_demo|answered,||1 \
 kill|a/dangerous_a_demo|seq=3|b/dangerous_b_kill|failed:|answered,|0 \
 hostile|a/dangerous_a_demo|seq=900|b/dangerous_b_hostile|step=6||1 \
 hostile_close|a/dangerous_a_demo|(killed)|b/dangerous_b_hostile_close|(killed)||1

SCEN_QUOTED := $(foreach s,$(SCENARIOS),'$(s)')
.PHONY: build run integrate record-golden clean measure
build:
	@python3 "$(HERE)/roles/gen_types.py"
	@for n in $(NODES); do ($(MAKE) -C "$(HERE)/nodes/$$n" build || $(MAKE) -C "$(HERE)/nodes/$$n" build) || exit 1; $(MAKE) -C "$(HERE)/nodes/$$n" build > /dev/null || exit 1; done

# an output is cleaned of what varies: addresses, the root actor's exit line, the count of ticks seen (a race with the stop),
# and, for the scenarios that end with the harness stopping the programs, what a program prints after its marker
run: build
	@cd "$(HERE)" && for s in $(SCEN_QUOTED); do \
		sc=$$(echo "$$s" | cut -d'|' -f1); ea=$$(echo "$$s" | cut -d'|' -f2); ma=$$(echo "$$s" | cut -d'|' -f3); eb=$$(echo "$$s" | cut -d'|' -f4); mb=$$(echo "$$s" | cut -d'|' -f5); kt=$$(echo "$$s" | cut -d'|' -f6); \
		if [ -n "$$kt" ]; then k="--kill-a-on"; else k=""; fi; \
		"$(BEES_ROOT)/tools/run_demo.py" --a "nodes/$$ea" "$$sc.a.sout" "$$ma" --b "nodes/$$eb" "$$sc.b.sout" "$$mb" $$k $${kt:+"$$kt"} || echo "pair $$sc: a run failed"; \
		sed -i '' -E -e 's/0x[0-9a-f]{6,}/0xADDR/g' -e '/^\[silica\] root actor exited/d' -e '/net ticks seen/d' "$$sc.a.sout" "$$sc.b.sout"; \
	done

integrate: run
	@cd "$(HERE)" && ok=0; ko=0; for s in $(SCEN_QUOTED); do \
		name=$$(echo "$$s" | cut -d'|' -f1); ag=$$(echo "$$s" | cut -d'|' -f7); \
		for side in a b; do \
			if [ "$$side" = a ] && [ "$$ag" = 0 ]; then continue; fi; \
			if [ ! -f "$$name.$$side.scout" ]; then echo "MISSING golden: [m4_demo] $$name.$$side.scout"; ko=$$((ko+1)); \
			elif diff -Bw -q "$$name.$$side.sout" "$$name.$$side.scout" > /dev/null; then ok=$$((ok+1)); \
			else echo "DIFF: [m4_demo] $$name.$$side"; diff -Bw "$$name.$$side.scout" "$$name.$$side.sout" || true; ko=$$((ko+1)); fi; \
		done; \
	done; printf '%d %d\n' "$$ok" "$$ko" > .integrate_counts; echo "[m4_demo] $$ok passed, $$ko failed"; [ "$$ko" -eq 0 ]

record-golden: run
	@cd "$(HERE)" && for s in $(SCEN_QUOTED); do name=$${s%%|*}; ag=$$(echo "$$s" | cut -d'|' -f7); cp "$$name.b.sout" "$$name.b.scout"; if [ "$$ag" = 1 ]; then cp "$$name.a.sout" "$$name.a.scout"; fi; done; echo "[m4_demo] goldens recorded"

# the rate and memory run: one run, this machine, each program under /usr/bin/time -l (peak resident set size)
measure: build
	@cd "$(HERE)" && "$(BEES_ROOT)/tools/run_demo.py" --time --stamps --cap 900 --a nodes/a/dangerous_a_rate rate.a.out "seq=4000" --b nodes/b/dangerous_b_rate rate.b.out "answered," && \
		python3 "$(BEES_ROOT)/tools/m4_measure.py" rate.a.out rate.b.out | tee measure.txt

clean:
	@for n in $(NODES); do $(MAKE) -C "$(HERE)/nodes/$$n" clean; done; cd "$(HERE)" && rm -f *.sout .integrate_counts rate.*.out* measure.txt
