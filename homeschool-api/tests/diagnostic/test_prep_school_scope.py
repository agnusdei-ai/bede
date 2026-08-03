"""
The math skill map has to hold its own against preparatory-school
expectations, not merely conventional public-school ones.

The bar: an independent/classical prep school normally has an 8th grader
FINISHING ALGEBRA I. (Singapore's Dimensions Math 7-8, widely used by
classical and prep schools, covers pre-algebra plus Algebra I with an
introduction to geometry across those two years.) Before the preparatory-
school extension the map topped out at two-step equations and a first look
at linear functions — no multi-step or literal equations, no inequalities,
no systems, no exponent laws, no radicals, no polynomial arithmetic, no
factoring, no quadratics, no slope, no Pythagorean theorem.

These tests pin the SCOPE so a future edit can't quietly thin it back out.
They deliberately assert on capability areas rather than exact counts,
so adding more skills is always allowed and removing a competency is not.

They also pin the structural invariants that make growing the map safe at
all — no cycles, no dangling prerequisites, no prerequisite sitting in a
higher band than the skill that depends on it, and no renaming of the
original ids that live inside already-stored MasteryProfile vectors.
"""

import pytest

from services.diagnostic.mastery import ensure_complete, new_vector
from services.diagnostic.skill_map import (
    PREREQUISITES,
    SKILL_MAP,
    GradeBand,
    all_skill_ids,
    get_skill,
    skills_in_band,
)

BAND_ORDER = {"K-2": 0, "3-5": 1, "6-8": 2}


# ── Algebra I by the end of 8th grade ────────────────────────────────────

ALGEBRA_I_CORE = [
    "ee.multi_step_equations",
    "ee.variables_both_sides",
    "ee.literal_equations",
    "ee.inequalities",
    "ee.systems_of_equations",
    "ee.distributive_expand",
    "ee.factor_expressions",
    "ee.polynomial_arithmetic",
    "ee.quadratic_by_factoring",
    "ns.exponent_laws",
    "ns.square_cube_roots",
    "ns.scientific_notation",
    "ns.irrational_numbers",
    "fn.slope",
    "fn.slope_intercept_form",
    "geo.pythagorean",
]


@pytest.mark.parametrize("skill_id", ALGEBRA_I_CORE)
def test_algebra_one_competency_is_present(skill_id):
    """Each of these was absent before the extension. A prep-school 8th
    grader is expected to have met all of them."""
    assert skill_id in SKILL_MAP, f"{skill_id} missing — Algebra I scope has been thinned"
    assert SKILL_MAP[skill_id].band is GradeBand.SIX_8


def test_the_top_band_is_no_longer_a_stub():
    """
    Before: 14 skills in 6-8, ending at linear functions. A band that thin
    cannot represent a full Algebra I year.
    """
    assert len(skills_in_band(GradeBand.SIX_8)) >= 35


# ── The arithmetic pre-algebra assumes is finished ───────────────────────

PRE_ALGEBRA_PREREQUISITES = [
    "oa.order_of_operations",
    "oa.factors_multiples",
    "oa.primes_composites",
    "nbt.decimal_operations",
    "fr.divide_fractions",
    "fr.compare_fractions",
    "fr.mixed_numbers",
    "nbt.rounding_estimation",
]


@pytest.mark.parametrize("skill_id", PRE_ALGEBRA_PREREQUISITES)
def test_3_5_covers_what_pre_algebra_assumes(skill_id):
    assert skill_id in SKILL_MAP
    assert SKILL_MAP[skill_id].band is GradeBand.THREE_5


def test_k2_builds_number_sense_not_just_counting():
    """
    Singapore-style number sense — bonds, skip counting, equal groups — is
    what makes multiplication land later. Counting and adding alone don't.
    """
    for skill_id in ("cc.number_bonds", "cc.skip_count_2_5_10", "oa.arrays_equal_groups"):
        assert skill_id in SKILL_MAP
        assert SKILL_MAP[skill_id].band is GradeBand.K_2


# ── Structural invariants ────────────────────────────────────────────────

def test_no_dangling_prerequisites():
    for skill_id, prereqs in PREREQUISITES.items():
        for prereq in prereqs:
            assert prereq in SKILL_MAP, f"{skill_id} requires unknown skill {prereq}"


def test_no_cycles():
    """A cycle would make kst.fringe unable to ever offer the skills in it."""
    WHITE, GREY, BLACK = 0, 1, 2
    color = dict.fromkeys(SKILL_MAP, WHITE)

    def visit(node, trail):
        color[node] = GREY
        for prereq in SKILL_MAP[node].prerequisites:
            if color[prereq] is GREY:
                pytest.fail(f"prerequisite cycle: {' -> '.join(trail + [node, prereq])}")
            if color[prereq] is WHITE:
                visit(prereq, trail + [node])
        color[node] = BLACK

    for skill_id in SKILL_MAP:
        if color[skill_id] is WHITE:
            visit(skill_id, [])


