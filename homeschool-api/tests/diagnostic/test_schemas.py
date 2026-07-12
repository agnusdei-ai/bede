"""
Real check for Diagnostic build-loop unit 2.3 (Pydantic schemas in
models/schemas.py: MasteryLevel, SkillMasteryView, DomainMasteryView,
MasteryProfileSummary, RecordSkillEvidenceInput) — see
docs/diagnostic/DIAGNOSTIC_BUILD_PROGRESS.md.

These are the render-only parent-facing view models (unit 4.1's router
will build them from services.diagnostic.mastery.aggregate_for_parent's
output) and the server-side validated shape of the silent
record_skill_evidence tool's input (Phase 3). Neither is wired to a
router/tool yet — this unit is schema-only, mirroring how unit 2.1 was
ORM-only.
"""

import pytest
from pydantic import ValidationError

from models.schemas import (
    DomainMasteryView,
    MasteryLevel,
    MasteryProfileSummary,
    RecordSkillEvidenceInput,
    SkillMasteryView,
)
from services.diagnostic.mastery import _MASTERY_LEVELS


def test_mastery_level_values_match_mastery_classify_exactly():
    """_classify()'s string returns ("secure"/"developing"/"gap") must be
    valid MasteryLevel members, or unit 4.1's router can't construct a
    SkillMasteryView from aggregate_for_parent's output without a
    translation layer that doesn't exist."""
    classify_level_names = {level for level, _floor in _MASTERY_LEVELS}
    schema_level_values = {level.value for level in MasteryLevel}
    assert classify_level_names == schema_level_values


def test_skill_mastery_view_accepts_valid_data():
    view = SkillMasteryView(
        skill_id="cc.rote_count_20",
        label="Rote counts to 20",
        domain="Counting & Cardinality",
        grade_band="K-2",
        probability=0.65,
        level=MasteryLevel.developing,
    )
    assert view.probability == 0.65
    assert view.level == MasteryLevel.developing


@pytest.mark.parametrize("bad_probability", [-0.01, 1.01])
def test_skill_mastery_view_rejects_out_of_range_probability(bad_probability):
    with pytest.raises(ValidationError):
        SkillMasteryView(
            skill_id="cc.rote_count_20", label="x", domain="x", grade_band="K-2",
            probability=bad_probability, level=MasteryLevel.gap,
        )


def test_domain_mastery_view_nests_skill_mastery_views():
    domain = DomainMasteryView(
        domain="Counting & Cardinality",
        average_probability=0.5,
        level=MasteryLevel.developing,
        skills=[
            SkillMasteryView(
                skill_id="cc.rote_count_20", label="x", domain="Counting & Cardinality",
                grade_band="K-2", probability=0.5, level=MasteryLevel.developing,
            )
        ],
    )
    assert len(domain.skills) == 1
    assert domain.skills[0].skill_id == "cc.rote_count_20"


def test_mastery_profile_summary_defaults_subject_area_to_mathematics():
    summary = MasteryProfileSummary(
        student_name="Emma",
        evidence_count=5,
        calibration=True,
        domains=[],
        gaps=[],
        next_steps=[],
        updated_at="2026-07-12T00:00:00+00:00",
    )
    assert summary.subject_area == "mathematics"


def test_record_skill_evidence_input_accepts_every_real_outcome():
    for outcome in ("correct", "partial", "incorrect", "hint_dependent"):
        ev = RecordSkillEvidenceInput(probe_id="probe.cc.rote_count_20", outcome=outcome)
        assert ev.outcome == outcome
        assert ev.confidence == 1.0  # default


def test_record_skill_evidence_input_rejects_an_invented_outcome():
    """Matches the tool description's own rule: 'Choose probe_id ONLY from
    the list provided ... never invent one' — outcome is equally closed."""
    with pytest.raises(ValidationError):
        RecordSkillEvidenceInput(probe_id="probe.cc.rote_count_20", outcome="mastered")


def test_record_skill_evidence_input_rejects_an_overlong_probe_id():
    with pytest.raises(ValidationError):
        RecordSkillEvidenceInput(probe_id="p" * 81, outcome="correct")


@pytest.mark.parametrize("bad_confidence", [-0.01, 1.01])
def test_record_skill_evidence_input_rejects_out_of_range_confidence(bad_confidence):
    with pytest.raises(ValidationError):
        RecordSkillEvidenceInput(
            probe_id="probe.cc.rote_count_20", outcome="correct", confidence=bad_confidence,
        )
