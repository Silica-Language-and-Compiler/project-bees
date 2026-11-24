# C7: the Python TEMPUS extension as a NODE (example_tempus_clients/python/lib/bees_tempus_node.py), in one network with Silica
# nodes on 127.0.0.1 (development-plan/tempus-design.md sections 3 to 6 and 8 to 11; owner's ruling of 2026-11-23:
# "nodes on non-silica are the plan").
#   tests         the extension's own tests (example_tempus_clients/python/test_bees_tempus_node.py and
#                 test_bees_tempus_client.py): its stores against the recorded outputs of trials/t0_tempus_view and
#                 trials/t1_tempus_store, its clock decisions against trials/t0_tempus_clock, admission against
#                 trials/t4_tempus_admission, its configuration's refusals against tools/test_bees_tempus_conf.py and
#                 trials/c4_tempus_boot
#   dangerous_q   node Q, a Silica sentinel, a test program (nodes/q, with the test unit of src/tempus_test)
#   dangerous_a   node A, a Silica edge, a test program (nodes/a). It joins through the Python sentinel S.
#   dangerous_w   node W, a Silica edge shaped like a production program (nodes/w: no test unit in its build). It reads
#                 the machine's clock and joins through the Python sentinel R.
#   py_s, py_p    the Python sentinel S (it joins through Q) and the Python edge P: test nodes, in the trial tool's
#                 process, each given a clock, timers and draws by the tool through the extension's constructor
#   py_r          the Python sentinel R: the program r_app.py, a process of its own that is NOT a test program: it
#                 imports no test support, reads the machine's clock and runs its own timers
#   py_h, py_t, py_v   Python test nodes for the clock's choices: H (hold, continue), T (stop above 60 s, pause) and the
#                 sentinel V that T joins through
#   walk          the transcript of walk.py: what each step showed, each step checked. Its part 2 sends every hostile
#                 case to the Silica sentinel Q and to the Python sentinel S and requires the two nodes' audit lines
#                 to be the same, word for word.
# Each Silica program is built in its own directory under nodes/, so that each has its own list of units (lib/), as
# trials/t6_tempus_clock builds its nodes. `make production-check` (part of integrate) searches the Python extension's
# modules (example_tempus_clients/python/lib/bees_tempus_*.py) for any trace of test support, and requires the same
# search to find it in the test support itself (example_tempus_clients/python/testing/bees_tempus_testing.py).
# Needs Python 3 with the `cryptography` package and an ssl module over OpenSSL 3.5 or later (the key exchange group
# X25519MLKEM768). Nothing is fetched. Files this trial writes while it runs: whitelist/, r_app.json, r_token.hex.
# Post-processing of the Silica nodes' outputs: tools/bees_tempus_reports.py (as every TEMPUS trial).
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)
HERE := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
include $(BEES_ROOT)/tools/silica.mk
EXT := $(BEES_ROOT)/example_tempus_clients/python
NODES := q a w
OUTS := tests walk dangerous_q dangerous_a dangerous_w py_s py_p py_r py_h py_t py_v
# the modules an application imports, and what must not be in them: the test frames, token making, keys from seeds,
# misbehaviour, and any import of the test support
LIBRARY := bees_tempus_codec.py bees_tempus_admission.py bees_tempus_peer.py bees_tempus_view.py bees_tempus_store.py bees_tempus_config.py bees_tempus_node.py
TRACES := def tick\(store\)|def clock\(ms|make_token|token_payload|fixture_key|fixture_identity|Misbehaviour|wrong_proof|oversize_frame|import bees_tempus_testing|from bees_tempus_testing|import bees_tempus_client|from_private_bytes
.DEFAULT_GOAL := build
.PHONY: build run integrate record-golden clean natives fixtures tools production-check
tools:
	@python3 -c "import cryptography, ssl, sys; sys.exit(0 if ssl.OPENSSL_VERSION_INFO >= (3, 5) and hasattr(ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT), '_msg_callback') else 1)" 2> /dev/null || { echo "FAIL: [c7_tempus_node_python] needs Python 3 with the cryptography package and an ssl module over OpenSSL 3.5 or later (example_tempus_clients/python/README.md says what to install)"; exit 1; }
natives:
	@out=$$($(MAKE) --no-print-directory -C "$(BEES_ROOT)/native" tempus tls 2>&1); rc=$$?; \
	[ -z "$$out" ] || printf '%s\n' "$$out" | grep -v '^ar \|^cc \|^mkdir ' ; \
	if [ "$$rc" != 0 ]; then echo "FAIL: [c7_tempus_node_python] needs the TEMPUS native edge and the TLS engine (make -C native tempus tls; OpenSSL 4.1.0 or later)"; exit 1; fi
fixtures:
	@python3 "$(BEES_ROOT)/tools/bees_tempus_certs.py" check > /dev/null || { echo "FAIL: [c7_tempus_node_python] the TEMPUS certificates are not what tools/bees_tempus_certs.py writes"; exit 1; }
build: tools natives fixtures
	@for n in $(NODES); do $(MAKE) --no-print-directory -C "$(HERE)/nodes/$$n" build SILICA_COMPILER="$(SILICA_COMPILER)" || exit 1; done
production-check:
	@cd "$(EXT)/lib" && if grep -n -E '$(TRACES)' $(LIBRARY); then echo "FAIL: [c7_tempus_node_python] a module of the Python extension holds a trace of test support (the lines above)"; exit 1; fi; \
	grep -q -E '$(TRACES)' ../testing/bees_tempus_testing.py || { echo "FAIL: [c7_tempus_node_python] the search finds nothing in the test support either, so it proves nothing"; exit 1; }; \
	echo "[c7_tempus_node_python] production check: no trace of test support in the $(words $(LIBRARY)) modules of the Python extension; the same search finds it in bees_tempus_testing.py"
run: build
	@cd "$(HERE)" && for o in $(OUTS); do : > "$$o.sout"; done; \
	python3 tests.py "$(BEES_ROOT)" > tests.sout 2>&1; rc=$$?; printf 'exit=%s\n' "$$rc" >> tests.sout; \
	if [ "$$rc" != 0 ]; then cat tests.sout; echo "FAIL: [c7_tempus_node_python] the extension's own tests failed (tests.sout)"; exit 1; fi; \
	python3 walk.py . || exit 1; \
	python3 "$(BEES_ROOT)/tools/bees_tempus_reports.py" dangerous_q.sout dangerous_a.sout dangerous_w.sout
integrate: run production-check
	@cd "$(HERE)" && ok=0; ko=0; for o in $(OUTS); do g="$$o$(GOLD_SUFFIX).scout"; \
		if [ ! -f "$$g" ]; then echo "MISSING golden for $(BEES_PLATFORM_ID) (record one on this platform with make record-golden): [c7_tempus_node_python] $$g"; ko=$$((ko+1)); \
		elif diff -q "$$o.sout" "$$g" > /dev/null; then ok=$$((ok+1)); \
		else echo "DIFF: [c7_tempus_node_python] $$o"; diff "$$g" "$$o.sout" || true; ko=$$((ko+1)); fi; done; \
	printf '%d %d\n' "$$ok" "$$ko" > .integrate_counts; echo "[c7_tempus_node_python] $$ok passed, $$ko failed"; [ "$$ko" -eq 0 ]
record-golden: run production-check
	@cd "$(HERE)" && for o in $(OUTS); do cp "$$o.sout" "$$o$(GOLD_SUFFIX).scout"; done; echo "[c7_tempus_node_python] goldens recorded"
clean:
	@for n in $(NODES); do $(MAKE) --no-print-directory -C "$(HERE)/nodes/$$n" clean; done; \
	cd "$(HERE)" && rm -f whitelist/*.pem r_app.json r_token.hex r_app.py.sout .integrate_counts && for o in $(OUTS); do rm -f "$$o.sout"; done; \
	[ ! -d whitelist ] || rmdir whitelist
