"""Opt-in, campus-scoped curriculum staging and independent human review.

This service has NO public router or startup integration. Callers must pass a
token already verified by the API authentication dependency; raw client
claims are not credentials. A reviewer grant is provisioned only by an
independent administrator (no grant-issuing path is exposed here).

The rights gate is mechanical, not legal proof. Approval is an explicitly
authorized HUMAN decision and cannot publish content to the learner tutor.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import insert, select, update

from core.database import PilotCampus, PilotEducatorCampus
from core.encryption import aad_for, decrypt_json, encrypt_json
from services.content_curation import ContentCandidate
from services.curriculum.flag import curriculum_engine_enabled
from services.curriculum.models import (
    ReviewDecision, ReviewRecord, RightsStatus, SourceRecord, Visibility,
    require_approvable,
)
from services.curriculum.persistence import lessons, reviewer_grants, reviews, sources
from services.curriculum.rights_gate import StagingSubmission, assess_staging_batch
from services.educator_access import live_educator
from models.schemas import GradeStage, Subject


class CurriculumWorkflowDenied(ValueError):
    """Fail-closed authorization, provenance, or state-transition denial."""


def _deny() -> None:
    raise CurriculumWorkflowDenied("Curriculum action not permitted")


def _aad(table: str, column: str, campus: str, item: str, version: int | None = None) -> bytes:
    key = f"{campus}:{item}" if version is None else f"{campus}:{item}:{version}"
    return aad_for(table, column, key)


async def _actor(db, token: dict, campus: str, *, reviewer: bool = False) -> str:
    """Verify active passkey educator, live campus membership, and review grant.

    The token must already be signature-verified upstream; this service adds
    current DB and version checks, including a second check before commit.
    """
    if not curriculum_engine_enabled():
        _deny()
    if (not isinstance(token, dict) or token.get("auth_method") != "webauthn_uv"
            or not isinstance(campus, str) or not campus.strip()):
        _deny()
    try:
        teacher = await live_educator(db, token)
        await db.refresh(teacher)
        if not teacher.enabled or teacher.credential_version != token.get("ev"):
            _deny()
        member = (await db.execute(
            select(PilotEducatorCampus)
            .where(PilotEducatorCampus.educator_id == teacher.id,
                   PilotEducatorCampus.campus_id == campus)
            .with_for_update()
            .execution_options(populate_existing=True)
        )).scalar_one_or_none()
        campus_row = (await db.execute(
            select(PilotCampus)
            .where(PilotCampus.id == campus)
            .with_for_update()
            .execution_options(populate_existing=True)
        )).scalar_one_or_none()
        if member is None or not member.enabled or campus_row is None or not campus_row.enabled:
            _deny()
        if reviewer:
            grant = (await db.execute(
                select(reviewer_grants.c.enabled)
                .where(reviewer_grants.c.educator_id == teacher.id,
                       reviewer_grants.c.campus_id == campus)
                .with_for_update()
            )).scalar_one_or_none()
            if grant is not True:
                _deny()
        return teacher.id
    except CurriculumWorkflowDenied:
        raise
    except Exception as exc:
        raise CurriculumWorkflowDenied("Curriculum action not permitted") from exc


def _as_utc(value: datetime) -> datetime:
    """Normalize UTC timestamps across SQLite and PostgreSQL deserialization."""
    return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None
            else value.astimezone(timezone.utc))


def _candidate_snapshot(c: ContentCandidate) -> dict:
    return dict(
        id=c.id, title=c.title, subject=c.subject.value, source=c.source,
        verbatim_text=c.verbatim_text, public_domain=c.public_domain,
        anti_twaddle=c.anti_twaddle, stages=[s.value for s in c.stages],
        body=c.body, skills=list(c.skills),
        exercises_no_tracked_skill=c.exercises_no_tracked_skill,
        extra_fields=c.extra_fields,
    )


def _submission_snapshot(s: StagingSubmission, author: str, visibility: Visibility, generated: bool) -> dict:
    source = s.source
    assert source is not None
    return dict(
        candidate=_candidate_snapshot(s.candidate),
        source=dict(source_id=source.source_id, edition=source.edition,
                    source_url=source.source_url,
                    retrieved_at=source.retrieved_at.isoformat(),
                    content_hash=source.content_hash,
                    rights_status=source.rights_status.value),
        rights_verified_by=s.rights_verified_by,
        rights_evidence_ref=s.rights_evidence_ref,
        author=author, visibility=visibility.value, generated=generated,
    )


def _restore_submission(campus: str, payload: dict) -> StagingSubmission:
    c, s = payload["candidate"], payload["source"]
    return StagingSubmission(
        campus_id=campus,
        candidate=ContentCandidate(
            id=c["id"], title=c["title"], subject=Subject(c["subject"]),
            source=c["source"], verbatim_text=c["verbatim_text"],
            public_domain=c["public_domain"], anti_twaddle=c["anti_twaddle"],
            stages=tuple(GradeStage(x) for x in c["stages"]),
            body=c["body"], skills=tuple(c["skills"]),
            exercises_no_tracked_skill=c["exercises_no_tracked_skill"],
            extra_fields=c["extra_fields"],
        ),
        source=SourceRecord(
            source_id=s["source_id"], edition=s["edition"],
            source_url=s["source_url"],
            retrieved_at=datetime.fromisoformat(s["retrieved_at"]),
            content_hash=s["content_hash"],
            rights_status=RightsStatus(s["rights_status"]),
        ),
        rights_verified_by=payload["rights_verified_by"],
        rights_evidence_ref=payload["rights_evidence_ref"],
    )


async def _latest(db, campus: str, item_id: str):
    return (await db.execute(
        select(lessons).where(
            lessons.c.campus_id == campus, lessons.c.lesson_id == item_id
        ).order_by(lessons.c.version.desc()).limit(1).with_for_update()
    )).mappings().first()


async def stage_lesson(
    db, token: dict, submission: StagingSubmission, *,
    visibility: Visibility = Visibility.campus, generated: bool = False,
) -> int:
    """Add a new immutable staged lesson version, never an approved record.

    No ingestion API is registered. Failure rolls back all pending writes.
    """
    campus = submission.campus_id
    try:
        author = await _actor(db, token, campus)
        if not isinstance(visibility, Visibility) or not isinstance(generated, bool):
            _deny()
        verdict, = assess_staging_batch([submission])
        if not verdict.accepted or submission.source is None:
            _deny()
        source = submission.source
        if source.rights_status == RightsStatus.teacher_private and visibility != Visibility.teacher_private:
            _deny()
        previous = await _latest(db, campus, submission.candidate.id)
        if previous is not None and previous["status"] in ("staged", "in_review"):
            _deny()
        version = previous["version"] + 1 if previous else 1

        source_row = (await db.execute(
            select(sources).where(sources.c.campus_id == campus,
                                  sources.c.source_id == source.source_id)
            .with_for_update()
        )).mappings().first()
        if source_row is None:
            await db.execute(insert(sources).values(
                campus_id=campus, source_id=source.source_id,
                edition=source.edition, source_url=source.source_url,
                retrieved_at=_as_utc(source.retrieved_at), content_hash=source.content_hash,
                rights_status=source.rights_status.value,
                rights_verified_by=submission.rights_verified_by,
            ))
        elif any((
            source_row["edition"] != source.edition,
            _as_utc(source_row["retrieved_at"]) != _as_utc(source.retrieved_at),
            source_row["source_url"] != source.source_url,
            source_row["content_hash"] != source.content_hash,
            source_row["rights_status"] != source.rights_status.value,
            source_row["rights_verified_by"] != submission.rights_verified_by,
        )):
            _deny()  # No silent replacement of source rights/provenance.
        snapshot = _submission_snapshot(submission, author, visibility, generated)
        await db.execute(insert(lessons).values(
            campus_id=campus, lesson_id=submission.candidate.id,
            version=version, owner_educator_id=author,
            visibility=visibility.value, status="staged", generated=generated,
            rights_status=source.rights_status.value, review_id=None,
            body_enc=encrypt_json(snapshot, _aad("curriculum_lessons", "body_enc",
                                                campus, submission.candidate.id, version)),
        ))
        if await _actor(db, token, campus) != author:
            _deny()
        await db.commit()
        return version
    except Exception:
        await db.rollback()
        raise


async def review_staged_lesson(
    db, token: dict, campus: str, lesson_id: str,
    *, decision: ReviewDecision, notes: str = "",
) -> tuple[str, int | None]:
    """Review the latest staged version, appending approval as a NEW version.

    An admin-issued reviewer grant, fresh passkey identity, a different
    author, and a second authorization check are mandatory. Reject and
    request_changes retire the stage and preserve an auditable review.
    """
    try:
        reviewer = await _actor(db, token, campus, reviewer=True)
        if (not isinstance(decision, ReviewDecision) or
                not isinstance(lesson_id, str) or not lesson_id.strip() or
                not isinstance(notes, str) or len(notes) > 4000):
            _deny()
        staged = await _latest(db, campus, lesson_id)
        if staged is None or staged["status"] != "staged" or staged["review_id"] is not None:
            _deny()
        if staged["owner_educator_id"] == reviewer:
            _deny()  # No self-approval, including generated drafts.
        payload = decrypt_json(
            staged["body_enc"],
            _aad("curriculum_lessons", "body_enc", campus, lesson_id, staged["version"]),
        )
        if (payload.get("author") != staged["owner_educator_id"] or
                payload.get("candidate", {}).get("id") != lesson_id or
                payload.get("visibility") != staged["visibility"] or
                payload.get("generated") is not staged["generated"]):
            _deny()
        submission = _restore_submission(campus, payload)
        source = submission.source
        if source is None or not assess_staging_batch([submission])[0].accepted:
            _deny()
        source_row = (await db.execute(
            select(sources).where(sources.c.campus_id == campus,
                                  sources.c.source_id == source.source_id)
            .with_for_update()
        )).mappings().first()
        # Source rights, edition and retrieval metadata must still match the
        # immutable staged snapshot at the moment of human promotion.
        if (source_row is None or source_row["content_hash"] != source.content_hash or
                source_row["edition"] != source.edition or
                _as_utc(source_row["retrieved_at"]) != _as_utc(source.retrieved_at) or
                source_row["rights_status"] != source.rights_status.value or
                source_row["source_url"] != source.source_url or
                source_row["rights_verified_by"] != submission.rights_verified_by):
            _deny()
        if source.rights_status == RightsStatus.teacher_private and staged["visibility"] != "teacher_private":
            _deny()
        new_version = staged["version"] + 1 if decision == ReviewDecision.approve else None
        review_id = str(uuid4())
        review = ReviewRecord(
            review_id=review_id, item_id=lesson_id,
            item_version=new_version or staged["version"],
            reviewed_by=reviewer, reviewed_at=datetime.now(timezone.utc),
            decision=decision,
        )
        if new_version is not None:
            require_approvable(item_id=lesson_id, version=new_version,
                               rights=(source.rights_status,), review=review)
        await db.execute(insert(reviews).values(
            campus_id=campus, review_id=review_id, item_id=lesson_id,
            item_version=review.item_version, reviewed_by=reviewer,
            reviewed_at=review.reviewed_at, decision=decision.value,
            notes_enc=encrypt_json({"notes": notes},
                                   _aad("curriculum_reviews", "notes_enc", campus, review_id)),
        ))
        if new_version is not None:
            await db.execute(insert(lessons).values(
                campus_id=campus, lesson_id=lesson_id, version=new_version,
                owner_educator_id=staged["owner_educator_id"],
                visibility=staged["visibility"], status="approved",
                generated=staged["generated"], rights_status=source.rights_status.value,
                review_id=review_id,
                body_enc=encrypt_json(
                    payload, _aad("curriculum_lessons", "body_enc", campus, lesson_id, new_version)
                ),
            ))
        await db.execute(update(lessons).where(
            lessons.c.campus_id == campus, lessons.c.lesson_id == lesson_id,
            lessons.c.version == staged["version"], lessons.c.status == "staged"
        ).values(status="retired"))
        if await _actor(db, token, campus, reviewer=True) != reviewer:
            _deny()
        await db.commit()
        return review_id, new_version
    except Exception:
        await db.rollback()
        raise
