# Development-only curriculum factory

Bede proprietary software and content, under the repository LICENSE.
No new application dependencies or license changes. Python standard-library
tooling reuses Bede's existing Pydantic content models/curation, diagnostic skills,
curriculum dataclasses/rights gate, and SQLAlchemy authenticated reviewer workflow.
All existing third-party notices and separately licensed components are unchanged.
No corpus copying, licensed-content runtime exception, provider, paid service,
training, real learner data, route, startup registration, migration, publication,
or activation is added.

## Scope and distinct gates

This is a finite, deterministic **manifest-to-draft** build, not a curriculum
authoring model or full-grade generator. The restored approved contract remains
`fixture_only: true`, grade `complete: false`. The included Bede-original fixture
is a small coordinate exercise for structural testing, not reviewed instruction.
Real source truth, mathematical correctness, pedagogy, rights ownership, access,
and outcomes need independent evidence. Do not interpret a successful build as
human-reviewed, student-ready, pilot-evaluated, published, or activated.

Unknown model/provider availability, CPU capability, context/token budgets,
permissions, aggregate cost ceilings and local-model qualification block any
future inference integration. There is **no inference entry point** here.
Authorized paid spend is zero; unmeasured tokens/cost remain null, not invented
zeros. The factory CLI enforces one process, 30 seconds, 256 MiB address space,
1 MiB per input, 256 file records, 8 MiB aggregate inputs and 10 MiB outputs.
Internal Python calls require the caller's process budget (the bounded test
runner applies it before imports). No indefinite worker or background loop.

The runtime `CURRICULUM_ENGINE_ENABLED` flag is not enabled or changed. The
separate factory requires **both** `BEDE_CURRICULUM_FACTORY_ENABLED=1` and
`BEDE_FACTORY_MODE=development`; all other values fail before output creation.
Live/deployed settings have not been inspected. “Default OFF” refers to the
verified source defaults, not an assertion about any production environment.

## Reproduce locally

Run at the actual Bede repository root with its existing Python test dependencies
available (see `homeschool-api/requirements-dev.lock.txt`; do not edit the lockfile
or install unrelated packages). The factory itself needs the existing model and
curation dependencies; the optional review tests additionally need the existing
SQLite/SQLAlchemy test stack. Missing dependencies fail explicitly.

```sh
# Default OFF: must exit 1 without creating a store.
python -B curriculum/factory/run.py fixture

# Opt in for this shell only; this does not enable the runtime curriculum engine.
export BEDE_CURRICULUM_FACTORY_ENABLED=1
export BEDE_FACTORY_MODE=development
python -B curriculum/factory/run.py fixture
python -B curriculum/factory/run.py build \
  --manifest generated-artifacts/curriculum-factory/local/input/bundle.json \
  --task synthetic-draft
# Same command verifies and reuses exact outputs; no duplicate events/artifacts.
python -B curriculum/factory/run.py build \
  --manifest generated-artifacts/curriculum-factory/local/input/bundle.json \
  --task synthetic-draft
python -B curriculum/factory/run.py status --key BUILD_KEY
python -B curriculum/factory/run.py cancel --key RUNNING_KEY \
  --reason 'Stop synthetic development run'

# Bounded acceptance suite. Network connection attempts are denied.
timeout 35s python -B curriculum/factory/verify.py
```

The last command temporarily uses synthetic test-only environment defaults
inside the test process, an in-memory SQLite database and test-only grants.
It never reads workspace secrets or connects to the placeholder PostgreSQL URL.
`test_review.py` reuses the existing workflow test setup; it does not mock
reviewer authorization. A real signature-verified session and authorized rights
review have **not** been established by these synthetic tests.

Existing affected regressions (without app-wide fixtures importing unrelated
voice/model services; no fixtures in these files depend on those fixtures):

```sh
cd homeschool-api
# Provide the same synthetic configuration as tests/conftest.py, never live keys.
SECRET_KEY=synthetic-test-key-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx \
MASTER_SECRET=synthetic-test-master-yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy \
ANTHROPIC_API_KEY=synthetic-no-network \
DATABASE_URL=postgresql+asyncpg://synthetic:synthetic@127.0.0.1/never_connect \
timeout 60s python -m pytest --noconftest \
  -o asyncio_default_fixture_loop_scope=function \
  tests/test_curriculum*.py tests/test_content_curation.py -q
```

## Outputs and safe content handling

Only strict JSON is read: no YAML constructors, templates, Markdown execution,
eval, remote asset fetch, or subprocess from content. Duplicate JSON keys,
nonfinite values, excessive depth/collections, unknown fields, stale exact
references, prerequisite cycles/order errors, missing coverage, unknown skills,
missing rights/citations and unsafe curation findings block the build.
All source assets remain local, bounded, checksummed evidence. Symlinks and path
traversal are rejected, including links inside the workspace.

Outputs are confined to `generated-artifacts/curriculum-factory/`, ignored by
Git and Replit publishing. Each successful content-addressed directory includes:

* `source.json`: readable structured curriculum source, including teacher keys.
* `student.html`: student-format **review draft**, allowlisted projection with
  no teacher key/rubric fields or worked-solution steps.
