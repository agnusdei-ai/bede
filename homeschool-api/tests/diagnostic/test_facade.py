"""
Real check for Diagnostic build-loop unit 1.8 (services/diagnostic/__init__.py
facade) — see docs/diagnostic/DIAGNOSTIC_BUILD_PROGRESS.md. An end-to-end
in-memory round trip through process_evidence and get_next_probe_hint,
composing every prior Phase 1 unit together.
"""

import inspect

import pytest

from services.diagnostic import get_next_probe_hint, process_evidence
from services.diagnostic.mastery import new_vector


def test_process_evidence_is_a_coroutine_function():
    assert inspect.iscoroutinefunction(process_evidence)


@pytest.mark.asyncio
async def test_process_evidence_correct_outcome_increases_the_probed_skill():
    vector = new_vector("K-2")
    new, updates = await process_evidence(vector, "probe.cc.rote_count_20", "correct", confidence=1.0)
    assert new["cc.rote_count_20"] > vector["cc.rote_count_20"]
    assert len(updates) == 1
    assert updates[0].skill_id == "cc.rote_count_20"


@pytest.mark.asyncio
async def test_process_evidence_unknown_probe_returns_vector_unchanged():
    vector = new_vector("K-2")
    new, updates = await process_evidence(vector, "not.a.real.probe", "correct", confidence=1.0)
    assert new == vector
    assert updates == []


@pytest.mark.asyncio
async def test_process_evidence_does_not_mutate_input_vector():
    vector = new_vector("K-2")
    original = dict(vector)
    await process_evidence(vector, "probe.cc.rote_count_20", "correct", confidence=1.0)
    assert vector == original


def test_get_next_probe_hint_returns_nonempty_string_for_a_fresh_vector():
    vector = new_vector("K-2")
    hint = get_next_probe_hint(vector, theta={}, grade_band="K-2", calibration=False)
    assert isinstance(hint, str)
    assert hint  # non-empty


def test_get_next_probe_hint_fallback_message_for_an_empty_vector():
    hint = get_next_probe_hint({}, theta={}, grade_band="K-2", calibration=False)
    assert hint == "No specific skills flagged for probing right now — tutor normally."


def test_get_next_probe_hint_mentions_a_real_skill_description():
    vector = {"cc.rote_count_20": 0.5}
    hint = get_next_probe_hint(vector, theta={}, grade_band="K-2", calibration=False)
    assert "rote counts to 20" in hint.lower()


@pytest.mark.asyncio
async def test_end_to_end_round_trip_hint_reflects_accumulated_evidence():
    """The full Phase 1 composition in one pass: cold-start a vector,
    feed real evidence through process_evidence, and confirm
    get_next_probe_hint's guidance actually reflects what's been learned
    — it should stop suggesting a skill once evidence has secured it."""
    vector = new_vector("K-2")

    hint_before = get_next_probe_hint(vector, theta={}, grade_band="K-2", calibration=False)
    assert "rote counts to 20" in hint_before.lower()

    for _ in range(8):
        vector, _ = await process_evidence(
            vector, "probe.cc.rote_count_20", "correct", confidence=1.0, calibration_weight=2.0
        )

    assert vector["cc.rote_count_20"] >= 0.8

    hint_after = get_next_probe_hint(vector, theta={}, grade_band="K-2", calibration=False)
    assert "rote counts to 20" not in hint_after.lower()
