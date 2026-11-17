# N2c: a peer that connects again (spikes/N2b-multi-link.md, "Reconnect"), the auth-none M3 node (dangerous_bees_net), BEES to BEES over 127.0.0.1. Three leaves
# under nodes/ (one manifest, one bees.config, generated bees_peers, entry programs):
#   h  the hub: listens ONCE (port 47471) for two listen-role peers, e and d
#   e  dials the hub, redial false; entries e1 and e2 are the same node (e@localhost) started twice
#   d  dials the hub, redial on (250 ms doubling to 4000 ms)
# Scenario replace (stagger 2 s: h, e1, e2): e1 casts req_e (21) and gets 42, and stays up. e2 starts and connects while e1's link is
#   still up: the hub ENDS e1's link (reason replaced), e1 prints "proxy ended (killed)" (its proxy of req_e was killed with the link), and
#   e2 casts req_e (34) and gets 68, which only the new link carries: the hub's proxy of ans_e was ended with the old link and started again
#   for the new one (no registered-name clash). The hub prints "all answered" after the second request.
# Scenario redial (stagger 2.5 s: h1, d, h2): d casts req_d (21) to h1 and gets 42; h1 is then stopped and h2 (the same program, the same port) is
#   started 2.5 s after d. d's link is lost, d dials again after 250 ms, 500 ms, ... (audit lines) until h2 accepts, and d's second request
#   (34, at 8 s) is answered (68) over the new link.
# The racy audit lines (the link-down block, the order of the reaper's "proxy ended" line against the others, the number of redial attempts)
# are dropped from the outputs; the two *.check files record what the dropped lines proved: how many links the hub replaced, and that d
# logged its redial attempts, the first after 250 ms.
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)
HERE := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
include $(BEES_ROOT)/tools/silica.mk
NODES := h e d
OUTS := replace.h.sout replace.e1.sout replace.e2.sout replace.check redial.h1.sout redial.d.sout redial.h2.sout redial.check
RACY := link down, proxies ended|frames delivered|frames dropped|control messages counted|net ticks seen
.PHONY: build run integrate record-golden clean
build:
	@for n in $(NODES); do ($(MAKE) -C "$(HERE)/nodes/$$n" build || $(MAKE) -C "$(HERE)/nodes/$$n" build) || exit 1; $(MAKE) -C "$(HERE)/nodes/$$n" build > /dev/null || exit 1; done

run: build
	@cd "$(HERE)" && \
	"$(BEES_ROOT)/tools/run_trio.py" nodes/h/dangerous_h replace.h.sout "all answered" nodes/e/dangerous_e1 replace.e1.sout "proxy ended" nodes/e/dangerous_e2 replace.e2.sout "got answer" 2.0 90 || echo "trio: a run failed"; \
	"$(BEES_ROOT)/tools/run_trio.py" nodes/h/dangerous_h redial.h1.sout "ans_d sent" nodes/d/dangerous_d redial.d.sout "got answer 68" nodes/h/dangerous_h redial.h2.sout "ans_d sent" 2.5 90 || echo "trio: a run failed"; \
	sed -i '' -E -e 's/0x[0-9a-f]{6,}/0xADDR/g' replace.*.sout redial.*.sout; $(STRIP_ROOT_EXIT) replace.h.sout replace.e1.sout replace.e2.sout redial.h1.sout redial.d.sout redial.h2.sout; \
	printf 'links replaced by the hub: %s\n' "$$(grep -c 'reason replaced' replace.h.sout)" > replace.check; \
	printf 'd logged a redial attempt: %s\n' "$$(grep -c 'redial attempt' redial.d.sout | sed -E 's/^[1-9][0-9]*$$/yes/')" > redial.check; \
	printf 'd first delay 250 ms: %s\n' "$$(grep -c 'delay in ms h@localhost 250$$' redial.d.sout | sed -E 's/^[1-9][0-9]*$$/yes/')" >> redial.check; \
	for pair in "replace.h|all answered" "replace.e1|proxy ended" "replace.e2|got answer" "redial.h1|ans_d sent" "redial.d|got answer 68" "redial.h2|ans_d sent"; do f=$${pair%%|*}; m=$${pair#*|}; \
		grep -v -E '$(RACY)|redial scheduled|redial attempt' "$$f.sout" > "$$f.tmp"; mv "$$f.tmp" "$$f.sout"; \
		if [ "$$f" != replace.e1 ]; then grep -v -E '^proxy ended' "$$f.sout" > "$$f.tmp"; mv "$$f.tmp" "$$f.sout"; fi; \
		awk -v m="$$m" 'done { if ($$0 ~ /^exit=/) print; next } { print } index($$0, m) { done = 1 }' "$$f.sout" > "$$f.tmp" && mv "$$f.tmp" "$$f.sout"; \
	done

integrate: run
	@cd "$(HERE)" && ok=0; ko=0; for out in $(OUTS); do gold="$${out%.*}.scout"; case "$$out" in *.check) gold="$$out.scout";; esac; \
		if [ ! -f "$$gold" ]; then echo "MISSING golden: [m3_reconnect] $$gold"; ko=$$((ko+1)); \
		elif diff -Bw -q "$$out" "$$gold" > /dev/null; then ok=$$((ok+1)); \
		else echo "DIFF: [m3_reconnect] $$out"; diff -Bw "$$gold" "$$out" || true; ko=$$((ko+1)); fi; \
	done; printf '%d %d\n' "$$ok" "$$ko" > .integrate_counts; echo "[m3_reconnect] $$ok passed, $$ko failed"; [ "$$ko" -eq 0 ]

record-golden: run
	@cd "$(HERE)" && for out in $(OUTS); do gold="$${out%.*}.scout"; case "$$out" in *.check) gold="$$out.scout";; esac; cp "$$out" "$$gold"; done; echo "[m3_reconnect] goldens recorded"

clean:
	@for n in $(NODES); do $(MAKE) -C "$(HERE)/nodes/$$n" clean; done; cd "$(HERE)" && rm -f replace.*.sout redial.*.sout *.check .integrate_counts

