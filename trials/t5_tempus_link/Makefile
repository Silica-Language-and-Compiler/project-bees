# T5: the TEMPUS link between two processes over real TLS on 127.0.0.1 (development-plan/tempus-design.md sections 4, 5,
# 17.6): the TLS link of tempus/1 (src/tempus/dangerous_bees_tempus_tls.silica), the connection actor's admission
# (dangerous_bees_tempus_conn.silica), the channel binding (the advert's pub must be the key of the peer's TLS certificate)
# and the tempus whitelist with the token also checked (rulings OQ-3, NQ-4). Three pairs, a listener and a dialer each
# (pairN.pair; the listener is the sentinel identity and its whitelist holds the bridge's certificate):
#   pair1  the dialer holds the node identity's certificate. Eight dials: admitted and a request answered; another peer's
#          advert under this certificate (binding refused); a tempus_bridge token without a whitelisted certificate; a token
#          under the old kid (the one key_rotated frame); an expired token; a proof signed with another key; and two where
#          the DIALER refuses the listener (its whitelist empty; its current kid another one)
#   pair2  the dialer holds the bridge's certificate: admitted by the whitelist entry and its tempus_bridge token; refused
#          with a tempus_edge token
#   pair3  the dialer's certificate has a P-256 key: the listener's link refuses it
# Each program's root unit is generated (tools/bees_tempus_gen.py) from the carrier edge, the TEMPUS link edge and its role
# files. lib/tempus_ids.silica holds the TEST-ONLY identities (tools/bees_tempus_ids.py; `build` fails when it is not what
# the tool writes); the certificates are those of trials/t5_tempus_tls/certs. Nonces are random and never printed.
# Post-processing (the only differences between runs): sout.sed removes the runtime's reports of actors that ended
# normally and makes the stage and peer of a closed_by_peer line `(any)` (the side that was refused learns of the close
# at whichever step it had reached); tools/bees_tempus_sort.py puts a listener's lines in the order of its connections
# (two connections are independent actors).
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)
LEAF_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
GEN := $(BEES_ROOT)/tools/bees_tempus_gen.py
# The generated root units are made by the rule of .gen.mk, an included makefile: when it is remade, make starts again and
# reads the directory afresh (make 3.81 lists a directory once, so units generated while the makefiles are read are not
# seen by the wildcards of tools/trial.mk in the same run: after `make clean` no entry was found).
-include $(LEAF_DIR)/.gen.mk
$(LEAF_DIR)/.gen.mk: $(wildcard $(LEAF_DIR)/*.role) $(GEN) $(BEES_ROOT)/src/tempus/bees_tempus_link.part $(BEES_ROOT)/src/shim/bees_tcp_edge.part
	@cd "$(LEAF_DIR)" && for n in 1 2 3; do \
	python3 "$(GEN)" edge dangerous_l$$n dangerous_l$$n.silica --use tempus_ids common.role l$$n.role listen.role && \
	python3 "$(GEN)" edge dangerous_d$$n dangerous_d$$n.silica --use tempus_ids common.role d$$n.role dial.role || exit 1; done && \
	echo "# written by the rule of this file in the Makefile: the generated units are current" > .gen.mk
include $(BEES_ROOT)/tools/trial.mk

.PHONY: natives fixtures sorted clean-generated
build: natives fixtures
natives:
	@out=$$($(MAKE) --no-print-directory -C "$(BEES_ROOT)/native" tempus tls 2>&1); rc=$$?; \
	[ -z "$$out" ] || printf '%s\n' "$$out" | grep -v '^ar \|^cc \|^mkdir ' ; \
	if [ "$$rc" != 0 ]; then echo "FAIL: [t5_tempus_link] needs the TEMPUS native edge and the TLS engine (make -C native tempus tls; OpenSSL 4.1.0 or later)"; exit 1; fi
fixtures:
	@python3 "$(BEES_ROOT)/tools/bees_tempus_certs.py" check > /dev/null && python3 "$(BEES_ROOT)/tools/bees_tempus_ids.py" check "$(LEAF_DIR)/lib/tempus_ids.silica" ../t5_tempus_tls/certs/ > /dev/null || { echo "FAIL: [t5_tempus_link] the certificates or lib/tempus_ids.silica are not what the tools write"; exit 1; }
sorted: run
	@cd "$(LEAF_DIR)" && python3 "$(BEES_ROOT)/tools/bees_tempus_sort.py" dangerous_l1.sout dangerous_l2.sout dangerous_l3.sout
integrate: sorted
record-golden: sorted
clean: clean-generated
clean-generated:
	@cd "$(LEAF_DIR)" && rm -f dangerous_l[123].silica dangerous_d[123].silica .gen.mk
