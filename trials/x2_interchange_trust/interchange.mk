# X2: TRUST mode over mutual TLS 1.3 between TWO MACHINES: node here on this machine (the machine the driver runs on: the Mac) and
# node there on the remote machine of .bees_build_hosts (the Linux box). NOT a trial leaf: this directory has no Makefile, so
# `make integrate` and tools/run_all_trials.sh never run it (it needs both machines). Run it with
#
#     make interchange                       at the root (both interchange trials), or
#     make -f interchange.mk integrate       here; `record-golden` writes the goldens (only after reading the NAME.SIDE.sout files)
#
# tools/bees_interchange.py is the driver; without .bees_build_hosts it prints "interchange: skipped: no remote" and succeeds.
# Each of the two nodes is a server (a whitelist with the other node's certificate) AND a client (a pin of the other node's
# address to its certificate); no CA is configured (D43). certs/ is TEST ONLY, made once by tools/bees_test_certs.sh (the tooling
# of trials/n4_trust_tls; keys that belong to nobody): a.pem is node there, b.pem is node here, u.pem is in no whitelist.
# Scenarios (NAME.here.<this machine's platform id>.scout and NAME.there.<the remote's>.scout):
#   here_calls        node here calls node there directly over the network (there listens on every IPv4 interface): n4's
#                     scenario set, one TLS connection per request (hello and token_issue, the token fast path, a cast, a binary)
#   there_calls       node there calls node here: the remote machine cannot dial this one, so it dials 127.0.0.1:22901 on its own
#                     machine, the remote end of an ssh -R forward of the driver's session to node here's listener on 127.0.0.1
#   here_wrong_pin, there_wrong_pin     node p pins the server's address to another certificate: {error, server_not_pinned}; the
#                     server sees the client leave inside the handshake
#   here_unlisted, there_unlisted       node u presents u.pem, which the server's whitelist does not list: the handshake completes,
#                     the server audits whitelist_reject and closes; no request is admitted
# The TLS bytes of the there_* scenarios travel inside the ssh forward unchanged (TLS end to end between the two BEES nodes; ssh
# only carries the TCP stream). Ports: tools/trial_ports.py (x2_interchange_trust).
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)
HERE := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
TRIAL := $(notdir $(HERE))
include $(BEES_ROOT)/tools/silica.mk
DRIVER = SILICA_COMPILER="$(SILICA_COMPILER)" python3 "$(BEES_ROOT)/tools/bees_interchange.py" --only $(TRIAL)
.PHONY: integrate record-golden list clean
integrate:
	@$(DRIVER)
record-golden:
	@$(DRIVER) --record
list:
	@$(DRIVER) --list
clean:
	@for n in "$(HERE)"/nodes/*/; do $(MAKE) -C "$$n" clean; done; cd "$(HERE)" && rm -rf *.sout *.raw build cookie cookie_args
