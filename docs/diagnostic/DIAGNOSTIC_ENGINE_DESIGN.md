# Bede Diagnostic Engine — Design Document

**Status:** Design only. No implementation code lands with this document.
**Scope of first build:** K–8 Mathematics.
**Author's note on citations:** Every file path, function, class, and signature below was read from the actual `bede` source at design time. Anything asserted but *not* directly verified in source is marked **[to verify]**.

---

## 1. Executive Summary, Goals, Locked Decisions, Privacy Constraints

### 1.1 Executive summary

Bede today runs a Socratic tutoring loop (`services/ai_service.py::stream_tutor_response`) with agentic tools, one of which — `assess_narration` — is **silent and server-side only**: it scores a child's narration, persists the result AES-256-GCM-encrypted (`_save_assessment` → `NarrationAssessment` ORM + `core.encryption.encrypt_json`), and emits only a minimal non-content event the child UI deliberately ignores (`SocraticChat.tsx` line 122–123: *"Silent server-side narration score — no UI change for child"*).

The **Diagnostic Engine** generalizes that pattern into a continuous, psychometrically-grounded **mastery profile**: a per-student `{skill_id → mastery_probability ∈ [0,1]}` vector over a K–8 math skill map, updated silently after tutoring interactions using open-standard CDM/IRT/KST algorithms implemented from scratch in pure Python (no external runtime dependency, no copyleft contamination of the proprietary codebase). It plugs into the existing streaming loop via a **new silent tool `record_skill_evidence`**, reuses the existing encryption hierarchy and `require_parent` gating, and surfaces to the parent through a **render-only** dashboard — no export, download, or print, fully compatible with the existing `ExfiltrationGuard`.

### 1.2 Goals

- **G1 — Embedded, not a test.** Diagnostic probes flow inside normal Socratic tutoring. No separate "assessment session," no standalone artifact.
- **G2 — Continuous mastery vector.** Maintain a Bayesian-updated per-skill probability vector per student, over a K–8 math skill map.
- **G3 — Open standards, proprietary implementation.** Implement IRT (1PL/2PL/3PL), CDM (DINA/DINO/G-DINA), KST (surmise relations), Q-matrix, and CAT item selection from published algorithms, in pure Python.
- **G4 — Privacy by construction.** Store derived probabilities only; never raw probe transcripts. Parent-confidential; invisible to the child.
- **G5 — Zero architectural drift.** Mirror existing bede patterns (encryption, ORM, routers, deps, SSE tool dispatch, prompt blocks) exactly. Extensible to reading/ELA and science.

### 1.3 Locked decisions (from the design brief)

1. **Loop model: Embedded / Interwoven.** Extends the `assess_narration` silent server-side pattern; no separate test session.
2. **CDM/KST core: pure-Python, from scratch.** No EduCAT/mycaas/Concerto vendoring (GPL/copyleft). Full IP ownership, no supply-chain risk, serializes cleanly to encrypted BYTEA.
3. **Scope: K-8 math first.** Extensible to reading/ELA and science later.
4. **Deliverable now: design doc only.**

### 1.4 Privacy constraints (HARD) → satisfied by (forward reference to §11)

| # | Constraint | Bede control |
|---|-----------|--------------|
| P1 | Mastery profile is parent-confidential, never shown to child | `require_parent` on all read endpoints; new tool emits **no** SSE event to the child stream |
| P2 | Store only derived probabilities as AES-256-GCM BYTEA | `core.encryption.encrypt_json` → `LargeBinary` columns, same DATA_KEY hierarchy |
| P3 | Never persist raw probe transcripts / child responses | Evidence processed in-memory during the stream, only the resulting probability delta persisted (§5) |
| P4 | Parent view render-only: no download/export/print | Reuse `ExfiltrationGuard` (blocks `/export /download /dump /backup /debug`, 2 MB cap, strips `content-disposition`); no new export endpoint |
| P5 | All endpoints behind `require_parent` (JWT + IP/UA fingerprint) | `core.deps.require_parent` |
| P6 | No new export/download endpoint of any kind | Only `GET /diagnostic/{student}/summary` (+ optional detail GET), both render-only JSON |

---

## 2. K–8 Math Skill Map

The skill map is a **directed acyclic graph (DAG)**: `domain → skill → sub-skill`, with **prerequisite (surmise) edges** between sub-skills for KST. The engine treats *sub-skills* as the atomic "attributes" of the CDM Q-matrix; domains and skills are aggregation layers for the parent view only.

### 2.1 Structure

```
Domain              (e.g. "Number & Operations")
  └─ Skill          (e.g. "Multiplication")
       └─ Sub-skill (atomic attribute, appears in Q-matrix, has mastery prob)
```

Each sub-skill node carries: `id`, `domain`, `skill`, `label`, `grade_band` (`K-2` | `3-5` | `6-8`, mirroring `GradeStage` in `models/schemas.py`), and `prerequisites: list[skill_id]` (the surmise relation — "mastering X is presumed before Y").

> **Grade-band note (verified):** `models/schemas.py::GradeStage` = `foundations="K-2"`, `core_mastery="3-5"`, `independent="6-8"`. The frontend `utils/gradeTimer.ts` separately uses `grade<=3` as "younger" for *timer* purposes only. The skill map uses the **GradeStage** K-2 / 3-5 / 6-8 banding, not the timer's K-3 split, to stay consistent with `grade_to_stage()`. **[design choice — flagged so the user can override]**

### 2.2 Domains (K–8 math, CCSS-aligned vocabulary, kept internal per brief)

1. **Counting & Cardinality** (K)
2. **Number & Operations in Base Ten**
3. **Operations & Algebraic Thinking**
4. **Number & Operations — Fractions**
5. **Measurement & Data**
6. **Geometry**
7. **Ratios & Proportional Relationships** (6-7)
8. **The Number System** (6-8: integers, rationals)
9. **Expressions & Equations** (6-8)
10. **Statistics & Probability** (6-8)
11. **Functions** (8)

### 2.3 Representative skeleton (extensible)

