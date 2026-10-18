# Valor Education 2025–26 District Improvement Plan — Bede pilot alignment

Reference: [Valor Education District Improvement Plan, 2025–26](https://static1.squarespace.com/static/62bb35f256ba253716ea0383/t/6937044063831b22abcbdeed/1765213248269/Valor+Education+DIP+2025-26.pdf), board-approved November 24, 2025.

This is a **district improvement plan**, not the licensed DIBELS manual,
a campus testing calendar, a school authorization, or a vendor integration
agreement. Statements below are paraphrases and page references.

| Public plan evidence | Bede teacher-only pilot response | Excluded or not confirmed |
| --- | --- | --- |
| p. 11: NWEA MAP three times per school year, used with formative teacher evidence to identify students who need support | Display manual contextual reference to a source report; preserve separately from official DIBELS measure rows | Do not claim a MAP API adapter, derive MAP scores, or treat its three windows as DIBELS windows |
| p. 21, Goal 1: classroom observation, classical teaching guides, lesson plans are implementation evidence; MAP, DIBELS and STAAR performance/growth inform impact | Capture distinct `implementation_evidence` and `impact_evidence` in encrypted teacher observation; never infer that Bede caused score changes | No automatic STAAR or MAP scoring, no fabricated attribution |
| p. 21: teaching accountability includes staff responsible, timeline, resources, implementation and impact | Capture `responsible_staff_role`, `instructional_strategy`, optional `follow_up_on`; preserve teacher's recorded plan | No autonomous task delegation, notifications, student sessions, or broad staff visibility |
| p. 21: monitoring at beginning, middle and end of year using the district assessment calendar | Keep official benchmark periods BOY/MOY/EOY separate from Bede's configurable Valor Data Day cycles | The DIP does not publish exact campus Data Day dates or authorized DIBELS form IDs |
| pp. 11 and 21: classical education uses Socratic discussion, nature study, coaching and practical activities | Teacher notes what was taught and approves or edits Bede's proposed support plan; teacher personally delivers instruction | Learner-facing Bede tutoring remains out of this pilot |
| p. 21: progress monitored for varied student groups | Preserve per-learner/campus evidence and authorized teacher decisions; group-level analysis is a *future* explicitly authorized workflow | Do not collect sensitive student-group attributes or imply district disaggregation is part of this synthetic pilot |

## Canonical pilot form, two panels

1. **Official assessment record:** authorized learner/campus/administrator,
   DIBELS 8 reference form/edition and measure, date, source, grade, purpose,
   official benchmark period, Valor cycle, accommodations, administration
   timing/marks/discontinue/fidelity, status, reported score and optional
   component values. Numeric missing = null, never zero. Composite is not
   calculated; even transcribed composite eligibility is not publisher-verified
   until the appropriate grade/window requirements and source are established.
2. **Teacher observation:** accuracy, fluency, error patterns, administration
   circumstances, comprehension, concepts taught, teacher interpretation,
   instructional strategy, staff role, next checkpoint, separate implementation
   vs impact evidence, and optional *reference only* to MAP/STAAR reports.
   Teacher controls approve/edit/reject and records an instructional plan.
   `delivery_state` remains `NOT_REQUESTED`.

Official score rows and teacher interpretation are stored separately.
Published proprietary test material, forms, item lists, passages and prompts
must not be embedded in Bede. Authorization, learner deletion, no implicit
score calculations, passkey restrictions and audit records continue to apply.

## Required Valor assessment-lead confirmations before real institution use

- Exact DIBELS edition, applicable K–8 grade/measure/form requirements,
  authorized publisher materials and approved campus form IDs.
- Official benchmark windows and school assessment calendar. Bede's
  `valor_q1` through `valor_q4` are configurable *instructional* checkpoints,
  **not** asserted official benchmark dates.
- Whether MAP, DIBELS and STAAR data arrive through authorized reports,
  manual transcription, mCLASS, the DIBELS Data System, or another provider.
  This pilot does not activate or promise any vendor API connection.
- Who owns score verification, instructional review, and any required
  school-level reporting. The current synthetic teacher-only pilot has no
  permission to process real pupil data.

## Evidence and rollout boundary

Real HTTP synthetic regression: official/source entry, missing-vs-zero,
full required measure set for any explicitly declared composite eligibility,
immutable finalization and supersession, teacher observation separation,
campus/learner isolation, G1 revocation, recorded plan/no delivery.
Physical Mac G3 and **Pilot GO** remain separate human decisions.

This is a mapping of Bede's *current capabilities and pilot boundaries*
against the public DIP, not a representation that Valor approved a new scope.
