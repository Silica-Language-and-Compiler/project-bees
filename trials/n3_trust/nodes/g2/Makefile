# N3 node g2: its bees.config (read by tools/bees_config_trust.py when the program is built: bees_trust_conf), its MFA table
# (tools/bees_trust_gen.py mfa from demo.trust: bees_trust_mfa) and its entries' dangerous_ root units (bees_trust_gen.py edge), all
# generated at parse time; then the generic leaf rules.
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../../../..)
LEAF_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
# the whitelist file of this trial exists and is made unreadable (mode 000) before bees.config is read
PRE_GEN := rm -f unreadable_whitelist.config && cp ../s/trust_whitelist.config unreadable_whitelist.config && chmod 000 unreadable_whitelist.config &&
ROLES := $(BEES_ROOT)/trials/n3_trust/roles
GEN := $(BEES_ROOT)/tools/bees_trust_gen.py
CONF := $(BEES_ROOT)/tools/bees_config_trust.py
_ := $(shell cd "$(LEAF_DIR)" && $(PRE_GEN) python3 "$(CONF)" conf -o lib bees.config && python3 "$(GEN)" mfa -o lib demo.trust && \
	python3 "$(GEN)" edge dangerous_g_boot dangerous_g_boot.silica $(ROLES)/server.role $(ROLES)/operator_none.role)
include $(BEES_ROOT)/tools/trial.mk

clean: clean-generated
.PHONY: clean-generated
clean-generated:
	@cd "$(LEAF_DIR)" && rm -f unreadable_whitelist.config dangerous_g_boot.silica lib/bees_trust_conf.silica lib/bees_trust_conf.atoms lib/bees_trust_mfa.silica
