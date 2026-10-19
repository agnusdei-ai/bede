#!/usr/bin/env bash
# Self-contained Bede operator bundle: no git, make, application sources, or build.
set -euo pipefail
cd "$(dirname "$0")"
# Keep failure telemetry local, secret-free and actionable for a nontechnical operator.
# No environment contents, commands, request bodies, credentials or docker logs
# are captured. A support record is written even if preflight fails.
umask 077
# One Bede application with separately owned campus and homeschool data.
install_context="${BEDE_INSTALL_CONTEXT:-homeschool}"
case "$install_context" in
  campus)
    [[ "${BEDE_CAMPUS_ID:-}" =~ ^[a-z0-9][a-z0-9_-]{2,63}$ ]] || {
      echo "A valid campus ID is needed for this pilot." >&2
      exit 2
    }
    export COMPOSE_PROJECT_NAME="bede_campus_${BEDE_CAMPUS_ID//-/_}"
    ;;
  homeschool)
    export BEDE_CAMPUS_ID=""
    export COMPOSE_PROJECT_NAME="bede_homeschool_local"
    ;;
  *)
    echo "Unsupported installation context." >&2
    exit 2
    ;;
esac
export BEDE_INSTALL_CONTEXT="$install_context"
support_dir="$(pwd)/bede-support"
mkdir -p "$support_dir"
chmod 700 "$support_dir"
support_log="$support_dir/setup-$(date -u +%Y%m%dT%H%M%SZ)-$.log"
phase="preflight"
progress() {
  local name="$1" state="$2" message="$3"
  printf 'BEDE_PROGRESS|%s|%s|%s\n' "$name" "$state" "$message"
}
progress "Checking this Mac" working "Checking the installation requirements"
diagnose_exit() {
  local status="$1"
  {
    printf 'timestamp_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf 'release_sha=%s\n' "$(if [[ -f RELEASE ]]; then tr -cd 'a-f0-9' < RELEASE | head -c 40; else printf unknown; fi)"
    printf 'phase=%s\n' "$phase"
    printf 'exit_status=%s\n' "$status"
    printf 'host_os=%s\n' "$(uname -s)"
    printf 'requested_arch=%s\n' "$(if [[ -f ARCH ]]; then tr -cd '[:alnum:]' < ARCH | head -c 16; else printf unknown; fi)"
    printf 'docker_available=%s\n' "$(if phase="docker-preflight"
command -v docker >/dev/null 2>&1; then echo yes; else echo no; fi)"
    printf 'compose_available=%s\n' "$(if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then echo yes; else echo no; fi)"
    printf 'docker_running=%s\n' "$(if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then echo yes; else echo no; fi)"
    printf 'result=%s\n' "$(if [[ "$status" = 0 ]]; then echo ready_for_operator_verification; else echo setup_incomplete; fi)"
  } > "$support_log"
  chmod 600 "$support_log"
  if [[ "$status" -ne 0 ]]; then
    printf 'Setup stopped at: %s (exit %s).\n' "$phase" "$status" >&2
    printf 'Share only this private, secret-free report with Bede support: %s\n' "$support_log" >&2
    printf 'You can still open Open-Bede-Prepilot.html without installing anything.\n' >&2
  else
    printf 'Setup diagnostics: %s\n' "$support_log"
  fi
}
trap 'diagnose_exit "$?"' EXIT
fail() { printf 'Bede installation incomplete: %s\n' "$*" >&2; exit 1; }
command -v docker >/dev/null || fail "Docker Desktop / Engine is required"
docker compose version >/dev/null 2>&1 || fail "Docker Compose is unavailable"
docker info >/dev/null 2>&1 || fail "Start Docker, then reopen Bede Setup"
[[ -f images.tar || -f IMAGE_DIGESTS ]] || fail "Missing image archive or pinned registry digest manifest."
[[ -f ARCH ]] || fail "The package CPU architecture manifest is missing."
phase="architecture-check"
required_arch="$(tr -d '\r\n' < ARCH)"
actual_arch="$(docker info --format '{{.Architecture}}' | tr '[:upper:]' '[:lower:]')"
case "$actual_arch" in x86_64|amd64) actual_arch=amd64 ;; aarch64|arm64) actual_arch=arm64 ;; esac
[[ "$required_arch" = "$actual_arch" ]] || fail "This package targets $required_arch; Docker requires $actual_arch. Choose the $actual_arch installer."
[[ -f WIZARD_IMAGE ]] || fail "Wizard reference missing."
[[ -f compose.yaml && -f Caddyfile ]] || fail "Installation manifest is incomplete."
progress "Checking this Mac" done "Mac checks complete"
phase="image-import"
if [[ -f images.tar || -f images.tar.zst ]]; then
  progress "Preparing Bede" working "Loading the Bede container images"
else
  progress "Preparing Bede" working "Downloading verified Bede container images"
fi
if [[ -f images.tar ]]; then
  docker load -i images.tar >/dev/null
elif [[ -f images.tar.zst ]]; then
  command -v zstd >/dev/null || fail "This package needs zstd; use the portable .tar.gz package or install zstd."
  zstd -dc images.tar.zst | docker load >/dev/null
