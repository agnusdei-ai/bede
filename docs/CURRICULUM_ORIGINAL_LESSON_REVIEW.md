# Curriculum PR 8 — original lessons and revision qualification

The existing opt-in `stage_lesson` and `review_staged_lesson` workflow
already supports independently reviewed original lessons. This increment
adds synthetic regression coverage rather than duplicating the staging or
review implementation.

## Required behavior

- A campus-authorized, passkey-verified educator submits an original
  non-verbatim lesson with an explicit `RightsStatus.original` source,
  provenance reference, rights-verifier assertion, and content digest.
- Staging creates a new immutable version with encrypted content, but
  **never** makes the lesson approved or learner-visible.
- A separate, currently authorized human reviewer must approve it.
  The review is recorded and the approved copy receives a **new version**.
- An author revision must carry its own source/provenance evidence and
  enters staging as another new version. Prior approval cannot approve
  the revised text. The new version requires another independent review.
- An `original` rights claim never permits verbatim source text. Such
  submissions are denied before any write.

The tests use synthetic educator identities, synthetic campuses, SQLite,
and the existing encrypted curriculum storage. They do not prove legal
authorship, independent licensing verification, a production school
deployment, or the identity of a real reviewer.

## Release boundaries

`CURRICULUM_ENGINE_ENABLED` remains off by default. There is no
learner-facing router, autonomous promotion, network access, or change to
existing tables in this PR. This PR is a **draft** requiring independent
human source review, exact-head applicable CI, and the PR 8 exit-gate
decision under epic #685. Retrospective review reconciliation of merged
#712, #714, and #717 remains outstanding. Mac Pilot Entry, owner/school
Pilot GO, and real learner-data authorization remain on HOLD.
