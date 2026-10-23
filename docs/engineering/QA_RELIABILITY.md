# Bede QA Reliability Agent

## Purpose and operating loop

The canonical reusable QA machinery lives in scripts/qa/. Existing CI and
agent workflows remain the execution foundation; no new runner or duplicated
test framework is introduced.

Code change → static/dependency checks → affected tests → classified failure
→ one bounded safe retry when appropriate → coding-agent source repair with
a regression test → exact-head CI → merge eligibility.

From the repository root (with dependencies installed):

    python3 -m unittest discover -s scripts/qa/tests -v
    python3 scripts/qa/validate_dependencies.py
    python3 scripts/qa/selector.py --base origin/main --head HEAD --output .qa-plan.json
    python3 scripts/qa/runner.py --plan .qa-plan.json --scope homeschool-tutor --report .qa-evidence/tutor.json
    python3 scripts/qa/runner.py --plan .qa-plan.json --scope backend --report .qa-evidence/backend.json
    python3 scripts/qa/metrics.py .qa-evidence/*.json

The selector uses git merge-base and name-status including deleted and renamed
paths. It traces static Python and TS/JS imports and their test consumers.
Dynamic imports, unknown paths, missing tests, build assets, security boundaries
and cross-component contracts expand the affected scope. Ambiguity can never
produce a vacuous green. Unit tests run before integration and release gates.

The bounded runner has a two-attempt ceiling. Its optional --repair only
reinstalls locally missing dependencies through npm ci or hash-locked pip;
semantic code/test failures are BLOCKED for an authenticated coding agent
to correct with a deterministic regression test and new commit. The CI runner
uses read-only tokens and never edits code, commits, merges or deploys.

## Non-negotiable qualification

* G1 real SQLite and non-superuser PostgreSQL are independent gates and
  never replaced with mocks.
* CodeQL, pip-audit, npm audit (moderate and above), dependency evidence,
  identity isolation, passkeys, authorization, deletion, backups and licensing
  gates remain enforced.
* Synthetic qualification is for frozen-SHA engineering evidence; authentic
  Mac installation and supervised human pilot acceptance remain distinct.
* Full regression is reserved for main, releases, critical/security/shared
  boundary changes and uncertain test mappings. Nothing can downgrade the
  separate physical Mac or owner Pilot GO requirements.
* The existing event-driven merge policy requires explicit opt-in, exact-head
  checks, current independent reviews, repository branch rules and no
  unresolved vulnerabilities or unexplained skips. This agent cannot
  grant Pilot GO or claim an unobserved check passed.
* Node 24 is the CI runtime; Python 3.12 dependencies are SHA256 hash-locked.
  NPM lockfile version 3 and root manifest parity are validated.
  Lockfile edits require an associated manifest/runtime/dependency change.

## Initial CI root-cause audit — October 23, 2026

GitHub Actions read-only sample: latest 200 runs = 149 success, 51 failure;
103 PR-event runs = 26 failed. These are *run-level* rates, NOT unique PR
first-pass rates (a PR can create multiple workflow runs).

The 31 latest failing runs grouped by workflow were:
* Backend regression: 6
* Frontend regression: 10
* Demo watchdog: 7
* Node 24 Action pin verifier: 3
* Production regression: 2
* Dependency remediation: 1
* G1: 1
* CodeQL: 1

Root causes directly confirmed from sampled job logs:

1. Outdated test/lifecycle regression — voice reconnect teardown changed
   expected worker lifetime; test_many_turns_leave_nothing_running expected
   immediately ended workers for sessions deliberately retained until TTL.
   Fix the assertion and independently test TTL cleanup; do not hide leaks.
2. Vulnerability gate — @vitest/mocker advisories
   GHSA-QXG6-89MG-RQV8 and GHSA-XP26-3454-MJGP affected multiple frontend
   runs, and the scheduled remediation workflow also reports uuid
   GHSA-W5HQ-G745-H8PQ. Upgrade only supported affected versions and verify
   the existing moderate-severity audit. Never mute advisories for CI green.
3. Brittle UI test — LessonFocusClock used ambiguous global
   getByRole('button') and failed when more than one matched. Scope the
   accessible-name query; preserve the component's accessible behavior.
4. CI action configuration — Node 24 verifier caught unreviewed upload-artifact
   SHAs. Use the reviewed SHA; do not modify the verifier to pass.
5. Demo watchdog repeatedly failed synthetic find-button on device profiles.
   A Cloudflare beacon CSP warning is present but is not itself proof of
   cause. Inspect captured browser/selector/JS evidence, not rerun blindly.
6. Other production, G1 and CodeQL failures lacked sufficient accessible
   step-level evidence in this review; leave root cause UNKNOWN, not flaky.

The existing dependency remediation, demo watchdog bounded repair,
non-superuser database, CodeQL and event-driven merge workflows are reused.

## Evidence and metrics

For each scope the runner writes a JSON artifact with changed modules, merge
base, plan fingerprint, selection reasons, exact commands, results, diagnosis
class, bounded repair attempts, security gates, wall-clock duration and
merge readiness. CI stores these artifacts for 14 days and publishes a
concise GitHub Step Summary.

metrics.py aggregates first-pass rate, ultimate selected-check pass rate,
repair attempts, recurrence fingerprints and p50/p95 runner seconds.
GitHub billed minutes are left NULL until verified from authorized billing
data. Timing alone is NOT billed-minute evidence. Do not claim efficiency
improvements until equivalent changes are compared over time.

The first acceptance check is the QA PR's exact-head CI. A red audit or
unverified mandatory check is a HOLD even if the selector unit tests pass.
