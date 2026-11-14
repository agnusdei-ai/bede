# Development factory: publication and integration

## Provenance and narrow scope

This is the completed development factory increment from project task 54.
Original local implementation commit:
`7ee9b26806c3797f576d1dbbdbec06571560fbd8`.
The original Git object did not survive the workspace transfer. The retained
135,524-byte diff has SHA-256
`2c78f182ed33561fc38c21827bcda588078bdd7ebeb5deefb3a90b172a3d084f`.
All ten factory Python files were restored byte-for-byte from that diff,
not silently reimplemented. Original documentation is retained with explicit
historical labeling and an updated handoff. No original test was removed.

Parent: merged production specification PR 816, main commit
`9dd27e68e040e2390f7594a33a246c073af3b4d6`.
Duplicate specification files from the factory handoff were compared with the
merged parent and are not overwritten or republished. No change to the approved
specification, existing runtime, database schema, dependency lockfiles, source
license or curriculum feature flag is included.

Changes are confined to `curriculum/factory/`, generated-output ignore rules,
and the existing curriculum contract CI workflow. The latter adds a focused
factory job using the existing Python 3.12 hash-locked test dependencies,
read-only permissions, pinned actions and exact-head checkout. It also runs
the existing affected curriculum/curation tests, without changing their fixtures
or assertions. Contract CI still tests Python 3.12 and 3.13.

## Public-repository screening

The factory Python files, guides and workflow contain proprietary Bede software
and deliberately sample test data, not a real authored lesson bank.
The coordinate exercise, sample teacher-key sentinels, fictional campus
identifiers and test-only placeholder configuration are safe software fixtures.
They are not credentials, learner records or restricted instructional answers.
Original Bede work remains proprietary under the existing repository LICENSE;
existing third-party notices remain unchanged.

No Grade 9 instructional sources, three-lesson authored Grade 8 slice,
teacher-key packets, private commercial draft, real learner data, SQLite file,
generated HTML/PDF/ZIP, browser evidence, installed dependency or model is
included. Generated evidence stays ignored. Unfinished full-year Grade 8 and
queued later grades are not represented as completed.

The owner authorized the scoped GitHub publication and resulting deployment
triggers. No deployment configuration, production command or activation setting
is changed by this increment. Pilot HOLD and separate school-administrator
authorization remain unchanged.

## Fresh integrated local acceptance

At the parent main above, Python 3.13.4 with existing Nix test dependencies:

| Command | Actual result |
| --- | --- |
| `timeout 35s python -B curriculum/factory/verify.py` | 32 passed, 10.638 s |
| `timeout 35s python -B curriculum/production-spec/verify.py` | 56 passed, 0.289 s |
| `timeout 35s python -B curriculum/production-spec/contract.py check` | Passed, original export hash reproduced |
| From `homeschool-api`, sample configuration, `timeout 60s python -B -m pytest --noconftest -o asyncio_default_fixture_loop_scope=function tests/test_curriculum*.py tests/test_content_curation.py -q` | 133 passed, 3.11 s; one existing Pydantic deprecation warning |

Original canonical specification export SHA-256 remains
`8361af57048f0f41340317284830249363c5051712a07ac30e5a9d9f6a21de93`.
The test-process-only Nix `PYTHONPATH` workaround is documented in the historical
qualification. Selected versions: pytest 8.3.5, Pydantic 2.11.4, SQLAlchemy 2.0.40,
aiosqlite 0.21.0. This local run is not exact production dependency parity.
The added GitHub job checks the repository's unchanged hashed lockfile instead.

The 32-test suite covers strict schema, prerequisite and rights checks;
existing curation and known skills; escaped deterministic projections and
student/teacher separation; default OFF; local file/database confinement;
real process crashes, cancellation and fencing; bounded repair budgets;
hash-chain integrity, reuse and invalidation; and the existing authenticated
SQLite reviewer workflow, including revoked and mismatched authorization.
The original native print qualification remains historical evidence, not a
claim that a new physical-device or signed-in browser run occurred.

## Exit gates and limitations

Before merge: inspect all applicable GitHub checks at the final exact head;
missing, skipped or in-progress applicable jobs are not a pass. Require genuine
human review of this diff, particularly the internal reviewer adapter and new
CI job, under epic 685 and the engineering rules. Do not enable auto-merge,
self-submit an approving review or bypass branch protection.

After merge: validate the integrated factory/specification and existing
curriculum regressions at the exact merge commit, and distinguish that result
from PR-head CI or any hosting build.

This software creates **review-only drafts**, not approved instruction.
There is no inference entry point, paid generation, training, production
PostgreSQL adapter, student delivery, full-grade claim, independent academic
qualification, live reviewer session, educational-effectiveness evidence,
pilot authorization or activation. All instructional approval gates remain
pending and `CURRICULUM_ENGINE_ENABLED` remains default OFF.
