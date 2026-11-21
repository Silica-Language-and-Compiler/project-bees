# The Python example TEMPUS client. EXAMPLE ONLY, not for production: see README.md.
#
#   make test    the tests of the library and of what the trials use (test_bees_tempus_client.py, test_tempus_gossip.py)
#   make gossip  four instances of the driver (driver/tempus_peer.py) as one TEMPUS network on this machine
#                (../gossip/gossip_run.py run python)
# Needs python3 with the `cryptography` package. Nothing is built.
HERE := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
BEES_ROOT := $(abspath $(HERE)/../..)

.PHONY: test gossip
test:
	@cd "$(BEES_ROOT)" && python3 "$(HERE)/test_bees_tempus_client.py" 2>&1 | tail -3
	@cd "$(BEES_ROOT)" && python3 "$(HERE)/test_tempus_gossip.py" 2>&1 | tail -3
gossip:
	@python3 "$(HERE)/../gossip/gossip_run.py" run python
