# Bede diagnostic evidence and invention disclosure — release gate

Status: **engineering evidence inventory; not a claim of validated clinical/educational accuracy or patent filing**. Owner review required. Prepared 2026-10-24.

## What exists, and what it proves
- The diagnostic progress tracker `docs/diagnostic/DIAGNOSTIC_BUILD_PROGRESS.md` records K–8 math prerequisite graph, Q-matrix, item-response functions (1PL/2PL/3PL), DINA/DINO/G-DINA posterior updates, knowledge-space closure, adaptive probe selection, Bayesian mastery update, encrypted persistence, and parent-facing mastery summary. These are **implementation descriptions and historical test claims**, not independently reproduced results on this candidate.
- Historical synthetic convergence experiments and slip/guess tuning are documented there. Their reported false-secure rates are conditional on simulated response-model assumptions; they do **not** measure accuracy on representative real learners.
- Phase 5.1 live end-to-end evidence was recorded as **blocked**. Do not silently mark it passed.
- `docs/ASSESSMENT_INTEROPERABILITY.md` documents manually entered external DIBELS scores; Bede does not administer, norm, score, or validate DIBELS. External scores are not mastery posterior inputs.

## Evidence ledger (populate with immutable links, commit SHA and sample definition)
| Gate | Acceptance evidence | Status |
|---|---|---|
| Algorithm correctness | Unit/property tests for IRT, CDM, CAT, prerequisites; edge cases and deterministic seeds | Historical documentation only; exact-head run NOT VERIFIED |
| Scoring reliability | Repeatability, assessor agreement, missing-data behavior, uncertainty intervals | NOT VERIFIED |
| Construct/criterion validity | Pre-registered objectives, representative grade/subject samples, independent educator-reviewed reference standard, blind adjudication | NOT VERIFIED |
| Calibration | Reliability diagrams/Brier score, error by grade and prior mastery, coverage, uncertainty, confidence intervals | NOT VERIFIED |
| Safety | False-secure and false-gap rates, abstention on sparse/conflicting evidence, subgroup checks with privacy safeguards | NOT VERIFIED |
| Instructional usefulness | Teacher-reviewed recommendation relevance, source citations, edit/reject outcomes, delayed retention and prospective comparison | NOT VERIFIED |
| Data boundaries | Synthetic campus/learner separation, revocation, deletion and audit; real-data permission separate | NOT VERIFIED ON CURRENT CANDIDATE |
| Integrated release | Exact-head security audits, CI, synthetic G1/G2/G3, owner and school administrator authorization | NOT VERIFIED |

Never describe Bede as 100% accurate, fully validated, diagnostically certified, or able to infer a learner's fixed style or medical/psychological diagnosis. Report denominators, uncertainty, reference standard, and limitations alongside every accuracy statistic. Distinguish correctness of code from psychometric validity and instructional outcomes. A teacher sees **observed evidence, uncertainty, source and approval controls**, not an unsupported precision claim.

## Minimum defensible validation protocol
1. Freeze candidate commit, assessment version, scoring thresholds, target population, preregistered endpoints, acceptance limits, sample-size rationale, and analysis plan **before** testing.
2. Build a rights-cleared, representative de-identified/synthetic test corpus with grade, objective, task, evidence source, and independent human adjudication. Synthetic tests qualify mechanics; real-world accuracy needs separate authorized data collection and qualified educational/psychometric review.
3. Calculate confusion matrix, sensitivity/specificity, false-secure rate, false-gap rate, abstention and coverage, calibration, confidence intervals, missing-data and subgroup performance; evaluate delayed retention separately. Do not invent thresholds or scores.
4. Test adverse cases: contradictory observations, guessing, assistance/hints, low sample counts, grade mismatches, cross-campus attempts, and stale curriculum versions. Fail closed and escalate to educator review.
5. Publish a versioned model card/educator evidence sheet with scope, provenance, metrics, limitations, change log, and explicit human approve/edit/reject requirement.
6. Use existing affected-code QA and one consolidated release regression; link actual CI run IDs. No new CI framework or automatic high-stakes placement.

## Confidential invention disclosure — attorney review before public release
**Working invention title:** Privacy-scoped evidence-to-instruction diagnostic orchestration with educator-controlled adaptive curricula.

**Potential technical combination to investigate, not a patentability conclusion:** prerequisite-closed skill graph; uncertainty-aware adaptive probe selection; encrypted learner-scoped posterior evidence ledger; source- and rights-gated retrieval; temporally separated mastery/retention updates; educator authorization of a bounded instructional follow-up; auditable campus-scoped revocation.

**Inventorship:** list only natural persons who conceived claimed subject matter, with dated contributions; verify ownership and assignments. **Prior art:** conduct patent and non-patent literature search (IRT, CAT, cognitive diagnosis, knowledge-space theory, adaptive tutoring, human-in-the-loop RAG); distinguish implementation novelty from known methods. **Enablement:** prepare architecture, algorithms, state transitions, diagrams, sample synthetic traces, alternative embodiments, threat boundaries, and dated development history. **Claims:** have qualified patent counsel assess novelty, non-obviousness, subject-matter eligibility, enablement and claim scope; software/educational-method claims face particular scrutiny.

**Filing checklist:** determine applicant/assignee, inventors, confidentiality/public-disclosure dates, priority strategy, specification and drawings, provisional versus nonprovisional route, required USPTO forms and fees, counsel review, and secure submission with official receipt/application number. **Do not mark “patent pending” until an application is actually filed.** A provisional application is not an issued patent and has follow-on deadlines; confirm requirements with USPTO/counsel. Keep sensitive invention details in restricted counsel-controlled materials rather than adding secrets, student records or unfiled claim specifics to a public repository.

## Narrow release order
1. Review diagnostic evidence ledger; fix any demonstrated algorithm/validity defect using targeted tests; do not block synthetic pilot on future real-world learning outcomes.
2. Verify exact-head security/CI and document any unresolved security exception with explicit risk owner.
3. Reuse unchanged G1/G2/G3 evidence, run only changed-path synthetic checks plus one integrated candidate regression; record PASS/FAIL/NOT RUN.
4. Resume #685: rights/provenance → reviewer-only staging/promotion → local tenant-filtered hybrid retrieval → cited ranking → delayed retention and evaluation. Feature flag remains off until qualified.
5. Joint owner/school administrator Pilot Entry GO after mandatory gates; real educator validation proceeds during the supervised four-week pilot under separate data authorization.
