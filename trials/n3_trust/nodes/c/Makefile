# N3 node c: its bees.config (read by tools/bees_config_trust.py when the program is built: bees_trust_conf), its MFA table
# (tools/bees_trust_gen.py mfa from none.trust: bees_trust_mfa) and its entries' dangerous_ root units (bees_trust_gen.py edge), all
# generated at parse time; then the generic leaf rules.
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../../../..)
LEAF_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
ROLES := $(BEES_ROOT)/trials/n3_trust/roles
GEN := $(BEES_ROOT)/tools/bees_trust_gen.py
CONF := $(BEES_ROOT)/tools/bees_config_trust.py
_ := $(shell cd "$(LEAF_DIR)" && $(PRE_GEN) python3 "$(CONF)" conf -o lib bees.config && python3 "$(GEN)" mfa -o lib none.trust && \
	python3 "$(GEN)" edge dangerous_c_scenario dangerous_c_scenario.silica $(ROLES)/client_common.role $(ROLES)/client_scenario.role && \
	python3 "$(GEN)" edge dangerous_c_negative dangerous_c_negative.silica $(ROLES)/client_common.role $(ROLES)/client_negative.role && \
	python3 "$(GEN)" edge dangerous_c_kill dangerous_c_kill.silica $(ROLES)/client_common.role $(ROLES)/client_kill.role && \
	python3 "$(GEN)" edge dangerous_c_rate dangerous_c_rate.silica $(ROLES)/client_common.role $(ROLES)/client_rate.role)
include $(BEES_ROOT)/tools/trial.mk

clean: clean-generated
.PHONY: clean-generated
clean-generated:
	@cd "$(LEAF_DIR)" && rm -f dangerous_c_scenario.silica dangerous_c_negative.silica dangerous_c_kill.silica dangerous_c_rate.silica lib/bees_trust_conf.silica lib/bees_trust_conf.atoms lib/bees_trust_mfa.silica
