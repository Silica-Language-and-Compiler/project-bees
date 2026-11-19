# D3 (spikes/N0d-store-config.md): the example application examples/store_node, built and run as a trial. The example is a
# single compilation unit that reads its configuration through the (:store) carrier (D46) and starts a small node with it;
# its sources, its cases (cases.py) and its goldens live in the example's directory. Port: tools/trial_ports.py d3_store_node +0.
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)
STORE_LEAF := $(BEES_ROOT)/examples/store_node
_ := $(shell cd "$(STORE_LEAF)" && python3 "$(BEES_ROOT)/tools/bees_pack_gen.py" root dangerous_store_node.silica.in beam dangerous_store_node.silica)
include $(BEES_ROOT)/tools/bees_pack_trial.mk
