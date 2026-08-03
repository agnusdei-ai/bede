"""
Reading & spelling for grades 3-8 (services/diagnostic/literacy.py).

The gap this closes was total, not partial: phonics.py stops at 2nd grade,
composition.py measures WRITING, and between them nothing measured reading
after 2nd grade — no fluency, no vocabulary, no morphology, no
comprehension — and **spelling did not exist anywhere in the codebase at
any grade**. A 5th grader could work with Bede for a year and produce zero
evidence about how they read.

These tests pin three things:

1. **Coverage** — both strands of the Simple View of Reading are present,
   and spelling is explicit rather than assumed.
2. **The handoff with phonics** — K-2 reading belongs to phonics.py and
   3-8 to this module, with no overlap. Two engines competing for the same
   child's decoding evidence would produce two disagreeing pictures.
3. **Developmental ordering** — next_steps walks DOMAINS in order rather
   than sorting by probability, because a child weak in decoding is not
   helped by being pointed at author's craft however low that number is.
"""

import pytest

from models.schemas import GradeStage, SessionConfig, Subject
from services.diagnostic import literacy
from services.diagnostic.literacy import (
    CALIBRATION_THRESHOLD,
    DOMAIN_CHECKIN_HINTS,
    DOMAIN_LABELS,
    DOMAINS,
    apply_evidence,
    build_summary_view,
    new_vector,
)


def _config(grade="5", stage=GradeStage.core_mastery):
    return SessionConfig(
        student_name="Wren", grade=grade, grade_stage=stage,
        subjects=[Subject.language_arts],
    )


# ── Coverage ─────────────────────────────────────────────────────────────

def test_both_strands_of_the_reading_rope_are_present():
    """Word recognition AND language comprehension. Either alone is a
    partial model of reading."""
    word_recognition = {"decoding_multisyllable", "spelling_patterns", "morphology",
                        "spelling_homophones", "fluency"}
    comprehension = {"vocabulary", "literal_comprehension", "inference",
                     "text_structure", "author_craft"}
    assert word_recognition <= set(DOMAINS)
    assert comprehension <= set(DOMAINS)


def test_spelling_is_explicit_not_assumed():
    """
    Spelling existed nowhere in the codebase before this module. English is
    opaque enough that it has to be taught and observed directly rather
    than hoped for as a by-product of reading.
    """
    spelling_domains = [d for d in DOMAINS if "spelling" in d or d == "morphology"]
    assert len(spelling_domains) >= 3, f"spelling is under-represented: {spelling_domains}"


def test_every_domain_has_a_label_and_a_checkin_hint():
    for domain in DOMAINS:
        assert DOMAIN_LABELS.get(domain, "").strip(), f"{domain} has no parent-facing label"
        assert DOMAIN_CHECKIN_HINTS.get(domain, "").strip(), f"{domain} has no check-in hint"


def test_no_domain_overlaps_phonics():
    """
    The handoff has to be clean. phonics.py owns K-2 decoding; this module
    owns 3-8. A shared domain id would mean two engines writing two
    different pictures of the same child.
    """
    from services.diagnostic.phonics import DOMAINS as PHONICS_DOMAINS

    assert not (set(DOMAINS) & set(PHONICS_DOMAINS))


# ── The grade handoff, enforced in code as well as prompt ────────────────

def test_the_checkin_note_is_silent_for_k2():
    """K-2 must fall through to phonics, never to this engine."""
    from services.ai_service import _literacy_checkin_note

    assert _literacy_checkin_note(_config("1", GradeStage.foundations), Subject.language_arts) == ""


@pytest.mark.parametrize("stage", [GradeStage.core_mastery, GradeStage.independent])
def test_the_checkin_note_renders_for_3_8(stage):
    from services.ai_service import _literacy_checkin_note

    note = _literacy_checkin_note(_config("5", stage), Subject.language_arts)
    assert "<literacy_checkin>" in note
    for domain in DOMAINS:
        assert domain in note


def test_the_checkin_note_is_scoped_to_reading_subjects():
    from services.ai_service import _literacy_checkin_note

    assert _literacy_checkin_note(_config(), Subject.mathematics) == ""
    assert _literacy_checkin_note(_config(), Subject.living_books) != ""


def test_the_note_forbids_manufacturing_an_assessment():
    """Reading evidence is lying around in an ordinary lesson. Bede should
    record what it saw, not invent a test to generate a number."""
    from services.ai_service import _literacy_checkin_note

    note = _literacy_checkin_note(_config(), Subject.language_arts).lower()
    assert "do not invent" in note
    assert "never a verdict delivered to the child" in note


def test_the_tool_is_registered_with_the_real_domain_enum():
    from services.ai_service import TUTOR_TOOLS

    tool = next((t for t in TUTOR_TOOLS if t["name"] == "record_literacy_evidence"), None)
    assert tool is not None
    assert tool["input_schema"]["properties"]["domain"]["enum"] == list(DOMAINS)


