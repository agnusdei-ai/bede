#!/usr/bin/env bash
# Bede installer for Linux and macOS — see docs/UNIX_INSTALLER.md.
#
# This is the Linux/macOS counterpart to packaging/windows/Setup-Bede.ps1.
# Same shape, same philosophy: get a family from "nothing installed" to the
# existing browser setup wizard (setup-gui.sh) without a manual Docker
# install or a manual `git clone` first — this script does NOT reimplement
# the wizard itself. One script covers both OSes (Linux x86_64/arm64 and
# macOS Apple Silicon/Intel) rather than two nearly-identical ones, since
# unlike Windows, both share the same shell/curl ecosystem — the only real
# differences are which package manager or official installer to reach for.
#
# Verify before you run, don't just curl | bash blind — see
# docs/UNIX_INSTALLER.md's "Verifying this script" section for the
# download-then-check-then-run pattern this repo publishes a SHA-256
# checksum for.
set -euo pipefail

REPO_URL="https://github.com/agnusdei-ai/bede.git"
INSTALL_ROOT="$HOME/Bede"
APP_DIR="$INSTALL_ROOT/app"
LOCAL_AI_MARKER_NAME="local-ai.json"  # read by scripts/setup_wizard/wizard.py — keep this name in sync
OLLAMA_READY_TIMEOUT_SECS=120
DOCKER_READY_TIMEOUT_SECS=300

# ── Small helpers ────────────────────────────────────────────────────────────

step() { printf '\n\033[1;36m==>\033[0m %s\n' "$1"; }
warn() { printf '    \033[1;33m%s\033[0m\n' "$1"; }
die()  { printf '    \033[1;31m%s\033[0m\n' "$1" >&2; exit 1; }

have() { command -v "$1" >/dev/null 2>&1; }

# ── OS / distro / architecture detection ────────────────────────────────────
# Only used to pick which official installer command to run — never to
# change what Bede itself does once installed. See docs/UNIX_INSTALLER.md's
# "Why a single script, not native per-distro packages" for the reasoning.

OS_KERNEL="$(uname -s)"   # Linux or Darwin
ARCH_RAW="$(uname -m)"    # x86_64, arm64, aarch64, ...

case "$OS_KERNEL" in
  Linux)  OS="linux" ;;
  Darwin) OS="macos" ;;
  *) die "This installer supports Linux and macOS only (detected: $OS_KERNEL). See docs/PARENT_SETUP.md for other options." ;;
esac

case "$ARCH_RAW" in
  x86_64|amd64)  ARCH="x86_64" ;;
  arm64|aarch64) ARCH="arm64" ;;
  *) die "Unrecognized CPU architecture: $ARCH_RAW. Bede needs x86_64 or arm64/aarch64." ;;
esac

LINUX_DISTRO_FAMILY=""   # debian | arch | unknown — Linux only, set below
if [ "$OS" = "linux" ] && [ -r /etc/os-release ]; then
  # shellcheck source=/dev/null
  . /etc/os-release
  case "${ID:-}${ID_LIKE:-}" in
    *debian*|*ubuntu*) LINUX_DISTRO_FAMILY="debian" ;;
    *arch*)            LINUX_DISTRO_FAMILY="arch" ;;
    *)                  LINUX_DISTRO_FAMILY="unknown" ;;
  esac
fi

# ── Docker ───────────────────────────────────────────────────────────────────

docker_installed() { have docker && docker info >/dev/null 2>&1; }

install_docker_linux() {
  case "$LINUX_DISTRO_FAMILY" in
    debian)
      step "Installing Docker (Docker's official convenience script — covers Ubuntu/Debian on x86_64 and arm64)"
      curl -fsSL https://get.docker.com | sh
      ;;
    arch)
      step "Installing Docker (pacman — Arch ships Docker in its own official repos, no third-party script needed)"
      sudo pacman -Sy --noconfirm docker docker-compose
      sudo systemctl enable --now docker
      ;;
    *)
      die "Couldn't detect your Linux distro automatically. Install Docker Engine + the Compose plugin yourself (https://docs.docker.com/engine/install/), then run this script again."
      ;;
  esac

  if ! id -nG "$USER" | grep -qw docker; then
    step "Adding $USER to the docker group (lets you run docker without sudo)"
    sudo usermod -aG docker "$USER"
    warn "You've been added to the 'docker' group. This needs a fresh login to take effect."
    warn "Log out and back in (or reboot), then run this script again to continue."
    exit 0
  fi
}

