# N5 over TLS, node s: node a, the multiplexing server over mutual TLS 1.3. Generated at parse time as in trials/n5_trust_mux (bees_trust_conf says tls, so the root
# units get the TLS link part); the roles are trials/n5_trust_mux's; the common client role is this trial's (N4's, with this trial's port).
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../../../..)
LEAF_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
ROLES := $(BEES_ROOT)/trials/n5_trust_mux/roles
N4ROLES := $(BEES_ROOT)/trials/n4_trust_tls/roles
TROLES := $(BEES_ROOT)/trials/n5_trust_mux_tls/roles
GEN := $(BEES_ROOT)/tools/bees_trust_gen.py
CONF := $(BEES_ROOT)/tools/bees_config_trust.py
PORTS := python3 "$(BEES_ROOT)/tools/trial_ports.py" port
_ := $(shell cd "$(LEAF_DIR)" && python3 "$(CONF)" conf -o lib bees.config && python3 "$(GEN)" mfa -o lib --config bees.config demo.trust && \
	python3 "$(GEN)" edge dangerous_s_main dangerous_s_main.silica $(ROLES)/server.role $(ROLES)/operator_none.role)
include $(BEES_ROOT)/tools/trial.mk

clean: clean-generated
.PHONY: clean-generated
GENERATED := $(wildcard $(LEAF_DIR)/dangerous_*.silica) $(wildcard $(LEAF_DIR)/gen_*.role) $(addprefix $(LEAF_DIR)/lib/,bees_trust_conf.silica bees_trust_conf.atoms bees_trust_mfa.silica bees_trust_slots.silica dangerous_bees_trust_mux.silica bees_trust_mux_frame.silica bees_trust_mux.atoms)
clean-generated:
	@$(RM) $(GENERATED)
