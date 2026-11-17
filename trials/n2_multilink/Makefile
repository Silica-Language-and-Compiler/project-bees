# N2b: more than one live link per node, BEAM mode, BEES to BEES over 127.0.0.1 (beam.epmd none). Three nodes, each its own leaf under
# nodes/ (one manifest, one bees.config, generated bees_peers, beam_conf and beam_peers, one entry program):
#   hub  listens ONCE (port 22100) for two listen-role peers, ea and ec; its table holds both, and a peer's proxies start when
#        the handshake names it
#   ea   dials the hub, casts req_a (21) to it and receives ITS answer, 42, on ans_a
#   ec   dials the hub, casts req_c (34) to it and receives ITS answer, 68, on ans_c
# The hub answers req_a by casting to ans_a (the proxy of ea) and req_c by casting to ans_c (the proxy of ec): each answer must leave
# over the link of the peer that name belongs to, so ea never sees 68 and ec never sees 42. Goldens: three_nodes.{hub,ea,ec}.scout.
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)
HERE := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
include $(BEES_ROOT)/tools/silica.mk
NODES := hub ea ec
SIDES := hub ea ec
.PHONY: build run integrate record-golden clean cookies
build: cookies
	@for n in $(NODES); do ($(MAKE) -C "$(HERE)/nodes/$$n" build || $(MAKE) -C "$(HERE)/nodes/$$n" build) || exit 1; $(MAKE) -C "$(HERE)/nodes/$$n" build > /dev/null || exit 1; done

# the link-down audit block and the reaper's line are dropped (the order against the other edge's traffic follows when the harness stops
# each program); what a program prints after its marker (the peers closing as the harness stops the programs) races the exit of the process, so it is
# dropped; the exit code line is kept
run: build
	@cd "$(HERE)" && "$(BEES_ROOT)/tools/run_trio.py" nodes/hub/dangerous_hub three_nodes.hub.sout "ans_c sent" nodes/ea/dangerous_ea three_nodes.ea.sout "got answer" nodes/ec/dangerous_ec three_nodes.ec.sout "got answer" 0.5 90 || echo "trio: a run failed"; \
	$(SED_I) -E -e 's/0x[0-9a-f]{6,}/0xADDR/g' three_nodes.*.sout; $(STRIP_ROOT_EXIT) three_nodes.hub.sout three_nodes.ea.sout three_nodes.ec.sout; \
	for pair in "hub|ans_c sent" "ea|got answer" "ec|got answer"; do side=$${pair%%|*}; m=$${pair#*|}; \
		grep -v -E 'link down, proxies ended|frames delivered|frames dropped|control messages counted|net ticks seen|^proxy ended' "three_nodes.$$side.sout" > "three_nodes.$$side.tmp"; mv "three_nodes.$$side.tmp" "three_nodes.$$side.sout"; \
		awk -v m="$$m" 'done { if ($$0 ~ /^exit=/) print; next } { print } index($$0, m) { done = 1 }' "three_nodes.$$side.sout" > "three_nodes.$$side.tmp" && mv "three_nodes.$$side.tmp" "three_nodes.$$side.sout"; \
	done

integrate: run
	@cd "$(HERE)" && ok=0; ko=0; for side in $(SIDES); do \
		if [ ! -f "three_nodes.$$side$(GOLD_SUFFIX).scout" ]; then echo "MISSING golden for $(BEES_PLATFORM_ID) (record one on this platform with make record-golden): [n2_multilink] three_nodes.$$side$(GOLD_SUFFIX).scout"; ko=$$((ko+1)); \
		elif diff -Bw -q "three_nodes.$$side.sout" "three_nodes.$$side$(GOLD_SUFFIX).scout" > /dev/null; then ok=$$((ok+1)); \
		else echo "DIFF: [n2_multilink] three_nodes.$$side"; diff -Bw "three_nodes.$$side$(GOLD_SUFFIX).scout" "three_nodes.$$side.sout" || true; ko=$$((ko+1)); fi; \
	done; printf '%d %d\n' "$$ok" "$$ko" > .integrate_counts; echo "[n2_multilink] $$ok passed, $$ko failed"; [ "$$ko" -eq 0 ]

record-golden: run
	@cd "$(HERE)" && for side in $(SIDES); do cp "three_nodes.$$side.sout" "three_nodes.$$side$(GOLD_SUFFIX).scout"; done; echo "[n2_multilink] goldens recorded"

clean:
	@for n in $(NODES); do $(MAKE) -C "$(HERE)/nodes/$$n" clean; done; cd "$(HERE)" && rm -f *.sout .integrate_counts

cookies:
	@cd "$(HERE)" && printf 'n2-multilink-cookie\n' > cookie && chmod 600 cookie
