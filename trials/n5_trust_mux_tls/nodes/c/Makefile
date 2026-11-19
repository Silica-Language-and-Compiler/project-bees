# N5 over TLS, node c: node b, a client that offers sessions; one entry per scenario. Generated at parse time as in trials/n5_trust_mux (bees_trust_conf says tls, so the root
# units get the TLS link part); the roles are trials/n5_trust_mux's; the common client role is this trial's (N4's, with this trial's port).
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../../../..)
LEAF_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
ROLES := $(BEES_ROOT)/trials/n5_trust_mux/roles
N4ROLES := $(BEES_ROOT)/trials/n4_trust_tls/roles
TROLES := $(BEES_ROOT)/trials/n5_trust_mux_tls/roles
GEN := $(BEES_ROOT)/tools/bees_trust_gen.py
CONF := $(BEES_ROOT)/tools/bees_config_trust.py
PORTS := python3 "$(BEES_ROOT)/tools/trial_ports.py" port
_ := $(shell cd "$(LEAF_DIR)" && python3 "$(CONF)" conf -o lib bees.config && python3 "$(GEN)" mfa -o lib --config bees.config none.trust && \
	sed -e "s/127\.0\.0\.1:[0-9]*/127.0.0.1:$$($(PORTS) n5_trust_mux_tls 0)/" "$(TROLES)/client_common.role" > gen_common.role && \
	sed -e "s/127\.0\.0\.1:[0-9]*/127.0.0.1:$$($(PORTS) n5_trust_mux_tls 3)/" "$(TROLES)/client_common.role" > gen_common_e.role && \
	python3 "$(GEN)" edge dangerous_c_interleave dangerous_c_interleave.silica gen_common.role $(ROLES)/client_raw.role $(ROLES)/client_interleave.role && \
	python3 "$(GEN)" edge dangerous_c_deny dangerous_c_deny.silica gen_common.role $(ROLES)/client_raw.role $(ROLES)/client_deny.role && \
	python3 "$(GEN)" edge dangerous_c_protocol dangerous_c_protocol.silica gen_common.role $(ROLES)/client_raw.role $(ROLES)/client_protocol.role && \
	python3 "$(GEN)" edge dangerous_c_cancel dangerous_c_cancel.silica gen_common.role $(ROLES)/client_raw.role $(ROLES)/client_cancel.role && \
	python3 "$(GEN)" edge dangerous_c_b1server dangerous_c_b1server.silica gen_common_e.role $(ROLES)/client_raw.role $(ROLES)/client_b1server.role)
include $(BEES_ROOT)/tools/trial.mk

clean: clean-generated
.PHONY: clean-generated
GENERATED := $(wildcard $(LEAF_DIR)/dangerous_*.silica) $(wildcard $(LEAF_DIR)/gen_*.role) $(addprefix $(LEAF_DIR)/lib/,bees_trust_conf.silica bees_trust_conf.atoms bees_trust_mfa.silica bees_trust_slots.silica dangerous_bees_trust_mux.silica bees_trust_mux_frame.silica bees_trust_mux.atoms)
clean-generated:
	@$(RM) $(GENERATED)
