#!/usr/bin/env bash
# Non-destructive, source-free operator verification for Mac installers.
set -Eeuo pipefail
cd "$(dirname "$0")"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
out="bede-evidence/$stamp"
mkdir -p "$out"
chmod 700 bede-evidence "$out"
exec > >(tee "$out/summary.txt") 2>&1
echo "Bede operator verification — $stamp"
echo "Only synthetic data may be entered in this pre-release environment."
echo "Release SHA: $(cat RELEASE 2>/dev/null || echo missing)"
echo "Bundle CPU: $(cat ARCH 2>/dev/null || echo missing)"
echo "Host: $(uname -srm)"
if command -v sw_vers >/dev/null 2>&1; then echo "macOS: $(sw_vers -productVersion)"; fi
if ! docker info >/dev/null 2>&1; then
  echo "BLOCKED: Docker Desktop must be running."; exit 2
fi
echo "Docker CPU: $(docker info --format '{{.Architecture}}')"
docker compose version
if [[ ! -s .env ]]; then echo "BLOCKED: installer setup has not finished."; exit 2; fi
if [[ ! -s bede-root-ca.crt ]]; then echo "BLOCKED: verified local CA missing."; exit 2; fi
compose_files=(-f compose.yaml)
if grep -qx 'BEDE_LAN_ENABLED=true' .env; then
  if [[ ! -f compose.lan.yaml ]]; then echo "FAIL: LAN override missing"; exit 1; fi
  compose_files+=(-f compose.lan.yaml)
fi
if ! docker compose --env-file .env "${compose_files[@]}" config --quiet >/dev/null 2>&1; then
  echo "FAIL: Compose configuration failed."; exit 1
fi
echo "PASS: Compose configuration"
docker compose --env-file .env "${compose_files[@]}" ps > "$out/container-status.txt"
if ! curl -fsS --max-time 15 --cacert bede-root-ca.crt https://localhost/api/health > "$out/health.json"; then
  echo "FAIL: HTTPS health verification"; exit 1
fi
echo "PASS: HTTPS health verified against this instance's CA"
if grep -qx 'BEDE_LAN_ENABLED=true' .env; then
  lan_host="$(sed -n 's/^WEBAUTHN_RP_ID=//p' .env | head -n1)"
  if [[ -z "$lan_host" ]]; then echo "FAIL: LAN passkey DNS host missing"; exit 1; fi
  echo "NOT RUN: client DNS and trusted TLS check on teacher Mac at https://$lan_host"
fi
cat > "$out/manual-acceptance.txt" <<'CHECKS'
NOT RUN: Browser recognizes trusted HTTPS certificate without bypass.
NOT RUN: Bede admin signs in and completes administrator passkey.
NOT RUN: Approved organizational instructor receives invite, enrolls a passkey and signs in again.
NOT RUN: G1 two synthetic campuses and same-named learners — authorized access and cross-campus/unassigned/revoked denial.
NOT RUN: G2 evidence -> Bede recommendation -> educator approve, edit and reject -> durable audit and follow-up.
NOT RUN: G3 invite-only manually approved grants and revocations, recovery, disable/shutdown and safe restart.
NOT RUN: Pilot commercial exclusions (no Stripe, purchase, auto-conversion, retained trial access).
NOT RUN: Mac local installation browser E2E and separately controlled recovery rehearsal.
No real student data may be used before independently qualified G1 and explicit owner release GO.
CHECKS
echo "Manual pilot gates are NOT RUN; see $out/manual-acceptance.txt."
echo "Evidence saved privately in $(pwd)/$out"
echo "Review and redact any evidence before sharing; never attach .env, secrets, passkeys or invitation URLs."
read -r -p "Press Return to close... " _ || true
