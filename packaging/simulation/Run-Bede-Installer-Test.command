#!/usr/bin/env bash
# Local synthetic installer acceptance. No GHCR credentials or student data.
set -euo pipefail
cd "$(dirname "$0")"
fail() { echo "Bede installer simulation FAILED: $*" >&2; exit 1; }
command -v docker >/dev/null || fail "Install Docker Desktop first."
docker info >/dev/null 2>&1 || fail "Start Docker Desktop and try again."
docker compose version >/dev/null 2>&1 || fail "Docker Compose is required."
arch="$(docker info --format '{{.Architecture}}')"
case "$arch" in aarch64|arm64|x86_64|amd64) : ;; *) fail "Unsupported Docker architecture: $arch" ;; esac
echo "Docker architecture: $arch"
echo "Building a small local simulation image (first run may download Python Alpine base layers)."
docker compose -p bede-installer-sim up -d --build
ok=0
for attempt in $(seq 1 30); do
  if curl --fail --silent --show-error --max-time 3 http://127.0.0.1:18766/health 2>/dev/null | grep -q '"real_bede": false'; then ok=1; break; fi
  sleep 2
done
[[ "$ok" = 1 ]] || fail "Local synthetic health endpoint did not respond."
echo
echo "PASS: Local container startup, architecture, loopback networking and synthetic HTTP health."
echo "SIMULATION ONLY: This is NOT the Bede API, WebAuthn, database or school pilot certification."
echo "Cleanup: docker compose -p bede-installer-sim down"
