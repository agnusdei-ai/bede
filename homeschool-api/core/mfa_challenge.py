"""
In-memory challenge tracking for WebAuthn ceremonies (registration and
login). Single-family app — at most one parent, so only one ceremony is ever
in flight at a time; no per-session table needed.

A challenge is popped (read-and-cleared) the moment it's used, so a captured
response can't be replayed against a second verify call. Also expires on its
own after a short TTL in case a ceremony is abandoned mid-flight. Deliberately
not persisted to the database — like core/demo_session.py, this tracks
nothing but "which challenge is currently outstanding," not any real user
data, so resetting on restart is harmless.
"""

import time

_CHALLENGE_TTL_SECONDS = 120

_register_challenge: tuple[bytes, float] | None = None
_authenticate_challenge: tuple[bytes, float] | None = None


def _pop(current: tuple[bytes, float] | None) -> bytes | None:
    if current is None:
        return None
    challenge, expires_at = current
    if time.time() > expires_at:
        return None
    return challenge


def set_register_challenge(challenge: bytes) -> None:
    global _register_challenge
    _register_challenge = (challenge, time.time() + _CHALLENGE_TTL_SECONDS)


def pop_register_challenge() -> bytes | None:
    global _register_challenge
    challenge = _pop(_register_challenge)
    _register_challenge = None
    return challenge


def set_authenticate_challenge(challenge: bytes) -> None:
    global _authenticate_challenge
    _authenticate_challenge = (challenge, time.time() + _CHALLENGE_TTL_SECONDS)


def pop_authenticate_challenge() -> bytes | None:
    global _authenticate_challenge
    challenge = _pop(_authenticate_challenge)
    _authenticate_challenge = None
    return challenge


# TOTP codes are valid for a whole 30s time-step, so unlike a WebAuthn
# challenge they're not inherently single-use. Track the last accepted step
# so the same code can't be replayed again within its own window.
_last_totp_step: int | None = None


def totp_step_already_used(step: int) -> bool:
    return _last_totp_step is not None and step <= _last_totp_step


def mark_totp_step_used(step: int) -> None:
    global _last_totp_step
    _last_totp_step = step
