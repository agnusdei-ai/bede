"""
Narration assessment history and learner-profile endpoints.

All assessment data is AES-256-GCM encrypted at rest — the DB never holds
plaintext narration scores or profile notes.

Routes:
  GET  /narration/{student}/assessments     — parent: score history
  GET  /narration/{student}/profile         — parent or child: current learner profile
  POST /narration/{student}/profile         — trigger profile synthesis (after session 1+)
  GET  /narration/{student}/behavior-check  — parent only: does Bede's kinesthetic
                                               adaptation actually change its own
                                               behavior (see LearnerBehaviorCheck)

Synthesis is available from the very first session on purpose — parents
should have an initial read on how their child learns (and Bede's first
recommendations) right away, not after waiting three sessions. It's simply
lower-confidence with fewer data points; the profile can (and should) be
rebuilt again after each additional session as more narrations accumulate.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import LearnerBehaviorCheck, LearnerProfile, NarrationAssessment, get_db
from core.deps import require_parent, require_real_user
from core.encryption import decrypt_json, encrypt_json
from services.ai_service import synthesize_learner_profile

router = APIRouter(prefix="/narration", tags=["narration"])


async def _sync_behavior_check(db: AsyncSession, student_name: str, old_style: str | None, new_style: str) -> None:
    """
    Keeps LearnerBehaviorCheck's existence tied to "is this student CURRENTLY
    profiled kinesthetic" — see that model's own docstring for why. Called
    once per profile (re)synthesis, comparing the style that's being
    replaced against the one just computed:
      - newly kinesthetic (wasn't before, or no prior profile) -> fresh row,
        count reset to 0 so the observation reflects this labeling, not a
        stale one from a much earlier, possibly-different period.
      - still kinesthetic across this rebuild -> leave the existing row
        alone; resetting it every rebuild would make the count too noisy
        to mean anything (narrations get reassessed roughly every session).
      - no longer kinesthetic -> delete the row; no reason to keep counting
        (or retain) a behavior check for a label the student no longer has.
    """
    if new_style == "kinesthetic":
        if old_style == "kinesthetic":
            return
        existing = await db.execute(
            select(LearnerBehaviorCheck).where(LearnerBehaviorCheck.student_name == student_name)
        )
        row = existing.scalar_one_or_none()
        count_enc = encrypt_json({"invite_handwriting_count": 0})
        if row is None:
            db.add(LearnerBehaviorCheck(student_name=student_name, count_enc=count_enc))
        else:
            row.count_enc = count_enc
            row.since = datetime.now(timezone.utc)
    else:
        await db.execute(
            delete(LearnerBehaviorCheck).where(LearnerBehaviorCheck.student_name == student_name)
        )


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
    """Return the current learner profile for a student (parent or child token)."""
    result = await db.execute(
        select(LearnerProfile).where(LearnerProfile.student_name == student_name)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No learner profile yet — complete a session to build one.",
        )
    return decrypt_json(row.profile_enc)


@router.post("/{student_name}/profile")
async def build_profile(
    student_name: str,
    session_count: int = Query(..., ge=1, description="Total sessions completed so far"),
    _: dict = Depends(require_real_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Synthesize (or refresh) the learner profile from accumulated assessments.
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

    enc = encrypt_json(profile)
    existing = await db.execute(
        select(LearnerProfile).where(LearnerProfile.student_name == student_name)
    )
    row = existing.scalar_one_or_none()
    old_processing_style = decrypt_json(row.profile_enc).get("processing_style") if row is not None else None
    if row is None:
        db.add(LearnerProfile(
            student_name=student_name,
            session_count=session_count,
            profile_enc=enc,
        ))
    else:
        row.profile_enc = enc
        row.session_count = session_count

    await _sync_behavior_check(db, student_name, old_processing_style, profile["processing_style"])

    await db.commit()
    return profile


@router.get("/{student_name}/behavior-check")
async def get_behavior_check(
    student_name: str,
    _: dict = Depends(require_parent),
    db: AsyncSession = Depends(get_db),
) -> dict | None:
    """
    Parent-only (unlike GET /profile above, which a child token can also
    read) — see LearnerBehaviorCheck's docstring for what this is and
    isn't. Returns null when the student isn't currently profiled
    kinesthetic (no row exists) rather than 404 — this is an expected,
    common state, not an error.
    """
    result = await db.execute(
        select(LearnerBehaviorCheck).where(LearnerBehaviorCheck.student_name == student_name)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None
    return {
        "invite_handwriting_count": decrypt_json(row.count_enc)["invite_handwriting_count"],
        "since": row.since.isoformat(),
    }
