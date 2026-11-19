# N2T: the live test of BEAM mode INSIDE TLS against a stock Erlang node started with `erl -proto_dist inet_tls` (the installed OTP 28's
# erl); development-plan/spikes/N2T-beam-tls.md. tools/bees_beam_tls_live.py (n2_live.py's mechanics) starts a private EPMD on
# 127.0.0.1:23390 (EPMD stays plaintext, as for stock Erlang), compiles trials/n2_live/stock_driver.erl and stock_tls.erl into build/,
# writes the stock node's ssl_dist_optfile files there, and runs the scenarios, each a BEES node (nodes/l: beesl@localhost, a TLS
# listener registered with EPMD; nodes/d: beesd@localhost, dialing through EPMD) against a stock node. The stock node's option file
# says {versions, ['tlsv1.3']} (OTP 28's inet_tls_dist offers TLS 1.2 only unless told), verify_peer and fail_if_no_peer_cert. The
# certificates are the TEST-ONLY ones of trials/n2t_pair/certs (tools/bees_beam_tls_certs.py; never real keys).
#   stock_dials        n2_live's stock_dials inside TLS: ping (pong), nodes(), a message each way, SEND through a handed-out pid, link,
#                      unlink, monitor, 26 s idle with ticks, BEES killed: nodedown, noconnection (the link negotiates classical X25519:
#                      OTP 28 has no X25519MLKEM768)
#   bees_dials         BEES finds the stock node in EPMD, dials it inside TLS (SNI localhost, the certificate checked against it), casts to
#                      its inbox; the stock node answers to outbox
#   stock_rsa_dials    a stock node with an RSA 2048 certificate dials BEES: pong, the link's protocol is tls, a message each way
#   bees_dials_rsa     BEES dials a stock node with an RSA 2048 certificate: a message each way
#   stock_tls12        a stock node with the DEFAULT settings of inet_tls_dist (TLS 1.2 only) pings BEES: refused at the handshake, pang
#   stock_plain        a stock node without -proto_dist inet_tls pings BEES's TLS listener: refused, pang
#   stock_wrong_ca     a stock node with a certificate of another CA pings BEES: refused (tls_verify_failed), pang
#   wrong_cookie       a stock node with good TLS and another cookie pings BEES: TLS established, the digest refused, pang
#   bees_dials_tls12   BEES dials a stock node that offers TLS 1.2 only: BEES's handshake fails, no link
#   bees_dials_plain   BEES dials a stock node that listens in plaintext: BEES's TLS handshake is closed, no link
#   bees_redials_epmd  F1-1 (spikes/F1-fuzzer.md): BEES node r (nodes/r: beesr@localhost, redial on, 6 s) starts before the stock node:
#                      its EPMD lookup fails (the peer is not registered), the link fails as a refused dial does and the redial is
#                      scheduled; the stock node registers, BEES's next attempt (a new EPMD lookup) finds it and dials inside TLS, and
#                      the stock node casts to BEES's outbox (a driver line says the stock node registered before that attempt)
# Each scenario writes NAME.bees.sout and NAME.stock.sout (normalised: numbers in "evidence:" lines) and NAME.*.raw (as printed).
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)
HERE := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
include $(BEES_ROOT)/tools/silica.mk
NODES := l d r
SCENARIOS := stock_dials bees_dials stock_rsa_dials bees_dials_rsa stock_tls12 stock_plain stock_wrong_ca wrong_cookie bees_dials_tls12 bees_dials_plain bees_redials_epmd
.PHONY: build run integrate record-golden clean cookies
build: cookies
	@$(MAKE) -C "$(BEES_ROOT)/native" tls > /dev/null
	@for n in $(NODES); do ($(MAKE) -C "$(HERE)/nodes/$$n" build || $(MAKE) -C "$(HERE)/nodes/$$n" build) || exit 1; $(MAKE) -C "$(HERE)/nodes/$$n" build > /dev/null || exit 1; done

run: build
	@cd "$(HERE)" && python3 "$(BEES_ROOT)/tools/bees_beam_tls_live.py" "$(HERE)" $(SCENARIOS)

integrate: run
	@cd "$(HERE)" && ok=0; ko=0; for s in $(SCENARIOS); do for side in bees stock; do \
		if [ ! -f "$$s.$$side$(GOLD_SUFFIX).scout" ]; then echo "MISSING golden for $(BEES_PLATFORM_ID) (record one on this platform with make record-golden): [n2t_live] $$s.$$side$(GOLD_SUFFIX).scout"; ko=$$((ko+1)); \
		elif diff -Bw -q "$$s.$$side.sout" "$$s.$$side$(GOLD_SUFFIX).scout" > /dev/null; then ok=$$((ok+1)); \
		else echo "DIFF: [n2t_live] $$s.$$side"; diff -Bw "$$s.$$side$(GOLD_SUFFIX).scout" "$$s.$$side.sout" || true; ko=$$((ko+1)); fi; \
	done; done; printf '%d %d\n' "$$ok" "$$ko" > .integrate_counts; echo "[n2t_live] $$ok passed, $$ko failed"; [ "$$ko" -eq 0 ]

record-golden: run
	@cd "$(HERE)" && for s in $(SCENARIOS); do cp "$$s.bees.sout" "$$s.bees$(GOLD_SUFFIX).scout"; cp "$$s.stock.sout" "$$s.stock$(GOLD_SUFFIX).scout"; done; echo "[n2t_live] goldens recorded"

clean:
	@for n in $(NODES); do $(MAKE) -C "$(HERE)/nodes/$$n" clean; done
	@cd "$(HERE)" && for f in build/*.beam build/*.optfile *.sout *.raw .integrate_counts; do [ -f "$$f" ] && unlink "$$f"; done; true

cookies:
	@cd "$(HERE)" && printf 'n2t-live-cookie\n' > cookie && chmod 600 cookie && chmod 600 ../n2t_pair/certs/*-key.pem
