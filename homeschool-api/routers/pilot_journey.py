"""Valor pilot G2: one complete teacher journey, UUID-scoped end to end.

    authorized evidence -> source-linked recommendation
      -> educator approve / edit / reject -> durable, auditable decision
      -> authorized instruction available for follow-up

Every route resolves the learner through G1's ``_assigned`` join (active
campus, active membership, active per-learner grant, live educator
session), so there is no path here that trusts a client-supplied campus
or a display name. Unassigned, cross-campus, revoked and malformed IDs all
return the same 404, so the API never confirms a record exists.

The decision itself goes through ``services.governed_orchestrator``'s
``review_recommendation`` (PR #591) with real adapters: authorization is a
fresh G1 grant check, persistence is a version-checked compare-and-swap,
and audit is an append to the hash-chained ``PilotDecision`` ledger, all
inside one transaction, so a decision is either fully recorded or not at
all.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import PilotLearner, get_db
from core.deps import require_educator
from core.encryption import aad_for, decrypt_json, encrypt_json
from core.pilot_journey_models import PilotDecision, PilotEvidence, PilotRecommendation
from routers.pilot_campuses import _assigned, _id
from services.assessment_interop import EducatorAssessmentSubmission
from services.educator_access import live_educator
from services.governed_orchestrator import (
    Decision, Evidence, Recommendation, Scope, review_recommendation,
)
from services.pilot_recommender import EvidenceRecord, recommend

router = APIRouter(prefix="/pilot/me/learners", tags=["valor-pilot"])

GENESIS = "0" * 64
_NOT_FOUND = HTTPException(status_code=404, detail="Record not found")


class _Conflict(Exception):
    """The recommendation was already decided or its version moved."""


def _aad(table: str, column: str, learner: PilotLearner, row_id: str) -> bytes:
    return aad_for(table, column, f"{learner.campus_id}:{learner.id}:{row_id}")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest() if text else ""


def entry_hash(prev_hash: str, row: dict) -> str:
    """Canonical hash of one ledger entry, committing to its predecessor."""
    body = {"prev_hash": prev_hash, **row}
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _ledger_fields(row: PilotDecision) -> dict:
    return {
        "seq": row.seq, "recommendation_id": row.recommendation_id,
        "campus_id": row.campus_id, "learner_id": row.learner_id,
        "educator_id": row.educator_id, "action": row.action,
        "from_version": row.from_version, "to_version": row.to_version,
        "content_sha256": row.content_sha256,
    }


def verify_chain(rows: list[PilotDecision]) -> bool:
    """True when the learner's ledger is complete, ordered and untampered."""
    prev = GENESIS
    for expected_seq, row in enumerate(sorted(rows, key=lambda r: r.seq), start=1):
        if row.seq != expected_seq or row.prev_hash != prev:
            return False
        if row.entry_hash != entry_hash(prev, _ledger_fields(row)):
            return False
        prev = row.entry_hash
    return True


# ── Evidence ────────────────────────────────────────────────────────────────

def _render_evidence(row: PilotEvidence, learner: PilotLearner) -> dict:
    detail = decrypt_json(row.detail_enc, _aad("pilot_evidence", "detail_enc", learner, row.id))
    return {"evidence_id": row.id, "recorded_at": row.created_at.isoformat(), **detail}


@router.post("/{learner_id}/evidence", status_code=201)
async def record_evidence(
    learner_id: str, payload: EducatorAssessmentSubmission,
    auth: dict = Depends(require_educator), db: AsyncSession = Depends(get_db),
) -> dict:
    learner = await _assigned(db, auth, learner_id)
    teacher = await live_educator(db, auth)
    row_id = str(uuid.uuid4())
    row = PilotEvidence(
        id=row_id, campus_id=learner.campus_id, learner_id=learner.id,
        recorded_by=teacher.id,
        detail_enc=encrypt_json(payload.model_dump(mode="json"),
                                _aad("pilot_evidence", "detail_enc", learner, row_id)),
        created_at=datetime.now(timezone.utc),
    )
    db.add(row)
    await db.commit()
    return _render_evidence(row, learner)


async def _evidence_rows(db: AsyncSession, learner: PilotLearner) -> list[PilotEvidence]:
    return list((await db.execute(
        select(PilotEvidence)
        .where(PilotEvidence.campus_id == learner.campus_id,
               PilotEvidence.learner_id == learner.id)
        .order_by(PilotEvidence.created_at, PilotEvidence.id)
    )).scalars().all())


