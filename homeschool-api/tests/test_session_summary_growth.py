"""
Real check for generate_session_summary's new Math Skill Growth section
(services/ai_service.py) — the parent-facing before/after report built
from services.diagnostic.get_session_growth, the read-back half of the
diagnostic evidence log (see tests/diagnostic/test_session_growth.py for
that function's own tests). This file only checks the wiring: growth data
reaches the prompt sent to Claude, in the right conditions, and is
correctly withheld otherwise — not the diagnostic math itself.

get_session_growth is patched at its defining module (services.diagnostic)
rather than on ai_service, since generate_session_summary imports it
locally (`from services.diagnostic import get_session_growth`) inside the
function body — patching the module attribute is what that late import
actually resolves at call time.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from models.schemas import ChatMessage, GradeStage, SessionConfig, SessionSummaryRequest, Subject
from services import ai_service

_FAKE_GROWTH = [
    {
        "skill_id": "cc.rote_count_20",
        "label": "Counting to 20",
        "domain": "counting_cardinality",
        "before": 0.42,
        "after": 0.61,
        "before_level": "developing",
        "after_level": "developing",
    },
]


def _fake_response(text: str = "A lovely summary."):
    return SimpleNamespace(
        content=[SimpleNamespace(text=text)],
        usage=SimpleNamespace(input_tokens=900, output_tokens=250),
    )


def _req(subjects_completed=None, locale_subjects=None) -> SessionSummaryRequest:
    return SessionSummaryRequest(
        session_config=SessionConfig(student_name="Emma", grade="1", grade_stage=GradeStage.core_mastery),
        conversation_history=[ChatMessage(role="user", content="hi")],
        subjects_completed=subjects_completed or [Subject.mathematics],
        duration_minutes=30,
    )


@pytest.mark.asyncio
async def test_growth_section_added_when_math_covered_and_db_given():
    mock_create = AsyncMock(return_value=_fake_response())
    with patch.object(ai_service._client.messages, "create", mock_create), \
         patch("services.diagnostic.get_session_growth", AsyncMock(return_value=_FAKE_GROWTH)), \
         patch("core.api_usage.record_usage", AsyncMock()):
        await ai_service.generate_session_summary(_req(), db=object())

    prompt = mock_create.await_args.kwargs["messages"][0]["content"]
    assert "Math Skill Growth" in prompt
    assert "Counting to 20" in prompt
    assert "42%" in prompt and "61%" in prompt


@pytest.mark.asyncio
async def test_no_growth_section_when_db_is_none():
    mock_create = AsyncMock(return_value=_fake_response())
    mock_growth = AsyncMock(return_value=_FAKE_GROWTH)
    with patch.object(ai_service._client.messages, "create", mock_create), \
         patch("services.diagnostic.get_session_growth", mock_growth), \
         patch("core.api_usage.record_usage", AsyncMock()):
        await ai_service.generate_session_summary(_req())  # db defaults to None

    mock_growth.assert_not_awaited()
    prompt = mock_create.await_args.kwargs["messages"][0]["content"]
    assert "Math Skill Growth" not in prompt


@pytest.mark.asyncio
async def test_no_growth_section_when_mathematics_not_covered():
    mock_create = AsyncMock(return_value=_fake_response())
    mock_growth = AsyncMock(return_value=_FAKE_GROWTH)
    with patch.object(ai_service._client.messages, "create", mock_create), \
         patch("services.diagnostic.get_session_growth", mock_growth), \
         patch("core.api_usage.record_usage", AsyncMock()):
        await ai_service.generate_session_summary(_req(subjects_completed=[Subject.science]), db=object())

    mock_growth.assert_not_awaited()
    prompt = mock_create.await_args.kwargs["messages"][0]["content"]
    assert "Math Skill Growth" not in prompt


@pytest.mark.asyncio
async def test_no_growth_section_when_nothing_moved_this_session():
    mock_create = AsyncMock(return_value=_fake_response())
    with patch.object(ai_service._client.messages, "create", mock_create), \
         patch("services.diagnostic.get_session_growth", AsyncMock(return_value=[])), \
         patch("core.api_usage.record_usage", AsyncMock()):
        await ai_service.generate_session_summary(_req(), db=object())

    prompt = mock_create.await_args.kwargs["messages"][0]["content"]
    assert "Math Skill Growth" not in prompt


@pytest.mark.asyncio
async def test_growth_lookup_failure_degrades_to_no_section_not_a_crash():
    mock_create = AsyncMock(return_value=_fake_response())
    with patch.object(ai_service._client.messages, "create", mock_create), \
         patch("services.diagnostic.get_session_growth", AsyncMock(side_effect=RuntimeError("boom"))), \
         patch("core.api_usage.record_usage", AsyncMock()):
        summary = await ai_service.generate_session_summary(_req(), db=object())

    assert summary == "A lovely summary."
    prompt = mock_create.await_args.kwargs["messages"][0]["content"]
    assert "Math Skill Growth" not in prompt


@pytest.mark.asyncio
async def test_growth_section_present_alongside_a_non_english_locale():
    """The growth facts (skill labels, numbers) go to the model as data to
    report natively in whatever locale the summary is being written in —
    not a fixed English block bolted onto a translated report (see
    generate_session_summary's own docstring)."""
    mock_create = AsyncMock(return_value=_fake_response())
    with patch.object(ai_service._client.messages, "create", mock_create), \
         patch("services.diagnostic.get_session_growth", AsyncMock(return_value=_FAKE_GROWTH)), \
         patch("core.api_usage.record_usage", AsyncMock()):
        await ai_service.generate_session_summary(_req(), locale="es", db=object())

    prompt = mock_create.await_args.kwargs["messages"][0]["content"]
    assert "Math Skill Growth" in prompt
    assert "Spanish (Español)" in prompt
