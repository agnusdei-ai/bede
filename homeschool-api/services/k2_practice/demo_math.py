"""Temporary Number Time lessons for public-demo sessions.

Lesson ids are demo-math-specific, bind to one live demo sign-in, and expire
no later than that sign-in. Attempt state is process-local and bounded; after
a restart an old id has no state and is refused rather than rebuilt with
fresh attempts.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field

from fastapi import HTTPException

from core.config import settings
from services.k2_practice import practical_math
from services.k2_practice.practical_math import Task

NOT_FOUND = "Practice is not available."
LESSON_TTL_SECONDS = 15 * 60
MAX_LESSONS = 1024
MAX_SUBMISSIONS_PER_LESSON = 10
_SUBMISSION_ID = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
_LOCK = threading.RLock()


@dataclass
class _LessonState:
    session_digest: str
    level: str
    topic: str
    seed: int
    expires_at: int
    expires_monotonic: float
    created_monotonic: float
    misses: dict[tuple[str, int], int] = field(default_factory=dict)
    settled: set[tuple[str, int]] = field(default_factory=set)
    submissions: dict[str, tuple[str, dict]] = field(default_factory=dict)


_lessons: OrderedDict[str, _LessonState] = OrderedDict()


def _session_digest(auth: dict) -> str:
    """Key one demo JWT's claims without retaining its code, name, or token."""
    code = auth.get("code")
    issued = auth.get("iat")
    expires = auth.get("exp")
    if not isinstance(code, str) or not code or type(issued) is not int or type(expires) is not int:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    material = f"{code}|{issued}|{expires}".encode()
    return hmac.new(
        settings.secret_key.encode(),
        b"k2-demo-math-session-v1|" + material,
        hashlib.sha256,
    ).hexdigest()


def _encode_id(auth: dict, level: str, topic: str, seed: int, expires_at: int) -> str:
    claims = {
        "v": 1,
        "session": _session_digest(auth),
        "level": level,
        "topic": topic,
        "seed": seed,
        "exp": expires_at,
        "nonce": secrets.token_hex(8),
    }
    payload = json.dumps(claims, sort_keys=True, separators=(",", ":")).encode()
    encoded = base64.urlsafe_b64encode(payload).rstrip(b"=").decode()
    mac = hmac.new(
        settings.secret_key.encode(),
        b"k2-demo-math-lesson-v1|" + encoded.encode(),
        hashlib.sha256,
    ).digest()
    signature = base64.urlsafe_b64encode(mac).rstrip(b"=").decode()
    return f"{encoded}.{signature}"


def _decode_id(auth: dict, lesson_id: str) -> tuple[dict, str]:
    try:
        if not isinstance(lesson_id, str) or len(lesson_id) > 512:
            raise ValueError
        encoded, signature = lesson_id.split(".")
        expected = base64.urlsafe_b64encode(hmac.new(
            settings.secret_key.encode(),
            b"k2-demo-math-lesson-v1|" + encoded.encode(),
            hashlib.sha256,
        ).digest()).rstrip(b"=").decode()
        if not hmac.compare_digest(signature, expected):
            raise ValueError
        payload = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        claims = json.loads(payload)
        if (not isinstance(claims, dict) or set(claims) != {"v", "session", "level", "topic", "seed", "exp", "nonce"}
                or type(claims["v"]) is not int or claims["v"] != 1
                or type(claims["seed"]) is not int or not 0 <= claims["seed"] < 1_000_000_000
                or type(claims["exp"]) is not int or claims["exp"] <= int(time.time())
                or not isinstance(claims["nonce"], str) or len(claims["nonce"]) != 16
                or claims["level"] not in practical_math.LEVELS
                or claims["topic"] not in practical_math.LEVEL_TOPICS[claims["level"]]):
            raise ValueError
        session_digest = _session_digest(auth)
        if not hmac.compare_digest(claims["session"], session_digest):
            raise ValueError
        return claims, session_digest
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        raise HTTPException(status_code=404, detail=NOT_FOUND) from None


def _purge(now: float) -> None:
    expired = [key for key, state in _lessons.items() if state.expires_monotonic <= now]
    for key in expired:
        _lessons.pop(key, None)


