# N2d: a three-node MESH (triangle, no hub), BEAM mode (cookie auth, epmd none), BEES to BEES over 127.0.0.1 (spikes/N2b-multi-link.md, "Mesh").
# Three nodes a, b, c; each link is ONE connection with one dialer and one listener, and EVERY node has a mixed role:
#   a  dials b (port 22601) and dials c (port 22602)
#   b  listens (port 22601) for a and dials c
#   c  listens ONCE (port 22602) for both a and b
# Requests: node X casts rq_XY to Y (value 100 * round + 10 * X + Y, a=1 b=2 c=3) and gets its own answer on an_XY (10 * request + Y). The
# answer is cast to the registered name of the ASKER at the responder, so it must leave over the link of that peer: a misrouted reply carries
# the wrong sender or responder digit.
# Scenario mesh (stagger 1 s: c, b, a; all six requests at 0.6 s intervals, "done" at 9 s everywhere): all three links up, each node asks both others.
# Scenario redial (stagger 1 s: c1, b, a; then c2 at 10 s, the same node c on the same port): a and b dial with redial on (250 ms doubling to 2000 ms).
#   Round 0: a asks b and c, b asks c (c1 answers, then the harness ends it). Outage: a and b lose their c link and redial it; the OTHER links
#   (a-b: a dialed b, b listens) keep answering in both directions (6.5 s, 7.0 s). Round 1/2: c2 is up; a and b dial it again and are answered over
#   the NEW links (12.5 s, 13.0 s) while a-b still works (13.5 s, 14.0 s).
# The audit lines of a run of consecutive [bees audit] lines are sorted (a node that dials two peers at once completes the handshakes in either order; the
# index at the end of a handshake line is the peer's line in the manifest, so it stays). Racy audit lines (link-down blocks, reaper lines, the number of redial attempts) are dropped; the *.check files record what they proved: the
# redial attempts of a and b, and that no node printed a failure (no case arm matched, actor_not_found, an unexpected failure report).
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)
HERE := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
include $(BEES_ROOT)/tools/silica.mk
NODES := a b c ar br
OUTS := mesh.c.sout mesh.b.sout mesh.a.sout mesh.check redial.c1.sout redial.b.sout redial.a.sout redial.c2.sout redial.check
RACY := link down, proxies ended|frames delivered|frames dropped|control messages counted|net ticks seen
FAIL := no case arm matched|actor_not_found|failure report|not_allowed
.PHONY: build run integrate record-golden clean cookies
build: cookies
	@for n in $(NODES); do ($(MAKE) -C "$(HERE)/nodes/$$n" build || $(MAKE) -C "$(HERE)/nodes/$$n" build) || exit 1; $(MAKE) -C "$(HERE)/nodes/$$n" build > /dev/null || exit 1; done

