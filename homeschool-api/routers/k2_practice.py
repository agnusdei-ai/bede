"""K-2 phonics practice routes (services/k2_practice/phonics.py,
docs/K2_PRACTICE.md §5.1). Modelled on routers/map_practice.py.

    GET  /k2-practice/{student}/phonics/lesson                 a new lesson
    POST /k2-practice/{student}/phonics/lessons/{id}/answers   check one answer

Nothing about a lesson is stored. A lesson id names the level, domain, seed
and day and is signed for one learner, so the server rebuilds the same
lesson to check an answer and a made-up id is refused. The level comes from
the learner's SAVED grade, and the domain from their saved phonics record;
nothing in a request chooses either.

What a "Your turn" question records (decision 40(b), owner ruling
2026-11-16; the weights are product defaults, not research values):

    right on the first try    one ledger row (unaided), and a phonics
                              observation at QUIZ_EVIDENCE_WEIGHT (0.5)
    right on the second try   one ledger row (with a hint), and a phonics
                              observation at half that (0.25)

Each observation moves the estimate by its weight alone, without the
early-evidence boost other check-ins get (owner ruling 2026-11-16), so from a
fresh record no single practice answer can make a domain secure.
    answer shown              nothing at all, the ledger's standing rule
                              for work that was not completed

Each question records once, however often it is retried. Watching and
Together record nothing. No call here reaches an AI provider.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from core import consent, student_keys
from core.config import settings
from core.database import StudentConfig, get_db
from core.deps import require_family_data_write, require_learner_access, require_real_user
from core.encryption import decrypt_json
from core.log_redaction import learner_ref
from models.schemas import GradeStage, SessionConfig
from services.diagnostic import phonics as phonics_record
from services.diagnostic.activity import record_activity
from services.k2_practice import phonics
from services.practice.evidence import QUIZ_EVIDENCE_WEIGHT

log = logging.getLogger("sage.k2_practice")

router = APIRouter(prefix="/k2-practice", tags=["k2-practice"])

NOT_FOUND = "Practice is not available."
#: Misses allowed on a "Your turn" question before the answer is shown.
YOUR_TURN_TRIES = 2

#: How far a "Your turn" answer moves the phonics estimate, by try. Owner
#: product defaults (decision 40(b), 2026-11-16), not research-backed values.
FIRST_TRY_WEIGHT = QUIZ_EVIDENCE_WEIGHT
SECOND_TRY_WEIGHT = QUIZ_EVIDENCE_WEIGHT / 2

_PROGRESS_TTL_SECONDS = 6 * 60 * 60
_MAX_PROGRESS = 4096

#: One recorded round per area per sign-in, and at most this many recorded
#: answers in it (owner ruling 2026-11-16, a product default). Later rounds
#: ("Another one") still work and record nothing.
MAX_RECORDED_ANSWERS = 3
AREA = "phonics"

#: (student, area, sign-in) -> {"at", "lesson_id", "count"}. Keyed on the
#: SIGN-IN (a digest of the authenticated token's own claims), never on the
#: client's session id, which a page reload re-mints: a reload or a fresh
#: lesson id must not open a second recorded round, and a new sign-in does.
#: In memory, like `_progress`: a server restart forgets it, so at most one
#: more round could record after a restart.
_rounds: dict[tuple[str, str, str], dict] = {}

#: (student, lesson id) -> {"at": monotonic, "misses": {index: n}, "done": set}.
#: In memory only, like map practice: a restart forgets misses, never a record.
_progress: dict[tuple[str, str], dict] = {}


def _mac(student_name: str, body: str) -> str:
    msg = f"k2-practice-phonics|{student_name}|{body}".encode()
    return hmac.new(settings.secret_key.encode(), msg, hashlib.sha256).hexdigest()[:20]


def _today() -> datetime:
    return datetime.now(timezone.utc)


def mint_lesson_id(student_name: str, level: str, domain: str, seed: int, audio: bool = True) -> str:
    body = f"{level}-{phonics.DOMAINS.index(domain)}-{seed}-{_today():%Y%m%d}-{1 if audio else 0}"
    return f"{body}-{_mac(student_name, body)}"


def read_lesson_id(student_name: str, lesson_id: str) -> tuple[str, str, int, bool]:
    """(level, domain, seed, audio) for an id this server signed for this
    learner today or yesterday. Anything else is the same 404. `audio` is
    signed in, so a lesson built without sound cannot be answered as one
    with it."""
    try:
        level, domain_index, seed, day, audio, mac = lesson_id.split("-")
        body = f"{level}-{domain_index}-{seed}-{day}-{audio}"
        if not hmac.compare_digest(mac, _mac(student_name, body)):
            raise ValueError
        valid_days = {f"{_today() - timedelta(days=n):%Y%m%d}" for n in (0, 1)}
        if day not in valid_days or level not in phonics.LEVELS or audio not in ("0", "1"):
            raise ValueError
        return level, phonics.DOMAINS[int(domain_index)], int(seed), audio == "1"
    except (ValueError, IndexError):
        raise HTTPException(status_code=404, detail=NOT_FOUND) from None


def sign_in_key(auth: dict) -> str:
    """A stable digest of one sign-in: the token's own claims, which survive a
    page reload and change with a new sign-in. Never a credential."""
    parts = [str(auth.get(k, "")) for k in ("role", "sub", "learner", "device_id", "iat", "exp")]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:24]


def _round(student_name: str, auth: dict) -> dict:
    now = time.monotonic()
    if len(_rounds) >= _MAX_PROGRESS:
        for key in [k for k, v in _rounds.items() if now - v["at"] > _PROGRESS_TTL_SECONDS]:
            _rounds.pop(key, None)
        while len(_rounds) >= _MAX_PROGRESS:
            _rounds.pop(next(iter(_rounds)))
    entry = _rounds.setdefault((student_name, AREA, sign_in_key(auth)),
                               {"at": now, "lesson_id": None, "count": 0})
    entry["at"] = now
    return entry


def _claim_round(student_name: str, auth: dict, lesson_id: str) -> None:
    """The first lesson served in a sign-in is its one recorded round."""
    entry = _round(student_name, auth)
    if entry["lesson_id"] is None:
        entry["lesson_id"] = lesson_id


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


async def _saved_config(db: AsyncSession, student_name: str) -> SessionConfig:
    row = await db.get(StudentConfig, student_name)
    if row is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    from routers.pod import _config_aad

    return SessionConfig(**decrypt_json(
        row.config_enc, _config_aad(student_name), await student_keys.get_existing(db, student_name)
    ))


async def saved_practice_offers(db: AsyncSession, student_name: str) -> str:
    """The per-child practice setting as the parent last SAVED it, never the
    copy a tablet sent with a turn. A tablet holds the config it loaded at the
    start of the session, so a parent switching a child to "off" or "only
    sets I approved" mid-session would otherwise not reach the offer gate.
    Fails closed: no saved row, or one that cannot be read, is "off"."""
    try:
        return (await _saved_config(db, student_name)).practice_offers
    except Exception:
        return "off"


async def _level_for(db: AsyncSession, student_name: str) -> str:
    """The learner's level from their SAVED grade, never from the request.
    Only "todays_subjects" serves a round in step 1: with "off" there is no
    practice, and with "only sets I approved" there is no approved phonics
    set yet, so neither may build a lesson or record evidence."""
    config = await _saved_config(db, student_name)
    level = phonics.level_for_grade(config.grade)
    if (level is None or config.grade_stage != GradeStage.foundations
            or config.practice_offers != "todays_subjects"):
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    return level


async def _saved_phonics_vector(db: AsyncSession, student_name: str) -> Optional[dict]:
    summary = await phonics_record.get_phonics_summary(db, student_name)
    if not summary:
        return None
    return {d["skills"][0]["skill_id"].split(".", 1)[1]: d["average_probability"] for d in summary["domains"]}


@router.get("/{student_name}/phonics/lesson")
async def new_lesson(
    student_name: str,
    audio: bool = True,
    auth: dict = Depends(require_real_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """`audio=false` means the child's device cannot speak this round. It may
    only remove questions that work only by ear; the level and domain still
    come from the saved grade and the saved phonics record."""
    await require_learner_access(auth, student_name, db)
    await consent.require_collection(db, student_name)
    level = await _level_for(db, student_name)
    domain = phonics.domain_for(level, await _saved_phonics_vector(db, student_name))
    seed = secrets.randbelow(1_000_000)
    lesson = phonics.build_lesson(level, seed, domain, audio=audio)
    lesson["lesson_id"] = mint_lesson_id(student_name, level, domain, seed, audio)
    _claim_round(student_name, auth, lesson["lesson_id"])
    lesson["your_turn_tries"] = YOUR_TURN_TRIES
    return lesson


class PhonicsAnswer(BaseModel):
    """One answer: a tapped choice or spoken words, never anything else, so
    nothing a child types or says is kept."""
    model_config = ConfigDict(extra="forbid")

    phase: Literal["together", "your_turn"]
    index: int = Field(ge=0, le=9)
    choice: Optional[str] = Field(default=None, max_length=24)
    spoken: Optional[str] = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _one_answer(self) -> "PhonicsAnswer":
        if (self.choice is None) == (self.spoken is None):
            raise ValueError("send exactly one of choice or spoken")
        return self


async def _record(db: AsyncSession, student_name: str, domain: str, first_try: bool) -> bool:
    """One completed question: a ledger row, then the weighted observation.
    Both best-effort, as every diagnostic write is. The observation moves the
    estimate by its weight alone and does not count toward the early-evidence
    window Bede's in-lesson check-ins use (owner rulings 2026-11-16)."""
    recorded = await record_activity(
        db, student_name, phonics.LEDGER_SUBJECT_AREA, domain, phonics.DOMAIN_LABELS[domain],
        "correct" if first_try else "partial",
    )
    if settings.retain_mastery_profiles:
        await phonics_record.process_evidence(
            db, student_name, domain, "correct",
            weight=FIRST_TRY_WEIGHT if first_try else SECOND_TRY_WEIGHT,
            # Practice moves the estimate by its weight alone, never the
            # early-evidence boost, and does not use up that window for
            # Bede's own check-ins (owner rulings 2026-11-16).
            skip_calibration_boost=True,
            count_toward_calibration=False,
        )
    return recorded


