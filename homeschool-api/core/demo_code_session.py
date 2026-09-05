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

Duration is intentionally generous — a code lives out its full
_CODE_TTL_SECONDS window, and POST /auth/demo-code lives under /auth/ so
minting one already inherits the existing per-IP auth rate limit
(core/middleware.py) for free, with _MAX_ACTIVE_CODES bounding how many
codes can be outstanding at once. Message VOLUME per code is a separate
question, and is now hard-capped (_MAX_MESSAGES_PER_CODE, enforced via
has_message_quota() below) — the per-IP "api" rate-limit bucket bounds
REQUEST RATE (120/min by default), never aggregate spend, so a single
scripted session sustained at that ceiling for a whole token/code
lifetime was a genuine unbounded-cost surface (OWASP Top 10 for LLM
Applications, LLM10 "Unbounded Consumption") with no dollar or
message-count ceiling underneath the rate limit. See has_message_quota's
own docstring for why the cap is a separate check rather than folded into
record_message.

Backed by core.database.DemoCodeSession (Postgres) rather than an
in-memory dict, so an in-flight demo/diagnostic session survives a backend
restart or redeploy, not just a lost tab or a network blip (the code/JWT
already outlived those on their own). Every function here follows
core/audit.py's self-contained-session convention: each opens (and
commits/closes) its own AsyncSessionLocal() rather than taking a `db`
parameter threaded in from the caller, so no signature anywhere upstream
(require_auth included) needs to grow a database dependency just for this.
"""

import logging
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select, update

log = logging.getLogger(__name__)

# Hygiene only, not a security boundary: forgets codes nobody ever redeemed
# (or finished using) so this table can't grow forever from abandoned visits.
_CODE_TTL_SECONDS = 6 * 60 * 60
# Hard ceiling on how many codes can be outstanding at once, so a script
# hammering the generate endpoint can't manufacture unbounded aggregate quota
# even within the per-IP rate limit's one-minute window.
_MAX_ACTIVE_CODES = 500

# Hard ceiling on chat messages a single code may send before being asked to
# start a fresh demo. The base demo is deliberately generous with DURATION
# and BREADTH (every subject, no artificial preview crippling — see this
# module's own docstring and diagnostic_preview_quota.py's), but nothing
# previously stopped a single scripted session from running indefinitely at
# the per-IP rate limit's own ceiling for the code's whole token lifetime —
# a real, unbounded per-visitor cost surface (OWASP LLM10). A genuine
# thorough evaluation — every subject, both faith modules, picture study,
# voice, the works — runs well under 200 exchanges; 400 leaves a wide
# safety margin over any real visitor while bounding worst-case model
# spend per code to a small, known number of calls.
_MAX_MESSAGES_PER_CODE = 400


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


async def generate_code(
    student_name: str | None = None, grade: str | None = None, current_unit: str | None = None,
    faith_tradition: str | None = None,
) -> str | None:
    """Mints a fresh 6-digit code, optionally carrying the visitor's chosen
    personalization (see routers/auth.py's /auth/demo-code and models.schemas
    DemoCodeRequest) through to the session config built once the code is
    redeemed (routers/tutor.py's _demo_session_config). Returns None if
    _MAX_ACTIVE_CODES is already reached — callers should surface that as a 429.

    current_unit (already sanitized by the caller) is stored in the separate
    DemoCodeUnitNote table, not on this row — see that model's own
    docstring for why. faith_tradition (also pre-sanitized) is stored the
    same way, in DemoCodeFaithNote — see that model's own docstring."""
    from core.database import (
        AsyncSessionLocal, DemoCodeActivityLog, DemoCodeFaithNote, DemoCodeParentConfig,
        DemoCodeSession, DemoCodeUnitNote,
    )

    async with AsyncSessionLocal() as db:
        # Opportunistic cleanup of long-abandoned codes — same lazy
        # eviction shape the old in-memory _evict_expired() had, just
        # against a query instead of a dict comprehension.
        await db.execute(delete(DemoCodeSession).where(DemoCodeSession.created_at < _cutoff()))
        await db.execute(delete(DemoCodeUnitNote).where(DemoCodeUnitNote.created_at < _cutoff()))
        await db.execute(delete(DemoCodeFaithNote).where(DemoCodeFaithNote.created_at < _cutoff()))
        await db.execute(delete(DemoCodeActivityLog).where(DemoCodeActivityLog.created_at < _cutoff()))
        await db.execute(delete(DemoCodeParentConfig).where(DemoCodeParentConfig.created_at < _cutoff()))

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
        if current_unit:
            db.add(DemoCodeUnitNote(code=code, note=current_unit))
        if faith_tradition:
            db.add(DemoCodeFaithNote(code=code, tradition=faith_tradition))
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


async def get_current_unit(code: str) -> str | None:
    """The parent-provided "what are we already covering at home" note set
    at /auth/demo-code (see DemoCodeRequest.current_unit), or None for an
    unknown/evicted code or one minted with no note. A separate lookup
    from get_personalization (its own table — see DemoCodeUnitNote's
    docstring) rather than folding into that function's tuple, so its two
    existing single-purpose callers (routers/diagnostic.py) don't have to
    change shape for a field they don't use."""
    from core.database import AsyncSessionLocal, DemoCodeUnitNote

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(DemoCodeUnitNote.note).where(
                DemoCodeUnitNote.code == code,
                DemoCodeUnitNote.created_at >= _cutoff(),
            )
        )
        return result.scalar_one_or_none()


