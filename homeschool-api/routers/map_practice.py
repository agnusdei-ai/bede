"""Map-reading practice for K-2 (services/map_practice.py).

Two routes, for the child's own session (or the parent trying it):

    GET  /map-practice/{student}/lesson             a new lesson
    POST /map-practice/{student}/lessons/{id}/answers   check one answer

Nothing about a lesson is stored. A lesson id names the level, skill, seed
and day and is signed for one learner, so the server rebuilds the same
lesson to check an answer and a made-up id is refused. A task finished in
"Your turn" adds one row to the work ledger, once; there is no map score.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from core import consent, student_keys
from core.config import settings
from core.database import StudentConfig, get_db
from core.deps import require_family_data_write, require_learner_access, require_real_user
from core.encryption import decrypt_json
from models.schemas import SessionConfig
from services import map_practice as maps
from services.diagnostic.activity import record_activity

log = logging.getLogger("sage.map_practice")

router = APIRouter(prefix="/map-practice", tags=["map-practice"])

NOT_FOUND = "Map practice is not available."
#: Misses allowed on a "Your turn" task before the answer is shown and the
#: child moves on. A task ended that way is not recorded as completed work.
YOUR_TURN_TRIES = 2
_PROGRESS_TTL_SECONDS = 6 * 60 * 60
_MAX_PROGRESS = 4096

#: (student, lesson id) -> {"at": monotonic, "misses": {index: n}, "done": set}.
#: In memory only, like the lesson: a restart forgets misses, never a child's record.
_progress: dict[tuple[str, str], dict] = {}


def _mac(student_name: str, body: str) -> str:
    msg = f"map-practice|{student_name}|{body}".encode()
    return hmac.new(settings.secret_key.encode(), msg, hashlib.sha256).hexdigest()[:20]


def _today() -> datetime:
    return datetime.now(timezone.utc)


def mint_lesson_id(student_name: str, level: str, skill: str, seed: int) -> str:
    body = f"{level}-{maps.SKILLS[level].index(skill)}-{seed}-{_today():%Y%m%d}"
    return f"{body}-{_mac(student_name, body)}"


def read_lesson_id(student_name: str, lesson_id: str) -> tuple[str, str, int]:
    """(level, skill, seed) for an id this server signed for this learner
    today or yesterday. Anything else is the same 404."""
    try:
        level, skill_index, seed, day, mac = lesson_id.split("-")
        body = f"{level}-{skill_index}-{seed}-{day}"
        if not hmac.compare_digest(mac, _mac(student_name, body)):
            raise ValueError
        valid_days = {f"{_today() - timedelta(days=n):%Y%m%d}" for n in (0, 1)}
        if day not in valid_days or level not in maps.LEVELS:
            raise ValueError
        return level, maps.SKILLS[level][int(skill_index)], int(seed)
    except (ValueError, IndexError):
        raise HTTPException(status_code=404, detail=NOT_FOUND) from None


def _state(student_name: str, lesson_id: str) -> dict:
    now = time.monotonic()
    if len(_progress) >= _MAX_PROGRESS:
        for key in [k for k, v in _progress.items() if now - v["at"] > _PROGRESS_TTL_SECONDS]:
            _progress.pop(key, None)
        while len(_progress) >= _MAX_PROGRESS:
            _progress.pop(next(iter(_progress)))
    state = _progress.setdefault((student_name, lesson_id), {"at": now, "misses": {}, "done": set()})
    state["at"] = now
    return state


async def _level_for(db: AsyncSession, student_name: str) -> str:
    """The learner's level from their SAVED grade, never from the request."""
    row = await db.get(StudentConfig, student_name)
    if row is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    from routers.pod import _config_aad

    config = SessionConfig(**decrypt_json(
        row.config_enc, _config_aad(student_name), await student_keys.get_existing(db, student_name)
    ))
    level = maps.level_for_grade(config.grade)
    if level is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    return level


@router.get("/{student_name}/lesson")
async def new_lesson(
    student_name: str,
    skill: Optional[str] = Query(default=None, max_length=40),
    auth: dict = Depends(require_real_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await require_learner_access(auth, student_name, db)
    await consent.require_collection(db, student_name)
    level = await _level_for(db, student_name)
    seed = secrets.randbelow(1_000_000)
    lesson = maps.build_lesson(level, seed, skill)
    lesson["lesson_id"] = mint_lesson_id(student_name, level, lesson["skill"], seed)
    lesson["your_turn_tries"] = YOUR_TURN_TRIES
    return lesson


class MapAnswer(BaseModel):
    """One answer. Exactly one of a square, a choice, or spoken words; no
    other text is accepted, so nothing a child types or says is kept."""
    model_config = ConfigDict(extra="forbid")

    phase: Literal["together", "your_turn"]
    index: int = Field(ge=0, le=9)
    cell: Optional[tuple[int, int]] = None
    choice: Optional[str] = Field(default=None, max_length=24)
    spoken: Optional[str] = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _one_answer(self) -> "MapAnswer":
        if sum(v is not None for v in (self.cell, self.choice, self.spoken)) != 1:
            raise ValueError("send exactly one of cell, choice or spoken")
        return self


@router.post("/{student_name}/lessons/{lesson_id}/answers")
async def answer(
    student_name: str,
    lesson_id: str,
    body: MapAnswer,
    auth: dict = Depends(require_family_data_write),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await require_learner_access(auth, student_name, db)
    await consent.require_collection(db, student_name)
    level, skill, seed = read_lesson_id(student_name, lesson_id)
    try:
        task = maps.build_task(level, skill, seed, body.phase, body.index)
    except ValueError:
        raise HTTPException(status_code=404, detail=NOT_FOUND) from None

    choice = body.choice
    if body.spoken is not None:
        choice = maps.match_spoken(task, body.spoken)
        if choice is None:
            # Not understood is not a miss: ask again, count nothing.
            return {"understood": False, "correct": False}
    if (body.cell is not None) != (task.answer_kind == "tap"):
        raise HTTPException(status_code=422, detail="That kind of answer does not fit this question.")
    if task.answer_kind == "choice" and choice not in task.choices:
        raise HTTPException(status_code=422, detail="That is not one of the choices.")
    if task.answer_kind == "scene_choice" and choice not in {str(i) for i in range(len(task.options))}:
        raise HTTPException(status_code=422, detail="That is not one of the choices.")
    if body.cell is not None and not task.scene.inside(tuple(body.cell)):
        raise HTTPException(status_code=422, detail="That square is not on the map.")

    right = task.is_right(cell=body.cell, choice=choice)
    if body.phase == "together":
        # Guided: a miss shows the answer straight away. Nothing is recorded.
        return {"understood": True, "correct": right, **({} if right else {"reveal": task.reveal()})}

    state = _state(student_name, lesson_id)
    misses = state["misses"].get(body.index, 0)
    if not right:
        misses += 1
        state["misses"][body.index] = misses
        if misses >= YOUR_TURN_TRIES:
            return {"understood": True, "correct": False, "tries_left": 0, "reveal": task.reveal()}
        return {"understood": True, "correct": False, "tries_left": YOUR_TURN_TRIES - misses}

    recorded = False
    if body.index not in state["done"] and misses < YOUR_TURN_TRIES:
        state["done"].add(body.index)
        recorded = await record_activity(
            db, student_name, maps.LEDGER_SUBJECT_AREA, skill, maps.SKILL_LABELS[skill],
            "correct" if misses == 0 else "partial",
        )
    return {"understood": True, "correct": True, "recorded": recorded}
