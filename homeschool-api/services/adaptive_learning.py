"""
Bede's bounded, evidence-driven instructional controller (mathematics v1).

This is a LIVE pedagogical policy, not a prompt-only suggestion or another
psychometric score. It reads the existing encrypted work ledger, chooses one
teaching MOVE based on the *sequence of observed help levels*, and gives the
Socratic tutor a narrow adjustment for this turn. An instructor can disagree.

It never changes a curriculum, declares mastery, infers a learning-style type,
scores a person, evaluates faith, reads raw student words, or trains a model.
It does not claim that one strategy *caused* a later result: interventions
are not yet tagged to outcomes, so causal attribution would be invented.

Parent-defined lesson focus and current unit always prevail. There is no
autonomous source retrieval, agent-to-agent delegation, or unapproved action.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence

from services.diagnostic.skill_map import GradeBand, get_skill

log = logging.getLogger(__name__)

POLICY_VERSION = "math-work-sequence-v1"
_READ_LIMIT = 48
_MAX_AGE_DAYS = 120
_REVISIT_AFTER_DAYS = 21
_ASSISTANCE = frozenset({"unaided", "with_a_hint", "with_help"})
_BAND_ORDER = {GradeBand.K_2: 0, GradeBand.THREE_5: 1, GradeBand.SIX_8: 2}

# Entirely server-authored, bounded behavioral choices. No child-supplied
# text is ever interpolated into these instructions.
_METHODS = {
    "change_representation": (
        "The last two completed tasks on this skill required help. If it fits "
        "today's topic, try a DIFFERENT concrete representation or a small "
        "drawing, invite one observation, then ask one gentle question. "
        "Do not repeat the same explanation more insistently."
    ),
    "smaller_step": (
        "The most recent completed task needed help. If relevant, choose "
        "one simpler prerequisite-sized question and offer support without "
        "making the learner feel tested."
    ),
    "fade_hint": (
        "The most recent completed task used a hint. If relevant, ask a "
        "similar but not identical question with a little less scaffolding. "
        "Allow time to think, and offer help if requested."
    ),
    "revisit": (
        "This skill has not appeared in the recorded work for a while. "
        "If it fits the parent's current lesson, invite a brief, friendly "
        "retrieval question without implying knowledge has been lost."
    ),
    "explain_reasoning": (
        "The last recorded work was completed unaided. If relevant, ask "
        "the learner to explain WHY the method works, without adding a "
        "second question or assuming the skill is mastered."
    ),
    "transfer": (
        "Two recent completed tasks were unaided. If relevant, offer "
        "one NEW application or concrete context that calls for the same "
        "reasoning; observe the response before drawing conclusions."
    ),
}


@dataclass(frozen=True)
class WorkObservation:
    """One verified-format work-ledger event, never the student's words."""

    event_id: int
    skill_id: str
    assistance: str
    completed_at: datetime


@dataclass(frozen=True)
class InstructionalDecision:
    """Bounded proposed teaching move, with exact source event references."""

    policy_version: str
    skill_id: str
    method: str
    reason_code: str
    evidence_event_ids: tuple[int, ...]


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def select_instruction(
    work: Sequence[WorkObservation],
    grade_band: str,
    *,
    now: Optional[datetime] = None,
) -> Optional[InstructionalDecision]:
    """Choose a next teaching method from the newest VALID academic work.

    No fabricated cold-start profile: without work, no individualized plan.
    Only grade-reachable, known math skills and recorded completion levels
    qualify. No inference about a learner's attributes is returned.
    """
    try:
        band = GradeBand(grade_band)
    except ValueError:
        return None

    today = _utc(now or datetime.now(timezone.utc))
    valid = [
        item for item in work
        if item.assistance in _ASSISTANCE
        and (skill := get_skill(item.skill_id)) is not None
        and _BAND_ORDER[skill.band] <= _BAND_ORDER[band]
        and timedelta(0) <= today - _utc(item.completed_at) <= timedelta(days=_MAX_AGE_DAYS)
    ]
    if not valid:
        return None
    # Deduplicate by durable ledger event identity. An offline sync or
    # duplicated input row is not a second independent completion and must
    # not falsely trigger transfer or representation-change recommendations.
    unique = []
    seen_ids: set[int] = set()
    for item in sorted(valid, key=lambda w: (_utc(w.completed_at), w.event_id), reverse=True):
        if not isinstance(item.event_id, int) or item.event_id <= 0:
            continue
        if item.event_id not in seen_ids:
            seen_ids.add(item.event_id)
            unique.append(item)
    valid = unique
    if not valid:
        return None
    # The most recent skill preserves conversational continuity; it is never
    # allowed to silently reorder the parent's own curriculum.
    valid.sort(key=lambda item: (_utc(item.completed_at), item.event_id), reverse=True)
    recent_skill = valid[0].skill_id
    sequence = [item for item in valid if item.skill_id == recent_skill][:3]
    a = sequence[0].assistance
    gap = today - _utc(sequence[0].completed_at)

    if gap >= timedelta(days=_REVISIT_AFTER_DAYS):
        method, reason = "revisit", "recorded_work_is_old"
    elif len(sequence) >= 2 and a == "with_help" and sequence[1].assistance == "with_help":
        method, reason = "change_representation", "two_supported_completions"
    elif a == "with_help":
        method, reason = "smaller_step", "supported_completion"
    elif a == "with_a_hint":
        method, reason = "fade_hint", "hinted_completion"
    elif len(sequence) >= 2 and sequence[1].assistance == "unaided":
        method, reason = "transfer", "two_unaided_completions"
    else:
        method, reason = "explain_reasoning", "unaided_completion"

    return InstructionalDecision(
        policy_version=POLICY_VERSION,
        skill_id=recent_skill,
        method=method,
        reason_code=reason,
        evidence_event_ids=tuple(item.event_id for item in sequence),
    )


