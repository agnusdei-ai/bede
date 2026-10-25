# Curriculum PR 7 — prerequisite and observed-support ranking

This increment is **offline, opt-in and not connected to learner delivery**.
`CURRICULUM_ENGINE_ENABLED` remains disabled by default. PR 7 adds only
`services/curriculum/policy_ranker.py` and synthetic tests.

## Ranking contract

- Input is PR 6's already-approved, policy-filtered `RankedCitation` set,
  a human-reviewed `PolicyContext` per citation, a learner-scoped
  `LearnerEvolutionProfile`, and bounded `ScopedObservation` records.
- A future authenticated service must derive the campus, learner and
  authorized objective from **current** teacher/parent roster grants and
  verify every review reference and evidence-to-learner binding. These
  pure Python objects are not credentials; their constructors do not
  establish authorization.
- `P` is prerequisite readiness estimated conservatively from existing
  skill mastery and confidence. Missing evidence is **neutral** (0.5);
  no prerequisites means no prerequisite constraint (1.0).
- `L` is fit to the **observed, temporary level of instructional support**,
  using evidence-backed independent/hinted/reexplained responses. No
  response data means neutral (0.5). It is not a fixed learning-style
  classification or an ability label.
- The weights are explicitly versioned, finite and sum to 1.0. Every
  returned citation exposes RRF/R/A/O/P/L/E component scores and opaque
  evidence references for inspection; there is no telemetry or raw
  learner-content logging. Effectiveness `E` is **fixed at zero**.
- No high-stakes placement, automatic curriculum approval, profile mutation,
  tutor action, external model call, network, database access, or learner
  data import is possible through this module.

## Qualification

Focused synthetic tests exercise P and L **ablation ordering**, profile
campus/learner mismatch, unbound/replayed evidence, missing/duplicate
review metadata, unsupported weights, disabled flag, and no network use.

## Still required before any learner-facing integration

Independent human review of this PR **and retrospective documented review
of merged #712/#714/#717**, which GitHub's PR review API currently shows
without submitted reviews despite epic #685's human-review requirement.
Also required: authenticated campus/roster binding, live revocation checks,
verified rights/review provenance, encrypted profile retention/deletion,
a held-out evaluation set, privacy checks, and an explicit activation
decision. The separate Mac Pilot Entry and real learner-data holds remain.