def test_no_prerequisite_sits_in_a_higher_band():
    """
    A 6-8 prerequisite on a 3-5 skill would be unreachable for the student
    who needs it, and would gate that skill forever.
    """
    for skill_id, prereqs in PREREQUISITES.items():
        own = BAND_ORDER[SKILL_MAP[skill_id].band.value]
        for prereq in prereqs:
            assert BAND_ORDER[SKILL_MAP[prereq].band.value] <= own, (
                f"{skill_id} ({SKILL_MAP[skill_id].band.value}) depends on "
                f"{prereq} ({SKILL_MAP[prereq].band.value}), which is a higher band"
            )


def test_ids_are_unique():
    assert len(all_skill_ids()) == len(set(all_skill_ids()))


# ── The original ids must survive, byte for byte ─────────────────────────

# Every id that existed before the extension. Stored MasteryProfile vectors
# reference these by name, so renaming or removing one silently orphans a
# real family's accumulated history — there is no migration path for an
# encrypted JSON blob.
ORIGINAL_IDS = [
    "cc.rote_count_20", "cc.count_objects_20", "cc.compare_quantities",
    "oa.add_within_20", "oa.subtract_within_20", "oa.multiplication_facts",
    "oa.division_facts", "oa.numeric_patterns",
    "nbt.place_value_tens", "nbt.place_value_hundreds", "nbt.add_within_100",
    "nbt.subtract_within_100", "nbt.standard_multiplication", "nbt.long_division",
    "nbt.place_value_decimals",
    "fr.unit_fractions", "fr.equivalent_fractions", "fr.add_subtract_fractions",
    "fr.multiply_fractions",
    "md.measure_length", "md.tell_time", "md.read_bar_graphs", "md.area_perimeter",
    "md.convert_units",
    "geo.identify_shapes", "geo.classify_shapes_by_attributes", "geo.coordinate_plane",
    "geo.area_of_polygons", "geo.volume",
    "rp.ratio_concept", "rp.unit_rate", "rp.percent",
    "ns.integers", "ns.rational_operations",
    "ee.evaluate_expressions", "ee.one_step_equations", "ee.two_step_equations",
    "sp.mean_median_mode", "sp.data_distribution", "sp.basic_probability",
    "fn.function_concept", "fn.linear_functions",
]


def test_the_original_map_is_exactly_42_ids():
    """Guards the list above from drifting out of date."""
    assert len(ORIGINAL_IDS) == 42


@pytest.mark.parametrize("skill_id", ORIGINAL_IDS)
def test_original_ids_still_exist(skill_id):
    assert skill_id in SKILL_MAP, (
        f"{skill_id} was removed or renamed — stored mastery vectors reference it by name"
    )


# ── Growing the map must not strand existing families ────────────────────

def test_a_vector_stored_before_the_extension_is_backfilled():
    """
    The failure this prevents is silent rather than loud: every consumer
    iterates the vector, not the map, so a stale vector wouldn't crash —
    the new skills would just never be rolled up, never offered as a next
    step, and never probed, for exactly the families using Bede longest.
    """
    stale = {skill_id: 0.9 for skill_id in ORIGINAL_IDS}
    restored = ensure_complete(stale, "6-8")

    assert set(restored) == set(all_skill_ids())
    # Real history is preserved untouched...
    assert restored["oa.multiplication_facts"] == 0.9
    # ...and everything new arrives at its cold-start prior, not at zero.
    assert restored["ee.systems_of_equations"] == new_vector("6-8")["ee.systems_of_equations"]


def test_backfill_without_a_band_is_neutral_not_zero():
    """get_mastery_summary is a render path with no grade to hand."""
    restored = ensure_complete({"oa.multiplication_facts": 0.9})
    assert restored["ee.systems_of_equations"] == 0.5
    assert restored["oa.multiplication_facts"] == 0.9


def test_backfill_drops_a_retired_id():
    assert "gone.forever" not in ensure_complete({"gone.forever": 0.4}, "3-5")


def test_every_skill_has_a_probe():
    """qmatrix builds probes from SKILL_MAP, so a new skill is only
    reachable if that generation really is 1:1."""
    from services.diagnostic.qmatrix import Q_MATRIX

    for skill_id in all_skill_ids():
        assert f"probe.{skill_id}" in Q_MATRIX, f"no probe archetype for {skill_id}"


def test_every_skill_has_a_label_and_domain():
    for skill_id in all_skill_ids():
        skill = get_skill(skill_id)
        assert skill.label.strip(), f"{skill_id} has no label"
        assert skill.domain.strip(), f"{skill_id} has no domain"