* `teacher.html`: teacher review packet with keys, evidence directions, access,
  safety, privacy, source attribution, edition, locator and original notices.
* `coverage.json`, `evidence.json`, `build.json`, `checksums.sha256`,
  `CHANGELOG.txt`, `LIMITATIONS.txt`.
* `review.zip`: deterministic file order, fixed timestamps, no machine paths or
  run timestamps. ZIP contents include teacher materials: never distribute the
  complete bundle as a student packet.

Both HTML packets escape every content string as text; URLs are printed text,
not active links. They have no scripts, forms, external images or executable
instructions. CSP restricts resource loading. Print through the browser's native
Print command; print CSS preserves readable long source hashes/URLs and attribution.
HTML/ZIP determinism is byte-for-byte for the same inputs and tool versions;
browser-created PDFs may have browser-added metadata and are not canonical builds.
Semantic answer leakage in arbitrary author-written prompts is still a review
responsibility, not something field projection proves.

## Ledger, cancellation and recovery

`ledger.sqlite` is additive development storage, not learner or campus storage.
Events and current checkpoints commit together in SQLite FULL-synchronous WAL
transactions; events have a global sequence and previous-event/checkpoint hash.
Triggers reject event deletion/update. Each open/resume audits the hash chain
and checkpoint correspondence. This is local audit integrity, not protection
against a privileged owner rewriting the whole database.

A single OS file lock fences the entire store. There is no timer-only lease:
a live worker cannot be displaced; a crashed process releases its lock.
Recovery increments the persisted epoch, and checkpoint writes compare that
epoch plus running state. Cancellation uses another SQLite connection, appends
its reason/time, increments the fence and makes the job terminal. Every phase
and pre-commit checkpoint checks cancellation. A canceled key cannot resume.
Use a new explicit task identity for a fresh job.

Writes use bounded temporary files, fsync, atomic directory rename, directory
fsync, then a committed success event. An orphan after rename has no authority.
Recovery preserves it under `.orphan-*`; hidden pre-rename temporary directories
from an actual killed process are also untrusted and never reused. Operators
may remove disposable orphan/temp evidence only after investigation, outside an
active build. Successful outputs missing or differing from their hashes block
reuse rather than silently regenerating an approval.

Failures are preserved by stable phase/root-cause family. The initial attempt
plus at most **three repairs per failure cluster** is allowed; a fourth repair
records a blocker. Counts persist across changed content keys within the same
task/workspace/manifest scope; a whitespace or source edit cannot reset them.
No test weakening, provider switch or rights relabeling.
There is no automatic repair authoring: each finite invocation is explicit.
Change the input to resolve an actual validation problem; repeated failed
invocations do not create more permissions.

The key binds task/workspace, raw manifest bytes, actual source/evidence bytes,
schema and all factory/curriculum/diagnostic code hashes and interpreter/SQLite
versions. The entire bundle is the invalidation unit: changing a source, rubric,
support, permission, child manifest or tool invalidates all output projections
and dependent lesson/unit/grade review targets. Historical outputs/reviews remain
historical. Review binding rechecks inputs/tools/output bytes again on use.

## Existing human workflow adapter

`review.py` is internal development tooling, **not** an API or alternate grant/
approval system. It refuses any database except in-memory SQLite or a SQLite
file confined to the development output directory. It cannot write PostgreSQL
or production tables. There is no CLI reviewer/approve flag.

An existing trusted API boundary must signature-verify the session before calling
these functions; raw browser claims, typed names, or manifest strings are not
credentials. `stage_for_review` delegates to existing `stage_lesson` and binds
the full exported content, exact lesson/version and factory fingerprint in the
encrypted immutable candidate. Source/rights assertions are still assertions
until authorized independent review; the helper does not issue grants.

Existing `review_staged_lesson` remains the only human decision path. It checks
live enabled educator/campus/membership, WebAuthn UV, current credential version,
admin-issued grant, independent author, rights and source fingerprint, and
reauthorizes before commit. Approval creates a distinct approved version in the
synthetic development database, not a factory-success or runtime publication.

`resolve_receipt` reads that existing record, checks current identity/grant,
latest approved version, decision, independent author, encrypted exact content,
source fingerprint and current build bytes/tools. Revoked grants, new versions,
changed rubrics/sources/tools or corrupt outputs fail. Returned development
receipts are not stored as offline “approved” gates or used to enable student
delivery. Offline manifest human gates remain pending.

The upstream workflow supports one source per staged candidate; multi-source
promotion is explicitly blocked by this adapter, not partially staged.
Licensed use is separately blocked by the approved contract even when a manifest
names a license; the existing verified-PD verbatim rule is unchanged. Report a
specific blocked asset/pathway for separate review; do not relabel it.

## Handoff

The dependent three-lesson Grade 8 slice has a separate handoff and publication
decision because its authored content includes teacher keys. It is not bundled
with this public software increment.
No complete grade, live human review, PostgreSQL qualification, real passkey/
administrator-grant issuance, educational effectiveness, pilot, publication,
deployment or activation of instructional content is asserted.
See `PR-VERIFICATION.md` for current integration and publication scope;
`VERIFICATION.md` preserves the original local development qualification.