async def get_faith_tradition(code: str) -> str | None:
    """The visitor-provided church-tradition label set at /auth/demo-code
    (see DemoCodeRequest.faith_tradition), or None for an unknown/evicted
    code or one minted with no label. Separate lookup from
    get_current_unit, same one-table-per-optional-field convention (see
    DemoCodeFaithNote's docstring)."""
    from core.database import AsyncSessionLocal, DemoCodeFaithNote

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(DemoCodeFaithNote.tradition).where(
                DemoCodeFaithNote.code == code,
                DemoCodeFaithNote.created_at >= _cutoff(),
            )
        )
        return result.scalar_one_or_none()


async def set_parent_config(code: str, config: dict) -> None:
    """Store this code's own Parent Setup (core/database.py's
    DemoCodeParentConfig), replacing whatever was there.

    The caller is responsible for having validated `config` through
    models/schemas.py's own validators — see routers/auth.py's
    set_demo_parent_config, which builds a real SessionConfig from it and
    would reject anything the product itself would reject. This function
    stores what it is handed.

    Silently does nothing for an unknown or evicted code, so a stale tab
    cannot resurrect a session that has already gone.
    """
    from core.database import AsyncSessionLocal, DemoCodeParentConfig
    from core.encryption import aad_for, encrypt_json

    if not await code_exists(code):
        return

    # Bound to its own row (P5), same as the activity log beside it: one
    # DATA_KEY covers every column, so without this a config blob could be
    # copied into another code's row and decrypt cleanly.
    blob = encrypt_json(config, aad_for("demo_code_parent_configs", "config_enc", code))
    async with AsyncSessionLocal() as db:
        existing = await db.get(DemoCodeParentConfig, code)
        if existing is not None:
            existing.config_enc = blob
        else:
            db.add(DemoCodeParentConfig(code=code, config_enc=blob))
        await db.commit()


