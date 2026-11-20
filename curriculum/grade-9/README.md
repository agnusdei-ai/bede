# Bede Grade 9 — Classical + STEM + AI Foundations

**Review edition · October 28, 2026 · Not a published or accredited offering**

**Current evidence status:** the repository terminology revision changed
source/report bytes. Prior approvals are historical and require re-review;
see [revision and evidence status](reviews/TERMINOLOGY-REVISION.md).

**Current scope decision:** the owner now prioritizes substantive Grades 9–12
content development over unfinished Grade 8 and requests rapid reuse of the
already identified open resources. This supersedes the earlier research-only
Grade 9 authoring limit. The owner subsequently required complete content
published in demo and enrolled Bede, delivered through ordered PRs. This does
not declare Grade 8 complete or bypass rights and review controls.
Start with the [audit and readiness review](audit/README.md).
The Week 10 teaching extensions follow this foundation in a separate PR.
This package is not yet an approved or available complete Grade 9 offering.

An adult-led curriculum design for families, co-ops, and schools. This package does not expand Bede's existing K–8 product, qualify a school deployment, or establish student-facing software capabilities.

## Review in this order

1. [Program, placement and timetable](01-program-and-delivery.md): fit, competencies, credit assumptions, schedules and boundaries.
2. [Resources and procurement](02-resources.md): exact editions, selection rules, licensing checks and costs.
3. [36-week scope and sequence](03-scope-and-sequence.md): four quarters and all six academic courses, with PE/health and practical-arts planning.
4. [First nine weeks: teaching guide](04-starter-lessons.md): daily agendas, original exercises, adult guidance and answer explanations. Use alongside the map, not instead of it.
5. [Assessment toolkit](05-assessments.md): placement, rubrics, first-quarter examples, portfolio and human grading.
6. [Biology investigations](06-biology-labs.md): preparation, supervision, risk controls, alternatives and lab-status limits.
7. [Computing and AI studio](07-computing-project.md): runnable no-account Python baseline, starter data, inquiry project and assessment.
8. [Implementation and status](08-implementation.md): launch checklist, cost worksheet, staffing and unresolved decisions.

## What is ready

- A coherent 36-week **curriculum map**, including specific readings, work products and checks.
- Nine weeks of authored teaching materials for the default sequence: Literature & Composition I, World History I, Algebra I, Biology with Laboratory, Latin I and Logic, Computing & AI Foundations I. Weeks 5–9 include bounded readings, daily PE/arts plans and the quarter demonstration; human adoption gates remain.
- Original exercises, sample responses, lab procedures, rubrics and an executable beginner project.
- A family/co-op/school delivery plan and transparent planning arithmetic.

## What is planned, not authored

Weeks 10–36 are mapped, **not complete daily lesson scripts, worksheets, answer books or a full examination bank** in this foundation package. Week 10 extensions are delivered separately. Geometry is a placement alternative map, not a second fully written starter course. Latin I is the developed default language pathway: full-year sequence plus first-quarter lessons, not a claim that all 180 daily lessons are finished. Modern-language substitution needs a sustained qualified instructor and selected materials.

Before enrollment or claims about credits, a responsible educator must approve level, workload, materials, accessibility and local requirements. Before a paid edition, resolve commercial permissions for linked resources where applicable.

## Review questions

See the [adoption review and decision register](ADOPTION-REVIEW.md) for current evidence, requested changes and owner decisions. The [owner-directed review policy](audit/REVIEW-POLICY.md) replaces routine human subject-review gates with separate evidence-backed agentic review; older human-review wording in teaching materials does not override that policy. Adult instruction, grading, supervision and institutional approval remain separate. Enrollment and paid distribution remain on hold.

- Does the learner need Algebra I, Geometry, or a paced bridge first?
- Can the household or institution supply 32.5 hours of learning time and the adult supervision described?
- Are the selected ancient texts appropriate for this learner, with alternatives available?
- Who teaches and grades language, writing, mathematics and biology?
- Are lab access, accommodations, permissions and school approval actually secured?

Run `python3 curriculum/grade-9/validate.py` for package integrity, map coverage, timetable arithmetic and baseline tests. This checks consistency, not instructional effectiveness, accreditation or external resource quality.

## Files and downloadable editions

The editable Markdown documents are the curriculum source. `project/` contains the original runnable teaching example, fictional records and tests. No copied textbook files are bundled. A combined print PDF and self-contained reading HTML are generated separately under `generated-artifacts/grade-9/`; the review archive includes both.

For the teaching project alone, use any approved Python 3 installation and the commands in document 07; it has no third-party dependencies. `export.mjs` rebuilds the reading editions using this workspace's existing Markdown/Chromium toolchain and is not needed to teach or run the project.

The assessment document includes adult answer guidance. Distribute learner prompts separately during unaided checks; do not hand out the answer section in advance.

