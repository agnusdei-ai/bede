"""Read-only, source-linked pilot diagnostic *view*, never an AI diagnosis.

Source records are finalized canonical assessment evidence. Nothing is
generated, scored, interpreted, approved, or delivered by this endpoint.
Access is resolved against G1's active campus, educator and learner grant,
and the finalized source hash must still match before returning a citation.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.deps import require_educator
from core.pilot_assessment_models import (
    PilotAssessmentAdministration, PilotAssessmentEvidence,
)
from routers.pilot_assessments import _snapshot_hash
from routers.pilot_campuses import _assigned
from services import pilot_authz

router = APIRouter(prefix="/pilot/me/learners", tags=["valor-pilot-evidence"])


class EvidenceCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidence_id: str
    assessment_id: str
    instrument: str
    measure: str
    grade: str
    administered_at: datetime
    administration_purpose: str
    snapshot_sha256: str
    recorded_at: datetime


class DiagnosticView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    learner_id: str
    status: Literal["no_evidence", "evidence_available"]
    sources: list[EvidenceCitation]
    has_more: bool
    message: str


@router.get("/{learner_id}/diagnostic", response_model=DiagnosticView)
async def diagnostic_view(
    learner_id: str,
    limit: int = Query(default=10, ge=1, le=25),
    auth: dict = Depends(require_educator),
    db: AsyncSession = Depends(get_db),
) -> DiagnosticView:
    learner = await _assigned(db, auth, learner_id)
    # Pin the original educator / campus / grant identity and version before
    # reading.  A second lookup in the SAME DB session can see a stale grant.
    ctx = await pilot_authz.resolve_campus_learner(
        db, auth, learner.id, pilot_authz.ACTION_LEARNER_READ,
    )
    rows = list((await db.execute(
        select(PilotAssessmentEvidence)
        .where(PilotAssessmentEvidence.campus_id == learner.campus_id,
               PilotAssessmentEvidence.learner_id == learner.id)
        .order_by(PilotAssessmentEvidence.created_at.desc(), PilotAssessmentEvidence.id.desc())
        .limit(limit + 1)
    )).scalars().all())

    out = []
    for ev in rows[:limit]:
        adm = await db.get(PilotAssessmentAdministration, ev.administration_id)
        if (adm is None or adm.id != ev.administration_id
                or adm.campus_id != learner.campus_id
                or adm.learner_id != learner.id
                or adm.finalized_at is None
                or not adm.snapshot_sha256
                or adm.snapshot_sha256 != ev.snapshot_sha256
                or await _snapshot_hash(db, adm, learner) != ev.snapshot_sha256):
            # Never display an invented or stale evidence citation if the
            # source snapshot no longer verifies.
            raise HTTPException(status_code=409,
                                detail="Verified assessment evidence is unavailable")
        out.append(EvidenceCitation(
            evidence_id=ev.id, assessment_id=ev.administration_id,
            instrument=adm.instrument, measure=adm.measure, grade=adm.grade,
            administered_at=adm.administered_at,
            administration_purpose=adm.administration_purpose,
            snapshot_sha256=ev.snapshot_sha256, recorded_at=ev.created_at,
        ))

    # A FRESH DB session must confirm that the original grant and credential
    # version still hold before any protected material leaves this endpoint.
    # The request's own SQLAlchemy identity map can be stale after revoke.
    if not await pilot_authz.revalidate(ctx):
        pilot_authz.audit_revoked(ctx, "diagnostic.read")
        raise HTTPException(status_code=404, detail="Record not found")

    return DiagnosticView(
        learner_id=learner.id,
        status="evidence_available" if out else "no_evidence",
        sources=out, has_more=len(rows) > limit,
        message=(
            "Verified assessment evidence is available for educator review. "
            "This view does not diagnose a learner or recommend instruction."
            if out else
            "No finalized, verified assessment evidence is recorded for this learner."
        ),
    )
