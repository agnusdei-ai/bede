#!/usr/bin/env bash
# Bede owner-operated, non-destructive Mac Docker smoke check.
# Does not seed users, touch subscriptions, reset databases or claim G1/G2/G3 passed.
set -Eeuo pipefail
cd "$(dirname "$0")/.."
MODE="${1:-check}"
if [[ "$MODE" != start && "$MODE" != check ]]; then
  echo "Usage: bash scripts/pilot-smoke.sh [start|check]" >&2
  exit 2
fi
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="pilot-evidence/$STAMP"
mkdir -p "$OUT"
chmod 700 pilot-evidence "$OUT"
exec > >(tee "$OUT/terminal.log") 2>&1
pass=0; fail=0; blocked=0
record() {
  local name="$1" state="$2" detail="$3"
  printf '%s | %s | %s\n' "$state" "$name" "$detail" | tee -a "$OUT/results.txt"
  case "$state" in PASS) pass=$((pass+1));; FAIL) fail=$((fail+1));; *) blocked=$((blocked+1));; esac
}
echo "Bede Mac pilot smoke; UTC $STAMP; mode=$MODE"
echo "Evidence directory: $OUT (private; inspect before sharing)"
echo "SHA: $(git rev-parse HEAD 2>/dev/null || echo unknown)" | tee "$OUT/revision.txt"
uname -srm | tee "$OUT/host.txt"
if ! command -v docker >/dev/null 2>&1 || ! docker info >/dev/null 2>&1; then
  record docker FAIL "Docker Desktop must be running"; exit 1
fi
if ! docker compose version >/dev/null 2>&1; then record compose FAIL "Compose plugin missing"; exit 1; fi
record docker PASS "Docker daemon and Compose available"
if [[ ! -f .env ]]; then record config BLOCKED "Run Bede setup wizard first to generate .env"; exit 2; fi
if ! docker compose config --quiet >/dev/null 2>&1; then
  record config FAIL "Compose config invalid; secrets withheld from logs"; exit 1
fi
record config PASS "Compose config parses (values not printed)"
# Never use a real-data deployment for the local synthetic qualification.
# Explicit operator acknowledgement is required for service startup.
if [[ "$MODE" == start && "${BEDE_SYNTHETIC_ONLY:-}" != "1" ]]; then
  record synthetic-scope BLOCKED "Set BEDE_SYNTHETIC_ONLY=1 after verifying disposable local data"
  exit 2
fi
if [[ "$MODE" == start ]]; then
  echo "Starting existing Bede Compose services; images may build on first run."
  if docker compose up -d --wait --wait-timeout 180; then record startup PASS "Compose services running/healthy"; else record startup FAIL "Compose readiness timed out"; fi
fi
docker compose ps --format json > "$OUT/compose-status.json" 2>/dev/null || true
# A 200 over --insecure is NOT a trusted HTTPS result. Never disable TLS
# verification in acceptance checks. The packaged Verify-Bede.command is the
# authoritative source-free operator path; this source-checkout helper may
# only claim HTTPS health with the locally issued CA present.
if [[ ! -s bede-root-ca.crt ]]; then
  record health BLOCKED "Trusted local CA missing; use packaged Verify-Bede.command"
elif curl --silent --show-error --fail --max-time 12 --cacert bede-root-ca.crt https://localhost/api/health > "$OUT/health.json"; then
  record health PASS "Local HTTPS health verified with the trusted instance CA"
else
  record health FAIL "HTTPS health or certificate verification failed"
fi
echo
echo "Manual checks (never auto-marked PASS):"
cat <<'CHECKS' | tee "$OUT/manual-gates.txt"
G1 NOT RUN: In disposable synthetic data, campus A teacher can open assigned learner A, but not campus B or unassigned learner. Revoke access and retry.
G2 NOT RUN: Open authorized learner, inspect cited evidence, generate recommendation, approve/edit/reject separately, refresh and confirm each saved decision.
G3 NOT RUN: Check approved campus list, manual grant/revoke and disable access, support contact and baseline time/feedback. Run a separately reviewed destructive recovery drill ONLY on a disposable instance.
PILOT BOUNDARY NOT RUN: Confirm no self-service purchasing, Stripe entitlement dependency, day-2 purchase notices, automatic conversion or retained_trial_access promise.
CHECKS
printf 'AUTOMATED: PASS=%s FAIL=%s BLOCKED=%s; G1/G2/G3=NOT RUN\n' "$pass" "$fail" "$blocked" | tee "$OUT/summary.txt"
echo "Logs saved in $OUT. Do not upload .env, keys, learner records or raw sensitive logs."
[[ "$fail" == 0 && "$blocked" == 0 ]]
