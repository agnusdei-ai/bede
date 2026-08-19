#!/usr/bin/env bash
# Assert the DEPLOYED site actually serves the security headers site/_headers
# declares — on every merge, and on a schedule.
#
# WHY THIS EXISTS, AND WHY THE EXISTING TESTS ARE NOT ENOUGH
#
# homeschool-api/tests/test_site_headers.py checks the SOURCE: that the file
# declares every header the product enforces, that no two rules conflict, that
# it survives the build into publish/, and that wrangler.jsonc has not grown a
# `main` script (which would stop Cloudflare applying _headers at all). Every
# one of those can be green while the live site serves nothing, because the
# last hop — Cloudflare's own project configuration — is not in this repo. A
# custom domain pointed at a different Worker, a Pages project shadowing the
# Workers one, a `run_worker_first` toggled in the dashboard rather than in
# wrangler.jsonc: all invisible to CI, all fatal to the header set.
#
# That gap is not hypothetical. It was reported from a browser while all three
# source-side layers were correct, and it could not be reproduced from the
# agent sandbox, whose egress proxy blocks agnusdei.io, agnusdei.ai and
# securityheaders.com. GitHub Actions runners have ordinary internet access,
# so the check belongs there rather than in the unit suite.
#
# THE EXPECTED SET IS READ FROM site/_headers, NOT RESTATED HERE.
# Two copies of one fact is the failure mode this repository documents most
# often. Add a header to site/_headers and it becomes a live requirement on
# the next run, with nothing to remember.
#
# Note the deliberate difference from demo-watchdog.yml, whose own comment
# warns that "curl is not a browser". That is true and important for CSP
# ENFORCEMENT — whether a policy actually permits the demo's fetches needs a
# real browser, which is that workflow's job. This script asserts something
# narrower and exactly curl-shaped: that the response headers are present at
# all. A missing header is missing whoever asks.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

HEADERS_FILE="site/_headers"
# Both hosts serve the identical build from the same Worker (see the file's
# own comment). A regression usually hits both, but checking one and assuming
# the other is how a half-configured custom domain goes unnoticed.
HOSTS="${SITE_HOSTS:-https://agnusdei.ai https://agnusdei.io}"
# "all pages", not just the root — the report that prompted this was about
# every page. These are cheap and cover the four shapes: root, a sub-page,
# the privacy inventory, and the demo under /bede/.
#
# /bede/ was named in this comment from the beginning and was NOT in the
# list until 2026-08-19 — the demo, the one path a prospective family
# actually opens, was the only shape this gate claimed to cover and never
# fetched.
PATHS="${SITE_PATHS:-/ /faq/ /privacy/ /bede/}"

# Paths checked WITHOUT following redirects, asserting the header set on the
# very first response rather than on wherever it lands.
#
# `curl -I --location` above concatenates EVERY hop's headers into one blob,
# and the grep that follows searches the whole blob — so a header present
# only on the final 200 passes even when the redirect that preceded it
# carried nothing at all. That is invisible by construction, and it is the
# shape a trailing-slash redirect takes: /bede -> /bede/.
#
# It matters most for exactly the header this was added for. A redirect is
# usually the FIRST response a browser sees, and hstspreload.org checks
# every hop in the chain: a redirect without Strict-Transport-Security fails
# preload eligibility, which site/_headers claims by carrying `preload`.
#
# Cloudflare does not apply _headers to responses it generates itself (see
# the failure message at the bottom of this file), and a trailing-slash
# redirect is generated rather than served from an asset — so this is not a
# hypothetical.
FIRST_HOP_PATHS="${SITE_FIRST_HOP_PATHS:-/bede}"
ATTEMPTS="${ATTEMPTS:-10}"
SLEEP_SECONDS="${SLEEP_SECONDS:-30}"

