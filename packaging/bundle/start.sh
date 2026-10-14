#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if ! command -v docker >/dev/null || ! docker compose version >/dev/null 2>&1 || ! docker info >/dev/null 2>&1; then
  echo "Docker with Compose is required and must be running." >&2; exit 1
fi
if [[ ! -f .env ]]; then
  cp .env.example .env
  chmod 600 .env
  echo "Created protected .env template. Configure a valid Bede license, strong secrets,"
  echo "PostgreSQL password, local inference endpoint, and passkey origin before proceeding."
  echo "The installer will not invent credentials or weaken authentication." >&2
  exit 2
fi
# Explicit config validation before requesting any image or opening any port.
docker compose --env-file .env -f compose.yaml config --quiet
docker compose --env-file .env -f compose.yaml pull
docker compose --env-file .env -f compose.yaml up -d --no-build
if ! curl --fail --silent --show-error --max-time 5 --cacert bede-root-ca.crt https://localhost/api/health; then
  echo "Install has NOT passed HTTPS health verification. Trust and export the"
  echo "Caddy root CA into bede-root-ca.crt; verify host trust and container status."
  exit 3
fi
echo "Bede is running with verified HTTPS at https://localhost"
