# Bede Classical Core — startup release contract

**Product intent:** Bede is an independent, household-controlled,
constitution-governed AI companion for classical instruction. It belongs
to the Agnus Dei product family, *beside* Portal and optional Locuto,
not inside either one.

**Release posture:** narrow, complete first family use case; no claim
that Bede has already demonstrated equivalent or superior educational
outcomes to Kumon, a classical school, a live tutor, or a co-op.

## The one job the foundation must do

A parent should be able to run a real classical lesson from beginning to
end without assembling a technology stack:

1. **Prepare**: select a student and a subject from the family's already
   approved daily plan, with an optional short focus or reading note.
2. **Teach**: start a genuine Bede tutoring session with Socratic dialogue,
   curriculum/context prompts, age safeguards, and any approved learning
   support intact. The student is present with the adult.
3. **Observe**: use the existing encrypted work ledger, narrated academic
   assessment, and appropriate diagnostic area, not a new personality score.
   Externally reported DIBELS results and classical observations remain
   separately labeled, per `docs/ASSESSMENT_INTEROPERABILITY.md`.
4. **Review**: the parent opens Progress for the same student, sees recorded
   academic work and approved assessment evidence, and determines what to
   change next. Bede's teaching suggestions are advisory.
5. **Continue**: existing lesson-resume fields and parent planning
   settings govern the next sitting; changing a day's plan still requires
   an explicit parent edit in Setup.

### This increment: launch from the actual Parent Pod

`PodDashboard` now offers **Teach one subject now** for each student.
A parent chooses an already approved subject, optionally describes the
focus, and begins a single-subject tutoring session on the parent
device. It uses the same `TutorSession` and `SessionConfig` as the
ordinary child tablet rather than implementing another tutor.

`prepareFocusedLesson` creates a session-only copy. No API call rewrites
the saved daily schedule. Unrelated resume entries are removed from the
temporary session, while constitutional, learning-support, access,
voice and accessibility settings remain unchanged. The existing tablet
links continue to load the unchanged daily plan from the server.
**Review academic evidence** opens the existing parent-only Progress
screen with the student selected.

The parent-led pathway is real instruction, not an anonymous demo or
throwaway preview. It can produce saved student academic evidence.

## Differentiation, not borrowed prestige

Kumon's published approach emphasizes individual learning levels,
small-step exercises, independent work, and instructor oversight.
Its tablet product includes assigned practice and instructor feedback.
Bede should measure against those *operational* dimensions without
copying worksheets, claiming accreditation, or reporting invented
learning gains.

Bede's intended educational distinction is different: a **classical
conversation** around books and ideas, careful questioning, oral and
written narration, reasoning, history, sciences and the arts, with
mathematics and literacy foundations where appropriate. Families
remain the educational authority. Technology follows pedagogy and
children never receive judgments of faith, virtue or aptitude.

Fair comparisons require separately defined baselines:
- **Operational:** an adult can set up the lesson, help a child start,
  see recorded academic work, and return next time without developer help.
- **Quality:** independent educators evaluate factual accuracy,
  appropriate Socratic prompts, source honesty, and usefulness of
  follow-up suggestions against predeclared rubrics.
- **Outcomes:** compare independent transfer tasks and observed academic
  development over time, with informed family consent and qualified
  assessment review. A benchmark is not a causal efficacy study.
- **Supportability:** document the supported deployment, backup, reset,
  model cost, failure handling, and an escalation procedure before
  selling it as a generally available service.

No comparative superiority claim is authorized by the existence of
a feature, an automated test, or an attractive interface.

## Deliberate startup exclusions

- No central Portal table of students, diagnostics, tutoring transcripts,
  or private lesson plans. The Portal handles its own membership,
  licensing, discovery, and curricular resource catalogue.
- No Portal login dependency for this parent-led teaching action.
- No Locuto dependency, mandatory messaging app, or portal-connected
  student-data exchange.
- No broad classroom roster, multi-family instructor write permissions,
  or multi-tenant access without a separately tested authorization and
  data isolation model.
- No autonomous curriculum rewriting, child profiling, unapproved model
  training, or AI alteration of the constitutional constraints.
- No inferred DIBELS standard scores, publisher benchmark tables, or
  proprietary instructional materials redistributed through Bede.

## Supportable release gate

A starter family release must show all of the following on a **declared
supported stack**:

- Parent creates a plan, launches a focused lesson, and opens the
  student's progress from the same workspace.
- A previously approved subject cannot be silently replaced or added.
- A parent-led lesson cannot mutate the saved child tablet schedule.
- A child cannot open adult-only diagnostics or assessment records.
- An offline/unavailable model or corrupted record produces a clear,
  recoverable error without data leakage.
- Source and student-key encryption/deletion controls remain intact.
- A second ordinary teaching day works from persisted student settings.
- Real-device accessibility, installation, backup/restore, and restart
  rehearsals completed on the supported platform.
- Evidence and educational efficacy claims have human review, not just
  CI passes.

**Current engineering evidence:** functional single-subject launch code
and invocation regression tests. CI, device rehearsals, and independent
instructional evaluation must be independently recorded before declaring
the complete startup foundation validated.
