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
# every page. These are cheap and cover the three shapes: root, a sub-page,
# and the demo under /bede/.
PATHS="${SITE_PATHS:-/ /faq/ /privacy/}"
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
unreachable=0
header_failed=0
for host in $HOSTS; do
  for path in $PATHS; do
    url="${host}${path}"

    # A merge triggers a Cloudflare deploy that finishes on its own schedule,
    # so retry rather than racing it. Only the fetch is retried; a fetch that
    # succeeds with headers missing is a real result, not a flake.
    # Emptiness is the wrong test. When an intermediary answers the request
    # itself — this repo's own agent sandbox returns 403 to CONNECT, and a
    # captive portal, a corporate proxy or a Cloudflare error page all behave
    # the same way — the response is NON-empty, carries that intermediary's
    # headers, and contains none of ours. Checking `-z` alone then reports
    # "missing: <every header>" and sends the reader to the Worker-config
    # advice below, which is a confident diagnosis of a problem that does not
    # exist. A false red is how a gate loses its reputation and then gets
    # deleted (see #296). So the status has to come from the origin before any
    # header is read off the response.
    got=""
    status=""
    for attempt in $(seq 1 "$ATTEMPTS"); do
      raw=""
      if raw=$(curl -sS -I --max-time 30 --location -w '\nHTTPSTATUS:%{http_code}' "$url" 2>/dev/null); then
        status=$(printf '%s' "$raw" | sed -n 's/^HTTPSTATUS:\([0-9][0-9]*\)$/\1/p' | tail -n 1)
        got=$(printf '%s' "$raw" | grep -v '^HTTPSTATUS:' || true)
        case "$status" in
          2??|3??) break ;;
        esac
        echo "  ($url answered HTTP ${status:-?}, attempt $attempt/$ATTEMPTS)"
        status=""
      else
        echo "  ($url unreachable, attempt $attempt/$ATTEMPTS)"
      fi
      [ "$attempt" -lt "$ATTEMPTS" ] && sleep "$SLEEP_SECONDS"
    done

    if [ -z "$status" ] || [ -z "$got" ]; then
      echo "FAIL $url — no response from the origin after $ATTEMPTS attempts."
      echo "     Not reading headers off a response the origin did not serve."
      failed=1
      unreachable=1
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
      header_failed=1
    fi
  done
done

if [ "$unreachable" -ne 0 ]; then
  cat <<'MSG'

At least one URL never answered from the origin, so this run proves nothing
about the header set either way. Look at the network path before the Worker
configuration: an egress proxy, DNS, or an intermediary answering on the
origin's behalf. This repository's own agent sandbox blocks these hosts, so
a run from there always lands here.
MSG
fi

if [ "$header_failed" -ne 0 ]; then
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
fi

if [ "$failed" -ne 0 ]; then
  exit 1
fi

echo
echo "All hosts and paths serve the full declared header set."
