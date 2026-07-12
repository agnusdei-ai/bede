# Diagnostic Build — Progress Tracker

**This file is the build loop's mutable state.** Every build-loop iteration (B1–B7, see `DIAGNOSTIC_BUILD_LOOP.md`) reads this to find the next unit and writes to it at B6. It is the single source of truth for build progress.

**Legend:** `[ ]` pending · `[~]` in progress · `[x]` done (real check green) · `[!]` blocked/paused

---

## Phase Status

| Phase | Status | Gate |
|---|---|---|
| 0 — Approval | done | Design doc + runtime loop + build loop signed off |
| 1 — Core package (pure Python) | **not started** | awaiting "go" |
| 2 — Persistence | not started | — |
| 3 — Loop integration | not started | — |
| 4 — Parent surface | not started | — |
| 5 — Validation & tuning | not started | — |

**Current next unit:** 1.1 — `services/diagnostic/skill_map.py`

---

## Phase 1 — Core package (pure Python, no DB, no LLM)

| Unit | Deliverable | Realizes runtime step | Real check | Status |
|---|---|---|---|---|
| 1.1 | `skill_map.py` — K-8 math DAG | S1 (fringe prereqs) | DAG acyclic; prereqs resolve; every skill has a band | `[ ]` |
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
| `numpy` already a bede dependency? (decide stdlib-`math`-only if not) | Unit 1.3/1.4 | `[ ]` |

---

## Decisions Log

| Date | Unit | Decision | Rationale |
|---|---|---|---|
| 2026-07-12 | — | Folded `SkillMastery` into encrypted vector (no separate table) | Avoid leaking plaintext `skill_id`s (design doc §5.2) |
| 2026-07-12 | — | Evidence-delta log off by default | Strictest reading of "never persist raw evidence" (design doc §5.3) |
| 2026-07-12 | — | Skill map uses `GradeStage` K-2/3-5/6-8 (not timer's K-3 split) | Consistency with `grade_to_stage()` (design doc §2.1) |
| 2026-07-12 | — | Design-doc/runtime-loop artifacts added to repo under `docs/diagnostic/` | They were previously only conversation attachments; the build loop needs a real, version-controlled shared workspace to read/write, not an ephemeral upload |
| 2026-07-12 | — | Appendix A / §5 line-number citations in `ai_service.py`/`core/database.py` are stale | Same-day, unrelated edits (previous-lesson-context + learner-profile-history work, this same repo session) shifted ~60–80 lines. Function names/structure unaffected. Flagged in both design docs; must be re-verified before any Phase 3 unit relies on them — Phase 1/2 do not depend on these citations |

---

## Completed-Unit Audit (filled as units merge)

_Format per row: `unit-id · branch · PR link · check output (1 line) · verified anchors`_

_(none yet — first merge will be unit 1.1)_
