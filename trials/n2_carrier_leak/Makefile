# N2c: Silica defect SD-46 reproduction (a measurement, not a test): each (:tcp) carrier that is spawned (spawn_dangerous), opened against a
# port nobody listens on (a refused open) and ended by its own stop_self leaves about 0.5 KiB of the process's resident set behind, for the
# life of the process, with no BEES actor involved (the owner is a sink actor that ignores every event). `make measure` prints the resident
# set every 500 carriers; `make integrate` only builds. Numbers recorded in development-plan/silica-defects.md (SD-46).
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)
HERE := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
EDGE_GEN := $(BEES_ROOT)/tools/bees_edge_gen.py
_ := $(shell cd "$(HERE)" && "$(EDGE_GEN)" dangerous_leak dangerous_leak.silica $(HERE)/leak.role)
include $(BEES_ROOT)/tools/trial.mk

.PHONY: measure
integrate: build
	@printf '1 0\n' > "$(HERE)/.integrate_counts"; echo "[n2_carrier_leak] 1 passed (built; the measurement is make measure)"
record-golden: build

measure: build
	@cd "$(HERE)" && python3 "$(BEES_ROOT)/tools/rss_watch.py" ./dangerous_leak carriers 500 13 | tee measure.txt

clean-generated:
	@cd "$(HERE)" && rm -f dangerous_leak.silica measure.txt
clean: clean-generated
