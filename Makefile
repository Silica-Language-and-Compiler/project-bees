# Project BEES root Makefile. The shim is a Silica library; there is nothing to build at the root
# except the trial tree, which is how BEES is verified (roadmap §4.9, R0.1).
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
include $(BEES_ROOT)/tools/silica.mk

.PHONY: integrate integrate-parallel record-golden build clean help native kit interchange

integrate: check-compiler native
	@$(MAKE) -C trials integrate
	@$(MAKE) kit

# The same trials in parallel on this machine (tools/README.md): `make integrate` stays the serial path.
integrate-parallel: check-compiler
	@"$(BEES_ROOT)/tools/run_all_trials.sh" --local-only

# The two-machine interchange trials (trials/x1_interchange_beam, trials/x2_interchange_trust; tools/README.md): this machine and
# the remote machine of .bees_build_hosts. Not part of `integrate`; without the hosts file it prints "skipped: no remote".
interchange:
	@SILICA_COMPILER="$(SILICA_COMPILER)" python3 "$(BEES_ROOT)/tools/bees_interchange.py"

# The conformance kit (contract/conformance), the lowering-choices checker and the wire generator's tests: no
# Silica is compiled (the wire test reads a recorded golden).
kit:
	@python3 "$(BEES_ROOT)/tools/conformance.py" check-kit
	@python3 "$(BEES_ROOT)/tools/test_check_lowering_choices.py" 2>&1 | tail -3
	@python3 "$(BEES_ROOT)/tools/test_bees_wire_gen.py" 2>&1 | tail -3
	@python3 "$(BEES_ROOT)/tools/test_bees_dist.py" 2>&1 | tail -3
	@python3 "$(BEES_ROOT)/tools/test_bees_conf.py" 2>&1 | tail -3

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
	@echo "make integrate-parallel   the same, in parallel (tools/run_all_trials.sh -j N; remote machines: tools/README.md)"
	@echo "make interchange    the two-machine trials (this machine and the remote of .bees_build_hosts; tools/README.md)"
	@echo "make kit            check the conformance kit's goldens and the lowering-choices checker"
	@echo "make record-golden  re-record every golden (after a deliberate change only)"
	@echo "make build | clean"
	@echo "compiler: $(SILICA_COMPILER)"

# N3 (TRUST): the TRUST half of the bees.config reader and erl reading the trust/1 frames BEES writes
kit: kit-trust
.PHONY: kit-trust
kit-trust:
	@python3 "$(BEES_ROOT)/tools/test_bees_config_trust.py" 2>&1 | tail -3
	@python3 "$(BEES_ROOT)/tools/test_bees_trust_mux.py" 2>&1 | tail -3

# N2 (BEAM mode): the beam half of the bees.config reader, and the BEAM-mode layouts and digests against erl and OTP's sources
kit: kit-beam
.PHONY: kit-beam
kit-beam:
	@python3 "$(BEES_ROOT)/tools/test_beam_dist.py" 2>&1 | tail -3

# 2026-11-17: the trials' port table and the platform / golden-name functions and the parallel runner's pure parts
kit: kit-platform
.PHONY: kit-platform
kit-platform:
	@python3 "$(BEES_ROOT)/tools/trial_ports.py" check
	@python3 "$(BEES_ROOT)/tools/test_platform_and_ports.py" 2>&1 | tail -3
	@python3 "$(BEES_ROOT)/example_tempus_clients/python/test_bees_tempus_client.py" 2>&1 | tail -3
	@python3 "$(BEES_ROOT)/tools/test_bees_tempus_admission.py" 2>&1 | tail -3
	@python3 "$(BEES_ROOT)/tools/test_bees_tempus_store.py" 2>&1 | tail -3
	@python3 "$(BEES_ROOT)/tools/test_bees_tempus_view.py" 2>&1 | tail -3
	@python3 "$(BEES_ROOT)/tools/test_run_all_trials.py" 2>&1 | tail -3
