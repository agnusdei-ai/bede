"""A teacher-confirmed classroom quiz, saved against one roster learner
(``routers/pilot_journey.py``'s ``/quiz-results`` routes).

Owner direction 2026-11-14:

* **Saved only once the teacher confirms.** The save re-runs
  ``teacher_quiz.finalize``: the quiz must be approved and every question
  settled by the teacher. The learner is the one the teacher selected, by its
  roster UUID; nothing reads a name off the page.
* **A retry counts once; a correction replaces.** One save is one
  ``submission_id``. A correction is a new save naming the result it
  replaces, which then stops counting.
* **Progress, with provenance.** A question that maps to a skill
  (mathematics, ``packs.math.skill_for``) moves that skill's estimate, at the
  marked-quiz weight; every estimate lists the result and question numbers it
  came from. A question with no mapping stays in the quiz history and moves
  nothing.
* **Computed on read, never stored.** No mastery row is written. The estimate
  is rebuilt from the current results each time it is asked for, so a
  correction or a deletion changes it with nothing left behind. This also
  keeps storage inside the school notice's §4(b) (assessment records and the
  teacher's evidence about the student's work); a stored estimate would be a
  further category to confirm first.
* **Not an official assessment.** Nothing here writes to the canonical
  assessment, gradebook or export paths.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Optional

from models.practice import FinalizeResultsRequest, TeacherQuestion
from services.practice import teacher_quiz
from services.practice.evidence import QUIZ_EVIDENCE_WEIGHT

MATH_SUBJECTS = ("mathematics", "math")

_BAND = {"K": "K-2", "1": "K-2", "2": "K-2", "3": "3-5", "4": "3-5", "5": "3-5",
         "6": "6-8", "7": "6-8", "8": "6-8"}


def body_digest(req: FinalizeResultsRequest) -> str:
    """What a retry must repeat exactly to count as the same save."""
    body = req.model_dump(mode="json")
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def snapshot(req: FinalizeResultsRequest) -> dict:
    """The record to store: the confirmed totals and just enough of the quiz
    to read them later. Raises the teacher_quiz errors when not confirmed."""
    final = teacher_quiz.finalize(req)
    points = {r["number"]: r for r in final["results"]}
    return {
        "title": req.quiz.title,
        "subject": req.quiz.subject,
        "grade": req.quiz.grade,
        "questions": [
            {"number": q.number, "type": q.type, "prompt": q.prompt,
             "points": points[q.number]["points"], "max_points": q.points,
             "skill_id": skill_for(req.quiz.subject, q)}
            for q in req.quiz.questions
        ],
        "total": final["total"],
        "possible": final["possible"],
        "source": "teacher_confirmed_classroom_quiz",
    }


@dataclass(frozen=True)
class _Item:
    prompt: str
    diagram: None = None


def skill_for(subject: str, question: TeacherQuestion) -> Optional[str]:
    """The skill a question exercises, or None. Mathematics only: the other
    subjects have no engine a classroom quiz can feed."""
    if subject.strip().lower() not in MATH_SUBJECTS:
        return None
    from services.practice.packs.math import skill_for as math_skill

    return math_skill(_Item(prompt=question.prompt))


def outcome(points: float, max_points: int) -> str:
    if points >= max_points:
        return "correct"
    if points <= 0:
        return "incorrect"
    return "partial"


async def estimate(results: list[tuple[str, dict]], grade: str) -> dict:
    """Mastery estimate from current results, oldest first, with sources.

    ``results`` is ``[(result_id, snapshot), ...]`` for CURRENT rows only.
    Pure apart from the engine's own arithmetic: nothing is read or written.
    """
    from services.diagnostic import apply_evidence, mastery
    from services.diagnostic.skill_map import SKILL_MAP

    vector = mastery.new_vector(_BAND.get(grade, "3-5"))
    sources: dict[str, list[dict]] = {}
    unmapped = 0
    count = 0
    for result_id, snap in results:
        for q in snap["questions"]:
            skill = q.get("skill_id")
            if not skill:
                unmapped += 1
                continue
            vector, _ = await apply_evidence(
                vector, f"probe.{skill}", outcome(q["points"], q["max_points"]),
                confidence=QUIZ_EVIDENCE_WEIGHT,
                calibration_weight=mastery.calibration_weight_for(count),
            )
            count += 1
            sources.setdefault(skill, []).append(
                {"result_id": result_id, "question": q["number"],
                 "outcome": outcome(q["points"], q["max_points"])})
    skills = [
        {"skill_id": skill, "label": SKILL_MAP[skill].label if skill in SKILL_MAP else skill,
         "estimate": round(vector.get(skill, 0.0), 3), "observations": len(found), "sources": found}
        for skill, found in sorted(sources.items())
    ]
    return {
        "skills": skills,
        "observations": count,
        "unmapped_questions": unmapped,
        "weight": QUIZ_EVIDENCE_WEIGHT,
        "computed_on_read": True,
        "stored": False,
        "basis": "teacher-confirmed classroom quiz results; not an official assessment",
    }
