"""The learning sprint setting: 20, 30 or 60 minutes, cleaned and never
rejected, and never handed to the model (Bede does not time a child)."""
import inspect

import pytest

from models.schemas import (
    SPRINT_MINUTES_OPTIONS, GradeStage, SessionConfig, Subject,
)
from services import ai_service


def _config(**extra):
    return SessionConfig(student_name="Sample Learner", grade="4",
                         grade_stage=GradeStage.core_mastery, subjects=[Subject.mathematics], **extra)


def test_the_three_lengths():
    assert SPRINT_MINUTES_OPTIONS == (20, 30, 60)


def test_unset_by_default():
    assert _config().sprint_minutes is None


@pytest.mark.parametrize("minutes", [20, 30, 60])
def test_an_offered_length_is_kept(minutes):
    assert _config(sprint_minutes=minutes).sprint_minutes == minutes


@pytest.mark.parametrize("bad", [0, 15, 45, 90, -20, "30", "soon", True, 20.5, [20]])
def test_anything_else_is_cleaned_to_unset_and_never_rejected(bad):
    assert _config(sprint_minutes=bad).sprint_minutes is None


def test_it_round_trips_through_the_saved_json():
    saved = _config(sprint_minutes=30).model_dump_json()
    assert SessionConfig.model_validate_json(saved).sprint_minutes == 30


def test_the_setting_never_reaches_a_prompt():
    assert "sprint_minutes" not in inspect.getsource(ai_service)
