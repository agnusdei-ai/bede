# Educator navigation and assessment acceptance contract

Status: acceptance specification, NOT a claim that all screens or tests exist.
Sequence: finish backup (#574), educator identity (#575), tenant and learner
authorization (#576), then integrated installer (#578), before institution use.

## Teacher task navigation

The educator desk must present five clear task destinations with the selected
campus and assigned learner always visible:

1. **My Class**: assigned learners, missing assessments, recent activity,
   unresolved needs, and next action. Empty or unauthorized roster never
   leaks names from another campus.
2. **Official record**: select an authorized campus and learner; record
   DIBELS 8 edition, approved form identifier, benchmark or progress-monitoring
   purpose, grade, official window and Valor Data Day cycle. Link to publisher
   materials; do not reproduce passages, items, or protected scoring forms.
3. **Teacher observation**: independently capture fluency, error patterns,
   circumstances, narration, taught concepts and interpretation. Keep these
   separate from the immutable official score and cited evidence.
4. **Review Bede suggestion**: cite canonical evidence and invite explicit
   teacher approve, edit or reject. The teacher personally delivers any
   approved instruction. The pilot cannot start a learner session;
   `delivery_state = NOT_REQUESTED` remains enforced.
5. **Review Growth**: compare only source-compatible benchmark results and
   progress-monitoring measures, show omission statuses without numeric zero,
   and record the teacher's observation at the next checkpoint.

## DIBELS 8 boundaries

- DIBELS is the University of Oregon's reading assessment. Use only legally
  authorized materials and follow official administration and scoring
  instructions. Record an educator-reported external score and original
  source; Bede may not fabricate a score from learner chat.
- Score entry validates measure, reported unit, numeric bounds, and source.
  The teacher enters scores, marks and interpretation; Bede never calculates
  official scoring norms or composites. A reported composite is not
  verified until all applicable official subtests and report provenance
  have been checked against the authorized source.
- Progress-monitoring measures and composite scores must not be confused,
  nor should tests at differing grades/windows be plotted as a single
  comparable series without explanation.
- Proposed instructional focus is a teacher-reviewed recommendation, not
  automatic diagnosis or proof of causal learning improvement.
- Other future frameworks enter through the existing catalog with
  framework-specific schema, provenance, permission and validation.

## UI acceptance journeys

| ID | Given | When | Required outcome |
| --- | --- | --- | --- |
| E01 | Approved educator with no assignments | Opens My Class | Accessible empty state; no learner disclosure |
| E02 | Two campuses each with a same-named student | Opens roster/evidence and direct URL/API | Only learner UUID and campus-granted records appear |
| E03 | Assigned learner, no assessment | Opens Assess | Clear source instructions, supported framework/measure, no fabricated data |
| E04 | Teacher selects valid DIBELS grade/measure/window | Enters external score and source | Stored once with audit, date, units, provenance and stable learner ID |
| E05 | Teacher enters missing source or invalid score | Submits | Field-specific accessible error, no partial write |
| E06 | Teacher opens learner longitudinal view | Reviews two windows | Separate benchmark/progress monitoring displays, no invented trends |
| E07 | Teacher selects reading focus | Confirms support plan | Decision and plan recorded, learner delivery remains NOT_REQUESTED |
| E08 | Teacher returns after personally teaching | Records observation | Separate teacher notes linked to official evidence and next Data Day |
| E09 | Teacher loses authorization | Attempts evidence or marks write | Server denies access; no learner session or stream is created |
| E10 | Admin revokes passkey | Teacher reopens desk | Existing session refused |
| E11 | Browser keyboard/screen reader | Navigates workflow | Landmarks, keyboard focus, announced errors, no pointer-only actions |
| E12 | Slow/offline/failed request | Saves assessment | No duplicate entry, actionable retry and confirmed saved state |
| E13 | Guardian/campus disclosure requested | Attempts report/share | No disclosure absent verified grant, scope, purpose and policy |
| E14 | Conflicting imported assessment | Reviews/proposes correction | Versioned source and audit, no silent overwrite |

## Completion evidence

- Component tests: navigation, forms, empty states, saved states, keyboard
  and error announcements.
- API integration: authorization by institution, campus and learner UUID;
  source-preserving assessment entry; no duplicates/replay; audit and
  cross-campus negative cases.
- Browser E2E: invited teacher WebAuthn sign-in → assigned learner →
  official score entry → separate observation → Bede recommendation →
  teacher approve/edit/reject → plan recorded but NOT_REQUESTED →
  evidence review → revoked access.
- Instructor acceptance: one to five owner-led synthetic sessions across
  supported browsers. Capture friction and task completion without genuine
  student data. Do not call the workflow qualified from static mockups.
