# N4.1 node m (a client whose pin file names the wrong certificate for node a): generated at parse time as for node c.
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../../../..)
LEAF_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
ROLES := $(BEES_ROOT)/trials/n4_trust_tls/roles
GEN := $(BEES_ROOT)/tools/bees_trust_gen.py
CONF := $(BEES_ROOT)/tools/bees_config_trust.py
_ := $(shell cd "$(LEAF_DIR)" && chmod 600 ../../certs/*-key.pem && python3 "$(CONF)" conf -o lib bees.config && python3 "$(GEN)" mfa -o lib --config bees.config none.trust && \
	python3 "$(GEN)" edge dangerous_m_pin dangerous_m_pin.silica $(ROLES)/client_common.role $(ROLES)/client_pin.role)
include $(BEES_ROOT)/tools/trial.mk

clean: clean-generated
.PHONY: clean-generated
clean-generated:
	@cd "$(LEAF_DIR)" && rm -f dangerous_m_pin.silica lib/bees_trust_conf.silica lib/bees_trust_conf.atoms lib/bees_trust_mfa.silica
