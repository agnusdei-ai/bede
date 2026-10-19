# Valor pilot: teacher-review contract (not an autonomous-agent contract)

## Authorized educational sequence

**Official assessment or educator observation captured → Bede presents an
evidence-bound advisory proposal → the teacher approves, edits, or rejects →
Bede prepares a teacher-use instructional artifact from the recorded plan →
the teacher teaches in person or offline → the teacher records follow-up
observation.**

The canonical assessment record is the source of truth for any transcribed
DIBELS 8 result. Bede does not administer, score, norm, relabel, overwrite or
recalculate an official DIBELS measure, and does not treat a teacher follow-up
as an official reassessment. The official report is kept distinct from
interpretation, recommendation, approval, and classroom activity.

## Minimal data contract

| Stage | Required fields | Enforcement |
| --- | --- | --- |
| Official assessment | `assessment_id`, `campus_id`, `learner_id`, instrument/edition/form, purpose, window, measure status, source and immutable `snapshot_sha256` | Authorized teacher captures/transcribes; finalized scores stay immutable and corrections use supersession |
| Evidence | `evidence_id`, `assessment_id`, source score IDs, exact assessment snapshot hash, optional separately attributed teacher observation | References a finalized, intact official snapshot; skipped measures never become zero |
| Bede proposal | `proposal_id`, `evidence_id`, `campus_id`, `learner_id`, policy version, rationale, advisory text, version and proposed review date | Never final or learner-facing; may abstain on missing/invalid evidence |
| Teacher decision | `decision_id`, evidence/proposal/assessment/campus/learner IDs, authorized educator ID, action `approve|edit|reject`, expected version, approved text hash, append-only audit | Real educator WebAuthn session + live roster grant; 409 for stale version; rejected proposals cannot create plans |
| Teacher-use plan | `plan_id`, `decision_id`, `assessment_id`, `campus_id`, `learner_id`, encrypted teacher-entered plan, created-by teacher, `NOT_REQUESTED` delivery | Explicit teacher POST only after approved/edited decision; no delivery, assignment or roster mutation |
| Artifact | `plan_id`, `decision_id`, source `assessment_snapshot_sha256`, teacher approval, plan text and disclosure | **Read-only** GET from an existing authorized plan, not model-autonomous generation; printable, never a DIBELS report or learner assignment |
| After-teaching observation | `follow_up_id`, `plan_id`, `decision_id`, `assessment_id`, `campus_id`, `learner_id`, teacher ID, `observed_on`, teaching mode, encrypted observed outcome and possible next step | Append-only educator POST with current grant check; no official score, assignment, roster or progress-monitoring change |

## Authority and boundary rules

1. G1's assignment lookup resolves the actual learner and campus; a name is
   never an identity. The original grant/version must still be valid at commit.
2. Official assessment and teacher observation are separate facts. The
   teacher's after-teaching account is **teacher-reported**, not a new scored
   DIBELS result, and does not auto-revise a benchmark or instructional tier.
3. A proposed instructional action cannot become a plan without an explicit,
   revision-bound teacher approval or edit. A reject stops that action.
4. Bede does not launch learner instruction from this workflow. The teacher
   uses the approved handout offline, conducts instruction and reports back.
5. Artifact access itself is a read-only operation. A learner session, family
   summary, curriculum assignment or roster update is a **different,
   separately approved action** and is never implied by downloading or
   printing a handout.
6. All sensitive note text remains encrypted and scoped with AAD to the
   canonical campus UUID, learner UUID and row UUID. Follow-ups are removed
   with the learner in the existing G1 deletion cascade.
7. A disallowed, revoked, cross-campus, unassigned, malformed or mismatched
   learner/resource is not discoverable through these endpoints.
8. The teacher may use a printed artifact; the system does not claim or
   infer an objective learning gain from an after-lesson note.

## API additions

- `GET /pilot/campuses/{campus_id}/learners/{learner_id}/assessments/{assessment_id}/plans/{plan_id}/artifact`
- `POST /pilot/campuses/{campus_id}/learners/{learner_id}/assessments/{assessment_id}/plans/{plan_id}/follow-ups`
- `GET /pilot/campuses/{campus_id}/learners/{learner_id}/assessments/{assessment_id}/plans/{plan_id}/follow-ups`

Current official assessment, evidence, proposal, teacher decision and plan
routes remain canonical. No separate model/autonomous agent contract is
introduced. Bede can later enrich the advisory rationale behind the same
teacher-controlled interface without changing the approval boundary.

## Minimum pilot acceptance

With synthetic campuses A and B and identically named learners, verify:
a teacher can complete the authorized lifecycle and open their plan; another
campus cannot read/append it; rejected or pending suggestions produce no
artifact; a version conflict cannot apply a decision; the artifact GET does
not change row counts; after-teaching notes append only to the correct
plan, are visible after reload, and never create official scores or change
rosters. These are functional checks, not Valor production-environment
certification. No real student data is authorized by passing them.

## Versioned schema and synthetic agent-state QA

The strict internal envelope is `services/pilot_teacher_review_contract.py`
(`TeacherReviewCycle`, schema version `1.1.0`). It has four separately
validated responsibilities sharing the same tenant-bound cycle:

1. `OfficialAssessment`: reported assessment status, purpose, benchmark
   window, immutable snapshot digest and educator finalization. This remains
   authoritative and must never be overwritten by Bede reasoning.
2. `EvidenceReview` + `ProposedAction`: advisory observations and an
   allowlist restricted to teacher prep, practice, grouping, observation
   sheets and review packets. No model-generated permission or roster writes.
3. `TeacherDecision`: the live educator identity, decision status, timestamp
   and version that determines which proposals may be used.
4. `GeneratedArtifact`: a paper-oriented output referencing one selected,
   approved action and exactly the current decision/version. Delivery remains
   `NOT_REQUESTED`.

The pure envelope rejects cross-tenant references, absent learner binding,
unfinalized DIBELS-based proposals, mixed benchmark/progress-monitoring
purpose, implicit approval, edited/stale version, unknown actions, and
artifacts after teacher rejection. Synthetic positive and negative scenario
tests live in `tests/test_pilot_teacher_review_contract.py`.

**Runtime separation:** the existing canonical assessment database and
scoped G1 routes remain the actual authority for reads/writes, formal
decisions, plan generation and follow-up. This envelope is a defensive
validation contract; landing it does not by itself claim that every API
response is persisted as one document or that every response has been
automatically validated through the new envelope. The PR's artifact and
follow-up endpoints have their own G1 authorization, snapshot and decision
checks. Physical Mac and G3 remain separate release gates.
