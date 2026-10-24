"""Synthetic, offline tests for the curriculum rights/provenance staging gate."""
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from models.schemas import Subject
from services.content_curation import ContentCandidate
from services.curriculum.models import RightsStatus, SourceRecord
from services.curriculum.rights_gate import StagingSubmission, assess_staging_batch

NOW = datetime(2026, 10, 24, tzinfo=timezone.utc)


def submission(**changes):
    candidate = ContentCandidate(
        id="history-1", title="History note", subject=Subject.history,
        source="source-1", public_domain=True,
        verbatim_text="A short public-domain excerpt",
        exercises_no_tracked_skill=True,
    )
    source = SourceRecord(
        "source-1", "Verified 1880 edition", "https://example.org/edition",
        NOW, "a" * 64, RightsStatus.public_domain_verified,
    )
    fields = dict(
        campus_id="campus-a", candidate=candidate, source=source,
        rights_verified_by="Reviewer 123", rights_evidence_ref="rights:review-001",
    )
    fields.update(changes)
    return StagingSubmission(**fields)


def rules(result):
    return {finding.rule for finding in result.findings if finding.severity == "block"}


@pytest.fixture(autouse=True)
def enabled(monkeypatch):
    monkeypatch.setenv("CURRICULUM_ENGINE_ENABLED", "true")


def test_valid_source_is_staging_eligible_not_approved():
    verdict, = assess_staging_batch([submission()])
    assert verdict.accepted
    assert not verdict.findings
    assert not hasattr(verdict, "approved")


def test_engine_defaults_to_fail_closed(monkeypatch):
    monkeypatch.delenv("CURRICULUM_ENGINE_ENABLED", raising=False)
    assert "engine.disabled" in rules(assess_staging_batch([submission()])[0])


def test_source_missing_and_wrong_citation_are_blocked():
    assert "provenance.source_record_required" in rules(
        assess_staging_batch([submission(source=None)])[0]
    )
    s = submission()
    assert "provenance.citation_mismatch" in rules(
        assess_staging_batch([replace(s, candidate=replace(s.candidate, source="different"))])[0]
    )


def test_unverified_and_mismatched_rights_are_blocked():
    s = submission()
    assert "rights.unverified" in rules(assess_staging_batch([
        replace(s, source=replace(s.source, rights_status=RightsStatus.unverified))
    ])[0])
    assert "rights.public_domain_mismatch" in rules(assess_staging_batch([
        replace(s, candidate=replace(s.candidate, public_domain=False))
    ])[0])


def test_verbatim_licensed_text_is_blocked():
    s = submission()
    licensed = replace(s.source, rights_status=RightsStatus.licensed)
    assert "rights.verbatim" in rules(assess_staging_batch([
        replace(s, source=licensed, candidate=replace(s.candidate, public_domain=False))
    ])[0])


def test_verification_and_source_integrity_required():
    s = submission()
    bad = replace(s, rights_verified_by="agent:curator", rights_evidence_ref="")
    assert {"rights.verifier_required", "rights.evidence_required"} <= rules(
        assess_staging_batch([bad])[0]
    )
    assert "provenance.hash" in rules(assess_staging_batch([
        replace(s, source=replace(s.source, content_hash="not-a-hash"))
    ])[0])
    assert "provenance.retrieved_at" in rules(assess_staging_batch([
        replace(s, source=replace(s.source, retrieved_at=datetime(2026, 10, 24)))
    ])[0])
    assert "provenance.source_url" in rules(assess_staging_batch([
        replace(s, source=replace(s.source, source_url="http://example.org/edition"))
    ])[0])


def test_unknown_skill_and_duplicate_candidate_ids_are_blocked(monkeypatch):
    import services.content_curation as curation
    monkeypatch.setattr(curation, "known_skill_ids", lambda: {"known-skill"})
    s = submission()
    unknown = replace(s, candidate=replace(
        s.candidate, skills=("unknown-skill",), exercises_no_tracked_skill=False,
    ))
    assert "mastery.unknown_skill" in rules(assess_staging_batch([unknown])[0])
    verdicts = assess_staging_batch([s, replace(s, campus_id="campus-b")])
    assert all("id.duplicate" in rules(verdict) for verdict in verdicts)


def test_missing_campus_and_unrecognized_rights_status_are_blocked():
    s = submission()
    assert "scope.campus_required" in rules(assess_staging_batch([
        replace(s, campus_id="")
    ])[0])
    assert "rights.invalid_status" in rules(assess_staging_batch([
        replace(s, source=replace(s.source, rights_status="invented"))
    ])[0])
