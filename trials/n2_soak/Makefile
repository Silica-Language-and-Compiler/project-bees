# N2c soak (a measurement, not a test): a node program that lives while a peer connects to it, or is dialed by it, over and over; tools/soak.py
# records the node's resident set along the way. Four leaves under nodes/, one peer line each:
#   m3l  the M3 node listens (peer c, one peer line: it claims its slot at accept); tools/soak.py connects and closes, CYCLES times
#   m3d  the M3 node dials (redial 10 ms); tools/soak.py accepts and closes, CYCLES times
#   bl, bd  the same for the BEAM-mode node (cookie, no EPMD)
# `make integrate` only builds (the numbers vary and the run takes minutes); `make measure [CYCLES=1000]` runs the six measurements into
# measure.txt (recorded in development-plan/spikes/N2b-multi-link.md).
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)
HERE := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
include $(BEES_ROOT)/tools/silica.mk
NODES := m3l m3d bl bd
CYCLES ?= 1000
.PHONY: build integrate record-golden measure clean cookies
build: cookies
	@for n in $(NODES); do ($(MAKE) -C "$(HERE)/nodes/$$n" build || $(MAKE) -C "$(HERE)/nodes/$$n" build) || exit 1; $(MAKE) -C "$(HERE)/nodes/$$n" build > /dev/null || exit 1; done

integrate: build
	@cd "$(HERE)" && printf '4 0\n' > .integrate_counts; echo "[n2_soak] 4 passed (built; the measurement is make measure)"

record-golden: build

measure: build
	@cd "$(HERE)" && { \
	for spec in "m3l connect" "m3l connect --overlap" "m3d accept" "bl connect" "bl connect --overlap" "bd accept"; do set -- $$spec; n=$$1; m=$$2; ov=$$3; \
		case $$n in m3l) p=47481;; m3d) p=47482;; bl) p=47483;; bd) p=47484;; esac; \
		echo "== $$n $$m $$ov, $(CYCLES) cycles: cycle rss_kib"; python3 "$(BEES_ROOT)/tools/soak.py" $$m "nodes/$$n/dangerous_$$n" $$p $(CYCLES) $$ov; \
	done; } | tee measure.txt

clean:
	@for n in $(NODES); do $(MAKE) -C "$(HERE)/nodes/$$n" clean; done; cd "$(HERE)" && rm -f measure.txt .integrate_counts nodes/*/*.soak.rusage

cookies:
	@cd "$(HERE)" && printf 'n2-soak-cookie\n' > cookie && chmod 600 cookie