else
  # Lite: only a release-published, digest-pinned manifest is permitted.
  [[ -s IMAGE_DIGESTS ]] || fail "Lite image digest manifest is empty"
  while IFS=' ' read -r image digest; do
    [[ -n "$image" && "$digest" =~ ^sha256:[0-9a-f]{64}$ ]] || fail "Invalid digest manifest entry"
    docker pull "${image}@${digest}" || fail "Unable to pull pinned image: $image"
    docker tag "${image}@${digest}" "$image" || fail "Unable to tag verified image: $image"
  done < IMAGE_DIGESTS
fi
progress "Preparing Bede" done "Bede container images are ready"
phase="configuration-wizard"
progress "Completing setup" working "Opening Bede setup in your browser"
if [[ ! -s .env ]]; then
  echo "Launching the secure Bede setup wizard..."
  image="$(tr -d '\r\n' < WIZARD_IMAGE)"
  [[ -n "$image" ]] || fail "Wizard image missing"
  if command -v open >/dev/null; then (sleep 2; open http://localhost:8765) &
  elif command -v xdg-open >/dev/null; then (sleep 2; xdg-open http://localhost:8765) &
  else echo "Open http://localhost:8765 in this computer's browser"; fi
  wizard_status=0
  docker run --rm --network bridge -p 127.0.0.1:8765:8765 \
    --env BEDE_INSTALL_CONTEXT --env BEDE_CAMPUS_ID \
    --user "$(id -u):$(id -g)" --mount "type=bind,src=$(pwd),dst=/repo" "$image" || wizard_status=$?
  if [[ "$wizard_status" -ne 0 ]]; then
    if [[ "$wizard_status" -eq 130 ]]; then
      echo "Bede setup canceled. Obtain your approved license, then reopen Install-Bede.command to resume." >&2
      exit 130
    fi
    fail "Setup wizard exited before installation finished (exit $wizard_status). No application containers were started."
  fi
fi
[[ -s .env ]] || fail "The setup wizard did not save a valid configuration"
chmod 600 .env
compose_files=(-f compose.yaml)
if grep -qx 'BEDE_LAN_ENABLED=true' .env; then
  [[ -f compose.lan.yaml ]] || fail "Private LAN configuration is missing"
  lan_ip="$(sed -n 's/^BEDE_LAN_BIND_IP=//p' .env | head -n1)"
  lan_rp="$(sed -n 's/^WEBAUTHN_RP_ID=//p' .env | head -n1)"
  lan_origin="$(sed -n 's/^WEBAUTHN_ORIGIN=//p' .env | head -n1)"
  [[ -n "$lan_rp" && "$lan_rp" != "localhost" && "$lan_origin" = "https://$lan_rp" ]] || fail "Private LAN HTTPS and WebAuthn hostname mismatch"
  [[ "$lan_ip" =~ ^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$ ]] || fail "Invalid private LAN IPv4 address"
  IFS=. read -r oct1 oct2 oct3 oct4 <<< "$lan_ip"
  for oct in "$oct1" "$oct2" "$oct3" "$oct4"; do
    (( 10#$oct >= 0 && 10#$oct <= 255 )) || fail "Invalid private LAN IPv4 octet"
  done
  if [[ "$oct1" = 10 ]]; then :
  elif [[ "$oct1" = 192 && "$oct2" = 168 ]]; then :
  elif [[ "$oct1" = 172 && "$oct2" -ge 16 && "$oct2" -le 31 ]]; then :
  else fail "Refusing a non-private LAN bind address (never use 0.0.0.0)"
  fi
  compose_files+=(-f compose.lan.yaml)
  echo "Private LAN access requested. Verify local DNS, firewall restrictions and certificate trust on each teacher Mac before enrollment."
fi
progress "Completing setup" done "Settings are saved"
phase="configuration-validation"
docker compose --env-file .env "${compose_files[@]}" config --quiet || fail "Invalid setup configuration"
progress "Starting Bede" working "Starting local services"
phase="container-start"
docker compose --env-file .env "${compose_files[@]}" up -d --no-build --pull never || fail "Bede containers did not start"
progress "Starting Bede" done "Services started"
phase="https-health"
progress "Confirming secure access" working "Checking the secure local connection"
# Trigger Caddy's local certificate issuance on the loopback interface.
# This first probe is NOT security validation; the final health test below
# validates against the root CA exported from this instance.
curl --silent --max-time 5 --insecure https://localhost/api/health >/dev/null 2>&1 || true
ready=0
for attempt in $(seq 1 30); do
  if docker compose --env-file .env "${compose_files[@]}" exec -T caddy \
    cat /data/caddy/pki/authorities/local/root.crt > bede-root-ca.crt 2>/dev/null \
    && [[ -s bede-root-ca.crt ]]; then ready=1; break; fi
  sleep 2
done
[[ "$ready" = 1 ]] || fail "The Bede HTTPS authority did not initialize"
chmod 600 bede-root-ca.crt
ok=0
for attempt in $(seq 1 45); do
  if curl -fsS --max-time 5 --cacert bede-root-ca.crt https://localhost/api/health >/dev/null 2>&1; then ok=1; break; fi
  sleep 2
done
[[ "$ok" = 1 ]] || fail "Verified HTTPS health check failed. Inspect Bede container logs."
progress "Confirming secure access" done "Secure connection confirmed"
phase="completed"
echo "Bede is healthy at https://localhost. On any teacher Mac, confirm private DNS and CA trust before using the configured HTTPS name for passkeys."
