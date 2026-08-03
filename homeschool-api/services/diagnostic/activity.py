"""
The work ledger — what a student has actually DONE, as distinct from what
Bede infers they can do.

WHY THIS EXISTS ALONGSIDE THE MASTERY ENGINE, NOT INSIDE IT.
services/diagnostic/mastery.py and its siblings answer "how likely is it
that this child has mastered X" — a psychometric claim about the child,
built from CDM/IRT/KST. That is useful to a parent and it stays. But it is
the wrong instrument for two things this project actually wants:

  1. A parent asking "what has my child actually done this term?" —
     a question of fact, which a probability cannot answer.
  2. A pod behaving like a self-managed team, where one member helps
     another. Knowing WHO HAS DONE a piece of work is ordinary and useful.
     Knowing who scores higher on a latent trait is a ranking of children,
     which this project does not build.

This module records only the first kind. Every row is an observed event:
on this date, in this subject, a task in this skill was completed, with
this much help. Nothing here classifies a child, estimates a trait, or
produces a score. `summarize` returns counts and dates — deliberately not
an average, a level, or a percentage, because each of those would quietly
turn a work record back into a judgment of the person.

WHAT "SIGNIFIES SKILL" HERE. A completion count is honest evidence in a way
a probability is not: fourteen equivalent-fraction tasks finished unaided
is a fact, and a parent can act on it without Bede having asserted anything
about their child's ability. That is the whole basis on which one student
might help another — demonstrated work, not a measured trait.

PARENT-FACING ONLY. Nothing in this module is exposed to a child, and the
pod view exists so a parent can arrange peer teaching among their own
students. A child is never shown their own or anyone else's ledger; a
child who can see they are behind a sibling has been ranked, whatever the
UI calls it.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from models.schemas import (
    WORK_DISTINCTION_LEVELS,
    WORK_QUALITY_LEVELS,
    WORK_SPEED_LEVELS,
)

log = logging.getLogger(__name__)

# Factual, not evaluative. Records how the work went, never how able the
# child is — "with_help" is a description of an event, not a deficiency.
ASSISTANCE_LEVELS = ("unaided", "with_a_hint", "with_help")

# Maps the outcome vocabulary every diagnostic in this package already uses
# onto that factual scale. `incorrect` is deliberately absent: a task that
# was attempted and missed is not a COMPLETED activity, and recording it
# here would turn a work ledger into a record of failures — precisely the
# thing this table exists to avoid being.
_OUTCOME_TO_ASSISTANCE: dict[str, str] = {
    "correct": "unaided",
    "partial": "with_a_hint",
    "hint_dependent": "with_help",
}


def assistance_for_outcome(outcome: str) -> Optional[str]:
    """None for an outcome that doesn't represent completed work."""
    return _OUTCOME_TO_ASSISTANCE.get(outcome)


async def record_activity(
    db,
    student_name: str,
    subject_area: str,
    skill_id: str,
    label: str,
    outcome: str,
    quality: Optional[str] = None,
    distinction: Optional[str] = None,
    speed: Optional[str] = None,
) -> bool:
    """
    Append one completed-activity row. Returns True if a row was written.

    Best-effort in exactly the way every other diagnostic write in this
    package is: a failure here is logged and swallowed, never raised, so a
    ledger hiccup can't break a child's tutoring turn. Called alongside the
    existing mastery writes rather than replacing them — the two answer
    different questions and both are wanted.
    """
    assistance = assistance_for_outcome(outcome)
    if assistance is None:
        return False

    from core.database import SkillActivityLog
    from core.encryption import encrypt_json

    try:
        db.add(SkillActivityLog(
            student_name=student_name,
            subject_area=subject_area,
            skill_id=skill_id,
            detail_enc=encrypt_json({
                "skill_id": skill_id,
                "label": label,
                "assistance": assistance,
                "subject_area": subject_area,
                # Scores of the WORK. Stored inside the encrypted blob
                # rather than as columns so adding a dimension later needs
                # no schema change — this codebase has no ALTER TABLE path
                # (see core/database.py). Absent when Bede didn't observe
                # enough to judge, which is an honest state and must stay
                # distinguishable from a low score.
                "quality": quality if quality in WORK_QUALITY_LEVELS else None,
                "distinction": distinction if distinction in WORK_DISTINCTION_LEVELS else None,
                "speed": speed if speed in WORK_SPEED_LEVELS else None,
            }),
        ))
        await db.commit()
        return True
    except Exception as exc:
        await db.rollback()
        log.warning("Skill-activity write failed for %s/%s: %s", student_name, skill_id, exc)
        return False


