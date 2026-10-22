"""Tests for the curriculum engine models and flag."""

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from services.curriculum import models
from services.curriculum.flag import curriculum_engine_enabled
from services.curriculum.models import (
    ContentChunk,
    CurriculumModelError,
    ItemStatus,
    Lesson,
    LessonVariant,
    ReviewDecision,
    ReviewRecord,
    RightsStatus,
    SourceRecord,
    Visibility,
    validate_skill_ids,
    validate_variant_parent,
)

NOW = datetime(2026, 10, 22, 12, 0, 0)


def review(item_id="lesson-1", version=1, by="Ms. Rivera", decision=ReviewDecision.approve):
    return ReviewRecord("rev-1", item_id, version, by, NOW, decision)


def lesson(**overrides):
    values = dict(
        lesson_id="lesson-1",
        title="Fractions",
        objective_ids=("obj-1",),
        skill_ids=(),
        subject="math",
        stage="grammar",
        campus_id="campus-a",
        visibility=Visibility.campus,
        status=ItemStatus.staged,
        version=1,
        source_ids=("src-1",),
        source_rights=(RightsStatus.original,),
    )
    values.update(overrides)
    return Lesson(**values)


def approved_lesson(**overrides):
    return lesson(status=ItemStatus.approved, review=review(), **overrides)


def chunk(**overrides):
    values = dict(
        chunk_id="chunk-1",
        source_id="src-1",
        locator="ch. 1",
        text="Some text",
        verbatim=False,
        source_edition="1st",
        rights_status=RightsStatus.original,
        objective_ids=("obj-1",),
        subject="history",
        stage="grammar",
        campus_id="campus-a",
        visibility=Visibility.campus,
        status=ItemStatus.staged,
        version=1,
    )
    values.update(overrides)
    return ContentChunk(**values)


def variant(**overrides):
    values = dict(
        variant_id="var-1",
        parent_lesson_id="lesson-1",
        parent_version=1,
        campus_id="campus-a",
        learner_ref="learner_abc123",
        adaptation_basis=("evidence:session-9",),
        created_at=NOW,
        refresh_after=NOW + timedelta(days=7),
    )
    values.update(overrides)
    return LessonVariant(**values)


def test_staged_lesson_is_valid():
    assert lesson().status == ItemStatus.staged


def test_approved_lesson_with_human_review_is_valid():
    assert approved_lesson().status == ItemStatus.approved


def test_unverified_rights_cannot_be_approved():
    with pytest.raises(CurriculumModelError):
        approved_lesson(source_rights=(RightsStatus.unverified,))


def test_approval_requires_review():
    with pytest.raises(CurriculumModelError):
        lesson(status=ItemStatus.approved)


def test_approval_requires_approving_decision():
    with pytest.raises(CurriculumModelError):
        lesson(status=ItemStatus.approved, review=review(decision=ReviewDecision.reject))


def test_approval_requires_matching_item_and_version():
    with pytest.raises(CurriculumModelError):
        lesson(status=ItemStatus.approved, review=review(item_id="other"))
    with pytest.raises(CurriculumModelError):
        lesson(status=ItemStatus.approved, review=review(version=2))


def test_generated_lesson_needs_human_reviewer():
    with pytest.raises(CurriculumModelError):
        lesson(generated=True, status=ItemStatus.approved, review=review(by="agent:bede"))
    assert lesson(generated=True, status=ItemStatus.approved, review=review()).generated


def test_verbatim_requires_public_domain_and_edition():
    with pytest.raises(CurriculumModelError):
        chunk(verbatim=True, rights_status=RightsStatus.licensed)
    with pytest.raises(CurriculumModelError):
        chunk(verbatim=True, rights_status=RightsStatus.public_domain_verified, source_edition="")
    assert chunk(verbatim=True, rights_status=RightsStatus.public_domain_verified).verbatim


def test_source_record_requires_fields():
    with pytest.raises(CurriculumModelError):
        SourceRecord("", "1st", "https://example.org", NOW, "abc", RightsStatus.original)


def test_review_record_rejects_bad_version():
    with pytest.raises(CurriculumModelError):
        ReviewRecord("r", "i", 0, "Ms. Rivera", NOW, ReviewDecision.approve)


def test_variant_valid_and_expires():
    item = variant()
    assert not item.is_stale(NOW)
    assert item.is_stale(NOW + timedelta(days=7))


def test_variant_requires_opaque_learner_ref():
    for bad in ("jane@example.org", "short", "Jane Doe 12345"):
        with pytest.raises(CurriculumModelError):
            variant(learner_ref=bad)


def test_variant_requires_evidence_references():
    with pytest.raises(CurriculumModelError):
        variant(adaptation_basis=("score:42",))
    with pytest.raises(CurriculumModelError):
        variant(adaptation_basis=())


def test_variant_refresh_must_follow_creation():
    with pytest.raises(CurriculumModelError):
        variant(refresh_after=NOW)


def test_variant_parent_checks():
    parent = approved_lesson()
    validate_variant_parent(variant(), parent)
    with pytest.raises(CurriculumModelError):
        validate_variant_parent(variant(), lesson())
    with pytest.raises(CurriculumModelError):
        validate_variant_parent(variant(parent_version=2), parent)
    with pytest.raises(CurriculumModelError):
        validate_variant_parent(variant(campus_id="campus-b"), parent)


def test_unknown_skill_ids_rejected(monkeypatch):
    import services.content_curation as curation

    monkeypatch.setattr(curation, "known_skill_ids", lambda: {"skill-a"})
    validate_skill_ids(("skill-a",))
    with pytest.raises(CurriculumModelError):
        validate_skill_ids(("skill-a", "skill-z"))


def test_flag_defaults_to_disabled(monkeypatch):
    monkeypatch.delenv("CURRICULUM_ENGINE_ENABLED", raising=False)
    assert curriculum_engine_enabled() is False


@pytest.mark.parametrize("value,expected", [("true", True), ("1", True), ("false", False), ("", False), ("maybe", False)])
def test_flag_values(monkeypatch, value, expected):
    monkeypatch.setenv("CURRICULUM_ENGINE_ENABLED", value)
    assert curriculum_engine_enabled() is expected


def test_main_does_not_import_curriculum_package():
    main_source = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
    assert "services.curriculum" not in main_source
    assert models.CurriculumModelError is not None
