# The Python TEMPUS extension. A usable example, to be used carefully: see README.md.
#
#   make test    every test in this directory:
#                test_bees_tempus_client.py  the codec, the frames and single connections
#                test_bees_tempus_node.py    the node: stores, clock, admission, configuration, replies, nodes in one process
#   make gossip  four instances of the driver (driver/tempus_peer.py) as one TEMPUS network on this machine
#                (../gossip/gossip_run.py run python)
# The extension's trial is trials/c7_tempus_node_python. Needs python3 with the `cryptography` package. Nothing is built.
HERE := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
BEES_ROOT := $(abspath $(HERE)/../..)

.PHONY: test gossip
test:
	@cd "$(BEES_ROOT)" && python3 "$(HERE)/test_bees_tempus_client.py" 2>&1 | tail -3
	@cd "$(BEES_ROOT)" && python3 "$(HERE)/test_bees_tempus_node.py" 2>&1 | tail -3
gossip:
	@python3 "$(HERE)/../gossip/gossip_run.py" run python
