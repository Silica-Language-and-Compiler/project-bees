# C1 codec coverage against a stock Erlang node (development-plan/spikes/C1-codec-term-coverage.md 2.1-2.7, 3.2, 3.5; the
# installed erl, OTP 27 or 28). tools/bees_codec_live.py starts a private EPMD on 127.0.0.1:24190 (the machine's own EPMD, if any, is
# not touched), compiles codec_driver.erl with the installed erlc into build/, and runs one scenario: the BEES node nodes/l
# (beesl@localhost, BEAM mode, cookie authentication, listening on 127.0.0.1:24100 and registered with that EPMD) against
# `erl -sname stock@localhost` with net_ticktime 8 and the dist listener on 127.0.0.1.
#   kinds   phase 1: BEES casts one message of each kind to a registered process of the stock node through the generated
#           BEAM-mode proxies (beam_peers@proxy_<name>): a sum value of each variant shape, a recursive chain, a map, a set, a
#           record holding a buf, a record of six fields, a dynamic term; for the map, set, buf and term a value the encoder
#           refuses is cast first (nothing arrives). The stock node prints each term as Erlang sees it, compares it with the
#           term expected (=:=), prints term_to_binary's bytes where they are canonical, and sends the term back to a registered
#           name of BEES, where the typed deliverer decodes it and the program prints it; only then is the next one sent.
#           phase 2: the stock node sends terms that do not fit the type of a typed name (a wrong tag, arity or variant; a chain
#           of 66 cells; a map with a wrong value or key type; a list, an ordset or a version 1 sets record (the default of sets:from_list/1 before OTP 28)
#           where the sets map is expected; a binary too
#           long for the buf; a record with a field missing or added): BEES drops each (`frame dropped` and the reason in its
#           audit) and the fitting term sent behind them arrives and is acknowledged.
#           phase 3: the stock node sends arbitrary terms to the name whose type is `term` (self(), make_ref(), a port, an
#           export fun, a local fun, an atom BEES never saw; integers small and big, a float, a bit string, an improper list, a
#           map with a pid as key): BEES prints the tokens (a pid, reference, port or fun as k12..k15, its kind number only: the
#           bytes vary between runs) and casts the token list back; the stock node confirms the echo =:= the original.
# Each run writes kinds.bees.sout and kinds.stock.sout (normalised: see tools/bees_codec_live.py) and kinds.*.raw (as printed).
# A machine without erl, erlc or epmd: the driver prints "[c1_codec_live] SKIPPED: ..." and writes .skipped; integrate then
# compares nothing, reports 0 passed, 0 failed and exits 0 (trials/n2_live has no such check: it fails there).
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)
HERE := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
include $(BEES_ROOT)/tools/silica.mk
NODES := l
SCENARIOS := kinds
.PHONY: build run integrate record-golden clean cookies
build: cookies
	@for n in $(NODES); do ($(MAKE) -C "$(HERE)/nodes/$$n" build || $(MAKE) -C "$(HERE)/nodes/$$n" build) || exit 1; $(MAKE) -C "$(HERE)/nodes/$$n" build > /dev/null || exit 1; done

run: build
	@cd "$(HERE)" && python3 "$(BEES_ROOT)/tools/bees_codec_live.py" "$(HERE)" $(SCENARIOS)

integrate: run
	@cd "$(HERE)" && if [ -f .skipped ]; then printf '0 0\n' > .integrate_counts; echo "[c1_codec_live] 0 passed, 0 failed (SKIPPED: $$(cat .skipped))"; exit 0; fi; \
	ok=0; ko=0; for s in $(SCENARIOS); do for side in bees stock; do \
		if [ ! -f "$$s.$$side$(GOLD_SUFFIX).scout" ]; then echo "MISSING golden for $(BEES_PLATFORM_ID) (record one on this platform with make record-golden): [c1_codec_live] $$s.$$side$(GOLD_SUFFIX).scout"; ko=$$((ko+1)); \
		elif diff -Bw -q "$$s.$$side.sout" "$$s.$$side$(GOLD_SUFFIX).scout" > /dev/null; then ok=$$((ok+1)); \
		else echo "DIFF: [c1_codec_live] $$s.$$side"; diff -Bw "$$s.$$side$(GOLD_SUFFIX).scout" "$$s.$$side.sout" || true; ko=$$((ko+1)); fi; \
	done; done; printf '%d %d\n' "$$ok" "$$ko" > .integrate_counts; echo "[c1_codec_live] $$ok passed, $$ko failed"; [ "$$ko" -eq 0 ]

record-golden: run
	@cd "$(HERE)" && if [ -f .skipped ]; then echo "[c1_codec_live] nothing recorded (SKIPPED: $$(cat .skipped))"; exit 0; fi; \
	for s in $(SCENARIOS); do cp "$$s.bees.sout" "$$s.bees$(GOLD_SUFFIX).scout"; cp "$$s.stock.sout" "$$s.stock$(GOLD_SUFFIX).scout"; done; echo "[c1_codec_live] goldens recorded"

clean:
	@for n in $(NODES); do $(MAKE) -C "$(HERE)/nodes/$$n" clean; done
	@cd "$(HERE)" && rm -f build/codec_driver.beam kinds.bees.sout kinds.stock.sout kinds.bees.raw kinds.stock.raw .integrate_counts .skipped

cookies:
	@cd "$(HERE)" && printf 'c1-codec-live-cookie\n' > cookie && chmod 600 cookie
