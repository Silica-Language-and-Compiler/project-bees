# T0 (clock): what a TEMPUS node does with each reading of the system clock (development-plan/tempus-design.md sections 4
# and 10, ruling NQ-22 of 2026-11-20), in memory: no carrier, no actor, no clock. A trial cannot set the machine's clock,
# so the decision is the pure bees_tempus_node@clock_back and bees_tempus_node@clock_turn, and this trial gives them
# readings as numbers: the three choices of clock_back (follow, hold, stop), both sides of the stop limit, the recovery
# under hold, and the two choices of clock_fail (continue, pause). The node part's tn_clock prints the lines and does what
# these functions say; that part is not run here.
# lib/bees_tempus_node.silica is generated from src/tempus/bees_tempus_node.silica.in (tools/bees_tempus_gen.py unit).
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)
LEAF_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
GEN := $(BEES_ROOT)/tools/bees_tempus_gen.py
SRC_T := $(BEES_ROOT)/src/tempus
-include $(LEAF_DIR)/.gen.mk
$(LEAF_DIR)/.gen.mk: $(GEN) $(SRC_T)/bees_tempus_node.silica.in
	@cd "$(LEAF_DIR)" && python3 "$(GEN)" unit "$(SRC_T)/bees_tempus_node.silica.in" lib/bees_tempus_node.silica && \
	echo "# written by the rule of this file in the Makefile: the generated unit is current" > .gen.mk
include $(BEES_ROOT)/tools/trial.mk
clean: clean-generated
.PHONY: clean-generated
clean-generated:
	@cd "$(LEAF_DIR)" && rm -f lib/bees_tempus_node.silica .gen.mk
