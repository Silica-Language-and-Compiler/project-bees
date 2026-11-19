# N5 node c: node b, a client that offers sessions; one entry per scenario. Its bees.config (tools/bees_config_trust.py: bees_trust_conf), its MFA table and, when the config
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
	sed -e "s/127\.0\.0\.1:[0-9]*/127.0.0.1:$$($(PORTS) n5_trust_mux 5)/" "$(ROLES)/client_common.role" > gen_common_w.role && \
	sed -e "s/127\.0\.0\.1:[0-9]*/127.0.0.1:$$($(PORTS) n5_trust_mux 3)/" "$(ROLES)/client_common.role" > gen_common_e.role && \
	python3 "$(GEN)" edge dangerous_c_interleave dangerous_c_interleave.silica $(ROLES)/client_common.role $(ROLES)/client_raw.role $(ROLES)/client_interleave.role && \
	python3 "$(GEN)" edge dangerous_c_deny dangerous_c_deny.silica $(ROLES)/client_common.role $(ROLES)/client_raw.role $(ROLES)/client_deny.role && \
	python3 "$(GEN)" edge dangerous_c_protocol dangerous_c_protocol.silica $(ROLES)/client_common.role $(ROLES)/client_raw.role $(ROLES)/client_protocol.role && \
	python3 "$(GEN)" edge dangerous_c_shutdown dangerous_c_shutdown.silica $(ROLES)/client_common.role $(ROLES)/client_raw.role $(ROLES)/client_shutdown.role && \
	python3 "$(GEN)" edge dangerous_c_cancel dangerous_c_cancel.silica $(ROLES)/client_common.role $(ROLES)/client_raw.role $(ROLES)/client_cancel.role && \
	python3 "$(GEN)" edge dangerous_c_pause dangerous_c_pause.silica $(ROLES)/client_common.role $(ROLES)/client_raw.role $(ROLES)/client_pause.role && \
	python3 "$(GEN)" edge dangerous_c_window dangerous_c_window.silica gen_common_w.role $(ROLES)/client_raw.role $(ROLES)/client_window.role && \
	python3 "$(GEN)" edge dangerous_c_b1server dangerous_c_b1server.silica gen_common_e.role $(ROLES)/client_raw.role $(ROLES)/client_b1server.role && \
	sed -e "s/127\.0\.0\.1:[0-9]*/127.0.0.1:$$($(PORTS) n5_trust_mux 0)/" "$(ROLES)/client_common.role" > gen_common_h.role && \
	python3 "$(GEN)" edge dangerous_c_hostile dangerous_c_hostile.silica gen_common_h.role $(ROLES)/client_hostile.role && \
	python3 "$(GEN)" edge dangerous_c_bigprobe dangerous_c_bigprobe.silica $(ROLES)/client_common.role $(ROLES)/client_raw.role $(ROLES)/client_bigprobe.role)
include $(BEES_ROOT)/tools/trial.mk

clean: clean-generated
.PHONY: clean-generated
GENERATED := $(wildcard $(LEAF_DIR)/dangerous_*.silica) $(wildcard $(LEAF_DIR)/gen_*.role) $(addprefix $(LEAF_DIR)/lib/,bees_trust_conf.silica bees_trust_conf.atoms bees_trust_mfa.silica bees_trust_slots.silica dangerous_bees_trust_mux.silica bees_trust_mux_frame.silica bees_trust_mux.atoms)
clean-generated:
	@$(RM) $(GENERATED)
