# The Diagnostic Prompt Loop

**What this is:** The Bede Diagnostic Engine, restructured as a single repeating loop. The engine is not a set of components that run once — it is a **per-turn cycle** that runs silently inside every Socratic tutoring turn, forever (across sessions and subjects), until the skill map is resolved and then in maintenance mode. This document specifies that loop: its state, its steps, its control logic, and how each step maps onto bede's existing streaming state machine.

**Design doc cross-refs:** Components referenced here (CDM/IRT/KST/CAT/mastery, `record_skill_evidence`, `MasteryProfile`, prompt blocks) are fully specified in `DIAGNOSTIC_ENGINE_DESIGN.md` (§4–§10). This document adds the *loop* — the orchestration and control flow that turns those parts into a living, evolving profile.

---

## 1. Loop Identity

| Property | Value |
|---|---|
| **Granularity** | One iteration = one Socratic tutoring turn within a subject session |
| **Embedding** | Woven into bede's existing `stream_tutor_response` SSE turn; does **not** replace tutoring |
| **Visibility** | Fully silent to the child. The child experiences normal Charlotte Mason tutoring. |
| **Persistence window** | Raw evidence exists in memory only during Steps 5→7; only derived probabilities are persisted (Step 8) |
| **Termination** | Never hard-stops. Per-skill stopping rule removes skills from the *active probe set*; the loop continues until the math map is resolved, then drops to refresh/maintenance cadence |
| **Cold start** | Calibration mode (widened probe spread, higher update weight) until each skill has ≥ N observations |

The loop is the engine. There is no separate "assessment" invocation — assessment is a *phase of every turn*.

---

## 2. Loop State (carried across iterations)

Per `(student_name, subject_area)`, stored encrypted in `MasteryProfile.profile_enc` (AES-256-GCM):

| Symbol | Meaning | Shape |
|---|---|---|
| `V` | Mastery vector | `{skill_id → P(mastery) ∈ [0,1]}` |
| `θ` | Global ability estimate (IRT) | `float` |
| `C` | Calibration state | `{skill_id → {n_observations, resolved: bool, last_seen: ts}}` |
| `band` | Grade band | `K-2 \| 3-5 \| 6-8` (from `GradeStage`) |

Derived per-iteration (not persisted):
- `F` = **KST fringe** — skills whose prerequisites are all mastered (`kst.fringe(V)`) but which are not yet `resolved`. This is the "probeable / learnable now" set.
- `active_probe_set` ⊆ `F` — the skills the CAT step will steer Bede toward this turn.

---

## 3. The Loop — Step by Step

```
        ┌──────────────────────────────────────────────────────────────┐
        │  TURN START (child sends a message / [START] subject opener) │
        └──────────────────────────────────────────────────────────────┘
                                │
        ┌─────────────────────── ▼ ────────────────────────┐
   S1   │  HYDRATE  — load + decrypt (V, θ, C); compute F   │   (pre-stream, server-side)
        └─────────────────────── ┬ ──────────────────────── ┘
                                │
        ┌─────────────────────── ▼ ──────────────────────── ┐
   S2   │  SELECT  — CAT picks probe targets from F (max     │   (server-side)
        │  Fisher info / max posterior entropy); widen if   │
        │  calibration mode                                   │
        └─────────────────────── ┬ ──────────────────────── ┘
                                │
        ┌─────────────────────── ▼ ──────────────────────── ┐
   S3   │  INJECT  — add <diagnostic_guidance> to subject    │   (server-side, non-cached
        │  prompt: mastery snapshot + probe hints + cal flag│    subject block)
        └─────────────────────── ┬ ──────────────────────── ┘
                                │
        ┌─────────────────────── ▼ ──────────────────────── ┐
   S4   │  INTERACT — Bede tutors Socratically; child        │   (the SSE stream itself;
        │  narrates / shows work. Normal tutoring.           │    child unaware)
        └─────────────────────── ┬ ──────────────────────── ┘
                                │  (Bede calls the silent tool mid-stream)
        ┌─────────────────────── ▼ ──────────────────────── ┐
   S5   │  CAPTURE — record_skill_evidence(probe_id, outcome,│   (silent tool dispatch;
        │  confidence)  → returns (None, None); emits nothing│    ContentBlockStop)
        └─────────────────────── ┬ ──────────────────────── ┘
                                │
        ┌─────────────────────── ▼ ──────────────────────── ┐
   S6   │  INFER  — q_row(probe_id) → attributes; IRT θ      │   (server-side, in-memory)
        │  update; CDM posteriors per attribute (DINA/G-DINA)│
        └─────────────────────── ┬ ──────────────────────── ┘
                                │
        ┌─────────────────────── ▼ ──────────────────────── ┐
   S7   │  UPDATE — Bayesian blend into V (calibration-     │   (server-side, in-memory)
        │  weighted); kst.propagate_prerequisites; emit deltas│
        └─────────────────────── ┬ ──────────────────────── ┘
                                │
        ┌─────────────────────── ▼ ──────────────────────── ┐
   S8   │  PERSIST — encrypt (V, θ, C) → MasteryProfile;     │   (encrypted write)
        │  optional encrypted delta log; raw evidence dropped│
        └─────────────────────── ┬ ──────────────────────── ┘
                                │
        ┌─────────────────────── ▼ ──────────────────────── ┐
   S9   │  DECIDE — apply stopping rule per probed skill;    │   (loop control)
        │  update C.resolved; toggle calibration exit;       │
        │  refresh F for next turn                            │
        └─────────────────────── ┬ ──────────────────────── ┘
                                │
                                ▼
        ┌──────────────────────────────────────────────────────────────┐
        │  TURN END (SSE `done`)  →  loop returns to S1 next turn      │
        └──────────────────────────────────────────────────────────────┘
```

