# Generic leaf Makefile for a BEES trial directory. A leaf's own Makefile is two lines:
#
#   BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)
#   include $(BEES_ROOT)/tools/trial.mk
#
# Layout of a leaf (the same conventions as Silica's trials/modules_addition and
# trials/ordered_data_structures):
#
#   lib/*.silica        library units, normally symlinks into src/; compiled, never run
#   *.silica            entry programs: each has fn main() and becomes one executable
#   NAME.pair           (optional) two entry names that run together, e.g. a listener and a connector
#   fail_*.silica (dangerous_fail_*.silica when the unit declares foreign functions: E4020 wants the dangerous_ prefix)       compile-fail trials, compiled in isolation; the compiler's output is
#                       the golden (NAME.$(BEES_PLATFORM_ID).golden_fail)
#   NAME.$(BEES_PLATFORM_ID).scout   golden stdout+stderr+exit code of entry NAME on this platform (recorded, then diffed; e.g.
#                       NAME.macos_applesilicon.scout; a run compares only with its own platform's golden, tools/README.md)
#   sout.sed            (optional) sed -E script applied to every entry's NAME.sout after its run (paired entries too), for what varies
#                       between runs (e.g. where the runtime's own lines land)
#
# Targets:
#   build           silica.config -> compile (reclaim loop) -> assemble -> link every entry
#   run             run every entry, writing NAME.sout
#   integrate       build + run + diff against the platform's .scout / .golden_fail; non-zero on any miss
#   record-golden   build + run, then copy .sout -> .PLATFORM.scout and .cur_fail -> .PLATFORM.golden_fail
#   clean           remove everything generated
#
# Every recipe cds into the leaf, because silica-compiler reads silica.config from the
# working directory and takes no arguments.

LEAF := $(patsubst %/,%,$(dir $(abspath $(firstword $(MAKEFILE_LIST)))))
LEAF_NAME := $(notdir $(LEAF))
include $(BEES_ROOT)/tools/silica.mk
TOPO := $(BEES_ROOT)/tools/topo_silica_config.sh

