"""A confirmed quiz's marks, counted toward the mastery estimate and the
work record (docs/PRACTICE_COACH.md, "Quizzes count toward progress").

Until this module, a graded quiz the parent uploaded built a practice set and
nothing else: the mastery estimate and the work record were fed only by
sessions with Bede. The owner's ruling (2026-11-11) is that a quiz counts
toward both. How it counts follows the rules those two records already keep:

* **Only the teacher's own marks.** A question marked correct, incorrect or
  partly right becomes one observation; an unmarked question records nothing,
  and Bede never marks one itself for this purpose. A question the parent
  left out (``excluded``) is gone before anything is read.
* **Only once the parent has confirmed the reading**, and only once per quiz
  (``PracticeEvidenceMark``). Editing a reading after it was counted does
  not count it again.
* **Only where the skill is clear.** A maths problem maps to one skill in
  ``services/diagnostic/skill_map.py`` when the pack can read it
  (``packs.math.skill_for``); a word problem or anything unclear records
  nothing. Spelling and reading map to the reading-and-spelling engine, which
  covers grades 3-8 only: a K-2 spelling or reading quiz records nothing,
  since the phonics engine measures decoding, which a marked quiz does not
  show. History, science, geography, grammar and Latin quizzes have no
  matching engine and record nothing.
* **Paper counts for less than live work.** Bede did not see how the answer
  was reached, whether help was given, or how long it took, so every
  observation moves the estimate by ``QUIZ_EVIDENCE_WEIGHT`` of a live one.
* **The work record keeps only completed work**, as it always has: a question
  marked correct is one row, tagged ``source="marked_quiz"``. A wrong or partly
  right answer writes no row (``activity.py``'s standing rule), and nothing
  here describes the child.
* **The privacy setting is honoured.** With ``RETAIN_MASTERY_PROFILES`` off
  no estimate is written; the work record still is, exactly as in a session.

Nothing here is measured for Scripture, Saints & Catechism or Morning Time:
there is no practice pack for them and no engine to write to.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from core.log_redaction import exc_text, learner_ref
from models.practice import GradedAssessment

log = logging.getLogger(__name__)

# How far one marked quiz question moves an estimate, relative to a question
# Bede watched the child answer in a session. Applied as the maths engine's
# `confidence` and the literacy engine's `weight`.
QUIZ_EVIDENCE_WEIGHT = 0.5

# A teacher's mark, as the outcome vocabulary every engine already uses.
_MARK_TO_OUTCOME = {"correct": "correct", "incorrect": "incorrect", "partial": "partial"}

# Grade stages the reading-and-spelling engine covers (ai_service's
# _LITERACY_STAGES, by value, so this module does not import ai_service).
_LITERACY_STAGES = ("3-5", "6-8")


@dataclass(frozen=True)
class QuizEvidence:
    subject_area: str   # "mathematics" or "literacy"
    skill_id: str       # a skill_map id, or a literacy domain
    outcome: str        # "correct", "incorrect" or "partial"


def _reading_domain(prompt: str) -> str:
    from services.practice.packs import reading

    if reading._JUDGEMENT.search(prompt):
        return "inference"
    if reading._VOCABULARY.search(prompt):
        return "vocabulary"
    return "literal_comprehension"


def _spelling_domain(assessment: GradedAssessment, section, item) -> str:
    from services.practice.packs import spelling

    if item.teacher_mark == "correct":
        return "spelling_patterns"
    ref = spelling._ref(section, item)
    for error in spelling.classify_errors(assessment):
        if error.item_ref == ref and error.category == "spelling.homophone":
            return "spelling_homophones"
    return "spelling_patterns"


def evidence_from(assessment: GradedAssessment, grade_stage: str) -> list[QuizEvidence]:
    """Every observation a confirmed quiz supports. Pure: no I/O."""
    from services.practice.packs import get_pack

    pack = get_pack(assessment.subject)
    if pack is None:
        return []
    assessment = assessment.reviewed()
    out: list[QuizEvidence] = []
    for section in assessment.sections:
        for item in section.items:
            outcome = _MARK_TO_OUTCOME.get(item.teacher_mark)
            if outcome is None or item.needs_parent():
                continue
            if pack.id == "math":
                from services.practice.packs.math import skill_for

                skill = skill_for(item)
                if skill:
                    out.append(QuizEvidence("mathematics", skill, outcome))
            elif pack.id == "spelling" and grade_stage in _LITERACY_STAGES:
                out.append(QuizEvidence("literacy", _spelling_domain(assessment, section, item), outcome))
            elif pack.id == "reading" and grade_stage in _LITERACY_STAGES:
                out.append(QuizEvidence("literacy", _reading_domain(item.prompt), outcome))
    return out


async def _grade_stage(db, student_name: str) -> Optional[str]:
    from sqlalchemy import select

    from core import student_keys
    from core.database import StudentConfig
    from core.encryption import decrypt_json
    from models.schemas import SessionConfig
    from routers.pod import _config_aad

    row = (await db.execute(
        select(StudentConfig).where(StudentConfig.student_name == student_name)
    )).scalar_one_or_none()
    if row is None:
        return None
    config = SessionConfig(**decrypt_json(
        row.config_enc, _config_aad(student_name), await student_keys.get_existing(db, student_name)
    ))
    return config.grade_stage.value


async def count_quiz(db, student_name: str, assessment_id: int, assessment: GradedAssessment) -> int:
    """Count a confirmed quiz toward progress, once. Returns how many
    observations were recorded (0 when already counted or nothing applies).

    Best-effort like every other evidence write: a failure is logged and
    swallowed, so it can never undo the parent's confirmation.
    """
    from sqlalchemy.exc import IntegrityError

    from core.config import settings
    from core.database import PracticeEvidenceMark

    try:
        if await db.get(PracticeEvidenceMark, assessment_id) is not None:
            return 0
        grade_stage = await _grade_stage(db, student_name)
        if grade_stage is None:
            return 0
        observations = evidence_from(assessment, grade_stage)
        # The mark is claimed first and committed, so two confirmations racing
        # each other cannot both count the quiz: the second insert fails on
        # the primary key and records nothing.
        db.add(PracticeEvidenceMark(assessment_id=assessment_id, student_name=student_name))
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            return 0
    except Exception as exc:
        await db.rollback()
        log.warning("Quiz evidence skipped for %s: %s", learner_ref(student_name), exc_text(exc, student_name))
        return 0

    from services.ai_service import _work_label
    from services.diagnostic import literacy, process_evidence
    from services.diagnostic.activity import record_activity

    recorded = 0
    for ev in observations:
        try:
            if settings.retain_mastery_profiles:
                if ev.subject_area == "mathematics":
                    await process_evidence(
                        db, student_name, f"probe.{ev.skill_id}", ev.outcome,
                        QUIZ_EVIDENCE_WEIGHT, grade_stage,
                    )
                else:
                    await literacy.process_evidence(
                        db, student_name, ev.skill_id, ev.outcome, weight=QUIZ_EVIDENCE_WEIGHT,
                    )
            if ev.outcome == "correct":
                await record_activity(
                    db, student_name, ev.subject_area, ev.skill_id,
                    _work_label(ev.subject_area, ev.skill_id), ev.outcome, source="marked_quiz",
                )
            recorded += 1
        except Exception as exc:
            log.warning("Quiz evidence write failed for %s/%s: %s", learner_ref(student_name), ev.skill_id, exc_text(exc, student_name))
    return recorded
