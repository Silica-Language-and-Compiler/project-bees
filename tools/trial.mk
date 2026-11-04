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
#   fail_*.silica       compile-fail trials, compiled in isolation; the compiler's output is
#                       the golden (.golden_fail)
#   NAME.scout          golden stdout+stderr+exit code of entry NAME (recorded, then diffed)
#
# Targets:
#   build           silica.config -> compile (reclaim loop) -> assemble -> link every entry
#   run             run every entry, writing NAME.sout
#   integrate       build + run + diff against .scout / .golden_fail; non-zero on any miss
#   record-golden   build + run, then copy .sout -> .scout and .cur_fail -> .golden_fail
#   clean           remove everything generated
#
# Every recipe cds into the leaf, because silica-compiler reads silica.config from the
# working directory and takes no arguments.

LEAF := $(patsubst %/,%,$(dir $(abspath $(firstword $(MAKEFILE_LIST)))))
LEAF_NAME := $(notdir $(LEAF))
include $(BEES_ROOT)/tools/silica.mk
TOPO := $(BEES_ROOT)/tools/topo_silica_config.sh

BEES_CONFIG := $(BEES_ROOT)/tools/bees_config.py
MANIFESTS   := $(strip $(filter-out %/silica.atoms,$(wildcard $(LEAF)/lib/*.atoms) $(wildcard $(LEAF)/*.atoms)))

ALL_UNITS   := $(sort $(notdir $(wildcard $(LEAF)/*.silica)))
FAIL_UNITS  := $(filter fail_%,$(ALL_UNITS))
ENTRY_UNITS := $(filter-out fail_%,$(ALL_UNITS))
ENTRIES     := $(ENTRY_UNITS:.silica=)
LIB_UNITS   := $(sort $(notdir $(wildcard $(LEAF)/lib/*.silica)))

.DEFAULT_GOAL := build
.PHONY: build run integrate record-golden clean help silica.config units bees_atoms

units:
	@echo "lib: $(LIB_UNITS)"; echo "entries: $(ENTRIES)"; echo "fail: $(FAIL_UNITS)"

# bees_atoms (D30): when the leaf or its lib has atom manifests, bees_config generates
# lib/bees_atoms.silica from them before anything is compiled, and checks that no other unit
# writes a BEAM atom literal.
bees_atoms:
	@cd "$(LEAF)" && if [ -n "$(MANIFESTS)" ]; then \
		mkdir -p lib && "$(BEES_CONFIG)" atoms -o lib $(MANIFESTS) && \
		"$(BEES_CONFIG)" check lib/*.silica *.silica; \
	fi

# silica.config lists lib units and entry units in use-dependency order; fail_* stay out.
silica.config: bees_atoms
	@cd "$(LEAF)" && "$(TOPO)" "$(LEAF)" | grep -v '^fail_' > silica.config

build: silica.config
	@cd "$(LEAF)" && rm -f *.sams *.iface *.o lib/*.sams lib/*.iface lib/*.o \
		silica.compile.order silica.needs_runtime silica.link __silica_runtime.sams
	@cd "$(LEAF)" && echo "[$(LEAF_NAME)] compiling $$(grep -c . silica.config) units" && $(RUN_SILICA_COMPILER)
	@cd "$(LEAF)" && for sams in *.sams lib/*.sams; do \
		[ -f "$$sams" ] || continue; \
		$(CLANG) $(ASFLAGS) -c -x assembler "$$sams" -o "$${sams%.sams}.o" || exit 1; \
	done
	@cd "$(LEAF)" && libs=""; for o in lib/*.o; do [ -f "$$o" ] && libs="$$libs $$o"; done; \
	rt=""; [ -f __silica_runtime.o ] && rt=__silica_runtime.o; \
	archives=""; [ -f silica.link ] && archives=$$(awk -F'"' '/^archive:/ { printf "%s ", $$2 }' silica.link); \
	for e in $(ENTRIES); do \
		[ -f "$$e.o" ] || { echo "FAIL: [$(LEAF_NAME)] $$e.o missing"; exit 1; }; \
		$(CLANG) "$$e.o" $$libs $$rt $$archives $(LDFLAGS) -o "$$e" || exit 1; \
	done; \
	echo "[$(LEAF_NAME)] built: $(ENTRIES)"

run: build
	@cd "$(LEAF)" && for e in $(ENTRIES); do $(call RUN_TRIAL,./$$e,$$e.sout); done

# Compile-fail trials: each is compiled alone in .fail/NAME/ with the leaf's lib/ beside it, so
# the paths in the compiler's diagnostics are stable. Output goes to NAME.cur_fail.
# Shell function; $$1 is the unit file name.
define COMPILE_FAIL_FN
compile_fail() { \
	n="$${1%.silica}"; d=".fail/$$n"; rm -rf "$$d"; mkdir -p "$$d"; \
	ln -s "../../$$1" "$$d/$$1"; [ -d lib ] && ln -s ../../lib "$$d/lib"; \
	( cd "$$d" && "$(TOPO)" . > silica.config && \
	  { "$(SILICA_COMPILER)" > "../../$$n.cur_fail" 2>&1; echo "exit=$$?" >> "../../$$n.cur_fail"; } ); \
	sed -i '' -E 's/0x[0-9a-f]{6,}/0xADDR/g' "$$n.cur_fail"; \
}
endef

integrate: run
	@cd "$(LEAF)" && ok=0; ko=0; \
	for e in $(ENTRIES); do \
		if [ ! -f "$$e.scout" ]; then echo "MISSING golden: [$(LEAF_NAME)] $$e.scout"; ko=$$((ko+1)); \
		elif diff -Bw -q "$$e.sout" "$$e.scout" > /dev/null; then ok=$$((ok+1)); \
		else echo "DIFF: [$(LEAF_NAME)] $$e"; diff -Bw "$$e.scout" "$$e.sout" || true; ko=$$((ko+1)); fi; \
	done; \
	$(COMPILE_FAIL_FN); \
	for f in $(FAIL_UNITS); do \
		compile_fail "$$f"; \
		g="$${f%.silica}.golden_fail"; c="$${f%.silica}.cur_fail"; \
		if [ ! -f "$$g" ]; then echo "MISSING golden: [$(LEAF_NAME)] $$g"; ko=$$((ko+1)); \
		elif grep -q '^exit=0$$' "$$c"; then echo "COMPILED BUT SHOULD FAIL: [$(LEAF_NAME)] $$f"; ko=$$((ko+1)); \
		elif diff -Bw -q "$$c" "$$g" > /dev/null; then ok=$$((ok+1)); \
		else echo "DIFF: [$(LEAF_NAME)] $$f"; diff -Bw "$$g" "$$c" || true; ko=$$((ko+1)); fi; \
	done; \
	printf '%d %d\n' "$$ok" "$$ko" > .integrate_counts; \
	echo "[$(LEAF_NAME)] $$ok passed, $$ko failed"; [ "$$ko" -eq 0 ]

record-golden: run
	@cd "$(LEAF)" && for e in $(ENTRIES); do cp "$$e.sout" "$$e.scout"; done; \
	$(COMPILE_FAIL_FN); \
	for f in $(FAIL_UNITS); do compile_fail "$$f"; cp "$${f%.silica}.cur_fail" "$${f%.silica}.golden_fail"; done; \
	echo "[$(LEAF_NAME)] goldens recorded"

clean:
	@cd "$(LEAF)" && rm -rf *.sams *.iface *.o *.sout *.cur_fail lib/*.sams lib/*.iface lib/*.o .fail \
		lib/bees_atoms.silica lib/bees_atoms.index \
		silica.config silica.compile.order silica.needs_runtime silica.link .integrate_counts $(ENTRIES)

help:
	@echo "targets: build run integrate record-golden clean units"; echo "compiler: $(SILICA_COMPILER)"