BEES_CONFIG := $(BEES_ROOT)/tools/bees_config.py
MANIFESTS   := $(strip $(filter-out %/silica.atoms,$(wildcard $(LEAF)/lib/*.atoms) $(wildcard $(LEAF)/*.atoms)) \
                $(wildcard $(LEAF)/lib/*.module) $(wildcard $(LEAF)/*.module) \
                $(wildcard $(LEAF)/lib/*.pools) $(wildcard $(LEAF)/*.pools) \
                $(wildcard $(LEAF)/lib/*.wire) $(wildcard $(LEAF)/*.wire))

# NAME.pair names two entries that must run at the same time (a listener and a connector): the file
# holds their two entry names, and tools/run_pair.py runs both, writing each one's .sout.
PAIR_FILES  := $(sort $(notdir $(wildcard $(LEAF)/*.pair)))
# (cat with no file names would read the standard input, so it is only run when there are .pair files)
PAIRED      := $(sort $(if $(PAIR_FILES),$(shell cat $(addprefix $(LEAF)/,$(PAIR_FILES)) 2>/dev/null)))
ALL_UNITS   := $(sort $(notdir $(wildcard $(LEAF)/*.silica)))
FAIL_UNITS  := $(filter fail_% dangerous_fail_%,$(ALL_UNITS))
ENTRY_UNITS := $(filter-out fail_% dangerous_fail_%,$(ALL_UNITS))
ENTRIES     := $(ENTRY_UNITS:.silica=)
LIB_UNITS   := $(sort $(notdir $(wildcard $(LEAF)/lib/*.silica)))

.DEFAULT_GOAL := build
.PHONY: build run integrate record-golden clean help silica.config units bees_atoms

units:
	@echo "lib: $(LIB_UNITS)"; echo "entries: $(ENTRIES)"; echo "fail: $(FAIL_UNITS)"

# bees_atoms (D30): when the leaf or its lib has manifests (.atoms, .module, .pools), bees_config
# generates lib/bees_atoms.silica, and lib/bees_modules.silica and lib/bees_ids.silica where there
# are .module and .pools manifests, lib/bees_peers.silica + lib/bees_msgs.silica where a .wire manifest has node lines
# (the language's encode/decode behind enc_/dec_), and lib/bees_wire_tables.silica + lib/bees_wire_ints.silica +
# lib/bees_wire_msgs.silica where a .wire manifest has none (the typed codec of the m1 trials), before anything is
# compiled, and checks that no other unit writes a BEAM atom literal. A leaf with a bees.config passes it (--config) to the one
# reader, tools/bees_conf.py (N0.2, a build-time stand-in): its values win over the manifest's, a violation stops the build.
bees_atoms:
	@cd "$(LEAF)" && if [ -n "$(MANIFESTS)" ]; then \
		mkdir -p lib && "$(BEES_CONFIG)" generate -o lib $(if $(wildcard $(LEAF)/bees.config),--config bees.config) $(MANIFESTS) && \
		"$(BEES_CONFIG)" check lib/*.silica *.silica; \
	fi

# silica.config lists lib units and entry units in use-dependency order; fail_* stay out.
silica.config: bees_atoms
	@cd "$(LEAF)" && "$(TOPO)" "$(LEAF)" | grep -Ev '^(dangerous_)?fail_' > silica.config

# Stale products of an earlier build, and the compiler's crash records (silica.compile.crashed, .inprogress), which survive
# between batches unless removed (Silica's own Makefile removes them too).
CLEAN_BUILD = rm -f *.sams *.iface *.o lib/*.sams lib/*.iface lib/*.o \
		silica.compile.order silica.compile.crashed silica.compile.inprogress silica.needs_runtime silica.link __silica_runtime.sams

# Compile with one retry (the "Flakes" section of development-plan/silica-defects.md): the compiler now and then dies on a unit with no diagnostic (silica-999925, once in a
# full `make integrate`: m1_wire_types_lists_b, lib/bees_wire_tables.silica; the same leaf then passed every time alone). Its
# crash record is the line "Error: the compiler crashed while compiling ..." and exit 1. When, and only when, that line is in the
# output, the build is cleaned and compiled once more, and the retry is announced with a line starting "RETRY"; a second crash
# fails the build, and a real compile error (diagnostics, no crash line) is never retried or hidden. Each attempt's output is
# shown in full.
build: silica.config
	@cd "$(LEAF)" && $(CLEAN_BUILD)
	@cd "$(LEAF)" && echo "[$(LEAF_NAME)] compiling $$(grep -c . silica.config) units" && attempt=1 && while true; do \
		( $(RUN_SILICA_COMPILER) ) > silica.compile.attempt.log 2>&1; rc=$$?; cat silica.compile.attempt.log; \
		if [ $$rc -eq 0 ]; then break; fi; \
		if [ $$attempt -eq 1 ] && grep -q 'the compiler crashed while compiling' silica.compile.attempt.log; then \
			echo "RETRY: [$(LEAF_NAME)] the compiler crashed (a known transient, see the Flakes section of development-plan/silica-defects.md); cleaning and compiling once more"; \
			attempt=2; $(CLEAN_BUILD); continue; fi; \
		rm -f silica.compile.attempt.log; exit $$rc; \
	done; rm -f silica.compile.attempt.log
	@cd "$(LEAF)" && for sams in *.sams lib/*.sams; do \
		[ -f "$$sams" ] || continue; \
		$(CLANG) $(ASFLAGS) -c -x assembler "$$sams" -o "$${sams%.sams}.o" || exit 1; \
	done
	@cd "$(LEAF)" && libs=""; for o in lib/*.o; do [ -f "$$o" ] && libs="$$libs $$o"; done; \
	rt=""; [ -f __silica_runtime.o ] && rt=__silica_runtime.o; \
	archives=""; [ -f silica.link ] && archives=$$(awk -F'"' '/^archive:/ { printf "%s ", $$2 }' silica.link); \
	case "$$archives" in *libsilica_bees_tls.a*) archives="$$archives $(OPENSSL_LDFLAGS)";; esac; \
	case "$$archives" in *libsilica_bees_native.a*) archives="$$archives $(NATIVE_CRYPTO_LDFLAGS)";; esac; \
	for e in $(ENTRIES); do \
		[ -f "$$e.o" ] || { echo "FAIL: [$(LEAF_NAME)] $$e.o missing"; exit 1; }; \
		$(CLANG) "$$e.o" $$libs $$rt $$archives $(LDFLAGS) -o "$$e" || exit 1; \
	done; \
	echo "[$(LEAF_NAME)] built: $(ENTRIES)"

run: build
	@cd "$(LEAF)" && for e in $(filter-out $(PAIRED),$(ENTRIES)); do $(call RUN_TRIAL,./$$e,$$e.sout); \
		if [ -f sout.sed ]; then $(SED_I) -E -f sout.sed "$$e.sout"; fi; done
	@cd "$(LEAF)" && for p in $(PAIR_FILES); do \
		set -- $$(cat "$$p"); \
		"$(BEES_ROOT)/tools/run_pair.py" "./$$1" "$$1.sout" "$$(cat "$$1.wait_for_exit")" "./$$2" "$$2.sout" "$$(cat "$$2.wait_for_exit")"; \
		$(SED_I) -E 's/0x[0-9a-f]{6,}/0xADDR/g' "$$1.sout" "$$2.sout"; $(STRIP_CARRIER_END) "$$1.sout" "$$2.sout"; \
		if [ -f sout.sed ]; then $(SED_I) -E -f sout.sed "$$1.sout" "$$2.sout"; fi; \
	done

# Compile-fail trials: each is compiled alone in .fail/NAME/ with the leaf's lib/ beside it, so
# the paths in the compiler's diagnostics are stable. Output goes to NAME.cur_fail.
# Shell function; $$1 is the unit file name.
define COMPILE_FAIL_FN
compile_fail() { \
	n="$${1%.silica}"; d=".fail/$$n"; rm -rf "$$d"; mkdir -p "$$d"; \
	ln -s "../../$$1" "$$d/$$1"; [ -d lib ] && ln -s ../../lib "$$d/lib"; \
	[ -e dangerous_exposure_source ] && ln -s ../../dangerous_exposure_source "$$d/dangerous_exposure_source"; \
	( cd "$$d" && "$(TOPO)" . > silica.config && \
	  { $(WITH_SLOT) "$(SILICA_COMPILER)" > "../../$$n.cur_fail" 2>&1; echo "exit=$$?" >> "../../$$n.cur_fail"; } ); \
	$(SED_I) -E 's/0x[0-9a-f]{6,}/0xADDR/g' "$$n.cur_fail"; \
}
endef

integrate: run
	@cd "$(LEAF)" && ok=0; ko=0; \
	for e in $(ENTRIES); do \
		if [ ! -f "$$e$(GOLD_SUFFIX).scout" ]; then echo "MISSING golden for $(BEES_PLATFORM_ID) (record one on this platform with make record-golden): [$(LEAF_NAME)] $$e$(GOLD_SUFFIX).scout"; ko=$$((ko+1)); \
		elif diff -Bw -q "$$e.sout" "$$e$(GOLD_SUFFIX).scout" > /dev/null; then ok=$$((ok+1)); \
		else echo "DIFF: [$(LEAF_NAME)] $$e"; diff -Bw "$$e$(GOLD_SUFFIX).scout" "$$e.sout" || true; ko=$$((ko+1)); fi; \
	done; \
	$(COMPILE_FAIL_FN); \
	for f in $(FAIL_UNITS); do \
		compile_fail "$$f"; \
		g="$${f%.silica}$(GOLD_SUFFIX).golden_fail"; c="$${f%.silica}.cur_fail"; \
		if [ ! -f "$$g" ]; then echo "MISSING golden for $(BEES_PLATFORM_ID) (record one on this platform with make record-golden): [$(LEAF_NAME)] $$g"; ko=$$((ko+1)); \
		elif grep -q '^exit=0$$' "$$c"; then echo "COMPILED BUT SHOULD FAIL: [$(LEAF_NAME)] $$f"; ko=$$((ko+1)); \
		elif diff -Bw -q "$$c" "$$g" > /dev/null; then ok=$$((ok+1)); \
		else echo "DIFF: [$(LEAF_NAME)] $$f"; diff -Bw "$$g" "$$c" || true; ko=$$((ko+1)); fi; \
	done; \
	printf '%d %d\n' "$$ok" "$$ko" > .integrate_counts; \
	echo "[$(LEAF_NAME)] $$ok passed, $$ko failed"; [ "$$ko" -eq 0 ]

record-golden: run
	@cd "$(LEAF)" && for e in $(ENTRIES); do cp "$$e.sout" "$$e$(GOLD_SUFFIX).scout"; done; \
	$(COMPILE_FAIL_FN); \
	for f in $(FAIL_UNITS); do compile_fail "$$f"; cp "$${f%.silica}.cur_fail" "$${f%.silica}$(GOLD_SUFFIX).golden_fail"; done; \
	echo "[$(LEAF_NAME)] goldens recorded"

clean:
	@cd "$(LEAF)" && rm -rf *.sams *.iface *.o *.sout *.cur_fail lib/*.sams lib/*.iface lib/*.o .fail *.silica.derived lib/*.silica.derived \
		lib/bees_atoms.silica lib/bees_atoms.index lib/bees_modules.silica lib/bees_ids.silica \
		lib/bees_wire_tables.silica lib/bees_wire_ints.silica lib/bees_wire_msgs.silica lib/bees_msgs.silica lib/bees_peers.silica \
		silica.config silica.compile.order silica.compile.crashed silica.compile.inprogress silica.needs_runtime silica.link .integrate_counts $(ENTRIES)

help:
	@echo "targets: build run integrate record-golden clean units"; echo "compiler: $(SILICA_COMPILER)"
