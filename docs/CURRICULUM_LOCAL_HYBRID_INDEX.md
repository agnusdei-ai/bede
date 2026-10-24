# Local hybrid curriculum retrieval — isolated PR 5 primitive

This is a **standalone, opt-in domain primitive**, not a production index, API,
learner tutor, or a claim that epic #685 PR 4's corpus has been approved.
`CURRICULUM_ENGINE_ENABLED` remains false by default. There is no startup
integration, network call, vector-model download, learner-profile access,
storage migration, or external model request.

## Algorithm and isolation boundary

The caller supplies a **server-verified** `SearchScope(campus_id,
educator_id)` and approved `IndexedChunk` records. The function has no
authentication capability itself; a future service boundary must check live
campus/educator/roster grants and revocation before supplying that scope.
It **filters before tokenization, vectorization or scoring**:

- Exact campus ID match, approved item status, valid approving human
  `ReviewRecord` bound to the item ID/version.
- Rights status restricted to `original`, `public_domain_verified`, or
  `teacher_private`; licensed material is excluded until an independently
  qualified license-scope contract is implemented. A rights-status assertion
  alone does not constitute legal rights verification.
- Teacher-private content requires a matching verified owner educator ID.
  Private-rights content is never campus-visible.
- Duplicate approved versions, oversized corpus/query and invalid scope
  fail closed. No learner identifiers are required or logged.

For the remaining authorized text, deterministic BM25 is combined with
128-dimensional signed feature-hashing cosine similarity. **These are
lexical hashed vectors, not learned semantic embeddings**. Hash collisions
cannot create results without BM25 lexical evidence. Score components are
inspectable and ordering is deterministic. Each hit carries its source ID,
edition, locator and excerpt; this is retrieval provenance, **not yet a
citation-grounded lesson-generation guarantee**.

## Qualification and limitations

Synthetic tests cover cross-campus and unapproved prefiltering before
tokenization, teacher-private ownership, excluded licensed rights, disabled
flag, no-network execution, deterministic citation metadata, duplicate
versions and malformed input. The primitive does not cache or persist data.
No inference about a learner's diagnostic status, learning style or
placement is made. Ranking by prerequisite, educator-authorized objective,
evidence-backed retention or learner preference is deliberately deferred.

This PR is **draft for human review under #685**. It is independent of the
unmerged staging/promotion PR #712 and does not seed or approve curriculum.
Before any live route is introduced, separately qualify source/rights
integrity, administrator authorization, per-campus and teacher-private
visibility, deletion/retention, true local vector embeddings if desired,
retrieval quality, and source-grounded lesson construction. Pilot GO and
real learner-data authorization are separate and remain HOLD.
