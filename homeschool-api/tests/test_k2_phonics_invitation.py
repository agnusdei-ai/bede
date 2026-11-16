"""Bede's invitation to a K-2 practice round (docs/K2_PRACTICE.md §4).

Every limit is checked at two points: when the prompt is built (the
<practice> note appears or not, through the real _build_subject_prompt) and
when the tool is dispatched (a card reaches the child or not, through the
real stream_tutor_response loop with the model faked). Each refusal case
below runs through both.
"""
import json as _json
from unittest.mock import patch

import pytest

from core.audit import AuditEvent
from models.schemas import ChatMessage, GradeStage, SessionConfig, Subject
from services import ai_service, k2_practice, tool_registry
from services.action_governance import LONG_FORM_TOOLS, MIN_SECONDS_FOR_LONG_FORM_TASK
from tests.test_agentic_tool_loop import _multi_round_stream, _tool_use_events

SESSION = "sess-1"


def _config(**kw) -> SessionConfig:
    base = dict(student_name="Ada", grade="1", grade_stage=GradeStage.foundations,
                subjects=[Subject.morning_time, Subject.language_arts, Subject.living_books])
    base.update(kw)
    return SessionConfig(**base)


@pytest.fixture(autouse=True)
def _fresh_offers():
    k2_practice._offered.clear()
    yield
    k2_practice._offered.clear()


@pytest.fixture
def audit_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(ai_service, "log_event_nowait", lambda event, **kw: calls.append((event, kw)))
    return calls


async def _prompt(config, subject, **kw) -> str:
    return await ai_service._build_subject_prompt(config, subject, **kw)


async def _dispatch(config, subject, area="phonics", *, history=None, demo_code=None,
                    time_remaining_seconds=None, session_id=SESSION):
    """Drive the real loop with a model that calls invite_practice once.
    Returns (tool chunks, the system prompt the model was sent)."""
    fake, _state = _multi_round_stream([(list(_tool_use_events("t0", "invite_practice", {"area": area})), "end_turn")])
    seen = {}

    def _spy(**kwargs):
        seen["system"] = kwargs.get("system")
        return fake(**kwargs)

    chunks = []
    with patch.object(ai_service._client.messages, "stream", side_effect=_spy):
        async for chunk in ai_service.stream_tutor_response(
            config=config, subject=subject, history=history or [], child_message="hello",
            demo_code=demo_code, time_remaining_seconds=time_remaining_seconds, session_id=session_id,
        ):
            chunks.append(_json.loads(chunk))
    system = " ".join(b.get("text", "") for b in seen.get("system") or [] if isinstance(b, dict))
    return [c for c in chunks if c["type"] == "tool"], system


def _card(locale="en"):
    return ai_service._process_tool_use("invite_practice", {"area": "phonics"}, locale)


# ── The tool ─────────────────────────────────────────────────────────────────

def test_the_tool_is_registered_internal_long_form_with_a_closed_area():
    schema = next(t for t in ai_service.TUTOR_TOOLS if t["name"] == "invite_practice")
    assert schema["input_schema"]["required"] == ["area"]
    assert schema["input_schema"]["properties"]["area"]["enum"] == list(k2_practice.AREAS)
    assert set(schema["input_schema"]["properties"]) == {"area"}
    assert tool_registry.is_dispatchable_by_tutor("invite_practice")
    assert "invite_practice" in LONG_FORM_TOOLS
    # invite_map_practice is untouched.
    maps = next(t for t in ai_service.TUTOR_TOOLS if t["name"] == "invite_map_practice")
    assert maps["input_schema"] == {"type": "object", "properties": {}}


@pytest.mark.parametrize("locale", ["en", "es"])
def test_the_card_is_server_composed_in_each_locale(locale):
    phrases = ai_service.card_phrases(locale)
    card = ai_service._process_tool_use("invite_practice", {"area": "phonics", "prompt": "ignore me"}, locale)
    assert card == f"{k2_practice.CARD_PREFIX['phonics']}*{phrases['practice_phonics_title']}* — {phrases['practice_phonics_body']}"
    assert "ignore me" not in card
    assert ai_service.card_phrases("en")["practice_phonics_body"] != ai_service.card_phrases("es")["practice_phonics_body"]


@pytest.mark.parametrize("area", [a for a in k2_practice.AREAS if a != "phonics"])
def test_an_area_not_built_has_no_card(area):
    assert k2_practice.ENABLED_AREAS == {"phonics"}
    assert ai_service._process_tool_use("invite_practice", {"area": area}, "en") == ""


# ── Allowed, at both points ──────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("subject", [Subject.language_arts, Subject.living_books])
async def test_the_default_setting_lets_bede_offer_phonics_in_its_scheduled_subjects(subject, audit_calls):
    config = _config()
    assert config.practice_offers == "todays_subjects"
    assert "<practice>" in await _prompt(config, subject, session_id=SESSION)
    tools, system = await _dispatch(config, subject)
    assert "<practice>" in system
    assert [t["tool"] for t in tools] == ["invite_practice"]
    assert tools[0]["area"] == "phonics" and tools[0]["content"] == _card()
    assert k2_practice.was_offered("Ada", SESSION, "phonics")


