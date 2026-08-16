"""
Which scheduled subjects are actually getting taught.

The whole value is in one distinction — a subject that was never scheduled
versus one scheduled for six weeks and opened twice — and the whole risk is
in the second one quietly becoming a verdict about the child. These pin both
halves.
"""

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from core.config import settings
from core.database import Base, LessonBookmark
from models.schemas import Subject
from services.subject_coverage import (
    STALE_AFTER_DAYS, coverage_for_student, to_payload,
)


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        from core.encryption import initialize_encryption
        await initialize_encryption(settings.master_secret, session)
        yield session
    await engine.dispose()


async def _taught(db, student: str, subject: Subject, days_ago: int):
    db.add(LessonBookmark(
        student_name=student,
        subject=subject.value,
        bookmark_enc=b"x",
        updated_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
    ))
    await db.commit()


@pytest.mark.asyncio
async def test_the_distinction_this_exists_for(db_session):
    """
    Scheduled and taught recently, scheduled and long untaught, scheduled and
    never taught. Before this, all three looked identical to a parent: a
    subject with nothing to show for it.
    """
    await _taught(db_session, "Wren", Subject.mathematics, days_ago=1)
    await _taught(db_session, "Wren", Subject.history, days_ago=40)

    coverage = await coverage_for_student(
        db_session, "Wren", [Subject.mathematics, Subject.history, Subject.science],
    )
    by_subject = {c.subject: c for c in coverage}

    assert by_subject[Subject.mathematics].needs_attention is False
    assert by_subject[Subject.mathematics].days_since == 1

    assert by_subject[Subject.history].needs_attention is True
    assert by_subject[Subject.history].days_since == 40

    # Never taught at all is its OWN state, not "0 days ago" and not a
    # missing row — a parent has to be able to tell "we have not started
    # this" from "we have let it slide".
    assert by_subject[Subject.science].last_taught is None
    assert by_subject[Subject.science].days_since is None
    assert by_subject[Subject.science].needs_attention is True


@pytest.mark.asyncio
async def test_only_scheduled_subjects_are_reported(db_session):
    """A subject the parent has dropped is not a gap in their plan."""
    await _taught(db_session, "Wren", Subject.latin, days_ago=90)
    coverage = await coverage_for_student(db_session, "Wren", [Subject.mathematics])
    assert [c.subject for c in coverage] == [Subject.mathematics]


@pytest.mark.asyncio
async def test_nothing_scheduled_reports_nothing(db_session):
    assert await coverage_for_student(db_session, "Wren", []) == []


@pytest.mark.asyncio
async def test_ordering_is_derived_from_the_schedule_never_the_child(db_session):
    """Never-taught first, then longest-untaught. Nothing here can be
    reordered by how well the child did — there is no such input."""
    await _taught(db_session, "Wren", Subject.mathematics, days_ago=2)
    await _taught(db_session, "Wren", Subject.history, days_ago=30)
    coverage = await coverage_for_student(
        db_session, "Wren", [Subject.mathematics, Subject.history, Subject.science],
    )
    assert [c.subject for c in coverage] == [
        Subject.science, Subject.history, Subject.mathematics,
    ]


@pytest.mark.asyncio
async def test_it_emits_no_measure_of_the_child(db_session):
    """
    The line. This reports a schedule; it must never acquire a field that
    reads as a judgment of the person — no engagement score, no interest
    rating, no "avoiding". If one of these names ever becomes useful, it
    belongs somewhere else, under its own review.
    """
    await _taught(db_session, "Wren", Subject.history, days_ago=40)
    payload = to_payload(await coverage_for_student(db_session, "Wren", [Subject.history]))

    forbidden = {
        "engagement", "interest", "motivation", "effort", "attitude",
        "avoidance", "avoiding", "disengaged", "score", "rating", "level",
    }
    # Scanned against everything EXCEPT the explanatory note, which uses
    # several of these words precisely to deny measuring them — the same
    # substring trap that would fail a well-written refusal for containing
    # the word it refuses.
    body = {k: v for k, v in payload.items() if k != "note"}
    serialized = repr(body).lower()
    for word in forbidden:
        assert word not in serialized, f"{word!r} reached the payload"
    for key in payload["subjects"][0]:
        assert not any(word in key.lower() for word in forbidden), key


@pytest.mark.asyncio
async def test_the_payload_states_its_own_refusal(db_session):
    """
    A consuming model can reintroduce a judgment the data doesn't contain
    just by summarizing it — exactly as the pod roster can be turned into a
    ranking by summing. So the refusal travels with the data, the same way
    scripts/mcp_server/ writes its refusals into the tool descriptions a
    model actually reads.
    """
    payload = to_payload(await coverage_for_student(db_session, "Wren", [Subject.history]))
    note = payload["note"].lower()
    assert "not a measure of interest, engagement, or effort" in note
    assert "says nothing about the child" in note
    assert payload["stale_after_days"] == STALE_AFTER_DAYS


def test_the_staleness_threshold_is_the_one_the_rest_of_the_app_uses():
    """Same 14 days _bookmark_note fades at and lesson_planner calls stale.
    One number for "long enough to notice", not three that drift apart."""
    from services.lesson_planner import STALE_AFTER_DAYS as PLANNER_STALE

    assert STALE_AFTER_DAYS == PLANNER_STALE == 14
