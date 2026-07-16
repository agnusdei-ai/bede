from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from core.audit import AuditEvent, audit_from_request, log_event
from core.database import get_db
from core.deps import require_auth, require_parent, require_real_user
from services.voice_auth import (
    delete_profile,
    enroll_student,
    list_profiles,
    parent_override,
    verify_student,
)
from services.transcription import transcribe_audio

router = APIRouter(prefix="/voice", tags=["voice"])

_MAX_AUDIO_BYTES = 10 * 1024 * 1024
_AUDIO_MAGIC_BYTES = {
    b"RIFF":          "wav",
    b"OggS":          "ogg",
    b"\x1aE\xdf\xa3": "webm",
    b"\xff\xfb":      "mp3",
    b"ID3":           "mp3",
}


def _validate_audio(data: bytes, filename: str) -> None:
    if len(data) > _MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="Audio file too large (max 10 MB)")
    for magic in _AUDIO_MAGIC_BYTES:
        if data[:len(magic)] == magic:
            return
    ext = filename.rsplit(".", 1)[-1].lower()
    if ext in {"wav", "webm", "ogg", "mp4", "m4a", "mp3"}:
        return
    raise HTTPException(status_code=415, detail="Unsupported file type — only audio files are accepted")


# ── Enrollment (parent only) ─────────────────────────────────────────────────

@router.post("/enroll")
async def enroll(
    request: Request,
    student_name: str = Form(..., min_length=1, max_length=50),
    samples: List[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_parent),
):
    """Enrol a student's voice. Embeddings stored encrypted — never returned."""
    if len(samples) < 2:
        raise HTTPException(status_code=400, detail="At least 2 audio samples required")
    if len(samples) > 5:
        raise HTTPException(status_code=400, detail="Maximum 5 samples per enrolment")

    ctx = audit_from_request(request)
    audio_bytes_list = []
    for sample in samples:
        data = await sample.read()
        _validate_audio(data, sample.filename or "audio")
        audio_bytes_list.append(data)

    try:
        result = await enroll_student(student_name, audio_bytes_list, db)
        await log_event(AuditEvent.VOICE_ENROLL, student_name=student_name, role="parent", **ctx)
        return {
            "success":      True,
            "student_name": result["student_name"],
            "samples_used": result["samples_used"],
            "method":       result["method"],
        }
    except ValueError as exc:
        await log_event(AuditEvent.VOICE_ENROLL, student_name=student_name, success=False, detail=str(exc), **ctx)
        raise HTTPException(status_code=422, detail=str(exc))


# ── Verification (both roles) ────────────────────────────────────────────────

@router.post("/verify")
async def verify(
    request: Request,
    student_name: str = Form(..., min_length=1, max_length=50),
    audio: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_real_user),
):
    """Verify student voice. Returns score + level — never the stored embedding."""
    ctx = audit_from_request(request)
    data = await audio.read()
    _validate_audio(data, audio.filename or "audio")

    result = await verify_student(student_name, data, db)

    event = AuditEvent.VOICE_VERIFY_PASS if result["verified"] else AuditEvent.VOICE_VERIFY_FAIL
    await log_event(
        event,
        student_name=student_name,
        role=auth.get("role"),
        detail=f"level={result['level']} score={result.get('score')}",
        success=result["verified"],
        **ctx,
    )
    return {
        "verified": result["verified"],
        "score":    result.get("score"),
        "level":    result["level"],
        "message":  result["message"],
    }


# ── Parent override ───────────────────────────────────────────────────────────

@router.post("/override")
async def override_verification(
    request: Request,
    student_name: str = Form(..., min_length=1, max_length=50),
    _: dict = Depends(require_parent),
):
    """Parent approves a medium-confidence session. Logged in audit trail."""
    ctx = audit_from_request(request)
    await log_event(AuditEvent.VOICE_OVERRIDE, student_name=student_name, role="parent", **ctx)
    return parent_override(student_name)


# ── Profile management (parent only) ─────────────────────────────────────────

@router.get("/profiles")
async def get_profiles(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_parent),
):
    """List enrolled student names. No embeddings returned."""
    return {"enrolled_students": await list_profiles(db)}


@router.delete("/profiles/{student_name}")
async def remove_profile(
    student_name: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_parent),
):
    if await delete_profile(student_name, db):
        await log_event(
            AuditEvent.VOICE_ENROLL,
            student_name=student_name,
            role="parent",
            detail="profile deleted",
            **audit_from_request(request),
        )
        return {"deleted": student_name}
    raise HTTPException(status_code=404, detail="Profile not found")


# ── Whisper fallback STT ──────────────────────────────────────────────────────

@router.post("/transcribe")
async def transcribe(
    request: Request,
    audio: UploadFile = File(...),
    language: str = Form(default="en"),
    # require_auth (not require_real_user): demo sessions may use the STT
    # fallback too — browser speech recognition breaks under them exactly
    # like under a real session (a Chrome update once removed it outright),
    # and this endpoint is safe to expose at demo scope: stateless (the
    # result is returned inline, nothing stored), size-capped by
    # _validate_audio, rate-limited under the per-IP voice bucket, and
    # backed by the lightweight 'tiny' Whisper model in a worker thread.
    auth: dict = Depends(require_auth),
):
    """
    Server-side Whisper transcription fallback.
    Result is returned inline — not stored anywhere on the server.
    """
    data = await audio.read()
    _validate_audio(data, audio.filename or "audio")
    result = await transcribe_audio(data, language=language)
    return {"text": result.get("text", ""), "language": result.get("language", language)}
