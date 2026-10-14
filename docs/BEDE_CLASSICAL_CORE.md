# Bede Classical Core — startup release contract

**Product intent:** Bede is an independent, household-controlled,
constitution-governed AI companion for classical instruction. It belongs
to the Agnus Dei product family, *beside* Portal and optional Locuto,
not inside either one.

**Release posture:** narrow, complete first family use case that
reduces the homeschool educator's preparation, instructional support,
diagnostic review, and follow-up burden while retaining human authority.
No claim of independent instructional replacement is implied.

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

## Educator-first operating model — the reason Bede exists

**Bede is a supportive teaching system, not a replacement for a
homeschool parent, classical instructor, or classroom community.**
Its value is reducing complex, repetitive instructional workload
while preserving the educator's voice, discernment, and oversight.

The initial usable workflow has five concrete responsibilities:

| Educator's demanding work | Bede's operating responsibility | Educator keeps authority |
| --- | --- | --- |
| Assemble and revisit a lesson | Reuse approved subjects, focus, books, and resumable lesson context | Select and approve curriculum and session focus |
| Lead individual tutoring while attending to other responsibilities | Conduct bounded Socratic dialogue, read/narrate, scaffold academic questions and practice | Set pace, intervene, redirect, or stop |
| Track what work the learner actually completed | Record encrypted narration/academic activity and existing diagnostic observations | Correct context and interpret the evidence |
| Review diagnostic and external assessment information | Offer math diagnostics, mastery estimates with uncertainty, and parent-only DIBELS/classical educator-entered evidence | Administer external instruments separately and decide the next educational action |
| Prepare the next sitting | Surface progress and relevant prior work; suggest but never impose an instructional adjustment | Approve the next lesson and respond to the learner |

This is a **workload-reduction and teacher-augmentation model**, built around
classical books, narration, Socratic questioning, reasoning and continuity.
AI is not an independent instructor with authority over a child. It does
not infer character, virtue, faith, aptitude, or a learning-style identity.

### What a supportable foundation must demonstrate

Use an educator-completed full-day and second-day rehearsal, not just
component tests:

1. An adult can prepare and start a real lesson quickly from approved
   settings without touching source code.
2. The student experiences accurate, age-appropriate classical dialogue.
3. Bede preserves academic observations, respecting source and consent
   boundaries; it does not claim external DIBELS scores were AI-administered.
4. The educator can see academic evidence, distinguish observations from
   inferred diagnostics, and make a next-step decision.
5. The student returns for another lesson with approved continuity.
6. A normal support operator can install, update, restore, and troubleshoot
   the declared supported deployment using written instructions.

The outcomes to measure are **educator preparation/review minutes saved,
successful lesson completion, diagnostic accuracy and traceability,
parent satisfaction with the assistance, support incidents, and system
cost per active student**. Academic learning outcomes are assessed
independently; do not automatically equate saved staff time with
increased student achievement.

### Market context, without substituting a competitor's business model

Kumon, Acton Academy, and Alpha School illustrate different approaches
to learner progression, guide support, and technology-assisted
instruction. They are useful *research references* for deciding what
educators expect, but they are not Bede's product architecture,
curriculum, or claims of equivalent school provision. Bede is designed
to complement human classical instruction and lower its operational
burden. Keep comparative claims limited to outcomes and costs
supported by an appropriate, like-for-like evaluation.

## Organizational student capacity is not a messaging group size

The parent Pod Dashboard now displays **licensed student seats** from
the effective signed Bede license, via the parent-only
`GET /pod/roster-capacity` endpoint. Locuto's organizational entitlements
are negotiated per account and distinguish `max_children` from adult
`max_seats`; the 10-person Locuto messaging Pod cap must **never** be
reused as an organizational classroom roster cap. The current runtime
does not verify Locuto entitlements; do not infer extra licensed
student capacity from a client-provided Locuto limit.

See [Classroom Roster Entitlements](CLASSROOM_ROSTER_ENTITLEMENTS.md).
Different-family educator logins, consented roster assignment and
per-student diagnostic permissions require a separate security-reviewed
milestone before academic institutional pilots.

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
- Educator workload measures, diagnostic interpretation, and any
  educational efficacy claims have human review, not just CI passes.

**Current engineering evidence:** functional single-subject launch code
and invocation regression tests. CI, device rehearsals, and independent
instructional evaluation must be independently recorded before declaring
the complete startup foundation validated.
