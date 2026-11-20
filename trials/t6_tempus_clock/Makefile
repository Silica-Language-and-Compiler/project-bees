# T6: the clock's configured choices on running nodes, and a node built without the test unit (development-plan/
# tempus-design.md sections 10, 11 and 16.3; rulings NQ-22 and, on OQ-20, the owner's of 2026-11-20). Each program is
# built in its own directory under nodes/, so that each has its own list of units (lib/):
#   nodes/h   node H, a test program: externally driven, by the test unit (src/tempus_test/bees_tempus_test.silica).
#             clock_back hold, clock_fail continue: the hold beginning and ending, a failed reading and going on
#   nodes/s   node S, a test program. clock_back stop with clock_back_limit_s 60, clock_fail pause: the wait for the
#             clock (the line, the application told with 86, an accepted connection closed with clock_refused, a join
#             request that waits and is dialed at once when the clock is read again), a step back inside the limit, the
#             stop above it (the line, the application told with 87, an accepted connection closed with clock_stopped,
#             no resume)
#   nodes/p   node P, shaped like a production program: its lib/ lists neither the test unit nor its atoms and its
#             build line has no --use of it. It reads the machine's clock. A tick or clock frame is refused like any
#             frame of no kind.
# tools/bees_tempus_trial.py t6 starts each node in turn and walks the Python client's steps. Each program's output is
# copied here as h.sout, s.sout, p.sout and compared with its golden.
# `make production-check` (part of integrate) searches everything node P was compiled to (the .sams of its root unit and
# of every unit in nodes/p/lib, its atom table, its unit list and the linked program) for any trace of the test unit:
# its name, its functions, its atoms and its banner. Any hit fails the trial. The same search must find the unit in
# node H, or it would prove nothing. The sources are not searched: the library's comments name the test unit, to say
# that it is not there.
# Post-processing: tools/bees_tempus_reports.py (the runtime's reports of actors that ended normally land anywhere).
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)
HERE := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
include $(BEES_ROOT)/tools/silica.mk
NODES := h s p
OUTS := h s p
# what must not be in a program built without the test unit: the unit's name, its functions, the names the handlers and
# decoders had while they were in the library, the banner, the old flag and its refusal
TRACES := bees_tempus_test|tdrv|dec_tick|dec_clock|enc_tick|enc_clock|tn_rq_tick|tn_rq_clock|clock_later|TEST ONLY|control_test_only|test_only_refused
# the atoms of the two frames, as a line of an atom table
TRACE_ATOMS := ^:?(tick|clock|ms|wait|later)$$
.PHONY: build run integrate record-golden clean natives production-check
natives:
	@out=$$($(MAKE) --no-print-directory -C "$(BEES_ROOT)/native" tempus tls 2>&1); rc=$$?; \
	[ -z "$$out" ] || printf '%s\n' "$$out" | grep -v '^ar \|^cc \|^mkdir ' ; \
	if [ "$$rc" != 0 ]; then echo "FAIL: [t6_tempus_clock] needs the TEMPUS native edge and the TLS engine (make -C native tempus tls; OpenSSL 4.1.0 or later)"; exit 1; fi
build: natives
	@python3 "$(BEES_ROOT)/tools/bees_tempus_certs.py" check > /dev/null || { echo "FAIL: [t6_tempus_clock] the TEMPUS certificates are not what tools/bees_tempus_certs.py writes"; exit 1; }
	@for n in $(NODES); do $(MAKE) --no-print-directory -C "$(HERE)/nodes/$$n" build SILICA_COMPILER="$(SILICA_COMPILER)" || exit 1; done
production-check: build
	@cd "$(HERE)/nodes/p" && n=$$(ls *.sams lib/*.sams | wc -l | tr -d ' ') && \
	if grep -a -l -E '$(TRACES)' *.sams lib/*.sams silica.config silica.atoms dangerous_p 2>/dev/null; then echo "FAIL: [t6_tempus_clock] node P, built without the test unit, holds a trace of it (the files above)"; exit 1; fi; \
	if grep -E '$(TRACE_ATOMS)' silica.atoms lib/bees_atoms.index 2>/dev/null; then echo "FAIL: [t6_tempus_clock] node P's atom table holds an atom of the test frames"; exit 1; fi; \
	if ls lib | grep -q 'bees_tempus_test'; then echo "FAIL: [t6_tempus_clock] nodes/p/lib lists the test unit"; exit 1; fi; \
	cd ../h && grep -a -q -E '$(TRACES)' dangerous_h.sams && grep -a -q -E '$(TRACES)' dangerous_h && grep -q -E '$(TRACE_ATOMS)' silica.atoms || { echo "FAIL: [t6_tempus_clock] the search finds nothing in node H either, so it proves nothing"; exit 1; }; \
	echo "[t6_tempus_clock] production check: no trace of the test unit in node P ($$n compiled units, its atom table, its unit list and the linked program); the same search finds the unit in node H"
run: build
	@cd "$(HERE)" && python3 "$(BEES_ROOT)/tools/bees_tempus_trial.py" t6 . ; \
	cp nodes/h/dangerous_h.sout h.sout; cp nodes/s/dangerous_s.sout s.sout; cp nodes/p/dangerous_p.sout p.sout; \
	python3 "$(BEES_ROOT)/tools/bees_tempus_reports.py" h.sout s.sout p.sout
integrate: run production-check
	@cd "$(HERE)" && ok=0; ko=0; for o in $(OUTS); do g="$$o$(GOLD_SUFFIX).scout"; \
		if [ ! -f "$$g" ]; then echo "MISSING golden for $(BEES_PLATFORM_ID) (record one on this platform with make record-golden): [t6_tempus_clock] $$g"; ko=$$((ko+1)); \
		elif diff -q "$$o.sout" "$$g" > /dev/null; then ok=$$((ok+1)); \
		else echo "DIFF: [t6_tempus_clock] $$o"; diff "$$g" "$$o.sout" || true; ko=$$((ko+1)); fi; done; \
	printf '%d %d\n' "$$ok" "$$ko" > .integrate_counts; echo "[t6_tempus_clock] $$ok passed, $$ko failed"; [ "$$ko" -eq 0 ]
record-golden: run production-check
	@cd "$(HERE)" && for o in $(OUTS); do cp "$$o.sout" "$$o$(GOLD_SUFFIX).scout"; done; echo "[t6_tempus_clock] goldens recorded"
clean:
	@for n in $(NODES); do $(MAKE) --no-print-directory -C "$(HERE)/nodes/$$n" clean; done; cd "$(HERE)" && rm -f h.sout s.sout p.sout .integrate_counts
