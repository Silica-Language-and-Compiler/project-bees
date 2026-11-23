# The Python TEMPUS extension and example client. EXAMPLE ONLY, not for production: see README.md.
#
#   make test    every test in this directory:
#                test_bees_tempus_client.py  the codec, the frames and single connections, run twice: once over the
#                                            extension's modules (lib/bees_tempus_*.py with testing/bees_tempus_testing.py,
#                                            what the trials use) and once over the library package (lib/tempus_client
#                                            with its testing.py), chosen by BEES_TEMPUS_TEST_SUPPORT
#                test_bees_tempus_node.py    the node half (lib/bees_tempus_*.py)
#                test_tempus_gossip.py       the gossip part of the library package (lib/tempus_client/gossip.py)
#   make gossip  four instances of the driver (driver/tempus_peer.py) as one TEMPUS network on this machine
#                (../gossip/gossip_run.py run python)
# The node half's trial is trials/c7_tempus_node_python. Needs python3 with the `cryptography` package. Nothing is built.
HERE := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
BEES_ROOT := $(abspath $(HERE)/../..)

.PHONY: test gossip
test:
	@cd "$(BEES_ROOT)" && python3 "$(HERE)/test_bees_tempus_client.py" 2>&1 | tail -3
	@cd "$(BEES_ROOT)" && BEES_TEMPUS_TEST_SUPPORT=tempus_client.testing python3 "$(HERE)/test_bees_tempus_client.py" 2>&1 | tail -3
	@cd "$(BEES_ROOT)" && python3 "$(HERE)/test_bees_tempus_node.py" 2>&1 | tail -3
	@cd "$(BEES_ROOT)" && python3 "$(HERE)/test_tempus_gossip.py" 2>&1 | tail -3
gossip:
	@python3 "$(HERE)/../gossip/gossip_run.py" run python
