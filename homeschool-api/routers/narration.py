"""
Narration assessment history and learner-profile endpoints.

All assessment data is AES-256-GCM encrypted at rest — the DB never holds
plaintext narration scores or profile notes.

Routes:
  GET  /narration/{student}/assessments     — parent: score history
  GET  /narration/{student}/profile         — parent or child: most recent learner profile
  GET  /narration/{student}/profile/history — parent: every past profile, most recent first
  POST /narration/{student}/profile         — trigger a fresh profile synthesis (after session 1+)

Synthesis is available from the very first session on purpose — parents
should have an initial read on how their child learns (and Bede's first
recommendations) right away, not after waiting three sessions. It's simply
lower-confidence with fewer data points; the profile can (and should) be
rebuilt again after each additional session as more narrations accumulate.

Each synthesis appends a new LearnerProfile row rather than overwriting
the last one (see core.database.LearnerProfile) — same automatic
refresh services.ai_service.refresh_learner_profile_if_stale performs at
session end. This endpoint's build_profile is the parent-forced version:
same underlying synthesis, always runs regardless of staleness.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import LearnerProfile, NarrationAssessment, get_db
from core.deps import require_parent, require_real_user
from core.encryption import decrypt_json, encrypt_json
from models.schemas import RUBRIC_VERSION
from services.ai_service import synthesize_learner_profile

router = APIRouter(prefix="/narration", tags=["narration"])


@router.get("/{student_name}/assessments")
async def get_assessments(
    student_name: str,
    limit: int = Query(default=30, le=100),
    _: dict = Depends(require_parent),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Parent retrieves narration assessment history for a student (most recent first)."""
    result = await db.execute(
        select(NarrationAssessment)
        .where(NarrationAssessment.student_name == student_name)
        .order_by(NarrationAssessment.session_date.desc())
        .limit(limit)
    )
    rows = result.scalars().all()
    return [decrypt_json(row.assessment_enc) for row in rows]


@router.get("/{student_name}/profile")
async def get_profile(
    student_name: str,
    _: dict = Depends(require_real_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return the most recent learner profile for a student (parent or child token)."""
    result = await db.execute(
        select(LearnerProfile)
        .where(LearnerProfile.student_name == student_name)
        .order_by(LearnerProfile.created_at.desc())
        .limit(1)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No learner profile yet — complete a session to build one.",
        )
    return decrypt_json(row.profile_enc)


@router.get("/{student_name}/profile/history")
async def get_profile_history(
    student_name: str,
    limit: int = Query(default=20, le=100),
    _: dict = Depends(require_parent),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Parent retrieves every past learner profile, most recent first — how
    the profile evolved over time rather than only its current state."""
    result = await db.execute(
        select(LearnerProfile)
        .where(LearnerProfile.student_name == student_name)
        .order_by(LearnerProfile.created_at.desc())
        .limit(limit)
    )
    rows = result.scalars().all()
    return [decrypt_json(row.profile_enc) for row in rows]


@router.post("/{student_name}/profile")
async def build_profile(
    student_name: str,
    session_count: int = Query(..., ge=1, description="Total sessions completed so far"),
    _: dict = Depends(require_real_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Synthesize the learner profile from accumulated assessments and append
    it as a new history entry — the parent-forced counterpart to
    services.ai_service.refresh_learner_profile_if_stale, which does the
    same thing automatically at session end but skips when nothing's
    changed. This endpoint always runs, regardless of staleness, since a
    parent clicking "refresh" expects a fresh read right now.

    Frontend calls this at the end of the very first session (an initial,
    lower-confidence read parents can act on immediately) and again after
    each subsequent session as more narrations accumulate.
    """
    result = await db.execute(
        select(NarrationAssessment)
        .where(NarrationAssessment.student_name == student_name)
        .order_by(NarrationAssessment.session_date.desc())
        .limit(30)
    )
    rows = result.scalars().all()

    if len(rows) < 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No narrations recorded yet — complete a session first.",
        )

    assessments = [decrypt_json(row.assessment_enc) for row in rows]
    profile = await synthesize_learner_profile(student_name, assessments, session_count)
    profile["session_count_assessed"] = session_count
    profile["assessed_at"] = datetime.now(timezone.utc).isoformat()
    profile["rubric_version"] = RUBRIC_VERSION

    db.add(LearnerProfile(
        student_name=student_name,
        session_count=session_count,
        rubric_version=RUBRIC_VERSION,
        profile_enc=encrypt_json(profile),
    ))
    await db.commit()
    return profile
