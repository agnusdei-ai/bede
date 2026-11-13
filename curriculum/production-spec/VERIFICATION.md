# Local verification and handoff

November 12, 2026. Scope: specification and synthetic contract fixtures only.
Base: `b36daf78c98d9c5184a650da70d09cc41f1f1233` in the actual Bede
repository, isolated detached worktree `release-checkout/bede-pipeline-spec`.
No new branch, remote write, PR, merge, publication, deployment, flag change,
production secret, inference call, real learner record or pilot was used.

## Exact checks and results

From `curriculum/production-spec/`:

* `timeout 35s python3 -B verify.py` — **PASS**, 56 tests, 0.327 seconds
  reported by unittest. The checker enforces a 30-second alarm, 256 MiB
  address-space limit, and 10 MiB per-file output limit. One process; no inference.
* `contract.py check`, `contract.py schema`, and `contract.py export` entry points
  were each executed via `runpy.run_path("contract.py", run_name="__main__")`,
  with `sys.argv=["contract.py", action]`, inside a 30-second alarm, 256 MiB
  address-space and 10 MiB per-file limit; external timeout 35 seconds.
  **All passed.** Schema/export output parsed back as JSON.
* Executable `example()` serialized with `canonical()`, stored as JSON alongside
  its synthetic asset, read with `read_bundle()`, then `check()` — **PASS**.
* Canonical review export (without CLI trailing newline) SHA-256:
  `8361af57048f0f41340317284830249363c5051712a07ac30e5a9d9f6a21de93`.
  Determinism under object-key reordering and changes to excluded ledger fields
  is tested; source/child/version tampering is rejected.
* Emitted JSON Schema file including CLI newline: 19,654 bytes, SHA-256
  `be7e3f13e9fc621b428a84e0854966a5782e2f26751213f03906845a13a5d798`.
* `git diff --check` — **PASS** before staging; the staged allowlist is checked
  again before the local commit.

Transient logs, schema, example, asset copy and review export are under the
outer workspace's ignored `generated-artifacts/curriculum-production-spec/`;
they are not source artifacts and are not required to reproduce the example.
Committed `example.py` and `fixtures/pairs.txt` reproduce it without downloads.

## Repairs and evidence limits

An initial shell-level memory limit stopped the environment's wrapped runtime
before Python could start. Applying the same declared limit inside Python fixed
that launcher issue; no budget was increased. The bounded entry point preserves
this behavior for future checks.

The first expanded vocabulary test used the guessed ID `cvc_blend`; source
inspection established the existing ID is `cvc_blending`. The assertion was
corrected to that exact upstream ID. No upstream vocabulary, denial rule, or
acceptance threshold was changed. This was one correction in that failure
cluster, not an indefinite repair loop.

These tests exercise plain upstream dataclasses, default-OFF behavior, existing
diagnostic vocabulary and pure spec invariants. They do **not** run the upstream
database/authenticated workflow suites, establish genuine reviewer credentials,
clear rights, evaluate pedagogy/accessibility, or verify deployed behavior.
The schema validator is a bounded implementation of its declared subset, not a
general JSON Schema library or independent educational validator.

## Next handoff

The already queued development-only factory consumes this specification.
It must implement durable transactional events, cancellation/lease fencing,
actual resource configuration, exact artifact verification and existing
authenticated workflow adapters, then run the affected upstream tests and
crash/recovery cases listed in GATES.md. Do not replace this institutional
review service with the local evidence records.

The queued three-lesson Grade 8 slice supplies the pending baseline scope,
lawfully usable exact assets, independent academic evidence, explicit human
slice acceptance and operating/access/safety evidence. Full-year work and
Grades 9–12 remain distinct downstream milestones. No duplicate follow-up task
was proposed; those planned tasks already cover the next work.
