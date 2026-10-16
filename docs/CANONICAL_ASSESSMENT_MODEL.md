# Canonical DIBELS / Assessment Model

This document describes the UUID-keyed assessment record that Bede keeps for a
learner in an institutional pilot campus. It also describes the instructional-review
calendar and the Data Day packet built from those records.

Code:

- `homeschool-api/core/pilot_assessment_models.py` holds the tables.
- `homeschool-api/services/assessment_lifecycle.py` holds the pure state machine.
- `homeschool-api/services/canonical_assessment.py` holds the contracts and the
  pure helpers.
- `homeschool-api/routers/pilot_assessments.py` holds the routes.
- `homeschool-api/services/canonical_assessment_adapter.py` is the G2 adapter seam.

Tests:

- `tests/test_canonical_assessment_lifecycle.py`
- `tests/test_canonical_assessment_api.py`, which uses real HTTP and runs on
  SQLite and on Postgres.
- `tests/test_canonical_assessment_adapter.py`

Synthetic fixtures live in `tests/canonical_assessment_fixtures.py`.

## What this is, and what it is not

Bede **transcribes** an official administration or a vendor report. It does not
administer DIBELS®, generate directions, alter timing, forms or scoring, or
calculate a benchmark. It contains no norm table and no cut-point table, and it
never computes a band. DIBELS is never used as a learner grade.

Three kinds of thing are kept apart:

1. **The official record.** This is the administration, its per-measure scores
   and its item responses. Once finalized it is immutable.
2. **Bede's interpretation.** This is a *proposal*, which is never an approval.
3. **The teacher's decision, plan and progress-monitoring dates.** Only a
   recorded teacher action creates these.

Teacher interpretation never overwrites a score. Both the database and the
routes enforce this.

## Tables

The learner-scoped tables are listed below. Each carries G1's immutable
`campus_id` and `learner_id`, and none is keyed by a display name.
`LEARNER_SCOPED_TABLES` names them. A test fails if a learner-bearing table in
the module is missing from that list or from this document.

**The deletion lane must cascade every one of these by `(campus_id, learner_id)`:**

| Table | Record | Encrypted columns |
| --- | --- | --- |
| `pilot_assessment_administrations` | AssessmentAdministration | `content_enc` (accommodations, notes, vendor guidance) |
| `pilot_assessment_scores` | AssessmentScore, per measure and composite | `detail_enc` (score, unit, reason, printed labels, printed cut points) |
| `pilot_assessment_responses` | AssessmentResponse, item marks | `marks_enc` |
| `pilot_assessment_transitions` | AuditEvent, the hash-chained lifecycle | `note_enc` |
| `pilot_assessment_evidence` | EvidenceRecord | `summary_enc` |
| `pilot_assessment_proposals` | Bede's proposed next step and review date | `proposal_enc` |
| `pilot_assessment_decisions` | TeacherDecision, hash-chained per learner | `rationale_enc` |
| `pilot_assessment_plans` | Teacher's instructional plan, recorded only | `plan_enc` |
| `pilot_progress_monitoring_schedules` | Teacher-confirmed progress-monitoring dates | none (dates only) |

The campus-scoped configuration tables hold no learner content:

- `pilot_campus_cycles` is the instructional-review calendar.
- `pilot_benchmark_authorizations` holds the benchmark authorization.

They are removed with the campus, not with a learner.

Every encrypted column is AES-256-GCM. Its AAD is bound to
`table:column:campus_id:learner_id:row_id`. A blob copied into another learner's
row, or into another campus's row, therefore fails to decrypt instead of attaching
to the wrong child.

The deletion lane must also account for three things:

- **The database triggers below.** They block UPDATE, not DELETE, so erasure is
  possible.
- **The two hash chains.** Erasing a learner removes that learner's whole chain.
  No chain spans learners.
- **The G1 rows themselves.** These are `pilot_learners` and
  `pilot_roster_grants`, and they are outside this lane.

## Immutability, enforced in the database

Triggers are created with the tables on both SQLite and Postgres:

- A `pilot_assessment_administrations` row cannot be updated once `finalized_at`
  is set.
- Score, response, transition, evidence, decision, plan and schedule rows can
  never be updated in place. During entry, scores and responses are replaced by a
  delete and an insert.
- No score or response can be inserted under a finalized administration.

A finalized administration records the SHA-256 of its exact content as
`snapshot_sha256`. The content hashed is the metadata, the decrypted content,
the scores and the responses. Every read recomputes the hash and reports
`snapshot_verified`. Evidence can only reference an intact snapshot.