```
Counting & Cardinality [K-2]
  count_sequence
    cc.rote_count_20            (prereq: —)
    cc.count_objects_20         (prereq: cc.rote_count_20)
    cc.compare_quantities       (prereq: cc.count_objects_20)

Number & Operations in Base Ten [K-2 → 3-5]
  place_value
    nbt.place_value_tens        (prereq: cc.count_objects_20)
    nbt.place_value_hundreds    (prereq: nbt.place_value_tens)
    nbt.place_value_decimals    (prereq: nbt.place_value_hundreds, fr.equivalent_fractions)
  multi_digit_arithmetic
    nbt.add_within_100          (prereq: oa.add_within_20, nbt.place_value_tens)
    nbt.subtract_within_100     (prereq: oa.subtract_within_20, nbt.place_value_tens)
    nbt.standard_multiplication (prereq: oa.multiplication_facts, nbt.place_value_hundreds)
    nbt.long_division           (prereq: nbt.standard_multiplication)

Operations & Algebraic Thinking [K-2 → 6-8]
  addition_subtraction
    oa.add_within_20            (prereq: cc.count_objects_20)
    oa.subtract_within_20       (prereq: oa.add_within_20)
  multiplication_division
    oa.multiplication_facts     (prereq: oa.add_within_20)
    oa.division_facts           (prereq: oa.multiplication_facts)
  patterns_expressions
    oa.numeric_patterns         (prereq: oa.multiplication_facts)

Number & Operations — Fractions [3-5]
  fr.unit_fractions            (prereq: oa.division_facts)
  fr.equivalent_fractions      (prereq: fr.unit_fractions)
  fr.add_subtract_fractions    (prereq: fr.equivalent_fractions)
  fr.multiply_fractions        (prereq: fr.add_subtract_fractions)

Ratios & Proportional Relationships [6-7]
  rp.ratio_concept             (prereq: fr.equivalent_fractions)
  rp.unit_rate                 (prereq: rp.ratio_concept)
  rp.percent                   (prereq: rp.unit_rate, fr.multiply_fractions)

The Number System [6-8]
  ns.integers                  (prereq: nbt.subtract_within_100)
  ns.rational_operations       (prereq: ns.integers, fr.multiply_fractions)

Expressions & Equations [6-8]
  ee.evaluate_expressions      (prereq: oa.numeric_patterns, ns.rational_operations)
  ee.one_step_equations        (prereq: ee.evaluate_expressions)
  ee.two_step_equations        (prereq: ee.one_step_equations)

Functions [8]
  fn.function_concept          (prereq: ee.two_step_equations, rp.unit_rate)
  fn.linear_functions          (prereq: fn.function_concept)
```

The prerequisite edges are exactly the **KST surmise relation** `≺`: `a ≺ b` means "a child who has mastered `b` is presumed to have mastered `a`." This drives both prerequisite chaining (a low prob on `b` implies re-probing `a`) and next-probe selection.

This skeleton lives in `services/diagnostic/skill_map.py` as data (§4), not code branches, so the user can extend it without touching engine logic.

---

## 3. Q-Matrix Design

### 3.1 What the Q-matrix maps

The **Q-matrix** `Q` is a binary matrix of shape `(num_items, num_skills)` where `Q[i][k] = 1` iff item/interaction `i` requires sub-skill `k`. In bede there is no item bank of multiple-choice questions; the "items" are **tutoring interactions** — a reasoning exchange, a narration, a worked math problem — classified by Bede in the moment.

We therefore define an **interaction-typed Q-matrix**: each *diagnostic probe archetype* is a row, tagged with the sub-skills it exercises. Bede, when it invokes the silent tool (§7), reports **which probe archetype** the interaction matched and **the observed outcome**, and the engine looks up that archetype's Q-row.

### 3.2 Probe archetypes → skills

Example rows (stored in `qmatrix.py` as data):

| probe_id | description | skills probed (Q-row = 1) |
|----------|-------------|---------------------------|
| `probe.frac_add_reasoning` | Child reasons through adding unlike fractions | `fr.equivalent_fractions`, `fr.add_subtract_fractions` |
| `probe.long_div_steps` | Child walks through a long-division problem | `nbt.long_division`, `nbt.standard_multiplication` |
| `probe.place_value_decompose` | Child decomposes a number by place value | `nbt.place_value_tens`, `nbt.place_value_hundreds` |
| `probe.ratio_word_problem` | Child sets up a ratio from a story problem | `rp.ratio_concept`, `rp.unit_rate` |

### 3.3 Mapping the existing `assess_narration` rubric into evidence

`assess_narration` already yields a rich rubric (`completeness/sequence/detail/language_quality/synthesis` each 1–5, plus `concepts_demonstrated`, `misconceptions`, `adaptive_signal`). For math specifically, that rubric becomes **secondary evidence**: `misconceptions` strings can be fuzzy-matched to sub-skill ids, and `adaptive_signal ∈ {advance, repeat, review_prerequisite}` maps to a coarse mastery nudge. The **primary** math evidence comes from the new dedicated tool (§7), which reports a discrete outcome (`correct` / `partial` / `incorrect` / `hint_dependent`) against a named `probe_id` — far cleaner for CDM inference than free-text rubric scores.

### 3.4 Evidence record shape (in-memory only, never persisted raw)

```python
# services/diagnostic/qmatrix.py
EvidenceObservation = TypedDict("EvidenceObservation", {
    "probe_id": str,           # row key into the Q-matrix
    "outcome": Literal["correct", "partial", "incorrect", "hint_dependent"],
    "confidence": float,       # 0..1, Bede's certainty this interaction was diagnostic
})
```

Only the *derived per-skill probability contribution* survives this record (§5); the `EvidenceObservation` itself is discarded after the Bayesian update.

---

## 4. Pure-Python CDM/KST Core — `services/diagnostic/`

A new package alongside the existing `services/` modules (`ai_service.py`, `voice_auth.py`, etc.). **No external runtime dependency** beyond what bede already ships (Python stdlib + `numpy` **[to verify: numpy is not currently imported anywhere in `services/`; if not present, implement with pure `math`/`list` to honor the "no new dependency" rule — see §4.8]**).

```
homeschool-api/services/diagnostic/
  __init__.py      Public façade: process_evidence(), get_next_probe_hint()
  skill_map.py     The DAG data (domains/skills/sub-skills/prereqs) + lookups
  qmatrix.py       Probe archetypes, Q-rows, EvidenceObservation type
  irt.py           1PL/2PL/3PL item response + ability (theta) estimation
  cdm.py           DINA / DINO / G-DINA attribute-mastery inference
  kst.py           Surmise relations, knowledge-state closure, prereq chaining
  cat.py           Item/probe selection (max Fisher info) + stopping rule
  mastery.py       Bayesian update of the mastery vector; MasteryVector type
```

### 4.1 `skill_map.py`

```python
@dataclass(frozen=True)
class SubSkill:
    id: str
    domain: str
    skill: str
    label: str
    grade_band: str            # "K-2" | "3-5" | "6-8"  (mirrors GradeStage)
    prerequisites: tuple[str, ...]

SKILL_MAP: dict[str, SubSkill]          # keyed by SubSkill.id, the §2.3 data

def all_skill_ids() -> list[str]: ...
def prerequisites_of(skill_id: str) -> list[str]: ...
def dependents_of(skill_id: str) -> list[str]: ...
def skills_for_grade_band(band: str) -> list[str]: ...
def domain_of(skill_id: str) -> str: ...
```

