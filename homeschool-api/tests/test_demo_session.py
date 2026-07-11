"""
Regression tests for core/demo_session.py — the shared public-demo's
single-active-session and one-email-per-session enforcement.

test_claim_email_send_rejects_stale_jti pins down a real bug caught during
development: claim_email_send() originally didn't check whether the caller's
jti was still the *active* session, so a stale/superseded token could still
claim an email send as long as a newer session hadn't claimed one yet.
"""
import core.demo_session as demo_session


def setup_function():
    """core/demo_session.py uses module-level state (deliberately, per its
    own docstring — it's in-memory by design), so each test starts from a
    clean slate rather than depending on ordering."""
    demo_session._active_jti = None
    demo_session._last_activity = None
    demo_session._message_count = 0
    demo_session._email_sent_jti = None


def test_new_session_supersedes_old_one():
    demo_session.start_new_session("jti-A")
    assert demo_session.is_active("jti-A") is True

    demo_session.start_new_session("jti-B")
    assert demo_session.is_active("jti-B") is True
    assert demo_session.is_active("jti-A") is False


def test_touch_only_updates_current_session():
    demo_session.start_new_session("jti-A")
    demo_session.start_new_session("jti-B")
    demo_session.touch("jti-A")  # stale — should be a no-op
    assert demo_session.is_active("jti-B") is True


def test_end_session_only_clears_if_still_current():
    demo_session.start_new_session("jti-A")
    demo_session.start_new_session("jti-B")
    demo_session.end_session("jti-A")  # stale logout — must not clobber jti-B
    assert demo_session.is_active("jti-B") is True


def test_claim_email_send_allows_first_then_blocks_second():
    demo_session.start_new_session("jti-A")
    assert demo_session.claim_email_send("jti-A") is True
    assert demo_session.claim_email_send("jti-A") is False


def test_claim_email_send_resets_on_new_login():
    demo_session.start_new_session("jti-A")
    demo_session.claim_email_send("jti-A")
    demo_session.start_new_session("jti-B")
    assert demo_session.claim_email_send("jti-B") is True


def test_claim_email_send_rejects_stale_jti():
    """The regression this test guards against: jti-A claims a send, jti-B
    supersedes it (without itself claiming), and jti-A must NOT be able to
    still claim — even though _email_sent_jti isn't "jti-A" at that point,
    jti-A is no longer the active session at all."""
    demo_session.start_new_session("jti-A")
    demo_session.claim_email_send("jti-A")

    demo_session.start_new_session("jti-B")
    assert demo_session.claim_email_send("jti-A") is False


def test_claim_email_send_rejects_never_active_jti():
    demo_session.start_new_session("jti-A")
    assert demo_session.claim_email_send("some-other-jti") is False


def test_record_message_allows_up_to_the_cap_then_blocks():
    demo_session.start_new_session("jti-A")
    demo_session._MAX_MESSAGES_PER_SESSION = 2
    try:
        assert demo_session.record_message("jti-A") is True
        assert demo_session.record_message("jti-A") is True
        assert demo_session.record_message("jti-A") is False
    finally:
        demo_session._MAX_MESSAGES_PER_SESSION = 50


def test_record_message_denied_does_not_consume_quota():
    demo_session.start_new_session("jti-A")
    demo_session._MAX_MESSAGES_PER_SESSION = 1
    try:
        assert demo_session.record_message("jti-A") is True
        assert demo_session.record_message("jti-A") is False
        assert demo_session.record_message("jti-A") is False  # still denied, not further decremented
    finally:
        demo_session._MAX_MESSAGES_PER_SESSION = 50


def test_record_message_rejects_stale_jti():
    demo_session.start_new_session("jti-A")
    demo_session.start_new_session("jti-B")  # supersedes jti-A
    assert demo_session.record_message("jti-A") is False


def test_message_count_resets_on_new_login():
    demo_session.start_new_session("jti-A")
    demo_session.record_message("jti-A")
    demo_session.start_new_session("jti-B")
    assert demo_session.remaining_messages("jti-B") == demo_session._MAX_MESSAGES_PER_SESSION


def test_remaining_messages_counts_down():
    demo_session.start_new_session("jti-A")
    demo_session._MAX_MESSAGES_PER_SESSION = 3
    try:
        assert demo_session.remaining_messages("jti-A") == 3
        demo_session.record_message("jti-A")
        assert demo_session.remaining_messages("jti-A") == 2
    finally:
        demo_session._MAX_MESSAGES_PER_SESSION = 50


def test_remaining_messages_rejects_stale_jti():
    demo_session.start_new_session("jti-A")
    demo_session.start_new_session("jti-B")
    assert demo_session.remaining_messages("jti-A") == 0