async def get_parent_config(code: str) -> dict | None:
    """This code's own Parent Setup, or None for a code that never set one
    (the ordinary case — the demo works with nothing configured) or one
    past the same TTL every other demo table uses."""
    from core.database import AsyncSessionLocal, DemoCodeParentConfig
    from core.encryption import aad_for, decrypt_json

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(DemoCodeParentConfig.config_enc).where(
                DemoCodeParentConfig.code == code,
                DemoCodeParentConfig.created_at >= _cutoff(),
            )
        )
        blob = result.scalar_one_or_none()
    if blob is None:
        return None
    try:
        value = decrypt_json(blob, aad_for("demo_code_parent_configs", "config_enc", code))
    except Exception:
        # A row this process cannot read is a row that does not exist, as
        # far as a demo session is concerned — never a 500 on the visitor's
        # first turn.
        logger.warning("demo parent config could not be decrypted; ignoring")
        return None
    return value if isinstance(value, dict) else None


# A demo session produces a few dozen completed activities at most. The cap
# is a bound on the encrypted blob's size, not a product decision — a demo
# visitor will never approach it, and if one somehow did, dropping the
# OLDEST entry keeps the card showing what they just did.
_MAX_DEMO_ACTIVITIES = 200


async def append_activity(code: str, entry: dict) -> None:
    """Append one completed-activity record to this code's own ephemeral
    work ledger (core/database.py's DemoCodeActivityLog — never
    SkillActivityLog, which is a real family's permanent record).

    Read-modify-write on a single encrypted blob rather than a row per
    activity; see that model's docstring for why. Best-effort like every
    other diagnostic write in this codebase: a failure here is swallowed,
    never raised, so a ledger hiccup can't break the visitor's turn."""
    from core.database import AsyncSessionLocal, DemoCodeActivityLog
    from core.encryption import aad_for, decrypt_json, encrypt_json

    # Bound to table/column/code, exactly as the sibling mastery_vector_enc
    # below is. One DATA_KEY covers every column in every table, so without
    # this an attacker with database write access could copy one visitor's
    # ledger into another visitor's row and it would decrypt cleanly. `code`
    # is the primary key and never changes for the life of the row, which is
    # what aad_for requires of a row_key.
    aad = aad_for("demo_code_activity_logs", "activities_enc", code)
    try:
        async with AsyncSessionLocal() as db:
            row = await db.get(DemoCodeActivityLog, code)
            if row is None:
                db.add(DemoCodeActivityLog(code=code, activities_enc=encrypt_json([entry], aad)))
            else:
                try:
                    existing = decrypt_json(row.activities_enc, aad)
                except Exception:
                    existing = []
                if not isinstance(existing, list):
                    existing = []
                existing.append(entry)
                row.activities_enc = encrypt_json(existing[-_MAX_DEMO_ACTIVITIES:], aad)
            await db.commit()
    except Exception as exc:
        log.warning("Demo activity append failed for %s: %s", code, exc)


async def get_activities(code: str) -> list[dict]:
    """This code's own completed-activity records, oldest first. Empty for
    an unknown, evicted, or expired code — the same read-time cutoff filter
    every other accessor in this module applies, so an expired session's
    ledger is unreachable even before the eviction sweep removes it."""
    from core.database import AsyncSessionLocal, DemoCodeActivityLog
    from core.encryption import aad_for, decrypt_json

    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(DemoCodeActivityLog.activities_enc).where(
                    DemoCodeActivityLog.code == code,
                    DemoCodeActivityLog.created_at >= _cutoff(),
                )
            )
            blob = result.scalar_one_or_none()
        if blob is None:
            return []
        entries = decrypt_json(blob, aad_for("demo_code_activity_logs", "activities_enc", code))
        return entries if isinstance(entries, list) else []
    except Exception as exc:
        log.warning("Demo activity read failed for %s: %s", code, exc)
        return []


async def get_mastery_vector(code: str) -> dict | None:
    """Raw mastery vector (skill_id -> probability) for this code, or None
    for an unknown code or one with no evidence recorded yet. Opaque dict —
    see services/diagnostic_demo.py for anything that actually interprets
    or builds one."""
    from core.database import AsyncSessionLocal
    from core.encryption import aad_for, decrypt_json

    async with AsyncSessionLocal() as db:
        row = await _fetch_live(db, code)
        if row is None or row.mastery_vector_enc is None:
            return None
        return decrypt_json(row.mastery_vector_enc, aad_for("demo_code_sessions", "mastery_vector_enc", code))


