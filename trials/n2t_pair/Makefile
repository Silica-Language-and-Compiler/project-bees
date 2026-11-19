# N2T: BEAM mode inside TLS, BEES to BEES over 127.0.0.1 (beam.epmd none); development-plan/spikes/N2T-beam-tls.md. The hub listens ONCE
# (port 23200, a TLS listener because its bees.config says {transport, tls}) for three listen-role peers; the edges dial it. Every node is
# its own leaf under nodes/ (one manifest, one bees.config, generated beam_conf and beam_peers, entry programs); the programs are the
# roles of trials/n2_multilink and trials/n2_reconnect (the hub's is roles/hub.role: theirs plus req_d). The certificates in certs/ are
# TEST ONLY, written by tools/bees_beam_tls_certs.py from fixed inputs (never real keys); the unit tests check that the files are the
# tool's. Scenarios (each writes NAME.SIDE.sout, compared with NAME.SIDE.<platform>.scout):
#   three_nodes     hub, ea, ec: ONE TLS listener, two links. ea casts req_a (21) and gets ITS answer 42, ec casts req_c (34) and gets 68:
#                   requests one way, answers the other, each over its own TLS link (TLSv1.3 X25519MLKEM768, both certificates verified)
#   redial          hub (h1), d, hub again (h2), 4 s apart: d's first request is answered by h1; h1 is stopped; d dials again inside TLS
#                   (redial on) until h2 accepts, and its second request is answered over the new TLS link (redial.check: d logged attempts)
#   rsa             hub and ea_rsa (an RSA 2048 certificate, N2T Q4): accepted, request and answer
#   edge_wrong_ca   hub and ea_rogue (a certificate of another CA): the hub refuses it (tls_verify_failed, as server); the edge sees the
#                   handshake finish and then the alert (TLS 1.3 delivers a server's refusal of the client certificate that way)
#   hub_untrusted   hub and ea_rogueca (an edge that trusts another CA): the edge refuses the hub's certificate (tls_verify_failed, as client)
#   wrong_name      hub_other (a certificate naming otherhost) and ea: the edge refuses it: not the name it dialed (hub@LOCALHOST)
#   plain_on_tls    hub and ea_plain ({transport, tcp}): a plaintext peer on the TLS listener is refused before any distribution byte
#   tls_on_plain    hub_plain ({transport, tcp}) and ea: a TLS peer on a plaintext listener is refused (a bad frame length), and the edge
#                   sees its TLS handshake closed
#   wrong_cookie    hub and ea's entry dangerous_ea_wrongcookie: TLS is established, then the cookie digest is refused, as in plaintext
#   probes          `openssl s_client` against the hub, one rule per case (tools/bees_beam_tls_probes.py): accepted at the TLS layer:
#                   the hybrid group, classical X25519, an offered ALPN (none selected), RSA 2048, RSA-PSS-signed by an RSA CA; refused:
#                   RSA 1024, no certificate, another CA, expired, TLS 1.2 only, a group outside the profile
# What is dropped from the outputs, as in n2_multilink and n2_reconnect: the four counter lines after "link down" and the reaper's
# "proxy ended" line (their order against the other side's traffic follows when the harness stops each program), everything after a
# program's marker except its exit line, and in three_nodes, redial and rsa the link-down line, the TLS audit lines of redial (their
# number depends on how many attempts were needed) and the racy redial lines (redial.check keeps the proof).
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)
HERE := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
include $(BEES_ROOT)/tools/silica.mk
NODES := hub ea ec d ea_rogueca ea_rogue ea_rsa ea_plain hub_plain hub_other
RUN_PAIR := "$(BEES_ROOT)/tools/run_pair.py"
RUN_TRIO := "$(BEES_ROOT)/tools/run_trio.py"
# pair scenarios: name|hub leaf/entry|hub marker|edge leaf/entry|edge marker
PAIRS := "rsa|hub/dangerous_hub|ans_a sent|ea_rsa/dangerous_ea_rsa|got answer" \
	"edge_wrong_ca|hub/dangerous_hub|link down|ea_rogue/dangerous_ea_rogue|link down" \
	"hub_untrusted|hub/dangerous_hub|link down|ea_rogueca/dangerous_ea_rogueca|link down" \
	"wrong_name|hub_other/dangerous_hub_other|link down|ea/dangerous_ea|link down" \
	"plain_on_tls|hub/dangerous_hub|link down|ea_plain/dangerous_ea_plain|link down" \
	"tls_on_plain|hub_plain/dangerous_hub_plain|link down|ea/dangerous_ea|link down" \
	"wrong_cookie|hub/dangerous_hub|link down|ea/dangerous_ea_wrongcookie|link down"
SOUTS := three_nodes.hub.sout three_nodes.ea.sout three_nodes.ec.sout redial.h1.sout redial.d.sout redial.h2.sout \
	rsa.hub.sout rsa.edge.sout edge_wrong_ca.hub.sout edge_wrong_ca.edge.sout hub_untrusted.hub.sout hub_untrusted.edge.sout \
	wrong_name.hub.sout wrong_name.edge.sout plain_on_tls.hub.sout plain_on_tls.edge.sout tls_on_plain.hub.sout tls_on_plain.edge.sout \
	wrong_cookie.hub.sout wrong_cookie.edge.sout probes.hub.sout
OUTS := $(SOUTS) redial.check
RACY := frames delivered|frames dropped|control messages counted|net ticks seen|^proxy ended
# keeps a program's output up to and including its marker line, and its exit line
CUT = awk -v m="$$m" 'done { if ($$0 ~ /^exit=/) print; next } { print } index($$0, m) { done = 1 }'
.PHONY: build run integrate record-golden clean cookies
build: cookies
	@$(MAKE) -C "$(BEES_ROOT)/native" tls > /dev/null
	@for n in $(NODES); do ($(MAKE) -C "$(HERE)/nodes/$$n" build || $(MAKE) -C "$(HERE)/nodes/$$n" build) || exit 1; $(MAKE) -C "$(HERE)/nodes/$$n" build > /dev/null || exit 1; done

