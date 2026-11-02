"""Where a learner's grade actually changes mathematics behaviour.

The Grade 1-8 lifecycle (tests/test_valor_pilot_g2_journey.py's
test_math_lifecycle_per_grade) runs one implementation over eight rows of
scenario data. That is honest only if the grade-dependent code is small and
named, so this file pins it at the two places a grade changes anything:

1. models/schemas.py's grade_to_stage(): grade -> one of three bands. The
   boundaries are 2|3 and 5|6, and anything unrecognised falls to K-2.
2. Two band-dependent consumers in services/diagnostic/: new_vector()'s
   cold-start seeds and cat.select_next_probes()'s on-band filter.

Nothing else in the pilot tutoring, recommendation or deletion path reads
a learner's grade, so there is no other grade boundary to test.
"""
import pytest

from models.schemas import GradeStage, grade_to_stage
from services.diagnostic.cat import select_next_probes
from services.diagnostic.mastery import UNEVIDENCED_BELOW_BAND_PRIOR, new_vector
from services.diagnostic.qmatrix import Q_MATRIX
from services.diagnostic.skill_map import get_skill

# The representative skill each grade's lifecycle row uses.
GRADE_TARGET = {
    "1": "cc.number_bonds", "2": "nbt.add_within_100",
    "3": "oa.order_of_operations", "4": "fr.mixed_numbers",
    "5": "fr.divide_fractions", "6": "ns.absolute_value",
    "7": "ee.variables_both_sides", "8": "ee.systems_of_equations",
}


@pytest.mark.parametrize("grade,stage", [
    ("K", GradeStage.foundations), ("0", GradeStage.foundations),
    ("1", GradeStage.foundations), ("2", GradeStage.foundations),
    ("3", GradeStage.core_mastery), ("5", GradeStage.core_mastery),
    ("6", GradeStage.independent), ("8", GradeStage.independent),
    ("9", GradeStage.foundations), ("", GradeStage.foundations),
    (" k ", GradeStage.foundations),
])
def test_grade_to_stage_boundaries(grade, stage):
    assert grade_to_stage(grade) is stage


@pytest.mark.parametrize("grade,target", sorted(GRADE_TARGET.items()))
def test_each_grades_skill_sits_in_that_grades_band(grade, target):
    """A row whose skill is outside its own band would test the wrong prior."""
    assert get_skill(target).band.value == grade_to_stage(grade).value


@pytest.mark.parametrize("lower,upper", [("2", "3"), ("5", "6")])
def test_crossing_a_boundary_changes_the_seed_in_both_directions(lower, upper):
    low_band = grade_to_stage(lower).value
    high_band = grade_to_stage(upper).value
    assert low_band != high_band

    low_skill, high_skill = GRADE_TARGET[lower], GRADE_TARGET[upper]
    low_vector, high_vector = new_vector(low_band), new_vector(high_band)

    # Own band: genuine ignorance.
    assert low_vector[low_skill] == 0.5
    assert high_vector[high_skill] == 0.5
    # One step up the boundary, the lower grade's skill is assumed met but
    # never mastered (below the 0.80 secure cutoff).
    assert high_vector[low_skill] == UNEVIDENCED_BELOW_BAND_PRIOR < 0.8
    # One step down, the higher grade's skill is assumed not yet reached.
    assert low_vector[high_skill] == pytest.approx(0.3)


@pytest.mark.parametrize("band", ["K-2", "3-5", "6-8"])
def test_off_calibration_probe_selection_stays_on_band(band):
    probes = select_next_probes(new_vector(band), {}, band, calibration=False, limit=5)
    assert probes, f"no probe offered for a new {band} learner"
    for probe_id in probes:
        assert all(get_skill(s).band.value == band for s in Q_MATRIX[probe_id].skills), probe_id
