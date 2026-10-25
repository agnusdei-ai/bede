"""Practice Coach pipeline: diagnose a confirmed assessment, plan practice,
and write the parent's summary (docs/PRACTICE_COACH.md).

Pure functions, no I/O, on services/policy_engine.py's precedent: a test
states a quiz and reads back exactly what Bede would say about it.
"""
from __future__ import annotations

import logging

from models.practice import Diagnosis, ErrorInstance, GradedAssessment, PracticeSet, teacher_mark_count
from services.practice import core_checks
from services.practice.packs import SubjectPack, get_pack

log = logging.getLogger(__name__)


class UnknownSubject(ValueError):
    pass


def pack_for(assessment: GradedAssessment) -> SubjectPack:
    pack = get_pack(assessment.subject)
    if pack is None:
        raise UnknownSubject(assessment.subject)
    return pack


def _known(pack: SubjectPack, error: ErrorInstance) -> bool:
    if error.category in core_checks.TAXONOMY or pack.knows(error.category):
        return True
    log.warning("Practice pack %s emitted unknown category %s; dropped", pack.id, error.category)
    return False


def diagnose(assessment: GradedAssessment, history: list | None = None) -> Diagnosis:
    pack = pack_for(assessment)
    errors = [e for e in core_checks.run(assessment) + pack.classify_errors(assessment, history) if _known(pack, e)]
    strengths = [s for s in pack.find_strengths(assessment) if pack.knows(s.category)]
    return Diagnosis(errors=errors, strengths=strengths, ask_parent=assessment.needs_parent())


def plan(diagnosis: Diagnosis, assessment: GradedAssessment, constraints: dict | None = None) -> PracticeSet | None:
    if diagnosis.ask_parent:
        # Guardrail 4: nothing is planned on a reading the parent hasn't settled.
        raise ValueError("Confirm the flagged answers before planning practice")
    return pack_for(assessment).generate_practice(diagnosis, assessment, constraints or {})


def parent_summary(assessment: GradedAssessment, diagnosis: Diagnosis, practice: PracticeSet | None) -> str:
    """Encouraging and specific, framed around growth (guardrail 5). Built
    from the diagnosis rather than written freely, so it can never mention
    something the diagnosis did not find."""
    count = teacher_mark_count(assessment)
    parts = [f"{count['correct']} of {count['total']}, by the teacher's marks."]
    misses = [e for e in diagnosis.errors if e.audience == "parent_and_child"]
    if misses:
        parts.append("What to work on: " + "; ".join(f"{e.item_ref}, {e.evidence}" for e in misses) + ".")
    elif not count["total"] or count["correct"] == count["total"]:
        parts.append("Nothing was missed.")
    for e in diagnosis.errors:
        if e.audience == "parent_only":
            parts.append(f"For you only: {e.evidence}")
    if diagnosis.strengths:
        parts.append("Solid: " + "; ".join(s.note for s in diagnosis.strengths) + ".")
    if practice:
        parts.append(
            f"Here is a {practice.est_minutes}-minute practice set for you to approve, with a quick re-check "
            f"in {practice.recheck_schedule[0].lstrip('+').replace('d', ' days')}."
        )
    return " ".join(parts)
