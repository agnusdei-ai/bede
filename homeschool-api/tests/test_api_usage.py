"""
Real check for core/api_usage.py — the BYOK token/cost estimate that
feeds both the per-student usage card on Progress.tsx and the household
total on GET /admin/status.

record_usage() follows core/audit.py's self-contained-session convention
(opens its own AsyncSessionLocal() internally), so — like
core/demo_code_session.py/core/diagnostic_preview_quota.py — these tests
need the demo_db fixture (tests/conftest.py) to monkeypatch
core.database.AsyncSessionLocal onto an isolated in-memory SQLite engine;
otherwise record_usage's writes would go to a completely different
(unconfigured) database than get_usage_summary's reads.
"""

import pytest
import pytest_asyncio

from core.api_usage import estimate_cost_usd, get_usage_summary, record_usage

pytestmark = pytest.mark.usefixtures("demo_db")


@pytest_asyncio.fixture
async def db_session(demo_db):
    async with demo_db() as session:
        yield session


# ── estimate_cost_usd (pure function, no DB) ────────────────────────────

def test_known_model_pricing_is_applied():
    cost = estimate_cost_usd("claude-sonnet-4-6", input_tokens=1_000_000, output_tokens=0)
    assert cost == pytest.approx(3.00)


def test_output_tokens_priced_separately_from_input():
    cost = estimate_cost_usd("claude-sonnet-4-6", input_tokens=0, output_tokens=1_000_000)
    assert cost == pytest.approx(15.00)


def test_unknown_model_falls_back_to_default_pricing_instead_of_raising():
    cost = estimate_cost_usd("some-future-model-id", input_tokens=1_000_000, output_tokens=0)
    assert cost == pytest.approx(3.00)  # same as claude-sonnet-4-6's own input price


def test_cache_read_is_priced_far_cheaper_than_a_fresh_input_token():
    fresh = estimate_cost_usd("claude-sonnet-4-6", input_tokens=1_000_000, output_tokens=0)
    cached = estimate_cost_usd("claude-sonnet-4-6", input_tokens=0, output_tokens=0, cache_read_tokens=1_000_000)
    assert cached < fresh


def test_cache_write_costs_more_than_a_fresh_input_token():
    fresh = estimate_cost_usd("claude-sonnet-4-6", input_tokens=1_000_000, output_tokens=0)
    write = estimate_cost_usd("claude-sonnet-4-6", input_tokens=0, output_tokens=0, cache_creation_tokens=1_000_000)
    assert write > fresh


def test_haiku_is_priced_cheaper_than_sonnet_for_identical_usage():
    sonnet = estimate_cost_usd("claude-sonnet-4-6", input_tokens=1000, output_tokens=1000)
    haiku = estimate_cost_usd("claude-haiku-4-5-20251001", input_tokens=1000, output_tokens=1000)
    assert haiku < sonnet


# ── record_usage / get_usage_summary (real DB round trip) ──────────────

@pytest.mark.asyncio
async def test_household_summary_is_all_zero_with_no_recorded_usage(db_session):
    summary = await get_usage_summary(db_session)
    assert summary["total_input_tokens"] == 0
    assert summary["total_output_tokens"] == 0
    assert summary["total_calls"] == 0
    assert summary["estimated_cost_usd"] == 0
    assert summary["by_model"] == []


@pytest.mark.asyncio
async def test_a_recorded_call_shows_up_in_the_household_total(db_session):
    await record_usage("Emma", "claude-sonnet-4-6", input_tokens=1000, output_tokens=200)

    summary = await get_usage_summary(db_session)
    assert summary["total_input_tokens"] == 1000
    assert summary["total_output_tokens"] == 200
    assert summary["total_calls"] == 1
    assert summary["estimated_cost_usd"] > 0


@pytest.mark.asyncio
async def test_per_student_summary_only_reflects_that_students_own_usage(db_session):
    await record_usage("Emma", "claude-sonnet-4-6", input_tokens=1000, output_tokens=200)
    await record_usage("Liam", "claude-sonnet-4-6", input_tokens=5000, output_tokens=800)

    emma = await get_usage_summary(db_session, "Emma")
    liam = await get_usage_summary(db_session, "Liam")

    assert emma["total_input_tokens"] == 1000
    assert liam["total_input_tokens"] == 5000


@pytest.mark.asyncio
async def test_sandbox_calls_with_no_student_name_count_toward_household_but_no_student(db_session):
    await record_usage(None, "claude-sonnet-4-6", input_tokens=2000, output_tokens=300)

    household = await get_usage_summary(db_session)
    assert household["total_input_tokens"] == 2000

    # A named student's own summary is unaffected by the sandbox's usage
    emma = await get_usage_summary(db_session, "Emma")
    assert emma["total_input_tokens"] == 0


@pytest.mark.asyncio
async def test_multiple_calls_for_the_same_student_accumulate(db_session):
    await record_usage("Noah", "claude-sonnet-4-6", input_tokens=100, output_tokens=50)
    await record_usage("Noah", "claude-sonnet-4-6", input_tokens=200, output_tokens=75)

    summary = await get_usage_summary(db_session, "Noah")
    assert summary["total_input_tokens"] == 300
    assert summary["total_output_tokens"] == 125
    assert summary["total_calls"] == 2


@pytest.mark.asyncio
async def test_usage_across_different_models_is_broken_out_separately(db_session):
    await record_usage("Ava", "claude-sonnet-4-6", input_tokens=1000, output_tokens=100)
    await record_usage("Ava", "claude-haiku-4-5-20251001", input_tokens=500, output_tokens=50)

    summary = await get_usage_summary(db_session, "Ava")
    models = {m["model"] for m in summary["by_model"]}
    assert models == {"claude-sonnet-4-6", "claude-haiku-4-5-20251001"}
    assert summary["total_calls"] == 2


@pytest.mark.asyncio
async def test_cache_tokens_are_persisted_and_reflected_in_the_estimate(db_session):
    await record_usage(
        "Zoe", "claude-sonnet-4-6", input_tokens=100, output_tokens=50,
        cache_creation_tokens=2000, cache_read_tokens=8000,
    )

    summary = await get_usage_summary(db_session, "Zoe")
    row = summary["by_model"][0]
    assert row["cache_creation_tokens"] == 2000
    assert row["cache_read_tokens"] == 8000
    assert row["estimated_cost_usd"] > 0
