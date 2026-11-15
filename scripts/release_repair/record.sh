#!/usr/bin/env bash
# Driver for release-repair.yml's `record` job. Runs from the TRUSTED checkout.
# Exit 0: state applied (and published if it changed). Exit 2: BLOCKED (the
# state could not be trusted). Exit 3: INFRA_ERROR (retry: a newer snapshot
# appeared, or the candidate job produced no evidence). Nothing here pushes,
# merges or deploys.
set -euo pipefail
RR=.rr
mkdir -p "$RR/events" "$RR/evidence"
CTRL=(python3 scripts/release_repair/controller.py --cycle "$CYCLE" --work "$RR/work"
      --acceptance "config/acceptance/$ACCEPTANCE" --controller-revision "$CONTROLLER_REVISION"
      --run-id "$RUN_ID" --run-attempt "$RUN_ATTEMPT" --summary-out "$RR/result.json")

events=()
if [ -n "${EVENT_JSON:-}" ]; then
  printf '%s' "$EVENT_JSON" > "$RR/events/00-input.json"
  events+=("$RR/events/00-input.json")
fi
if [ -n "${RESULTS_RUNS:-}" ]; then
  SHA="${CANDIDATE_SHA:-}"
  python3 scripts/release_repair/collect_results.py --runs "$RESULTS_RUNS" --sha "${SHA:?candidate_sha is required with results_runs}" \
    --event-id "results-$RUN_ID-$RUN_ATTEMPT" --out "$RR/events/10-results.json"
  events+=("$RR/events/10-results.json")
fi
if [ -n "${RESOLVED_SHA:-}" ]; then
  if [ ! -f ../candidate-out/regression.json ]; then
    echo '{"status":"INFRA_ERROR","reason":"candidate job produced no evidence; no repair attempt spent"}'
    exit 3
  fi
  python3 scripts/release_repair/validate.py --repo ../candidate-data --base "$BASE_SHA" --head "$RESOLVED_SHA" \
    --branch "$BRANCH" --out "$RR/validation.json"
  python3 scripts/release_repair/build_event.py --task-id "$TASK_ID" --branch "$BRANCH" --base "$BASE_SHA" \
    --resolved "$RESOLVED_SHA" --validation "$RR/validation.json" --regression ../candidate-out/regression.json \
    --run-id "$RUN_ID" --run-attempt "$RUN_ATTEMPT" --controller-revision "$CONTROLLER_REVISION" \
    --out "$RR/events/20-verification.json"
  events+=("$RR/events/20-verification.json")
fi
python3 - "$RR/events/all.json" "${events[@]}" <<'PY'
import json, sys
out, items = sys.argv[1], []
for f in sys.argv[2:]:
    d = json.load(open(f))
    items += d if isinstance(d, list) else [d]
json.dump(items, open(out, "w"))
PY

if [ "$ACTION" = "start" ]; then
  # A cycle starts once. A second start would create a second sequence 0,
  # which every later load would refuse as ambiguous.
  # Fail closed: start only on a clear "no snapshot exists" answer, never on
  # an API error, which would otherwise let a lookup failure double-start.
  set +e
  python3 scripts/release_repair/artifacts.py latest --cycle "$CYCLE" --out "$RR/existing" > "$RR/existing.json"
  code=$?
  set -e
  if [ "$code" -ne 2 ] || ! grep -q '"snapshot_missing"' "$RR/existing.json"; then
    echo '{"status":"refused","reason":"cycle_already_started_or_lookup_failed"}'; exit 2
  fi
  printf '{"candidate_sha": "%s"}' "$CANDIDATE_SHA" > "$RR/events/start.json"
  "${CTRL[@]}" --action start --event "$RR/events/start.json" --snapshot-out "$RR/snapshot-out"
  LOADED=-1
else
  set +e
  python3 scripts/release_repair/artifacts.py latest --cycle "$CYCLE" --out "$RR/snapshot-in" | tee "$RR/load.json"
  code=${PIPESTATUS[0]}
  set -e
  [ "$code" -eq 0 ] || exit "$code"
  LOADED=$(python3 -c "import json; print(json.load(open('$RR/load.json'))['sequence'])")
  if [ "$ACTION" = "status" ]; then
    "${CTRL[@]}" --action status --snapshot-in "$RR/snapshot-in"
  else
    "${CTRL[@]}" --action record --event "$RR/events/all.json" --snapshot-in "$RR/snapshot-in" --snapshot-out "$RR/snapshot-out"
  fi
fi

python3 - "$RR" <<'PY'
import json, sys
from pathlib import Path
sys.path.insert(0, "scripts")
from release_repair import evidence
rr = Path(sys.argv[1])
res = json.loads((rr / "result.json").read_text())
evidence.write(rr / "evidence", res["summary"])
summary = evidence.markdown(res["summary"])
ack = json.dumps(res.get("ack", []), indent=2)
import os
with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as fp:
    fp.write(summary + "\n### Acknowledged events\n\n```json\n" + ack + "\n```\n")
print("ACK " + json.dumps(res.get("ack", [])))
PY
echo "evidence=true" >> "$GITHUB_OUTPUT"

if [ "$ACTION" != "status" ]; then
  SEQ=$(python3 -c "import json; print(json.load(open('$RR/snapshot-out/snapshot.json'))['state_sequence'])")
  if [ "$ACTION" != "start" ]; then
    python3 scripts/release_repair/artifacts.py check-unchanged --cycle "$CYCLE" --loaded-sequence "$LOADED"
  fi
  echo "sequence=$SEQ" >> "$GITHUB_OUTPUT"
  echo "publish=true" >> "$GITHUB_OUTPUT"
fi
