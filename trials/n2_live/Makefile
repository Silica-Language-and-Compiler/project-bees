# N2: the live test against a stock Erlang node (the installed OTP 28's erl; D14 names OTP 29). tools/n2_live.py starts a
# private EPMD on 127.0.0.1:22090 (the machine's own EPMD, if any, is not touched), compiles stock_driver.erl with the installed
# erlc into build/, and runs five scenarios, each a BEES node (nodes/l: beesl@localhost, listening and registered with EPMD;
# nodes/d: beesd@localhost, dialing through EPMD) against `erl -sname ...@localhost` with net_ticktime 8 and the dist listener
# on 127.0.0.1:
#   stock_dials    ping (pong), nodes(), {inbox, BEES} ! Term, {Pid, Term} from BEES with a handed-out pid, Pid ! Term (SEND),
#                  a SEND to a pid BEES did not hand out (dropped), link/unlink/monitor (counted, monitor dropped), link to an
#                  unknown pid (EXIT noproc), 26 s idle with ticks, BEES killed: nodedown, noconnection to the linked process
#   bees_dials     BEES finds the stock node in EPMD, dials it, casts to its registered inbox; the stock node answers to outbox
#   wrong_ping     a stock node with another cookie pings BEES: refused by BEES, pang
#   wrong_listen   BEES dials a stock node with another cookie: refused by the stock node (its kernel's log line is kept)
#   unlisted       a stock node BEES does not list pings it: not_allowed, pang
# Each scenario writes NAME.bees.sout and NAME.stock.sout (normalised: numbers in "evidence:" lines) and NAME.*.raw (as printed).
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)
HERE := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
include $(BEES_ROOT)/tools/silica.mk
NODES := l d
SCENARIOS := stock_dials bees_dials wrong_ping wrong_listen unlisted
.PHONY: build run integrate record-golden clean cookies
build: cookies
	@for n in $(NODES); do ($(MAKE) -C "$(HERE)/nodes/$$n" build || $(MAKE) -C "$(HERE)/nodes/$$n" build) || exit 1; $(MAKE) -C "$(HERE)/nodes/$$n" build > /dev/null || exit 1; done

run: build
	@cd "$(HERE)" && python3 "$(BEES_ROOT)/tools/n2_live.py" "$(HERE)" $(SCENARIOS)

integrate: run
	@cd "$(HERE)" && ok=0; ko=0; for s in $(SCENARIOS); do for side in bees stock; do \
		if [ ! -f "$$s.$$side$(GOLD_SUFFIX).scout" ]; then echo "MISSING golden for $(BEES_PLATFORM_ID) (record one on this platform with make record-golden): [n2_live] $$s.$$side$(GOLD_SUFFIX).scout"; ko=$$((ko+1)); \
		elif diff -Bw -q "$$s.$$side.sout" "$$s.$$side$(GOLD_SUFFIX).scout" > /dev/null; then ok=$$((ok+1)); \
		else echo "DIFF: [n2_live] $$s.$$side"; diff -Bw "$$s.$$side$(GOLD_SUFFIX).scout" "$$s.$$side.sout" || true; ko=$$((ko+1)); fi; \
	done; done; printf '%d %d\n' "$$ok" "$$ko" > .integrate_counts; echo "[n2_live] $$ok passed, $$ko failed"; [ "$$ko" -eq 0 ]

record-golden: run
	@cd "$(HERE)" && for s in $(SCENARIOS); do cp "$$s.bees.sout" "$$s.bees$(GOLD_SUFFIX).scout"; cp "$$s.stock.sout" "$$s.stock$(GOLD_SUFFIX).scout"; done; echo "[n2_live] goldens recorded"

clean:
	@for n in $(NODES); do $(MAKE) -C "$(HERE)/nodes/$$n" clean; done
	@cd "$(HERE)" && rm -f build/stock_driver.beam *.sout *.raw .integrate_counts

cookies:
	@cd "$(HERE)" && printf 'n2-live-cookie\n' > cookie && chmod 600 cookie
