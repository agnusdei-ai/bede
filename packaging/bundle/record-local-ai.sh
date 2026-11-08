#!/usr/bin/env bash
# Record which Ollama model this Mac actually serves, for the setup wizard.
#
# Usage: record-local-ai.sh <bundle-dir>
#
# The Windows and unix installers pull an Ollama model and then write
# local-ai.json, which scripts/setup_wizard/wizard.py reads to write
# LOCAL_LLM_BASE_URL and LOCAL_LLM_MODEL into .env (and deletes once
# consumed). The Mac app runs the operator bundle's start.sh instead, which
# wrote no marker, so .env never named a model and LOCAL_LLM_MODEL fell back
# to docker-compose.yml's default (a vLLM/Hugging Face name no Ollama serves).
# Campus tutoring uses only the local model, so every lesson would fail.
#
# This writes the SAME marker in the SAME format, so the wizard's existing,
# validated consumption logic is reused rather than duplicated. It pulls
# nothing: it records a model that is already present. Selection mirrors
# packaging/unix/install.sh's recommended_ollama_model() for a Mac (no
# NVIDIA GPU): qwen3:4b at 16 GB or more, else qwen3:1.7b. When that model
# is not installed, a single installed model is used; with none, or several
# and no recommended one, no marker is written and the wizard's ordinary
# provider choices are shown. Any stale marker is removed first, so a model
# that has since gone away is never recorded.
#
# Only start.sh calls this, only on macOS, and only while .env does not yet
# exist, so an explicit choice already saved in .env is never overwritten.
# bash 3.2 compatible (macOS /bin/bash).
set -u
dir="${1:?bundle directory required}"
marker="$dir/local-ai.json"
ollama_url="${BEDE_OLLAMA_URL:-http://127.0.0.1:11434}"

rm -f "$marker"

tags="$(curl -fsS --max-time 3 "$ollama_url/api/tags" 2>/dev/null)" || exit 0
[ -n "$tags" ] || exit 0

# Same character rule the wizard enforces on the marker's model field.
names="$(printf '%s' "$tags" \
  | grep -oE '"name"[[:space:]]*:[[:space:]]*"[^"]*"' \
  | sed -E 's/^"name"[[:space:]]*:[[:space:]]*"([^"]*)"$/\1/' \
  | grep -E '^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$')"
[ -n "$names" ] || exit 0

if [ -n "${BEDE_HOST_RAM_BYTES:-}" ]; then
  ram_bytes="$BEDE_HOST_RAM_BYTES"
else
  ram_bytes="$(sysctl -n hw.memsize 2>/dev/null || echo 0)"
fi
ram_gb=$(( (ram_bytes + 536870912) / 1073741824 ))
if [ "$ram_gb" -ge 16 ]; then recommended="qwen3:4b"; else recommended="qwen3:1.7b"; fi

model=""
if printf '%s\n' "$names" | grep -qxF "$recommended"; then
  model="$recommended"
elif [ "$(printf '%s\n' "$names" | wc -l | tr -d ' ')" = 1 ]; then
  model="$names"
fi
[ -n "$model" ] || exit 0

# host.docker.internal reaches the Mac's own loopback Ollama from inside
# Docker Desktop. This exact URL is the only one the wizard accepts.
tmp="$marker.tmp.$$"
printf '{"base_url":"http://host.docker.internal:11434/v1","model":"%s"}' "$model" > "$tmp" \
  && mv -f "$tmp" "$marker"
echo "Found the local AI model $model on this Mac."
exit 0
