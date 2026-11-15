# Bede v1.0 pilot content inventory

**Content revision:** `pilot-content/2026-11-15` (recommender `pilot-recommender/2`,
official-record proposals `canonical-review-2026-11-15`).
**Scope:** the teacher-only Valor pilot. Household and demo content is not
part of this inventory and is not reviewed here.
**What this is:** a record of what a teacher sees or prints in the pilot,
what was checked, and what is still owed. It is not a claim that an
educator has signed off. Every review below was done by reading the code,
running it, and looking at the printed result in one working session; the
"reviewer" line says so.

Statuses are `accepted`, `needs_revision` and `excluded_from_pilot`.
Nothing required is excluded here. Two items that ship on the teacher desk
but are not named in the pilot agreement are marked as **owner scope
decisions**, not excluded.

## Summary

| Item | Required | Status | Still owed |
| --- | --- | --- | --- |
| `g2-suggestion-wording` | yes | accepted | educator read-through |
| `official-record-proposal-wording` | yes | accepted | educator read-through |
| `teacher-plan-sheet` | yes | accepted | print from a real Mac and Safari |
| `assessment-framework-catalog` | yes | accepted | check against the publisher's guide |
| `teacher-screen-copy` | yes | accepted | educator read-through; Spanish scope decision |
| `school-data-notice` | yes | accepted for sample data | counsel review before any real learner data |
| `valor-sample-records` | yes | accepted | none |
| `teacher-quiz-studio` | owner to decide | accepted | scope decision |
| `educator-quiz-drafting` | owner to decide | needs_revision | scope decision; output depends on the campus's local model |

## Findings fixed in this revision

1. **Suggested focuses were picked in alphabetical order of the measure
   code.** With three measures at the same support level the two kept were
   the first two alphabetically, so a comprehension measure could displace
   phonemic awareness. They now follow the reading-skill sequence (sounds,
   letters, decoding, word reading, connected text, comprehension).
2. **Internal codes reached the teacher** (`PSF`, `intensive_at_risk`). The
   reason now reads "Phonemic Segmentation Fluency (PSF), 2026-11-10: the
   source report lists intensive support (at risk), so this skill is
   suggested for practice."
3. **Two focuses told the teacher to practise the test task itself**
   (letter naming, the Maze task). They now name the skill: letter-name and
   letter-sound practice; comprehension practice with connected text.
4. **"Continue current instruction" was proposed when the composite was
   printed Below or Well Below Benchmark** and no single measure was
   labelled. The proposal now says the composite calls for support, names
   no skill, and leaves the focus to the teacher.
5. **"Continue current instruction" was proposed when no label was
   entered at all.** The proposal now says no focus is suggested and why.
   It stays a proposal so the teacher can still record a decision.
6. **"Print teacher material" printed the whole teacher screen.** It now
   prints one sheet: learner, approval line, the plan, the reasons, lined
   space for notes, and the "not an official score" line.
7. **The suggestion journey had no print at all.** Approved guidance now
   has "Print this plan", shown only after approval.

## Records

```yaml
content_item:
  id: g2-suggestion-wording
  version: pilot-recommender/2
  pilot_required: true
  audience: {grade_or_stage: "K-8 (DIBELS 8 measures), all grades (classical observations)", subject: reading and classical observations, topic: suggested next focus from entered evidence}
  review:
    instructional_accuracy: checked against the measure definitions; educator read-through not done
    classical_socratic_fit: wording describes instruction, never the child; tested
    age_appropriateness: teacher-only text; no learner sees it
    source_and_usage_rights: uses measure names only; no test items, norms or cut points
    answer_key_accuracy: not applicable
    printable_layout: printed through teacher-plan-sheet
    language_review_if_in_scope: English only; Spanish not offered on teacher screens
  teacher_workflow:
    evidence_basis_visible: yes, each reason names the measure, date and the band the report lists
    suggestion_distinct_from_decision: yes, pending until approve, edit or reject
    approve_edit_reject_supported: yes
    paper_output_usable: yes, after approval only
  result:
    status: accepted
    reviewer: automated review in a working session; no educator review
    evidence_refs:
      - homeschool-api/tests/test_valor_pilot_g2_journey.py
      - homeschool-api/services/pilot_recommender.py
    blocking_findings: [educator read-through of the focus wording is outstanding]
```

