# N3 node s: its bees.config (read by tools/bees_config_trust.py when the program is built: bees_trust_conf), its MFA table
# (tools/bees_trust_gen.py mfa from demo.trust: bees_trust_mfa) and its entries' dangerous_ root units (bees_trust_gen.py edge), all
# generated at parse time; then the generic leaf rules.
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../../../..)
LEAF_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
ROLES := $(BEES_ROOT)/trials/n3_trust/roles
GEN := $(BEES_ROOT)/tools/bees_trust_gen.py
CONF := $(BEES_ROOT)/tools/bees_config_trust.py
_ := $(shell cd "$(LEAF_DIR)" && $(PRE_GEN) python3 "$(CONF)" conf -o lib bees.config && python3 "$(GEN)" mfa -o lib --config bees.config demo.trust && \
	python3 "$(GEN)" edge dangerous_s_main dangerous_s_main.silica $(ROLES)/server.role $(ROLES)/operator_none.role && \
	python3 "$(GEN)" edge dangerous_s_negative dangerous_s_negative.silica $(ROLES)/server.role $(ROLES)/operator_reset.role)
include $(BEES_ROOT)/tools/trial.mk

clean: clean-generated
.PHONY: clean-generated
clean-generated:
	@cd "$(LEAF_DIR)" && rm -f dangerous_s_main.silica dangerous_s_negative.silica lib/bees_trust_conf.silica lib/bees_trust_conf.atoms lib/bees_trust_mfa.silica
