# examples/store_node: an application that reads its configuration through the (:store) carrier and starts a node with it
# (development-plan/spikes/N0d-store-config.md). One compilation unit: silica.config lists this root, BEES's units and the
# language's (through the links in lib/), and the compiler runs once.
#
#   make pack     bees.config -> node.sildat (tools/bees_pack.py; the capacity is the literal of the root's declaration)
#   make build    one compiler run, then the link
#   make start    pack, build and run the node here (it listens on the configured address until told `exit`)
#   make integrate / record-golden / clean    as in a trial leaf (tools/bees_pack_trial.mk, cases.py); trials/d3_store_node
#                 runs them from `make integrate`
#
# The root dangerous_store_node.silica is written from dangerous_store_node.silica.in when this file is read
# (tools/bees_pack_gen.py root spells the configuration type).
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)
EXAMPLE_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
_ := $(shell cd "$(EXAMPLE_DIR)" && python3 "$(BEES_ROOT)/tools/bees_pack_gen.py" root dangerous_store_node.silica.in beam dangerous_store_node.silica)
include $(BEES_ROOT)/tools/bees_pack_trial.mk

.PHONY: pack start
pack:
	@cd "$(EXAMPLE_DIR)" && python3 "$(BEES_ROOT)/tools/bees_pack.py" pack --config bees.config --capacity 65536 -o node.sildat manifest/node.wire

start: pack build
	@cd "$(EXAMPLE_DIR)" && ./dangerous_store_node
