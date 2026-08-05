"""Ordering the day — the one planning decision Bede is competent to make.

Until this module, Bede had no planner at all. The "plan" was the parent's
subject list plus fixed `SUBJECT_DURATIONS`, and Bede's only sequencing
authority was `suggest_next_subject` (move on from this one, now). Mastery
data existed and shaped questions *within* mathematics
(`get_next_probe_hint`), but nothing ever looked across the day.

## What this may decide, and what it may not

**It orders. It never chooses.** `plan_session` returns a permutation of the
subjects the parent selected — never a subject added, never one dropped, never
one shortened. That is not a conservative implementation choice, it is the
constitution's `authority_order`: the parent is the child's primary educator,
and Bede's own non-negotiable rule is to form the learner rather than replace
the parent's judgment. A planner that decided your child should skip Latin
today would be making a curriculum decision that is not Bede's to make.
`test_plan_is_always_a_permutation_of_the_parents_subjects` pins this against
generated inputs rather than a few examples.

**Faith-formation subjects are never moved by evidence.** `morning_time`,
`scripture`, and `saints` hold the position the parent gave them, and the only
thing that may touch them is the Mater Amabilis convention that Morning Time
opens the day. This is the constitution's faith rule reached by a route that
is easy to miss: Bede must never measure or quantify a child's spiritual
engagement, and "Scripture keeps getting scheduled first because the signals
say this child is behind in it" is exactly such a measurement, just expressed
as an ordering instead of a number. The rule had to be written into the
priority function explicitly, because every other subject legitimately moves
on evidence and faith would otherwise have been swept along with them.
See `_FAITH_FORMATION` and `test_faith_subjects_never_move_on_evidence`.

**Nothing here is a judgment about the child.** Every reason this planner can
give is a fact about the *plan* or about ordinary pedagogy — "you asked Bede
to pick this up", "demanding subjects go while attention is freshest", "this
hasn't come up in a while". None of them says a child is behind, weak, or
slow. That mirrors the mastery cycle's own `no_evidence` decision: a gap in
evidence is a finding about the schedule, not about the learner.

**Nothing here hurries anyone.** Ordering changes what comes first, never how
long anything takes. `SUBJECT_DURATIONS` is untouched, and no reason string
mentions speed or falling behind — the same standing rule
`_WORK_SCORING_NOTE` states for scoring.

**A child never sees this.** Like the work ledger, the plan and its reasons
are parent-facing only. A child shown "Bede put maths first because you
haven't done it in a while" has been told something about themselves that
Bede has no standing to say.

## Why a pure function

No I/O, following `services/policy_engine.py`'s precedent. Signals are
gathered by the caller and passed in, so every rule here is testable without a
database, and the ordering can be explained to a parent without running a
session.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Sequence, Set

from models.schemas import GradeStage, Subject

#: Faith-formation subjects. Their order is the parent's alone — see this
#: module's docstring. `latin`/`greek` are deliberately NOT here: they are
#: language subjects that happen to draw on Christian texts, and ordering them
#: by how recently they came up says nothing about a child's spiritual life.
_FAITH_FORMATION = frozenset({
    Subject.morning_time,
    Subject.scripture,
    Subject.saints,
})

#: Subjects that ask the most sustained attention, and so belong earlier in the
#: day while it is freshest. An ordinary pedagogical convention — it is a claim
#: about mornings, not about any child.
_DEMANDING = frozenset({
    Subject.mathematics,
    Subject.logic,
    Subject.latin,
    Subject.greek,
    Subject.language_arts,
})

#: A bookmark older than this reads as "a while back" rather than "last time"
#: (matching `_bookmark_note`'s own 14-day phrasing in ai_service.py).
STALE_AFTER_DAYS = 14

# Priority bands. Lower sorts earlier. Gaps are deliberate so a band can be
# inserted later without renumbering, and every band below is a fact about the
# plan or about pedagogy — never about the child.
_BAND_MORNING_TIME = 0     # the day's opening, by Mater Amabilis convention
_BAND_PARENT_RESUME = 10   # the parent wrote "pick this up here"
_BAND_DEMANDING = 20       # sustained attention, while the day is freshest
_BAND_STALE = 30           # hasn't come up in a while
_BAND_ORDINARY = 40
_BAND_FREE_STUDY = 90      # child-directed exploration closes the day


@dataclass(frozen=True)
class PlanningSignals:
    """Everything `plan_session` is allowed to look at.

    Deliberately small. A planner that could see mastery probabilities
    per subject would be one step from ordering a child's day by how badly
    they are doing in each part of it, which is a judgment rendered as a
    timetable. What it sees instead are facts about the plan: what the parent
    asked to resume, and what has not come up lately.
    """

    #: The parent's own subject list, in the parent's own order. The output is
    #: always a permutation of this.
    subjects: Sequence[Subject]
    grade_stage: GradeStage = GradeStage.core_mastery
    #: Subjects the parent wrote a `lesson_resume` note for — an explicit
    #: instruction, not an inference.
    resume_subjects: Set[Subject] = field(default_factory=set)
    #: Subjects whose last bookmark is older than STALE_AFTER_DAYS, or which
    #: have none at all.
    stale_subjects: Set[Subject] = field(default_factory=set)


@dataclass(frozen=True)
class PlannedSubject:
    subject: Subject
    #: Plain-language, parent-facing, and never about the child. Shown in the
    #: parent UI so the ordering is explained rather than imposed.
    reason: str


@dataclass(frozen=True)
class SessionPlan:
    subjects: List[PlannedSubject]

    @property
    def order(self) -> List[Subject]:
        return [entry.subject for entry in self.subjects]


_REASONS: Dict[int, str] = {
    _BAND_MORNING_TIME: "Morning Time opens the day.",
    _BAND_PARENT_RESUME: "You left a note to pick this one up where it stopped.",
    _BAND_DEMANDING: "This one asks for sustained attention, so it sits earlier while the day is fresh.",
    _BAND_STALE: "This hasn't come up in a while — worth scheduling before it drifts further.",
    _BAND_ORDINARY: "Kept in the order you chose.",
    _BAND_FREE_STUDY: "Child-directed exploration, so it closes the day.",
}


def _band(subject: Subject, signals: PlanningSignals) -> int:
    """Which priority band this subject falls into.

    Faith-formation subjects short-circuit before any evidence-driven band is
    considered — see this module's docstring. Morning Time is the one
    exception, and only because opening the day is a fixed convention rather
    than a response to anything about the child.
    """
    if subject == Subject.morning_time:
        return _BAND_MORNING_TIME
    if subject in _FAITH_FORMATION:
        return _BAND_ORDINARY
    if subject == Subject.free_study:
        return _BAND_FREE_STUDY
    if subject in signals.resume_subjects:
        return _BAND_PARENT_RESUME
    if subject in _DEMANDING:
        return _BAND_DEMANDING
    if subject in signals.stale_subjects:
        return _BAND_STALE
    return _BAND_ORDINARY


def _place_anchor(preferred: int, free: List[int]) -> int:
    """The slot an anchored subject actually gets.

    Its own original index when that is still free; otherwise the nearest
    free slot, preferring to stay later rather than jump earlier — moving a
    faith subject *forward* is the direction that would read as Bede pushing
    it, which is exactly what must not happen.
    """
    if preferred in free:
        return preferred
    later = [slot for slot in free if slot > preferred]
    if later:
        return later[0]
    return free[-1]


def plan_session(signals: PlanningSignals) -> SessionPlan:
    """Order the parent's own subjects, with a reason for each.

    Three passes, in this order:

    1. **Morning Time opens the day.** A fixed Mater Amabilis convention, and
       the only thing permitted to move a faith-formation subject.
    2. **Faith-formation subjects are anchored to the position the parent gave
       them.** Anchored, not merely "unaffected by their own signals" — the
       first version of this function only skipped promoting them, and a
       Scripture block still slid to the END of a day whenever the ordinary
       subjects around it happened to go stale. Bede had not scored the
       child's spiritual life, but the timetable said something about it all
       the same, which is the thing the rule exists to prevent. Position is
       held against movement in either direction.
    3. **Everything else fills the remaining slots** in band order, with the
       parent's own order as the tiebreak — so the plan is predictable day to
       day and a parent who rearranges their list sees that respected
       wherever Bede has no reason to do otherwise.

    Duplicates in the input are preserved rather than collapsed: this
    function's contract is to permute what it was given, and silently dropping
    an entry would break the guarantee that makes it safe.
    """
    indexed = list(enumerate(signals.subjects))
    total = len(indexed)
    placed: Dict[int, tuple[Subject, int]] = {}

    openers = [pair for pair in indexed if pair[1] == Subject.morning_time]
    anchors = [
        pair for pair in indexed
        if pair[1] in _FAITH_FORMATION and pair[1] != Subject.morning_time
    ]
    movable = [
        pair for pair in indexed
        if pair[1] != Subject.morning_time and pair[1] not in _FAITH_FORMATION
    ]

    free = list(range(total))
    for offset, (_, subject) in enumerate(openers):
        placed[offset] = (subject, _BAND_MORNING_TIME)
        free.remove(offset)

    for original_index, subject in anchors:
        slot = _place_anchor(original_index, free)
        placed[slot] = (subject, _BAND_ORDINARY)
        free.remove(slot)

    movable.sort(key=lambda pair: (_band(pair[1], signals), pair[0]))
    for slot, (_, subject) in zip(free, movable):
        placed[slot] = (subject, _band(subject, signals))

    return SessionPlan(
        subjects=[
            PlannedSubject(subject=subject, reason=_REASONS[band])
            for subject, band in (placed[slot] for slot in sorted(placed))
        ]
    )


def stale_subjects_from_bookmarks(
    bookmark_ages_in_days: Dict[Subject, float | None],
    *,
    stale_after_days: int = STALE_AFTER_DAYS,
) -> Set[Subject]:
    """Which subjects count as not-recently-touched.

    A subject with no bookmark at all counts as stale: it has either never
    been covered or was covered before bookmarks existed, and in both cases
    "schedule it before it drifts further" is the right read. This is a
    statement about the schedule — the same thing the mastery cycle's
    `no_evidence` outcome reports about the plan rather than the child.
    """
    stale: Set[Subject] = set()
    for subject, age in bookmark_ages_in_days.items():
        if age is None or age >= stale_after_days:
            stale.add(subject)
    return stale
