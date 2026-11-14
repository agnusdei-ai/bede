# Development factory qualification — November 12, 2026

Historical local qualification, preserved from the original implementation.
Its checkout, no-push state, build fingerprints and next-step wording describe
that earlier run, not current GitHub status. See `PR-VERIFICATION.md` for the
current integration against the merged specification.

## Target and scope

Actual repository: `agnusdei-ai/bede`, verified by its own linked-worktree Git
metadata/common directory and origin. Current upstream main was checked read-only
before implementation: `b36daf78c98d9c5184a650da70d09cc41f1f1233`.
Worktree: `release-checkout/bede-factory-local`, detached HEAD.
The older dirty `release-checkout/bede` and its demo test/site files were not
changed. `AGENTS.md`, engineering rules, licenses, existing curriculum services,
feature flags, app startup and database schemas were not modified.

The original approved specification commit was unavailable in this transferred
workspace. The existing handoff patch supplied the executable core. Schema,
contract, vocabulary, original example and original source fixture were restored
byte-for-byte. Their canonical original review export matches the handoff:
`8361af57048f0f41340317284830249363c5051712a07ac30e5a9d9f6a21de93`.
The full prior specification documentation/contract test suite remains in the
prior handoff patch; this implementation has its own acceptance suite and guide.

## Exact final checks

1. `timeout 35 python -B curriculum/factory/verify.py` — **32 tests passed**,
   10.406 seconds. Enforced inside the interpreter: 30-second alarm, 30-second
   CPU ceiling, 256 MiB address-space ceiling, 10 MiB per-file ceiling; parent
   process socket connection attempts denied. Tests include:
   * structure, prerequisites, rights, exact citations/hashes and existing curation;
   * licensed-pathway and non-PD verbatim denial, training denial;
   * content escaping/nonexecution, deterministic ZIP/HTML, teacher-key isolation;
   * default OFF and output/database confinement;
   * initial failure plus three repairs, including across edited manifest keys;
   * cancellation during validation/render/write/rename/pre-commit;
   * fault injection and actual child-process exit before/after rename and commit;
   * cross-process OS fencing, stale epochs, committed checkpoint/hash integrity;
   * resume without duplicate authoritative outputs; corrupt/missing output denial;
   * source/rubric/support/tool invalidation;
   * existing authenticated SQLite staging/review, independent reviewer,
     bad/missing receipt, campus/credential/UV/grant denial and grant revocation;
   * refusal to resolve approval after rubric/tool/source/output changes.
2. From `homeschool-api`, sample configuration as in README:
   `timeout 60 python -m pytest --noconftest -o asyncio_default_fixture_loop_scope=function tests/test_curriculum*.py tests/test_content_curation.py -q`
   — **133 tests passed**, 2.89 seconds, one existing Pydantic class-config
   deprecation warning. These are all nine existing curriculum test files plus
   the existing content-curation tests. No affected service or test was weakened.
3. `python -B curriculum/production-spec/contract.py check` — **PASS**,
   original canonical hash reproduced above.
4. Factory CLI fixture/build and exact same build rerun — **PASS**; serialized
   returned job records matched byte-for-byte with `cmp`. Default-OFF invocation
   exited 1 with the explicit disabled message; no output directory was created.
5. Native Chromium rendered student HTML and printed **both** packets to PDF.
   `pdftotext -layout` checks — **PASS** for draft warning, source attribution,
   proprietary notice and teacher-key separation. Student viewport visually
   inspected: readable, no broken/executable markup. Browser PDF metadata is not
   included in canonical output checksums. No signed-in application UI changed.
6. `git diff --check` — **PASS**. Governance/feature-flag diffs were empty.
   Original dirty site files and `demo/src/audienceDiscovery.test.ts` still
   appeared unchanged in the original checkout's dirty-file list.

Canonical sample factory build:

* Key: `9d4303ca0d43e62a696cca9069eb701dd4405ee2ce7970ed008bc9d36068dec9`
* Review ZIP SHA-256:
  `5c34da4b58b628ee791e2e9b8b681dd1580d94f82fc16117bf6ebfb0ae1c2fef`