### 4.2 `qmatrix.py`

```python
@dataclass(frozen=True)
class ProbeArchetype:
    id: str
    description: str
    skills: tuple[str, ...]    # sub-skill ids this probe exercises

Q_MATRIX: dict[str, ProbeArchetype]     # keyed by probe_id

def q_row(probe_id: str) -> list[str]:              # skills required by a probe
def probes_for_skill(skill_id: str) -> list[str]:   # inverse lookup
def outcome_to_score(outcome: str) -> float:        # correct=1.0 ... incorrect=0.0
```

### 4.3 `irt.py`

Logistic IRT. `theta` = latent ability; `a` discrimination, `b` difficulty, `c` guessing.

```python
def p_1pl(theta: float, b: float) -> float: ...                       # Rasch
def p_2pl(theta: float, a: float, b: float) -> float: ...
def p_3pl(theta: float, a: float, b: float, c: float) -> float: ...

def fisher_information(theta: float, a: float, b: float, c: float = 0.0) -> float: ...

def estimate_theta_mle(
    responses: list[tuple[float, ...]],   # (a,b,c) params paired with outcomes
    outcomes: list[float],                # 0/1 (or graded) observed
    prior_mean: float = 0.0,
    prior_sd: float = 1.0,
) -> tuple[float, float]:                 # (theta_hat, standard_error) — EAP/MAP
```

IRT provides a *within-skill continuous ability* estimate feeding the calibration weighting (§8.3) and the CAT information calculation (§4.6). CDM provides the *per-skill mastery classification*.

### 4.4 `cdm.py` — DINA / DINO / G-DINA

Attribute mastery vector `alpha ∈ {0,1}^K`; the engine tracks the **posterior probability** of mastery per attribute rather than a hard 0/1.

```python
def dina_likelihood(alpha, q_row, slip: float, guess: float) -> float:
    """Conjunctive: all required skills needed. P(correct) = (1-slip) if all mastered else guess."""

def dino_likelihood(alpha, q_row, slip: float, guess: float) -> float:
    """Disjunctive: any one required skill suffices."""

def gdina_likelihood(alpha, q_row, delta: dict) -> float:
    """General: saturated interaction terms `delta` over required-skill subsets."""

def update_attribute_posteriors(
    prior: dict[str, float],              # skill_id -> P(mastery) before
    observation: EvidenceObservation,
    model: Literal["dina", "dino", "gdina"] = "dina",
    params: CdmParams | None = None,
) -> dict[str, float]:                    # posterior P(mastery) for the probed skills
```

Baseline ships **DINA** (simplest, most robust with sparse evidence — appropriate for a single-family, low-volume deployment). DINO and G-DINA are implemented for later opt-in; the `model` parameter selects. `CdmParams` carries per-probe slip/guess (default slip=0.1, guess=0.2 — conservative literature priors, **[to verify: final defaults during scaffolding]**).

### 4.5 `kst.py` — surmise relations

```python
def surmise_closure(mastered: set[str]) -> set[str]:
    """Add all prerequisites of every mastered skill (downward closure)."""

def is_valid_knowledge_state(state: set[str]) -> bool:
    """A state is valid iff it is closed under the surmise relation."""

def propagate_prerequisites(vector: dict[str, float], threshold: float = 0.8) -> dict[str, float]:
    """If P(skill) >= threshold, gently raise floor on its prerequisites' probs
    (a child demonstrably doing X almost certainly has its prereqs)."""

def fringe(vector: dict[str, float], lo: float = 0.2, hi: float = 0.8) -> list[str]:
    """The 'outer fringe' — skills whose prerequisites are (mostly) mastered but
    which are not yet mastered themselves: the ideal next things to probe."""
```

`fringe()` is the KST-driven learning-path selector: it names the skills at the edge of the child's current knowledge state.

### 4.6 `cat.py` — item selection + stopping rule

```python
def select_next_probe(
    vector: dict[str, float],
    theta: dict[str, float],              # per-skill ability estimates
    grade_band: str,
    calibration: bool,
) -> list[str]:
    """Return a ranked list of probe_ids to prefer next turn. Combines:
       - KST fringe() (which skills are learnable now)
       - maximum Fisher information (which probe most reduces uncertainty)
       - calibration widening (§8.3) when calibration=True."""

def should_stop_probing(vector: dict[str, float], skill_ids: list[str],
                        se_threshold: float = 0.15) -> bool:
    """Stopping rule: stop diagnostically pressing a skill once its posterior
    is confident (near 0 or 1) or its standard error < se_threshold. Bede then
    stops steering probes toward it and tutors normally."""
```

Note: `cat.py` does not *ask* questions — it produces **prompt hints** (a short ranked list of skills/probe archetypes) injected into the subject prompt so Bede naturally weaves them into Socratic dialogue (§8). This is "CAT expressed through prompting," per the brief.

### 4.7 `mastery.py` — Bayesian update + vector

```python
MasteryVector = dict[str, float]          # skill_id -> P(mastery) in [0,1]

@dataclass
class MasteryUpdate:
    skill_id: str
    prior: float
    posterior: float
    probe_id: str
    model_used: str
    observed_at: str                      # ISO8601

def new_vector(grade_band: str) -> MasteryVector:
    """Cold-start: prior 0.5 for on-band skills, lower for above-band."""

def bayesian_update(
    vector: MasteryVector,
    observation: EvidenceObservation,
    calibration_weight: float = 1.0,
    model: str = "dina",
) -> tuple[MasteryVector, list[MasteryUpdate]]:
    """1. Look up q_row(probe_id).
       2. cdm.update_attribute_posteriors() for those skills.
       3. Blend posterior into vector with calibration_weight (higher early).
       4. kst.propagate_prerequisites().
       Returns the new vector + a list of per-skill MasteryUpdate deltas
       (the ONLY thing that may optionally be persisted — §5)."""

def aggregate_for_parent(vector: MasteryVector) -> dict:
    """Roll sub-skill probs up to skill/domain averages + classify each as
    'secure' (>=0.8) / 'developing' (0.4-0.8) / 'gap' (<0.4); compute
    'next steps' from kst.fringe(). Render-only summary payload (§9/§10)."""
```

### 4.8 `__init__.py` façade

```python
async def process_evidence(
    db, student_name: str, probe_id: str, outcome: str,
    confidence: float, grade_band: str,
) -> None:
    """Load+decrypt vector -> bayesian_update -> encrypt+persist. All in-memory
    between load and store; the raw outcome is never written."""

def get_next_probe_hint(vector, theta, grade_band, calibration) -> str:
    """Human-readable one-liner for the subject prompt (§8)."""
```

