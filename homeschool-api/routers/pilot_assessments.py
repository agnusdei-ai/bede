"""Canonical DIBELS / assessment routes and the Data Day packet.

Every learner route is ``/pilot/campuses/{campus_id}/learners/{learner_id}/...``
and resolves through G1's ``_assigned`` join (live educator session, active
campus, active membership, active per-learner grant). The path's campus UUID
must also equal the learner's own campus. Malformed, missing, random,
unauthorized, cross-campus, stale and substituted UUIDs all produce the same
``404 Record not found`` body, so nothing confirms that a record exists.

Writes re-check the grant immediately before commit (``_recheck``), so a
grant revoked while a request is in flight cannot persist anything. The
re-check is bound to the ``services.pilot_authz`` context resolved when the
request STARTED (grant id, grant version, educator credential version): a
grant revoked and re-approved mid-request is a NEW grant version and is
refused, even though a fresh lookup would find it enabled again.

State changes happen only through recorded teacher actions on the pure
lifecycle in ``services/assessment_lifecycle.py``; nothing here advances on
a timer, schedules instruction, alters placement or delivers anything to a
learner. See docs/CANONICAL_ASSESSMENT_MODEL.md.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, select, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import PilotLearner, PilotRosterGrant, get_db
from core.deps import require_educator, require_elevated_parent
from core.encryption import aad_for, decrypt_json, encrypt_json
from core.pilot_assessment_models import (
    PilotAssessmentAdministration, PilotAssessmentDecision, PilotAssessmentEvidence,
    PilotAssessmentPlan, PilotAssessmentProposal, PilotAssessmentResponse,
    PilotAssessmentScore, PilotAssessmentTransition, PilotBenchmarkAuthorization,
    PilotCampusCycle, PilotProgressMonitoringSchedule,
)
import routers.pilot_campuses as g1
from services import canonical_assessment as ca
from services import pilot_authz
from services.assessment_lifecycle import (
    POST_FINALIZATION, SCORE_ENTRY, Action, IllegalTransition, State, next_state,
)
from services.educator_access import live_educator

GENESIS = "0" * 64
NOT_FOUND_DETAIL = "Record not found"

learner_router = APIRouter(
    prefix="/pilot/campuses/{campus_id}/learners/{learner_id}", tags=["valor-pilot-assessment"],
)
campus_router = APIRouter(prefix="/pilot/campuses/{campus_id}", tags=["valor-pilot-assessment"])


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail=NOT_FOUND_DETAIL)


def _conflict(detail: str = "The record changed; reload and try again") -> HTTPException:
    return HTTPException(status_code=409, detail=detail)


def _aad(table: str, column: str, learner: PilotLearner, row_id: str) -> bytes:
    return aad_for(table, column, f"{learner.campus_id}:{learner.id}:{row_id}")


def _enc(obj: dict, table: str, column: str, learner: PilotLearner, row_id: str) -> bytes:
    return encrypt_json(obj, _aad(table, column, learner, row_id))


def _dec(blob: bytes, table: str, column: str, learner: PilotLearner, row_id: str) -> dict:
    return decrypt_json(blob, _aad(table, column, learner, row_id))


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest() if text else ""


def _iso(value) -> Optional[str]:
    if value is None:
        return None
    return value.isoformat()


# ── Scope resolution ────────────────────────────────────────────────────────

#: Key under which ``_scope`` pins the request-start authorization context on
#: the request's own session (``AsyncSession.info``), for ``_recheck``.
_CTX_KEY = "pilot_assessment_authz_ctx"


async def _scope(db: AsyncSession, auth: dict, campus_id: str, learner_id: str):
    """(teacher, learner) or the uniform 404. Never trusts the path's campus.

    Also resolves and pins the request's ``PilotAuthzContext``: the grant id
    and version, and the educator's credential version, as they stood when
    this request started. ``_recheck`` refuses the write if any of them has
    moved, which is what makes a revoke-then-re-grant mid-request a refusal
    rather than a pass."""
    cid = g1._id(campus_id)
    learner = await g1._assigned(db, auth, learner_id)
    if learner.campus_id != cid:
        raise _not_found()
    db.info[_CTX_KEY] = await pilot_authz.resolve_campus_learner(
        db, auth, learner.id, pilot_authz.ACTION_ASSESSMENT, claimed_campus_id=cid,
    )
    teacher = await live_educator(db, auth)
    return teacher, learner


async def _recheck(db: AsyncSession, auth: dict, learner: PilotLearner) -> None:
    """Grant re-check at write time, inside the open transaction."""
    try:
        again = await g1._assigned(db, auth, learner.id)
    except HTTPException:
        await db.rollback()
        raise _not_found()
    if again.id != learner.id or again.campus_id != learner.campus_id:
        await db.rollback()
        raise _not_found()
    ctx = db.info.get(_CTX_KEY)
    if ctx is None or ctx.learner_id != learner.id or ctx.campus_id != learner.campus_id:
        # No pinned context means _scope did not run for this learner on this
        # session: fail closed rather than write on an unbound check.
        await db.rollback()
        raise _not_found()
    # Hold the learner row FOR SHARE until this write commits. Learner
    # deletion (services/pilot_learner_deletion.py) takes FOR UPDATE on the
    # same row, so a write in flight either lands before the deletion counts
    # and is deleted with everything else, or waits and then finds no
    # learner. Without this, a write could commit an orphan row for a
    # learner the deletion just removed. A no-op on SQLite.
    locked = (await db.execute(
        select(PilotLearner.id)
        .where(PilotLearner.id == learner.id, PilotLearner.campus_id == learner.campus_id)
        .with_for_update(read=True)
    )).scalar_one_or_none()
    if locked is None:
        await db.rollback()
        raise _not_found()
    # Hold the grant row FOR SHARE as well, re-read past the identity map
    # (populate_existing: the request already loaded this row, and a plain
    # select would hand back the stale object). A concurrent revoke's UPDATE
    # then waits for this write to commit, so the two serialize. It must
    # still be THE grant at THE version this request started under.
    grant = (await db.execute(
        select(PilotRosterGrant)
        .where(PilotRosterGrant.educator_id == ctx.principal_id,
               PilotRosterGrant.campus_id == learner.campus_id,
               PilotRosterGrant.learner_id == learner.id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )).scalar_one_or_none()
    if (grant is None or not grant.enabled
            or grant.grant_id != ctx.grant_id or grant.version != ctx.grant_version):
        pilot_authz.audit_revoked(ctx, "assessment.write")
        await db.rollback()
        raise _not_found()
    # And the whole context once more in a FRESH session (educator account,
    # credential version, membership, campus, learner, grant), which also
    # covers SQLite, where the request's own transaction may read a snapshot
    # and FOR SHARE is a no-op. Fails closed on any error.
    if not await pilot_authz.revalidate(ctx):
        pilot_authz.audit_revoked(ctx, "assessment.write")
        await db.rollback()
        raise _not_found()


async def _administration(db: AsyncSession, learner: PilotLearner,
                          assessment_id: str) -> PilotAssessmentAdministration:
    row = await db.get(PilotAssessmentAdministration, g1._id(assessment_id))
    if row is None or row.learner_id != learner.id or row.campus_id != learner.campus_id:
        raise _not_found()
    return row


async def _commit(db: AsyncSession, auth: dict, learner: PilotLearner) -> None:
    await _recheck(db, auth, learner)
    try:
        await db.commit()
    except (IntegrityError, DBAPIError):
        # Unique (administration_id, seq) collision = a concurrent
        # transition from the same head; DB trigger = immutability.
        await db.rollback()
        raise _conflict()


# ── Lifecycle ledger ────────────────────────────────────────────────────────

def _transition_fields(row: PilotAssessmentTransition) -> dict:
    return {
        "seq": row.seq, "administration_id": row.administration_id,
        "campus_id": row.campus_id, "learner_id": row.learner_id,
        "actor_id": row.actor_id, "action": row.action,
        "from_state": row.from_state, "to_state": row.to_state,
        "result": row.result, "link_id": row.link_id or "",
        "content_sha256": row.content_sha256,
    }


def entry_hash(prev_hash: str, fields: dict) -> str:
    return ca.canonical_hash({"prev_hash": prev_hash, **fields})


def verify_chain(rows: list, fields) -> bool:
    prev = GENESIS
    for expected_seq, row in enumerate(sorted(rows, key=lambda r: r.seq), start=1):
        if row.seq != expected_seq or row.prev_hash != prev:
            return False
        if row.entry_hash != entry_hash(prev, fields(row)):
            return False
        prev = row.entry_hash
    return True


async def _transitions(db: AsyncSession, adm_id: str) -> list[PilotAssessmentTransition]:
    return list((await db.execute(
        select(PilotAssessmentTransition)
        .where(PilotAssessmentTransition.administration_id == adm_id)
        .order_by(PilotAssessmentTransition.seq)
    )).scalars().all())


async def _state(db: AsyncSession, adm_id: str) -> tuple[State, Optional[PilotAssessmentTransition]]:
    head = (await db.execute(
        select(PilotAssessmentTransition)
        .where(PilotAssessmentTransition.administration_id == adm_id)
        .order_by(PilotAssessmentTransition.seq.desc()).limit(1)
    )).scalar_one_or_none()
    return (State(head.to_state) if head else State.DRAFT), head


def _append(db: AsyncSession, learner: PilotLearner, adm_id: str, actor: str,
            head: Optional[PilotAssessmentTransition], action: str,
            from_state: str, to_state: str, *, link_id: Optional[str] = None,
            content_sha256: str = "", note: Optional[str] = None) -> PilotAssessmentTransition:
    prev = head.entry_hash if head else GENESIS
    row_id = str(uuid.uuid4())
    row = PilotAssessmentTransition(
        id=row_id, administration_id=adm_id, campus_id=learner.campus_id,
        learner_id=learner.id, seq=(head.seq + 1) if head else 1, actor_id=actor,
        action=action, from_state=from_state, to_state=to_state, result="applied",
        link_id=link_id, content_sha256=content_sha256, prev_hash=prev, entry_hash="",
        created_at=datetime.now(timezone.utc),
    )
    row.entry_hash = entry_hash(prev, _transition_fields(row))
    if note and note.strip():
        row.note_enc = _enc({"note": note.strip()}, "pilot_assessment_transitions",
                            "note_enc", learner, row_id)
    db.add(row)
    return row


async def _advance(db: AsyncSession, learner: PilotLearner, adm: PilotAssessmentAdministration,
                   actor: str, action: Action, *, expected: Optional[State] = None,
                   resolution: Optional[str] = None, link_id: Optional[str] = None,
                   content_sha256: str = ""):
    current, head = await _state(db, adm.id)
    if expected is not None and current is not expected:
        raise _conflict(f"Expected {expected.value}; the record is {current.value}")
    try:
        t = next_state(current, action, resolution=resolution, link_id=link_id)
    except IllegalTransition as exc:
        raise _conflict(str(exc))
    _append(db, learner, adm.id, actor, head, t.action.value, t.from_state.value,
            t.to_state.value, link_id=link_id, content_sha256=content_sha256, note=resolution)
    try:
        # Flush now: a concurrent transition from the same head collides on
        # (administration_id, seq) here, and must surface as a 409 rather
        # than as an autoflush error from some later query.
        await db.flush()
    except (IntegrityError, DBAPIError):
        await db.rollback()
        raise _conflict()
    return t


# ── Calendar and authorization lookups ──────────────────────────────────────

async def _calendar(db: AsyncSession, campus_id: str) -> tuple[list[ca.Cycle], bool]:
    rows = (await db.execute(
        select(PilotCampusCycle).where(PilotCampusCycle.campus_id == campus_id)
        .order_by(PilotCampusCycle.position)
    )).scalars().all()
    if rows:
        return [ca.Cycle(r.cycle_key, r.label, r.position, r.data_day_on) for r in rows], True
    return ca.valor_default_calendar(), False


async def _benchmark_authorization(db: AsyncSession, campus_id: str,
                                   payload: ca.AdministrationInput) -> Optional[str]:
    rows = (await db.execute(
        select(PilotBenchmarkAuthorization).where(
            PilotBenchmarkAuthorization.campus_id == campus_id,
            PilotBenchmarkAuthorization.enabled.is_(True),
            PilotBenchmarkAuthorization.instrument == payload.instrument,
        ).order_by(PilotBenchmarkAuthorization.recorded_at.desc())
    )).scalars().all()
    for row in rows:
        if payload.form_id in json.loads(row.approved_forms):
            return row.id
    return None


# ── Rendering ───────────────────────────────────────────────────────────────

def _meta(adm: PilotAssessmentAdministration) -> dict:
    return {
        "assessment_id": adm.id, "campus_id": adm.campus_id, "learner_id": adm.learner_id,
        "administrator_id": adm.administrator_id, "instrument": adm.instrument,
        "edition": adm.edition, "measure": adm.measure, "grade": adm.grade,
        "form_id": adm.form_id, "administration_purpose": adm.administration_purpose,
        "instructional_cycle": adm.instructional_cycle,
        "administered_at": _iso(adm.administered_at),
        "report_source": adm.report_source,
        "official_benchmark_window": adm.official_benchmark_window,
        "vendor_next_assessment_date": _iso(adm.vendor_next_assessment_date),
        "benchmark_authorization_id": adm.benchmark_authorization_id,
        "fidelity_state": adm.fidelity_state, "supersedes_id": adm.supersedes_id,
    }


def _snapshot_meta(adm: PilotAssessmentAdministration) -> dict:
    meta = _meta(adm)
    # Normalize datetimes so SQLite (naive) and Postgres (aware) hash alike.
    at = adm.administered_at
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    meta["administered_at"] = at.astimezone(timezone.utc).isoformat()
    return meta


async def _score_rows(db, adm_id) -> list[PilotAssessmentScore]:
    return list((await db.execute(
        select(PilotAssessmentScore).where(PilotAssessmentScore.administration_id == adm_id)
        .order_by(PilotAssessmentScore.measure)
    )).scalars().all())


async def _response_rows(db, adm_id) -> list[PilotAssessmentResponse]:
    return list((await db.execute(
        select(PilotAssessmentResponse).where(PilotAssessmentResponse.administration_id == adm_id)
        .order_by(PilotAssessmentResponse.measure, PilotAssessmentResponse.item_index)
    )).scalars().all())


def _render_score(row: PilotAssessmentScore, learner: PilotLearner) -> dict:
    d = _dec(row.detail_enc, "pilot_assessment_scores", "detail_enc", learner, row.id)
    return {
        "score_id": row.id, "measure": row.measure, "is_composite": row.is_composite,
        "administration_status": row.administration_status,
        "calculation_version": row.calculation_version,
        "raw_score": d["raw_score"], "score_unit": d["score_unit"], "reason": d["reason"],
        "benchmark_label": d["benchmark_label"], "support_label": d["support_label"],
        "printed_cut_points": {"provenance": ca.CUT_POINT_PROVENANCE,
                               "values": d["printed_cut_points"]},
        "official_marks": d.get("official_marks"),
        "composite_eligible": d.get("composite_eligible"),
    }


def _render_response(row: PilotAssessmentResponse, learner: PilotLearner) -> dict:
    d = _dec(row.marks_enc, "pilot_assessment_responses", "marks_enc", learner, row.id)
    return {"measure": row.measure, "item_index": row.item_index, **d}


def _score_snapshot(s: dict) -> dict:
    return {k: s[k] for k in ("measure", "is_composite", "administration_status",
                              "calculation_version", "raw_score", "score_unit", "reason",
                              "benchmark_label", "support_label")} | {
        "printed_cut_points": s["printed_cut_points"]["values"],
        "official_marks": s.get("official_marks"),
        "composite_eligible": s.get("composite_eligible")}


async def _snapshot_hash(db, adm, learner) -> str:
    content = _dec(adm.content_enc, "pilot_assessment_administrations", "content_enc",
                   learner, adm.id)
    scores = [_score_snapshot(_render_score(r, learner)) for r in await _score_rows(db, adm.id)]
    responses = [_render_response(r, learner) for r in await _response_rows(db, adm.id)]
    return ca.canonical_hash(ca.snapshot(_snapshot_meta(adm), content, scores, responses))


async def _render_administration(db, adm, learner, *, detail: bool = False) -> dict:
    state, _ = await _state(db, adm.id)
    content = _dec(adm.content_enc, "pilot_assessment_administrations", "content_enc",
                   learner, adm.id)
    out = {**_meta(adm), "state": state.value,
           "accommodations": content["accommodations"], "notes": content["notes"],
           "vendor_guidance": (
               {"attribution": ca.VENDOR_ATTRIBUTION, **content["vendor_guidance"]}
               if content["vendor_guidance"] else None),
           "snapshot_sha256": adm.snapshot_sha256,
           "finalized_at": _iso(adm.finalized_at), "finalized_by": adm.finalized_by}
    if detail:
        out["scores"] = [_render_score(r, learner) for r in await _score_rows(db, adm.id)]
        out["responses"] = [_render_response(r, learner) for r in await _response_rows(db, adm.id)]
        if adm.snapshot_sha256:
            out["snapshot_verified"] = (await _snapshot_hash(db, adm, learner)) == adm.snapshot_sha256
    return out


# ── Campus administration (verified administrator passkey) ──────────────────

@campus_router.put("/calendar")
async def set_calendar(campus_id: str, payload: ca.CalendarInput,
                       auth: dict = Depends(require_elevated_parent),
                       db: AsyncSession = Depends(get_db)) -> dict:
    g1._admin(auth)
    campus = await g1._campus(db, campus_id)
    await db.execute(delete(PilotCampusCycle).where(PilotCampusCycle.campus_id == campus.id))
    cycles = payload.resolve()
    for c in cycles:
        db.add(PilotCampusCycle(campus_id=campus.id, cycle_key=c.cycle_key, label=c.label,
                                position=c.position, data_day_on=c.data_day_on))
    await db.commit()
    return {"campus_id": campus.id, "configured": True,
            "cycles": [{"cycle_key": c.cycle_key, "label": c.label, "position": c.position,
                        "data_day_on": _iso(c.data_day_on)} for c in cycles]}


@campus_router.get("/calendar")
async def get_calendar(campus_id: str, auth: dict = Depends(require_elevated_parent),
                       db: AsyncSession = Depends(get_db)) -> dict:
    g1._admin(auth)
    campus = await g1._campus(db, campus_id)
    cycles, configured = await _calendar(db, campus.id)
    return {"campus_id": campus.id, "configured": configured,
            "cycles": [{"cycle_key": c.cycle_key, "label": c.label, "position": c.position,
                        "data_day_on": _iso(c.data_day_on)} for c in cycles]}


@campus_router.post("/benchmark-authorizations", status_code=201)
async def record_benchmark_authorization(
    campus_id: str, payload: ca.BenchmarkAuthorizationInput,
    auth: dict = Depends(require_elevated_parent), db: AsyncSession = Depends(get_db),
) -> dict:
    g1._admin(auth)
    campus = await g1._campus(db, campus_id)
    row = PilotBenchmarkAuthorization(
        id=str(uuid.uuid4()), campus_id=campus.id, instrument=payload.instrument,
        licensed_program_ref=payload.licensed_program_ref.strip(),
        approved_forms=json.dumps(payload.approved_forms),
        local_policy_ref=payload.local_policy_ref.strip(),
        recorded_by="verified-administrator-passkey",
        recorded_at=datetime.now(timezone.utc),
    )
    db.add(row)
    await db.commit()
    return {"authorization_id": row.id, "campus_id": campus.id,
            "instrument": row.instrument, "approved_forms": payload.approved_forms,
            "licensed_program_ref": row.licensed_program_ref,
            "local_policy_ref": row.local_policy_ref}


# ── Administrations ─────────────────────────────────────────────────────────

@learner_router.post("/assessments", status_code=201)
async def create_administration(
    campus_id: str, learner_id: str, payload: ca.AdministrationInput,
    auth: dict = Depends(require_educator), db: AsyncSession = Depends(get_db),
) -> dict:
    teacher, learner = await _scope(db, auth, campus_id, learner_id)
    cycles, _ = await _calendar(db, learner.campus_id)
    if payload.instructional_cycle not in {c.cycle_key for c in cycles}:
        raise HTTPException(status_code=422, detail="Unknown instructional cycle for this campus")
    authorization_id = None
    if payload.administration_purpose == "benchmark":
        authorization_id = await _benchmark_authorization(db, learner.campus_id, payload)
        if authorization_id is None:
            raise HTTPException(
                status_code=403,
                detail="Benchmark administration is not authorized for this campus and form",
            )
    row_id = str(uuid.uuid4())
    adm = PilotAssessmentAdministration(
        id=row_id, campus_id=learner.campus_id, learner_id=learner.id,
        administrator_id=teacher.id, instrument=payload.instrument,
        edition=payload.edition.strip(), measure=payload.measure, grade=payload.grade,
        form_id=payload.form_id.strip(), administration_purpose=payload.administration_purpose,
        instructional_cycle=payload.instructional_cycle,
        administered_at=payload.administered_at, report_source=payload.report_source,
        official_benchmark_window=payload.official_benchmark_window,
        vendor_next_assessment_date=payload.vendor_next_assessment_date,
        benchmark_authorization_id=authorization_id, fidelity_state="standard",
        content_enc=_enc(payload.content(), "pilot_assessment_administrations",
                         "content_enc", learner, row_id),
        created_at=datetime.now(timezone.utc),
    )
    db.add(adm)
    _append(db, learner, row_id, teacher.id, None, "create", "", State.DRAFT.value)
    await _commit(db, auth, learner)
    return await _render_administration(db, adm, learner)


@learner_router.get("/assessments")
async def list_administrations(campus_id: str, learner_id: str,
                               auth: dict = Depends(require_educator),
                               db: AsyncSession = Depends(get_db)) -> list[dict]:
    _, learner = await _scope(db, auth, campus_id, learner_id)
    rows = (await db.execute(
        select(PilotAssessmentAdministration).where(
            PilotAssessmentAdministration.campus_id == learner.campus_id,
            PilotAssessmentAdministration.learner_id == learner.id,
        ).order_by(PilotAssessmentAdministration.administered_at, PilotAssessmentAdministration.id)
    )).scalars().all()
    return [await _render_administration(db, r, learner) for r in rows]


@learner_router.get("/assessments/{assessment_id}")
async def get_administration(campus_id: str, learner_id: str, assessment_id: str,
                             auth: dict = Depends(require_educator),
                             db: AsyncSession = Depends(get_db)) -> dict:
    _, learner = await _scope(db, auth, campus_id, learner_id)
    adm = await _administration(db, learner, assessment_id)
    return await _render_administration(db, adm, learner, detail=True)


@learner_router.put("/assessments/{assessment_id}/scores")
async def enter_scores(campus_id: str, learner_id: str, assessment_id: str,
                       payload: ca.ScoresSubmission,
                       auth: dict = Depends(require_educator),
                       db: AsyncSession = Depends(get_db)) -> dict:
    teacher, learner = await _scope(db, auth, campus_id, learner_id)
    adm = await _administration(db, learner, assessment_id)
    state, _ = await _state(db, adm.id)
    if state not in SCORE_ENTRY or adm.finalized_at is not None:
        raise _conflict(f"Scores cannot be entered while the record is {state.value}")
    measures = {s.measure for s in payload.scores}
    if adm.measure != "multiple" and measures != {adm.measure}:
        raise HTTPException(status_code=422, detail="Scores must be for the administered measure")
    await db.execute(delete(PilotAssessmentResponse)
                     .where(PilotAssessmentResponse.administration_id == adm.id))
    await db.execute(delete(PilotAssessmentScore)
                     .where(PilotAssessmentScore.administration_id == adm.id))
    for s in payload.scores:
        sid = str(uuid.uuid4())
        db.add(PilotAssessmentScore(
            id=sid, administration_id=adm.id, campus_id=learner.campus_id,
            learner_id=learner.id, measure=s.measure, is_composite=s.is_composite,
            administration_status=s.administration_status,
            calculation_version=s.calculation_version,
            detail_enc=_enc(s.detail(), "pilot_assessment_scores", "detail_enc", learner, sid),
        ))
    for r in payload.responses:
        rid = str(uuid.uuid4())
        db.add(PilotAssessmentResponse(
            id=rid, administration_id=adm.id, campus_id=learner.campus_id,
            learner_id=learner.id, measure=r.measure, item_index=r.item_index,
            marks_enc=_enc({"mark": r.mark, "correct": r.correct, "error_type": r.error_type,
                            "annotation": (r.annotation or "").strip() or None},
                           "pilot_assessment_responses", "marks_enc", learner, rid),
        ))
    await _commit(db, auth, learner)
    return await _render_administration(db, adm, learner, detail=True)


_FIDELITY_AFTER = {
    Action.INTERRUPT: "interrupted", Action.INVALIDATE: "invalid",
    Action.RESUME: "interrupted_resolved", Action.RESOLVE_INVALID: "invalid_resolved",
}


@learner_router.post("/assessments/{assessment_id}/transitions")
async def transition(campus_id: str, learner_id: str, assessment_id: str,
                     payload: ca.TransitionInput,
                     auth: dict = Depends(require_educator),
                     db: AsyncSession = Depends(get_db)) -> dict:
    teacher, learner = await _scope(db, auth, campus_id, learner_id)
    adm = await _administration(db, learner, assessment_id)
    try:
        expected = State(payload.expected_state)
    except ValueError:
        raise HTTPException(status_code=422, detail="Unknown expected_state")
    action = Action(payload.action)
    content_sha = ""
    if action in (Action.SUBMIT, Action.FINALIZE):
        if not await _score_rows(db, adm.id):
            raise _conflict("Enter at least one measure before submitting")
    if action is Action.FINALIZE:
        content_sha = await _snapshot_hash(db, adm, learner)
    await _advance(db, learner, adm, teacher.id, action, expected=expected,
                   resolution=payload.resolution, content_sha256=content_sha)
    values = {}
    if action in _FIDELITY_AFTER:
        values["fidelity_state"] = _FIDELITY_AFTER[action]
    if action is Action.FINALIZE:
        values.update(snapshot_sha256=content_sha, finalized_by=teacher.id,
                      finalized_at=datetime.now(timezone.utc))
    if values:
        await db.execute(update(PilotAssessmentAdministration)
                         .where(PilotAssessmentAdministration.id == adm.id).values(**values))
    await _commit(db, auth, learner)
    await db.refresh(adm)
    return await _render_administration(db, adm, learner, detail=True)


@learner_router.post("/assessments/{assessment_id}/supersede", status_code=201)
async def supersede(campus_id: str, learner_id: str, assessment_id: str,
                    payload: ca.SupersedeInput,
                    auth: dict = Depends(require_educator),
                    db: AsyncSession = Depends(get_db)) -> dict:
    """Correct a finalized record: a NEW draft, linked, and the old one closed.

    The finalized row is never modified; only its ledger gains a
    SUPERSEDED_WITH_AUDIT_LINK entry pointing at the replacement.
    """
    teacher, learner = await _scope(db, auth, campus_id, learner_id)
    old = await _administration(db, learner, assessment_id)
    new_id = str(uuid.uuid4())
    await _advance(db, learner, old, teacher.id, Action.SUPERSEDE,
                   resolution=payload.reason, link_id=new_id)
    content = _dec(old.content_enc, "pilot_assessment_administrations", "content_enc",
                   learner, old.id)
    new = PilotAssessmentAdministration(
        id=new_id, campus_id=old.campus_id, learner_id=old.learner_id,
        administrator_id=teacher.id, instrument=old.instrument, edition=old.edition,
        measure=old.measure, grade=old.grade, form_id=old.form_id,
        administration_purpose=old.administration_purpose,
        instructional_cycle=old.instructional_cycle, administered_at=old.administered_at,
        report_source=old.report_source, official_benchmark_window=old.official_benchmark_window,
        vendor_next_assessment_date=old.vendor_next_assessment_date,
        benchmark_authorization_id=old.benchmark_authorization_id, fidelity_state="standard",
        supersedes_id=old.id,
        content_enc=_enc(content, "pilot_assessment_administrations", "content_enc",
                         learner, new_id),
        created_at=datetime.now(timezone.utc),
    )
    db.add(new)
    _append(db, learner, new_id, teacher.id, None, "create", "", State.DRAFT.value,
            link_id=old.id, note=payload.reason)
    await _commit(db, auth, learner)
    return await _render_administration(db, new, learner)


@learner_router.get("/assessments/{assessment_id}/audit")
async def audit(campus_id: str, learner_id: str, assessment_id: str,
                auth: dict = Depends(require_educator),
                db: AsyncSession = Depends(get_db)) -> dict:
    _, learner = await _scope(db, auth, campus_id, learner_id)
    adm = await _administration(db, learner, assessment_id)
    rows = await _transitions(db, adm.id)
    return {"assessment_id": adm.id,
            "chain_valid": verify_chain(rows, _transition_fields),
            "entries": [_render_transition(r, learner) for r in rows]}


def _render_transition(r: PilotAssessmentTransition, learner: PilotLearner) -> dict:
    note = None
    if r.note_enc is not None:
        note = _dec(r.note_enc, "pilot_assessment_transitions", "note_enc", learner, r.id)["note"]
    return {**_transition_fields(r), "object_type": "assessment_administration",
            "object_id": r.administration_id, "entry_hash": r.entry_hash,
            "prev_hash": r.prev_hash, "note": note, "created_at": _iso(r.created_at)}


# ── Evidence, proposal, decision, plan, progress monitoring ─────────────────

@learner_router.post("/assessments/{assessment_id}/evidence", status_code=201)
async def record_evidence(campus_id: str, learner_id: str, assessment_id: str,
                          payload: ca.EvidenceInput,
                          auth: dict = Depends(require_educator),
                          db: AsyncSession = Depends(get_db)) -> dict:
    teacher, learner = await _scope(db, auth, campus_id, learner_id)
    adm = await _administration(db, learner, assessment_id)
    if adm.snapshot_sha256 is None or await _snapshot_hash(db, adm, learner) != adm.snapshot_sha256:
        raise _conflict("Evidence can only reference an intact finalized snapshot")
    scores = await _score_rows(db, adm.id)
    await _advance(db, learner, adm, teacher.id, Action.RECORD_EVIDENCE,
                   content_sha256=adm.snapshot_sha256)
    ev_id = str(uuid.uuid4())
    db.add(PilotAssessmentEvidence(
        id=ev_id, administration_id=adm.id, campus_id=learner.campus_id,
        learner_id=learner.id, snapshot_sha256=adm.snapshot_sha256,
        score_ids=json.dumps([s.id for s in scores]),
        summary_enc=_enc({"summary": (payload.summary or "").strip() or None},
                         "pilot_assessment_evidence", "summary_enc", learner, ev_id),
        recorded_by=teacher.id, created_at=datetime.now(timezone.utc),
    ))
    await _commit(db, auth, learner)
    ev = await db.get(PilotAssessmentEvidence, ev_id)
    return _render_evidence(ev, learner)


def _render_evidence(ev: PilotAssessmentEvidence, learner: PilotLearner) -> dict:
    summary = _dec(ev.summary_enc, "pilot_assessment_evidence", "summary_enc", learner, ev.id)
    return {"evidence_id": ev.id, "assessment_id": ev.administration_id,
            "snapshot_sha256": ev.snapshot_sha256, "score_ids": json.loads(ev.score_ids),
            "summary": summary["summary"], "recorded_at": _iso(ev.created_at)}


async def _last_decision(db, adm_id) -> Optional[PilotAssessmentDecision]:
    return (await db.execute(
        select(PilotAssessmentDecision).where(PilotAssessmentDecision.administration_id == adm_id)
        .order_by(PilotAssessmentDecision.seq.desc()).limit(1)
    )).scalar_one_or_none()


@learner_router.post("/assessments/{assessment_id}/proposal")
async def request_proposal(campus_id: str, learner_id: str, assessment_id: str,
                           auth: dict = Depends(require_educator),
                           db: AsyncSession = Depends(get_db)) -> dict:
    teacher, learner = await _scope(db, auth, campus_id, learner_id)
    adm = await _administration(db, learner, assessment_id)
    state, _ = await _state(db, adm.id)
    if state is State.TEACHER_DECISION_RECORDED:
        last = await _last_decision(db, adm.id)
        if last is None or last.action != "reject":
            raise _conflict("Only a rejected proposal may be followed by a new one")
    evidence = (await db.execute(select(PilotAssessmentEvidence).where(
        PilotAssessmentEvidence.administration_id == adm.id))).scalar_one_or_none()
    if evidence is None:
        raise _conflict("Record evidence before requesting a proposal")
    scores = [_render_score(s, learner) for s in await _score_rows(db, adm.id)]
    cycles, _ = await _calendar(db, learner.campus_id)
    proposal = ca.propose(scores, ca.next_data_day(cycles, adm.instructional_cycle))
    if proposal.abstained:
        return {"abstained": True, "reason": proposal.reason,
                "policy_version": proposal.policy_version}
    await _advance(db, learner, adm, teacher.id, Action.REQUEST_REVIEW)
    pid = str(uuid.uuid4())
    db.add(PilotAssessmentProposal(
        id=pid, administration_id=adm.id, evidence_id=evidence.id,
        campus_id=learner.campus_id, learner_id=learner.id, status="pending", version=1,
        policy_version=proposal.policy_version, proposed_review_on=proposal.proposed_review_on,
        proposal_enc=_enc({"text": proposal.text, "rationale": list(proposal.rationale)},
                          "pilot_assessment_proposals", "proposal_enc", learner, pid),
        requested_by=teacher.id, created_at=datetime.now(timezone.utc),
    ))
    await _commit(db, auth, learner)
    return {"abstained": False, **_render_proposal(await db.get(PilotAssessmentProposal, pid), learner)}


def _render_proposal(p: PilotAssessmentProposal, learner: PilotLearner) -> dict:
    body = _dec(p.proposal_enc, "pilot_assessment_proposals", "proposal_enc", learner, p.id)
    return {"proposal_id": p.id, "assessment_id": p.administration_id,
            "evidence_id": p.evidence_id, "status": p.status, "version": p.version,
            "policy_version": p.policy_version, "proposed_next_step": body["text"],
            "rationale": body["rationale"], "proposed_review_on": _iso(p.proposed_review_on),
            "is_approval": False}


def _decision_fields(r: PilotAssessmentDecision) -> dict:
    return {"seq": r.seq, "evidence_id": r.evidence_id, "proposal_id": r.proposal_id,
            "administration_id": r.administration_id, "campus_id": r.campus_id,
            "learner_id": r.learner_id, "teacher_id": r.teacher_id, "action": r.action,
            "version": r.version, "confirmed_review_on": _iso(r.confirmed_review_on) or "",
            "content_sha256": r.content_sha256}


@learner_router.post("/assessments/{assessment_id}/proposals/{proposal_id}/decision")
async def decide(campus_id: str, learner_id: str, assessment_id: str, proposal_id: str,
                 payload: ca.DecisionInput,
                 auth: dict = Depends(require_educator),
                 db: AsyncSession = Depends(get_db)) -> dict:
    teacher, learner = await _scope(db, auth, campus_id, learner_id)
    adm = await _administration(db, learner, assessment_id)
    prop = await db.get(PilotAssessmentProposal, g1._id(proposal_id))
    if prop is None or prop.administration_id != adm.id or prop.learner_id != learner.id \
            or prop.campus_id != learner.campus_id:
        raise _not_found()
    if prop.status != "pending" or prop.version != payload.expected_version:
        raise _conflict("Proposal already decided or changed")
    original = _dec(prop.proposal_enc, "pilot_assessment_proposals", "proposal_enc",
                    learner, prop.id)
    text = {"approve": original["text"], "edit": (payload.edited_text or "").strip(),
            "reject": ""}[payload.action]
    await _advance(db, learner, adm, teacher.id, Action.RECORD_DECISION,
                   content_sha256=_sha(text))
    result = await db.execute(
        update(PilotAssessmentProposal)
        .where(PilotAssessmentProposal.id == prop.id,
               PilotAssessmentProposal.status == "pending",
               PilotAssessmentProposal.version == payload.expected_version)
        .values(status={"approve": "approved", "edit": "edited", "reject": "rejected"}[payload.action],
                version=payload.expected_version + 1)
    )
    if result.rowcount != 1:
        await db.rollback()
        raise _conflict("Proposal already decided or changed")
    last = (await db.execute(
        select(PilotAssessmentDecision).where(PilotAssessmentDecision.learner_id == learner.id)
        .order_by(PilotAssessmentDecision.seq.desc()).limit(1)
    )).scalar_one_or_none()
    did = str(uuid.uuid4())
    row = PilotAssessmentDecision(
        id=did, evidence_id=prop.evidence_id, proposal_id=prop.id, administration_id=adm.id,
        campus_id=learner.campus_id, learner_id=learner.id, teacher_id=teacher.id,
        seq=(last.seq + 1) if last else 1, action=payload.action,
        version=payload.expected_version + 1, confirmed_review_on=payload.confirmed_review_on,
        content_sha256=_sha(text),
        rationale_enc=_enc({"rationale": (payload.rationale or "").strip() or None,
                            "authorized_text": text or None},
                           "pilot_assessment_decisions", "rationale_enc", learner, did),
        prev_hash=last.entry_hash if last else GENESIS, entry_hash="",
        created_at=datetime.now(timezone.utc),
    )
    row.entry_hash = entry_hash(row.prev_hash, _decision_fields(row))
    db.add(row)
    await _commit(db, auth, learner)
    return _render_decision(row, learner)


def _render_decision(r: PilotAssessmentDecision, learner: PilotLearner) -> dict:
    body = _dec(r.rationale_enc, "pilot_assessment_decisions", "rationale_enc", learner, r.id)
    return {**_decision_fields(r), "decision_id": r.id,
            "confirmed_review_on": _iso(r.confirmed_review_on),
            "rationale": body["rationale"], "authorized_text": body["authorized_text"],
            "entry_hash": r.entry_hash, "prev_hash": r.prev_hash,
            "created_at": _iso(r.created_at)}


@learner_router.post("/assessments/{assessment_id}/plan", status_code=201)
async def record_plan(campus_id: str, learner_id: str, assessment_id: str,
                      payload: ca.PlanInput,
                      auth: dict = Depends(require_educator),
                      db: AsyncSession = Depends(get_db)) -> dict:
    teacher, learner = await _scope(db, auth, campus_id, learner_id)
    adm = await _administration(db, learner, assessment_id)
    last = await _last_decision(db, adm.id)
    if last is None or last.action not in ("approve", "edit"):
        raise _conflict("A plan follows an approved or edited proposal")
    await _advance(db, learner, adm, teacher.id, Action.RECORD_PLAN,
                   content_sha256=_sha(payload.plan_text.strip()))
    pid = str(uuid.uuid4())
    db.add(PilotAssessmentPlan(
        id=pid, administration_id=adm.id, decision_id=last.id, campus_id=learner.campus_id,
        learner_id=learner.id, delivery_state="NOT_REQUESTED",
        plan_enc=_enc({"plan_text": payload.plan_text.strip()}, "pilot_assessment_plans",
                      "plan_enc", learner, pid),
        created_by=teacher.id, created_at=datetime.now(timezone.utc),
    ))
    await _commit(db, auth, learner)
    return {"plan_id": pid, "assessment_id": adm.id, "decision_id": last.id,
            "status": "recorded", "delivery_state": "NOT_REQUESTED"}


@learner_router.post("/assessments/{assessment_id}/progress-monitoring", status_code=201)
async def schedule_progress_monitoring(campus_id: str, learner_id: str, assessment_id: str,
                                       payload: ca.ProgressMonitoringInput,
                                       auth: dict = Depends(require_educator),
                                       db: AsyncSession = Depends(get_db)) -> dict:
    """Records teacher-confirmed dates. Creates no administration and starts nothing."""
    teacher, learner = await _scope(db, auth, campus_id, learner_id)
    adm = await _administration(db, learner, assessment_id)
    plan = (await db.execute(select(PilotAssessmentPlan).where(
        PilotAssessmentPlan.administration_id == adm.id)
        .order_by(PilotAssessmentPlan.created_at.desc()).limit(1))).scalar_one_or_none()
    if plan is None:
        raise _conflict("Record a plan first")
    await _advance(db, learner, adm, teacher.id, Action.SCHEDULE_PROGRESS_MONITORING)
    sid = str(uuid.uuid4())
    dates = sorted(d.isoformat() for d in payload.planned_dates)
    db.add(PilotProgressMonitoringSchedule(
        id=sid, administration_id=adm.id, plan_id=plan.id, campus_id=learner.campus_id,
        learner_id=learner.id, measure=payload.measure, planned_dates=json.dumps(dates),
        created_by=teacher.id, created_at=datetime.now(timezone.utc),
    ))
    await _commit(db, auth, learner)
    return {"schedule_id": sid, "assessment_id": adm.id, "plan_id": plan.id,
            "measure": payload.measure, "planned_dates": dates,
            "status": "teacher_confirmed_dates_recorded"}


# ── Data Day packet ─────────────────────────────────────────────────────────

_VALID_FIDELITY = ("standard", "interrupted_resolved")


@learner_router.get("/data-day")
async def data_day_packet(campus_id: str, learner_id: str,
                          cycle: str = Query(min_length=2, max_length=32, pattern=r"^[a-z0-9_]+$"),
                          auth: dict = Depends(require_educator),
                          db: AsyncSession = Depends(get_db)) -> dict:
    """Read-only, teacher-controlled review packet built from canonical records.

    Changes nothing: no score, placement, schedule or instruction is
    touched by reading it. Approve/edit/reject controls are links to the
    decision route, which only a teacher's explicit POST exercises.
    """
    _, learner = await _scope(db, auth, campus_id, learner_id)
    cycles, configured = await _calendar(db, learner.campus_id)
    by_key = {c.cycle_key: c for c in cycles}
    if cycle not in by_key:
        raise HTTPException(status_code=422, detail="Unknown instructional cycle for this campus")
    position = by_key[cycle].position
    adms = (await db.execute(
        select(PilotAssessmentAdministration).where(
            PilotAssessmentAdministration.campus_id == learner.campus_id,
            PilotAssessmentAdministration.learner_id == learner.id,
        ).order_by(PilotAssessmentAdministration.administered_at, PilotAssessmentAdministration.id)
    )).scalars().all()

    current, prior, not_valid, skipped, points, responses = [], [], [], [], [], []
    audit_view, superseded_by = [], {}
    for adm in adms:
        trs = await _transitions(db, adm.id)
        for t in trs:
            if t.action == Action.SUPERSEDE.value and t.link_id:
                superseded_by[adm.id] = t.link_id
    for adm in adms:
        state, _ = await _state(db, adm.id)
        cyc = by_key.get(adm.instructional_cycle)
        if cyc is None or cyc.position > position:
            continue  # later cycles are not part of this Data Day
        trs = await _transitions(db, adm.id)
        audit_view.append({"assessment_id": adm.id,
                           "chain_valid": verify_chain(trs, _transition_fields),
                           "entries": [_render_transition(t, learner) for t in trs]})
        rendered = await _render_administration(db, adm, learner, detail=True)
        valid = (state in POST_FINALIZATION and adm.fidelity_state in _VALID_FIDELITY
                 and rendered.get("snapshot_verified") is True)
        if not valid:
            not_valid.append({"assessment_id": adm.id, "state": state.value,
                              "fidelity_state": adm.fidelity_state,
                              "instructional_cycle": adm.instructional_cycle,
                              "superseded_by": superseded_by.get(adm.id),
                              "snapshot_verified": rendered.get("snapshot_verified")})
            continue
        (current if cyc.position == position else prior).append(rendered)
        for s in rendered["scores"]:
            if s["administration_status"] != "scored":
                skipped.append({"assessment_id": adm.id, "measure": s["measure"],
                                "administration_status": s["administration_status"],
                                "reason": s["reason"]})
            at = adm.administered_at if adm.administered_at.tzinfo else \
                adm.administered_at.replace(tzinfo=timezone.utc)
            points.append(ca.ScorePoint(adm.id, at, adm.administration_purpose, s["measure"],
                                        s["administration_status"], s["raw_score"],
                                        s["score_unit"]))
        responses.extend(rendered["responses"])

    evidence = [
        _render_evidence(e, learner) for e in (await db.execute(
            select(PilotAssessmentEvidence).where(
                PilotAssessmentEvidence.learner_id == learner.id,
                PilotAssessmentEvidence.campus_id == learner.campus_id,
                PilotAssessmentEvidence.administration_id.in_(
                    [a["assessment_id"] for a in current + prior])))).scalars().all()]
    decisions = list((await db.execute(
        select(PilotAssessmentDecision).where(
            PilotAssessmentDecision.learner_id == learner.id,
            PilotAssessmentDecision.campus_id == learner.campus_id,
        ).order_by(PilotAssessmentDecision.seq))).scalars().all())
    plans = {p.decision_id: p for p in (await db.execute(
        select(PilotAssessmentPlan).where(PilotAssessmentPlan.learner_id == learner.id,
                                          PilotAssessmentPlan.campus_id == learner.campus_id)
    )).scalars().all()}
    prior_decisions = []
    for d in decisions:
        r = _render_decision(d, learner)
        plan = plans.get(d.id)
        r["outcome"] = {"plan_recorded": plan is not None,
                        "delivery_state": plan.delivery_state if plan else "NOT_REQUESTED"}
        prior_decisions.append(r)
    pending = [
        _render_proposal(p, learner) for p in (await db.execute(
            select(PilotAssessmentProposal).where(
                PilotAssessmentProposal.learner_id == learner.id,
                PilotAssessmentProposal.campus_id == learner.campus_id,
                PilotAssessmentProposal.status == "pending",
                PilotAssessmentProposal.administration_id.in_(
                    [a["assessment_id"] for a in current]),
            ).order_by(PilotAssessmentProposal.created_at))).scalars().all()]
    base = f"/pilot/campuses/{learner.campus_id}/learners/{learner.id}/assessments"
    controls = [
        {"proposal_id": p["proposal_id"], "expected_version": p["version"],
         "actions": ["approve", "edit", "reject"], "method": "POST",
         "path": f"{base}/{p['assessment_id']}/proposals/{p['proposal_id']}/decision"}
        for p in pending
    ]
    return {
        "campus_id": learner.campus_id, "learner_id": learner.id,
        "cycle": {"cycle_key": cycle, "label": by_key[cycle].label,
                  "data_day_on": _iso(by_key[cycle].data_day_on),
                  "calendar_configured": configured},
        "current_valid_results": current,
        "prior_valid_results": prior,
        "not_valid_administrations": not_valid,
        "skipped_or_invalid_measures": skipped,
        "growth_by_measure": ca.growth_by_measure(points),
        "cited_evidence": evidence,
        "observed_error_patterns": ca.error_patterns(responses),
        "prior_teacher_decisions": prior_decisions,
        "proposed_next_steps": pending,
        "recommended_next_review": [
            {"proposal_id": p["proposal_id"], "proposed_review_on": p["proposed_review_on"],
             "status": "proposed_awaiting_teacher_confirmation"} for p in pending],
        "controls": controls,
        "audit_history": {
            "administrations": audit_view,
            "decisions_chain_valid": verify_chain(decisions, _decision_fields),
        },
        "boundaries": {"changes_official_scores": False, "alters_placement": False,
                       "starts_instruction": False, "delivers_instruction": False},
    }