### S1 — HYDRATE (pre-stream, server-side)
Before `_build_subject_prompt` runs, load `MasteryProfile` for `(student_name, "mathematics")`, decrypt to `(V, θ, C)`. If none exists, `mastery.new_vector(band)` → uniform prior 0.5 for on-band skills, lower for above-band. Compute `F = kst.fringe(V, prerequisites)`. Demo role (`db is None`, `routers/tutor.py:92`): short-circuit, skip the whole loop.

### S2 — SELECT (CAT, server-side)
`cat.select_next_probes(V, θ, F, band, calibration=C[skill].n < N)`:
- Rank `F` by expected Fisher information (or posterior entropy — maximum uncertainty reduction).
- In calibration mode, **widen**: also include a spread of below/above-band skills to localize the child's level faster.
- Return a ranked `probe_hint`: short list of `{skill_id, label, suggested_socratic_angle}`.
- Apply `cat.should_stop_probing` per skill to drop resolved ones from the active set.

### S3 — INJECT (subject prompt block, server-side)
Append `<diagnostic_guidance>` to the **non-cached** subject block in `_build_subject_prompt` (keeps the static block in `_build_static_prompt` cacheable — verified two-block prompt design):
- mastery snapshot: counts of secure / developing / gap
- the `probe_hint` from S2 (skills Bede should naturally elicit evidence for this turn)
- calibration flag (so Bede knows to spread probes wider early)
- one line: "Weave these into normal Socratic dialogue. Do not announce assessment."

### S4 — INTERACT (the SSE stream)
`stream_tutor_response` runs normally — Bede tutors Socratically, the child narrates / shows math work / answers. This is ordinary tutoring. The child has no indication assessment is occurring.

### S5 — CAPTURE (silent tool dispatch)
When Bede judges the interaction revealed mastery of a probed skill, it calls `record_skill_evidence(probe_id, outcome∈{correct, partial, incorrect, hint_dependent}, confidence)`. The tool is accumulated in the SSE tool buffer and dispatched at `ContentBlockStop` via `_dispatch_completed_tool_call` (verified). `_record_skill_evidence` returns `(None, None)` — **stricter than `assess_narration`**: emits no SSE event at all, so `SocraticChat.tsx` is untouched. `probe_id` is validated against the Q-matrix server-side (invented ids drop silently).

### S6 — INFER (CDM/IRT, server-side, in-memory)
- `qmatrix.q_row(probe_id)` → the attribute vector (which sub-skills this evidence bears on).
- IRT: update `θ` from `(probe difficulty, outcome)` (1PL/2PL/3PL).
- CDM: for each attribute, compute `P(attribute | outcome)` via DINA (slip/guess) — or G-DINA for finer-grained — in `cdm.update_attribute_posteriors`.

### S7 — UPDATE (Bayesian, server-side, in-memory)
`mastery.bayesian_update(V, observation, calibration_weight, model)`:
- Blend CDM posteriors into `V`, weighted by `calibration_weight` (higher early, decaying as `C.n` grows).
- `kst.propagate_prerequisites(V)`: enforce surmise relations — if a skill is mastered but its prereqs are not, reconcile (downgrade or unlock).
- Emit `MasteryUpdate` deltas (prior→posterior per skill).

### S8 — PERSIST (encrypted write)
`encrypt_json({V, θ, C})` → `MasteryProfile.profile_enc` (AES-256-GCM, existing DATA_KEY hierarchy — no new key material). If `settings.diagnostic_evidence_log_enabled` (default `False`), write the encrypted deltas to `DiagnosticEvidenceLog`. **The raw `outcome` tuple and any transcript are discarded** — they never leave the S5→S7 in-memory window.

### S9 — DECIDE (loop control)
- Per probed skill: if `|P − 0.5|` is large **and** `SE < threshold`, mark `C[skill].resolved = True` → it leaves the active probe set.
- If enough on-band skills reach `resolved`, exit calibration mode.
- Recompute `F` for the next turn.
- The loop returns to S1 on the next turn. No hard termination.

---

## 4. Loop Control Logic (pseudocode)

