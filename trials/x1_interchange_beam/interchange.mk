# X1: BEAM mode between TWO MACHINES. A BEES node on this machine ("here", the machine the driver runs on: the Mac) and a BEES
# node, or a stock erl, on the remote machine of .bees_build_hosts ("there": the Linux box). NOT a trial leaf: this directory has no
# Makefile, so `make integrate` and tools/run_all_trials.sh never run it (it needs both machines). Run it with
#
#     make interchange                       at the root (both interchange trials), or
#     make -f interchange.mk integrate       here; `record-golden` writes the goldens (only after reading the NAME.SIDE.sout files)
#
# tools/bees_interchange.py is the driver (its header says how the machines are reached); without .bees_build_hosts it prints
# "interchange: skipped: no remote" and succeeds. The cookie is a random one per run, written mode 600 on both machines and
# removed afterwards. Scenarios (NAME.here.<this machine's platform id>.scout and NAME.there.<the remote's>.scout):
#   here_dials         node hd here dials node tl there BY NAME, directly over the network (tl listens on every IPv4 interface):
#                      the name lookup, the cookie handshake, hd's request (21) answered by tl (42), tl's request (34) answered by
#                      hd (68), all over the one link
#   there_dials        node td there dials node hl here: the remote machine cannot dial this one (address translation), so td
#                      dials 127.0.0.1:22801 on its own machine, the remote end of an ssh -R forward of the driver's session to
#                      hl's listener on 127.0.0.1:22801 here; the same exchange
#   erl_there_dials    trials/n2_live's stock_dials with the stock erl node THERE and BEES (node el) HERE: ping, a registered
#                      send, a BEES pid handed out and used, link, unlink, monitor, 26 s of ticks, BEES killed: nodedown
#   erl_there_listens  n2_live's bees_dials with the stock node THERE and BEES (node ed) HERE: BEES asks the stock node's EPMD,
#                      dials it, casts to its registered process; the stock node answers over the same link
#   erl_here_dials, erl_here_listens   the same two with the stock erl node HERE and BEES THERE
# The four erl scenarios use ssh forwards only (-L and -R, tools/bees_interchange.py lists them per scenario): the stock node and
# its private EPMD stay on 127.0.0.1 of their machine, because a stock node is a remote shell for whoever passes the cookie
# handshake. Ports: tools/trial_ports.py (x1_interchange_beam).
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
