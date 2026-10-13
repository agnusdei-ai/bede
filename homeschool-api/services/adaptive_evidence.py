"""
Encrypted audit of adaptive instructional *recommendations*, not efficacy.

For transparency and defensible evaluations, record which bounded teaching
policy was PREPARED as part of a model prompt, and which completed academic
work came later. The first fact is verifiable in code; the second is temporal.
Neither proves the tutor actually followed the advice or caused progress.

Do not write child text, student abilities, religious engagement, confidence
scores, model prompts, or teaching directives into this table.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from services.adaptive_learning import (
    InstructionalDecision, _METHODS, _utc, load_recent_math_work,
)
from services.diagnostic.skill_map import get_skill

log = logging.getLogger(__name__)

TRACE_SCHEMA_VERSION = 1
_MAX_REPORT = 40
_REPORT_DAYS = 90


def recommendation_fingerprint(decision: InstructionalDecision, *, parent_focus: bool = False) -> str:
    """Stable de-duplication for repeat prompts from identical work history."""
    body = [
        decision.policy_version, decision.skill_id, decision.method,
        decision.reason_code, list(decision.evidence_event_ids),
        bool(parent_focus),
    ]
    return hashlib.sha256(json.dumps(body, separators=(",", ":")).encode("utf-8")).hexdigest()


async def record_prompt_recommendation(
    db,
    student_name: str,
    decision: InstructionalDecision,
    *,
    parent_focus: bool,
) -> bool:
    """Persist one proposed strategy, once per evidence signature.

    Returns True only when a *new* record is created. The instruction is
    already supplied to the prompt separately; failure here must never
    interrupt an authorized tutoring session or claim mastery.
    """
    from sqlalchemy import select
    from core import student_keys
    from core.database import AdaptiveInstructionTrace
    from core.encryption import encrypt_json, student_aad

    if (get_skill(decision.skill_id) is None
            or decision.method not in _METHODS
            or not decision.evidence_event_ids
            or any(not isinstance(i, int) or i <= 0 for i in decision.evidence_event_ids)):
        return False

    fingerprint = recommendation_fingerprint(decision, parent_focus=parent_focus)
    try:
        existing = (await db.execute(
            select(AdaptiveInstructionTrace.id).where(
                AdaptiveInstructionTrace.student_name == student_name,
                AdaptiveInstructionTrace.fingerprint == fingerprint,
            )
        )).scalar_one_or_none()
        if existing is not None:
            return False

        key = await student_keys.get_or_create(db, student_name)
        detail = {
            "schema_version": TRACE_SCHEMA_VERSION,
            "policy_version": decision.policy_version,
            "skill_id": decision.skill_id,
            "method": decision.method,
            "reason_code": decision.reason_code,
            "source_activity_ids": list(decision.evidence_event_ids),
            "parent_focus": bool(parent_focus),
            "status": "recommended_in_prompt",
        }
        db.add(AdaptiveInstructionTrace(
            student_name=student_name,
            fingerprint=fingerprint,
            detail_enc=encrypt_json(
                detail,
                student_aad("adaptive_instruction_traces", "detail_enc", student_name),
                key,
            ),
            created_at=datetime.now(timezone.utc),
        ))
        await db.commit()
        return True
    except Exception as exc:
        # A duplicated concurrent turn can hit the uniqueness constraint.
        # A trace is never worth disrupting the child's work.
        await db.rollback()
        log.warning("Adaptive teaching recommendation trace unavailable: %s", type(exc).__name__)
        return False


async def parent_recommendation_history(
    db, student_name: str, *, days: int = _REPORT_DAYS, limit: int = _MAX_REPORT,
) -> dict:
    """Parent-only caller. Honest observations, never a causal success score."""
    from sqlalchemy import select
    from core import student_keys
    from core.database import AdaptiveInstructionTrace
    from core.encryption import decrypt_json, student_aad

    days = min(365, max(1, int(days)))
    limit = min(100, max(1, int(limit)))
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)

    rows = (await db.execute(
        select(AdaptiveInstructionTrace).where(
            AdaptiveInstructionTrace.student_name == student_name,
            AdaptiveInstructionTrace.created_at >= cutoff,
        ).order_by(
            AdaptiveInstructionTrace.created_at.desc(),
            AdaptiveInstructionTrace.id.desc(),
        ).limit(limit)
    )).scalars().all()
    if not rows:
        return _report(student_name, days, [])

    key = await student_keys.get_existing(db, student_name)
    # The existing bounded, student-scoped loader performs the decryption
    # and record-integrity checks. It may omit older work beyond 48 events;
    # any missing later evidence must stay "not observed", not "failed".
    recent_work = await load_recent_math_work(db, student_name)
    entries = []
    for row in rows:
        try:
            d = decrypt_json(
                row.detail_enc,
                student_aad("adaptive_instruction_traces", "detail_enc", student_name),
                key,
            )
            if (d.get("schema_version") != TRACE_SCHEMA_VERSION
                    or d.get("status") != "recommended_in_prompt"
                    or d.get("method") not in _METHODS
                    or get_skill(d.get("skill_id")) is None):
                continue
            source_ids = d.get("source_activity_ids", [])
            if (not isinstance(source_ids, list)
                    or not source_ids
                    or not all(isinstance(i, int) and i > 0 for i in source_ids)):
                continue
            candidates = [
                w for w in recent_work
                if w.skill_id == d["skill_id"]
                and w.event_id not in source_ids
                and _utc(w.completed_at) > _utc(row.created_at)
            ]
            candidates.sort(key=lambda w: (_utc(w.completed_at), w.event_id))
            next_work = candidates[0] if candidates else None
            entries.append({
                "recommendation_id": row.id,
                "recommended_at": _utc(row.created_at).isoformat(),
                "policy_version": d["policy_version"],
                "skill_id": d["skill_id"],
                "method": d["method"],
                "reason_code": d["reason_code"],
                "source_activity_ids": source_ids,
                "parent_focus": d["parent_focus"],
                "status": "recommended_in_prompt",
                "later_completed_work": ({
                    "activity_id": next_work.event_id,
                    "completed_at": _utc(next_work.completed_at).isoformat(),
                    "assistance": next_work.assistance,
                } if next_work else None),
            })
        except Exception:
            # Invalid or undecryptable records cannot become evidence.
            continue
    return _report(student_name, days, entries)


def _report(student_name: str, days: int, entries: list[dict]) -> dict:
    return {
        "student_name": student_name,
        "since_days": days,
        "recommendations": entries,
        "interpretation": (
            "These are teaching methods recommended in the model's prompt, "
            "not proven delivered interventions. Later completed work is an "
            "observation, not evidence that the recommendation caused learning. "
            "Older work may be absent from the bounded activity window."
        ),
    }
