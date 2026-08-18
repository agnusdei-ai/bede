"""
The mastery vector itself — cold-start initialization, the Bayesian
update loop, and the parent-facing rollup — realizes runtime-loop step
S7 (see docs/diagnostic/DIAGNOSTIC_LOOP.md). Pure stdlib, no numpy, per
docs/diagnostic/DIAGNOSTIC_BUILD_LOOP.md's Phase 1 hard rules.

This is where cdm.py (unit 1.4) and kst.py (unit 1.5) compose: one
observation's CDM posterior gets blended into the vector, then
kst.propagate_prerequisites enforces the surmise relation so a
confidently-mastered skill's prerequisites are never left behind. This
module is also Phase 1's acceptance unit — its own real check is a
synthetic evidence stream proving the whole pipeline converges sensibly
and never produces a vector where a mastered skill's prerequisites lag
behind (see tests/diagnostic/test_mastery.py).
"""

from dataclasses import dataclass
from datetime import datetime, timezone

from services.diagnostic.cdm import CdmParams, update_attribute_posteriors
from services.diagnostic.kst import fringe, propagate_prerequisites
from services.diagnostic.qmatrix import EvidenceObservation, q_row
from services.diagnostic.skill_map import GradeBand, all_skill_ids, get_skill

MasteryVector = dict[str, float]

_MASTERY_LEVELS = (
    ("secure", 0.8),
    ("developing", 0.4),
    ("gap", 0.0),
)

_BAND_ORDER = (GradeBand.K_2, GradeBand.THREE_5, GradeBand.SIX_8)
_BAND_INDEX = {band.value: index for index, band in enumerate(_BAND_ORDER)}

# Per-subject evidence-point count (MasteryProfile.evidence_count's own
# scalar, not a per-skill count — see DIAGNOSTIC_BUILD_PROGRESS.md's unit
# 2.2 review) below which a student is still "calibrating".
#
# MEASURED AND DELIBERATELY LEFT AT 5. The map grew from 42 skills to 95,
# which made it fair to ask whether a threshold set against the smaller map
# still held. It does, and the measurement said something more useful than
# a new number: the threshold is a second-order knob here. Swept 3 → 20
# against the DINA simulator (band 6-8, one sitting), a struggling child's
# false-secure rate moves 1.7% → 3.8% and accuracy 92.2% → 90.0%, while
# coverage rises 30% → 42%. A higher threshold buys coverage and pays for
# it in exactly the error that hurts most, so there is no free move; 5 sits
# near the knee.
#
# For contrast, the cold-start PRIORS — fixed in the same pass, see
# new_vector below — moved that same false-secure rate 13.1% → 1.9%. The
# threshold was never where the problem was, and changing it for the sake
# of having changed something would have been noise dressed as tuning.
#
# Coincidentally the same value as services/diagnostic_demo.py's own,
# separately-declared CALIBRATION_THRESHOLD, but the two are not coupled.
CALIBRATION_THRESHOLD = 5

# ── Phase 5.2 tuning (see docs/diagnostic/DIAGNOSTIC_ENGINE_DESIGN.md §15,
# and tests/diagnostic/test_convergence.py, which is the measurement) ────────
#
# The response-model parameters the engine assumes about a child. Before this
# they were `CdmParams`' own defaults (slip 0.10 / guess 0.20) and — the real
# defect — `bayesian_update` never passed `params` at all, so the two values
# Phase 5 exists to tune were not reachable from the code path that used them.
# Threading `params` through is what makes them tunable; this constant is what
# they were tuned TO.
#
# WHAT THE MEASUREMENT FOUND. Simulating students with a known true knowledge
# state (test_convergence.py) and scoring the engine's own verdicts against it
# surfaced a bias nobody had measured: accuracy is NOT uniform across children.
# The child who knows least gets the least accurate picture — the opposite of
# what a diagnostic is for.
#
#     student truly knows      false-secure @ guess 0.20    @ guess 0.25
#     15% of the map                    9.3%                    4.9%
#     50% of the map                    3.0%                    1.7%
#     85% of the map                    0.8%                    0.5%
#
# "False-secure" is the error that actually reaches a family: the parent is
# told their child is secure on a skill the child does not have. At 0.20 a
# struggling child drew that verdict on nearly one skill in ten.
#
# The cause is structural, not a bug. `guess` is P(correct | not mastered). A
# child who has mastered little produces far more not-mastered attempts, so
# understating `guess` mis-credits far more of them — the bias grows precisely
# as true mastery falls.
#
# WHY 0.25 AND NOT HIGHER. Raising `guess` trades coverage for caution: fewer
# skills get any verdict at all. 0.20→0.25 removes almost half the false-secure
# rate for ~10 points of coverage; every step past it buys much less (4.9% →
# 4.8% → 4.5% at 0.30/0.35) for the same steady coverage loss. 0.25 is the knee.
# Raising the "secure" cutoff instead was also measured and rejected: it cut
# more false-secures but cost twice the coverage, and in a world messier than
# the engine assumes it made overall accuracy WORSE for middle and advanced
# students (85.0% → 77.5%).
#
# `slip` is unchanged at 0.10. Nothing in the sweep argued for moving it, and
# it governs the opposite, far less costly error: understating a skill the
# child does have.
TUNED_PARAMS = CdmParams(slip=0.10, guess=0.25)