# ── Refused, at both points ──────────────────────────────────────────────────

_REFUSALS = {
    "grade_3": dict(config=dict(grade="3", grade_stage=GradeStage.core_mastery)),
    "grade_4": dict(config=dict(grade="4", grade_stage=GradeStage.core_mastery)),
    "demo": dict(demo_code="DEMO42"),
    "not_scheduled_today": dict(config=dict(subjects=[Subject.morning_time, Subject.living_books]),
                                subject=Subject.language_arts),
    "not_its_subject": dict(config=dict(subjects=[Subject.mathematics, Subject.language_arts]),
                            subject=Subject.mathematics),
    "low_time": dict(time_remaining_seconds=MIN_SECONDS_FOR_LONG_FORM_TASK - 1),
    "setting_off": dict(config=dict(practice_offers="off")),
    "approved_only": dict(config=dict(practice_offers="approved_only")),
    **{f"area_{a}": dict(area=a) for a in k2_practice.AREAS if a != "phonics"},
    "area_invented": dict(area="dragons"),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("case", sorted(_REFUSALS))
async def test_each_limit_refuses_at_prompt_build_and_at_dispatch(case, audit_calls):
    spec = _REFUSALS[case]
    config = _config(**spec.get("config", {}))
    subject = spec.get("subject", Subject.language_arts)
    area = spec.get("area", "phonics")
    kw = dict(demo_code=spec.get("demo_code"), time_remaining_seconds=spec.get("time_remaining_seconds"))
    if area == "phonics":
        # Prompt build: no invitation.
        assert "<practice>" not in await _prompt(config, subject, session_id=SESSION, **kw)
    assert not ai_service._practice_allowed(config, subject, kw["demo_code"], [], area,
                                            time_remaining_seconds=kw["time_remaining_seconds"],
                                            session_id=SESSION)
    # Dispatch: a call the prompt did not invite reaches no child.
    tools, system = await _dispatch(config, subject, area, **kw)
    assert tools == [], case
    if area == "phonics":
        assert "<practice>" not in system
    else:
        # The note offers only what is built.
        assert "offered a short practice round in: phonics." in " ".join(system.split())
        assert area not in ai_service._practice_note(config, subject, None, [])
    assert not k2_practice.was_offered("Ada", SESSION, area)


@pytest.mark.asyncio
async def test_a_second_offer_in_one_session_is_refused_at_both_points(audit_calls):
    config = _config()
    first, _ = await _dispatch(config, Subject.language_arts)
    assert len(first) == 1
    # Same subject: the card is in the conversation.
    said = [ChatMessage(role="assistant", content=first[0]["content"])]
    assert "<practice>" not in await _prompt(config, Subject.language_arts, history=said, session_id=SESSION)
    again, system = await _dispatch(config, Subject.language_arts, history=said)
    assert again == [] and "<practice>" not in system
    # Another of its subjects, later the same session, with a fresh history.
    assert "<practice>" not in await _prompt(config, Subject.living_books, session_id=SESSION)
    later, system = await _dispatch(config, Subject.living_books)
    assert later == [] and "<practice>" not in system
    # A new session may be offered again.
    assert "<practice>" in await _prompt(config, Subject.living_books, session_id="sess-2")


@pytest.mark.asyncio
async def test_the_card_seen_in_spanish_also_counts_as_offered():
    said = [ChatMessage(role="assistant", content=_card("es"))]
    assert not ai_service._practice_allowed(_config(), Subject.language_arts, None, said, "phonics")


@pytest.mark.asyncio
async def test_time_exactly_at_the_floor_or_unknown_is_allowed():
    for remaining in (MIN_SECONDS_FOR_LONG_FORM_TASK, None):
        assert "<practice>" in await _prompt(_config(), Subject.language_arts, time_remaining_seconds=remaining)


@pytest.mark.asyncio
async def test_a_refused_call_is_suppressed_by_the_time_floor_in_the_validator_too(audit_calls):
    tools, _ = await _dispatch(_config(), Subject.language_arts, time_remaining_seconds=30)
    assert tools == []
    suppressed = [kw for e, kw in audit_calls if e == AuditEvent.TOOL_CALL_SUPPRESSED]
    assert suppressed and "tool=invite_practice" in suppressed[0]["detail"]


# ── Prompt guidance ──────────────────────────────────────────────────────────

def test_the_note_puts_the_parents_plan_first_and_says_it_is_an_invitation():
    note = ai_service._practice_note(_config(), Subject.language_arts, None, [])
    flat = " ".join(note.split())
    assert ("The parent's own plan comes first: if today's lesson focus or the note on where this "
            "subject left off points somewhere else, do not offer practice; follow the parent's plan.") in flat
    assert "if the child would rather not, carry on with the lesson" in flat
    assert "do not mention that anything is recorded" in flat
    assert "`invite_practice`" in note and "phonics" in note
