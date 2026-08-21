#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Agnus Dei Technologies, LLC
#
# Hardens an OpenClaw install and loads the governance prompt.
# Safe to run twice. It backs up anything it replaces and changes nothing
# until it has told you what it is about to do.
#
#   bash tools/harden-openclaw.sh
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE="${OPENCLAW_STATE_DIR:-$HOME/.openclaw}"
CONFIG="${OPENCLAW_CONFIG_PATH:-$STATE/openclaw.json}"
WORKSPACE="$STATE/workspace"
STAMP="$(date +%Y%m%d-%H%M%S)"

say()  { printf '\n\033[1m%s\033[0m\n' "$*"; }
ok()   { printf '  \033[32mok\033[0m   %s\n' "$*"; }
warn() { printf '  \033[33mnote\033[0m %s\n' "$*"; }
die()  { printf '\n\033[31mstopped:\033[0m %s\n\n' "$*" >&2; exit 1; }

say "Bede governance layer for OpenClaw"
echo "  config     $CONFIG"
echo "  workspace  $WORKSPACE"

# ---------------------------------------------------------------- checks ----
command -v python3 >/dev/null || die "python3 is needed to build the prompt. Install it and run this again."

if command -v openclaw >/dev/null; then
  ok "openclaw found: $(openclaw --version 2>/dev/null | head -1)"
  warn "the biggest group of published advisories is fixed by upgrading, so keep this current"
else
  warn "openclaw is not on PATH. This script still writes the files; install OpenClaw before starting it."
fi

# ---------------------------------------------------------------- config ----
say "1. Configuration"
mkdir -p "$STATE" "$WORKSPACE"

if [ -f "$CONFIG" ]; then
  cp "$CONFIG" "$CONFIG.backup-$STAMP"
  ok "existing config backed up to $(basename "$CONFIG").backup-$STAMP"
  warn "your config was left in place. Compare it against the hardened one:"
  warn "  diff $CONFIG $HERE/profiles/openclaw.hardened.json5"
else
  TOKEN="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
  python3 - "$HERE/profiles/openclaw.hardened.json5" "$CONFIG" "$TOKEN" <<'PY'
import pathlib, sys
src, dst, token = sys.argv[1], sys.argv[2], sys.argv[3]
text = pathlib.Path(src).read_text()
text = text.replace("REPLACE-ME-32-bytes-of-randomness", token)
pathlib.Path(dst).write_text(text)
PY
  chmod 600 "$CONFIG"
  ok "wrote a hardened config with a fresh access token"
  warn "edit channels.whatsapp.allowFrom before connecting a channel, or nobody can reach it"
fi

# ---------------------------------------------------------------- prompt ----
say "2. Governance prompt"
AGENTS="$WORKSPACE/AGENTS.md"
[ -f "$AGENTS" ] && cp "$AGENTS" "$AGENTS.backup-$STAMP" && ok "existing AGENTS.md backed up"

python3 - "$HERE" "$AGENTS" <<'PY'
import json, pathlib, sys
root = pathlib.Path(sys.argv[1])
sys.path.insert(0, str(root / "reference"))
import governance

values = {k: v for k, v in
          json.loads((root / "profiles/openclaw.values.json").read_text()).items()
          if not k.startswith("_")}
constitution = root / "constitution.json"
if not constitution.exists():
    constitution = root / "constitution.template.json"
text = governance.render(values, constitution_path=constitution,
                         extra_blocks=["10-untrusted-content"])
pathlib.Path(sys.argv[2]).write_text(text)
print(f"  ok   wrote {len(text):,} characters to AGENTS.md")
PY

SIZE=$(wc -c < "$AGENTS" | tr -d ' ')
if [ "$SIZE" -ge 20000 ]; then
  die "AGENTS.md is $SIZE characters. OpenClaw truncates bootstrap files at 20000, which would silently drop the end of your rules. Raise agents.defaults.bootstrapMaxChars or shorten the prompt."
fi
ok "fits the 20000 character bootstrap budget with $((20000 - SIZE)) to spare"

TOTAL=$(cat "$WORKSPACE"/*.md 2>/dev/null | wc -c | tr -d ' ')
[ "$TOTAL" -ge 60000 ] && warn "workspace .md files total $TOTAL characters, over the 60000 budget. Some will be truncated."

# ----------------------------------------------------------------- check ----
say "3. Check"
python3 - "$CONFIG" <<'PY'
import json, pathlib, re, sys
raw = pathlib.Path(sys.argv[1]).read_text()
s = re.sub(r"^\s*//.*$", "", raw, flags=re.M)
s = re.sub(r"//.*$", "", s, flags=re.M)
s = re.sub(r",(\s*[}\]])", r"\1", s)
s = re.sub(r'([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:', r'\1"\2":', s)
cfg = json.loads(s)

def check(label, got, want):
    mark = "ok  " if got == want else "MISS"
    print(f"  {mark} {label}: {got!r}")
    return got == want

good = True
good &= check("gateway reachable only from this machine", cfg.get("gateway", {}).get("bind"), "loopback")
good &= check("access token set", cfg.get("gateway", {}).get("auth", {}).get("token", "").startswith("REPLACE") is False, True)
good &= check("self-modification tool denied", "gateway" in cfg.get("tools", {}).get("deny", []), True)
good &= check("file tools kept to the workspace", cfg.get("tools", {}).get("fs", {}).get("workspaceOnly"), True)
sandbox = cfg.get("agents", {}).get("defaults", {}).get("sandbox", {}).get("mode")
good &= check("commands sandboxed", sandbox in ("non-main", "all"), True)
sys.exit(0 if good else 1)
PY

say "Done"
cat <<EOF
  Next, in this order:
    1. Open $CONFIG and put the phone numbers or handles you will talk to
       in channels.whatsapp.allowFrom.
    2. Start OpenClaw and approve each person once:  openclaw pairing approve
    3. Read $HERE/profiles/openclaw.runbook.md for what each setting does.

  Anything you change in $CONFIG takes effect when OpenClaw restarts.
EOF
