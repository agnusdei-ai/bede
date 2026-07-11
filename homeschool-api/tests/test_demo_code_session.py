"""
Regression tests for core/demo_code_session.py — the self-service, one-time
6-digit code alternative to the shared DEMO_PIN trial.
"""
import time

import core.demo_code_session as demo_code_session


def setup_function():
    """Module-level state (deliberately, per its own docstring — in-memory by
    design), so each test starts from a clean slate rather than depending on
    ordering."""
    demo_code_session._codes = {}


def test_generate_code_is_six_digits():
    code = demo_code_session.generate_code()
    assert code is not None
    assert len(code) == 6
    assert code.isdigit()


def test_generate_code_never_collides_with_outstanding_code():
    demo_code_session._codes["123456"] = {"created_at": time.time(), "message_count": 0, "redeemed": False}
    # Force the RNG to only ever produce the colliding value first, so this
    # would loop forever (or return a duplicate) if the collision check were broken.
    import unittest.mock as mock
    with mock.patch("core.demo_code_session.secrets.randbelow", side_effect=[123456, 654321]):
        code = demo_code_session.generate_code()
    assert code == "654321"


def test_generate_code_respects_max_active_codes():
    demo_code_session._MAX_ACTIVE_CODES = 1
    try:
        first = demo_code_session.generate_code()
        assert first is not None
        second = demo_code_session.generate_code()
        assert second is None
    finally:
        demo_code_session._MAX_ACTIVE_CODES = 500


def test_redeem_code_allows_first_then_blocks_second():
    code = demo_code_session.generate_code()
    assert demo_code_session.redeem_code(code) is True
    assert demo_code_session.redeem_code(code) is False


def test_redeem_code_rejects_unknown_code():
    assert demo_code_session.redeem_code("000000") is False


def test_code_exists_true_until_end_session():
    code = demo_code_session.generate_code()
    assert demo_code_session.code_exists(code) is True
    demo_code_session.end_session(code)
    assert demo_code_session.code_exists(code) is False


def test_end_session_on_unknown_code_is_a_no_op():
    demo_code_session.end_session("999999")  # must not raise


def test_record_message_has_no_cap():
    code = demo_code_session.generate_code()
    for _ in range(200):
        assert demo_code_session.record_message(code) is True


def test_record_message_rejects_unknown_code():
    assert demo_code_session.record_message("000000") is False


def test_claim_email_send_allows_first_then_blocks_second():
    code = demo_code_session.generate_code()
    assert demo_code_session.claim_email_send(code) is True
    assert demo_code_session.claim_email_send(code) is False


def test_claim_email_send_rejects_unknown_code():
    assert demo_code_session.claim_email_send("000000") is False
