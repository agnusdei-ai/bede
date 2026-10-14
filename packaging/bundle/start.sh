#!/usr/bin/env bash
# Self-contained Bede operator bundle: no git, make, application sources, or build.
set -euo pipefail
cd "$(dirname "$0")"
fail() { printf 'Bede installation incomplete: %s\n' "$*" >&2; exit 1; }
command -v docker >/dev/null || fail "Docker Desktop / Engine is required"
docker compose version >/dev/null 2>&1 || fail "Docker Compose is unavailable"
docker info >/dev/null 2>&1 || fail "Start Docker, then reopen Bede Setup"
[[ -f images.tar ]] || fail "Installation image archive missing. Use the complete installer package."
[[ -f WIZARD_IMAGE ]] || fail "Wizard reference missing."
[[ -f compose.yaml && -f Caddyfile ]] || fail "Installation manifest is incomplete."
docker load -i images.tar >/dev/null
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
docker compose --env-file .env -f compose.yaml config --quiet || fail "Invalid setup configuration"
docker compose --env-file .env -f compose.yaml up -d --no-build --pull never || fail "Bede containers did not start"
# Trigger Caddy's local certificate issuance on the loopback interface.
# This first probe is NOT security validation; the final health test below
# validates against the root CA exported from this instance.
curl --silent --max-time 5 --insecure https://localhost/api/health >/dev/null 2>&1 || true
ready=0
for attempt in $(seq 1 30); do
  if docker compose --env-file .env -f compose.yaml exec -T caddy \
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
echo "Bede is healthy at https://localhost. Trust the bundled local CA on this device before passkey enrollment."