* Readable source JSON SHA-256:
  `969215d4f179e68e35fd8794f4263506c8acfff14a7279ee7f27e29cc41289aa`

All generated evidence, browser captures, PDFs and SQLite files are ignored under
`generated-artifacts/curriculum-factory/`; none is a release artifact.

## Test environment and dependency/license review

Python 3.13.4 on Linux. No new Bede application dependency or lockfile change.
The outer Replit test environment added Nix packages for **existing** dependencies.
The current Python executable did not automatically include those installed
package paths; qualification commands exported:

```sh
export PYTHONPATH="$(find /nix/store -maxdepth 4 -type d \
  -path '*/lib/python3.13/site-packages' 2>/dev/null | paste -sd:)"
```

This environment-specific path selection is not an application startup change.
Selected installed versions: pytest 8.3.5; pytest-asyncio 0.26.0; SQLAlchemy
2.0.40; aiosqlite 0.21.0; Pydantic 2.11.4; pydantic-settings 2.8.1; asyncpg
0.30.0; PyCryptodome 3.21.0; email-validator 2.2.0; FastAPI 0.115.12; httpx
0.28.1; pyotp 2.9.0; Anthropic 0.51.0. Existing installed notices remain intact;
no dependency code or binaries were copied into Bede or relicensed. Recorded
metadata licenses are MIT, Apache-2.0, BSD/Public Domain and Unlicense;
aiosqlite/FastAPI use installed distribution notices rather than a License
metadata string. They are already repository dependencies, not new runtime
license grants for original Bede work.

The first broader collection attempt lacked the existing Anthropic SDK; adding
that existing test dependency resolved it. A bootstrap attempt using an
in-memory global SQLite URL conflicted with the upstream global engine's pool
settings; the final tests use the same sample, never-connected PostgreSQL
bootstrap pattern as the existing test setup and actual isolated SQLite test
engines. No real connection credentials were used or accessed.

## Limits, not established claims

* Exact locked production dependency parity and the full API/voice/frontend suite
  were not run. Some selected Nix package versions predate current lockfile
  requirements; the reported checks establish this development environment only.
* No genuine signed-in reviewer/passkey session, privileged grant issuance,
  live human curriculum review, PostgreSQL qualification, source ownership/
  legal judgment, math/source truth proof, learner effectiveness, or live settings
  were verified.
* Multi-source human staging is explicitly blocked because the existing workflow
  accepts one source per candidate. Licensed use needs a separately reviewed
  pathway; no licensed asset was relabeled public domain.
* There is no model execution, generation budget, paid inference, model training
  or automatic curriculum authoring. Unknown future model budgets remain blocking.
* The job ledger records draft success only. Fully authored, agent-reviewed,
  human-reviewed, pilot-evaluated, published and activated remain distinct.
* No remote write, push, branch, PR, merge, publication, deployment or activation.
  The next handoff is the already queued three-lesson Grade 8 slice, not a
  completed or student-ready curriculum.

## Changed files in the local Bede commit

* `.gitignore`, `.replitignore`
* `curriculum/factory/README.md`, `VERIFICATION.md`
* `curriculum/factory/boundary.py`, `fixture.py`, `ledger.py`, `render.py`,
  `review.py`, `run.py`, `validation.py`, `verify.py`
* `curriculum/factory/test_factory.py`, `test_review.py`
* `curriculum/production-spec/RESTORED.md`, `schema.py`, `contract.py`,
  `vocabulary.py`, `example.py`, `fixtures/pairs.txt`

**2026-11-14 note.** The fixture's wording was renamed under the banned
nomenclature rule (CLAUDE.md, "Banned Nomenclature"), which changes the
fixture text and so the digests above. `pairs.txt` is now 52 bytes,
SHA-256 `a8c7a3c347ef3bacd41d9e93948b5d58eaf6742306f2416fd92f7f8e15ff9819`, and
`contract.py check` reports review export SHA-256
`7967cf5399867ff57d262cbf9b968028c4aea2cac5af7aeb8d6b8520bc24fee7`. The
records above stay as they were observed at the time.
