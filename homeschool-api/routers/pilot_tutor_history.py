"""Read-only tutoring history for an assigned campus learner.

Reads *only* existing encrypted institutional transcripts keyed by the
canonical LearnerScope storage subject. Nothing is fabricated and no data
key is created on a read. Explicitly does not launch tutor delivery.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core import student_keys
from core.database import SessionTranscript, get_db
from core.deps import require_educator
from core.encryption import decrypt_json, student_aad
from core.learner_scope import LearnerScope
from services import pilot_authz

router = APIRouter(prefix="/pilot/me/learners", tags=["valor-pilot-history"])


class RetainedSession(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: int
    session_date: datetime
    subjects: list[str]
    duration_minutes: int
    message_count: int


class HistoryPage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    learner_id: str
    sessions: list[RetainedSession]
    has_more: bool


@router.get("/{learner_id}/tutoring/history", response_model=HistoryPage)
async def read_tutoring_history(
    learner_id: str, limit: int = Query(default=10, ge=1, le=30),
    auth: dict = Depends(require_educator),
    db: AsyncSession = Depends(get_db),
) -> HistoryPage:
    ctx = await pilot_authz.resolve_campus_learner(
        db, auth, learner_id, pilot_authz.ACTION_LEARNER_READ,
    )
    scope = LearnerScope.institutional(ctx.campus_id, ctx.learner_id)
    rows = (await db.execute(
        select(SessionTranscript)
        .where(SessionTranscript.student_name == scope.storage_subject)
        .order_by(SessionTranscript.session_date.desc(), SessionTranscript.id.desc())
        .limit(limit + 1)
    )).scalars().all()

    page = []
    for row in rows[:limit]:
        try:
            data = decrypt_json(
                row.transcript_enc,
                student_aad("session_transcripts", "transcript_enc", scope.storage_subject),
                await student_keys.get_existing(db, scope),
            )
            if not isinstance(data, dict) or not isinstance(data.get("messages"), list):
                raise ValueError("invalid transcript format")
            page.append(RetainedSession(
                session_id=row.id, session_date=row.session_date,
                subjects=[v for v in row.subjects.split(",") if v],
                duration_minutes=row.duration_minutes,
                message_count=len(data["messages"]),
            ))
        except Exception as exc:
            # A corrupt or undecryptable session must not be skipped to
            # produce misleading learning history.
            raise HTTPException(status_code=409,
                                detail="Verified tutoring history is unavailable") from exc

    # Freshly re-check the original grant/version before returning content.
    if not await pilot_authz.revalidate(ctx):
        pilot_authz.audit_revoked(ctx, "history.read")
        raise HTTPException(status_code=404, detail="Record not found")

    return HistoryPage(learner_id=scope.learner_id, sessions=page,
                       has_more=len(rows) > limit)
