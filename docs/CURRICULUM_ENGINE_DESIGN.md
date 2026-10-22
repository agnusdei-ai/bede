# Curriculum Engine Design

Status: PR 0-1 of the sequence tracked in issue #685. Everything is behind `CURRICULUM_ENGINE_ENABLED` (default false). No request path or startup code imports the new package.

## Principles

1. Approved content only. The student-facing tutor retrieves only items that are approved, rights-verified, and in the learner's campus scope.
2. Filters before scoring. Campus, visibility, approval, and rights filters run before any ranking, so isolation is structural.
3. Two loops. The approved base library changes only through staged, human-reviewed promotion. Per-learner adaptation happens through `LessonVariant` records, which are derived, learner-scoped, and expire via `refresh_after` so they are regenerated instead of going stale.
4. A generated item is never approved without a `ReviewRecord` naming a human reviewer.
5. The tutor makes no live web calls. External discovery is a separate, authorized ingestion job.
6. Additive schema only. Skill ids link to a family's mastery history, so content maps to existing ids (see `services/content_curation.known_skill_ids`). New skills are a separate reviewed change.
7. Ranking decisions are explainable: per-term scores are logged without learner PII.

## Ranking model (later PRs)

After hard filters, candidates are scored as:

S = w1*R + w2*A + w3*O + w4*P + w5*L + w6*E

- R: source reliability and provenance
- A: classical alignment
- O: match to the teacher-authorized objective
- P: prerequisite readiness
- L: learner interests and preferred supports
- E: independent evidence of effectiveness, fixed at 0 until the evaluation harness passes and a person signs off

Weights live in versioned config.

## This PR

- `services/curriculum/flag.py`: reads `CURRICULUM_ENGINE_ENABLED`, default false.
- `services/curriculum/models.py`: `SourceRecord`, `ReviewRecord`, `ContentChunk`, `Lesson`, `LessonVariant`, plus invariant checks.
- Persistence (new tables, created idempotently) is deferred to the next PR. This codebase has no ALTER TABLE path, so existing tables are never modified.

## Invariants enforced in code and tests

- Unverified rights can never be approved.
- Approval requires a `ReviewRecord` with an approving decision, matching item id and version, and a human reviewer.
- Verbatim chunks require `public_domain_verified` rights and a cited edition.
- A `LessonVariant` must reference an approved parent lesson version in the same campus, uses an opaque learner reference, and cites evidence references instead of raw scores.
- Declared skill ids must already exist.

## Open items

- Table creation mechanism and encryption pattern for learner-scoped records.
- Review roles and approval rules.
- Authoritative `campus_id` resolution (likely `services/pilot_authz.py`).