```yaml
content_item:
  id: official-record-proposal-wording
  version: canonical-review-2026-11-15
  pilot_required: true
  audience: {grade_or_stage: K-8, subject: reading, topic: proposed next step from one finalized official record}
  review:
    instructional_accuracy: proposes only from labels printed on the report; never computes a band
    classical_socratic_fit: describes instruction, never the child; tested
    age_appropriateness: teacher-only text
    source_and_usage_rights: transcribed labels only
    answer_key_accuracy: not applicable
    printable_layout: printed through teacher-plan-sheet
    language_review_if_in_scope: English only
  teacher_workflow:
    evidence_basis_visible: yes, each printed label is listed as a reason
    suggestion_distinct_from_decision: yes, `is_approval` is always false on a proposal
    approve_edit_reject_supported: yes
    paper_output_usable: yes, after a plan is recorded
  result:
    status: accepted
    reviewer: automated review in a working session; no educator review
    evidence_refs:
      - homeschool-api/tests/test_canonical_proposal_wording.py
      - homeschool-api/tests/test_canonical_assessment_api.py
    blocking_findings: [educator read-through is outstanding]
```

```yaml
content_item:
  id: teacher-plan-sheet
  version: pilot-content/2026-11-15
  pilot_required: true
  audience: {grade_or_stage: all, subject: all, topic: printed teacher-use plan}
  review:
    instructional_accuracy: prints the approved text unchanged
    classical_socratic_fit: not applicable
    age_appropriateness: teacher-only sheet, marked for teacher use
    source_and_usage_rights: the teacher's own approved text
    answer_key_accuracy: not applicable
    printable_layout: one page for a short plan, four for a very long one, nothing clipped, in headless Chromium
    language_review_if_in_scope: English only
  teacher_workflow:
    evidence_basis_visible: yes, the reasons print under the plan
    suggestion_distinct_from_decision: yes, the sheet carries the approval line and exists only after approval
    approve_edit_reject_supported: not applicable
    paper_output_usable: yes in Chromium; Safari on a Mac not checked
  result:
    status: accepted
    reviewer: automated review in a working session
    evidence_refs:
      - homeschool-tutor/src/utils/printTeacherPlan.test.ts
      - homeschool-tutor/src/components/PilotTeacherJourney.test.tsx
      - PDF renders made in the session (not archived)
    blocking_findings: [print from Safari on the pilot Mac is outstanding]
```

```yaml
content_item:
  id: assessment-framework-catalog
  version: pilot-content/2026-11-15
  pilot_required: true
  audience: {grade_or_stage: K-8, subject: reading and classical observations, topic: measures, units and band labels a teacher picks from}
  review:
    instructional_accuracy: measure and unit pairs read correctly; not compared line by line with the publisher's guide
    classical_socratic_fit: classical observation types are listed beside DIBELS, never merged with it
    age_appropriateness: teacher-only
    source_and_usage_rights: names and labels only; no items, norms, cut points or administration text
    answer_key_accuracy: not applicable
    printable_layout: not printed
    language_review_if_in_scope: English only
  teacher_workflow:
    evidence_basis_visible: yes
    suggestion_distinct_from_decision: not applicable
    approve_edit_reject_supported: not applicable
    paper_output_usable: not applicable
  result:
    status: accepted
    reviewer: automated review in a working session
    evidence_refs:
      - homeschool-api/services/assessment_interop.py
      - homeschool-api/tests/test_assessment_interop.py
    blocking_findings: [comparison with the publisher's administration guide is outstanding]
```

```yaml
content_item:
  id: teacher-screen-copy
  version: pilot-content/2026-11-15
  pilot_required: true
  audience: {grade_or_stage: all, subject: all, topic: headings, buttons and notices on the two teacher journeys}
  review:
    instructional_accuracy: no screen claims delivery to a learner; tested
    classical_socratic_fit: "You decide what is helpful" framing kept
    age_appropriateness: teacher-only
    source_and_usage_rights: our own text
    answer_key_accuracy: not applicable
    printable_layout: not printed
    language_review_if_in_scope: not in scope as built (English only); offering Spanish is an owner decision
  teacher_workflow:
    evidence_basis_visible: yes
    suggestion_distinct_from_decision: yes
    approve_edit_reject_supported: yes
    paper_output_usable: yes
  result:
    status: accepted
    reviewer: automated review in a working session
    evidence_refs:
      - homeschool-tutor/src/components/PilotTeacherJourney.test.tsx
      - homeschool-api/tests/test_pilot_teacher_review_contract.py
    blocking_findings: []
```

