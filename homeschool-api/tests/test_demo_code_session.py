"""
Regression tests for core/demo_code_session.py — the self-service, one-time
6-digit code alternative to the shared DEMO_PIN trial. Postgres-backed (see
core.database.DemoCodeSession) rather than an in-memory dict, so every test
here runs against the isolated per-test SQLite engine the `demo_db` fixture
(tests/conftest.py) swaps in for core.database.AsyncSessionLocal.
"""
import pytest

import core.demo_code_session as demo_code_session

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("demo_db")]


async def test_generate_code_is_six_digits():
    code = await demo_code_session.generate_code()
    assert code is not None
    assert len(code) == 6
    assert code.isdigit()


async def test_generate_code_never_collides_with_outstanding_code():
    from core.database import AsyncSessionLocal, DemoCodeSession

    async with AsyncSessionLocal() as db:
        db.add(DemoCodeSession(code="123456"))
        await db.commit()

    # Force the RNG to only ever produce the colliding value first, so this
    # would loop forever (or return a duplicate) if the collision check were broken.
    import unittest.mock as mock
    with mock.patch("core.demo_code_session.secrets.randbelow", side_effect=[123456, 654321]):
        code = await demo_code_session.generate_code()
    assert code == "654321"


async def test_generate_code_respects_max_active_codes():
    demo_code_session._MAX_ACTIVE_CODES = 1
    try:
        first = await demo_code_session.generate_code()
        assert first is not None
        second = await demo_code_session.generate_code()
        assert second is None
    finally:
        demo_code_session._MAX_ACTIVE_CODES = 500


async def test_redeem_code_allows_first_then_blocks_second():
    code = await demo_code_session.generate_code()
    assert await demo_code_session.redeem_code(code) is True
    assert await demo_code_session.redeem_code(code) is False


async def test_redeem_code_rejects_unknown_code():
    assert await demo_code_session.redeem_code("000000") is False


async def test_code_exists_true_until_end_session():
    code = await demo_code_session.generate_code()
    assert await demo_code_session.code_exists(code) is True
    await demo_code_session.end_session(code)
    assert await demo_code_session.code_exists(code) is False


async def test_end_session_on_unknown_code_is_a_no_op():
    await demo_code_session.end_session("999999")  # must not raise


async def test_record_message_has_no_cap():
    code = await demo_code_session.generate_code()
    for _ in range(200):
        assert await demo_code_session.record_message(code) is True


async def test_record_message_rejects_unknown_code():
    assert await demo_code_session.record_message("000000") is False


async def test_claim_email_send_allows_first_then_blocks_second():
    code = await demo_code_session.generate_code()
    assert await demo_code_session.claim_email_send(code) is True
    assert await demo_code_session.claim_email_send(code) is False


async def test_claim_email_send_rejects_unknown_code():
    assert await demo_code_session.claim_email_send("000000") is False


async def test_get_personalization_round_trips_name_and_grade():
    code = await demo_code_session.generate_code(student_name="Ellie", grade="5")
    assert await demo_code_session.get_personalization(code) == ("Ellie", "5")


async def test_get_personalization_defaults_to_none_when_not_provided():
    code = await demo_code_session.generate_code()
    assert await demo_code_session.get_personalization(code) == (None, None)


async def test_get_personalization_unknown_code_returns_none_none():
    assert await demo_code_session.get_personalization("000000") == (None, None)
