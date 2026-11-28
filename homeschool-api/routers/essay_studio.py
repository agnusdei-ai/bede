"""Essay Studio routes (docs/ESSAY_STUDIO.md).

    GET    /essay-studio/{student}/status          may this learner start one, and what
    GET    /essay-studio/{student}/drafts          every draft (parent)
    POST   /essay-studio/{student}/drafts          start an essay
    GET    /essay-studio/{student}/drafts/active   the unfinished draft
    GET    /essay-studio/{student}/drafts/{id}     one draft
    PUT    /essay-studio/{student}/drafts/{id}     save (must carry the current version)
    POST   /essay-studio/{student}/drafts/{id}/coach     one note and one question
    POST   /essay-studio/{student}/drafts/{id}/complete  mark the essay finished
    DELETE /essay-studio/{student}/drafts/{id}     delete (parent)

Every route resolves the learner through `require_learner_access`, so a child
token reaches its own learner and nothing else, and every failure that names
a draft is the same 404. Eligibility (grades 6-12) comes from the SAVED
config, never the request. Writes need collection consent. Coaching goes
through the lesson's own routed client, so it follows the installation's
adapter order and any local-only pin; it never changes the draft.

Drafts are stored encrypted with the student's own key, or, with
ESSAY_STUDIO_SAVE_DRAFTS off, only in this process's memory for the sign-in
that wrote them.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core import consent, student_keys
from core.audit import AuditEvent, audit_from_request, log_event
from core.config import settings
from core.database import EssayDraft, get_db
from core.deps import require_learner_access, require_parent, require_real_user
from core.encryption import decrypt_json, encrypt_json, student_aad
from core.log_redaction import learner_ref
from models.schemas import SessionConfig, Subject
from services import essay_studio as es

log = logging.getLogger("sage.essay_studio")

router = APIRouter(prefix="/essay-studio", tags=["essay-studio"])

NOT_FOUND = "Essay not found."
COACH_TIMEOUT_SECONDS = 45
SESSION_TTL_SECONDS = 6 * 60 * 60
_MAX_SESSION_DRAFTS = 2048

Stage = Literal["task", "model", "position", "plan", "draft", "examine", "revise", "reflect"]


# ── Who, and may they ────────────────────────────────────────────────────────

async def _config(db: AsyncSession, student_name: str) -> SessionConfig:
    from routers.k2_practice import _saved_config

    return await _saved_config(db, student_name)


async def _learner(auth: dict, student_name: str, db: AsyncSession) -> SessionConfig:
    await require_learner_access(auth, student_name, db)
    try:
        return await _config(db, student_name)
    except HTTPException:
        raise HTTPException(status_code=404, detail=NOT_FOUND) from None


def _locale(auth: dict) -> str:
    return "es" if auth.get("locale") == "es" else "en"


def _persistence() -> str:
    return "saved" if settings.essay_studio_save_drafts else "session"


# ── Storage: the database, or this sign-in's memory ──────────────────────────

class _Record:
    """One draft as the routes handle it, whichever store it lives in."""

    def __init__(self, id: str, status: str, version: int, detail: dict,
                 created_at: datetime, updated_at: datetime, row: Optional[EssayDraft] = None):
        self.id, self.status, self.version, self.detail = id, status, version, detail
        self.created_at, self.updated_at, self.row = created_at, updated_at, row


_session_drafts: dict[tuple[str, str], dict[str, dict]] = {}


def _session_bucket(student_name: str, auth: dict) -> dict[str, dict]:
    from routers.k2_practice import sign_in_key

    now = time.monotonic()
    if len(_session_drafts) >= _MAX_SESSION_DRAFTS:
        for key in [k for k, v in _session_drafts.items()
                    if all(now - d["touched"] > SESSION_TTL_SECONDS for d in v.values())]:
            _session_drafts.pop(key, None)
        while len(_session_drafts) >= _MAX_SESSION_DRAFTS:
            _session_drafts.pop(next(iter(_session_drafts)))
    bucket = _session_drafts.setdefault((student_name, sign_in_key(auth)), {})
    for draft_id in [i for i, d in bucket.items() if now - d["touched"] > SESSION_TTL_SECONDS]:
        bucket.pop(draft_id, None)
    return bucket


def _aad(student_name: str, draft_id: str) -> bytes:
    return student_aad("essay_drafts", "detail_enc", student_name, draft_id)


async def _all(db: AsyncSession, student_name: str, auth: dict) -> list[_Record]:
    if _persistence() == "session":
        return [_Record(i, d["status"], d["version"], d["detail"], d["created_at"], d["updated_at"])
                for i, d in _session_bucket(student_name, auth).items()]
    rows = (await db.execute(select(EssayDraft).where(EssayDraft.student_name == student_name))).scalars().all()
    if not rows:
        return []
    key = await student_keys.get_existing(db, student_name)
    out = []
    for row in rows:
        try:
            detail = decrypt_json(row.detail_enc, _aad(student_name, row.id), key)
        except Exception:  # an unreadable row is skipped, never shown half-read
            log.warning("Unreadable essay draft for %s", learner_ref(student_name))
            continue
        out.append(_Record(row.id, row.status, row.version, detail, row.created_at, row.updated_at, row))
    return out


async def _one(db: AsyncSession, student_name: str, auth: dict, draft_id: str) -> _Record:
    for record in await _all(db, student_name, auth):
        if record.id == draft_id:
            return record
    raise HTTPException(status_code=404, detail=NOT_FOUND)


def _active(records: list[_Record]) -> Optional[_Record]:
    active = [r for r in records if r.status == "active"]
    return max(active, key=lambda r: r.updated_at) if active else None


async def _write(db: AsyncSession, student_name: str, auth: dict, record: _Record, *, new: bool = False) -> None:
    record.updated_at = datetime.now(timezone.utc)
    if _persistence() == "session":
        _session_bucket(student_name, auth)[record.id] = {
            "status": record.status, "version": record.version, "detail": record.detail,
            "created_at": record.created_at, "updated_at": record.updated_at, "touched": time.monotonic(),
        }
        return
    key = await student_keys.get_or_create(db, student_name)
    blob = encrypt_json(record.detail, _aad(student_name, record.id), key)
    if new:
        db.add(EssayDraft(id=record.id, student_name=student_name, status=record.status,
                          version=record.version, detail_enc=blob,
                          created_at=record.created_at, updated_at=record.updated_at))
    else:
        row = record.row or await db.get(EssayDraft, record.id)
        if row is None or row.student_name != student_name:
            raise HTTPException(status_code=404, detail=NOT_FOUND)
        row.status, row.version, row.detail_enc, row.updated_at = (
            record.status, record.version, blob, record.updated_at)
    await db.commit()


async def _remove(db: AsyncSession, student_name: str, auth: dict, record: _Record) -> None:
    if _persistence() == "session":
        _session_bucket(student_name, auth).pop(record.id, None)
        return
    row = record.row or await db.get(EssayDraft, record.id)
    if row is not None and row.student_name == student_name:
        await db.delete(row)
        await db.commit()


# ── What a client sees ───────────────────────────────────────────────────────

def _summary(record: _Record, locale: str) -> dict:
    d = record.detail
    return {"id": record.id, "title": es.title_for(d.get("prompt", ""), d["exercise"], locale),
            "exercise": d["exercise"], "stage": d["stage"], "status": record.status,
            "word_count": es.word_count(d.get("text", "")), "updated_at": record.updated_at.isoformat()}


def _full(record: _Record, locale: str) -> dict:
    d = record.detail
    text = d.get("text", "")
    return {
        **_summary(record, locale),
        "subject": d["subject"], "prompt": d.get("prompt", ""),
        "model_source": d.get("model_source", ""), "model_observation": d.get("model_observation", ""),
        "position": d.get("position", ""), "opposing_view": d.get("opposing_view", ""),
        "plan": d.get("plan", []), "text": text, "reflection": d.get("reflection", ""),
        "next_step": d.get("next_step", ""), "version": record.version,
        "word_count": es.word_count(text), "paragraph_count": es.paragraph_count(text),
        "typed_chars": d.get("typed_chars", 0), "pasted_chars": d.get("pasted_chars", 0),
        "coaching": d.get("coaching"),
        "reflect_questions": es.reflect_questions(d["exercise"], locale),
        "uses_opposing_view": es.uses_opposing_view(d["exercise"]),
        "criteria": es.criteria_for(d["exercise"], None, locale),
        "persistence": _persistence(),
        "created_at": record.created_at.isoformat(),
    }


# ── Routes ───────────────────────────────────────────────────────────────────

@router.get("/{student_name}/status")
async def status(
    student_name: str,
    subject: Optional[Subject] = Query(default=None),
    auth: dict = Depends(require_real_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    config = await _learner(auth, student_name, db)
    locale = _locale(auth)
    band = es.stage_band(config)
    reason = None
    if band is None:
        reason = "grade"
    elif subject is not None and subject not in es.ESSAY_SUBJECTS:
        reason = "subject"
    available = reason is None
    active = _active(await _all(db, student_name, auth)) if band else None
    return {
        "available": available, "reason": reason, "persistence": _persistence(),
        "stage_band": band,
        "exercises": [{"id": e, "label": es.exercise_label(e, locale)} for e in es.exercises_for(config)]
        if available else [],
        "active": _summary(active, locale) if active else None,
    }


@router.get("/{student_name}/drafts")
async def list_drafts(
    student_name: str,
    auth: dict = Depends(require_parent),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _learner(auth, student_name, db)
    records = sorted(await _all(db, student_name, auth),
                     key=lambda r: (r.status != "active", -r.updated_at.timestamp()))
    return {"drafts": [_summary(r, _locale(auth)) | {"pasted_chars": r.detail.get("pasted_chars", 0)}
                       for r in records], "persistence": _persistence()}


class StartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: Subject
    exercise: Literal["narrative", "refutation", "thesis"]
    prompt: str = Field(default="", max_length=es.MAX_PROMPT_CHARS)
    replace: bool = False
    time_remaining_seconds: Optional[int] = Field(default=None, ge=0)


@router.post("/{student_name}/drafts", status_code=201)
async def start(
    student_name: str,
    body: StartRequest,
    auth: dict = Depends(require_real_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from services.action_governance import MIN_SECONDS_FOR_LONG_FORM_TASK
    from services.ai_service import _redact_credentials

    config = await _learner(auth, student_name, db)
    if es.stage_band(config) is None or body.subject not in es.ESSAY_SUBJECTS:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    if body.exercise not in es.exercises_for(config):
        raise HTTPException(status_code=422, detail="That exercise is not offered at this student's stage.")
    if body.time_remaining_seconds is not None and body.time_remaining_seconds < MIN_SECONDS_FOR_LONG_FORM_TASK:
        raise HTTPException(status_code=409, detail={"code": "not_enough_time"})
    await consent.require_collection(db, student_name)
    locale = _locale(auth)
    active = _active(await _all(db, student_name, auth))
    if active is not None:
        if not body.replace:
            raise HTTPException(status_code=409, detail={"code": "active_draft_exists",
                                                         "active": _summary(active, locale)})
        await _remove(db, student_name, auth, active)
    now = datetime.now(timezone.utc)
    record = _Record(str(uuid.uuid4()), "active", 1, {
        "subject": body.subject.value, "exercise": body.exercise,
        "prompt": _redact_credentials(body.prompt.strip()) or "", "stage": "task",
        "plan": [], "text": "", "typed_chars": 0, "pasted_chars": 0, "coaching_log": [],
    }, now, now)
    await _write(db, student_name, auth, record, new=True)
    return _full(record, locale)


@router.get("/{student_name}/drafts/active")
async def active_draft(
    student_name: str,
    auth: dict = Depends(require_real_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _learner(auth, student_name, db)
    record = _active(await _all(db, student_name, auth))
    if record is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    return _full(record, _locale(auth))


@router.get("/{student_name}/drafts/{draft_id}")
async def get_draft(
    student_name: str,
    draft_id: str,
    auth: dict = Depends(require_real_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _learner(auth, student_name, db)
    record = await _one(db, student_name, auth, draft_id)
    if record.status != "active" and auth.get("role") != "parent":
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    return _full(record, _locale(auth))


class SaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    stage: Optional[Stage] = None
    model_source: Optional[str] = Field(default=None, max_length=es.MAX_FIELD_CHARS)
    model_observation: Optional[str] = Field(default=None, max_length=es.MAX_FIELD_CHARS)
    position: Optional[str] = Field(default=None, max_length=es.MAX_FIELD_CHARS)
    opposing_view: Optional[str] = Field(default=None, max_length=es.MAX_FIELD_CHARS)
    plan: Optional[list[str]] = Field(default=None, max_length=es.MAX_PLAN_POINTS)
    text: Optional[str] = Field(default=None, max_length=es.MAX_TEXT_CHARS)
    reflection: Optional[str] = Field(default=None, max_length=es.MAX_FIELD_CHARS)
    typed_chars: int = Field(default=0, ge=0, le=es.MAX_TEXT_CHARS * 4)
    pasted_chars: int = Field(default=0, ge=0, le=es.MAX_TEXT_CHARS * 4)


def _conflict(record: _Record):
    return HTTPException(status_code=409, detail={"code": "version_conflict", "current_version": record.version})


@router.put("/{student_name}/drafts/{draft_id}")
async def save(
    student_name: str,
    draft_id: str,
    body: SaveRequest,
    auth: dict = Depends(require_real_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _learner(auth, student_name, db)
    await consent.require_collection(db, student_name)
    record = await _one(db, student_name, auth, draft_id)
    if record.status != "active":
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    if body.version != record.version:
        raise _conflict(record)
    d = record.detail
    for field in ("stage", "model_source", "model_observation", "position", "reflection", "text"):
        value = getattr(body, field)
        if value is not None:
            d[field] = value
    if body.opposing_view is not None and es.uses_opposing_view(d["exercise"]):
        d["opposing_view"] = body.opposing_view
    if body.plan is not None:
        d["plan"] = [str(p)[: es.MAX_FIELD_CHARS] for p in body.plan if str(p).strip()][: es.MAX_PLAN_POINTS]
    d["typed_chars"] = d.get("typed_chars", 0) + body.typed_chars
    d["pasted_chars"] = d.get("pasted_chars", 0) + body.pasted_chars
    record.version += 1
    if _persistence() == "saved":
        # The version check and the write are one guarded UPDATE, so two tabs
        # saving the same version at once cannot both succeed.
        from sqlalchemy import update

        key = await student_keys.get_or_create(db, student_name)
        now = datetime.now(timezone.utc)
        result = await db.execute(
            update(EssayDraft)
            .where(EssayDraft.id == draft_id, EssayDraft.student_name == student_name,
                   EssayDraft.version == body.version)
            .values(version=record.version, updated_at=now,
                    detail_enc=encrypt_json(d, _aad(student_name, draft_id), key))
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            await db.rollback()
            current = await _one(db, student_name, auth, draft_id)
            raise _conflict(current)
        await db.commit()
        record.updated_at = now
    else:
        await _write(db, student_name, auth, record)
    return {"version": record.version, "updated_at": record.updated_at.isoformat(), "persistence": _persistence()}


class CoachRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)


@router.post("/{student_name}/drafts/{draft_id}/coach")
async def coach(
    student_name: str,
    draft_id: str,
    body: CoachRequest,
    request: Request,
    auth: dict = Depends(require_real_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from services import ai_service, safeguarding_alerts
    from services.practice.extract import _text_of

    config = await _learner(auth, student_name, db)
    await consent.require_collection(db, student_name)
    record = await _one(db, student_name, auth, draft_id)
    band = es.stage_band(config)
    if record.status != "active" or band is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    if body.version != record.version:
        raise _conflict(record)
    d = record.detail
    if es.coaching_used_today(d.get("coaching_log", [])) >= es.MAX_COACHING_PER_DAY:
        raise HTTPException(status_code=429, detail="That is all the coaching for this essay today.")
    locale = _locale(auth)
    words = es.own_words(d)
    if ai_service.check_safeguarding(words):
        await log_event(AuditEvent.SAFEGUARDING, role=auth.get("role"), student_name=student_name,
                        success=True, detail="trigger:essay_studio", **audit_from_request(request))
        asyncio.create_task(safeguarding_alerts.deliver(
            role=auth.get("role"), student_name=student_name, display_name=config.display_name,
            trigger_excerpt="(in an essay draft)", dedupe_source=words, audit=audit_from_request(request),
        ))
        return {"safeguarding": True, "message": ai_service.safeguarding_response(locale)}
    redacted = {**d, **{k: ai_service._redact_credentials(d.get(k)) or "" for k in (
        "prompt", "model_observation", "position", "opposing_view", "text")},
        "plan": [ai_service._redact_credentials(p) or "" for p in d.get("plan", [])]}
    stage = d.get("stage", "draft")
    system = es.coaching_system_prompt(d["exercise"], stage, band, locale, config.learning_support)
    try:
        # The lesson's own routed client: the installation's adapter order and
        # any BEDE_FORCE_ADAPTER pin, so a local-only install stays local.
        response = await asyncio.wait_for(ai_service._client.messages.create(
            model=settings.tutor_model, max_tokens=400, temperature=0.3, system=system,
            messages=[{"role": "user", "content": [{"type": "text", "text": es.coaching_user_message(redacted)}]}],
        ), timeout=COACH_TIMEOUT_SECONDS)
        coaching = es.clean_coaching(es.parse_model_json(_text_of(response)), draft=d, stage=stage,
                                     draft_version=record.version, locale=locale)
    except Exception as exc:  # never log the draft
        log.warning("Essay coaching unavailable for %s: %s", learner_ref(student_name), type(exc).__name__)
        raise HTTPException(status_code=503, detail="Bede could not look at your essay just now. "
                                                    "Your writing is saved; try again in a moment.") from None
    # Coaching is stored without touching the draft's text or version, so a
    # save in flight never conflicts with it.
    fresh = await _one(db, student_name, auth, draft_id)
    fresh.detail["coaching"] = coaching
    fresh.detail["next_step"] = coaching["question"]
    fresh.detail["coaching_log"] = (fresh.detail.get("coaching_log", []) + [coaching["created_at"]])[-50:]
    await _write(db, student_name, auth, fresh)
    return {"coaching": coaching}


@router.post("/{student_name}/drafts/{draft_id}/complete")
async def complete(
    student_name: str,
    draft_id: str,
    auth: dict = Depends(require_real_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _learner(auth, student_name, db)
    await consent.require_collection(db, student_name)
    record = await _one(db, student_name, auth, draft_id)
    if record.status != "active":
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    record.status = "finished"
    await _write(db, student_name, auth, record)
    return _full(record, _locale(auth))


@router.delete("/{student_name}/drafts/{draft_id}", status_code=204)
async def delete_draft(
    student_name: str,
    draft_id: str,
    auth: dict = Depends(require_parent),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await _learner(auth, student_name, db)
    record = await _one(db, student_name, auth, draft_id)
    await _remove(db, student_name, auth, record)
    return Response(status_code=204)
