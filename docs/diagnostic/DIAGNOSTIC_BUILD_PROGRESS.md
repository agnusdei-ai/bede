# Diagnostic Build — Progress Tracker

**This file is the build loop's mutable state.** Every build-loop iteration (B1–B7, see `DIAGNOSTIC_BUILD_LOOP.md`) reads this to find the next unit and writes to it at B6. It is the single source of truth for build progress.

**Legend:** `[ ]` pending · `[~]` in progress · `[x]` done (real check green) · `[!]` blocked/paused

---

## Phase Status

| Phase | Status | Gate |
|---|---|---|
| 0 — Approval | done | Design doc + runtime loop + build loop signed off |
| 1 — Core package (pure Python) | **in progress** (1/8 units) | — |
| 2 — Persistence | not started | — |
| 3 — Loop integration | not started | — |
| 4 — Parent surface | not started | — |
| 5 — Validation & tuning | not started | — |

**Current next unit:** 1.2 — `services/diagnostic/qmatrix.py`

---

## Phase 1 — Core package (pure Python, no DB, no LLM)

| Unit | Deliverable | Realizes runtime step | Real check | Status |
|---|---|---|---|---|
| 1.1 | `skill_map.py` — K-8 math DAG | S1 (fringe prereqs) | DAG acyclic; prereqs resolve; every skill has a band | `[x]` |
| 1.2 | `qmatrix.py` — probes, `q_row`, `EvidenceObservation` | S5/S6 | every probe maps to ≥1 attribute; unknown id → None | `[ ]` |
| 1.3 | `irt.py` — 1PL/2PL/3PL, Fisher info, θ update | S6 | known P values; Fisher monotonicity; θ converges | `[ ]` |
| 1.4 | `cdm.py` — DINA/DINO/G-DINA posteriors | S6 | slip/guess sanity; posterior moves correctly | `[ ]` |
| 1.5 | `kst.py` — surmise closure, `fringe`, `propagate_prerequisites` | S1/S7 | fringe correct on small map; prereqs enforced | `[ ]` |
| 1.6 | `cat.py` — `select_next_probes`, `should_stop_probing` | S2/S9 | selects highest-uncertainty fringe skill; respects resolved | `[ ]` |
| 1.7 | `mastery.py` — vector, `bayesian_update`, `aggregate_for_parent` | S7 | **acceptance**: synthetic stream converges + respects prereqs | `[ ]` |
| 1.8 | `__init__.py` façade — `process_evidence`, `get_next_probe_hint` (in-memory) | S6–S8 | end-to-end in-memory round trip | `[ ]` |

## Phase 2 — Persistence

| Unit | Deliverable | Realizes | Real check | Status |
|---|---|---|---|---|
| 2.1 | `MasteryProfile` + `DiagnosticEvidenceLog` ORM; config flag | S8 | `create_tables()` picks up; `LargeBinary` encrypted | `[ ]` |
| 2.2 | `process_evidence` load→update→encrypt→store round trip | S8 | round-trip vs test Postgres; decrypt == in-memory | `[ ]` |
| 2.3 | Pydantic schemas in `models/schemas.py` | S6/S9 | validation passes | `[ ]` |

## Phase 3 — Loop integration

| Unit | Deliverable | Realizes | Real check | Status |
|---|---|---|---|---|
| 3.1 | `record_skill_evidence` tool + handler + dispatcher branch | S5 | child SSE byte-identical; demo writes nothing | `[ ]` |
| 3.2 | `_build_subject_prompt` diagnostic injection | S3 | static block cacheable; subject block has `<diagnostic_guidance>` | `[ ]` |
| 3.3 | calibration weighting + widened spread | S2/S9 | banner toggles; weight decays with C.n | `[ ]` |

## Phase 4 — Parent surface

