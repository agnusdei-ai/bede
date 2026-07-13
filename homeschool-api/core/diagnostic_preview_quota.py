"""
Per-IP quota on the demo's diagnostic-preview feature (GET /diagnostic/summary,
POST /diagnostic/chat) — see routers/diagnostic.py.

The base demo (routers/tutor.py's /chat) is deliberately uncapped in
duration and message count (see core/demo_code_session.py's own docstring)
— a real, full-length tutoring demo is the point, not a crippled preview.
But the diagnostic engine layered on top of it is a materially heavier
feature (mastery tracking built up across a whole session, plus its own
direct-answer chat), and an uncapped diagnostic preview is the single
most abuse-prone surface for someone using the "demo" as an ongoing free
substitute for a real production deployment rather than a one-time
evaluation. Capped separately here, by IP, over a rolling window — not
per demo code, since a code is already single-session and short-lived;
the actual abuse vector is one visitor minting many fresh codes over time
specifically to keep reaching this feature for free.

Deliberately in-memory, matching demo_code_session.py's own convention —
a backend restart resetting everyone's quota is an accepted cost for a
demo-only feature with no schema/migration, same tradeoff already made
there.
"""

import time

# One "use" = the first time a given IP opens the diagnostic preview
# (summary or chat) for a particular demo code. Every subsequent call for
# that SAME code is free — a legitimate one-time evaluation naturally
# refreshes the summary and asks several chat questions, and none of that
# should burn extra quota. Set to the top of the product-decided "1-3x"
# range: generous enough that a parent can look twice (e.g. show a
# spouse) without feeling capped mid-evaluation, strict enough that
# sustained real abuse (treating the demo as ongoing free production)
# would require minting a fresh code for essentially every single use,
# for no real gain over just signing up for production.
DIAGNOSTIC_PREVIEW_QUOTA = 3

_WINDOW_SECONDS = 30 * 24 * 60 * 60  # rolling 30 days

# ip -> [(code, first_used_at), ...] — one entry per distinct code this IP
# has ever opened the diagnostic preview for, within the current window.
_usage: dict[str, list[tuple[str, float]]] = {}


def _prune(ip: str) -> None:
    """Drops entries older than the rolling window, and the IP's whole
    entry once nothing recent is left — same eviction shape as
    demo_code_session.py's _evict_expired, so this dict can't grow
    forever either."""
    now = time.time()
    entries = _usage.get(ip)
    if not entries:
        return
    fresh = [(code, ts) for code, ts in entries if now - ts < _WINDOW_SECONDS]
    if fresh:
        _usage[ip] = fresh
    else:
        del _usage[ip]


def has_quota(ip: str, code: str) -> bool:
    """True if this IP may open the diagnostic preview for `code` right
    now — either it already has (free re-access to the same session), or
    it hasn't used up DIAGNOSTIC_PREVIEW_QUOTA distinct codes yet within
    the current rolling window."""
    _prune(ip)
    entries = _usage.get(ip, [])
    if any(c == code for c, _ in entries):
        return True
    return len(entries) < DIAGNOSTIC_PREVIEW_QUOTA


def record_use(ip: str, code: str) -> None:
    """Records that this IP opened the diagnostic preview for `code` —
    idempotent per (ip, code) pair, so repeated calls within the same
    already-permitted session never consume extra quota. Callers should
    only call this after has_quota() has already confirmed access is
    allowed (routers/diagnostic.py's _require_diagnostic_quota does both
    together)."""
    _prune(ip)
    entries = _usage.setdefault(ip, [])
    if not any(c == code for c, _ in entries):
        entries.append((code, time.time()))
