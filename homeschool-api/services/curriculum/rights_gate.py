"""Offline curriculum PR 2: provenance and rights checks before staging.

This is a pure validation adapter around content_curation.curate_all().
A passing verdict is NOT approval or permission to deliver to a learner.
The human-reviewed, campus-authorized promotion path is a later PR.
No network, persistence, startup registration, or student records.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Sequence
from urllib.parse import urlsplit

from services.content_curation import (
    ContentCandidate, CurationVerdict, Finding, curate_all,
)
from services.curriculum.flag import curriculum_engine_enabled
from services.curriculum.models import RightsStatus, SourceRecord, is_human_reviewer

_SHA256 = re.compile(r"^[a-fA-F0-9]{64}$")


@dataclass(frozen=True)
class StagingSubmission:
    """A campus-scoped candidate and independently recorded source evidence.

    rights_verified_by and rights_evidence_ref are assertions for a future
    authenticated reviewer workflow; they do not themselves prove identity,
    licensing, or public-domain status.
    """

    campus_id: str
    candidate: ContentCandidate
    source: SourceRecord | None
    rights_verified_by: str = ""
    rights_evidence_ref: str = ""


def _provenance_findings(submission: StagingSubmission) -> list[Finding]:
    candidate, source = submission.candidate, submission.source
    findings: list[Finding] = []

    def block(rule: str, message: str) -> None:
        findings.append(Finding(rule, message))

    if not isinstance(submission.campus_id, str) or not submission.campus_id.strip():
        block("scope.campus_required", "A staging submission requires a campus scope.")

    if source is None:
        block("provenance.source_record_required", "Staging requires a SourceRecord.")
        return findings

    if not isinstance(source.rights_status, RightsStatus):
        block("rights.invalid_status", "Rights status must be a recognized RightsStatus.")
        return findings

    if source.rights_status == RightsStatus.unverified:
        block("rights.unverified", "Unverified rights cannot pass the staging gate.")

    if not _SHA256.fullmatch(source.content_hash):
        block("provenance.hash", "Source content_hash must be a SHA-256 hex digest.")

    if not isinstance(source.retrieved_at, datetime) or (
        source.retrieved_at.tzinfo is None
        or source.retrieved_at.utcoffset() is None
    ):
        block("provenance.retrieved_at", "Source retrieval time must include a timezone.")

    # Link the curation citation to this exact source record; an unrelated
    # SourceRecord must never satisfy a missing or different citation.
    if candidate.source not in (source.source_id, source.source_url):
        block("provenance.citation_mismatch", "Candidate must cite this source id or URL.")

    parsed = urlsplit(source.source_url)
    if source.rights_status in (RightsStatus.public_domain_verified, RightsStatus.licensed):
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            block("provenance.source_url", "Externally sourced works require an HTTPS source URL.")

    if candidate.public_domain != (source.rights_status == RightsStatus.public_domain_verified):
        block("rights.public_domain_mismatch", "Candidate public_domain must match verified source rights.")

    if candidate.verbatim_text:
        if source.rights_status != RightsStatus.public_domain_verified:
            block("rights.verbatim", "Verbatim text requires independently verified public-domain rights.")
        if not source.edition.strip():
            block("provenance.edition", "Verbatim text requires a cited source edition.")

    if not isinstance(submission.rights_evidence_ref, str) or not submission.rights_evidence_ref.strip():
        block("rights.evidence_required", "Staging requires a rights evidence reference.")
    if not isinstance(submission.rights_verified_by, str) or not is_human_reviewer(submission.rights_verified_by):
        block("rights.verifier_required", "Staging requires a named human rights verifier.")

    return findings


def assess_staging_batch(submissions: Sequence[StagingSubmission]) -> list[CurationVerdict]:
    """Return blocking findings; never write, promote, or approve curriculum.

    The flag is disabled by default. When enabled, the existing curation
    rules still run, including unknown skill IDs and duplicate IDs.
    """
    if not curriculum_engine_enabled():
        return [
            CurationVerdict(s.candidate.id, [
                Finding("engine.disabled", "Curriculum engine is disabled.")
            ])
            for s in submissions
        ]

    base = curate_all([s.candidate for s in submissions])
    return [
        CurationVerdict(
            candidate_id=verdict.candidate_id,
            findings=verdict.findings + _provenance_findings(submission),
        )
        for submission, verdict in zip(submissions, base)
    ]