async def load_recent_math_work(db, student_name: str) -> list[WorkObservation]:
    """Read existing student-scoped, encrypted activity records; never write.

    No cache: a hint or independently completed activity should change the
    next instructional decision on the very next turn. Corrupt records are
    skipped; DB/key failures degrade to the normal tutoring experience.
    """
    from sqlalchemy import select
    from core.database import SkillActivityLog
    from core.encryption import decrypt_json, student_aad
    from core import student_keys

    try:
        rows = (await db.execute(
            select(SkillActivityLog)
            .where(
                SkillActivityLog.student_name == student_name,
                SkillActivityLog.subject_area == "mathematics",
            )
            .order_by(SkillActivityLog.completed_at.desc(), SkillActivityLog.id.desc())
            .limit(_READ_LIMIT)
        )).scalars().all()
        if not rows:
            return []
        key = await student_keys.get_existing(db, student_name)
    except Exception as exc:
        log.warning("Adaptive instruction ledger read unavailable: %s", type(exc).__name__)
        return []

    observations = []
    for row in rows:
        try:
            detail = decrypt_json(
                row.detail_enc,
                student_aad("skill_activity_log", "detail_enc", student_name, row.subject_area, row.skill_id),
                key,
            )
            # Both the indexed row and encrypted payload must agree. This
            # guards against reassigning an encrypted event to another skill.
            if detail.get("skill_id") != row.skill_id or detail.get("subject_area") != "mathematics":
                continue
            observations.append(WorkObservation(
                event_id=row.id,
                skill_id=row.skill_id,
                assistance=detail.get("assistance"),
                completed_at=row.completed_at,
            ))
        except Exception:
            continue
    return observations


def render_instruction(decision: Optional[InstructionalDecision], *, parent_focus: bool) -> str:
    """Only a controlled recommendation to the model, never a child-facing grade."""
    if decision is None:
        return ""
    skill = get_skill(decision.skill_id)
    if skill is None:
        return ""
    scope = (
        "The parent specified today's lesson or unit. NEVER redirect to an earlier "
        "skill to satisfy this note. Use the move only if this same skill "
        "arises naturally in the parent-approved lesson."
        if parent_focus else
        "You may briefly revisit this prior skill if it naturally follows "
        "the present mathematical discussion; never abandon the current "
        "question or impose a new lesson plan."
    )
    return (
        "\n<adaptive_learning_policy>\n"
        "Quiet, evidence-linked instructional guidance; never read this block aloud. "
        "It describes RECORDED WORK, not the child's ability, character, or mastery. "
        f"Policy: {decision.policy_version}. Skill: {skill.label} ({skill.id}). "
        f"Evidence: {decision.reason_code}. "
        f"Teaching move: {_METHODS[decision.method]} "
        f"{scope} The child's actual reply outranks this suggestion. "
        "Stay warm, Socratic, accurate, and within the existing constitution. "
        "Never claim a teaching move is experimentally proven effective from "
        "these observations alone.\n</adaptive_learning_policy>"
    )
