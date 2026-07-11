"""
In-memory tracking for self-generated, single-use demo access codes — the
sole way into the public demo.

A visitor clicks one button, the backend mints a fresh 6-digit code
instantly (POST /auth/demo-code), and the frontend immediately exchanges it
for a JWT via the normal POST /auth/login (role="demo_code") — no PIN to
remember, no key to paste. The operator's real Anthropic key stays
server-side the whole time. Each code is unique to whoever generated it, so
unlike a shared PIN, concurrent visitors never collide with or invalidate
each other's sessions — no single-active-session lock needed here.

The cost-control risk instead is unbounded cost via (a) unbounded messages
on one code, or (b) unbounded codes. (a) is capped by
_MAX_MESSAGES_PER_CODE. (b) is capped by _MAX_ACTIVE_CODES, and POST
/auth/demo-code lives under /auth/ so it already inherits the existing
per-IP auth rate limit (core/middleware.py) for free.

Deliberately not persisted to the database — a code is a single-sitting
credential by design (see routers/auth.py), so losing this on restart just
means codes issued right before a restart stop working, which is an
acceptable cost for not needing a schema/migration for a demo-only feature.
"""

import secrets
import time

_MAX_MESSAGES_PER_CODE = 50
# Hygiene only, not a security boundary: forgets codes nobody ever redeemed
# (or finished using) so this dict can't grow forever from abandoned visits.
_CODE_TTL_SECONDS = 6 * 60 * 60
# Hard ceiling on how many codes can be outstanding at once, so a script
# hammering the generate endpoint can't manufacture unbounded aggregate quota
# even within the per-IP rate limit's one-minute window.
_MAX_ACTIVE_CODES = 500

_codes: dict[str, dict] = {}


def _evict_expired() -> None:
    now = time.time()
    expired = [c for c, info in _codes.items() if now - info["created_at"] > _CODE_TTL_SECONDS]
    for c in expired:
        del _codes[c]


def generate_code() -> str | None:
    """Mints a fresh 6-digit code. Returns None if _MAX_ACTIVE_CODES is
    already reached — callers should surface that as a 429."""
    _evict_expired()
    if len(_codes) >= _MAX_ACTIVE_CODES:
        return None
    while True:
        code = f"{secrets.randbelow(1_000_000):06d}"
        if code not in _codes:
            break
    _codes[code] = {"created_at": time.time(), "message_count": 0, "redeemed": False}
    return code


def redeem_code(code: str) -> bool:
    """One-time exchange of a code for a JWT (see /auth/login). Returns False
    for an unknown or already-redeemed code — a code can only ever become a
    session once, so sharing a code with someone else after you've already
    logged in with it doesn't grant them a second, independent quota."""
    info = _codes.get(code)
    if info is None or info["redeemed"]:
        return False
    info["redeemed"] = True
    return True


def code_exists(code: str) -> bool:
    """True if this code is still tracked (redeemed or not) — used by
    require_auth to reject a JWT whose code was evicted for being long
    abandoned, distinct from record_message's quota check below."""
    return code in _codes


def record_message(code: str) -> bool:
    """Call once per actual chat message sent. Returns False (and does not
    increment) once the code's message cap is reached, so a denied request
    never itself consumes quota."""
    info = _codes.get(code)
    if info is None:
        return False
    if info["message_count"] >= _MAX_MESSAGES_PER_CODE:
        return False
    info["message_count"] += 1
    return True


def remaining_messages(code: str) -> int:
    info = _codes.get(code)
    if info is None:
        return 0
    return max(0, _MAX_MESSAGES_PER_CODE - info["message_count"])


def end_session(code: str) -> None:
    """Explicit logout — deletes the code immediately so a copied/leaked
    token stops working right away instead of riding out its remaining
    expiry, and frees its _MAX_ACTIVE_CODES slot. Safe to call with an
    unknown code (no-op)."""
    _codes.pop(code, None)


def claim_email_send(code: str) -> bool:
    """One diagnostic email send allowed per code, ever."""
    info = _codes.get(code)
    if info is None:
        return False
    if info.get("email_sent"):
        return False
    info["email_sent"] = True
    return True