**Dependency rule:** if `numpy` is not already a bede dependency (**[to verify]** — it is not imported by any current `services/*.py`), the entire package is implemented with the standard library `math` module only. Matrices are `list[list[float]]`; the DINA update is a handful of scalar operations per probe, so this is cheap and keeps the "no new runtime dependency / no copyleft" rule intact.

---

## 5. Data Models — new encrypted SQLAlchemy ORM

New models added to `homeschool-api/core/database.py`, mirroring the **exact** pattern of `NarrationAssessment` / `LearnerProfile` (verified: `Base` / `Mapped` / `mapped_column`, `LargeBinary` for every `_enc` column, `String(100)` PK on `student_name`, timezone-aware `DateTime`). They are created idempotently by the existing `create_tables()` (`Base.metadata.create_all`) — no migration tooling needed, matching current practice.

### 5.1 `MasteryProfile` (one row per student — the vector)

```python
class MasteryProfile(Base):
    """Per-student CDM mastery vector for the K-8 math skill map.
    profile_enc holds encrypt_json({skill_id: prob, ...}) plus metadata
    (grade_band, calibration_count, updated skills). Never any transcript."""
    __tablename__ = "mastery_profiles"

    student_name: Mapped[str] = mapped_column(String(100), primary_key=True)
    subject_area: Mapped[str] = mapped_column(String(30), primary_key=True, default="mathematics")
    evidence_count: Mapped[int] = mapped_column(nullable=False, default=0)
    profile_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)   # AES-256-GCM
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
```

Composite PK `(student_name, subject_area)` future-proofs the same table for reading/ELA/science vectors (§13) without schema change.

### 5.2 `SkillMastery` — optional denormalized per-skill rows (design decision below)

**Decision: do NOT ship `SkillMastery` as a separate table in Phase 1.** The full vector already lives in `MasteryProfile.profile_enc` as one encrypted JSON object; splitting it into one row per skill would (a) multiply encrypted-blob overhead, (b) create a plaintext `skill_id` column that leaks *which* skills are tracked, and (c) add nothing the parent view needs that `aggregate_for_parent()` can't compute on read. If a future feature needs per-skill history/time-series, add it then as `SkillMasteryHistory` with encrypted value + plaintext skill_id justified explicitly. This is called out because the brief listed `SkillMastery` as a candidate — we're consciously folding it into the encrypted vector instead.

### 5.3 `DiagnosticEvidenceLog` — **argue for NOT persisting raw evidence**

The brief allows either "store only skill_id + inferred probability contribution + timestamp + model used" **or** "argue for not persisting evidence at all."

**Decision: persist a minimal, transcript-free evidence *delta* log, opt-in and off by default.**

Rationale:
- **Not persisting anything** loses the parent's ability to see *why* a mastery estimate moved (auditability of the AI's inferences — a genuine parent-trust concern for an AI tutor).
- **Persisting transcripts** violates P3 outright and is forbidden.
- The middle path — logging only `MasteryUpdate` deltas (skill_id, prior→posterior, probe_id, model_used, timestamp) — carries **no child utterance, no probe text, no rubric free-text**. It is the same privacy class as the existing `NarrationAssessment` (which already stores derived scores, not transcripts).

```python
class DiagnosticEvidenceLog(Base):
    """One row per mastery update. Contains ONLY derived deltas — never a
    transcript, never the child's words, never probe prose. delta_enc holds
    encrypt_json([{skill_id, prior, posterior, probe_id, model_used}, ...])."""
    __tablename__ = "diagnostic_evidence_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    student_name: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    subject_area: Mapped[str] = mapped_column(String(30), nullable=False, default="mathematics")
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc), index=True, nullable=False,
    )
    delta_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)   # AES-256-GCM
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc), nullable=False,
    )
```

A config flag (`settings.diagnostic_evidence_log_enabled`, default `False` **[to verify: add to core/config.py]**) governs whether this table is written at all; when off, only `MasteryProfile` is updated and the deltas are discarded — the strictest reading of P3.

### 5.4 How they fit alongside `StudentConfig`

`StudentConfig` (verified: `String(100)` PK `student_name`, `config_enc` BYTEA) is the per-student config keyed by name. `MasteryProfile` keys on the *same* `student_name` string (no FK — the codebase uses none; single-family app, `student_name` is the natural key everywhere: `VoiceProfile`, `NarrationAssessment`, `LearnerProfile`, `SessionTranscript` all do this). The diagnostic tables sit as peers, exactly like `NarrationAssessment`/`LearnerProfile` do today.

---

## 6. Pydantic Schemas — additions to `models/schemas.py`

Mirrors the existing `NarrationAssessmentData` / `LearnerProfileData` block at the end of `schemas.py`.

```python
# ── Diagnostic engine (mastery profile) ──────────────────────────────────────

class MasteryLevel(str, Enum):
    gap        = "gap"          # P(mastery) < 0.4
    developing = "developing"   # 0.4 <= P < 0.8
    secure     = "secure"       # P >= 0.8

class SkillMasteryView(BaseModel):
    """One sub-skill's rolled-up view for the parent dashboard."""
    skill_id:     str
    label:        str
    domain:       str
    skill:        str
    grade_band:   str
    probability:  float = Field(..., ge=0.0, le=1.0)
    level:        MasteryLevel

class DomainMasteryView(BaseModel):
    domain:            str
    average_probability: float = Field(..., ge=0.0, le=1.0)
    level:             MasteryLevel
    skills:            List[SkillMasteryView]

class MasteryProfileSummary(BaseModel):
    """Render-only parent summary. No raw evidence, no transcript."""
    student_name:   str
    subject_area:   str = "mathematics"
    evidence_count: int
    calibration:    bool                       # still in cold-start widening phase
    domains:        List[DomainMasteryView]
    gaps:           List[SkillMasteryView]     # level == gap, worst first
    next_steps:     List[SkillMasteryView]     # KST fringe — learnable now
    updated_at:     str

class RecordSkillEvidenceInput(BaseModel):
    """Server-side validation of the silent tool's input (§7). Never leaves
    the server; not part of any response body."""
    probe_id:   str = Field(..., max_length=80)
    outcome:    Literal["correct", "partial", "incorrect", "hint_dependent"]
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
```

No changes to `Subject`, `SessionConfig`, or `TutorRequest` are required — the diagnostic tool operates on the existing `session_config.student_name` + `current_subject` already threaded through `stream_tutor_response`.

---

## 7. New Silent Agentic Tool — `record_skill_evidence`

### 7.1 Design (mirrors `assess_narration`, but *stricter* on silence)

