"""
Pod session management.

The parent saves each student's config before the day's sessions begin.
Students then load their config from the server after PIN login, keyed
by their name from the session URL. All configs are AES-256-GCM encrypted
at rest — no plaintext student data is written to the database.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import StudentConfig, get_db
from core.deps import require_parent, require_real_user
from core.encryption import decrypt_json, encrypt_json
from models.schemas import PodConfigsRequest, SessionConfig

router = APIRouter(prefix="/pod", tags=["pod"])


@router.post("/configs", status_code=204)
async def save_pod_configs(
    req: PodConfigsRequest,
    _: dict = Depends(require_parent),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Parent saves all student configs for today's pod. Upserts per student name."""
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


@router.delete("/configs/{student_name}", status_code=204)
async def delete_student_config(
    student_name: str,
    _: dict = Depends(require_parent),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Parent removes a student from the pod."""
    result = await db.execute(
        select(StudentConfig).where(StudentConfig.student_name == student_name)
    )
    row = result.scalar_one_or_none()
    if row:
        await db.delete(row)
        await db.commit()
