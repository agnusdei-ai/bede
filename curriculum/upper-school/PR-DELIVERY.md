# Ordered curriculum delivery — Week 10 academic instruction

Depends on the Grade 9 foundation PR; review this branch against that branch,
not against main, until the foundation is merged. Retarget to main only after
the dependency is present there.

## Included

Five-session instruction for each Grade 9 Week 10 academic subject:
literature, history, algebra, biology, Latin and computing. Humanities and
mathematics adult keys are separate files. Biology and computing retain
clearly marked adult-only sections: these combined source files must not be
served directly to learners or ingested wholesale into learner retrieval.

The source-intake tooling acquires allowlisted review copies with edition
checks and attribution. No downloaded textbooks or generated HTML are
included in this PR. No network acquisition runs as part of verification.
Historical intake reports describe workspace evidence, not assets shipped
in Git or guarantees that sources are currently downloadable.

## Verification

`python3 -m unittest discover -s curriculum/upper-school -p 'test_*.py'`

These checks cover intake behavior, mathematical answers, executable Boolean
examples, humanities agendas and selected grammatical keys. They are not
independent academic approval or evidence of learning outcomes.

## Not completed by this increment

Remaining Grade 9 weeks and weekly practical/arts/PE strands, full-year
Grades 10–12 instruction, separate subject review, authorized source
promotion, tutor integration and verified live availability. No website,
runtime, deployment or enrolled-user storage code changes here.

## Next sequence

Complete the remaining Grade 9 teaching content, continue Grades 10–12 in
order, and deliver verified runtime integration and release pieces. Keep each
PR's content completion, academic review, integration and live-release status
distinct. Do not merge this PR ahead of its foundation dependency.
