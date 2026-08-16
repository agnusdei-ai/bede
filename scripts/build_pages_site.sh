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

# The site's forms (/feedback/, /survey/, /educators/) post to the same
# API and the same Resend inbox the in-app feedback does. They need its
# URL, and it is a per-deployment value this repository deliberately does
# not hold — so take it from the SAME variable the demo build just used
# above (demo/src/api.ts's VITE_DEMO_API_BASE), rather than asking anyone
# to paste it into a committed file where it would be a second copy to
# keep in step.
#
# Unset is a supported outcome, not a failure: site/assets/api-base.js
# ships empty, and feedback-form.js falls back to the visitor's own mail
# client. Say which one happened rather than leaving it to be discovered
# from an inbox that stays quiet.
API_BASE_FILE="publish/assets/api-base.js"
if [ -n "${VITE_DEMO_API_BASE:-}" ]; then
  # Trailing slashes trimmed here so the value is canonical before it is
  # written, matching demo/src/api.ts's own handling.
  api_base="${VITE_DEMO_API_BASE%"${VITE_DEMO_API_BASE##*[!/]}"}"
  # Validated, not interpolated blind: this string is written into a
  # JavaScript file served to every visitor, so anything that is not a
  # plain https origin is refused rather than escaped and hoped for.
  if printf '%s' "$api_base" | grep -Eq '^https://[A-Za-z0-9._-]+(:[0-9]+)?$'; then
    printf 'window.BEDE_API_BASE = "%s";\n' "$api_base" > "$API_BASE_FILE"
    echo "Forms will post to $api_base"
  else
    echo "WARNING: VITE_DEMO_API_BASE is not a plain https origin ('$VITE_DEMO_API_BASE')." >&2
    echo "         Leaving it unset; the site's forms will hand off to the" >&2
    echo "         visitor's own mail client instead." >&2
  fi
else
  echo "VITE_DEMO_API_BASE is not set — the site's forms will hand off to the"
  echo "visitor's own mail client. See docs/BETA_SURVEY.md."
fi

echo "Done — publish/ is ready to deploy."
