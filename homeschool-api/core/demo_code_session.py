"""
Postgres-backed tracking for self-generated, single-use demo access codes —
the sole way into the public demo.

A visitor clicks one button, the backend mints a fresh 6-digit code
instantly (POST /auth/demo-code), and the frontend immediately exchanges it
for a JWT via the normal POST /auth/login (role="demo_code") — no PIN to
remember, no key to paste. The operator's real Anthropic key stays
server-side the whole time. Each code is unique to whoever generated it, so
unlike a shared PIN, concurrent visitors never collide with or invalidate
each other's sessions — no single-active-session lock needed here.

No per-code message cap by design — a code is good for as long as its
_CODE_TTL_SECONDS lifetime lasts. The cost-control lever instead is the
number of codes that can exist at all: _MAX_ACTIVE_CODES caps how many are
outstanding at once, and POST /auth/demo-code lives under /auth/ so it
already inherits the existing per-IP auth rate limit (core/middleware.py)
for free.

Backed by core.database.DemoCodeSession (Postgres) rather than an
in-memory dict, so an in-flight demo/diagnostic session survives a backend
restart or redeploy, not just a lost tab or a network blip (the code/JWT
already outlived those on their own). Every function here follows
core/audit.py's self-contained-session convention: each opens (and
commits/closes) its own AsyncSessionLocal() rather than taking a `db`
parameter threaded in from the caller, so no signature anywhere upstream
(require_auth included) needs to grow a database dependency just for this.
"""

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select, update

# Hygiene only, not a security boundary: forgets codes nobody ever redeemed
# (or finished using) so this table can't grow forever from abandoned visits.
_CODE_TTL_SECONDS = 6 * 60 * 60
# Hard ceiling on how many codes can be outstanding at once, so a script
# hammering the generate endpoint can't manufacture unbounded aggregate quota
# even within the per-IP rate limit's one-minute window.
_MAX_ACTIVE_CODES = 500


def _cutoff() -> datetime:
    return datetime.now(timezone.utc) - timedelta(seconds=_CODE_TTL_SECONDS)


async def _fetch_live(db, code: str):
    from core.database import DemoCodeSession

    result = await db.execute(
        select(DemoCodeSession).where(
            DemoCodeSession.code == code,
            DemoCodeSession.created_at >= _cutoff(),
        )
    )
    return result.scalar_one_or_none()


async def generate_code(student_name: str | None = None, grade: str | None = None) -> str | None:
    """Mints a fresh 6-digit code, optionally carrying the visitor's chosen
    personalization (see routers/auth.py's /auth/demo-code and models.schemas
    DemoCodeRequest) through to the session config built once the code is
    redeemed (routers/tutor.py's _demo_session_config). Returns None if
    _MAX_ACTIVE_CODES is already reached — callers should surface that as a 429."""
    from core.database import AsyncSessionLocal, DemoCodeSession

    async with AsyncSessionLocal() as db:
        # Opportunistic cleanup of long-abandoned codes — same lazy
        # eviction shape the old in-memory _evict_expired() had, just
        # against a query instead of a dict comprehension.
        await db.execute(delete(DemoCodeSession).where(DemoCodeSession.created_at < _cutoff()))

        count = (await db.execute(select(func.count()).select_from(DemoCodeSession))).scalar_one()
        if count >= _MAX_ACTIVE_CODES:
            await db.commit()
            return None

        while True:
            code = f"{secrets.randbelow(1_000_000):06d}"
            existing = (await db.execute(
                select(DemoCodeSession.code).where(DemoCodeSession.code == code)
            )).scalar_one_or_none()
            if existing is None:
                break

        db.add(DemoCodeSession(code=code, student_name=student_name, grade=grade))
        await db.commit()
        return code


async def get_personalization(code: str) -> tuple[str | None, str | None]:
    """(student_name, grade) as submitted at /auth/demo-code, or (None, None)
    for an unknown code or a code minted with neither field set."""
    from core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        row = await _fetch_live(db, code)
        if row is None:
            return None, None
        return row.student_name, row.grade