@router.post("/{student_name}/phonics/lessons/{lesson_id}/answers")
async def answer(
    student_name: str,
    lesson_id: str,
    body: PhonicsAnswer,
    auth: dict = Depends(require_family_data_write),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await require_learner_access(auth, student_name, db)
    await consent.require_collection(db, student_name)
    await _level_for(db, student_name)
    level, domain, seed, audio = read_lesson_id(student_name, lesson_id)
    if not audio and domain in phonics.AUDIO_ONLY_DOMAINS:
        # A lesson built without sound has no questions that work only by ear.
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    try:
        task = phonics.build_task(level, domain, seed, body.phase, body.index)
    except ValueError:
        raise HTTPException(status_code=404, detail=NOT_FOUND) from None

    choice = body.choice
    if body.spoken is not None:
        choice = phonics.match_spoken(task, body.spoken)
        if choice is None:
            # Not understood is not a miss and not an answer: ask again.
            return {"understood": False, "correct": False}
    if choice not in task.choices:
        raise HTTPException(status_code=422, detail="That is not one of the choices.")

    right = task.is_right(choice)
    if body.phase == "together":
        # Guided: a miss shows the answer straight away. Nothing is recorded.
        return {"understood": True, "correct": right, **({} if right else {"reveal": task.reveal()})}

    state = _state(student_name, lesson_id)
    misses = state["misses"].get(body.index, 0)
    if body.index in state["done"]:
        # Already settled: a retry never records a second time.
        return {"understood": True, "correct": right, "recorded": False}
    if not right:
        misses += 1
        state["misses"][body.index] = misses
        if misses >= YOUR_TURN_TRIES:
            # The answer is shown and the question is over. Nothing is recorded.
            state["done"].add(body.index)
            return {"understood": True, "correct": False, "tries_left": 0, "reveal": task.reveal()}
        return {"understood": True, "correct": False, "tries_left": YOUR_TURN_TRIES - misses}

    # Claimed before the first await, so two overlapping retries cannot both record.
    state["done"].add(body.index)
    entry = _round(student_name, auth)
    if entry["lesson_id"] is None:
        entry["lesson_id"] = lesson_id
    if entry["lesson_id"] != lesson_id or entry["count"] >= MAX_RECORDED_ANSWERS:
        # "Another one": practice only. Nothing is written anywhere.
        return {"understood": True, "correct": True, "recorded": False, "practice_only": True}
    entry["count"] += 1
    recorded = await _record(db, student_name, domain, first_try=misses == 0)
    if not recorded:
        log.info("Phonics practice answer not recorded for %s", learner_ref(student_name))
    return {"understood": True, "correct": True, "recorded": recorded}