# Header names declared under the `/*` rule. Indented, `Name: value`, and not
# a comment.
mapfile -t EXPECTED < <(
  awk '
    /^[^[:space:]#]/ { inrule = ($0 ~ /^\/\*/) ; next }
    inrule && /^[[:space:]]*#/ { next }
    inrule && /^[[:space:]]+[A-Za-z-]+:/ {
      sub(/^[[:space:]]+/, ""); sub(/:.*$/, ""); print tolower($0)
    }
  ' "$HEADERS_FILE" | sort -u
)

if [ "${#EXPECTED[@]}" -eq 0 ]; then
  echo "FAIL: parsed no headers out of $HEADERS_FILE."
  echo "      Either the file lost its /* rule or this parser needs updating —"
  echo "      both are reasons to stop, not to pass vacuously."
  exit 1
fi

echo "Expecting ${#EXPECTED[@]} headers, read from $HEADERS_FILE:"
printf '  %s\n' "${EXPECTED[@]}"
echo

failed=0
for host in $HOSTS; do
  for path in $PATHS; do
    url="${host}${path}"

    # A merge triggers a Cloudflare deploy that finishes on its own schedule,
    # so retry rather than racing it. Only the fetch is retried; a fetch that
    # succeeds with headers missing is a real result, not a flake.
    got=""
    for attempt in $(seq 1 "$ATTEMPTS"); do
      if got=$(curl -sS -I --max-time 30 --location "$url" 2>/dev/null); then
        break
      fi
      echo "  ($url unreachable, attempt $attempt/$ATTEMPTS)"
      [ "$attempt" -lt "$ATTEMPTS" ] && sleep "$SLEEP_SECONDS"
    done

    if [ -z "$got" ]; then
      echo "FAIL $url — unreachable after $ATTEMPTS attempts."
      failed=1
      continue
    fi

    lower=$(printf '%s' "$got" | tr '[:upper:]' '[:lower:]')
    missing=()
    for h in "${EXPECTED[@]}"; do
      printf '%s' "$lower" | grep -qE "^${h}:" || missing+=("$h")
    done

    if [ "${#missing[@]}" -eq 0 ]; then
      echo "OK   $url — all ${#EXPECTED[@]} headers present"
    else
      echo "FAIL $url — missing: ${missing[*]}"
      failed=1
    fi
  done
done

# See FIRST_HOP_PATHS above: same assertion, on the first response only.
for host in $HOSTS; do
  for path in $FIRST_HOP_PATHS; do
    url="${host}${path}"

    got=""
    for attempt in $(seq 1 "$ATTEMPTS"); do
      # No --location, deliberately. That is the entire point of this loop.
      if got=$(curl -sS -I --max-time 30 "$url" 2>/dev/null); then
        break
      fi
      echo "  ($url unreachable, attempt $attempt/$ATTEMPTS)"
      [ "$attempt" -lt "$ATTEMPTS" ] && sleep "$SLEEP_SECONDS"
    done

    if [ -z "$got" ]; then
      echo "FAIL $url — unreachable after $ATTEMPTS attempts."
      failed=1
      continue
    fi

    status=$(printf '%s' "$got" | head -n1 | tr -d '\r')
    lower=$(printf '%s' "$got" | tr '[:upper:]' '[:lower:]')
    missing=()
    for h in "${EXPECTED[@]}"; do
      printf '%s' "$lower" | grep -qE "^${h}:" || missing+=("$h")
    done

    if [ "${#missing[@]}" -eq 0 ]; then
      echo "OK   $url (first hop: $status) — all ${#EXPECTED[@]} headers present"
    else
      echo "FAIL $url (first hop: $status) — missing: ${missing[*]}"
      echo "     This response is what a browser sees FIRST. If it is a 3xx,"
      echo "     Cloudflare generated it and did not apply site/_headers."
      failed=1
    fi
  done
done

if [ "$failed" -ne 0 ]; then
  cat <<'MSG'

The deployed site is not serving headers that site/_headers declares.

The source side is covered by homeschool-api/tests/test_site_headers.py, so if
that suite is green the cause is downstream of this repository. Check, in
order:
  1. Is the domain attached to the `bede` Worker, or to some other project?
  2. Has a `main` script or assets.run_worker_first been added? Cloudflare does
     not apply _headers to responses generated by Worker code.
     https://developers.cloudflare.com/workers/static-assets/headers/
  3. Did the deploy for this commit actually finish?
MSG
  exit 1
fi

echo
echo "All hosts and paths serve the full declared header set."
