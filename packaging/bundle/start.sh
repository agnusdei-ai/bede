#!/usr/bin/env bash
# Self-contained Bede operator bundle: no git, make, application sources, or build.
set -euo pipefail
cd "$(dirname "$0")"
fail() { printf 'Bede installation incomplete: %s\n' "$*" >&2; exit 1; }
command -v docker >/dev/null || fail "Docker Desktop / Engine is required"
docker compose version >/dev/null 2>&1 || fail "Docker Compose is unavailable"
docker info >/dev/null 2>&1 || fail "Start Docker, then reopen Bede Setup"
[[ -f images.tar || -f IMAGE_DIGESTS ]] || fail "Missing image archive or pinned registry digest manifest."
[[ -f ARCH ]] || fail "The package CPU architecture manifest is missing."
required_arch="$(tr -d '\r\n' < ARCH)"
actual_arch="$(docker info --format '{{.Architecture}}' | tr '[:upper:]' '[:lower:]')"
case "$actual_arch" in x86_64|amd64) actual_arch=amd64 ;; aarch64|arm64) actual_arch=arm64 ;; esac
[[ "$required_arch" = "$actual_arch" ]] || fail "This package targets $required_arch; Docker requires $actual_arch. Choose the $actual_arch installer."
[[ -f WIZARD_IMAGE ]] || fail "Wizard reference missing."
[[ -f compose.yaml && -f Caddyfile ]] || fail "Installation manifest is incomplete."
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
if [[ ! -s .env ]]; then
  echo "Launching the secure Bede setup wizard..."
  image="$(tr -d '\r\n' < WIZARD_IMAGE)"
  [[ -n "$image" ]] || fail "Wizard image missing"
  if command -v open >/dev/null; then (sleep 2; open http://localhost:8765) &
  elif command -v xdg-open >/dev/null; then (sleep 2; xdg-open http://localhost:8765) &
  else echo "Open http://localhost:8765 in this computer's browser"; fi
  docker run --rm --network bridge -p 127.0.0.1:8765:8765 \
    --user "$(id -u):$(id -g)" --mount "type=bind,src=$(pwd),dst=/repo" "$image" || fail "Wizard was not completed"
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
docker compose --env-file .env "${compose_files[@]}" config --quiet || fail "Invalid setup configuration"
docker compose --env-file .env "${compose_files[@]}" up -d --no-build --pull never || fail "Bede containers did not start"
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
echo "Bede is healthy at https://localhost. On any teacher Mac, confirm private DNS and CA trust before using the configured HTTPS name for passkeys."
