#!/usr/bin/env bash
# Bede Homeschool Tutor — first-run setup wizard
# Usage: bash setup.sh   (or: make setup)
set -euo pipefail

BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
RESET='\033[0m'

info()    { echo -e "${CYAN}▶  $*${RESET}"; }
success() { echo -e "${GREEN}✓  $*${RESET}"; }
warn()    { echo -e "${YELLOW}⚠  $*${RESET}"; }
error()   { echo -e "${RED}✗  $*${RESET}"; exit 1; }
blank()   { echo ""; }

# At least 6 digits and not an easily-guessable pattern: no sequential run —
# ascending or descending, wraparound included (123456, 654321, 789012) — no
# repeated block (111111, 123123, 121212), and not a palindrome (669966).
# Repeated digits are otherwise fine, e.g. 602656 is a good PIN.
is_sequential_pin() {
  local pin="$1" prev="" d="" diff="" first_diff="" all_same=1
  for ((i = 0; i < ${#pin}; i++)); do
    d="${pin:i:1}"
    if [[ -n "$prev" ]]; then
      diff=$(( (10#$d - 10#$prev + 10) % 10 ))
      if [[ -z "$first_diff" ]]; then
        first_diff="$diff"
      elif [[ "$diff" != "$first_diff" ]]; then
        all_same=0
      fi
    fi
    prev="$d"
  done
  [[ "$all_same" -eq 1 && ( "$first_diff" == "1" || "$first_diff" == "9" ) ]]
}

is_repeating_block_pin() {
  local pin="$1" n=${#pin} block_len block reps candidate r
  for ((block_len = 1; block_len <= n / 2; block_len++)); do
    if (( n % block_len == 0 )); then
      block="${pin:0:block_len}"
      reps=$(( n / block_len ))
      candidate=""
      for ((r = 0; r < reps; r++)); do candidate+="$block"; done
      [[ "$candidate" == "$pin" ]] && return 0
    fi
  done
  return 1
}

is_palindrome_pin() {
  local pin="$1" rev="" i
  for ((i = ${#pin} - 1; i >= 0; i--)); do rev+="${pin:i:1}"; done
  [[ "$pin" == "$rev" ]]
}

is_strong_pin() {
  local pin="$1"
  [[ "$pin" =~ ^[0-9]{6,}$ ]] || return 1
  is_sequential_pin "$pin" && return 1
  is_repeating_block_pin "$pin" && return 1
  is_palindrome_pin "$pin" && return 1
  return 0
}

# ── Banner ────────────────────────────────────────────────────────────────────
blank
echo -e "${BOLD}╔══════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}║      Bede Homeschool Tutor — Setup       ║${RESET}"
echo -e "${BOLD}╚══════════════════════════════════════════╝${RESET}"
blank

# ── Prerequisites ─────────────────────────────────────────────────────────────
info "Checking prerequisites..."
command -v docker >/dev/null 2>&1     || error "Docker is not installed. Visit https://docs.docker.com/get-docker/"
command -v openssl >/dev/null 2>&1    || error "openssl is not installed."
docker compose version >/dev/null 2>&1 || error "Docker Compose v2 is required. Update Docker Desktop or install the plugin."
success "Docker and Compose found"

# ── Existing .env ─────────────────────────────────────────────────────────────
if [[ -f .env ]]; then
  warn ".env already exists."
  read -rp "   Overwrite it and start fresh? [y/N] " OVERWRITE
  [[ "${OVERWRITE,,}" == "y" ]] || { info "Keeping existing .env. Run 'make start' to launch."; exit 0; }
  cp .env .env.backup
  success "Existing .env backed up to .env.backup"
fi

blank
echo -e "${BOLD}Let's collect the required values.${RESET}"
echo -e "Press Enter to skip optional fields."
blank

# ── AI provider ───────────────────────────────────────────────────────────────
# No single vendor is required to get started — pick whichever fits your
# family. See docs/PROVIDER_ADAPTERS.md for the full picture (including how
# to add more than one later, for automatic failover).
ANTHROPIC_API_KEY=""
OPENAI_API_KEY=""
MISTRAL_API_KEY=""
LOCAL_LLM_BASE_URL=""
LOCAL_LLM_MODEL=""
BEDE_ADAPTER_ORDER=""

info "1/6  AI provider"
echo "     Which should Bede use for tutoring? Pick one:"
echo "     1) Anthropic (Claude) — cloud, pay-as-you-go. console.anthropic.com"
echo "     2) OpenAI — cloud, pay-as-you-go. platform.openai.com/api-keys"
echo "     3) Mistral AI — cloud, pay-as-you-go. console.mistral.ai"
echo "     4) A self-hosted model on your own server — open-weight, no"
echo "        account, no per-message cost, but needs a separate computer"
echo "        with a capable GPU running it. See docs/PROVIDER_ADAPTERS.md"
echo "        if you haven't set one up yet."
while true; do
  read -rp "     Which one? [1-4]: " PROVIDER_CHOICE
  case "$PROVIDER_CHOICE" in
    1|2|3|4) break ;;
    *) warn "Enter 1, 2, 3, or 4." ;;
  esac
done

case "$PROVIDER_CHOICE" in
  1)
    BEDE_ADAPTER_ORDER="anthropic"
    while true; do
      read -rp "     ANTHROPIC_API_KEY: " ANTHROPIC_API_KEY
      [[ -n "$ANTHROPIC_API_KEY" ]] && break
      warn "This field is required."
    done
    ;;
  2)
    BEDE_ADAPTER_ORDER="openai"
    while true; do
      read -rp "     OPENAI_API_KEY: " OPENAI_API_KEY
      [[ -n "$OPENAI_API_KEY" ]] && break
      warn "This field is required."
    done
    ;;
  3)
    BEDE_ADAPTER_ORDER="mistral"
    while true; do
      read -rp "     MISTRAL_API_KEY: " MISTRAL_API_KEY
      [[ -n "$MISTRAL_API_KEY" ]] && break
      warn "This field is required."
    done
    ;;
  4)
    BEDE_ADAPTER_ORDER="local"
    echo "     Format: http://your-gpu-box.lan:8000/v1 (the model server's"
    echo "     OpenAI-compatible endpoint — see docs/PROVIDER_ADAPTERS.md)"
    while true; do
      read -rp "     LOCAL_LLM_BASE_URL: " LOCAL_LLM_BASE_URL
      [[ -n "$LOCAL_LLM_BASE_URL" ]] && break
      warn "This field is required."
    done
    read -rp "     Model name [Qwen/Qwen3-Coder-30B-A3B-Instruct]: " LOCAL_LLM_MODEL
    ;;
esac

# ── Database ──────────────────────────────────────────────────────────────────
blank
info "2/6  Database"
echo "     1) Local Postgres (recommended) — runs alongside Bede in Docker."
echo "        No external account, nothing leaves this machine. You're"
echo "        responsible for backups — see 'make db-backup' after setup."
echo "     2) Managed Postgres (Neon, Supabase, Railway, Render, etc.) —"
echo "        automatic backups, but an extra account and your encrypted"
echo "        data leaves this machine for their cloud."
read -rp "     Use local Postgres? [Y/n] " USE_LOCAL_DB
if [[ "${USE_LOCAL_DB,,}" != "n" ]]; then
  COMPOSE_PROFILES="local-db"
  POSTGRES_PASSWORD=$(openssl rand -hex 24)
  DATABASE_URL="postgresql+asyncpg://sage:${POSTGRES_PASSWORD}@db:5432/bede"
  success "Will run a local Postgres container — remember 'make db-backup' regularly."
else
  COMPOSE_PROFILES=""
  POSTGRES_PASSWORD=""
  blank
  echo "     Format: postgresql+asyncpg://user:pass@host/dbname?ssl=require"
  while true; do
    read -rp "     DATABASE_URL: " DATABASE_URL
    [[ -n "$DATABASE_URL" ]] && break
    warn "This field is required."
  done
fi

# ── Access credentials ────────────────────────────────────────────────────────
blank
info "3/6  Parent password (admin login)"
while true; do
  read -rsp "     PARENT_PASSWORD: " PARENT_PASSWORD; echo
  [[ ${#PARENT_PASSWORD} -ge 8 ]] && break
  warn "Must be at least 8 characters."
done

blank
info "4/6  Child PIN (student login, 6+ digits, no easily-guessable pattern)"
while true; do
  read -rp "     CHILD_PIN: " CHILD_PIN
  is_strong_pin "$CHILD_PIN" && break
  warn "Must be 6+ digits and not a sequential run, repeated block, or palindrome (e.g. 602656 is fine, not 111111, 123123, 121212, 123456, 654321, or 669966)."
done

# ── License ───────────────────────────────────────────────────────────────────
blank
info "5/6  License key"
echo "     Paste the LICENSE_KEY you received when you purchased or started a"
echo "     trial of Bede — it's the line printed by scripts/issue_license.py."
echo "     No internet connection is needed to verify it; nothing is sent"
echo "     anywhere. See docs/PRODUCTION_SETUP.md#licensing if you don't have one yet."
while true; do
  read -rp "     LICENSE_KEY: " LICENSE_KEY
  [[ -n "$LICENSE_KEY" ]] && break
  warn "This field is required — Bede will not start in production without a valid license."
done

# ── Auto-generate secrets ─────────────────────────────────────────────────────
blank
info "6/6  Generating cryptographic secrets..."
SECRET_KEY=$(openssl rand -hex 32)
MASTER_SECRET=$(openssl rand -hex 32)
success "SECRET_KEY and MASTER_SECRET generated (64 hex chars each)"

# ── Detect LAN IP for tablet access ──────────────────────────────────────────
# `hostname -I` is GNU/Linux-only (BSD/macOS's hostname has no -I flag and
# errors out) — this was silently falling through to "could not detect" on
# every Mac, which per docs/PARENT_SETUP.md is a realistic "server" choice
# (Mac mini). Try, in order: modern Linux (ip route), macOS, then the
# original GNU hostname -I as a last resort for older Linux systems.
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
if [[ -n "$LAN_IP" ]]; then
  CORS_ORIGINS="https://localhost,https://${LAN_IP},http://ui:80"
  success "Detected LAN IP: ${LAN_IP} — tablets can reach Bede at https://${LAN_IP}"
else
  CORS_ORIGINS="https://localhost,http://ui:80"
  warn "Could not detect LAN IP. Add it to CORS_ORIGINS in .env if needed."
fi

# ── Write .env ────────────────────────────────────────────────────────────────
blank
info "Writing .env..."
cat > .env <<EOF
# Generated by setup.sh on $(date -u +"%Y-%m-%d %H:%M UTC")
# DO NOT commit this file — it contains secrets.

BEDE_ADAPTER_ORDER=${BEDE_ADAPTER_ORDER}
SECRET_KEY=${SECRET_KEY}
MASTER_SECRET=${MASTER_SECRET}
PARENT_PASSWORD=${PARENT_PASSWORD}
CHILD_PIN=${CHILD_PIN}
DATABASE_URL=${DATABASE_URL}
CORS_ORIGINS=${CORS_ORIGINS}
DISABLE_API_DOCS=true
PRODUCTION=true
LICENSE_KEY=${LICENSE_KEY}
EOF
# Only the chosen provider's credential is written — see docs/PROVIDER_ADAPTERS.md
# to add another one later for automatic failover.
case "$BEDE_ADAPTER_ORDER" in
  anthropic) echo "ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}" >> .env ;;
  openai)    echo "OPENAI_API_KEY=${OPENAI_API_KEY}" >> .env ;;
  mistral)   echo "MISTRAL_API_KEY=${MISTRAL_API_KEY}" >> .env ;;
  local)
    echo "LOCAL_LLM_BASE_URL=${LOCAL_LLM_BASE_URL}" >> .env
    [[ -n "$LOCAL_LLM_MODEL" ]] && echo "LOCAL_LLM_MODEL=${LOCAL_LLM_MODEL}" >> .env
    ;;
esac
if [[ -n "$COMPOSE_PROFILES" ]]; then
  cat >> .env <<EOF
COMPOSE_PROFILES=${COMPOSE_PROFILES}
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
EOF
fi
chmod 600 .env
success ".env written (mode 600 — only readable by you)"

# ── Start services ────────────────────────────────────────────────────────────
blank
echo -e "${BOLD}Starting Bede...${RESET}"
docker compose up -d --build

# ── Wait for health ───────────────────────────────────────────────────────────
blank
info "Waiting for the API to become healthy (up to 90 s)..."
DEADLINE=$((SECONDS + 90))
until curl -skf https://localhost/api/health >/dev/null 2>&1; do
  if [[ $SECONDS -ge $DEADLINE ]]; then
    warn "API did not respond in time. Check logs with: make logs"
    break
  fi
  printf "."
  sleep 2
done
echo ""

if curl -skf https://localhost/api/health >/dev/null 2>&1; then
  success "API is healthy!"
fi

# ── Done ──────────────────────────────────────────────────────────────────────
blank
echo -e "${BOLD}${GREEN}══════════════════════════════════════════${RESET}"
echo -e "${BOLD}${GREEN}  Bede is running!${RESET}"
echo -e "${BOLD}${GREEN}══════════════════════════════════════════${RESET}"
blank
echo "  Open in your browser:  https://localhost"
if [[ -n "$LAN_IP" ]]; then
  echo "  From tablets on your network: https://${LAN_IP}"
  echo "  (Run 'make caddy-trust' to install the cert on each tablet — no more warnings)"
fi
echo "  Log in as parent with: PARENT_PASSWORD you just set"
blank
echo "  Useful commands:"
echo "    make status    — check container health"
echo "    make logs      — tail live logs"
echo "    make stop      — shut down"
if [[ -n "$COMPOSE_PROFILES" ]]; then
echo "    make db-backup — back up your local database (do this regularly!)"
fi
echo "    make help      — all available commands"
blank