## Lifecycle

`services/assessment_lifecycle.next_state()` is a pure function. Its tests cover
every pair in the full state × action product.

```
DRAFT → READY_FOR_ADMINISTRATION → IN_PROGRESS → COMPLETED_PENDING_REVIEW
      → FINALIZED → EVIDENCE_AVAILABLE → TEACHER_DECISION_PENDING
      → TEACHER_DECISION_RECORDED → INSTRUCTIONAL_PLAN_READY
      → PROGRESS_MONITORING_SCHEDULED
```

There are four side states:

- `INTERRUPTED`, reached from IN_PROGRESS. The teacher can only `resume` with a
  written resolution, or `void`.
- `INVALID_ADMINISTRATION`, reached from IN_PROGRESS or COMPLETED_PENDING_REVIEW.
  The teacher can only `resolve_invalid` with a written resolution, or `void`.
  A resolved invalid administration may be finalized for the file. It stays
  `invalid_resolved` and is excluded from valid results and growth.
- `VOIDED_BY_TEACHER`, which needs a reason. It is refused after finalization.
  This state is terminal.
- `SUPERSEDED_WITH_AUDIT_LINK`. This is the only correction for a finalized
  record. It creates a **new** DRAFT administration with `supersedes_id`, and the
  old record's ledger gains a transition whose `link_id` names the replacement.
  The old row is never touched. This state is terminal.

The current state is the head of the `pilot_assessment_transitions` chain. It is
not a column. This means a finalized row never has to change for its lifecycle to
continue.

Each transition commits to the previous one's hash. `seq` is unique per
administration, so two concurrent transitions from the same head collide. One
wins and the other gets `409`. The API test races two real requests to show this.

Refused attempts are not written to the chain. Writing them would let a refused
request race a legitimate one. The `result` column therefore always reads
`applied`.

## Semantics enforced at input

| Rule | Where |
| --- | --- |
| `administration_purpose` is `benchmark`, `progress_monitoring`, `instructional_check` or `teacher_observation`, and is separate from `instructional_cycle`. | `AdministrationInput` |
| Only `benchmark` may carry an `official_benchmark_window` (`BOY`, `MOY` or `EOY`). Every other purpose must say `none`. A progress-monitoring result is never a benchmark, whatever Data Day it falls on. | `AdministrationInput` |
| `benchmark` requires a recorded, enabled per-campus authorization whose approved forms include the `form_id`. Without one, the API answers `403` and writes nothing. | router `_benchmark_authorization` |
| `report_source`, `official_benchmark_window` and `vendor_next_assessment_date` are transcribed separately and never derived from `instructional_cycle`. | `AdministrationInput`, test |
| Each measure has an `administration_status` of `scored`, `not_administered_by_rule`, `not_administered_other` or `invalid`. Only `scored` carries a raw score. Every other status needs a transcribed reason and carries no number. It is never 0 and never enters growth. | `ScoreInput`, `growth_by_measure` |
| A composite or measure may carry a printed `benchmark_label` (Well Below, Below, At or Above Benchmark), a printed `support_label` (Most Support, Some Support, Goal or Above Goal), or both. Each is validated against its own allowed set and stored exactly as printed. Neither is computed, and they are never reconciled with each other or with the score. | `ScoreInput` |
| Cut points printed on the report are stored per score row and returned with `provenance: "as printed on the source report"`. No band is computed from them. | `ScoreInput`, `_render_score` |
| Vendor guidance (support areas and home activities) is stored as `vendor_guidance` and attributed to the vendor. It is never a Bede recommendation and never an approved action. A printed band and a named support area are both recorded, and neither is reconciled with the other. | `VendorGuidance`, `propose` |

## Calendar (configurable per campus)

`PUT /pilot/campuses/{campus_id}/calendar` requires a verified administrator
passkey. It takes one of two bodies:

- `{"preset": "valor_default", "first_data_day": "YYYY-MM-DD"}` sets the Valor
  default. That is Q1, Q2, Q3 and Q4 / year-end Data Days, nine weeks apart.
- `{"cycles": [...]}` sets any other campus calendar.

A campus with no configured calendar falls back to the Valor cycle keys with
**no dates**. Bede does not invent dates. No Fall, Winter or Spring schedule
exists in the code, and a test scans for one.

`POST /pilot/campuses/{campus_id}/benchmark-authorizations` records the
authorization. It holds references only:

- the licensed program;
- the approved form identifiers;
- the local policy;
- a fixed attestation that these permit benchmark administration.

## Routes

