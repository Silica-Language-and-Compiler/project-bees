#!/usr/bin/env bash
# Run every BEES trial in parallel on this machine, and on the remote machines of .bees_build_hosts.
#
#   tools/run_all_trials.sh                    all trials here (-j = cores minus one, BEES_JOBS), plus the remotes if the file exists
#   tools/run_all_trials.sh -j 4               at most 4 trials at a time
#   tools/run_all_trials.sh --compile-jobs 1   at most 1 Silica compile at a time (BEES_COMPILE_JOBS; default 2)
#   tools/run_all_trials.sh --only n3_trust,s01_trait_mapping
#   tools/run_all_trials.sh --local-only       this machine only (what a remote runs)
#   tools/run_all_trials.sh --list             what would run, where; --dry-run prints every command
#
# The work is in tools/run_all_trials.py (modelled on silica's programmer_tools/run_trials_all_platforms.sh); the options are
# documented in tools/README.md. Remote machines are reached with key-based ssh in batch mode only: check one with
#   ssh -o BatchMode=yes user@host true
# Exit status 0 only when every trial that ran passed; a platform whose build is not supported yet is reported SKIPPED.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
command -v python3 >/dev/null || { echo "run_all_trials: python3 is required" >&2; exit 2; }
exec python3 "$HERE/run_all_trials.py" "$@"