install_docker_macos() {
  local dmg_arch dmg_url mount_point work_dir dmg_path
  dmg_arch="$([ "$ARCH" = "arm64" ] && echo arm64 || echo amd64)"
  dmg_url="https://desktop.docker.com/mac/main/${dmg_arch}/Docker.dmg"

  # Download into a fresh private directory (mktemp -d, 0700, unguessable
  # name) rather than a fixed /tmp/Docker.dmg.
  #
  # /tmp is world-writable. A fixed filename there lets any other local
  # account pre-create that path — as a real file it may be writable
  # through, as a symlink it redirects our write somewhere else entirely —
  # and whatever ends up at that path is then mounted and copied into
  # /Applications as a trusted app. mktemp -d removes the predictability
  # the attack depends on; the trap makes sure the directory does not
  # outlive this function even on a failed download or a mount error.
  work_dir="$(mktemp -d)" || die "Could not create a temporary download directory."
  # shellcheck disable=SC2064  # expand work_dir now, not at trap time
  trap "rm -rf '$work_dir'" RETURN
  dmg_path="$work_dir/Docker.dmg"

  step "Downloading Docker Desktop for Mac (this can take a few minutes)"
  curl -fsSL -o "$dmg_path" "$dmg_url"

  step "Installing Docker Desktop (you may see a macOS permission prompt — approve it)"
  mount_point="$(hdiutil attach "$dmg_path" -nobrowse | tail -1 | awk -F'\t' '{print $NF}')"
  [ -d "$mount_point/Docker.app" ] || die "The downloaded Docker disk image did not contain Docker.app — not installing it."
  cp -R "$mount_point/Docker.app" /Applications/
  hdiutil detach "$mount_point" >/dev/null

  step "Starting Docker Desktop for the first time — finish any prompts it shows you"
  open -a Docker
}

wait_for_docker() {
  step "Waiting for Docker to be ready"
  local deadline=$((SECONDS + DOCKER_READY_TIMEOUT_SECS))
  while [ "$SECONDS" -lt "$deadline" ]; do
    docker info >/dev/null 2>&1 && return 0
    sleep 5
  done
  die "Docker did not become ready within $((DOCKER_READY_TIMEOUT_SECS / 60)) minutes. Start it manually, wait for it to finish, then run this again."
}

# ── The app itself ───────────────────────────────────────────────────────────

sync_bede_app() {
  if [ -d "$APP_DIR/.git" ]; then
    step "Updating Bede ($APP_DIR)"
    git -C "$APP_DIR" pull --ff-only
    return
  fi

  have git || die "Git is required to download Bede. Install it (${LINUX_DISTRO_FAMILY:-your package manager}, or 'xcode-select --install' on macOS), then run this again."

  step "Downloading Bede to $APP_DIR"
  mkdir -p "$INSTALL_ROOT"
  git clone --depth 1 "$REPO_URL" "$APP_DIR"
}

# ── Local AI (Ollama) — same hardware tiers as Setup-Bede.ps1, kept in sync
# deliberately (see that script's Get-RecommendedOllamaModel). Falls back to
# system RAM when there's no usable NVIDIA GPU — the right proxy on Apple
# Silicon too, where memory is unified rather than discrete VRAM.

ollama_installed() { have ollama; }

install_ollama_linux() {
  step "Downloading and installing Ollama (official installer — covers x86_64 and arm64)"
  curl -fsSL https://ollama.com/install.sh | sh
}

install_ollama_macos() {
  # Same predictable-/tmp-path reasoning as install_docker_macos above —
  # and it matters more here, because the payload is extracted straight
  # into /Applications with -o (overwrite). An attacker-supplied archive
  # at a guessable path would be unpacked over whatever it names.
  local work_dir zip_path
  work_dir="$(mktemp -d)" || die "Could not create a temporary download directory."
  # shellcheck disable=SC2064  # expand work_dir now, not at trap time
  trap "rm -rf '$work_dir'" RETURN
  zip_path="$work_dir/Ollama-darwin.zip"

  step "Downloading Ollama for Mac"
  curl -fsSL -o "$zip_path" "https://ollama.com/download/Ollama-darwin.zip"

  # Unpack into the private directory first and check what we actually got
  # before anything reaches /Applications, rather than extracting an
  # unverified archive directly over it.
  step "Installing Ollama"
  unzip -oq "$zip_path" -d "$work_dir/extracted"
  [ -d "$work_dir/extracted/Ollama.app" ] || die "The downloaded Ollama archive did not contain Ollama.app — not installing it."
  rm -rf /Applications/Ollama.app
  cp -R "$work_dir/extracted/Ollama.app" /Applications/

  open -a Ollama
}