Every learner route is
`/pilot/campuses/{campus_id}/learners/{learner_id}/...`. Each one is resolved
through G1's `_assigned`, which checks the live educator session, the active
campus, the active membership and the active per-learner grant. The path's
campus must also equal the learner's own campus.

These IDs all return the byte-identical `404 {"detail": "Record not found"}`:

- malformed;
- random;
- unassigned;
- cross-campus;
- substituted;
- stale, meaning a revoked grant.

Every write re-checks the grant immediately before commit. A grant revoked while
a request is in flight therefore persists nothing.

| Method | Path | Effect |
| --- | --- | --- |
| POST | `/assessments` | Creates a DRAFT administration. |
| GET | `/assessments`, `/assessments/{id}`, `/assessments/{id}/audit` | Read only. |
| PUT | `/assessments/{id}/scores` | Enters scores and responses. Allowed only in IN_PROGRESS or COMPLETED_PENDING_REVIEW. |
| POST | `/assessments/{id}/transitions` | `mark_ready`, `start`, `interrupt`, `resume`, `invalidate`, `resolve_invalid`, `submit`, `finalize` or `void`, with `expected_state`. |
| POST | `/assessments/{id}/evidence` | Moves FINALIZED → EVIDENCE_AVAILABLE. |
| POST | `/assessments/{id}/proposal` | Moves to TEACHER_DECISION_PENDING. Abstains when nothing is scored. |
| POST | `/assessments/{id}/proposals/{pid}/decision` | Teacher approves, edits or rejects, using a compare-and-swap on `expected_version`. |
| POST | `/assessments/{id}/plan` | Records a teacher plan. `delivery_state` is `NOT_REQUESTED`. |
| POST | `/assessments/{id}/progress-monitoring` | Records teacher-confirmed dates. Creates no administration. |
| POST | `/assessments/{id}/supersede` | Corrects a finalized record, with an audit link. |
| GET | `/data-day?cycle=…` | Returns the Data Day packet. Read only. |

### Nothing changes without a recorded teacher action

No recommendation changes placement, starts instruction or schedules anything.

A proposal carries a `proposed_review_on` date. That date is taken from the
campus's next configured Data Day, and the proposal is marked
`proposed_awaiting_teacher_confirmation`. Approving the proposal does **not**
confirm the date. Only the teacher's `confirmed_review_on`, recorded with the
decision, does that. A rejection schedules nothing.

Plans are recorded with `delivery_state: "NOT_REQUESTED"`. No route delivers
instruction to a learner.

## Data Day packet

`GET /data-day?cycle=valor_q2` is built only from canonical records. It returns
these sections:

- **Results.** `current_valid_results` holds results for the requested cycle, and
  `prior_valid_results` holds results for earlier cycles. A valid result is
  finalized, not superseded, not voided, not invalid, and has an intact snapshot.
- **Metadata.** Each result carries its instrument, edition, form, measure,
  purpose, state and fidelity state.
- **`growth_by_measure`.** This is kept per purpose, so progress monitoring and
  benchmark are never mixed. It includes scored points only, and only those with
  the same unit.
- **Records that did not count.** `not_valid_administrations` lists interrupted,
  invalid, voided and superseded records, with the superseding link.
  `skipped_or_invalid_measures` lists measures that were not scored.
- **Cited material.** `cited_evidence` holds the cited evidence, and
  `observed_error_patterns` holds counts of teacher-marked error types.
- **Teacher history.** `prior_teacher_decisions` lists earlier decisions and
  their outcomes: whether a plan was recorded, and the delivery state.
- **Proposals and controls.** `proposed_next_steps` lists the pending proposals.
  `recommended_next_review` lists their proposed dates, each awaiting the
  teacher's confirmation. `controls` gives the approve, edit and reject POST
  paths, with `expected_version`.
- **`audit_history`.** This holds each administration's transition chain and the
  decision chain, each with `chain_valid`.
- **`boundaries`.** All four values are `false`: the packet changes no score,
  alters no placement, starts no instruction and delivers no instruction.

Reading the packet writes nothing; a test compares row counts.

## G2 adapter seam (#604)

G2's `PilotEvidence`, `PilotRecommendation` and `PilotDecision` live on
`feat/valor-pilot-g2-teacher-journey` and are restacked later.
`services/canonical_assessment_adapter.py` is the one place the two sides meet.

- `to_g2_evidence_submission()` maps one **scored** measure from a **finalized**
  record to G2's real `EducatorAssessmentSubmission` body. The test validates
  against that model. It refuses skipped, unfinalized and windowless records.
  Printed labels are not translated into G2's band vocabulary, because
  translating would be computing a band.
