"""services/lesson_planner.py — what Bede may and may not decide about a day.

The interesting tests here are the refusals. An ordering algorithm is easy;
the hard part is that several natural-looking improvements to one would each
break something the constitution actually says, and none of them would fail
loudly.
"""
import itertools

import pytest

from models.schemas import GradeStage, Subject
from services.lesson_planner import (
    STALE_AFTER_DAYS,
    PlanningSignals,
    plan_session,
    stale_subjects_from_bookmarks,
)

ALL_SUBJECTS = list(Subject)


def order_for(subjects, **kwargs):
    return plan_session(PlanningSignals(subjects=subjects, **kwargs)).order


# ── The guarantee: order, never membership ──────────────────────────────


@pytest.mark.parametrize(
    "subjects",
    [
        ALL_SUBJECTS,
        [Subject.mathematics],
        [],
        [Subject.free_study, Subject.morning_time],
        [Subject.history, Subject.science, Subject.art_music],
    ],
)
def test_plan_is_always_a_permutation_of_the_parents_subjects(subjects):
    """The constitution's authority_order: the parent is the child's primary
    educator. Bede orders the day; it does not decide what is in it."""
    assert sorted(order_for(subjects), key=lambda s: s.value) == sorted(
        subjects, key=lambda s: s.value
    )


def test_no_subject_is_ever_added():
    plan = order_for([Subject.mathematics, Subject.history])
    assert set(plan) == {Subject.mathematics, Subject.history}


def test_duplicates_are_preserved_not_collapsed():
    """Permuting what we were given is the contract. Silently dropping an
    entry would break the guarantee that makes this safe."""
    subjects = [Subject.mathematics, Subject.mathematics, Subject.history]
    assert len(order_for(subjects)) == 3


def test_an_empty_day_plans_to_nothing():
    assert order_for([]) == []


# ── The faith rule ──────────────────────────────────────────────────────


@pytest.mark.parametrize("faith_subject", [Subject.scripture, Subject.saints])
def test_faith_subjects_never_move_on_evidence(faith_subject):
    """Bede must never measure or quantify a child's spiritual engagement.
    "Scripture keeps landing first because the signals say this child is
    behind in it" is exactly such a measurement, expressed as an ordering
    rather than a number.

    So the evidence signals that legitimately move every other subject must
    have no effect here: the same list, planned with and without every signal
    pointing at the faith subject, must come out identically.
    """
    subjects = [Subject.history, faith_subject, Subject.science]

    without = order_for(subjects)
    with_signals = order_for(
        subjects,
        resume_subjects={faith_subject},
        stale_subjects={faith_subject},
    )
    assert without == with_signals


def test_a_faith_subject_keeps_its_parent_given_position_among_ordinary_ones():
    """Not merely "unmoved by signals" — it holds the slot the parent put it
    in, relative to the other subjects Bede has no reason to move."""
    subjects = [Subject.history, Subject.saints, Subject.science]
    assert order_for(subjects) == subjects


def test_morning_time_opens_the_day():
    """The one convention allowed to touch a faith subject's position, and
    only because opening the day is fixed rather than a response to anything
    about the child."""
    subjects = [Subject.science, Subject.mathematics, Subject.morning_time]
    assert order_for(subjects)[0] == Subject.morning_time


def test_latin_and_greek_are_not_treated_as_faith_subjects():
    """They draw on Christian texts but are language subjects. Ordering them
    by how recently they came up says nothing about a child's spiritual
    life — so they are allowed to move like any other subject."""
    subjects = [Subject.history, Subject.latin]
    # latin is demanding, so it should move ahead of ordinary history.
    assert order_for(subjects)[0] == Subject.latin


# ── What actually drives the order ──────────────────────────────────────


def test_a_parents_resume_note_wins_over_bedes_own_reasons():
    """An explicit parent instruction outranks any convention of Bede's."""
    subjects = [Subject.mathematics, Subject.history]
    planned = order_for(subjects, resume_subjects={Subject.history})
    assert planned[0] == Subject.history


def test_demanding_subjects_come_before_ordinary_ones():
    subjects = [Subject.art_music, Subject.mathematics]
    assert order_for(subjects)[0] == Subject.mathematics


def test_a_stale_subject_outranks_an_ordinary_one():
    subjects = [Subject.art_music, Subject.history]
    planned = order_for(subjects, stale_subjects={Subject.history})
    assert planned[0] == Subject.history


def test_free_study_closes_the_day():
    subjects = [Subject.free_study, Subject.history, Subject.mathematics]
    assert order_for(subjects)[-1] == Subject.free_study


def test_ordering_is_stable_within_a_band():
    """Predictable day to day, and a parent who rearranges their list sees
    that respected wherever Bede has no reason to do otherwise."""
    subjects = [Subject.science, Subject.history, Subject.art_music]
    assert order_for(subjects) == subjects


