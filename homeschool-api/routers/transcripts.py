from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.audit import AuditEvent, audit_from_request, log_event
from core.database import SessionTranscript, get_db
from core.deps import require_parent, require_real_user
from core.encryption import decrypt_json, encrypt_json
from services.ai_service import _redact_credentials

router = APIRouter(prefix="/transcripts", tags=["transcripts"])


class TranscriptMessage(BaseModel):
    role: str
    content: str
    timestamp: str


class TranscriptSaveRequest(BaseModel):
    student_name: str
    subjects: List[str]
    duration_minutes: int
    messages: List[TranscriptMessage]


@router.post("/{student_name}")
async def save_transcript(
    student_name: str,
    req: TranscriptSaveRequest,
    request: Request,
    auth: dict = Depends(require_real_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Save encrypted session transcript. Callable by parent or child at session end.
    Stored as AES-256-GCM BYTEA — the database provider never sees plaintext content.
    """
    now = datetime.now(timezone.utc)
    data = {
        "student_name": student_name,
        "subjects": req.subjects,
        "duration_minutes": req.duration_minutes,
        # AIUC-1 A008 — this is a client-submitted, independently-stored
        # copy of the conversation (not derived from the already-redacted
        # /tutor/chat path), so it needs its own credential redaction
        # before it's encrypted and persisted.
        "messages": [
            {**m.model_dump(), "content": _redact_credentials(m.content)}
            for m in req.messages
        ],
        "saved_at": now.isoformat(),
    }
    db.add(SessionTranscript(
        student_name=student_name,
        session_date=now,
        subjects=",".join(req.subjects),
        duration_minutes=req.duration_minutes,
        transcript_enc=encrypt_json(data),
    ))
    await db.commit()
    await log_event(
        AuditEvent.SESSION_END,
        role=auth.get("role"),
        student_name=student_name,
        detail=f"transcript saved duration={req.duration_minutes}min msgs={len(req.messages)}",
        **audit_from_request(request),
    )
    return {"saved": True}


@router.get("/{student_name}")
async def list_transcripts(
    student_name: str,
    request: Request,
    limit: int = 10,
    auth: dict = Depends(require_parent),
    db: AsyncSession = Depends(get_db),
):
    """List recent session transcripts for a student. Parent only."""
    result = await db.execute(
        select(SessionTranscript)
        .where(SessionTranscript.student_name == student_name)
        .order_by(SessionTranscript.session_date.desc())
        .limit(min(limit, 30))
    )
    rows = result.scalars().all()
    transcripts = []
    for row in rows:
        try:
            data = decrypt_json(row.transcript_enc)
            transcripts.append({
                "id": row.id,
                "session_date": row.session_date.isoformat(),
                "subjects": row.subjects.split(","),
                "duration_minutes": row.duration_minutes,
                "message_count": len(data.get("messages", [])),
            })
        except Exception:
            transcripts.append({"id": row.id, "_corrupt": True})
    return {"transcripts": transcripts}


@router.get("/{student_name}/{transcript_id}")
async def get_transcript(
    student_name: str,
    transcript_id: int,
    request: Request,
    auth: dict = Depends(require_parent),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve a full decrypted transcript. Parent only."""
    result = await db.execute(
        select(SessionTranscript).where(
            SessionTranscript.id == transcript_id,
            SessionTranscript.student_name == student_name,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Transcript not found")
    return decrypt_json(row.transcript_enc)