# How many "next steps" the parent-facing summary offers. kst.fringe can
# legitimately return a dozen or more candidates at once; a list that long
# is an inventory, not a priority. Matches composition.py's and
# language_exposure.py's own cap in spirit — theirs is 3, this is a little
# wider because math spans eight domains rather than one rubric.
_MAX_NEXT_STEPS = 5


def calibration_weight_for(evidence_count: int, threshold: int = CALIBRATION_THRESHOLD) -> float:
    """
    Linear decay from a doubled posterior push at evidence_count==0 down to
    a normal 1.0 blend once evidence_count reaches threshold — design doc
    §8.3: "higher calibration_weight... early evidence moves the posterior
    more — faster cold-start convergence." Never below 1.0 (bayesian_update
    itself clamps the result to [0,1] regardless, but this keeps the
    caller's own semantics: calibration only ever pushes harder than a
    normal update, never softer)."""
    if evidence_count >= threshold:
        return 1.0
    return 2.0 - (evidence_count / threshold)


@dataclass
class MasteryUpdate:
    skill_id: str
    prior: float
    posterior: float
    probe_id: str
    model_used: str
    observed_at: str


#: What a below-band skill is seeded at before anyone has asked the child
#: anything. It has to sit inside a genuinely narrow window, and BOTH edges
#: are load-bearing:
#:
#:   - strictly BELOW the secure cutoff (0.80, models/schemas.py's
#:     MasteryLevel), because a grade is not evidence and no skill may be
#:     reported Mastered until the child has shown something;
#:   - strictly ABOVE kst.fringe's `prereq_hi` (0.65), because that is the
#:     bar for "is the ground solid enough to build on". Drop under it and
#:     every unprobed earlier-band prerequisite BLOCKS its dependents, which
#:     is precisely the defect test_next_steps_band_leak.py exists for — a
#:     3-5 student whose entire "next steps" list was the two K-2 skills
#:     that happen to have no prerequisites at all.
#:
#: 0.70 sits in that window, and it was where the one-band-down prior always
#: was. The bug was never that value: it was the two-bands-down case, which
#: climbed to 0.90 and straight past secure. So this is flat across
#: distance rather than rising — "probably met this" does not become more
#: evidenced the further back the material goes, and the cap is about
#: evidence, not about plausibility.
UNEVIDENCED_BELOW_BAND_PRIOR = 0.70


def new_vector(grade_band: str) -> MasteryVector:
    """Cold-start vector. The only thing a grade licenses assuming is that
    the child has probably MET the earlier material — never that they have
    mastered it.

    WHAT THIS REPLACED, AND WHY IT WAS WRONG. Below-band skills used to seed
    at 0.5 + 0.2 per band of distance, reaching 0.9 — above the 0.80 secure
    cutoff. The consequence was measurable and bad: a brand-new 6-8 student's
    profile reported **24 of 95 skills as Mastered before Bede had asked a
    single question.** The software was asserting mastery from a birth date.

    That is the false-secure error, and it is the one that actually reaches a
    family: telling a parent their child is secure on something they cannot
    do sends the household PAST a gap, the next lesson builds on sand, and
    nobody knows why it collapsed. Understating costs review time; this costs
    a term. See test_convergence.py's own note on why the two are bounded
    asymmetrically.

    The change is narrower than it first looks, and deliberately so. The
    one-band-down prior (0.70) is unchanged — it was always correct, and
    kst.fringe depends on it clearing `prereq_hi`. What moved is the
    two-bands-down case, which climbed to 0.90; it is now the same 0.70. So
    only band 6-8 is affected at all, which is exactly the band that showed
    the damage, being the only one with two bands beneath it.

    A grade is also a weaker signal for the families this is built for than
    it would be in a school. Homeschooled children are routinely ahead in one
    area and behind in another; that asymmetry is frequently the reason the
    family homeschools at all.

    An unrecognized grade_band gets a flat 0.5 everywhere rather than raising
    — this only ever seeds a starting point, never a security-relevant
    decision, matching grade_to_stage()'s own degrade-gracefully convention
    in models/schemas.py.
    """
    student_index = _BAND_INDEX.get(grade_band)
    vector: MasteryVector = {}
    for skill_id in all_skill_ids():
        skill = get_skill(skill_id)
        if student_index is None or skill is None:
            vector[skill_id] = 0.5
            continue
        distance = _BAND_INDEX[skill.band.value] - student_index
        if distance == 0:
            # Their own band: genuine ignorance, and 0.5 says exactly that.
            vector[skill_id] = 0.5
        elif distance > 0:
            # Above their band: probably not reached yet.
            vector[skill_id] = max(0.1, 0.5 - 0.2 * distance)
        else:
            # Below their band: probably MET, not probably mastered — see
            # UNEVIDENCED_BELOW_BAND_PRIOR for why this single value has to
            # sit between kst's prereq_hi and the secure cutoff, and why it
            # does not rise with distance.
            vector[skill_id] = UNEVIDENCED_BELOW_BAND_PRIOR
    return vector


