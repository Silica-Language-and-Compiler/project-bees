# N1: frame caps from bees.config (D39 R1: up to BEAM's 4294967295), two plain Silica programs on M3's auth-none node over
# 127.0.0.1. Node a's beam.frame_size_max is 9 MiB, node b's 4294967295 (BEAM's) (nodes/*/bees.config; the one reader, tools/bees_conf.py,
# turns the cap into the generated decode limits and the wireframe@unframe cap).
#   big   b sends { seq, blob } of 64 KiB, 1 MiB and 8 MiB to blobs on a, one at a time; a casts each back whole (a round trip,
#         the answer's length is printed); then a blob of 10 MiB, above a's cap: a refuses the frame from its 4-byte length,
#         before any byte of it is stored (`bad frame length, link closed too_large 5`). b, still writing the 10 MiB, sees its
#         write fail: its carrier reports the link down (`link down, proxies ended; reason link_down 3`) and b ends with exit=0.
#         Until Silica commit 71009f96f8 (SO_NOSIGPIPE on the carrier's sockets) b was killed by SIGPIPE here (exit=-13, a
#         flaky golden; SD-42 in development-plan/silica-defects.md, now resolved); the golden was re-recorded 2026-11-12 after
#         four identical runs.
# The `time ms` lines (the round-trip time of each frame) vary and are moved out of the golden into big.times; `make measure`
# runs the scenario once under /usr/bin/time -l (peak resident set of each program) and writes measure.txt.
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)
HERE := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
include $(BEES_ROOT)/tools/silica.mk
NODES := a b
.PHONY: build run integrate record-golden clean measure
build:
	@for n in $(NODES); do ($(MAKE) -C "$(HERE)/nodes/$$n" build || $(MAKE) -C "$(HERE)/nodes/$$n" build) || exit 1; $(MAKE) -C "$(HERE)/nodes/$$n" build > /dev/null || exit 1; done

run: build
	@cd "$(HERE)" && "$(BEES_ROOT)/tools/run_pair.py" nodes/a/dangerous_a_echo big.a.sout "link closed" nodes/b/dangerous_b_big big.b.sout "killed)" 0.5 300 || echo "pair big: a run failed"; \
		sed -i '' -E -e 's/0x[0-9a-f]{6,}/0xADDR/g' big.a.sout big.b.sout; $(STRIP_ROOT_EXIT) big.a.sout big.b.sout; \
		grep '^time ' big.b.sout > big.times; sed -i '' -e '/^time /d' big.b.sout

integrate: run
	@cd "$(HERE)" && ok=0; ko=0; for side in a b; do \
		if [ ! -f "big.$$side.scout" ]; then echo "MISSING golden: [n1_frames] big.$$side.scout"; ko=$$((ko+1)); \
		elif diff -Bw -q "big.$$side.sout" "big.$$side.scout" > /dev/null; then ok=$$((ok+1)); \
		else echo "DIFF: [n1_frames] big.$$side"; diff -Bw "big.$$side.scout" "big.$$side.sout" || true; ko=$$((ko+1)); fi; \
	done; printf '%d %d\n' "$$ok" "$$ko" > .integrate_counts; echo "[n1_frames] $$ok passed, $$ko failed"; [ "$$ko" -eq 0 ]

record-golden: run
	@cd "$(HERE)" && cp big.a.sout big.a.scout && cp big.b.sout big.b.scout && echo "[n1_frames] goldens recorded"

# two runs: 64 KiB and 1 MiB only (dangerous_b_small), then all four (dangerous_b_big; b's last write fails and its link goes down)
measure: build
	@cd "$(HERE)" && "$(BEES_ROOT)/tools/run_demo.py" --time --cap 900 --a nodes/a/dangerous_a_echo measure_small.a.out "len 1048576" --b nodes/b/dangerous_b_small measure_small.b.out "answer len 1048576"; \
		"$(BEES_ROOT)/tools/run_demo.py" --time --cap 900 --a nodes/a/dangerous_a_echo measure_big.a.out "link closed" --b nodes/b/dangerous_b_big measure_big.b.out "killed)"; \
		{ for r in small big; do echo "== $$r"; grep '^time ' measure_$$r.b.out; for s in a b; do printf '%s: ' $$s; grep -E 'maximum resident set size|peak memory footprint|real' measure_$$r.$$s.out.rusage | tr -s ' ' | tr '\n' ';'; echo; done; done; } | tee measure.txt

clean:
	@for n in $(NODES); do $(MAKE) -C "$(HERE)/nodes/$$n" clean; done; cd "$(HERE)" && rm -f *.sout .integrate_counts big.times measure.*
