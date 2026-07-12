# The Diagnostic Build Loop

**What this is:** The development loop that *constructs* the Bede Diagnostic Engine. Where `DIAGNOSTIC_LOOP.md` defines the engine's **runtime** cycle (S1–S9 per tutoring turn), this document defines the **build** cycle (B1–B7 per implementation unit) that turns the design doc into verified, merged code. The two loops are paired: each build-loop iteration delivers one verified increment of the runtime loop.

**Companion artifacts:**
- `DIAGNOSTIC_ENGINE_DESIGN.md` — the full design (components, data models, prompts, file list).
- `DIAGNOSTIC_LOOP.md` — the runtime loop (what we are building).
- `DIAGNOSTIC_BUILD_PROGRESS.md` — the build loop's **mutable state** (unit checklist + decisions log). Every iteration reads and writes this file.

---

## 1. Loop Identity

| Property | Value |
|---|---|
| **Granularity** | One iteration = one atomic implementation unit (typically one module or one wiring change) |
| **Driver** | The main agent orchestrates; each iteration's S2 is a `codebase` subagent on a feature branch |
| **Gate discipline** | Bede's Standing Workflow (CLAUDE.md): every fix/feature is **verified with a real check** before merge |
| **Hard gate** | B3 (Verify) must pass, or the iteration does not advance (≤2 retries, then pause for user) |
| **Phase gate** | Between phases, pause for user sign-off before starting the next phase |
| **Termination** | When Phase 5 acceptance (end-to-end real math session) passes and tuning is signed off |

The build loop is the engine's construction lifecycle. It does not run on a schedule — it runs when you say "next" (or "go" to chain iterations within a phase).

---

## 2. Loop State — `DIAGNOSTIC_BUILD_PROGRESS.md`

The loop's memory. Each iteration:
1. **Reads** it to find the next not-started unit and its acceptance check.
2. **Writes** to it at B6 (status, test result, decisions, verified anchors).

It contains:
- The full unit breakdown (§4 below) as a checklist with per-unit status.
- A decisions log (design deviations, `[to verify]` resolutions).
- A phase-status header (current phase, phase-gate state).
- The privacy-invariant checklist carried from the runtime loop (§6 of `DIAGNOSTIC_LOOP.md`).

This file is the single source of truth for build progress — readable by you and by every build subagent.

---

## 3. The Loop — Step by Step

```
        ┌──────────────────────────────────────────────────────────────┐
        │  ITERATION START  (user: "next" / "go")                       │
        └──────────────────────────────────────────────────────────────┘
                                │
        ┌─────────────────────── ▼ ────────────────────────┐
   B1   │  SCOPE  — read PROGRESS + design doc + runtime   │   (main agent)
        │  loop; pick next not-done unit; confirm acceptance│
        │  check + which runtime step(s) it implements     │
        └─────────────────────── ┬ ──────────────────────── ┘
                                │
        ┌─────────────────────── ▼ ────────────────────────┐
   B2   │  SCAFFOLD — codebase subagent implements the unit │   (subagent, feature branch)
        │  on a branch; follows design doc + §6 invariants  │
        └─────────────────────── ┬ ──────────────────────── ┘
                                │
        ┌─────────────────────── ▼ ────────────────────────┐
   B3   │  VERIFY  — run the REAL CHECK (unit test /        │   (subagent, then main agent confirms)
        │  typecheck / build / e2e) per the unit's spec.    │
        │  Must pass. ≤2 retries with feedback, else pause. │
        └─────────────────────── ┬ ──────────────────────── ┘
                                │
        ┌─────────────────────── ▼ ──────────────────────── ┐
   B4   │  REVIEW  — privacy-invariant checklist for any   │   (main agent; dual-agent review
        │  data/persistence/prompt unit; optional dual-agent│    for non-trivial units)
        │  code review (codebase + codex_codebase)          │
        └─────────────────────── ┬ ──────────────────────── ┘
                                │
        ┌─────────────────────── ▼ ────────────────────────┐
   B5   │  MERGE  — squash-merge to main (or stage on branch│   (main agent, via GitHub)
        │  until phase complete per user pref); PR link     │
        │  recorded in PROGRESS                             │
        └─────────────────────── ┬ ──────────────────────── ┘
                                │
        ┌─────────────────────── ▼ ────────────────────────┐
   B6   │  RECORD — update PROGRESS: unit ✓, test result,   │   (main agent)
        │  decisions, verified anchors; advance phase if    │
        │  phase complete                                    │
        └─────────────────────── ┬ ──────────────────────── ┘
                                │
        ┌─────────────────────── ▼ ────────────────────────┐
   B7   │  NEXT — if phase boundary reached → PAUSE for    │   (loop control)
        │  user sign-off; else loop to B1 for next unit     │
        └─────────────────────── ┬ ──────────────────────── ┘
                                ▼
        ┌──────────────────────────────────────────────────────────────┐
        │  ITERATION END  →  (continue | pause at phase gate | done)  │
        └──────────────────────────────────────────────────────────────┘
```

