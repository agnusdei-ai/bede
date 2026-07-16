"""
Pod session management.

The parent saves each student's config before the day's sessions begin.
Students then load their config from the server after PIN login, keyed
by their name from the session URL. All configs are AES-256-GCM encrypted
at rest — no plaintext student data is written to the database.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core import licensing
from core.audit import AuditEvent, audit_from_request, log_event
from core.config import settings
from core.database import StudentConfig, get_db
from core.deps import require_parent, require_real_user
from core.encryption import decrypt_json, encrypt_json
from models.schemas import PodConfigsRequest, SessionConfig, VoiceNarrationPreferenceRequest
from services.student_deletion import delete_all_student_data

router = APIRouter(prefix="/pod", tags=["pod"])


@router.post("/configs", status_code=204)
async def save_pod_configs(
    req: PodConfigsRequest,
    _: dict = Depends(require_parent),
    db: AsyncSession = Depends(get_db),
) -> None:
    """
    Parent saves all student configs for today's pod. Upserts per student
    name. Enforces the license's seat cap when a license is configured
    (unset LICENSE_KEY — dev/self-managed mode — skips this, same
    "empty = disabled" pattern as DEMO_PIN); in production a license is
    always present by the time this runs (core/config.py rejects startup
    without one), so this is a defense-in-depth check, not the primary gate.
    """
    if settings.locale != "en":
        missing = [c.student_name for c in req.configs if c.sex is None]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Sex must be set for every student on a "
                    f"{settings.locale!r}-locale deployment, so Bede can address them "
                    f"grammatically correctly: {', '.join(missing)}"
                ),
            )

    license_info = licensing.get_license(settings.license_key)
    if license_info is not None:
        result = await db.execute(select(StudentConfig.student_name))
        existing_names = {row[0] for row in result.all()}
        new_names = {config.student_name for config in req.configs}
        total_seats_used = len(existing_names | new_names)
        if total_seats_used > license_info.seats:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Your {license_info.tier} license allows up to {license_info.seats} "
                    f"student{'s' if license_info.seats != 1 else ''} "
                    f"(this pod would have {total_seats_used}) — contact us to upgrade."
                ),
            )
    for config in req.configs:
        enc = encrypt_json(config.model_dump())
        result = await db.execute(
            select(StudentConfig).where(StudentConfig.student_name == config.student_name)
        )
        row = result.scalar_one_or_none()
        if row is None:
            db.add(StudentConfig(student_name=config.student_name, config_enc=enc))
        else:
            row.config_enc = enc
    await db.commit()


@router.get("/configs", response_model=list[SessionConfig])
async def list_pod_configs(
    _: dict = Depends(require_parent),
    db: AsyncSession = Depends(get_db),
) -> list[SessionConfig]:
    """Parent retrieves all stored student configs for the dashboard."""
    result = await db.execute(select(StudentConfig))
    rows = result.scalars().all()
    return [SessionConfig(**decrypt_json(row.config_enc)) for row in rows]


@router.get("/configs/{student_name}", response_model=SessionConfig)
async def get_student_config(
    student_name: str,
    _: dict = Depends(require_real_user),
    db: AsyncSession = Depends(get_db),
) -> SessionConfig:
    """Any authenticated user can fetch a student config — child loads their own session."""
    result = await db.execute(
        select(StudentConfig).where(StudentConfig.student_name == student_name)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No configuration found for '{student_name}' — ask a parent to set up today's pod.",
        )
    return SessionConfig(**decrypt_json(row.config_enc))


@router.patch("/configs/{student_name}/voice-narration", status_code=204)
async def update_voice_narration_preference(
    student_name: str,
    req: VoiceNarrationPreferenceRequest,
    _: dict = Depends(require_real_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """
    Persists just the child's own mute/unmute choice for Bede's spoken
    narration, so it's remembered next session. Deliberately require_real_user
    (not require_parent) — the child is who actually taps this toggle during
    their own session — but only this one field is ever touched: every other
    stored config value is decrypted and re-saved unchanged, so a child token
    can never use this to rewrite subjects, lesson focus, or any other setting
    that should stay parent-controlled.
    """
    result = await db.execute(
        select(StudentConfig).where(StudentConfig.student_name == student_name)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No configuration found for '{student_name}'",
        )
    config = decrypt_json(row.config_enc)
    config["voice_narration_enabled"] = req.voice_narration_enabled
    row.config_enc = encrypt_json(config)
    await db.commit()


@router.delete("/configs/{student_name}", status_code=204)
async def delete_student_config(
    student_name: str,
    request: Request,
    _: dict = Depends(require_parent),
    db: AsyncSession = Depends(get_db),
) -> None:
    """
    Parent permanently deletes a student and ALL of their data — not just
    removal from today's pod. Before this, this route only deleted the
    StudentConfig row; every other per-student table (narration history,
    learner profile, mastery tracking, session transcripts, usage events,
    voice enrollment) silently persisted forever with no way for a parent
    to actually remove it. See services/student_deletion.py for the full
    list and reasoning. Idempotent — deleting a student with no data
    (or already deleted) still returns 204, since the end state is
    identical either way.
    """
    counts = await delete_all_student_data(db, student_name)
    await log_event(
        AuditEvent.STUDENT_DATA_DELETED,
        role="parent",
        student_name=student_name,
        detail=f"rows_deleted={sum(counts.values())}",
        **audit_from_request(request),
    )