| Unit | Deliverable | Realizes | Real check | Status |
|---|---|---|---|---|
| 4.1 | `routers/diagnostic.py` + `main.py` registration | S9 (read) | behind `require_parent`; ExfiltrationGuard passes; 404 on missing | `[ ]` |
| 4.2 | `MasteryDashboard.tsx` + types + api.ts + route | — | render-only; no download/print; `tsc --noEmit` clean | `[ ]` |

## Phase 5 — Validation & tuning

| Unit | Deliverable | Realizes | Real check | Status |
|---|---|---|---|---|
| 5.1 | end-to-end real math session | S1–S9 | evidence flows; vector moves; child sees nothing | `[ ]` |
| 5.2 | tune slip/guess, calibration N, thresholds | — | converges across multi-session corpus | `[ ]` |

---

## Privacy-Invariant Checklist (carried from runtime loop §6)

Checked at B4 for every data/persistence/prompt unit:

- [ ] Child-invisible — no score/probe/assessment signal reaches the child SSE stream
- [ ] Transcript-free persistence — only derived `(V, θ, C)` (+ optional deltas) persisted, encrypted
- [ ] Cache-safe prompting — per-turn state in subject block only, never static block
- [ ] No new exposure surface — no export/download/print endpoint; `require_parent` + ExfiltrationGuard
- [ ] Demo isolation — `db is None` → loop no-op
- [ ] Subject gating — math only in Phase 1 (extensible later)

---

## Open `[to verify]` items (from design doc)

| Item | Where | Resolved? |
|---|---|---|
| `settings.diagnostic_evidence_log_enabled` flag in `core/config.py` | Unit 2.1 | `[ ]` |
| `AuditEvent.DIAGNOSTIC_VIEW` enum member in `core/audit.py` | Unit 4.1 | `[ ]` |
| Best host page for dashboard link (`PodDashboard` vs `Progress`) | Unit 4.2 | `[ ]` |
| `numpy` already a bede dependency? (decide stdlib-`math`-only if not) | Unit 1.3/1.4 | `[x]` — see Decisions Log 2026-07-12 (unit 1.1) |

---

## Decisions Log