`assess_narration` today emits a minimal `{'type':'assessment', 'data': summary}` SSE event which the child UI ignores (`SocraticChat.tsx:122`). The brief requires the diagnostic tool be **silent — never emitted to the child's client as structured data**. We therefore make `record_skill_evidence` emit **nothing at all** to the stream (returns `(None, None)` from the dispatcher), which is even stricter than `assess_narration` and requires no frontend change.

Tool definition, appended to `TUTOR_TOOLS` in `services/ai_service.py`:

```python
{
    "name": "record_skill_evidence",
    "description": (
        "SILENTLY record diagnostic evidence about a specific MATH sub-skill after a "
        "reasoning exchange reveals how well the child understands it. The child never "
        "sees this. Call it when a Socratic exchange has genuinely surfaced the child's "
        "grasp (or gap) on one of the math skills listed in this subject's context — not "
        "after every turn, only when you have real signal. Choose probe_id ONLY from the "
        "list provided in the subject context; never invent one."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "probe_id": {"type": "string",
                "description": "The exact probe archetype id from this subject's context list"},
            "outcome": {"type": "string",
                "enum": ["correct", "partial", "incorrect", "hint_dependent"],
                "description": "How the child performed: correct=solid unaided, partial=some grasp, "
                               "incorrect=misconception, hint_dependent=only after heavy scaffolding"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1,
                "description": "Your certainty this exchange was genuinely diagnostic (default 1.0)"},
        },
        "required": ["probe_id", "outcome"],
    },
}
```

### 7.2 Hooking into the streaming state machine

The tool-call plumbing is already provider-agnostic and centralized in `_dispatch_completed_tool_call(tool_name, tool_input, db, config, subject) -> (chunk, ends_on_questionless)` (verified: shared by both the Anthropic path `_stream_tutor_events` and the OpenAI path `_stream_tutor_events_openai`). We add one branch, modeled on the `assess_narration` branch:

```python
# inside _dispatch_completed_tool_call, alongside the assess_narration branch
if tool_name == "record_skill_evidence":
    # Server-side, fully silent. No SSE chunk to the child. Second value None
    # so it leaves ends_on_questionless_tool untouched (same convention the
    # assess_narration / show_visual_aid branches already use).
    await _record_skill_evidence(db, config, subject, tool_input)
    return None, None
```

