# F1 (fuzzer) node ts: a TRUST server under test. Its bees.config (tools/bees_config_trust.py: bees_trust_conf), its MFA table
# (tools/bees_trust_gen.py mfa from demo.trust) and its entry's dangerous_ root unit (bees_trust_gen.py edge), all generated at
# parse time; then the generic leaf rules.
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../../../..)
LEAF_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
ROLES := $(BEES_ROOT)/trials/f1_fuzz_wire/roles
GEN := $(BEES_ROOT)/tools/bees_trust_gen.py
CONF := $(BEES_ROOT)/tools/bees_config_trust.py
_ := $(shell cd "$(LEAF_DIR)" && python3 "$(CONF)" conf -o lib bees.config 1>&2 && python3 "$(GEN)" mfa -o lib --config bees.config demo.trust 1>&2 && \
	python3 "$(GEN)" edge dangerous_ts dangerous_ts.silica $(ROLES)/fuzz_trust_server.role 1>&2)
include $(BEES_ROOT)/tools/trial.mk

clean: clean-generated
.PHONY: clean-generated
clean-generated:
	@cd "$(LEAF_DIR)" && rm -f dangerous_ts.silica lib/bees_trust_conf.silica lib/bees_trust_conf.atoms lib/bees_trust_mfa.silica
