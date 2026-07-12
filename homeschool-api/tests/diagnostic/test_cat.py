"""
Real check for Diagnostic build-loop unit 1.6 (cat.py) — see
docs/diagnostic/DIAGNOSTIC_BUILD_PROGRESS.md. Asserts probe selection
prefers the highest-uncertainty fringe skill, respects band filtering and
calibration widening, and the stopping rule behaves correctly at the
confidence boundary.
"""

from services.diagnostic.cat import select_next_probes, should_stop_probing


def test_select_next_probes_prefers_highest_entropy_fringe_skill():
    # cc.rote_count_20 has no prerequisites, so it and cc.compare_quantities
    # (whose only prereq, cc.count_objects_20, we mark mastered) are both
    # on the fringe. 0.5 is maximum entropy; 0.75 is lower.
    vector = {
        "cc.rote_count_20": 0.5,
        "cc.count_objects_20": 0.9,
        "cc.compare_quantities": 0.75,
    }
    result = select_next_probes(vector, theta={}, grade_band="K-2", calibration=False)
    assert result[0] == "probe.cc.rote_count_20"


def test_select_next_probes_filters_by_band_when_not_calibrating():
    vector = {
        "cc.rote_count_20": 0.5,          # K-2
        "cc.count_objects_20": 0.9,        # mastered, unlocks the below
        "cc.compare_quantities": 0.6,      # K-2, on fringe
        "nbt.place_value_hundreds": 0.9,   # mastered, unlocks below
        "nbt.add_within_100": 0.5,         # K-2 band per skill_map (still)
    }
    result = select_next_probes(vector, theta={}, grade_band="K-2", calibration=False)
    for probe_id in result:
        assert probe_id.startswith("probe.cc.") or probe_id.startswith("probe.nbt.add_within_100")


# fr.unit_fractions's FULL transitive prerequisite chain (fringe() checks
# the whole closure, not just the direct prereq, since a mid-chain skill
# being "mastered" doesn't mean everything beneath it has been confirmed).
_FR_UNIT_FRACTIONS_CHAIN_MASTERED = {
    "oa.division_facts": 0.9,
    "oa.multiplication_facts": 0.9,
    "oa.add_within_20": 0.9,
    "cc.count_objects_20": 0.9,
    "cc.rote_count_20": 0.9,
}


def test_select_next_probes_falls_back_to_full_fringe_with_no_on_band_candidates():
    # fr.unit_fractions is 3-5 band, fully unlocked here, but the
    # requested band is 6-8 where nothing is on the fringe.
    vector = {**_FR_UNIT_FRACTIONS_CHAIN_MASTERED, "fr.unit_fractions": 0.5}
    result = select_next_probes(vector, theta={}, grade_band="6-8", calibration=False)
    assert result == ["probe.fr.unit_fractions"]


def test_select_next_probes_widens_across_bands_when_calibrating():
    # geo.identify_shapes (K-2, no prerequisites, on the fringe at 0.5) and
    # fr.unit_fractions (3-5, off-band for a K-2 request) should BOTH
    # appear when calibration=True removes band filtering entirely.
    vector = {
        **_FR_UNIT_FRACTIONS_CHAIN_MASTERED,
        "fr.unit_fractions": 0.6,
        "geo.identify_shapes": 0.5,
    }
    result = select_next_probes(vector, theta={}, grade_band="K-2", calibration=True)
    assert "probe.fr.unit_fractions" in result
    assert "probe.geo.identify_shapes" in result


def test_select_next_probes_never_selects_an_already_mastered_skill():
    vector = {"cc.rote_count_20": 0.95, "cc.count_objects_20": 0.5}
    result = select_next_probes(vector, theta={}, grade_band="K-2", calibration=False)
    assert "probe.cc.rote_count_20" not in result


def test_select_next_probes_returns_real_probe_ids():
    vector = {"cc.rote_count_20": 0.5}
    result = select_next_probes(vector, theta={}, grade_band="K-2", calibration=False)
    assert result == ["probe.cc.rote_count_20"]


def test_select_next_probes_respects_limit():
    vector = {
        "cc.rote_count_20": 0.5,
        "cc.count_objects_20": 0.9,
        "cc.compare_quantities": 0.5,
        "nbt.place_value_tens": 0.5,
    }
    result = select_next_probes(vector, theta={}, grade_band="K-2", calibration=False, limit=1)
    assert len(result) == 1


def test_select_next_probes_empty_fringe_returns_empty_list():
    assert select_next_probes({}, theta={}, grade_band="K-2", calibration=False) == []


def test_should_stop_probing_true_for_confident_high_probability():
    assert should_stop_probing({"a": 0.99}, ["a"])


def test_should_stop_probing_true_for_confident_low_probability():
    assert should_stop_probing({"a": 0.01}, ["a"])


def test_should_stop_probing_false_for_maximally_uncertain_probability():
    assert not should_stop_probing({"a": 0.5}, ["a"])


def test_should_stop_probing_false_when_any_skill_still_uncertain():
    assert not should_stop_probing({"a": 0.99, "b": 0.5}, ["a", "b"])


def test_should_stop_probing_true_when_all_skills_confident():
    assert should_stop_probing({"a": 0.99, "b": 0.01}, ["a", "b"])


def test_should_stop_probing_missing_skill_defaults_to_uncertain():
    assert not should_stop_probing({}, ["not.tracked.yet"])


def test_should_stop_probing_empty_skill_list_returns_false():
    assert not should_stop_probing({"a": 0.99}, [])


def test_should_stop_probing_threshold_is_tunable():
    # se_threshold looser than the maximum possible SE (0.5 at p=0.5) makes
    # even a fully uncertain skill count as "confident."
    assert should_stop_probing({"a": 0.5}, ["a"], se_threshold=0.6)
