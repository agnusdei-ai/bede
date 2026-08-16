"""
Tests for the curriculum-resources framing note — see services/ai_service.py's
_curriculum_resources_note and models/schemas.py's
SessionConfig.curriculum_resources / CURRICULUM_RESOURCE_SUGGESTIONS.
"""
from models.schemas import GradeStage, SessionConfig
from services.ai_service import _build_static_prompt, _curriculum_resources_note


def _config(curriculum_resources=None, **kwargs) -> SessionConfig:
    return SessionConfig(
        student_name="Sam", grade="4", grade_stage=GradeStage.core_mastery,
        curriculum_resources=curriculum_resources or [], **kwargs,
    )


def test_empty_list_produces_no_note():
    assert _curriculum_resources_note(_config()) == ""


def test_named_resources_appear_in_the_note():
    note = _curriculum_resources_note(_config(["RightStart Mathematics", "Logic of English"]))
    assert "RightStart Mathematics" in note
    assert "Logic of English" in note


def test_never_claims_to_reproduce_proprietary_content():
    note = _curriculum_resources_note(_config(["Memoria Press"]))
    assert "Never claim to know or reproduce" in note
    assert "proprietary" in note


def test_a_familys_own_entry_outside_the_suggestion_list_is_honored():
    note = _curriculum_resources_note(_config(["Our co-op's own Latin club"]))
    assert "Our co-op's own Latin club" in note


def test_static_prompt_includes_the_note_when_set():
    prompt = _build_static_prompt(_config(["Well-Trained Mind Press"]))
    assert "Well-Trained Mind Press" in prompt


def test_static_prompt_omits_the_note_when_unset():
    prompt = _build_static_prompt(_config())
    assert "already uses material from" not in prompt


def test_schema_validator_dedupes_trims_and_caps_at_six():
    config = SessionConfig(
        student_name="Sam", grade="4", grade_stage=GradeStage.core_mastery,
        curriculum_resources=[
            " Memoria Press ", "memoria press", "Classical Academic Press",
            "Well-Trained Mind Press", "Institute for Excellence in Writing",
            "RightStart Mathematics", "Logic of English", "One Too Many",
        ],
    )
    assert config.curriculum_resources == [
        "Memoria Press", "Classical Academic Press", "Well-Trained Mind Press",
        "Institute for Excellence in Writing", "RightStart Mathematics", "Logic of English",
    ]


def test_schema_validator_drops_empty_entries():
    config = SessionConfig(
        student_name="Sam", grade="4", grade_stage=GradeStage.core_mastery,
        curriculum_resources=["", "   ", "Memoria Press"],
    )
    assert config.curriculum_resources == ["Memoria Press"]
