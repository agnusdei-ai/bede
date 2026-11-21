# Ordered curriculum delivery — foundation

This is the first unpublished Grade 9 content increment following the existing
production specification and factory on main. It preserves existing authoring,
source decisions, audit evidence and known gaps rather than replacing them.

## Scope

- Grade 9 full-year map, teaching materials for weeks 1–9, assessment toolkit,
  biology investigation guidance and executable computing studio.
- Source edition/rights registers and prior reviews, with their original
  scope and limitations retained.
- No application routes, retrieval activation, public asset copy or deployment
  configuration changes.

## Sequence

Merge this foundation before the Week 10 teaching increment. Remaining Grade 9
content precedes Grades 10, 11 and 12 in the curriculum completion sequence.
Integration and verified live delivery in both demo and enrolled Bede are
required deliverables, not satisfied by these source files or by merging a PR.
Adult keys must never become learner-facing retrieval or public assets.

## Verification

Run `python3 curriculum/grade-9/validate.py` and
`python3 -m unittest discover -s curriculum/grade-9 -p test_review_gate.py`.
The validator also runs the studio tests. These are structural and code checks;
they do not certify the full year, pedagogy, source permissions or outcomes.

Historical audit statements about local-only delivery describe earlier scope.
The owner's subsequent direction authorizes ordered PR publication and
eventual verified delivery in demo and enrolled Bede. Rights, safety,
review and role-based access controls are not waived.