def create_lesson(auth: dict, level: str, topic: str | None = None) -> dict:
    if level not in practical_math.LEVELS:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    allowed_topics = practical_math.LEVEL_TOPICS[level]
    chosen_topic = topic or allowed_topics[0]
    if chosen_topic not in allowed_topics:
        raise HTTPException(status_code=422, detail="Choose a topic available for this grade.")

    now = time.monotonic()
    session_expiry = auth.get("exp")
    if type(session_expiry) is not int or session_expiry <= int(time.time()):
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    expires_at = min(session_expiry, int(time.time()) + LESSON_TTL_SECONDS)
    seed = secrets.randbelow(1_000_000_000)
    lesson_id = _encode_id(auth, level, chosen_topic, seed, expires_at)
    lesson = practical_math.build_lesson(level, seed, chosen_topic, audio=True)
    lesson.update(
        lesson_id=lesson_id,
        your_turn_tries=2,
        available_topics=list(allowed_topics),
        demo=True,
        recorded=False,
    )
    with _LOCK:
        _purge(now)
        while len(_lessons) >= MAX_LESSONS:
            _lessons.popitem(last=False)
        _lessons[lesson_id] = _LessonState(
            session_digest=_session_digest(auth),
            level=level,
            topic=chosen_topic,
            seed=seed,
            expires_at=expires_at,
            expires_monotonic=now + max(0, expires_at - int(time.time())),
            created_monotonic=now,
        )
    return lesson


def answer(
    auth: dict,
    lesson_id: str,
    phase: str,
    index: int,
    choice: str,
    submission_id: str,
    current_level: str,
) -> dict:
    if not isinstance(submission_id, str) or not _SUBMISSION_ID.fullmatch(submission_id):
        raise HTTPException(status_code=422, detail="A valid submission id is required.")
    claims, session_digest = _decode_id(auth, lesson_id)
    fingerprint = hashlib.sha256(
        json.dumps(
            {"phase": phase, "index": index, "choice": choice},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    with _LOCK:
        now = time.monotonic()
        _purge(now)
        state = _lessons.get(lesson_id)
        if (
            state is None
            or state.expires_at <= int(time.time())
            or state.expires_monotonic <= now
            or state.level != current_level
            or not hmac.compare_digest(state.session_digest, session_digest)
            or state.level != claims["level"]
            or state.topic != claims["topic"]
            or state.seed != claims["seed"]
        ):
            raise HTTPException(status_code=404, detail=NOT_FOUND)

        prior = state.submissions.get(submission_id)
        if prior is not None:
            prior_fingerprint, result = prior
            if not hmac.compare_digest(prior_fingerprint, fingerprint):
                raise HTTPException(status_code=409, detail="Submission id was already used.")
            _lessons.move_to_end(lesson_id)
            return dict(result)

        try:
            task: Task = practical_math.build_task(
                state.level, state.topic, state.seed, phase, index,
            )
        except ValueError:
            raise HTTPException(status_code=404, detail=NOT_FOUND) from None
        if choice not in task.choices:
            raise HTTPException(status_code=422, detail="That is not one of the choices.")
        if len(state.submissions) >= MAX_SUBMISSIONS_PER_LESSON:
            raise HTTPException(status_code=409, detail="This round is complete.")

        key = (phase, index)
        if key in state.settled:
            raise HTTPException(status_code=409, detail="This question is already complete.")

        correct = task.is_right(choice)
        if phase == "together":
            state.settled.add(key)
            result = {
                "understood": True,
                "correct": correct,
                **({} if correct else {"reveal": task.reveal()}),
            }
        elif not correct:
            misses = state.misses.get(key, 0) + 1
            state.misses[key] = misses
            if misses >= 2:
                state.settled.add(key)
                result = {
                    "understood": True,
                    "correct": False,
                    "tries_left": 0,
                    "reveal": task.reveal(),
                }
            else:
                result = {"understood": True, "correct": False, "tries_left": 1}
        else:
            state.settled.add(key)
            result = {"understood": True, "correct": True}

        response = {**result, "demo": True, "recorded": False}
        state.submissions[submission_id] = (fingerprint, response)
        _lessons.move_to_end(lesson_id)
        return dict(response)


def clear_state() -> None:
    """Clear volatile state for tests and controlled process shutdown."""
    with _LOCK:
        _lessons.clear()