### B1 — SCOPE (main agent)
Read `DIAGNOSTIC_BUILD_PROGRESS.md`, find the lowest-numbered unit with status `pending`. Confirm: the unit's deliverable, its **real check** (§5), and which runtime-loop step(s) (S1–S9) it realizes. Resolve any `[to verify]` items blocking it.

### B2 — SCAFFOLD (codebase subagent)
Spawn a `codebase` subagent (managed clone, or existing workspace at `/home/user/workspace/bede`) with: the unit spec, references to the design doc + runtime loop + progress file, the §6 invariants, and the reusable driver prompt (§6 of this doc). It implements on a feature branch `diagnostic/<unit-id>`.

### B3 — VERIFY (subagent → main agent confirms)
Run the unit's **real check** (the bede Standing Workflow gate). If it fails: subagent retries with the failure output (max 2). If still failing: pause for user. No unit advances without a green real check.

### B4 — REVIEW (main agent; dual-agent for non-trivial)
- Every unit touching data, persistence, or prompts must pass the **privacy-invariant checklist** (runtime loop §6).
- Non-trivial units (CDM, the silent tool handler, the prompt injection, the parent router) get a dual review (`codebase` + `codex_codebase`, per the coding skill's review protocol); I synthesize and report.

### B5 — MERGE (main agent, via GitHub)
Squash-merge `diagnostic/<unit-id>` → `main` (or stage on a long-lived `diagnostic-engine` branch until the phase is complete — your preference; default: merge per unit so progress is incremental and reviewable). Record the PR link in the progress file.

### B6 — RECORD (main agent)
Update `DIAGNOSTIC_BUILD_PROGRESS.md`: mark the unit `done`, paste the test result, log any design deviation or decision, record verified source anchors. If the phase is now complete, set the phase-gate state to `awaiting sign-off`.

### B7 — NEXT (loop control)
- Within a phase: loop to B1 for the next unit (user can say "go" to chain without pausing).
- At a phase boundary: **pause for user sign-off** before starting the next phase.
- On Phase 5 acceptance: loop terminates — engine is live.

---

## 4. Unit Breakdown (the build loop's work queue)

Each unit is one iteration. Status tracked in `DIAGNOSTIC_BUILD_PROGRESS.md`.

### Phase 1 — Core package (pure Python, no DB, no LLM, unit-tested)
| Unit | Deliverable | Real check |
|---|---|---|
| 1.1 | `services/diagnostic/skill_map.py` — K-8 math DAG (domains→skills→sub-skills, prerequisites, bands) | DAG acyclic; prereqs resolve; every skill has a band |
| 1.2 | `qmatrix.py` — probe archetypes, `q_row`, `EvidenceObservation` | every probe maps to ≥1 attribute; unknown id → `None` |
| 1.3 | `irt.py` — 1PL/2PL/3PL P(correct), Fisher info, θ MLE/EAP update | known P values; Fisher monotonicity; θ converges on synthetic stream |
| 1.4 | `cdm.py` — DINA/DINO/G-DINA posterior update | slip/guess sanity; posterior moves correctly on correct/incorrect |
| 1.5 | `kst.py` — surmise closure, knowledge states, `fringe`, `propagate_prerequisites` | fringe correct on small map; prereqs enforced |
| 1.6 | `cat.py` — `select_next_probes` (max Fisher/entropy), `should_stop_probing` | selects highest-uncertainty fringe skill; respects `resolved` |
| 1.7 | `mastery.py` — `MasteryVector`, `new_vector`, `bayesian_update`, `aggregate_for_parent` | **acceptance**: synthetic evidence stream converges vector sensibly + respects prereqs |
| 1.8 | `__init__.py` façade — `process_evidence`, `get_next_probe_hint` (in-memory) | end-to-end in-memory round trip green |

**Phase 1 gate:** all 8 units green; the pure core works with no DB/LLM. → pause for sign-off.

### Phase 2 — Persistence
| Unit | Deliverable | Real check |
|---|---|---|
| 2.1 | `MasteryProfile` + `DiagnosticEvidenceLog` ORM in `core/database.py`; config flag in `core/config.py` | `create_tables()` picks them up; columns are `LargeBinary` encrypted |
| 2.2 | `process_evidence` load→update→encrypt→store round trip | round-trip test with a test Postgres; decrypt equals in-memory |
| 2.3 | Pydantic schemas in `models/schemas.py` | `ResponseModel` validation passes |

**Phase 2 gate:** encrypted vector survives a real DB round trip; no raw evidence persisted. → sign-off.

### Phase 3 — Loop integration
| Unit | Deliverable | Real check |
|---|---|---|
| 3.1 | `record_skill_evidence` tool def + `_record_skill_evidence` handler + dispatcher branch in `ai_service.py` | child SSE stream byte-for-byte unchanged; demo role writes nothing |
| 3.2 | `_build_subject_prompt` diagnostic injection (thread decrypted vector) | static block still cacheable; subject block carries `<diagnostic_guidance>` |
| 3.3 | Calibration weighting + widened probe spread | calibration banner toggles correctly; weight decays with `C.n` |

**Phase 3 gate:** runtime loop S1–S9 runs end-to-end on a real tutoring turn; child sees nothing. → sign-off.

### Phase 4 — Parent surface
| Unit | Deliverable | Real check |
|---|---|---|
| 4.1 | `routers/diagnostic.py` (`GET .../summary`) + `main.py` registration | behind `require_parent`; `ExfiltrationGuard` passes; 404 on missing |
| 4.2 | `MasteryDashboard.tsx` + `types` + `api.ts` + `/mastery` route | render-only; no download/print button; `tsc --noEmit` clean |

**Phase 4 gate:** parent can open the dashboard on a real session; child UI unaffected. → sign-off.

### Phase 5 — Validation & tuning
| Unit | Deliverable | Real check |
|---|---|---|
| 5.1 | End-to-end real math tutoring session | evidence flows; vector moves; parent renders; child sees nothing |
| 5.2 | Tune slip/guess, calibration N, mastery thresholds | vector converges sensibly across a multi-session synthetic + real corpus |

**Phase 5 gate:** engine live. Loop terminates.

---

## 5. Real-Check Definitions (the B3 gate)

A "real check" is concrete and runnable — never "looks right."
- **Pure-core units (1.x):** `pytest` unit tests in `homeschool-api/tests/diagnostic/`. The Phase 1 acceptance test (1.7) is the spine: a synthetic evidence stream that proves the vector converges and respects prerequisites.
- **Persistence units (2.x):** a round-trip test against a real (containerized) Postgres, asserting decrypt(in-memory) == encrypt(store(load)).
- **Integration units (3.x):** a streamed tutoring-turn fixture asserting (a) the child SSE output is byte-identical with and without the tool, (b) `db=None` writes nothing.
- **Frontend units (4.x):** `npx tsc --noEmit` clean + a render snapshot of the dashboard with no export/print affordances.
- **E2E (5.x):** a real Claude-driven math session (the bede Standing Workflow's "actual session" check).

If a check can't be made runnable (e.g., subjective tuning), the gate is a documented decision recorded in the progress file, signed off by you.

---

## 6. Reusable Build-Subagent Driver Prompt

Paste this (with the `{unit}` filled in) into each B2 `run_subagent` call:

```
Repository setup: managed clone from https://github.com/agnusdei-ai/bede
(you share the workspace at /home/user/workspace/bede — do not re-clone if present).

CONTEXT — read these first, in order:
1. /home/user/workspace/DIAGNOSTIC_ENGINE_DESIGN.md  (full design)
2. /home/user/workspace/DIAGNOSTIC_LOOP.md            (runtime loop S1–S9 + §6 invariants)
3. /home/user/workspace/DIAGNOSTIC_BUILD_PROGRESS.md  (build state — find your unit)

TASK — implement unit {unit-id}: {unit-deliverable}.
Branch: diagnostic/{unit-id}. Follow the design doc's signatures exactly.
This unit realizes runtime-loop step(s): {S-list}.

HARD RULES:
- Pure Python only. No new runtime deps. No third-party CAT/CDM/IRT code. Use stdlib `math`.
- Honor all §6 invariants (child-invisible, transcript-free persistence, cache-safe prompting, no new exposure surface, demo isolation, subject gating) as they apply to this unit.
- Mirror existing bede patterns (encryption, ORM, deps, prompt blocks) — do not invent parallel patterns.

DELIVERABLE:
- The implementation on branch diagnostic/{unit-id}.
- A real, runnable check (see this unit's real-check in the progress file) that passes.
- Update DIAGNOSTIC_BUILD_PROGRESS.md: mark the unit done, paste the check output, log any decision/deviation, record verified source anchors.

Return: branch name, check output, and a 3-line summary of what you implemented.
```

---

## 7. Gate Summary

| Gate | Rule |
|---|---|
| **B3 hard gate** | Real check must pass (≤2 retries, then pause for user) |
| **Privacy gate (B4)** | Every data/persistence/prompt unit passes the runtime §6 invariant checklist |
| **Phase gate (B7)** | Pause for user sign-off between phases |
| **Acceptance (Phase 5)** | End-to-end real math session passes → loop terminates |

---

## 8. How the Two Loops Relate

| | Runtime loop | Build loop |
|---|---|---|
| **What it does** | Operates the engine each tutoring turn | Constructs the engine unit by unit |
| **Steps** | S1–S9 | B1–B7 |
| **State** | `(V, θ, C)` in `MasteryProfile` | `DIAGNOSTIC_BUILD_PROGRESS.md` |
| **Cadence** | Every turn | On demand ("next" / "go") |
| **Termination** | Never (shifts to maintenance) | When Phase 5 acceptance passes |
| **Relationship** | Each build iteration delivers a verified piece of the runtime loop | The runtime loop is the acceptance criterion for the build loop |

The build loop exists to produce the runtime loop, correctly and privately, one verified increment at a time.