@router.get("/{learner_id}/evidence")
async def list_evidence(
    learner_id: str, auth: dict = Depends(require_educator),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    learner = await _assigned(db, auth, learner_id)
    return [_render_evidence(r, learner) for r in await _evidence_rows(db, learner)]


# ── Recommendations ─────────────────────────────────────────────────────────

def _render_recommendation(row: PilotRecommendation, learner: PilotLearner) -> dict:
    proposal = decrypt_json(row.proposal_enc,
                            _aad("pilot_recommendations", "proposal_enc", learner, row.id))
    authorized = None
    if row.authorized_enc is not None:
        authorized = decrypt_json(
            row.authorized_enc,
            _aad("pilot_recommendations", "authorized_enc", learner, row.id),
        )["text"]
    return {
        "recommendation_id": row.id, "learner_id": row.learner_id,
        "status": row.status, "version": row.version,
        "policy_version": row.policy_version,
        "source_evidence_ids": json.loads(row.source_evidence_ids),
        "proposal": proposal["text"], "rationale": proposal["rationale"],
        "authorized_instruction": authorized,
        "created_at": row.created_at.isoformat(),
        "decided_at": row.decided_at.isoformat() if row.decided_at else None,
    }


@router.post("/{learner_id}/recommendations")
async def request_recommendation(
    learner_id: str, auth: dict = Depends(require_educator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    learner = await _assigned(db, auth, learner_id)
    teacher = await live_educator(db, auth)
    pending = (await db.execute(
        select(PilotRecommendation.id).where(
            PilotRecommendation.learner_id == learner.id,
            PilotRecommendation.campus_id == learner.campus_id,
            PilotRecommendation.status == "pending",
        ).limit(1)
    )).scalar_one_or_none()
    if pending is not None:
        # One open proposal at a time, so a decision is never made against
        # a recommendation the teacher has not seen superseded.
        raise HTTPException(status_code=409, detail="Decide the pending recommendation first")

    records = []
    for row in await _evidence_rows(db, learner):
        d = decrypt_json(row.detail_enc, _aad("pilot_evidence", "detail_enc", learner, row.id))
        records.append(EvidenceRecord(
            evidence_id=row.id, framework=d["framework"], measure=d["measure"],
            assessed_on=datetime.fromisoformat(d["assessed_on"]).date(),
            reported_band=d.get("reported_band"), assistance=d.get("assistance"),
            recorded_at=row.created_at,
        ))
    proposal = recommend(records)
    if proposal.abstained:
        return {"abstained": True, "reason": proposal.reason,
                "policy_version": proposal.policy_version}

    row_id = str(uuid.uuid4())
    row = PilotRecommendation(
        id=row_id, campus_id=learner.campus_id, learner_id=learner.id,
        requested_by=teacher.id, status="pending", version=1,
        policy_version=proposal.policy_version,
        source_evidence_ids=json.dumps(list(proposal.source_evidence_ids)),
        proposal_enc=encrypt_json(
            {"text": proposal.text, "rationale": list(proposal.rationale)},
            _aad("pilot_recommendations", "proposal_enc", learner, row_id),
        ),
        created_at=datetime.now(timezone.utc),
    )
    db.add(row)
    await db.commit()
    return {"abstained": False, **_render_recommendation(row, learner)}


async def _owned_recommendation(
    db: AsyncSession, learner: PilotLearner, recommendation_id: str,
) -> PilotRecommendation:
    row = await db.get(PilotRecommendation, _id(recommendation_id))
    if row is None or row.learner_id != learner.id or row.campus_id != learner.campus_id:
        raise _NOT_FOUND
    return row


@router.get("/{learner_id}/recommendations")
async def list_recommendations(
    learner_id: str, auth: dict = Depends(require_educator),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    learner = await _assigned(db, auth, learner_id)
    rows = (await db.execute(
        select(PilotRecommendation)
        .where(PilotRecommendation.learner_id == learner.id,
               PilotRecommendation.campus_id == learner.campus_id)
        .order_by(PilotRecommendation.created_at.desc(), PilotRecommendation.id)
    )).scalars().all()
    return [_render_recommendation(r, learner) for r in rows]


# ── Decision ────────────────────────────────────────────────────────────────

class DecisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["approve", "edit", "reject"]
    expected_version: int = Field(ge=1)
    edited_text: str | None = Field(default=None, max_length=1200)
    note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _edit_contract(self):
        text = (self.edited_text or "").strip()
        if self.action == "edit" and not text:
            raise ValueError("An edit must include the edited instruction")
        if self.action != "edit" and self.edited_text is not None:
            raise ValueError("Only an edit carries edited instruction text")
        return self


_STATUS_FOR = {"approve": "approved", "edit": "edited", "reject": "rejected"}


@router.post("/{learner_id}/recommendations/{recommendation_id}/decision")
async def decide(
    learner_id: str, recommendation_id: str, payload: DecisionInput,
    auth: dict = Depends(require_educator), db: AsyncSession = Depends(get_db),
) -> dict:
    learner = await _assigned(db, auth, learner_id)
    teacher = await live_educator(db, auth)
    rec = await _owned_recommendation(db, learner, recommendation_id)
    if rec.status != "pending" or rec.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Recommendation already decided or changed")

    original = decrypt_json(rec.proposal_enc,
                            _aad("pilot_recommendations", "proposal_enc", learner, rec.id))
    authorized_text = {
        "approve": original["text"],
        "edit": (payload.edited_text or "").strip(),
        "reject": "",
    }[payload.action]
    expected = payload.expected_version
    scope = Scope(campus_id=learner.campus_id, learner_id=learner.id, educator_id=teacher.id)
    proposal = Recommendation(
        text=original["text"],
        evidence=tuple(Evidence(source_id=e, summary="")
                       for e in json.loads(rec.source_evidence_ids)),
        proposal_id=rec.id,
    )
    now = datetime.now(timezone.utc)

    async def authorize(s: Scope, task: str) -> bool:
        # Re-check the live G1 grant at the moment of decision, not only at
        # request start: a grant revoked mid-request must not authorize.
        try:
            again = await _assigned(db, auth, s.learner_id)
        except HTTPException:
            return False
        return again.id == s.learner_id and again.campus_id == s.campus_id

    async def persist(s: Scope, p: Recommendation, d: Decision) -> None:
        values = {
            "status": _STATUS_FOR[d.value], "version": expected + 1,
            "decided_at": now, "decided_by": s.educator_id,
        }
        if authorized_text:
            values["authorized_enc"] = encrypt_json(
                {"text": authorized_text},
                _aad("pilot_recommendations", "authorized_enc", learner, p.proposal_id),
            )
        result = await db.execute(
            update(PilotRecommendation)
            .where(PilotRecommendation.id == p.proposal_id,
                   PilotRecommendation.status == "pending",
                   PilotRecommendation.version == expected)
            .values(**values)
        )
        if result.rowcount != 1:
            raise _Conflict()

    async def audit(s: Scope, proposal_id: str, action: str) -> None:
        if not action.startswith("teacher:"):
            return  # blocked attempts are refused before any ledger write
        last = (await db.execute(
            select(PilotDecision)
            .where(PilotDecision.learner_id == s.learner_id)
            .order_by(PilotDecision.seq.desc()).limit(1)
        )).scalar_one_or_none()
        prev = last.entry_hash if last else GENESIS
        seq = (last.seq + 1) if last else 1
        row = PilotDecision(
            id=str(uuid.uuid4()), recommendation_id=proposal_id,
            campus_id=s.campus_id, learner_id=s.learner_id, educator_id=s.educator_id,
            seq=seq, action=action.split(":", 1)[1],
            from_version=expected, to_version=expected + 1,
            content_sha256=_sha(authorized_text), prev_hash=prev, entry_hash="",
            created_at=now,
        )
        row.entry_hash = entry_hash(prev, _ledger_fields(row))
        if payload.note and payload.note.strip():
            row.note_enc = encrypt_json(
                {"note": payload.note.strip()},
                _aad("pilot_decisions", "note_enc", learner, row.id),
            )
        db.add(row)
        await db.flush()

    try:
        await review_recommendation(
            scope, proposal, Decision(payload.action),
            authorize=authorize, persist=persist, audit=audit,
        )
        await db.commit()
    except PermissionError:
        await db.rollback()
        raise _NOT_FOUND
    except (_Conflict, IntegrityError):
        await db.rollback()
        raise HTTPException(status_code=409, detail="Recommendation already decided or changed")

    await db.refresh(rec)
    return _render_recommendation(rec, learner)


@router.get("/{learner_id}/decisions")
async def decision_ledger(
    learner_id: str, auth: dict = Depends(require_educator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    learner = await _assigned(db, auth, learner_id)
    rows = list((await db.execute(
        select(PilotDecision)
        .where(PilotDecision.learner_id == learner.id,
               PilotDecision.campus_id == learner.campus_id)
        .order_by(PilotDecision.seq)
    )).scalars().all())
    entries = []
    for r in rows:
        note = None
        if r.note_enc is not None:
            note = decrypt_json(r.note_enc, _aad("pilot_decisions", "note_enc", learner, r.id))["note"]
        entries.append({**_ledger_fields(r), "decision_id": r.id,
                        "entry_hash": r.entry_hash, "prev_hash": r.prev_hash,
                        "note": note, "created_at": r.created_at.isoformat()})
    return {"chain_valid": verify_chain(rows), "entries": entries}


@router.get("/{learner_id}/instruction")
async def authorized_instruction(
    learner_id: str, auth: dict = Depends(require_educator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """The most recent teacher-authorized instruction for follow-up.

    Only approved or edited recommendations are ever returned; a pending or
    rejected proposal is never presented as instruction.
    """
    learner = await _assigned(db, auth, learner_id)
    row = (await db.execute(
        select(PilotRecommendation)
        .where(PilotRecommendation.learner_id == learner.id,
               PilotRecommendation.campus_id == learner.campus_id,
               PilotRecommendation.status.in_(("approved", "edited")))
        .order_by(PilotRecommendation.decided_at.desc(), PilotRecommendation.id)
        .limit(1)
    )).scalar_one_or_none()
    if row is None:
        return {"authorized_instruction": None}
    rendered = _render_recommendation(row, learner)
    return {"authorized_instruction": rendered["authorized_instruction"],
            "recommendation_id": row.id, "status": row.status,
            "source_evidence_ids": rendered["source_evidence_ids"],
            "decided_at": rendered["decided_at"]}
