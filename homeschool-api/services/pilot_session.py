"""Live tutoring for a Valor pilot learner, delivering teacher-approved instruction.

A pilot learner exists only as an immutable campus-scoped UUID (G1). It has
no name-keyed ``StudentConfig``, and must never acquire one: name-keyed rows
are exactly what lets two same-named children on different campuses collide.
So a pilot session differs from a household session in three ways, each
deliberate:

* **The plan is the owner's.** ``PilotSessionPlan`` (grade + subjects), set
  with an administrator passkey, is the only authority for what may be
  taught. The request body's ``session_config`` is discarded on every turn.
* **The instruction is pinned at launch.** The latest approved or edited
  recommendation is copied into the launch row with its SHA-256, so what
  reaches the learner is exactly what the teacher authorized, even if another
  decision lands mid-session. A rejected or pending draft is never used.
* **Nothing is persisted by name.** The tutor stream runs with ``db=None``,
  so no narration, mastery, bookmark or ledger row is written under a display
  name. Learning evidence for a pilot learner is recorded by the teacher on
  the UUID routes, which is the G2 loop.

Every turn re-checks, live: the launch belongs to this educator, it is not
stale, the educator still holds an active grant for that learner, and the
subject is in the owner's plan.
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import PilotLearner
from core.encryption import aad_for, decrypt_json, encrypt_json
from core.pilot_journey_models import (
    PilotRecommendation, PilotSessionLaunch, PilotSessionPlan,
)
from models.schemas import VALID_GRADES, SessionConfig, Subject, grade_to_stage
from routers.pilot_campuses import _assigned, _id, _render
from services.educator_access import live_educator

SESSION_MAX_AGE = timedelta(hours=8)
# lesson_focus is truncated to 500 characters at prompt-build time
# (_sanitize_parent_field), so the prefix plus the longest instruction a
# teacher can authorize must fit inside it, verbatim.
INSTRUCTION_PREFIX = "Teacher-authorized focus: "
MAX_INSTRUCTION_CHARS = 450
_FOCUS_LIMIT = 500
assert len(INSTRUCTION_PREFIX) + MAX_INSTRUCTION_CHARS <= _FOCUS_LIMIT

_NOT_FOUND = HTTPException(status_code=404, detail="Record not found")


class SessionPlanInput(BaseModel):
    grade: str = Field(min_length=1, max_length=2)
    subjects: list[Subject] = Field(min_length=1, max_length=20)
    session_cap_minutes: int | None = Field(default=None, ge=30, le=240)


def _aad(table: str, column: str, campus_id: str, learner_id: str, row_id: str) -> bytes:
    return aad_for(table, column, f"{campus_id}:{learner_id}:{row_id}")


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest() if text else ""


def build_config(display_name: str, plan: dict, instruction: str | None) -> SessionConfig:
    """Construct a real SessionConfig so every product validator applies
    (grade, subjects, the K-2 Logic gate) exactly as for a household."""
    if plan["grade"] not in VALID_GRADES:
        raise ValueError(f"Grade must be one of {', '.join(VALID_GRADES)}")
    fields = {"student_name": display_name, "grade": plan["grade"],
              "grade_stage": grade_to_stage(plan["grade"]),
              "subjects": plan["subjects"]}
    if plan.get("session_cap_minutes"):
        fields["session_cap_minutes"] = plan["session_cap_minutes"]
    if instruction:
        fields["lesson_focus"] = INSTRUCTION_PREFIX + instruction
    return SessionConfig(**fields)


def validated_plan(learner_display: str, payload: SessionPlanInput) -> dict:
    """Validate a plan by building the config it would produce. Stores the
    CLEANED values (e.g. Logic dropped for K-2), never the raw request."""
    try:
        cfg = build_config(learner_display, payload.model_dump(mode="json"), None)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc).splitlines()[0][:200])
    if not cfg.subjects:
        raise HTTPException(status_code=422, detail="No subject in this plan is valid for that grade")
    return {"grade": cfg.grade, "subjects": [s.value for s in cfg.subjects],
            "session_cap_minutes": payload.session_cap_minutes}


async def load_plan(db: AsyncSession, learner: PilotLearner) -> dict | None:
    row = await db.get(PilotSessionPlan, learner.id)
    if row is None or row.campus_id != learner.campus_id:
        return None
    return decrypt_json(row.plan_enc, _aad("pilot_session_plans", "plan_enc",
                                           learner.campus_id, learner.id, learner.id))


async def save_plan(db: AsyncSession, learner: PilotLearner, plan: dict) -> None:
    blob = encrypt_json(plan, _aad("pilot_session_plans", "plan_enc",
                                   learner.campus_id, learner.id, learner.id))
    row = await db.get(PilotSessionPlan, learner.id)
    if row is None:
        db.add(PilotSessionPlan(learner_id=learner.id, campus_id=learner.campus_id,
                                plan_enc=blob, updated_at=datetime.now(timezone.utc)))
    else:
        row.plan_enc, row.updated_at = blob, datetime.now(timezone.utc)


async def latest_authorized(db: AsyncSession, learner: PilotLearner) -> tuple[str | None, str | None]:
    """(recommendation_id, authorized text) for the newest approved/edited
    decision, or (None, None). Pending and rejected drafts never qualify."""
    rec = (await db.execute(
        select(PilotRecommendation)
        .where(PilotRecommendation.learner_id == learner.id,
               PilotRecommendation.campus_id == learner.campus_id,
               PilotRecommendation.status.in_(("approved", "edited")))
        .order_by(PilotRecommendation.decided_at.desc(), PilotRecommendation.id)
        .limit(1)
    )).scalar_one_or_none()
    if rec is None or rec.authorized_enc is None:
        return None, None
    text = decrypt_json(rec.authorized_enc, aad_for(
        "pilot_recommendations", "authorized_enc",
        f"{learner.campus_id}:{learner.id}:{rec.id}"))["text"]
    return rec.id, text


async def launch(db: AsyncSession, auth: dict, learner_id: str) -> dict:
    learner = await _assigned(db, auth, learner_id)
    teacher = await live_educator(db, auth)
    plan = await load_plan(db, learner)
    if plan is None:
        raise HTTPException(status_code=409,
                            detail="The owner has not set a session plan for this learner yet")
    rec_id, text = await latest_authorized(db, learner)
    launch_id = str(uuid.uuid4())
    row = PilotSessionLaunch(
        id=launch_id, campus_id=learner.campus_id, learner_id=learner.id,
        educator_id=teacher.id, recommendation_id=rec_id,
        instruction_sha256=sha256(text or ""),
        instruction_enc=(encrypt_json({"text": text}, _aad(
            "pilot_session_launches", "instruction_enc",
            learner.campus_id, learner.id, launch_id)) if text else None),
        started_at=datetime.now(timezone.utc), turns=0,
    )
    db.add(row)
    await db.commit()
    display = _render(learner)["display_name"]
    return {
        "pilot_session_id": launch_id,
        "learner_id": learner.id,
        "recommendation_id": rec_id,
        "instruction": text,
        "instruction_sha256": row.instruction_sha256,
        "session_config": build_config(display, plan, text).model_dump(mode="json"),
    }


async def config_for_turn(
    db: AsyncSession, auth: dict, pilot_session_id: str, subject: Subject,
) -> SessionConfig:
    """The authoritative config for one live turn; refuses on any failed check."""
    row = await db.get(PilotSessionLaunch, _id(pilot_session_id))
    teacher = await live_educator(db, auth)
    if row is None or row.educator_id != teacher.id:
        raise _NOT_FOUND
    started = row.started_at if row.started_at.tzinfo else row.started_at.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) - started > SESSION_MAX_AGE:
        raise HTTPException(status_code=410, detail="This pilot session has ended; start a new one")
    learner = await _assigned(db, auth, row.learner_id)  # live grant re-check
    plan = await load_plan(db, learner)
    if plan is None or subject.value not in plan["subjects"]:
        raise HTTPException(status_code=403, detail="Subject not included in the owner's session plan")
    text = None
    if row.instruction_enc is not None:
        text = decrypt_json(row.instruction_enc, _aad(
            "pilot_session_launches", "instruction_enc",
            row.campus_id, row.learner_id, row.id))["text"]
    await db.execute(update(PilotSessionLaunch).where(PilotSessionLaunch.id == row.id)
                     .values(turns=PilotSessionLaunch.turns + 1,
                             last_turn_at=datetime.now(timezone.utc)))
    await db.commit()
    return build_config(_render(learner)["display_name"], plan, text)


def render_launch(row: PilotSessionLaunch) -> dict:
    return {
        "pilot_session_id": row.id, "learner_id": row.learner_id,
        "campus_id": row.campus_id, "educator_id": row.educator_id,
        "recommendation_id": row.recommendation_id,
        "instruction_sha256": row.instruction_sha256,
        "started_at": row.started_at.isoformat(), "turns": row.turns,
        "last_turn_at": row.last_turn_at.isoformat() if row.last_turn_at else None,
    }
