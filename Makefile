# Project BEES root Makefile. The shim is a Silica library; there is nothing to build at the root
# except the trial tree, which is how BEES is verified (roadmap §4.9, R0.1).
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
include $(BEES_ROOT)/tools/silica.mk

.PHONY: integrate record-golden build clean help native kit

integrate: check-compiler native
	@$(MAKE) -C trials integrate
	@$(MAKE) kit

# The conformance kit (contract/conformance) and the lowering-choices checker: no Silica involved.
kit:
	@python3 "$(BEES_ROOT)/tools/conformance.py" check-kit
	@python3 "$(BEES_ROOT)/tools/test_check_lowering_choices.py" 2>&1 | tail -3

record-golden: check-compiler
	@$(MAKE) -C trials record-golden

build: check-compiler native
	@$(MAKE) -C trials build

.PHONY: native
native:
	@$(MAKE) -C native

clean:
	@$(MAKE) -C trials clean
	@$(MAKE) -C native clean

help:
	@echo "make integrate      build, run and diff every trial leaf against its goldens"
	@echo "make kit            check the conformance kit's goldens and the lowering-choices checker"
	@echo "make record-golden  re-record every golden (after a deliberate change only)"
	@echo "make build | clean"
	@echo "compiler: $(SILICA_COMPILER)"