async def get_mastery_vector(code: str) -> dict | None:
    """Raw mastery vector (skill_id -> probability) for this code, or None
    for an unknown code or one with no evidence recorded yet. Opaque dict —
    see services/diagnostic_demo.py for anything that actually interprets
    or builds one."""
    from core.database import AsyncSessionLocal
    from core.encryption import decrypt_json

    async with AsyncSessionLocal() as db:
        row = await _fetch_live(db, code)
        if row is None or row.mastery_vector_enc is None:
            return None
        return decrypt_json(row.mastery_vector_enc)


async def set_mastery_vector(code: str, vector: dict, evidence_count: int) -> None:
    """Overwrite this code's mastery vector and evidence count. No-op for
    an unknown/evicted code — a diagnostic write racing a logout should
    lose silently, not raise."""
    from core.database import AsyncSessionLocal
    from core.encryption import encrypt_json

    async with AsyncSessionLocal() as db:
        row = await _fetch_live(db, code)
        if row is None:
            return
        row.mastery_vector_enc = encrypt_json(vector)
        row.mastery_evidence_count = evidence_count
        await db.commit()


async def get_mastery_evidence_count(code: str) -> int:
    from core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        row = await _fetch_live(db, code)
        return row.mastery_evidence_count if row else 0


async def redeem_code(code: str) -> bool:
    """One-time exchange of a code for a JWT (see /auth/login). Returns False
    for an unknown or already-redeemed code — a code can only ever become a
    session once, so sharing a code with someone else after you've already
    logged in with it doesn't grant them a second, independent quota.

    A single conditional UPDATE...WHERE, not a SELECT-then-UPDATE — this is
    the one function two concurrent requests can genuinely race on (the
    same code, redeemed at the same instant), and Postgres's row-level
    locking makes exactly one of two concurrent UPDATEs against the same
    row win, matching the atomicity the old in-memory dict got for free
    from Python's GIL."""
    from core.database import AsyncSessionLocal, DemoCodeSession

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            update(DemoCodeSession)
            .where(
                DemoCodeSession.code == code,
                DemoCodeSession.redeemed.is_(False),
                DemoCodeSession.created_at >= _cutoff(),
            )
            .values(redeemed=True)
        )
        await db.commit()
        return result.rowcount == 1


async def code_exists(code: str) -> bool:
    """True if this code is still tracked (redeemed or not) — used by
    require_auth to reject a JWT whose code was evicted for being long
    abandoned."""
    from core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        return (await _fetch_live(db, code)) is not None


async def record_message(code: str) -> bool:
    """Call once per actual chat message sent, for usage bookkeeping — no
    cap enforced. Returns False only for an unknown/evicted code (e.g. the
    visitor logged out or the code's TTL expired mid-session)."""
    from core.database import AsyncSessionLocal, DemoCodeSession

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            update(DemoCodeSession)
            .where(DemoCodeSession.code == code, DemoCodeSession.created_at >= _cutoff())
            .values(message_count=DemoCodeSession.message_count + 1)
        )
        await db.commit()
        return result.rowcount == 1


async def end_session(code: str) -> None:
    """Explicit logout — deletes the code immediately so a copied/leaked
    token stops working right away instead of riding out its remaining
    expiry, and frees its _MAX_ACTIVE_CODES slot. Safe to call with an
    unknown code (no-op)."""
    from core.database import AsyncSessionLocal, DemoCodeSession

    async with AsyncSessionLocal() as db:
        await db.execute(delete(DemoCodeSession).where(DemoCodeSession.code == code))
        await db.commit()


async def claim_email_send(code: str) -> bool:
    """One diagnostic email send allowed per code, ever. Atomic conditional
    UPDATE, same reasoning as redeem_code above."""
    from core.database import AsyncSessionLocal, DemoCodeSession

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            update(DemoCodeSession)
            .where(
                DemoCodeSession.code == code,
                DemoCodeSession.email_sent.is_(False),
                DemoCodeSession.created_at >= _cutoff(),
            )
            .values(email_sent=True)
        )
        await db.commit()
        return result.rowcount == 1
