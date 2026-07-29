"""
Real check for core/api_usage.py's get_loop_stats — the timestamp-gap
approximation of stream_tutor_response's tool_result loop (see
ai_service.py's _MAX_TOOL_LOOP_ROUNDS) behind
GET /admin/agentic-loop-stats.

Inserts ApiUsageEvent rows directly (bypassing record_usage's
datetime.now() default) so each test controls exact timestamps and can
assert deterministic bucketing — same direct-DB-object pattern as
tests/test_record_skill_evidence.py.
"""
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from core.api_usage import _TURN_GAP_SECONDS, get_loop_stats
from core.config import settings
from core.database import ApiUsageEvent
from routers.admin import agentic_loop_stats

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("demo_db")]


@pytest_asyncio.fixture
async def db_session(demo_db):
    async with demo_db() as session:
        yield session


_BASE = datetime.now(timezone.utc) - timedelta(hours=1)


def _row(student_name, offset_seconds, model=None, **overrides):
    # A single fixed anchor shared by every call (not datetime.now() per
    # call) — otherwise two _row() calls meant to be exactly
    # _TURN_GAP_SECONDS apart would drift by however long Python took
    # between the two statements, which is exactly the flakiness that
    # broke the boundary test this comment replaces.
    base = _BASE
    defaults = dict(
        student_name=student_name,
        model=model or settings.tutor_model,
        input_tokens=500,
        output_tokens=100,
        cache_creation_tokens=0,
        cache_read_tokens=0,
        created_at=base + timedelta(seconds=offset_seconds),
    )
    defaults.update(overrides)
    return ApiUsageEvent(**defaults)


async def _insert(db, *rows):
    for row in rows:
        db.add(row)
    await db.commit()


async def test_no_data_returns_an_all_zero_result(db_session):
    stats = await get_loop_stats(db_session)
    assert stats["turns_analyzed"] == 0
    assert stats["multi_round_turns"] == 0
    assert stats["round_distribution"] == {}
    assert stats["extra_round_estimated_cost_usd"] == 0.0


async def test_single_round_turns_never_count_as_multi_round(db_session):
    """Two ordinary, well-separated turns — each just one API call — must
    never be misread as one multi-round turn."""
    await _insert(
        db_session,
        _row("Emma", 0),
        _row("Emma", 300),  # 5 minutes later — a real second turn
    )

    stats = await get_loop_stats(db_session)
    assert stats["turns_analyzed"] == 2
    assert stats["multi_round_turns"] == 0
    assert stats["round_distribution"] == {1: 2}


async def test_rows_within_the_gap_cluster_into_one_multi_round_turn(db_session):
    await _insert(
        db_session,
        _row("Emma", 0),
        _row("Emma", 2),  # well within _TURN_GAP_SECONDS
        _row("Emma", 300),  # a separate, later turn
    )

    stats = await get_loop_stats(db_session)
    assert stats["turns_analyzed"] == 2
    assert stats["multi_round_turns"] == 1
    assert stats["round_distribution"] == {2: 1, 1: 1}
    assert stats["max_rounds_seen"] == 2
    assert stats["avg_added_latency_seconds"] == pytest.approx(2.0)


async def test_gap_exactly_at_the_threshold_still_clusters(db_session):
    await _insert(
        db_session,
        _row("Emma", 0),
        _row("Emma", _TURN_GAP_SECONDS),
    )
    stats = await get_loop_stats(db_session)
    assert stats["turns_analyzed"] == 1
    assert stats["multi_round_turns"] == 1


async def test_gap_just_past_the_threshold_does_not_cluster(db_session):
    await _insert(
        db_session,
        _row("Emma", 0),
        _row("Emma", _TURN_GAP_SECONDS + 0.5),
    )
    stats = await get_loop_stats(db_session)
    assert stats["turns_analyzed"] == 2
    assert stats["multi_round_turns"] == 0


async def test_different_students_never_cluster_together_even_back_to_back(db_session):
    await _insert(
        db_session,
        _row("Emma", 0),
        _row("Liam", 1),  # 1 second later, but a different student
    )
    stats = await get_loop_stats(db_session)
    assert stats["turns_analyzed"] == 2
    assert stats["multi_round_turns"] == 0


async def test_non_tutor_model_rows_are_excluded(db_session):
    """Session summaries / learner-profile synthesis use settings.session_model
    (Haiku) and must never be mistaken for tutor-loop rounds."""
    await _insert(
        db_session,
        _row("Emma", 0),
        _row("Emma", 2, model=settings.session_model),
    )
    stats = await get_loop_stats(db_session)
    assert stats["turns_analyzed"] == 1
    assert stats["multi_round_turns"] == 0


async def test_sandbox_rows_with_no_student_name_are_excluded(db_session):
    await _insert(db_session, _row(None, 0), _row(None, 2))
    stats = await get_loop_stats(db_session)
    assert stats["turns_analyzed"] == 0


async def test_rows_older_than_the_window_are_excluded(db_session):
    old = ApiUsageEvent(
        student_name="Emma", model=settings.tutor_model,
        input_tokens=500, output_tokens=100,
        created_at=datetime.now(timezone.utc) - timedelta(days=45),
    )
    await _insert(db_session, old)

    stats = await get_loop_stats(db_session, days=30)
    assert stats["turns_analyzed"] == 0


async def test_extra_round_cost_only_counts_rounds_after_the_first(db_session):
    await _insert(
        db_session,
        _row("Emma", 0, input_tokens=1000, output_tokens=200),
        _row("Emma", 2, input_tokens=300, output_tokens=50),
    )
    stats = await get_loop_stats(db_session)

    from core.api_usage import estimate_cost_usd
    expected = estimate_cost_usd(settings.tutor_model, 300, 50)
    assert stats["extra_round_estimated_cost_usd"] == pytest.approx(round(expected, 4))


async def test_three_round_turn_is_reflected_in_round_distribution(db_session):
    await _insert(
        db_session,
        _row("Emma", 0),
        _row("Emma", 1),
        _row("Emma", 2),
    )
    stats = await get_loop_stats(db_session)
    assert stats["turns_analyzed"] == 1
    assert stats["max_rounds_seen"] == 3
    assert stats["round_distribution"] == {3: 1}
    assert stats["avg_rounds_per_turn"] == pytest.approx(3.0)


# ── router endpoint ──────────────────────────────────────────────────────

async def test_endpoint_returns_zeroed_stats_with_nothing_recorded(db_session):
    stats = await agentic_loop_stats(db=db_session, _={"role": "parent"})
    assert stats.turns_analyzed == 0
    assert stats.window_days == 30


async def test_endpoint_caps_days_at_90(db_session):
    stats = await agentic_loop_stats(days=99999, db=db_session, _={"role": "parent"})
    assert stats.window_days == 90


async def test_endpoint_rejects_a_non_positive_days_value_by_flooring_to_one(db_session):
    stats = await agentic_loop_stats(days=-5, db=db_session, _={"role": "parent"})
    assert stats.window_days == 1
