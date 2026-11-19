# C1 codec coverage, two nodes (development-plan/spikes/C1-codec-term-coverage.md 2.1-2.7, 3.2, 3.5): two plain Silica
# programs (separate OS processes) on M3's auth-none node over 127.0.0.1:24000 exchange one message of every kind of the
# .wire grammar through the generated proxies (bees_peers@proxy_<name>) and deliverers. Node b listens and is started first;
# node a dials.
#   kinds   a sends to b, one at a time: a sum value of each variant shape (tagged tuples, a record, an atom), a recursive
#           chain with its region, a map, a set, a record holding a buf with its region, a record of six fields, a dynamic
#           term (integers small and big, a float, atoms, one of which no manifest of b holds, a binary, a bit string, a
#           tuple, a byte list, a proper and an improper list, a map). b's actors print what arrived (the chain walked and the
#           buffer read in the region that came with the message, the term's tokens) and cast the same message back through
#           b's own proxies; a prints the echo and only then sends the next message, so the order of every line of both
#           programs is fixed by the protocol. For the map, the set, the buf and the term, a value the sender's encoder refuses
#           (a key twice, an element twice, a count outside the buffer, a token list that is not one term) is cast first:
#           nothing arrives for it and nothing fails (ruling Q9: not sent, silently; the proxy reports nothing today, a known
#           gap), and the good message cast right behind it through the same proxy arrives next (b's `im 1`, `ints 1`,
#           `pkt 1`, `any 1`).
# Post-processing: the runtime's root-actor notice (one per deliverer that ends, placed by the scheduler) is removed, and what
# a program prints after its marker (`a: done`, `b: done`) is dropped except the exit code: the link ends only because the
# harness stops the programs, so the peer's close races the exit (trials/m3_dist does the same).
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)
HERE := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
include $(BEES_ROOT)/tools/silica.mk
NODES := a b
.PHONY: build run integrate record-golden clean
build:
	@for n in $(NODES); do ($(MAKE) -C "$(HERE)/nodes/$$n" build || $(MAKE) -C "$(HERE)/nodes/$$n" build) || exit 1; $(MAKE) -C "$(HERE)/nodes/$$n" build > /dev/null || exit 1; done

run: build
	@cd "$(HERE)" && "$(BEES_ROOT)/tools/run_pair.py" nodes/b/dangerous_b_echo kinds.b.sout "b: done" nodes/a/dangerous_a_send kinds.a.sout "a: done" 0.5 120 || echo "pair kinds: a run failed"; \
		$(SED_I) -E -e 's/0x[0-9a-f]{6,}/0xADDR/g' kinds.a.sout kinds.b.sout; $(STRIP_ROOT_EXIT) kinds.a.sout kinds.b.sout; \
		for side in a b; do \
			awk -v m="$$side: done" 'done { if ($$0 ~ /^exit=/) print; next } { print } index($$0, m) { done = 1 }' "kinds.$$side.sout" > "kinds.$$side.tmp" && mv "kinds.$$side.tmp" "kinds.$$side.sout"; \
		done

integrate: run
	@cd "$(HERE)" && ok=0; ko=0; for side in a b; do \
		if [ ! -f "kinds.$$side$(GOLD_SUFFIX).scout" ]; then echo "MISSING golden for $(BEES_PLATFORM_ID) (record one on this platform with make record-golden): [c1_codec_nodes] kinds.$$side$(GOLD_SUFFIX).scout"; ko=$$((ko+1)); \
		elif diff -Bw -q "kinds.$$side.sout" "kinds.$$side$(GOLD_SUFFIX).scout" > /dev/null; then ok=$$((ok+1)); \
		else echo "DIFF: [c1_codec_nodes] kinds.$$side"; diff -Bw "kinds.$$side$(GOLD_SUFFIX).scout" "kinds.$$side.sout" || true; ko=$$((ko+1)); fi; \
	done; printf '%d %d\n' "$$ok" "$$ko" > .integrate_counts; echo "[c1_codec_nodes] $$ok passed, $$ko failed"; [ "$$ko" -eq 0 ]

record-golden: run
	@cd "$(HERE)" && cp kinds.a.sout kinds.a$(GOLD_SUFFIX).scout && cp kinds.b.sout kinds.b$(GOLD_SUFFIX).scout && echo "[c1_codec_nodes] goldens recorded"

clean:
	@for n in $(NODES); do $(MAKE) -C "$(HERE)/nodes/$$n" clean; done; cd "$(HERE)" && rm -f kinds.a.sout kinds.b.sout .integrate_counts
