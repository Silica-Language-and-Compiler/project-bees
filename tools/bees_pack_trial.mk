# The leaf Makefile of a configuration-store trial (trials/d1_store_layout, d2_store_config, d3_store_node; spikes/N0d-store-config.md).
#
#   BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)
#   include $(BEES_ROOT)/tools/bees_pack_trial.mk
#
# The leaf (or STORE_LEAF, when the programs live elsewhere: trials/d3_store_node builds examples/store_node) holds its
# programs, lib/ (links to the units), build.mk (the two lines of an ordinary leaf: tools/trial.mk does the build) and cases.py
# (tools/bees_pack_trial.py: one program is run on several prepared backings, each in its own directory). Targets as in
# tools/trial.mk: build, run, integrate, record-golden, clean. The store carrier's wrappers are built on request
# (`make -C native store`).
THIS_LEAF := $(patsubst %/,%,$(dir $(abspath $(firstword $(MAKEFILE_LIST)))))
STORE_LEAF ?= $(THIS_LEAF)
include $(BEES_ROOT)/tools/silica.mk
STORE_DRIVER := python3 "$(BEES_ROOT)/tools/bees_pack_trial.py"

.DEFAULT_GOAL := build
.PHONY: build run integrate record-golden clean

build:
	@$(MAKE) --no-print-directory -C "$(BEES_ROOT)/native" store
	@$(MAKE) --no-print-directory -C "$(STORE_LEAF)" -f build.mk build

run: build
	@$(STORE_DRIVER) run "$(STORE_LEAF)"

integrate: run
	@$(STORE_DRIVER) compare "$(STORE_LEAF)"; rc=$$?; \
	if [ "$(STORE_LEAF)" != "$(THIS_LEAF)" ] && [ -f "$(STORE_LEAF)/.integrate_counts" ]; then cp "$(STORE_LEAF)/.integrate_counts" "$(THIS_LEAF)/.integrate_counts"; fi; exit $$rc

record-golden: run
	@$(STORE_DRIVER) record "$(STORE_LEAF)"

clean:
	@$(MAKE) --no-print-directory -C "$(STORE_LEAF)" -f build.mk clean; rm -rf "$(STORE_LEAF)/.run" "$(STORE_LEAF)"/*.sout "$(STORE_LEAF)/.integrate_counts" "$(THIS_LEAF)/.integrate_counts"