def ensure_complete(vector: MasteryVector, grade_band: str | None = None) -> MasteryVector:
    """
    Return a copy of `vector` with every skill in the current SKILL_MAP
    present, filling anything missing at its cold-start prior.

    THIS IS WHAT MAKES GROWING THE SKILL MAP SAFE. A MasteryProfile row
    holds `encrypt_json({skill_id: probability})` — a snapshot of whatever
    the map contained on the day it was last written. When skills are added
    (as the preparatory-school extension in skill_map.py did, taking the map
    from 42 to 95), every already-stored vector is missing the new ids.
    Nothing crashed on that: aggregate_for_parent, build_summary_view and
    kst.fringe all iterate the VECTOR rather than the map, so the new skills
    would simply have been invisible — never rolled up, never offered as a
    next step, never probed — for exactly those families who had been using
    Bede the longest. Silent, permanent, and impossible to notice from the
    UI. Backfilling on load closes that.

    An unknown or absent grade_band fills at a flat 0.5 rather than raising:
    get_mastery_summary is a render path that has no grade to hand (
    MasteryProfile stores no band, and this codebase has no ALTER TABLE
    path to add one — see core/database.py). A neutral prior there is
    honest, since it says only "we have no evidence about this yet", which
    is precisely true.

    Skills no longer in the map are dropped, so a retired id can't linger in
    a rollup forever.
    """
    complete = new_vector(grade_band) if grade_band is not None else {
        skill_id: 0.5 for skill_id in all_skill_ids()
    }
    for skill_id, probability in vector.items():
        if skill_id in complete:
            complete[skill_id] = probability
    return complete


def _classify(probability: float) -> str:
    for level, floor in _MASTERY_LEVELS:
        if probability >= floor:
            return level
    return "gap"


def classify_level(probability: float) -> str:
    """Public wrapper around _classify for other diagnostic-package modules
    (e.g. services.diagnostic.get_session_growth) that need the same
    secure/developing/gap thresholds this module already owns, without
    reaching into a private name across module boundaries."""
    return _classify(probability)


def bayesian_update(
    vector: MasteryVector,
    observation: EvidenceObservation,
    calibration_weight: float = 1.0,
    model: str = "dina",
    params: "CdmParams | None" = None,
) -> tuple[MasteryVector, list[MasteryUpdate]]:
    """
    One evidence-driven update cycle:
      1. Look up q_row(probe_id) — an unknown probe touches nothing.
      2. cdm.update_attribute_posteriors() for those skills.
      3. Blend each skill's CDM posterior into the vector, scaled by
         calibration_weight (1.0 = trust the CDM posterior as computed;
         >1.0, used during calibration mode per design doc §8.3, pushes
         further than one natural Bayesian step for faster cold-start
         convergence; results are clamped to [0,1] regardless).
      4. kst.propagate_prerequisites() over the blended vector, so a
         skill that crossed the "mastered" threshold this turn correctly
         raises its own prerequisites' floors immediately.

    Returns the new vector (input is not mutated) and one MasteryUpdate
    per skill actually touched, timestamped now in UTC ISO8601 — the
    only thing that may optionally be persisted (design doc §5.3), never
    the raw observation itself.
    """
    required_skills = q_row(observation["probe_id"])
    if not required_skills:
        return dict(vector), []

    cdm_posteriors = update_attribute_posteriors(
        vector, observation, model=model, params=params or TUNED_PARAMS,
    )

    updated = dict(vector)
    updates: list[MasteryUpdate] = []
    observed_at = datetime.now(timezone.utc).isoformat()

    for skill_id in required_skills:
        prior = vector.get(skill_id, 0.5)
        cdm_posterior = cdm_posteriors.get(skill_id, prior)
        blended = prior + calibration_weight * (cdm_posterior - prior)
        blended = max(0.0, min(1.0, blended))
        updated[skill_id] = blended
        updates.append(MasteryUpdate(
            skill_id=skill_id,
            prior=prior,
            posterior=blended,
            probe_id=observation["probe_id"],
            model_used=model,
            observed_at=observed_at,
        ))

    updated = propagate_prerequisites(updated)
    return updated, updates


