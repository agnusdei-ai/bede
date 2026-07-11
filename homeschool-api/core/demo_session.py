"""
In-memory single-active-session tracking for the "demo" auth role.

The demo PIN is shared and public by design — without this, an unlimited
number of people could each log in with the same PIN and run concurrent
15-minute sessions against the operator's real Anthropic key at the same
time. Each successful demo login replaces the one active session id; any
older demo token is rejected on its very next request, even though it
hasn't reached its own 15-minute expiry yet. This makes the login "unique"
in the sense that matters for cost control: at most one demo session is
usable at any given moment, no matter how many people know the PIN.

Also enforces the 5-minute inactivity timeout SERVER-SIDE, not just in the
frontend's timer. The frontend timer is UX only — it can't be trusted as the
actual security boundary (a stalled tab, a browser's back-forward cache
restoring old JS state, or simply a bug can leave it running long past where
it should've fired). Every authenticated demo request touches the activity
clock; is_active() checks it before the touch, so a request that arrives
after 5+ silent minutes is rejected regardless of what the client believes
its own state is.

Deliberately not persisted to the database — it resets on server restart,
which is fine here since this tracks nothing but "which login is currently
allowed to keep using the shared trial," not any real user data.
"""

import time

_INACTIVITY_TIMEOUT_SECONDS = 5 * 60
# Same cap as the self-service code tier (core/demo_code_session.py) — the
# trial ends at 15 minutes OR this many messages, whichever comes first, so
# a rapid-fire visitor can't run up cost just by staying under the clock.
_MAX_MESSAGES_PER_SESSION = 50

_active_jti: str | None = None
_last_activity: float | None = None
_message_count = 0
# jti of the demo session that has already sent its one allowed diagnostic
# email, if any — a shared public trial shouldn't let a single login send
# unlimited emails through the operator's Resend account.
_email_sent_jti: str | None = None


def start_new_session(jti: str) -> None:
    """Called on every successful demo login — supersedes any prior session."""
    global _active_jti, _last_activity, _message_count, _email_sent_jti
    _active_jti = jti
    _last_activity = time.time()
    _message_count = 0
    _email_sent_jti = None


def is_active(jti: str) -> bool:
    """True if this token's session id is still current AND hasn't been
    idle for 5+ minutes. Checked before touch() records this request, so an
    inactivity-expired request is rejected even though it's the one that
    would otherwise refresh the clock."""
    if _active_jti is None or _active_jti != jti:
        return False
    if _last_activity is not None and (time.time() - _last_activity) > _INACTIVITY_TIMEOUT_SECONDS:
        return False
    return True


def touch(jti: str) -> None:
    """Call on every successful authenticated request for this session —
    resets the 5-minute inactivity clock. Only updates if it's still the
    current session, so a stale/superseded token can't revive itself."""
    global _last_activity
    if _active_jti == jti:
        _last_activity = time.time()


def end_session(jti: str) -> None:
    """
    Called on explicit logout — clears the active session so this token (and
    any copy of it) stops working immediately, rather than waiting out its
    remaining 15-minute expiry. Only clears if it's still the current session,
    so a stale logout can't accidentally clobber a newer login.
    """
    global _active_jti, _last_activity, _email_sent_jti
    if _active_jti == jti:
        _active_jti = None
        _last_activity = None
        _email_sent_jti = None


def record_message(jti: str) -> bool:
    """Call once per actual chat message sent. Returns False (and does not
    increment) once the session's message cap is reached OR jti is no longer
    the active session, so a denied/stale request never consumes quota."""
    global _message_count
    if _active_jti != jti:
        return False
    if _message_count >= _MAX_MESSAGES_PER_SESSION:
        return False
    _message_count += 1
    return True


def remaining_messages(jti: str) -> int:
    if _active_jti != jti:
        return 0
    return max(0, _MAX_MESSAGES_PER_SESSION - _message_count)


def claim_email_send(jti: str) -> bool:
    """
    Returns True the first time this demo session's jti calls it, False on
    every call after — the shared public trial gets exactly one diagnostic
    email send per login, not per request, so a visitor can't loop the send
    button to spam an address or run up the operator's Resend usage. Callers
    should only actually send the email after this returns True.

    Also requires jti to still be the active session, same as touch() — a
    stale/superseded jti must never be able to claim just because a newer
    session hasn't sent its email yet.
    """
    global _email_sent_jti
    if _active_jti != jti:
        return False
    if _email_sent_jti == jti:
        return False
    _email_sent_jti = jti
    return True
