"""Synthetic SQLite qualification for curriculum staging and human promotion."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from core import encryption
from core.database import Base, ClassicalEducator, PilotCampus, PilotEducatorCampus
from models.schemas import Subject
from services.content_curation import ContentCandidate
from services.curriculum.models import ReviewDecision, RightsStatus, SourceRecord, Visibility
from services.curriculum.persistence import (
    create_curriculum_tables, lessons, reviewer_grants, reviews, sources,
)
from services.curriculum.rights_gate import StagingSubmission
from services.curriculum.workflow import (
    CurriculumWorkflowDenied, review_staged_lesson, stage_lesson,
)

NOW = datetime(2026, 10, 24, tzinfo=timezone.utc)


def token(principal: str, **changes):
    base = dict(role="educator", sub=principal, ev=1, auth_method="webauthn_uv")
    base.update(changes)
    return base


def submission(campus="campus-a", lesson="lesson-1", *, generated=False):
    return StagingSubmission(
        campus_id=campus,
        candidate=ContentCandidate(
            id=lesson, title="History note", subject=Subject.history,
            source="source-1", public_domain=True,
            verbatim_text="A brief public-domain excerpt",
            exercises_no_tracked_skill=True,
        ),
        source=SourceRecord(
            "source-1", "Verified 1880 edition", "https://example.org/edition",
            NOW, "a" * 64, RightsStatus.public_domain_verified,
        ),
        rights_verified_by="Rights staff assertion",
        rights_evidence_ref="rights:independent-document-1",
    )


async def setup(monkeypatch):
    monkeypatch.setenv("CURRICULUM_ENGINE_ENABLED", "true")
    monkeypatch.setattr(encryption, "_DATA_KEY", b"q" * 32)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    assert await create_curriculum_tables(engine)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    author, reviewer, outsider = (str(uuid4()) for _ in range(3))
    async with Session() as db:
        for ident, username in ((author, "author"), (reviewer, "reviewer"), (outsider, "outsider")):
            db.add(ClassicalEducator(
                id=ident, username=username, password_hash=b"synthetic",
                password_salt=b"synthetic", totp_enc=b"synthetic",
                enabled=True, credential_version=1,
            ))
        db.add_all([
            PilotCampus(id="campus-a", title="Synthetic campus A", enabled=True),
            PilotCampus(id="campus-b", title="Synthetic campus B", enabled=True),
            PilotEducatorCampus(educator_id=author, campus_id="campus-a", enabled=True),
            PilotEducatorCampus(educator_id=reviewer, campus_id="campus-a", enabled=True),
            PilotEducatorCampus(educator_id=outsider, campus_id="campus-b", enabled=True),
        ])
        await db.execute(insert(reviewer_grants).values(
            campus_id="campus-a", educator_id=reviewer,
            granted_by="independent-admin", issued_at=NOW, enabled=True,
        ))
        await db.commit()
    return engine, Session, author, reviewer, outsider


@pytest.mark.asyncio
async def test_staging_and_independent_approval_create_two_versions(monkeypatch):
    engine, Session, author, reviewer, outsider = await setup(monkeypatch)
    try:
        async with Session() as db:
            version = await stage_lesson(db, token(author), submission(), generated=True)
            assert version == 1
            stage = (await db.execute(select(lessons))).mappings().one()
            assert stage["status"] == "staged" and stage["review_id"] is None
            assert stage["generated"] is True
            assert stage["body_enc"].startswith(b"SAGE")
            assert b"public-domain excerpt" not in stage["body_enc"]

            review_id, promoted_version = await review_staged_lesson(
                db, token(reviewer), "campus-a", "lesson-1",
                decision=ReviewDecision.approve, notes="Synthetic review only",
            )
            assert promoted_version == 2
            rows = (await db.execute(
                select(lessons).order_by(lessons.c.version)
            )).mappings().all()
            assert [(r["version"], r["status"]) for r in rows] == [
                (1, "retired"), (2, "approved")
            ]
            assert rows[1]["review_id"] == review_id
            audit = (await db.execute(select(reviews))).mappings().one()
            assert audit["reviewed_by"] == reviewer
            assert audit["item_version"] == 2
            assert audit["decision"] == "approve"
            assert audit["notes_enc"].startswith(b"SAGE")
            assert b"Synthetic review" not in audit["notes_enc"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_no_self_approval_even_if_reviewer_grant_or_generated(monkeypatch):
    engine, Session, author, reviewer, outsider = await setup(monkeypatch)
    try:
        async with Session() as db:
            await db.execute(insert(reviewer_grants).values(
                campus_id="campus-a", educator_id=author,
                granted_by="independent-admin", issued_at=NOW, enabled=True,
            ))
            await db.commit()
            await stage_lesson(db, token(author), submission(), generated=True)
            with pytest.raises(CurriculumWorkflowDenied):
                await review_staged_lesson(
                    db, token(author), "campus-a", "lesson-1",
                    decision=ReviewDecision.approve,
                )
            assert (await db.execute(select(reviews))).all() == []
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_review_requires_separate_authorized_active_campus_member(monkeypatch):
    engine, Session, author, reviewer, outsider = await setup(monkeypatch)
    try:
        async with Session() as db:
            await stage_lesson(db, token(author), submission())
            for invalid in (token(outsider), token(reviewer, ev=0),
                            token(reviewer, auth_method="password"),
                            token(reviewer, role="admin")):
                with pytest.raises(CurriculumWorkflowDenied):
                    await review_staged_lesson(
                        db, invalid, "campus-a", "lesson-1",
                        decision=ReviewDecision.approve,
                    )
            await db.execute(update(reviewer_grants).values(enabled=False))
            await db.commit()
            with pytest.raises(CurriculumWorkflowDenied):
                await review_staged_lesson(
                    db, token(reviewer), "campus-a", "lesson-1",
                    decision=ReviewDecision.approve,
                )
            assert (await db.execute(select(reviews))).all() == []
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_stage_requires_campus_membership_and_passkey(monkeypatch):
    engine, Session, author, reviewer, outsider = await setup(monkeypatch)
    try:
        async with Session() as db:
            for t in (token(outsider), token(author, ev=0),
                      token(author, auth_method="password"), token(author, role="admin")):
                with pytest.raises(CurriculumWorkflowDenied):
                    await stage_lesson(db, t, submission())
            assert (await db.execute(select(lessons))).all() == []
            assert (await db.execute(select(sources))).all() == []
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_reject_and_request_changes_are_auditable_without_promotion(monkeypatch):
    engine, Session, author, reviewer, outsider = await setup(monkeypatch)
    try:
        async with Session() as db:
            await stage_lesson(db, token(author), submission())
            review_id, new_version = await review_staged_lesson(
                db, token(reviewer), "campus-a", "lesson-1",
                decision=ReviewDecision.reject,
            )
            assert new_version is None
            await stage_lesson(db, token(author), submission())
            _, other = await review_staged_lesson(
                db, token(reviewer), "campus-a", "lesson-1",
                decision=ReviewDecision.request_changes,
            )
            assert other is None
            result = (await db.execute(select(lessons))).mappings().all()
            assert [r["status"] for r in result] == ["retired", "retired"]
            history = (await db.execute(select(reviews.c.decision))).scalars().all()
            assert history == ["reject", "request_changes"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_no_repeat_approval_or_parallel_pending_stage(monkeypatch):
    engine, Session, author, reviewer, outsider = await setup(monkeypatch)
    try:
        async with Session() as db:
            await stage_lesson(db, token(author), submission())
            with pytest.raises(CurriculumWorkflowDenied):
                await stage_lesson(db, token(author), submission())
            await review_staged_lesson(
                db, token(reviewer), "campus-a", "lesson-1",
                decision=ReviewDecision.approve,
            )
            with pytest.raises(CurriculumWorkflowDenied):
                await review_staged_lesson(
                    db, token(reviewer), "campus-a", "lesson-1",
                    decision=ReviewDecision.approve,
                )
            assert await stage_lesson(db, token(author), submission()) == 3
    finally:
        await engine.dispose()


@pytest.mark.parametrize("tampered", [
    {"content_hash": "tampered"},
    {"edition": "Unverified substituted edition"},
    {"retrieved_at": datetime(2025, 10, 24, tzinfo=timezone.utc)},
])
@pytest.mark.asyncio
async def test_source_tampering_denies_review_and_rolls_back(monkeypatch, tampered):
    engine, Session, author, reviewer, outsider = await setup(monkeypatch)
    try:
        async with Session() as db:
            await stage_lesson(db, token(author), submission())
            await db.execute(update(sources).values(**tampered))
            await db.commit()
            with pytest.raises(CurriculumWorkflowDenied):
                await review_staged_lesson(
                    db, token(reviewer), "campus-a", "lesson-1",
                    decision=ReviewDecision.approve,
                )
            assert (await db.execute(select(reviews))).all() == []
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_source_timestamp_with_offset_round_trips_without_false_tamper(monkeypatch):
    engine, Session, author, reviewer, outsider = await setup(monkeypatch)
    try:
        async with Session() as db:
            s = submission()
            offset_time = NOW.astimezone(timezone(timedelta(hours=-5)))
            s = replace(s, source=replace(s.source, retrieved_at=offset_time))
            await stage_lesson(db, token(author), s)
            review_id, version = await review_staged_lesson(
                db, token(reviewer), "campus-a", "lesson-1",
                decision=ReviewDecision.approve,
            )
            assert review_id and version == 2
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_existing_source_retrieval_metadata_cannot_be_silently_replaced(monkeypatch):
    engine, Session, author, reviewer, outsider = await setup(monkeypatch)
    try:
        async with Session() as db:
            await stage_lesson(db, token(author), submission())
            await review_staged_lesson(
                db, token(reviewer), "campus-a", "lesson-1",
                decision=ReviewDecision.reject,
            )
            next_submission = submission()
            next_submission = replace(
                next_submission,
                source=replace(next_submission.source,
                               retrieved_at=datetime(2025, 10, 24, tzinfo=timezone.utc)),
            )
            with pytest.raises(CurriculumWorkflowDenied):
                await stage_lesson(db, token(author), next_submission)
            assert len((await db.execute(select(lessons))).all()) == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_disabled_flag_blocks_all_writes(monkeypatch):
    engine, Session, author, reviewer, outsider = await setup(monkeypatch)
    try:
        monkeypatch.delenv("CURRICULUM_ENGINE_ENABLED", raising=False)
        async with Session() as db:
            with pytest.raises(CurriculumWorkflowDenied):
                await stage_lesson(db, token(author), submission())
            assert (await db.execute(select(lessons))).all() == []
    finally:
        await engine.dispose()


def test_no_curriculum_route_or_automatic_activation():
    root = Path(__file__).resolve().parents[1]
    main = (root / "main.py").read_text(encoding="utf-8")
    assert "services.curriculum.workflow" not in main
    assert "services.curriculum" not in main


@pytest.mark.asyncio
async def test_original_lesson_and_revision_each_require_independent_approval(monkeypatch):
    """PR 8: original writing is staged, reviewed, and versioned on revision."""
    engine, Session, author, reviewer, _ = await setup(monkeypatch)
    try:
        initial = submission(lesson="original-lesson")
        initial = replace(
            initial,
            candidate=replace(
                initial.candidate, source="original-source-1",
                public_domain=False, verbatim_text=None,
                body="An original, synthetic history explanation for review.",
            ),
            source=SourceRecord(
                "original-source-1", "Synthetic teacher-authored draft",
                "urn:bede:original:synthetic-lesson-1", NOW,
                "b" * 64, RightsStatus.original,
            ),
            rights_verified_by="Independent synthetic rights verifier",
            rights_evidence_ref="rights:synthetic-original-1",
        )
        async with Session() as db:
            assert await stage_lesson(db, token(author), initial) == 1
            first = (await db.execute(
                select(lessons).where(lessons.c.version == 1)
            )).mappings().one()
            assert first["status"] == "staged"
            assert first["rights_status"] == RightsStatus.original.value
            assert first["review_id"] is None
            assert first["body_enc"].startswith(b"SAGE")
            assert b"synthetic history" not in first["body_enc"]

            first_review, first_approved = await review_staged_lesson(
                db, token(reviewer), "campus-a", "original-lesson",
                decision=ReviewDecision.approve,
            )
            assert first_approved == 2 and first_review

            revision = replace(
                initial,
                candidate=replace(
                    initial.candidate, source="original-source-2",
                    body="A revised, original history explanation for review.",
                ),
                source=replace(
                    initial.source, source_id="original-source-2",
                    source_url="urn:bede:original:synthetic-lesson-2",
                    content_hash="c" * 64,
                ),
                rights_evidence_ref="rights:synthetic-original-2",
            )
            assert await stage_lesson(db, token(author), revision) == 3
            before_second_review = (await db.execute(
                select(lessons.c.version, lessons.c.status, lessons.c.review_id)
                .order_by(lessons.c.version)
            )).all()
            assert [(row.version, row.status) for row in before_second_review] == [
                (1, "retired"), (2, "approved"), (3, "staged"),
            ]
            assert before_second_review[-1].review_id is None

            second_review, second_approved = await review_staged_lesson(
                db, token(reviewer), "campus-a", "original-lesson",
                decision=ReviewDecision.approve,
            )
            assert second_approved == 4 and second_review != first_review
            rows = (await db.execute(
                select(lessons.c.version, lessons.c.status, lessons.c.review_id)
                .order_by(lessons.c.version)
            )).all()
            assert [(row.version, row.status) for row in rows] == [
                (1, "retired"), (2, "approved"),
                (3, "retired"), (4, "approved"),
            ]
            assert rows[1].review_id == first_review
            assert rows[3].review_id == second_review
            assert (await db.execute(select(reviews.c.review_id))).scalars().all() == [
                first_review, second_review,
            ]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_original_rights_do_not_allow_verbatim_source_text(monkeypatch):
    """PR 8: original rights cannot be used to bypass the verbatim rights gate."""
    engine, Session, author, _, _ = await setup(monkeypatch)
    try:
        original = submission(lesson="original-with-verbatim")
        original = replace(
            original,
            candidate=replace(
                original.candidate, public_domain=False,
                body="An original explanation.", source="original-source",
            ),
            source=SourceRecord(
                "original-source", "Synthetic original work",
                "urn:bede:original:verbatim-rejection", NOW,
                "d" * 64, RightsStatus.original,
            ),
        )
        async with Session() as db:
            with pytest.raises(CurriculumWorkflowDenied):
                await stage_lesson(db, token(author), original)
            assert (await db.execute(select(lessons))).all() == []
    finally:
        await engine.dispose()
