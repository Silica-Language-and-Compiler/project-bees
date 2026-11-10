# N2: the cookie worker (dangerous_beam_auth over native/src/silica_bees_beam.c, CommonCrypto). The cookie file is written here,
# mode 600, before the run (git keeps no permissions); tools/test_beam_dist.py compares the printed digests with erlang:md5.
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)
include $(BEES_ROOT)/tools/trial.mk
run: cookie
.PHONY: cookie
cookie:
	@cd "$(LEAF)" && printf 'n2cookie\n' > cookie.txt && chmod 600 cookie.txt