run: build
	@cd "$(HERE)" && \
	"$(BEES_ROOT)/tools/run_trio.py" nodes/c/dangerous_cm mesh.c.sout "c: done" nodes/b/dangerous_b mesh.b.sout "b: done" nodes/a/dangerous_a mesh.a.sout "a: done" 1.0 90 || echo "trio: a run failed"; \
	( sleep 10; "$(BEES_ROOT)/tools/run_trial.py" nodes/c/dangerous_c2 redial.c2.sout "c: done" 0.5 90 || echo "c2: a run failed" ) & \
	"$(BEES_ROOT)/tools/run_trio.py" nodes/c/dangerous_c1 redial.c1.sout "c: answer to b sent" nodes/br/dangerous_br redial.b.sout "b: done" nodes/ar/dangerous_ar redial.a.sout "a: done" 1.0 90 || echo "trio: a run failed"; \
	wait; \
	$(SED_I) -E -e 's/0x[0-9a-f]{6,}/0xADDR/g' mesh.*.sout redial.*.sout; $(STRIP_ROOT_EXIT) mesh.c.sout mesh.b.sout mesh.a.sout redial.c1.sout redial.b.sout redial.a.sout redial.c2.sout; \
	printf 'failure lines in any node output: %s\n' "$$(cat mesh.c.sout mesh.b.sout mesh.a.sout | grep -c -E '$(FAIL)')" > mesh.check; \
	printf 'failure lines in any node output: %s\n' "$$(cat redial.c1.sout redial.b.sout redial.a.sout redial.c2.sout | grep -c -E '$(FAIL)')" > redial.check; \
	printf 'a logged a redial attempt: %s\n' "$$(grep -c 'redial attempt' redial.a.sout | sed -E 's/^[1-9][0-9]*$$/yes/')" >> redial.check; \
	printf 'b logged a redial attempt: %s\n' "$$(grep -c 'redial attempt' redial.b.sout | sed -E 's/^[1-9][0-9]*$$/yes/')" >> redial.check; \
	printf 'a first delay 250 ms to c: %s\n' "$$(grep -c 'delay in ms c@localhost 250$$' redial.a.sout | sed -E 's/^[1-9][0-9]*$$/yes/')" >> redial.check; \
	printf 'b first delay 250 ms to c: %s\n' "$$(grep -c 'delay in ms c@localhost 250$$' redial.b.sout | sed -E 's/^[1-9][0-9]*$$/yes/')" >> redial.check; \
	for pair in "mesh.c|c: done" "mesh.b|b: done" "mesh.a|a: done" "redial.c1|c: answer to b sent" "redial.b|b: done" "redial.a|a: done" "redial.c2|c: done"; do f=$${pair%%|*}; m=$${pair#*|}; \
		grep -v -E '$(RACY)|redial scheduled|redial attempt|^proxy ended' "$$f.sout" > "$$f.tmp"; mv "$$f.tmp" "$$f.sout"; \
		awk '/^\[bees audit\]/ { print | "LC_ALL=C sort"; next } { close("LC_ALL=C sort"); print; fflush() } END { close("LC_ALL=C sort") }' "$$f.sout" > "$$f.tmp" && mv "$$f.tmp" "$$f.sout"; \
		awk -v m="$$m" 'done { if ($$0 ~ /^exit=/) print; next } { print } index($$0, m) { done = 1 }' "$$f.sout" > "$$f.tmp" && mv "$$f.tmp" "$$f.sout"; \
	done

integrate: run
	@cd "$(HERE)" && ok=0; ko=0; for out in $(OUTS); do gold="$${out%.*}$(GOLD_SUFFIX).scout"; case "$$out" in *.check) gold="$$out$(GOLD_SUFFIX).scout";; esac; \
		if [ ! -f "$$gold" ]; then echo "MISSING golden for $(BEES_PLATFORM_ID) (record one on this platform with make record-golden): [n2_mesh] $$gold"; ko=$$((ko+1)); \
		elif diff -Bw -q "$$out" "$$gold" > /dev/null; then ok=$$((ok+1)); \
		else echo "DIFF: [n2_mesh] $$out"; diff -Bw "$$gold" "$$out" || true; ko=$$((ko+1)); fi; \
	done; printf '%d %d\n' "$$ok" "$$ko" > .integrate_counts; echo "[n2_mesh] $$ok passed, $$ko failed"; [ "$$ko" -eq 0 ]

record-golden: run
	@cd "$(HERE)" && for out in $(OUTS); do gold="$${out%.*}$(GOLD_SUFFIX).scout"; case "$$out" in *.check) gold="$$out$(GOLD_SUFFIX).scout";; esac; cp "$$out" "$$gold"; done; echo "[n2_mesh] goldens recorded"

clean:
	@for n in $(NODES); do $(MAKE) -C "$(HERE)/nodes/$$n" clean; done; cd "$(HERE)" && rm -f mesh.*.sout redial.*.sout *.check *.tmp .integrate_counts

cookies:
	@cd "$(HERE)" && printf 'n2-mesh-cookie\n' > cookie && chmod 600 cookie