- `to_g2_decision_input()` maps a canonical decision to G2's `DecisionInput`
  body.
- `TeacherDecisionLink` and `TeacherDecisionSink` describe the join record. After
  restack, it links a canonical proposal and decision to a G2 recommendation ID
  without rewriting either table.

## Deleting a pilot learner

`homeschool-api/services/pilot_learner_deletion.py` removes one pilot learner's
**active application records**. Its tests are in
`tests/test_pilot_learner_deletion.py`, which runs on SQLite and on Postgres.

It is keyed by campus UUID and learner UUID, never by a display name. In one
transaction it:

1. locks the `pilot_learners` row `FOR UPDATE`;
2. signs out every teacher who held a grant for the learner, by raising their
   credential version;
3. deletes the learner's rows from every table below, by `(campus_id, learner_id)`:
   `pilot_assessment_administrations`, `pilot_assessment_scores`,
   `pilot_assessment_responses`, `pilot_assessment_transitions`,
   `pilot_assessment_evidence`, `pilot_assessment_proposals`,
   `pilot_assessment_decisions`, `pilot_assessment_plans`,
   `pilot_progress_monitoring_schedules`, `pilot_roster_grants`, and last
   `pilot_learners` (the encrypted display name);
4. deletes any household-shaped row stored under the learner's institutional
   storage subject (`pilot:<campus_uuid>:<learner_uuid>`) in every table with a
   `student_name` column, except `student_keys`;
5. re-counts every one of those tables by learner UUID alone, and rolls the whole
   transaction back if any row remains.

Only after the commit succeeds does it call `evict_learner` from
`core/learner_scope.py`. That drops the learner's prompt-cache entries and the
unwrapped data key, in every environment. A deletion that fails is never
evicted, so a failure never reports success.

The campus calendar and benchmark authorization are kept. They describe the
campus, not the learner.

**The tombstone.** One audit event, `student.data_deleted`, whose detail is
exactly:

```
pilot_learner_deleted campus=<uuid> learner=<uuid> rows=<n> tables=<n>
```

It holds the UUIDs, the counts, the timestamp and the actor role. It never holds
a name, score, label, evidence text or note. A test scans the whole audit view
for the fixture's content.

**Concurrency.** A teacher's write re-checks the grant immediately before commit
and holds the learner row `FOR SHARE` until it commits. A write in flight is
therefore either deleted with everything else, or waits and then answers the
uniform `404`. Both orders are tested on Postgres.

Granting a teacher access to the learner (`approve_roster_grant` in
`routers/pilot_campuses.py`) takes the same `FOR SHARE` lock until the grant
commits. A grant racing a deletion is therefore either deleted with everything
else, or waits and then answers the uniform `404` and writes nothing. Both
orders are tested on Postgres.

**After deletion,** every learner route, the Data Day packet, the per-assessment
audit, `GET /pilot/me/learners`, and a direct lookup of an old administration ID
all answer the uniform `404 Record not found`. Re-granting the learner is also
`404`.

**What this is not.** It is not secure deletion, permanent erasure, or backup
destruction. These tables are encrypted under the deployment's data key, not a
per-learner key. Database backups, write-ahead log segments and dead tuples taken
before the deletion may still hold encrypted historical copies, readable by this
deployment, until a human-approved retention policy exists. The learner's
`student_keys` row, if one exists, is left in place. Destroying it would be
per-learner cryptographic erasure, which is a human-only decision.

Eviction is per process. Another replica's cache entries expire within their TTL.

**Integration seam.** No deletion route exists on this base. The owner route in
#609 (`routers/pilot_owner.py`) should call `delete_pilot_learner` after the
restack, and pass its content-free receipt as `before_commit` so the receipt
commits with the deletion. Its G2 tables must join the cascade; the metadata
guard fails until they do. The caller authorizes the actor. The service
authorizes nothing itself.

## Not built or deferred

- **Campus engagement rubric.** This is deferred until the owner decides whether
  character-adjacent categories may be stored at all. No rubric table, route or
  field exists.
- **Learner deletion route.** The deletion *service* is built (see "Deleting a
  pilot learner" below). No route on this base calls it; the owner route arrives
  with #609.
- **Per-learner cryptographic erasure.** Not built. Destroying a per-learner key
  is a human-only decision.
- **Delivery to a learner session.** This is not built. Plans stay at
  `NOT_REQUESTED`.
- **Teacher UI for these routes.** This is not built in this lane. The routes are
  reachable over HTTP and tested there.
