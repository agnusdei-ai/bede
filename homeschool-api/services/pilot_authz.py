"""One resolved, immutable authorization context for an educator's request.

Every educator surface that touches a learner (a voice-transcription
session, a tutoring turn, a learner lookup) resolves ONE
``PilotAuthzContext`` up front, server-side, and then re-validates it
against the database wherever continuing would release or persist learner
data. ``revalidate()`` is that single check.

Why a context rather than re-running a lookup everywhere: *who* may act and
*under which grant* must be compared as one value. A voice session owned by
"an educator" was a real defect here (``routers/voice.py`` once used the
literal string ``"educator"`` as the owner of every educator's session). A
session owned by THIS principal, on THIS campus, for THIS learner, under
THIS grant at THIS version cannot be reached by a second teacher, by a
substituted learner UUID, or by the same teacher after the grant is revoked.

Two modes, never mixed:

``campus``  The learner is a ``PilotLearner`` (immutable UUID). The campus is
            resolved from the grant join, never trusted from the client; a
            client-supplied campus is only compared. The grant is a
            ``PilotRosterGrant`` row with its own ``grant_id`` and ``version``,
            which revoke and re-approve advance.

``legacy``  The single-household, name-keyed roster (``EducatorRosterAssignment``).
            Valid only while NO pilot campus exists anywhere on the instance,
            because name-keyed rows cannot say which campus owns them. The
            grant version is the educator's ``credential_version``, which every
            legacy revocation path bumps (``disable_educator`` and
            ``assign_class_roster`` when it removes a learner).

Every context also pins the educator's ``credential_version``, so disabling
the account or any revocation that bumps it ends every context at once.

Fail closed. ``revalidate()`` answers False on ANY exception, including a
database outage. A check that cannot ask is indistinguishable from a check
that said no, and the two directions cost very different things.

Uniform denial. Every failure that names a record answers the same 404 with
the same body, ``NOT_FOUND``, whether the id is random, malformed, missing,
belongs to another campus, or was revoked. Nothing distinguishes them.

This module imports nothing from ``services/ai_service.py`` or the cache
code another lane owns.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from typing import Any, AsyncIterator, Optional

from fastapi import HTTPException
from sqlalchemy import select

from core.config import settings

log = logging.getLogger(__name__)

NOT_FOUND = "Record not found"

# How often an open stream with nothing to emit re-checks its grant. Also the
# upper bound on how long a revoked educator's idle stream stays open.
# Module-level so a test can shorten it.
REVALIDATE_INTERVAL_SECONDS = 1.0

# The actions this module authorizes. Recorded on the context and in audit
# detail, so a denial says what was being attempted.
ACTION_VOICE = "voice.stream"
ACTION_TUTOR = "tutor.chat"
ACTION_LEARNER_READ = "learner.read"


class AuthzRevoked(Exception):
    """The grant behind a PilotAuthzContext no longer holds."""


@dataclass(frozen=True)
class PilotAuthzContext:
    principal_id: str
    action: str
    grant_id: str
    grant_version: int
    credential_version: int
    campus_id: Optional[str] = None
    learner_id: Optional[str] = None
    # Legacy mode only. Never used as an authorization key on its own: it is
    # checked against the roster AND against "no campus exists".
    legacy_student_name: Optional[str] = None

    @property
    def mode(self) -> str:
        return "campus" if self.campus_id is not None else "legacy"

    def owner_key(self) -> str:
        """The voice-session owner. Every field participates, so a session
        minted under one grant version, campus, learner or principal is
        unreachable from any other."""
        learner = self.learner_id if self.mode == "campus" else (
            # A digest, not the display name, so the name never sits in an
            # owner string that might be logged.
            "legacy-" + uuid.uuid5(uuid.NAMESPACE_URL, f"bede-legacy:{self.legacy_student_name}").hex
        )
        return "|".join((
            "educator", self.principal_id, self.campus_id or "-", learner,
            self.grant_id, str(self.grant_version), str(self.credential_version),
        ))

    def audit_detail(self) -> str:
        # UUIDs only. Never a display name, never a token.
        return (
            f"action={self.action} mode={self.mode} principal={self.principal_id} "
            f"campus={self.campus_id} learner={self.learner_id} "
            f"grant={self.grant_id} v={self.grant_version} ev={self.credential_version}"
        )


def not_found() -> HTTPException:
    return HTTPException(status_code=404, detail=NOT_FOUND)


def canonical_uuid(value: Any) -> str:
    """A canonical lowercase UUIDv4, or the uniform 404."""
    try:
        parsed = uuid.UUID(value)
        if parsed.version != 4 or str(parsed) != value:
            raise ValueError("Noncanonical UUID")
    except (ValueError, AttributeError, TypeError):
        raise not_found()
    return str(parsed)


def _pilot_enabled() -> bool:
    return bool(settings.educator_pilot_enabled) and not settings.is_demo_deployment


async def campus_mode_active(db) -> bool:
    """True once ANY pilot campus row exists, enabled or not.

    Deliberately ignores ``enabled``: if disabling every campus reopened the
    name-keyed routes, same-named learners on two campuses could again share
    one name-keyed record."""
    from core.database import PilotCampus
    return (await db.execute(select(PilotCampus.id).limit(1))).scalar_one_or_none() is not None


async def legacy_name_routes_allowed(db) -> bool:
    """The single answer to "may a name-keyed educator path run here"."""
    if not settings.educator_pilot_enabled:
        return True
    return not await campus_mode_active(db)


def _grant_query(educator_id: str, learner_id: str):
    from core.database import (
        PilotCampus, PilotEducatorCampus, PilotLearner, PilotRosterGrant,
    )
    return (
        select(PilotRosterGrant, PilotLearner)
        .join(PilotLearner,
              (PilotLearner.id == PilotRosterGrant.learner_id)
              & (PilotLearner.campus_id == PilotRosterGrant.campus_id))
        .join(PilotCampus, PilotCampus.id == PilotLearner.campus_id)
        .join(PilotEducatorCampus,
              (PilotEducatorCampus.campus_id == PilotLearner.campus_id)
              & (PilotEducatorCampus.educator_id == PilotRosterGrant.educator_id))
        .where(PilotRosterGrant.educator_id == educator_id,
               PilotRosterGrant.learner_id == learner_id,
               PilotLearner.enabled.is_(True),
               PilotCampus.enabled.is_(True),
               PilotEducatorCampus.enabled.is_(True),
               PilotRosterGrant.enabled.is_(True))
    )


async def resolve_campus_learner(
    db, token: dict, learner_id: Any, action: str,
    claimed_campus_id: Any = None,
) -> PilotAuthzContext:
    """Campus mode. The campus comes from the grant join; a client-supplied
    campus is only compared. Every failure that names a record is the same
    404."""
    from services.educator_access import live_educator
    if not _pilot_enabled():
        raise HTTPException(status_code=403, detail="Institutional pilot is disabled")
    teacher = await live_educator(db, token)
    learner = canonical_uuid(learner_id)
    claimed = canonical_uuid(claimed_campus_id) if claimed_campus_id is not None else None
    row = (await db.execute(_grant_query(teacher.id, learner))).first()
    if row is None:
        raise not_found()
    grant, pupil = row
    if claimed is not None and claimed != pupil.campus_id:
        raise not_found()
    return PilotAuthzContext(
        principal_id=teacher.id, action=action,
        grant_id=grant.grant_id, grant_version=grant.version,
        credential_version=teacher.credential_version,
        campus_id=pupil.campus_id, learner_id=pupil.id,
    )


async def resolve_legacy_learner(db, token: dict, student_name: str, action: str) -> PilotAuthzContext:
    """Single-household mode. ``require_assignment`` denies it instance-wide
    once any campus exists."""
    from services.educator_access import live_educator, require_assignment
    await require_assignment(db, token, student_name)
    teacher = await live_educator(db, token)
    return PilotAuthzContext(
        principal_id=teacher.id, action=action,
        grant_id="legacy-roster", grant_version=teacher.credential_version,
        credential_version=teacher.credential_version,
        legacy_student_name=student_name,
    )


async def _still_valid(db, ctx: PilotAuthzContext) -> bool:
    from core.database import ClassicalEducator, EducatorRosterAssignment
    if not settings.educator_pilot_enabled:
        return False
    teacher = await db.get(ClassicalEducator, ctx.principal_id)
    if (teacher is None or not teacher.enabled
            or teacher.credential_version != ctx.credential_version):
        return False
    if ctx.mode == "campus":
        if not _pilot_enabled():
            return False
        row = (await db.execute(_grant_query(ctx.principal_id, ctx.learner_id))).first()
        if row is None:
            return False
        grant, pupil = row
        return (grant.grant_id == ctx.grant_id
                and grant.version == ctx.grant_version
                and pupil.campus_id == ctx.campus_id)
    if await campus_mode_active(db):
        return False
    link = await db.get(EducatorRosterAssignment, (ctx.principal_id, ctx.legacy_student_name))
    return link is not None


async def revalidate(ctx: PilotAuthzContext) -> bool:
    """Re-read the grant in a FRESH session, never the request's own, whose
    identity map could serve a stale row. Any error fails closed."""
    try:
        from core import database  # looked up at call time; tests patch it
        async with database.AsyncSessionLocal() as session:
            return await _still_valid(session, ctx)
    except Exception:
        log.warning("pilot_authz: revalidation failed closed", exc_info=True)
        return False


def audit_revoked(ctx: PilotAuthzContext, stage: str, request_ctx: Optional[dict] = None) -> None:
    """Durable evidence that a grant stopped holding mid-flight. Fire and
    forget: the stream it describes is already ending."""
    from core.audit import AuditEvent, log_event_nowait
    log_event_nowait(
        AuditEvent.AUTHZ_REVOKED_IN_FLIGHT,
        role="educator", success=False,
        detail=f"stage={stage} {ctx.audit_detail()}",
        **(request_ctx or {}),
    )


async def require_valid(ctx: PilotAuthzContext, stage: str, request_ctx: Optional[dict] = None) -> None:
    if not await revalidate(ctx):
        audit_revoked(ctx, stage, request_ctx)
        raise AuthzRevoked(stage)


async def guarded_stream(
    agen: AsyncIterator[Any], ctx: PilotAuthzContext, *,
    stage: str, request_ctx: Optional[dict] = None,
    interval: Optional[float] = None,
) -> AsyncIterator[Any]:
    """Release items from ``agen`` only while ``ctx`` still holds.

    Re-validates before every item is released, and at least every
    ``interval`` seconds while the inner stream is silent, so a revoked
    stream ends promptly even when nothing is being produced. At most one
    item is fetched ahead of the check, and it is discarded, never released,
    if the check fails.

    On revocation the in-flight fetch is cancelled and the inner generator
    closed, so its own cleanup runs (a voice session discards itself; a
    tutoring turn stops generating). Then ``AuthzRevoked`` is raised.
    """
    period = REVALIDATE_INTERVAL_SECONDS if interval is None else interval
    it = agen.__aiter__()
    pending: Optional[asyncio.Task] = None
    try:
        await require_valid(ctx, f"{stage}.open", request_ctx)
        while True:
            if pending is None:
                pending = asyncio.ensure_future(it.__anext__())
            done, _ = await asyncio.wait({pending}, timeout=period)
            if not done:
                await require_valid(ctx, f"{stage}.idle", request_ctx)
                continue
            task, pending = pending, None
            try:
                item = task.result()
            except StopAsyncIteration:
                return
            await require_valid(ctx, f"{stage}.item", request_ctx)
            yield item
    finally:
        if pending is not None:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        aclose = getattr(agen, "aclose", None)
        if aclose is not None:
            try:
                await aclose()
            except Exception:
                log.debug("pilot_authz: inner stream close raised", exc_info=True)


class RevocationGatedSession:
    """Wraps a request's ``AsyncSession`` so no write becomes durable after
    the grant is revoked.

    ``commit`` and ``flush`` re-validate first; on failure the pending work
    is rolled back and ``AuthzRevoked`` raised. Everything else is forwarded,
    so code written against ``AsyncSession`` keeps working. Staged work that
    is never committed is discarded with the session at request end, so
    gating ``commit`` is what makes a write durable or not.
    """

    def __init__(self, session, ctx: PilotAuthzContext, request_ctx: Optional[dict] = None):
        object.__setattr__(self, "_session", session)
        object.__setattr__(self, "_ctx", ctx)
        object.__setattr__(self, "_request_ctx", request_ctx)
        object.__setattr__(self, "refused_writes", 0)

    async def _gate(self) -> None:
        if not await revalidate(self._ctx):
            object.__setattr__(self, "refused_writes", self.refused_writes + 1)
            audit_revoked(self._ctx, "write", self._request_ctx)
            try:
                await self._session.rollback()
            finally:
                raise AuthzRevoked("write")

    async def commit(self) -> None:
        await self._gate()
        await self._session.commit()

    async def flush(self, *args, **kwargs) -> None:
        await self._gate()
        await self._session.flush(*args, **kwargs)

    def __getattr__(self, name: str):
        return getattr(self._session, name)

    def __setattr__(self, name: str, value) -> None:
        setattr(self._session, name, value)
