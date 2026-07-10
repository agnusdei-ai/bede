#!/usr/bin/env bash
# Shared logic for Bede's browser-based setup — called by the double-click
# launchers at the repo root (setup-gui.command for macOS, setup-gui.sh for
# Linux). Builds and runs a tiny wizard container that serves a form in your
# browser instead of terminal prompts, waits for it to finish, then starts
# Bede the same way setup.sh does.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."   # repo root, regardless of caller's cwd

BOLD='\033[1m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; RED='\033[0;31m'; RESET='\033[0m'
info()    { echo -e "${CYAN}▶  $*${RESET}"; }
success() { echo -e "${GREEN}✓  $*${RESET}"; }
error()   { echo -e "${RED}✗  $*${RESET}"; read -rp "Press Enter to close this window..."; exit 1; }

echo ""
echo -e "${BOLD}Bede — Setup${RESET}"
echo ""

command -v docker >/dev/null 2>&1 || error "Docker is not installed. Get Docker Desktop from https://docker.com/products/docker-desktop, then run this again."
docker compose version >/dev/null 2>&1 || error "Docker Compose v2 is required — update Docker Desktop."
docker info >/dev/null 2>&1 || error "Docker doesn't seem to be running yet. Open Docker Desktop, wait for it to finish starting, then run this again."

# Same portable detection as setup.sh — see that file for why `hostname -I`
# alone isn't enough (it's Linux-only; macOS needs ipconfig instead).
detect_lan_ip() {
  if command -v ip >/dev/null 2>&1; then
    ip route get 1.1.1.1 2>/dev/null | awk '{for (i=1;i<=NF;i++) if ($i=="src") print $(i+1)}'
  elif [[ "$(uname)" == "Darwin" ]]; then
    ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null
  else
    hostname -I 2>/dev/null | awk '{print $1}'
  fi
}
LAN_IP=$(detect_lan_ip)

info "Preparing the setup wizard (first run only takes a minute)..."
docker build -q -t bede-setup-wizard -f scripts/setup_wizard/Dockerfile . >/dev/null

info "Opening the setup wizard in your browser..."
(
  sleep 1.5
  if command -v open >/dev/null 2>&1; then open "http://localhost:8765"
  elif command -v xdg-open >/dev/null 2>&1; then xdg-open "http://localhost:8765"
  else echo "  Open this yourself: http://localhost:8765"
  fi
) &

# --user matches the container process to your own account — without it,
# the wizard (which otherwise runs as root inside the container) writes
# .env owned by root, and chmod 600 on a root-owned file then locks YOU
# out of your own .env (caught by production-regression.yml's CI run).
docker run --rm -p 8765:8765 -e HOST_LAN_IP="$LAN_IP" -v "$(pwd)":/repo \
  --user "$(id -u):$(id -g)" bede-setup-wizard

if [[ ! -f .env ]]; then
  error "Setup wasn't completed (no configuration was saved). Run this again when you're ready."
fi

success "Configuration saved. Starting Bede — this can take a few minutes the first time..."
docker compose up -d --build

info "Waiting for the API to become healthy (up to 90s)..."
DEADLINE=$((SECONDS + 90))
until curl -skf https://localhost/api/health >/dev/null 2>&1; do
  if [[ $SECONDS -ge $DEADLINE ]]; then
    echo ""
    echo "Bede is taking longer than expected to start. Run 'make logs' to see what's happening."
    break
  fi
  sleep 2
done

echo ""
echo -e "${BOLD}${GREEN}Bede is running!${RESET}"
echo "  Open in your browser: https://localhost"
if [[ -n "$LAN_IP" ]]; then
  echo "  From tablets on your network: https://${LAN_IP}"
  echo "  (Run 'make caddy-trust' to install the cert on each tablet — no more warnings)"
fi
echo ""
read -rp "Press Enter to close this window..."
