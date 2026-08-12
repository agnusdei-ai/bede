#!/usr/bin/env bash
# Fails if requirements.lock.txt / requirements-dev.lock.txt no longer match
# what `pip-compile --generate-hashes` would produce from the current
# requirements.in / requirements-dev.in — i.e. the lockfile has drifted from
# the human-edited source of intent. See docs/SECURITY.md's "Backend
# requirements.txt is floor-pinned..." closed-gap entry and CLAUDE.md's
# "Required Environment Variables" section for the standing shape of this
# problem in this repo: a file that looks maintained but silently isn't.
#
# Run locally after editing requirements*.in:
#   homeschool-api/scripts/check_lockfile_freshness.sh --fix
# to regenerate both lockfiles in place, or without --fix to just check.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

if ! command -v pip-compile >/dev/null 2>&1; then
  echo "pip-compile not found — installing pip-tools..."
  pip install -q pip-tools
fi

FIX=false
if [[ "${1:-}" == "--fix" ]]; then
  FIX=true
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

pip-compile --generate-hashes --quiet \
  --output-file="$TMP_DIR/requirements.lock.txt" requirements.in
pip-compile --generate-hashes --quiet \
  --output-file="$TMP_DIR/requirements-dev.lock.txt" requirements-dev.in

STALE=false

if ! diff -q requirements.lock.txt "$TMP_DIR/requirements.lock.txt" >/dev/null 2>&1; then
  STALE=true
  if $FIX; then
    cp "$TMP_DIR/requirements.lock.txt" requirements.lock.txt
    echo "Updated requirements.lock.txt"
  else
    echo "requirements.lock.txt is STALE relative to requirements.in:"
    diff -u requirements.lock.txt "$TMP_DIR/requirements.lock.txt" || true
  fi
fi

if ! diff -q requirements-dev.lock.txt "$TMP_DIR/requirements-dev.lock.txt" >/dev/null 2>&1; then
  STALE=true
  if $FIX; then
    cp "$TMP_DIR/requirements-dev.lock.txt" requirements-dev.lock.txt
    echo "Updated requirements-dev.lock.txt"
  else
    echo "requirements-dev.lock.txt is STALE relative to requirements-dev.in:"
    diff -u requirements-dev.lock.txt "$TMP_DIR/requirements-dev.lock.txt" || true
  fi
fi

if $STALE && ! $FIX; then
  echo ""
  echo "Lockfile(s) are out of date. Run this script with --fix and commit the" \
       "result, or run pip-compile --generate-hashes directly (see" \
       "docs/PRODUCTION_SETUP.md / CLAUDE.md)."
  exit 1
fi

echo "Lockfiles are up to date."
