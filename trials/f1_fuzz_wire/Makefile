# F1: the wire fuzzer's smoke case (development-plan/spikes/F1-fuzzer.md). The driver, tools/bees_fuzz.py, plays a small fixed
# number of generated hostile cases (seed 1) against this leaf's own node programs and writes one line per case to smoke.sout:
# the surface, the case index, the generator's kind, the case's id (the SHA-256 of the generated case, so the golden pins the
# generator's output) and `ok`, or a FINDING line. No wall-clock value is printed. Surfaces and nodes (ports: tools/trial_ports.py,
# README.md here):
#   beam_accept    nodes/bl, a listening BEAM-mode node: the driver dials it as a hostile peer (handshake, frames)
#   beam_dial      nodes/bd, a dialing BEAM-mode node: the driver is its EPMD and the listener it dials
#   epmd_register  nodes/bl registering with the driver's EPMD at boot
#   trust_plain    nodes/ts, a TRUST server over plaintext test mode
#   trust_tls      nodes/tt, a TRUST server over mutual TLS 1.3 (needs the TLS engine, as trials/n4_trust_tls)
#   resolve        resolve/, generated resolver answers through the one filter (bees_addr), compiled into one program
# nodes/tc (a TRUST client that dials the driver: the trust_client surface) is built here and fuzzed only in the long run: its
# outcome depends on timing while the finding F1-3 of the spike document is open (an actor failure in the client's connection
# actor on a hostile token step), so it cannot be in a golden yet.
# The long run is trials/f2_fuzz_long (make -f fuzz.mk), never part of integrate.
# A FINDING line in the golden is a known, reported defect (the spike document lists each); the golden changes when it is fixed.
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)
HERE := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
include $(BEES_ROOT)/tools/silica.mk
NODES := bl bd ts tt tc
SMOKE_CASES := beam_accept=24,beam_dial=12,epmd_register=4,trust_plain=24,trust_tls=16,resolve=60
FUZZ = SILICA_COMPILER="$(SILICA_COMPILER)" python3 "$(BEES_ROOT)/tools/bees_fuzz.py"
.PHONY: build run integrate record-golden clean tls
# the TLS engine for node tt, or the leaf fails here with native/Makefile's refusal (as trials/n4_trust_tls)
tls:
	@out=$$($(MAKE) --no-print-directory -C "$(BEES_ROOT)/native" tls); rc=$$?; \
	if [ "$$rc" != 0 ] || ! grep -q '^ok ' "$(BEES_ROOT)/native/build/tls.status" 2>/dev/null; then \
		echo "FAIL: [f1_fuzz_wire] needs the TLS engine, which needs OpenSSL 4.1.0 or later: $$(cat "$(BEES_ROOT)/native/build/tls.status" 2>/dev/null)"; exit 1; fi
# a node leaf is built twice the first time: its root unit is generated at parse time, after make has listed the entries
build: tls
	@chmod 600 "$(BEES_ROOT)"/trials/n4_trust_tls/certs/*-key.pem
	@for n in $(NODES); do ($(MAKE) -C "$(HERE)/nodes/$$n" build || $(MAKE) -C "$(HERE)/nodes/$$n" build) || exit 1; $(MAKE) -C "$(HERE)/nodes/$$n" build > /dev/null || exit 1; done

run: build
	@cd "$(HERE)" && rm -rf smoke_out && { $(FUZZ) run --seed 1 --cases $(SMOKE_CASES) --trial "$(HERE)" --out smoke_out --smoke smoke.sout || true; }

integrate: run
	@cd "$(HERE)" && ok=0; ko=0; \
	if [ ! -f "smoke$(GOLD_SUFFIX).scout" ]; then echo "MISSING golden for $(BEES_PLATFORM_ID) (record one on this platform with make record-golden): [f1_fuzz_wire] smoke$(GOLD_SUFFIX).scout"; ko=1; \
	elif diff -Bw -q smoke.sout "smoke$(GOLD_SUFFIX).scout" > /dev/null; then ok=1; \
	else echo "DIFF: [f1_fuzz_wire] smoke"; diff -Bw "smoke$(GOLD_SUFFIX).scout" smoke.sout || true; ko=1; fi; \
	printf '%d %d\n' "$$ok" "$$ko" > .integrate_counts; echo "[f1_fuzz_wire] $$ok passed, $$ko failed"; [ "$$ko" -eq 0 ]

record-golden: run
	@cd "$(HERE)" && cp smoke.sout "smoke$(GOLD_SUFFIX).scout" && echo "[f1_fuzz_wire] golden recorded"

clean:
	@for n in $(NODES); do $(MAKE) -C "$(HERE)/nodes/$$n" clean; done; $(MAKE) -C "$(HERE)/resolve" clean
	@cd "$(HERE)" && rm -rf smoke.sout smoke_out .integrate_counts nodes/cookie resolve/fz_resolve.silica
