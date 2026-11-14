# Production and evidence contract

## Manifest semantics

`schema.py` defines exact fields for one bundle: objectives, sources, lessons,
units, grade, evidence, gate references and a ledger checkpoint. IDs are stable
across versions; versions are positive integers. References always include exact
version and SHA-256 of canonical manifest bytes (UTF-8, sorted keys, no whitespace,
no NaN, arrays preserve pedagogical order). Raw source hashes cover **raw bytes**,
not canonical metadata. Duplicate IDs, unknown skills/references and cycles fail.
An ID rename requires a reviewed alias/migration, never silent mastery rewriting.

* **Lesson:** objectives, existing skills, prior objectives, source/version/locator,
  explicit permitted uses, steps with modality/minutes/materials, answer/rubric,
  independent, delayed and transfer assessments, access and safety, student and
  teacher outputs. Explicit teaching, worked example, seminar, studio, practice
  and exit evidence are required in the fixture contract; varied real templates
  require a versioned contract change, not omission. No outsourced AI task is
  required to demonstrate a learner's thinking.
* **Unit:** ordered exact-version lessons, prerequisite objectives, outcomes,
  culminating task, synthesis/reteaching and adult workload. Lesson order must
  satisfy objective prerequisites or an explicit assessed entry prerequisite.
* **Grade:** exact-version units, entry evidence, domains, calendar and workload,
  coverage/noncoverage decisions, completion criteria and transition evidence.
  `complete: false` is the only locally accepted value in this specification.
  A future completion evaluator consumes evidence, not a file-count threshold.
* **Sources:** exact edition, URL, retrieved timestamp, bytes hash, territory,
  creator/editor/translator, rights classification, license and notices. Copy,
  distribution, adaptation, TTS, storage, retrieval, model processing and training
  have **independent** `pending/allowed/denied` decisions and evidence refs.
  Unknown is not permitted. Training is denied by default. TTS text rights do
  not clear a voice recording/provider; permission to store does not clear
  sending to a model. No paywalled/private corpus, illustration, modern edition
  notes, translation or publisher sequence inherits another asset's clearance.
* **Access/safety:** supports, construct being measured, alternative response,
  adult supervision, hazards, stop/escalation, safer alternative, privacy and
  retention/deletion policy. Never score spiritual engagement or character.
  Essential access and safety cannot require premium coaching. No diagnosis,
  lab certification or automatic credit follows from these fields.
* **Assessment:** objective, novel prompt/key/rubric, method, allowed supports,
  prompt/rescue record, assessor role and success criteria fixed in advance.
  Record independent work separately from guided practice; delayed evidence at
  7–14 days and transfer in a different context must be planned and then actually
  collected when authorized. A missed check is missing, not a zero or a pass.
  A proposed timing is not a validated retention interval.
* **Outputs:** versioned student reading/task/accessible response packet;
  teacher explanation, worked solutions, misconceptions, prompting/reteaching,
  safety/access directions, materials, assessment and evidence collection.
  No teacher answer key in a student export.

## Ledger storage and lifecycle (factory implementation contract)

Use an additive development ledger, never learner/campus approval tables as a
job queue. Store each event transactionally with append-only event sequence,
previous-event hash and checkpoint digest. Unique `(idempotency_key, sequence)`
and compare-and-swap lease/version prevent duplicate workers. A durable
checkpoint has: task/parent/dependency references, isolated workspace identity,
input and output hashes, schema/tool/content versions, status, attempt/failure
cluster, timestamps, cancellation reason/time, actual usage/cost and measurement
source, validation results, artifact URI/hash/size, blockers and reviewer roles.
The executable checkpoint fixture covers these fields; actor authorization,
append-only storage, leases and crash injection are factory responsibilities.
Never put tokens, raw student work or personal identifiers in the ledger.

States: queued -> running -> succeeded/failed/blocked/canceled; failed ->
queued only while repair budget remains; blocked -> queued only after evidenced
blocker resolution; succeeded -> stale when an input/contract changes. Canceled
is terminal; a fresh explicit job is required. Timestamps are UTC, ordered,
and completion time required for terminal states. Each attempt writes an event
before execution; preserve failed validations rather than replacing history.
The maximum is **three repair attempts per failure cluster**, beyond the initial
attempt. Cluster by root cause/check family, not message spelling. The fourth
repair is blocked and reported; do not change tests to pass.

Idempotency key = SHA-256 of canonical `{task_ref, workspace, inputs, versions}`;
sort inputs by path first. Same key + successful verified outputs reuses them;
missing/mismatched output bytes blocks reuse, never silently regenerates an
approval. Resume only from the last committed checkpoint after verifying exact
input/output bytes, versions, dependencies and cancellation. A running worker's
expired lease requires fenced recovery, not concurrent takeover. Write artifacts
to a bounded temporary file, fsync, atomic rename, then commit the event; an
orphan before commit is untrusted. Evidence timestamps never enter content/export
hashes unless they are deliberately part of the versioned content.

Any change to source bytes, permissions, objectives, prompts, key/rubric,
supports, safety, tools/schema, or included child manifests invalidates the
affected output and transitive dependents. Preserve old versions and approvals
as historical; mark them stale, never edit their target hash. Recompute at least
the affected validations, independent reviews and gate receipts. A new learner
variant cannot replace its approved base and must expire.

## Evidence and deterministic exports

Evidence records bind exact target ID/version/hash, author run, distinct reviewer
run/identity/version (explicit `unavailable` if not exposed), UTC date, role,
scope/method, source and assessment artifacts, findings/disagreements/conditions,
decision and validation command/result. Store evidence under role-authorized
access, with retention/deletion and revocation references. Sample and actual
learner evidence must never be conflated; no real learner use is allowed here.
`contract.py` rejects self-review, stale review targets and unchecked claims.

Canonical export contains only schema version, source metadata, objectives,
lessons, units and grade, excluding run ledger, wall clock, machine paths and
reviewer identities. Identical bytes/versions yield identical output SHA-256.
The reference CLI emits review JSON only, not executable tutor prompts or
published packets. Factory student/teacher exports must be separate allowlisted
projections, deterministic archive ordering with fixed timestamps if archived,
include attribution/notices and source locator, and bind output hashes in the
ledger. Sanitize links/HTML, reject path traversal/symlinks outside workspace,
and do not retrieve remote assets during export.

## Bounded execution before work

This spec's offline checks: one process, 30-second timeout, 256 MiB address-space
limit, 1 MiB per input, at most 256 items per collection, depth 32, at most
10 MiB generated output, no network/subprocess/model invocation by the validator.
The caller applies OS limits and timeout (recorded in verification). Reading the
bounded local source fixture and upstream Python dataclasses needs no service.

Before any future authoring/model job, the factory must record verified CPU/RAM,
concurrency, wall time, context/input/output token limits, per-job/aggregate
usage/cost ceilings, disk/artifact and retry limits, cancellation mechanism,
provider/model/version and permissions. Unknown execution limits block **that
job**, not these deterministic offline tests. Paid inference budget is zero;
no paid service may run. Local model availability is unknown, not presumed.
Actual tokens/seconds/currency/cost are null when unmeasured; never report an
invented zero cost. Zero authorized spend is a policy, not a usage measurement.
