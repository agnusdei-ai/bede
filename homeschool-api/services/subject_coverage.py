"""
Which scheduled subjects are actually getting taught — a fact about the
PLAN, never a verdict about the child.

THE QUESTION THIS ANSWERS, AND THE ONE IT REFUSES TO. A parent looking at a
term can see that History has produced almost nothing, and cannot tell which
of two completely different situations they are in:

  1. History has not been on the plan. Nothing is wrong; it simply hasn't
     come up, and the fix is scheduling.
  2. History has been on the plan for six weeks and has been opened twice.
     Something about that subject, or that hour, or that book, is not
     working — and the fix is a conversation, not a calendar.

Those demand opposite responses and nothing in this codebase could tell them
apart. Both halves of the answer already existed separately: StudentConfig
says what the parent scheduled, and LessonBookmark's `updated_at` says when
a subject was last actually taught (it is written at the end of every session
for each subject genuinely covered). Nobody had ever compared them.

WHAT THIS IS NOT, AND THE LINE IS NOT SUBTLE. This does not score
engagement, rate interest, or say a child is avoiding anything. "Emma is
disengaged from History" is a claim about a person, made from a count, and
Bede has no standing to make it — it could as easily be the hour it is
scheduled, the book, a hard month, or a subject taught in a way that isn't
landing. What this module emits is what happened: scheduled, and last taught
on this date. The parent supplies the meaning.

That is the same discipline the mastery cycle already applies to its
`no_evidence` outcome (utils/masteryCycle.ts), and the same one
lesson_planner.py applies when it reports a reason about the plan rather
than about the child. This is the third instance of one rule, not a new one.

PARENT-FACING ONLY, like every other view built on the ledger. A child shown
"you have not done History in three weeks" has been handed a reproach.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence

from models.schemas import SUBJECT_LABELS, Subject

log = logging.getLogger(__name__)

# How long a scheduled subject may go untaught before it is worth telling the
# parent about. Deliberately the same 14 days _bookmark_note uses to switch
# from "last time" to "a while back", and that lesson_planner.py uses to call
# a subject stale — one number for "long enough to notice", not three that
# could drift apart.
STALE_AFTER_DAYS = 14


@dataclass(frozen=True)
class SubjectCoverage:
    """One scheduled subject, and when it was last actually taught."""

    subject: Subject
    label: str
    #: None when this subject has never been taught at all.
    last_taught: Optional[str]
    days_since: Optional[int]
    #: Scheduled, and not taught within STALE_AFTER_DAYS. The only thing this
    #: module asserts, and it asserts it about the schedule.
    needs_attention: bool


async def coverage_for_student(
    db,
    student_name: str,
    scheduled: Sequence[Subject],
) -> list[SubjectCoverage]:
    """
    For each subject the parent has scheduled, when it was last taught.

    Ordered by longest-untaught first, because that is the order a parent
    would act in — never by any measure of the child.

    Best-effort like every other read in this package: a failure returns an
    empty list rather than raising into a page render.
    """
    from sqlalchemy import select

    from core.database import LessonBookmark

    if not scheduled:
        return []

    try:
        rows = (await db.execute(
            select(LessonBookmark.subject, LessonBookmark.updated_at)
            .where(LessonBookmark.student_name == student_name)
        )).all()
    except Exception as exc:
        log.warning("Subject-coverage read failed for %s: %s", student_name, exc)
        return []

    last_by_subject = {subject: updated_at for subject, updated_at in rows}
    now = datetime.now(timezone.utc)
    cutoff = timedelta(days=STALE_AFTER_DAYS)

    out: list[SubjectCoverage] = []
    for subject in scheduled:
        stamp = last_by_subject.get(subject.value)
        if stamp is None:
            out.append(SubjectCoverage(
                subject=subject,
                label=SUBJECT_LABELS.get(subject, subject.value),
                last_taught=None,
                days_since=None,
                needs_attention=True,
            ))
            continue
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        elapsed = now - stamp
        out.append(SubjectCoverage(
            subject=subject,
            label=SUBJECT_LABELS.get(subject, subject.value),
            last_taught=stamp.replace(microsecond=0).isoformat(),
            days_since=max(0, elapsed.days),
            needs_attention=elapsed >= cutoff,
        ))

    # Never taught first, then longest-untaught. A stable, purely
    # schedule-derived order — nothing here can be reordered by anything the
    # child did or didn't do well.
    out.sort(key=lambda c: (c.days_since is not None, -(c.days_since or 0), c.label))
    return out


def to_payload(coverage: Sequence[SubjectCoverage]) -> dict:
    """
    The API shape. Carries the threshold it used, so the client never has to
    hardcode a second copy of it, and states the refusal in the payload
    itself — a consuming model that reads this (see scripts/mcp_server/)
    can reintroduce a judgment the data doesn't contain just by summarizing
    it, exactly as the pod roster can be turned into a ranking by summing.
    """
    return {
        "stale_after_days": STALE_AFTER_DAYS,
        "subjects": [
            {
                "subject": c.subject.value,
                "label": c.label,
                "last_taught": c.last_taught,
                "days_since": c.days_since,
                "needs_attention": c.needs_attention,
            }
            for c in coverage
        ],
        "note": (
            "This reports what has been scheduled and when it was last taught. "
            "It is not a measure of interest, engagement, or effort, and says "
            "nothing about the child — a subject can go untaught because of the "
            "hour, the book, a hard month, or simply a busy fortnight."
        ),
    }
