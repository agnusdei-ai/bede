# Bede Roadmap — Toward the Orchestration North Star

## North Star

Christian homeschooling families and co-ops manage curricula, household
info, events, and cross-family coordination in fragmented, non-digital, or
insecure ways. Bede's North Star is to become the AI-enabled coordination
layer for a family's — and their co-op's — flow of learning:

```
Student asks question
        ↓
Bede determines intent
        ↓
Checks curriculum
        ↓
Checks parent's philosophy
        ↓
Checks grade level
        ↓
Checks previous lessons
        ↓
Checks family travel plans
        ↓
Checks co-op schedule
        ↓
Produces response
        ↓
Updates learning graph
```

This document tracks each step against what's actually implemented today,
so the gap between vision and shipped product stays honest and visible —
in the codebase, in docs, and in anything derived from this roadmap
(pitch materials, the trademark filing's intent-to-use classes, investor
conversations).

## Status of each step today

| # | Step | Status | Where |
|---|---|---|---|
| 1 | Determines intent | 🟡 Implicit | No explicit intent-classification step; the model infers intent from the current subject + message within a single cached system prompt turn |
| 2 | Checks curriculum | ✅ Implemented | `services/catalog_service.py` — Ambleside Online-derived book lists and term plans per grade year, plus a Catholic catechism scope note, injected via `_get_catalog_context()` |
| 3 | Checks parent's philosophy | 🟡 Partial | Hardcoded to Charlotte Mason in the static system prompt (`ai_service.py`); not a per-parent configurable philosophy check |
| 4 | Checks grade level | ✅ Implemented | `GradeStage` enum + `grade_to_stage()`, drives narration pacing and UI timers |
| 5 | Checks previous lessons | 🟡 Partial | Current-subject history is sliced into every request (`getApiMessages`); `SessionTranscript` and `NarrationAssessment` tables persist past sessions, but nothing yet actively re-surfaces prior lessons into a new session's context |
| 6 | Checks family travel plans | ⬜ Not started | No schema, no storage, no UI |
| 7 | Checks co-op schedule | ⬜ Not started | No schema, no storage, no UI. `PodConfigsRequest` models a single family's up-to-10 students, not a multi-family co-op |
| 8 | Produces response | ✅ Implemented | Core tutoring loop, SSE streaming, agentic tool cards |
| 9 | Updates learning graph | 🟡 Foundation exists | `NarrationAssessment` (per-narration encrypted rubric, `adaptive_signal`, versioned via `rubric_version`) and `LearnerProfile` (now a history table — one row per synthesis, not an overwritten snapshot) are real, persisted, encrypted tables — a relational precursor to a graph, not a graph structure itself. Profile freshness is now automatic (session-end fire-and-forget refresh), not dependent on a parent remembering to click "build." Still not injected into Bede's own prompt context — that's the remaining Phase A work. |

## Phased plan for the four target steps (2, 6, 7, 9)

Step 2 is already real — included here to show its maturity path forward,
not because it needs to be built from scratch.

### Step 2 — Curriculum depth (mature further)
- **Today:** book-list and term-plan notes injected per subject/grade year.
- **Phase A:** surface catalog coverage back to the parent (what's been
  covered vs. remaining in the year) instead of only forward into the
  prompt.
- **Phase B:** let a parent override/extend the catalog per family
  (already partially possible via `current_unit`), tracked longitudinally.

### Step 6 — Family travel plans
- **Today:** nothing.
- **Phase A (spike):** a `FamilyEvent` concept (date range, label, subject
  impact — e.g., "no formal lessons," "field-trip tie-in for history") —
  parent-entered only, encrypted at rest like every other student/family
  record, surfaced to Bede as a read-only context note (never a new tool
  Bede can write to unprompted).
- **Phase B:** Bede adjusts pacing/expectations around a travel window
  (e.g., lighter narration load, ties history/geography to the actual
  trip) — this is the first point where it actually changes tutoring
  behavior, not just storage.
- **Data note:** travel dates are sensitive household PII; this needs the
  same AES-256-GCM treatment as everything else, and its own audit-log
  coverage — not a shortcut table.

### Step 7 — Co-op schedule
- **Today:** nothing; `Pod` currently means "one family's students," not
  a multi-family group.