| Date | Unit | Decision | Rationale |
|---|---|---|---|
| 2026-07-12 | — | Folded `SkillMastery` into encrypted vector (no separate table) | Avoid leaking plaintext `skill_id`s (design doc §5.2) |
| 2026-07-12 | — | Evidence-delta log off by default | Strictest reading of "never persist raw evidence" (design doc §5.3) |
| 2026-07-12 | — | Skill map uses `GradeStage` K-2/3-5/6-8 (not timer's K-3 split) | Consistency with `grade_to_stage()` (design doc §2.1) |
| 2026-07-12 | — | Design-doc/runtime-loop artifacts added to repo under `docs/diagnostic/` | They were previously only conversation attachments; the build loop needs a real, version-controlled shared workspace to read/write, not an ephemeral upload |
| 2026-07-12 | — | Appendix A / §5 line-number citations in `ai_service.py`/`core/database.py` are stale | Same-day, unrelated edits (previous-lesson-context + learner-profile-history work, this same repo session) shifted ~60–80 lines. Function names/structure unaffected. Flagged in both design docs; must be re-verified before any Phase 3 unit relies on them — Phase 1/2 do not depend on these citations |
| 2026-07-12 | 1.1 | `numpy>=1.26.0` IS already a bede dependency (`requirements.txt`), pulled in transitively (voice/Resemblyzer), not used by anything in `services/`. Units 1.3/1.4 will still NOT import it. | The build loop's own hard rule (§6 driver prompt) says "NO numpy" unconditionally, independent of whether it happens to already be installed — keeps the diagnostic core's "full IP ownership, no supply-chain risk" intent (design doc §1.3) from silently piggybacking on an unrelated dependency |
| 2026-07-12 | 1.1 | Added Measurement & Data, Geometry, and Statistics & Probability skill breakdowns (not detailed in design doc §2.3's skeleton, which only fleshed out 8 of the 11 §2.2 domains) | Task spec required "at least the major domains" with §2.2's full domain list; skeleton was explicitly labeled representative/extensible, not exhaustive |
| 2026-07-12 | 1.1 (fix) | Detailed code review (8-angle, 10 verified findings) run post-merge on 57ea785, per user request that review now happens before every future merge. 4 findings fixed immediately (see below); 6 acknowledged but explicitly deferred, not silently dropped: (1) `GradeBand` duplicates `GradeStage` with no automated equivalence check — real drift risk over time, though today's runtime comparison works fine (verified directly, corrected a wrong claim from one finder pass); (2) `domain` is a free-form string, not an enum — a typo could create a silent phantom domain; (3) the 42-skill catalog is hand-written Python source rather than a JSON/YAML file like `catalog_service.py`'s established pattern — undercuts this module's own "parent can extend it without touching engine logic" claim and risks an import-time crash on a syntax mistake; (4) `Skill` has no mid-tier "skill" grouping field per the design doc's 3-level domain→skill→sub-skill hierarchy (§4.1) — will need retrofitting before Phase 4's parent dashboard groups skills for display; (5) `PREREQUISITES` duplicates data already in `SKILL_MAP[id].prerequisites`; (6) the `_s()` wrapper and `field(default_factory=tuple)` are minor unnecessary indirection. None of these are fixed in this pass — revisit before Phase 1 sign-off or when a later unit (1.5 kst.py, 4.2 dashboard) actually needs the missing piece. | Scoped the immediate fix to what the user explicitly approved (the 3 prerequisite gaps + `dependents_of()`); the rest need either a real design decision (data-file format, enum migration) or aren't blocking Phase 1's own gate, so recording them here rather than fixing unprompted |
| 2026-07-12 | 1.1 (fix) | Fixed 3 prerequisite-gap findings: `ns.integers` now requires `nbt.long_division` (pulls in the full 3-5 arithmetic chain) in addition to `nbt.subtract_within_100`; `sp.mean_median_mode` now requires `oa.division_facts` in addition to `nbt.standard_multiplication`; `geo.coordinate_plane` now requires `nbt.place_value_tens` in addition to `cc.compare_quantities`. Added `dependents_of()` (design doc §4.1's missing accessor) as a precomputed reverse index, `DEPENDENTS`. Added a regression-guard test (`test_six_eight_band_skills_do_not_skip_the_three_five_band_entirely`) asserting every 6-8 band skill's transitive prerequisite closure includes at least one 3-5/6-8 skill, so this class of gap can't silently recur as more skills are added later. | Code-review findings 1, 2, 3 (correctness) and 4 (spec-deviation) from the 57ea785 review — see PR for this fix |
| 2026-07-12 | — | User authorized proceeding through remaining Phase 1 units (1.2-1.8) autonomously, chaining B1-B7 without a "next"/"go" per unit | Still pausing at the Phase 1 → Phase 2 boundary (the build loop's own explicit phase-gate rule) since that transition introduces real DB persistence — a materially higher-stakes change for a system handling children's data than another pure-Python unit. Will also stop immediately for any B3 verification failure that doesn't resolve in 2 retries, or a genuine design ambiguity the docs don't already resolve. |

---

## Completed-Unit Audit (filled as units merge)

_Format per row: `unit-id · branch · PR link · check output (1 line) · verified anchors`_

**1.1** · branch `diagnostic/1.1` · PR: https://github.com/agnusdei-ai/bede/pull/31 (squash-merged to main)

Check output (`pytest tests/diagnostic/test_skill_map.py -v`):
```
tests/diagnostic/test_skill_map.py::test_prerequisite_graph_is_acyclic PASSED
tests/diagnostic/test_skill_map.py::test_no_dangling_prerequisites PASSED
tests/diagnostic/test_skill_map.py::test_every_skill_has_a_band_and_domain PASSED
tests/diagnostic/test_skill_map.py::test_get_skill_returns_none_for_unknown_id PASSED
tests/diagnostic/test_skill_map.py::test_get_skill_returns_the_skill_for_known_id PASSED
tests/diagnostic/test_skill_map.py::test_skills_in_band_partitions_all_skills_and_is_non_empty_per_band PASSED
tests/diagnostic/test_skill_map.py::test_skills_in_domain_covers_every_declared_domain PASSED
tests/diagnostic/test_skill_map.py::test_all_skill_ids_matches_skill_map_keys PASSED
======================= 8 passed in 0.03s =======================
```

Also confirmed via `pytest --collect-only -q` on the full `tests/` directory
that this unit introduces no collection regressions — the only 3 errors
present (`test_demo_personalization.py`, `test_document_extraction.py`,
`test_extract_narration_router.py`) are pre-existing sandbox dependency
gaps (`webauthn`, `pypdf` not installed in this environment), unrelated to
`services.diagnostic`.

Deliverable: 42 skills across all 11 CCSS-aligned domains from design doc
§2.2 (Counting & Cardinality, Number & Operations in Base Ten, Operations
& Algebraic Thinking, Number & Operations — Fractions, Measurement &
Data, Geometry, Ratios & Proportional Relationships, The Number System,
Expressions & Equations, Statistics & Probability, Functions), `GradeBand`
enum matching `GradeStage` exactly, `Skill` frozen dataclass, and the 6
accessor functions the unit spec required.

Verified anchors:
- `GradeStage` values confirmed at `models/schemas.py:7-10` (`foundations="K-2"`, `core_mastery="3-5"`, `independent="6-8"`) — `GradeBand`'s string values mirror these exactly.
- `numpy>=1.26.0` confirmed present in `requirements.txt` (not imported by this unit regardless — see Decisions Log).
- No existing `homeschool-api/tests/__init__.py` at the top level (flat test-file convention); `tests/diagnostic/__init__.py` added per the unit spec's explicit fallback instruction.

**1.1 (fix)** · branch `diagnostic/1.1-fixes` · PR: https://github.com/agnusdei-ai/bede/pull/32 (squash-merged to main)

Code review of `57ea785` (8-angle, 10 verified findings — see decisions log) run post-merge; user approved fixing the 3 correctness findings + the `dependents_of()` spec-deviation now, before Unit 1.2. Check output (`pytest tests/diagnostic/test_skill_map.py -v`):
```
tests/diagnostic/test_skill_map.py::test_prerequisite_graph_is_acyclic PASSED
tests/diagnostic/test_skill_map.py::test_no_dangling_prerequisites PASSED
tests/diagnostic/test_skill_map.py::test_every_skill_has_a_band_and_domain PASSED
tests/diagnostic/test_skill_map.py::test_get_skill_returns_none_for_unknown_id PASSED
tests/diagnostic/test_skill_map.py::test_get_skill_returns_the_skill_for_known_id PASSED
tests/diagnostic/test_skill_map.py::test_skills_in_band_partitions_all_skills_and_is_non_empty_per_band PASSED
tests/diagnostic/test_skill_map.py::test_skills_in_domain_covers_every_declared_domain PASSED
tests/diagnostic/test_skill_map.py::test_all_skill_ids_matches_skill_map_keys PASSED
tests/diagnostic/test_skill_map.py::test_dependents_of_is_the_inverse_of_prerequisites_of PASSED
tests/diagnostic/test_skill_map.py::test_dependents_of_returns_empty_list_for_unknown_id PASSED
tests/diagnostic/test_skill_map.py::test_six_eight_band_skills_do_not_skip_the_three_five_band_entirely PASSED
======================= 11 passed in 0.04s =======================
```

Verified anchor: re-ran the full acyclicity check after adding the new prerequisite edges (`nbt.long_division` → `ns.integers`, `oa.division_facts` → `sp.mean_median_mode`, `nbt.place_value_tens` → `geo.coordinate_plane`) — no cycle introduced, confirmed by `test_prerequisite_graph_is_acyclic` staying green.
