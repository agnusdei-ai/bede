# Owner-directed agentic curriculum review

Effective 2026-11-11, the owner replaced mandatory human subject-review gates for curriculum production with evidence-backed agentic review. Missing human reviewers are no longer a routine production blocker. Historical human-review records and decisions remain historical; do not rewrite them as automated approvals.

## Required evidence

- Separate authoring and reviewing runs. Review the exact materials, underlying lawfully usable sources, assessments and supporting evidence, not merely the author's summary.
- Record reviewer agent identifier, agent/model version if exposed (otherwise explicitly unavailable), date, authoring-run identifier, curriculum file hashes, scope, methods, findings, evidence, unresolved disagreements and approval conditions. Never invent model identity or professional credentials.
- Humanities checks historical accuracy, source support, translation fidelity, interpretation, reading demand and assessment alignment.
- Algebra independently solves problems and checks prerequisites, explanations and keys; use executable checks where helpful.
- Latin checks morphology, grammar, translation, acceptable alternatives and progression.
- Biology safety examines each procedure, hazards, equipment, supervision, handling, disposal and safer alternatives. Exclude or replace unresolved hazardous activities.
- Computing runs examples/tests and checks security, privacy, dependencies and objective alignment.
- Statuses: `agent-reviewed`, `changes required`, `blocked by specific defect`. An agent-reviewed status applies only to its recorded scope. Never use “human-approved,” “expert-certified,” or “pilot-validated” for automated work.
- Repair failures and rerun affected checks. Changed source hashes invalidate the affected review; substantive revisions require new review evidence. Reviewers cannot edit or weaken acceptance tests to secure a pass. Record disagreements instead of silently choosing the favorable report.

## Independent gates remain

Commercial rights require documented ownership, an applicable license or verified public-domain evidence for the actual edition, territory and use. Agent review cannot grant permission. Exclude uncleared material from distribution and AI ingestion; provisional references are not cleared resources.

Automated review does not establish laboratory certification, accessibility for every learner or demonstrated learning outcomes. Adult teaching, site supervision, consequential educational decisions, and institution-specific approvals remain separate.

No remote write, publication, purchase, enrollment, pilot, corpus activation or student-data use is authorized by this policy. Grade 8-first sequencing is unchanged.

## Implementation boundary

`grade-9/review_gate.py` checks development-only evidence records and current source hashes. It never promotes a database lesson, enables a service, or authorizes delivery. Passing it means evidence structure and freshness passed, not that rights or educational effectiveness are established.

The linked upstream `docs/CURRICULUM_REVIEW_WORKFLOW.md` describes a separate campus-scoped authenticated staging service. Its educator grants, passkeys, encrypted history and institutional deployment controls are **not** a curriculum-production subject-review requirement and are not bypassed here. This local production policy is not permission to impersonate a campus educator. Integrating automated reviewers into that service requires a distinct service identity/authorization design; this task does not alter that institutional system.

Run `python3 -B curriculum/grade-9/review_gate.py` to report current review evidence. A nonzero result means explicit missing/stale/blocked evidence, not a reason to revert to mandatory human appointments.