def test_the_same_signals_always_produce_the_same_plan():
    subjects = [Subject.mathematics, Subject.history, Subject.morning_time]
    signals = dict(resume_subjects={Subject.history}, stale_subjects={Subject.science})
    assert order_for(subjects, **signals) == order_for(subjects, **signals)


@pytest.mark.parametrize("permutation", list(itertools.permutations(
    [Subject.mathematics, Subject.history, Subject.morning_time]
)))
def test_morning_time_leads_whatever_order_the_parent_typed(permutation):
    assert order_for(list(permutation))[0] == Subject.morning_time


# ── The reasons ─────────────────────────────────────────────────────────


def test_every_planned_subject_carries_a_reason():
    plan = plan_session(PlanningSignals(subjects=ALL_SUBJECTS))
    assert all(entry.reason.strip() for entry in plan.subjects)


def test_no_reason_is_a_judgment_about_the_child():
    """Every reason must be a fact about the plan or about ordinary pedagogy.
    None may say a child is behind, weak, slow, or struggling — the same
    distinction the mastery cycle draws when it reports missing evidence as a
    finding about the schedule rather than about the learner."""
    plan = plan_session(
        PlanningSignals(
            subjects=ALL_SUBJECTS,
            resume_subjects={Subject.history},
            stale_subjects={Subject.science},
        )
    )
    forbidden = (
        "behind", "weak", "struggl", "poor", "slow", "fail", "gap in",
        "catch up", "remedial", "低", "needs work", "falling",
    )
    for entry in plan.subjects:
        lowered = entry.reason.lower()
        for word in forbidden:
            assert word not in lowered, f"{entry.subject}: {entry.reason!r}"


def test_no_reason_mentions_hurrying():
    """Ordering changes what comes first, never how long anything takes."""
    plan = plan_session(PlanningSignals(subjects=ALL_SUBJECTS))
    for entry in plan.subjects:
        lowered = entry.reason.lower()
        assert "hurry" not in lowered
        assert "quickly" not in lowered
        assert "faster" not in lowered


# ── Staleness is a fact about the schedule ──────────────────────────────


def test_a_subject_with_no_bookmark_counts_as_stale():
    """Never covered, or covered before bookmarks existed — either way
    'schedule it before it drifts further' is the right read."""
    stale = stale_subjects_from_bookmarks({Subject.history: None})
    assert stale == {Subject.history}


def test_a_recent_bookmark_is_not_stale():
    stale = stale_subjects_from_bookmarks({Subject.history: 1.0})
    assert stale == set()


def test_staleness_uses_the_same_threshold_as_the_bookmark_note():
    """_bookmark_note phrases anything past 14 days as 'a while back'. Two
    different thresholds for the same idea would be a quiet inconsistency."""
    assert STALE_AFTER_DAYS == 14
    assert stale_subjects_from_bookmarks({Subject.history: 14.0}) == {Subject.history}
    assert stale_subjects_from_bookmarks({Subject.history: 13.9}) == set()


# ── Durations are untouched ─────────────────────────────────────────────


def test_the_planner_does_not_change_any_duration():
    """It orders. It never shortens, lengthens, or drops a block — the
    'never hurry a child' rule applied to scheduling."""
    from models.schemas import SUBJECT_DURATIONS

    before = dict(SUBJECT_DURATIONS)
    plan_session(PlanningSignals(subjects=ALL_SUBJECTS, grade_stage=GradeStage.independent))
    assert SUBJECT_DURATIONS == before


def test_a_faith_subject_is_not_demoted_either():
    """The failure the first version of the planner actually had, and the
    reason "never moved by evidence" has to mean both directions.

    Scripture was never promoted — but when every ordinary subject around it
    went stale, they all rose past it and Scripture slid to the end of the
    day. Bede had scored nothing about the child's spiritual life, and the
    timetable said something about it regardless.
    """
    subjects = [Subject.history, Subject.scripture, Subject.science]
    planned = order_for(
        subjects,
        # Everything EXCEPT the faith subject has a reason to move.
        stale_subjects={Subject.history, Subject.science},
    )
    assert planned == subjects


def test_a_faith_subject_holds_position_however_the_others_are_ranked():
    """Whatever the other subjects do — resume notes, staleness, demanding
    or not — the faith subject stays in the slot the parent gave it."""
    subjects = [Subject.history, Subject.saints, Subject.mathematics]
    for signals in (
        {},
        {"stale_subjects": {Subject.history}},
        {"resume_subjects": {Subject.mathematics}},
        {"stale_subjects": {Subject.history, Subject.mathematics}},
        {"resume_subjects": {Subject.history}, "stale_subjects": {Subject.mathematics}},
    ):
        assert order_for(subjects, **signals)[1] == Subject.saints, signals
