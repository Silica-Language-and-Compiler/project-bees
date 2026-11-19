#!/bin/sh
# Builds the probe without the BEES tree (used on the Linux box, where only this directory is copied).
#   SILICA_COMPILER=... SILICA_ROOT=... sh standalone_build.sh
# Flags as in native/linux/platform.mk (-no-pie -rdynamic -lpthread); on the Mac use `make build` instead.
set -e
cd "$(dirname "$0")"
CC=$(command -v clang || echo cc)
ENTRIES="a_ticker_first b_busy_first c_two_busy d_migrate_away e_migrate_onto"
sh ./gen.sh
rm -f *.sams *.iface *.o silica.compile.order silica.compile.crashed silica.compile.inprogress silica.needs_runtime silica.link
: > silica.config
for e in $ENTRIES; do echo "$e.silica" >> silica.config; done
while true; do
  set +e; "$SILICA_COMPILER" > compile.log 2>&1; ec=$?; set -e
  [ $ec -eq 0 ] && break
  [ $ec -eq 75 ] && continue
  tail -40 compile.log; exit $ec
done
for s in *.sams; do $CC -c -x assembler "$s" -o "${s%.sams}.o"; done
for e in $ENTRIES; do $CC "$e.o" __silica_runtime.o -no-pie -rdynamic -lpthread -o "$e"; done
echo "built: $ENTRIES"
