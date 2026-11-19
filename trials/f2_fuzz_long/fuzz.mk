# F2: the wire fuzzer's LONG run (development-plan/spikes/F1-fuzzer.md). NOT a trial leaf: this directory has no Makefile, so
# `make integrate` and tools/run_all_trials.sh never run it. Run it with
#
#     make -f fuzz.mk nodes     SILICA_COMPILER=...      copy trials/f1_fuzz_wire's node sources here with this block's ports
#                                                        (tools/trial_ports.py: f2_fuzz_long) and build them
#     make -f fuzz.mk fuzz-long SILICA_COMPILER=... [SEED=N] [DURATION=86400] [SURFACES=a,b] [SLICE=250] [RUNS=DIR]
#     make -f fuzz.mk replay    SEED=N SURFACE=s CASE=i [BEFORE=k]
#
# The node programs are the ones of trials/f1_fuzz_wire, on other ports, so a long run and `make integrate` can go on at the same
# time on one machine. A run is identified by SEED and the number of cases per surface it reached (RUNS/SEED/summary.json,
# written at the end; RUNS/SEED/run.log has a progress line per slice; RUNS defaults to runs/ here). Findings: RUNS/SEED/findings/, each with case.json,
# input.bin (the exact bytes), node_output.txt and repro.txt (the replay command). SILICA_COMPILER is needed by `nodes` and by the
# resolve surface (it compiles a batch of generated answers per slice); the other surfaces only run the built programs.
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)
HERE := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
include $(BEES_ROOT)/tools/silica.mk
NODES := bl bd ts tt tc
SEED ?= 20261118
DURATION ?= 86400
SLICE ?= 250
SURFACES ?=
BEFORE ?= 0
# where a run's output goes. On a machine the tree is synced to with rsync --delete (tools/run_all_trials.sh, .bees_build_hosts), set
# RUNS to a directory OUTSIDE the tree, or the next sync removes the run's output
RUNS ?= $(HERE)/runs
PORT_BASE := $(shell python3 "$(BEES_ROOT)/tools/trial_ports.py" port f2_fuzz_long 0)
FUZZ = SILICA_COMPILER="$(SILICA_COMPILER)" python3 "$(BEES_ROOT)/tools/bees_fuzz.py"
.PHONY: nodes fuzz-long replay clean tls
tls:
	@out=$$($(MAKE) --no-print-directory -C "$(BEES_ROOT)/native" tls); rc=$$?; \
	if [ "$$rc" != 0 ] || ! grep -q '^ok ' "$(BEES_ROOT)/native/build/tls.status" 2>/dev/null; then \
		echo "FAIL: [f2_fuzz_long] needs the TLS engine, which needs OpenSSL 4.1.0 or later: $$(cat "$(BEES_ROOT)/native/build/tls.status" 2>/dev/null)"; exit 1; fi

nodes: tls
	@chmod 600 "$(BEES_ROOT)"/trials/n4_trust_tls/certs/*-key.pem
	@$(FUZZ) prepare --from "$(BEES_ROOT)/trials/f1_fuzz_wire" --to "$(HERE)" --port-base $(PORT_BASE)
	@for n in $(NODES); do ($(MAKE) -C "$(HERE)/nodes/$$n" build || $(MAKE) -C "$(HERE)/nodes/$$n" build) || exit 1; $(MAKE) -C "$(HERE)/nodes/$$n" build > /dev/null || exit 1; done

fuzz-long:
	@mkdir -p "$(RUNS)/$(SEED)" && cd "$(HERE)" && \
	$(FUZZ) run --seed $(SEED) --duration $(DURATION) --slice $(SLICE) $(if $(SURFACES),--surfaces $(SURFACES)) --trial "$(HERE)" --out "$(RUNS)/$(SEED)" 2>&1 | tee "$(RUNS)/$(SEED)/run.log"

replay:
	@cd "$(HERE)" && $(FUZZ) replay --seed $(SEED) --surface $(SURFACE) --case $(CASE) --before $(BEFORE) --trial "$(HERE)"

clean:
	@for n in $(NODES); do [ -f "$(HERE)/nodes/$$n/Makefile" ] && $(MAKE) -C "$(HERE)/nodes/$$n" clean; done; true
