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

Deliberately not persisted to the database — it resets on server restart,
which is fine here since this tracks nothing but "which login is currently
allowed to keep using the shared trial," not any real user data.
"""

_active_jti: str | None = None


def start_new_session(jti: str) -> None:
    """Called on every successful demo login — supersedes any prior session."""
    global _active_jti
    _active_jti = jti


def is_active(jti: str) -> bool:
    """True if this token's session id is still the current one."""
    return _active_jti is not None and _active_jti == jti


def end_session(jti: str) -> None:
    """
    Called on explicit logout — clears the active session so this token (and
    any copy of it) stops working immediately, rather than waiting out its
    remaining 15-minute expiry. Only clears if it's still the current session,
    so a stale logout can't accidentally clobber a newer login.
    """
    global _active_jti
    if _active_jti == jti:
        _active_jti = None