New helper next to `_save_assessment` (which it structurally mirrors — `db is None` guard for the demo role, try/except that logs and swallows so a diagnostic failure never breaks the child's stream):

```python
async def _record_skill_evidence(db, config, subject, tool_input) -> None:
    if db is None:                       # demo role passes db=None (verified, tutor.py:92)
        return
    if subject != Subject.mathematics:   # Phase 1 scope: math only
        return
    try:
        from models.schemas import RecordSkillEvidenceInput
        from services.diagnostic import process_evidence
        ev = RecordSkillEvidenceInput(**tool_input)     # validate/clamp
        await process_evidence(
            db, config.student_name, ev.probe_id, ev.outcome,
            ev.confidence, config.grade_stage.value,
        )
    except Exception as exc:
        log.warning("Skill-evidence record failed for %s: %s", config.student_name, exc)
```

Because it returns `None, None`, the `content_block_stop` handler in `_stream_tutor_events` (verified lines 1033–1047) yields no chunk and leaves `ends_on_questionless_tool` alone — identical to how `assess_narration`/`show_visual_aid` behave. The child stream is byte-for-byte unchanged. The OpenAI path routes through the same dispatcher, so it's covered for free.

### 7.3 Why not overload `assess_narration`

Kept separate deliberately (same reasoning bede applies to `stream_sandbox_response` vs `stream_tutor_response`): `assess_narration` scores *narration quality* across all subjects and *does* emit a (child-ignored) event; `record_skill_evidence` records *math skill outcomes*, must be *fully* silent, and feeds a different persistence path. Conflating them would risk math-diagnostic logic leaking into every narration and vice-versa.

---

## 8. Prompt Changes

Bede's system prompt is two cached blocks (verified in `_stream_tutor_events`, lines 886–902): static block `_build_static_prompt(config)` with `cache_control: ephemeral`, subject block `_build_subject_prompt(config, subject)` sent fresh, and the tools block cached on its last element (`TUTOR_TOOLS[-1]` gets `cache_control`).

### 8.1 Static block additions (`_build_static_prompt`)

Add a new XML-tagged section (consistent with the existing `<tools_guidance>` / `<ai_literacy_guardrails>` structure), describing *how* to diagnose — subject-agnostic, so it stays in the cached static block:

```
<diagnostic_guidance>
As you tutor, you quietly notice how well {student_name} grasps specific skills. When a
Socratic exchange genuinely reveals their understanding of a math skill — not a guess, real
signal — call `record_skill_evidence` with the matching probe_id from the subject context and
an honest outcome. This is silent; {student_name} never sees it and it never interrupts the
lesson. Never turn the conversation into a test to generate evidence: evidence is a by-product
of good Socratic dialogue, never its goal. Probe a skill at most as often as natural
conversation warrants, and prefer skills the subject context flags as "still needs evidence"
or "next up."
</diagnostic_guidance>
```

**Cache safety:** this text depends only on `config.student_name` (already in the static block) — it does **not** vary per turn, so the static block stays cacheable exactly as today. Per-turn mastery state goes in the *subject* block (§8.2), which is already sent fresh.

### 8.2 Subject block additions (`_build_subject_prompt`) — math only

`_build_subject_prompt` currently composes `_SUBJECT_CONTEXT[subject]` + sanitized parent notes + catalog/visual-aid/session-position notes (verified lines 691–704). We add a **diagnostic context note**, only when `subject == Subject.mathematics`, built from the live mastery vector:

```python
def _diagnostic_context(config, subject, db) -> str:
    if subject != Subject.mathematics:
        return ""
    # Load+decrypt the vector, compute the CAT/KST hint. Falls back to "" on any
    # failure so a missing profile never breaks a math lesson.
    ...
    return (
        "\n\nMATH SKILL DIAGNOSTIC (silent — for your own probing choices only):"
        "\nProbe archetypes available (use exact ids with record_skill_evidence):"
        "\n- probe.frac_add_reasoning — adding unlike fractions"
        "\n- probe.long_div_steps — long division steps"
        "  ...(the grade-band-relevant subset)..."
        "\nStill needs evidence / next up (weave these in naturally): "
        "fr.add_subtract_fractions, nbt.long_division"
        "\nAlready secure (no need to keep probing): oa.multiplication_facts"
    )
```

This is `cat.select_next_probe()` + `kst.fringe()` output rendered as prose — the adaptive/CAT selection expressed through prompting, exactly as the brief requires. It's injected into the **non-cached** subject block, so it can change every turn without breaking the static-block cache.

> **Integration point (verified):** `_build_subject_prompt(config, subject)` is called synchronously inside `_stream_tutor_events` while building `system`. To inject *live* per-turn state we either (a) pass the loaded vector into `_build_subject_prompt` (add a param, load the vector once in `stream_tutor_response` before building `system`), or (b) load it inside a small async pre-step. Recommended: load the decrypted vector in `stream_tutor_response` (which already has `db`) and thread it into `_build_subject_prompt` as an optional arg — keeps the DB read off the hot per-delta path and out of the sync prompt builder. **[implementation detail for scaffolding PR]**

### 8.3 Calibration-phase behavior

`MasteryProfile.evidence_count` tracks how much evidence exists. While `evidence_count < CALIBRATION_THRESHOLD` (e.g. per-skill first N=3 observations, **[to verify final N]**):

- `mastery.bayesian_update` applies a **higher `calibration_weight`** (early evidence moves the posterior more — faster cold-start convergence).
- `cat.select_next_probe(..., calibration=True)` **widens** the probe spread: instead of drilling the single highest-information skill, it returns a broader slate across the grade band, so Bede surfaces a wider variety of skills in early sessions.
- The subject-prompt note appends: *"You are still getting to know how {student_name} thinks about math — let your questions roam a little more widely across topics than usual, still as natural conversation, never a test."*

Crucially this stays **woven into Socratic tutoring** — it changes *which* skills Bede gravitates toward, never the format. No separate calibration test.

---

## 9. New Backend Router — `routers/diagnostic.py`

Modeled directly on `routers/narration.py` (verified: `require_parent` dependency, `select().where(student_name==...)`, `decrypt_json(row.*_enc)`, 404 when absent). Registered in `main.py` via `app.include_router(diagnostic.router)` alongside the others.

```python
router = APIRouter(prefix="/diagnostic", tags=["diagnostic"])

@router.get("/{student_name}/summary")
async def get_mastery_summary(
    student_name: str,
    subject_area: str = Query(default="mathematics"),
    _: dict = Depends(require_parent),          # PARENT ONLY (P1, P5)
    db: AsyncSession = Depends(get_db),
) -> MasteryProfileSummary:
    """Render-only parent view: rolled-up domain/skill mastery, gaps, next steps.
    No raw evidence, no transcript, no downloadable artifact."""
    row = (await db.execute(
        select(MasteryProfile).where(
            MasteryProfile.student_name == student_name,
            MasteryProfile.subject_area == subject_area,
        )
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "No mastery profile yet — complete some math sessions to build one.")
    vector = decrypt_json(row.profile_enc)
    return aggregate_for_parent_summary(student_name, subject_area, vector, row.evidence_count)
```

**No POST/PUT/DELETE, no `/export`, `/download`, `/print`.** The profile is built *only* as a side effect of tutoring (the silent tool), never via a client-triggered endpoint — so there is nothing to export and no write surface to abuse. Optionally a second **render-only** GET for detail (`GET /diagnostic/{student}/skills`) returning `List[SkillMasteryView]` — same gating, still no export.

### 9.1 ExfiltrationGuard compatibility (verified)

`ExfiltrationGuard.dispatch` (verified `core/middleware.py`) does three relevant things:
1. **Blocks path substrings** `/export /download /dump /backup /debug`. Our paths (`/diagnostic/{name}/summary`, `/skills`) contain none. ✅
2. **2 MB response cap.** A mastery summary is a few KB of JSON. ✅
3. **Scans JSON bodies** for `"embedding":[`, `"data_key"`, `"device_salt"`, and the `SAGE` magic. Our `MasteryProfileSummary` uses keys `probability`, `level`, `skill_id`, `domain`, etc. — **none of the blocked tokens**. ⚠️ **Design rule:** never name a field `embedding`, `data_key`, or `device_salt`, and never echo raw ciphertext. The summary is fully decrypted, plain floats/strings — safe. ✅

Because these are plain buffered JSON responses (not `text/event-stream`), they go through the normal buffer-and-scan path and also get `content-disposition: inline` forced — reinforcing "render-only, no attachment download."

---

## 10. Frontend — parent-only render-only Mastery Dashboard

The child UI shows **nothing** (the tool emits no SSE event; `SocraticChat.tsx` needs no change). Everything is on the parent side.

### 10.1 `types/index.ts` additions

```ts
export type MasteryLevel = 'gap' | 'developing' | 'secure'

export interface SkillMasteryView {
  skill_id: string; label: string; domain: string; skill: string
  grade_band: string; probability: number; level: MasteryLevel
}
export interface DomainMasteryView {
  domain: string; average_probability: number; level: MasteryLevel
  skills: SkillMasteryView[]
}
export interface MasteryProfileSummary {
  student_name: string; subject_area: string; evidence_count: number
  calibration: boolean; domains: DomainMasteryView[]
  gaps: SkillMasteryView[]; next_steps: SkillMasteryView[]; updated_at: string
}
```

### 10.2 `services/api.ts` addition (mirrors `fetchLearnerProfile`)

```ts
export async function fetchMasterySummary(
  token: string, studentName: string, subjectArea = 'mathematics'
): Promise<MasteryProfileSummary | null> {
  const res = await fetch(
    `${BASE}/diagnostic/${encodeURIComponent(studentName)}/summary?subject_area=${subjectArea}`,
    { headers: { Authorization: `Bearer ${token}` } })
  if (res.status === 404) return null
  if (!res.ok) throw new Error(`Failed to load mastery profile for ${studentName}`)
  return res.json()
}
```

### 10.3 `pages/MasteryDashboard.tsx` (new, render-only)

A read-only page structured like the existing `pages/Progress.tsx` (verified: reads `useSessionStore` token, fetches via api.ts, renders cards, no download controls). It renders:
- Per-domain progress bars (probability → colored bar, `level` badge reusing the emerald/amber/red badge style already in `Progress.tsx`).
- A **"Gaps"** list (skills at `level==='gap'`).
- A **"Next steps"** list (KST fringe).
- A **calibration banner** when `calibration===true` ("Bede is still getting to know how {name} thinks about math — early estimates").
- **No** print/export/download button anywhere (P4).

### 10.4 `App.tsx` wiring (mirrors the `/progress` route, verified present)

```tsx
import MasteryDashboard from './pages/MasteryDashboard'
// ...
<Route path="/mastery" element={
  <RequireAuth allowedRole="parent"><MasteryDashboard /></RequireAuth>
} />
```

`RequireAuth allowedRole="parent"` (verified pattern) enforces P1/P5 client-side; the server's `require_parent` is the real gate.

---

## 11. Security & Privacy — constraint → control mapping

| Constraint | Exact bede control satisfying it (verified) |
|-----------|---------------------------------------------|
| **P1** Parent-confidential, never shown to child | Silent tool returns `(None,None)` → no SSE event reaches `SocraticChat.tsx`; `GET` endpoints use `Depends(require_parent)` (`core/deps.py:145`); route guard `RequireAuth allowedRole="parent"` (`App.tsx`) |
| **P2** Derived probs as AES-256-GCM BYTEA | `MasteryProfile.profile_enc: LargeBinary` via `core.encryption.encrypt_json`; same DATA_KEY (MASTER_SECRET→PBKDF2/KEK→DATA_KEY) hierarchy in `core/encryption.py` — no new key material |
| **P3** Never persist raw transcripts | `_record_skill_evidence` receives only a `{probe_id, outcome, confidence}` tuple; `process_evidence` persists only the resulting probability vector (+ optional `MasteryUpdate` deltas). No child utterance is ever passed to the diagnostic package. Evidence-delta log itself is off by default (§5.3) |
| **P4** Render-only, no download/export/print | No write/export endpoint exists; `ExfiltrationGuard` blocks `/export /download /dump /backup /debug`, caps 2 MB, forces `content-disposition: inline` (`core/middleware.py`); no download button in `MasteryDashboard.tsx` |
| **P5** All endpoints behind `require_parent` (JWT+IP/UA) | `require_parent` → `require_auth` → `_validate_token` verifies JWT signature/expiry + device fingerprint (`compute_fingerprint`, `validate_fingerprint`) |
| **P6** No new export/download endpoint | Router exposes only `GET .../summary` (+ optional `.../skills`); both render-only JSON |
| Demo isolation | `chat()` sets `db=None` for the demo role (`routers/tutor.py:92`); `_record_skill_evidence` short-circuits on `db is None` — demo visitors never write a mastery profile |
| Prompt-injection of probe ids | `probe_id` validated against `Q_MATRIX` keys server-side (`RecordSkillEvidenceInput` + `q_row` lookup); an invented id resolves to nothing and is dropped — same defense pattern as `_lookup_visual_aid` (`ai_service.py:737`) |
| Parent free-text safety | Existing `_sanitize_parent_field` / `_INJECTION_PATTERN` already strip injection from parent notes before they reach the prompt; the diagnostic subject-note text is machine-generated from the vector, not free text |
| Audit trail | Reuse `core.audit.log_event` for a new `AuditEvent.DIAGNOSTIC_VIEW` on summary reads **[to verify: add enum member]**, matching how `narration`/`tutor` routes audit access |

---

## 12. File-by-File Change List

### New files

| File | Purpose |
|------|---------|
| `homeschool-api/services/diagnostic/__init__.py` | Façade: `process_evidence`, `get_next_probe_hint` |
| `homeschool-api/services/diagnostic/skill_map.py` | K-8 math DAG data + lookups |
| `homeschool-api/services/diagnostic/qmatrix.py` | Probe archetypes, Q-rows, `EvidenceObservation` |
| `homeschool-api/services/diagnostic/irt.py` | 1PL/2PL/3PL, Fisher info, theta estimation |
| `homeschool-api/services/diagnostic/cdm.py` | DINA/DINO/G-DINA posteriors |
| `homeschool-api/services/diagnostic/kst.py` | Surmise closure, knowledge states, fringe |
| `homeschool-api/services/diagnostic/cat.py` | Probe selection (max Fisher info) + stopping rule |
| `homeschool-api/services/diagnostic/mastery.py` | `MasteryVector`, `bayesian_update`, `aggregate_for_parent` |
| `homeschool-api/routers/diagnostic.py` | `GET /diagnostic/{student}/summary` (parent, render-only) |
| `homeschool-tutor/src/pages/MasteryDashboard.tsx` | Parent render-only dashboard |

### Modified files

| File | Change |
|------|--------|
| `homeschool-api/core/database.py` | Add `MasteryProfile` (+ optional `DiagnosticEvidenceLog`) ORM models |
| `homeschool-api/models/schemas.py` | Add `MasteryLevel`, `SkillMasteryView`, `DomainMasteryView`, `MasteryProfileSummary`, `RecordSkillEvidenceInput` |
| `homeschool-api/services/ai_service.py` | Append `record_skill_evidence` to `TUTOR_TOOLS`; add `_record_skill_evidence`; add branch in `_dispatch_completed_tool_call`; add `<diagnostic_guidance>` to `_build_static_prompt`; add math diagnostic note to `_build_subject_prompt` (thread decrypted vector through) |
| `homeschool-api/main.py` | `app.include_router(diagnostic.router)` |
| `homeschool-api/core/config.py` | Add `diagnostic_evidence_log_enabled: bool = False` **[to verify]** |
| `homeschool-api/core/audit.py` | Add `AuditEvent.DIAGNOSTIC_VIEW` **[to verify]** |
| `homeschool-tutor/src/types/index.ts` | Add mastery view types |
| `homeschool-tutor/src/services/api.ts` | Add `fetchMasterySummary` |
| `homeschool-tutor/src/App.tsx` | Add `/mastery` parent route |
| `homeschool-tutor/src/pages/PodDashboard.tsx` (or `Progress.tsx`) | Add a "Math Mastery" link/tab to reach the dashboard **[to verify best host page]** |

### Explicitly unchanged

- `SocraticChat.tsx` — the tool emits no event; the child stream is untouched.
- `ExfiltrationGuard` / `middleware.py` — no new filtering needed; the design fits the existing guard.
- Encryption hierarchy — reused as-is, no new keys.

---

## 13. Extensibility — reading/ELA, science later

The engine is subject-generic below the skill map. Adding a domain later:

1. **New skill-map module** — `services/diagnostic/skill_map_ela.py` (or a `subject_area`-keyed registry inside `skill_map.py`). Add its Q-matrix rows to `qmatrix.py`.
2. **No new ORM** — `MasteryProfile` composite PK `(student_name, subject_area)` already stores multiple vectors per child; `subject_area="reading"` is a new row, not a new table.
3. **Tool** — either broaden `record_skill_evidence` to accept a `subject_area` (defaulting from `current_subject`) or add a sibling tool; the dispatcher branch is one line either way.
4. **Prompt** — extend the `subject != Subject.mathematics` guard in `_build_subject_prompt`/`_record_skill_evidence` to the new subject; add its probe list to the subject context.
5. **Frontend** — `MasteryDashboard.tsx` already takes `subject_area`; add a subject switcher.
6. **CDM reuse** — DINA/DINO/G-DINA and KST are subject-agnostic; only the skill map + Q-matrix data change. Reading might favor DINO (disjunctive — multiple sub-skills can each satisfy a comprehension item); the `model` param already supports this.

This mirrors bede's documented "Adding a New Subject" flow (CLAUDE.md) — data-driven, not logic-driven.

---

## 14. Open-Standards Appendix

Standards implemented from scratch (proprietary implementation of open, published algorithms):

- **Q-matrix** — Tatsuoka, K. K. (1983). *Rule space: an approach for dealing with misconceptions based on item response theory.* Journal of Educational Measurement, 20(4). The binary item×attribute incidence matrix.
- **Item Response Theory (IRT)**
  - **1PL / Rasch** — Rasch, G. (1960). *Probabilistic Models for Some Intelligence and Attainment Tests.*
  - **2PL** — Birnbaum, A. (1968), in Lord & Novick, *Statistical Theories of Mental Test Scores.*
  - **3PL** — Birnbaum (1968); guessing parameter `c`.
  - **Fisher information & MLE/EAP ability estimation** — Lord, F. M. (1980). *Applications of Item Response Theory to Practical Testing Problems.*
- **Cognitive Diagnostic Models (CDM)**
  - **DINA** (Deterministic Inputs, Noisy "And") — Junker, B. W. & Sijtsma, K. (2001). *Cognitive assessment models with few assumptions…* Applied Psychological Measurement, 25(3); de la Torre, J. (2009).
  - **DINO** (Deterministic Inputs, Noisy "Or") — Templin, J. & Henson, R. (2006). *Measurement of psychological disorders using cognitive diagnosis models.* Psychological Methods, 11(3).
  - **G-DINA** (Generalized DINA) — de la Torre, J. (2011). *The generalized DINA model framework.* Psychometrika, 76(2).
- **Knowledge Space Theory (KST) / surmise relations** — Doignon, J.-P. & Falmagne, J.-C. (1985). *Spaces for the assessment of knowledge.* International Journal of Man-Machine Studies, 23; and Falmagne & Doignon (2011), *Learning Spaces.* (Basis for the surmise relation, knowledge states, inner/outer fringe.)
- **Computerized Adaptive Testing (CAT)**
  - **Maximum Fisher Information item selection** — Lord (1980); van der Linden, W. J. & Glas, C. A. W. (2000). *Computerized Adaptive Testing: Theory and Practice.*
  - **Cognitive-diagnostic CAT (CD-CAT) selection** — Cheng, Y. (2009). *When cognitive diagnosis meets CAT: The modified maximum global discrimination index method.* Psychometrika, 74(4).
  - **Stopping rules** — standard error / posterior-confidence threshold (van der Linden & Glas, 2000).
- **Bayesian attribute updating** — standard posterior update `P(α|X) ∝ P(X|α)P(α)`, applied incrementally per observation.

All references are to published methods; no third-party code (EduCAT, mirt, CDM R package, mycaas, Concerto) is used or vendored.

---

## 15. Phased Implementation Roadmap (follow-up scaffolding PR)

**Phase 0 — Approval (this doc).** User reviews and signs off on skill map, model choices, and privacy posture.

**Phase 1 — Core package + data (no wiring).**
- `services/diagnostic/skill_map.py` (full K-8 math DAG), `qmatrix.py` (probe archetypes).
- `irt.py`, `cdm.py` (DINA first), `kst.py`, `cat.py`, `mastery.py`.
- Pure-Python, unit-tested in isolation (no DB, no LLM). Deliverable: `pytest` proving a synthetic evidence stream converges the vector sensibly and respects prerequisites.

**Phase 2 — Persistence.**
- `MasteryProfile` ORM (+ config-gated `DiagnosticEvidenceLog`), `create_tables()` picks them up.
- `process_evidence` load→update→encrypt→store round-trip test.
- Pydantic schemas in `schemas.py`.

**Phase 3 — Loop integration.**
- Append `record_skill_evidence` to `TUTOR_TOOLS`; add `_record_skill_evidence` + dispatcher branch (verify child SSE stream unchanged, demo role writes nothing).
- Static-block `<diagnostic_guidance>` + math subject-note injection (thread decrypted vector into `_build_subject_prompt`).
- Calibration weighting + widening.

**Phase 4 — Parent surface.**
- `routers/diagnostic.py` (`GET .../summary`), registered in `main.py`; confirm `ExfiltrationGuard` passes.
- `MasteryDashboard.tsx`, `types`, `api.ts`, `/mastery` route; render-only, no export.

**Phase 5 — Validation & tuning.**
- End-to-end: run real math tutoring sessions, confirm evidence flows and the vector moves; parent view renders; child sees nothing.
- Tune slip/guess, calibration N, mastery thresholds. Optionally enable DINO/G-DINA.

**Per the repo's Standing Workflow (CLAUDE.md):** each phase's fix/feature is verified with a real check (unit tests for the pure core; an actual math session for loop integration) before its PR is opened, and merged once confirmed.

---

### Appendix A — Verified source anchors

**Note (added post-design, see DIAGNOSTIC_BUILD_PROGRESS.md decisions log):** the line numbers below were accurate at design time but have since drifted due to unrelated same-day edits to `ai_service.py`/`core/database.py` (the previous-lesson-context and learner-profile-history work). Function/class names and the overall architecture remain accurate; re-verify exact line numbers before any Phase 3 unit relies on them.

- Silent tool pattern & dispatcher: `services/ai_service.py` — `assess_narration` (lines 190–243), `_dispatch_completed_tool_call` (924–963), `_save_assessment` (764–812), `_stream_tutor_events` `content_block_stop` (1033–1052).
- Two-block cached prompt: `_stream_tutor_events` (886–902); `_build_static_prompt` (523–593); `_build_subject_prompt` (691–704).
- Prompt-injection defense: `_sanitize_parent_field` / `_INJECTION_PATTERN` (375–397).
- Encryption: `core/encryption.py` — `encrypt_json`/`decrypt_json` (164–171), DATA_KEY hierarchy header (1–14).
- ORM patterns: `core/database.py` — `NarrationAssessment` (121–139), `LearnerProfile` (142–154), `create_tables` (223–226).
- Auth gating: `core/deps.py` — `require_parent` (145–158), `require_auth`/`_validate_token` (24–92).
- ExfiltrationGuard: `core/middleware.py` — blocked endpoints/patterns (49–60), SSE pass-through (84–87), 2 MB cap & scan (89–128).
- Router registration: `main.py` (74–84). Parent router precedent: `routers/narration.py` (whole file).
- SSE child consumer ignoring silent events: `homeschool-tutor/src/components/SocraticChat.tsx:122–123`.
- Frontend precedents: `App.tsx` `/progress` route (83–90), `services/api.ts` `fetchLearnerProfile` (422–432), `pages/Progress.tsx`.
- Grade bands: `models/schemas.py::GradeStage` (7–11), `grade_to_stage` (18–31); timer split `utils/gradeTimer.ts::getTimerConfig` (38–44).
- Demo `db=None`: `routers/tutor.py::chat` (92).
