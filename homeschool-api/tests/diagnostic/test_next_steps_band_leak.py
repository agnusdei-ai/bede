"""
Regression: "next steps" used to be structurally incapable of naming a
student's own grade band.

FOUND BY RUNNING A REAL SESSION, not by reading code. A simulated 4th-grade
math block (10 observations through the real process_evidence path) produced
this list of recommended next steps:

    Compares two quantities              (0.70)   <- K-2, never probed
    Identifies basic 2D/3D shapes        (0.70)   <- K-2, never probed
    Measures length with standard units  (0.70)   <- K-2, never probed
    Tells time to the hour/minute        (0.70)   <- K-2, never probed
    Adds within 100                      (0.70)   <- K-2, never probed
    Multi-digit multiplication           (0.47)   <- what she ACTUALLY struggled with

Two independent defects, both fixed:

1. **kst.fringe required prerequisites at `hi` (0.8), the MASTERY floor.**
   mastery.new_vector cold-starts a below-band skill at 0.7 on the stated
   presumption that earlier bands are "very likely already mastered" — but
   0.7 < 0.8, so every unprobed K-2 prerequisite BLOCKED its dependents.
   A 3-5 student's entire fringe was the two K-2 skills that happen to have
   no prerequisites at all. No amount of 3-5 evidence could change that.
   `prereq_hi` (0.65) now answers "is the ground solid enough to build on"
   separately from "is this mastered".

2. **The list was in skill-id order** — alphabetical, and therefore
   arbitrary to a parent — and uncapped.  It is now least-secure first and
   capped, matching composition.py/language_exposure.py.

cat.py's adaptive probe selection feeds on the same fringe(), so defect 1
was steering probe choice too, not just the parent report.
"""

import pytest

from services.diagnostic.kst import fringe
from services.diagnostic.mastery import (
    _MAX_NEXT_STEPS,
    aggregate_for_parent,
    build_summary_view,
    new_vector,
)
from services.diagnostic.skill_map import get_skill

BANDS = ["K-2", "3-5", "6-8"]


def _bands_of(skill_ids):
    return {get_skill(s).band.value for s in skill_ids if get_skill(s)}


@pytest.mark.parametrize("band", BANDS)
def test_a_cold_start_student_is_offered_their_own_band(band):
    """
    The core regression. Before the fix, a 3-5 or 6-8 student's fringe
    contained ONLY K-2 skills — their own level was unreachable.
    """
    candidates = fringe(new_vector(band))
    assert candidates, f"{band} student has no next steps at all"
    assert band in _bands_of(candidates), (
        f"a {band} student is never offered a {band} skill; "
        f"fringe returned only {sorted(_bands_of(candidates))}"
    )


def test_the_old_threshold_reproduces_the_bug():
    """
    Pins the diagnosis itself, so the fix can't be undone by 'simplifying'
    prereq_hi back to hi. With the old behaviour a 4th grader's entire
    fringe is K-2.
    """
    vector = new_vector("3-5")
    old = fringe(vector, prereq_hi=0.8)
    assert _bands_of(old) == {"K-2"}, (
        "expected the pre-fix behaviour to offer only K-2 skills; "
        "if this now passes differently, the diagnosis above is stale"
    )
    assert "3-5" in _bands_of(fringe(vector)), "the fix no longer helps"


def test_an_unprobed_lower_band_presumption_does_not_block():
    """new_vector's own docstring promises earlier bands are presumed
    mastered. fringe must honour that promise rather than contradict it."""
    vector = new_vector("3-5")
    assert vector["cc.count_objects_20"] == pytest.approx(0.7)
    # oa.multiplication_facts depends (transitively) on K-2 material.
    assert "oa.multiplication_facts" in fringe(vector)


def test_evidence_still_overrides_the_presumption():
    """
    The presumption must yield to real evidence: a below-band skill that
    was actually probed and missed still blocks its dependents. Otherwise
    the fix would have traded one wrong answer for another.
    """
    vector = new_vector("3-5")
    vector["oa.add_within_20"] = 0.05          # probed and firmly missed
    blocked = [
        s for s in fringe(vector)
        if "oa.add_within_20" in _transitive(s)
    ]
    assert blocked == [], (
        "a firmly-missed prerequisite must still gate its dependents"
    )


def _transitive(skill_id):
    from services.diagnostic.kst import _transitive_prerequisites
    return _transitive_prerequisites(skill_id)


def test_same_band_prerequisites_still_gate():
    """
    KST's whole point. prereq_hi (0.65) sits ABOVE the same-band cold-start
    prior (0.5), so an unprobed same-band prerequisite still blocks — only
    the below-band presumption was ever meant to pass.
    """
    vector = new_vector("3-5")
    assert vector["oa.multiplication_facts"] == pytest.approx(0.5)
    # division facts sit behind multiplication facts in the same band.
    prereqs = _transitive("oa.division_facts")
    if "oa.multiplication_facts" in prereqs:
        assert "oa.division_facts" not in fringe(vector)


@pytest.mark.parametrize("band", BANDS)
def test_next_steps_are_least_secure_first(band):
    view = build_summary_view(new_vector(band), "Sam", "mathematics", 10, 5, "2026-01-01T00:00:00")
    probabilities = [s["probability"] for s in view["next_steps"]]
    assert probabilities == sorted(probabilities), (
        "next steps must be a priority list, not skill-id order"
    )


@pytest.mark.parametrize("band", BANDS)
def test_next_steps_are_capped(band):
    view = build_summary_view(new_vector(band), "Sam", "mathematics", 10, 5, "2026-01-01T00:00:00")
    assert 0 < len(view["next_steps"]) <= _MAX_NEXT_STEPS


def test_a_struggled_skill_outranks_an_untouched_lower_band_one():
    """
    The exact shape of the reported symptom: the thing the child actually
    got wrong today must come before a K-2 skill nobody has ever probed.
    """
    vector = new_vector("3-5")
    # Mirrors the real session that surfaced this. Both same-band
    # prerequisites were probed and answered well — which is precisely what
    # makes multi-digit multiplication fringe-eligible; leave either at its
    # unprobed 0.50 prior and KST correctly gates it, which is the
    # behaviour test_same_band_prerequisites_still_gate covers.
    vector["oa.multiplication_facts"] = 1.0
    vector["nbt.place_value_hundreds"] = 0.96
    vector["nbt.standard_multiplication"] = 0.47
    view = build_summary_view(vector, "Sam", "mathematics", 10, 5, "2026-01-01T00:00:00")
    ids = [s["skill_id"] for s in view["next_steps"]]
    assert ids[0] == "nbt.standard_multiplication", (
        f"expected the struggled skill first, got {ids}"
    )


def test_aggregate_for_parent_still_returns_raw_fringe_ids():
    """The sort/cap belongs to the parent-facing view, not the rollup —
    cat.py consumes fringe() directly and must keep seeing everything."""
    rollup = aggregate_for_parent(new_vector("3-5"))
    assert isinstance(rollup["next_steps"], list)
    assert all(isinstance(s, str) for s in rollup["next_steps"])
    assert len(rollup["next_steps"]) >= _MAX_NEXT_STEPS
