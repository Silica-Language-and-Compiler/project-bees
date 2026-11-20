# examples/trust_mesh: how one node of the mesh is built (included by nodes/n1 ... nodes/n5, which hold only their
# configuration). Written when this file is read, before anything is compiled:
#   lib/bees_trust_conf.silica     the node's bees.config with its whitelist and pin file (tools/bees_config_trust.py)
#   lib/bees_trust_mfa.silica      the functions TRUST peers may name, from ../../roles/mesh.trust, and the session units,
#                                  because bees.config writes trust.session (tools/bees_trust_gen.py mfa)
#   dangerous_mesh_node.silica     the program: BEES's carrier, TLS link, TRUST node and session parts, then
#                                  ../../roles/mesh.role (tools/bees_trust_gen.py edge)
# then the ordinary leaf rules (tools/trial.mk: one compiler run, assemble, link with the installed OpenSSL).
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../../..)
LEAF_DIR := $(patsubst %/,%,$(dir $(abspath $(firstword $(MAKEFILE_LIST)))))
ROLES := $(BEES_ROOT)/examples/trust_mesh/roles
GEN := $(BEES_ROOT)/tools/bees_trust_gen.py
CONF := $(BEES_ROOT)/tools/bees_config_trust.py
_ := $(shell cd "$(LEAF_DIR)" && chmod 600 ../../certs/*-key.pem && python3 "$(CONF)" conf -o lib bees.config && \
	python3 "$(GEN)" mfa -o lib --config bees.config "$(ROLES)/mesh.trust" && \
	python3 "$(GEN)" edge dangerous_mesh_node dangerous_mesh_node.silica "$(ROLES)/mesh.role")
include $(BEES_ROOT)/tools/trial.mk

clean: clean-generated
.PHONY: clean-generated
GENERATED := $(LEAF_DIR)/dangerous_mesh_node.silica $(addprefix $(LEAF_DIR)/lib/,bees_trust_conf.silica bees_trust_conf.atoms bees_trust_mfa.silica bees_trust_slots.silica dangerous_bees_trust_mux.silica bees_trust_mux_frame.silica bees_trust_mux.atoms)
clean-generated:
	@$(RM) $(GENERATED)
