"""
Real check for Diagnostic build-loop unit 1.5 (kst.py) — see
docs/diagnostic/DIAGNOSTIC_BUILD_PROGRESS.md. Verified against a small,
hand-traceable slice of the real K-8 skill map:

  cc.rote_count_20 (no prereqs)
    <- cc.count_objects_20
         <- cc.compare_quantities
         <- oa.add_within_20
              <- oa.subtract_within_20
              <- oa.multiplication_facts
                   <- oa.division_facts
"""

from services.diagnostic.kst import (
    fringe,
    is_valid_knowledge_state,
    propagate_prerequisites,
    surmise_closure,
)


def test_surmise_closure_includes_transitive_prerequisites():
    closure = surmise_closure({"oa.division_facts"})
    assert closure == {
        "oa.division_facts",
        "oa.multiplication_facts",
        "oa.add_within_20",
        "cc.count_objects_20",
        "cc.rote_count_20",
    }


def test_surmise_closure_of_a_no_prerequisite_skill_is_itself():
    assert surmise_closure({"cc.rote_count_20"}) == {"cc.rote_count_20"}


def test_surmise_closure_of_multiple_skills_unions_their_closures():
    closure = surmise_closure({"oa.subtract_within_20", "cc.compare_quantities"})
    assert closure == {
        "oa.subtract_within_20", "oa.add_within_20",
        "cc.compare_quantities", "cc.count_objects_20", "cc.rote_count_20",
    }


def test_is_valid_knowledge_state_true_for_a_closed_state():
    assert is_valid_knowledge_state({"cc.rote_count_20", "cc.count_objects_20"})


def test_is_valid_knowledge_state_false_when_missing_a_prerequisite():
    assert not is_valid_knowledge_state({"cc.count_objects_20"})  # missing cc.rote_count_20
    assert not is_valid_knowledge_state({"oa.division_facts"})


def test_propagate_prerequisites_raises_floor_on_transitive_prereqs():
    vector = {
        "oa.division_facts": 0.9,
        "oa.multiplication_facts": 0.3,
        "oa.add_within_20": 0.1,
        "cc.count_objects_20": 0.1,
        "cc.rote_count_20": 0.1,
    }
    updated = propagate_prerequisites(vector, threshold=0.8)
    for skill_id in ("oa.multiplication_facts", "oa.add_within_20", "cc.count_objects_20", "cc.rote_count_20"):
        assert updated[skill_id] == 0.8, f"{skill_id} was not raised to the threshold floor"
    assert updated["oa.division_facts"] == 0.9  # unchanged


def test_propagate_prerequisites_does_not_lower_already_higher_values():
    vector = {"oa.division_facts": 0.9, "oa.multiplication_facts": 0.95}
    updated = propagate_prerequisites(vector, threshold=0.8)
    assert updated["oa.multiplication_facts"] == 0.95


def test_propagate_prerequisites_does_not_mutate_input():
    vector = {"oa.division_facts": 0.9, "oa.multiplication_facts": 0.1}
    original = dict(vector)
    propagate_prerequisites(vector, threshold=0.8)
    assert vector == original


def test_propagate_prerequisites_only_touches_keys_already_in_vector():
    # cc.rote_count_20 (a transitive prereq) is deliberately absent.
    vector = {"oa.division_facts": 0.9, "oa.multiplication_facts": 0.1}
    updated = propagate_prerequisites(vector, threshold=0.8)
    assert "cc.rote_count_20" not in updated


def test_propagate_prerequisites_below_threshold_does_not_propagate():
    vector = {"oa.division_facts": 0.5, "oa.multiplication_facts": 0.1}
    updated = propagate_prerequisites(vector, threshold=0.8)
    assert updated["oa.multiplication_facts"] == 0.1


def test_fringe_includes_a_no_prerequisite_skill_when_its_own_probability_is_in_band():
    assert fringe({"cc.rote_count_20": 0.5}) == ["cc.rote_count_20"]


def test_fringe_excludes_an_already_mastered_skill():
    assert fringe({"cc.rote_count_20": 0.9}) == []


def test_fringe_excludes_a_confirmed_gap_skill():
    assert fringe({"cc.rote_count_20": 0.1}) == []


def test_fringe_excludes_a_skill_whose_prerequisites_are_not_yet_mastered():
    vector = {"cc.rote_count_20": 0.3, "cc.count_objects_20": 0.5}
    result = fringe(vector)
    assert "cc.count_objects_20" not in result
    assert "cc.rote_count_20" in result  # no prereqs, own prob in-band


def test_fringe_includes_a_skill_once_its_prerequisites_are_mastered():
    vector = {"cc.rote_count_20": 0.9, "cc.count_objects_20": 0.5}
    result = fringe(vector)
    assert "cc.count_objects_20" in result
    assert "cc.rote_count_20" not in result  # already mastered, no longer "next up"


def test_fringe_correct_on_a_small_hand_verified_map():
    vector = {
        "cc.rote_count_20": 0.9,        # mastered -> off the fringe
        "cc.count_objects_20": 0.85,    # mastered -> off the fringe
        "cc.compare_quantities": 0.5,   # prereq (count_objects_20) mastered -> ON the fringe
        "oa.add_within_20": 0.6,        # prereq (count_objects_20) mastered -> ON the fringe
        "oa.subtract_within_20": 0.5,   # prereq (add_within_20) NOT yet mastered -> off
        "oa.multiplication_facts": 0.05,  # confirmed gap (below lo) -> off
    }
    assert fringe(vector) == ["cc.compare_quantities", "oa.add_within_20"]


def test_fringe_result_is_sorted():
    vector = {"oa.add_within_20": 0.5, "cc.compare_quantities": 0.5, "cc.rote_count_20": 0.9}
    result = fringe(vector)
    assert result == sorted(result)
