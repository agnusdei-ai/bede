"""SQLite-only development adapter to existing authenticated curriculum workflow.

No CLI approval action or public endpoint. Tokens MUST have been signature-verified
by the existing API boundary. Never use caller-provided identity text as authority.
"""
from datetime import datetime

from boundary import Error, contract as c, enabled, store_path
from run import binding


def development_database(db):
    enabled()
    url = db.bind.url
    if url.drivername != "sqlite+aiosqlite":
        raise Error("Factory review adapter refuses nondevelopment databases")
    if url.database != ":memory:":
        store_path(url.database)


async def stage_for_review(db, verified_token, campus, ledger, job, lesson_id, *,
                           rights_verified_by, rights_evidence_ref):
    """Stage exact complete content using existing rights gate; never approve."""
    development_database(db)
    from models.schemas import GradeStage, Subject
    from services.content_curation import ContentCandidate
    from services.curriculum.models import RightsStatus, SourceRecord
    from services.curriculum.rights_gate import StagingSubmission
    from services.curriculum.workflow import stage_lesson

    target, bundle, lesson = binding(ledger, job, lesson_id)
    if len(lesson["source_refs"]) != 1:
        raise Error("Existing staging workflow supports one source; multi-source review blocked")
    source = c.resolve(lesson["source_refs"][0]["source"],
                       {s["id"]: s for s in bundle["sources"]})
    # Raw source bytes are NOT inserted into body. No licensed/verbatim exception.
    candidate = ContentCandidate(
        id=lesson["id"], title=lesson["title"], subject=Subject(lesson["subject"]),
        source=source["id"], public_domain=source["rights"] == "public_domain_verified",
        body=c.canonical(dict(factory_binding=target, content=c.export(bundle))).decode(),
        skills=tuple(lesson["skill_ids"]), stages=(GradeStage(lesson["stage"]),),
        exercises_no_tracked_skill=lesson["exercises_no_tracked_skill"],
    )
    submission = StagingSubmission(
        campus_id=campus, candidate=candidate,
        source=SourceRecord(
            source["id"], source["edition"], source["url"],
            datetime.fromisoformat(source["retrieved_at"].replace("Z", "+00:00")),
            source["asset"]["sha256"], RightsStatus(source["rights"])),
        rights_verified_by=rights_verified_by, rights_evidence_ref=rights_evidence_ref,
    )
    return await stage_lesson(db, verified_token, submission, generated=False)


async def resolve_receipt(db, verified_token, campus, review_id, ledger, job, lesson_id):
    """Resolve an existing trusted receipt, rechecking live grant and exact content.

    Historical reviews stay in existing tables. A stale, revoked, cross-campus,
    self-authored, superseded or rejected receipt never becomes current approval.
    The job and export remain review-only even if this development check passes.
    """
    development_database(db)
    import json
    from sqlalchemy import select
    from core.encryption import decrypt_json
    from services.curriculum.persistence import lessons, reviews, sources
    from services.curriculum.rights_gate import assess_staging_batch
    from services.curriculum.workflow import (
        _actor, _aad, _latest, _restore_submission, _as_utc,
    )

    target, bundle, lesson = binding(ledger, job, lesson_id)
    actor = await _actor(db, verified_token, campus, reviewer=True)
    review = (await db.execute(select(reviews).where(
        reviews.c.campus_id == campus, reviews.c.review_id == review_id,
    ))).mappings().first()
    row = await _latest(db, campus, lesson_id)
    if (not review or not row or review["decision"] != "approve"
            or row["status"] != "approved" or row["review_id"] != review_id
            or review["item_id"] != lesson_id or review["item_version"] != row["version"]
            or review["reviewed_by"] != actor or row["owner_educator_id"] == actor):
        raise Error("No current independent authenticated approval for this exact target")
    payload = decrypt_json(
        row["body_enc"], _aad("curriculum_lessons", "body_enc", campus, lesson_id, row["version"]))
    content = json.loads(payload["candidate"]["body"])
    if (content != dict(factory_binding=target, content=c.export(bundle))
            or payload["author"] != row["owner_educator_id"]):
        raise Error("Approval target differs from current draft")
    submission = _restore_submission(campus, payload)
    if not assess_staging_batch([submission])[0].accepted:
        raise Error("Approval source no longer passes existing rights gate")
    source = submission.source
    current = (await db.execute(select(sources).where(
        sources.c.campus_id == campus, sources.c.source_id == source.source_id,
    ))).mappings().first()
    if (not current or any(current[k] != expected for k, expected in {
            "edition": source.edition, "source_url": source.source_url,
            "content_hash": source.content_hash, "rights_status": source.rights_status.value,
            "rights_verified_by": submission.rights_verified_by}.items())
            or _as_utc(current["retrieved_at"]) != _as_utc(source.retrieved_at)):
        raise Error("Approval source fingerprint changed")
    # Recheck output bytes, source/tool hashes and live authorization at return.
    binding(ledger, job, lesson_id)
    if await _actor(db, verified_token, campus, reviewer=True) != actor:
        raise Error("Review authorization changed")
    return dict(review_id=review_id, campus=campus, item_version=row["version"],
                target=target, kind="authenticated_development_receipt",
                does_not_authorize=["student use", "pilot", "publication", "activation"])
