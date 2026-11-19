# N5 node rc: the soak's client (make measure): CALLS calls, one outstanding (seq), 4 (win4) or 8 (win), to the session server r or to the server without sessions e (base). Its bees.config (tools/bees_config_trust.py: bees_trust_conf), its MFA table and, when the config
# multiplexes, its session units (tools/bees_trust_gen.py mfa) and its entries' dangerous_ root units (bees_trust_gen.py edge) are
# generated at parse time; then the generic leaf rules.
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../../../..)
LEAF_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
ROLES := $(BEES_ROOT)/trials/n5_trust_mux/roles
N3ROLES := $(BEES_ROOT)/trials/n3_trust/roles
GEN := $(BEES_ROOT)/tools/bees_trust_gen.py
CONF := $(BEES_ROOT)/tools/bees_config_trust.py
PORTS := python3 "$(BEES_ROOT)/tools/trial_ports.py" port
# CALLS: the number of calls (make measure sets it); the generated role files are the committed one with the count, the window
# and the server's address changed
CALLS ?= 2000
rate_role = sed -e 's/fn total() -> int64 { 2000 }/fn total() -> int64 { $(CALLS) }/' -e 's/fn window() -> int64 { 1 }/fn window() -> int64 { $(1) }/' "$(ROLES)/client_rate.role" > $(2)
common_role = sed -e "s/127\.0\.0\.1:[0-9]*/127.0.0.1:$$($(PORTS) n5_trust_mux $(1))/" "$(ROLES)/client_common.role" > $(2)
_ := $(shell cd "$(LEAF_DIR)" && python3 "$(CONF)" conf -o lib bees.config && python3 "$(GEN)" mfa -o lib --config bees.config none.trust && \
	$(call rate_role,1,gen_rate_seq.role) && $(call rate_role,8,gen_rate_win.role) && $(call rate_role,4,gen_rate_win4.role) && $(call common_role,7,gen_common_r.role) && $(call common_role,3,gen_common_e.role) && \
	python3 "$(GEN)" edge dangerous_rc_seq dangerous_rc_seq.silica gen_common_r.role gen_rate_seq.role && \
	python3 "$(GEN)" edge dangerous_rc_win dangerous_rc_win.silica gen_common_r.role gen_rate_win.role && \
	python3 "$(GEN)" edge dangerous_rc_win4 dangerous_rc_win4.silica gen_common_r.role gen_rate_win4.role && \
	python3 "$(GEN)" edge dangerous_rc_base_seq dangerous_rc_base_seq.silica gen_common_e.role gen_rate_seq.role && \
	python3 "$(GEN)" edge dangerous_rc_base_win dangerous_rc_base_win.silica gen_common_e.role gen_rate_win.role)
include $(BEES_ROOT)/tools/trial.mk

clean: clean-generated
.PHONY: clean-generated
GENERATED := $(wildcard $(LEAF_DIR)/dangerous_*.silica) $(wildcard $(LEAF_DIR)/gen_*.role) $(addprefix $(LEAF_DIR)/lib/,bees_trust_conf.silica bees_trust_conf.atoms bees_trust_mfa.silica bees_trust_slots.silica dangerous_bees_trust_mux.silica bees_trust_mux_frame.silica bees_trust_mux.atoms)
clean-generated:
	@$(RM) $(GENERATED)
