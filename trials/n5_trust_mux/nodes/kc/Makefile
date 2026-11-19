# N5 node kc: the compat client: N3's node b and N3's roles, with trust.session limits 1 and 1. Its bees.config (tools/bees_config_trust.py: bees_trust_conf), its MFA table and, when the config
# multiplexes, its session units (tools/bees_trust_gen.py mfa) and its entries' dangerous_ root units (bees_trust_gen.py edge) are
# generated at parse time; then the generic leaf rules.
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../../../..)
LEAF_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
ROLES := $(BEES_ROOT)/trials/n5_trust_mux/roles
N3ROLES := $(BEES_ROOT)/trials/n3_trust/roles
GEN := $(BEES_ROOT)/tools/bees_trust_gen.py
CONF := $(BEES_ROOT)/tools/bees_config_trust.py
PORTS := python3 "$(BEES_ROOT)/tools/trial_ports.py" port
_ := $(shell cd "$(LEAF_DIR)" && python3 "$(CONF)" conf -o lib bees.config && python3 "$(GEN)" mfa -o lib --config bees.config none.trust && \
	sed -e "s/127\.0\.0\.1:[0-9]*/127.0.0.1:$$($(PORTS) n5_trust_mux 2)/" "$(N3ROLES)/client_common.role" > gen_common.role && \
	python3 "$(GEN)" edge dangerous_kc_scenario dangerous_kc_scenario.silica gen_common.role $(N3ROLES)/client_scenario.role && \
	python3 "$(GEN)" edge dangerous_kc_negative dangerous_kc_negative.silica gen_common.role $(N3ROLES)/client_negative.role)
include $(BEES_ROOT)/tools/trial.mk

clean: clean-generated
.PHONY: clean-generated
GENERATED := $(wildcard $(LEAF_DIR)/dangerous_*.silica) $(wildcard $(LEAF_DIR)/gen_*.role) $(addprefix $(LEAF_DIR)/lib/,bees_trust_conf.silica bees_trust_conf.atoms bees_trust_mfa.silica bees_trust_slots.silica dangerous_bees_trust_mux.silica bees_trust_mux_frame.silica bees_trust_mux.atoms)
clean-generated:
	@$(RM) $(GENERATED)
