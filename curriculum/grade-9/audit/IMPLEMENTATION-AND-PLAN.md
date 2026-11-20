# Implementation evidence and bounded completion plan

## Current source snapshot

Read-only upstream HEAD/main check on November 12, 2026 identified **b36daf78c98d9c5184a650da70d09cc41f1f1233** in `agnusdei-ai/bede`. A detached linked worktree in the same Bede Git object database was created at that revision. The original dirty checkout remains untouched. No remote branch was created.

References below are relative to that Bede root. **S** means source inspected; **T** means test definition inspected, not executed; **X** means an explicitly recorded check executed. None means live deployment. Current Grade 8 baseline source evidence was older; this audit rechecks the relevant interfaces on the fresh revision.

| System | Evidence | Gap / safe reuse |
|---|---|---|
| Objectives, source metadata, versions | S: `homeschool-api/services/curriculum/models.py` SourceRecord, Lesson, ContentChunk and LessonVariant; T: `tests/test_curriculum_models.py` | Objective IDs exist; no complete Grade 9 prerequisite/standards graph. Verbatim requires verified PD, not merely `licensed`. Preserve this gate. |
| Rights staging | S: `services/curriculum/rights_gate.py` binds source ID/URL, hash, timezone, campus, verifier evidence and rights status | Research register is not a runtime ingestion manifest. Human verifier assertions are not proof; do not promote these candidates. |
| Independent institutional review | S: `services/curriculum/workflow.py`; DOC: `docs/CURRICULUM_REVIEW_WORKFLOW.md`, `CURRICULUM_ORIGINAL_LESSON_REVIEW.md`; T: workflow synthetic tests located | Authenticated membership, WebAuthn, credential version, independent reviewer grants, encrypted versions and rechecks remain. Local agentic review does not impersonate this service's human authority. |
| Retrieval and citations | S: `services/curriculum/local_hybrid_index.py`, `citation_retriever.py`; DOC: corresponding curriculum documents | Approved campus/private scope and allowed rights filtered before retrieval; licensed material excluded absent a license-scope contract. Exact passages and objective annotations need trustworthy provenance, not a citation-shaped string. No Grade 9 corpus activated. |
| Adaptation | S: `learner_evolution.py` and model variant invariants | Synthetic evidence aggregation/confidence cap is not calibrated placement or disability diagnosis. Preserve parent version, expiry, evidence and independent demonstrations. |
| Planning and coaching | DOC: `docs/PRACTICE_COACH.md`; S: Grade 8 inventory and current curriculum interfaces | Upload/parent-reviewed software practice coaching is not staffed premium coaching. No end-to-end weekly packet, bounded co-plan, delayed-check or human-coach allocation service demonstrated. |
| Access/privacy | DOC: `docs/ACCESSIBILITY_RESEARCH.md`; institutional workflow source | Reading controls are not comprehensive accessibility. Future synthetic tests must cover consent, tenant scope, key retention/deletion, unauthorized grants and provider boundaries. No actual child records inspected. |

Do not weaken authenticated reviewer/rights gates to reconcile production policy. The factory specification must define a separate authorized production identity and version-bound handoff if integrating automated reviews. Licensed content is not public domain under current verbatim restrictions. Bede-owned content remains proprietary; preserve all third-party repository notices.

## Completion stages and acceptance

| Stage | Required outputs and evidence | Exit authority / status now |
|---|---|---|
| 1. Outcomes, sources and year design | Approved outcome/prerequisite crosswalk, selected history/science/language paths, exact licensed assets, reading demand, time/burden budget, alternate access paths | Owner decisions and evidence-backed separate academic review; audit prepared, adoption HOLD |
| 2. Production prerequisites | Proprietary production specification, minimum development-only factory, three Grade 8 lessons through the pipeline, tests and explicit human slice review | Existing implementation milestones; not established complete here. No parallel factory/full-year generation |
| 3. Full lessons and assessments | Weeks 10–36, daily packets, keys, rubrics, worked models, misconception responses, independent/delayed/transfer forms; preserve nine existing weeks | Versioned authoring and independent review; not authored here |
| 4. Content, access and lab qualification | Separate exact-version academic/source checks, accessible device tests, modality ledger, safe alternatives, site supervision/handling/emergency decisions | Routine academic agentic review allowed; local safety/access/rights decisions remain substantive; no invented professional credentials |
| 5. Implementation and synthetic testing | Reuse existing models/rights/workflow; fail-closed flags; tenant/role denial; stale approval/hash mismatch; bounded adaptation; no real records | Factory/interface tests plus real artifact journeys in approved development environment; no service activation here |
| 6. Separately authorized pilot/evaluation | Defined population, lawful consent/data minimization, comparator, rubrics, safety/access support, burden logging, stopping rules | New explicit authorization required before recruitment/data collection; not authorized |
| 7. Completion/release | Exact-version academic, rights, access, safety, operational and evaluation evidence; local credit decisions; release sign-off | Fully authored ≠ reviewed ≠ pilot-evaluated ≠ publication-approved ≠ live-activated. All remain separate |

## Evaluation design proposal, not a pilot

Measure independent learning on new items and delayed retention/transfer, not clicks, time online or completion badges. Preserve lawful accommodations across groups. Adults score against common rubrics, with blinded scoring where feasible and disagreement calibration. Report attrition, adverse/access events, missing evidence, uncertainty and deviations.

To isolate **prepared-material effects**, compare usual materials with reviewed ready-to-teach materials at comparable adult/coaching support. To estimate **incremental Bede effects**, compare the same reviewed materials and comparable coaching with versus without Bede orchestration. Do not change materials, staffing and software simultaneously then attribute the result to software. Feasibility or a small pilot cannot establish prep-school equivalence or generalized efficacy.

Collect baseline readiness, supported/independent performance, proposed 2-/6-week retention, new-source/problem transfer, learner fatigue and parent/educator/coach time by category. Predefine practical burden and safety stopping rules before any future authorization. Use synthetic fixtures for development now; do not create participant records or start recruitment.

## Specific handoff blockers

Yearwide writing strategy cycles, corroborating history sources, full lesson/exam production, actual access checks, secure history-download route, jurisdictional credit/safety decisions and verified net workload remain missing. Existing reviewed Q1 material is valuable evidence, not a substitute for those gates. Grade 10 must not assume Grade 9 mastery from map coverage or code tests.
