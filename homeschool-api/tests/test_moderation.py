"""
AIUC-1 B005 — services/moderation.py's classify_child_message(). The
deterministic regexes (_INJECTION_PATTERN, check_safeguarding) are fast
and free but only catch phrasing someone already wrote a pattern for;
this is the broader, real classifier layer AIUC-1's "automated moderation
tools" language calls for. Covers: category/confidence -> should_block
logic, markdown-fence-wrapped JSON parsing (matches generate_session_
summary's existing pattern), fail-open behavior on every kind of failure
(API error, timeout, malformed JSON), and sentinel/empty-message skipping.
"""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from services import ai_service
from services.moderation import classify_child_message

pytestmark = pytest.mark.asyncio


def _fake_response(payload: dict, wrap_in_fences: bool = False) -> MagicMock:
    text = json.dumps(payload)
    if wrap_in_fences:
        text = f"```json\n{text}\n```"
    response = MagicMock()
    response.content = [MagicMock(text=text)]
    response.usage = MagicMock(input_tokens=42, output_tokens=8)
    return response


async def test_skips_sentinel_messages_without_calling_the_api(monkeypatch):
    mock_create = AsyncMock(side_effect=AssertionError("must not be called"))
    monkeypatch.setattr(ai_service._client.messages, "create", mock_create)

    for sentinel in ("[START]", "[CONTINUE]", ""):
        result = await classify_child_message(sentinel)
        assert result == {"flagged": False, "categories": [], "confidence": "low", "should_block": False}
    mock_create.assert_not_called()


async def test_not_flagged_response_never_blocks(monkeypatch):
    monkeypatch.setattr(
        ai_service._client.messages, "create",
        AsyncMock(return_value=_fake_response({"flagged": False, "categories": [], "confidence": "low"})),
    )
    result = await classify_child_message("What is 7 times 8?")
    assert result["flagged"] is False
    assert result["should_block"] is False


@pytest.mark.parametrize("categories,confidence,expected_block", [
    (["self_harm"], "high", True),
    (["self_harm"], "medium", True),
    (["self_harm"], "low", False),  # confidence too low to act on
    (["violence"], "high", True),
    (["sexual_content"], "medium", True),
    (["hate_or_harassment"], "high", True),
    (["prompt_injection"], "high", False),  # never blocks alone, by design
    (["prompt_injection", "self_harm"], "high", True),  # blocks because self_harm is present too
    ([], "high", False),
])
async def test_should_block_logic(monkeypatch, categories, confidence, expected_block):
    monkeypatch.setattr(
        ai_service._client.messages, "create",
        AsyncMock(return_value=_fake_response(
            {"flagged": bool(categories), "categories": categories, "confidence": confidence}
        )),
    )
    result = await classify_child_message("some message")
    assert result["should_block"] is expected_block
    assert result["categories"] == categories


async def test_strips_markdown_fences_around_json(monkeypatch):
    monkeypatch.setattr(
        ai_service._client.messages, "create",
        AsyncMock(return_value=_fake_response(
            {"flagged": True, "categories": ["violence"], "confidence": "high"}, wrap_in_fences=True,
        )),
    )
    result = await classify_child_message("some message")
    assert result["flagged"] is True
    assert result["should_block"] is True


async def test_fails_open_on_api_error(monkeypatch):
    monkeypatch.setattr(
        ai_service._client.messages, "create",
        AsyncMock(side_effect=RuntimeError("simulated Anthropic API failure")),
    )
    result = await classify_child_message("some message")
    assert result == {"flagged": False, "categories": [], "confidence": "low", "should_block": False}


async def test_fails_open_on_timeout(monkeypatch):
    import asyncio

    async def _hangs(*args, **kwargs):
        await asyncio.sleep(10)

    monkeypatch.setattr(ai_service._client.messages, "create", _hangs)
    monkeypatch.setattr("services.moderation._TIMEOUT_SECONDS", 0.05)

    result = await classify_child_message("some message")
    assert result == {"flagged": False, "categories": [], "confidence": "low", "should_block": False}


async def test_fails_open_on_malformed_json(monkeypatch):
    response = MagicMock()
    response.content = [MagicMock(text="not valid json at all")]
    response.usage = MagicMock(input_tokens=1, output_tokens=1)
    monkeypatch.setattr(ai_service._client.messages, "create", AsyncMock(return_value=response))

    result = await classify_child_message("some message")
    assert result == {"flagged": False, "categories": [], "confidence": "low", "should_block": False}


async def test_usage_recording_failure_does_not_break_classification(monkeypatch):
    """Mirrors generate_session_summary's own try/except around record_usage
    — a usage-tracking hiccup must never take down the actual classification."""
    monkeypatch.setattr(
        ai_service._client.messages, "create",
        AsyncMock(return_value=_fake_response({"flagged": False, "categories": [], "confidence": "low"})),
    )
    monkeypatch.setattr(
        "core.api_usage.record_usage", AsyncMock(side_effect=RuntimeError("simulated DB failure")),
    )
    result = await classify_child_message("some message", student_name="Sam")
    assert result["flagged"] is False
