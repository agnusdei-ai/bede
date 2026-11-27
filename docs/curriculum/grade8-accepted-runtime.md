# Accepted Grade 8 year: student runtime

This connects the owner's accepted authored year to the existing Bede tutor,
demo Parent Setup, and enrolled Parent Setup. It does **not** declare a learner
pilot, institutional corpus promotion, course credit, or demonstrated Grade 9
readiness.

## Published content and privacy

- 592 current student-facing lesson/check records across 20 strands.
- 36 adult-selected weeks and two mathematics pathways: foundations and Algebra I.
- Each weekly plan selects 14 instructional modules. Quarter checks replace their
  reviewed independent/transfer slots rather than adding an extra test day.
- History includes its geographic source comparison, modern reference coordinates,
  an original accessible atlas, and dated historical-map references.
- The original clothed visual source and its text-access guide are available.
- Original Bede curriculum retains its proprietary notice. Referenced works retain
  their own attribution, edition, rights, and access qualifications; a reference
  is not an ingestion license or permission to retrieve externally.

The source manifest pins the accepted review digest
`c7d7502eb6fb041db87e5d394de2bb63d234c8a15c6f655fb1d5b20914876e9d`
and SHA-256 digests of each published strand and visual resource. The runtime
fails explicitly if the installed projection is absent, changed, or incomplete.

The exporter uses an explicit public-field allowlist. It omits worked teacher
models, assessment keys/rubrics, rescue records, private placement plans, original
authoring bundles, and private Git history. The 20 readable JSON strand files
are the application's original instructional source, not ZIP/build artifacts.
The only public HTML files are the two already accepted student resources.
No teacher-resource download endpoint is introduced.

## Activation is separate

`BEDE_GRADE8_CURRICULUM_ENABLED` defaults to `true` for the accepted original
student course in the shared API, Docker Compose, Render Blueprint, and both
installers. This makes the same course available in the demo and installed
runtime; it does not automatically select it for a learner. The separate
`CURRICULUM_ENGINE_ENABLED` institutional engine remains off by default, with
its existing rights, review, and promotion controls unchanged.

An authorized operator can set `BEDE_GRADE8_CURRICULUM_ENABLED=false` to disable
the course. Both installers preserve an explicit value during reconfiguration.
Stored choices remain readable and removable while the runtime is disabled;
a teaching request returns HTTP 409 before streaming or contacting a model.
Publishing source or setting a client-side selection cannot bypass this gate.

For an existing Render service, deploy the updated API and, if an older explicit
`false` is present, intentionally change that non-secret setting to `true` and
redeploy. A Blueprint sync applies the committed `true`; an existing service not
managed by this Blueprint requires its normal environment controls. Verify
`GET /catalog/grade8/release?week=1&pathway=foundations` returns
`runtime_enabled: true` and release `bede-grade8-2026-accepted` after rollout;
repeat for `pathway=algebra` and week 36. Check the adult course controls and
saved selection before claiming end-to-end teaching verification.

Availability is not pilot evaluation, institutional promotion, installer
qualification, or real learner-data authorization. Swift/App Store packaging
must use this same API contract when implemented; no native Swift delivery
is established by this configuration change.

For a Grade 8 profile, Parent Setup shows the release status and source links.
After operator activation, the adult can choose the week, mathematics pathway,
subjects, and an optional specific lesson. The choice is saved with the existing
profile or demo-code configuration. Changing week/pathway clears a stale lesson;
removing its subject clears that specific choice. Turning the year off, or
changing to another grade, removes its course-only subjects from the draft.
Temporary metadata failures preserve saved choices.
For enrolled teaching, the server reloads the authorized adult plan while this
runtime is enabled; a posted week cannot replace it, and omitting the selection
cannot remove it. Educator and demo requests retain their existing server-owned
configuration resolution.

Spanish, computing/research, and movement/health literacy are explicit opt-ins
for this course, not additions to every family's default workload. Other
grades, classical-language electives, and optional faith formation retain their
existing routes. English and general Spanish setup labels are provided.

## Tutor behavior

The real subject-prompt path receives one selected original lesson, its objective
and prerequisite references, assessments, access/safety boundaries, and the
relevant weekly pacing/quarter context. It does not load an entire year into a
single prompt. Existing session language and parent adjustments remain in force.
The adapter itself reads local files only.

Bede guides active work with Socratic questions and hints. It is not supplied
with the teacher answer key. A scheduled week or prerequisite reference is not
evidence of ability. Listening, actual movement/practical performance, and
written reasoning stay distinct; unavailable constructs remain unassessed.
Delayed checks require confirmation of elapsed time. The Grade 9 handoff must
report actual dated evidence and supports for adult interpretation, not an
automatic placement or completion decision.

## Routes and verification

- `GET /catalog/grade8/release?week=1&pathway=foundations`
- `GET /catalog/grade8/atlas`
- `GET /catalog/grade8/visual-source`

These routes contain only published original student content, not personal
records. Existing authenticated book-catalog endpoints are unchanged.

Focused regression tests cover all 72 week/pathway combinations, the real
three-subject route, scope/version validation, source integrity, private-field
noninterference, quarter replacements, actual demo save/reload, disabled teaching,
and both controlled setup components. The legacy catalog's original coverage
is retained; the new course-only subjects have their own stricter explicit-course
coverage rather than being treated as legacy book lists for every grade.

To reproduce a new projection, use the retained private authoring worktree and
its exact accepted artifact receipt:

```sh
python -B scripts/export_grade8_student_release.py \
  --source-worktree /path/to/retained-private-authoring \
  --acceptance /path/to/exact-owner-acceptance.json \
  --output homeschool-api/data/curriculum/grade8-student.json
```

This is an operator build step, never an API. CI and installations use the
checked-in student projection and require no access to private authoring files.
The exporter first verifies the accepted artifact hashes and immutable factory
records. A changed authored year requires a new review/acceptance, not rewriting
the historical receipt.
