#!/usr/bin/env bash
# Builds and runs bees_board_balance on the ESP32-S3 twice: balanced, and the control with no balance check.
# The program is loaded into the board's RAM over the console jack (nothing is written to flash).
#
#   run.sh --build-only     compile and link both images; touches no board
#   run.sh                  run both and compare: the balanced run must show 2 2 and at least 1.5 times the control's
#                           dispatches per second, the control 4 0
#
# Environment: SILICA_ROOT (default ../silica next to this repository), BOARD_SILICA_COMPILER, BOARD_PORT,
# BOARD_PYTHON (as examples/esp32s3_trust_serial/run.sh).
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
BEES="$(cd "$HERE/../.." && pwd)"
SILICA="${SILICA_ROOT:-$(cd "$BEES/../silica" && pwd)}"
BOARD_CC="${BOARD_SILICA_COMPILER:-$SILICA/binaries/silica-compiler-ESP32-S3_raw}"
export BOARD_PYTHON="${BOARD_PYTHON:-$HOME/.espressif/python_env/idf6.2_py3.14_env/bin/python}"
RUN_APP="$SILICA/compiler/src/emitter/ESP32-S3_raw/board/tools/run_app.sh"
WORK="$HERE/build"
APP=bees_board_balance
MODE=board
[ "${1:-}" = "--build-only" ] && MODE=build
die() { echo "run: $1" >&2; exit 1; }
[ -x "$BOARD_CC" ] || die "no ESP32-S3_raw compiler at $BOARD_CC"
rel() { python3 -c 'import os,sys; print(os.path.relpath(sys.argv[1], sys.argv[2]))' "$1" "$SILICA/compiler"; }

mkdir -p "$WORK"
for kind in balanced control; do
    d="$WORK/$kind/$APP"
    mkdir -p "$d"
    if [ $kind = control ]; then
        sed 's/^fn check_every() -> int64 { 512 }$/fn check_every() -> int64 { 1000000000000 }/' "$HERE/$APP.silica" > "$d/$APP.silica"
        cmp -s "$HERE/$APP.silica" "$d/$APP.silica" && die "the control's check_every() line was not found"
    else
        cp "$HERE/$APP.silica" "$d/$APP.silica"
    fi
    { rel "$BEES/src/shim/bees_reporter.silica"; rel "$BEES/src/shim/bees_place.silica"; } > "$d/extra_sources.txt"
done

if [ "$MODE" = build ]; then
    for kind in balanced control; do
        SILICA_COMPILER="$BOARD_CC" "$RUN_APP" --build-only "$WORK/$kind/$APP" || exit 1
    done
    exit 0
fi

if [ -z "${BOARD_PORT:-}" ]; then
    set -- /dev/cu.usbserial-*
    [ $# -eq 1 ] && [ -e "$1" ] || die "set BOARD_PORT: expected exactly one /dev/cu.usbserial-* console port"
    BOARD_PORT=$1
fi
for kind in balanced control; do
    SILICA_COMPILER="$BOARD_CC" "$RUN_APP" --port "$BOARD_PORT" --timeout 60 "$WORK/$kind/$APP" > "$WORK/$kind.log" 2>&1
    echo "--- $kind (run_app exit $?):"
    grep -a "workers per core\|dispatches per second\|\[silica\]\|run_app: \(FAIL\|PASS\|timeout\)" "$WORK/$kind.log"
done
rate() { grep -a "dispatches per second" "$WORK/$1.log" | tr -dc '0-9\n' | head -1; }
b=$(rate balanced); c=$(rate control)
ok=1
grep -aq "^workers per core: 2 2" "$WORK/balanced.log" || ok=0
grep -aq "^workers per core: 4 0" "$WORK/control.log" || ok=0
[ -n "$b" ] && [ -n "$c" ] && [ "$c" -gt 0 ] && [ $((b * 10)) -ge $((c * 15)) ] || ok=0
[ -n "$b" ] && [ -n "$c" ] && [ "$c" -gt 0 ] && echo "run: balanced does $((b * 100 / c)) % of the control's dispatches per second"
[ $ok = 1 ] && { echo "=== PASS"; exit 0; }
echo "=== FAIL"; exit 1