```python
# Runs once per tutoring turn, embedded in stream_tutor_response.
async def diagnostic_loop_turn(db, session_config, current_subject):
    student = session_config.student_name
    band    = grade_to_stage(session_config.grade)

    if db is None or current_subject != Subject.mathematics:
        return                                   # demo or non-math: loop is a no-op

    # S1 HYDRATE
    V, θ, C = await load_or_init_vector(db, student, "mathematics", band)
    F        = kst.fringe(V, SKILL_PREREQS)

    # S2 SELECT
    calibration = any(C[s].n < CALIBRATION_N for s in F)
    probe_hint  = cat.select_next_probes(V, θ, F, band, calibration)

    # S3 INJECT  (called from _build_subject_prompt)
    subject_prompt_extra = render_diagnostic_guidance(V, probe_hint, calibration)

    # -- S4 INTERACT happens inside the SSE stream; Bede may call: --
    #    record_skill_evidence(probe_id, outcome, confidence)   [S5 CAPTURE]

    # S6–S8 run inside _record_skill_evidence (the silent tool handler):
    #   q_row -> irt.update_theta -> cdm.posteriors ->
    #   mastery.bayesian_update -> kst.propagate -> encrypt_json -> persist
    # The tool returns (None, None); nothing reaches the child stream.

    # S9 DECIDE  (executed at turn finalize, before SSE `done`)
    for s in probe_hint.skills:
        if should_stop_probing(V[s], C[s].n):
            C[s].resolved = True
    await persist(db, student, "mathematics", V, θ, C)
    # loop returns; S1 fires again next turn
```

---

## 5. Mapping to bede's Streaming State Machine

| Loop step | bede code anchor (verified) | When |
|---|---|---|
| S1 Hydrate, S2 Select, S3 Inject | Before `_stream_tutor_events` emits; inside `_build_subject_prompt` (691–704) | Turn start |
| S4 Interact | `stream_tutor_response` SSE stream | During stream |
| S5 Capture | Tool buffer → `_dispatch_completed_tool_call` (924–963) at `content_block_stop` (1033–1052) | Mid-stream |
| S6 Infer, S7 Update, S8 Persist | Inside `_record_skill_evidence` (the silent-tool handler) | After tool dispatch |
| S9 Decide | Turn finalize, before `data: {"type":"done"}` | Turn end |

**Critical invariant:** per-turn state (`V`, `probe_hint`, calibration) lives only in the **non-cached subject block**. The static block (`_build_static_prompt`, 523–593) stays cacheable — the diagnostic never breaks bede's prompt-caching economics.

> **Line-number note (added post-design):** the anchors above drifted after same-day, unrelated edits to `ai_service.py` (the previous-lesson-context and learner-profile-history work) — see `DIAGNOSTIC_BUILD_PROGRESS.md`'s decisions log for corrected current line numbers before any Phase 3 unit relies on them. Function names and structure are still accurate.

---

## 6. Loop Invariants (must hold every iteration)

1. **Child-invisible:** no score, probe selection, or assessment signal ever reaches the child's SSE stream. (`record_skill_evidence` returns `(None, None)`.)
2. **Transcript-free persistence:** raw `outcome` and any child utterance exist only in the S5→S7 in-memory window; only derived `(V, θ, C)` (and optional deltas) are persisted, encrypted.
3. **Cache-safe prompting:** per-turn mastery state is injected into the subject block, never the static block.
4. **No new exposure surface:** no export/download/print endpoint is added; parent reads via `GET /diagnostic/{student}/summary` behind `require_parent`, compatible with `ExfiltrationGuard`.
5. **Demo isolation:** `db is None` → entire loop is a no-op (demo visitors never write a profile).
6. **Subject gating:** loop runs only for `Subject.mathematics` in Phase 1; non-math turns pass through untouched (extensible per §13 of the design doc).

---

## 7. Lifecycle Modes of the Loop

The same loop runs in three modes, distinguished only by `C` state:

| Mode | Trigger | Behavior |
|---|---|---|
| **Calibration** | First `N` observations per skill, or new student | Widened probe spread; higher `calibration_weight`; parent sees a "Bede is still getting to know how {name} thinks about math" banner |
| **Resolution** | Calibration exited, skills still unresolved | Standard CAT (max Fisher info over fringe); normal update weight |
| **Maintenance** | Most on-band skills `resolved` | Light refresh probing on a decay schedule; detects regression (a `resolved` skill slipping → re-enters active set) |

Transitions are automatic, driven by `C` — no separate "modes" in code, just the same S1→S9 cycle reading different `C` state.

---

## 8. What This Loop Is Not

- **Not a test loop.** No item bank of questions is asked in sequence. The "items" are normal Socratic exchanges; the CAT step produces *prompt hints*, not test items.
- **Not a batch job.** It does not run on a schedule or over historical data. It runs inline with each live turn. (A separate, optional offline re-estimation pass over the encrypted delta log could refine `V` later — out of scope for Phase 1.)
- **Not a separate session.** There is no "diagnostic session" the child enters. The loop is a phase of every math tutoring turn.

---

## 9. Resolved: runtime loop + build loop, both in scope

(Originally an open question at design time — resolved: both this runtime loop and `DIAGNOSTIC_BUILD_LOOP.md`'s build loop are in scope, paired as designed. See `DIAGNOSTIC_BUILD_PROGRESS.md` for current build status.)
