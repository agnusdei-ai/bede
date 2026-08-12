#!/usr/bin/env bash
# Fails if requirements.lock.txt / requirements-dev.lock.txt no longer match
# what `pip-compile --generate-hashes --allow-unsafe` would produce from the
# current requirements.in / requirements-dev.in — i.e. the lockfile has
# drifted from the human-edited source of intent. See docs/SECURITY.md's
# "Backend requirements.txt is floor-pinned..." closed-gap entry and
# CLAUDE.md's "Required Environment Variables" section for the standing
# shape of this problem in this repo: a file that looks maintained but
# silently isn't. --allow-unsafe is required here, not optional: without it
# pip-compile refuses to pin setuptools at all (see requirements.in's own
# comment on why setuptools is pinned explicitly), so every run of this
# script without the flag would regenerate a DIFFERENT lockfile than the
# one actually committed and never converge — caught on the first real PR
# CI run against this script, which failed for exactly that reason.
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

# pip-compile records its own exact invocation — including the --output-file
# path it was given — in the generated file's header comment. Passing a
# tmp-dir path there would make that one header line differ from the
# committed file's (which was generated with a plain relative filename)
# on every single run, a permanent false positive unrelated to real drift.
# Copying the .in files into TMP_DIR and running from there instead means
# the recorded --output-file argument is the same plain filename either way.
cp requirements.in requirements-dev.in "$TMP_DIR/"
(
  cd "$TMP_DIR"
  pip-compile --generate-hashes --allow-unsafe --quiet \
    --output-file=requirements.lock.txt requirements.in
  pip-compile --generate-hashes --allow-unsafe --quiet \
    --output-file=requirements-dev.lock.txt requirements-dev.in
)

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
