# Reviewed Grades 9–12 student runtime

Release `bede-upper-2026-reviewed` contains 1,728 original student-facing lessons:
Grades 9, 10, 11 and 12 × 12 strands × 36 weeks. Each lesson was built by the
existing curriculum factory (`curriculum/factory`) from a version-bound record
approved by separate AI author, reviewer, key-verification and (for science,
practical arts, fine arts and movement/health) safety passes.

This is **not** human acceptance, learner-efficacy evidence, school credit or
institutional corpus promotion (`pilot_evaluated: false`, `human_accepted: false`).

## What is published

`homeschool-api/data/curriculum/upper-student.json` (manifest, pinned by
SHA-256 in `services/upper_curriculum_service.py`) and one file per grade and
strand in `upper-student/`. The export (`scripts/export_upper_student_release.py`)
drops teacher worked models, adult answer keys/rubrics, misconceptions and the
private original records. Practical, science and movement work uses the stated
paper/data route and supervision rules.

Strand → tutor subject: literature → `living_books`, composition →
`language_arts`, history, mathematics, science, latin, spanish,
logic and rhetoric → `logic`, computing, fine arts → `art_music`,
practical arts → `nature_study`, movement and health → `movement_health`.
Shared academics are nondevotional; optional faith subjects keep their own route.

## Selection

An adult selects a week (and optionally one lesson) for a Grade 9–12 learner in
Parent Setup (demo and enrolled). The grade comes from the learner plan; a
lesson from another grade, week or disabled subject is rejected. Enrolled turns
use the saved adult plan, never a posted position.

## Operator control

`BEDE_UPPER_CURRICULUM_ENABLED` defaults to `true`. An explicit `false` stops
teaching from this release without deleting saved choices.
