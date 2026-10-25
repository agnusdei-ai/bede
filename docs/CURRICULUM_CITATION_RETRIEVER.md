# Curriculum PR 6 — objective-gated citation retrieval (stacked draft)

**Dependency:** PR #714 (offline campus-filtered hybrid search). This PR is
stacked on that unmerged branch and must be rebased/retargeted after #714's
required human review and merge. It is not independently deployable.

## Offline flow

1. A future authenticated service resolves campus/educator/roster grants and
   calls PR 5's `search_chunks()`, which excludes cross-campus, staged,
   unapproved, unlicensed and unauthorized private content before scoring.
2. That service loads **independently human-reviewed** annotations for the
   exact chunk ID/version, including source reliability, classical alignment,
   authorized objective IDs and an opaque review reference. Missing or
   duplicate annotations block retrieval. Ratings are not invented by this
   module, and a `review:` reference is not proof of reviewer identity.
3. `rank_citations()` requires an independently authorized educator
   objective, filters out nonmatching objectives, fuses BM25 and local-vector
   ranks with reciprocal-rank fusion (k=60), then computes an inspectable
   R/A/O policy contribution. Prerequisite P and learner-interest L are not
   used; effectiveness E is **always 0** until separate evaluation and human
   authorization. No learning-style labels, diagnostic conclusions, or
   automated placement decisions.
4. `project_exact_passages()` emits only literal substrings of ranked,
   previously filtered excerpts with source ID, edition, locator and review
   reference. Uncited, altered and fabricated quotes are dropped. This is
   **exact-quote grounding**, not verification of arbitrary generated
   paraphrases or factual correctness.

## Safety and qualification limits

- `CURRICULUM_ENGINE_ENABLED` remains **off by default**. There is no API
  route, tutor integration, model invocation, data migration, persistence,
  logging of learner data, or external network access.
- Pure function inputs are **not authentication**. The future adapter must
  fetch authenticated campus-scoped approvals and annotations from the
  reviewed DB workflow (PR #712) and must revalidate revocation, provenance,
  rights and source-to-review bindings. Forged in-memory hits or annotations
  must never be accepted from an untrusted client.
- Local vectors in PR #714 are signed feature hashes, not semantic
  embeddings. Citation correctness on the small synthetic test set is not
  a production-quality retrieval/lesson evaluation.
- Tests cover deterministic rank fusion, score terms, authorized-objective
  filtering, missing/duplicate annotations, quote exactness, cross-campus
  exclusion inherited from PR #714, feature flag, and no network.
- Exit gate: exact-head CI, independent human review under epic #685,
  then integration with trusted approval/revocation and a broader citation
  correctness evaluation. Do not auto-merge, publish content, enable the
  engine, or change Mac Pilot GO status.