async def set_mastery_vector(code: str, vector: dict, evidence_count: int) -> None:
    """Overwrite this code's mastery vector and evidence count. No-op for
    an unknown/evicted code — a diagnostic write racing a logout should
    lose silently, not raise."""
    from core.database import AsyncSessionLocal
    from core.encryption import aad_for, encrypt_json

    async with AsyncSessionLocal() as db:
        row = await _fetch_live(db, code)
        if row is None:
            return
        row.mastery_vector_enc = encrypt_json(vector, aad_for("demo_code_sessions", "mastery_vector_enc", code))
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
    from Python's GIL. Verified for real against a live Postgres instance
    at up to 50 concurrent redeems of distinct codes (test_demo_concurrency.py)
    and, per-code, at up to 20 concurrent redeems of the SAME code
    (test_demo_code_session.py) — exactly one winner every time.

    This correctness depends on Postgres's default READ COMMITTED
    isolation level specifically: when a second UPDATE blocks on the
    first's row lock, READ COMMITTED re-evaluates its WHERE clause against
    the row's newly committed state once the lock releases (EvalPlanQual),
    so the loser correctly sees redeemed=true and updates 0 rows — it does
    NOT see the pre-update snapshot it started with. core/database.py sets
    no explicit isolation_level, so this holds as long as nothing upstream
    changes that default (e.g. to REPEATABLE READ, where the loser would
    raise a serialization error instead of silently updating 0 rows —
    still correct, but this function's `rowcount == 1` check would need to
    also catch and treat that as "lost the race" rather than surfacing it
    as a 500)."""
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


async def has_message_quota(code: str) -> bool:
    """True if `code` may still send a chat message — False once it has
    reached _MAX_MESSAGES_PER_CODE, or for an unknown/evicted code (there's
    nothing to meter, and by the time an authenticated request reaches this
    point the code should already exist — treat the edge case the same
    direction record_message does).

    Deliberately a separate check from record_message rather than folded
    into it: the ENFORCEMENT point has to run before the expensive model
    call a chat turn triggers (so an over-quota turn is refused for free,
    never billed), while record_message's own job — incrementing the
    counter — has to run only once a turn is actually going to happen. A
    caller checks this first, then calls record_message only if it passes;
    see routers/tutor.py's chat() and routers/sandbox.py's demo_chat()."""
    from core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        row = await _fetch_live(db, code)
        if row is None:
            return False
        return row.message_count < _MAX_MESSAGES_PER_CODE


async def record_message(code: str) -> bool:
    """Call once per actual chat message sent, for usage bookkeeping —
    pure counting, no cap enforced here (see has_message_quota above,
    which callers must check first). Returns False only for an
    unknown/evicted code (e.g. the visitor logged out or the code's TTL
    expired mid-session)."""
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
    unknown code (no-op). Also deletes this code's DemoCodeUnitNote,
    DemoCodeFaithNote and DemoCodeActivityLog rows, if any, so nothing set
    or recorded during the session outlives it."""
    from core.database import (
        AsyncSessionLocal, DemoCodeActivityLog, DemoCodeFaithNote, DemoCodeParentConfig,
        DemoCodeSession, DemoCodeUnitNote,
    )

    async with AsyncSessionLocal() as db:
        await db.execute(delete(DemoCodeSession).where(DemoCodeSession.code == code))
        await db.execute(delete(DemoCodeUnitNote).where(DemoCodeUnitNote.code == code))
        await db.execute(delete(DemoCodeFaithNote).where(DemoCodeFaithNote.code == code))
        await db.execute(delete(DemoCodeActivityLog).where(DemoCodeActivityLog.code == code))
        await db.execute(delete(DemoCodeParentConfig).where(DemoCodeParentConfig.code == code))
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
