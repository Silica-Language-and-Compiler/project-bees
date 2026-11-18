# x2_interchange_trust node u (a TRUST client with a certificate no whitelist lists (u.pem) and the RIGHT pins; runs on either machine). Built and run by tools/bees_interchange.py on the machine that runs the node; never
# by `make integrate` (the trial has no leaf Makefile). Written at parse time: bees.config and trust_servers.config from their .in files, the common client role of
# trials/n4_trust_tls with the address of the server THIS machine calls (X_SERVER) in place of n4's, then as for n4's nodes:
# bees_trust_conf (tools/bees_config_trust.py), the MFA table and the entries' root units (tools/bees_trust_gen.py).
# @THERE_IP@ / X_THERE_IP is the remote machine's IPv4 address (TRUST dials IPv4 literals), from .bees_build_hosts through the
# driver, so no tracked file names a machine.
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../../../..)
LEAF_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
N4ROLES := $(BEES_ROOT)/trials/n4_trust_tls/roles
XROLES := $(BEES_ROOT)/trials/x2_interchange_trust/roles
GEN := $(BEES_ROOT)/tools/bees_trust_gen.py
CONF := $(BEES_ROOT)/tools/bees_config_trust.py
X_THERE_IP ?= 192.0.2.1
# the address n4's common client role names, from the one table of ports (replaced by X_SERVER)
N4_PORT := $(shell python3 "$(BEES_ROOT)/tools/trial_ports.py" port n4_trust_tls 0)
X_SERVER ?= 192.0.2.1:22900
# this machine as the remote dials it, and what node here binds: 127.0.0.1 (an ssh -R forward, the default), or this machine's
# reachable IPv4 address and 0.0.0.0 (the driver's --here-address: the remote dials this machine directly)
X_HERE_HOST ?= 127.0.0.1
X_HERE_LISTEN ?= 127.0.0.1
_ := $(shell cd "$(LEAF_DIR)" && chmod 600 ../../certs/*-key.pem && \
	sed -e "s/@HERE_LISTEN@/$(X_HERE_LISTEN)/g" bees.config.in > bees.config && \
	sed -e "s/@THERE_IP@/$(X_THERE_IP)/g" -e "s/@HERE_HOST@/$(X_HERE_HOST)/g" trust_servers.config.in > trust_servers.config && \
	sed "s/127\.0\.0\.1:$(N4_PORT)/$(X_SERVER)/" $(N4ROLES)/client_common.role > client_common.gen.role && grep -q '"$(X_SERVER)"' client_common.gen.role && \
	python3 "$(CONF)" conf -o lib bees.config && python3 "$(GEN)" mfa -o lib --config bees.config none.trust && \
	python3 "$(GEN)" edge dangerous_u_unlisted dangerous_u_unlisted.silica client_common.gen.role $(BEES_ROOT)/trials/x2_interchange_trust/roles/client_unlisted.role)
include $(BEES_ROOT)/tools/trial.mk

clean: clean-generated
.PHONY: clean-generated
clean-generated:
	@cd "$(LEAF_DIR)" && rm -f dangerous_*.silica client_common.gen.role bees.config trust_servers.config lib/bees_trust_conf.silica lib/bees_trust_conf.atoms lib/bees_trust_mfa.silica .interchange_stamp