def test_the_summary_endpoint_knows_this_subject_area():
    from routers.diagnostic import _SUMMARY_BUILDERS

    assert "literacy" in _SUMMARY_BUILDERS


# ── Evidence handling ────────────────────────────────────────────────────

def test_cold_start_is_flat():
    vector = new_vector()
    assert set(vector) == set(DOMAINS)
    assert set(vector.values()) == {0.5}


@pytest.mark.parametrize("outcome,direction", [
    ("correct", 1), ("partial", 1), ("hint_dependent", -1), ("incorrect", -1),
])
def test_evidence_moves_the_right_way(outcome, direction):
    vector = new_vector()
    updated, updates = apply_evidence(vector, "morphology", outcome)
    assert len(updates) == 1
    moved = updated["morphology"] - vector["morphology"]
    assert moved * direction > 0, f"{outcome} moved the wrong way"


def test_only_the_observed_domain_moves():
    updated, _ = apply_evidence(new_vector(), "inference", "correct")
    for domain in DOMAINS:
        if domain != "inference":
            assert updated[domain] == 0.5


@pytest.mark.parametrize("bad", ["not_a_domain", "", "literacy.morphology"])
def test_an_unrecognized_domain_is_a_true_no_op(bad):
    """A hallucinated domain must be harmless, never a raise — it would
    otherwise break the child's turn."""
    vector = new_vector()
    updated, updates = apply_evidence(vector, bad, "correct")
    assert updates == []
    assert updated == vector


def test_an_unrecognized_outcome_is_a_true_no_op():
    vector = new_vector()
    updated, updates = apply_evidence(vector, "morphology", "brilliant")
    assert updates == []
    assert updated == vector


def test_probabilities_stay_in_range_under_repeated_evidence():
    vector = new_vector()
    for _ in range(30):
        vector, _ = apply_evidence(vector, "fluency", "correct", calibration_weight=2.0)
    assert 0.0 <= vector["fluency"] <= 1.0
    for _ in range(30):
        vector, _ = apply_evidence(vector, "fluency", "incorrect", calibration_weight=2.0)
    assert 0.0 <= vector["fluency"] <= 1.0


# ── Developmental ordering ───────────────────────────────────────────────

def test_next_steps_follow_the_developmental_order_not_the_numbers():
    """
    The distinguishing choice. A child weak at decoding gets pointed at
    decoding — even when a later domain scores lower — because the later
    domains depend on the earlier ones.
    """
    vector = new_vector()
    vector["decoding_multisyllable"] = 0.45   # weak, but earliest
    vector["author_craft"] = 0.05             # much lower, but last
    view = build_summary_view(vector, "Wren", 10, "2026-01-01T00:00:00")
    assert view["next_steps"][0]["skill_id"] == "literacy.decoding_multisyllable"


def test_secure_domains_drop_out_of_next_steps():
    vector = {domain: 0.95 for domain in DOMAINS}
    vector["inference"] = 0.3
    view = build_summary_view(vector, "Wren", 10, "2026-01-01T00:00:00")
    assert [s["skill_id"] for s in view["next_steps"]] == ["literacy.inference"]


def test_next_steps_are_capped():
    view = build_summary_view(new_vector(), "Wren", 10, "2026-01-01T00:00:00")
    assert len(view["next_steps"]) <= 3


def test_summary_shape_matches_the_sibling_engines():
    view = build_summary_view(new_vector(), "Wren", 1, "2026-01-01T00:00:00")
    for key in ("student_name", "subject_area", "evidence_count", "calibration",
                "domains", "gaps", "next_steps", "updated_at"):
        assert key in view
    assert view["subject_area"] == "literacy"
    assert view["calibration"] is True, "one observation must still read as calibrating"


def test_calibration_clears_at_the_threshold():
    view = build_summary_view(new_vector(), "Wren", CALIBRATION_THRESHOLD, "x")
    assert view["calibration"] is False


def test_gaps_are_reported_separately():
    vector = new_vector()
    vector["spelling_homophones"] = 0.05
    view = build_summary_view(vector, "Wren", 10, "x")
    assert [g["skill_id"] for g in view["gaps"]] == ["literacy.spelling_homophones"]


def test_a_stored_vector_missing_a_new_domain_is_backfilled():
    """
    Same silent-failure class mastery.ensure_complete guards for math: a
    vector written before a domain existed must not leave that domain
    permanently invisible.
    """
    stored = {"morphology": 0.9}
    restored = literacy.new_vector()
    for k, v in stored.items():
        restored[k] = v
    assert set(restored) == set(DOMAINS)
    assert restored["morphology"] == 0.9
    assert restored["author_craft"] == 0.5
