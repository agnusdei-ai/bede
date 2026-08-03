"""
SessionConfig.mastery_cycle_days / travel_mode — the parent-facing cadence
for reading term-mastery topics (see the field comments in schemas.py).

Two things are pinned here. The first is the "clean, never reject"
convention this codebase applies to every low-stakes parent field
(_validate_term, _validate_curriculum_resources, _validate_logic_stage): a
malformed or stale value is corrected, never 422'd, so a parent editing one
setting is never blocked by another.

The second is the actual product rule: travel mode is what UNLOCKS the
choice. With it off there is exactly one honest window — 28 actual days,
which is what the learner's guarantee is written against — and any other
value is a stale leftover rather than an instruction.
"""
import pytest

from models.schemas import (
    DEFAULT_MASTERY_CYCLE_DAYS,
    TRAVEL_MASTERY_CYCLE_MAX_DAYS,
    TRAVEL_MASTERY_CYCLE_MIN_DAYS,
    GradeStage,
    SessionConfig,
    Subject,
)


def _config(**kw) -> SessionConfig:
    base = dict(
        student_name="Ada",
        grade="4",
        grade_stage=GradeStage.core_mastery,
        subjects=[Subject.mathematics],
    )
    base.update(kw)
    return SessionConfig(**base)


def test_default_is_four_actual_weeks():
    assert DEFAULT_MASTERY_CYCLE_DAYS == 28
    assert _config().mastery_cycle_days == 28


def test_travel_mode_is_off_by_default():
    """A family that never travels should never meet this setting at all."""
    assert _config().travel_mode is False


@pytest.mark.parametrize("requested", [7, 21, 35, 42, 90, 0, -5])
def test_without_travel_mode_the_window_is_always_the_default(requested):
    """No travel mode means no choice — whatever arrives is corrected back,
    rather than rejected. A value here without travel_mode is a leftover
    from when it WAS on, not a request."""
    cfg = _config(travel_mode=False, mastery_cycle_days=requested)
    assert cfg.mastery_cycle_days == DEFAULT_MASTERY_CYCLE_DAYS


@pytest.mark.parametrize("requested", [21, 28, 35, 42])
def test_travel_mode_honors_three_to_six_weeks_exactly(requested):
    cfg = _config(travel_mode=True, mastery_cycle_days=requested)
    assert cfg.mastery_cycle_days == requested


@pytest.mark.parametrize(
    "requested,expected",
    [
        (20, TRAVEL_MASTERY_CYCLE_MIN_DAYS),   # under three weeks
        (1, TRAVEL_MASTERY_CYCLE_MIN_DAYS),
        (43, TRAVEL_MASTERY_CYCLE_MAX_DAYS),   # over six weeks
        (365, TRAVEL_MASTERY_CYCLE_MAX_DAYS),
    ],
)
def test_travel_mode_clamps_rather_than_rejecting(requested, expected):
    """Under three weeks there isn't room for evidence to accumulate; over
    six it stops being a cadence and becomes the term again. Both are
    clamped, so a parent dragging a slider never gets a save error."""
    cfg = _config(travel_mode=True, mastery_cycle_days=requested)
    assert cfg.mastery_cycle_days == expected


def test_the_travel_range_brackets_the_default():
    """The default has to be reachable with travel mode on, or turning it on
    would force a family off a window that was working for them."""
    assert TRAVEL_MASTERY_CYCLE_MIN_DAYS <= DEFAULT_MASTERY_CYCLE_DAYS <= TRAVEL_MASTERY_CYCLE_MAX_DAYS


def test_turning_travel_mode_off_restores_the_default():
    """The round trip a parent actually makes: widen the window for a trip,
    come home, turn it off. They should land back on 28 without having to
    remember what it used to be."""
    away = _config(travel_mode=True, mastery_cycle_days=42)
    assert away.mastery_cycle_days == 42

    home = _config(travel_mode=False, mastery_cycle_days=away.mastery_cycle_days)
    assert home.mastery_cycle_days == DEFAULT_MASTERY_CYCLE_DAYS


def test_cycle_settings_do_not_disturb_the_rest_of_the_config():
    """This cadence is a reporting window and nothing else — it must not
    reach the subject list, the session cap, or the term."""
    cfg = _config(travel_mode=True, mastery_cycle_days=42, current_term=2)
    assert cfg.subjects == [Subject.mathematics]
    assert cfg.current_term == 2
    assert cfg.session_cap_minutes == _config().session_cap_minutes
