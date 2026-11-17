# N1: addresses other than 127.0.0.1, on this machine only (no network beyond it). BEAM-mode nodes of N2 (Erlang cookie
# authentication: a non-loopback listen or dial without TLS and authentication is refused by the reader, because auth none and
# plaintext_test_only are loopback-only test settings). Each node is its own leaf under nodes/; @IP@ in a node's bees.config.in
# is this machine's non-loopback IPv4 address (ipconfig getifaddr en0, else en1), so the goldens do not contain it.
#   loop_only   a listens on 127.0.0.1 only and b dials this machine's non-loopback address: refused, the link never comes up,
#               a sees nothing (the listener is not reachable over the non-loopback address)
#   name        a listens and n dials the name localhost: the BEES resolver edge (getaddrinfo) answers 127.0.0.1, the cookie
#               handshake completes and the cast to inbox arrives
#   dns_error   e dials no-such-host.invalid: the resolver answers dns_error, nothing is dialed, nothing crashes; a sees nothing
# OPT-IN, not part of `make integrate` (`make any_ip`): w listens on 0.0.0.0 (the carrier's listen:any) and v dials the
# non-loopback address. A listener on every interface is reachable from the machine's networks while it runs, so it is run only
# when the user asks (the sandbox of the 2026-11-10 session refused to start it).
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)
HERE := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
include $(BEES_ROOT)/tools/silica.mk
NODES := a b n e
SCENARIOS := \
 loop_only|a/dangerous_a_late|late:|b/dangerous_b_watch|late:|0 \
 name|a/dangerous_a_slow|got|n/dangerous_n_slow|sent|1 \
 dns_error|a/dangerous_a_late|late:|e/dangerous_e_watch|late:|0

SCEN_QUOTED := $(foreach s,$(SCENARIOS),'$(s)')
.PHONY: build run integrate record-golden clean cookies
# a node leaf is built until it succeeds (once more on a transient compiler crash, SD-29 family) and then once more, because the
# root units are generated at parse time and make may list the entries before they exist on the very first build
build: cookies
	@for n in $(NODES); do ($(MAKE) -C "$(HERE)/nodes/$$n" build || $(MAKE) -C "$(HERE)/nodes/$$n" build) || exit 1; $(MAKE) -C "$(HERE)/nodes/$$n" build > /dev/null || exit 1; done

run: build
	@cd "$(HERE)" && for s in $(SCEN_QUOTED); do \
		sc=$$(echo "$$s" | cut -d'|' -f1); ea=$$(echo "$$s" | cut -d'|' -f2); ma=$$(echo "$$s" | cut -d'|' -f3); eb=$$(echo "$$s" | cut -d'|' -f4); mb=$$(echo "$$s" | cut -d'|' -f5); tr=$$(echo "$$s" | cut -d'|' -f6); \
		"$(BEES_ROOT)/tools/run_pair.py" "nodes/$$ea" "$$sc.a.sout" "$$ma" "nodes/$$eb" "$$sc.b.sout" "$$mb" 0.5 60 || echo "pair $$sc: a run failed"; \
		$(SED_I) -E -e 's/0x[0-9a-f]{6,}/0xADDR/g' "$$sc.a.sout" "$$sc.b.sout"; $(STRIP_ROOT_EXIT) "$$sc.a.sout" "$$sc.b.sout"; \
		if [ "$$tr" = 1 ]; then \
			awk -v m="$$ma" 'done { if ($$0 ~ /^exit=/) print; next } { print } index($$0, m) { done = 1 }' "$$sc.a.sout" > "$$sc.a.tmp" && mv "$$sc.a.tmp" "$$sc.a.sout"; \
			awk -v m="$$mb" 'done { if ($$0 ~ /^exit=/) print; next } { print } index($$0, m) { done = 1 }' "$$sc.b.sout" > "$$sc.b.tmp" && mv "$$sc.b.tmp" "$$sc.b.sout"; \
		fi; \
	done

integrate: run
	@cd "$(HERE)" && ok=0; ko=0; for s in $(SCEN_QUOTED); do \
		name=$${s%%|*}; \
		for side in a b; do \
			if [ ! -f "$$name.$$side$(GOLD_SUFFIX).scout" ]; then echo "MISSING golden for $(BEES_PLATFORM_ID) (record one on this platform with make record-golden): [n1_addr] $$name.$$side$(GOLD_SUFFIX).scout"; ko=$$((ko+1)); \
			elif diff -Bw -q "$$name.$$side.sout" "$$name.$$side$(GOLD_SUFFIX).scout" > /dev/null; then ok=$$((ok+1)); \
			else echo "DIFF: [n1_addr] $$name.$$side"; diff -Bw "$$name.$$side$(GOLD_SUFFIX).scout" "$$name.$$side.sout" || true; ko=$$((ko+1)); fi; \
		done; \
	done; printf '%d %d\n' "$$ok" "$$ko" > .integrate_counts; echo "[n1_addr] $$ok passed, $$ko failed"; [ "$$ko" -eq 0 ]

record-golden: run
	@cd "$(HERE)" && for s in $(SCEN_QUOTED); do name=$${s%%|*}; cp "$$name.a.sout" "$$name.a$(GOLD_SUFFIX).scout"; cp "$$name.b.sout" "$$name.b$(GOLD_SUFFIX).scout"; done; echo "[n1_addr] goldens recorded"

clean:
	@for n in $(NODES); do $(MAKE) -C "$(HERE)/nodes/$$n" clean; done; cd "$(HERE)" && rm -f *.sout .integrate_counts

# the cookie of trials/n2_dist (git keeps no permissions)
cookies:
	@$(MAKE) -s -C "$(BEES_ROOT)/trials/n2_dist" cookies

# the opt-in scenario (see the header): builds w and v and runs the pair once, printing both outputs (no golden)
.PHONY: any_ip
any_ip: cookies
	@for n in w v; do ($(MAKE) -C "$(HERE)/nodes/$$n" build || $(MAKE) -C "$(HERE)/nodes/$$n" build) || exit 1; done
	@cd "$(HERE)" && "$(BEES_ROOT)/tools/run_pair.py" nodes/w/dangerous_w_slow any_ip.a.out got nodes/v/dangerous_v_slow any_ip.b.out sent 0.5 60; \
		cat any_ip.a.out any_ip.b.out