wait_for_ollama() {
  local deadline=$((SECONDS + OLLAMA_READY_TIMEOUT_SECS))
  while [ "$SECONDS" -lt "$deadline" ]; do
    curl -fsS http://localhost:11434/api/tags >/dev/null 2>&1 && return 0
    sleep 3
  done
  die "Ollama did not become ready within $((OLLAMA_READY_TIMEOUT_SECS / 60)) minutes. Start it manually and try again."
}

recommended_ollama_model() {
  local vram_mb=""
  if have nvidia-smi; then
    vram_mb="$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -1 | tr -d '[:space:]')"
  fi

  if [ -n "$vram_mb" ]; then
    if [ "$vram_mb" -ge 20000 ]; then echo "qwen3:32b"; return; fi
    if [ "$vram_mb" -ge 10000 ]; then echo "qwen3:14b"; return; fi
    if [ "$vram_mb" -ge 5000 ];  then echo "qwen3:8b";  return; fi
    echo "qwen3:4b"  # a GPU was found but it's small
    return
  fi

  # Rounds to the nearest GB (+ half a GB, then floor-divide) rather than
  # truncating — a machine marketed/expected as "16GB" commonly reports
  # something like 15.7GB to the OS once firmware/reserved memory is
  # subtracted, and should still land in the 16GB+ tier here, matching
  # Setup-Bede.ps1's [math]::Round behavior for the same case.
  local ram_bytes ram_gb
  if [ "$OS" = "macos" ]; then
    ram_bytes="$(sysctl -n hw.memsize)"
  else
    ram_bytes=$(( $(grep MemTotal /proc/meminfo | awk '{print $2}') * 1024 ))
  fi
  ram_gb=$(( (ram_bytes + 536870912) / 1073741824 ))
  if [ "$ram_gb" -ge 16 ]; then echo "qwen3:4b"; else echo "qwen3:1.7b"; fi
}

setup_local_ai() {
  if ollama_installed; then
    wait_for_ollama
  elif [ "$OS" = "linux" ]; then
    install_ollama_linux
    wait_for_ollama
  else
    install_ollama_macos
    wait_for_ollama
  fi

  local model
  model="$(recommended_ollama_model)"
  step "Downloading the $model AI model (first time only — can take a while, several GB)"
  ollama pull "$model"

  # host.docker.internal is Docker Desktop's own DNS name for the host
  # machine on Windows/Mac; on Linux the api container gets the same
  # mapping via docker-compose.yml's extra_hosts (host-gateway) — see that
  # file's own comment. Same URL works everywhere either way.
  local marker="$APP_DIR/$LOCAL_AI_MARKER_NAME"
  printf '{"base_url":"http://host.docker.internal:11434/v1","model":"%s"}' "$model" > "$marker"
  step "Local AI ready ($model)"
}

# ── 1. Docker ────────────────────────────────────────────────────────────────
if ! docker_installed; then
  if [ "$OS" = "linux" ]; then install_docker_linux; else install_docker_macos; fi
fi
wait_for_docker

# ── 2. The app itself ─────────────────────────────────────────────────────────
sync_bede_app

# ── 3. The one decision this installer asks: where should Bede's AI run? ─────
# Everything past this point (which model, installing Ollama, cleaning up
# afterward) is automatic — see this file's own header comment.
LOCAL_AI_MARKER="$APP_DIR/$LOCAL_AI_MARKER_NAME"
step "How should Bede get its AI?"
echo "  [1] Run AI on this computer (free, private, no account needed — recommended)"
echo "  [2] Use a cloud AI service you already have an account with (Anthropic, OpenAI, or Mistral)"
read -r -p "Choose 1 or 2: " AI_CHOICE
if [ "$AI_CHOICE" = "1" ]; then
  setup_local_ai
else
  # A family that changes their mind on a re-run shouldn't have a stale
  # local-AI marker steer the wizard back to it.
  rm -f "$LOCAL_AI_MARKER"
fi

# ── 4. Hand off to the already-shipped browser setup wizard ──────────────────
step "Handing off to the Bede setup wizard"
cd "$APP_DIR"
trap 'rm -f "$LOCAL_AI_MARKER"' EXIT
bash setup-gui.sh
