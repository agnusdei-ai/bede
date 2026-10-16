"""Adapter seam: canonical EvidenceRecord / TeacherDecision <-> G2 (#604).

This lane is built on #596 (G1). G2's teacher journey (#604:
``PilotEvidence``, ``PilotRecommendation``, ``PilotDecision``) lands on a
different branch and is restacked later by the orchestrator. Neither side
imports the other; this module is the ONE documented place they meet, and
it is pure so it can be tested on either branch:

* ``to_g2_evidence_submission`` turns one scored canonical measure into the
  exact dict G2's ``POST /pilot/me/learners/{id}/evidence`` accepts
  (``services.assessment_interop.EducatorAssessmentSubmission``). It refuses
  (returns ``None``) for anything that is not a scored measure from a
  finalized snapshot: a skipped measure is never sent as a zero, and a
  record whose purpose has no G2 window is not forced into one.
* ``to_g2_decision_input`` turns a canonical teacher decision into G2's
  ``DecisionInput`` body.
* ``TeacherDecisionLink`` is the record the orchestrator persists after
  restack to join a canonical decision to a G2 recommendation id, so the
  canonical ``PilotAssessmentDecision.proposal_id`` and G2's
  ``PilotRecommendation.id`` reference each other without either table
  being rewritten.

Printed band labels are deliberately NOT mapped onto G2's ``reported_band``
vocabulary: the two vocabularies differ, and translating one into the other
would be computing a band, which this model never does. ``reported_band``
is left unset and the canonical record remains the source of the printed
labels.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional, Protocol

_G2_WINDOW = {"BOY": "beginning_of_year", "MOY": "middle_of_year", "EOY": "end_of_year"}


def _g2_window(meta: dict) -> Optional[str]:
    if meta["administration_purpose"] == "progress_monitoring":
        return "progress_monitoring"
    if meta["administration_purpose"] == "benchmark":
        return _G2_WINDOW.get(meta["official_benchmark_window"])
    return None


def to_g2_evidence_submission(meta: dict, score: dict, *, finalized: bool) -> Optional[dict]:
    """One scored canonical measure -> G2 evidence body, or None."""
    if not finalized or score.get("administration_status") != "scored":
        return None
    if score.get("raw_score") is None:
        return None
    window = _g2_window(meta)
    if window is None:
        return None
    administered = meta["administered_at"]
    if isinstance(administered, str):
        administered = datetime.fromisoformat(administered)
    assessed_on = administered.date() if isinstance(administered, datetime) else administered
    assert isinstance(assessed_on, date)
    return {
        "framework": "dibels8",
        "measure": score["measure"],
        "assessed_on": assessed_on.isoformat(),
        "source_name": f"Canonical record {meta['assessment_id']}",
        "score": score["raw_score"],
        "score_unit": score["score_unit"],
        "assessed_grade": meta["grade"],
        "assessment_window": window,
    }


def to_g2_decision_input(decision: dict) -> dict:
    """Canonical teacher decision -> G2 ``DecisionInput`` body."""
    body = {"action": decision["action"], "expected_version": decision["version"] - 1}
    if decision["action"] == "edit":
        body["edited_text"] = decision["authorized_text"]
    if decision.get("rationale"):
        body["note"] = decision["rationale"][:500]
    return body


@dataclass(frozen=True)
class TeacherDecisionLink:
    canonical_evidence_id: str
    canonical_proposal_id: str
    canonical_decision_id: str
    g2_recommendation_id: str


class TeacherDecisionSink(Protocol):
    """Implemented after restack by whatever persists the G2 side."""

    async def link(self, link: TeacherDecisionLink) -> None: ...
