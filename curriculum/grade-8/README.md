# Bede Grade 8-first — baseline and source-rights review

**Phase 0 · Review only · Review assembled November 3, 2026**

**Public-review candidate prepared November 13, 2026:** the historical baseline was replayed onto main `b36daf78c98d9c5184a650da70d09cc41f1f1233`. Unapproved coaching availability/allocation terms were omitted from decision U04; the original local baseline remains preserved. Earlier no-push statements below describe the original delivery. The owner subsequently authorized opening the scoped curriculum PR and deployment triggered by that operation; deployment-isolation evidence is no longer a prerequisite for this push. Exact-head CI, genuine human PR review and baseline acceptance remain separate pending gates. The historical source inventory has not been re-audited against current runtime behavior.

**Bede-owned research, curriculum and production tooling are proprietary.** No open license is granted by this package. Third-party licenses and notices remain separate. Researching a candidate grants no authority to ingest it.

## Executive decision

Grade 8 is first. Bede is a paid tutoring operating system: standard family delivery is parent-directed and Bede-orchestrated; premium may add human coaching. Bede is not being recast as a downloadable curriculum, Q&A product or staffed online school.

The existing repository contains useful curriculum models, rights gates, independent human-review services and scoped retrieval primitives. **Reuse them.** They are not evidence of a complete reviewed Grade 8 year, a running production curriculum factory, authentic review approvals, or a qualified live learner deployment.

The earlier Grade 9 package remains **provisional reference**. Finish and review Grade 8 end to end before separately approving Grade 9, then Grades 10, 11 and 12 in order. No full-year authoring may bypass the forthcoming proprietary production specification, development-only factory and human-reviewed three-lesson Grade 8 verification slice.

**Canonical repository integration:** see [Integration and current status](INTEGRATION.md). This package preserves the earlier baseline's historical source snapshot; it does not claim that snapshot is current main. Seven inspected source files have since changed. No Grade 9 draft, unchanged Year 8 catalog, external source texts or generated exports are included in this local commit.

## Read in this order

1. [Decisions and assumptions](01-decisions.md).
2. [Source capability inventory](02-capabilities.md).
3. [Gaps, gates and sequential roadmap](03-gates-and-risks.md).
4. [Rights policy, register guide and ingestion distinctions](04-rights-guide.md).
5. [Primary-source education evidence register](05-research-evidence.md).
6. [Seminar/studio and educator-burden evaluation](06-operating-model.md).
7. [Verification and handoff](07-verification.md).
8. [Initial source register](source-register.json): 12 bounded candidates, with per-use rights judgments.
9. [Blank entry template](source-register-template.json): required fields for future research.
10. [Repository integration](INTEGRATION.md) and `python3 -B curriculum/grade-8/validate.py` for portable, standard-library document/data checks.

## Gate 0 disposition

**Baseline research ready for owner review; baseline acceptance not recorded.** Source choices, Grade 8 history period/language path, outcomes, sequence, operating costs, implementation, participants and pilots are **not approved** by this document.

Immediate next decision: accept/correct this baseline and resolve the blocking scope choices listed in document 03. Nonblocking coaching-hour allocation and price unknowns remain documented, not repeatedly asked.

## What this package does not do

No year or lessons authored; no corpus downloaded/activated; no new application features; no real learner records; no model training; no public-site edits; no branch, PR, remote fetch, push, merge, deployment, purchase, billing or pilot action. Downloadable copies are review documents, not a curriculum offer or service activation.

The public website remains K–8. The current institutional pilot remains teacher-only/sample-only unless separately qualified and authorized. The paid-service direction is an owner decision, not proof that every described capability is already available.

## Evidence limits

The original baseline's checkout was historical. Integration verified current GitHub main read-only and used a separate local worktree, preserving unrelated dirty work; deployed behavior remains **unverified**. The baseline's sample checks demonstrate selected historical source contracts only. They are not current-main runtime evidence. Upstream pytest/database tests were not executed. No learner, legal, accessibility or efficacy certification follows.
