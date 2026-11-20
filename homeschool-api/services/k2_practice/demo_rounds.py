"""Temporary Sound Time and Map Practice rounds for public-demo sessions.

The same boundary as Number Time's demo rounds (demo_math.py, decision 40(g)
as amended 2026-11-19): a round belongs to one live demo sign-in and expires
no later than it; its state lives only in this process and is bounded; after
a restart an old round id has no state and is refused. Nothing reads or
writes a learner record, a ledger row, mastery, or demo progress, and every
answer says ``recorded: false``. No model is called.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Optional

from fastapi import HTTPException

from core.config import settings
from services import map_practice as maps
from services.k2_practice import phonics

NOT_FOUND = "Practice is not available."
AREAS = ("phonics", "maps")
LESSON_TTL_SECONDS = 15 * 60
MAX_LESSONS = 1024
MAX_ANSWERS_PER_LESSON = 20
YOUR_TURN_TRIES = 2
_LOCK = threading.RLock()


@dataclass
class _Round:
    area: str
    session_digest: str
    level: str
    focus: str  # the phonics domain or the map skill
    seed: int
    audio: bool
    expires_at: int
    misses: dict[int, int] = field(default_factory=dict)
    settled: set[tuple[str, int]] = field(default_factory=set)
    answers: int = 0


_rounds: OrderedDict[str, _Round] = OrderedDict()


def _session_digest(auth: dict) -> str:
    """Key one demo sign-in's claims without keeping its code, name or token."""
    code, issued, expires = auth.get("code"), auth.get("iat"), auth.get("exp")
    if not isinstance(code, str) or not code or type(issued) is not int or type(expires) is not int:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    return hmac.new(
        settings.secret_key.encode(),
        f"k2-demo-round-session-v1|{code}|{issued}|{expires}".encode(),
        hashlib.sha256,
    ).hexdigest()


def _purge(now: int) -> None:
    for key in [k for k, r in _rounds.items() if r.expires_at <= now]:
        _rounds.pop(key, None)


def create_lesson(auth: dict, area: str, level: str, *, audio: bool = True) -> dict:
    """A new temporary round for the demo sign-in's server-held grade."""
    if area not in AREAS:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    session_expiry = auth.get("exp")
    now = int(time.time())
    if type(session_expiry) is not int or session_expiry <= now:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    seed = secrets.randbelow(1_000_000)
    if area == "phonics":
        if level not in phonics.LEVELS:
            raise HTTPException(status_code=404, detail=NOT_FOUND)
        focus = phonics.domain_for(level)
        lesson = phonics.build_lesson(level, seed, focus, audio=audio)
    else:
        if level not in maps.LEVELS:
            raise HTTPException(status_code=404, detail=NOT_FOUND)
        lesson = maps.build_lesson(level, seed, None)
        focus = lesson["skill"]
    lesson_id = secrets.token_urlsafe(24)
    lesson.update(lesson_id=lesson_id, your_turn_tries=YOUR_TURN_TRIES, demo=True, recorded=False)
    with _LOCK:
        _purge(now)
        while len(_rounds) >= MAX_LESSONS:
            _rounds.popitem(last=False)
        _rounds[lesson_id] = _Round(
            area=area, session_digest=_session_digest(auth), level=level, focus=focus,
            seed=seed, audio=audio, expires_at=min(session_expiry, now + LESSON_TTL_SECONDS),
        )
    return lesson


def _task(state: _Round, phase: str, index: int):
    try:
        if state.area == "phonics":
            return phonics.build_task(state.level, state.focus, state.seed, phase, index)
        return maps.build_task(state.level, state.focus, state.seed, phase, index)
    except ValueError:
        raise HTTPException(status_code=404, detail=NOT_FOUND) from None


def _check(state: _Round, task, cell: Optional[tuple[int, int]], choice: Optional[str]) -> bool:
    """Whether the answer is right, after refusing one that does not fit."""
    if state.area == "phonics":
        if cell is not None or choice not in task.choices:
            raise HTTPException(status_code=422, detail="That is not one of the choices.")
        return task.is_right(choice)
    if (cell is not None) != (task.answer_kind == "tap"):
        raise HTTPException(status_code=422, detail="That kind of answer does not fit this question.")
    if task.answer_kind == "choice" and choice not in task.choices:
        raise HTTPException(status_code=422, detail="That is not one of the choices.")
    if task.answer_kind == "scene_choice" and choice not in {str(i) for i in range(len(task.options))}:
        raise HTTPException(status_code=422, detail="That is not one of the choices.")
    if cell is not None and not task.scene.inside(tuple(cell)):
        raise HTTPException(status_code=422, detail="That square is not on the map.")
    return task.is_right(cell=cell, choice=choice)


def answer(
    auth: dict,
    area: str,
    lesson_id: str,
    phase: str,
    index: int,
    *,
    current_level: str,
    choice: Optional[str] = None,
    cell: Optional[tuple[int, int]] = None,
) -> dict:
    """Check one answer. Nothing is kept beyond this round's own tries."""
    digest = _session_digest(auth)
    with _LOCK:
        now = int(time.time())
        _purge(now)
        state = _rounds.get(lesson_id) if isinstance(lesson_id, str) else None
        if (state is None or state.area != area or state.level != current_level
                or not hmac.compare_digest(state.session_digest, digest)):
            raise HTTPException(status_code=404, detail=NOT_FOUND)
        if area == "phonics" and not state.audio and state.focus in phonics.AUDIO_ONLY_DOMAINS:
            raise HTTPException(status_code=404, detail=NOT_FOUND)
        task = _task(state, phase, index)
        right = _check(state, task, cell, choice)
        key = (phase, index)
        if key in state.settled:
            raise HTTPException(status_code=409, detail="This question is already complete.")
        if state.answers >= MAX_ANSWERS_PER_LESSON:
            raise HTTPException(status_code=409, detail="This round is complete.")
        state.answers += 1
        _rounds.move_to_end(lesson_id)

        if phase == "together":
            # Guided: a miss shows the answer straight away.
            state.settled.add(key)
            result = {"understood": True, "correct": right, **({} if right else {"reveal": task.reveal()})}
        elif right:
            state.settled.add(key)
            result = {"understood": True, "correct": True}
        else:
            misses = state.misses.get(index, 0) + 1
            state.misses[index] = misses
            if misses >= YOUR_TURN_TRIES:
                state.settled.add(key)
                result = {"understood": True, "correct": False, "tries_left": 0, "reveal": task.reveal()}
            else:
                result = {"understood": True, "correct": False, "tries_left": YOUR_TURN_TRIES - misses}
        return {**result, "demo": True, "recorded": False}


def clear_state() -> None:
    """Clear volatile state for tests and controlled process shutdown."""
    with _LOCK:
        _rounds.clear()
