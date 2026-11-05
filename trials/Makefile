# Fan out over every trial leaf (a subdirectory holding a Makefile). `make integrate` prints a
# summary and fails if any leaf failed; `make record-golden` re-records every golden, which is
# only right after a deliberate behaviour change.
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/..)
LEAVES := $(sort $(patsubst %/Makefile,%,$(wildcard $(BEES_ROOT)/trials/*/Makefile)))

.PHONY: integrate record-golden build clean list

list:
	@for l in $(LEAVES); do echo "$$(basename $$l)"; done

build:
	@for l in $(LEAVES); do $(MAKE) -C "$$l" build || exit 1; done

integrate:
	@failed=0; ok=0; ko=0; \
	for l in $(LEAVES); do \
		rm -f "$$l/.integrate_counts"; \
		$(MAKE) -C "$$l" integrate || failed=1; \
		if [ -f "$$l/.integrate_counts" ]; then read a b < "$$l/.integrate_counts"; ok=$$((ok+a)); ko=$$((ko+b)); \
		else echo "FAIL: [$$(basename $$l)] did not finish (build failed or no result): counted as one failure"; ko=$$((ko+1)); failed=1; fi; \
	done; \
	echo "== trials: $$ok passed, $$ko failed"; exit $$failed

record-golden:
	@for l in $(LEAVES); do $(MAKE) -C "$$l" record-golden || exit 1; done

clean:
	@for l in $(LEAVES); do $(MAKE) -C "$$l" clean; done
