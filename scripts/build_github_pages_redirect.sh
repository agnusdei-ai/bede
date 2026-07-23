#!/usr/bin/env bash
set -euo pipefail

# GitHub Pages now serves as a redirect only, not a live copy of the site —
# the canonical build (site/ + demo) is Cloudflare's own deployment, at
# https://bede.agnusdei.workers.dev/ (and, once agnusdei.ai's nameservers are
# pointed at Cloudflare, that same Worker under the custom domain instead).
# Keeping the old GitHub Pages URLs alive as redirects means any link
# already shared or bookmarked still lands somewhere real, without this
# repo having to keep two independently live copies from drifting apart.
#
# GitHub Pages has no server-side redirect support (no _redirects file,
# no rewrite rules) — a client-side meta-refresh + JS redirect, with a
# plain link as a no-JS fallback, is the standard workaround.
#
# Run from anywhere; cd's to the repo root itself. GitHub Actions should be
# configured with this as the only build step — see
# .github/workflows/deploy-demo.yml.

cd "$(dirname "$0")/.."

MARKETING_URL="https://bede.agnusdei.workers.dev/"
DEMO_URL="https://bede.agnusdei.workers.dev/bede/"

make_redirect() {
  local out_file="$1"
  local target="$2"
  local label="$3"
  mkdir -p "$(dirname "$out_file")"
  cat > "$out_file" <<EOF
<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta http-equiv="refresh" content="0; url=${target}" />
  <link rel="canonical" href="${target}" />
  <title>Agnus Dei Technologies</title>
</head>
<body>
  <script>location.replace("${target}");</script>
  <p>This page has moved. <a href="${target}">Continue to ${label}</a>.</p>
</body>
</html>
EOF
}

echo "Assembling publish/ (redirect stubs only) ..."
rm -rf publish
mkdir -p publish
make_redirect publish/index.html "$MARKETING_URL" "Agnus Dei Technologies"
make_redirect publish/bede/index.html "$DEMO_URL" "the Bede demo"

echo "Done — publish/ is ready to deploy."