async def summarize(
    db,
    student_name: str,
    since_days: int = 90,
    subject_area: Optional[str] = None,
) -> dict:
    """
    What this student has actually done, as counts and dates.

    Deliberately returns no average, level, percentage, or score. Those
    would each collapse a work record back into a judgment of the child,
    which is the one thing this ledger is for avoiding. A parent gets
    facts: which skills have been worked, how many times, how much help was
    needed, and when it last happened.
    """
    from sqlalchemy import select

    from core.database import SkillActivityLog
    from core.encryption import decrypt_json

    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, since_days))
    try:
        stmt = select(SkillActivityLog).where(
            SkillActivityLog.student_name == student_name,
            SkillActivityLog.completed_at >= cutoff,
        )
        if subject_area:
            stmt = stmt.where(SkillActivityLog.subject_area == subject_area)
        rows = (await db.execute(stmt)).scalars().all()
    except Exception as exc:
        log.warning("Skill-activity summary failed for %s: %s", student_name, exc)
        return {"student_name": student_name, "since_days": since_days, "total": 0, "skills": []}

    by_skill: dict[str, dict] = {}
    for row in rows:
        try:
            detail = decrypt_json(row.detail_enc)
        except Exception:
            continue
        entry = by_skill.setdefault(row.skill_id, {
            "skill_id": row.skill_id,
            "label": detail.get("label") or row.skill_id,
            "subject_area": row.subject_area,
            "completed": 0,
            "unaided": 0,
            "with_a_hint": 0,
            "with_help": 0,
            "scored": 0,
            "quality": {level: 0 for level in WORK_QUALITY_LEVELS},
            "distinction": {level: 0 for level in WORK_DISTINCTION_LEVELS},
            "speed": {level: 0 for level in WORK_SPEED_LEVELS},
            "last_worked": None,
        })
        entry["completed"] += 1
        assistance = detail.get("assistance")
        if assistance in ASSISTANCE_LEVELS:
            entry[assistance] += 1
        # Distributions, never an average. A mean over an ordinal scale
        # would invent a precision the scale doesn't carry and would read
        # as a grade for the child rather than a picture of their work.
        scored_here = False
        for dimension, levels in (
            ("quality", WORK_QUALITY_LEVELS),
            ("distinction", WORK_DISTINCTION_LEVELS),
            ("speed", WORK_SPEED_LEVELS),
        ):
            value = detail.get(dimension)
            if value in levels:
                entry[dimension][value] += 1
                scored_here = True
        if scored_here:
            entry["scored"] += 1
        stamp = row.completed_at.replace(microsecond=0).isoformat()
        if entry["last_worked"] is None or stamp > entry["last_worked"]:
            entry["last_worked"] = stamp

    skills = sorted(by_skill.values(), key=lambda e: (-e["completed"], e["label"]))
    return {
        "student_name": student_name,
        "since_days": since_days,
        "total": sum(e["completed"] for e in skills),
        "skills": skills,
    }


def initiative_signal(summary: dict) -> dict:
    """
    Where a student's WORK shows the entrepreneurial pattern: done well,
    taken further than it was set, and done efficiently.

    WHAT THIS IS AND ISN'T. It reports three counts over completed work —
    how often it was exemplary, how often it went beyond the task as set,
    and how often it moved briskly. It does NOT rate the child as
    entrepreneurial, assign them a type, or produce a single number
    standing for their character. A learning entrepreneur is not a category
    Bede is competent to place a child in; initiative shown in a term's
    work is something a parent can see for themselves once the work is
    counted, and then decide what it means.

    `beyond_the_task` is the load-bearing one. Correctness alone cannot
    distinguish a student who answered the question from one who answered
    it and then asked a better one, and it is the second that a parent
    looking for initiative actually wants to find. That is exactly why
    `distinction` had to be its own dimension rather than folded into
    quality.

    Deliberately no threshold, badge, or "is/isn't" verdict. Counts and the
    skills they occurred in, so the parent reads the evidence rather than
    a label Bede assigned.
    """
    exemplary = beyond = brisk = 0
    standout_skills: list[dict] = []
    for entry in summary.get("skills", []):
        e = entry["quality"].get("exemplary", 0)
        b = entry["distinction"].get("noteworthy", 0) + entry["distinction"].get("original", 0)
        k = entry["speed"].get("brisk", 0)
        exemplary += e
        beyond += b
        brisk += k
        if e or b:
            standout_skills.append({
                "skill_id": entry["skill_id"],
                "label": entry["label"],
                "exemplary": e,
                "beyond_the_task": b,
            })

    standout_skills.sort(key=lambda s: (-(s["beyond_the_task"] + s["exemplary"]), s["label"]))
    return {
        "student_name": summary.get("student_name"),
        "scored_activities": sum(e["scored"] for e in summary.get("skills", [])),
        "exemplary": exemplary,
        "beyond_the_task": beyond,
        "brisk": brisk,
        "standout_skills": standout_skills[:5],
    }


async def pod_activity(
    db,
    student_names: list[str],
    since_days: int = 90,
    subject_area: Optional[str] = None,
) -> dict:
    """
    The same ledger across a parent's own students, so a self-managed team
    can be arranged around demonstrated work.

    WHAT THIS RETURNS AND WHAT IT REFUSES TO. Per skill, it names the
    students who have COMPLETED work in it and how many times — a factual
    roster of who has done what. It does not rank students, score them
    against each other, compute who is "ahead", or emit any per-student
    aggregate at all. There is deliberately no ordering of students and no
    total per student in the output, because either would read as a
    leaderboard the moment it reached a screen.

    A parent uses this the way any team lead uses a record of completed
    work: to see that one of their children has done a piece of work
    another hasn't yet, and to ask the first to show the second. That is
    peer teaching grounded in evidence of activity, which is what was
    asked for — not in a measured trait, which is what was ruled out.
    """
    per_student = {}
    for name in student_names:
        per_student[name] = await summarize(db, name, since_days, subject_area)

    by_skill: dict[str, dict] = {}
    for name, summary in per_student.items():
        for entry in summary["skills"]:
            skill = by_skill.setdefault(entry["skill_id"], {
                "skill_id": entry["skill_id"],
                "label": entry["label"],
                "subject_area": entry["subject_area"],
                "worked_by": [],
            })
            skill["worked_by"].append({
                "student_name": name,
                "completed": entry["completed"],
                "unaided": entry["unaided"],
                "last_worked": entry["last_worked"],
            })

    # Sorted by skill label — NOT by any measure of the students. The output
    # has no student ordering at all, by design.
    skills = sorted(by_skill.values(), key=lambda s: s["label"])
    for skill in skills:
        skill["worked_by"].sort(key=lambda w: w["student_name"])

    return {"since_days": since_days, "skills": skills}