run: build
	@cd "$(HERE)" && \
	$(RUN_TRIO) nodes/hub/dangerous_hub three_nodes.hub.sout "ans_c sent" nodes/ea/dangerous_ea three_nodes.ea.sout "got answer" nodes/ec/dangerous_ec three_nodes.ec.sout "got answer" 0.5 90 || echo "three_nodes: a run failed"; \
	$(RUN_TRIO) nodes/hub/dangerous_hub redial.h1.sout "ans_d sent" nodes/d/dangerous_d redial.d.sout "got answer 68" nodes/hub/dangerous_hub redial.h2.sout "ans_d sent" 4.0 90 || echo "redial: a run failed"; \
	for p in $(PAIRS); do name=$${p%%|*}; r=$${p#*|}; hub=$${r%%|*}; r=$${r#*|}; hm=$${r%%|*}; r=$${r#*|}; edge=$${r%%|*}; em=$${r#*|}; \
		$(RUN_PAIR) "nodes/$$hub" "$$name.hub.sout" "$$hm" "nodes/$$edge" "$$name.edge.sout" "$$em" 3.0 60 || echo "$$name: a run failed"; \
	done; \
	"$(BEES_ROOT)/tools/bees_beam_tls_probes.py" nodes/hub/dangerous_hub probes.hub.sout "BEAM mode" certs 127.0.0.1:$$("$(BEES_ROOT)/tools/trial_ports.py" port n2t_pair 0) --openssl "$(OPENSSL_PREFIX)/bin/openssl" || echo "probes: the run failed"; \
	$(SED_I) -E -e 's/0x[0-9a-f]{6,}/0xADDR/g' $(SOUTS); $(STRIP_ROOT_EXIT) $(SOUTS); \
	printf 'd logged a redial attempt: %s\n' "$$(grep -c 'redial attempt' redial.d.sout | sed -E 's/^[1-9][0-9]*$$/yes/')" > redial.check; \
	printf 'd first delay 250 ms: %s\n' "$$(grep -c 'delay in ms hub@localhost 250$$' redial.d.sout | sed -E 's/^[1-9][0-9]*$$/yes/')" >> redial.check; \
	printf 'd established TLS more than once: %s\n' "$$(grep -c 'tls: established' redial.d.sout | sed -E 's/^([2-9]|[1-9][0-9]+)$$/yes/')" >> redial.check; \
	for f in $(SOUTS); do grep -v -E '$(RACY)' "$$f" > "$$f.tmp"; mv "$$f.tmp" "$$f"; done; \
	for pair in "three_nodes.hub|ans_c sent" "three_nodes.ea|got answer" "three_nodes.ec|got answer" "redial.h1|ans_d sent" "redial.d|got answer 68" "redial.h2|ans_d sent" "rsa.hub|ans_a sent" "rsa.edge|got answer"; do f=$${pair%%|*}; m=$${pair#*|}; \
		grep -v -E 'link down, proxies ended|redial scheduled|redial attempt' "$$f.sout" > "$$f.tmp"; mv "$$f.tmp" "$$f.sout"; \
		case "$$f" in redial.*) grep -v -E 'tls: ' "$$f.sout" > "$$f.tmp"; mv "$$f.tmp" "$$f.sout";; esac; \
		$(CUT) "$$f.sout" > "$$f.tmp" && mv "$$f.tmp" "$$f.sout"; \
	done; \
	for p in $(PAIRS); do name=$${p%%|*}; [ "$$name" = rsa ] && continue; m="link down"; for side in hub edge; do \
		$(CUT) "$$name.$$side.sout" > "$$name.$$side.tmp" && mv "$$name.$$side.tmp" "$$name.$$side.sout"; done; done

integrate: run
	@cd "$(HERE)" && ok=0; ko=0; for out in $(OUTS); do gold="$${out%.*}$(GOLD_SUFFIX).scout"; case "$$out" in *.check) gold="$$out$(GOLD_SUFFIX).scout";; esac; \
		if [ ! -f "$$gold" ]; then echo "MISSING golden for $(BEES_PLATFORM_ID) (record one on this platform with make record-golden): [n2t_pair] $$gold"; ko=$$((ko+1)); \
		elif diff -Bw -q "$$out" "$$gold" > /dev/null; then ok=$$((ok+1)); \
		else echo "DIFF: [n2t_pair] $$out"; diff -Bw "$$gold" "$$out" || true; ko=$$((ko+1)); fi; \
	done; printf '%d %d\n' "$$ok" "$$ko" > .integrate_counts; echo "[n2t_pair] $$ok passed, $$ko failed"; [ "$$ko" -eq 0 ]

record-golden: run
	@cd "$(HERE)" && for out in $(OUTS); do gold="$${out%.*}$(GOLD_SUFFIX).scout"; case "$$out" in *.check) gold="$$out$(GOLD_SUFFIX).scout";; esac; cp "$$out" "$$gold"; done; echo "[n2t_pair] goldens recorded"

clean:
	@for n in $(NODES); do $(MAKE) -C "$(HERE)/nodes/$$n" clean; done; cd "$(HERE)" && for f in $(OUTS); do [ -f "$$f" ] && unlink "$$f"; done; true

cookies:
	@cd "$(HERE)" && printf 'n2t-pair-cookie\n' > cookie && chmod 600 cookie && printf 'n2t-pair-other-cookie\n' > cookie_wrong && chmod 600 cookie_wrong && chmod 600 certs/*-key.pem
