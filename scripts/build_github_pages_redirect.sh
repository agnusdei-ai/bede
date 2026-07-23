#!/usr/bin/env bash
set -euo pipefail

# GitHub Pages now serves as a redirect only, not a live copy of the site —
# the canonical build (site/ + demo) is Cloudflare's own deployment, at
# https://bede.agnusdei.workers.dev/ (and, once agnusdei.ai's nameservers are
# pointed at Cloudflare, that same Worker under the custom domain instead).
# Keeping the old GitHub Pages URL alive as a redirect means any link
# already shared or bookmarked still lands somewhere real, without this
# repo having to keep two independently live copies from drifting apart.
#
# IMPORTANT: this repo's project-page URL is permanently
# https://agnusdei-ai.github.io/bede/ (GitHub derives the path from the repo
# name, "bede") — confirmed directly from a real deploy-pages run's own
# "Evaluated environment url" log line. The bare https://agnusdei-ai.github.io/
# root is NOT reachable for this repo at all (it 404s) and nothing in this
# script's output can change that — only a custom domain, or a separate repo
# literally named agnusdei-ai.github.io, could claim that root. An earlier
# version of this script published a second file nested under publish/bede/,
# assuming it would land at /bede/ — but since the artifact's own top level
# already IS /bede/, that nested file was actually unreachable at
# /bede/bede/, and the top-level file was a redirect to the marketing page,
# not the demo. That silently broke the one URL actually shared throughout
# this project's beta (agnusdei-ai.github.io/bede/) until caught by a real
# 404 report. Only ONE redirect file is produced now, at the artifact root,
# targeting the demo — the URL that was actually being shared.
#
# GitHub Pages has no server-side redirect support (no _redirects file,
# no rewrite rules) — a client-side meta-refresh + JS redirect, with a
# plain link as a no-JS fallback, is the standard workaround.
#
# Run from anywhere; cd's to the repo root itself. GitHub Actions should be
# configured with this as the only build step — see
# .github/workflows/deploy-demo.yml.

cd "$(dirname "$0")/.."

DEMO_URL="https://bede.agnusdei.workers.dev/bede/"

echo "Assembling publish/ (a single redirect stub) ..."
rm -rf publish
mkdir -p publish
cat > publish/index.html <<EOF
<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta http-equiv="refresh" content="0; url=${DEMO_URL}" />
  <link rel="canonical" href="${DEMO_URL}" />
  <title>Agnus Dei Technologies</title>
</head>
<body>
  <script>location.replace("${DEMO_URL}");</script>
  <p>This page has moved. <a href="${DEMO_URL}">Continue to the Bede demo</a>.</p>
</body>
</html>
EOF

echo "Done — publish/ is ready to deploy."