- **Phase A (spike):** define what a co-op actually is in the data model
  — a group of pods that share a schedule, distinct from any single
  family's encryption boundary. This is the biggest open design question
  on the whole roadmap: today, each family's data is encrypted and scoped
  to that family. A co-op means *some* data (meeting days, shared subject
  blocks) needs to be visible across families without breaking the
  per-family encryption/security model described in `CLAUDE.md`.
- **Phase B:** read-only co-op calendar surfaced to Bede as context
  (similar to travel plans) so it can avoid suggesting conflicting
  independent work on a co-op day.
- **Phase C:** actual cross-family scheduling UI (parent-facing), which is
  a larger product surface, not just a context note for Bede.

### Step 9 — Learning graph
- **Today:** `NarrationAssessment` + `LearnerProfile` already capture
  per-student mastery signals and a synthesized profile — this is real,
  shipped groundwork, not a green field.
- **Phase A progress:**
  - ✅ `rubric_version` stamped on every new `NarrationAssessment` and
    `LearnerProfile` row (`models/schemas.RUBRIC_VERSION`), so the rubric
    can evolve later without silently blending incompatible historical
    scores. Existing rows predate this and carry `rubric_version=None`
    ("legacy"), not a backfilled guess.
  - ✅ `LearnerProfile` converted from a single overwritten snapshot
    (`student_name` as primary key) into a proper history table
    (`learner_profile_history`) — every synthesis appends a row. New:
    `GET /narration/{student}/profile/history` for a parent to see how
    the profile evolved, not just its current state.
  - ✅ Profile freshness is now automatic: `POST /tutor/summary` (real
    session end) fire-and-forgets `refresh_learner_profile_if_stale`,
    which re-synthesizes only if new assessments accrued since last
    time. No longer depends on a parent remembering to visit Progress
    and click "build profile" — that button still exists as a manual
    override, but isn't the only path to freshness anymore.
  - ⬜ Still open: actually reading this back into Bede's own prompt
    context at `[START]` — the original point of "checks previous
    lessons" (step 5). Everything above is the freshness/history
    prerequisite; the injection itself hasn't been built yet.
  - ⬜ Still open: benchmarking/validation. `rubric_version` makes the
    rubric *safe to evolve*, but there's still no ground-truth
    validation of what these scores actually predict — the assessment
    is an LLM judgment call, not a validated diagnostic. Worth its own
    design pass before this is presented to parents as more than a
    beta signal.
- **Phase B:** model relationships between concepts/units (not just a flat
  per-subject score) — this is where "graph" becomes literal rather than
  a relational stand-in. Needs a concrete decision on whether this lives
  in Postgres (adjacency tables) or a dedicated graph store, deferred
  until Phase A proves out what data actually needs to be connected.

## How "active but not fully tested" gets tested safely

Given this handles children's data, family schedules, and (for co-ops)
data that touches multiple families at once, none of Phases A/B above
should go to real families silently. The existing `FeedbackRequest` /
`routers/feedback.py` beta-feedback path is the right mechanism to build
on, not a substitute for it:

- Each new capability ships behind an explicit flag, opt-in per family
  (parent turns it on knowingly, same as any other `SessionConfig`
  setting) — never silently active for existing users.
- Anything parent-facing as "beta" is labeled as such in the UI, not
  presented as finished.
- Feedback is collected through the existing `FeedbackRequest` category
  system (`cx`, `ux`, `content_quality`, `other`) rather than an ad hoc
  channel.

## Definition of "initial release maturity"

A phase graduates out of beta when, over a rolling window (proposed: 4
weeks of active use across opted-in families):
- No open P0/P1 bugs tied to the feature.
- No security/audit-log anomalies traced to the feature.
- Parent feedback rating (1–5 scale, existing `FeedbackRequest.rating`)
  averages ≥ 4 across a minimum sample size, to be set once opt-in volume
  is known.

These thresholds are a starting proposal, not fixed — revisit once Phase
A of any given step actually has real families using it.

## Maintaining this document

This roadmap should be updated at the end of each phase above — status
table, phase notes, and the North Star flow diagram itself — so it never
drifts from what's actually shipped. Anything sourced from this document
(pitch materials, trademark intent-to-use language, investor
conversations) should always trace back to the status column here, not
to the aspirational flow diagram alone.