def aggregate_for_parent(vector: MasteryVector) -> dict:
    """Render-only rollup for the parent dashboard (design doc §9/§10):
    per-domain average probability + level classification, a gaps list
    (level=='gap', worst first), and next_steps from kst.fringe(). No
    raw evidence, no per-skill history — just where things stand now."""
    domain_probabilities: dict[str, list[float]] = {}
    for skill_id, probability in vector.items():
        skill = get_skill(skill_id)
        if skill is None:
            continue
        domain_probabilities.setdefault(skill.domain, []).append(probability)

    domains = {
        domain: {
            "average_probability": sum(probabilities) / len(probabilities),
            "level": _classify(sum(probabilities) / len(probabilities)),
        }
        for domain, probabilities in domain_probabilities.items()
    }

    gaps = sorted(
        (skill_id for skill_id, probability in vector.items() if _classify(probability) == "gap"),
        key=lambda skill_id: vector[skill_id],
    )

    return {
        "domains": domains,
        "gaps": gaps,
        "next_steps": fringe(vector),
    }


def build_summary_view(
    vector: MasteryVector,
    student_name: str,
    subject_area: str,
    evidence_count: int,
    calibration_threshold: int,
    updated_at: str,
) -> dict:
    """
    Builds the full MasteryProfileSummary-shaped dict (matching
    models.schemas.MasteryProfileSummary field-for-field) from a raw
    vector. Both the demo's in-memory/session backend
    (services/diagnostic_demo.py's get_mastery_summary_demo) and the
    real, persistent backend (services/diagnostic/__init__.py's
    get_mastery_summary) used to build this same shape independently
    inline — factored out here so the view-building logic (domain
    rollup, per-skill views, gaps/next-steps) exists in exactly one
    place instead of drifting between the two.
    """
    rollup = aggregate_for_parent(vector)

    def _skill_view(skill_id: str) -> dict | None:
        skill = get_skill(skill_id)
        if skill is None:
            return None
        probability = vector[skill_id]
        return {
            "skill_id": skill_id,
            "label": skill.label,
            "domain": skill.domain,
            "grade_band": skill.band.value,
            "probability": probability,
            "level": _classify(probability),
        }

    domains = []
    for domain, info in rollup["domains"].items():
        domain_skill_ids = sorted(
            (skill_id for skill_id in vector if (s := get_skill(skill_id)) is not None and s.domain == domain),
            key=lambda skill_id: vector[skill_id],
        )
        domains.append({
            "domain": domain,
            "average_probability": info["average_probability"],
            "level": info["level"],
            "skills": [v for skill_id in domain_skill_ids if (v := _skill_view(skill_id)) is not None],
        })

    return {
        "student_name": student_name,
        "subject_area": subject_area,
        "evidence_count": evidence_count,
        "calibration": evidence_count < calibration_threshold,
        "domains": domains,
        "gaps": [v for skill_id in rollup["gaps"] if (v := _skill_view(skill_id)) is not None],
        # Least-secure first, capped — the same ordering composition.py and
        # language_exposure.py already use for their own next_steps, and
        # for the same reason: "what's worth working on next" is a
        # priority list, not an inventory. kst.fringe returns skill-id
        # order, which is alphabetical and therefore meaningless to a
        # parent; unsorted it put "Compares two quantities" (a K-2 skill
        # sitting at its untouched 0.70 prior) above the multi-digit
        # multiplication a 4th grader had actually struggled with at 0.47.
        # Sorting by probability also does the band work implicitly, since
        # new_vector seeds a student's own band lower than the bands below
        # it.
        "next_steps": sorted(
            (v for skill_id in rollup["next_steps"] if (v := _skill_view(skill_id)) is not None),
            key=lambda v: v["probability"],
        )[:_MAX_NEXT_STEPS],
        "updated_at": updated_at,
    }