```yaml
content_item:
  id: school-data-notice
  version: sha256 699a1bb983a268ee5cf76107f45c777f3b7453454521bd1d1a4d80968da371d8
  pilot_required: true
  audience: {grade_or_stage: all, subject: all, topic: the notice a school official authorizes before learner data is stored}
  review:
    instructional_accuracy: not applicable
    classical_socratic_fit: not applicable
    age_appropriateness: adult reader
    source_and_usage_rights: our own text; wording is counsel's to settle
    answer_key_accuracy: not applicable
    printable_layout: not printed
    language_review_if_in_scope: English only
  teacher_workflow:
    evidence_basis_visible: not applicable
    suggestion_distinct_from_decision: not applicable
    approve_edit_reject_supported: not applicable
    paper_output_usable: not applicable
  result:
    status: accepted
    reviewer: unchanged in this revision; not reviewed by counsel
    evidence_refs:
      - homeschool-api/data/school_data_notice.txt
      - docs/SCHOOL_DATA_AUTHORIZATION.md
    blocking_findings: [accepted for sample data only; counsel review is required before real learner data]
```

```yaml
content_item:
  id: valor-sample-records
  version: pilot-content/2026-11-15
  pilot_required: true
  audience: {grade_or_stage: K-8, subject: reading, topic: two sample campuses with same-named sample learners}
  review:
    instructional_accuracy: not applicable
    classical_socratic_fit: not applicable
    age_appropriateness: no person's name, identifier or email
    source_and_usage_rights: made for this project
    answer_key_accuracy: not applicable
    printable_layout: not applicable
    language_review_if_in_scope: not applicable
  teacher_workflow:
    evidence_basis_visible: not applicable
    suggestion_distinct_from_decision: not applicable
    approve_edit_reject_supported: not applicable
    paper_output_usable: not applicable
  result:
    status: accepted
    reviewer: automated review in a working session
    evidence_refs: [homeschool-api/tests/valor_sample_fixture.py]
    blocking_findings: []
```

```yaml
content_item:
  id: teacher-quiz-studio
  version: pilot-content/2026-11-15
  pilot_required: owner scope decision (on the teacher desk; not named in the pilot agreement)
  audience: {grade_or_stage: K-8, subject: any taught subject, topic: a teacher's own quiz, its key, printing and scoring}
  review:
    instructional_accuracy: the teacher writes or approves every answer; scoring is fixed code
    classical_socratic_fit: written responses are proposed for review, never auto-marked
    age_appropriateness: the student page is the teacher's own questions
    source_and_usage_rights: the teacher's own material
    answer_key_accuracy: the key prints only after approval; unsettled answers block it; tested
    printable_layout: student page and answer key are separate prints; a key never shares a page with the quiz
    language_review_if_in_scope: English and Spanish labels exist
  teacher_workflow:
    evidence_basis_visible: yes, each answer shows where it came from
    suggestion_distinct_from_decision: yes, proposed scores wait for the teacher
    approve_edit_reject_supported: yes
    paper_output_usable: yes
  result:
    status: accepted
    reviewer: automated review in a working session
    evidence_refs:
      - homeschool-api/tests/test_teacher_quiz.py
      - homeschool-tutor/src/components/TeacherQuizStudio.test.tsx
      - homeschool-tutor/src/utils/printDocument.test.ts
    blocking_findings: [owner to say whether this is in the pilot]
```

```yaml
content_item:
  id: educator-quiz-drafting
  version: pilot-content/2026-11-15
  pilot_required: owner scope decision (on the teacher desk; not named in the pilot agreement)
  audience: {grade_or_stage: K-8, subject: taught subjects except the faith subjects, topic: quiz questions drafted by the campus's local model}
  review:
    instructional_accuracy: cannot be reviewed as fixed content; each draft is new and depends on the local model
    classical_socratic_fit: not reviewed
    age_appropriateness: not reviewed
    source_and_usage_rights: questions copied from the source are dropped in code
    answer_key_accuracy: math answers are recomputed; other answers are cross-checked by a second model call, not against sources
    printable_layout: same print path as the quiz studio
    language_review_if_in_scope: not reviewed
  teacher_workflow:
    evidence_basis_visible: each answer is marked computed, checked or verify
    suggestion_distinct_from_decision: yes, the teacher approves before use
    approve_edit_reject_supported: yes
    paper_output_usable: yes
  result:
    status: needs_revision
    reviewer: automated review in a working session
    evidence_refs: [homeschool-api/tests/test_practice_quiz_generation.py]
    blocking_findings:
      - owner to say whether this is in the pilot
      - if it is, a set of drafts from the pilot's actual local model has to be read by an educator first
```

## How to change this file

Change a wording, then change its version here and in the code
(`POLICY_VERSION` in `services/pilot_recommender.py` or
`services/canonical_assessment.py`), and move the content revision at the
top. A status moves to `accepted` on someone's review, with their role and
the date in `reviewer`.
