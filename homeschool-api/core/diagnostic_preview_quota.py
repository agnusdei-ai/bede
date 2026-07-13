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

Backed by core.database.DiagnosticPreviewUse (Postgres), matching
core/demo_code_session.py's own move off in-memory storage — a backend
restart no longer resets everyone's quota, closing the same "in-flight
session data lost on restart" gap for this feature too. Every function
here follows core/audit.py's self-contained-session convention: each opens
its own AsyncSessionLocal() rather than taking a `db` parameter.

IP addresses are never written to the table in plaintext — see
DiagnosticPreviewUse's own docstring in core/database.py for why moving
this off an ephemeral in-memory dict onto a durable row made that a real
new exposure worth closing, not just carrying over. _hash_ip() below is
applied at every call site that touches the DB; has_quota()/record_use()'s
own `ip` parameter stays a real IP string throughout — callers
(routers/diagnostic.py) never need to know hashing happens at all.
"""

import hashlib
import hmac as hmac_module
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from core.config import settings


def _hash_ip(ip: str) -> str:
    """Keyed HMAC-SHA256, not a bare hash — an unkeyed hash of an IP is
    reversible in practice (the input space is tiny; a rainbow table over
    every IPv4 address is trivial), which would defeat the point. Keyed on
    settings.secret_key (already a strong, server-only secret used for JWT
    signing elsewhere) so only this deployment can ever produce or match
    these tokens."""
    return hmac_module.new(
        settings.secret_key.encode("utf-8"), ip.encode("utf-8"), hashlib.sha256
    ).hexdigest()

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


def _window_start() -> datetime:
    return datetime.now(timezone.utc) - timedelta(seconds=_WINDOW_SECONDS)


async def has_quota(ip: str, code: str) -> bool:
    """True if this IP may open the diagnostic preview for `code` right
    now — either it already has (free re-access to the same session), or
    it hasn't used up DIAGNOSTIC_PREVIEW_QUOTA distinct codes yet within
    the current rolling window. Read-only — pruning of this IP's own
    stale rows happens in record_use below, the one call site that
    already pays for a write."""
    from core.database import AsyncSessionLocal, DiagnosticPreviewUse

    ip_hash = _hash_ip(ip)
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(DiagnosticPreviewUse.code).where(
                DiagnosticPreviewUse.ip_hash == ip_hash,
                DiagnosticPreviewUse.used_at >= _window_start(),
            )
        )
        codes = {row[0] for row in result.all()}
        if code in codes:
            return True
        return len(codes) < DIAGNOSTIC_PREVIEW_QUOTA


async def record_use(ip: str, code: str) -> None:
    """Records that this IP opened the diagnostic preview for `code` —
    idempotent per (ip, code) pair, so repeated calls within the same
    already-permitted session never consume extra quota. Callers should
    only call this after has_quota() has already confirmed access is
    allowed (routers/diagnostic.py's _require_diagnostic_quota does both
    together)."""
    from core.database import AsyncSessionLocal, DiagnosticPreviewUse

    ip_hash = _hash_ip(ip)
    async with AsyncSessionLocal() as db:
        # Opportunistic cleanup of this IP's own stale rows — same lazy
        # eviction shape as the old in-memory _prune(), just piggybacked
        # onto the one call site that already pays for a write.
        await db.execute(
            delete(DiagnosticPreviewUse).where(
                DiagnosticPreviewUse.ip_hash == ip_hash,
                DiagnosticPreviewUse.used_at < _window_start(),
            )
        )
        existing = (await db.execute(
            select(DiagnosticPreviewUse.id).where(
                DiagnosticPreviewUse.ip_hash == ip_hash,
                DiagnosticPreviewUse.code == code,
                DiagnosticPreviewUse.used_at >= _window_start(),
            )
        )).scalar_one_or_none()
        if existing is None:
            db.add(DiagnosticPreviewUse(ip_hash=ip_hash, code=code))
            try:
                await db.commit()
            except IntegrityError:
                # Lost a race against a concurrent record_use for this
                # exact (ip, code) pair — the uq_diagnostic_preview_uses_
                # ip_hash_code constraint caught it, which means the use is
                # already recorded either way. Not an error from the
                # caller's perspective (see this function's own docstring:
                # idempotent per (ip, code)).
                await db.rollback()
        else:
            await db.commit()
