# C7: the gossip examples of the example TEMPUS clients (example_tempus_clients/gossip), built and run as a trial.
# Eight networks, one after the other, each on this machine (127.0.0.1): four instances of the Python driver, four of
# the Kotlin driver, four of the Swift driver, four of the Silica driver, four of the C# driver, four of the Rust driver
# (one sentinel and three edges each), a mixed network of a Silica sentinel with one edge of each language (Silica,
# Python, Kotlin, Swift, C#, Rust), and that network without the Silica driver, kept under its older name `trio` (a
# Swift sentinel with one edge each of Python, Kotlin, Swift, C# and Rust). In every network each edge is given the
# sentinel's address only; the check says whether every instance learned of every edge, whether every edge learned of
# the sentinel, whether every instance merged a shuffle it started, and whether none failed.
# The drivers, their libraries, the runner (gossip_run.py) and the goldens (NAME.check) live in example_tempus_clients;
# example_tempus_clients/gossip/README.md says what the check shows and what it does not.
# Recorded on the Mac: all eight.
# Ports: tools/trial_ports.py c7_tempus_gossip +0 to +6. The trial needs every driver's toolchain (python3 with the
# cryptography package, kotlinc and a JDK 27, Swift, the Silica compiler, the .NET SDK 11, cargo and rustc, OpenSSL
# 4.1.0 or later). Without one of them the leaf FAILS and says which; it never skips.
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)
THIS_LEAF := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
GOSSIP := $(BEES_ROOT)/example_tempus_clients/gossip

.DEFAULT_GOAL := build
.PHONY: build run integrate record-golden clean

build run record-golden:
	@$(MAKE) --no-print-directory -C "$(GOSSIP)" $@

integrate:
	@rm -f "$(GOSSIP)/.integrate_counts"; $(MAKE) --no-print-directory -C "$(GOSSIP)" integrate; rc=$$?; \
	if [ -f "$(GOSSIP)/.integrate_counts" ]; then cp "$(GOSSIP)/.integrate_counts" "$(THIS_LEAF)/.integrate_counts"; fi; exit $$rc

clean:
	@$(MAKE) --no-print-directory -C "$(GOSSIP)" clean
