# Specification PR preparation

## Provenance and current scope

Prepared November 13, 2026 on main
`5620bfaab4f3a2f0bfbd96180b8330f1b2d68816`, after the Grade 8 baseline PR.
Original specification commit reported in its handoff:
`1677d53a5d0e0d1bb8801ec9d6d4ffc03d0243d2`; that original local object no longer
exists in this checkout. Its exact source-transfer patch survives with SHA-256
`e3d359d0f794921fa71e4dbbf32369b5a2ac12cbb0e2b25c8baed78455c9d697`.
Restoration was checked file-by-file against that patch; no output was invented.
Only the README's explicit PR-preparation note differs from the original twelve
files. This new evidence document and focused CI workflow are additional files.

The separate factory patch contains complete copies of five specification files,
not incremental edits to them. Do not apply its duplicate additions over this
specification without comparing exact bytes first.

## Public-repository screening

| Artifact | Disposition |
| --- | --- |
| `GATES.md` | Completion/review rules, no approval receipts or lesson keys |
| `INVENTORY.md` | Historical public-code inventory and known gaps; not a live security or deployment attestation |
| `PRODUCTION.md` | Manifest/ledger/evidence contract; no private service terms or learner records |
| `README.md` | Proprietary notice, limitations and current authorization context |
| `VERIFICATION.md` | Original historical verification record, not relabeled as current evidence |
| `contract.py` | Offline validator and JSON export; no delivery or approval authority |
| `schema.py` | Structured contract and bounded fail-closed schema subset |
| `vocabulary.py` | Existing public diagnostic vocabulary adapter; no learner data |
| `example.py` | Clearly labeled sample software fixture with trivial coordinate expectations; not an authored lesson or restricted assessment bank |
| `fixtures/pairs.txt` | Bede-original sample coordinate test bytes, no external source asset |
| `test_contract.py` | Sample positive/negative assertions, including denial of student-key leakage; no real lesson answers or credentials |
| `verify.py` | Bounded offline test runner |
| `PR-VERIFICATION.md` | This provenance, screening and current test record |
| `.github/workflows/curriculum-contract.yml` | Read-only, immutable action pins, no secrets or deployment commands; runs the contract at exact PR head |

All Bede-owned material remains proprietary. No license file or third-party
notice is changed. Real Grade 8/9 lesson authoring sources, teacher packets,
assessment keys, the private commercial draft and generated artifacts remain
excluded. No paid model, external asset download, database or learner data is
used. Publication of sample software-test expectations does not publish the
withheld instructional answer keys.

## Current checks and limits

From `curriculum/production-spec/`:

```sh
timeout 35s python3 -B verify.py
timeout 35s python3 -B contract.py check
```

The full 56-test suite passed on Python 3.13.4 in 0.256 seconds. The test runner
enforces a 30-second alarm, 256 MiB address-space limit and 10 MiB per-file
output limit. The canonical export reproduced the original SHA-256:
`8361af57048f0f41340317284830249363c5051712a07ac30e5a9d9f6a21de93`.

The added GitHub workflow runs the suite and CLI on Python 3.12 and 3.13, parses
schema/export output and compares two independent CLI runs byte-for-byte.
It is additional CI implementation, not a branch-protection change or a
replacement for existing regression/security checks. Its CI results must be
inspected at the final head before merge; local Python 3.13 results are not
fabricated Python 3.12 evidence.

Tests cover schema/type/size/depth bounds, existing model and vocabulary reuse,
default-OFF behavior, prerequisites, source/permission/citation references,
version hashes, assessment coverage, student/teacher section separation,
self/stale/string-only approval denial, repair/cancellation/resume/invalidation,
path/symlink confinement and malformed JSON. This specification emits JSON;
there is no changed application UI, HTML/PDF export, runtime route, database
schema, model inference, live lab or substantive math curriculum to qualify.
Those acceptance checks belong to the separately reviewed factory and authored
lesson packages. No assistive-technology, teaching efficacy, authentic campus
authorization, legal clearance or real learner readiness is claimed here.

## Exit gates

- Genuine human review of this exact PR diff, including the new CI workflow.
- Green applicable exact-head checks, including the new contract matrix.
- No weakening of existing rights/reviewer protections, no runtime activation.
- After merge, validate the integrated specification and inspect exact-merge CI.

The owner's acceptance of the earlier baseline is not approval of this unseen
specification diff. No auto-merge, self-approval or mock human review.
