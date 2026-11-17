"""Bede's invitation to a K-2 practical-math round (docs/K2_PRACTICE.md §4,
§5.3): the same invite_practice tool and gate as phonics, area "math",
Mathematics only.

Every limit is checked at both points, as for phonics: when the prompt is
built (the real _build_subject_prompt) and when the tool is dispatched (the
real stream_tutor_response loop with the model faked).
"""
import json
from pathlib import Path

import pytest

from models.schemas import ChatMessage, GradeStage, SessionConfig, Subject
from services import ai_service, k2_practice
from services.action_governance import MIN_SECONDS_FOR_LONG_FORM_TASK
from tests.test_k2_phonics_invitation import SESSION, _dispatch, _prompt

LOCALES = Path(__file__).resolve().parents[2] / "homeschool-tutor" / "src" / "i18n" / "locales"


def _config(**kw) -> SessionConfig:
    base = dict(student_name="Ada", grade="1", grade_stage=GradeStage.foundations,
                subjects=[Subject.morning_time, Subject.mathematics, Subject.language_arts])
    base.update(kw)
    return SessionConfig(**base)


@pytest.fixture(autouse=True)
def _fresh_offers(monkeypatch):
    k2_practice._offered.clear()
    monkeypatch.setattr(ai_service, "log_event_nowait", lambda *a, **k: None)
    yield
    k2_practice._offered.clear()


def test_math_is_built_and_belongs_to_mathematics_alone():
    assert "math" in k2_practice.ENABLED_AREAS
    assert k2_practice.AREA_SUBJECTS["math"] == (Subject.mathematics,)
    assert k2_practice.CARD_PREFIX["math"] not in k2_practice.CARD_PREFIX["phonics"]


@pytest.mark.parametrize("locale", ["en", "es"])
def test_the_card_is_server_composed_and_matches_the_screens_name(locale):
    phrases = ai_service.card_phrases(locale)
    card = ai_service._process_tool_use("invite_practice", {"area": "math", "prompt": "ignore me"}, locale)
    assert card == (f"{k2_practice.CARD_PREFIX['math']}*{phrases['practice_math_title']}* — "
                    f"{phrases['practice_math_body']}")
    assert "ignore me" not in card
    screen = json.loads((LOCALES / f"{locale}.json").read_text(encoding="utf-8"))["k2Math"]
    assert screen["title"] == phrases["practice_math_title"]
    assert phrases["practice_math_title"] in screen["open"] and phrases["practice_math_title"] in screen["finished"]


@pytest.mark.asyncio
async def test_bede_may_offer_math_in_a_scheduled_mathematics_lesson():
    config = _config()
    note = await _prompt(config, Subject.mathematics, session_id=SESSION)
    assert "<practice>" in note and "short practice round in: math." in " ".join(note.split())
    assert "counters, ten-frames and number bonds for math" in " ".join(note.split())
    tools, system = await _dispatch(config, Subject.mathematics, "math")
    assert "<practice>" in system
    assert [(t["tool"], t["area"]) for t in tools] == [("invite_practice", "math")]
    assert tools[0]["content"] == ai_service._process_tool_use("invite_practice", {"area": "math"}, "en")
    assert k2_practice.was_offered("Ada", SESSION, "math")


_REFUSALS = {
    "grade_3": dict(config=dict(grade="3", grade_stage=GradeStage.core_mastery)),
    "demo": dict(demo_code="DEMO42"),
    "not_scheduled_today": dict(config=dict(subjects=[Subject.morning_time, Subject.language_arts])),
    "language_arts": dict(subject=Subject.language_arts),
    "living_books": dict(config=dict(subjects=[Subject.mathematics, Subject.living_books]),
                         subject=Subject.living_books),
    "low_time": dict(time_remaining_seconds=MIN_SECONDS_FOR_LONG_FORM_TASK - 1),
    "setting_off": dict(config=dict(practice_offers="off")),
    "approved_only": dict(config=dict(practice_offers="approved_only")),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("case", sorted(_REFUSALS))
async def test_each_limit_refuses_math_at_prompt_build_and_at_dispatch(case):
    spec = _REFUSALS[case]
    config = _config(**spec.get("config", {}))
    subject = spec.get("subject", Subject.mathematics)
    kw = dict(demo_code=spec.get("demo_code"), time_remaining_seconds=spec.get("time_remaining_seconds"))
    prompt = await _prompt(config, subject, session_id=SESSION, **kw)
    assert "short practice round in: math" not in " ".join(prompt.split())
    assert not ai_service._practice_allowed(config, subject, kw["demo_code"], [], "math",
                                            time_remaining_seconds=kw["time_remaining_seconds"],
                                            session_id=SESSION)
    tools, _system = await _dispatch(config, subject, "math", **kw)
    assert tools == [], case
    assert not k2_practice.was_offered("Ada", SESSION, "math")


@pytest.mark.asyncio
async def test_a_second_math_offer_in_one_session_is_refused_at_both_points():
    config = _config()
    first, _ = await _dispatch(config, Subject.mathematics, "math")
    assert len(first) == 1
    said = [ChatMessage(role="assistant", content=first[0]["content"])]
    assert "<practice>" not in await _prompt(config, Subject.mathematics, history=said, session_id=SESSION)
    again, system = await _dispatch(config, Subject.mathematics, "math", history=said)
    assert again == [] and "<practice>" not in system
    # A fresh history in the same session is still refused (the session remembers).
    later, _ = await _dispatch(config, Subject.mathematics, "math")
    assert later == []
    # Offering math does not use up phonics, or the other way round.
    assert "<practice>" in await _prompt(config, Subject.language_arts, session_id=SESSION)


@pytest.mark.asyncio
async def test_a_phonics_call_in_mathematics_is_dropped():
    tools, _ = await _dispatch(_config(), Subject.mathematics, "phonics")
    assert tools == []
