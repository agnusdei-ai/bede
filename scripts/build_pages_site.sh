#!/usr/bin/env bash
set -euo pipefail

# Assembles the combined Cloudflare Pages publish directory: site/ (the
# company's own home page, agnusdei.ai) at the root, and demo/dist/ (the
# interactive Bede demo) nested under /bede/ — matching site/index.html's
# own "Meet Bede ->" link, which points at /bede/.
#
# Run from anywhere; cd's to the repo root itself. Cloudflare Pages should
# be configured with this as its build command and `publish` as its output
# directory — see docs/DEMO_HOSTING.md's "Moving to Cloudflare Pages"
# section for the full one-time project setup.
#
# demo/'s own vite.config.ts already uses `base: './'` (relative asset
# paths), which is exactly what makes it safe to nest demo/dist under any
# subpath like this — an absolute base path would break the moment it's
# served from anywhere other than the domain root.

cd "$(dirname "$0")/.."

echo "Building demo..."
(cd demo && npm ci && npm run build)

echo "Assembling publish/ ..."
rm -rf publish
mkdir -p publish
cp -r site/* publish/
mkdir -p publish/bede
cp -r demo/dist/* publish/bede/

echo "Done — publish/ is ready to deploy."
