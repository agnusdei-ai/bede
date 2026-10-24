"""Synthetic offline and isolation qualification for the local hybrid index."""
from datetime import datetime, timezone
from pathlib import Path
import socket

import pytest

from services.curriculum import local_hybrid_index as idx
from services.curriculum.local_hybrid_index import (
    IndexedChunk, LocalIndexDenied, SearchScope, search_chunks,
)
from services.curriculum.models import (
    ContentChunk, ItemStatus, ReviewDecision, ReviewRecord, RightsStatus,
    Visibility,
)

NOW = datetime(2026, 10, 24, tzinfo=timezone.utc)


def record(
    chunk_id: str, text: str, *,
    campus: str = "campus-a",
    status: ItemStatus = ItemStatus.approved,
    rights: RightsStatus = RightsStatus.original,
    visibility: Visibility = Visibility.campus,
    owner: str | None = None,
    version: int = 1,
) -> IndexedChunk:
    review = ReviewRecord(
        review_id="review-" + chunk_id, item_id=chunk_id, item_version=version,
        reviewed_by="educator-verified", reviewed_at=NOW,
        decision=ReviewDecision.approve,
    ) if status == ItemStatus.approved else None
    return IndexedChunk(
        chunk=ContentChunk(
            chunk_id=chunk_id, source_id="source-" + chunk_id,
            locator="chapter 2, paragraph 4", text=text, verbatim=False,
            source_edition="1880 original edition", rights_status=rights,
            objective_ids=("objective-1",), subject="history", stage="grammar",
            campus_id=campus, visibility=visibility, status=status,
            version=version, review=review,
        ),
        owner_educator_id=owner,
    )


@pytest.fixture(autouse=True)
def enabled(monkeypatch):
    monkeypatch.setenv("CURRICULUM_ENGINE_ENABLED", "true")


def test_scoped_hybrid_returns_citable_approved_matches():
    candidates = [
        record("c1", "Roman republic and Roman history."),
        record("c2", "Geometric fractions and proportions."),
        record("c3", "Rome and republic, political history."),
    ]
    result = search_chunks("Roman republic", candidates, SearchScope("campus-a"))
    assert result and result[0].chunk_id in {"c1", "c3"}
    assert all(hit.score > 0 and hit.bm25_score >= 0
               and hit.vector_score >= 0 for hit in result)
    assert result[0].source_id.startswith("source-")
    assert result[0].source_edition == "1880 original edition"
    assert result[0].locator == "chapter 2, paragraph 4"
    assert search_chunks("Roman republic", candidates, SearchScope("campus-a")) == result


def test_prefilter_before_any_tokenization_of_excluded_text(monkeypatch):
    allowed = record("safe", "fractions practice with a teacher")
    blocked = [
        record("other-campus", "DO_NOT_TOKENIZE cross-campus fractions", campus="campus-b"),
        record("staged", "DO_NOT_TOKENIZE staged fractions", status=ItemStatus.staged),
        record("unlicensed", "DO_NOT_TOKENIZE licensed fractions", rights=RightsStatus.licensed),
        record("private", "DO_NOT_TOKENIZE private fractions",
               visibility=Visibility.teacher_private, owner="teacher-a"),
    ]
    original = idx._tokens

    def inspect_tokens(value):
        assert "DO_NOT_TOKENIZE" not in value
        return original(value)

    monkeypatch.setattr(idx, "_tokens", inspect_tokens)
    result = search_chunks("fractions", [*blocked, allowed], SearchScope("campus-a"))
    assert [hit.chunk_id for hit in result] == ["safe"]


def test_teacher_private_only_for_matching_owner():
    private = record(
        "private", "private algebra lesson",
        visibility=Visibility.teacher_private, owner="teacher-a",
        rights=RightsStatus.teacher_private,
    )
    assert search_chunks("algebra", [private], SearchScope("campus-a")) == ()
    assert search_chunks("algebra", [private], SearchScope("campus-a", "teacher-b")) == ()
    assert len(search_chunks("algebra", [private], SearchScope("campus-a", "teacher-a"))) == 1


def test_teacher_private_rights_never_visible_to_campus():
    # A private-rights record cannot be promoted to campus visibility.
    misclassified = record(
        "misclassified", "algebra", rights=RightsStatus.teacher_private,
        visibility=Visibility.campus,
    )
    assert search_chunks("algebra", [misclassified], SearchScope("campus-a")) == ()


def test_duplicate_versions_fail_closed():
    entry = record("same", "fractions")
    with pytest.raises(LocalIndexDenied, match="Duplicate"):
        search_chunks("fractions", [entry, entry], SearchScope("campus-a"))


def test_disabled_flag_denies_and_never_reads_content(monkeypatch):
    monkeypatch.delenv("CURRICULUM_ENGINE_ENABLED", raising=False)
    with pytest.raises(LocalIndexDenied, match="disabled"):
        search_chunks("fractions", [record("safe", "fractions")], SearchScope("campus-a"))


def test_empty_query_and_no_matches_return_empty():
    data = [record("c1", "fractions and proportions")]
    assert search_chunks("", data, SearchScope("campus-a")) == ()
    assert search_chunks("no_match_token", data, SearchScope("campus-a")) == ()


def test_invalid_scope_query_size_and_limits_fail_closed():
    data = [record("c1", "fractions")]
    with pytest.raises(LocalIndexDenied):
        SearchScope("")
    with pytest.raises(LocalIndexDenied):
        SearchScope("campus-a", "")
    for query in (None, "a" * 501):
        with pytest.raises(LocalIndexDenied):
            search_chunks(query, data, SearchScope("campus-a"))
    for limit in (0, -1, 21, True):
        with pytest.raises(LocalIndexDenied):
            search_chunks("fractions", data, SearchScope("campus-a"), limit=limit)
    with pytest.raises(LocalIndexDenied):
        search_chunks("fractions", data * 1001, SearchScope("campus-a"))


def test_no_network_or_external_model_download(monkeypatch):
    def deny_socket(*args, **kwargs):
        raise AssertionError("No network is permitted in curriculum search")

    monkeypatch.setattr(socket, "socket", deny_socket)
    result = search_chunks(
        "fractions", [record("c1", "fractions")], SearchScope("campus-a")
    )
    assert len(result) == 1


def test_search_module_not_imported_by_live_app():
    root = Path(__file__).resolve().parents[1]
    main = (root / "main.py").read_text(encoding="utf-8")
    assert "services.curriculum" not in main
