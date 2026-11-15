#!/usr/bin/env bash
# Copy the native crash reports macOS wrote during this job, and print the
# start of each, so a WebKit "Page crashed" can be read as a real stack
# instead of a Playwright event with no backtrace.
#
#   collect_crash_reports.sh <marker-file> <dest-dir> <report-dir>...
#
# Only reports newer than the marker (touched when the job started) are
# taken, so a runner's older reports never appear as this run's. Matches
# the WebKit/Playwright processes and JetsamEvent: a memory-pressure kill
# leaves a Jetsam report and no crash report, so its presence or absence
# is part of the answer. Sample data only; a report holds process and
# stack state, not learner content.
#
# Diagnostic only: it always exits 0, so it can never turn a row green or
# red. The row's result stays the journeys' own.
set -u
marker="${1:-}"; dest="${2:-}"
if [ -z "$marker" ] || [ -z "$dest" ]; then
  echo "usage: collect_crash_reports.sh <marker-file> <dest-dir> <report-dir>..."; exit 0
fi
shift 2
mkdir -p "$dest" 2>/dev/null || true
if [ ! -f "$marker" ]; then
  echo "crash reports: no job-start marker at $marker; nothing collected"; exit 0
fi
found=0
for dir in "$@"; do
  [ -d "$dir" ] || { echo "crash reports: $dir does not exist"; continue; }
  while IFS= read -r -d '' f; do
    name=$(basename "$f")
    case "$name" in
      *WebKit*|*WebContent*|*webkit*|*Playwright*|*pw_run*|*JetsamEvent*) ;;
      *) continue ;;
    esac
    cp "$f" "$dest/" 2>/dev/null || continue
    found=$((found + 1))
    echo "===== crash report: $name ====="
    head -n 80 "$f"
    echo "===== end of excerpt: $name ====="
  done < <(find "$dir" -maxdepth 1 -type f \( -name '*.ips' -o -name '*.crash' \) -newer "$marker" -print0 2>/dev/null)
done
echo "crash reports collected: $found"
exit 0
